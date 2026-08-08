"""Focused safety and capability contracts for the Windows setup script."""

from __future__ import annotations

import os
import shutil
import subprocess
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SETUP_SCRIPT = REPOSITORY_ROOT / "setup_windows_environment.ps1"
SETTINGS_FILE = REPOSITORY_ROOT / "src" / "core" / "settings.py"
SPEC_FILE = REPOSITORY_ROOT / "BluraySubtitle_windows_x64.spec"
NOTICES_TEMPLATE = REPOSITORY_ROOT / "legal" / "THIRD_PARTY_NOTICES.md"


class WindowsSetupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = SETUP_SCRIPT.read_text(encoding="utf-8-sig")
        cls.settings_source = SETTINGS_FILE.read_text(encoding="utf-8")
        cls.spec_source = SPEC_FILE.read_text(encoding="utf-8")
        cls.notices_template = NOTICES_TEMPLATE.read_text(encoding="utf-8")

    def test_elevation_and_platform_checks_precede_environment_changes(self) -> None:
        elevation = self.source.index("if (-not (Test-Administrator))")
        language_prompt = self.source.index("$script:SelectedLanguage = Select-SetupLanguage")
        os_check = self.source.index("$windows = Assert-SupportedWindows")
        temp_creation = self.source.index("Initialize-SetupTempRoot")

        self.assertLess(elevation, language_prompt)
        self.assertLess(language_prompt, os_check)
        self.assertLess(elevation, temp_creation)
        self.assertIn("-Verb RunAs", self.source)
        self.assertIn("$productType -eq 1", self.source)
        self.assertIn("$productType -in @(2, 3)", self.source)
        self.assertIn("[Environment]::Is64BitOperatingSystem", self.source)
        self.assertIn("[Environment]::Is64BitProcess", self.source)

    def test_downloads_cleanup_and_installers_keep_the_safety_boundaries(self) -> None:
        for fragment in (
            "[IO.Path]::GetTempPath()",
            "Downloads may only be written inside",
            "Test-PathIsUnderRoot $resolvedTemp $script:SystemTempRoot",
            "Remove-Item -LiteralPath $resolvedTemp -Recurse -Force",
            "Assert-ValidAuthenticodeSignature",
            "Get-FileHash -LiteralPath $installer -Algorithm SHA256",
            "Remove-SetupTempRoot",
            "[Net.WebRequest]::DefaultWebProxy",
            "[Net.CredentialCache]::DefaultNetworkCredentials",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, self.source)

        seven_zip = self.source.split("function Install-SevenZip", 1)[1].split(
            "function Test-SevenZip", 1
        )[0]
        self.assertIn("if (-not $release.Sha256)", seven_zip)
        self.assertIn("-Sha256 $release.Sha256", seven_zip)

    def test_all_required_components_are_registered_in_stage_order(self) -> None:
        required_components = (
            "7zip", "python", "python-dependencies", "python-system-path", "git",
            "git-system-path", "visual-studio-build-tools", "cmake", "ninja", "nasm",
            "msys2", "msys2-packages", "ffmpeg", "flac", "mkvtoolnix", "tsmuxer",
            "dovi-tool", "hdr10plus-tool", "truehdd", "x264", "x265", "svt-av1",
            "fdkaac", "libass", "vapoursynth-classic", "vapoursynth-python",
            "vapoursynth-tools",
        )
        for component in required_components:
            with self.subTest(component=component):
                self.assertIn(f'-Name "{component}"', self.source)

        stage_positions = [
            self.source.index(f"function Register-Stage{stage}Components")
            for stage in ("Two", "Three", "Four", "Five")
        ]
        self.assertEqual(stage_positions, sorted(stage_positions))

    def test_managed_sources_are_official_and_resolved_dynamically(self) -> None:
        for source in (
            "ip7z/7zip",
            "git-for-windows/git",
            "Kitware/CMake",
            "ninja-build/ninja",
            "msys2/msys2-installer",
            "justdan96/tsMuxer",
            "quietvoid/dovi_tool",
            "quietvoid/hdr10plus_tool",
            "truehdd/truehdd",
            "code.videolan.org/videolan/x264.git",
            "Multicorewareinc/x265",
            "nu774/fdkaac",
            "mstorsjo/fdk-aac",
            "libass/libass",
            "AmusementClub/vapoursynth-classic",
            "AmusementClub/tools",
            "www.python.org/api/v2/downloads/release/",
        ):
            with self.subTest(source=source):
                self.assertIn(source, self.source)

        self.assertIn("Get-GitHubLatestTaggedSource", self.source)
        self.assertIn("Get-LatestPyPiVersion", self.source)
        self.assertNotIn("Yuuki-Asuna", self.source)
        self.assertNotIn("x264_tmod", self.source.lower())

    def test_encoder_builds_keep_required_bit_depth_and_hdr_capabilities(self) -> None:
        x264 = self.source.split("function Install-X264", 1)[1].split(
            "function Test-X264", 1
        )[0]
        for fragment in (
            "--bit-depth=all",
            "--chroma-format=all",
            "--enable-lto",
            'fprofiled VIDS="$training_y4m"',
        ):
            self.assertIn(fragment, x264)

        x265 = self.source.split("function Install-X265", 1)[1].split(
            "function Test-X265", 1
        )[0]
        for fragment in (
            "-DHIGH_BIT_DEPTH=ON",
            "-DMAIN12=ON",
            "-DLINKED_10BIT=ON",
            "-DLINKED_12BIT=ON",
            "-DENABLE_HDR10_PLUS=ON",
            "hdr10plus-all-depths",
        ):
            self.assertIn(fragment, x265)

        verification = self.source.split("function Test-X265", 1)[1].split(
            "function Get-SvtAv1Release", 1
        )[0]
        for capability in (
            "8bit+10bit+12bit",
            "--dhdr10-info",
            "--dolby-vision-profile",
            "--dolby-vision-rpu",
        ):
            self.assertIn(capability, verification)

    def test_native_build_dependencies_remain_static_and_failure_checked(self) -> None:
        fdkaac = self.source.split("function Install-FdkAac", 1)[1].split(
            "function Test-FdkAac", 1
        )[0]
        self.assertIn("--disable-shared --enable-static", fdkaac)
        self.assertIn('LDFLAGS="-static -static-libgcc"', fdkaac)

        libass = self.source.split("function Install-Libass", 1)[1].split(
            "function Test-Libass", 1
        )[0]
        self.assertIn("-Ddirectwrite=enabled", libass)
        self.assertIn("-Dprefer_static=true", libass)

        command_runner = self.source.split("function Invoke-SetupCommand", 1)[1].split(
            "function Assert-ValidAuthenticodeSignature", 1
        )[0]
        self.assertIn("if ($AcceptedExitCodes -notcontains $exitCode)", command_runner)

    def test_msys2_is_conditional_and_does_not_upgrade_the_whole_installation(self) -> None:
        stage_two = self.source.split("function Register-StageTwoComponents", 1)[1].split(
            "function Register-StageThreeComponents", 1
        )[0]
        self.assertLess(
            stage_two.index("if (Test-CompiledToolsReady)"),
            stage_two.index('-Name "msys2"'),
        )

        installer = self.source.split("function Install-Msys2Packages", 1)[1].split(
            "function Test-Msys2Packages", 1
        )[0]
        self.assertIn('"--needed", "-S"', installer)
        self.assertNotIn("Syuu", installer)
        self.assertNotIn("Scc", installer)

    def test_portable_vapoursynth_contains_the_required_runtime(self) -> None:
        for fragment in (
            '"vapoursynth.cp313-win_amd64.pyd"',
            "python313._pth",
            "cp313-cp313-win_amd64.whl",
            '"libvslsmashsource.dll"',
            '"libvs_placebo.dll"',
            '"neo-f3kdb.dll"',
            '"vsnlm_ispc.dll"',
            "vapoursynth_plugins_paths=./vapoursynth64/coreplugins",
            "import numpy, vapoursynth as vs",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, self.source)

    def test_packaged_settings_tools_and_notices_are_preserved(self) -> None:
        for path in (
            r'C:\Software\ffmpeg.exe',
            r'C:\Software\ffprobe.exe',
            r'C:\Software\x264.exe',
            r'C:\Software\x265.exe',
            r'C:\Software\SvtAv1EncApp.exe',
            r'C:\Software\hdr10plus_tool.exe',
        ):
            with self.subTest(path=path):
                self.assertIn(path, self.settings_source)

        for fragment in (
            "exclude_binaries=True",
            "coll = COLLECT(",
            'PROJECT_ROOT / "config.default.json"',
            '(str(SETTINGS_PATH), "src/core")',
            '("HDR10PLUS_TOOL_PATH", "hdr10plus_tool")',
        ):
            self.assertIn(fragment, self.spec_source)
        self.assertNotIn('collect_all("librosa")', self.spec_source)
        self.assertIn("{{FFMPEG_VERSION}}", self.notices_template)
        self.assertIn("{{PYINSTALLER_VERSION}}", self.notices_template)

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
