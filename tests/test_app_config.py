"""Focused contracts for persistent application settings."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from src.core.app_config import (
    GpuEncodePreferences,
    PathPreferences,
    UiPreferences,
    UserEncodePreset,
    app_config_from_mapping,
    default_app_config,
    load_app_config,
    save_app_config,
)
from src.core.encode_presets import UserGpuEncodePreset
from src.core.tool_paths import TOOL_PATH_NAMES, require_tool_path, resolve_tool_paths, using_tool_paths


class AppConfigTests(unittest.TestCase):
    def test_gpu_encoding_requires_explicit_opt_in(self) -> None:
        self.assertFalse(app_config_from_mapping({"encode": {"cpu_enabled": False}}).encode.gpu_enabled)
        self.assertTrue(app_config_from_mapping({"encode": {"gpu_enabled": True}}).encode.gpu_enabled)

    def test_custom_gpu_presets_round_trip_by_device_and_mode(self) -> None:
        legacy = app_config_from_mapping({"encode": {"gpu_devices": [{
            "device": "nvenc:0", "enabled": True, "parameters": "-cq 20",
        }]}}).encode.gpu_devices[0]
        self.assertEqual(legacy, GpuEncodePreferences("nvenc:0", True, parameters="-cq 20"))

        devices = (
            replace(legacy, preset="Film", parameters=None, custom_presets=(
                UserGpuEncodePreset("hevc", "Film", "-cq 18", "10"),
                UserGpuEncodePreset("hevc", "Film", "-cq 21", "8"),
                UserGpuEncodePreset("av1", "Film", "-cq 24", "10"),
            )),
            GpuEncodePreferences("qsv:1", preset="Film", custom_presets=(
                UserGpuEncodePreset("hevc", "Film", "-global_quality 19", "10"),
            )),
        )
        config = default_app_config()
        config = replace(config, encode=replace(config.encode, gpu_devices=devices))
        with tempfile.TemporaryDirectory() as temporary_directory:
            target = Path(temporary_directory) / "config.json"
            save_app_config(config, target)
            self.assertEqual(load_app_config(target).encode.gpu_devices, devices)

    def test_missing_config_is_created_from_packaged_template(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            target = root / "config.json"
            template = root / "config.default.json"
            expected = replace(
                default_app_config(),
                ui=UiPreferences(language="zh", theme="dark", font_size=12, opacity=88),
                paths=PathPreferences(remux_output="R:/Remux", encode_output="E:/Encode"),
            )
            save_app_config(expected, template)

            loaded = load_app_config(target, template)

            self.assertEqual(loaded, expected)
            self.assertEqual(load_app_config(target, template), expected)
            raw = target.read_bytes()
            self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))

    def test_invalid_existing_config_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            target = Path(temporary_directory) / "config.json"
            target.write_bytes(b"{broken")

            with self.assertRaisesRegex(ValueError, "Invalid JSON"):
                load_app_config(target)

            self.assertEqual(target.read_bytes(), b"{broken")

    def test_legacy_tool_paths_are_imported_once_and_resolve_relative_to_config(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            target = root / "config.json"
            legacy = root / "settings.py"
            target.write_text(json.dumps({"ui": {"language": "zh"}}), encoding="utf-8")
            legacy.write_text(
                "FFMPEG_PATH = 'my tools/ffmpeg'\n"
                "PLUGIN_PATH = _bundled_path('plugins', os.path.expanduser('~/test-plugins'))\n"
                "raise RuntimeError('Must only read paths')\n",
                encoding="utf-8",
            )
            observed = []
            config = load_app_config(target, settings_path=legacy, on_tools_initialized=observed.append)
            self.assertEqual(observed, [config])
            self.assertEqual(config.ui.language, "zh")
            self.assertEqual(set(config.tools), set(TOOL_PATH_NAMES))
            self.assertEqual(config.tools["FFMPEG_PATH"], "my tools/ffmpeg")
            self.assertEqual(Path(config.tools["PLUGIN_PATH"]), Path.home() / "test-plugins")

            legacy.unlink()
            self.assertEqual(load_app_config(target, settings_path=legacy), config)
            path = root / "my tools" / "ffmpeg"
            path.parent.mkdir()
            path.touch(mode=0o755)
            with using_tool_paths(resolve_tool_paths(config.tools, target.parent)):
                self.assertEqual(require_tool_path("FFMPEG_PATH"), str(path))
                path.unlink()
                with self.assertRaisesRegex(FileNotFoundError, "my tools"):
                    require_tool_path("FFMPEG_PATH")

    def test_source_discovers_tools_on_path_and_respects_explicit_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            first = root / "incomplete tools"
            suite = root / "complete tools"
            first.mkdir()
            suite.mkdir()
            suffix = ".exe" if os.name == "nt" else ""
            (first / f"mkvmerge{suffix}").touch(mode=0o755)
            for name in ("ffmpeg", "mkvmerge", "mkvinfo", "mkvpropedit", "mkvextract"):
                (suite / f"{name}{suffix}").touch(mode=0o755)

            config = load_app_config(root / "config.json")
            self.assertEqual(config.tools["FFMPEG_PATH"], "")
            with patch.dict(os.environ, {"PATH": os.pathsep.join(map(str, (first, suite)))}):
                resolved = resolve_tool_paths(config.tools, root)
                self.assertEqual(Path(resolved["FFMPEG_PATH"]), suite / f"ffmpeg{suffix}")
                self.assertEqual(resolved["MKVTOOLNIX_PATH"], str(suite))
                self.assertEqual(resolved["MKV_MERGE_PATH"], str(suite / f"mkvmerge{suffix}"))

                explicit = {"FFMPEG_PATH": "unavailable/ffmpeg", "MKVTOOLNIX_PATH": first.name}
                resolved = resolve_tool_paths(explicit, root)
                self.assertEqual(resolved["FFMPEG_PATH"], str(root / "unavailable/ffmpeg"))
                self.assertEqual(resolved["MKV_MERGE_PATH"], str(first / f"mkvmerge{suffix}"))

    def test_ui_save_keeps_tool_paths_edited_in_the_config_file(self) -> None:
        previous = default_app_config()
        edited = replace(previous, tools={**previous.tools, "X265_PATH": "bin/other-x265"})
        saved = replace(previous, ui=replace(previous.ui, font_size=13))
        with tempfile.TemporaryDirectory() as temporary_directory:
            target = Path(temporary_directory) / "config.json"
            save_app_config(edited, target)
            save_app_config(saved, target, preserve_tools=True)
            loaded = load_app_config(target)
        self.assertEqual(loaded.tools, edited.tools)
        self.assertEqual(loaded.ui.font_size, 13)

    def test_migrates_mkvtoolnix_paths_to_one_directory(self) -> None:
        legacy = {
            "MKV_MERGE_PATH": "media/mkvmerge",
            "MKV_INFO_PATH": "old/mkvinfo",
            "MKV_PROP_EDIT_PATH": "old/mkvpropedit",
            "MKV_EXTRACT_PATH": "old/mkvextract",
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            target = Path(temporary_directory) / "config.json"
            for explicit in ({}, {"MKVTOOLNIX_PATH": "custom"}):
                with self.subTest(explicit=explicit):
                    raw = {"tools": legacy | explicit, "ui": {"language": "zh"}}
                    target.write_text(json.dumps(raw), encoding="utf-8")
                    config = load_app_config(target)
                    directory = explicit.get("MKVTOOLNIX_PATH", "media")
                    self.assertEqual(config.tools["MKVTOOLNIX_PATH"], directory)
                    self.assertEqual(config.ui.language, "zh")
                    saved_tools = json.loads(target.read_text(encoding="utf-8"))["tools"]
                    self.assertFalse(legacy.keys() & saved_tools.keys())
                    resolved = resolve_tool_paths(config.tools, target.parent, discover=False)
                    for name, old_path in legacy.items():
                        filename = Path(old_path).name + (".exe" if os.name == "nt" else "")
                        self.assertEqual(resolved[name], str(target.parent / directory / filename))

    def test_legacy_edited_parameters_migrate_to_a_user_preset(self) -> None:
        config = app_config_from_mapping({
            "schema_version": 1,
            "encode": {
                "encoder": "x265",
                "preset": "Balanced",
                "preset_parameters": "--preset slow --crf 17",
            },
        })

        self.assertEqual(config.encode.preset, "Balanced Custom")
        self.assertEqual(config.encode.custom_presets, (
            UserEncodePreset(
                encoder="x265",
                name="Balanced Custom",
                parameters="--preset slow --crf 17",
            ),
        ))

    def test_saved_config_contains_only_user_defined_encode_presets(self) -> None:
        config = replace(
            default_app_config(),
            encode=replace(
                default_app_config().encode,
                preset="Cinema",
                custom_presets=(UserEncodePreset(
                    encoder="x265",
                    name="Cinema",
                    parameters="--preset slow --crf 17",
                ),),
            ),
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            target = Path(temporary_directory) / "config.json"

            save_app_config(config, target)
            raw = json.loads(target.read_text(encoding="utf-8"))

        self.assertNotIn("preset_parameters", raw["encode"])
        self.assertEqual(raw["encode"]["custom_presets"], [{
            "encoder": "x265",
            "name": "Cinema",
            "parameters": "--preset slow --crf 17",
        }])


if __name__ == "__main__":
    unittest.main()
