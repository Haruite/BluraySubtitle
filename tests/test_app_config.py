"""Focused contracts for persistent application settings."""

from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from src.core.app_config import (
    PathPreferences,
    UiPreferences,
    UserEncodePreset,
    app_config_from_mapping,
    default_app_config,
    load_app_config,
    save_app_config,
)


class AppConfigTests(unittest.TestCase):
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
