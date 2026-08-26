"""Static contracts for the bundled x264/x265 toolchains and documentation."""

from __future__ import annotations

import unittest
from pathlib import Path

from src.core.encode_presets import ENCODE_PRESET_PARAMETERS


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
X264_REPOSITORY = "https://code.videolan.org/videolan/x264.git"
X264_MIRROR_REPOSITORY = "https://github.com/mirror/x264.git"
X265_REPOSITORY = "https://github.com/Multicorewareinc/x265.git"
FFMPEG_REPOSITORY = "https://github.com/FFmpeg/FFmpeg.git"
SVT_AV1_REPOSITORY = "https://gitlab.com/AOMediaCodec/SVT-AV1.git"
FDKAAC_REPOSITORY = "https://github.com/nu774/fdkaac.git"
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
        cls.docker_workflow = (
            REPOSITORY_ROOT / ".github" / "workflows" / "docker-image.yml"
        ).read_text(encoding="utf-8")

    def test_linux_setup_tracks_latest_official_encoders(self) -> None:
        for fragment in (
            f'X264_SOURCE_REPOSITORY="{X264_REPOSITORY}"',
            f'X264_SOURCE_MIRROR="{X264_MIRROR_REPOSITORY}"',
            f'X265_SOURCE_REPOSITORY="{X265_REPOSITORY}"',
            'for repository in "$X264_SOURCE_REPOSITORY" "$X264_SOURCE_MIRROR"; do',
            'git ls-remote "$repository" refs/heads/master',
            'latest_stable_tag "$X265_SOURCE_REPOSITORY"',
            'git clone --depth 1 --branch master "$x264_repository" x264',
            'git clone --depth 1 --branch "$x265_version"',
            "__patch_x265_hdr10plus_json11",
            "#include <cstdint>",
            "make || return $?",
            "mv libx265.a libx265_main.a || return $?",
            'SETTINGS_FILE="${BLURAY_SETTINGS_FILE:-',
            "load_configured_tool_paths",
            'version_file="$X264_VERSION_FILE"',
            "--bit-depth=all",
            "--chroma-format=all",
            "-DENABLE_HDR10_PLUS=ON",
            "hdr10plus-all-depths",
            "--dhdr10-info",
            "--dolby-vision-profile",
            "--dolby-vision-rpu",
            'installed_help="$("$X265_PATH" --help 2>&1 || true)"',
            "install_hdr10plus_tool",
            HDR10PLUS_REPOSITORY,
            "unknown-linux-musl.tar.gz",
            "8bit+10bit+12bit",
            'install_configured_executable x264 "$X264_PATH"',
            'install_configured_executable "$_x265_out" "$X265_PATH"',
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, self.linux_setup)

        flac_function = self.linux_setup.split("install_flac()", 1)[1].split(
            "install_zimg_latest()", 1
        )[0]
        self.assertIn('local flac_source_path="/usr/local/bin/flac"', flac_function)
        self.assertLess(
            flac_function.index('[[ -x "$flac_source_path" ]]'),
            flac_function.index('[[ -x "$FLAC_PATH" ]]'),
        )
        self.assertIn(
            'install_configured_executable "$flac_bin" "$FLAC_PATH"',
            flac_function,
        )
        self.assertEqual(flac_function.count("head -n 1 || true"), 2)
        for removed_pin in (
            "X264_SOURCE_REVISION=",
            "X264_SOURCE_COMMIT=",
            "X265_SOURCE_VERSION=",
            "X265_SOURCE_COMMIT=",
        ):
            self.assertNotIn(removed_pin, self.linux_setup)
        self.assertNotIn("Yuuki-Asuna", self.linux_setup)
        self.assertNotIn("cmake4-patched", self.linux_setup)
        self.assertNotIn("-DENABLE_HDR10_PLUS=OFF", self.linux_setup)

    def test_built_in_presets_do_not_force_x264_level_or_synthetic_grain(self) -> None:
        for name, parameters in ENCODE_PRESET_PARAMETERS["x264"].items():
            with self.subTest(encoder="x264", preset=name):
                self.assertNotIn("--level", parameters)
        for name, parameters in ENCODE_PRESET_PARAMETERS["svtav1"].items():
            with self.subTest(encoder="svtav1", preset=name):
                self.assertNotIn("--film-grain", parameters)

    def test_linux_setup_updates_managed_media_tools_and_python_packages(self) -> None:
        mpv_function = self.linux_setup.split("install_mpv()", 1)[1].split(
            "# L-SMASH", 1
        )[0]
        for fragment in (
            f'FFMPEG_SOURCE_REPOSITORY="{FFMPEG_REPOSITORY}"',
            'latest_stable_tag "$FFMPEG_SOURCE_REPOSITORY"',
            '__installed_ffmpeg_version "$FFMPEG_PATH"',
            '__installed_ffmpeg_version "$FFPROBE_PATH"',
            'dpkg --compare-versions "$installed_ffmpeg_version" ge "$target_ffmpeg_version"',
            "./use-ffmpeg-release",
            'echo "--enable-libbluray" > ffmpeg_options',
            'echo "--enable-libdav1d" >> ffmpeg_options',
            'install_configured_executable build_libs/bin/ffmpeg "$FFMPEG_PATH"',
            'install_configured_executable build_libs/bin/ffprobe "$FFPROBE_PATH"',
        ):
            with self.subTest(tool="ffmpeg", fragment=fragment):
                source = (
                    self.linux_setup
                    if "REPOSITORY=" in fragment
                    else mpv_function
                )
                self.assertIn(fragment, source)
        self.assertLess(
            mpv_function.index("./use-ffmpeg-release"),
            mpv_function.index("./rebuild"),
        )
        self.assertNotIn("install_ffmpeg()", self.linux_setup)
        self.assertNotIn("FFMPEG_VERSION_FILE", self.linux_setup)

        package_sync = self.linux_setup.split("sync_mkvtoolnix_paths()", 1)[1].split(
            "verify_configured_tool_paths()", 1
        )[0]
        system_dependencies = self.linux_setup.split("sys_deps=(", 1)[1].split(
            ")", 1
        )[0]
        self.assertNotIn("ffmpeg", package_sync)
        self.assertNotIn("ffprobe", package_sync)
        self.assertNotIn("ffmpeg", system_dependencies)

        svt_function = self.linux_setup.split("install_svt_av1()", 1)[1].split(
            "# tsMuxer", 1
        )[0]
        for fragment in (
            f'SVT_AV1_SOURCE_REPOSITORY="{SVT_AV1_REPOSITORY}"',
            'latest_stable_tag "$SVT_AV1_SOURCE_REPOSITORY"',
            "__installed_svt_av1_version",
            'dpkg --compare-versions "$installed_version" ge "$target_version"',
            'git clone --depth 1 --branch "$svt_tag"',
            "building the unmodified upstream source with 8/10-bit support",
        ):
            with self.subTest(tool="svt-av1", fragment=fragment):
                source = (
                    self.linux_setup
                    if "REPOSITORY=" in fragment
                    else svt_function
                )
                self.assertIn(fragment, source)
        self.assertIn("local patch_status=$?", self.linux_setup)
        self.assertNotIn("v4.2.0", self.linux_setup)

        fdkaac_function = self.linux_setup.split("install_fdk_aac()", 1)[1].split(
            "# FLAC", 1
        )[0]
        for fragment in (
            f'FDKAAC_SOURCE_REPOSITORY="{FDKAAC_REPOSITORY}"',
            'latest_stable_tag "$FDKAAC_SOURCE_REPOSITORY"',
            "__installed_fdkaac_version",
            'dpkg --compare-versions "$installed_version" ge "$target_version"',
            "autoreconf -fi",
        ):
            with self.subTest(tool="fdkaac", fragment=fragment):
                source = (
                    self.linux_setup
                    if "REPOSITORY=" in fragment
                    else fdkaac_function
                )
                self.assertIn(fragment, source)

        python_function = self.linux_setup.split(
            "install_bluray_python_deps()", 1
        )[1].split("# Main execution", 1)[0]
        self.assertNotIn("already importable, skipping pip", python_function)
        self.assertIn(
            "python3 -m pip install --upgrade \"${pip_extra[@]}\" numpy "
            "pycountry PyQt6 soundfile pillow matplotlib",
            python_function,
        )
        self.assertNotIn(
            'python3 -m pip install --upgrade "${pip_extra[@]}" pip ',
            python_function,
        )
        self.assertIn("__bluray_python_imports_ok || die", python_function)

    def test_mkvtoolnix_uses_official_apt_repository_on_supported_ubuntu(self) -> None:
        installer = self.linux_setup.split("install_mkvtoolnix()", 1)[1].split(
            "# libdovi", 1
        )[0]
        for fragment in (
            '24.04) mkvtoolnix_codename="noble"',
            '26.04) mkvtoolnix_codename="resolute"',
            "https://mkvtoolnix.download/gpg-pub-moritzbunkus.gpg",
            "https://mkvtoolnix.download/ubuntu/",
            "apt_install mkvtoolnix mkvtoolnix-gui",
        ):
            with self.subTest(target="linux setup", fragment=fragment):
                self.assertIn(fragment, installer)
        self.assertLess(
            installer.index("apt_install mkvtoolnix mkvtoolnix-gui"),
            installer.index("https://mkvtoolnix.download/latest-release.xml"),
        )
        self.assertIn("rake install", installer)

        for fragment in (
            "/etc/apt/keyrings/gpg-pub-moritzbunkus.gpg",
            "https://mkvtoolnix.download/ubuntu/ resolute main",
            "mkvtoolnix mkvtoolnix-gui",
            "ARG MKVTOOLNIX_VERSION",
            "https://mkvtoolnix.download/latest-release.xml",
            'TARGET_MKVTOOLNIX_VERSION="${MKVTOOLNIX_VERSION:-',
            "--only-upgrade mkvtoolnix mkvtoolnix-gui",
        ):
            with self.subTest(target="Dockerfile", fragment=fragment):
                self.assertIn(fragment, self.dockerfile)
        self.assertNotIn("rake install", self.dockerfile)

    def test_libdovi_repairs_the_truncated_ubuntu_header_without_docker_cargo(
        self,
    ) -> None:
        linux_libdovi = self.linux_setup.split("# libdovi", 1)[1].split(
            "# dovi_tool", 1
        )[0]
        for fragment in (
            "libdovi_header_is_complete()",
            "repair_packaged_libdovi_header()",
            "https://bugs.debian.org/1124682",
            "libdovi-dev_${repair_version}_${architecture}.deb",
            "dpkg-deb -x",
            "sha256sum -c -",
            "falling back to a cargo-c source build",
        ):
            with self.subTest(target="linux setup", fragment=fragment):
                self.assertIn(fragment, linux_libdovi)

        for fragment in (
            "libdovi-dev_${DOVI_REPAIR_VERSION}_${DOVI_ARCH}.deb",
            "517d9a81e904d0b337e04b4f9fef0c4a1939fddc49237612547fd8ae033f3ad1",
            "27c6b2a66ab2de4ddd2f5b87ecb0826cb504f7218fc1cf73a649fdbc4b2c760b",
            "dpkg-deb -x",
            "sha256sum -c -",
            "void dovi_rpu_free_header(",
        ):
            with self.subTest(target="Dockerfile", fragment=fragment):
                self.assertIn(fragment, self.dockerfile)
        self.assertNotIn("cargo install cargo-c", self.dockerfile)
        self.assertNotIn("cargo cinstall", self.dockerfile)

    def test_linux_setup_disables_mpv_manpage_build_on_ubuntu_22_04(self) -> None:
        mpv_options = self.linux_setup.split(
            'echo "-Dlibbluray=enabled" > mpv_options', 1
        )[1].split('tmux_run "mpv-build rebuild"', 1)[0]

        self.assertIn('if [[ "$is_ubuntu_2204" == "true" ]]; then', mpv_options)
        self.assertIn(
            'echo "-Dmanpage-build=disabled" >> mpv_options', mpv_options
        )

    def test_linux_setup_uses_settings_paths_for_installed_tools(self) -> None:
        setting_names = (
            "FLAC_PATH",
            "FFMPEG_PATH",
            "FFPROBE_PATH",
            "X265_PATH",
            "X264_PATH",
            "SVT_AV1_PATH",
            "FDK_AAC_PATH",
            "DOVI_TOOL_PATH",
            "HDR10PLUS_TOOL_PATH",
            "TRUEHDD_PATH",
            "VSEDIT_PATH",
            "VSPIPE_PATH",
            "PLUGIN_PATH",
            "TS_MUXER_PATH",
            "MKV_INFO_PATH",
            "MKV_MERGE_PATH",
            "MKV_PROP_EDIT_PATH",
            "MKV_EXTRACT_PATH",
        )
        loader = self.linux_setup.split("load_configured_tool_paths()", 1)[1].split(
            "install_configured_executable()", 1
        )[0]
        for name in setting_names:
            with self.subTest(name=name):
                self.assertIn(f'"{name}"', loader)

        for fragment in (
            'install_configured_executable dovi_tool "$DOVI_TOOL_PATH"',
            'install_configured_executable hdr10plus_tool "$HDR10PLUS_TOOL_PATH"',
            'install_configured_executable truehdd "$TRUEHDD_PATH"',
            'install_configured_executable "$_svt_bin" "$SVT_AV1_PATH"',
            'install_configured_executable tsMuxeR "$TS_MUXER_PATH"',
            'install_command_at_configured_path fdkaac "$FDK_AAC_PATH"',
            'install_configured_executable /usr/local/bin/flac "$FLAC_PATH"',
            'install_command_at_configured_path vspipe "$VSPIPE_PATH"',
            'local plugins_dir="$PLUGIN_PATH"',
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, self.linux_setup)

        for hardcoded_target in (
            "sudo cp dovi_tool /usr/bin/dovi_tool",
            "sudo cp truehdd /usr/bin/truehdd",
            "bluray_sudo cp x264 /usr/bin/x264",
            'cp "$_x265_out" /usr/bin/',
            "sudo cp tsMuxeR /usr/bin/tsMuxeR",
            'local plugins_dir="$HOME/plugins"',
        ):
            with self.subTest(hardcoded_target=hardcoded_target):
                self.assertNotIn(hardcoded_target, self.linux_setup)

    def test_linux_setup_installs_lsmash_before_dependent_plugin(self) -> None:
        detector = self.linux_setup.split("__lsmash_is_installed()", 1)[1].split(
            "install_lsmash()", 1
        )[0]
        installer = self.linux_setup.split("install_lsmash()", 1)[1].split(
            "# ---------------------------------------------------------------------------", 1
        )[0]
        plugin_builder = self.linux_setup.split(
            'if [[ ! -f "$lsmash_plugin" ]]', 1
        )[1].split(
            'if [[ ! -f "$plugins_dir/eedi3m.so" ]]', 1
        )[0]
        install_call = self.linux_setup.index("\ninstall_lsmash\n")
        plugin_call = self.linux_setup.index("\nbuild_vs_plugins\n")

        self.assertIn("pkg-config --exists liblsmash", detector)
        self.assertNotIn("ldconfig -p", detector)
        self.assertIn("pkg-config", installer)
        self.assertIn("PKG_CONFIG_PATH", installer)
        self.assertIn("__lsmash_is_installed || die", installer)
        self.assertIn('cd "$build_dir"', plugin_builder)
        self.assertNotIn('cd "$HOME"', plugin_builder)
        self.assertIn('ldd -r "$lsmash_plugin"', self.linux_setup)
        self.assertGreaterEqual(
            self.linux_setup.count(
                'lsmash_linker_report="$(LC_ALL=C ldd -r "$lsmash_plugin" 2>&1 || true)"'
            ),
            2,
        )
        self.assertNotIn('ldd -r "$lsmash_plugin" 2>&1 | grep -qF', self.linux_setup)
        self.assertIn(
            'Rebuilt L-SMASH-Works plugin still has unresolved dependencies',
            plugin_builder,
        )
        self.assertIn("LIBAVFORMAT_VERSION_MAJOR < 59", plugin_builder)
        self.assertIn("avformat_index_get_entries_count", plugin_builder)
        self.assertIn("avformat_index_get_entry", plugin_builder)
        self.assertLess(install_call, plugin_call)

    def test_docker_builds_at_original_positions_on_ubuntu_26_04(self) -> None:
        self.assertEqual(self.dockerfile.count("FROM "), 1)
        self.assertIn("FROM ubuntu:26.04", self.dockerfile)
        for fragment in (
            X264_MIRROR_REPOSITORY,
            X265_REPOSITORY,
            "git ls-remote --refs --tags --sort=-version:refname",
            "ARG FFMPEG_TAG",
            "ARG X265_TAG",
            "ARG SVT_AV1_TAG",
            "ARG FDK_AAC_TAG",
            "ARG FDKAAC_TAG",
            "ARG X264_COMMIT",
            "ARG TSMUXER_TAG",
            "ARG HDR10PLUS_TAG",
            "-DCMAKE_POLICY_VERSION_MINIMUM=3.10",
            'json11_source="$source_root/dynamicHDR10/json11/json11.cpp"',
            "sed -i '/^#include <limits>$/a #include <cstdint>'",
            "-DENABLE_HDR10_PLUS=ON",
            "--dhdr10-info",
            "--dolby-vision-profile",
            "--dolby-vision-rpu",
            'x265_help="$(/usr/bin/x265 --help 2>&1 || true)"',
            HDR10PLUS_REPOSITORY,
            "unknown-linux-musl.tar.gz",
            "--bit-depth=all",
            "--chroma-format=all",
            "8bit+10bit+12bit",
            "install -m 0755 dovi_tool /usr/bin/dovi_tool",
            "install -m 0755 truehdd /usr/bin/truehdd",
            'install -m 0755 "$build_root/8bit/x265" /usr/bin/x265',
            'cp "$svt_root/Bin/Release/SvtAv1EncApp" /usr/bin/SvtAv1EncApp',
            "./configure --prefix=/usr/local",
            "install -m 0755 /usr/local/bin/flac /usr/bin/flac",
            "cp tsMuxeR /usr/bin/tsMuxeR",
            "install -m 0755 x264 /usr/bin/x264",
            "install -m 0755 hdr10plus_tool /usr/bin/hdr10plus_tool",
            "mkdir -p /app/plugins",
            "cp \"${BIN_PATH}\" /usr/local/bin/vsedit-bin",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, self.dockerfile)
        x265_cache_key = self.dockerfile.index("ARG X265_TAG")
        x264_cache_key = self.dockerfile.index("ARG X264_COMMIT")
        hdr10plus_cache_key = self.dockerfile.index("ARG HDR10PLUS_TAG")
        x265_position = self.dockerfile.index(X265_REPOSITORY)
        x264_position = self.dockerfile.index(X264_MIRROR_REPOSITORY)
        self.assertLess(self.dockerfile.index("LSMASH_TAG="), x265_cache_key)
        self.assertLess(x265_cache_key, x265_position)
        self.assertLess(x265_position, self.dockerfile.index("SVTAV1EOS"))
        self.assertLess(self.dockerfile.index("vapoursynth_portable.7z"), x264_cache_key)
        self.assertLess(x264_cache_key, x264_position)
        self.assertLess(x264_position, self.dockerfile.index("ARG TSMUXER_TAG"))
        self.assertLess(self.dockerfile.index("ARG TSMUXER_TAG"), hdr10plus_cache_key)
        self.assertLess(
            hdr10plus_cache_key,
            self.dockerfile.index("test -x /usr/bin/dovi_tool"),
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
        self.assertNotIn("-DENABLE_HDR10_PLUS=OFF", self.dockerfile)
        self.assertNotIn("TOOLPATHS", self.dockerfile)
        self.assertNotIn("place_tool", self.dockerfile)
        self.assertNotIn('ADD ["http', self.dockerfile)
        self.assertNotIn("\nADD http", self.dockerfile)

    def test_docker_version_cache_keys_are_resolved_with_retries(self) -> None:
        self.assertIn("retry_ls_remote()", self.docker_workflow)
        self.assertIn("for attempt in 1 2 3 4 5; do", self.docker_workflow)
        self.assertIn("timeout 45s git ls-remote", self.docker_workflow)
        for command in (
            "resolve_latest_mkvtoolnix mkvtoolnix_version https://mkvtoolnix.download/ubuntu/dists/resolute/main/binary-amd64/Packages",
            "resolve_latest_tag ffmpeg_tag https://github.com/FFmpeg/FFmpeg.git",
            "resolve_latest_tag x265_tag https://github.com/Multicorewareinc/x265.git",
            "resolve_latest_tag svt_av1_tag https://gitlab.com/AOMediaCodec/SVT-AV1.git",
            "resolve_latest_tag fdk_aac_tag https://github.com/mstorsjo/fdk-aac.git",
            "resolve_latest_tag fdkaac_tag https://github.com/nu774/fdkaac.git",
            "resolve_branch_commit x264_commit https://github.com/mirror/x264.git master",
            "resolve_latest_tag tsmuxer_tag https://github.com/justdan96/tsMuxer.git",
            "resolve_latest_tag hdr10plus_tag https://github.com/quietvoid/hdr10plus_tool.git",
        ):
            with self.subTest(command=command):
                self.assertIn(command, self.docker_workflow)
        for argument, output_name in (
            ("MKVTOOLNIX_VERSION", "mkvtoolnix_version"),
            ("FFMPEG_TAG", "ffmpeg_tag"),
            ("X265_TAG", "x265_tag"),
            ("SVT_AV1_TAG", "svt_av1_tag"),
            ("FDK_AAC_TAG", "fdk_aac_tag"),
            ("FDKAAC_TAG", "fdkaac_tag"),
            ("X264_COMMIT", "x264_commit"),
            ("TSMUXER_TAG", "tsmuxer_tag"),
            ("HDR10PLUS_TAG", "hdr10plus_tag"),
        ):
            with self.subTest(argument=argument):
                self.assertIn(f"ARG {argument}", self.dockerfile)
                self.assertIn(
                    f"{argument}=${{{{ steps.versions.outputs.{output_name} }}}}",
                    self.docker_workflow,
                )

    def test_docker_tracks_updated_linux_tools_and_python_packages(self) -> None:
        apt_dependencies = self.dockerfile.split("apt-get install", 1)[1].split(
            "rm -rf /var/lib/apt/lists", 1
        )[0]
        self.assertNotIn("ffmpeg", apt_dependencies)

        ffmpeg_build = self.dockerfile.split("mkdir -p /tmp/mpv", 1)[1].split(
            "\n\nRUN set -eux;", 1
        )[0]
        for fragment in (
            "./use-ffmpeg-release",
            'echo "--enable-libbluray" > ffmpeg_options',
            'echo "--enable-libdav1d" >> ffmpeg_options',
            "install -m 0755 build_libs/bin/ffmpeg /usr/bin/ffmpeg",
            "install -m 0755 build_libs/bin/ffprobe /usr/bin/ffprobe",
            "/usr/bin/ffmpeg -version",
            "/usr/bin/ffprobe -version",
        ):
            with self.subTest(tool="ffmpeg", fragment=fragment):
                self.assertIn(fragment, ffmpeg_build)
        self.assertLess(
            ffmpeg_build.index("./use-ffmpeg-release"),
            ffmpeg_build.index("./rebuild"),
        )
        self.assertNotIn("RUN bash <<'FFMPEG'", self.dockerfile)

        svt_build = self.dockerfile.split("RUN bash <<'SVTAV1EOS'", 1)[1].split(
            "\nSVTAV1EOS\n", 1
        )[0]
        self.assertIn('SVT_TAG="${SVT_AV1_TAG:-', svt_build)
        self.assertIn(
            "git ls-remote --refs --tags --sort=-version:refname",
            svt_build,
        )
        self.assertIn(SVT_AV1_REPOSITORY, svt_build)
        self.assertIn("SVT_TAG=", svt_build)
        self.assertIn('git clone --depth 1 --branch "$SVT_TAG"', svt_build)
        self.assertNotIn("v4.2.0", svt_build)
        self.assertIn("svt_patched=0", svt_build)

        fdkaac_build = self.dockerfile.split("RUN bash <<'FDKAAC'", 1)[1].split(
            "\nFDKAAC\n", 1
        )[0]
        self.assertIn(FDKAAC_REPOSITORY, fdkaac_build)
        self.assertNotIn("latest_stable_tag", fdkaac_build)
        self.assertIn("autoreconf -fi", fdkaac_build)
        self.assertIn(
            "--upgrade numpy pycountry PyQt6 soundfile pillow matplotlib",
            self.dockerfile,
        )
        self.assertNotIn("--upgrade pip numpy", self.dockerfile)
        self.assertIn('test -n "$FFMPEG_TAG"', self.dockerfile)

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
            "--dolby-vision-profile",
            "--dolby-vision-rpu",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, self.windows_setup)
        for removed_pin in (
            "r3223",
            "0480cb05fa188d37ae87e8f4fd8f1aea3711f7ee",
            "e444744c03978c1fb4e037168967020cf2648427",
        ):
            self.assertNotIn(removed_pin, self.windows_setup)

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
        self.assertIn('"$HDR10PLUS_TOOL_PATH"', install_function)
        self.assertIn("--version", install_function)
        self.assertNotIn("cargo", install_function)

if __name__ == "__main__":
    unittest.main()
