"""Auto-generated base contracts for `BluraySubtitle` split migration."""

from __future__ import annotations

import threading
from typing import Any, Optional, Generator

from PyQt6.QtWidgets import QTableWidget

from src.bdmv import Chapter


class BluraySubtitleServiceBase:
    """Base class with declared attrs/method contracts for service split."""

    __init_service_base_attrs__: bool = False

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize optionally declared attrs for tooling."""
        if not bool(getattr(type(self), "__init_service_base_attrs__", False)):
            return
        self._audio_tracks_to_exclude = None
        self._disc_output_name_cache = None
        self._sp_index_by_bdmv = None
        self._subtitle_cache = None
        self._track_flac_map = None
        self.approx_episode_duration_seconds = None
        self.bdmv_path = None
        self.bluray_folders = None
        self.checked = None
        self.configuration = None
        self.episode_subtitle_languages = None
        self.movie_mode = None
        self.progress_dialog = None
        self.sub_files = None
        self.tmp_folders = None

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

    def t(self, text: str) -> str:
        """Stub for `t`."""
        raise NotImplementedError

    def _progress(self, value: Optional[int]=None, text: Optional[str]=None):
        """Stub for `_progress`."""
        raise NotImplementedError

    def _preload_subtitles(self, file_paths: list[str], cancel_event: Optional[threading.Event]=None):
        """Preload subtitles into cache with platform-aware fallback strategy."""
        raise NotImplementedError

    def _preload_subtitles_single(self, file_paths: list[str], cancel_event: Optional[threading.Event]=None):
        """Parse subtitles in single-process mode."""
        raise NotImplementedError

    def _preload_subtitles_multiprocess(self, file_paths: list[str], cancel_event: Optional[threading.Event]=None):
        """Parse subtitles in multiprocessing mode."""
        raise NotImplementedError

    @staticmethod
    def get_available_drives():
        """Stub for `get_available_drives`."""
        raise NotImplementedError

    def get_main_mpls(self, bluray_folder: str, checked: bool) -> str:
        """Stub for `get_main_mpls`."""
        raise NotImplementedError

    def select_mpls_from_table(self, table: QTableWidget) -> Generator[str, Chapter, str]:
        """Stub for `select_mpls_from_table`."""
        raise NotImplementedError

    def _resolve_disc_output_name(self, selected_mpls_no_ext: str) -> str:
        """Stub for `_resolve_disc_output_name`."""
        raise NotImplementedError

    @staticmethod
    def _configuration_default_chapter_segments_checked(configuration: dict[int, dict[str, int | str]]) -> None:
        """Stub for `_configuration_default_chapter_segments_checked`."""
        raise NotImplementedError

    def generate_configuration(self, table: QTableWidget, sub_combo_index: Optional[dict[int, int]]=None, subtitle_index: Optional[int]=None) -> dict[int, dict[str, int | str]]:
        """Stub for `generate_configuration`."""
        raise NotImplementedError

    @staticmethod
    def _group_selected_mpls_by_folder_runs(selected_mpls: list[tuple[str, str]]) -> list[list[tuple[str, str]]]:
        """Stub for `_group_selected_mpls_by_folder_runs`."""
        raise NotImplementedError

    def _volume_configuration_no_sub_files(self, volume_selected: list[tuple[str, str]], cancel_event: Optional[threading.Event]=None) -> dict[int, dict[str, int | str]]:
        """Episode rows for one disc's selected main MPLS list (no subtitle files). Keys 0..n-1 local."""
        raise NotImplementedError

    def generate_configuration_from_selected_mpls(self, selected_mpls: list[tuple[str, str]], sub_combo_index: Optional[dict[int, int]]=None, subtitle_index: Optional[int]=None, cancel_event: Optional[threading.Event]=None) -> dict[int, dict[str, int | str]]:
        """Stub for `generate_configuration_from_selected_mpls`."""
        raise NotImplementedError

    def generate_bluray_subtitle(self, table: Optional[QTableWidget]=None, configuration: Optional[dict[int, dict[str, int | str]]]=None, cancel_event: Optional[threading.Event]=None):
        """Stub for `generate_bluray_subtitle`."""
        raise NotImplementedError

    def _group_mkv_paths_by_bdmv(self, sorted_paths: list[str], bdmv_keys: list[int]) -> dict[int, list[str]]:
        """Map episode MKV paths to configuration bdmv_index (from BD_Vol_XXX in filename)."""
        raise NotImplementedError

    @staticmethod
    def _detect_repeated_single_m2ts_mpls(mpls_path: str) -> tuple[bool, str]:
        """
        Detect menu-like MPLS that loops the exact same clip window repeatedly.
        Condition: in_out_time has >10 items and all entries are identical.
        Returns (True, "<clip>.m2ts") when matched.
        """
        raise NotImplementedError

    def _write_remux_segment_chapter_txt(self, mpls_path: str, start_chapter: int, end_chapter: int, out_path: str) -> None:
        """Write OGM chapter file for one episode remux segment.

        Episode covers MPLS chapter marks with indices ``start_chapter`` .. ``end_chapter - 1``
        (same half-open interval as split). For each original mark ``j`` in that range:
        new index is ``j - start_chapter + 1`` (e.g. start 11 → new 01..06 for j=11..16),
        timestamp is ``offset(j) - offset(start_chapter)`` (first chapter is always 0).
        """
        raise NotImplementedError

    def _ordered_episode_confs_by_bdmv(self, configuration: dict[int, dict[str, int | str]]) -> dict[int, list[dict[str, int | str]]]:
        """Stub for `_ordered_episode_confs_by_bdmv`."""
        raise NotImplementedError

    def _add_chapter_to_mkv_from_configuration(self, mkv_files: list[str], configuration: dict[int, dict[str, int | str]], cancel_event: Optional[threading.Event]=None) -> None:
        """Stub for `_add_chapter_to_mkv_from_configuration`."""
        raise NotImplementedError

    @staticmethod
    def _parse_timecode_to_sec(raw: str) -> Optional[float]:
        """Stub for `_parse_timecode_to_sec`."""
        raise NotImplementedError

    @staticmethod
    def _split_parts_windows_from_mkvmerge_cmd(cmd: str) -> list[tuple[float, float]]:
        """Stub for `_split_parts_windows_from_mkvmerge_cmd`."""
        raise NotImplementedError

    @staticmethod
    def _chapter_bounds_from_split_windows(mpls_path: str, windows: list[tuple[float, float]]) -> list[tuple[int, int]]:
        """Stub for `_chapter_bounds_from_split_windows`."""
        raise NotImplementedError

    def _add_chapter_to_mkv_by_duration(self, mkv_files: list[str], table: Optional[QTableWidget]=None, selected_mpls: Optional[list[tuple[str, str]]]=None, cancel_event: Optional[threading.Event]=None) -> None:
        """Stub for `_add_chapter_to_mkv_by_duration`."""
        raise NotImplementedError

    def add_chapter_to_mkv(self, mkv_files, table: Optional[QTableWidget]=None, selected_mpls: Optional[list[tuple[str, str]]]=None, cancel_event: Optional[threading.Event]=None, configuration: Optional[dict[int, dict[str, int | str]]]=None):
        """Apply chapters to each episode MKV from configuration (remux / encode).

        For an episode with ``start_at_chapter=11`` and ``end_at_chapter=17``, writes six
        entries ``Chapter 01``..``Chapter 06`` at times 0 and ``offset(j)-offset(11)`` for
        MPLS marks ``j`` = 11..16 (new ordinal = ``j - 10`` in that example).
        """
        raise NotImplementedError

    def completion(self):
        """Finalize folder layout after processing and clean temporary artifacts."""
        raise NotImplementedError

    def _create_sp_mkvs_from_entries(self, bdmv_index_conf: dict[int, list[dict[str, int | str]]], sp_entries: list[dict[str, int | str]], sps_folder: str, cancel_event: Optional[threading.Event]=None) -> list[tuple[int, str]]:
        """Stub for `_create_sp_mkvs_from_entries`."""
        raise NotImplementedError

    def _write_chapter_txt_from_mpls(self, mpls_path: str, chapter_txt_path: str) -> list[float]:
        """Stub for `_write_chapter_txt_from_mpls`."""
        raise NotImplementedError

    def _get_chapter_offsets(self, mpls_path: str) -> list[float]:
        """Stub for `_get_chapter_offsets`."""
        raise NotImplementedError

    def _write_custom_chapter_for_segment(self, mpls_path: str, chapter_txt_path: str, output_name: str):
        """Parse SP suffix like beginning_to_chapter_4, chapter_33_to_chapter_40, chapter_33_to_ending; same bounds as --split parts."""
        raise NotImplementedError

    def _mkv_sort_key(self, p: str):
        """Stub for `_mkv_sort_key`."""
        raise NotImplementedError

    @staticmethod
    def _default_track_selection_from_streams(streams: list[dict[str, object]], pid_to_lang: Optional[dict[int, str]]=None) -> tuple[list[str], list[str]]:
        """Stub for `_default_track_selection_from_streams`."""
        raise NotImplementedError

    @staticmethod
    def _read_media_streams(media_path: str) -> list[dict[str, object]]:
        """Stub for `_read_media_streams`."""
        raise NotImplementedError

    @staticmethod
    def _stream_service_id(stream: dict) -> Optional[int]:
        """MPEG-TS elementary stream id from stream metadata field ``id`` (e.g. ``0x1011``)."""
        raise NotImplementedError

    @staticmethod
    def _stream_index_to_service_pid(m2ts_path: str) -> dict[int, int]:
        """Map stream index (0,1,…) → TS PID from ``streams[].id``. m2ts has no reliable language tags."""
        raise NotImplementedError

    @staticmethod
    def _m2ts_track_streams(m2ts_path: str) -> list[dict[str, object]]:
        """Stub for `_m2ts_track_streams`."""
        raise NotImplementedError

    @staticmethod
    def _m2ts_duration_90k(m2ts_path: str) -> int:
        """Stub for `_m2ts_duration_90k`."""
        raise NotImplementedError

    @staticmethod
    def _m2ts_frame_count(m2ts_path: str) -> int:
        """Stub for `_m2ts_frame_count`."""
        raise NotImplementedError

    @staticmethod
    def _video_frame_count_static(media_path: str) -> int:
        """Stub for `_video_frame_count_static`."""
        raise NotImplementedError

    @staticmethod
    def _is_audio_only_media(media_path: str) -> bool:
        """Stub for `_is_audio_only_media`."""
        raise NotImplementedError

    @staticmethod
    def _extract_single_audio_from_mka(output_file: str):
        """Stub for `_extract_single_audio_from_mka`."""
        raise NotImplementedError

    @staticmethod
    def _is_silent_audio_file(path: str, threshold_db: float=-60.0) -> tuple[bool, float]:
        """Stub for `_is_silent_audio_file`."""
        raise NotImplementedError

    @staticmethod
    def _compress_audio_stream_to_flac(input_media: str, map_idx: str, out_flac: str) -> bool:
        """Stub for `_compress_audio_stream_to_flac`."""
        raise NotImplementedError

    @staticmethod
    def _pid_lang_from_mkvmerge_json(media_path: str) -> dict[int, str]:
        """Stub for `_pid_lang_from_mkvmerge_json`."""
        raise NotImplementedError

    @staticmethod
    def _mkvmerge_identify_json(media_path: str) -> dict[str, object]:
        """Stub for `_mkvmerge_identify_json`."""
        raise NotImplementedError

    @staticmethod
    def _fix_output_track_languages_with_mkvpropedit(output_mkv_path: str, input_m2ts_path: str, pid_to_lang: dict[int, str], selected_audio_ids: list[str], selected_sub_ids: list[str], override_lang_by_source_index: Optional[dict[str, str]]=None):
        """Stub for `_fix_output_track_languages_with_mkvpropedit`."""
        raise NotImplementedError

    @staticmethod
    def _ordered_track_slots_for_remux(m2ts_path: str, copy_audio_track: list[str], copy_sub_track: list[str]) -> list[dict[str, object]]:
        """Reference order: first video, then selected audios / subs by stream ``index``; PID from ``id`` hex."""
        raise NotImplementedError

    @staticmethod
    def _mkvmerge_tid_for_pid(m2ts_path: str, pid: int, slot_type: str) -> Optional[int]:
        """mkvmerge track id for this m2ts = stream ``index`` of the stream with matching ``id`` (PID)."""
        raise NotImplementedError

    @staticmethod
    def _map_slots_to_mkvmerge_track_ids(ref_slots: list[dict[str, object]], m2ts_path: str) -> Optional[list[int]]:
        """Same slot order as ref_slots; each slot matched by PID on ``m2ts_path``."""
        raise NotImplementedError

    @staticmethod
    def _track_lists_from_mkvmerge_cmd(cmd: str) -> tuple[Optional[list[str]], Optional[list[str]]]:
        """
        Best-effort parse of ``-a`` / ``-s`` track lists from a mkvmerge command line.
        Returns (audio_ids, subtitle_ids); each entry is None if that flag was not found
        (caller should keep defaults from ``_select_tracks_for_source``).
        Returns (None, None) only when neither flag appears.
        """
        raise NotImplementedError

    @staticmethod
    def _fallback_track_lists(remux_cmd: str, copy_audio_track: list[str], copy_sub_track: list[str]) -> tuple[list[str], list[str]]:
        """Stub for `_fallback_track_lists`."""
        raise NotImplementedError

    @staticmethod
    def _split_segment_count_from_mkvmerge_cmd(cmd: str) -> Optional[int]:
        """
        Best-effort parse of mkvmerge ``--split``.
        Supports ``--split parts:...`` and ``--split chapters:...``.
        Returns segment count when recognizable; otherwise None.
        """
        raise NotImplementedError

    @staticmethod
    def _m2ts_clip_time_window_sec(m2ts_path: str, in_time: int, out_time: int) -> tuple[bool, float, float]:
        """
        (needs_split, start_sec, end_sec) for one playlist item.
        start = (in_time*2 - first_pts)/90000
        end   = start + (out_time-in_time)/45000
        No split when start==0 and end ~= file duration.
        """
        raise NotImplementedError

    @staticmethod
    def _mkvmerge_track_order_arg(mapped_ids: list[int]) -> str:
        """Stub for `_mkvmerge_track_order_arg`."""
        raise NotImplementedError

    @staticmethod
    def _mkvmerge_select_flags_from_mapped(mapped_ids: list[int], cur_identify: dict[str, object]) -> tuple[str, str, str]:
        """Return (d_flags, a_flags, s_flags) for mkvmerge: enable only mapped ids per type."""
        raise NotImplementedError

    @staticmethod
    def _series_episode_segments_bounds(chapter: Chapter, confs: list[dict[str, int | str]]) -> list[tuple[int, int]]:
        """Same (start_chapter, end_chapter) pairs as the series branch of ``_make_main_mpls_remux_cmd``."""
        raise NotImplementedError

    @staticmethod
    def _expected_mkvmerge_split_output_paths(output_norm: str, n_segments: int) -> list[str]:
        """Paths ``stem-001.mkv`` … mkvmerge writes when ``-o stem.mkv`` and ``--split parts:``."""
        raise NotImplementedError

    @staticmethod
    def _filter_ref_slots_common_across_playlist(ref_slots: list[dict[str, object]], stream_dir: str, rows: list[tuple[str, int, int]]) -> Optional[list[dict[str, object]]]:
        """
        Keep only slots whose PID exists (same codec_type) in every m2ts of this playlist.
        This implements "drop extra / keep common" to avoid aborting concat on missing optional tracks.
        """
        raise NotImplementedError

    @staticmethod
    def _audio_stream_by_pid(m2ts_path: str, pid: int) -> Optional[dict[str, object]]:
        """Stub for `_audio_stream_by_pid`."""
        raise NotImplementedError

    @staticmethod
    def _channel_layout_from_count(ch: int) -> str:
        """Stub for `_channel_layout_from_count`."""
        raise NotImplementedError

    @staticmethod
    def _build_slot_mux_plan_with_silence(ref_slots: list[dict[str, object]], m2ts_path: str) -> Optional[list[dict[str, object]]]:
        """
        Resolve each reference slot to current m2ts track id.
        Missing audio slots are marked with ``needs_silence=True``; video/subtitle must exist.
        """
        raise NotImplementedError

    @staticmethod
    def _create_silence_track_for_audio_slot(ref_audio_stream: dict[str, object], duration_sec: float, out_path: str) -> bool:
        """Stub for `_create_silence_track_for_audio_slot`."""
        raise NotImplementedError

    def _try_remux_mpls_track_aligned_concat(self, mpls_path: str, output_file: str, copy_audio_track: list[str], copy_sub_track: list[str], cover: str, cancel_event: Optional[threading.Event]=None) -> bool:
        """
        Fallback when direct ``mkvmerge … mpls`` fails (e.g. different track counts across m2ts).
        Track identity uses ``streams[].id`` (e.g. ``0x1011``) as PID; mkvmerge track id = stream ``index``.
        Per-clip m2ts mux with ``--split parts`` if needed, ``--track-order`` aligned to first m2ts, then
        ``+`` concat with ``--append-mode track``. Languages: ``_fix_output_track_languages_with_mkvpropedit`` on caller.
        """
        raise NotImplementedError

    def _try_remux_mpls_split_outputs_track_aligned(self, mpls_path: str, output_file: str, confs: list[dict[str, int | str]], copy_audio_track: list[str], copy_sub_track: list[str], cover: str, cancel_event: Optional[threading.Event]=None) -> bool:
        """
        Fallback when ``mkvmerge mpls`` with ``--split parts`` fails but multiple episode MKVs are required.
        For each episode window on the MPLS timeline, mux overlapping m2ts slices with PID-aligned
        ``--track-order``, then ``+`` concat slices; writes ``basename-001.mkv``, ``-002.mkv``, … like mkvmerge.
        """
        raise NotImplementedError

    def _select_tracks_for_source(self, source_path: str, pid_to_lang: Optional[dict[int, str]]=None, config_key: Optional[str]=None) -> tuple[list[str], list[str]]:
        """Stub for `_select_tracks_for_source`."""
        raise NotImplementedError

    @staticmethod
    def _sp_track_key_from_entry(entry: dict[str, int | str]) -> str:
        """Stub for `_sp_track_key_from_entry`."""
        raise NotImplementedError

    def _prepare_episode_run(self, table: Optional[QTableWidget], folder_path: str, configuration: Optional[dict[int, dict[str, int | str]]], ensure_tools: bool) -> tuple[str, set[str], dict[int, list[dict[str, int | str]]]]:
        """Stub for `_prepare_episode_run`."""
        raise NotImplementedError

    def _collect_target_mkv_files(self, dst_folder: str, mkv_files_before: set[str]) -> list[str]:
        """Stub for `_collect_target_mkv_files`."""
        raise NotImplementedError

    def _apply_episode_output_names(self, mkv_files: list[str], output_names: Optional[list[str]]=None) -> list[str]:
        """Stub for `_apply_episode_output_names`."""
        raise NotImplementedError

    def _build_main_episode_mkvs(self, bdmv_index_conf: dict[int, list[dict[str, int | str]]], dst_folder: str, cancel_event: Optional[threading.Event]=None) -> None:
        """Stub for `_build_main_episode_mkvs`."""
        raise NotImplementedError

    def _run_shell_command(self, cmd: str) -> int:
        """Stub for `_run_shell_command`."""
        raise NotImplementedError

    def _run_single_command(self, cmd: str) -> int:
        """Stub for `_run_single_command`."""
        raise NotImplementedError

    def _make_main_mpls_remux_cmd(self, confs: list[dict[str, int | str]], dst_folder: str, bdmv_index: int, disc_count: int, *, ensure_disc_out_dir: bool=False) -> tuple[str, str, str, str, str, dict[int, str], list[str], list[str]]:
        """Stub for `_make_main_mpls_remux_cmd`."""
        raise NotImplementedError

    def episodes_remux(self, table: Optional[QTableWidget], folder_path: str, selected_mpls: Optional[list[tuple[str, str]]]=None, configuration: Optional[dict[int, dict[str, int | str]]]=None, cancel_event: Optional[threading.Event]=None, ensure_tools: bool=True, sp_entries: Optional[list[dict[str, int | str]]]=None, episode_output_names: Optional[list[str]]=None, episode_subtitle_languages: Optional[list[str]]=None):
        """Stub for `episodes_remux`."""
        raise NotImplementedError

    def episodes_encode(self, table: Optional[QTableWidget], folder_path: str, selected_mpls: Optional[list[tuple[str, str]]]=None, configuration: Optional[dict[int, dict[str, int | str]]]=None, cancel_event: Optional[threading.Event]=None, ensure_tools: bool=True, vpy_paths: Optional[list[str]]=None, sp_vpy_paths: Optional[list[str]]=None, sp_entries: Optional[list[dict[str, int | str]]]=None, episode_output_names: Optional[list[str]]=None, episode_subtitle_languages: Optional[list[str]]=None, vspipe_mode: str='bundle', x265_mode: str='bundle', x265_params: str='', sub_pack_mode: str='external'):
        """Stub for `episodes_encode`."""
        raise NotImplementedError

    def process_audio_to_flac(self, output_file, dst_folder, i, source_file: Optional[str]=None) -> tuple[int, dict[int, str], list[str]]:
        """Stub for `process_audio_to_flac`."""
        raise NotImplementedError

    def flac_task(self, output_file, dst_folder, i, source_file: Optional[str]=None):
        """Stub for `flac_task`."""
        raise NotImplementedError

    def encode_task(self, output_file, dst_folder, i, vpy_path: str, vspipe_mode: str, x265_mode: str, x265_params: str, sub_pack_mode: str, source_file: Optional[str]=None):
        """Stub for `encode_task`."""
        raise NotImplementedError

    def generate_remux_cmd(self, track_count, track_info, flac_files, output_file, mkv_file, hevc_file: Optional[str]=None):
        """Stub for `generate_remux_cmd`."""
        raise NotImplementedError

    def extract_lossless(self, mkv_file: str, dolby_truehd_tracks: list[int], output_base: Optional[str]=None) -> tuple[int, dict[int, str]]:
        """Stub for `extract_lossless`."""
        raise NotImplementedError

