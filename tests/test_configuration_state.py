"""Captured configuration and scan lifecycle regressions."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.runtime.gui_runtime_classes.bluray_subtitle_gui_entry import BluraySubtitleGUI
from src.runtime.gui_runtime_split.scan_and_worker_hooks import ScanWorkerHooksMixin
from src.runtime.services_split.lifecycle_and_configuration import LifecycleConfigurationMixin


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
            _table2_labels_for_current_mode=lambda: (),
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


class ConfigurationRowTests(unittest.TestCase):
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


class SpScanLifecycleTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
