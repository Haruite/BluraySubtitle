"""Install Leap's relocatable Qt 6.6 SDK and abi3 PyQt bindings into the build cache."""

from concurrent.futures import ThreadPoolExecutor
from fcntl import LOCK_EX, flock
import gzip
import hashlib
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
from tempfile import NamedTemporaryFile, TemporaryDirectory
from urllib.request import urlopen
import xml.etree.ElementTree as ET

from linux_runtime_libs import QT_MODULES, linked_libraries, selected_plugins


REPOSITORY = "https://download.opensuse.org/distribution/leap/15.6/repo/oss/"
# The pinned Leap 15.6 GA index contains checksums for both architectures.
INDEX = "72ade5926fe32d0008e6c2b8d931d47abbf209bd488d4156b3756b23734a47b6c63917f1940ee441fb363adb08daa46632d51cedfe9c4bea87a0f3fd9452e9db"
SDK = {
    "qt6-base-common-devel", "qt6-core-devel", "qt6-gui-devel", "qt6-widgets-devel",
    "qt6-network-devel", "qt6-dbus-devel", "qt6-concurrent-devel",
    "libQt6Core6", "libQt6Gui6", "libQt6Widgets6", "libQt6Network6", "libQt6DBus6",
    "libQt6Concurrent6", "libQt6Svg6", "libQt6WaylandClient6", "libQt6WaylandEglClientHwIntegration6",
    "qt6-wayland", "qt6-imageformats", "qt6-translations", "python311-PyQt6", "libicu-suse65_1",
}


def cached_download(cache: Path, relative: str, algorithm: str, digest: str) -> Path:
    target = cache / Path(relative).name
    if target.is_file():
        with target.open("rb") as stream:
            if hashlib.file_digest(stream, algorithm).hexdigest() == digest:
                return target
    with NamedTemporaryFile(dir=cache, delete=False) as output:
        temporary = Path(output.name)
    try:
        with urlopen(REPOSITORY + relative, timeout=90) as source, temporary.open("wb") as output:
            shutil.copyfileobj(source, output)
        with temporary.open("rb") as stream:
            if hashlib.file_digest(stream, algorithm).hexdigest() != digest:
                raise ValueError(f"Invalid checksum for {relative}")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def repository(cache: Path, architecture: str):
    index = cached_download(cache, f"repodata/{INDEX}-primary.xml.gz", "sha512", INDEX)
    packages, sonames = {}, {}
    with gzip.open(index, "rb") as stream:
        for _, item in ET.iterparse(stream, events=("end",)):
            if not item.tag.endswith("}package"):
                continue
            if item.findtext("{*}arch") in (architecture, "noarch"):
                name = item.findtext("{*}name")
                checksum = item.find("{*}checksum")
                packages[name] = item.find("{*}location").get("href"), checksum.get("type"), checksum.text
                for entry in item.findall("{*}format/{*}provides/{*}entry"):
                    symbol = entry.get("name")
                    if symbol.endswith("()(64bit)"):
                        sonames.setdefault(symbol.removesuffix("()(64bit)"), name)
            item.clear()
    return packages, sonames


def check_sdk(prefix: Path) -> None:
    lib = prefix / "lib64"
    qt = lib / "qt6"
    bindings = next(lib.glob("python*/site-packages/PyQt6"), None)
    if bindings is None or not all((bindings / f"{name}.abi3.so").is_file() for name in QT_MODULES):
        raise ValueError("Incomplete Qt 6.6 Python bindings")
    for binary in ("moc", "rcc", "uic"):
        if not (prefix / "lib/qt6" / binary).is_file():
            raise ValueError(f"Missing Qt 6.6 tool: {binary}")
    for key, expected in (("QT_VERSION", "6.6.3"), ("QT_INSTALL_LIBS", str(lib)),
                          ("QT_HOST_LIBEXECS", str(prefix / "lib/qt6"))):
        actual = subprocess.check_output([qt / "bin/qmake", "-query", key],
                                         env=dict(os.environ, LD_LIBRARY_PATH=str(lib)), text=True).strip()
        if actual != expected:
            raise ValueError(f"Invalid private SDK {key}: {actual} (expected {expected})")


def install(cache: Path) -> Path:
    arch = platform.machine()
    downloads = cache / "downloads" / "qt66" / arch
    downloads.mkdir(parents=True, exist_ok=True)
    recipe = hashlib.sha256(Path(__file__).read_bytes() + Path(__file__).with_name("linux_runtime_libs.py").read_bytes())
    destination = downloads / f"sdk-{recipe.hexdigest()[:12]}"
    with (cache / f"qt66-{arch}.lock").open("a") as lock:
        flock(lock, LOCK_EX)
        if destination.is_dir():
            try:
                check_sdk(destination / "usr")
                return destination / "usr"
            except (OSError, ValueError, subprocess.CalledProcessError) as error:
                print(f"Reassembling cached Qt 6.6 SDK: {error}", file=sys.stderr)
        packages, providers = repository(downloads, arch)
        with TemporaryDirectory(dir=destination.parent) as directory:
            tree = Path(directory) / "sdk"
            tree.mkdir()
            prefix = tree / "usr"
            lib = prefix / "lib64"
            qt = lib / "qt6"
            installed = set()
            required = SDK.copy()

            def fetch(name):
                return cached_download(downloads, *packages[name])

            # Inspect precisely the tools, bindings and plugins that will be used. Ubuntu
            # supplies ordinary ABI-compatible dependencies; Qt libraries must come from Leap.
            while required:
                with ThreadPoolExecutor(max_workers=6) as workers:
                    for rpm in workers.map(fetch, sorted(required)):
                        subprocess.run(["bsdtar", "-xf", rpm, "-C", tree], check=True)
                if "libpxbackend-1_0" in required:
                    # Leap's libproxy searches /usr/lib64/libproxy. Expose its backend on the
                    # private library path used by both SDK tools and dependency collection.
                    backend = Path("libproxy/libpxbackend-1.0.so")
                    (lib / backend.name).symlink_to(backend)
                installed.update(required)
                bindings = next(lib.glob("python*/site-packages/PyQt6"))
                binaries = [qt / "bin/qmake", *(prefix / "lib/qt6" / n for n in ("moc", "uic", "rcc")),
                            *(bindings / f"{n}.abi3.so" for n in QT_MODULES),
                            *selected_plugins(qt / "plugins")]
                required = set()
                for binary in binaries:
                    for soname, path in linked_libraries(binary, (lib,), resolving=True).items():
                        if path is None or (soname.startswith("libQt6") and not path.resolve().is_relative_to(lib)):
                            provider = providers.get(soname)
                            if not provider or provider in installed or provider == "glibc":
                                raise RuntimeError(f"Unresolved Qt 6.6 SDK dependency: {binary.name}: {soname}")
                            required.add(provider)
            for binary in binaries:
                linked_libraries(binary, (lib,))
            # qmake and VSEdit test for the GCC family by name. Use Ubuntu's native
            # GCC drivers while preserving the mkspec's CROSS_COMPILE prefix.
            gcc_spec = qt / "mkspecs/common/g++-base.conf"
            gcc_spec.write_text(gcc_spec.read_text().replace("gcc-13", "gcc").replace("g++-13", "g++"))
            # qmake and pkg-config must resolve their target headers and libraries inside this SDK.
            (qt / "bin/qt.conf").write_text(
                "[Paths]\nPrefix=../../..\nHeaders=include/qt6\nLibraries=lib64\n"
                "Binaries=lib64/qt6/bin\nLibraryExecutables=lib/qt6\nArchData=lib64/qt6\n"
                "Data=share/qt6\nPlugins=lib64/qt6/plugins\nTranslations=share/qt6/translations\n"
                "HostPrefix=../../..\nHostData=lib64/qt6\nHostBinaries=lib64/qt6/bin\n"
                "HostLibraryExecutables=lib/qt6\nHostLibraries=lib64\n"
            )
            for pc in (lib / "pkgconfig").glob("Qt6*.pc"):
                pc.write_text(pc.read_text().replace("prefix=/usr\n", "prefix=${pcfiledir}/../..\n"))
            for prl in lib.glob("libQt6*.prl"):
                # Graphics development libraries come from the Ubuntu build host.
                prl.write_text(re.sub(r"\$\$\[QT_INSTALL_LIBS\]/lib(EGL|GL|GLESv2|GLX|OpenGL)\.so\b", r"-l\1", prl.read_text()))
            check_sdk(prefix)
            if destination.exists():
                destination.rename(Path(directory) / "incomplete")
            tree.rename(destination)
    return destination / "usr"


if __name__ == "__main__":
    try:
        print(install(Path(sys.argv[1]).resolve()))
    except FileNotFoundError as error:
        if error.filename != "bsdtar":
            raise
        sys.exit(127)
