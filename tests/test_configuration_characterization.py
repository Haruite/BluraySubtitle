"""Characterization tests for configuration behavior that currently drives the GUI."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from src.runtime.gui_runtime_classes.bluray_subtitle_gui_entry import BluraySubtitleGUI
from src.runtime.services_split.lifecycle_and_configuration import LifecycleConfigurationMixin
from src.runtime.services_split.misc_workflows import MiscWorkflowsMixin


class _Combo:
    def __init__(self, text: str = "", data: object = None) -> None:
        self._text = text
        self._data = data

    def currentText(self) -> str:
        return self._text

    def currentData(self) -> object:
        return self._data


class _CheckBox:
    def __init__(self, checked: bool) -> None:
        self._checked = checked

    def isChecked(self) -> bool:
        return self._checked


class _TextEdit:
    def __init__(self, text: str) -> None:
        self._text = text

    def toPlainText(self) -> str:
        return self._text


class ConfigurationSnapshotTests(unittest.TestCase):
    def test_service_snapshot_is_a_recursive_copy(self) -> None:
        source = {
            0: {
                "selected_mpls": "00001",
                "track_ids": ["4352", "4608"],
                "metadata": {"language": "eng"},
            }
        }
        owner = SimpleNamespace(_last_configuration_34=source)

        snapshot = BluraySubtitleGUI._configuration_snapshot_for_service_run(owner)
        snapshot[0]["track_ids"].append("4609")
        snapshot[0]["metadata"]["language"] = "chi"

        self.assertEqual(source[0]["track_ids"], ["4352", "4608"])
        self.assertEqual(source[0]["metadata"], {"language": "eng"})
        self.assertIsNot(snapshot, source)
        self.assertIsNot(snapshot[0], source[0])

    def test_service_snapshot_returns_empty_dict_without_nonempty_mapping(self) -> None:
        self.assertEqual(
            BluraySubtitleGUI._configuration_snapshot_for_service_run(SimpleNamespace()),
            {},
        )
        self.assertEqual(
            BluraySubtitleGUI._configuration_snapshot_for_service_run(
                SimpleNamespace(_last_configuration_34=[])
            ),
            {},
        )


class ConfigurationRowTests(unittest.TestCase):
    def test_chapter_segment_default_preserves_explicit_false(self) -> None:
        configuration = {
            0: {"selected_mpls": "00001"},
            1: {"selected_mpls": "00002", "chapter_segments_fully_checked": False},
        }

        LifecycleConfigurationMixin._configuration_default_chapter_segments_checked(configuration)

        self.assertTrue(configuration[0]["chapter_segments_fully_checked"])
        self.assertFalse(configuration[1]["chapter_segments_fully_checked"])

    def test_invalid_chapter_ranges_are_removed_and_rows_reindexed(self) -> None:
        configuration = {
            3: {"name": "kept-open-end", "chapter_index": 4, "end_at_chapter": 0},
            8: {"name": "removed-equal", "start_at_chapter": 3, "end_at_chapter": 3},
            9: {"name": "removed-reversed", "start_at_chapter": 5, "end_at_chapter": 2},
            12: {"name": "kept", "start_at_chapter": 2, "end_at_chapter": 6},
            14: {"name": "kept-unparseable", "start_at_chapter": "chapter", "end_at_chapter": 7},
        }

        result = LifecycleConfigurationMixin._configuration_drop_invalid_episode_rows(configuration)

        self.assertEqual(list(result), [0, 1, 2])
        self.assertEqual(
            [row["name"] for row in result.values()],
            ["kept-open-end", "kept", "kept-unparseable"],
        )
        self.assertIsNot(result[0], configuration[3])

    def test_config_input_diff_prioritizes_segments_then_start_then_end(self) -> None:
        base = {
            "segments": {"00001": [True, True]},
            "start": {0: 1, 1: 4},
            "end": {0: 4, 1: 8},
        }
        segment_change = {
            "segments": {"00001": [True, False]},
            "start": {0: 2, 1: 4},
            "end": {0: 5, 1: 8},
        }
        start_change = {**base, "start": {0: 1, 1: 5}, "end": {0: 5, 1: 8}}
        end_change = {**base, "end": {0: 4, 1: 9}}

        self.assertEqual(
            BluraySubtitleGUI._diff_config_inputs(None, base, segment_change),
            ("segments", 0),
        )
        self.assertEqual(
            BluraySubtitleGUI._diff_config_inputs(None, base, start_change),
            ("start", 1),
        )
        self.assertEqual(
            BluraySubtitleGUI._diff_config_inputs(None, base, end_change),
            ("end", 1),
        )
        self.assertEqual(
            BluraySubtitleGUI._diff_config_inputs(None, base, dict(base)),
            ("none", -1),
        )

    def test_selected_mpls_are_grouped_by_adjacent_folder_runs(self) -> None:
        selected = [
            (r"C:\DiscA", "00001"),
            (r"C:\DiscA", "00002"),
            (r"C:\DiscB", "00003"),
            (r"C:\DiscA", "00004"),
        ]

        groups = MiscWorkflowsMixin._group_selected_mpls_by_folder_runs(selected)

        self.assertEqual([len(group) for group in groups], [2, 1, 1])
        self.assertEqual(groups[2], [(r"C:\DiscA", "00004")])

    def test_episode_output_names_follow_global_and_per_volume_order(self) -> None:
        configuration = {
            0: {"bdmv_index": 2, "chapter_index": 1, "disc_output_name": "DiscB"},
            1: {"bdmv_index": 1, "chapter_index": 5, "disc_output_name": "DiscA"},
            2: {"bdmv_index": 1, "chapter_index": 1, "disc_output_name": "DiscA"},
        }

        result = BluraySubtitleGUI._build_episode_output_name_map(object(), configuration)

        self.assertEqual(
            result,
            {
                0: "EP1 DiscB_BD_Vol_002-001.mkv",
                1: "EP2 DiscA_BD_Vol_001-002.mkv",
                2: "EP3 DiscA_BD_Vol_001-001.mkv",
            },
        )


class GuiEncodeConfigurationTests(unittest.TestCase):
    def test_function_selection_uses_visible_tab_order(self) -> None:
        tabbar = SimpleNamespace(currentIndex=lambda: 2)
        owner = SimpleNamespace(
            function_tabbar=tabbar,
            _function_id_order=[1, 3, 5, 4],
            _selected_function_id=1,
        )

        self.assertEqual(BluraySubtitleGUI.get_selected_function_id(owner), 5)

    def test_function_selection_falls_back_to_saved_id(self) -> None:
        tabbar = SimpleNamespace(currentIndex=lambda: -1)
        owner = SimpleNamespace(function_tabbar=tabbar, _selected_function_id=4)

        self.assertEqual(BluraySubtitleGUI.get_selected_function_id(owner), 4)

    def test_encode_tool_and_depth_follow_current_mode_controls(self) -> None:
        encode_owner = SimpleNamespace(
            get_selected_function_id=lambda: 4,
            encode_tool_combo=_Combo("x264"),
            encode_bit_depth_combo=_Combo(data=8),
        )
        diy_h264_owner = SimpleNamespace(
            get_selected_function_id=lambda: 5,
            _track_convert_config={"00001": {"4113": "h264(encoded)"}},
        )
        diy_hevc_owner = SimpleNamespace(
            get_selected_function_id=lambda: 5,
            _track_convert_config={"00001": {"4113": "hevc"}},
        )

        self.assertEqual(
            BluraySubtitleGUI._current_encode_tool_and_depth(encode_owner),
            ("x264", "8"),
        )
        self.assertEqual(
            BluraySubtitleGUI._current_encode_tool_and_depth(diy_h264_owner),
            ("x264", "8"),
        )
        self.assertEqual(
            BluraySubtitleGUI._current_encode_tool_and_depth(diy_hevc_owner),
            ("x265", "10"),
        )

    def test_compatibility_parameters_only_apply_to_diy(self) -> None:
        encode_owner = self._encode_parameter_owner(4, "x265", True, "--crf 18")
        unchecked_owner = self._encode_parameter_owner(5, "x265", False, " --crf 19 ")

        self.assertEqual(BluraySubtitleGUI._effective_encode_params(encode_owner), "--crf 18")
        self.assertEqual(BluraySubtitleGUI._effective_encode_params(unchecked_owner), "--crf 19")

    def test_diy_compatibility_parameters_follow_selected_encoder(self) -> None:
        x264_owner = self._encode_parameter_owner(5, "x264", True, "--crf 18 --profile custom")
        x265_owner = self._encode_parameter_owner(5, "x265", True, "--crf 18")
        av1_owner = self._encode_parameter_owner(5, "svtav1", True, "--preset 4")

        self.assertEqual(
            BluraySubtitleGUI._effective_encode_params(x264_owner),
            "--crf 18 --profile custom --level 4.1 --keyint 24",
        )
        self.assertEqual(
            BluraySubtitleGUI._effective_encode_params(x265_owner),
            "--crf 18 --profile main10 --level-idc 4.1 --vbv-maxrate 30000 --vbv-bufsize 30000",
        )
        self.assertEqual(BluraySubtitleGUI._effective_encode_params(av1_owner), "--preset 4")

    @staticmethod
    def _encode_parameter_owner(
        function_id: int,
        tool: str,
        compatibility_checked: bool,
        params: str,
    ) -> SimpleNamespace:
        return SimpleNamespace(
            x265_params_edit=_TextEdit(params),
            use_bluray_compat_params_checkbox=_CheckBox(compatibility_checked),
            get_selected_function_id=lambda: function_id,
            encode_tool_combo=_Combo(tool),
            _append_compat_arg_if_missing=BluraySubtitleGUI._append_compat_arg_if_missing,
        )


if __name__ == "__main__":
    unittest.main()
