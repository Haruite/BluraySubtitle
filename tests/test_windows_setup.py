"""Static contract tests for the Windows environment setup script."""

from __future__ import annotations

import os
import shutil
import subprocess
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SETUP_SCRIPT = REPOSITORY_ROOT / "setup_windows_environment.ps1"
CMD_LAUNCHER = REPOSITORY_ROOT / "setup_windows_environment.cmd"
SETTINGS_FILE = REPOSITORY_ROOT / "src" / "core" / "settings.py"
CODE_STANDARDS_EN = REPOSITORY_ROOT / "docs" / "development" / "code-standards.md"
CODE_STANDARDS_ZH = (
    REPOSITORY_ROOT / "docs" / "development" / "code-standards.zh-Hans.md"
)


class WindowsSetupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.raw = SETUP_SCRIPT.read_bytes()
        cls.source = cls.raw.decode("utf-8-sig")
        cls.settings_source = SETTINGS_FILE.read_text(encoding="utf-8")
        cls.code_standards_en = CODE_STANDARDS_EN.read_text(encoding="utf-8")
        cls.code_standards_zh = CODE_STANDARDS_ZH.read_text(encoding="utf-8")

    def test_script_uses_utf8_and_crlf(self) -> None:
        self.assertTrue(self.source)
        self.assertNotIn(b"\n", self.raw.replace(b"\r\n", b""))

    def test_elevation_precedes_environment_work(self) -> None:
        elevation = self.source.index("if (-not (Test-Administrator))")
        language_prompt = self.source.index("$script:SelectedLanguage = Select-SetupLanguage")
        os_check = self.source.index("$windows = Assert-SupportedWindows")
        temp_creation = self.source.index("Initialize-SetupTempRoot")
        self.assertLess(elevation, language_prompt)
        self.assertLess(language_prompt, os_check)
        self.assertLess(elevation, temp_creation)
        self.assertIn("-Verb RunAs", self.source)

    def test_elevated_window_stays_open(self) -> None:
        self.assertIn('@("-NoProfile", "-NoExit", "-File", $PSCommandPath)', self.source)
        self.assertNotIn("exit (Start-ElevatedSetup)", self.source)
        self.assertNotIn("exit $exitCode", self.source)

    def test_only_windows_10_11_amd64_workstations_are_accepted(self) -> None:
        required_fragments = (
            r"\bWindows 10\b",
            r"\bWindows 11\b",
            "$productType -eq 1",
            "$processorArchitecture -eq 9",
            "[Environment]::Is64BitOperatingSystem",
            "[Environment]::Is64BitProcess",
        )
        for fragment in required_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, self.source)

    def test_script_has_no_command_line_interface(self) -> None:
        self.assertNotIn("[CmdletBinding()]", self.source)
        self.assertFalse(self.source.lstrip().startswith("param("))
        for removed_parameter in ("$Language", "$Only", "$Force", "$CheckOnly", "$Elevated"):
            with self.subTest(parameter=removed_parameter):
                self.assertNotIn(removed_parameter, self.source)

    def test_language_is_requested_after_elevation(self) -> None:
        elevation = self.source.index("if (-not (Test-Administrator))")
        language_prompt = self.source.index("$script:SelectedLanguage = Select-SetupLanguage")
        os_check = self.source.index("$windows = Assert-SupportedWindows")
        self.assertLess(elevation, language_prompt)
        self.assertLess(language_prompt, os_check)
        self.assertIn("Read-Host", self.source)
        self.assertIn("请选择语言", self.source)

    def test_console_and_native_command_output_use_utf8(self) -> None:
        elevation = self.source.index("if (-not (Test-Administrator))")
        encoding = self.source.index(
            "$script:Utf8Encoding = New-Object Text.UTF8Encoding($false)"
        )
        language_prompt = self.source.index(
            "$script:SelectedLanguage = Select-SetupLanguage"
        )
        self.assertLess(elevation, encoding)
        self.assertLess(encoding, language_prompt)
        self.assertIn("[Console]::InputEncoding = $script:Utf8Encoding", self.source)
        self.assertIn("[Console]::OutputEncoding = $script:Utf8Encoding", self.source)
        self.assertIn("$OutputEncoding = $script:Utf8Encoding", self.source)

    def test_script_does_not_read_environment_variables(self) -> None:
        self.assertNotIn("$env:", self.source)

    def test_no_cmd_launcher_exists(self) -> None:
        self.assertFalse(CMD_LAUNCHER.exists())

    def test_downloads_and_cleanup_are_confined_to_system_temp(self) -> None:
        self.assertIn("[IO.Path]::GetTempPath()", self.source)
        self.assertIn("Downloads may only be written inside", self.source)
        self.assertIn("Test-PathIsUnderRoot $resolvedTemp $script:SystemTempRoot", self.source)
        self.assertIn("Remove-Item -LiteralPath $resolvedTemp -Recurse -Force", self.source)
        self.assertIn('$name = ".tmp" + [IO.Path]::GetRandomFileName()', self.source)
        self.assertIn("^\\.tmp[a-z0-9]{6}$", self.source)
        self.assertNotIn("BluraySubtitle-setup-", self.source)

    def test_system_proxy_uses_default_credentials(self) -> None:
        self.assertIn("[Net.WebRequest]::DefaultWebProxy", self.source)
        self.assertIn("[Net.CredentialCache]::DefaultNetworkCredentials", self.source)

    def test_fixed_tool_paths_are_declared_in_script(self) -> None:
        paths = (
            r"C:\Program Files\7-Zip\7z.exe",
            r"C:\Program Files\Python314\python.exe",
            r"C:\Program Files\Python314\Scripts",
            r"C:\Program Files\Git\cmd\git.exe",
            r"C:\Program Files\Microsoft Visual Studio\18\BuildTools",
            r"C:\Program Files\CMake\bin\cmake.exe",
            r"C:\Software\ninja.exe",
            r"C:\Software\nasm.exe",
            r"C:\msys64\usr\bin\bash.exe",
            r"C:\Software\ffmpeg.exe",
            r"C:\Software\ffprobe.exe",
            r"C:\Software\flac.exe",
            r"C:\Software\libFLAC.dll",
            r"C:\Software\libass-9.dll",
            r"C:\Program Files\MKVToolNix\mkvmerge.exe",
            r"C:\Program Files\MKVToolNix\mkvinfo.exe",
            r"C:\Program Files\MKVToolNix\mkvextract.exe",
            r"C:\Program Files\MKVToolNix\mkvpropedit.exe",
            r"C:\Software\tsMuxeR.exe",
            r"C:\Software\dovi_tool.exe",
            r"C:\Software\truehdd.exe",
            r"C:\Software\x264.exe",
            r"C:\Software\x265.exe",
            r"C:\Software\SvtAv1EncApp.exe",
            r"C:\Software\fdkaac.exe",
            r"C:\Software\vapoursynth\python.exe",
            r"C:\Software\vapoursynth\vspipe.exe",
            r"C:\Software\vapoursynth\vsedit.exe",
            r"C:\Software\vapoursynth\Lib\site-packages",
            r"C:\Software\vapoursynth\vapoursynth64\plugins",
        )
        for path in paths:
            with self.subTest(path=path):
                self.assertIn(path, self.source)
        self.assertNotIn(r"C:\Software\ninja\ninja.exe", self.source)
        self.assertNotIn(r"C:\Software\nasm\nasm.exe", self.source)

    def test_nasm_archive_is_located_by_executable_instead_of_directory_name(self) -> None:
        install_function = self.source.split("function Install-Nasm", 1)[1].split(
            "function Test-Nasm", 1
        )[0]
        self.assertIn('-Filter "nasm.exe" -File -Recurse', install_function)
        self.assertIn('Join-Path $_.DirectoryName "ndisasm.exe"', install_function)
        self.assertIn("Join-Path $destinationDirectory $name", install_function)
        self.assertNotIn('Where-Object { $_.Name -like "nasm-*-win64" }', install_function)

    def test_only_official_release_sources_are_used(self) -> None:
        repositories = (
            "ip7z/7zip",
            "git-for-windows/git",
            "Kitware/CMake",
            "ninja-build/ninja",
            "msys2/msys2-installer",
            "xiph/flac",
            "justdan96/tsMuxer",
            "quietvoid/dovi_tool",
            "truehdd/truehdd",
            "jpsdr/x264",
            "msg7086/x265-Yuuki-Asuna",
            "nu774/fdkaac",
            "mstorsjo/fdk-aac",
            "libass/libass",
            "AmusementClub/vapoursynth-classic",
            "AmusementClub/tools",
        )
        for repository in repositories:
            with self.subTest(repository=repository):
                self.assertIn(repository, self.source)

        sources = (
            "www.python.org/api/v2/downloads/release/",
            "aka.ms/vs/stable/vs_buildtools.exe",
            "www.nasm.us/pub/nasm/releasebuilds/",
            "pypi.org/pypi/",
            "www.gyan.dev/ffmpeg/builds/",
            "mkvtoolnix.download/latest-release.xml",
            "mkvtoolnix.download/windows/releases/",
            "gitlab.com/api/v4/projects/AOMediaCodec%2FSVT-AV1/releases",
        )
        for source in sources:
            with self.subTest(source=source):
                self.assertIn(source, self.source)

    def test_all_stage_two_components_are_registered(self) -> None:
        components = (
            "7zip",
            "python",
            "python-dependencies",
            "python-system-path",
            "git",
            "git-system-path",
            "visual-studio-build-tools",
            "cmake",
            "ninja",
            "nasm",
            "msys2",
            "msys2-packages",
        )
        for component in components:
            with self.subTest(component=component):
                self.assertIn(f'-Name "{component}"', self.source)
        self.assertIn("Register-StageTwoComponents", self.source)
        self.assertIn("Invoke-RegisteredSetupComponents", self.source)

    def test_all_stage_three_components_are_registered(self) -> None:
        components = (
            "ffmpeg",
            "flac",
            "mkvtoolnix",
            "tsmuxer",
            "dovi-tool",
            "truehdd",
        )
        for component in components:
            with self.subTest(component=component):
                self.assertIn(f'-Name "{component}"', self.source)
        self.assertIn("Register-StageThreeComponents", self.source)
        self.assertLess(
            self.source.index("Register-StageTwoComponents"),
            self.source.index("Register-StageThreeComponents"),
        )


    def test_all_stage_four_components_are_registered(self) -> None:
        components = ("x264", "x265", "svt-av1", "fdkaac", "libass")
        for component in components:
            with self.subTest(component=component):
                self.assertIn(f'-Name "{component}"', self.source)
        self.assertIn("Register-StageFourComponents", self.source)
        self.assertLess(
            self.source.index("Register-StageThreeComponents"),
            self.source.index("Register-StageFourComponents"),
        )


    def test_all_stage_five_components_are_registered(self) -> None:
        components = (
            "vapoursynth-classic",
            "vapoursynth-python",
            "vapoursynth-tools",
        )
        for component in components:
            with self.subTest(component=component):
                self.assertIn(f'-Name "{component}"', self.source)
        self.assertIn("Register-StageFiveComponents", self.source)
        self.assertLess(
            self.source.index("Register-StageFourComponents"),
            self.source.index("Register-StageFiveComponents"),
        )

    def test_vapoursynth_classic_includes_prereleases_and_installs_portably(self) -> None:
        release_function = self.source.split(
            "function Get-VapourSynthClassicRelease", 1
        )[1].split("function Get-InstalledVapourSynthClassicVersion", 1)[0]
        install_function = self.source.split(
            "function Install-VapourSynthClassic", 1
        )[1].split("function Test-VapourSynthClassic", 1)[0]
        self.assertIn("releases?per_page=100", release_function)
        self.assertNotIn("releases/latest", release_function)
        self.assertIn('"release-x64.zip"', release_function)
        self.assertIn('"vapoursynth.cp313-win_amd64.pyd"', self.source)
        self.assertIn('"portable.vs"', install_function)
        self.assertIn("$script:ToolPaths.VapourSynthRoot", install_function)
        classic_verify = self.source.split("function Test-VapourSynthClassic", 1)[1].split(
            "function Get-VapourSynthPythonRelease", 1
        )[0]
        self.assertNotIn("$script:ToolPaths.VsPipe", classic_verify)

    def test_vapoursynth_uses_python_313_embed_and_offline_numpy_wheel(self) -> None:
        python_functions = self.source.split(
            "function Get-VapourSynthPythonRelease", 1
        )[1].split("function Get-VapourSynthToolsRelease", 1)[0]
        required = (
            "python-$version-embed-amd64.zip",
            "python313._pth",
            "python313.zip",
            "import site",
            "cp313-cp313-win_amd64.whl",
            "numpy.libs",
            '"import numpy, vapoursynth; print(numpy.__version__)"',
        )
        for fragment in required:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, python_functions)
        self.assertIn("$candidate.Major -eq 3 -and $candidate.Minor -eq 13", python_functions)
        self.assertIn("$preferredVersion = [string]$package.info.version", python_functions)
        self.assertNotIn("pip install", python_functions)
        embedded_verify = python_functions.split(
            "function Test-VapourSynthEmbeddedPython", 1
        )[1]
        self.assertIn("$script:ToolPaths.VsPipe", embedded_verify)
        self.assertIn("import numpy, vapoursynth", embedded_verify)

    def test_vapoursynth_tools_extract_only_required_plugins(self) -> None:
        tools_function = self.source.split(
            "function Install-VapourSynthTools", 1
        )[1].split("function Test-VapourSynthTools", 1)[0]
        required_plugins = (
            "addgrain.dll",
            "assrender.dll",
            "bilateral.dll",
            "descale.dll",
            "dfttest.dll",
            "eedi2.dll",
            "eedi3m.dll",
            "f3kdb.dll",
            "fmtconv.dll",
            "libsangnom.dll",
            "libvslsmashsource.dll",
            "mvtools.dll",
            "neo-f3kdb.dll",
            "vsnlm_ispc.dll",
            "zsmooth.dll",
        )
        for plugin in required_plugins:
            with self.subTest(plugin=plugin):
                self.assertIn(f'"{plugin}"', self.source)
        self.assertIn("VapourSynthScripts", tools_function)
        self.assertIn("$selectedEntries", tools_function)
        self.assertIn("-Arguments $extractArguments", tools_function)
        self.assertNotIn("Expand-SetupArchiveWithSevenZip", tools_function)
        self.assertIn("vapoursynth_plugins_paths=./vapoursynth64/coreplugins", tools_function)
        self.assertIn("import numpy, vapoursynth as vs", self.source)
        self.assertIn("'rgvs'", self.source)
        self.assertIn("'grain'", self.source)
        self.assertIn("'mv'", self.source)
        self.assertIn("'zsmooth'", self.source)

    def test_large_downloads_report_periodic_progress(self) -> None:
        download_function = self.source.split("function Invoke-SetupDownload", 1)[1].split(
            "function Invoke-SetupInstaller", 1
        )[0]
        self.assertIn("$progressTimer.Elapsed.TotalSeconds -ge 10", download_function)
        self.assertIn("$downloadedMiB/$totalMiB MiB", download_function)
        self.assertNotIn("CopyToAsync", download_function)

    def test_x264_uses_prebuilt_jpsdr_release(self) -> None:
        install_function = self.source.split("function Install-X264", 1)[1].split(
            "function Test-X264", 1
        )[0]
        self.assertIn('-Repository "jpsdr/x264"', self.source)
        self.assertIn("^x264_tmod_r[0-9]+\\.7z$", self.source)
        self.assertIn(r'winthread\x264_x64.exe', install_function)
        self.assertIn("Expand-SetupArchiveWithSevenZip", install_function)
        self.assertIn("-ExpectedSize $release.Size", install_function)
        self.assertNotIn("CMake", install_function)
        self.assertNotIn("git clone", install_function)

    def test_x265_build_links_8_10_12_bit_cores(self) -> None:
        install_function = self.source.split("function Install-X265", 1)[1].split(
            "function Test-X265", 1
        )[0]
        required = (
            "Visual Studio 18 2026",
            "-DHIGH_BIT_DEPTH=ON",
            "-DMAIN12=ON",
            "-DEXPORT_C_API=OFF",
            "-DEXTRA_LIB=$library10Path;$library12Path",
            "-DLINKED_10BIT=ON",
            "-DLINKED_12BIT=ON",
            "-DENABLE_AVISYNTH=OFF",
            "-DNASM_EXECUTABLE=$nasmPath",
            '"--target", "cli"',
        )
        for fragment in required:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, install_function)
        self.assertIn("8bit+10bit+12bit", self.source)

    def test_x265_uses_stable_branch_and_records_its_source_version(self) -> None:
        release_function = self.source.split("function Get-X265Release", 1)[1].split(
            "function Get-InstalledX265Version", 1
        )[0]
        self.assertIn('$branchName = "stable"', release_function)
        self.assertIn("branches/$branchName", release_function)
        self.assertIn("x265Version.txt", release_function)
        self.assertIn('StartsWith("releasetag:"', release_function)
        self.assertNotIn("TagPattern", release_function)
        self.assertNotIn("Get-GitHubLatestTaggedSource", release_function)

        installed_version = self.source.split(
            "function Get-InstalledX265Version", 1
        )[1].split("function Update-X265SourceForCMake4", 1)[0]
        self.assertIn("$script:ToolPaths.X265Version", installed_version)
        self.assertNotIn("encoder version", installed_version)

        install_function = self.source.split("function Install-X265", 1)[1].split(
            "function Test-X265", 1
        )[0]
        self.assertIn("$script:ToolPaths.X265Version", install_function)
        self.assertIn("$release.Version", install_function)

        verify_function = self.source.split("function Test-X265", 1)[1].split(
            "function Get-SvtAv1Release", 1
        )[0]
        self.assertIn('IndexOf("8bit+10bit+12bit"', verify_function)
        self.assertNotIn("Get-InstalledX265Version", verify_function)
        self.assertNotIn("[regex]", verify_function)

    def test_validation_simplicity_rule_is_synchronized(self) -> None:
        self.assertIn(
            "Avoid any unnecessary validation unrelated to the objective.",
            self.code_standards_en,
        )
        self.assertIn(
            "避免任何与目的无关的不必要校验。",
            self.code_standards_zh,
        )

    def test_svt_av1_12_bit_patch_is_experimental_and_optional(self) -> None:
        patch_function = self.source.split(
            "function Try-Update-SvtAv1SourceFor12Bit", 1
        )[1].split("function Build-SvtAv1Executable", 1)[0]
        required = (
            "EB_TWELVE_BIT",
            "12-bit encoding requires Professional profile",
            "[8, 10, 12]",
            "encoder_bit_depth > 8",
            "1u << cfg->encoder_bit_depth",
            "$originalFiles",
            "[IO.File]::WriteAllBytes",
            "return $false",
            "experimental SVT-AV1 12-bit patch could not be applied",
            "unmodified upstream source will be compiled",
        )
        for fragment in required:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, patch_function)
        install_function = self.source.split("function Install-SvtAv1", 1)[1].split(
            "function Test-SvtAv1", 1
        )[0]
        self.assertIn(
            "$patchApplied = Try-Update-SvtAv1SourceFor12Bit -SourceRoot $sourceRoot",
            install_function,
        )
        build_function = self.source.split("function Build-SvtAv1Executable", 1)[
            1
        ].split("function Install-SvtAv1", 1)[0]
        self.assertIn('-DBUILD_SHARED_LIBS=OFF', build_function)
        self.assertIn('-DSVT_AV1_LTO=ON', build_function)
        self.assertIn("svt-av1-fallback-extracted", install_function)
        self.assertIn("fresh copy of the unmodified upstream source", install_function)
        test_function = self.source.split("function Test-SvtAv1", 1)[1].split(
            "function Get-FdkAacLibraryRelease", 1
        )[0]
        self.assertIn("return [bool](Get-InstalledSvtAv1Version)", test_function)
        self.assertNotIn('Arguments @("--help")', test_function)
        self.assertIn("experimental 12-bit patch", self.source)

    def test_fdkaac_and_libass_use_static_dependencies(self) -> None:
        fdkaac_function = self.source.split("function Install-FdkAac", 1)[1].split(
            "function Test-FdkAac", 1
        )[0]
        libass_function = self.source.split("function Install-Libass", 1)[1].split(
            "function Test-Libass", 1
        )[0]
        self.assertIn('-Repository "mstorsjo/fdk-aac"', self.source)
        self.assertIn('-Repository "nu774/fdkaac"', self.source)
        self.assertIn("autoreconf -fi", fdkaac_function)
        self.assertNotIn("autoreconf -i", fdkaac_function)
        self.assertIn("--host=x86_64-w64-mingw32", fdkaac_function)
        self.assertIn("--disable-shared --enable-static", fdkaac_function)
        self.assertIn('LDFLAGS="-static -static-libgcc"', fdkaac_function)
        self.assertIn('-Repository "libass/libass"', self.source)
        self.assertIn("-Dfontconfig=disabled", libass_function)
        self.assertIn("-Ddirectwrite=enabled", libass_function)
        self.assertIn("-Dlibunibreak=enabled", libass_function)
        self.assertIn("-Dprefer_static=true", libass_function)
        self.assertIn('"-Dc_link_args=-static -static-libgcc"', libass_function)
        self.assertNotIn("-Dc_link_args=-static,-static-libgcc", libass_function)
        self.assertIn(
            "-Dc_winlibs=-lkernel32,-luser32,-lgdi32,-lwinspool,-lshell32,"
            "-lole32,-loleaut32,-luuid,-lcomdlg32,-ladvapi32,-lstdc++",
            libass_function,
        )
        self.assertIn("ctypes.WinDLL", self.source)

    def test_fdkaac_version_uses_its_help_banner(self) -> None:
        version_function = self.source.split(
            "function Get-InstalledFdkAacVersion", 1
        )[1].split("function Install-FdkAac", 1)[0]
        self.assertIn("$script:ToolPaths.FdkAac -h", version_function)
        self.assertIn("$exitCode -ne 0 -and $exitCode -ne 1", version_function)
        self.assertIn('StartsWith("fdkaac "', version_function)
        self.assertNotIn('Arguments @("--version")', version_function)
        self.assertNotIn("[regex]", version_function)

    def test_all_source_compilation_uses_the_processor_count(self) -> None:
        self.assertIn(
            "$script:BuildJobs = [Math]::Max(1, [Environment]::ProcessorCount)",
            self.source,
        )
        x265_function = self.source.split("function Install-X265", 1)[1].split(
            "function Test-X265", 1
        )[0]
        self.assertEqual(x265_function.count('"--parallel", $script:BuildJobs'), 3)
        svt_function = self.source.split("function Build-SvtAv1Executable", 1)[1].split(
            "function Install-SvtAv1", 1
        )[0]
        self.assertIn('"--parallel", $script:BuildJobs', svt_function)
        fdkaac_function = self.source.split("function Install-FdkAac", 1)[1].split(
            "function Test-FdkAac", 1
        )[0]
        self.assertIn("jobs=$4", fdkaac_function)
        self.assertEqual(fdkaac_function.count('make -j"$jobs"'), 2)
        libass_function = self.source.split("function Install-Libass", 1)[1].split(
            "function Test-Libass", 1
        )[0]
        self.assertIn("jobs=$3", libass_function)
        self.assertIn('meson compile -C "$build" -j "$jobs"', libass_function)
        self.assertNotIn("jobs=$(/usr/bin/nproc)", self.source)
        self.assertIn("Parallel compilation workers: $script:BuildJobs", self.source)

    def test_stage_four_msys2_packages_are_declared(self) -> None:
        packages = (
            "autotools",
            "freetype",
            "fribidi",
            "harfbuzz",
            "libunibreak",
            "gettext-runtime",
            "libpng",
        )
        for package in packages:
            with self.subTest(package=package):
                self.assertIn(f'"mingw-w64-ucrt-x86_64-{package}"', self.source)
    def test_stage_three_release_integrity_and_archive_handling(self) -> None:
        self.assertIn("ffmpeg-release-essentials.7z.sha256", self.source)
        self.assertIn("$release.ReleaseBody", self.source)
        self.assertIn("`?([0-9a-fA-F]{64})`?\\s+", self.source)
        self.assertIn("Copy-Item -LiteralPath $flacLibrary", self.source)
        self.assertIn("mkvtoolnix-$version-sha256sums.txt", self.source)
        self.assertIn("Assert-ValidAuthenticodeSignature $installer", self.source)
        self.assertIn("Expand-SetupArchiveWithSevenZip", self.source)
        self.assertIn("Archive extraction completed", self.source)
        self.assertIn("-Sha256 $release.Sha256", self.source)

    def test_versioned_settings_paths_are_replaced_with_fixed_paths(self) -> None:
        expected_paths = (
            r'C:\Software\ffmpeg.exe',
            r'C:\Software\ffprobe.exe',
            r'C:\Software\flac.exe',
            r'C:\Software\libass-9.dll',
            r'C:\Software\x264.exe',
            r'C:\Software\x265.exe',
            r'C:\Software\SvtAv1EncApp.exe',
            r'C:\Software\fdkaac.exe',
            r'C:\Software\vapoursynth\vsedit.exe',
            r'C:\Software\vapoursynth\vspipe.exe',
        )
        for path in expected_paths:
            with self.subTest(path=path):
                self.assertIn(path, self.settings_source)
        self.assertNotIn(r'C:\Downloads\ffmpeg-', self.settings_source)
        self.assertNotIn(r'C:\Downloads\flac-', self.settings_source)
        self.assertNotIn(r'C:\Downloads\libass-9.dll', self.settings_source)

    def test_python_dependencies_are_latest_version_components(self) -> None:
        distributions = ("pip", "pycountry", "PyQt6", "librosa", "pillow", "matplotlib")
        for distribution in distributions:
            with self.subTest(distribution=distribution):
                self.assertIn(f'Distribution = "{distribution}"', self.source)
        self.assertIn("Get-LatestPyPiVersion", self.source)
        self.assertIn("--upgrade", self.source)
        self.assertIn("--only-binary=:all:", self.source)
        self.assertIn("function Install-AllPythonDependencies", self.source)
        self.assertIn("function Install-PythonDependenciesWithFallback", self.source)
        self.assertLess(
            self.source.index('-Name "python-dependencies"'),
            self.source.index('-Name "python-system-path"'),
        )

    def test_python_and_pip_are_added_to_machine_path(self) -> None:
        self.assertIn("function Add-PythonToMachinePath", self.source)
        self.assertIn(r"Control\Session Manager\Environment", self.source)
        self.assertIn("RegistryValueOptions]::DoNotExpandEnvironmentNames", self.source)
        self.assertIn('$key.SetValue("Path"', self.source)
        self.assertIn("BluraySubtitleEnvironmentNotifier", self.source)
        self.assertIn('-Name "python-system-path"', self.source)
        self.assertIn("@($installation.Root, $installation.Scripts)", self.source)

    def test_existing_python_versions_are_detected_and_preserved(self) -> None:
        detection_function = self.source.split("function Get-DetectedPythonInstallation", 1)[
            1
        ].split("function Get-InstalledPythonVersion", 1)[0]
        self.assertIn("[Microsoft.Win32.Registry]::LocalMachine", detection_function)
        self.assertIn("[Microsoft.Win32.Registry]::CurrentUser", detection_function)
        self.assertIn('OpenSubKey("Software\\Python\\PythonCore"', detection_function)
        self.assertIn(r"C:\Software\Python\python.exe", detection_function)
        self.assertIn(
            '-GetAvailableVersion { $script:SelectedPythonRelease.Version }', self.source
        )
        self.assertNotIn('"/uninstall"', self.source)

    def test_latest_python_is_selected_from_official_release_api(self) -> None:
        release_function = self.source.split("function Get-PythonStableVersions", 1)[1].split(
            "function Get-LatestNasmRelease", 1
        )[0]
        self.assertIn("is_published=true&pre_release=false", release_function)
        self.assertIn("^Python (3\\.[0-9]+\\.[0-9]+)$", release_function)
        self.assertIn("Sort-Object { ConvertTo-ComparableVersion $_ } -Descending", release_function)
        self.assertIn("function Get-PreviousPythonRelease", release_function)
        self.assertIn("$targetMinor = $currentVersion.Minor - 1", release_function)
        self.assertIn('status = "fallback"', release_function)
        self.assertIn("attempted_version = $AttemptedVersion", release_function)
        self.assertIn('$script:Manifest.components["python-selection"]', release_function)
        self.assertNotIn("downloads/windows", release_function)
        self.assertNotIn("Latest Python 3 Release", release_function)

    def test_visual_studio_2026_stable_is_used_without_reusing_2022(self) -> None:
        release_function = self.source.split("function Get-LatestVisualStudioRelease", 1)[
            1
        ].split("function Get-LatestPyPiVersion", 1)[0]
        self.assertIn("https://aka.ms/vs/stable/channel", release_function)
        self.assertIn("https://aka.ms/vs/stable/vs_buildtools.exe", release_function)
        self.assertNotIn("aka.ms/vs/17/release", release_function)

        detection_functions = self.source.split(
            "function Get-VisualStudioInstallationPath", 1
        )[1].split("function Install-VisualStudioBuildTools", 1)[0]
        self.assertEqual(detection_functions.count('"-version", "[18.0,19.0)"'), 2)

        install_function = self.source.split("function Install-VisualStudioBuildTools", 1)[
            1
        ].split("function Test-VisualStudioBuildTools", 1)[0]
        self.assertIn('if ($installationPath) {', install_function)
        self.assertIn(
            '$clientInstaller = Join-Path $script:ToolPaths.VisualStudioInstaller "setup.exe"',
            install_function,
        )
        self.assertIn('"update",', install_function)
        self.assertIn('"--installPath", $installationPath', install_function)
        self.assertLess(
            install_function.index('if ($installationPath) {'),
            install_function.index('$release = Get-LatestVisualStudioRelease'),
        )
        self.assertIn(
            '"--installPath", $script:ToolPaths.VisualStudioRoot', install_function
        )
        self.assertIn('"--channelUri", "https://aka.ms/vs/stable/channel"', install_function)
        self.assertIn('"--channelId", "VisualStudio.18.Stable"', install_function)
        self.assertIn(r"C:\Program Files\Microsoft Visual Studio\18\BuildTools", self.source)
        self.assertIn("Visual Studio 2026 C++ Build Tools", self.source)
    def test_msys2_uses_temp_proxy_config_and_verifies_real_packages(self) -> None:
        release_function = self.source.split("function Get-Msys2Release", 1)[1].split(
            "function Get-InstalledMsys2Version", 1
        )[0]
        self.assertIn("^msys2-base-x86_64-latest\\.sfx\\.exe$", release_function)
        self.assertIn("$release.AssetUpdatedAtUtc", release_function)
        self.assertIn('"yyyy.MM.dd.HHmmss"', release_function)
        self.assertIn("AssetUpdatedAtUtc = [string]$asset.updated_at", self.source)
        self.assertIn('Join-Path $script:TempRoot "pacman-proxy.conf"', self.source)
        self.assertIn("--proxy-anyauth", self.source)
        self.assertIn("mingw-w64-ucrt-x86_64-toolchain", self.source)
        self.assertIn(r"ucrt64\bin\gcc.exe", self.source)
        self.assertNotIn('@("--noconfirm", "-Syuu")', self.source)
        self.assertNotIn('-Arguments @("-Qu")', self.source)
        self.assertIn('[int[]]$AcceptedExitCodes = @(0)', self.source)
        self.assertIn('-AcceptedExitCodes $AcceptedExitCodes', self.source)
        self.assertIn(
            'Where-Object { $_ -ne "mingw-w64-ucrt-x86_64-toolchain" }', self.source
        )

        installed_function = self.source.split("function Get-InstalledMsys2Version", 1)[
            1
        ].split("function Install-Msys2", 1)[0]
        self.assertIn('return ""', installed_function)
        self.assertNotIn("return (Get-Msys2Release).Version", installed_function)
        self.assertIn("Running MSYS2 first-start initialization.", self.source)
        install_function = self.source.split("function Install-Msys2", 1)[1].split(
            "function Test-Msys2", 1
        )[0]
        self.assertIn("$reuseExistingCore", install_function)
        self.assertIn("Existing MSYS2 core files detected", install_function)
        self.assertIn("skipping the base archive download", install_function)
        self.assertIn("else {", install_function)

    def test_msys2_is_only_checked_when_compilation_is_needed(self) -> None:
        readiness_function = self.source.split(
            "function Test-CompiledToolsReady", 1
        )[1].split("function Register-StageTwoComponents", 1)[0]
        for check in (
            "Test-X265",
            "Test-SvtAv1",
            "Test-FdkAac",
            "Get-InstalledLibassVersion",
        ):
            with self.subTest(check=check):
                self.assertIn(check, readiness_function)
        self.assertIn("Get-X265Release", readiness_function)
        self.assertIn("Get-SvtAv1Release", readiness_function)
        self.assertIn("Get-FdkAacRelease", readiness_function)
        self.assertIn("Get-LibassRelease", readiness_function)
        self.assertIn(
            "All compiled tools are ready; skipping MSYS2",
            readiness_function,
        )

        stage_two = self.source.split("function Register-StageTwoComponents", 1)[1].split(
            "function Register-StageThreeComponents", 1
        )[0]
        self.assertIn("Compare-SetupVersion $installedVersion $availableVersion", readiness_function)
        self.assertIn("if (Test-CompiledToolsReady)", stage_two)
        self.assertLess(
            stage_two.index("if (Test-CompiledToolsReady)"),
            stage_two.index('-Name "msys2"'),
        )

    def test_msys2_packages_check_presence_without_upgrading(self) -> None:
        installed_function = self.source.split(
            "function Get-Msys2PackagesVersion", 1
        )[1].split("function Install-Msys2Packages", 1)[0]
        install_function = self.source.split(
            "function Install-Msys2Packages", 1
        )[1].split("function Test-Msys2Packages", 1)[0]
        self.assertIn('Invoke-Msys2Pacman -Arguments (@("-Q")', installed_function)
        self.assertNotIn('"-Sy"', installed_function)
        self.assertNotIn('"-Qu"', installed_function)
        self.assertIn('"--needed", "-S"', install_function)
        self.assertNotIn("Syuu", install_function)
        self.assertNotIn("Scc", install_function)
        self.assertIn("without a full system upgrade", install_function)

    def test_native_stderr_is_validated_by_exit_code(self) -> None:
        command_function = self.source.split("function Invoke-SetupCommand", 1)[1].split(
            "function Assert-ValidAuthenticodeSignature", 1
        )[0]
        self.assertIn('$ErrorActionPreference = "Continue"', command_function)
        self.assertIn(
            "$ErrorActionPreference = $previousErrorActionPreference", command_function
        )
        self.assertIn("if ($AcceptedExitCodes -notcontains $exitCode)", command_function)

    def test_git_uses_portable_release_without_stopping_existing_git(self) -> None:
        git_functions = self.source.split("function Get-GitRelease", 1)[1].split(
            "function Get-VisualStudioWherePath", 1
        )[0]
        self.assertIn("[Microsoft.Win32.Registry]::CurrentUser", git_functions)
        self.assertIn('OpenSubKey("Software\\GitForWindows"', git_functions)
        self.assertIn("^PortableGit-", git_functions)
        self.assertIn("if (-not $release.Sha256)", git_functions)
        self.assertIn("-Sha256 $release.Sha256", git_functions)
        self.assertIn("Invoke-SetupCommand -FilePath $script:ToolPaths.SevenZip", git_functions)
        self.assertIn('"-aoa"', git_functions)
        self.assertIn('"-o$($script:ToolPaths.GitRoot)"', git_functions)
        installed_git = git_functions.split("function Get-InstalledGitVersion", 1)[1].split(
            "function Install-Git", 1
        )[0]
        self.assertIn(
            "return Get-GitVersionFromExecutable $script:ToolPaths.Git", installed_git
        )
        self.assertNotIn("Get-DetectedGitPath", installed_git)
        self.assertNotIn("Stop-Process", git_functions)
        self.assertNotIn('"/CLOSEAPPLICATIONS"', git_functions)

    def test_git_is_added_to_machine_path(self) -> None:
        self.assertIn("function Test-GitMachinePath", self.source)
        self.assertIn("function Add-GitToMachinePath", self.source)
        self.assertIn('Join-Path $script:ToolPaths.GitRoot "cmd"', self.source)
        self.assertIn("Send-EnvironmentChangeNotification", self.source)
        self.assertIn('-Name "git-system-path"', self.source)
        self.assertIn('"Added Git to the system PATH."', self.source)

    def test_component_download_and_installer_progress_is_logged(self) -> None:
        component_function = self.source.split("function Invoke-SetupComponent", 1)[1].split(
            "function Invoke-RegisteredSetupComponents", 1
        )[0]
        self.assertIn("installed version/status: $installedVersion", component_function)
        self.assertIn("is not installed or not configured", component_function)
        self.assertIn("target version/status: $availableVersion", component_function)
        self.assertIn("requires an upgrade", component_function)
        self.assertIn("Starting installation or configuration", component_function)
        self.assertIn("verification succeeded", component_function)
        self.assertIn("installation/configuration completed", component_function)

        download_function = self.source.split("function Invoke-SetupDownload", 1)[1].split(
            "function Invoke-SetupInstaller", 1
        )[0]
        self.assertIn("Downloading $fileName", download_function)
        self.assertIn("Download completed: $fileName", download_function)
        self.assertIn("SHA-256 verification succeeded", download_function)
        self.assertIn("Retrying", download_function)

        installer_function = self.source.split("function Invoke-SetupInstaller", 1)[1].split(
            "function Invoke-SetupCommand", 1
        )[0]
        self.assertIn("Running installer: $installerName", installer_function)
        self.assertIn("Installer completed successfully", installer_function)
    def test_download_and_installer_security_checks_are_present(self) -> None:
        self.assertIn("Assert-ValidAuthenticodeSignature", self.source)
        self.assertIn("Get-FileHash -LiteralPath $installer -Algorithm SHA256", self.source)
        self.assertIn("Downloads may only be written inside", self.source)
        self.assertIn("Remove-SetupTempRoot", self.source)

    def test_unsigned_seven_zip_installer_uses_release_digest(self) -> None:
        install_function = self.source.split("function Install-SevenZip", 1)[1].split(
            "function Test-SevenZip", 1
        )[0]
        self.assertIn("if (-not $release.Sha256)", install_function)
        self.assertIn("-Sha256 $release.Sha256", install_function)
        self.assertNotIn("Assert-ValidAuthenticodeSignature", install_function)

    def test_no_winget_or_environment_variable_configuration_is_used(self) -> None:
        self.assertNotIn("winget", self.source.lower())
        self.assertNotIn("$env:", self.source)
        self.assertNotIn("SetEnvironmentVariable", self.source)

    @unittest.skipUnless(os.name == "nt", "PowerShell parser check requires Windows")
    def test_powershell_parser_accepts_script(self) -> None:
        powershell = shutil.which("powershell.exe") or shutil.which("powershell")
        if not powershell:
            self.skipTest("Windows PowerShell is unavailable")
        escaped_path = str(SETUP_SCRIPT).replace("'", "''")
        command = (
            "$tokens=$null; $errors=$null; "
            f"[System.Management.Automation.Language.Parser]::ParseFile('{escaped_path}', "
            "[ref]$tokens, [ref]$errors) | Out-Null; "
            "if ($errors.Count -gt 0) { $errors | ForEach-Object { Write-Error $_ }; exit 1 }"
        )
        result = subprocess.run(
            [powershell, "-NoProfile", "-NonInteractive", "-Command", command],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
