"""IDE base contracts for split GUI mixins.

The declarations are verified against the mixins by
`tools/check_split_contracts.py`.
"""

from __future__ import annotations

from typing import Any, Optional

from PyQt6.QtCore import QPoint, Qt, QProcess
from PyQt6.QtWidgets import QWidget, QComboBox, QPlainTextEdit, QTableWidgetItem, QTableWidget, QToolButton


class BluraySubtitleGuiBase(QWidget):
    """Base class with declared instance attrs and method contracts."""

    __init_gui_base_attrs__: bool = False

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize QWidget; optionally inject declared attrs for tooling."""
        super().__init__(*args, **kwargs)
        if not bool(getattr(type(self), "__init_gui_base_attrs__", False)):
            return
        self._bottom_message_remaining = None
        self._bottom_message_text = None
        self._bottom_message_timer = None
        self._chapter_change_reason = None
        self._chapter_checkbox_states = None
        self._chapter_combo_debounce = None
        self._chapter_combo_force_mode = None
        self._chapter_pending_append_episode = None
        self._chapter_pending_remove_row = None
        self._chapter_thread = None
        self._chapter_worker = None
        self._colorful_opacity = None
        self._close_pending = None
        self._current_cancel_event = None
        self._encode_input_mode = None
        self._encode_preset_params = None
        self._encode_setting_updating = None
        self._svtav1_preset_params = None
        self._x264_preset_params = None
        self._x265_preset_params = None
        self._encode_thread = None
        self._encode_worker = None
        self._exe_button_default_text = None
        self._exe_button_progress_text = None
        self._exe_button_progress_value = None
        self._app_config = None
        self._app_config_errors = None
        self._app_config_load_failed = None
        self._app_config_path = None
        self._auto_output_folders = None
        self._bdmv_source_state_path = None
        self._language_code = None
        self._language_updating = None
        self._last_config_inputs = None
        self._last_configuration_34 = None
        self._merge_thread = None
        self._merge_worker = None
        self._mode_group = None
        self._movie_configuration = None
        self._pending_chapter_combo_index = None
        self._pending_subtitle_folder = None
        self._remux_cmd_refresh_timer = None
        self._remux_thread = None
        self._remux_worker = None
        self._selected_function_id = None
        self._output_folder_values = None
        self._window_geometry_restored = None
        self._selected_main_mpls_prev = None
        self._sp_index_by_bdmv = None
        self._sp_scan_cancel_event = None
        self._sp_scan_completed = None
        self._sp_scan_error = None
        self._sp_scan_in_progress = None
        self._sp_scan_pending_function_id = None
        self._sp_scan_progress_bar = None
        self._sp_scan_progress_dialog = None
        self._sp_scan_progress_done = None
        self._sp_scan_progress_rows_seen = None
        self._sp_scan_progress_show_timer = None
        self._sp_scan_progress_total = None
        self._retired_sp_scans = None
        self._sp_scan_thread = None
        self._sp_scan_worker = None
        self._sub_pack_group = None
        self._sub_pack_row = None
        self._subtitle_scan_cancel_event = None
        self._subtitle_scan_debounce = None
        self._subtitle_scan_progress_dialog = None
        self._subtitle_scan_seq = None
        self._subtitle_scan_show_timer = None
        self._subtitle_scan_thread = None
        self._subtitle_scan_worker = None
        self._theme_mode = None
        self._available_track_selection_config = None
        self._track_selection_config = None
        self._track_convert_config = None
        self._track_lossless_audio_config = None
        self._track_language_config = None
        self._updating_sp_table = None
        self._vsedit_edit_sessions = None
        self._vsedit_preview_sessions = None
        self.altered = None
        self.approx_episode_minutes_combo = None
        self.bdmv_folder_path = None
        self.bluray_path_box = None
        self.bottom_message_label = None
        self.checkbox1 = None
        self.encode_box = None
        self.encode_source_bdmv_radio = None
        self.encode_source_remux_radio = None
        self.encode_source_row = None
        self.diy_mode_row = None
        self.diy_mode_label = None
        self.diy_simple_radio = None
        self.diy_advanced_radio = None
        self.episode_length_container = None
        self.episode_mode_row = None
        self.exe_button = None
        self.function_button = None
        self.function_tabbar = None
        self.label1 = None
        self.label1_container = None
        self.label2 = None
        self.label2_container = None
        self.language_combo = None
        self.language_label = None
        self.layout = None
        self.merge_options_row = None
        self.movie_mode_radio = None
        self.opacity_label = None
        self.opacity_slider = None
        self.settings_button = None
        self.output_folder_path = None
        self.output_folder_row = None
        self.remux_folder_path = None
        self.remux_path_box = None
        self.select_all_tracks_checkbox = None
        self.select_all_tracks_row = None
        self.trim_copyright_tail_checkbox = None
        self.mux_dolby_vision_checkbox = None
        self.remux_flac_checkbox = None
        self.series_mode_radio = None
        self.sub_check_state = None
        self.sub_pack_external_radio = None
        self.sub_pack_hard_radio = None
        self.sub_pack_soft_radio = None
        self.subtitle_folder_path = None
        self.subtitle_suffix_combo = None
        self.subtitle_suffix_label = None
        self.subtitle_tables_splitter = None
        self.simple_diy_sub_lang_combo = None
        self.simple_diy_sub_lang_label = None
        self.simple_diy_add_sub_row_btn = None
        self.simple_diy_remove_sub_row_btn = None
        self.simple_diy_extra_sub_rows = None
        self.subtitle_label_row = None
        self._simple_diy_subtitle_config = None
        self.track_scope_row = None
        self.track_scope_main_radio = None
        self.track_scope_all_radio = None
        self.table1 = None
        self.table2 = None
        self.table3 = None
        self.tables_splitter = None
        self.theme_combo = None
        self.theme_label = None
        self.vspipe_mode_combo = None
        self.use_getnative_checkbox = None
        self.auto_crop_black_borders_checkbox = None
        self.output_comparison_checkbox = None
        self.frame_check_checkbox = None
        self.vpy_processing_row = None
        self.vpy_denoise_strength_spin = None
        self.vpy_dehalo_strength_spin = None
        self.vpy_dering_strength_spin = None
        self.vpy_deband_strength_spin = None
        self.vpy_antialiasing_strength_spin = None
        self.encode_tool_combo = None
        self.encode_tool_label = None
        self.encode_source_label = None
        self.encode_bit_depth_combo = None
        self.encode_bit_depth_label = None
        self.diy_bd_encode_hint_label = None
        self.x265_mode_combo = None
        self.x265_mode_label = None
        self.x265_params_edit = None
        self.x265_params_label = None
        self.x265_preset_combo = None

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        for _name, _obj in BluraySubtitleGuiBase.__dict__.items():
            if _name in ('__init__', '__init_subclass__'):
                continue
            _fn = None
            if isinstance(_obj, staticmethod):
                _fn = _obj.__func__
            elif isinstance(_obj, classmethod):
                _fn = _obj.__func__
            elif callable(_obj):
                _fn = _obj
            if _fn is not None:
                setattr(_fn, "__gui_base_stub__", True)

    # BEGIN GENERATED MIXIN CONTRACTS
    def _add_or_update_table3_mpls_as_sp(self, bdmv_index: int, mpls_path: str):
        raise NotImplementedError

    def _add_sp_entries_for_unchecked_segments(self, mpls_path: str, segments: list[tuple[int, int]], bdmv_index: int, chapter_to_m2ts: dict=None):
        raise NotImplementedError

    def _adjust_combo_width_to_contents(self, combo: QComboBox, padding: int=44, min_width: int=80, max_width: int=520):
        raise NotImplementedError

    def _all_track_ids_from_streams(self, streams: list[dict[str, object]]) -> tuple[list[str], list[str]]:
        raise NotImplementedError

    @staticmethod
    def _append_compat_arg_if_missing(base: str, option_name: str, option_value: str='') -> str:
        raise NotImplementedError

    def _apply_configuration_after_subtitle_change(self, sub_files: list[str]) -> None:
        raise NotImplementedError

    def _apply_encode_codec_slot_visibility(self) -> None:
        raise NotImplementedError

    def _apply_encode_input_mode_ui(self):
        raise NotImplementedError

    def _apply_end_combo_min_constraint(self, combo: QComboBox, min_allowed: int):
        raise NotImplementedError

    def _apply_episode_copyright_trim_to_configuration(self, configuration: dict[int, dict[str, int | str]], enabled: bool) -> None:
        raise NotImplementedError

    def _apply_episode_mode_to_table2(self):
        raise NotImplementedError

    def _apply_hidden_m2ts_file_detail_columns(self):
        raise NotImplementedError

    def _apply_language(self, language_code: str):
        raise NotImplementedError

    def _apply_main_remux_cmds_to_configuration(self, configuration: dict[int, dict[str, int | str]]):
        raise NotImplementedError

    def _apply_movie_mode_table2_chapter_widgets(self, row: int, labels: list[str], mpls_no_ext: str, *, connect_end_handler: bool=False) -> None:
        raise NotImplementedError

    def _apply_saved_encode_defaults(self) -> None:
        raise NotImplementedError

    def _apply_saved_ui_preferences(self) -> None:
        raise NotImplementedError

    def _apply_select_all_tracks_to_main_and_sp(self):
        raise NotImplementedError

    def _apply_start_chapter_constraints(self, labels: list[str]):
        raise NotImplementedError

    def _apply_table3_uncheck_rows_covered_by_table2(self) -> None:
        raise NotImplementedError

    def _apply_theme(self, mode: str):
        raise NotImplementedError

    def _apply_ui_font_size(self, point_size: int):
        raise NotImplementedError

    def _bdmv_index_for_table1_folder_norm(self, folder_norm: str) -> int:
        raise NotImplementedError

    def _bdmv_root_from_mpls_path(self, mpls_path: str) -> str:
        raise NotImplementedError

    def _bdmv_to_first_main_mpls_from_table1(self) -> dict[int, str]:
        raise NotImplementedError

    def _begin_delayed_busy(self, label_text: str, minimum_delay_sec: float=2.0) -> dict[str, object]:
        raise NotImplementedError

    def _build_end_chapter_combo(self, rows: int, has_beginning: bool, start_value: int, selected_value: int=0) -> QComboBox:
        raise NotImplementedError

    def _build_episode_output_name_map(self, configuration: dict[int, dict[str, int | str]]) -> dict[int, str]:
        raise NotImplementedError

    def _build_main_remux_cmd_template(self, mpls_path: str, bdmv_index: int, root: str, *, name_seq_index: int=0, name_seq_total: int=1) -> str:
        raise NotImplementedError

    def _cache_available_track_ids(self, key: str, streams: list[dict[str, object]]) -> dict[str, list[str]]:
        raise NotImplementedError

    def _captured_audio_encoding_settings(self) -> AudioEncodingSettings:
        raise NotImplementedError

    def _chapter_label_text(self, value: int, rows: int, has_beginning: bool, for_end: bool=False) -> str:
        raise NotImplementedError

    def _chapter_node_data(self, mpls_path_no_ext: str) -> dict[str, object]:
        raise NotImplementedError

    def _closest_endpoint(self, start_idx: int, target_sec: float, rows: int, offsets: dict[int, float], m2ts: dict[int, str], checked: list[bool], approx_episode_sec: Optional[float]=None) -> int:
        raise NotImplementedError

    def _collect_config_inputs(self) -> dict[str, object]:
        raise NotImplementedError

    def _collect_main_remux_cmd_map_from_table1(self) -> dict[str, str]:
        raise NotImplementedError

    def _configuration_for_service_run(self) -> dict[int, dict[str, int | str]]:
        raise NotImplementedError

    def _conversion_options_for_stream(self, stream: dict[str, object]) -> list[str]:
        raise NotImplementedError

    def _create_main_remux_cmd_editor(self, text: str, parent: Optional[QWidget]=None) -> QPlainTextEdit:
        raise NotImplementedError

    def _create_temp_edit_vpy_from_default(self, video_path: str, subtitle_path: str) -> str:
        raise NotImplementedError

    def _create_temp_preview_vpy_from_default(self, video_path: str, subtitle_path: str) -> str:
        raise NotImplementedError

    def _current_encode_lossless_audio_codec(self) -> str:
        raise NotImplementedError

    def _current_encode_tool_and_depth(self) -> tuple[str, str]:
        raise NotImplementedError

    def _current_vpy_processing_values(self) -> dict[str, float]:
        raise NotImplementedError

    def _default_track_lists_for_mkv_path(self, mkv_path: str) -> Optional[tuple[list[str], list[str]]]:
        raise NotImplementedError

    def _default_track_lists_for_mpls_path(self, mpls_path: str) -> Optional[tuple[list[str], list[str]]]:
        raise NotImplementedError

    def _diff_config_inputs(self, prev: dict[str, object], cur: dict[str, object]) -> tuple[str, int]:
        raise NotImplementedError

    def _dismiss_sp_scan_progress_ui(self):
        raise NotImplementedError

    def _edit_chapters_for_mkv(self, mkv_path: str):
        raise NotImplementedError

    def _edit_vpy_with_default_sync(self, video_path: str, subtitle_path: str):
        raise NotImplementedError

    def _effective_encode_params(self) -> str:
        raise NotImplementedError

    def _end_delayed_busy(self, state: Optional[dict[str, object]]):
        raise NotImplementedError

    def _ensure_default_track_config_for_main(self, mpls_path: str):
        raise NotImplementedError

    def _ensure_default_track_config_for_mkv(self, mkv_path: str, *, sp: bool=False) -> None:
        raise NotImplementedError

    def _extract_attachment_to_temp_and_open(self, mkv_path: str, attachment_id: str, filename: str):
        raise NotImplementedError

    def _extract_track_to_temp_and_open(self, mkv_path: str, track_id: int, codec_id: str):
        raise NotImplementedError

    def _filter_streams_by_pid_lang(self, streams: list[dict[str, object]], pid_lang: dict[int, str]) -> list[dict[str, object]]:
        raise NotImplementedError

    def _filtered_chapter_visible_layout(self, mpls_path: str) -> tuple[list[int], dict[int, str]]:
        raise NotImplementedError

    def _finalize_movie_mode_table2_layout(self, labels: list[str]) -> None:
        raise NotImplementedError

    def _find_table3_insert_row_for_entry(self, bdmv_index: int, mpls_file: str, m2ts_file: str) -> int:
        raise NotImplementedError

    def _folder_path_for_bdmv_index_from_table1(self, bdmv_index: int) -> str:
        raise NotImplementedError

    @staticmethod
    def _folder_set_mains_from_configuration(last_cfg: dict[int, dict[str, int | str]]) -> dict[str, set[str]]:
        raise NotImplementedError

    @staticmethod
    def _folder_set_mains_from_selected(selected: list[tuple[str, str]]) -> dict[str, set[str]]:
        raise NotImplementedError

    def _folders_with_changed_main_selection(self, selected: list[tuple[str, str]], last_cfg: dict[int, dict[str, int | str]]) -> set[str]:
        raise NotImplementedError

    def _full_refresh_remux_encode_tables_for_mode(self) -> None:
        raise NotImplementedError

    def _generate_configuration_from_ui_inputs(self) -> dict[int, dict[str, int | str]]:
        raise NotImplementedError

    def _get_approx_episode_duration_seconds(self) -> float:
        raise NotImplementedError

    def _get_disc_root_for_bdmv_index(self, bdmv_index: int) -> str:
        raise NotImplementedError

    def _get_episode_output_names_from_table2(self) -> list[str]:
        raise NotImplementedError

    def _get_episode_subtitle_languages_from_table2(self) -> list[str]:
        raise NotImplementedError

    def _get_first_m2ts_for_mpls(self, mpls_path: str) -> str:
        raise NotImplementedError

    def _get_first_subtitle_path_for_bdmv_index(self, bdmv_index: int) -> str:
        raise NotImplementedError

    def _get_main_mpls_path_for_bdmv_index(self, bdmv_index: int) -> str:
        raise NotImplementedError

    def _get_playlist_dir_for_bdmv_index(self, bdmv_index: int) -> str:
        raise NotImplementedError

    def _get_remux_source_path_from_table2_row(self, row_index: int) -> str:
        raise NotImplementedError

    def _get_remux_source_path_from_table3_row(self, row_index: int) -> str:
        raise NotImplementedError

    def _get_root_for_bdmv_index(self, bdmv_index: int) -> str:
        raise NotImplementedError

    def _get_selected_main_mpls_paths(self) -> list[str]:
        raise NotImplementedError

    def _get_stream_dir_for_bdmv_index(self, bdmv_index: int) -> str:
        raise NotImplementedError

    def _get_subtitle_suffix(self) -> str:
        raise NotImplementedError

    def _has_subtitle_in_table2(self) -> bool:
        raise NotImplementedError

    def _inherit_main_track_config_for_sp_key(self, bdmv_index: int, mpls_file: str, sp_key: str):
        raise NotImplementedError

    @staticmethod
    def _is_auto_chapter_segment_sp_item(out_item: Optional[QTableWidgetItem]) -> bool:
        raise NotImplementedError

    @staticmethod
    def _is_lossless_audio_stream_dict(s: dict[str, object]) -> bool:
        raise NotImplementedError

    def _is_movie_mode(self) -> bool:
        raise NotImplementedError

    def _is_mpls_currently_main(self, mpls_path: str) -> bool:
        raise NotImplementedError

    def _iter_all_mpls_paths_in_root(self, source_root: str) -> list[str]:
        raise NotImplementedError

    def _iter_table2_episode_m2ts_details(self, bdmv_index: int):
        raise NotImplementedError

    def _localized_headers_for_keys(self, keys: list[str]) -> list[str]:
        raise NotImplementedError

    def _m2ts_detail_for_stream_on_disc_playlists(self, bdmv_index: int, m2ts_files: list[str]) -> str:
        raise NotImplementedError

    def _m2ts_file_detail_for_sp_table_row(self, row: int, labels: Optional[list[str]]=None) -> str:
        raise NotImplementedError

    def _m2ts_file_detail_from_mpls_path(self, mpls_path: str) -> str:
        raise NotImplementedError

    @staticmethod
    def _main_mpls_abs_path_for_remux_cmd_lookup(conf: dict[str, int | str]) -> str:
        raise NotImplementedError

    def _max_sp_serial_for_bdmv(self, bdmv_index: int) -> int:
        raise NotImplementedError

    def _merge_temp_edit_back_to_default_vpy(self, temp_vpy: str):
        raise NotImplementedError

    def _merge_volume_part_from_last_cfg(self, part: dict[int, dict[str, int | str]], last_cfg: dict[int, dict[str, int | str]], bdmv_index: int) -> None:
        raise NotImplementedError

    def _movie_main_duration_map_from_table1(self) -> dict[int, float]:
        raise NotImplementedError

    def _normalize_default_vpy_runtime_lines(self):
        raise NotImplementedError

    def _normalize_path_input(self, text: str) -> str:
        raise NotImplementedError

    def _on_encode_lossless_audio_preset_changed(self) -> None:
        raise NotImplementedError

    def _on_end_chapter_combo_changed(self, row: int, labels: list[str]):
        raise NotImplementedError

    def _on_exe_button_progress_text(self, text: str):
        raise NotImplementedError

    def _on_exe_button_progress_value(self, value: int):
        raise NotImplementedError

    def _on_font_size_changed(self):
        raise NotImplementedError

    def _on_language_changed(self):
        raise NotImplementedError

    def _on_opacity_changed(self, value: int):
        raise NotImplementedError

    def _on_play_sp_table_row_clicked(self):
        raise NotImplementedError

    def _on_retired_sp_scan_thread_finished(self):
        raise NotImplementedError

    def _on_select_all_tracks_toggled(self, checked: bool):
        raise NotImplementedError

    def _on_sp_scan_thread_finished(self):
        raise NotImplementedError

    def _on_sp_table_scan_failed(self, error: str):
        raise NotImplementedError

    def _on_sp_table_scan_finished(self):
        raise NotImplementedError

    def _on_sp_table_scan_result(self, row: int, disabled: bool, special: str, payload: object):
        raise NotImplementedError

    def _on_table3_item_changed(self, item: QTableWidgetItem):
        raise NotImplementedError

    def _on_theme_changed(self):
        raise NotImplementedError

    def _on_trim_copyright_tail_toggled(self, _checked: bool=False) -> None:
        raise NotImplementedError

    def _open_third_party_notices_dialog(self):
        raise NotImplementedError

    def _parse_stream_pid(self, raw_id: object) -> Optional[int]:
        raise NotImplementedError

    @staticmethod
    def _patch_fmtc_output_bits_in_text(raw_line: str, bits: int) -> str:
        raise NotImplementedError

    @staticmethod
    def _patch_vpy_processing_value_in_text(text: str, values: dict[str, float]) -> str:
        raise NotImplementedError

    def _pid_lang_from_m2ts_track_info(self, tracks: list[dict[str, object]]) -> dict[int, str]:
        raise NotImplementedError

    def _pid_lang_from_streams(self, streams: list[dict[str, object]]) -> dict[int, str]:
        raise NotImplementedError

    def _play_m2ts_path(self, m2ts_path: str):
        raise NotImplementedError

    def _play_mpls_path(self, mpls_path: str):
        raise NotImplementedError

    def _populate_encode_from_remux_folder(self):
        raise NotImplementedError

    def _populate_encode_sps_from_remux_folder(self, folder: str):
        raise NotImplementedError

    def _preview_script_for_row(self, vpy_path: str, video_path: str, subtitle_path: str):
        raise NotImplementedError

    def _read_m2ts_track_info(self, m2ts_path: str) -> list[dict[str, object]]:
        raise NotImplementedError

    def _read_mkvinfo_attachments(self, mkv_path: str) -> list[dict[str, str]]:
        raise NotImplementedError

    def _read_mkvinfo_tracks(self, mkv_path: str) -> list[dict[str, object]]:
        raise NotImplementedError

    def _read_mkvmerge_attachment_ids(self, mkv_path: str) -> dict[str, str]:
        raise NotImplementedError

    def _read_mkvmerge_attachment_rows(self, mkv_path: str) -> list[dict[str, str]]:
        raise NotImplementedError

    @staticmethod
    def _read_mpls_track_info(mpls_path: str) -> list[dict[str, object]]:
        raise NotImplementedError

    def _rebuild_configuration_for_function_34(self):
        raise NotImplementedError

    def _recompute_sp_output_names(self, only_bdmv_index: Optional[int]=None):
        raise NotImplementedError

    def _refill_encode_bit_depth_combo(self, tool: str) -> None:
        raise NotImplementedError

    def _refresh_all_table_headers(self):
        raise NotImplementedError

    def _refresh_encode_tool_dependent_ui(self, apply_preset: bool=True) -> None:
        raise NotImplementedError

    def _refresh_font_size_combo(self):
        raise NotImplementedError

    def _refresh_function_tabbar_theme(self):
        raise NotImplementedError

    def _refresh_language_column_defaults(self):
        raise NotImplementedError

    def _refresh_language_combo(self):
        raise NotImplementedError

    def _refresh_language_dependent_sizes(self):
        raise NotImplementedError

    def _refresh_movie_subtitle_table2(self, rows: Optional[list[tuple[str, str]]]=None):
        raise NotImplementedError

    def _refresh_movie_table2(self):
        raise NotImplementedError

    def _refresh_opacity_controls(self):
        raise NotImplementedError

    def _refresh_subtitle_suffix_options(self):
        raise NotImplementedError

    def _refresh_table1_remux_cmds(self):
        raise NotImplementedError

    def _refresh_table2_m2ts_duration_from_widgets(self, labels: list[str]) -> None:
        raise NotImplementedError

    def _refresh_table3_m2ts_file_detail(self, only_bdmv_index: Optional[int]=None):
        raise NotImplementedError

    def _refresh_theme_combo(self):
        raise NotImplementedError

    def _refresh_track_selection_config_for_selected_main(self):
        raise NotImplementedError

    def _reload_encode_preset_parameters(self) -> None:
        raise NotImplementedError

    def _remember_output_folder_for_function(self, function_id: int) -> None:
        raise NotImplementedError

    def _remove_table2_rows_by_bdmv_index(self, bdmv_index: int):
        raise NotImplementedError

    def _remove_table3_auto_chapter_sp_rows(self, bdmv_index: int, mpls_basename: str):
        raise NotImplementedError

    def _remove_table3_rows_for_main_mpls(self, bdmv_index: int, mpls_path: str):
        raise NotImplementedError

    def _remux_dst_folder_for_cmd_template(self, root: str) -> str:
        raise NotImplementedError

    def _remux_mkv_source_for_edit(self, table: QTableWidget, row_or_source: int | str) -> str:
        raise NotImplementedError

    def _reposition_subtitle_path_box(self):
        raise NotImplementedError

    def _reset_exe_button(self):
        raise NotImplementedError

    def _reset_table3_column_layout(self):
        raise NotImplementedError

    def _resize_table_columns_for_language(self, table: QTableWidget):
        raise NotImplementedError

    def _resolve_bdmv_index_for_main_mpls(self, mpls_path: str, fallback_index: int) -> int:
        raise NotImplementedError

    def _resolve_output_name_from_mpls(self, mpls_no_ext: str) -> str:
        raise NotImplementedError

    def _resolve_remux_output_folder(self, base_folder: str) -> str:
        raise NotImplementedError

    def _resolve_table2_row_edit_context(self, row_index: int) -> tuple[str, str]:
        raise NotImplementedError

    def _resolve_table3_row_edit_context(self, row_index: int) -> tuple[str, str]:
        raise NotImplementedError

    def _restore_default_vpy_after_preview(self, mapping: dict[str, tuple[str, str]]):
        raise NotImplementedError

    def _restore_output_folder_for_function(self, function_id: int) -> None:
        raise NotImplementedError

    def _restore_window_geometry(self) -> bool:
        raise NotImplementedError

    def _resync_episode_tables_from_main_mpls_selection(self) -> None:
        raise NotImplementedError

    def _retire_sp_table_scan(self):
        raise NotImplementedError

    def _run_chapter_combo_update(self):
        raise NotImplementedError

    def _save_application_state(self) -> None:
        raise NotImplementedError

    def _save_simple_diy_subtitle_config(self):
        raise NotImplementedError

    def _scroll_table_h_to_right(self, table: QTableWidget):
        raise NotImplementedError

    def _segment_diff_mpls(self, prev: dict[str, object], cur: dict[str, object]) -> set[str]:
        raise NotImplementedError

    def _select_video_path(self, bdmv_index: int, m2ts_files: list[str]) -> str:
        raise NotImplementedError

    def _selected_output_bits_for_vpy(self) -> int:
        raise NotImplementedError

    @staticmethod
    def _set_combo_value(combo: QComboBox, value: str) -> None:
        raise NotImplementedError

    def _set_compact_table(self, table: QTableWidget, row_height: int=22, header_height: int=22):
        raise NotImplementedError

    def _set_segment_states_for_range(self, mpls_no_ext: str, start_idx: int, end_idx: int, checked: bool):
        raise NotImplementedError

    def _set_table2_default_column_order(self):
        raise NotImplementedError

    def _set_table2_subtitle_column_order(self):
        raise NotImplementedError

    def _set_table_column_visual_order(self, table: QTableWidget, order: list[int]):
        raise NotImplementedError

    def _set_table_headers(self, table: QTableWidget, keys: list[str]):
        raise NotImplementedError

    def _set_window_opacity_if_supported(self, opacity: float):
        raise NotImplementedError

    def _show_app_config_error(self, action: str, error: Exception | str) -> None:
        raise NotImplementedError

    def _show_attachments_dialog(self, mkv_path: str):
        raise NotImplementedError

    def _show_bottom_message(self, text: str, duration_ms: int=10000):
        raise NotImplementedError

    def _show_error_dialog(self, err_text: str):
        raise NotImplementedError

    def _show_m2ts_file_detail_columns(self) -> None:
        raise NotImplementedError

    def _show_settings_dialog(self) -> None:
        raise NotImplementedError

    def _show_tracks_dialog(self, title: str, streams: list[dict[str, object]], selected_indexes: Optional[set[str]]=None, pid_lang: Optional[dict[int, str]]=None, source_mkv: Optional[str]=None, convert_map: Optional[dict[str, str]]=None, language_map: Optional[dict[str, str]]=None, lossless_audio_map: Optional[dict[str, str]]=None) -> Optional[set[str]]:
        raise NotImplementedError

    def _snapshot_chapter_segment_sp_entries(self) -> list[dict[str, object]]:
        raise NotImplementedError

    def _sp_covered_by_table2_episode_row(self, bdmv_index: int, sp_detail: str, sp_track_key: str, *, sp_mpls_path: str='') -> bool:
        raise NotImplementedError

    def _sp_covered_by_table2_movie_row(self, bdmv_index: int, sp_detail: str) -> bool:
        raise NotImplementedError

    def _sp_m2ts_detail_for_entry(self, bdmv_index: int, mpls_file: str, m2ts_files: list[str]) -> str:
        raise NotImplementedError

    def _sp_output_display_path(self, bdmv_index: int, row_r: int, candidate_rel: str, *, detail_override: Optional[str]=None, table2_detail_out_map: Optional[dict[str, str]]=None) -> str:
        raise NotImplementedError

    def _split_m2ts_files(self, text: str) -> list[str]:
        raise NotImplementedError

    def _start_sp_table_scan(self):
        raise NotImplementedError

    def _start_subtitle_folder_scan(self):
        raise NotImplementedError

    def _streams_for_track_config_key(self, key: str) -> list[dict[str, object]]:
        raise NotImplementedError

    @staticmethod
    def _streams_for_track_selection_dialog(streams: list[dict[str, object]]) -> list[dict[str, object]]:
        raise NotImplementedError

    def _sync_chapter_checkbox_sp_for_mpls(self, mpls_path: str, bdmv_index: int):
        raise NotImplementedError

    def _sync_chapter_checkbox_sp_rows_all_volumes(self, configuration: dict[int, dict[str, int | str]]):
        raise NotImplementedError

    def _sync_end_chapter_min_constraints(self, labels: list[str]):
        raise NotImplementedError

    def _sync_main_mpls_track_config_by_pid(self, source_mpls_path: str, source_streams: list[dict[str, object]], source_selected_indexes: set[str], source_convert_map: dict[str, str], source_language_map: dict[str, str], source_lossless_audio_map: Optional[dict[str, str]]=None):
        raise NotImplementedError

    def _sync_sp_table_row_m2ts_column_from_detail(self, row: int, labels: Optional[list[str]]=None) -> None:
        raise NotImplementedError

    def _table1_bluray_folder_order(self) -> list[str]:
        raise NotImplementedError

    def _table2_labels_for_current_mode(self):
        raise NotImplementedError

    def _table2_m2ts_detail_duration_from_chapter_bounds(self, mpls_selected: str, j1: int, j2: int) -> tuple[str, str, str]:
        raise NotImplementedError

    def _table2_output_name_if_same_m2ts_detail(self, bdmv_index: int, detail_sp: str) -> str:
        raise NotImplementedError

    def _table2_row_mpls_path(self, row: int) -> str:
        raise NotImplementedError

    def _table3_get_sp_entry_for_row(self, row: int) -> dict[str, int | str]:
        raise NotImplementedError

    def _tick_delayed_busy(self, state: Optional[dict[str, object]], text: Optional[str]=None):
        raise NotImplementedError

    def _track_id_sets_for_config_key(self, key: str, *, mpls_path_fallback: str='') -> tuple[set[str], set[str]]:
        raise NotImplementedError

    def _track_pid_sets_for_config_key(self, key: str, *, mpls_path_fallback: str='') -> Optional[tuple[set[int], set[int]]]:
        raise NotImplementedError

    def _track_selection_contained_in(self, sub_key: str, sup_key: str, *, sub_mpls_fallback: str='', sup_mpls_fallback: str='') -> bool:
        raise NotImplementedError

    def _translate_widget_texts(self):
        raise NotImplementedError

    def _unchecked_segments_from_checkbox_states(self, mpls_path: str) -> tuple[list[tuple[int, int]], dict[int, str]]:
        raise NotImplementedError

    def _update_default_vpy_paths(self, video_path: str, subtitle_path: str) -> dict[str, tuple[str, str]]:
        raise NotImplementedError

    def _update_encode_bit_depth_combo_tooltip(self) -> None:
        raise NotImplementedError

    def _update_exe_button_progress(self, value: Optional[int]=None, text: Optional[str]=None):
        raise NotImplementedError

    def _update_language_combo_enabled_state(self):
        raise NotImplementedError

    def _update_main_row_play_button(self):
        raise NotImplementedError

    def _update_trim_copyright_tail_checkbox_for_episode_movie_mode(self) -> None:
        raise NotImplementedError

    def _update_vpy_paths_in_file(self, vpy_path: str, video_path: str, subtitle_path: str) -> bool:
        raise NotImplementedError

    def _vpy_raw_string(self, path: str) -> str:
        raise NotImplementedError

    def _window_geometry_text(self) -> str:
        raise NotImplementedError

    def _window_opacity_supported(self) -> bool:
        raise NotImplementedError

    def add_chapters(self):
        raise NotImplementedError

    def apply_lossless_audio_preset_globally(self, codec: str) -> None:
        raise NotImplementedError

    def closeEvent(self, event):
        raise NotImplementedError

    def create_language_combo(self, initial: str='chi', parent: Optional[QWidget]=None) -> QComboBox:
        raise NotImplementedError

    def create_vpy_path_widget(self, initial_path: Optional[str]=None, parent: Optional[QWidget]=None) -> QWidget:
        raise NotImplementedError

    def delete_default_vpy_file(self):
        raise NotImplementedError

    def edit_subtitle(self, path: str):
        raise NotImplementedError

    def encode_bluray(self):
        raise NotImplementedError

    def ensure_default_vpy_file(self):
        raise NotImplementedError

    def ensure_encode_row_widgets(self, row_index: int):
        raise NotImplementedError

    def generate_subtitle(self, silent_mode: bool=False):
        raise NotImplementedError

    def get_default_vpy_path(self) -> str:
        raise NotImplementedError

    def get_mkv_files_in_table_order(self):
        raise NotImplementedError

    def get_selected_function_id(self) -> int:
        raise NotImplementedError

    def get_selected_mpls_no_ext(self) -> list[tuple[str, str]]:
        raise NotImplementedError

    def get_sp_vpy_path_from_row(self, row_index: int) -> str:
        raise NotImplementedError

    def get_vpy_path_from_row(self, row_index: int) -> str:
        raise NotImplementedError

    def init_encode_box(self):
        raise NotImplementedError

    def init_ui(self):
        raise NotImplementedError

    def main(self):
        raise NotImplementedError

    def on_bdmv_folder_path_change(self):
        raise NotImplementedError

    def on_button_click(self, mpls_path: str, is_main_at_build: bool=True, bdmv_index: int=0):
        raise NotImplementedError

    def on_button_main(self, mpls_path: str, clicked_checked: Optional[bool]=None):
        raise NotImplementedError

    def on_button_play(self, mpls_path: str, btn: QToolButton):
        raise NotImplementedError

    def on_chapter_combo(self, subtitle_index: int):
        raise NotImplementedError

    def on_configuration(self, configuration: dict[int, dict[str, int | str]], update_sp_table: bool=True):
        raise NotImplementedError

    def on_edit_attachments_from_mkv_row(self, table: QTableWidget, row_index: int | str):
        raise NotImplementedError

    def on_edit_chapters_from_mkv_row(self, table: QTableWidget, row_index: int | str):
        raise NotImplementedError

    def on_edit_sp_vpy_clicked(self):
        raise NotImplementedError

    def on_edit_tracks_from_mkv_row(self, table: QTableWidget, row_index: int | str):
        raise NotImplementedError

    def on_edit_tracks_from_mpls(self, mpls_path: str):
        raise NotImplementedError

    def on_edit_tracks_from_sp_table(self, row: int):
        raise NotImplementedError

    def on_edit_vpy_clicked(self):
        raise NotImplementedError

    def on_play_sp_table_row(self, row_index: int, bdmv_col: int, mpls_col: int, m2ts_col: int):
        raise NotImplementedError

    def on_play_table2_disc_row(self, row_index: int, bdmv_col: int, m2ts_col: int):
        raise NotImplementedError

    def on_preview_script_clicked(self):
        raise NotImplementedError

    def on_preview_sp_scripts_clicked(self):
        raise NotImplementedError

    def on_select_function(self, force: bool=False, keep_inputs: bool=False, keep_state: bool=False):
        raise NotImplementedError

    def on_subtitle_drop(self):
        raise NotImplementedError

    def on_subtitle_folder_path_change(self):
        raise NotImplementedError

    def on_subtitle_menu(self, pos: QPoint):
        raise NotImplementedError

    def on_subtitle_select(self):
        raise NotImplementedError

    def on_subtitle_table_sorted(self, logicalIndex: int, order: Qt.SortOrder):
        raise NotImplementedError

    def on_view_mpls_play_items(self, mpls_path: str) -> None:
        raise NotImplementedError

    def open_file_path(self, path: str):
        raise NotImplementedError

    def open_folder_path(self, path: str):
        raise NotImplementedError

    def open_vpy_in_editor(self, path: str):
        raise NotImplementedError

    def open_vpy_in_vsedit(self, path: str) -> Optional[QProcess]:
        raise NotImplementedError

    def refresh_sp_table(self, configuration: dict[int, dict[str, int | str]]):
        raise NotImplementedError

    def remux_episodes(self):
        raise NotImplementedError

    def select_bdmv_folder(self):
        raise NotImplementedError

    def select_output_folder(self):
        raise NotImplementedError

    def select_remux_folder(self):
        raise NotImplementedError

    def select_subtitle_folder(self):
        raise NotImplementedError

    def set_vpy_hardsub_enabled(self, enabled: bool):
        raise NotImplementedError

    def sync_default_vpy_fmtc_with_encode_ui(self) -> None:
        raise NotImplementedError

    def t(self, text: str) -> str:
        raise NotImplementedError

    # END GENERATED MIXIN CONTRACTS
