"""Characterization tests for configuration behavior that currently drives the GUI."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QTableWidgetItem

from src.core import ENCODE_SP_LABELS
from src.runtime.gui_runtime_classes.bluray_subtitle_gui_entry import BluraySubtitleGUI
from src.runtime.gui_runtime_split import configuration_and_modes as configuration_modes
from src.runtime.gui_runtime_split import remux_and_episode_layout as remux_layout
from src.runtime.gui_runtime_split.actions_and_file_dialogs import ActionsAndDialogsMixin
from src.runtime.gui_runtime_split.configuration_and_modes import ConfigurationModesMixin
from src.runtime.gui_runtime_split.remux_and_episode_layout import RemuxEpisodeLayoutMixin
from src.runtime.gui_runtime_split.scan_and_worker_hooks import ScanWorkerHooksMixin
from src.runtime.gui_runtime_split.sp_chapter_segment_logic import SpChapterSegmentLogicMixin
from src.runtime.gui_runtime_split.track_and_attachment_editing import TrackAttachmentEditingMixin
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
            on_configuration=Mock(),
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
        owner.on_configuration.assert_not_called()

    def test_movie_run_uses_current_visible_configuration_without_refresh(self) -> None:
        current = {0: {"selected_mpls": "movie"}}
        owner = SimpleNamespace(
            _movie_configuration=current,
            _is_movie_mode=lambda: True,
            _refresh_movie_table2=Mock(),
            _apply_main_remux_cmds_to_configuration=lambda value: None,
            t=lambda text: text,
        )

        configuration = BluraySubtitleGUI._configuration_for_service_run(owner)

        self.assertEqual(configuration, current)
        self.assertIsNot(configuration, current)
        owner._refresh_movie_table2.assert_not_called()

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
            0: {"start_at_chapter": 1, "end_at_chapter": 2},
            1: {"start_at_chapter": 1, "end_at_chapter": 2, "chapter_segments_fully_checked": False},
        }

        with patch.object(LifecycleConfigurationMixin, '_enrich_configuration_chapter_bounds'):
            result = LifecycleConfigurationMixin._finalize_configuration_episode_rows(configuration)

        self.assertTrue(result[0]["chapter_segments_fully_checked"])
        self.assertFalse(result[1]["chapter_segments_fully_checked"])

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


class GuiEncodeConfigurationTests(unittest.TestCase):
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


class ManualChapterEditingTests(unittest.TestCase):
    def test_extract_failure_stops_before_opening_the_chapter_editor(self) -> None:
        error_dialog = Mock()
        owner = SimpleNamespace(_show_error_dialog=error_dialog, t=lambda text: text)
        result = SimpleNamespace(returncode=2, stdout='extract failed', stderr='')

        with (
                patch('src.runtime.gui_runtime_split.track_and_attachment_editing.find_mkvtoolnix'),
                patch('src.runtime.gui_runtime_split.track_and_attachment_editing.MKV_EXTRACT_PATH', 'mkvextract'),
                patch('src.runtime.gui_runtime_split.track_and_attachment_editing.MKV_PROP_EDIT_PATH', 'mkvpropedit'),
                patch('src.runtime.gui_runtime_split.track_and_attachment_editing.run_command', return_value=result) as run,
        ):
            TrackAttachmentEditingMixin._edit_chapters_for_mkv(owner, 'episode.mkv')

        error_dialog.assert_called_once_with('extract failed')
        command = run.call_args.args[0]
        self.assertEqual(command[0], 'mkvextract')
        self.assertEqual(command[-3:-1], ['chapters', '--simple'])

    def test_attachment_extract_failure_reports_the_tool_output(self) -> None:
        error_dialog = Mock()
        open_folder = Mock()
        owner = SimpleNamespace(_show_error_dialog=error_dialog, open_folder_path=open_folder, t=lambda text: text)
        result = SimpleNamespace(returncode=2, stdout='attachment extract failed', stderr='')

        with (
                patch('src.runtime.gui_runtime_split.track_and_attachment_editing.find_mkvtoolnix'),
                patch('src.runtime.gui_runtime_split.track_and_attachment_editing.MKV_EXTRACT_PATH', 'mkvextract'),
                patch('src.runtime.gui_runtime_split.track_and_attachment_editing.tempfile.mkdtemp', return_value='tmp'),
                patch('src.runtime.gui_runtime_split.track_and_attachment_editing.run_command', return_value=result) as run,
        ):
            TrackAttachmentEditingMixin._extract_attachment_to_temp_and_open(
                owner, 'episode.mkv', '3', 'cover.jpg'
            )

        error_dialog.assert_called_once_with('attachment extract failed')
        open_folder.assert_not_called()
        self.assertEqual(run.call_args.args[0][-2:], ['attachments', '3:tmp\\cover.jpg'])

    def test_track_extract_opens_only_the_created_output(self) -> None:
        error_dialog = Mock()
        open_folder = Mock()
        owner = SimpleNamespace(_show_error_dialog=error_dialog, open_folder_path=open_folder, t=lambda text: text)
        result = SimpleNamespace(returncode=0, stdout='', stderr='')

        with (
                patch('src.runtime.gui_runtime_split.track_and_attachment_editing.find_mkvtoolnix'),
                patch('src.runtime.gui_runtime_split.track_and_attachment_editing.MKV_EXTRACT_PATH', 'mkvextract'),
                patch('src.runtime.gui_runtime_split.track_and_attachment_editing.tempfile.mkdtemp', return_value='tmp'),
                patch('src.runtime.gui_runtime_split.track_and_attachment_editing.os.path.isfile', return_value=True),
                patch('src.runtime.gui_runtime_split.track_and_attachment_editing.run_command', return_value=result) as run,
        ):
            TrackAttachmentEditingMixin._extract_track_to_temp_and_open(owner, 'episode.mkv', 2, 'A_FLAC')

        error_dialog.assert_not_called()
        open_folder.assert_called_once_with('tmp')
        self.assertEqual(run.call_args.args[0][-2:], ['tracks', '2:tmp\\track2.flac'])


class SpScanLifecycleTests(unittest.TestCase):
    def test_series_refresh_scans_only_the_final_gui_configuration(self) -> None:
        generated_configuration = {0: {'selected_mpls': 'generated'}}
        current_configuration = {0: {'selected_mpls': 'current'}}
        configuration_calls = []
        owner = SimpleNamespace(
            get_selected_function_id=lambda: 3,
            _sync_chapter_tail_trim_episode=lambda: None,
            bdmv_folder_path=SimpleNamespace(text=lambda: r'C:\Disc'),
            table1=SimpleNamespace(rowCount=lambda: 1),
            table2=SimpleNamespace(rowCount=lambda: 1, item=lambda *_args: None),
            _is_movie_mode=lambda: False,
            checkbox1=SimpleNamespace(isChecked=lambda: False),
            _get_approx_episode_duration_seconds=lambda: 1440.0,
            get_selected_mpls_no_ext=lambda: [(r'C:\Disc', r'C:\Disc\BDMV\PLAYLIST\00000')],
            _generate_configuration_from_ui_inputs=lambda: current_configuration,
            on_configuration=lambda configuration, update_sp_table=True: configuration_calls.append(
                (configuration, update_sp_table)
            ),
        )
        service = SimpleNamespace(
            generate_configuration_from_selected_mpls=lambda _selected: generated_configuration
        )

        with patch.object(configuration_modes, 'BluraySubtitle', return_value=service):
            ConfigurationModesMixin._full_refresh_remux_encode_tables_for_mode(owner)

        self.assertEqual(configuration_calls, [
            (generated_configuration, False),
            (current_configuration, True),
        ])

    def test_finished_old_scan_does_not_clear_the_current_scan(self) -> None:
        old_thread = object()
        current_thread = object()
        current_worker = object()
        cancel_event = object()
        dismiss_progress = Mock()
        owner = SimpleNamespace(
            _sp_scan_thread=current_thread,
            _sp_scan_worker=current_worker,
            _sp_scan_cancel_event=cancel_event,
            _sp_scan_in_progress=True,
            sender=lambda: old_thread,
            _dismiss_sp_scan_progress_ui=dismiss_progress,
        )

        ScanWorkerHooksMixin._on_sp_scan_thread_finished(owner)

        self.assertTrue(owner._sp_scan_in_progress)
        self.assertIs(owner._sp_scan_thread, current_thread)
        dismiss_progress.assert_not_called()

        owner.sender = lambda: current_thread
        ScanWorkerHooksMixin._on_sp_scan_thread_finished(owner)

        self.assertFalse(owner._sp_scan_in_progress)
        self.assertIsNone(owner._sp_scan_thread)
        self.assertIsNone(owner._sp_scan_worker)
        self.assertIsNone(owner._sp_scan_cancel_event)
        dismiss_progress.assert_called_once()


    def test_remux_waits_for_the_current_sp_scan(self) -> None:
        remux = Mock()
        progress = Mock()
        button = Mock()
        owner = SimpleNamespace(
            _current_cancel_event=None,
            _sp_scan_thread=object(),
            _sp_scan_completed=False,
            _sp_scan_pending_function_id=None,
            exe_button=button,
            get_selected_function_id=lambda: 3,
            _update_exe_button_progress=progress,
            remux_episodes=remux,
        )

        ActionsAndDialogsMixin.main(owner)

        self.assertEqual(owner._sp_scan_pending_function_id, 3)
        button.setEnabled.assert_called_once_with(False)
        progress.assert_called_once_with(value=0, text='Waiting for SP track scan')
        remux.assert_not_called()

    def test_missing_selected_sp_tracks_fail_without_restarting_the_full_scan(self) -> None:
        remux = Mock()
        start_scan = Mock()
        error_dialog = Mock()
        owner = SimpleNamespace(
            _current_cancel_event=None,
            _sp_scan_thread=None,
            _sp_scan_completed=True,
            _sp_scan_error='',
            _sp_scan_pending_function_id=None,
            _track_selection_config={},
            table3=SimpleNamespace(rowCount=lambda: 1),
            get_selected_function_id=lambda: 3,
            _table3_get_sp_entry_for_row=lambda _row: {
                'bdmv_index': 1,
                'mpls_file': '00001.mpls',
                'm2ts_file': '00001.m2ts',
                'output_name': 'SPs/00001.mkv',
                'selected': True,
            },
            _show_error_dialog=error_dialog,
            t=lambda text: text,
            remux_episodes=remux,
            _start_sp_table_scan=start_scan,
        )

        ActionsAndDialogsMixin.main(owner)

        start_scan.assert_not_called()
        error_dialog.assert_called_once_with('SP row 1 has no captured track selection')
        remux.assert_not_called()

    def test_stale_sp_scan_boolean_does_not_block_remux(self) -> None:
        remux = Mock()
        owner = SimpleNamespace(
            _current_cancel_event=None,
            _sp_scan_thread=None,
            _sp_scan_completed=False,
            _sp_scan_in_progress=True,
            get_selected_function_id=lambda: 3,
            remux_episodes=remux,
        )

        ActionsAndDialogsMixin.main(owner)

        remux.assert_called_once_with()

    def test_remux_source_encode_does_not_wait_for_a_bdmv_sp_scan(self) -> None:
        encode = Mock()
        owner = SimpleNamespace(
            _current_cancel_event=None,
            _encode_input_mode='remux',
            _sp_scan_thread=object(),
            _sp_scan_error='stale BDMV scan failure',
            get_selected_function_id=lambda: 4,
            encode_bluray=encode,
        )

        ActionsAndDialogsMixin.main(owner)

        encode.assert_called_once_with()

    def test_failed_scan_state_blocks_later_remux(self) -> None:
        remux = Mock()
        error_dialog = Mock()
        owner = SimpleNamespace(
            _current_cancel_event=None,
            _sp_scan_thread=None,
            _sp_scan_completed=False,
            _sp_scan_error='scan traceback',
            get_selected_function_id=lambda: 3,
            _show_error_dialog=error_dialog,
            t=lambda text: text,
            remux_episodes=remux,
        )

        ActionsAndDialogsMixin.main(owner)

        error_dialog.assert_called_once_with('SP track scan failed; refresh the source before starting the task')
        remux.assert_not_called()

    def test_result_from_an_old_sp_worker_is_ignored(self) -> None:
        old_worker = object()
        owner = SimpleNamespace(_sp_scan_worker=object(), sender=lambda: old_worker)

        ScanWorkerHooksMixin._on_sp_table_scan_result(owner, 0, False, '', {})

    def test_scan_result_uses_the_worker_track_selection_without_reprobing(self) -> None:
        class Table:
            def __init__(self) -> None:
                self.items: dict[tuple[int, int], QTableWidgetItem] = {}

            def rowCount(self) -> int:
                return 1

            def item(self, row: int, column: int) -> QTableWidgetItem | None:
                return self.items.get((row, column))

            def setItem(self, row: int, column: int, item: QTableWidgetItem | None) -> None:
                if item is not None:
                    self.items[(row, column)] = item

            def cellWidget(self, _row: int, _column: int) -> None:
                return None

        table = Table()
        table.setItem(0, ENCODE_SP_LABELS.index('select'), QTableWidgetItem(''))
        table.setItem(0, ENCODE_SP_LABELS.index('output_name'), QTableWidgetItem('SP.mkv'))
        current_worker = object()
        owner = SimpleNamespace(
            _sp_scan_worker=current_worker,
            _sp_scan_in_progress=True,
            _sp_scan_progress_rows_seen=set(),
            _sp_scan_progress_total=1,
            _sp_scan_progress_bar=None,
            _track_selection_config={},
            table3=table,
            sender=lambda: current_worker,
            get_selected_function_id=lambda: 3,
            _sync_sp_table_row_m2ts_column_from_detail=Mock(),
            select_all_tracks_checkbox=SimpleNamespace(isChecked=lambda: False),
        )

        ScanWorkerHooksMixin._on_sp_table_scan_result(
            owner,
            0,
            False,
            '',
            {
                'sp_key': 'sp::1::mpls::00001.mpls',
                'tracks': {'audio': ['1'], 'subtitle': ['2']},
            },
        )

        self.assertEqual(
            owner._track_selection_config['sp::1::mpls::00001.mpls'],
            {'audio': ['1'], 'subtitle': ['2']},
        )

    def test_output_name_failure_keeps_the_sp_scan_invalid(self) -> None:
        current_worker = object()
        error_dialog = Mock()
        owner = SimpleNamespace(
            _sp_scan_worker=current_worker,
            _sp_scan_completed=False,
            sender=lambda: current_worker,
            _recompute_sp_output_names=Mock(side_effect=RuntimeError('invalid SP output')),
            _show_error_dialog=error_dialog,
        )

        SpChapterSegmentLogicMixin._on_sp_table_scan_finished(owner)

        self.assertFalse(owner._sp_scan_completed)
        self.assertEqual(owner._sp_scan_error, 'invalid SP output')
        error_dialog.assert_called_once_with('invalid SP output')

    def test_successful_sp_scan_resumes_the_queued_remux_once(self) -> None:
        current_thread = object()
        resume = Mock()
        reset_button = Mock()
        owner = SimpleNamespace(
            _sp_scan_thread=current_thread,
            _sp_scan_worker=object(),
            _sp_scan_cancel_event=object(),
            _sp_scan_in_progress=True,
            _sp_scan_completed=True,
            _sp_scan_pending_function_id=3,
            sender=lambda: current_thread,
            _dismiss_sp_scan_progress_ui=Mock(),
            _reset_exe_button=reset_button,
            get_selected_function_id=lambda: 3,
            main=resume,
        )

        with patch('src.runtime.gui_runtime_split.scan_and_worker_hooks.QTimer.singleShot') as single_shot:
            ScanWorkerHooksMixin._on_sp_scan_thread_finished(owner)

        self.assertIsNone(owner._sp_scan_pending_function_id)
        reset_button.assert_called_once_with()
        single_shot.assert_called_once_with(0, resume)

    def test_failed_sp_scan_does_not_resume_the_queued_remux(self) -> None:
        current_thread = object()
        owner = SimpleNamespace(
            _sp_scan_thread=current_thread,
            _sp_scan_worker=object(),
            _sp_scan_cancel_event=object(),
            _sp_scan_in_progress=True,
            _sp_scan_completed=False,
            _sp_scan_pending_function_id=3,
            sender=lambda: current_thread,
            _dismiss_sp_scan_progress_ui=Mock(),
            _reset_exe_button=Mock(),
            get_selected_function_id=lambda: 3,
            main=Mock(),
        )

        with patch('src.runtime.gui_runtime_split.scan_and_worker_hooks.QTimer.singleShot') as single_shot:
            ScanWorkerHooksMixin._on_sp_scan_thread_finished(owner)

        single_shot.assert_not_called()
        owner.main.assert_not_called()

    def test_finished_old_sp_worker_does_not_complete_the_current_scan(self) -> None:
        old_worker = object()
        current_worker = object()
        recompute = Mock()
        owner = SimpleNamespace(
            _sp_scan_worker=current_worker,
            _sp_scan_completed=False,
            sender=lambda: old_worker,
            _recompute_sp_output_names=recompute,
        )

        SpChapterSegmentLogicMixin._on_sp_table_scan_finished(owner)

        self.assertFalse(owner._sp_scan_completed)
        recompute.assert_not_called()

        owner.sender = lambda: current_worker
        SpChapterSegmentLogicMixin._on_sp_table_scan_finished(owner)

        self.assertTrue(owner._sp_scan_completed)
        recompute.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
