"""Install Windows VapourSynth components from their independent upstreams."""
from __future__ import annotations

import argparse
import configparser
import ctypes
from dataclasses import dataclass, replace
import hashlib
import html
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.core.i18n import translate_text
from tools import build_vsedit_windows as vsedit_build
from tools.vapoursynth_plugin_versions import fallback_version, normalize_version, record_version, version_satisfies
from tools.windows_build_cache import files_under, publish as publish_build_cache, restore as restore_build_cache
from tools.windows_native_tools import (
    PE_ARM64, VSEDIT_ARM64_RECIPE, VSEDIT_PLUGINS, VSEDIT_PROGRAMS, VSEDIT_QT_LIBRARIES, VSEDIT_RECIPE,
    build_record, editor_runtime_matches, fetch_verified, file_hash, fingerprint, has_pe_machine, install_build,
    msvc_environment, pyqt_runtime, record_build, windows_machine,
)
from tools.windows_tool_paths import normalize_vsedit_path

BUILD_PROFILE = "static-runtime-shared-fftw-1"
# The smaller library retains the ABI of the cached FFTW build.
FFTW_CACHE_RECIPE = "8e3206eeecb37b7fe3ef3fc7d5723d0f937a6f8d8f51a04e94e87b79d9c192bd"
MSYS2_REQUIRED_EXIT_CODE = 75


class Msys2Required(Exception):
    """Resume component installation after MSYS2 preparation."""


def vulkan_device_available() -> bool:
    """Check Vulkan from the same process architecture as the filters."""
    class VkApplicationInfo(ctypes.Structure):
        _fields_ = [
            ("s_type", ctypes.c_uint32), ("next", ctypes.c_void_p),
            ("application_name", ctypes.c_char_p), ("application_version", ctypes.c_uint32),
            ("engine_name", ctypes.c_char_p), ("engine_version", ctypes.c_uint32),
            ("api_version", ctypes.c_uint32),
        ]

    class VkInstanceCreateInfo(ctypes.Structure):
        _fields_ = [
            ("s_type", ctypes.c_uint32), ("next", ctypes.c_void_p),
            ("flags", ctypes.c_uint32), ("application_info", ctypes.POINTER(VkApplicationInfo)),
            ("layer_count", ctypes.c_uint32), ("layers", ctypes.c_void_p),
            ("extension_count", ctypes.c_uint32), ("extensions", ctypes.c_void_p),
        ]

    try:
        loader = ctypes.WinDLL("vulkan-1.dll", winmode=0x800)  # LOAD_LIBRARY_SEARCH_SYSTEM32
        create = loader.vkCreateInstance
        destroy = loader.vkDestroyInstance
        enumerate_devices = loader.vkEnumeratePhysicalDevices
    except (OSError, AttributeError):
        return False
    create.argtypes = [ctypes.POINTER(VkInstanceCreateInfo), ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    destroy.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    destroy.restype = None
    enumerate_devices.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p]

    # libplacebo requires Vulkan 1.2. A loader can be present with no usable driver.
    application = VkApplicationInfo(s_type=0, api_version=(1 << 22) | (2 << 12))
    configuration = VkInstanceCreateInfo(s_type=1, application_info=ctypes.pointer(application))
    instance = ctypes.c_void_p()
    if create(ctypes.byref(configuration), None, ctypes.byref(instance)) != 0:
        return False
    try:
        count = ctypes.c_uint32()
        return enumerate_devices(instance, ctypes.byref(count), None) == 0 and count.value > 0
    finally:
        destroy(instance, None)


@dataclass(frozen=True)
class Component:
    key: str
    repository: str
    ref: str
    filename: str
    namespace: str
    recipe: str = "meson"
    asset: str = ""
    fallback_ref: str = ""


# Source revisions follow Linux's established VS Classic compatibility limits.
COMPONENTS = (
    Component("descale", "AmusementClub/descale", "", "descale.dll", "descale", asset=r"amd64[.]zip$"),
    Component("addgrain", "HomeOfVapourSynthEvolution/VapourSynth-AddGrain", "r10", "addgrain.dll", "grain", asset=r"win64[.]7z$"),
    Component("assrender", "AmusementClub/assrender", "0.38.4", "assrender.dll", "assrender", "assrender"),
    Component("bilateral", "HomeOfVapourSynthEvolution/VapourSynth-Bilateral", "r3", "bilateral.dll", "bilateral", "configure"),
    Component("dfttest", "HomeOfVapourSynthEvolution/VapourSynth-DFTTest", "r7", "dfttest.dll", "dfttest", asset=r"[.]7z$"),
    Component("eedi2", "HomeOfVapourSynthEvolution/VapourSynth-EEDI2", "r7.1", "eedi2.dll", "eedi2", asset=r"[.]7z$"),
    Component("eedi3m", "HomeOfVapourSynthEvolution/VapourSynth-EEDI3", "r9", "eedi3m.dll", "eedi3m", asset=r"win64.*[.](?:7z|zip)$"),
    Component("fmtconv", "EleonoreMizo/fmtconv", "r30", "fmtconv.dll", "fmtc", "autotools", r"[.]zip$"),
    # Accept the previous source fallback alongside the API3-compatible release.
    Component("lsmas", "HomeOfAviSynthPlusEvolution/L-SMASH-Works", "1282", "libvslsmashsource.dll", "lsmas", "lsmash",
              fallback_ref="ae51313"),
    Component("sangnom", "HomeOfVapourSynthEvolution/VapourSynth-SangNomMod", "v0.1-fix", "vs_sangnommod.dll", "sangnom", "configure", r"[.]zip$"),
    Component("placebo", "Lypheo/vs-placebo", "2.0.4", "libvs_placebo.dll", "placebo"),
    Component("nlm_ispc", "AmusementClub/vs-nlm-ispc", "v4", "vsnlm_ispc.dll", "nlm_ispc", "cmake", r"windows-x64.*[.]7z$"),
    Component("zsmooth", "adworacz/zsmooth", "0.7", "zsmooth.dll", "zsmooth", "zig", r"zsmooth[.]avx2[.]dll[.]zip$"),
    Component("mvtools", "dubhatervapoursynth/vapoursynth-mvtools", "v26", "mvtools.dll", "mv", asset=r"win64[.]7z$"),
    Component("removegrain", "vapoursynth/vs-removegrain", "R1", "RemoveGrainVS.dll", "rgvs", "removegrain", r"win64.*[.](?:zip|7z)$"),
)
R79_ADDITIONAL_COMPONENTS = (
    Component("eedi3", "AmusementClub/vapoursynth-classic", "R57.A15", "EEDI3.dll", "eedi3", "legacy-core"),
    Component("misc", "AmusementClub/vapoursynth-classic", "R57.A15", "MiscFilters.dll", "misc", "legacy-core"),
    Component("vivtc", "vapoursynth/vivtc", "R2", "VIVTC.dll", "vivtc", "legacy-core"),
)
EDITOR = Component("vsedit", "YomikoR/VapourSynth-Editor", "", "vsedit.exe", "")
PROBE = r"""
import ctypes, json, os, sys
from pathlib import Path
ctypes.windll.kernel32.SetErrorMode(0x8003)
sys.path.insert(0, sys.argv[4])
from vapoursynth_plugin_versions import reported_version
handles = [os.add_dll_directory(str(Path(p).resolve())) for p in json.loads(sys.argv[3]) if Path(p).is_dir()]
import vapoursynth as vs
vs.core.num_threads = 2
vs.core.std.LoadPlugin(path=sys.argv[1], forcens='setup_probe', forceid='bluraysubtitle.setup.probe')
p = vs.core.setup_probe
if sys.argv[2] == 'descale':
    assert hasattr(p, 'Descale'), 'Generic Descale is required by muvsfunc'
    assert 'blur:' in p.Debilinear.signature, 'Descale blur support is required'
    if vs.__version__.release_major == 79:
        clip = vs.core.std.BlankClip(width=64, height=48, format=vs.GRAYS, length=1)
        assert p.Descale(clip, 48, 32, kernel='bilinear', blur=1.0).get_frame(0).width == 48
elif sys.argv[2] == 'removegrain':
    assert hasattr(p, 'Repair'), 'RemoveGrain Repair is required'
elif sys.argv[2] == 'sangnom':
    assert hasattr(p, 'SangNom'), 'SangNom is required by the Python filter scripts'
print(json.dumps({'version': str(p.version), 'name': p.name, 'native_version': reported_version(p, sys.argv[5])}))
"""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def imported_dlls(path: Path) -> list[str]:
    import pefile
    image = pefile.PE(str(path), fast_load=True)
    try:
        image.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"]])
        return [entry.dll.decode("ascii") for entry in getattr(image, "DIRECTORY_ENTRY_IMPORT", ())]
    finally:
        image.close()


class Installer:
    def __init__(self, args):
        self.args = args
        self.arm64 = windows_machine() == PE_ARM64
        self.subsystem = "clangarm64" if self.arm64 else "ucrt64"
        self.package_prefix = "mingw-w64-clang-aarch64-" if self.arm64 else "mingw-w64-ucrt-x86_64-"
        self.msys = args.msys2_root / self.subsystem
        self.cc = "clang" if self.arm64 else "gcc"
        self.cxx = "clang++" if self.arm64 else "g++"
        self.static_runtime = "-static" if self.arm64 else "-static -static-libgcc -static-libstdc++"
        self.runtime = args.runtime_root.resolve()
        default_plugins = "vapoursynth-arm64/plugins" if self.arm64 else "vapoursynth64/plugins"
        self.plugins = (args.plugins_dir or self.runtime / default_plugins).resolve()
        self.editor = normalize_vsedit_path(args.editor_path or self.runtime / "vsedit/vsedit.exe")
        self.work = args.work_root.resolve()
        self.work.mkdir(parents=True, exist_ok=True)
        self.state_path = self.runtime / "vapoursynth-components.json"
        self.state = json.loads(self.state_path.read_text(encoding="utf-8")) if self.state_path.is_file() else {
            "schema": 1, "components": {}, "dependencies": {},
        }
        self.sdk = self.runtime / "sdk"
        build_state = self.runtime / "vapoursynth-build.json"
        self.r79 = not args.windows_on_arm and build_state.is_file() and (
            json.loads(build_state.read_text(encoding="utf-8"))["version"] == "79"
        )
        self.components = COMPONENTS
        if self.r79:
            # The Windows descale release contains a Classic-only API3 bridge.
            self.components = tuple(
                replace(component, ref="r12.A", asset="") if component.key == "descale" else component
                for component in COMPONENTS
            ) + R79_ADDITIONAL_COMPONENTS
        self.use_vulkan = (
            args.build_with_vulkan
            or (not self.arm64 and not args.windows_on_arm and not self.r79)
            or vulkan_device_available()
        )
        self.package_checked = set()
        self.used_packages = set()
        self.source_dependencies = []
        self.source_licenses = []
        self.github_api_token = os.environ.pop("BLURAYSUBTITLE_GITHUB_TOKEN", "")
        self.http = urllib.request.build_opener()
        self.http.addheaders = [("User-Agent", "BluraySubtitle-Windows-Setup")]
        self.json_cache = {}
        self.cache_archive = args.build_cache / "vapoursynth-components.zip" if args.build_cache else None
        self.cache_key = self.component_cache_key() if self.cache_archive else None
        self.editor_cache = args.editor_cache or args.build_cache or (
            Path(os.environ["ProgramData"]) / "BluraySubtitle/build-cache/artifacts"
        )

    def component_cache_key(self):
        import numpy as np

        inputs = [self.args.build_fingerprint, str(self.runtime), str(self.plugins), str(self.editor),
                  bool(np._core._multiarray_umath.__cpu_features__.get("AVX2"))]
        if self.arm64:
            inputs.append("arm64")
        return hashlib.sha256(json.dumps(inputs).encode("utf-8")).hexdigest()

    def component_cache_files(self, state):
        files = {}
        for name, digest in state["dependencies"].items():
            target = self.runtime / name
            if target.parent != self.runtime or target.suffix.lower() != ".dll" or target.name.lower() in (
                "vapoursynth.dll", "vsscript.dll",
            ):
                raise ValueError("Invalid cached VapourSynth dependency path")
            files[name] = (target, digest)
        for component in self.components:
            record = state["components"][component.key]
            license_root = self.runtime / "licenses/components" / component.key
            folder = self.runtime / "vapoursynth64/coreplugins" if component.key == "removegrain" and not self.r79 else self.plugins
            entry = folder / component.filename
            if (self.runtime / record["plugin"]).resolve() != entry.resolve() or record["repository"] != component.repository:
                raise ValueError("Invalid cached VapourSynth component entry")
            if record["plugin"] not in record["files"] or not set(record.get("dependencies", ())) <= state["dependencies"].keys():
                raise ValueError("Incomplete cached VapourSynth component")
            for name, digest in record["files"].items():
                target = (self.runtime / name).resolve()
                if target != entry.resolve() and not target.is_relative_to(license_root.resolve()):
                    raise ValueError("Invalid cached VapourSynth component file path")
                files[name] = (target, digest)
        return {"files/" + hashlib.sha256(name.encode("utf-8")).hexdigest(): value for name, value in files.items()}

    def restore_components(self):
        payload = self.work / "cached-components"
        if not self.cache_archive or not restore_build_cache(self.cache_archive, self.cache_key, payload):
            return False
        try:
            state = json.loads((payload / "components.json").read_text(encoding="utf-8"))
            if state["schema"] != 1 or state.get("cache_fingerprint") != self.cache_key:
                return False
            files = self.component_cache_files(state)
            if any(not (payload / name).is_file() or sha256(payload / name) != digest
                   or (target.suffix.lower() == ".dll" and not has_pe_machine(payload / name))
                   for name, (target, digest) in files.items()):
                return False
        except (KeyError, OSError, TypeError, ValueError):
            return False
        state["components"].pop(EDITOR.key, None)
        # Let normal installation handle existing plugins that differ from the cache.
        for component in self.components:
            record = state["components"][component.key]
            target = self.runtime / record["plugin"]
            if component.key != "removegrain" and target.exists() and sha256(target) != record["files"][record["plugin"]]:
                return False
        for name, (target, _) in files.items():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(payload / name, target)
        self.state = state
        self.verify_plugins(restore_versions=True)
        self.save()
        return True

    def record_path(self, path):
        if path.is_relative_to(self.runtime):
            return path.relative_to(self.runtime).as_posix()
        return path.as_posix()

    def log(self, template, **values):
        print("[BluraySubtitle][SETUP] " + translate_text(template, self.args.language).format(**values), flush=True)

    def open_url(self, url, *, timeout, headers=None):
        request = urllib.request.Request(url, headers=headers or {})
        uri = urllib.parse.urlsplit(url)
        if self.github_api_token and uri.scheme == "https" and uri.netloc == "api.github.com":
            request.add_unredirected_header("Authorization", f"Bearer {self.github_api_token}")
            try:
                return self.http.open(request, timeout=timeout)
            except urllib.error.HTTPError as error:
                if error.code not in (401, 403, 404):
                    raise
                error.close()
                request.remove_header("Authorization")
        return self.http.open(request, timeout=timeout)

    def download(self, url, destination, digest=""):
        expected = digest.removeprefix("sha256:")
        if destination.is_file() and (not expected or sha256(destination) == expected):
            return destination
        destination.parent.mkdir(parents=True, exist_ok=True)
        partial = destination.with_name(destination.name + ".part")
        uri = urllib.parse.urlsplit(url)
        github_asset = (
            uri.scheme == "https" and uri.hostname == "api.github.com"
            and re.fullmatch(r"/repos/[^/]+/[^/]+/releases/assets/[0-9]+", uri.path) is not None
        )
        release_download = github_asset or (
            uri.scheme == "https" and uri.hostname == "github.com"
            and re.match(r"/[^/]+/[^/]+/releases/(?:latest/)?download/", uri.path) is not None
        )
        headers = {"Accept": "application/octet-stream", "X-GitHub-Api-Version": "2022-11-28"} if github_asset else {}
        for attempt in range(3):
            try:
                with self.open_url(url, timeout=120, headers=headers) as response:
                    content_type = response.headers.get_content_type()
                    if release_download and (content_type.endswith("json") or content_type == "text/html"):
                        raise urllib.error.URLError(f"{url} returned {content_type}")
                    with partial.open("wb") as output:
                        shutil.copyfileobj(response, output)
                if expected and sha256(partial) != expected:
                    raise RuntimeError(f"SHA-256 mismatch: {url}")
                partial.replace(destination)
                return destination
            except (urllib.error.URLError, TimeoutError, OSError):
                if attempt == 2:
                    raise
                time.sleep(attempt + 1)
        raise RuntimeError(f"Unable to download {url}")

    def download_release_asset(self, asset, destination):
        url = asset["url"]
        digest = asset.get("digest") or ""
        try:
            return self.download(url, destination, digest)
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            direct_url = asset.get("browser_download_url")
            if not direct_url or direct_url == url:
                raise
            return self.download(direct_url, destination, digest)

    def web_release(self, repository, ref):
        if not ref:
            with self.http.open(f"https://github.com/{repository}/releases/latest", timeout=90) as response:
                location = urllib.parse.urlsplit(response.geturl())
            match = re.fullmatch(r"/([^/]+/[^/]+)/releases/tag/(.+)", location.path)
            if location.scheme != "https" or location.hostname != "github.com" or not match:
                raise RuntimeError(f"Unable to resolve the latest release for {repository}")
            repository, encoded_ref = match.groups()
            ref = urllib.parse.unquote(encoded_ref)

        assets_url = f"https://github.com/{repository}/releases/expanded_assets/{urllib.parse.quote(ref, safe='')}"
        with self.http.open(assets_url, timeout=90) as response:
            page = response.read().decode("utf-8")
        link_pattern = rf'\bhref="(?:https://github\.com)?(/{re.escape(repository)}/releases/download/[^"]+)"'
        assets = []
        for row in re.findall(r"<li\b[^>]*>.*?</li>", page, re.I | re.S):
            link = re.search(link_pattern, row, re.I)
            if not link:
                continue
            url = "https://github.com" + html.unescape(link[1])
            name = urllib.parse.unquote(urllib.parse.urlsplit(url).path.rsplit("/", 1)[-1])
            digest = re.search(r"\bsha256:[0-9a-f]{64}\b", row, re.I)
            assets.append({"name": name, "url": url, "digest": digest[0] if digest else ""})
        return {"tag_name": ref, "assets": assets}

    def release(self, repository, ref="", *, missing_ok=False):
        suffix = "tags/" + urllib.parse.quote(ref, safe="") if ref else "latest"
        url = f"https://api.github.com/repos/{repository}/releases/{suffix}"
        if url not in self.json_cache:
            try:
                with self.open_url(url, timeout=90) as response:
                    release = json.load(response)
            except (OSError, ValueError) as error:
                if missing_ok and isinstance(error, urllib.error.HTTPError) and error.code == 404:
                    release = None
                else:
                    try:
                        release = self.web_release(repository, ref)
                    except urllib.error.HTTPError as page_error:
                        if not missing_ok or page_error.code != 404:
                            raise
                        release = None
            self.json_cache[url] = release
        return self.json_cache[url]

    def unpack(self, archive, destination):
        marker = destination / ".unpacked"
        if not marker.is_file():
            destination.mkdir(parents=True, exist_ok=True)
            subprocess.run([self.args.seven_zip, "x", str(archive), "-o" + str(destination), "-y", "-bso0", "-bsp0"], check=True)
            if archive.name.endswith((".tar.gz", ".tar.xz")):
                for nested in destination.glob("*.tar"):
                    subprocess.run([self.args.seven_zip, "x", str(nested), "-o" + str(destination), "-y", "-bso0", "-bsp0"], check=True)
            marker.touch()
        return destination

    def source(self, component, ref):
        parent = self.work / component.key / ("source-" + ref.replace("/", "_"))
        archive_url = f"https://codeload.github.com/{component.repository}/zip/{urllib.parse.quote(ref, safe='/')}"
        archive = self.download(archive_url, parent / "source.zip")
        directories = [path for path in self.unpack(archive, parent / "unpacked").iterdir() if path.is_dir()]
        if len(directories) != 1:
            raise RuntimeError(f"Unexpected source archive layout: {archive}")
        return directories[0]

    @staticmethod
    def posix(path):
        value = path.resolve().as_posix()
        return "/" + value[0].lower() + value[2:]

    def run_msys(self, commands, directory):
        self.require_msys2()
        script = "\n".join([
            "set -euo pipefail", f"export PATH=/{self.subsystem}/bin:/usr/bin:$PATH",
            f"export CC={self.cc} CXX={self.cxx}",
            *([] if not self.arm64 else ["export AR=llvm-ar RANLIB=llvm-ranlib NM=llvm-nm RC=windres"]),
            "export PKG_CONFIG_PATH=" + shlex.quote(self.posix(self.sdk / "lib/pkgconfig")),
            "export LDFLAGS=" + shlex.quote(self.static_runtime if self.arm64 else "-static-libgcc -static-libstdc++"),
            "cd " + shlex.quote(self.posix(directory)), *commands, "",
        ])
        path = self.work / "run-build.sh"
        path.write_text(script, encoding="utf-8", newline="\n")
        subprocess.run([str(self.args.msys2_root / "usr/bin/bash.exe"), "--noprofile", "--norc", self.posix(path)], check=True)

    def require_msys2(self):
        if self.args.defer_msys2:
            raise Msys2Required

    def ensure_packages(self, *names):
        self.used_packages.update(names)
        packages = [self.package_prefix + name for name in names if name not in self.package_checked]
        if packages:
            self.run_msys(["pacman --noconfirm --needed -S " + " ".join(map(shlex.quote, packages))], self.work)
            self.package_checked.update(names)

    def prepare_sdk(self):
        include = self.sdk / "include/vapoursynth"
        if not all((include / name).is_file() for name in ("VSConstants4.h", "VapourSynth4.h", "VSScript4.h", "VSHelper4.h")):
            if self.r79:
                raise RuntimeError("The VapourSynth R79 SDK is missing; run Windows setup to repair it")
            version = (self.runtime / "vapoursynth-classic-version.txt").read_text(encoding="utf-8-sig").strip()
            major, minor = version.split(".", 1)
            source = self.source(Component("sdk", "AmusementClub/vapoursynth-classic", "", "", ""), f"R{major}.A{minor}")
            include.mkdir(parents=True, exist_ok=True)
            for header in (source / "include").glob("*.h"):
                shutil.copyfile(header, include / header.name)
        release = "79" if self.r79 else "57"
        pc = self.sdk / "lib/pkgconfig/vapoursynth.pc"
        pc.parent.mkdir(parents=True, exist_ok=True)
        pc.write_text(
            f"prefix={self.sdk.as_posix()}\n"
            "libdir=${prefix}/lib64\nincludedir=${prefix}/include/vapoursynth\n"
            "Name: VapourSynth\nDescription: VapourSynth plugin headers\n"
            f"Version: {release}\n"
            "Cflags: -I${includedir}\n",
            encoding="utf-8", newline="\n",
        )

    def prepare_fftw(self):
        # DFTTest's Windows ABI expects the thread-safe planner in the same DLL.
        prefix = self.work / "fftw/prefix"
        if has_pe_machine(prefix / "bin/libfftw3f-3.dll"):
            return prefix
        cache = self.args.build_cache / "fftw.zip" if self.args.build_cache else None
        key = fingerprint(FFTW_CACHE_RECIPE, "arm64") if self.arm64 else FFTW_CACHE_RECIPE
        if cache:
            restored = self.work / "fftw/restored"
            if restore_build_cache(cache, key, restored) and all((restored / name).is_file() for name in (
                "bin/libfftw3f-3.dll", "lib/libfftw3f.dll.a", "include/fftw3.h", "share/licenses/fftw/COPYING",
            )):
                restored.rename(prefix)
                self.log("Restored FFTW from the build cache.")
                return prefix
        self.require_msys2()
        archive = self.download("https://fftw.org/fftw-3.3.11.tar.gz", self.work / "fftw/fftw.tar.gz")
        source = self.unpack(archive, self.work / "fftw/source") / "fftw-3.3.11"
        if self.arm64:
            self.run_msys([
                "unset LDFLAGS",
                "NEON_CFLAGS=-march=armv8-a+simd ./configure --host=aarch64-w64-mingw32 "
                + "--prefix=" + shlex.quote(self.posix(prefix))
                + " --enable-single --enable-neon --enable-threads --with-combined-threads"
                + " --with-our-malloc --disable-fortran --enable-shared --disable-static",
                f"make -j{self.args.jobs}",
                "make install",
            ], source)
        else:
            config = source / "cmake.config.h.in"
            config.write_text(config.read_text(encoding="utf-8").replace(
                "/* #undef WITH_OUR_MALLOC */", "#define WITH_OUR_MALLOC 1"), encoding="utf-8")
            cmake = source / "CMakeLists.txt"
            text = cmake.read_text(encoding="utf-8").replace("set (FFTW_VERSION 3.3.10)", "set (FFTW_VERSION 3.3.11)")
            # Upstream CMake overwrites AVX2 flags when enabling FMA.
            text = text.replace('PROPERTIES COMPILE_FLAGS "${FMA_FLAG}"',
                                'PROPERTIES COMPILE_FLAGS "${AVX2_FLAG} ${FMA_FLAG}"')
            naming = '\nset_target_properties(fftw3f PROPERTIES RUNTIME_OUTPUT_NAME "fftw3f-3")\n'
            if naming not in text:
                text += naming
            cmake.write_text(text, encoding="utf-8")
            # An earlier Autotools cache must not shadow CMake's generated header.
            (source / "config.h").unlink(missing_ok=True)
            self.run_msys([
                "cmake -S . -B cmake-build -G Ninja -DCMAKE_POLICY_VERSION_MINIMUM=3.5 -DCMAKE_BUILD_TYPE=MinSizeRel "
                + "-DCMAKE_INSTALL_PREFIX=" + shlex.quote(self.posix(prefix))
                + " -DENABLE_FLOAT=ON -DENABLE_THREADS=ON -DWITH_COMBINED_THREADS=ON "
                + "-DENABLE_SSE2=ON -DENABLE_AVX=ON -DENABLE_AVX2=ON -DDISABLE_FORTRAN=ON -DBUILD_TESTS=OFF "
                + "'-DCMAKE_C_FLAGS_MINSIZEREL=-Os -DNDEBUG -ffunction-sections -fdata-sections' "
                + "'-DCMAKE_SHARED_LINKER_FLAGS=-Wl,--gc-sections -s'",
                "cmake --build cmake-build --parallel " + str(self.args.jobs),
                "cmake --install cmake-build",
            ], source)
        license_path = prefix / "share/licenses/fftw/COPYING"
        license_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / "COPYING", license_path)
        if cache:
            publish_build_cache(cache, key, files_under(prefix))
        return prefix

    def migrate_plugins(self):
        active = {component.key for component in self.components}
        for key, record in list(self.state["components"].items()):
            if "plugin" not in record:
                continue
            relative = record["plugin"]
            path = (self.runtime / relative).resolve()
            if path.is_relative_to(self.plugins) and path.is_file():
                if (key not in active or not has_pe_machine(path)) and sha256(path) == record["files"].get(relative):
                    archive = self.plugins.with_name(self.plugins.name + "-disabled")
                    destination = archive / record["files"][relative] / path.name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    path.replace(destination)
            if key not in active:
                self.state["components"].pop(key)

    def probe(self, binary, component, target=None):
        if not has_pe_machine(binary):
            raise RuntimeError(f"Unexpected Windows binary architecture: {binary}")
        folders = [binary.parent, self.runtime, self.plugins,
                   self.runtime / "vapoursynth64/coreplugins"]
        environment = dict(os.environ, VAPOURSYNTH_EXTRA_PLUGIN_PATH="") if self.r79 else None
        result = subprocess.run([sys.executable, "-c", PROBE, str(binary), component.key, json.dumps(list(map(str, folders))),
                                 str(Path(__file__).resolve().parent), target or component.ref],
                                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120, env=environment)
        if result.returncode:
            raise RuntimeError(f"{component.key} compatibility probe failed ({result.returncode}): {result.stderr.strip()}")
        return json.loads(result.stdout.strip().splitlines()[-1])

    def dependencies(self, binary, stage, *, installed=False):
        pending, copied, msys_libraries = [binary], {}, []
        while pending:
            current = pending.pop()
            for name in imported_dlls(current):
                key = name.lower()
                if key in copied or key.startswith(("api-ms-", "ext-ms-")):
                    continue
                candidates = [current.parent / name, binary.parent / name]
                if key == "libass-9.dll":
                    candidates.append(self.args.libass)
                if installed:
                    candidates.append(self.runtime / name)
                candidates += [self.work / "fftw/prefix/bin" / name, self.msys / "bin" / name]
                dependency = next((path for path in candidates if path.is_file() and path != binary and has_pe_machine(path)), None)
                if dependency is None:
                    continue
                target = stage / name
                if dependency.resolve() != target.resolve():
                    shutil.copyfile(dependency, target)
                copied[key] = target
                pending.append(target)
                if dependency.parent.resolve() == (self.msys / "bin").resolve():
                    msys_libraries.append(f"/{self.subsystem}/bin/" + dependency.name)
        if msys_libraries:
            result = subprocess.run([str(self.args.msys2_root / "usr/bin/pacman.exe"), "-Qqo", *msys_libraries],
                                    check=True, capture_output=True, text=True, encoding="utf-8")
            self.used_packages.update(name.removeprefix(self.package_prefix) for name in result.stdout.splitlines())
        return list(copied.values())

    def valid(self, record, ref):
        if not record or record.get("target_ref", record["ref"]) != ref:
            return False
        files = dict(record["files"])
        for name in record.get("dependencies", ()):
            if name not in self.state["dependencies"]:
                return False
            files[name] = self.state["dependencies"][name]
        return all((self.runtime / name).is_file() and sha256(self.runtime / name) == digest for name, digest in files.items())

    def licenses(self, component, source, extra=None):
        destination, collected = self.runtime / "licenses/components" / component.key, {}
        for index, root in enumerate([source] + ([extra] if extra else [])):
            for path in root.rglob("*"):
                in_license_directory = any(part.lower() in ("licenses", "licences") for part in path.relative_to(root).parts)
                if not path.is_file() or not (in_license_directory or re.match(r"^(COPYING|COPYRIGHT|LICEN[CS]E|UNLICENSE)([._-].*)?$", path.name, re.I)):
                    continue
                if any(part in ("build", ".git", "node_modules") for part in path.relative_to(root).parts):
                    continue
                target = destination / ("release" if index else "source") / path.relative_to(root)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
                collected[target.relative_to(self.runtime).as_posix()] = sha256(target)
        if not collected:
            destination.mkdir(parents=True, exist_ok=True)
            notices = [f"Upstream: https://github.com/{component.repository}\n",
                       "This source snapshot has no standalone license file. No license is inferred.\n"]
            readme = source / "README.md"
            if readme.is_file():
                target = destination / "README.md"
                shutil.copyfile(readme, target)
                collected[target.relative_to(self.runtime).as_posix()] = sha256(target)
            for path in source.rglob("*"):
                if path.suffix.lower() not in (".h", ".c", ".cpp", ".hpp"):
                    continue
                text = path.read_text(encoding="utf-8-sig", errors="replace")[:16384]
                for block in re.findall(r"/\*.*?\*/", text, re.S):
                    if re.search(r"copyright|permission|license", block, re.I):
                        notices.append(f"\n{path.relative_to(source).as_posix()}\n{block}\n")
            target = destination / "UPSTREAM-NOTICES.txt"
            target.write_text("\n".join(notices), encoding="utf-8")
            collected[target.relative_to(self.runtime).as_posix()] = sha256(target)
        compiler_packages = {"libc++", "libunwind"} if self.arm64 else {"gcc-libs"}
        for name in self.used_packages | compiler_packages | {"mingw-w64-crt"}:
            directory = self.msys / "share/licenses" / name
            if directory.is_dir():
                for path in directory.rglob("*"):
                    if path.is_file():
                        target = destination / "dependencies" / name / path.relative_to(directory)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(path, target)
                        collected[target.relative_to(self.runtime).as_posix()] = sha256(target)
        if self.used_packages:
            packages = [self.package_prefix + name for name in sorted(self.used_packages)]
            result = subprocess.run([str(self.args.msys2_root / "usr/bin/pacman.exe"), "-Ql", *packages],
                                    check=True, capture_output=True, text=True, encoding="utf-8")
            for line in result.stdout.splitlines():
                package_name, _, relative = line.partition(" ")
                if "/share/licenses/" not in relative:
                    continue
                path = self.args.msys2_root / relative.lstrip("/")
                if path.is_file():
                    target = destination / "dependencies" / package_name.removeprefix(self.package_prefix) / path.name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(path, target)
                    collected[target.relative_to(self.runtime).as_posix()] = sha256(target)
        if component.key == "dfttest":
            source_license = self.work / "fftw/prefix/share/licenses/fftw/COPYING"
            if source_license.is_file():
                target = destination / "dependencies/fftw/COPYING"
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source_license, target)
                collected[target.relative_to(self.runtime).as_posix()] = sha256(target)
        for name, path in self.source_licenses:
            target = destination / "dependencies" / name / path.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
            collected[target.relative_to(self.runtime).as_posix()] = sha256(target)
        if component.key == "assrender" and not self.source_licenses:
            recipe = source / ".github/workflows/build.yml"
            version = re.search(r"ass_ver:\s*([0-9.]+)", recipe.read_text(encoding="utf-8")).group(1)
            dependency = Component("assrender-libass", "libass/libass", version, "", "")
            library = self.source(dependency, version)
            for path in (recipe, library / "COPYING"):
                target = destination / "dependencies/libass" / path.name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
                collected[target.relative_to(self.runtime).as_posix()] = sha256(target)
            self.source_dependencies.append({"name": "libass", "version": version,
                                             "source_url": f"https://github.com/libass/libass/tree/{version}"})
        return collected

    def save(self):
        self.runtime.mkdir(parents=True, exist_ok=True)
        staged = self.state_path.with_suffix(".json.part")
        staged.write_text(json.dumps(self.state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        staged.replace(self.state_path)

    def prepare_static_placebo(self):
        self.ensure_packages("libplacebo", "shaderc", "spirv-cross", "vulkan-headers", "glslang", "spirv-tools", "lcms2", "libdovi")
        # Upstream asks for shaderc_combined on Windows. Use the shared import
        # archive under that name so L-SMASH and vs-placebo load one compiler.
        directory = self.work / "placebo/static-pc"
        directory.mkdir(parents=True, exist_ok=True)
        prefix = self.msys
        for name in ("libplacebo", "shaderc_combined", "spirv-cross-c", "vulkan"):
            text = (prefix / "lib/pkgconfig" / (name + ".pc")).read_text(encoding="utf-8")
            text = text.replace(f"prefix=/{self.subsystem}", "prefix=" + prefix.as_posix())
            if name == "libplacebo":
                text = text.replace("shaderc >=", "shaderc_combined >=").replace("spirv-cross-c-shared >=", "spirv-cross-c >=")
                # Pkgconf versions that ignore Cflags.private still need static declarations.
                text = re.sub(r"(?m)^Cflags:.*$", lambda match: match[0] + " -DPL_STATIC", text)
            elif name == "shaderc_combined":
                text = re.sub(r"(?m)^Libs:.*$", "Libs: " + (prefix / "lib/libshaderc_shared.dll.a").as_posix(), text)
            elif name == "spirv-cross-c":
                text += "\nLibs.private: -lspirv-cross-glsl -lspirv-cross-hlsl -lspirv-cross-msl -lspirv-cross-cpp -lspirv-cross-reflect -lspirv-cross-util -lspirv-cross-core\n"
            else:
                # The Vulkan loader must remain dynamic to discover GPU drivers.
                text = text.replace("-lvulkan-1", "-l:libvulkan-1.dll.a")
            (directory / (name + ".pc")).write_text(text, encoding="utf-8", newline="\n")
        return directory

    def dependency_source(self, name, repository, ref):
        source = self.source(Component(name, repository, ref, "", ""), ref)
        self.source_dependencies.append({
            "name": name, "version": ref, "source_url": f"https://github.com/{repository}/tree/{ref}",
        })
        return source

    def build_lsmash(self, source):
        self.ensure_packages("dav1d", "libvpx", "libxml2", "libiconv", "zlib")
        if not self.arm64:
            self.ensure_packages("libmfx")
        if self.use_vulkan:
            self.ensure_packages("shaderc", "glslang", "spirv-tools", "vulkan-headers", "vulkan-loader")
        # Use the same FFmpeg fork and submodule revisions as L-SMASH Works r1282.
        ffmpeg = self.dependency_source("FFmpeg", "HomeOfAviSynthPlusEvolution/FFmpeg", "805074e")
        nvcodec = None if self.arm64 else self.dependency_source(
            "nv-codec-headers", "FFmpeg/nv-codec-headers", "n13.0.19.0")
        for name, repository, ref, destination in (
            ("l-smash", "HomeOfAviSynthPlusEvolution/l-smash", "84740c5", "l-smash"),
            ("obuparse", "HomeOfAviSynthPlusEvolution/obuparse", "ada116e", "obuparse"),
            ("xxHash", "Cyan4973/xxHash", "v0.8.3", "xxHash"),
        ):
            shutil.copytree(self.dependency_source(name, repository, ref), source / destination, dirs_exist_ok=True)
        self.source_licenses.extend(("ffmpeg", ffmpeg / name) for name in ("LICENSE.md", "COPYING.GPLv3"))
        if nvcodec:
            # The NVCodec headers carry their copyright and license in their leading comments.
            nvcodec_license = self.work / "nv-codec-headers/COPYING"
            notices = dict.fromkeys(
                path.read_text(encoding="utf-8").split("*/", 1)[0] + "*/"
                for path in sorted((nvcodec / "include/ffnvcodec").glob("*.h"))
            )
            nvcodec_license.write_text("\n\n".join(notices) + "\n", encoding="utf-8")
            self.source_licenses.append(("nv-codec-headers", nvcodec_license))

        work = self.work / "lsmas"
        ffmpeg_build = work / "ffmpeg-build"
        ffmpeg_prefix = work / "ffmpeg-prefix"
        msys = self.msys
        pc = ffmpeg_build / "pc"
        pc.mkdir(parents=True, exist_ok=True)
        libraries = [("dav1d", "dav1d"), ("vpx", "vpx")]
        if not self.arm64:
            libraries.append(("libmfx", "mfx"))
        for name, library in libraries:
            package = (msys / "lib/pkgconfig" / (name + ".pc")).read_text(encoding="utf-8")
            package = package.replace(f"prefix=/{self.subsystem}", "prefix=" + msys.as_posix())
            (pc / (name + ".pc")).write_text(
                package.replace(f"-l{library}", f"-l:lib{library}.a", 1), encoding="utf-8", newline="\n")
        if self.arm64 and self.use_vulkan:
            # The FFmpeg build links statically. Select Shaderc's import archive by filename.
            package = (msys / "lib/pkgconfig/shaderc.pc").read_text(encoding="utf-8")
            package = package.replace(f"prefix=/{self.subsystem}", "prefix=" + msys.as_posix())
            (pc / "shaderc.pc").write_text(
                package.replace("-lshaderc_shared", "-l:libshaderc_shared.dll.a"),
                encoding="utf-8", newline="\n",
            )
        if nvcodec:
            nvcodec_pc = (nvcodec / "ffnvcodec.pc.in").read_text(encoding="utf-8")
            (pc / "ffnvcodec.pc").write_text(nvcodec_pc.replace("@@PREFIX@@", nvcodec.as_posix()),
                                            encoding="utf-8", newline="\n")
        # MinGW places zero-initialized tables in the file with -fdata-sections.
        ffmpeg_options = [
            "--arch=" + ("aarch64" if self.arm64 else "x86_64"),
            "--target-os=mingw32", "--disable-autodetect", "--enable-w32threads",
            "--enable-static", "--disable-shared", "--disable-programs", "--disable-doc", "--disable-debug",
            "--disable-avdevice", "--disable-avfilter", "--disable-encoders", "--disable-muxers",
            "--enable-gpl", "--enable-version3", "--enable-small", "--enable-network", "--enable-schannel",
            "--enable-zlib", "--enable-libxml2", "--enable-libvpx", "--enable-libdav1d",
            "--enable-dxva2", "--enable-d3d11va", "--enable-d3d12va", "--pkg-config-flags=--static",
            "--extra-cflags=-ffunction-sections -DLIBXML_STATIC", f"--prefix={ffmpeg_prefix.as_posix()}",
        ]
        if self.arm64:
            ffmpeg_options.extend(("--cc=clang", "--cxx=clang++", "--ar=llvm-ar", "--nm=llvm-nm",
                                   "--ranlib=llvm-ranlib", "--strip=llvm-strip",
                                   "--windres=windres",
                                   f"--extra-ldflags=-L{msys.as_posix()}/lib -static"))
        else:
            ffmpeg_options.extend(("--enable-libmfx", "--enable-ffnvcodec", "--enable-nvdec", "--enable-cuvid"))
        if self.use_vulkan:
            ffmpeg_options.extend(("--enable-vulkan", "--enable-libshaderc"))
        self.run_msys([
            "export PKG_CONFIG_PATH=" + shlex.quote(pc.as_posix()),
            shlex.join([self.posix(ffmpeg / "configure"), *ffmpeg_options]),
            f"make -j{self.args.jobs}",
            "make install",
        ], ffmpeg_build)

        # Use the real audio helpers when compiling both plugin entry points.
        wrapper = source / "VapourSynth/lwlibav_source.c"
        text = wrapper.read_text(encoding="utf-8")
        wrapper.write_text(text.replace("#ifndef _MSC_VER\n", "#if !defined(_MSC_VER) && !defined(LSMASH_WITH_AVISYNTH)\n", 1),
                           encoding="utf-8")
        cmake = source / "CMakeLists.txt"
        text = cmake.read_text(encoding="utf-8").replace("if (${sse2})", "if (ENABLE_SSE2)")
        cmake.write_text(text.replace(
            "        target_link_libraries(LSMASHSource PRIVATE ws2_32)\n",
            "        set_target_properties(LSMASHSource PROPERTIES LINKER_LANGUAGE CXX)\n"
            "        target_link_libraries(LSMASHSource PRIVATE ws2_32 secur32 crypt32 ncrypt "
            f'\"{msys.as_posix()}/lib/libiconv.a\" \"{msys.as_posix()}/lib/libz.a\")\n',
        ), encoding="utf-8")
        build = work / "plugin-build"
        cmake_options = [
            "-G", "Ninja", "-DCMAKE_BUILD_TYPE=MinSizeRel", "-DCMAKE_DISABLE_FIND_PACKAGE_Git=ON",
            "-DBUILD_VS_PLUGIN=ON",
            "-DBUILD_AVS_PLUGIN=" + ("OFF" if self.arm64 else "ON"),
            "-DENABLE_SSE2=" + ("OFF" if self.arm64 else "ON"),
            "-DENABLE_MFX=" + ("OFF" if self.arm64 else "ON"),
            "-DENABLE_VULKAN=" + ("ON" if self.use_vulkan else "OFF"),
            "-DCMAKE_C_FLAGS_MINSIZEREL=-Os -DNDEBUG -ffunction-sections -DLIBXML_STATIC"
            + ("" if self.arm64 else " -DLSMASH_WITH_AVISYNTH"),
            "-DCMAKE_CXX_FLAGS_MINSIZEREL=-Os -DNDEBUG -ffunction-sections",
            f"-DCMAKE_MODULE_LINKER_FLAGS={self.static_runtime} -Wl,--gc-sections -s",
            f"-DCMAKE_PREFIX_PATH={ffmpeg_prefix.as_posix()};{msys.as_posix()}",
            f"-DLIBXML2_LIBRARY={msys.as_posix()}/lib/libxml2.a",
            f"-DZLIB_LIBRARY={msys.as_posix()}/lib/libz.a",
            f"-Ddav1d_LIBRARY={msys.as_posix()}/lib/libdav1d.a",
            f"-DVPX_LIBRARY={msys.as_posix()}/lib/libvpx.a",
        ]
        if self.arm64:
            cmake_options.append("-DCMAKE_RC_COMPILER=windres")
        else:
            cmake_options.append(f"-DMFX_LIBRARY={msys.as_posix()}/lib/libmfx.a")
        if self.use_vulkan:
            cmake_options.append(f"-DVulkan_shaderc_combined_LIBRARY={msys.as_posix()}/lib/libshaderc_shared.dll.a")
        self.run_msys([
            shlex.join(["cmake", "-S", ".", "-B", build.as_posix(), *cmake_options]),
            shlex.join(["cmake", "--build", build.as_posix(), "--target", "LSMASHSource", "--parallel", str(self.args.jobs)]),
        ], source)
        return build / "LSMASHSource.dll"

    def build_assrender(self, source):
        version = self.args.libass_version
        libass = self.dependency_source("libass", "libass/libass", version)
        self.source_licenses.append(("libass", libass / "COPYING"))
        build = self.work / "assrender/build"
        headers = build / "include/ass"
        headers.mkdir(parents=True, exist_ok=True)
        for name in ("ass.h", "ass_types.h"):
            shutil.copyfile(libass / "libass" / name, headers / name)
        source = source / "src"
        resources = build / "ASSRender.res.o"
        binary = build / "assrender.dll"
        self.run_msys([
            shlex.join(["windres", "-i", "ASSRender.rc", "-o", resources.as_posix()]),
            shlex.join([self.cc, "-std=c99", "-O3", "-s", "-shared", "-static-libgcc",
                        "-I", headers.parent.as_posix(), "-I", (source / "include").as_posix(),
                        "-o", binary.as_posix(), *[path.name for path in sorted(source.glob("*.c"))],
                        "assrender.def", resources.as_posix(), self.args.libass.as_posix(), "-lgdi32", "-luser32"]),
        ], source)
        return binary

    def build(self, component, source):
        self.require_msys2()
        if component.recipe == "lsmash":
            return self.build_lsmash(source)
        if component.recipe == "assrender":
            return self.build_assrender(source)
        self.prepare_sdk()
        include = self.sdk / "include/vapoursynth"
        build_directory = "build-" + BUILD_PROFILE
        commands = [f"export LDFLAGS='{self.static_runtime} -Wl,--gc-sections -s'",
                    "export CFLAGS='-ffunction-sections -fdata-sections'",
                    "export CXXFLAGS='-ffunction-sections -fdata-sections'"]
        if component.key == "eedi3m":
            if self.arm64:
                header = source / "EEDI3/EEDI3.h"
                text = header.read_text(encoding="utf-8")
                if "#include <cmath>" not in text:
                    header.write_text("#include <cmath>\n" + text, encoding="utf-8")
            meson = source / "meson.build"
            text = meson.read_text(encoding="utf-8")
            start, end = text.index("incdir = include_directories("), text.index("\nlibs = []")
            meson.write_text(text[:start] + f"incdir = include_directories('{include.as_posix()}')\n" + text[end:], encoding="utf-8")
        elif component.key == "mvtools":
            target = source / "vapoursynth/include"
            target.mkdir(parents=True, exist_ok=True)
            for header in include.glob("*.h"):
                shutil.copyfile(header, target / header.name)
            prefix = self.prepare_fftw()
            path = source / "meson.build"
            text = path.read_text(encoding="utf-8")
            # DFTTest already needs this DLL; do not embed a second FFTW copy.
            text = text.replace("dependency('fftw3f')", "declare_dependency(include_directories: include_directories('"
                          + (prefix / "include").as_posix() + "'), link_args: ['"
                          + (prefix / "lib/libfftw3f.dll.a").as_posix() + "'])")
            path.write_text(text, encoding="utf-8")
        elif component.key == "dfttest":
            prefix = self.prepare_fftw()
            path = source / "meson.build"
            text = path.read_text(encoding="utf-8")
            text = text.replace("fftw3f_dep = dependency('fftw3f')",
                                "fftw3f_dep = declare_dependency(include_directories: include_directories('"
                                + (prefix / "include").as_posix() + "'), link_args: ['"
                                + (prefix / "lib/libfftw3f.dll.a").as_posix() + "'])")
            path.write_text(text, encoding="utf-8")
        elif component.key == "descale":
            path = source / "src/vsplugin.cc"
            text = path.read_text(encoding="utf-8")
            path.write_text("\n".join(line.replace("data->", "d.") if "vsapi->createVideoFilter" in line else line
                                      for line in text.split("\n")), encoding="utf-8")
        elif component.key == "placebo":
            pc = self.prepare_static_placebo()
            commands.append("export PKG_CONFIG_PATH=" + shlex.quote(pc.as_posix() + ";" + (self.sdk / "lib/pkgconfig").as_posix()))
            # Populate Meson's package cache through the setup downloader.
            subprojects = source / "subprojects"
            wrap = configparser.ConfigParser()
            wrap.read(subprojects / "libp2p.wrap", encoding="utf-8")
            archive = wrap["wrap-file"]
            url = archive["source_url"].replace("https://github.com/sekrit-twc/libp2p/archive/",
                                                "https://codeload.github.com/sekrit-twc/libp2p/tar.gz/").removesuffix(".tar.gz")
            self.download(url, subprojects / "packagecache" / archive["source_filename"], archive["source_hash"])
            path = source / "meson.build"
            text = path.read_text(encoding="utf-8")
            text = re.sub(r"^static_deps = .*", "static_deps = true", text, flags=re.M)
            text = text.replace("-Wl,-Bdynamic,-lvulkan-1,-Bstatic", "-l:libvulkan-1.dll.a")
            path.write_text(text, encoding="utf-8")
        elif component.key == "sangnom":
            path = source / "src/sangnom.cpp"
            text = path.read_text(encoding="utf-8")
            registration = next(line for line in text.splitlines() if 'registerFunc("SangNomMod",' in line)
            if 'registerFunc("SangNom",' not in text:
                text = text.replace(registration, registration + "\n" + registration.replace('"SangNomMod"', '"SangNom"'))
            if self.arm64:
                dependency = self.dependency_source("sse2neon", "DLTcollab/sse2neon", "v1.8.0")
                self.source_licenses.append(("sse2neon", dependency / "LICENSE"))
                text = text.replace("#include <emmintrin.h>", "#include <sse2neon.h>")
                commands.append("export CPATH=" + shlex.quote(dependency.as_posix()))
            path.write_text(text, encoding="utf-8")
        elif component.key == "nlm_ispc":
            if self.arm64:
                self.ensure_packages("ispc")
                executable = self.msys / "bin/ispc.exe"
                # Use ISPC to emit AArch64 COFF with the NEON target.
                output = source / build_directory
                output.mkdir(exist_ok=True)
                kernels = output / "nlm.obj"
                header = output / "nlm_ispc.h"
                subprocess.run([executable, "--arch=aarch64", "--target-os=windows", "--target=neon-i32x4",
                                "-O2", source / "source/nlm.ispc", "-h", header, "-o", kernels], check=True)
                template = (source / "source/config.h.in").read_text(encoding="utf-8")
                (output / "config.h").write_text(template.replace("@VCS_TAG@", component.ref), encoding="utf-8")
                binary = output / component.filename
                self.run_msys([shlex.join([self.cxx, "-O3", "-std=c++17", "-shared", "-static",
                                          "-I" + include.as_posix(), "-I" + output.as_posix(),
                                          "source/vsnlm.cpp", kernels.as_posix(), "-o", binary.as_posix()])], source)
                return binary
            release = self.release("ispc/ispc", "v1.31.0")
            asset = next(item for item in release["assets"] if re.search(r"windows[.]zip$", item["name"]))
            archive = self.download_release_asset(asset, self.work / "ispc" / asset["name"])
            executable = next(self.unpack(archive, self.work / "ispc/unpacked").rglob("ispc.exe"))
            shutil.copyfile(executable, self.msys / "bin/ispc.exe")
        jobs = str(self.args.jobs)
        if component.recipe == "meson":
            static = "false" if self.arm64 and component.key == "placebo" else "true"
            options = ["-Dprefer_static=" + static, "-Db_lto=" + ("false" if self.arm64 else "true")]
            if not self.arm64:
                options += ["-Db_lto_threads=" + jobs]
            if component.key == "descale":
                headers = include.parent if self.r79 else include
                options += ["-Dlibtype=vapoursynth", f"-Dc_args=-I{headers.as_posix()}", f"-Dcpp_args=-I{headers.as_posix()}"]
            if component.key == "placebo":
                options += ["-Dr73-compat=true"]
            wipe = " --wipe" if (source / build_directory / "meson-private/coredata.dat").is_file() else ""
            self.run_msys(commands + ["meson setup " + build_directory + wipe + " --buildtype=release " + " ".join(map(shlex.quote, options)),
                                     "meson compile -C " + build_directory + " -j " + jobs], source)
        elif component.recipe == "cmake":
            self.run_msys(commands + ["cmake -S . -B " + build_directory + " -G Ninja -DCMAKE_BUILD_TYPE=Release "
                           + "-DCMAKE_PREFIX_PATH=" + shlex.quote(self.sdk.as_posix()),
                           "cmake --build " + build_directory + " --parallel " + jobs], source)
        elif component.recipe == "autotools":
            directory = source / "build/unix" if component.key == "fmtconv" else source
            commands = ["sh ./autogen.sh"] if (directory / "autogen.sh").is_file() else []
            if self.arm64 and component.key == "fmtconv":
                header = source / "src/conc/Interlocked.hpp"
                text = header.read_text(encoding="utf-8").replace("<Windows.h>", "<windows.h>")
                if "defined (__aarch64__)" not in text:
                    start = text.index("int64_t\tInterlocked::cas")
                    text = text[:start] + text[start:].replace(
                        "#elif defined (_WIN32) ||",
                        "#elif defined (_WIN32) && defined (__aarch64__)\n"
                        "\treturn (::InterlockedCompareExchange64 (&dest, excg, comp));\n"
                        "#elif defined (_WIN32) ||", 1)
                header.write_text(text, encoding="utf-8")
                # Libtool's Windows link recipe drops Clang's stack-probe runtime.
                commands += [
                    "CXX=aarch64-w64-mingw32-clang++ ./configure --host=aarch64-w64-mingw32 --enable-static --disable-shared",
                    "make -j" + jobs,
                    f"{self.cxx} -shared -static -o {component.filename} -Wl,--whole-archive .libs/libfmtconv.a -Wl,--no-whole-archive",
                ]
            else:
                commands = ["export LDFLAGS='-static -static-libgcc -static-libstdc++ -Wl,--gc-sections -s'"] + commands
                commands += ["./configure --host=x86_64-w64-mingw32 --disable-static --enable-shared", "make -j" + jobs]
            self.run_msys(commands, directory)
        elif component.recipe == "configure":
            if self.arm64:
                sources = source / ("src" if component.key == "sangnom" else "source")
                self.run_msys(commands + [shlex.join([
                    self.cxx, "-O3", "-std=c++11", "-shared", "-static", "-I" + include.parent.as_posix(),
                    "-Iinclude", "-o", component.filename, *[path.as_posix() for path in sorted(sources.glob("*.cpp"))],
                ]) + " $CXXFLAGS"], source)
            else:
                self.run_msys(commands + ["./configure --gcc --target-os=mingw --target=sse2 --extra-cxxflags="
                               + shlex.quote("-I" + include.parent.as_posix())
                               + " --extra-ldflags='-static -static-libgcc -static-libstdc++ -Wl,--gc-sections -s'", "make -j" + jobs], source)
        elif component.recipe == "legacy-core":
            classic_source = component.repository == "AmusementClub/vapoursynth-classic"
            folder = source / "src/filters" / component.key if classic_source else source / "src"
            sources = sorted(folder.glob("*.cpp")) + sorted(folder.glob("*.c"))
            compiler = self.cxx if any(path.suffix == ".cpp" for path in sources) else self.cc
            self.run_msys(commands + [shlex.join([
                compiler, "-O3", "-shared", *self.static_runtime.split(),
                *([] if self.arm64 else ["-DVS_TARGET_CPU_X86"]),
                "-I" + ("include" if classic_source else include.as_posix()),
                "-I.", "-o", component.filename,
                *[path.as_posix() for path in sources],
            ])], source)
        elif component.recipe == "removegrain":
            objects = [name + ".o" for name in ("clense", "removegrainvs", "repairvs", "shared", "verticalcleaner")]
            cpu_option = "" if self.arm64 else "-DVS_TARGET_CPU_X86 "
            makefile = f"CXXFLAGS = -O3 -std=c++11 {cpu_option}-I" + shlex.quote(include.as_posix()) + "\n"
            makefile += "RemoveGrainVS.dll: " + " ".join(objects) + "\n\t$(CXX) -shared $(LDFLAGS) -o $@ $^\n"
            makefile += "%.o: src/%.cpp Makefile\n\t$(CXX) $(CXXFLAGS) -c -o $@ $<\n"
            (source / "Makefile").write_text(makefile, encoding="utf-8", newline="\n")
            self.run_msys(commands + ["make -j" + jobs], source)
        elif component.recipe == "zig":
            # The 0.7 source uses Zig 0.12's Build API.
            architecture = "aarch64" if self.arm64 else "x86_64"
            url = f"https://ziglang.org/download/0.12.0/zig-windows-{architecture}-0.12.0.zip"
            archive = self.download(url, self.work / "zig/zig.zip")
            executable = next(self.unpack(archive, self.work / "zig/unpacked").rglob("zig.exe"))
            manifest = source / "build.zig.zon"
            text = manifest.read_text(encoding="utf-8")
            dependency = re.search(r'\.url = "https://github.com/([^/]+/[^/]+)/archive/([0-9a-f]+)[.]tar[.]gz",\s*\.hash = "[0-9a-f]+",', text)
            if dependency:
                repository, revision = dependency.groups()
                bindings = self.source(Component("vapoursynth-zig", repository, revision, "", ""), revision)
                shutil.copytree(bindings, source / "dependencies/vapoursynth", dirs_exist_ok=True)
                manifest.write_text(text.replace(dependency.group(), '.path = "dependencies/vapoursynth",'), encoding="utf-8")
                self.source_dependencies.append({"name": "vapoursynth-zig", "version": revision,
                                                 "source_url": f"https://github.com/{repository}/tree/{revision}"})
            if self.arm64:
                # Zig 0.12's MinGW DLL loads with STATUS_INVALID_IMAGE_FORMAT on ARM64.
                # Use Zig to emit COFF and let the native CLANGARM64 toolchain link it.
                project = source / "build.zig"
                text = project.read_text(encoding="utf-8")
                text = text.replace("b.addSharedLibrary(.{", "b.addObject(.{", 1).replace(
                    "b.installArtifact(lib);",
                    'b.getInstallStep().dependOn(&b.addInstallFile(lib.getEmittedBin(), "zsmooth.obj").step);')
                project.write_text(text, encoding="utf-8")
            subprocess.run([executable, "build", "-j" + jobs, "-Doptimize=ReleaseFast",
                            f"-Dtarget={architecture}-windows-gnu", "-Dcpu=baseline"], cwd=source, check=True)
            if self.arm64:
                self.run_msys([f"{self.cc} -shared -static -o {component.filename} zig-out/zsmooth.obj"], source)
        else:
            raise RuntimeError(f"Unsupported source recipe: {component.recipe}")
        names = {component.filename.lower(), "lib" + component.filename.lower()}
        if component.key == "removegrain":
            names |= {"libremovegrain.dll", "removegrain.dll"}
        if component.key == "sangnom":
            names.add("libvs_sangnommod.dll")
        output = source / build_directory if component.recipe in ("meson", "cmake") else source
        candidates = [path for path in output.rglob("*.dll") if path.name.lower() in names and has_pe_machine(path)]
        if not candidates:
            raise RuntimeError(f"No plugin with the expected architecture was built for {component.key}")
        binary = min(candidates, key=lambda path: len(path.parts))
        strip = "llvm-strip.exe" if self.arm64 else "strip.exe"
        subprocess.run([str(self.msys / "bin" / strip), "--strip-unneeded", str(binary)], check=True)
        return binary

    def install_plugin(self, component):
        self.used_packages = set()
        self.source_dependencies = []
        self.source_licenses = []
        previous = self.state["components"].get(component.key)
        release = self.release(component.repository) if not component.ref else None
        target_ref = component.ref or release["tag_name"]
        folder = self.runtime / "vapoursynth64/coreplugins" if component.key == "removegrain" and not self.r79 else self.plugins
        target = folder / component.filename
        relative = self.record_path(target)
        known_file = bool(previous and target.is_file() and previous["files"].get(relative) == sha256(target))
        fallback = bool(previous and previous["method"] == "source" and previous["ref"] == component.fallback_ref)
        expected = "commit:" + component.fallback_ref if fallback else target_ref
        installed, probe = None, None
        if target.is_file():
            try:
                probe = self.probe(target, component, expected)
            except RuntimeError as error:
                self.log("Installed VapourSynth plugin cannot be loaded: {name}: {detail}", name=component.key, detail=str(error))
            else:
                installed = probe["native_version"] or fallback_version(target)
                # Migrate the previous hash-bound component manifest once.
                if installed is None and known_file:
                    installed = expected if fallback else normalize_version(previous["ref"])
                if installed is not None:
                    record_version(target, installed, probe["native_version"])
        build_profile = BUILD_PROFILE + ("-arm64" if self.arm64 else "")
        if component.key == "lsmas" and not self.use_vulkan:
            build_profile += "-without-vulkan"
        if self.arm64 and component.key == "placebo":
            build_profile += "-static-placebo"
        same_target = known_file and previous.get("target_ref", previous["ref"]) == target_ref
        rebuild = bool(same_target and previous["method"] == "source" and previous.get("build_profile") != build_profile)
        if installed is not None and version_satisfies(installed, expected) and not rebuild:
            if not known_file:
                # Adopt a readable current/newer DLL without replacing it.
                stage = self.work / component.key / "adopted"
                stage.mkdir(parents=True, exist_ok=True)
                dependencies = self.dependencies(target, stage, installed=True)
                dependency_names = []
                for dependency in dependencies:
                    installed_dependency = self.runtime / dependency.name
                    shutil.copyfile(dependency, installed_dependency)
                    name = installed_dependency.relative_to(self.runtime).as_posix()
                    self.state["dependencies"][name] = sha256(installed_dependency)
                    dependency_names.append(name)
                source = self.source(component, target_ref)
                files = {relative: sha256(target), **self.licenses(component, source)}
                previous = {
                    "name": component.key, "repository": component.repository, "target_ref": target_ref,
                    "ref": installed, "method": "existing", "source_url": f"https://github.com/{component.repository}",
                    "license_source_ref": target_ref, "artifact_url": "", "plugin": relative,
                    "files": files, "dependencies": dependency_names, "source_dependencies": self.source_dependencies,
                }
                self.state["components"][component.key] = previous
            previous.update(target_ref=target_ref, installed_version=installed, registered_version=probe["version"])
            self.save()
            self.log("VapourSynth plugin meets the required version: {name} {installed} >= {target}",
                     name=component.key, installed=installed, target=expected)
            return
        if rebuild:
            self.log("Rebuilding VapourSynth plugin with updated link options: {name}", name=component.key)
        else:
            self.log("VapourSynth plugin needs installation or update: {name} {installed} -> {target}",
                     name=component.key, installed=installed or "?", target=expected)
        if release is None and component.asset and not self.arm64:
            release = self.release(component.repository, component.ref, missing_ok=True)
        self.log("Installing VapourSynth component: {name} {version}", name=component.key, version=target_ref)
        if component.key == "dfttest":
            self.prepare_fftw()
        package, artifact, binary = None, None, None
        if release and not self.arm64:
            assets = [item for item in release["assets"] if component.asset and re.search(component.asset, item["name"], re.I)]
            if component.key == "zsmooth":
                import numpy as np
                if not np._core._multiarray_umath.__cpu_features__.get("AVX2"):
                    assets = []
            if assets:
                artifact = assets[0]
                archive = self.download_release_asset(artifact, self.work / component.key / artifact["name"])
                package = self.unpack(archive, self.work / component.key / ("release-" + archive.stem))
                names = {component.filename.lower()} | ({"lsmashsource.dll"} if component.key == "lsmas" else set())
                if component.key == "zsmooth":
                    names.add("zsmooth.avx2.dll")
                candidates = [path for path in package.rglob("*.dll") if path.name.lower() in names and has_pe_machine(path)]
                if component.key == "sangnom":
                    candidates.sort(key=lambda path: ("clang" not in path.parts, "x64" not in path.parts))
                for candidate in candidates:
                    candidate_stage = self.work / component.key / "candidate"
                    candidate_stage.mkdir(parents=True, exist_ok=True)
                    candidate_binary = candidate_stage / component.filename
                    shutil.copyfile(candidate, candidate_binary)
                    self.dependencies(candidate, candidate_stage)
                    try:
                        self.probe(candidate_binary, component, target_ref)
                    except RuntimeError as error:
                        self.log("Release binary is incompatible; trying source: {name}: {detail}", name=component.key, detail=str(error))
                    else:
                        binary = candidate_binary
                        break
        method = "release" if binary else "source"
        source = self.source(component, target_ref)
        if binary is None:
            self.log("Building VapourSynth component from source: {name} {version}", name=component.key, version=target_ref)
            binary = self.build(component, source)
        stage = self.work / component.key / "staged"
        stage.mkdir(parents=True, exist_ok=True)
        staged_binary = stage / component.filename
        shutil.copyfile(binary, staged_binary)
        dependencies = self.dependencies(binary, stage)
        probe = self.probe(staged_binary, component, target_ref)
        folder.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(staged_binary, target)
        record_version(target, target_ref, probe["native_version"])
        dependency_names = []
        for dependency in dependencies:
            installed = self.runtime / dependency.name
            shutil.copyfile(dependency, installed)
            relative = installed.relative_to(self.runtime).as_posix()
            self.state["dependencies"][relative] = sha256(installed)
            dependency_names.append(relative)
        files = {self.record_path(target): sha256(target)}
        files.update(self.licenses(component, source, package))
        self.state["components"][component.key] = {
            "name": component.key, "repository": component.repository, "target_ref": target_ref, "ref": target_ref, "method": method,
            "source_url": f"https://github.com/{component.repository}/tree/{target_ref}",
            "artifact_url": artifact["url"] if method == "release" else "",
            "plugin": self.record_path(target), "registered_version": probe["version"],
            "installed_version": probe["native_version"] or normalize_version(target_ref),
            "build_profile": build_profile if method == "source" else "",
            "files": files, "dependencies": dependency_names,
            "source_dependencies": self.source_dependencies + ([{"name": "FFTW", "version": "3.3.11", "source_url": "https://fftw.org/fftw-3.3.11.tar.gz"}]
                                   if component.key in ("dfttest", "mvtools") else []),
        }
        self.save()

    def install_editor(self):
        ref = self.release(EDITOR.repository)["tag_name"]
        recipe = VSEDIT_ARM64_RECIPE if self.arm64 else VSEDIT_RECIPE
        qt_version, qt = pyqt_runtime()
        qt_plugins = qt / "plugins"
        include = self.sdk / "include/vapoursynth"
        if not all((include / name).is_file() for name in ("VapourSynth4.h", "VSScript4.h", "VSHelper4.h")):
            self.prepare_sdk()
        key = fingerprint(
            recipe, ref, qt_version,
            {header.name: file_hash(header) for header in include.glob("*.h")},
            {name: file_hash(qt / "bin" / name) for name in VSEDIT_QT_LIBRARIES},
            {name: file_hash(qt_plugins / name) for name in VSEDIT_PLUGINS},
        )
        entrypoints = {name: self.editor.name if name == "vsedit.exe" else name for name in VSEDIT_PROGRAMS}
        record = build_record(self.editor.parent, EDITOR.key, installed=True)
        if record and record["fingerprint"] == key and record["entrypoints"] == entrypoints and editor_runtime_matches(record, qt_version, qt):
            try:
                vsedit_build.verify_editor(self.editor.parent, self.editor.name, ref)
            except (OSError, RuntimeError, subprocess.SubprocessError):
                pass
            else:
                self.update_editor_record(record)
                self.log("VapourSynth component is current: {name} {version}", name="VSEdit", version=ref)
                return

        archive = self.editor_cache / ("vsedit-arm64.zip" if self.arm64 else "vsedit.zip")
        with tempfile.TemporaryDirectory(prefix="editor-", dir=self.work) as temporary:
            work = Path(temporary)
            payload = work / "cached"
            record = build_record(payload, EDITOR.key) if restore_build_cache(archive, key, payload) else None
            if record and record["fingerprint"] == key and editor_runtime_matches(record, qt_version, qt):
                try:
                    vsedit_build.verify_editor(payload, record["entrypoints"]["vsedit.exe"], ref)
                except (OSError, RuntimeError, subprocess.SubprocessError):
                    record = None
            else:
                record = None
            if record:
                self.log("Restored VSEdit from the build cache.")
            else:
                self.log("Installing VapourSynth component: {name} {version}", name="VSEdit", version=ref)
                source = work / "src"
                # Keep generated paths short within the setup temporary directory.
                shutil.copytree(self.source(EDITOR, ref), source)
                payload = work / "payload"
                environment = msvc_environment(
                    arm64_host=self.args.windows_on_arm, arm64_target=self.arm64,
                    installation=self.args.visual_studio_installation,
                )
                architecture = "arm64" if self.arm64 else "x64"
                downloads = self.editor_cache.parent / "downloads" / f"qt-msvc-{qt_version}-{architecture}"
                sdk = work / "qt"
                vsedit_build.prepare_qt_sdk(qt_version, downloads, sdk, self.args.seven_zip, arm64=self.arm64)
                jom_archive = fetch_verified(vsedit_build.JOM_URL, downloads.parent / "jom_1_1_7.zip", vsedit_build.JOM_SHA256)
                vsedit_build.unpack(jom_archive, work / "jom", self.args.seven_zip)
                programs = vsedit_build.build_programs(
                    source, sdk, work / "jom/jom.exe", include, environment, self.args.jobs, qt_version,
                    arm64=self.arm64,
                )
                vsedit_build.stage_editor(source, programs, payload, qt, environment, arm64=self.arm64)
                for name in ("LGPL-3.0-only.txt", "GPL-3.0-only.txt"):
                    url = f"https://raw.githubusercontent.com/qt/qtbase/v{qt_version}/LICENSES/{name}"
                    license_file = self.download(url, downloads / "licenses" / name)
                    shutil.copyfile(license_file, payload / "licenses/Qt" / name)
                record_build(payload, EDITOR.key, recipe, ref, key, VSEDIT_PROGRAMS, qt_version=qt_version)
                record = build_record(payload, EDITOR.key)
                if not record:
                    raise RuntimeError("Invalid VSEdit build record")
                vsedit_build.verify_editor(payload, "vsedit.exe", ref)
                publish_build_cache(archive, key, files_under(payload))
            install_build(payload, self.editor.parent, EDITOR.key, record, entrypoints)
        installed = build_record(self.editor.parent, EDITOR.key, installed=True)
        if not installed:
            raise RuntimeError("VSEdit installation failed verification")
        self.update_editor_record(installed)

    def update_editor_record(self, record):
        destination = self.editor.parent
        files = {self.record_path(destination / name): digest for name, digest in record["files"].items()}
        previous = self.state["components"].get(EDITOR.key)
        if previous and (self.runtime / previous["entrypoint"]).resolve() == self.editor:
            old_licenses = (self.runtime / "licenses/components/vsedit").resolve()
            retained = {name.casefold() for name in files}
            for name, digest in previous["files"].items():
                target = (self.runtime / name).resolve()
                if (name.casefold() not in retained and target.name != "vsedit.config"
                        and (target.is_relative_to(destination) or target.is_relative_to(old_licenses))
                        and target.is_file() and file_hash(target) == digest):
                    target.unlink()
        self.configure_editor()
        ref, version = record["version"], record["qt_version"]
        series = ".".join(version.split(".")[:2])
        self.state["components"][EDITOR.key] = {
            "name": "VapourSynth Editor", "repository": EDITOR.repository, "ref": ref, "method": "source",
            "recipe": record["recipe"], "qt_version": version,
            "source_url": f"https://github.com/{EDITOR.repository}/tree/{ref}",
            "qt_source_url": f"https://download.qt.io/archive/qt/{series}/{version}/single/qt-everywhere-src-{version}.tar.xz",
            "entrypoint": self.record_path(self.editor), "files": files, "dependencies": [],
        }
        self.save()

    def configure_editor(self):
        config = self.editor.parent / "vsedit.config"
        if not config.exists() and (self.runtime / "vsedit.config").is_file():
            shutil.copyfile(self.runtime / "vsedit.config", config)
        settings = configparser.ConfigParser(interpolation=None, strict=False)
        settings.optionxform = str
        if config.exists():
            settings.read(config, encoding="utf-8-sig")
        if not settings.has_section("common"):
            settings.add_section("common")
        prefer_configured_runtime = self.arm64 or self.args.windows_on_arm
        settings["common"]["prefer_vs_libs_from_list"] = "true" if prefer_configured_runtime else "false"
        settings["common"]["vapoursynth_library_paths"] = self.runtime.as_posix()
        plugin_paths = [self.plugins.as_posix()]
        if not self.r79:
            plugin_paths.insert(0, (self.runtime / "vapoursynth64/coreplugins").as_posix())
        settings["common"]["vapoursynth_plugins_paths"] = ", ".join(plugin_paths)
        with config.open("w", encoding="utf-8", newline="\r\n") as output:
            settings.write(output, space_around_delimiters=False)

    def verify_plugins(self, *, restore_versions=False):
        for component in self.components:
            if component.key in self.state.get("skipped", {}):
                continue
            record = self.state["components"][component.key]
            target = self.runtime / record["plugin"]
            ref = ("commit:" + record["ref"] if record["method"] == "source" and record["ref"] == component.fallback_ref
                   else record.get("target_ref", record["ref"]))
            probe = self.probe(target, component, ref)
            if restore_versions:
                release = ref if ref.startswith("commit:") else record["ref"]
                record_version(target, release, probe["native_version"])

    def cached_release_is_current(self, component):
        record = self.state["components"].get(component.key)
        if record is None:
            return False
        target = component.ref or self.release(component.repository)["tag_name"]
        return record.get("target_ref", record["ref"]) == target

    def install(self):
        ctypes.windll.kernel32.SetErrorMode(0x8003)
        self.migrate_plugins()
        cacheable = self.use_vulkan and self.cache_archive and (
            not self.state_path.is_file() or self.state.get("cache_fingerprint") == self.cache_key
        )
        restored = False
        if self.use_vulkan and self.cache_archive and self.cache_archive.is_file() and not self.state_path.is_file():
            try:
                restored = self.restore_components()
            except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
                pass
        components = self.components
        if restored:
            self.log("Restored VapourSynth components from the build cache.")
            components = tuple(component for component in self.components if not self.cached_release_is_current(component))
        if cacheable:
            self.state["cache_fingerprint"] = self.cache_key
        elif self.state.get("cache_fingerprint") != self.cache_key:
            self.state.pop("cache_fingerprint", None)
        skipped = {}
        if not self.use_vulkan:
            architecture = "ARM64" if self.arm64 else "x64"
            skipped["placebo"] = f"vs-placebo requires a Vulkan device usable by {architecture} applications"
            self.log("Skipping {name} because no {architecture} Vulkan device is available.",
                     name="vs-placebo", architecture=architecture)
            self.log("L-SMASH Works will use CPU decoding when no {architecture} Vulkan device is available.",
                     architecture=architecture)
        if skipped:
            self.state["skipped"] = skipped
            for name in skipped:
                previous = self.state["components"].pop(name, None)
                if previous:
                    plugin = self.runtime / previous["plugin"]
                    digest = previous["files"].get(previous["plugin"])
                    if (plugin.parent.resolve() == self.plugins and digest and plugin.is_file()
                            and sha256(plugin) == digest):
                        # Keep the managed file outside the plugin scan directory.
                        disabled = self.runtime / "disabled-plugins" / plugin.name
                        disabled.parent.mkdir(exist_ok=True)
                        plugin.replace(disabled)
        else:
            self.state.pop("skipped", None)
        for component in components:
            if component.key in skipped:
                continue
            self.install_plugin(component)
        required = {name for record in self.state["components"].values() for name in record.get("dependencies", ())}
        self.state["dependencies"] = {name: digest for name, digest in self.state["dependencies"].items() if name in required}
        self.save()
        if not restored or components:
            self.verify_plugins()
        if cacheable and (not restored or components):
            files = self.component_cache_files(self.state)
            payload = {name: path for name, (path, _) in files.items()}
            cache_state = dict(self.state, components={component.key: self.state["components"][component.key] for component in self.components})
            state_path = self.work / "plugin-cache-components.json"
            state_path.write_text(json.dumps(cache_state, indent=2) + "\n", encoding="utf-8")
            payload["components.json"] = state_path
            publish_build_cache(self.cache_archive, self.cache_key, payload)
        self.install_editor()
        if self.r79:
            # Verify once with the actual autoload paths and installed dependencies.
            code = (
                "import vapoursynth as vs; c=vs.core; "
                "clip=c.std.BlankClip(width=64,height=48,length=1,format=vs.GRAY16); "
                "assert c.descale.Debilinear(clip,48,32).get_frame(0).width==48; "
                "assert c.rgvs.RemoveGrain(clip,mode=1).get_frame(0).width==64; "
                "assert c.lsmas.LWLibavSource and c.eedi2.EEDI2 and c.nlm_ispc.NLMeans and c.assrender.TextSub"
            )
            subprocess.run([sys.executable, "-I", "-c", code], check=True, timeout=120)
        self.log("Independent VapourSynth components verified: {count}", count=len(self.state["components"]))


def main():
    import errno
    import msvcrt

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", required=True, type=Path)
    parser.add_argument("--plugins-dir", type=Path)
    parser.add_argument("--editor-path", type=Path)
    parser.add_argument("--editor-cache", type=Path)
    parser.add_argument("--visual-studio-installation", type=Path)
    parser.add_argument("--libass", required=True, type=Path)
    parser.add_argument("--libass-version", required=True)
    parser.add_argument("--work-root", required=True, type=Path)
    parser.add_argument("--msys2-root", type=Path, default=Path(r"C:\msys64"))
    parser.add_argument("--seven-zip", default=r"C:\Program Files\7-Zip\7z.exe")
    parser.add_argument("--jobs", type=int, default=os.cpu_count() or 1)
    parser.add_argument("--language", choices=("en", "zh"), default="en")
    parser.add_argument("--build-cache", type=Path)
    parser.add_argument("--build-fingerprint", default="")
    parser.add_argument("--defer-msys2", action="store_true")
    parser.add_argument("--build-with-vulkan", action="store_true")
    parser.add_argument("--windows-on-arm", action="store_true")
    args = parser.parse_args()
    if args.build_cache and not args.build_fingerprint:
        parser.error("--build-cache requires --build-fingerprint")
    args.runtime_root.mkdir(parents=True, exist_ok=True)
    with (args.runtime_root / ".components.lock").open("a+b") as lock:
        if lock.tell() == 0:
            lock.write(b"0")
            lock.flush()
        waiting = False
        while True:
            lock.seek(0)
            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError as error:
                if error.errno not in (errno.EACCES, errno.EDEADLK):
                    raise
                if not waiting:
                    print("[BluraySubtitle][SETUP] " + translate_text(
                        "Another VapourSynth installation is running; waiting.", args.language), flush=True)
                    waiting = True
                time.sleep(1)
        try:
            Installer(args).install()
        except Msys2Required:
            return MSYS2_REQUIRED_EXIT_CODE
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
