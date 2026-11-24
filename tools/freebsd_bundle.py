"""Collect the relocatable FreeBSD runtime and write the release archive."""

from __future__ import annotations

from importlib.util import find_spec
import json
import os
from pathlib import Path
import shutil
from stat import S_IMODE, S_IWUSR
import subprocess
import sys
import sysconfig
import tempfile

from src.core.version import BUILD_COMMIT_FILENAME, FREEBSD_PACKAGE_ARCHIVE as ARCHIVE, git_commit_record, parse_commit_record
from tools.freebsd_build import LOCAL, PYTHON_SITE, PYTHON_VERSION, PLUGIN_NAMESPACES, ROOT
from tools.macos_build_support import copy, digest, download, output
from tools.mpv import install as mpv_config
from tools.update_third_party_notices import render_notices


PORT_PROGRAMS = ("7zz", "ffmpeg", "ffprobe", "mkvmerge", "mkvinfo", "mkvextract", "mkvpropedit",
                 "x264", "x265", "SvtAv1EncApp", "flac", "dovi_tool", "xclip")
SOURCE_PROGRAMS = ("mpv", "tsMuxeR", "vsedit", "hdr10plus_tool", "fdkaac", "vspipe")
QT_MODULES = ("QtCore", "QtDBus", "QtGui", "QtNetwork", "QtWidgets", "sip")
PYTHON_MODULES = ("PyQt6", "numpy", "PIL", "olefile", "pycountry", "cffi", "_cffi_backend", "pycparser",
                  "soundfile", "_soundfile", "typing_extensions")
EXCLUDED_PYTHON = ("__pycache__", "*.py[co]", ".pkgtemp.*", "tests", "test", "idlelib", "tkinter", "ensurepip")
# These FreeBSD 14 SONAMEs are no longer supplied by the 15 base system.
# Match misc/compat14x from Ports, and copy only files reached by the bundle.
BASE_COMPAT = frozenset("""libasn1.so.11 libcom_err.so.5 libcrypto.so.30 libdevinfo.so.6 libdialog.so.10
    libdpv.so.3 libfigpar.so.0 libgssapi.so.10 libgssapi_krb5.so.10 libgssapi_ntlm.so.10 libgssapi_spnego.so.10
    libhdb.so.11 libheimbase.so.11 libheimntlm.so.11 libhx509.so.11 libkadm5clnt.so.11 libkadm5srv.so.11
    libkafs5.so.11 libkdc.so.11 libkrb5.so.11 libmd.so.6 libprivateheimipcc.so.11 libprivateheimipcs.so.11
    libroken.so.11 libssl.so.30 libutil.so.9 libwind.so.11""".split())
# The base libc++ version can differ between release branches without a SONAME change.
BASE_CXX = frozenset({"libc++.so.1", "libcxxrt.so.1"})
NOTICE_PORTS = {
    "archivers/7-zip": "SEVEN_ZIP",
    "multimedia/ffmpeg": "FFMPEG",
    "audio/flac": "FLAC",
    "audio/fdk-aac": "FDK_AAC",
    "multimedia/x264": "X264",
    "multimedia/x265": "X265",
    "multimedia/svt-av1": "SVT_AV1",
    "multimedia/dovi_tool": "DOVI_TOOL",
    "multimedia/libass": "LIBASS",
    "multimedia/mkvtoolnix": "MKVTOOLNIX",
    f"lang/python{PYTHON_VERSION.replace('.', '')}": "PYTHON",
    "math/py-numpy": "NUMPY",
    "devel/qt6-base": "QT",
    "devel/py-qt6-pyqt": "PYQT",
    "audio/py-SoundFile": "SOUNDFILE",
    "audio/libsndfile": "LIBSNDFILE",
    "graphics/py-pillow": "PILLOW",
    "textproc/py-pycountry": "PYCOUNTRY",
}
PORT_LICENSE_NAMES = {
    "BSD2CLAUSE": "BSD-2-Clause",
    "BSD3CLAUSE": "BSD-3-Clause",
    "FRAUNHOFER_FDK_AAC": "Fraunhofer FDK AAC Software License",
    "GPLv2": "GPL-2.0-only",
    "GPLv2+": "GPL-2.0-or-later",
    "GPLv3": "GPL-3.0-only",
    "GPLv3+": "GPL-3.0-or-later",
    "ISCL": "ISC",
    "LGPL21": "LGPL-2.1-only",
    "LGPL21+": "LGPL-2.1-or-later",
    "LGPL3+": "LGPL-3.0-or-later",
    "PSFL": "PSF License",
    "UNRAR": "unRAR restriction",
}


def elf(path):
    with path.open("rb") as stream:
        return stream.read(4) == b"\x7fELF"


def dependencies(path, environment):
    if not elf(path):
        return ()
    result = subprocess.run(["ldd", "-f", "%o\\t%p\\n", "-f", "%o\\t%p\\n", path], env=environment,
                            capture_output=True, text=True)
    if result.returncode:
        if "not a dynamic" in result.stderr:
            return ()
        raise RuntimeError(f"ldd failed for {path}: {result.stderr}")
    libraries = []
    for line in result.stdout.splitlines():
        name, separator, file = line.strip().partition("\t")
        if not separator or name == "[vdso]":
            continue
        if not file.startswith("/"):
            raise FileNotFoundError(f"{path}: {name} ({file})")
        libraries.append((name, Path(file)))
    return libraries


def copy_python(ctx, runtime, owners):
    python = runtime / "python"
    stdlib = Path(sysconfig.get_path("stdlib"))
    shutil.copytree(stdlib, python / "lib" / stdlib.name,
                    ignore=shutil.ignore_patterns(*EXCLUDED_PYTHON, "site-packages", "config-*"))
    interpreter = Path(sys.executable).resolve()
    library = Path(sysconfig.get_config_var("LIBDIR")) / sysconfig.get_config_var("INSTSONAME")
    copy(interpreter, python / "bin/python3")
    copy(library.resolve(), python / "lib" / library.name)
    (runtime / "lib").mkdir()
    (runtime / "lib" / library.name).symlink_to(Path("../python/lib") / library.name)
    owners.add(interpreter)
    site = python / PYTHON_SITE
    site.mkdir(exist_ok=True)
    for name in PYTHON_MODULES:
        spec = find_spec(name)
        if spec is None:
            raise ModuleNotFoundError(name)
        source = Path(spec.origin) if spec.origin else None
        if spec.submodule_search_locations is None:
            owners.add(source)
            copy(source, site / source.name)
            metadata_root = source.parent
        elif name == "PyQt6":
            qt_package, = map(Path, spec.submodule_search_locations)
            package = site / name
            if source is not None:
                owners.add(source)
                copy(source, package / source.name)
            for module in QT_MODULES:
                extension, = qt_package.glob(module + ".*.so")
                copy(extension, package / extension.name)
                owners.add(extension)
            metadata_root = qt_package.parent
        else:
            owners.add(source)
            shutil.copytree(source.parent, site / name, ignore=shutil.ignore_patterns(*EXCLUDED_PYTHON))
            metadata_root = source.parent.parent
        for metadata in metadata_root.glob("*.dist-info"):
            if metadata.name.lower().replace("_", "-").startswith(name.lower().replace("_", "-") + "-"):
                shutil.copytree(metadata, site / metadata.name)
    soundfile = site / "soundfile.py"
    code = soundfile.read_text()
    search = "_find_library('sndfile')"
    if code.count(search) != 1:
        raise ValueError("Unexpected SoundFile library discovery")
    library_path = os.path.relpath(runtime / "lib/libsndfile.so.1", site)
    soundfile.write_text(code.replace(search, f"_os.path.join(_os.path.dirname(__file__), {library_path!r})"))
    for directory in (LOCAL / PYTHON_SITE).glob("numpy.libs"):
        shutil.copytree(directory, site / directory.name)
    shutil.copytree(ctx.prefix / PYTHON_SITE / "vapoursynth", site / "vapoursynth", symlinks=True)
    for script in (ROOT / "third_party/vapoursynth_scripts").glob("*.py"):
        copy(script, site / script.name)


def copy_native(ctx, runtime, owners):
    from PyQt6.QtCore import QLibraryInfo

    programs = runtime / "libexec"
    for name in PORT_PROGRAMS:
        executable = shutil.which(name, path=f"{LOCAL}/bin:{LOCAL}/sbin")
        if executable is None:
            raise FileNotFoundError(name)
        path = Path(executable).resolve()
        copy(path, programs / name)
        owners.add(path)
    for name in SOURCE_PROGRAMS:
        if name != "vspipe":
            copy(ctx.prefix / "bin" / name, programs / name)
    for name in ("libass.so", "libsndfile.so", "libsndfile.so.1"):
        path = LOCAL / "lib" / name
        owners.add(path.resolve())
        copy(path.resolve(), runtime / "lib" / name)
    qt = LOCAL / "lib/qt6/plugins"
    for directory in ("platforms", "platformthemes", "platforminputcontexts", "wayland-graphics-integration-client",
                      "wayland-decoration-client", "wayland-shell-integration", "imageformats", "tls", "xcbglintegrations",
                      "multimedia"):
        for path in (qt / directory).glob("*.so"):
            if (directory != "platforms" or path.name in ("libqxcb.so", "libqoffscreen.so", "libqminimal.so")
                    or path.name.startswith("libqwayland")):
                copy(path, runtime / "qt" / directory / path.name)
                owners.add(path)
    translations = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath))
    chinese = translations / "qtbase_zh_CN.qm"
    copy(chinese, runtime / "qt/translations" / chinese.name)
    owners.add(chinese)
    for directory, prefix in ((runtime / "python/bin", "../.."), (programs, "..")):
        (directory / "qt.conf").write_text(f"[Paths]\nPrefix={prefix}\nPlugins=qt\nTranslations=qt/translations\n",
                                          encoding="utf-8")
    shutil.copytree(ctx.prefix / "plugins", runtime / "plugins")
    catalog = LOCAL / "share/locale/zh_CN/LC_MESSAGES/mkvtoolnix.mo"
    if catalog.is_file():
        copy(catalog, runtime / "share/locale/zh_CN/LC_MESSAGES" / catalog.name)


def relocate(ctx, runtime, owners):
    lib = runtime / "lib"
    vs = runtime / "python" / PYTHON_SITE / "vapoursynth"
    environment = dict(ctx.env, LD_LIBRARY_PATH=f"{lib}:{vs}:{ctx.prefix}/lib:{LOCAL}/lib:{LOCAL}/lib/qt6")
    binaries = {path for path in runtime.rglob("*") if path.is_file() and not path.is_symlink() and elf(path)}
    compatibility = set()
    for binary in sorted(binaries):
        for name, path in dependencies(binary, environment):
            resolved = path.resolve()
            if resolved.is_relative_to(runtime):
                continue
            base = resolved.is_relative_to("/lib") or resolved.is_relative_to("/usr/lib")
            if (base and name not in BASE_COMPAT and name not in BASE_CXX) or resolved.is_relative_to("/libexec"):
                continue
            if not base and not resolved.is_relative_to(LOCAL):
                raise ValueError(f"Unexpected library for {binary}: {path}")
            target = lib / name
            if target.exists() and digest(target) != digest(resolved):
                raise ValueError(f"Conflicting library {name} for {binary}: {path}")
            if not target.exists():
                copy(resolved, target)
            binaries.add(target)
            if base:
                compatibility.add(name)
            else:
                owners.add(resolved)
    for binary in sorted(binaries):
        needed = subprocess.run(["patchelf", "--print-needed", binary], capture_output=True, text=True)
        if needed.returncode:
            if "dynamic" in needed.stderr:
                continue
            raise RuntimeError(f"Cannot read ELF dependencies for {binary}: {needed.stderr}")
        paths = ("$ORIGIN", *("$ORIGIN/" + os.path.relpath(directory, binary.parent) for directory in (lib, vs)))
        mode = S_IMODE(binary.stat().st_mode)
        binary.chmod(mode | S_IWUSR)
        try:
            ctx.run("patchelf", "--set-rpath", ":".join(paths), binary)
        finally:
            binary.chmod(mode)
    return sorted(compatibility)


def licenses(ctx, runtime, owners, sources, compatibility):
    legal = runtime / "legal"
    notices = {"FREEBSD_VERSION": output("freebsd-version", "-u"), "SITE_PACKAGES": (Path("python") / PYTHON_SITE).as_posix()}
    packages = {output("pkg", "which", "-q", owner) for owner in sorted(owners)}
    additional = []
    query = "%n\t%v\t%L\t%o\t%w"
    for package in sorted(packages - {""}):
        metadata = output("pkg", "query", query, package).splitlines()
        versions = [line.split("\t", 4) for line in metadata]
        name, version, _, origin, website = versions[0]
        license_ids = dict.fromkeys(license_id for row in versions for license_id in row[2].split(", ") if license_id)
        license_types = ", ".join(PORT_LICENSE_NAMES.get(license_id, license_id) for license_id in license_ids)
        recipe = f"https://cgit.freebsd.org/ports/tree/{origin}"
        source = website.strip() or recipe
        folder = LOCAL / "share/licenses" / package
        license_files = recipe
        if folder.is_dir():
            shutil.copytree(folder, legal / "ports" / package)
            license_files = f"`legal/ports/{package}/`"
        if component := NOTICE_PORTS.get(origin):
            notices.update({f"{component}_VERSION": version, f"{component}_SOURCE": source,
                            f"{component}_LICENSE_FILES": license_files})
            if component != "QT":
                notices[f"{component}_LICENSE"] = license_types
        else:
            additional.append(f"| `{name}` | `{version}` | {license_types} | {source} |")
    filters = []
    for name, (tag, url) in sorted(sources.items()):
        if name.startswith("vs-"):
            filters.append(f"| `{name}` | `{tag}` | {url} | `legal/{name}/` |")
        else:
            component = name.upper().replace("-", "_")
            notices.update({f"{component}_VERSION": tag, f"{component}_SOURCE": url})
    if compatibility:
        copy(Path("/COPYRIGHT"), legal / "freebsd-base/COPYRIGHT")
        source = f"https://github.com/freebsd/freebsd-src/tree/releng/{ctx.version}"
        additional.append(f"| FreeBSD base | `{notices['FREEBSD_VERSION']}` | [COPYRIGHT](freebsd-base/COPYRIGHT) | {source} |")
        raw = f"https://raw.githubusercontent.com/freebsd/freebsd-src/releng/{ctx.version}"
        if {"libssl.so.30", "libcrypto.so.30"}.intersection(compatibility):
            copy(download(f"{raw}/crypto/openssl/LICENSE.txt", ctx.downloads), legal / "freebsd-base/OpenSSL-LICENSE.txt")
        if "libkrb5.so.11" in compatibility:
            copy(download(f"{raw}/crypto/heimdal/LICENSE", ctx.downloads), legal / "freebsd-base/Heimdal-LICENSE.txt")
        if "libc++.so.1" in compatibility:
            copy(download(f"{raw}/contrib/llvm-project/libcxx/LICENSE.TXT", ctx.downloads),
                 legal / "freebsd-base/libc++-LICENSE.txt")
        if "libcxxrt.so.1" in compatibility:
            copy(download(f"{raw}/contrib/libcxxrt/LICENSE", ctx.downloads), legal / "freebsd-base/libcxxrt-LICENSE.txt")
    templates = {path: legal / path.name for path in (ROOT / "legal/freebsd").glob("THIRD_PARTY_NOTICES*.md")}
    render_notices(templates, notices | {"ADDITIONAL_COMPONENTS": "\n".join(additional),
                                        "VAPOURSYNTH_COMPONENTS": "\n".join(filters)})
    copy(ROOT / "LICENSE", legal / "LICENSE")
    scripts = ROOT / "third_party/vapoursynth_scripts"
    for license_file in scripts.glob("COPYRIGHT*.md"):
        copy(license_file, legal / "vapoursynth_scripts" / license_file.name)
    shutil.copytree(scripts / "licenses", legal / "vapoursynth_scripts/licenses")


def stage_mpv(ctx, runtime):
    assets = runtime / "mpv"
    shutil.copytree(ctx.prefix / "mpv", assets)
    mpv_config.install_lazy_assets(assets)
    files = mpv_config.playback_files(assets, runtime / "plugins", mpv_config.default_menu(str(runtime / "bin/mpv")))
    files.update({assets / "mpv.conf": ("\n".join(mpv_config.PLAYBACK_INCLUDES) + "\n").encode(),
                  assets / "menu.conf": files[assets / "menu.en.conf"],
                  assets / "bluray-defaults.conf": mpv_config.SAVED_SETTINGS_TEMPLATE,
                  assets / "script-opts/context_menu.conf": mpv_config.update_context_options("").encode()})
    for destination, content in files.items():
        mpv_config.write_if_changed(destination, content)
    shader_licenses = runtime / "legal/mpv_lazy_shaders"
    shutil.copytree(mpv_config.BUNDLED_SHADERS / "licenses", shader_licenses / "licenses")
    for notice in mpv_config.BUNDLED_SHADERS.glob("COPYRIGHT*.md"):
        copy(notice, shader_licenses / notice.name)


def stage_runtime(ctx, runtime, sources, recipe):
    owners = set()
    copy_python(ctx, runtime, owners)
    copy_native(ctx, runtime, owners)
    compatibility = relocate(ctx, runtime, owners)
    shutil.copytree(ctx.prefix / "legal", runtime / "legal")
    licenses(ctx, runtime, owners, sources, compatibility)
    wrappers = runtime / "bin"
    wrappers.mkdir()
    for name in (*PORT_PROGRAMS, *SOURCE_PROGRAMS, "python3"):
        copy(ROOT / "tools/launch_freebsd_tool.sh", wrappers / name)
        (wrappers / name).chmod(0o755)
    stage_mpv(ctx, runtime)
    (runtime / "runtime.json").write_text(json.dumps({"recipe": recipe, "release": ctx.version,
                                                        "base_compat": compatibility,
                                                        "components": ctx.built, "plugins": PLUGIN_NAMESPACES},
                                                       indent=2, sort_keys=True) + "\n")


def stage_application(runtime, record):
    app = runtime / "app"
    app.mkdir()
    for directory in ("src", "resource"):
        shutil.copytree(ROOT / directory, app / directory, ignore=shutil.ignore_patterns(*EXCLUDED_PYTHON))
    copy(ROOT / "config.default.json", app / "config.default.json")
    copy(ROOT / "tools/freebsd_entry.py", app / "entry.py")
    (runtime / BUILD_COMMIT_FILENAME).write_text(record, encoding="utf-8")


def archive(runtime, destination, verify):
    destination.mkdir(parents=True, exist_ok=True)
    archive_path = destination / ARCHIVE
    record_path = destination / (ARCHIVE + ".txt")
    for path in (archive_path, record_path):
        if os.path.lexists(path):
            raise FileExistsError(path)
    record_path_source = os.environ.get("BLURAY_FREEBSD_COMMIT_FILE")
    record = Path(record_path_source).read_text(encoding="utf-8") if record_path_source else git_commit_record(ROOT)
    commit = parse_commit_record(record)
    if (expected := os.environ.get("GITHUB_SHA")) and commit.commit_hash != expected:
        raise ValueError("The FreeBSD build record does not match the checked-out commit")
    with tempfile.TemporaryDirectory(dir=destination, prefix=".freebsd package ") as temporary:
        work = Path(temporary)
        package = work / "BluraySubtitle"
        package.mkdir()
        target = package / "_internal"
        shutil.copytree(runtime, target, symlinks=True)
        stage_application(target, record)
        copy(ROOT / "tools/linux_update.py", target / "tools/linux_update.py")
        launcher = package / "BluraySubtitle"
        copy(ROOT / "tools/launch_freebsd_app.sh", launcher)
        launcher.chmod(0o755)
        verify(package)
        compressed = work / ARCHIVE
        with compressed.open("wb") as stream, subprocess.Popen(
            ["tar", "-cf", "-", "-C", work, package.name], stdout=subprocess.PIPE
        ) as tar:
            subprocess.run(["xz", "-T4", "-6", "-c"], stdin=tar.stdout, stdout=stream, check=True)
            tar.stdout.close()
            if tar.wait():
                raise subprocess.CalledProcessError(tar.returncode, tar.args)
        sidecar = work / record_path.name
        sidecar.write_text(f"sha256={digest(compressed)}\n{record}", encoding="utf-8")
        os.link(compressed, archive_path)
        try:
            os.link(sidecar, record_path)
        except OSError:
            archive_path.unlink()
            raise
    return archive_path
