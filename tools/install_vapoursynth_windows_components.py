"""Install Windows VapourSynth components from their independent upstreams."""
from __future__ import annotations

import argparse
import configparser
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.core.i18n import translate_text
from tools.vapoursynth_plugin_versions import fallback_version, normalize_version, record_version, version_satisfies

BUILD_PROFILE = "static-runtime-shared-fftw-1"


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
    Component("assrender", "AmusementClub/assrender", "0.38.4", "assrender.dll", "assrender", "cmake", r"win-x64.*[.]zip$"),
    Component("bilateral", "HomeOfVapourSynthEvolution/VapourSynth-Bilateral", "r3", "bilateral.dll", "bilateral", "configure", r"[.]7z$"),
    Component("dfttest", "HomeOfVapourSynthEvolution/VapourSynth-DFTTest", "r7", "dfttest.dll", "dfttest", asset=r"[.]7z$"),
    Component("eedi2", "HomeOfVapourSynthEvolution/VapourSynth-EEDI2", "r7.1", "eedi2.dll", "eedi2", asset=r"[.]7z$"),
    Component("eedi3m", "HomeOfVapourSynthEvolution/VapourSynth-EEDI3", "r9", "eedi3m.dll", "eedi3m", asset=r"win64.*[.](?:7z|zip)$"),
    Component("fmtconv", "EleonoreMizo/fmtconv", "r30", "fmtconv.dll", "fmtc", "autotools", r"[.]zip$"),
    # Newer Windows releases use API4.2; this is the last published API3 binary.
    Component("lsmas", "HomeOfAviSynthPlusEvolution/L-SMASH-Works", "1282", "libvslsmashsource.dll", "lsmas", "lsmash", r"[.]7z$", "ae51313"),
    Component("sangnom", "HomeOfVapourSynthEvolution/VapourSynth-SangNomMod", "v0.1-fix", "vs_sangnommod.dll", "sangnom", "configure", r"[.]zip$"),
    Component("placebo", "Lypheo/vs-placebo", "2.0.4", "libvs_placebo.dll", "placebo", asset=r"windows.*[.]zip$"),
    Component("nlm_ispc", "AmusementClub/vs-nlm-ispc", "v4", "vsnlm_ispc.dll", "nlm_ispc", "cmake", r"windows-x64.*[.]7z$"),
    Component("zsmooth", "adworacz/zsmooth", "0.7", "zsmooth.dll", "zsmooth", "zig", r"zsmooth[.]avx2[.]dll[.]zip$"),
    Component("mvtools", "dubhatervapoursynth/vapoursynth-mvtools", "v26", "mvtools.dll", "mv", asset=r"win64[.]7z$"),
    Component("removegrain", "vapoursynth/vs-removegrain", "R1", "RemoveGrainVS.dll", "rgvs", "removegrain", r"win64.*[.](?:zip|7z)$"),
)
EDITOR = Component("vsedit", "YomikoR/VapourSynth-Editor", "", "vsedit.exe", "", "editor", r"[.]7z$")
PROBE = r"""
import json, os, sys
from pathlib import Path
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
elif sys.argv[2] == 'removegrain':
    assert hasattr(p, 'Repair'), 'RemoveGrain Repair is required'
elif sys.argv[2] == 'sangnom':
    assert hasattr(p, 'SangNom'), 'SangNom is required by the Python filter scripts'
print(json.dumps({'version': str(p.version), 'name': p.name, 'native_version': reported_version(p, sys.argv[5])}))
"""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pe64(path: Path) -> bool:
    data = path.read_bytes()
    return data[:2] == b"MZ" and struct.unpack_from("<H", data, struct.unpack_from("<I", data, 60)[0] + 4)[0] == 0x8664


def imported_dlls(path: Path) -> list[str]:
    import pefile
    image = pefile.PE(str(path), fast_load=True)
    try:
        image.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"]])
        return [entry.dll.decode("ascii") for entry in getattr(image, "DIRECTORY_ENTRY_IMPORT", ())]
    finally:
        image.close()


def file_version(path: Path) -> str:
    import pefile
    image = pefile.PE(str(path))
    try:
        for group in getattr(image, "FileInfo", ()):
            for entry in group:
                if entry.Key == b"StringFileInfo":
                    for table in entry.StringTable:
                        value = table.entries.get(b"ProductVersion", b"").decode("utf-8", errors="replace")
                        match = re.search(r"[0-9]+[.][0-9]+[.][0-9]+", value)
                        if match:
                            return match.group(0)
    finally:
        image.close()
    raise RuntimeError(f"Unable to read product version: {path}")


class Installer:
    def __init__(self, args):
        self.args = args
        self.runtime = args.runtime_root.resolve()
        self.work = args.work_root.resolve()
        self.work.mkdir(parents=True, exist_ok=True)
        self.state_path = self.runtime / "vapoursynth-components.json"
        self.state = json.loads(self.state_path.read_text(encoding="utf-8")) if self.state_path.is_file() else {
            "schema": 1, "components": {}, "dependencies": {},
        }
        self.sdk = self.runtime / "sdk"
        self.package_checked = set()
        self.used_packages = set()
        self.source_dependencies = []
        self.http = urllib.request.build_opener()
        self.http.addheaders = [("User-Agent", "BluraySubtitle-Windows-Setup")]
        self.json_cache = {}

    def log(self, template, **values):
        print("[BluraySubtitle][SETUP] " + translate_text(template, self.args.language).format(**values), flush=True)

    def download(self, url, destination, digest=""):
        expected = digest.removeprefix("sha256:")
        if destination.is_file() and (not expected or sha256(destination) == expected):
            return destination
        destination.parent.mkdir(parents=True, exist_ok=True)
        partial = destination.with_name(destination.name + ".part")
        for attempt in range(3):
            try:
                with self.http.open(url, timeout=120) as response, partial.open("wb") as output:
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

    def github(self, url, *, missing_ok=False):
        if url not in self.json_cache:
            try:
                with self.http.open(url, timeout=90) as response:
                    self.json_cache[url] = json.load(response)
            except urllib.error.HTTPError as error:
                if not missing_ok or error.code != 404:
                    raise
                self.json_cache[url] = None
        return self.json_cache[url]

    def release(self, component):
        suffix = "tags/" + urllib.parse.quote(component.ref, safe="") if component.ref else "latest"
        return self.github(f"https://api.github.com/repos/{component.repository}/releases/{suffix}", missing_ok=True)

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
        archive = self.download(f"https://github.com/{component.repository}/archive/{ref}.zip", parent / "source.zip")
        directories = [path for path in self.unpack(archive, parent / "unpacked").iterdir() if path.is_dir()]
        if len(directories) != 1:
            raise RuntimeError(f"Unexpected source archive layout: {archive}")
        return directories[0]

    @staticmethod
    def posix(path):
        value = path.resolve().as_posix()
        return "/" + value[0].lower() + value[2:]

    def run_msys(self, commands, directory):
        script = "\n".join([
            "set -euo pipefail", "export PATH=/ucrt64/bin:/usr/bin:$PATH",
            "export PKG_CONFIG_PATH=" + shlex.quote(self.posix(self.sdk / "lib/pkgconfig")),
            "export LDFLAGS='-static-libgcc -static-libstdc++'",
            "cd " + shlex.quote(self.posix(directory)), *commands, "",
        ])
        path = self.work / "run-build.sh"
        path.write_text(script, encoding="utf-8", newline="\n")
        subprocess.run([str(self.args.msys2_root / "usr/bin/bash.exe"), "--noprofile", "--norc", self.posix(path)], check=True)

    def ensure_packages(self, *names):
        self.used_packages.update(names)
        packages = ["mingw-w64-ucrt-x86_64-" + name for name in names if name not in self.package_checked]
        if packages:
            self.run_msys(["pacman --noconfirm --needed -S " + " ".join(map(shlex.quote, packages))], self.work)
            self.package_checked.update(names)

    def prepare_sdk(self):
        include = self.sdk / "include/vapoursynth"
        if not (include / "VSConstants4.h").is_file():
            version = (self.runtime / "vapoursynth-classic-version.txt").read_text(encoding="utf-8-sig").strip()
            major, minor = version.split(".", 1)
            source = self.source(Component("sdk", "AmusementClub/vapoursynth-classic", "", "", ""), f"R{major}.A{minor}")
            include.mkdir(parents=True, exist_ok=True)
            for header in (source / "include").glob("*.h"):
                shutil.copyfile(header, include / header.name)
        pc = self.sdk / "lib/pkgconfig/vapoursynth.pc"
        pc.parent.mkdir(parents=True, exist_ok=True)
        pc.write_text("prefix=" + self.sdk.as_posix() + "\nlibdir=$" + "{prefix}/lib64\nincludedir=$"
                      + "{prefix}/include/vapoursynth\nName: VapourSynth\nDescription: VapourSynth Classic plugin headers\n"
                      + "Version: 57\nCflags: -I$" + "{includedir}\n", encoding="utf-8", newline="\n")

    def prepare_fftw(self):
        # DFTTest's Windows ABI expects the thread-safe planner in the same DLL.
        prefix = self.work / "fftw/prefix"
        if not (prefix / "bin/libfftw3f-3.dll").is_file():
            archive = self.download("https://fftw.org/fftw-3.3.11.tar.gz", self.work / "fftw/fftw.tar.gz")
            source = self.unpack(archive, self.work / "fftw/source") / "fftw-3.3.11"
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
                "cmake -S . -B cmake-build -G Ninja -DCMAKE_POLICY_VERSION_MINIMUM=3.5 -DCMAKE_BUILD_TYPE=Release "
                + "-DCMAKE_INSTALL_PREFIX=" + shlex.quote(self.posix(prefix))
                + " -DENABLE_FLOAT=ON -DENABLE_THREADS=ON -DWITH_COMBINED_THREADS=ON -DENABLE_SSE2=ON "
                + "-DENABLE_AVX=ON -DENABLE_AVX2=ON -DDISABLE_FORTRAN=ON -DBUILD_TESTS=OFF",
                "cmake --build cmake-build --parallel " + str(self.args.jobs),
                "cmake --install cmake-build",
            ], source)
        return prefix

    def probe(self, binary, component, target=None):
        folders = [binary.parent, self.runtime, self.runtime / "vapoursynth64/plugins",
                   self.runtime / "vapoursynth64/coreplugins"]
        result = subprocess.run([sys.executable, "-c", PROBE, str(binary), component.key, json.dumps(list(map(str, folders))),
                                 str(Path(__file__).resolve().parent), target or component.ref],
                                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
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
                if installed:
                    candidates.append(self.runtime / name)
                candidates += [self.work / "fftw/prefix/bin" / name, self.args.msys2_root / "ucrt64/bin" / name]
                dependency = next((path for path in candidates if path.is_file() and path != binary), None)
                if dependency is None:
                    continue
                target = stage / name
                if dependency.resolve() != target.resolve():
                    shutil.copyfile(dependency, target)
                copied[key] = target
                pending.append(target)
                if dependency.parent.resolve() == (self.args.msys2_root / "ucrt64/bin").resolve():
                    msys_libraries.append("/ucrt64/bin/" + dependency.name)
        if msys_libraries:
            result = subprocess.run([str(self.args.msys2_root / "usr/bin/pacman.exe"), "-Qqo", *msys_libraries],
                                    check=True, capture_output=True, text=True, encoding="utf-8")
            self.used_packages.update(name.removeprefix("mingw-w64-ucrt-x86_64-") for name in result.stdout.splitlines())
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
        for name in self.used_packages | {"gcc-libs", "mingw-w64-crt"}:
            directory = self.args.msys2_root / "ucrt64/share/licenses" / name
            if directory.is_dir():
                for path in directory.rglob("*"):
                    if path.is_file():
                        target = destination / "dependencies" / name / path.relative_to(directory)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(path, target)
                        collected[target.relative_to(self.runtime).as_posix()] = sha256(target)
        if self.used_packages:
            packages = ["mingw-w64-ucrt-x86_64-" + name for name in sorted(self.used_packages)]
            result = subprocess.run([str(self.args.msys2_root / "usr/bin/pacman.exe"), "-Ql", *packages],
                                    check=True, capture_output=True, text=True, encoding="utf-8")
            for line in result.stdout.splitlines():
                package_name, _, relative = line.partition(" ")
                if "/share/licenses/" not in relative:
                    continue
                path = self.args.msys2_root / relative.lstrip("/")
                if path.is_file():
                    target = destination / "dependencies" / package_name.removeprefix("mingw-w64-ucrt-x86_64-") / path.name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(path, target)
                    collected[target.relative_to(self.runtime).as_posix()] = sha256(target)
        if component.key == "dfttest":
            source_license = self.work / "fftw/source/fftw-3.3.11/COPYING"
            if source_license.is_file():
                target = destination / "dependencies/fftw/COPYING"
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source_license, target)
                collected[target.relative_to(self.runtime).as_posix()] = sha256(target)
        if component.key == "assrender":
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
        # MSYS2's static .pc files omit several transitive shader libraries.
        # Keep these build-local corrections out of the shared toolchain.
        directory = self.work / "placebo/static-pc"
        directory.mkdir(parents=True, exist_ok=True)
        prefix = self.args.msys2_root / "ucrt64"
        for name in ("libplacebo", "shaderc_combined", "spirv-cross-c", "vulkan"):
            text = (prefix / "lib/pkgconfig" / (name + ".pc")).read_text(encoding="utf-8")
            text = text.replace("prefix=/ucrt64", "prefix=" + prefix.as_posix())
            if name == "libplacebo":
                text = text.replace("shaderc >=", "shaderc_combined >=").replace("spirv-cross-c-shared >=", "spirv-cross-c >=")
            elif name == "shaderc_combined":
                text += "\nLibs.private: -lglslang -lSPIRV-Tools-opt -lSPIRV-Tools\n"
            elif name == "spirv-cross-c":
                text += "\nLibs.private: -lspirv-cross-glsl -lspirv-cross-hlsl -lspirv-cross-msl -lspirv-cross-cpp -lspirv-cross-reflect -lspirv-cross-util -lspirv-cross-core\n"
            else:
                # The Vulkan loader must remain dynamic to discover GPU drivers.
                text = text.replace("-lvulkan-1", "-Wl,-Bdynamic,-lvulkan-1,-Bstatic")
            (directory / (name + ".pc")).write_text(text, encoding="utf-8", newline="\n")
        return directory

    def build(self, component, source):
        self.prepare_sdk()
        include = self.sdk / "include/vapoursynth"
        build_directory = "build-" + BUILD_PROFILE
        commands = ["export LDFLAGS='-static -static-libgcc -static-libstdc++ -Wl,--gc-sections -s'",
                    "export CFLAGS='-ffunction-sections -fdata-sections'",
                    "export CXXFLAGS='-ffunction-sections -fdata-sections'"]
        if component.key == "eedi3m":
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
            path = source / "meson.build"
            text = path.read_text(encoding="utf-8")
            path.write_text(re.sub(r"^static_deps = .*", "static_deps = true", text, flags=re.M), encoding="utf-8")
        elif component.key == "assrender":
            self.ensure_packages("libass")
        elif component.key == "sangnom":
            path = source / "src/SangNom.cpp"
            text = path.read_text(encoding="utf-8")
            registration = next(line for line in text.splitlines() if 'registerFunc("SangNomMod",' in line)
            if 'registerFunc("SangNom",' not in text:
                text = text.replace(registration, registration + "\n" + registration.replace('"SangNomMod"', '"SangNom"'))
            path.write_text(text, encoding="utf-8")
        elif component.key == "nlm_ispc":
            release = self.github("https://api.github.com/repos/ispc/ispc/releases/tags/v1.31.0")
            asset = next(item for item in release["assets"] if re.search(r"windows[.]zip$", item["name"]))
            archive = self.download(asset["browser_download_url"], self.work / "ispc" / asset["name"], asset.get("digest") or "")
            executable = next(self.unpack(archive, self.work / "ispc/unpacked").rglob("ispc.exe"))
            shutil.copyfile(executable, self.args.msys2_root / "ucrt64/bin/ispc.exe")
        jobs = str(self.args.jobs)
        if component.recipe == "meson":
            options = ["-Dprefer_static=true", "-Db_lto=true", "-Db_lto_threads=" + jobs]
            if component.key == "descale":
                options += ["-Dlibtype=vapoursynth", f"-Dc_args=-I{include.as_posix()}", f"-Dcpp_args=-I{include.as_posix()}"]
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
            commands += ["./configure --host=x86_64-w64-mingw32 --disable-static --enable-shared", "make -j" + jobs]
            self.run_msys(["export LDFLAGS='-static -static-libgcc -static-libstdc++ -Wl,--gc-sections -s'"] + commands, directory)
        elif component.recipe == "configure":
            self.run_msys(commands + ["./configure --gcc --target-os=mingw --target=sse2 --extra-cxxflags="
                           + shlex.quote("-I" + include.parent.as_posix())
                           + " --extra-ldflags='-static -static-libgcc -static-libstdc++ -Wl,--gc-sections -s'", "make -j" + jobs], source)
        elif component.recipe == "removegrain":
            objects = [name + ".o" for name in ("clense", "removegrainvs", "repairvs", "shared", "verticalcleaner")]
            makefile = "CXXFLAGS = -O3 -std=c++11 -DVS_TARGET_CPU_X86 -I" + shlex.quote(include.as_posix()) + "\n"
            makefile += "RemoveGrainVS.dll: " + " ".join(objects) + "\n\t$(CXX) -shared $(LDFLAGS) -o $@ $^\n"
            makefile += "%.o: src/%.cpp Makefile\n\t$(CXX) $(CXXFLAGS) -c -o $@ $<\n"
            (source / "Makefile").write_text(makefile, encoding="utf-8", newline="\n")
            self.run_msys(commands + ["make -j" + jobs], source)
        elif component.recipe == "lsmash":
            self.ensure_packages("ffmpeg")
            library = self.source(Component("l-smash-library", "l-smash/l-smash", "", "", ""), "master")
            self.run_msys(["./configure --prefix=/ucrt64 --disable-shared --enable-static", "make -j" + jobs, "make install"], library)
            path = source / "common/libavsmash.c"
            text = path.read_text(encoding="utf-8")
            text = text.replace("        ELSE_IF_GET_CODEC_ID_FROM_CODEC_TYPE(AV_CODEC_ID_V410, QT_CODEC_TYPE_V410_VIDEO);\n", "")
            path.write_text(text, encoding="utf-8")
            self.run_msys(["meson setup build --buildtype=release -Dprefer_static=true", "meson compile -C build -j " + jobs], source / "VapourSynth")
        elif component.recipe == "zig":
            # The 0.7 source uses Zig 0.12's Build API.
            archive = self.download("https://ziglang.org/download/0.12.0/zig-windows-x86_64-0.12.0.zip", self.work / "zig/zig.zip")
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
            subprocess.run([str(executable), "build", "-j" + jobs, "-Doptimize=ReleaseFast", "-Dtarget=x86_64-windows-gnu", "-Dcpu=baseline"], cwd=source, check=True)
        else:
            raise RuntimeError(f"Unsupported source recipe: {component.recipe}")
        names = {component.filename.lower(), "lib" + component.filename.lower()}
        if component.key == "removegrain":
            names |= {"libremovegrain.dll", "removegrain.dll"}
        if component.key == "sangnom":
            names.add("libvs_sangnommod.dll")
        output = source / build_directory if component.recipe in ("meson", "cmake") else source
        candidates = [path for path in output.rglob("*.dll") if path.name.lower() in names and pe64(path)]
        if not candidates:
            raise RuntimeError(f"No built x64 plugin found for {component.key}")
        binary = sorted(candidates, key=lambda path: len(path.parts))[0]
        subprocess.run([str(self.args.msys2_root / "ucrt64/bin/strip.exe"), "--strip-unneeded", str(binary)], check=True)
        return binary

    def install_plugin(self, component):
        self.used_packages = set()
        self.source_dependencies = []
        previous = self.state["components"].get(component.key)
        release = self.release(component) if not component.ref else None
        target_ref = component.ref or release["tag_name"]
        folder = self.runtime / "vapoursynth64" / ("coreplugins" if component.key == "removegrain" else "plugins")
        target = folder / component.filename
        relative = target.relative_to(self.runtime).as_posix()
        known_file = bool(previous and target.is_file() and previous["files"].get(relative) == sha256(target))
        expected = ("commit:" + component.fallback_ref if previous and previous["method"] == "source" and component.fallback_ref
                    else target_ref)
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
                    installed = "commit:" + previous["ref"] if component.fallback_ref and previous["method"] == "source" else normalize_version(previous["ref"])
                if installed is not None:
                    record_version(target, installed, probe["native_version"])
        rebuild = bool(known_file and previous["method"] == "source" and previous.get("target_ref", previous["ref"]) == target_ref
                       and previous.get("build_profile") != BUILD_PROFILE)
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
                source = self.source(component, component.fallback_ref or target_ref)
                files = {relative: sha256(target), **self.licenses(component, source)}
                previous = {
                    "name": component.key, "repository": component.repository, "target_ref": target_ref,
                    "ref": installed, "method": "existing", "source_url": f"https://github.com/{component.repository}",
                    "license_source_ref": component.fallback_ref or target_ref, "artifact_url": "", "plugin": relative,
                    "files": files, "dependencies": dependency_names, "source_dependencies": self.source_dependencies,
                }
                self.state["components"][component.key] = previous
            previous.update(installed_version=installed, registered_version=probe["version"])
            self.save()
            self.log("VapourSynth plugin meets the required version: {name} {installed} >= {target}",
                     name=component.key, installed=installed, target=expected)
            return
        if rebuild:
            self.log("Rebuilding VapourSynth plugin with updated link options: {name}", name=component.key)
        else:
            self.log("VapourSynth plugin needs installation or update: {name} {installed} -> {target}",
                     name=component.key, installed=installed or "?", target=expected)
        release = release if release is not None else self.release(component)
        self.log("Installing VapourSynth component: {name} {version}", name=component.key, version=target_ref)
        if component.key == "dfttest":
            self.prepare_fftw()
        package, artifact, binary = None, None, None
        if release:
            assets = [item for item in release["assets"] if component.asset and re.search(component.asset, item["name"], re.I)]
            if component.key == "zsmooth":
                import numpy as np
                if not np._core._multiarray_umath.__cpu_features__.get("AVX2"):
                    assets = []
            if assets:
                artifact = assets[0]
                archive = self.download(artifact["browser_download_url"], self.work / component.key / artifact["name"], artifact.get("digest") or "")
                package = self.unpack(archive, self.work / component.key / ("release-" + archive.stem))
                names = {component.filename.lower()} | ({"lsmashsource.dll"} if component.key == "lsmas" else set())
                if component.key == "zsmooth":
                    names.add("zsmooth.avx2.dll")
                candidates = [path for path in package.rglob("*.dll") if path.name.lower() in names and pe64(path)]
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
        ref = target_ref if binary else component.fallback_ref or target_ref
        source = self.source(component, ref)
        if binary is None:
            self.log("Building VapourSynth component from source: {name} {version}", name=component.key, version=ref)
            binary = self.build(component, source)
        stage = self.work / component.key / "staged"
        stage.mkdir(parents=True, exist_ok=True)
        staged_binary = stage / component.filename
        shutil.copyfile(binary, staged_binary)
        dependencies = self.dependencies(binary, stage)
        expected = "commit:" + ref if method == "source" and component.fallback_ref else target_ref
        probe = self.probe(staged_binary, component, expected)
        folder.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(staged_binary, target)
        record_version(target, expected, probe["native_version"])
        dependency_names = []
        for dependency in dependencies:
            installed = self.runtime / dependency.name
            shutil.copyfile(dependency, installed)
            relative = installed.relative_to(self.runtime).as_posix()
            self.state["dependencies"][relative] = sha256(installed)
            dependency_names.append(relative)
        files = {target.relative_to(self.runtime).as_posix(): sha256(target)}
        files.update(self.licenses(component, source, package))
        self.state["components"][component.key] = {
            "name": component.key, "repository": component.repository, "target_ref": target_ref, "ref": ref, "method": method,
            "source_url": f"https://github.com/{component.repository}/tree/{ref}",
            "artifact_url": artifact["browser_download_url"] if method == "release" else "",
            "plugin": target.relative_to(self.runtime).as_posix(), "registered_version": probe["version"],
            "installed_version": probe["native_version"] or normalize_version(expected),
            "build_profile": BUILD_PROFILE if method == "source" else "",
            "files": files, "dependencies": dependency_names,
            "source_dependencies": self.source_dependencies + ([{"name": "FFTW", "version": "3.3.11", "source_url": "https://fftw.org/fftw-3.3.11.tar.gz"}]
                                   if component.key in ("dfttest", "mvtools") else []),
        }
        self.save()

    def install_editor(self):
        self.used_packages = set()
        release = self.release(EDITOR)
        ref = release["tag_name"]
        if self.valid(self.state["components"].get("vsedit"), ref):
            self.configure_editor()
            self.editor_metadata(self.state["components"]["vsedit"])
            self.save()
            self.log("VapourSynth component is current: {name} {version}", name="VSEdit", version=ref)
            return
        self.log("Installing VapourSynth component: {name} {version}", name="VSEdit", version=ref)
        assets = [item for item in release["assets"] if re.search(EDITOR.asset, item["name"], re.I)]
        source = self.source(EDITOR, ref)
        package, directory, method = None, None, "source"
        for artifact in assets:
            archive = self.download(artifact["browser_download_url"], self.work / "vsedit" / artifact["name"], artifact.get("digest") or "")
            package = self.unpack(archive, self.work / "vsedit" / ("release-" + archive.stem))
            executable = next((path for path in package.rglob("vsedit.exe") if pe64(path)), None)
            if executable is None:
                continue
            try:
                version = subprocess.run([str(executable), "--version"], capture_output=True, text=True,
                                         encoding="utf-8", errors="replace", timeout=30, check=True)
                if ref not in version.stdout + version.stderr:
                    continue
            except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
                self.log("Release binary is incompatible; trying source: {name}: {detail}", name="VSEdit", detail=str(error))
                continue
            directory, method = executable.parent, "release"
            break
        if directory is None:
            package = None
            self.prepare_sdk()
            self.ensure_packages("qt6-base", "qt6-5compat", "qt6-websockets", "qt6-multimedia")
            include = (self.sdk / "include/vapoursynth").as_posix()
            for project in (source / "pro").rglob("*.pro"):
                text = project.read_text(encoding="utf-8")
                text = text.replace("QMAKE_LFLAGS += '/entry:mainCRTStartup'", "win32-msvc: QMAKE_LFLAGS += /entry:mainCRTStartup")
                project.write_text(text.replace("DEPLOY_COMMAND = windeployqt\n", "DEPLOY_COMMAND = windeployqt6\n"), encoding="utf-8")
            self.run_msys([f"export VS_INCLUDE_PATH={shlex.quote(include)}", "cd pro", "qmake6 -norecursive pro.pro CONFIG+=release", "make -j" + str(self.args.jobs)], source)
            executable = next(source.rglob("vsedit.exe"))
            directory = executable.parent
            self.run_msys(["windeployqt6 --release --no-translations " + shlex.quote(executable.as_posix())], directory)
        destination = self.runtime / "vsedit"
        destination.mkdir(parents=True, exist_ok=True)
        files = {}
        for path in directory.rglob("*"):
            if not path.is_file() or path.suffix.lower() in (".pdb", ".lib", ".exp") or path.name in ("vsedit.config", ".unpacked"):
                continue
            target = destination / path.relative_to(directory)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
            files[target.relative_to(self.runtime).as_posix()] = sha256(target)
        self.configure_editor()
        version = subprocess.run([str(destination / "vsedit.exe"), "--version"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30, check=True)
        if ref not in version.stdout + version.stderr:
            raise RuntimeError("VSEdit release version verification failed")
        files.update(self.licenses(EDITOR, source, package))
        qt_licenses = self.runtime / "licenses/components/vsedit/Qt"
        qt_licenses.mkdir(parents=True, exist_ok=True)
        for name in ("LGPL-3.0-only.txt", "GPL-3.0-only.txt"):
            target = self.download("https://raw.githubusercontent.com/qt/qtbase/dev/LICENSES/" + name, qt_licenses / name)
            files[target.relative_to(self.runtime).as_posix()] = sha256(target)
        self.state["components"]["vsedit"] = {
            "name": "VapourSynth Editor", "repository": EDITOR.repository, "ref": ref, "method": method,
            "source_url": f"https://github.com/{EDITOR.repository}/tree/{ref}",
            "artifact_url": artifact["browser_download_url"] if method == "release" else "",
            "entrypoint": "vsedit/vsedit.exe", "files": files, "dependencies": [],
        }
        self.editor_metadata(self.state["components"]["vsedit"])
        self.save()

    def configure_editor(self):
        config = self.runtime / "vsedit/vsedit.config"
        if not config.exists() and (self.runtime / "vsedit.config").is_file():
            shutil.copyfile(self.runtime / "vsedit.config", config)
        settings = configparser.ConfigParser(interpolation=None, strict=False)
        settings.optionxform = str
        if config.exists():
            settings.read(config, encoding="utf-8-sig")
        if not settings.has_section("common"):
            settings.add_section("common")
        settings["common"]["prefer_vs_libs_from_list"] = "false"
        settings["common"]["vapoursynth_library_paths"] = "../"
        settings["common"]["vapoursynth_plugins_paths"] = "../vapoursynth64/coreplugins, ../vapoursynth64/plugins"
        with config.open("w", encoding="utf-8", newline="\r\n") as output:
            settings.write(output, space_around_delimiters=False)

    def editor_metadata(self, record):
        version = file_version(self.runtime / "vsedit/Qt6Core.dll")
        record["qt_version"] = version
        series = ".".join(version.split(".")[:2])
        record["qt_source_url"] = f"https://download.qt.io/official_releases/qt/{series}/{version}/single/qt-everywhere-src-{version}.tar.xz"

    def install(self):
        for component in COMPONENTS:
            self.install_plugin(component)
        self.install_editor()
        required = {name for record in self.state["components"].values() for name in record.get("dependencies", ())}
        self.state["dependencies"] = {name: digest for name, digest in self.state["dependencies"].items() if name in required}
        self.save()
        for component in COMPONENTS:
            record = self.state["components"][component.key]
            self.probe(self.runtime / record["plugin"], component, record.get("target_ref", record["ref"]))
        self.log("Independent VapourSynth components verified: {count}", count=len(self.state["components"]))


def main():
    import errno
    import msvcrt

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", required=True, type=Path)
    parser.add_argument("--work-root", required=True, type=Path)
    parser.add_argument("--msys2-root", type=Path, default=Path(r"C:\msys64"))
    parser.add_argument("--seven-zip", default=r"C:\Program Files\7-Zip\7z.exe")
    parser.add_argument("--jobs", type=int, default=os.cpu_count() or 1)
    parser.add_argument("--language", choices=("en", "zh"), default="en")
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
            Installer(args).install()
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
