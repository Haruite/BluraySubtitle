"""Install Windows VapourSynth components from their independent upstreams."""
from __future__ import annotations

import argparse
import ast
import configparser
import ctypes
from dataclasses import asdict, dataclass, replace
import hashlib
import html
from inspect import getsource
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from textwrap import dedent
import time
import urllib.error
import urllib.parse
import urllib.request
from zipfile import BadZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.core.i18n import translate_text
from tools import build_vsedit_windows as vsedit_build
from tools.vapoursynth_plugin_releases import SOURCES, resolve_releases
from tools.vapoursynth_plugin_versions import fallback_version, normalize_version, record_version, version_satisfies
from tools.vulkan_device import vulkan_device_available
from tools.windows_build_cache import files_under, publish as publish_build_cache, restore as restore_build_cache
from tools.windows_native_tools import (
    PE_ARM64, VSEDIT_ARM64_RECIPE, VSEDIT_PLUGINS, VSEDIT_PROGRAMS, VSEDIT_QT_LIBRARIES, VSEDIT_RECIPE,
    build_record, editor_runtime_matches, fetch_verified, file_hash, fingerprint, has_pe_machine, install_build,
    msvc_environment, msys_pkg_config_environment, pyqt_runtime, record_build, windows_machine,
)
from tools.windows_tool_paths import normalize_vsedit_path

BUILD_PROFILE = "static-runtime-shared-fftw-1"
# The smaller library retains the ABI of the cached FFTW build.
FFTW_CACHE_RECIPE = "8e3206eeecb37b7fe3ef3fc7d5723d0f937a6f8d8f51a04e94e87b79d9c192bd"
MSYS2_REQUIRED_EXIT_CODE = 75


class Msys2Required(Exception):
    """Resume component installation after MSYS2 preparation."""


class BuildInputs(ast.NodeTransformer):
    """Keep build commands and patches while ignoring diagnostics."""

    def visit_Expr(self, node):
        value = node.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return None
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute):
            receiver = value.func.value
            if isinstance(receiver, ast.Name) and receiver.id == "self" and value.func.attr == "log":
                return None
        return self.generic_visit(node)


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
    source_archive: tuple[str, str] | None = None
    data_files: tuple[str, ...] = ()


LEGACY_SOURCE_KEYS = {"eedi3": "legacy-filters", "misc": "legacy-filters"}


def upstream_component(key, filename, namespace, recipe="meson", asset="", **options):
    repository = SOURCES[LEGACY_SOURCE_KEYS.get(key, key)].repository
    return Component(key, repository, "", filename, namespace, recipe, asset, **options)


COMPONENTS = (
    upstream_component("descale", "descale.dll", "descale", asset=r"amd64[.]zip$"),
    upstream_component("addgrain", "addgrain.dll", "grain", asset=r"win64[.]7z$"),
    upstream_component("assrender", "assrender.dll", "assrender", "assrender"),
    upstream_component("bilateral", "bilateral.dll", "bilateral", "configure"),
    upstream_component("dfttest", "dfttest.dll", "dfttest", asset=r"[.]7z$"),
    upstream_component("eedi2", "eedi2.dll", "eedi2", asset=r"[.]7z$"),
    upstream_component("eedi3m", "eedi3m.dll", "eedi3m", asset=r"win64.*[.](?:7z|zip)$"),
    upstream_component("znedi3", "znedi3.dll", "znedi3", "znedi3", data_files=("nnedi3_weights.bin",)),
    upstream_component("fmtconv", "fmtconv.dll", "fmtc", "autotools"),
    upstream_component("lsmas", "libvslsmashsource.dll", "lsmas", "lsmash", fallback_ref="ae51313"),
    upstream_component("sangnom", "vs_sangnommod.dll", "sangnom", "configure", r"[.]zip$"),
    upstream_component("placebo", "libvs_placebo.dll", "placebo"),
    upstream_component("nlm_ispc", "vsnlm_ispc.dll", "nlm_ispc", "cmake", r"windows-x64.*[.]7z$"),
    upstream_component("zsmooth", "zsmooth.dll", "zsmooth", "zig", r"zsmooth(?:[.]avx2[.]dll|-x86_64-windows)[.]zip$"),
    upstream_component("mvtools", "mvtools.dll", "mv", asset=r"win64[.]7z$"),
    upstream_component("removegrain", "RemoveGrainVS.dll", "rgvs", "removegrain", r"win64.*[.](?:zip|7z)$"),
)
R79_ADDITIONAL_COMPONENTS = (
    upstream_component("eedi3", "EEDI3.dll", "eedi3", "legacy-core"),
    upstream_component("misc", "MiscFilters.dll", "misc", "legacy-core"),
    upstream_component("vivtc", "VIVTC.dll", "vivtc", "legacy-core"),
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
elif sys.argv[2] == 'znedi3':
    assert hasattr(p, 'nnedi3'), 'ZNEDI3 must expose the NNEDI3 filter'
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
                replace(component, asset="") if component.key == "descale" else component
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
        self.cached_plugins = {}
        self.editor_cache = args.editor_cache or args.build_cache or (
            Path(os.environ["ProgramData"]) / "BluraySubtitle/build-cache/artifacts"
        )

    def component_cache_keys(self, component, ref, build_profile):
        builder, patch = self.source_recipe(component)
        recipe = [self.run_msys, builder]
        if patch:
            recipe.append(patch)
        inputs = [asdict(component), ref, build_profile, self.r79, self.static_runtime]
        if component.recipe not in ("lsmash", "assrender"):
            recipe.append(self.build_environment)
        if component.recipe not in ("lsmash", "assrender", "znedi3", "zig"):
            inputs.append(self.sdk_hashes)
            recipe.append(self.prepare_sdk)
        if component.key in ("dfttest", "mvtools"):
            inputs.append(FFTW_CACHE_RECIPE)
        if component.key == "assrender":
            inputs += [self.args.libass_version, file_hash(self.args.libass)]
        if component.key == "placebo":
            recipe.append(self.prepare_static_placebo)
        if component.recipe == "meson":
            if options := getattr(self, f"{component.key}_meson_options", None):
                recipe.append(options)
        if component.key == "zsmooth" and not self.arm64:
            import numpy as np
            inputs.append(bool(np._core._multiarray_umath.__cpu_features__.get("AVX2")))
        sources = [getsource(method) for method in recipe]
        build_inputs = [ast.dump(BuildInputs().visit(ast.parse(dedent(source)))) for source in sources]
        key = fingerprint("vapoursynth-plugin-2", self.subsystem, inputs, build_inputs)
        legacy_keys = [fingerprint("vapoursynth-plugin-1", inputs, sources)]
        if component.key == "descale":
            # The previous resolver stored an empty component ref alongside the resolved tag.
            legacy_keys.append(fingerprint("vapoursynth-plugin-1", [{**inputs[0], "ref": ""}, *inputs[1:]], sources))
        return key, tuple(legacy_keys)

    def component_cache_files(self, component, record, plugin_files):
        license_root = (self.runtime / "licenses/components" / component.key).resolve()
        expected = [self.record_path(path) for path in plugin_files]
        if (record["name"] != component.key or record["repository"] != component.repository
                or record["plugin"] != expected[0] or record.get("data", []) != expected[1:]
                or not set(expected) <= record["files"].keys()):
            raise ValueError("Invalid cached VapourSynth component entry")
        files = {}
        for name, digest in record["files"].items():
            target = (self.runtime / name).resolve()
            if name not in expected and (Path(name).is_absolute() or not target.is_relative_to(license_root)):
                raise ValueError("Invalid cached VapourSynth component file path")
            files["files/" + hashlib.sha256(name.encode("utf-8")).hexdigest()] = (target, digest)
        return files

    def dependency_cache(self, name, digest):
        key = fingerprint(name.casefold(), digest)
        return self.args.build_cache / f"vs-dll-{key}.zip", key

    def restore_plugin(self, archive, key, legacy_keys, component, ref, plugin_files):
        with tempfile.TemporaryDirectory(prefix="filter-", dir=self.work) as temporary:
            work = Path(temporary)
            payload = work / "cached"
            try:
                matched = restore_build_cache(archive, key, payload, legacy_keys=legacy_keys)
                if not matched:
                    return False
                cached = json.loads((payload / "component.json").read_text(encoding="utf-8"))
                record, dependencies = cached["record"], cached["dependencies"]
                if (record.get("target_ref", record["ref"]) != ref or record["cache_recipe"] != matched
                        or set(dependencies) != set(record["dependencies"])):
                    return False
                files = self.component_cache_files(component, record, plugin_files)
                if any(not (payload / name).is_file() or sha256(payload / name) != digest
                       for name, (_, digest) in files.items()):
                    return False
                if component.key != "removegrain" and any(
                    path.exists() and sha256(path) != record["files"][self.record_path(path)] for path in plugin_files
                ):
                    return False
                staged = work / "staged"
                staged.mkdir()
                for name, (path, _) in files.items():
                    if path in plugin_files:
                        shutil.copyfile(payload / name, staged / path.name)
                effective = {}
                for name, digest in dependencies.items():
                    target = self.runtime / name
                    if (target.parent != self.runtime or target.suffix.lower() != ".dll"
                            or name.casefold() in {"vapoursynth.dll", "vsscript.dll", component.filename.casefold()}):
                        return False
                    if name.casefold() == "libass-9.dll":
                        source = self.args.libass
                        if file_hash(source) != digest:
                            return False
                    elif target.is_file() and self.state["dependencies"].get(name) == file_hash(target):
                        # DLL names share one runtime directory. Probe with the copy already in use.
                        source = target
                    else:
                        library, library_key = self.dependency_cache(name, digest)
                        restored = work / library.stem
                        if not restore_build_cache(library, library_key, restored):
                            return False
                        source = restored / name
                        if file_hash(source) != digest:
                            return False
                    if not has_pe_machine(source):
                        return False
                    shutil.copyfile(source, staged / name)
                    effective[name] = file_hash(source)
                expected = ("commit:" + record["ref"] if record["method"] == "source"
                            and record["ref"] == component.fallback_ref else ref)
                probe = self.probe(staged / component.filename, component, expected)
            except (BadZipFile, KeyError, OSError, RuntimeError, TypeError, ValueError, subprocess.SubprocessError):
                return False

            for name, (path, digest) in files.items():
                if not path.is_file() or sha256(path) != digest:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(payload / name, path)
            for name, digest in effective.items():
                path = self.runtime / name
                if not path.is_file() or file_hash(path) != digest:
                    shutil.copyfile(staged / name, path)
            record_version(plugin_files[0], expected, probe["native_version"])
            record["cache_recipe"] = key
            self.state["components"][component.key] = record
            self.state["dependencies"].update(effective)
            self.cached_plugins[component.key] = (archive, key, dependencies)
            if matched != key:
                self.publish_plugin(archive, key, component, plugin_files)
            self.save()
            return True

    def publish_plugin(self, archive, key, component, plugin_files):
        record = self.state["components"][component.key]
        files = self.component_cache_files(component, record, plugin_files)
        dependencies = {name: self.state["dependencies"][name] for name in record["dependencies"]}
        for name, digest in dependencies.items():
            if name.casefold() != "libass-9.dll":
                library, library_key = self.dependency_cache(name, digest)
                publish_build_cache(library, library_key, {name: self.runtime / name})
        with tempfile.TemporaryDirectory(prefix="publish-", dir=self.work) as temporary:
            metadata = Path(temporary) / "component.json"
            metadata.write_text(json.dumps({"record": record, "dependencies": dependencies}) + "\n", encoding="utf-8")
            publish_build_cache(archive, key, {"component.json": metadata, **{name: item[0] for name, item in files.items()}})
        self.cached_plugins[component.key] = (archive, key, dependencies)

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
        if component.source_archive:
            url, digest = component.source_archive
            archive = self.download(url, parent / "source.tar.gz", digest)
        else:
            url = f"https://codeload.github.com/{component.repository}/zip/{urllib.parse.quote(ref, safe='/')}"
            archive = self.download(url, parent / "source.zip")
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
        cache = self.args.build_cache / "fftw.zip" if self.args.build_cache else None
        key = fingerprint(FFTW_CACHE_RECIPE, "arm64") if self.arm64 else FFTW_CACHE_RECIPE

        def valid_prefix(directory):
            return has_pe_machine(directory / "bin/libfftw3f-3.dll") and all(
                (directory / name).is_file() for name in (
                    "lib/libfftw3f.dll.a", "include/fftw3.h", "share/licenses/fftw/COPYING",
                )
            )

        if valid_prefix(prefix):
            if self.complete_fftw_runtime(prefix) and cache:
                publish_build_cache(cache, key, files_under(prefix))
            return prefix
        if cache:
            restored = self.work / "fftw/restored"
            if restore_build_cache(cache, key, restored) and valid_prefix(restored):
                restored.rename(prefix)
                if self.complete_fftw_runtime(prefix):
                    publish_build_cache(cache, key, files_under(prefix))
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
                + " --with-our-malloc --disable-fortran --enable-shared --disable-static --disable-dependency-tracking",
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
        self.complete_fftw_runtime(prefix)
        if cache:
            publish_build_cache(cache, key, files_under(prefix))
        return prefix

    def complete_fftw_runtime(self, prefix):
        binaries = prefix / "bin"
        thread_library = "libwinpthread-1.dll"
        target = binaries / thread_library
        if has_pe_machine(target) or thread_library not in {
            name.casefold() for name in imported_dlls(binaries / "libfftw3f-3.dll")
        }:
            return False
        source = self.msys / "bin" / thread_library
        if not has_pe_machine(source):
            self.require_msys2()
            raise RuntimeError(f"FFTW requires the missing MSYS2 runtime {source}")
        pacman = self.args.msys2_root / "usr/bin/pacman.exe"
        owner = subprocess.check_output([str(pacman), "-Qqo", f"/{self.subsystem}/bin/{thread_library}"],
                                        text=True, encoding="utf-8").strip()
        for _, path in self.msys_package_licenses([owner]):
            notice = prefix / "share/licenses/libwinpthread" / path.name
            notice.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, notice)
        shutil.copyfile(source, target)
        return True

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

    def msys_package_licenses(self, packages):
        result = subprocess.run([str(self.args.msys2_root / "usr/bin/pacman.exe"), "-Ql", *packages],
                                check=True, capture_output=True, text=True, encoding="utf-8")
        for line in result.stdout.splitlines():
            package_name, _, relative = line.partition(" ")
            if "/share/licenses/" in relative:
                path = self.args.msys2_root / relative.lstrip("/")
                if path.is_file():
                    yield package_name.removeprefix(self.package_prefix), path

    def licenses(self, component, source, extra=None):
        destination, collected = self.runtime / "licenses/components" / component.key, {}
        for index, root in enumerate([source] + ([extra] if extra else [])):
            for path in root.rglob("*"):
                in_license_directory = any(part.lower() in ("licenses", "licences") for part in path.relative_to(root).parts)
                if not path.is_file() or not (in_license_directory or re.match(r"^(COPYING|COPYRIGHT|LICEN[CS]E|UNLICENSE|GPL[23])([._-].*)?$", path.name, re.I)):
                    continue
                if any(part in ("build", ".git", "node_modules") for part in path.relative_to(root).parts):
                    continue
                target = destination / ("release" if index else "source") / path.relative_to(root)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
                collected[target.relative_to(self.runtime).as_posix()] = sha256(target)
        if not collected:
            destination.mkdir(parents=True, exist_ok=True)
            repository = urllib.parse.urljoin("https://github.com/", component.repository)
            notices = [f"Upstream: {repository}\n",
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
            for package_name, path in self.msys_package_licenses(packages):
                target = destination / "dependencies" / package_name / path.name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
                collected[target.relative_to(self.runtime).as_posix()] = sha256(target)
        if component.key in ("dfttest", "mvtools"):
            fftw_licenses = self.work / "fftw/prefix/share/licenses"
            for path in fftw_licenses.glob("*/*"):
                if path.is_file():
                    target = destination / "dependencies" / path.relative_to(fftw_licenses)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(path, target)
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

    def build_lsmash(self, component, source):
        self.ensure_packages("dav1d", "libvpx", "libxml2", "libiconv", "zlib")
        if not self.arm64:
            self.ensure_packages("libmfx")
        if self.use_vulkan:
            self.ensure_packages("shaderc", "glslang", "spirv-tools", "vulkan-headers", "vulkan-loader")
        tree_url = f"https://api.github.com/repos/{component.repository}/git/trees/{component.ref}"
        with self.open_url(tree_url, timeout=60) as response:
            revisions = {item["path"]: item["sha"] for item in json.load(response)["tree"] if item["type"] == "commit"}
        ffmpeg = self.dependency_source("FFmpeg", "HomeOfAviSynthPlusEvolution/FFmpeg", revisions["FFmpeg"])
        nvcodec = None if self.arm64 else self.dependency_source(
            "nv-codec-headers", "FFmpeg/nv-codec-headers", "n13.0.19.0")
        for name, repository in (
            ("l-smash", "HomeOfAviSynthPlusEvolution/l-smash"),
            ("obuparse", "HomeOfAviSynthPlusEvolution/obuparse"),
            ("xxHash", "Cyan4973/xxHash"),
        ):
            dependency = self.dependency_source(name, repository, revisions[name])
            shutil.copytree(dependency, source / name, dirs_exist_ok=True)
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

        work = self.work / "lsmas" / component.ref
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
        if self.use_vulkan:
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
            shlex.join([self.posix(ffmpeg / "configure"), *ffmpeg_options]) + ' --pkg-config="$PKG_CONFIG"',
            f"make -j{self.args.jobs}",
            "make install",
        ], ffmpeg_build)

        # Use the real audio helpers when compiling both plugin entry points.
        wrapper = source / "VapourSynth/lwlibav_source.c"
        text = wrapper.read_text(encoding="utf-8")
        wrapper.write_text(text.replace("#ifndef _MSC_VER\n", "#if !defined(_MSC_VER) && !defined(LSMASH_WITH_AVISYNTH)\n", 1),
                           encoding="utf-8")
        cmake = source / "CMakeLists.txt"
        link_libraries = ["ws2_32", "secur32", "crypt32", "ncrypt",
                          f'"{msys.as_posix()}/lib/libiconv.a"', f'"{msys.as_posix()}/lib/libz.a"']
        text = cmake.read_text(encoding="utf-8").replace("if (${sse2})", "if (ENABLE_SSE2)")
        cmake_vulkan = "Vulkan::shaderc_combined" in text
        if self.use_vulkan and not cmake_vulkan:
            link_libraries.append(f'"{msys.as_posix()}/lib/libshaderc_shared.dll.a"')
        cmake.write_text(text.replace(
            "        target_link_libraries(LSMASHSource PRIVATE ws2_32)\n",
            "        set_target_properties(LSMASHSource PROPERTIES LINKER_LANGUAGE CXX)\n"
            f"        target_link_libraries(LSMASHSource PRIVATE {' '.join(link_libraries)})\n",
        ), encoding="utf-8")
        build = work / "plugin-build"
        cmake_options = [
            "-G", "Ninja", "-DCMAKE_BUILD_TYPE=MinSizeRel", "-DCMAKE_DISABLE_FIND_PACKAGE_Git=ON",
            "-DBUILD_VS_PLUGIN=ON",
            "-DBUILD_AVS_PLUGIN=" + ("OFF" if self.arm64 else "ON"),
            "-DENABLE_SSE2=" + ("OFF" if self.arm64 else "ON"),
            "-DENABLE_MFX=" + ("OFF" if self.arm64 else "ON"),
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
        if cmake_vulkan:
            cmake_options.extend(["-DENABLE_VULKAN=" + ("ON" if self.use_vulkan else "OFF"),
                                  f"-DVulkan_shaderc_combined_LIBRARY={msys.as_posix()}/lib/libshaderc_shared.dll.a"])
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

    def prepare_eedi3m_source(self, component, source, commands):
        include = self.sdk / "include/vapoursynth"
        if self.arm64:
            header = source / "EEDI3/EEDI3.h"
            text = header.read_text(encoding="utf-8")
            if "#include <cmath>" not in text:
                header.write_text("#include <cmath>\n" + text, encoding="utf-8")
        meson = source / "meson.build"
        text = meson.read_text(encoding="utf-8")
        start, end = text.index("incdir = include_directories("), text.index("\nlibs = []")
        meson.write_text(text[:start] + f"incdir = include_directories('{include.as_posix()}')\n" + text[end:], encoding="utf-8")

    def prepare_mvtools_source(self, component, source, commands):
        include = self.sdk / "include/vapoursynth"
        prefix = self.prepare_fftw()
        path = source / "meson.build"
        text = path.read_text(encoding="utf-8")
        text = re.sub(r"incdir = include_directories\(\s*(?:'vapoursynth/include'|run_command\(.*?\.stdout\(\)\.strip\(\),?)\s*\)",
                      f"incdir = include_directories('{include.as_posix()}')", text, flags=re.S)
        # DFTTest already needs this DLL; do not embed a second FFTW copy.
        text = text.replace("dependency('fftw3f')", "declare_dependency(include_directories: include_directories('"
                      + (prefix / "include").as_posix() + "'), link_args: ['"
                      + (prefix / "lib/libfftw3f.dll.a").as_posix() + "'])")
        path.write_text(text, encoding="utf-8")

    def prepare_dfttest_source(self, component, source, commands):
        prefix = self.prepare_fftw()
        path = source / "meson.build"
        text = path.read_text(encoding="utf-8")
        text = text.replace("fftw3f_dep = dependency('fftw3f')",
                            "fftw3f_dep = declare_dependency(include_directories: include_directories('"
                            + (prefix / "include").as_posix() + "'), link_args: ['"
                            + (prefix / "lib/libfftw3f.dll.a").as_posix() + "'])")
        path.write_text(text, encoding="utf-8")

    def prepare_descale_source(self, component, source, commands):
        path = source / "src/vsplugin.cc"
        text = path.read_text(encoding="utf-8")
        path.write_text("\n".join(line.replace("data->", "d.") if "vsapi->createVideoFilter" in line else line
                                  for line in text.split("\n")), encoding="utf-8")

    def prepare_placebo_source(self, component, source, commands):
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

    def prepare_sangnom_source(self, component, source, commands):
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

    def prepare_nlm_ispc_source(self, component, source, commands):
        build_directory = "build-" + BUILD_PROFILE
        include = self.sdk / "include/vapoursynth"
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

    def descale_meson_options(self):
        include = self.sdk / "include/vapoursynth"
        headers = include.parent if self.r79 else include
        return "true", ["-Dlibtype=vapoursynth", f"-Dc_args=-I{headers.as_posix()}", f"-Dcpp_args=-I{headers.as_posix()}"]

    def placebo_meson_options(self):
        return "false" if self.arm64 else "true", ["-Dr73-compat=true"]

    def build_meson(self, component, source, commands):
        jobs = str(self.args.jobs)
        build_directory = "build-" + BUILD_PROFILE
        configure = getattr(self, f"{component.key}_meson_options", None)
        static, overrides = configure() if configure else ("true", [])
        options = ["-Dprefer_static=" + static, "-Db_lto=" + ("false" if self.arm64 else "true")]
        if not self.arm64:
            options += ["-Db_lto_threads=" + jobs]
        options += overrides
        wipe = " --wipe" if (source / build_directory / "meson-private/coredata.dat").is_file() else ""
        self.run_msys(commands + ["meson setup " + build_directory + wipe + " --buildtype=release " + " ".join(map(shlex.quote, options)),
                                 "meson compile -C " + build_directory + " -j " + jobs], source)

    def build_cmake(self, component, source, commands):
        jobs = str(self.args.jobs)
        build_directory = "build-" + BUILD_PROFILE
        self.run_msys(commands + ["cmake -S . -B " + build_directory + " -G Ninja -DCMAKE_BUILD_TYPE=Release "
                       + "-DCMAKE_PREFIX_PATH=" + shlex.quote(self.sdk.as_posix()),
                       "cmake --build " + build_directory + " --parallel " + jobs], source)

    def build_znedi3(self, component, source, commands):
        jobs = str(self.args.jobs)
        targets = "" if self.arm64 else " X86=1 X86_AVX512=1"
        self.run_msys(commands + ["make -j" + jobs + targets, f"mv vsznedi3.so {component.filename}"], source)

    def build_autotools(self, component, source, commands):
        jobs = str(self.args.jobs)
        # fmtconv keeps its configure script outside the source root.
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

    def build_configure(self, component, source, commands):
        jobs = str(self.args.jobs)
        include = self.sdk / "include/vapoursynth"
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

    def build_legacy_core(self, component, source, commands):
        include = self.sdk / "include/vapoursynth"
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

    def build_removegrain(self, component, source, commands):
        jobs = str(self.args.jobs)
        include = self.sdk / "include/vapoursynth"
        objects = [name + ".o" for name in ("clense", "removegrainvs", "repairvs", "shared", "verticalcleaner")]
        cpu_option = "" if self.arm64 else "-DVS_TARGET_CPU_X86 "
        makefile = f"CXXFLAGS = -O3 -std=c++11 {cpu_option}-I" + shlex.quote(include.as_posix()) + "\n"
        makefile += "RemoveGrainVS.dll: " + " ".join(objects) + "\n\t$(CXX) -shared $(LDFLAGS) -o $@ $^\n"
        makefile += "%.o: src/%.cpp Makefile\n\t$(CXX) $(CXXFLAGS) -c -o $@ $<\n"
        (source / "Makefile").write_text(makefile, encoding="utf-8", newline="\n")
        self.run_msys(commands + ["make -j" + jobs], source)

    def build_zig(self, component, source, commands):
        manifest = source / "build.zig.zon"
        text = manifest.read_text(encoding="utf-8")
        minimum = re.search(r'\.minimum_zig_version\s*=\s*"([0-9]+\.[0-9]+\.[0-9]+)"', text)
        # The Classic-compatible source predates the minimum Zig version field.
        version = minimum[1] if minimum else "0.12.0"
        architecture = "aarch64" if self.arm64 else "x86_64"
        zig_dir = self.work / "zig" / version
        with self.open_url("https://ziglang.org/download/index.json", timeout=60) as response:
            download = json.load(response)[version][architecture + "-windows"]
        archive = self.download(download["tarball"], zig_dir / "zig.zip", download["shasum"])
        executable = next(self.unpack(archive, zig_dir / "unpacked").rglob("zig.exe"))

        dependencies = re.compile(
            r'\.url = "(?:https://github\.com/([^/]+/[^/]+)/archive/([0-9a-f]+)\.tar\.gz|'
            r'git\+https://github\.com/([^/]+/[^/]+?)\.git(?:\?[^"#]*)?#([0-9a-f]+))",\s*\.hash = "[^"]+",'
        )

        def vendor(match):
            repository, revision = match.groups()[:2] if match[1] else match.groups()[2:]
            name = repository.rsplit("/", 1)[1]
            relative = Path("dependencies") / name
            shutil.copytree(self.dependency_source(name, repository, revision), source / relative, dirs_exist_ok=True)
            return f'.path = "{relative.as_posix()}",'

        manifest.write_text(dependencies.sub(vendor, text), encoding="utf-8")
        subprocess.run([executable, "build", "-j" + str(self.args.jobs), "-Doptimize=ReleaseFast",
                        f"-Dtarget={architecture}-windows-gnu", "-Dcpu=baseline"], cwd=source, check=True)

    def source_recipe(self, component):
        builder = getattr(self, "build_" + component.recipe.replace("-", "_"))
        patch = getattr(self, f"prepare_{component.key}_source", None)
        return builder, patch

    def build_environment(self):
        return [f"export LDFLAGS='{self.static_runtime} -Wl,--gc-sections -s'",
                "export CFLAGS='-ffunction-sections -fdata-sections'",
                "export CXXFLAGS='-ffunction-sections -fdata-sections'"]

    def build(self, component, source):
        self.require_msys2()
        builder, patch = self.source_recipe(component)
        if component.recipe == "lsmash":
            return builder(component, source)
        if component.recipe == "assrender":
            return builder(source)
        if component.recipe != "znedi3":
            self.prepare_sdk()
        commands = self.build_environment()
        if patch:
            binary = patch(component, source, commands)
            if binary is not None:
                return binary
        builder(component, source, commands)
        names = {component.filename.lower(), "lib" + component.filename.lower()}
        if component.key == "removegrain":
            names |= {"libremovegrain.dll", "removegrain.dll"}
        if component.key == "sangnom":
            names.add("libvs_sangnommod.dll")
        output = source / ("build-" + BUILD_PROFILE) if component.recipe in ("meson", "cmake") else source
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
        target_ref = component.ref
        repository_url = urllib.parse.urljoin("https://github.com/", component.repository)
        folder = self.runtime / "vapoursynth64/coreplugins" if component.key == "removegrain" and not self.r79 else self.plugins
        target = folder / component.filename
        relative = self.record_path(target)
        plugin_files = (target, *(folder / name for name in component.data_files))
        data = [self.record_path(path) for path in plugin_files[1:]]
        build_profile = BUILD_PROFILE + ("-arm64" if self.arm64 else "")
        if component.key == "lsmas" and not self.use_vulkan:
            build_profile += "-without-vulkan"
        if self.arm64 and component.key == "placebo":
            build_profile += "-static-placebo"
        cache_archive, cache_key, legacy_keys = None, None, ()
        if self.args.build_cache:
            runtime = "r79" if self.r79 else "classic"
            cache_archive = self.args.build_cache / f"vs-{runtime}-{component.key}.zip"
            cache_key, legacy_keys = self.component_cache_keys(component, target_ref, build_profile)
            if self.restore_plugin(cache_archive, cache_key, legacy_keys, component, target_ref, plugin_files):
                self.log("Restored VapourSynth component from the build cache: {name}", name=component.key)
                return False

        present = all(path.is_file() and path.stat().st_size > 0 for path in plugin_files)
        known_files = bool(previous and present and all(
            previous["files"].get(self.record_path(path)) == sha256(path) for path in plugin_files
        ))
        same_target = known_files and previous.get("target_ref", previous["ref"]) == target_ref
        fallback = bool(known_files and previous["method"] == "source" and previous["ref"] == component.fallback_ref)
        expected = "commit:" + component.fallback_ref if fallback and same_target else target_ref
        installed, probe = None, None
        if present:
            try:
                probe = self.probe(target, component, expected)
            except RuntimeError as error:
                self.log("Installed VapourSynth plugin cannot be loaded: {name}: {detail}", name=component.key, detail=str(error))
            else:
                installed = fallback_version(target)
                # Migrate the previous hash-bound component manifest once.
                if installed is None and known_files and previous["method"] != "existing":
                    installed = "commit:" + component.fallback_ref if fallback else normalize_version(previous["ref"])
                    record_version(target, installed, probe["native_version"])
                installed = installed or probe["native_version"]
        rebuild = bool(same_target and previous["method"] == "source" and (
            previous.get("build_profile") != build_profile
            or (cache_key and previous.get("cache_recipe", cache_key) not in (cache_key, *legacy_keys))
        ))
        if installed is not None and version_satisfies(installed, expected) and not rebuild:
            if not known_files:
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
                files = {self.record_path(path): sha256(path) for path in plugin_files}
                files.update(self.licenses(component, source))
                previous = {
                    "name": component.key, "repository": component.repository, "target_ref": target_ref,
                    "ref": installed, "method": "existing", "source_url": repository_url,
                    "license_source_ref": target_ref, "artifact_url": "", "plugin": relative,
                    "files": files, "data": data, "dependencies": dependency_names, "source_dependencies": self.source_dependencies,
                }
                self.state["components"][component.key] = previous
            previous.update(target_ref=target_ref, installed_version=installed, registered_version=probe["version"])
            if cache_archive and previous.get("cache_recipe") in (cache_key, *legacy_keys) and self.valid(previous, target_ref):
                previous["cache_recipe"] = cache_key
                self.publish_plugin(cache_archive, cache_key, component, plugin_files)
            self.save()
            self.log("VapourSynth plugin meets the required version: {name} {installed} >= {target}",
                     name=component.key, installed=installed, target=expected)
            return True
        if rebuild:
            self.log("Rebuilding VapourSynth plugin with updated link options: {name}", name=component.key)
        else:
            self.log("VapourSynth plugin needs installation or update: {name} {installed} -> {target}",
                     name=component.key, installed=installed or "?", target=expected)
        release = self.release(component.repository, target_ref, missing_ok=True) if component.asset and not self.arm64 else None
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
                release_archive = self.download_release_asset(artifact, self.work / component.key / target_ref / artifact["name"])
                package = self.unpack(release_archive, release_archive.parent / ("release-" + release_archive.stem))
                names = {component.filename.lower()} | ({"lsmashsource.dll"} if component.key == "lsmas" else set())
                if component.key == "zsmooth":
                    names.add("zsmooth.avx2.dll")
                candidates = [path for path in package.rglob("*.dll") if path.name.lower() in names and has_pe_machine(path)]
                if component.key == "sangnom":
                    candidates.sort(key=lambda path: ("clang" not in path.parts, "x64" not in path.parts))
                for index, candidate in enumerate(candidates):
                    candidate_stage = self.work / component.key / f"candidate-{index}"
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
        for name in component.data_files:
            shutil.copyfile(source / name, stage / name)
        dependencies = self.dependencies(binary, stage)
        probe = self.probe(staged_binary, component, target_ref)
        folder.mkdir(parents=True, exist_ok=True)
        for path in reversed(plugin_files):
            shutil.copyfile(stage / path.name, path)
        record_version(target, target_ref, probe["native_version"])
        dependency_names = []
        for dependency in dependencies:
            installed = self.runtime / dependency.name
            shutil.copyfile(dependency, installed)
            relative = installed.relative_to(self.runtime).as_posix()
            self.state["dependencies"][relative] = sha256(installed)
            dependency_names.append(relative)
        files = {self.record_path(path): sha256(path) for path in plugin_files}
        files.update(self.licenses(component, source, package))
        source_url = (
            component.source_archive[0] if component.source_archive
            else f"{repository_url}/tree/{target_ref}"
        )
        self.state["components"][component.key] = {
            "name": component.key, "repository": component.repository, "target_ref": target_ref, "ref": target_ref, "method": method,
            "source_url": source_url,
            "artifact_url": artifact["url"] if method == "release" else "",
            "plugin": self.record_path(target), "registered_version": probe["version"],
            "installed_version": probe["native_version"] or normalize_version(target_ref),
            "build_profile": build_profile if method == "source" else "",
            "files": files, "data": data, "dependencies": dependency_names,
            "source_dependencies": self.source_dependencies + ([{"name": "FFTW", "version": "3.3.11", "source_url": "https://fftw.org/fftw-3.3.11.tar.gz"}]
                                   if component.key in ("dfttest", "mvtools") else []),
        }
        if cache_archive:
            self.state["components"][component.key]["cache_recipe"] = cache_key
        self.save()
        if cache_archive:
            self.publish_plugin(cache_archive, cache_key, component, plugin_files)
        return True

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

    def verify_plugins(self):
        for component in self.components:
            if component.key in self.state.get("skipped", {}):
                continue
            record = self.state["components"][component.key]
            target = self.runtime / record["plugin"]
            ref = ("commit:" + record["ref"] if record["method"] == "source" and record["ref"] == component.fallback_ref
                   else record.get("target_ref", record["ref"]))
            self.probe(target, component, ref)

    def install(self):
        ctypes.windll.kernel32.SetErrorMode(0x8003)
        self.migrate_plugins()
        self.state.pop("cache_fingerprint", None)
        if self.args.build_cache:
            include = self.sdk / "include/vapoursynth"
            if not all((include / name).is_file() for name in ("VSConstants4.h", "VapourSynth4.h", "VSScript4.h", "VSHelper4.h")):
                self.prepare_sdk()
            self.sdk_hashes = {header.name: file_hash(header) for header in include.glob("*.h")}
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
        needs_verification = False
        active = [component for component in self.components if component.key not in skipped]
        releases = resolve_releases(
            (LEGACY_SOURCE_KEYS.get(component.key, component.key) for component in active),
            self.args.git, classic=not self.r79,
        )
        for component in active:
            release = releases[LEGACY_SOURCE_KEYS.get(component.key, component.key)]
            archive = (release.source_url, release.sha256) if release.sha256 or component.key == "fmtconv" else None
            component = replace(component, ref=release.ref, source_archive=archive)
            if self.install_plugin(component):
                needs_verification = True
        required = {name for record in self.state["components"].values() for name in record.get("dependencies", ())}
        self.state["dependencies"] = {name: digest for name, digest in self.state["dependencies"].items() if name in required}
        self.save()
        if needs_verification:
            self.verify_plugins()
        for component in self.components:
            cached = self.cached_plugins.get(component.key)
            if cached:
                archive, key, dependencies = cached
                if any(self.state["dependencies"][name] != digest for name, digest in dependencies.items()):
                    record = self.state["components"][component.key]
                    plugin_files = [self.runtime / name for name in (record["plugin"], *record["data"])]
                    self.publish_plugin(archive, key, component, plugin_files)
        self.install_editor()
        if self.r79:
            # Verify once with the actual autoload paths and installed dependencies.
            code = (
                "import vapoursynth as vs; c=vs.core; "
                "clip=c.std.BlankClip(width=64,height=48,length=1,format=vs.GRAY16); "
                "assert c.descale.Debilinear(clip,48,32).get_frame(0).width==48; "
                "assert c.rgvs.RemoveGrain(clip,mode=1).get_frame(0).width==64; "
                "assert c.znedi3.nnedi3(clip, field=0, dh=True).get_frame(0).height==96; "
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
    parser.add_argument("--git", default="git")
    parser.add_argument("--jobs", type=int, default=os.cpu_count() or 1)
    parser.add_argument("--language", choices=("en", "zh"), default="en")
    parser.add_argument("--build-cache", type=Path)
    parser.add_argument("--defer-msys2", action="store_true")
    parser.add_argument("--build-with-vulkan", action="store_true")
    parser.add_argument("--windows-on-arm", action="store_true")
    args = parser.parse_args()
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
            installer = Installer(args)
            os.environ.update(msys_pkg_config_environment(installer.msys))
            installer.install()
        except Msys2Required:
            return MSYS2_REQUIRED_EXIT_CODE
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
