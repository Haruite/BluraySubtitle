"""Static contracts for the bundled x264/x265 toolchains and documentation."""

from __future__ import annotations

import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
X264_REPOSITORY = "https://code.videolan.org/videolan/x264.git"
X265_REPOSITORY = "https://github.com/Multicorewareinc/x265.git"
HDR10PLUS_REPOSITORY = "https://github.com/quietvoid/hdr10plus_tool"


class EncoderToolchainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.linux_setup = (REPOSITORY_ROOT / "setup_linux_environment.sh").read_text(
            encoding="utf-8"
        )
        cls.windows_setup = (
            REPOSITORY_ROOT / "setup_windows_environment.ps1"
        ).read_text(encoding="utf-8-sig")
        cls.dockerfile = (REPOSITORY_ROOT / "Dockerfile").read_text(encoding="utf-8")
        cls.readme_en = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")
        cls.readme_zh = (REPOSITORY_ROOT / "README.zh-Hans.md").read_text(
            encoding="utf-8"
        )
        cls.notices = (
            REPOSITORY_ROOT / "legal" / "THIRD_PARTY_NOTICES.md"
        ).read_text(encoding="utf-8")
        cls.standards_en = (
            REPOSITORY_ROOT / "docs" / "development" / "code-standards.md"
        ).read_text(encoding="utf-8")
        cls.standards_zh = (
            REPOSITORY_ROOT / "docs" / "development" / "code-standards.zh-Hans.md"
        ).read_text(encoding="utf-8")

    def test_linux_setup_tracks_latest_official_encoders(self) -> None:
        for fragment in (
            f'X264_SOURCE_REPOSITORY="{X264_REPOSITORY}"',
            f'X265_SOURCE_REPOSITORY="{X265_REPOSITORY}"',
            'git ls-remote "$X264_SOURCE_REPOSITORY" HEAD',
            'latest_stable_tag "$X265_SOURCE_REPOSITORY"',
            'git clone --depth 1 "$X264_SOURCE_REPOSITORY" x264',
            'git clone --depth 1 --branch "$x265_version"',
            "__patch_x265_hdr10plus_json11",
            "#include <cstdint>",
            "make || return $?",
            "mv libx265.a libx265_main.a || return $?",
            'version_file="/usr/bin/x264-version.txt"',
            "--bit-depth=all",
            "--chroma-format=all",
            "-DENABLE_HDR10_PLUS=OFF",
            "-DENABLE_HDR10_PLUS=ON",
            "--dhdr10-info",
            'installed_help="$(/usr/bin/x265 --help 2>&1 || true)"',
            "install_hdr10plus_tool",
            HDR10PLUS_REPOSITORY,
            "unknown-linux-musl.tar.gz",
            "8bit+10bit+12bit",
            "bluray_sudo cp x264 /usr/bin/x264",
            'cp "$_x265_out" /usr/bin/',
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, self.linux_setup)
        for removed_pin in (
            "X264_SOURCE_REVISION=",
            "X264_SOURCE_COMMIT=",
            "X265_SOURCE_VERSION=",
            "X265_SOURCE_COMMIT=",
        ):
            self.assertNotIn(removed_pin, self.linux_setup)
        self.assertNotIn("Yuuki-Asuna", self.linux_setup)
        self.assertNotIn("cmake4-patched", self.linux_setup)

    def test_docker_builds_at_original_positions_on_ubuntu_26_04(self) -> None:
        self.assertEqual(self.dockerfile.count("FROM "), 1)
        self.assertIn("FROM ubuntu:26.04", self.dockerfile)
        for fragment in (
            X264_REPOSITORY,
            X265_REPOSITORY,
            "git ls-remote --refs --tags --sort=-version:refname",
            "api.github.com/repos/Multicorewareinc/x265/tags?per_page=100",
            "videolan%2Fx264/repository/commits?ref_name=master&per_page=1",
            "-DCMAKE_POLICY_VERSION_MINIMUM=3.10",
            'json11_source="$source_root/dynamicHDR10/json11/json11.cpp"',
            "sed -i '/^#include <limits>$/a #include <cstdint>'",
            "-DENABLE_HDR10_PLUS=OFF",
            "-DENABLE_HDR10_PLUS=ON",
            "--dhdr10-info",
            'x265_help="$(/usr/bin/x265 --help 2>&1 || true)"',
            HDR10PLUS_REPOSITORY,
            "unknown-linux-musl.tar.gz",
            "--bit-depth=all",
            "--chroma-format=all",
            "8bit+10bit+12bit",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, self.dockerfile)
        x265_cache_key = self.dockerfile.index("api.github.com/repos/Multicorewareinc/x265/tags")
        x264_cache_key = self.dockerfile.index("videolan%2Fx264/repository/commits")
        hdr10plus_cache_key = self.dockerfile.index(
            "api.github.com/repos/quietvoid/hdr10plus_tool/releases/latest"
        )
        x265_position = self.dockerfile.index(X265_REPOSITORY)
        x264_position = self.dockerfile.index(X264_REPOSITORY)
        self.assertLess(self.dockerfile.index("LSMASH_TAG="), x265_cache_key)
        self.assertLess(x265_cache_key, x265_position)
        self.assertLess(x265_position, self.dockerfile.index("SVTAV1EOS"))
        self.assertLess(self.dockerfile.index("vapoursynth_portable.7z"), x264_cache_key)
        self.assertLess(x264_cache_key, x264_position)
        self.assertLess(x264_position, self.dockerfile.index("TSMUXER_TAG="))
        self.assertLess(self.dockerfile.index("TSMUXER_TAG="), hdr10plus_cache_key)
        self.assertLess(
            hdr10plus_cache_key,
            self.dockerfile.index("RUN test -x /usr/bin/dovi_tool"),
        )
        for removed in (
            "ubuntu:22.04",
            "encoder-builder",
            "COPY --from=encoder-builder",
            "Yuuki-Asuna",
            "cmake4-patched",
            "ARG X264_SOURCE",
            "ARG X265_SOURCE",
        ):
            self.assertNotIn(removed, self.dockerfile)

    def test_windows_setup_tracks_latest_sources_and_preserves_paths(self) -> None:
        for fragment in (
            r'C:\Software\x264.exe',
            r'C:\Software\x265.exe',
            r'C:\Software\hdr10plus_tool.exe',
            X264_REPOSITORY,
            "code.videolan.org/api/v4/projects/videolan%2Fx264/repository/commits",
            '-Repository "Multicorewareinc/x265"',
            '-Repository "quietvoid/hdr10plus_tool"',
            "Get-GitHubLatestTaggedSource",
            "Update-X265Hdr10PlusSource",
            "#include <cstdint>",
            "-DENABLE_HDR10_PLUS=ON",
            "--dhdr10-info",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, self.windows_setup)
        for removed_pin in (
            "r3223",
            "0480cb05fa188d37ae87e8f4fd8f1aea3711f7ee",
            "e444744c03978c1fb4e037168967020cf2648427",
        ):
            self.assertNotIn(removed_pin, self.windows_setup)

    def test_latest_version_and_replacement_policy_are_documented(self) -> None:
        for readme in (self.readme_en, self.readme_zh):
            with self.subTest(readme=readme[:20]):
                self.assertIn("x264", readme)
                self.assertIn("x265", readme)
                self.assertIn(r"C:\Software\x264.exe", readme)
                self.assertIn(r"C:\Software\x265.exe", readme)
                self.assertIn("hdr10plus_tool", readme)
                self.assertNotIn("r3223", readme)
                self.assertNotIn("0480cb05", readme)
                self.assertNotIn("e444744c", readme)
        self.assertIn("latest official", self.readme_en)
        self.assertIn("官方", self.readme_zh)
        self.assertIn("最新", self.readme_zh)
        self.assertIn(X264_REPOSITORY, self.notices)
        self.assertIn(X265_REPOSITORY, self.notices)
        self.assertIn(HDR10PLUS_REPOSITORY, self.notices)
        self.assertGreaterEqual(self.notices.count("latest official"), 3)
        self.assertNotIn("r3223", self.notices)

    def test_hdr10plus_linux_install_uses_official_prebuilt_release(self) -> None:
        install_function = self.linux_setup.split(
            "install_hdr10plus_tool()", 1
        )[1].split("# ---------------------------------------------------------------------------", 1)[0]
        self.assertIn("latest_stable_tag", install_function)
        self.assertIn(
            "x86_64-unknown-linux-musl",
            install_function.replace("${arch}", "x86_64"),
        )
        self.assertIn("aarch64", install_function)
        self.assertIn("/usr/bin/hdr10plus_tool", install_function)
        self.assertIn("--version", install_function)
        self.assertNotIn("cargo", install_function)

    def test_bilingual_standards_define_version_and_docker_rules(self) -> None:
        for fragment in (
            "latest version published by the official upstream",
            "Ubuntu 26.04 adaptation",
            "corresponding existing build section",
            "added near the end",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, self.standards_en)
        for fragment in (
            "官方上游发布的最新版本",
            "面向 Ubuntu 26.04 的适配版",
            "已有的对应构建位置",
            "尽量放到最后",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, self.standards_zh)


if __name__ == "__main__":
    unittest.main()
