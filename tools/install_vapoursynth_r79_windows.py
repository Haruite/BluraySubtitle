"""Install Windows VapourSynth R79 at the configured VSPipe location."""

import argparse
import ctypes
from importlib.metadata import PackageNotFoundError, distribution
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.windows_native_tools import PE_ARM64, runtime_dependencies, windows_machine


ARM64_RECIPE = 2
WINDOWS_CPU_DETECTION = r'''#elif defined(_WIN32)
#include <windows.h>

static bool haveWindowsFhm() {
    // Windows exposes FP16 arithmetic separately from the widening FMLAL instructions.
    HKEY processors;
    if (RegOpenKeyExW(HKEY_LOCAL_MACHINE, L"HARDWARE\\DESCRIPTION\\System\\CentralProcessor",
                      0, KEY_READ, &processors) != ERROR_SUCCESS)
        return false;
    DWORD index = 0;
    LONG status;
    for (;; ++index) {
        wchar_t name[32];
        DWORD nameLength = ARRAYSIZE(name);
        status = RegEnumKeyExW(processors, index, name, &nameLength, nullptr, nullptr, nullptr, nullptr);
        if (status != ERROR_SUCCESS)
            break;
        ULONGLONG isar0 = 0;
        DWORD size = sizeof(isar0);
        // CP 4030 holds ID_AA64ISAR0_EL1, with FHM in bits 51:48.
        status = RegGetValueW(processors, name, L"CP 4030", RRF_RT_REG_QWORD, nullptr, &isar0, &size);
        if (status != ERROR_SUCCESS || ((isar0 >> 48) & 0xf) != 1) {
            RegCloseKey(processors);
            return false;
        }
    }
    RegCloseKey(processors);
    return status == ERROR_NO_MORE_ITEMS && index > 0 &&
           index >= GetActiveProcessorCount(ALL_PROCESSOR_GROUPS);
}

static void doGetCPUFeatures(CPUFeatures *cpuFeatures) {
    *cpuFeatures = {};
    cpuFeatures->can_run_vs = 1;
    // Values from the Windows SDK; older MinGW headers omit the names.
    cpuFeatures->dotprod = !!IsProcessorFeaturePresent(43); // PF_ARM_V82_DP_INSTRUCTIONS_AVAILABLE
    cpuFeatures->i8mm = !!IsProcessorFeaturePresent(66); // PF_ARM_V82_I8MM_INSTRUCTIONS_AVAILABLE
    cpuFeatures->fp16 = !!IsProcessorFeaturePresent(67); // PF_ARM_V82_FP16_INSTRUCTIONS_AVAILABLE
    cpuFeatures->fhm = cpuFeatures->fp16 && haveWindowsFhm();
}

'''


def patch_arm64_source(source: Path) -> None:
    # Preserve the public DLL name when building with the MinGW linker.
    meson = source / "meson.build"
    text = meson.read_text(encoding="utf-8")
    before, separator, after = text.partition("libvsscript = library('vsscript',")
    if not separator:
        raise RuntimeError("Cannot find the R79 VSScript build target")
    name_option = "    name_prefix: '',"
    target_end = after.index("\n)")
    if name_option not in after[:target_end]:
        meson.write_text(before + separator + after[:target_end] + "\n" + name_option + after[target_end:],
                         encoding="utf-8", newline="\r\n")
    cpu = source / "src/core/cpufeatures.cpp"
    text = cpu.read_text(encoding="utf-8")
    if "static bool haveWindowsFhm()" not in text:
        marker = "#elif defined(__linux__)\n#include <sys/auxv.h>"
        if marker not in text:
            raise RuntimeError("Cannot find the R79 AArch64 CPU detection code")
        cpu.write_text(text.replace(marker, WINDOWS_CPU_DETECTION + marker, 1),
                       encoding="utf-8", newline="\r\n")
    expr = source / "src/core/exprfilter.cpp"
    text = expr.read_text(encoding="utf-8")
    if "#include <exception>" not in text:
        expr.write_text("#include <exception>\n" + text, encoding="utf-8", newline="\r\n")


def build_arm64_wheel(source: Path, msys2: Path, proxy: str, jobs: int) -> Path:
    patch_arm64_source(source)
    compiler = msys2 / "clangarm64/bin"
    tool_directory = source.parent
    environment = dict(os.environ, CC=str(compiler / "clang.exe"), CXX=str(compiler / "clang++.exe"),
                       PKG_CONFIG=str(compiler / "pkg-config.exe"))
    archiver = compiler / "llvm-ar.exe"
    environment["AR"] = str(archiver)
    pip_options = ["--proxy", proxy] if proxy else []
    venv = tool_directory / "venv"
    subprocess.run([sys.executable, "-m", "venv", venv], check=True)
    python = venv / "Scripts/python.exe"
    subprocess.run([python, "-m", "pip", "install", "--disable-pip-version-check", "--only-binary=:all:",
                    *pip_options, "Cython>=3.1", "meson", "meson-python"], check=True)
    environment["PATH"] = os.pathsep.join(map(str, (python.parent, compiler, msys2 / "usr/bin",
                                                  environment.get("PATH", ""))))
    output = tool_directory / "wheels"
    subprocess.run([python, "-m", "pip", "wheel", "--no-build-isolation", "--no-deps", *pip_options,
                    "-Csetup-args=-Denable_arm_asm=true", "-Csetup-args=-Denable_x86_asm=false",
                    "-Csetup-args=--wrap-mode=nodownload", "-Csetup-args=--force-fallback-for=zimg,libp2p",
                    f"-Ccompile-args=-j{jobs}", "-w", output, source],
                   env=environment, check=True)
    return next(output.glob("*-win_arm64.whl"))


def check(vspipe: Path) -> None:
    root = vspipe.parent
    # Inspect the core before plugin migration. Old third-party DLLs may be incompatible.
    os.environ["VAPOURSYNTH_EXTRA_PLUGIN_PATH"] = ""
    import vapoursynth as vs

    state = json.loads((root / "vapoursynth-build.json").read_text(encoding="utf-8"))
    sdk = root / "sdk/include/vapoursynth"
    if not all((sdk / name).is_file() for name in ("VapourSynth.h", "VapourSynth4.h", "VSScript4.h", "VSHelper4.h")):
        raise RuntimeError("VapourSynth R79 SDK headers are missing")
    if windows_machine() == PE_ARM64:
        package = Path(vs.__file__).parent
        binaries = [vspipe, root / "VSScript.dll", package / "libvapoursynth.dll",
                    package / "libvapoursynthfilters.dll", package / "vapoursynth.pyd"]
        runtime_dependencies(binaries, [package, root, Path(sys.base_prefix)])
        if state.get("arm64_recipe") != ARM64_RECIPE:
            raise RuntimeError("VapourSynth R79 ARM64 binaries do not match the setup build")
    if (state["version"] != "79" or state["python_tag"] != sys.implementation.cache_tag
            or Path(state["python_executable"]) != Path(sys.executable)
            or Path(state["package"]) != Path(vs.__file__).parent
            or vs.core.core_version.release_major != 79):
        raise RuntimeError("VapourSynth R79 does not match the selected Python")
    output = subprocess.check_output([vspipe, "--version"], text=True, stderr=subprocess.STDOUT, timeout=120)
    if "Core R79" not in output.splitlines():
        raise RuntimeError(output.strip())


def install(vspipe: Path, plugins: Path, source: Path | None, proxy: str, *, artifacts: Path | None = None,
            msys2: Path | None = None, jobs: int = 1) -> None:
    arm64 = windows_machine() == PE_ARM64
    if arm64:
        if source is not None:
            if msys2 is None:
                raise RuntimeError("ARM64 VapourSynth requires the MSYS2 CLANGARM64 toolchain")
            artifacts = artifacts or source.parent / "artifacts"
            artifacts.mkdir(parents=True, exist_ok=True)
            wheel_path = build_arm64_wheel(source, msys2, proxy, jobs)
            shutil.copy2(wheel_path, artifacts / wheel_path.name)
        if artifacts is None:
            raise RuntimeError("ARM64 VapourSynth requires a build artifact directory")
        (wheel_path,) = artifacts.glob("vapoursynth-79-*-win_arm64.whl")
        subprocess.run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
                        "--no-deps", "--force-reinstall", wheel_path], check=True)
    try:
        wheel = distribution("VapourSynth")
    except PackageNotFoundError:
        wheel = None
    if wheel is None or wheel.version != "79" or not wheel.locate_file("vapoursynth/vspipe.exe").is_file():
        arguments = ["-m", "pip", "install", "--disable-pip-version-check", "--only-binary=:all:", "VapourSynth==79"]
        if wheel is not None and wheel.version == "79":
            arguments.append("--force-reinstall")
        if proxy:
            arguments += ["--proxy", proxy]
        subprocess.run([sys.executable, *arguments], check=True)
        wheel = distribution("VapourSynth")
    package = Path(wheel.locate_file("vapoursynth"))
    site_packages = package.parent
    root = vspipe.parent
    root.mkdir(parents=True, exist_ok=True)

    # Copy the entry points so existing VSPIPE_PATH settings and editors can find them.
    # The selected Python imports the original wheel and loads its own libvapoursynth.
    for original, target in (
        (package / "vspipe.exe", vspipe),
        (package / "vsscript.dll", root / "VSScript.dll"),
    ):
        if original.resolve() != target.resolve():
            shutil.copy2(original, target)
    include = root / "sdk/include/vapoursynth"
    licenses = root / "licenses"
    include.mkdir(parents=True, exist_ok=True)
    licenses.mkdir(exist_ok=True)
    if arm64:
        runtime = artifacts / "runtime"
        if source is not None:
            compiler = msys2 / "clangarm64"
            compiler_bin = compiler / "bin"
            inputs = [Path(wheel.locate_file(entry)) for entry in wheel.files
                      if entry.parts[0] == "vapoursynth" and entry.suffix.lower() in {".dll", ".pyd", ".exe"}]
            wheel_binaries = {path.name.casefold() for path in inputs}
            dependencies = runtime_dependencies(inputs, [package, compiler_bin, Path(sys.base_prefix)])
            sources = {
                "VapourSynth-COPYING.LESSER": source / "COPYING.LESSER",
                "libp2p-COPYING": source / "subprojects/libp2p/COPYING",
                "zimg-COPYING": source / "subprojects/zimg/COPYING",
                "graphengine-COPYING": source / "subprojects/zimg/graphengine/COPYING",
            }
            runtime.mkdir(exist_ok=True)
            for path in dependencies.values():
                if path.parent in (package, compiler_bin) and path.name.casefold() not in wheel_binaries:
                    shutil.copy2(path, runtime / path.name)
                    license_file = compiler / "share/licenses" / path.stem / "LICENSE"
                    if license_file.is_file():
                        sources[f"{path.stem}-LICENSE"] = license_file
            shutil.copytree(source / "include", artifacts / "include", dirs_exist_ok=True)
            cache_licenses = artifacts / "licenses"
            cache_licenses.mkdir(exist_ok=True)
            for name, path in sources.items():
                shutil.copy2(path, cache_licenses / name)
        # VSPipe imports VSScript before Python or any .pth hooks are active.
        for path in runtime.glob("*.dll"):
            shutil.copy2(path, package / path.name)
            shutil.copy2(path, root / path.name)
        shutil.copytree(artifacts / "licenses", licenses, dirs_exist_ok=True)
        (root / "python-runtime.ini").unlink(missing_ok=True)
        (root / "vapoursynth-classic-version.txt").unlink(missing_ok=True)
        sdk = artifacts / "include"
    else:
        shutil.copy2(source / "COPYING.LESSER", licenses / "VapourSynth-COPYING.LESSER")
        sdk = source / "include"
    for header in sdk.glob("*.h"):
        shutil.copy2(header, include / header.name)

    # R79's native plugin loader uses AddDllDirectory for DLLs outside the plugin folder.
    (site_packages / "vapoursynth_runtime.py").write_text(
        "import os\nimport sys\n"
        f"_dll_directory = os.add_dll_directory({str(root)!r})\n"
        f"os.environ.setdefault('VAPOURSYNTH_EXTRA_PLUGIN_PATH', {str(plugins)!r})\n"
        f"sys.path.append({str(root / 'Lib/site-packages')!r})\n",
        encoding="utf-8", newline="\r\n",
    )
    (site_packages / "vapoursynth-runtime.pth").write_text(
        "import vapoursynth_runtime\n", encoding="utf-8", newline="\r\n",
    )

    # Register the copied VSScript under its own key and retain other installations.
    # Run in a new process so the .pth hook is active during the runtime check.
    environment = dict(os.environ, VAPOURSYNTH_EXTRA_PLUGIN_PATH="")
    configuration = (
        "from vapoursynth import _utils; import sys; "
        # The MSVC probe is specific to the upstream Windows wheel.
        + ("_utils._check_visual_studio_runtime = lambda: None; " if arm64 else "")
    )
    if package.resolve() != root.resolve():
        configure_copy = (
            configuration + "_utils.get_vsscript = lambda: sys.argv[1]; "
            "_utils._has_implicit_config = lambda: False; _utils.vapoursynth_config()"
        )
        subprocess.run([sys.executable, "-I", "-c", configure_copy, str(root / "VSScript.dll")],
                       check=True, env=environment, timeout=30)
    subprocess.run([sys.executable, "-I", "-c", configuration + "_utils.vapoursynth_config()"],
                   check=True, env=environment, timeout=30)
    state = {
        "version": wheel.version,
        "python_executable": sys.executable,
        "python_tag": sys.implementation.cache_tag,
        "python_library": sysconfig.get_config_var("LDLIBRARY"),
        "package": str(package),
    }
    if arm64:
        state["arm64_recipe"] = ARM64_RECIPE
    marker = root / "vapoursynth-build.json"
    pending = marker.with_suffix(".json.part")
    pending.write_text(json.dumps(state, indent=2), encoding="utf-8", newline="\r\n")
    pending.replace(marker)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("vspipe", type=Path)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--plugins", type=Path)
    parser.add_argument("--proxy", default="")
    parser.add_argument("--artifacts", type=Path)
    parser.add_argument("--msys2-root", type=Path)
    parser.add_argument("--jobs", type=int, default=os.cpu_count() or 1)
    args = parser.parse_args()
    # Report broken binaries through the setup log instead of waiting on a loader dialog.
    ctypes.windll.kernel32.SetErrorMode(0x8003)
    vspipe = args.vspipe.resolve()
    if args.source or args.artifacts:
        if not args.plugins or (args.source is None and windows_machine() != PE_ARM64):
            parser.error("R79 installation requires --plugins and a source or ARM64 artifacts")
        install(vspipe, args.plugins.resolve(), args.source.resolve() if args.source else None, args.proxy, artifacts=args.artifacts,
                msys2=args.msys2_root, jobs=args.jobs)
    else:
        check(vspipe)


if __name__ == "__main__":
    main()
