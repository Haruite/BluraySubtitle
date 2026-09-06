"""IDE contracts for the split `BluraySubtitle` service.

The declarations are verified against the mixins by
`tools/check_split_contracts.py`.
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Optional


from src.bdmv import Chapter
from src.runtime.audio_conversion import AudioEncodingSettings
from src.runtime.remux import RemuxMainJob, RemuxRequest
from src.runtime.encode import EncodeRequest, EncodeRow
from src.runtime.encode_results import EncodeBatchResult
from src.runtime.sp import SpEntry, SpJob


class BluraySubtitleServiceBase:
    """Base class with declared attrs/method contracts for service split."""

    __init_service_base_attrs__: bool = False

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize optionally declared attrs for tooling."""
        if not bool(getattr(type(self), "__init_service_base_attrs__", False)):
            return
        self._disc_output_name_cache = None
        self._sp_index_by_bdmv = None
        self._subtitle_cache = None
        self.approx_episode_duration_seconds = None
        self.bdmv_path = None
        self.bluray_folders = None
        self.checked = None
        self.configuration = None
        self.episode_subtitle_languages = None
        self.encode_warnings = None
        self.movie_mode = None
        self.progress_dialog = None
        self.remux_warnings = None
        self.sub_files = None

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        for _name, _obj in BluraySubtitleServiceBase.__dict__.items():
            if _name in {"__init__", "__init_subclass__"}:
                continue
            _fn = None
            if isinstance(_obj, staticmethod):
                _fn = _obj.__func__
            elif isinstance(_obj, classmethod):
                _fn = _obj.__func__
            elif callable(_obj):
                _fn = _obj
            if _fn is not None:
                setattr(_fn, "__service_base_stub__", True)

    # BEGIN GENERATED MIXIN CONTRACTS
    @staticmethod
    def _aligned_output_track_ids_for_pid_slots(media_path: str, selected_pid_slots: list[tuple[str, int]]) -> Optional[tuple[list[str], list[str], dict[int, int]]]:
        raise NotImplementedError

    def _assign_movie_sp_output_names(self, entries: list[dict[str, object]]) -> None:
        raise NotImplementedError

    def _build_main_episode_mkvs(self, jobs: list[RemuxMainJob], cancel_event: Optional[threading.Event]=None, *, mux_progress_base: int=0, mux_progress_span: int=380) -> list[str]:
        raise NotImplementedError

    def _build_sp_outputs(self, jobs: list[SpJob], cancel_event: Optional[threading.Event]=None, progress_cb: Optional[Callable[[int, str], None]]=None, audio_encoding: AudioEncodingSettings=AudioEncodingSettings(), standalone_audio_targets: Optional[dict[int, str]]=None) -> list[tuple[int, str]]:
        raise NotImplementedError

    @staticmethod
    def _chapter_bounds_from_split_windows(mpls_path: str, windows: list[tuple[float, float]]) -> list[tuple[int, int]]:
        raise NotImplementedError

    @staticmethod
    def _chapter_split_bounds_from_multi_line_remux_cmd(cmd0: str, confs: list[dict[str, object]]) -> list[tuple[int, int]]:
        raise NotImplementedError

    @staticmethod
    def _collect_tsmuxer_demux_files(demux_dir: str, stem_hint: str) -> list[tuple[int, str]]:
        raise NotImplementedError

    def _compute_mkv_id_to_mpls_track_signature_for_main_mpls(self, mpls_path: str) -> dict[int, tuple[tuple[str, int], ...]]:
        raise NotImplementedError

    def _concat_mpls_logical_parts(self, part_descriptors: list[dict[str, object]], logical_slots: list[dict[str, object]], output_file: str, cover_path: str, mkvmerge_executable: str, ui_language_argument: str) -> bool:
        raise NotImplementedError

    @staticmethod
    def _configuration_drop_invalid_episode_rows(configuration: dict[int, dict[str, int | str]]) -> dict[int, dict[str, int | str]]:
        raise NotImplementedError

    @staticmethod
    def _dedupe_remux_shell_lines(cmd: str) -> str:
        raise NotImplementedError

    @staticmethod
    def _default_track_selection_from_streams(streams: list[dict[str, object]], pid_to_lang: Optional[dict[int, str]]=None) -> tuple[list[str], list[str]]:
        raise NotImplementedError

    @staticmethod
    def _detect_repeated_single_m2ts_mpls(mpls_path: str) -> tuple[bool, str]:
        raise NotImplementedError

    @staticmethod
    def _detect_sp_looping_mpls(mpls_path: str) -> Optional[dict[str, object]]:
        raise NotImplementedError

    @staticmethod
    def _disc_paths_for_output_title(bdmv_root: str, selected_mpls_no_ext: str) -> tuple[str, str, str]:
        raise NotImplementedError

    def _encode_mkv_rows(self, request: EncodeRequest, main_rows: list[EncodeRow], sp_rows: list[EncodeRow], cancel_event: Optional[threading.Event], *, companion_root: str='', progress_base: int=0, progress_span: int=1000, main_progress_span: Optional[int]=None, sp_progress_span: Optional[int]=None) -> EncodeBatchResult:
        raise NotImplementedError

    @staticmethod
    def _enrich_configuration_chapter_bounds(configuration: dict[int, dict[str, int | str]]) -> None:
        raise NotImplementedError

    @staticmethod
    def _episode_float_windows_from_config_bounds(mpls_path: str, confs: list[dict[str, int | str]]) -> list[tuple[float, float]]:
        raise NotImplementedError

    @staticmethod
    def _expected_mkvmerge_split_output_paths(output_norm: str, n_segments: int) -> list[str]:
        raise NotImplementedError

    def _extract_sample_images(self, video_path: str, temp_dir: str, max_total: int=100, score_map: Optional[dict[str, float]]=None) -> list[str]:
        raise NotImplementedError

    @staticmethod
    def _filter_pid_slots_for_dovi_plan(slots: list[dict[str, object]], dovi_plan: Optional[dict[str, object]]) -> list[dict[str, object]]:
        raise NotImplementedError

    @staticmethod
    def _filter_video_pids_for_dovi_plan(video_pids: list[int], dovi_plan: Optional[dict[str, object]]) -> list[int]:
        raise NotImplementedError

    @staticmethod
    def _finalize_configuration_episode_rows(configuration: dict[int, dict[str, int | str]]) -> dict[int, dict[str, int | str]]:
        raise NotImplementedError

    @staticmethod
    def _fix_output_track_languages_with_mkvpropedit(output_mkv_path: str, input_source_path: str, selected_audio_ids: list[str], selected_sub_ids: list[str], override_lang_by_source_index: Optional[dict[str, str]]=None, dovi_plan: Optional[dict[str, object]]=None, selected_pid_slots: Optional[list[tuple[str, int]]]=None, selected_source_slots: tuple[tuple[str, str, int], ...]=()) -> None:
        raise NotImplementedError

    @staticmethod
    def _fix_remux_shell_rm_glob(raw: str) -> str:
        raise NotImplementedError

    @staticmethod
    def _format_remux_slot_pid_list(slots: list[dict[str, object]]) -> str:
        raise NotImplementedError

    @staticmethod
    def _frame_discriminability_score(image_path: str) -> float:
        raise NotImplementedError

    @staticmethod
    def _group_selected_mpls_by_folder_runs(selected_mpls: list[tuple[str, str]]) -> list[list[tuple[str, str]]]:
        raise NotImplementedError

    def _infer_native_resolution(self, video_path: str) -> Optional[dict]:
        raise NotImplementedError

    @staticmethod
    def _int_from_mkvmerge_prop(raw: object) -> Optional[int]:
        raise NotImplementedError

    @staticmethod
    def _is_audio_only_media(media_path: str) -> bool:
        raise NotImplementedError

    @staticmethod
    def _log_mkvmerge_identify_slot_gap(ident_path: str, probe_m2ts: str, ref_slots: list[dict[str, object]], ident: Optional[dict[str, object]], reason: str, missing_slots: Optional[list[dict[str, object]]]=None) -> None:
        raise NotImplementedError

    @staticmethod
    def _m2ts_clip_time_window_sec(m2ts_path: str, in_time: int, out_time: int) -> tuple[bool, float, float]:
        raise NotImplementedError

    @staticmethod
    def _m2ts_duration_90k(m2ts_path: str) -> int:
        raise NotImplementedError

    @staticmethod
    def _m2ts_track_streams(m2ts_path: str) -> list[dict[str, object]]:
        raise NotImplementedError

    @staticmethod
    def _main_remux_command_with_track_placeholders(command: str, mpls_path: str) -> str:
        raise NotImplementedError

    def _make_main_mpls_remux_cmd(self, confs: list[dict[str, int | str]], dst_folder: str, bdmv_index: int, disc_count: int, *, ensure_disc_out_dir: bool=False) -> tuple[str, str, str, str, str, list[str], list[str]]:
        raise NotImplementedError

    @staticmethod
    def _map_selected_pids_to_mpls_track_ids(mpls_path: str, selected_audio_pids: list[str], selected_subtitle_pids: list[str]) -> tuple[list[str], list[str]]:
        raise NotImplementedError

    @staticmethod
    def _map_slots_to_mkvmerge_track_ids(reference_slots: list[dict[str, object]], m2ts_path: str) -> Optional[list[int]]:
        raise NotImplementedError

    @staticmethod
    def _mkvmerge_das_flag_strings_for_m2ts(m2ts_path: str, copy_audio_track: list[str], copy_sub_track: list[str], dovi_plan: Optional[dict[str, object]]=None) -> Optional[tuple[str, str, str]]:
        raise NotImplementedError

    @staticmethod
    def _mkvmerge_dovi_primary_video_opts(mpls_path: str, dovi_plan: Optional[dict[str, object]]) -> str:
        raise NotImplementedError

    @staticmethod
    def _mkvmerge_expected_paths_for_shell_line(line: str, confs: list[dict[str, int | str]], mpls_path_default: str) -> tuple[Optional[str], list[str]]:
        raise NotImplementedError

    def _mkvmerge_identify_covers_mpls_pid_slots(self, mpls_path: str, selected_pid_slots: list[tuple[str, int]], *, identification: Optional[dict[str, object]]=None, alternate_mpls_paths: tuple[str, ...]=(), selected_source_slots: tuple[tuple[str, str, int], ...]=()) -> bool:
        raise NotImplementedError

    def _mkvmerge_identify_covers_remux_slots(self, source_path: str, copy_audio_track: list[str], copy_sub_track: list[str], selected_pid_slots: Optional[list[tuple[str, int]]]=None, identification: Optional[dict[str, object]]=None, alternate_mpls_paths: tuple[str, ...]=(), selected_source_slots: tuple[tuple[str, str, int], ...]=()) -> bool:
        raise NotImplementedError

    @staticmethod
    def _mkvmerge_identify_json(media_path: str) -> dict[str, object]:
        raise NotImplementedError

    @staticmethod
    def _mkvmerge_line_source_mpls_stem(line: str) -> str:
        raise NotImplementedError

    @staticmethod
    def _mkvmerge_output_path_from_line(line: str) -> Optional[str]:
        raise NotImplementedError

    @staticmethod
    def _mkvmerge_pid_id_map(media_path: str, identification: Optional[dict[str, object]]=None) -> dict[tuple[str, int], int]:
        raise NotImplementedError

    @staticmethod
    def _mkvmerge_select_flags_from_mapped(mapped_track_ids: list[int], identification: dict[str, object]) -> tuple[str, str, str]:
        raise NotImplementedError

    @staticmethod
    def _mkvmerge_tid_for_pid(m2ts_path: str, pid: int, slot_type: str) -> Optional[int]:
        raise NotImplementedError

    def _movie_sp_covered_by_table2(self, bdmv_index: int, sp_detail: str, table2_details: list[str]) -> bool:
        raise NotImplementedError

    @staticmethod
    def _mpls_clip_slots(logical_slots: list[dict[str, object]], play_item_index: int) -> list[dict[str, object]]:
        raise NotImplementedError

    @staticmethod
    def _mpls_default_language_map(mpls_path: str, selected_pid_slots: list[tuple[str, int]], configured_languages: Optional[dict[str, str]]=None, *, alternate_mpls_paths: tuple[str, ...]=(), selected_source_slots: tuple[tuple[str, str, int], ...]=()) -> dict[str, str]:
        raise NotImplementedError

    @staticmethod
    def _mpls_hevc_dv_video_pids(mpls_path: str) -> list[int]:
        raise NotImplementedError

    @staticmethod
    def _mpls_identify_has_slot(ident: dict[str, object], slot: dict[str, object]) -> bool:
        raise NotImplementedError

    @staticmethod
    def _mpls_identify_pids_by_type(ident: dict[str, object]) -> dict[str, list[int]]:
        raise NotImplementedError

    @staticmethod
    def _mpls_logical_slots_for_selection(mpls_path: str, selected_pid_slots: list[tuple[str, int]], *, alternate_mpls_paths: tuple[str, ...]=(), selected_source_slots: tuple[tuple[str, str, int], ...]=()) -> tuple[list[dict[str, object]], list[tuple[str, int]]]:
        raise NotImplementedError

    @staticmethod
    def _mpls_track_mapping_signature(logical_slot: dict[str, object]) -> tuple[tuple[str, int], ...]:
        raise NotImplementedError

    @staticmethod
    def _mpls_track_selection_key(mpls_path: str, bucket: str, slot_index: int) -> str:
        raise NotImplementedError

    @staticmethod
    def _mpls_track_streams(mpls_path: str) -> list[dict[str, object]]:
        raise NotImplementedError

    def _mux_episode_linked_sp_mkvmerge(self, *, episode_mkv: str, sp_mpls_path: str, episode_main_mpls: str, selected_sp_audio_track_ids: list[str], selected_sp_subtitle_track_ids: list[str], language_by_sp_track_id: dict[str, str], cancel_event: Optional[threading.Event], source_signature_by_track_id: Optional[dict[int, tuple[tuple[str, int], ...]]]=None) -> bool:
        raise NotImplementedError

    @staticmethod
    def _norm_lang_for_track_selection(raw: object) -> str:
        raise NotImplementedError

    @staticmethod
    def _norm_lang_mkv(lcode: str) -> str:
        raise NotImplementedError

    @staticmethod
    def _ordered_track_slots_for_remux(m2ts_path: str, copy_audio_track: list[str], copy_sub_track: list[str], dovi_plan: Optional[dict[str, object]]=None) -> list[dict[str, object]]:
        raise NotImplementedError

    @staticmethod
    def _parse_timecode_to_sec(raw: str) -> Optional[float]:
        raise NotImplementedError

    @staticmethod
    def _parse_tsmuxer_probe_output(text: str) -> list[dict[str, object]]:
        raise NotImplementedError

    @staticmethod
    def _pid_lang_from_media_streams(streams: list[dict[str, object]]) -> dict[int, str]:
        raise NotImplementedError

    def _post_remux_finalize_episodes(self, jobs: list[RemuxMainJob], cancel_event: Optional[threading.Event]) -> list[str]:
        raise NotImplementedError

    def _preload_subtitles(self, file_paths: list[str], cancel_event: Optional[threading.Event]=None):
        raise NotImplementedError

    def _preload_subtitles_multiprocess(self, file_paths: list[str], cancel_event: Optional[threading.Event]=None):
        raise NotImplementedError

    def _preload_subtitles_single(self, file_paths: list[str], cancel_event: Optional[threading.Event]=None):
        raise NotImplementedError

    def _prepare_remux_main_jobs(self, request: RemuxRequest) -> tuple[str, list[RemuxMainJob]]:
        raise NotImplementedError

    def _prepare_sp_jobs(self, entries: tuple[SpEntry, ...], destination_folder: str, main_jobs: list[RemuxMainJob], track_selection_config: dict[str, dict[str, list[str]]] | None, track_language_config: dict[str, dict[str, str]]) -> list[SpJob]:
        raise NotImplementedError

    @staticmethod
    def _probe_m2ts_for_remux_source(source_path: str) -> tuple[str, str]:
        raise NotImplementedError

    def _progress(self, value: Optional[int]=None, text: Optional[str]=None):
        raise NotImplementedError

    @staticmethod
    def _read_m2ts_track_info(m2ts_path: str) -> list[dict[str, object]]:
        raise NotImplementedError

    @staticmethod
    def _read_media_streams(media_path: str) -> list[dict[str, object]]:
        raise NotImplementedError

    def _remux_aligned_clip(self, m2ts_path: str, mpls_path: str, clip_slots: list[dict[str, object]], part_output: str, split_argument: str, clip_duration_sec: float, work_dir: str, part_tag: str, mkvmerge_executable: str, ui_language_argument: str) -> bool:
        raise NotImplementedError

    @staticmethod
    def _remux_cmd_shell_lines(cmd: str) -> list[str]:
        raise NotImplementedError

    def _remux_fallback_merge_demux_with_base(self, mkvmerge_executable: str, ui_language_argument: str, base_mkv: Optional[str], base_pid_list: list[int], demux_by_pid: dict[int, str], pid_to_lang: dict[int, str], output_mkv: str, *, base_track_by_pid: Optional[dict[int, int]]=None, selected_pid_order: list[int]) -> bool:
        raise NotImplementedError

    @staticmethod
    def _remux_fallback_promote_merge_to_part_out(part_out: str, merged_path: str) -> bool:
        raise NotImplementedError

    @staticmethod
    def _remux_fallback_run_tsmuxer_demux_subset(m2ts_path: str, work_dir: str, part_tag: str, pid_to_lang: dict[int, str], requested_pids: set[int], tsmuxer_tracks: list[dict[str, object]], *, path_tag: Optional[str]=None) -> Optional[dict[int, str]]:
        raise NotImplementedError

    @staticmethod
    def _remux_output_track_warnings(output_path: str, dovi_plan: Optional[dict[str, object]], selected_pid_slots: list[tuple[str, int]]) -> list[str]:
        raise NotImplementedError

    @staticmethod
    def _remux_parsed_chapter_bounds_for_theory_count(cmd: str, confs: list[dict[str, int | str]], mpls_path0: str, n_expect: int) -> Optional[list[tuple[int, int]]]:
        raise NotImplementedError

    def _resolve_disc_output_name(self, selected_mpls_no_ext: str) -> str:
        raise NotImplementedError

    @staticmethod
    def _resolve_main_remux_track_placeholders(command: str, selected_pid_slots: list[tuple[str, int]], identification: dict[str, object], dovi_plan: Optional[dict[str, object]]=None) -> str:
        raise NotImplementedError

    @staticmethod
    def _resolve_mpls_path_from_conf(conf: dict[str, int | str], bdmv_root: str='') -> str:
        raise NotImplementedError

    def _run_shell_command_detailed(self, cmd: str) -> tuple[int, list[int]]:
        raise NotImplementedError

    def _run_single_command(self, cmd: str) -> int:
        raise NotImplementedError

    @staticmethod
    def _run_tsmuxer_probe(m2ts_path: str) -> str:
        raise NotImplementedError

    def _select_tracks_for_source(self, source_path: str, pid_to_lang: Optional[dict[int, str]]=None, config_key: Optional[str]=None) -> tuple[list[str], list[str]]:
        raise NotImplementedError

    @staticmethod
    def _selected_pid_slots_for_mpls(mpls_path: str, track_configuration: dict[str, object], *, alternate_mpls_paths: tuple[str, ...]=()) -> list[dict[str, object]]:
        raise NotImplementedError

    @staticmethod
    def _series_episode_segments_bounds(chapter: Chapter, confs: list[dict[str, int | str]]) -> list[tuple[int, int]]:
        raise NotImplementedError

    def _set_dovi_mux_plan_for_mpls(self, mpls_path: str, *, report_detected_pair: bool=False) -> None:
        raise NotImplementedError

    @staticmethod
    def _slot_pids_in_order(slots: list[dict[str, object]]) -> list[int]:
        raise NotImplementedError

    def _sp_m2ts_detail_for_entry(self, bdmv_index: int, mpls_file: str, m2ts_files: list[str]) -> str:
        raise NotImplementedError

    @staticmethod
    def _split_chapters_ints_from_mkvmerge_one_line(line: str) -> Optional[list[int]]:
        raise NotImplementedError

    @staticmethod
    def _split_parts_windows_from_mkvmerge_cmd(cmd: str, *, mpls_stem: Optional[str]=None) -> list[tuple[float, float]]:
        raise NotImplementedError

    @staticmethod
    def _split_parts_windows_from_mkvmerge_one_line(line: str) -> list[tuple[float, float]]:
        raise NotImplementedError

    @staticmethod
    def _split_segment_count_from_mkvmerge_one_line(line: str) -> Optional[int]:
        raise NotImplementedError

    @staticmethod
    def _stream_service_id(stream: dict) -> Optional[int]:
        raise NotImplementedError

    @staticmethod
    def _time_windows_from_split_chapter_numbers(mpls_path: str, cuts: list[int]) -> list[tuple[float, float]]:
        raise NotImplementedError

    def _try_remux_mpls_split_outputs_track_aligned(self, mpls_path: str, output_file: str, episode_configurations: list[dict[str, int | str]], cover_path: str, cancel_event: Optional[threading.Event]=None, *, progress_base: int=0, progress_span: int=380, selected_pid_slots: list[tuple[str, int]], alternate_mpls_paths: tuple[str, ...]=(), selected_source_slots: tuple[tuple[str, str, int], ...]=()) -> bool:
        raise NotImplementedError

    def _try_remux_mpls_track_aligned(self, mpls_path: str, output_file: str, cover_path: str, cancel_event: Optional[threading.Event]=None, *, max_play_items: Optional[int]=None, selected_pid_slots: list[tuple[str, int]], alternate_mpls_paths: tuple[str, ...]=(), selected_source_slots: tuple[tuple[str, str, int], ...]=()) -> bool:
        raise NotImplementedError

    @staticmethod
    def _tsmuxer_demux_audio_use_track0_after_identify(media_path: str, slot_type: str) -> bool:
        raise NotImplementedError

    @staticmethod
    def _tsmuxer_exe() -> str:
        raise NotImplementedError

    @staticmethod
    def _tsmuxer_mpeg_pid(track: dict[str, object]) -> Optional[int]:
        raise NotImplementedError

    def _validate_mpls_tracks_for_execution(self, mpls_path: str, selected_pid_slots: list[tuple[str, int]], *, max_play_items: Optional[int]=None, alternate_mpls_paths: tuple[str, ...]=(), selected_source_slots: tuple[tuple[str, str, int], ...]=()) -> list[tuple[str, int]]:
        raise NotImplementedError

    @staticmethod
    def _video_frame_count_static(media_path: str, progress_callback: Optional[Callable[[int, float, Optional[float], Optional[float]], None]]=None, cancel_event: Optional[threading.Event]=None, max_frames: Optional[int]=None) -> int:
        raise NotImplementedError

    @staticmethod
    def _video_pids_on_m2ts(m2ts_path: str) -> list[int]:
        raise NotImplementedError

    def _volume_configuration_no_sub_files(self, volume_selected: list[tuple[str, str]], cancel_event: Optional[threading.Event]=None) -> dict[int, dict[str, int | str]]:
        raise NotImplementedError

    def _write_chapter_txt_from_mpls(self, mpls_path: str, chapter_txt_path: str, *, max_play_items: Optional[int]=None) -> list[float]:
        raise NotImplementedError

    def _write_custom_chapter_for_segment(self, mpls_path: str, chapter_txt_path: str, output_name: str):
        raise NotImplementedError

    def _write_remux_segment_chapter_txt(self, mpls_path: str, start_chapter: int, end_chapter: int, out_path: str) -> None:
        raise NotImplementedError

    @staticmethod
    def _write_tsmuxer_demux_meta(m2ts_path: str, tracks: list[dict[str, object]], pid_to_lang: dict[int, str], out_meta_path: str, fps_default: str) -> bool:
        raise NotImplementedError

    def add_chapters_to_mkv(self, mkv_targets: list[tuple[str, str]], selected_mpls: list[str], edit_original: bool, cancel_event: Optional[threading.Event]=None) -> None:
        raise NotImplementedError

    def build_movie_mode_configuration(self, selected_mpls: list[tuple[str, str]]) -> tuple[dict[int, dict[str, int | str]], list[str]]:
        raise NotImplementedError

    def build_movie_mode_sp_entries(self, configuration: dict[int, dict[str, int | str]]) -> list[dict[str, int | str]]:
        raise NotImplementedError

    def completion(self):
        raise NotImplementedError

    @staticmethod
    def detect_dovi_mux_pair(mpls_path: str, probe_m2ts: str, mux_dolby_vision: bool) -> Optional[dict[str, object]]:
        raise NotImplementedError

    def encode_task(self, output_file: str, vpy_path: str, vspipe_mode: str, encoder_mode: str, encoder_parameters: str, subtitle_mode: str, *, source_file: str, encoder: str, bit_depth: str, selected_audio_tracks: Optional[tuple[str, ...]], selected_subtitle_tracks: Optional[tuple[str, ...]], audio_codec_choices: tuple[str, ...], track_language_overrides: tuple[tuple[str, str], ...], subtitle_path: str='', subtitle_language: str='', audio_encoding: AudioEncodingSettings=AudioEncodingSettings(), wave64_bit_depth: int=32, audio_timeline_by_track: Optional[dict[int, tuple[tuple[float, float], ...]]]=None, detect_audio_gaps: bool=False, auto_crop_black_borders: bool=False, vpy_denoise_strength: float=0.6, vpy_dehalo_strength: float=0.0, vpy_dering_strength: float=0.0, vpy_deband_strength: float=0.5, vpy_antialiasing_strength: float=0.5, check_corrupted_frames: bool=False, frame_check_luma_psnr_threshold_db: float=30.0, frame_check_chroma_psnr_threshold_db: float=30.0, progress_name: str='', video_progress_name: str='', cancel_event: Optional[threading.Event]=None) -> None:
        raise NotImplementedError

    def episodes_encode(self, request: EncodeRequest, cancel_event: Optional[threading.Event]=None) -> EncodeBatchResult:
        raise NotImplementedError

    def episodes_remux(self, request: RemuxRequest, cancel_event: Optional[threading.Event]=None) -> None:
        raise NotImplementedError

    def generate_configuration_from_selected_mpls(self, selected_mpls: list[tuple[str, str]], sub_combo_index: Optional[dict[int, int]]=None, subtitle_index: Optional[int]=None, cancel_event: Optional[threading.Event]=None) -> dict[int, dict[str, int | str]]:
        raise NotImplementedError

    def get_main_mpls(self, bluray_folder: str, checked: bool) -> str:
        raise NotImplementedError

    @staticmethod
    def m2ts_basenames_from_mpls_timeline_window(mpls_path: str, w0: float, w1: float) -> list[str]:
        raise NotImplementedError

    @staticmethod
    def m2ts_file_basenames_from_mpls_playlist(mpls_path: str) -> list[str]:
        raise NotImplementedError

    @staticmethod
    def m2ts_file_detail_for_mpls_timeline_window(mpls_path: str, w0: float, w1: float) -> str:
        raise NotImplementedError

    @staticmethod
    def m2ts_file_detail_for_standalone_m2ts_paths(m2ts_paths: list[str]) -> str:
        raise NotImplementedError

    @staticmethod
    def m2ts_file_detail_from_mpls_playlist(mpls_path: str) -> str:
        raise NotImplementedError

    @staticmethod
    def m2ts_file_detail_whole_stream_file(m2ts_path: str) -> str:
        raise NotImplementedError

    def merge_subtitles(self, selected_mpls: list[tuple[str, str]], movie_tasks: Optional[list[tuple[str, str, str]]]=None, series_configuration: Optional[list[tuple[str, str, int, str]]]=None, subtitle_suffix: str='', cancel_event: Optional[threading.Event]=None) -> list[str]:
        raise NotImplementedError

    @staticmethod
    def mkvinfo_dolby_vision_track_id(mkv_path: str) -> Optional[int]:
        raise NotImplementedError

    @staticmethod
    def resolve_disc_output_title(bdmv_root: str, selected_mpls_no_ext: str) -> str:
        raise NotImplementedError

    def t(self, text: str) -> str:
        raise NotImplementedError

    @staticmethod
    def theoretical_remux_output_paths_ordered(cmd: str, confs: list[dict[str, int | str]], mpls_path_default: str) -> list[str]:
        raise NotImplementedError

    # END GENERATED MIXIN CONTRACTS
