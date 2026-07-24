"""IDE contracts for the split `BluraySubtitle` service.

The declarations are verified against the mixins by
`tools/check_split_contracts.py`.
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Optional, Generator

from PyQt6.QtWidgets import QTableWidget

from src.bdmv import Chapter
from src.runtime.remux import RemuxMainJob, RemuxRequest
from src.runtime.encode import EncodeRequest, EncodeRow
from src.runtime.sp import SpEntry, SpJob


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

    def merge_subtitles(self, selected_mpls: list[tuple[str, str]], movie_tasks: Optional[list[tuple[str, str, str]]]=None, subtitle_suffix: str='', cancel_event: Optional[threading.Event]=None) -> list[str]:
        """Merge selected subtitle rows and write both disc-root and playlist-adjacent outputs."""
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
    def _split_parts_windows_from_mkvmerge_cmd(cmd: str, *, mpls_stem: Optional[str] = None) -> list[tuple[float, float]]:
        """Stub for `_split_parts_windows_from_mkvmerge_cmd`."""
        raise NotImplementedError

    @staticmethod
    def _split_parts_windows_from_mkvmerge_one_line(line: str) -> list[tuple[float, float]]:
        """Stub for ``_split_parts_windows_from_mkvmerge_one_line``."""
        raise NotImplementedError

    @staticmethod
    def _chapter_bounds_from_split_windows(mpls_path: str, windows: list[tuple[float, float]]) -> list[tuple[int, int]]:
        """Stub for `_chapter_bounds_from_split_windows`."""
        raise NotImplementedError

    def add_chapters_to_mkv(self, mkv_targets: list[tuple[str, str]], selected_mpls: list[str], edit_original: bool, cancel_event: Optional[threading.Event]=None) -> None:
        """Match ordered MKVs to ordered playlists and apply the resulting chapter documents."""
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

    def _build_sp_outputs(
            self,
            jobs: list[SpJob],
            cancel_event: Optional[threading.Event] = None,
            progress_cb: Optional[Callable[[int, str], None]] = None,
    ) -> list[tuple[int, str]]:
        """Stub for `_build_sp_outputs`."""
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
    def _fix_output_track_languages_with_mkvpropedit(output_mkv_path: str, input_m2ts_path: str, selected_audio_ids: list[str], selected_sub_ids: list[str], override_lang_by_source_index: Optional[dict[str, str]]=None, dovi_plan: Optional[dict[str, object]]=None) -> None:
        """Stub for `_fix_output_track_languages_with_mkvpropedit`."""
        raise NotImplementedError

    @staticmethod
    def _ordered_track_slots_for_remux(m2ts_path: str, copy_audio_track: list[str], copy_sub_track: list[str], dovi_plan: Optional[dict[str, object]]=None) -> list[dict[str, object]]:
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
    def _remux_cmd_shell_lines(cmd: str) -> list[str]:
        """Stub for ``_remux_cmd_shell_lines``."""
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
    def _split_segment_count_from_mkvmerge_one_line(line: str) -> Optional[int]:
        """Stub for ``_split_segment_count_from_mkvmerge_one_line``."""
        raise NotImplementedError

    @staticmethod
    def _split_chapters_ints_from_mkvmerge_one_line(line: str) -> Optional[list[int]]:
        """Stub for ``_split_chapters_ints_from_mkvmerge_one_line``."""
        raise NotImplementedError

    @staticmethod
    def _mkvmerge_output_path_from_cmd(cmd: str) -> Optional[str]:
        """Parse ``-o`` / ``--output`` path from a full mkvmerge command line (after template substitution)."""
        raise NotImplementedError

    @staticmethod
    def _mkvmerge_output_path_from_line(line: str) -> Optional[str]:
        """Stub for ``_mkvmerge_output_path_from_line``."""
        raise NotImplementedError

    @staticmethod
    def _conf_selected_mpls_stem(conf: dict[str, int | str]) -> str:
        """Stub for ``_conf_selected_mpls_stem``."""
        raise NotImplementedError

    @staticmethod
    def _mkvmerge_expected_paths_for_shell_line(
            line: str, confs: list[dict[str, int | str]], mpls_path_default: str) -> tuple[Optional[str], list[str]]:
        """Stub for ``_mkvmerge_expected_paths_for_shell_line``."""
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
    def _episode_float_windows_from_config_bounds(mpls_path: str, confs: list[dict[str, int | str]]) -> list[tuple[float, float]]:
        """Stub for ``_episode_float_windows_from_config_bounds``."""
        raise NotImplementedError

    @staticmethod
    def _time_windows_from_split_chapter_numbers(mpls_path: str, cuts: list[int]) -> list[tuple[float, float]]:
        """Stub for ``_time_windows_from_split_chapter_numbers``."""
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

    def _create_silence_track_for_audio_slot(ref_audio_stream: dict[str, object], duration_sec: float, out_path: str) -> bool:
        """Stub for `_create_silence_track_for_audio_slot`."""
        raise NotImplementedError

    def _try_remux_mpls_track_aligned(self, mpls_path: str, output_file: str, copy_audio_track: list[str], copy_sub_track: list[str], cover: str, cancel_event: Optional[threading.Event]=None, *, max_play_items: Optional[int]=None) -> bool:
        """
        Fallback when direct ``mkvmerge … mpls`` fails (e.g. different track counts across m2ts).
        Track identity uses ``streams[].id`` (e.g. ``0x1011``) as PID; mkvmerge track id = stream ``index``.
        Per-clip m2ts mux with ``--split parts`` if needed, ``--track-order`` aligned to first m2ts, then
        ``+`` concat with ``--append-mode track``. Callers apply configured languages after success.
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

    def _prepare_remux_main_jobs(self, request: RemuxRequest) -> tuple[str, list[RemuxMainJob]]:
        """Stub for `_prepare_remux_main_jobs`."""
        raise NotImplementedError

    def _prepare_sp_jobs(
            self,
            entries: tuple[SpEntry, ...],
            destination_folder: str,
            main_jobs: list[RemuxMainJob],
            track_selection_config: dict[str, dict[str, list[str]]] | None,
            track_language_config: dict[str, dict[str, str]],
    ) -> list[SpJob]:
        """Stub for `_prepare_sp_jobs`."""
        raise NotImplementedError

    def _apply_episode_output_names(self, mkv_files: list[str], output_names: Optional[list[str]]=None) -> list[str]:
        """Stub for `_apply_episode_output_names`."""
        raise NotImplementedError

    def _build_main_episode_mkvs(
            self,
            jobs: list[RemuxMainJob],
            cancel_event: Optional[threading.Event] = None,
            *,
            mux_progress_base: int = 0,
            mux_progress_span: int = 380,
    ) -> list[str]:
        """Stub for `_build_main_episode_mkvs`."""
        raise NotImplementedError

    def _remux_remap_chapter_skip_after_rename(self, mkv_files: list[str]) -> None:
        """Stub for `_remux_remap_chapter_skip_after_rename`."""
        raise NotImplementedError

    def _run_shell_command(self, cmd: str) -> int:
        """Stub for `_run_shell_command`."""
        raise NotImplementedError

    def _run_shell_command_detailed(self, cmd: str) -> tuple[int, list[int]]:
        """Stub for `_run_shell_command_detailed`."""
        raise NotImplementedError

    def _run_single_command(self, cmd: str) -> int:
        """Stub for `_run_single_command`."""
        raise NotImplementedError

    def _make_main_mpls_remux_cmd(
            self,
            confs: list[dict[str, int | str]],
            dst_folder: str,
            bdmv_index: int,
            disc_count: int,
            *,
            ensure_disc_out_dir: bool = False,
    ) -> tuple[str, str, str, str, str, list[str], list[str]]:
        """Stub for `_make_main_mpls_remux_cmd`."""
        raise NotImplementedError

    def episodes_remux(self, request: RemuxRequest, cancel_event: Optional[threading.Event]=None) -> None:
        """Stub for `episodes_remux`."""
        raise NotImplementedError

    def _encode_mkv_rows(
            self,
            request: EncodeRequest,
            main_rows: list[EncodeRow],
            sp_rows: list[EncodeRow],
            cancel_event: Optional[threading.Event],
            *,
            companion_root: str = '',
            progress_base: int = 0,
            progress_span: int = 1000,
    ) -> None:
        """Stub for `_encode_mkv_rows`."""
        raise NotImplementedError

    def episodes_encode(
            self,
            request: EncodeRequest,
            cancel_event: Optional[threading.Event] = None,
    ) -> None:
        """Stub for `episodes_encode`."""
        raise NotImplementedError

    def process_audio_to_flac(self, output_file, dst_folder, i, source_file: Optional[str]=None) -> tuple[int, dict[int, str], list[str]]:
        """Stub for `process_audio_to_flac`."""
        raise NotImplementedError

    def flac_task(self, output_file, dst_folder, i, source_file: Optional[str]=None):
        """Stub for `flac_task`."""
        raise NotImplementedError

    def encode_task(self, output_file, dst_folder, i, vpy_path: str, vspipe_mode: str, x265_mode: str, x265_params: str, sub_pack_mode: str, source_file: Optional[str]=None, encode_tool: str='x265', encode_bit_depth: str='10'):
        """Stub for `encode_task`."""
        raise NotImplementedError

    def generate_remux_cmd(self, track_count, track_info, flac_files, output_file, mkv_file, encoded_video_file: Optional[str]=None):
        """Stub for `generate_remux_cmd`."""
        raise NotImplementedError

    def extract_lossless(self, mkv_file: str, output_base: Optional[str]=None) -> tuple[int, dict[int, str]]:
        """Stub for `extract_lossless`."""
        raise NotImplementedError

    def _assign_movie_sp_output_names(self, entries: list[dict[str, object]]) -> None:
        raise NotImplementedError

    @staticmethod
    def _audio_stream_ok_for_pcm_silence_template(stream: dict[str, object]) -> bool:
        raise NotImplementedError

    @staticmethod
    def _canonical_remux_mkv_path(path: str) -> str:
        raise NotImplementedError

    @staticmethod
    def _chapter_split_bounds_from_multi_line_remux_cmd(cmd0: str, confs: list[dict[str, object]]) -> list[tuple[int, int]]:
        raise NotImplementedError

    def _cleanup_getnative_artifacts(self):
        raise NotImplementedError

    @staticmethod
    def _clip_ref_slots_for_m2ts(ref_slots: list[dict[str, object]], m2ts_path: str, dovi_plan: Optional[dict[str, object]]=None) -> list[dict[str, object]]:
        raise NotImplementedError

    @staticmethod
    def _collect_tsmuxer_demux_files(demux_dir: str, stem_hint: str) -> list[tuple[int, str]]:
        raise NotImplementedError

    def _compute_mkv_id_to_m2ts_pid_core(self, mp: str, mcfg: dict[str, object]) -> dict[int, int]:
        raise NotImplementedError

    def _compute_mkv_id_to_m2ts_pid_for_main_mpls(self, mpls_path: str) -> dict[int, int]:
        raise NotImplementedError

    @staticmethod
    def _configuration_drop_invalid_episode_rows(configuration: dict[int, dict[str, int | str]]) -> dict[int, dict[str, int | str]]:
        raise NotImplementedError

    def _decode_truehd_atmos_thd_files(self, output_base: str, track_info: dict[int, str]) -> None:
        raise NotImplementedError

    @staticmethod
    def _dedupe_remux_shell_lines(cmd: str) -> str:
        raise NotImplementedError

    @staticmethod
    def _detect_sp_looping_mpls(mpls_path: str) -> Optional[dict[str, object]]:
        raise NotImplementedError

    @staticmethod
    def _disc_paths_for_output_title(bdmv_root: str, selected_mpls_no_ext: str) -> tuple[str, str, str]:
        raise NotImplementedError

    @staticmethod
    def _dovi_tool_exe() -> str:
        raise NotImplementedError

    @staticmethod
    def _dovi_tool_mux_bl_el(bl_hevc: str, el_hevc: str) -> bool:
        raise NotImplementedError

    @staticmethod
    def _enrich_configuration_chapter_bounds(configuration: dict[int, dict[str, int | str]]) -> None:
        raise NotImplementedError

    @staticmethod
    def _episode_ident_track_type(ident_ep: dict, tid: int) -> str:
        raise NotImplementedError

    @staticmethod
    def _episode_sp_mux_mkv_cache_key(episode_mkv: str) -> str:
        raise NotImplementedError

    def _estimate_native_from_image(self, image_path: str) -> Optional[dict]:
        raise NotImplementedError

    def _extract_sample_images(self, video_path: str, temp_dir: str, max_total: int=100) -> list[str]:
        raise NotImplementedError

    @staticmethod
    def _ffmpeg_compress_wav_to_codec(wav_path: str, out_path: str, codec: str) -> bool:
        raise NotImplementedError

    @staticmethod
    def _filter_video_pids_for_dovi_plan(video_pids: list[int], dovi_plan: Optional[dict[str, object]]) -> list[int]:
        raise NotImplementedError

    @staticmethod
    def _finalize_configuration_episode_rows(configuration: dict[int, dict[str, int | str]]) -> dict[int, dict[str, int | str]]:
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
    def _ident_muxable_track_count(ident_ep: dict) -> int:
        raise NotImplementedError

    @staticmethod
    def _in_out_play_item_duration_sec(row: tuple) -> float:
        raise NotImplementedError

    @staticmethod
    def _in_out_play_item_key(row: tuple) -> tuple[str, int, int]:
        raise NotImplementedError

    def _infer_native_resolution(self, video_path: str) -> Optional[dict]:
        raise NotImplementedError

    @staticmethod
    def _int_from_mkvmerge_prop(raw: object) -> Optional[int]:
        raise NotImplementedError

    @staticmethod
    def _log_getnative(message: str):
        raise NotImplementedError

    @staticmethod
    def _log_mkvmerge_identify_slot_gap(ident_path: str, probe_m2ts: str, ref_slots: list[dict[str, object]], ident: Optional[dict[str, object]], reason: str, missing_slots: Optional[list[dict[str, object]]]=None) -> None:
        raise NotImplementedError

    @staticmethod
    def _lossless_codec_choice(map_by_idx: dict[str, str], idx_str: str, default: str='flac') -> str:
        raise NotImplementedError

    def _lossless_submap_from_track_cfg(self, cfg_all: dict[str, object], nk: str) -> dict[str, str]:
        raise NotImplementedError

    @staticmethod
    def _map_selected_tracks_to_mpls_track_ids(mpls_path: str, selected_audio_track_indexes: list[str], selected_sub_track_indexes: list[str]) -> tuple[list[str], list[str]]:
        raise NotImplementedError

    @staticmethod
    def _merged_mkv_id_to_m2ts_pid_episode_sp(main_map: dict[int, int], sp_selected_pids: list[int]) -> dict[int, int]:
        raise NotImplementedError

    @staticmethod
    def _mkvmerge_audio_track_count(media_path: str) -> int:
        raise NotImplementedError

    @staticmethod
    def _mkvmerge_das_flag_strings_for_m2ts(m2ts_path: str, copy_audio_track: list[str], copy_sub_track: list[str], dovi_plan: Optional[dict[str, object]]=None) -> tuple[str, str, str]:
        raise NotImplementedError

    @staticmethod
    def _mkvmerge_dovi_primary_video_opts(mpls_path: str, dovi_plan: Optional[dict[str, object]]) -> str:
        raise NotImplementedError

    @staticmethod
    def _mkvmerge_exe() -> str:
        raise NotImplementedError

    @staticmethod
    def _mkvmerge_ident_transport_pid(props: object) -> Optional[int]:
        raise NotImplementedError

    def _mkvmerge_identify_covers_remux_slots(self, source_path: str, copy_audio_track: list[str], copy_sub_track: list[str]) -> bool:
        raise NotImplementedError

    @staticmethod
    def _mkvmerge_identify_tid_for_pid_file(media_path: str, pid: int) -> Optional[int]:
        raise NotImplementedError

    @staticmethod
    def _mkvmerge_line_source_mpls_stem(line: str) -> str:
        raise NotImplementedError

    @staticmethod
    def _mkvmerge_track_ids_by_type(media_path: str, track_type: str) -> list[int]:
        raise NotImplementedError

    def _movie_sp_covered_by_table2(self, bdmv_index: int, sp_detail: str, table2_details: list[str]) -> bool:
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

    def _mux_episode_linked_sp_mkvmerge(self, *, episode_mkv: str, sp_mpls_path: str, episode_main_mpls: str, cmd_audio_sp: list[str], cmd_sub_sp: list[str], language_by_sp_track_id: dict[str, str], cancel_event: Optional[threading.Event]) -> bool:
        raise NotImplementedError

    @staticmethod
    def _norm_lang_for_track_selection(raw: object) -> str:
        raise NotImplementedError

    @staticmethod
    def _norm_lang_mkv(lcode: str) -> str:
        raise NotImplementedError

    @staticmethod
    def _parse_tsmuxer_probe_output(text: str) -> list[dict[str, object]]:
        raise NotImplementedError

    @staticmethod
    def _pid_lang_from_m2ts_track_info(track_info: list[dict[str, object]]) -> dict[int, str]:
        raise NotImplementedError

    @staticmethod
    def _pid_lang_from_media_streams(streams: list[dict[str, object]]) -> dict[int, str]:
        raise NotImplementedError

    def _post_remux_finalize_episodes(self, jobs: list[RemuxMainJob], cancel_event: Optional[threading.Event]) -> list[str]:
        raise NotImplementedError

    @staticmethod
    def _probe_fps_from_tsmuxer_tracks(tracks: list[dict[str, object]]) -> str:
        raise NotImplementedError

    @staticmethod
    def _probe_m2ts_for_remux_source(source_path: str) -> tuple[str, str]:
        raise NotImplementedError

    @staticmethod
    def _read_m2ts_track_info(m2ts_path: str) -> list[dict[str, object]]:
        raise NotImplementedError

    @staticmethod
    def _ref_slot_pid_set(ref_slots: list[dict[str, object]]) -> set[int]:
        raise NotImplementedError

    def _remux_exclude_audio_track_ids(self, mkv_file: str, track_info: dict[int, str], track_flac_map: dict[int, str], *, drop_all_source_audio: bool=False) -> list[int]:
        raise NotImplementedError

    def _remux_fallback_append_silence_pid_order(self, exe: str, ui: str, base_mkv: str, m2ts_pid_list: list[int], audio_slots: list[dict[str, object]], first_m2ts: str, clip_duration_sec: float, work_dir: str, part_tag: str, pid_to_lang: dict[int, str], out_mkv: str) -> Optional[list[int]]:
        raise NotImplementedError

    @staticmethod
    def _remux_fallback_demux_slot_guess(fpth: str) -> str:
        raise NotImplementedError

    def _remux_fallback_merge_demux_with_base(self, exe: str, ui: str, base_mkv: Optional[str], base_pid_list: list[int], demux_by_pid: dict[int, str], pid_to_lang: dict[int, str], out_mkv: str, split_arg: Optional[str]=None, *, base_track_by_pid: Optional[dict[int, int]]=None, pid_order: Optional[list[int]]=None) -> bool:
        raise NotImplementedError

    @staticmethod
    def _remux_fallback_promote_merge_to_part_out(part_out: str, merged_path: str) -> bool:
        raise NotImplementedError

    @staticmethod
    def _remux_fallback_run_tsmuxer_demux_subset(m2ts_path: str, work_dir: str, part_tag: str, pid_to_lang: dict[int, str], want_pids: set[int], tsm_all: list[dict[str, object]], *, path_tag: Optional[str]=None) -> Optional[dict[int, str]]:
        raise NotImplementedError

    def _remux_aligned_clip(self, m2ts_path: str, mpls_path: str, first_m2ts: str, ref_slots: list[dict[str, object]], part_out: str, split_arg: str, clip_duration_sec: float, work_dir: str, part_tag: str, exe: str, ui: str) -> bool:
        raise NotImplementedError

    @staticmethod
    def _remux_parsed_chapter_bounds_for_theory_count(cmd: str, confs: list[dict[str, int | str]], mpls_path0: str, n_expect: int) -> Optional[list[tuple[int, int]]]:
        raise NotImplementedError

    def _resolve_lossless_audio_map_for_mkv(self, mkv_path: str, episode_i: int) -> dict[str, str]:
        raise NotImplementedError

    @staticmethod
    def _resolve_mpls_path_from_conf(conf: dict[str, int | str], bdmv_root: str='') -> str:
        raise NotImplementedError

    @staticmethod
    def _run_tsmuxer_probe(m2ts_path: str) -> str:
        raise NotImplementedError

    @staticmethod
    def _sanitize_movie_output_basename(name: str) -> str:
        raise NotImplementedError

    def _set_dovi_mux_plan_for_mpls(self, mpls_path: str) -> None:
        raise NotImplementedError

    @staticmethod
    def _slot_pids_in_order(slots: list[dict[str, object]]) -> list[int]:
        raise NotImplementedError

    def _sp_m2ts_detail_for_entry(self, bdmv_index: int, mpls_file: str, m2ts_files: list[str]) -> str:
        raise NotImplementedError

    @staticmethod
    def _split_parts_from_start_duration(duration_sec: float) -> str:
        raise NotImplementedError

    @staticmethod
    def _tsmuxer_demux_audio_use_track0_after_identify(fpth: str, slot_type: str) -> bool:
        raise NotImplementedError

    @staticmethod
    def _tsmuxer_demux_skip_audio_identify(fpth: str) -> bool:
        raise NotImplementedError

    @staticmethod
    def _tsmuxer_exe() -> str:
        raise NotImplementedError

    @staticmethod
    def _tsmuxer_has_video_and_subtitles(tracks: list[dict[str, object]]) -> bool:
        raise NotImplementedError

    @staticmethod
    def _tsmuxer_mpeg_pid(row: dict[str, object]) -> Optional[int]:
        raise NotImplementedError

    @staticmethod
    def _tsmuxer_rows_for_pids(tsm_all: list[dict[str, object]], want_pids: set[int]) -> Optional[list[dict[str, object]]]:
        raise NotImplementedError

    @staticmethod
    def _tsmuxer_tracks_ordered_for_ref_slots(tsmuxer_tracks: list[dict[str, object]], ref_slots: list[dict[str, object]]) -> list[dict[str, object]]:
        raise NotImplementedError

    @staticmethod
    def _video_pids_on_m2ts(m2ts_path: str) -> list[int]:
        raise NotImplementedError

    @staticmethod
    def _wav_channel_count(wav_path: str) -> int:
        raise NotImplementedError

    @staticmethod
    def _wav_channel_layout(wav_path: str) -> str:
        raise NotImplementedError

    @staticmethod
    def _write_tsmuxer_demux_meta(m2ts_path: str, tracks: list[dict[str, object]], pid_to_lang: dict[int, str], out_meta_path: str, fps_default: str) -> bool:
        raise NotImplementedError

    def build_movie_mode_configuration(self, selected_mpls: list[tuple[str, str]]) -> tuple[dict[int, dict[str, int | str]], list[str]]:
        raise NotImplementedError

    def build_movie_mode_sp_entries(self, configuration: dict[int, dict[str, int | str]]) -> list[dict[str, int | str]]:
        raise NotImplementedError

    @staticmethod
    def detect_dovi_mux_pair(mpls_path: str, probe_m2ts: str, mux_dolby_vision: bool) -> Optional[dict[str, object]]:
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

    @staticmethod
    def m2ts_sp_custom_segment_time_window_sec(mpls_path: str, output_name: str) -> Optional[tuple[float, float]]:
        raise NotImplementedError

    @staticmethod
    def mkvinfo_dolby_vision_track_id(mkv_path: str) -> Optional[int]:
        raise NotImplementedError

    @staticmethod
    def resolve_disc_output_title(bdmv_root: str, selected_mpls_no_ext: str) -> str:
        raise NotImplementedError

    @staticmethod
    def theoretical_remux_output_paths_ordered(cmd: str, confs: list[dict[str, int | str]], mpls_path_default: str) -> list[str]:
        raise NotImplementedError

