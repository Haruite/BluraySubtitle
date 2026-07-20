"""Characterization tests for configuration behavior that currently drives the GUI."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.runtime.gui_runtime_classes.bluray_subtitle_gui_entry import BluraySubtitleGUI
from src.runtime.gui_runtime_split import remux_and_episode_layout as remux_layout
from src.runtime.gui_runtime_split.remux_and_episode_layout import RemuxEpisodeLayoutMixin
from src.runtime.services_split.lifecycle_and_configuration import LifecycleConfigurationMixin
from src.runtime.services_split.misc_workflows import MiscWorkflowsMixin
from src.runtime.services_split.remux_and_episode_workflows import RemuxEpisodeWorkflowsMixin
from src.runtime.services_split.subtitle_and_chapter_pipeline import SubtitleChapterPipelineMixin


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


class _TableItem:
    def __init__(self, text: str) -> None:
        self._text = text

    def text(self) -> str:
        return self._text


class _PlaylistTable:
    def __init__(self, playlist_names: list[str]) -> None:
        self._playlist_names = playlist_names

    def rowCount(self) -> int:
        return len(self._playlist_names)

    def cellWidget(self, row: int, column: int) -> _CheckBox | None:
        return _CheckBox(True) if column == 3 else None

    def item(self, row: int, column: int) -> _TableItem | None:
        return _TableItem(self._playlist_names[row]) if column == 0 else None


class _MainPlaylistTable:
    def __init__(self, playlist_names: list[str], command_text: str) -> None:
        self._playlist_table = _PlaylistTable(playlist_names)
        self._command_editor = _TextEdit(command_text)

    def rowCount(self) -> int:
        return 1

    def item(self, row: int, column: int) -> _TableItem | None:
        return _TableItem(r'D:\Disc') if row == 0 and column == 0 else None

    def cellWidget(self, row: int, column: int) -> object | None:
        if row != 0:
            return None
        return self._playlist_table if column == 2 else self._command_editor


class ServiceRunConfigurationTests(unittest.TestCase):
    def test_series_run_uses_current_gui_configuration_and_returns_a_copy(self) -> None:
        current = {
            0: {
                "selected_mpls": "00001",
                "track_ids": ["4352", "4608"],
                "metadata": {"language": "eng"},
            }
        }
        applied: list[dict[int, dict[str, object]]] = []
        owner = SimpleNamespace(
            _last_configuration_34={0: {"selected_mpls": "stale"}},
            _is_movie_mode=lambda: False,
            _generate_configuration_from_ui_inputs=lambda: current,
            on_configuration=lambda configuration, update_sp_table=True: None,
            _apply_main_remux_cmds_to_configuration=lambda value: applied.append(value),
            t=lambda text: text,
        )

        configuration = BluraySubtitleGUI._configuration_for_service_run(owner)
        configuration[0]["track_ids"].append("4609")
        configuration[0]["metadata"]["language"] = "chi"

        self.assertEqual(current[0]["track_ids"], ["4352", "4608"])
        self.assertEqual(current[0]["metadata"], {"language": "eng"})
        self.assertEqual(applied, [current])
        self.assertIsNot(configuration, current)
        self.assertIsNot(configuration[0], current[0])

    def test_movie_run_refreshes_and_uses_current_movie_configuration(self) -> None:
        current = {0: {"selected_mpls": "movie"}}
        owner = SimpleNamespace(
            _movie_configuration={0: {"selected_mpls": "stale"}},
            _is_movie_mode=lambda: True,
            _apply_main_remux_cmds_to_configuration=lambda value: None,
            t=lambda text: text,
        )

        def refresh() -> None:
            owner._movie_configuration = current

        owner._refresh_movie_table2 = refresh

        configuration = BluraySubtitleGUI._configuration_for_service_run(owner)

        self.assertEqual(configuration, current)
        self.assertIsNot(configuration, current)

    def test_current_configuration_failure_is_not_replaced_by_old_snapshot(self) -> None:
        def fail() -> dict[int, dict[str, object]]:
            raise RuntimeError("invalid current state")

        owner = SimpleNamespace(
            _last_configuration_34={0: {"selected_mpls": "stale"}},
            _is_movie_mode=lambda: False,
            _generate_configuration_from_ui_inputs=fail,
            on_configuration=lambda configuration, update_sp_table=True: None,
            _apply_main_remux_cmds_to_configuration=lambda value: None,
            t=lambda text: text,
        )

        with self.assertRaisesRegex(RuntimeError, "invalid current state"):
            BluraySubtitleGUI._configuration_for_service_run(owner)

    def test_empty_current_configuration_is_an_error(self) -> None:
        owner = SimpleNamespace(
            _last_configuration_34={0: {"selected_mpls": "stale"}},
            _is_movie_mode=lambda: False,
            _generate_configuration_from_ui_inputs=lambda: {},
            on_configuration=lambda configuration, update_sp_table=True: None,
            _apply_main_remux_cmds_to_configuration=lambda value: None,
            t=lambda text: text,
        )

        with self.assertRaisesRegex(ValueError, "Task configuration is empty"):
            BluraySubtitleGUI._configuration_for_service_run(owner)


class MainRemuxCommandMappingTests(unittest.TestCase):
    def test_each_selected_main_playlist_maps_to_one_command_line(self) -> None:
        owner = SimpleNamespace(
            table1=_MainPlaylistTable(['00001.mpls', '00002.mpls'], 'command one\ncommand two'),
            t=lambda text: text,
        )

        with patch.multiple(
                remux_layout,
                QTableWidget=_PlaylistTable,
                QToolButton=_CheckBox,
                QPlainTextEdit=_TextEdit,
        ):
            result = RemuxEpisodeLayoutMixin._collect_main_remux_cmd_map_from_table1(owner)

        self.assertEqual(list(result.values()), ['command one', 'command two'])

    def test_command_count_must_match_selected_main_playlist_count(self) -> None:
        mismatches = [
            (['00001.mpls'], ''),
            (['00001.mpls'], 'command one\ncommand two'),
            (['00001.mpls', '00002.mpls'], 'command one'),
        ]

        with patch.multiple(
                remux_layout,
                QTableWidget=_PlaylistTable,
                QToolButton=_CheckBox,
                QPlainTextEdit=_TextEdit,
        ):
            for playlist_names, command_text in mismatches:
                with self.subTest(playlist_names=playlist_names, command_text=command_text):
                    owner = SimpleNamespace(
                        table1=_MainPlaylistTable(playlist_names, command_text),
                        t=lambda text: text,
                    )
                    with self.assertRaisesRegex(ValueError, 'must match'):
                        RemuxEpisodeLayoutMixin._collect_main_remux_cmd_map_from_table1(owner)


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

    def test_movie_output_name_comes_from_the_visible_table_cell(self) -> None:
        output_item = SimpleNamespace(text=lambda: "Custom Movie Name.mkv")
        table = SimpleNamespace(
            rowCount=lambda: 1,
            item=lambda row, column: output_item,
        )
        owner = SimpleNamespace(
            table2=table,
            get_selected_function_id=lambda: 3,
            _is_movie_mode=lambda: True,
        )

        self.assertEqual(
            BluraySubtitleGUI._get_episode_output_names_from_table2(owner),
            ["Custom Movie Name.mkv"],
        )


class ExplicitServiceConfigurationTests(unittest.TestCase):
    def test_episode_run_requires_explicit_configuration(self) -> None:
        with self.assertRaisesRegex(ValueError, "Task configuration is required"):
            RemuxEpisodeWorkflowsMixin._prepare_episode_run(
                SimpleNamespace(),
                "unused",
                None,
                False,
            )

    def test_subtitle_generation_requires_explicit_configuration(self) -> None:
        with self.assertRaisesRegex(ValueError, "Task configuration is required"):
            SubtitleChapterPipelineMixin.generate_bluray_subtitle(
                SimpleNamespace(),
                configuration=None,
            )

    def test_episode_run_rejects_invalid_chapter_range_before_writing(self) -> None:
        configuration = {
            0: {
                "bdmv_index": 1,
                "chapter_index": 4,
                "start_at_chapter": 4,
                "end_at_chapter": 4,
            }
        }

        with self.assertRaisesRegex(
            ValueError,
            "End chapter must be greater than start chapter in row 1",
        ):
            RemuxEpisodeWorkflowsMixin._prepare_episode_run(
                SimpleNamespace(),
                "unused",
                configuration,
                False,
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
