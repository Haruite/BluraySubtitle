"""Build VapourSynth Classic and its Python binding for the running CPython."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig
import textwrap


def replace_source(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8-sig")
    if new in text:
        return
    if text.count(old) != 1:
        raise RuntimeError(f"Unexpected upstream source layout: {path}")
    path.write_text(text.replace(old, new), encoding="utf-8", newline="\r\n")


def patch_python_runtime(source: Path, python_library: str) -> None:
    """Use one configured Python home for VSPipe and VSEdit on Windows."""
    cpp = source / "src/vsscript/vsscript.cpp"
    text = cpp.read_text(encoding="utf-8")
    start = text.index("static std::wstring getPyPath(")
    end = text.index("#endif // _MSC_VER", start)
    get_path = r'''static std::wstring getPyPath(bool *isolated = nullptr) VS_NOEXCEPT {
    HMODULE module;
    GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS, (LPCWSTR)&getPyPath, &module);
    std::vector<wchar_t> buffer(65536);
    GetModuleFileNameW(module, buffer.data(), (DWORD)buffer.size());
    std::wstring directory = buffer.data();
    directory.resize(directory.find_last_of(L'\\') + 1);
    const std::wstring configuration = directory + L"python-runtime.ini";
    if (isolated)
        *isolated = GetPrivateProfileIntW(L"Python", L"Isolated", 0, configuration.c_str()) != 0;
    GetPrivateProfileStringW(L"Python", L"Home", L"", buffer.data(), (DWORD)buffer.size(), configuration.c_str());
    std::wstring home = buffer.data();
    if (home.empty())
        return directory;
    if (home.size() < 2 || (home[1] != L':' && home[0] != L'\\'))
        home = directory + home;
    GetFullPathNameW(home.c_str(), (DWORD)buffer.size(), buffer.data(), nullptr);
    return buffer.data();
}
'''
    text = text[:start] + get_path + text[end:]
    start = text.index("        const std::vector<std::wstring> pythonDllNames {")
    end = text.index(";", start) + 1
    text = text[:start] + (
        f'        const std::vector<std::wstring> pythonDllNames {{ L"{python_library}" }};'
    ) + text[end:]
    start = text.index("    if (!preInitialized)", text.index("static void real_init"))
    end = text.index("    s = PyGILState_Ensure();", start)
    initialization = '''    if (!preInitialized) {
#ifdef _MSC_VER
        PyConfig config;
        PyConfig_InitPythonConfig(&config);
        config.install_signal_handlers = 0;
        bool isolated = false;
        const std::wstring home = getPyPath(&isolated);
        config.use_environment = !isolated;
        config.user_site_directory = !isolated;
        PyStatus status = PyConfig_SetString(&config, &config.home, home.c_str());
        if (!PyStatus_Exception(status))
            status = PyConfig_SetString(&config, &config.pythonpath_env, home.c_str());
        if (!PyStatus_Exception(status))
            status = Py_InitializeFromConfig(&config);
        if (PyStatus_Exception(status)) {
            fprintf(stderr, "vsscript: Python initialization failed: %s\\n", status.err_msg);
            PyConfig_Clear(&config);
            return;
        }
        PyConfig_Clear(&config);
#else
        Py_InitializeEx(0);
#endif
    }
'''
    cpp.write_text(text[:start] + initialization + text[end:], encoding="utf-8", newline="\r\n")
    replace_source(
        source / "src/cython/vapoursynth.pyx",
        "\ntry:\n    import vsinitrc\n",
        '''
# Cython 3.1 stopped exporting named enum items as module-level constants.
for _enum_name in (
    "MediaType", "ColorFamily", "SampleType", "PresetFormat", "AudioChannels",
    "MessageType", "CoreCreationFlags", "ColorRange", "ChromaLocation",
    "FieldBased", "MatrixCoefficients", "TransferCharacteristics", "ColorPrimaries",
):
    globals().update(globals()[_enum_name].__members__)
del _enum_name

try:
    import vsinitrc
''',
    )


def build_runtime(args: argparse.Namespace) -> Path:
    from setuptools._distutils.compilers.C.msvc import _get_vc_env

    source = args.source.resolve()
    python_library = Path(str(sysconfig.get_config_var("LDLIBRARY"))).name
    patch_python_runtime(source, python_library)

    # R57's old reset options were removed by current mimalloc releases.
    replace_source(
        source / "src/core/vscore.cpp",
        "        mi_option_disable(mi_option_page_reset);\n        mi_option_disable(mi_option_segment_reset);",
        "        mi_option_set(mi_option_purge_delay, -1);",
    )
    environment = os.environ.copy()
    environment.update({key.upper(): value for key, value in _get_vc_env("x64").items()})
    mimalloc_build = source / "mimalloc-build"
    subprocess.run(
        [args.cmake, "-S", str(source / "mimalloc"), "-B", str(mimalloc_build),
         "-G", "Ninja", "-DCMAKE_BUILD_TYPE=Release", "-DMI_BUILD_SHARED=OFF",
         "-DMI_BUILD_STATIC=ON", "-DMI_BUILD_OBJECT=OFF", "-DMI_BUILD_TESTS=OFF",
         "-DMI_OVERRIDE=OFF"],
        env=environment, check=True,
    )
    subprocess.run(
        [args.cmake, "--build", str(mimalloc_build), "--parallel", str(args.jobs)],
        env=environment, check=True,
    )
    allocator_directory = source / "mimalloc/out/msvc-x64/Release"
    allocator_directory.mkdir(parents=True, exist_ok=True)
    shutil.copy2(mimalloc_build / "mimalloc.lib", allocator_directory / "mimalloc-static.lib")

    # Let the installed Visual Studio select its current C++ toolset and SDK.
    for project in source.rglob("*.vcxproj"):
        text = project.read_text(encoding="utf-8-sig")
        text = text.replace("<PlatformToolset>v142</PlatformToolset>",
                            "<PlatformToolset>$(DefaultPlatformToolset)</PlatformToolset>")
        text = text.replace("<PlatformToolset>v143</PlatformToolset>",
                            "<PlatformToolset>$(DefaultPlatformToolset)</PlatformToolset>")
        text = text.replace("C:\\Program Files\\Python39\\include", str(Path(sys.base_prefix) / "include"))
        text = text.replace("C:\\Program Files\\Python39\\libs", str(Path(sys.base_prefix) / "libs"))
        text = text.replace("Python39.dll", python_library)
        if "mimalloc-static.lib;bcrypt.lib;psapi.lib;" not in text:
            text = text.replace("mimalloc-static.lib;", "mimalloc-static.lib;bcrypt.lib;psapi.lib;")
        if text != project.read_text(encoding="utf-8-sig"):
            project.write_text(text, encoding="utf-8", newline="\r\n")
    targets = "VapourSynth;VSScript;VSPipe;RemoveGrainVS;Vinverse;VIVTC;EEDI3;AvsCompat;MiscFilters;Morpho"
    subprocess.run(
        [args.msbuild, str(source / "msvc_project/VapourSynth.sln"), f"/t:{targets}",
         "/p:Configuration=Release", "/p:Platform=x64", f"/m:{args.jobs}",
         "/nologo", "/verbosity:minimal"],
        check=True,
    )
    return source / "msvc_project/x64/Release"


def build_binding(source: Path, binaries: Path, wheel_directory: Path, version: str) -> Path:
    # Keep generated Cython files separate: the upstream VSScript API header
    # intentionally omits data imports incompatible with Windows delay loading.
    build_script = source / "build_python_binding.py"
    build_script.write_text(
        textwrap.dedent(f'''\
            from Cython.Build import cythonize
            from setuptools import Extension, setup
            extension = Extension(
                "vapoursynth", ["src/cython/vapoursynth.pyx"],
                define_macros=[("VS_GRAPH_API", None)],
                libraries=["VapourSynth"], library_dirs=[{str(binaries)!r}],
                include_dirs=[".", "src/cython", "src/vsscript"],
            )
            setup(name="VapourSynth", version={version!r},
                  ext_modules=cythonize([extension], build_dir="build/cython",
                                        compiler_directives={{"language_level": 3}}))
        '''),
        encoding="utf-8", newline="\r\n",
    )
    subprocess.run(
        [sys.executable, str(build_script), "bdist_wheel", "--dist-dir", str(wheel_directory)],
        cwd=source, check=True,
    )
    wheels = list(wheel_directory.glob("*.whl"))
    if len(wheels) != 1:
        raise RuntimeError(f"Expected one VapourSynth wheel in {wheel_directory}")
    return wheels[0]


def install_runtime(args: argparse.Namespace, binaries: Path, wheel: Path) -> None:
    runtime = args.runtime_root.resolve()
    runtime.mkdir(parents=True, exist_ok=True)
    for name in ("VapourSynth.dll", "VSScript.dll", "VSPipe.exe"):
        shutil.copy2(binaries / name, runtime / name)
    core_plugins = runtime / "vapoursynth64/coreplugins"
    core_plugins.mkdir(parents=True, exist_ok=True)
    for name in ("RemoveGrainVS", "Vinverse", "VIVTC", "EEDI3", "AvsCompat", "MiscFilters", "Morpho"):
        shutil.copy2(binaries / (name + ".dll"), core_plugins / (name + ".dll"))
    sdk = runtime / "sdk/lib64"
    sdk.mkdir(parents=True, exist_ok=True)
    for name in ("VapourSynth.lib", "VSScript.lib"):
        shutil.copy2(binaries / name, sdk / name)
    licenses = runtime / "licenses"
    licenses.mkdir(exist_ok=True)
    for source_name, destination_name in (
        ("COPYING.LESSER", "VapourSynth-COPYING.LESSER"),
        ("zimg/COPYING", "zimg-COPYING"),
        ("libp2p/COPYING", "libp2p-COPYING"),
        ("mimalloc/LICENSE", "mimalloc-LICENSE"),
        ("AviSynthPlus/avs_core/include/avisynth.h", "AviSynthPlus-avisynth.h"),
        ("AviSynthPlus/distrib/docs/english/source/avisynthdoc/FilterSDK/SDKLicense.rst",
         "AviSynthPlus-SDKLicense.rst"),
    ):
        shutil.copy2(args.source / source_name, licenses / destination_name)
    (runtime / "portable.vs").touch()
    (runtime / "python-runtime.ini").write_text(
        "[Python]\nHome=" + sys.base_prefix + "\n", encoding="utf-8", newline="\r\n",
    )
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--no-deps", "--force-reinstall", str(wheel)],
        check=True,
    )
    installed_location = subprocess.run(
        [sys.executable, "-c", "from importlib.metadata import distribution; print(distribution('VapourSynth').locate_file(''))"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    site_packages = Path(installed_location)
    (site_packages / "vapoursynth_runtime.py").write_text(
        "import os\nimport sys\n"
        f"_dll_directory = os.add_dll_directory({str(runtime)!r})\n"
        f"sys.path.append({str(runtime / 'Lib/site-packages')!r})\n",
        encoding="utf-8", newline="\r\n",
    )
    (site_packages / "vapoursynth-runtime.pth").write_text(
        "import vapoursynth_runtime\n", encoding="utf-8", newline="\r\n",
    )
    manifest = {
        "version": args.version,
        "python_executable": sys.executable,
        "python_version": list(sys.version_info[:2]),
        "python_tag": sys.implementation.cache_tag,
        "python_library": sysconfig.get_config_var("LDLIBRARY"),
        "dependencies": json.loads(args.dependencies.read_text(encoding="utf-8-sig")),
    }
    (runtime / "vapoursynth-build.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8", newline="\r\n",
    )
    (runtime / "vapoursynth-classic-version.txt").write_text(args.version, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--dependencies", type=Path, required=True)
    parser.add_argument("--msbuild", required=True)
    parser.add_argument("--cmake", required=True)
    parser.add_argument("--jobs", type=int, default=os.cpu_count() or 1)
    args = parser.parse_args()
    if sys.platform != "win32" or sys.maxsize <= 2**32:
        raise RuntimeError("The VapourSynth Windows build requires x64 CPython on Windows")
    binaries = build_runtime(args)
    wheel_directory = args.source.resolve() / "wheels"
    wheel_directory.mkdir(exist_ok=True)
    wheel = build_binding(args.source.resolve(), binaries, wheel_directory, args.version)
    install_runtime(args, binaries, wheel)


if __name__ == "__main__":
    main()
