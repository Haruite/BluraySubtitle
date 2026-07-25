"""Auto-generated split target: subtitle_and_chapter_pipeline."""

from bisect import bisect_left
import os
import re
import shutil
import subprocess
import tempfile
import threading
from typing import Any, Callable, Optional

from PyQt6.QtWidgets import QTableWidget

from src.bdmv import Chapter, M2TS
from src.core import FFMPEG_PATH, MKV_MERGE_PATH, MKV_EXTRACT_PATH, find_mkvtoolnix, \
    mkvtoolnix_ui_language_arg, MKV_PROP_EDIT_PATH
from src.core.i18n import translate_text
from src.domain import MKV, Subtitle
from src.exports.utils import get_index_to_m2ts_and_offset, append_ogm_chapter_lines, force_remove_folder, \
    force_remove_file, print_terminal_line, print_exc_terminal, get_time_str, parse_time_to_seconds, run_command
from .service_base import BluraySubtitleServiceBase
from src.runtime.sp import SpJob, media_track_key
from .. import TaskCancelled


def _svc_cls():
    from ..services.bluray_subtitle_entry import BluraySubtitle
    return BluraySubtitle


class SubtitleChapterPipelineMixin(BluraySubtitleServiceBase):
    @staticmethod
    def _read_m2ts_track_info(m2ts_path: str) -> list[dict[str, object]]:
        """Read stream metadata for one m2ts file."""
        try:
            return list(_svc_cls()._m2ts_track_streams(m2ts_path) or [])
        except Exception:
            return []

    @staticmethod
    def _pid_lang_from_m2ts_track_info(track_info: list[dict[str, object]]) -> dict[int, str]:
        """Convert track info list to pid->language mapping."""
        out: dict[int, str] = {}
        for row in list(track_info or []):
            if not isinstance(row, dict):
                continue
            pid_raw: Any = (
                row.get("pid")
                or row.get("service_id")
                or row.get("id")
                or row.get("stream_id")
            )
            try:
                pid = int(str(pid_raw), 0) if isinstance(pid_raw, str) else int(pid_raw)
            except Exception:
                continue
            tags = row.get("tags") if isinstance(row.get("tags"), dict) else {}
            lang = (
                row.get("language")
                or tags.get("language")
                or tags.get("LANGUAGE")
                or ""
            )
            lang = str(lang).strip().lower()
            if lang:
                out[pid] = lang
        return out

    def merge_subtitles(
            self,
            selected_mpls: list[tuple[str, str]],
            movie_tasks: Optional[list[tuple[str, str, str]]] = None,
            subtitle_suffix: str = '',
            cancel_event: Optional[threading.Event] = None,
    ) -> list[str]:
        """Merge the selected subtitle rows and write every planned output without overwriting files."""
        movie_tasks = list(movie_tasks or [])
        subtitle_files = [task[0] for task in movie_tasks] if movie_tasks else list(self.sub_files or [])
        if not subtitle_files:
            raise ValueError(translate_text('Subtitle file is not selected'))

        self._progress(text='Loading Subtitles')
        self._preload_subtitles(subtitle_files, cancel_event=cancel_event)
        suffix = str(subtitle_suffix or '')
        output_jobs: list[tuple[Subtitle, str, str]] = []

        if movie_tasks:
            for subtitle_path, folder, selected_mpls_no_ext in movie_tasks:
                output_jobs.append((
                    self._subtitle_cache[subtitle_path].clone(),
                    folder + suffix,
                    selected_mpls_no_ext + suffix,
                ))
        else:
            self._progress(text='Generating Configuration')
            configuration = self.generate_configuration_from_selected_mpls(
                selected_mpls,
                cancel_event=cancel_event,
            )
            if not configuration:
                raise ValueError(translate_text('Task configuration is empty'))
            configuration_rows = [configuration[key] for key in sorted(configuration, key=int)]
            if len(configuration_rows) != len(subtitle_files):
                raise ValueError(translate_text(
                    'Could not map all selected subtitle files to the selected main playlists'
                ))

            merged_subtitle = None
            current_bdmv_index = None
            output_folder_base = ''
            output_mpls_base = ''
            for subtitle_index, (subtitle_path, row) in enumerate(zip(subtitle_files, configuration_rows)):
                if cancel_event and cancel_event.is_set():
                    raise TaskCancelled()
                self._progress(
                    int((subtitle_index + 1) / len(subtitle_files) * 700),
                    f'Merging {subtitle_index + 1}/{len(subtitle_files)}',
                )
                parsed_subtitle = self._subtitle_cache[subtitle_path]
                bdmv_index = int(row['bdmv_index'])
                if current_bdmv_index != bdmv_index:
                    if merged_subtitle is not None:
                        output_jobs.append((merged_subtitle, output_folder_base, output_mpls_base))
                    merged_subtitle = parsed_subtitle.clone()
                    current_bdmv_index = bdmv_index
                else:
                    if merged_subtitle.output_extension() != parsed_subtitle.output_extension():
                        raise ValueError(translate_text(
                            'Subtitle formats cannot be mixed within one merged output'
                        ))
                    offset_seconds = float(parse_time_to_seconds(row['offset']))
                    merged_subtitle.append_subtitle(parsed_subtitle, offset_seconds)
                output_folder_base = str(row['folder']) + suffix
                output_mpls_base = str(row['selected_mpls']) + suffix
            if merged_subtitle is not None:
                output_jobs.append((merged_subtitle, output_folder_base, output_mpls_base))
            self.configuration = configuration

        # Plan and validate every destination before the first file is created.
        output_paths: list[str] = []
        normalized_paths: set[str] = set()
        for merged_subtitle, folder_base, mpls_base in output_jobs:
            extension = merged_subtitle.output_extension()
            for output_path in (folder_base + extension, mpls_base + extension):
                normalized_path = os.path.normcase(os.path.abspath(output_path))
                if normalized_path in normalized_paths:
                    raise ValueError(translate_text('Duplicate output path: {path}').format(path=output_path))
                if os.path.exists(output_path):
                    raise FileExistsError(
                        translate_text('Output file already exists: {path}').format(path=output_path)
                    )
                normalized_paths.add(normalized_path)
                output_paths.append(output_path)

        for output_index, (merged_subtitle, folder_base, mpls_base) in enumerate(output_jobs, start=1):
            if cancel_event and cancel_event.is_set():
                raise TaskCancelled()
            self._progress(
                700 + int(output_index / len(output_jobs) * 300),
                f'Writing Subtitle File {output_index}/{len(output_jobs)}',
            )
            merged_subtitle.dump(folder_base, mpls_base)
        self._progress(1000, 'Done')
        return output_paths

    def _group_mkv_paths_by_bdmv(self, sorted_paths: list[str], bdmv_keys: list[int]) -> dict[int, list[str]]:
        """Map episode MKV paths to configuration bdmv_index (from BD_Vol_XXX in filename)."""
        if not sorted_paths:
            return {k: [] for k in bdmv_keys}
        if len(bdmv_keys) == 1:
            return {bdmv_keys[0]: list(sorted_paths)}
        out: dict[int, list[str]] = {k: [] for k in bdmv_keys}
        for p in sorted_paths:
            m = re.search(r'BD_Vol_(\d{3})', os.path.basename(p or ''), re.I)
            if m:
                try:
                    v = int(m.group(1))
                except Exception:
                    continue
                if v in out:
                    out[v].append(p)
        return out

    @staticmethod
    def _detect_repeated_single_m2ts_mpls(mpls_path: str) -> tuple[bool, str]:
        """
        Detect menu-like MPLS that loops the exact same clip window repeatedly.
        Condition: in_out_time has >10 items and all entries are identical.
        Returns (True, "<clip>.m2ts") when matched.
        """
        try:
            ch = Chapter(mpls_path)
            ios = list(ch.in_out_time or [])
            if len(ios) <= 10:
                return False, ''
            first = ios[0]
            if any(tuple(x) != tuple(first) for x in ios[1:]):
                return False, ''
            clip = str(first[0] or '').strip()
            if not clip:
                return False, ''
            return True, f'{clip}.m2ts'
        except Exception:
            return False, ''

    def _write_remux_segment_chapter_txt(
            self,
            mpls_path: str,
            start_chapter: int,
            end_chapter: int,
            out_path: str,
    ) -> None:
        """Write an OGM chapter file for one half-open episode segment.

        The segment contains original chapter marks ``start_chapter <= index < end_chapter``. Chapter
        numbers are rebased to start at 1, while timestamps are rebased to the selected start mark so the
        first retained chapter is always at 00:00:00.000.
        """
        chapter = Chapter(mpls_path)
        _, index_to_offset = get_index_to_m2ts_and_offset(chapter)
        chapter_count = sum(map(len, chapter.mark_info.values()))
        exclusive_playlist_end = chapter_count + 1
        bounded_start = max(1, min(int(start_chapter), exclusive_playlist_end))
        bounded_end = max(bounded_start + 1, min(int(end_chapter), exclusive_playlist_end))
        segment_origin_seconds = float(index_to_offset.get(bounded_start, 0.0))

        lines: list[str] = []
        for original_index in range(bounded_start, bounded_end):
            if original_index > chapter_count:
                break
            segment_index = original_index - bounded_start + 1
            absolute_offset_seconds = float(index_to_offset.get(original_index, 0.0))
            relative_offset_seconds = max(0.0, absolute_offset_seconds - segment_origin_seconds)
            append_ogm_chapter_lines(lines, segment_index, relative_offset_seconds)
        output_folder = os.path.dirname(out_path)
        if output_folder:
            os.makedirs(output_folder, exist_ok=True)
        with open(out_path, 'w', encoding='utf-8-sig') as chapter_file:
            chapter_file.write('\n'.join(lines) + ('\n' if lines else ''))
        print(
            f'{self.t("[chapter-debug] ")}{self.t("segment chapter file written: ")}{out_path} '
            f'(mpls={os.path.basename(mpls_path)} start={bounded_start} end={bounded_end} entries={len(lines) // 2})'
        )

    def _ordered_episode_confs_by_bdmv(
            self, configuration: dict[int, dict[str, int | str]]
    ) -> dict[int, list[dict[str, int | str]]]:
        by_bdmv: dict[int, list[dict[str, int | str]]] = {}
        for _, conf in (configuration or {}).items():
            bdmv_index = int(conf.get('bdmv_index') or 0)
            by_bdmv.setdefault(bdmv_index, []).append(conf)
        for bdmv_index, confs in by_bdmv.items():
            try:
                confs.sort(key=lambda c: int(c.get('chapter_index') or c.get('start_at_chapter') or 0))
            except Exception:
                pass
            by_bdmv[bdmv_index] = confs
        return by_bdmv

    def _add_chapter_to_mkv_from_configuration(
            self,
            mkv_files: list[str],
            configuration: dict[int, dict[str, int | str]],
            cancel_event: Optional[threading.Event] = None,
    ) -> None:
        by_bdmv = self._ordered_episode_confs_by_bdmv(configuration)
        bdmv_keys = sorted(by_bdmv.keys())
        sorted_paths = sorted(mkv_files, key=self._mkv_sort_key)
        grouped = self._group_mkv_paths_by_bdmv(sorted_paths, bdmv_keys)
        total_mkv = sum(len(grouped.get(b, [])) for b in bdmv_keys)
        done = 0
        chapter_txt = os.path.join(os.getcwd(), 'chapter.txt')
        for bdmv_index in bdmv_keys:
            paths = grouped.get(bdmv_index, [])
            confs = by_bdmv.get(bdmv_index, [])
            n = min(len(paths), len(confs))
            if len(paths) != len(confs):
                print(
                    f'{self.t("add_chapter_to_mkv: BD Vol ")}{bdmv_index}'
                    f'{self.t(" MKV count (")}{len(paths)}'
                    f'{self.t(") differs from configuration count (")}{len(confs)}'
                    f'{self.t("), processing first ")}{n}{self.t(" items")}'
                )
            rows_cache: dict[str, int] = {}
            split_bounds_override: list[tuple[int, int]] = []
            try:
                first_conf = confs[0] if confs else {}
                mpls_key0 = str((first_conf or {}).get('selected_mpls') or '').strip()
                mpls_path0 = mpls_key0 if mpls_key0.lower().endswith('.mpls') else (
                    mpls_key0 + '.mpls' if mpls_key0 else '')
                cmd0 = str((first_conf or {}).get('main_remux_cmd') or '').strip()
                lines_chk = _svc_cls()._remux_cmd_shell_lines(cmd0)
                used_multiline_bounds = False
                if len(lines_chk) > 1:
                    mb = _svc_cls()._chapter_split_bounds_from_multi_line_remux_cmd(cmd0, confs)
                    if mb:
                        split_bounds_override = mb
                        used_multiline_bounds = True
                        print(
                            f'{self.t("[chapter-debug] ")}{self.t("multi-line remux_cmd chapter bounds (applied): ")}{len(mb)}'
                        )
                if not used_multiline_bounds:
                    stem0 = ''
                    if mpls_path0:
                        stem0 = os.path.splitext(os.path.basename(mpls_path0.replace('\\', '/')))[0]
                    has_split = any('--split' in ln.lower() for ln in lines_chk) if lines_chk else (
                        '--split' in cmd0.lower())
                    windows = _svc_cls()._split_parts_windows_from_mkvmerge_cmd(cmd0, mpls_stem=stem0 or None)
                    if not windows:
                        for ln in lines_chk:
                            cuts_ln = _svc_cls()._split_chapters_ints_from_mkvmerge_one_line(ln)
                            if not cuts_ln:
                                continue
                            stem_ln = _svc_cls()._mkvmerge_line_source_mpls_stem(ln)
                            mpath_use = ''
                            for c in confs:
                                raw_m = str(c.get('selected_mpls') or '').strip()
                                sc = os.path.splitext(os.path.basename(raw_m.replace('\\', '/')))[0]
                                if stem_ln and sc and stem_ln.lower() != sc.lower():
                                    continue
                                cand = raw_m if raw_m.lower().endswith('.mpls') else (raw_m + '.mpls' if raw_m else '')
                                if cand and os.path.isfile(cand):
                                    mpath_use = cand
                                    break
                            if not mpath_use and mpls_path0 and os.path.isfile(mpls_path0):
                                mpath_use = mpls_path0
                            if mpath_use:
                                windows = _svc_cls()._time_windows_from_split_chapter_numbers(mpath_use, cuts_ln)
                                if windows:
                                    break
                    if (not windows) and ('{parts_split}' in cmd0) and mpls_path0 and os.path.isfile(mpls_path0):
                        ch_tmp = Chapter(mpls_path0)
                        segs_tmp = _svc_cls()._series_episode_segments_bounds(ch_tmp, confs)
                        _i2m_tmp, i2o_tmp = get_index_to_m2ts_and_offset(ch_tmp)
                        rows_tmp = sum(map(len, ch_tmp.mark_info.values()))
                        total_end_tmp = rows_tmp + 1

                        def _off_tmp(idx: int) -> float:
                            if idx >= total_end_tmp:
                                return ch_tmp.get_total_time()
                            return float(i2o_tmp.get(idx, 0.0))

                        windows = [(float(_off_tmp(s0)), float(_off_tmp(e0))) for s0, e0 in segs_tmp]
                    if (not windows) and has_split and mpls_path0 and os.path.isfile(mpls_path0) and confs:
                        windows = _svc_cls()._episode_float_windows_from_config_bounds(mpls_path0, confs)
                        if windows:
                            print(
                                f'{self.t("[chapter-debug] ")}{self.t("derived split timeline from table2 chapter bounds: ")}{len(windows)}'
                            )
                    if windows and mpls_path0 and os.path.isfile(mpls_path0):
                        split_bounds_override = _svc_cls()._chapter_bounds_from_split_windows(mpls_path0, windows)
            except Exception:
                split_bounds_override = []
            skip_chapter_norm: set[str] = set()
            try:
                skip_chapter_norm = set(getattr(self, '_remux_chapter_skip_paths', None) or set())
            except Exception:
                skip_chapter_norm = set()
            for i in range(n):
                if cancel_event and cancel_event.is_set():
                    raise TaskCancelled()
                conf = confs[i]
                mkv_path = paths[i]
                try:
                    if skip_chapter_norm and os.path.normcase(os.path.normpath(mkv_path)) in skip_chapter_norm:
                        print(
                            f'{self.t("[chapter-debug] ")}{self.t("skip chapters (remux failed or split-check for this output): ")}{mkv_path}'
                        )
                        done += 1
                        self._progress(int(done / max(total_mkv, 1) * 1000))
                        continue
                except Exception:
                    pass
                mpls_key = str(conf.get('selected_mpls') or '').strip()
                if not mpls_key:
                    continue
                mpls_path = mpls_key if mpls_key.lower().endswith('.mpls') else mpls_key + '.mpls'
                if mpls_key not in rows_cache:
                    ch = Chapter(mpls_path)
                    rows_cache[mpls_key] = sum(map(len, ch.mark_info.values()))
                rows = rows_cache[mpls_key]
                total_end = rows + 1
                if i < len(split_bounds_override):
                    s, e = split_bounds_override[i]
                else:
                    s = int(conf.get('start_at_chapter') or conf.get('chapter_index') or 1)
                    if conf.get('end_at_chapter'):
                        e = int(conf.get('end_at_chapter') or total_end)
                    elif i + 1 < len(confs):
                        e = int(confs[i + 1].get('start_at_chapter') or confs[i + 1].get('chapter_index') or total_end)
                    else:
                        e = total_end
                s = max(1, min(s, total_end))
                e = max(s + 1, min(e, total_end))
                self._write_remux_segment_chapter_txt(mpls_path, s, e, chapter_txt)
                MKV(mkv_path).add_chapter(self.checked)
                done += 1
                self._progress(int(done / max(total_mkv, 1) * 1000))
        self._progress(1000)

    @staticmethod
    def _parse_timecode_to_sec(raw: str) -> Optional[float]:
        normalized_timecode = str(raw or '').strip()
        if not normalized_timecode:
            return None
        match = re.match(r'^(\d+):([0-5]?\d):([0-5]?\d(?:\.\d+)?)$', normalized_timecode)
        if not match:
            return None
        return int(match.group(1)) * 3600.0 + int(match.group(2)) * 60.0 + float(match.group(3))

    @staticmethod
    def _split_parts_windows_from_mkvmerge_one_line(line: str) -> list[tuple[float, float]]:
        command_line = (line or '').strip()
        if not command_line:
            return []
        split_match = re.search(r'--split\s+("([^"]+)"|\'([^\']+)\'|(\S+))', command_line)
        if not split_match:
            return []
        split_specification = (split_match.group(2) or split_match.group(3) or split_match.group(4) or '').strip()
        if not split_specification.lower().startswith('parts:'):
            return []
        payload = split_specification[6:].strip()
        if not payload or '{' in payload or '}' in payload:
            return []
        windows: list[tuple[float, float]] = []
        for segment in [item.strip() for item in payload.split(',') if item.strip()]:
            if '-' not in segment:
                continue
            start_text, end_text = segment.split('-', 1)
            start_seconds = _svc_cls()._parse_timecode_to_sec(start_text)
            end_seconds = _svc_cls()._parse_timecode_to_sec(end_text)
            if start_seconds is None or end_seconds is None or end_seconds <= start_seconds + 1e-6:
                continue
            windows.append((start_seconds, end_seconds))
        return windows

    @staticmethod
    def _split_parts_windows_from_mkvmerge_cmd(cmd: str, *, mpls_stem: Optional[str] = None) -> list[tuple[float, float]]:
        """Parse ``--split parts:`` time windows; newline-split ``remux_cmd``, optional ``mpls_stem`` filters lines."""
        lines = _svc_cls()._remux_cmd_shell_lines(cmd)
        if not lines:
            return []
        filt = (mpls_stem or '').strip()
        if len(lines) == 1:
            return _svc_cls()._split_parts_windows_from_mkvmerge_one_line(lines[0])
        acc: list[tuple[float, float]] = []
        for ln in lines:
            if filt:
                st = _svc_cls()._mkvmerge_line_source_mpls_stem(ln)
                if st.lower() != filt.lower():
                    continue
            acc.extend(_svc_cls()._split_parts_windows_from_mkvmerge_one_line(ln))
        if acc:
            return acc
        if filt:
            for ln in lines:
                w = _svc_cls()._split_parts_windows_from_mkvmerge_one_line(ln)
                if w:
                    return w
        return []

    @staticmethod
    def _mkvmerge_line_source_mpls_stem(line: str) -> str:
        """Playlist stem (e.g. ``00001``) from the last ``.mpls`` path token on one mkvmerge command line."""
        line = (line or '').strip()
        if not line:
            return ''
        named = re.findall(r'["\']([^"\']+\.(?:mpls|MPLS))["\']', line)
        if named:
            return os.path.splitext(os.path.basename(named[-1]))[0]
        bare = re.findall(r'(?:^|\s)((?:[A-Za-z]:)?[^\s"\']+\.(?:mpls|MPLS))(?=\s|$)', line, re.I)
        if bare:
            return os.path.splitext(os.path.basename(bare[-1]))[0]
        return ''

    @staticmethod
    def _chapter_split_bounds_from_multi_line_remux_cmd(
            cmd0: str, confs: list[dict[str, object]],
    ) -> list[tuple[int, int]]:
        """
        When ``main_remux_cmd`` has multiple lines (separate mkvmerge invocations), map each line's
        ``--split parts:`` windows to episode rows in order: match playlist stem on the line to
        ``selected_mpls``, then convert time windows to chapter bounds on that playlist.
        """
        lines = _svc_cls()._remux_cmd_shell_lines(cmd0)
        if len(lines) <= 1:
            return []
        bounds_out: list[tuple[int, int]] = []
        ci = 0
        for ln in lines:
            wins = _svc_cls()._split_parts_windows_from_mkvmerge_one_line(ln)
            stem_ln = _svc_cls()._mkvmerge_line_source_mpls_stem(ln)
            if not wins and '--split' in ln.lower():
                cuts_ln = _svc_cls()._split_chapters_ints_from_mkvmerge_one_line(ln)
                sub_confs: list[dict[str, object]] = []
                for c in confs:
                    raw_m = str(c.get('selected_mpls') or '').strip()
                    sc = os.path.splitext(os.path.basename(raw_m.replace('\\', '/')))[0]
                    if stem_ln and sc and stem_ln.lower() != sc.lower():
                        continue
                    sub_confs.append(c)
                if stem_ln and not sub_confs:
                    continue
                if not sub_confs:
                    sub_confs = list(confs)
                sub_confs.sort(key=lambda c: int(c.get('chapter_index') or c.get('start_at_chapter') or 0))
                mpath = ''
                for c in sub_confs:
                    kk = str(c.get('selected_mpls') or '').strip()
                    cand = kk if kk.lower().endswith('.mpls') else (kk + '.mpls' if kk else '')
                    if cand and os.path.isfile(cand):
                        mpath = cand
                        break
                if cuts_ln and mpath:
                    wins = _svc_cls()._time_windows_from_split_chapter_numbers(mpath, cuts_ln)
                if not wins and mpath and sub_confs:
                    wins = _svc_cls()._episode_float_windows_from_config_bounds(mpath, sub_confs)
            if not wins:
                continue
            for w0, w1 in wins:
                placed = False
                j = ci
                while j < len(confs):
                    conf = confs[j]
                    raw_m = str(conf.get('selected_mpls') or '').strip()
                    stem_c = os.path.splitext(os.path.basename(raw_m.replace('\\', '/')))[0]
                    if stem_ln and stem_c and stem_ln.lower() != stem_c.lower():
                        j += 1
                        continue
                    mpls_key = raw_m
                    mpls_path = mpls_key if mpls_key.lower().endswith('.mpls') else (mpls_key + '.mpls' if mpls_key else '')
                    if not mpls_path or not os.path.isfile(mpls_path):
                        j += 1
                        continue
                    bb = _svc_cls()._chapter_bounds_from_split_windows(mpls_path, [(w0, w1)])
                    if bb:
                        bounds_out.append(bb[0])
                    ci = j + 1
                    placed = True
                    break
                if not placed:
                    break
        return bounds_out

    @staticmethod
    def _chapter_bounds_from_split_windows(
            mpls_path: str,
            windows: list[tuple[float, float]],
    ) -> list[tuple[int, int]]:
        """Convert timeline windows to the half-open chapter bounds used by episode configuration.

        MPLS chapter marks are monotonic. ``bisect_left`` selects the first mark at or after each split edge,
        allowing a 1 ms tolerance for mkvmerge time formatting. A window that falls between the same pair of
        marks still retains one chapter instead of producing an empty segment.
        """
        if not mpls_path or not windows:
            return []
        chapter = Chapter(mpls_path)
        _, index_to_offset = get_index_to_m2ts_and_offset(chapter)
        chapter_count = sum(map(len, chapter.mark_info.values()))
        exclusive_playlist_end = chapter_count + 1
        offsets = [float(index_to_offset.get(index, 0.0)) for index in range(1, chapter_count + 1)]
        tolerance_seconds = 1e-3

        bounds: list[tuple[int, int]] = []
        for window_start, window_end in windows:
            start_chapter = bisect_left(offsets, float(window_start) - tolerance_seconds) + 1
            end_chapter = bisect_left(offsets, float(window_end) - tolerance_seconds) + 1
            if end_chapter <= start_chapter:
                end_chapter = min(exclusive_playlist_end, start_chapter + 1)
            bounds.append((start_chapter, end_chapter))
        return bounds

    def add_chapters_to_mkv(
            self,
            mkv_targets: list[tuple[str, str]],
            selected_mpls: list[str],
            edit_original: bool,
            cancel_event: Optional[threading.Event] = None,
    ) -> None:
        """Match ordered MKVs to ordered playlists and apply the resulting chapter documents."""
        if not mkv_targets:
            raise ValueError(translate_text('MKV file is not selected'))
        if not selected_mpls:
            raise ValueError(translate_text('Main MPLS is not selected'))

        for _, output_path in mkv_targets:
            if not edit_original and os.path.exists(output_path):
                raise FileExistsError(
                    translate_text('Output file already exists: {path}').format(path=output_path)
                )

        durations = []
        for target_index, (mkv_path, _) in enumerate(mkv_targets):
            if cancel_event and cancel_event.is_set():
                raise TaskCancelled()
            durations.append(MKV(mkv_path).get_duration())
            self._progress(int((target_index + 1) / len(mkv_targets) * 250), 'Preparing')

        # Each matching chapter mark closes the current MKV. The remaining marks at
        # the end of one playlist belong to that playlist's final unmatched MKV.
        chapter_documents: list[tuple[str, str, str]] = []
        target_index = 0
        for selected_mpls_no_ext in selected_mpls:
            if target_index >= len(mkv_targets):
                break
            if cancel_event and cancel_event.is_set():
                raise TaskCancelled()
            mpls_path = selected_mpls_no_ext
            if not mpls_path.lower().endswith('.mpls'):
                mpls_path += '.mpls'
            chapter = Chapter(mpls_path)
            current_duration = durations[target_index]
            play_item_duration = 0.0
            completed_episode_duration = 0.0
            chapter_number = 0
            chapter_lines: list[str] = []

            for play_item_id, (_, in_time, out_time) in enumerate(chapter.in_out_time):
                if target_index >= len(mkv_targets):
                    break
                if cancel_event and cancel_event.is_set():
                    raise TaskCancelled()
                for mark_timestamp in chapter.mark_info.get(play_item_id) or []:
                    if cancel_event and cancel_event.is_set():
                        raise TaskCancelled()
                    relative_time = play_item_duration + (
                        mark_timestamp - in_time
                    ) / 45000 - completed_episode_duration
                    if abs(relative_time - current_duration) < 0.1:
                        source_path, output_path = mkv_targets[target_index]
                        chapter_documents.append(
                            (source_path, output_path, '\n'.join(chapter_lines))
                        )
                        completed_episode_duration += relative_time
                        target_index += 1
                        if target_index >= len(mkv_targets):
                            break
                        current_duration = durations[target_index]
                        chapter_number = 0
                        chapter_lines = []
                        relative_time = 0.0

                    chapter_number += 1
                    append_ogm_chapter_lines(
                        chapter_lines,
                        chapter_number,
                        max(0.0, float(relative_time)),
                    )
                play_item_duration += (out_time - in_time) / 45000

            if target_index < len(mkv_targets):
                source_path, output_path = mkv_targets[target_index]
                chapter_documents.append((source_path, output_path, '\n'.join(chapter_lines)))
                target_index += 1

        if target_index < len(mkv_targets):
            unmatched_path = mkv_targets[target_index][0]
            raise ValueError(
                translate_text(
                    'Could not map all MKV files to the selected main playlists: {path}'
                ).format(path=unmatched_path)
            )

        with tempfile.TemporaryDirectory(prefix='bluray-subtitle-chapters-') as temporary_directory:
            total = len(chapter_documents)
            for document_index, (source_path, output_path, chapter_text) in enumerate(
                    chapter_documents, start=1):
                if cancel_event and cancel_event.is_set():
                    raise TaskCancelled()
                chapter_path = os.path.join(
                    temporary_directory, f'chapter-{document_index:04d}.txt'
                )
                with open(chapter_path, 'w', encoding='utf-8-sig') as chapter_file:
                    chapter_file.write(chapter_text)
                MKV(source_path).add_chapter(
                    edit_original,
                    chapter_path,
                    None if edit_original else output_path,
                )
                self._progress(250 + int(document_index / total * 750), 'Writing Chapters')
        self._progress(1000, 'Done')

    def _add_chapter_to_mkv_by_duration(
            self,
            mkv_files: list[str],
            table: Optional[QTableWidget] = None,
            selected_mpls: Optional[list[tuple[str, str]]] = None,
            cancel_event: Optional[threading.Event] = None,
    ) -> None:
        mkv_index = 0

        def _vol_from_name(p: str) -> Optional[int]:
            m = re.search(r'BD_Vol_(\d{3})', os.path.basename(p or ''))
            if not m:
                return None
            try:
                return int(m.group(1))
            except Exception:
                return None

        mkv_files = sorted(mkv_files, key=self._mkv_sort_key)
        current_target_vol = _vol_from_name(mkv_files[0]) if mkv_files else None
        if selected_mpls is not None:
            iterator = ((folder, Chapter(selected_mpls_no_ext + '.mpls'), selected_mpls_no_ext)
                        for folder, selected_mpls_no_ext in selected_mpls)
        else:
            if table is None:
                return
            iterator = self.select_mpls_from_table(table)

        for folder, chapter, selected_mpls in iterator:
            if cancel_event and cancel_event.is_set():
                raise TaskCancelled()
            while mkv_index < len(mkv_files):
                v = _vol_from_name(mkv_files[mkv_index])
                if current_target_vol is None or v is None or v == current_target_vol:
                    break
                mkv_index += 1
            if mkv_index >= len(mkv_files):
                break
            duration = MKV(mkv_files[mkv_index]).get_duration()
            print(f'{self.t("folder: ")}{folder}')
            print(f'{self.t("in_out_time: ")}{chapter.in_out_time}')
            print(f'{self.t("mark_info: ")}{chapter.mark_info}')
            print(f'{self.t("Episode: ")}{mkv_index + 1}, {self.t("Duration: ")}{duration}')

            play_item_duration_time_sum = 0
            episode_duration_time_sum = 0
            chapter_id = 0
            chapter_text = []
            volume_done = False
            for ref_to_play_item_id in range(len(chapter.in_out_time)):
                mark_timestamps = chapter.mark_info.get(ref_to_play_item_id) or []
                if volume_done:
                    break
                if cancel_event and cancel_event.is_set():
                    raise TaskCancelled()
                _, in_time, out_time = chapter.in_out_time[ref_to_play_item_id]
                for mark_timestamp in mark_timestamps:
                    if cancel_event and cancel_event.is_set():
                        raise TaskCancelled()
                    real_time = play_item_duration_time_sum + (
                            mark_timestamp - in_time) / 45000 - episode_duration_time_sum
                    if abs(real_time - duration) < 0.1:
                        with open(f'chapter.txt', 'w', encoding='utf-8-sig') as f:
                            f.write('\n'.join(chapter_text))
                        chapter_id = 0
                        episode_duration_time_sum += real_time
                        real_time = 0
                        mkv = MKV(mkv_files[mkv_index])
                        mkv.add_chapter(self.checked)
                        self._progress(int((mkv_index + 1) / len(mkv_files) * 1000))
                        mkv_index += 1
                        if mkv_index >= len(mkv_files):
                            volume_done = True
                            break
                        next_vol = _vol_from_name(mkv_files[mkv_index])
                        if current_target_vol is not None and next_vol is not None and next_vol != current_target_vol:
                            volume_done = True
                            break
                        duration = MKV(mkv_files[mkv_index]).get_duration()
                        print(f'{self.t("Episode: ")}{mkv_index + 1}, {self.t("Duration: ")}{duration}')
                        chapter_text.clear()

                    chapter_id += 1
                    append_ogm_chapter_lines(chapter_text, chapter_id, max(0.0, float(real_time)))
                play_item_duration_time_sum += (out_time - in_time) / 45000

            with open(f'chapter.txt', 'w', encoding='utf-8-sig') as f:
                f.write('\n'.join(chapter_text))
            if mkv_index < len(mkv_files):
                this_vol = _vol_from_name(mkv_files[mkv_index])
                if current_target_vol is None or this_vol is None or this_vol == current_target_vol:
                    mkv = MKV(mkv_files[mkv_index])
                    mkv.add_chapter(self.checked)
                    self._progress(int((mkv_index + 1) / len(mkv_files) * 1000))
                    mkv_index += 1
            current_target_vol = None
            if mkv_index < len(mkv_files):
                current_target_vol = _vol_from_name(mkv_files[mkv_index])

        self._progress(1000)

    def add_chapter_to_mkv(
            self,
            mkv_files,
            table: Optional[QTableWidget] = None,
            selected_mpls: Optional[list[tuple[str, str]]] = None,
            cancel_event: Optional[threading.Event] = None,
            configuration: Optional[dict[int, dict[str, int | str]]] = None,
    ):
        """Apply chapters to each episode MKV from configuration (remux / encode).

        For an episode with ``start_at_chapter=11`` and ``end_at_chapter=17``, writes six
        entries ``Chapter 01``..``Chapter 06`` at times 0 and ``offset(j)-offset(11)`` for
        MPLS marks ``j`` = 11..16 (new ordinal = ``j - 10`` in that example).
        """
        cfg = configuration if configuration is not None else self.configuration
        if cfg:
            self._add_chapter_to_mkv_from_configuration(mkv_files, cfg, cancel_event=cancel_event)
        else:
            self._add_chapter_to_mkv_by_duration(mkv_files, table, selected_mpls, cancel_event=cancel_event)

    def completion(self):  # complete Blu-ray folder; remove temporary files
        """Finalize folder layout after processing and clean temporary artifacts."""
        if self.checked:
            for folder in self.bluray_folders:
                bdmv = os.path.join(folder, 'BDMV')
                backup = os.path.join(bdmv, 'BACKUP')
                if os.path.exists(backup):
                    for item in os.listdir(backup):
                        if not os.path.exists(os.path.join(bdmv, item)):
                            if os.path.isdir(os.path.join(backup, item)):
                                shutil.copytree(os.path.join(backup, item), os.path.join(bdmv, item))
                            else:
                                shutil.copy(os.path.join(backup, item), os.path.join(bdmv, item))
                for item in 'AUXDATA', 'BDJO', 'JAR', 'META':
                    if not os.path.exists(os.path.join(bdmv, item)):
                        os.mkdir(os.path.join(bdmv, item))
        for tmp_folder in self.tmp_folders:
            try:
                force_remove_folder(tmp_folder)
            except:
                pass
        if os.path.exists('chapter.txt'):
            try:
                force_remove_file('chapter.txt')
            except:
                pass
        if os.path.exists('mkvinfo.txt'):
            try:
                force_remove_file('mkvinfo.txt')
            except:
                pass
        if os.path.exists('info.json'):
            try:
                force_remove_file('info.json')
            except:
                pass
        if os.path.exists('.meta'):
            try:
                force_remove_file('.meta')
            except:
                pass
        print_terminal_line('[BluraySubtitle] completion(): cleanup finished.')

    def _compute_mkv_id_to_m2ts_pid_core(
            self,
            mpls_path: str,
            track_configuration: dict[str, object],
    ) -> dict[int, int]:
        """Map planned Matroska track IDs to transport-stream PIDs on the reference clip.

        GUI track indices identify streams on the first MPLS play item. Output track IDs follow the exact
        mkvmerge layout: selected video tracks (or the first video when none are configured), then selected
        audio tracks, then selected subtitle tracks. A missing source index does not consume an output ID
        because mkvmerge cannot create that track.
        """
        selected_audio_indices = [str(index) for index in (track_configuration.get('audio') or [])]
        selected_subtitle_indices = [str(index) for index in (track_configuration.get('subtitle') or [])]
        configured_video = track_configuration.get('video')
        selected_video_indices = [str(index) for index in configured_video] if isinstance(configured_video, list) else []
        try:
            chapter = Chapter(mpls_path)
            index_to_m2ts, _ = get_index_to_m2ts_and_offset(chapter)
            if not index_to_m2ts:
                return {}
            first_play_item_index = min(index_to_m2ts)
            stream_folder = os.path.normpath(os.path.join(os.path.dirname(os.path.dirname(mpls_path)), 'STREAM'))
            reference_m2ts = os.path.join(stream_folder, index_to_m2ts[first_play_item_index])
        except Exception:
            return {}
        if not os.path.isfile(reference_m2ts):
            return {}

        reference_streams = _svc_cls()._m2ts_track_streams(reference_m2ts)
        pid_by_stream_index: dict[str, int] = {}
        for stream in reference_streams:
            if not isinstance(stream, dict):
                continue
            stream_index = str(stream.get('index') or '').strip()
            if not stream_index:
                continue
            transport_pid = _svc_cls()._stream_service_id(stream)
            track_type = str(stream.get('codec_type') or '').strip().lower()
            if transport_pid is None or track_type not in ('audio', 'subtitle', 'subtitles', 'video'):
                continue
            pid_by_stream_index[stream_index] = int(transport_pid)

        track_id_to_pid: dict[int, int] = {}
        next_track_id = 0
        if selected_video_indices:
            for stream_index in selected_video_indices:
                transport_pid = pid_by_stream_index.get(stream_index.strip())
                if transport_pid is not None:
                    track_id_to_pid[next_track_id] = transport_pid
                    next_track_id += 1
        else:
            for stream in reference_streams:
                if not isinstance(stream, dict) or str(stream.get('codec_type') or '').strip().lower() != 'video':
                    continue
                transport_pid = _svc_cls()._stream_service_id(stream)
                if transport_pid is not None:
                    track_id_to_pid[next_track_id] = int(transport_pid)
                    next_track_id += 1
                    break
        for selected_indices in (selected_audio_indices, selected_subtitle_indices):
            for stream_index in selected_indices:
                transport_pid = pid_by_stream_index.get(stream_index.strip())
                if transport_pid is not None:
                    track_id_to_pid[next_track_id] = transport_pid
                    next_track_id += 1
        return track_id_to_pid

    def _compute_mkv_id_to_m2ts_pid_for_main_mpls(self, mpls_path: str) -> dict[int, int]:
        """Map episode-main Matroska track IDs to reference M2TS PIDs using captured GUI selection."""
        normalized_mpls_path = os.path.normpath(str(mpls_path or '').strip())
        if not normalized_mpls_path.lower().endswith('.mpls'):
            normalized_mpls_path += '.mpls'
        track_configurations = getattr(self, 'track_selection_config', {}) or {}
        if not isinstance(track_configurations, dict):
            track_configurations = {}
        track_configuration = track_configurations.get(media_track_key('main', normalized_mpls_path)) or {}
        return self._compute_mkv_id_to_m2ts_pid_core(normalized_mpls_path, track_configuration)

    @staticmethod
    def _mkvmerge_ident_transport_pid(properties: object) -> Optional[int]:
        """Read an MPEG-TS PID from identify JSON without mistaking a Matroska track ordinal for a PID."""
        if not isinstance(properties, dict):
            return None
        for key in ('stream_id', 'original_transport_stream_id'):
            transport_pid = _svc_cls()._int_from_mkvmerge_prop(properties.get(key))
            if transport_pid is not None and 1 <= int(transport_pid) <= 0x1FFF:
                return int(transport_pid)
        return None

    @staticmethod
    def _merged_mkv_id_to_m2ts_pid_episode_sp(
            main_track_id_to_pid: dict[int, int],
            selected_sp_pids: list[int],
    ) -> dict[int, int]:
        """Describe the EP+SP output layout: main tracks first, then new SP PIDs in selected order."""
        main_pids = set(main_track_id_to_pid.values())
        merged_track_id_to_pid = {
            output_track_id: main_track_id_to_pid[output_track_id]
            for output_track_id in sorted(main_track_id_to_pid)
        }
        next_track_id = len(merged_track_id_to_pid)
        for transport_pid in selected_sp_pids:
            if transport_pid in main_pids:
                continue
            merged_track_id_to_pid[next_track_id] = int(transport_pid)
            next_track_id += 1
        return merged_track_id_to_pid

    def _mux_episode_linked_sp_mkvmerge(
            self,
            *,
            episode_mkv: str,
            sp_mpls_path: str,
            episode_main_mpls: str,
            selected_sp_audio_track_ids: list[str],
            selected_sp_subtitle_track_ids: list[str],
            language_by_sp_track_id: dict[str, str],
            cancel_event: Optional[threading.Event],
    ) -> bool:
        """Attach selected SP tracks while preserving transport-PID identity across repeated SP merges.

        mkvmerge track IDs (TIDs) are local to each input and cannot be compared directly. The main MPLS first
        maps the existing episode MKV track IDs to MPEG transport PIDs; the SP MPLS identify result independently
        maps SP track IDs to PIDs. Their unique PID union is sorted, then each PID becomes either ``0:track_id``
        for the existing episode or ``1:track_id`` for the SP input. An SP PID already present in the episode is
        not appended again. The resulting output track-ID-to-PID map is cached because a later SP merge identifies
        the already extended episode rather than the original main-only layout.
        """
        normalized_main_mpls = os.path.normpath(episode_main_mpls)
        try:
            main_chapter = Chapter(episode_main_mpls)
            main_play_items, _ = get_index_to_m2ts_and_offset(main_chapter)
            if not main_play_items:
                return False
            first_play_item_index = min(main_play_items)
            playlist_folder = os.path.dirname(episode_main_mpls)
            stream_folder = os.path.normpath(os.path.join(os.path.dirname(playlist_folder), 'STREAM'))
            reference_m2ts = os.path.join(stream_folder, main_play_items[first_play_item_index])
        except Exception:
            return False
        if not os.path.isfile(reference_m2ts):
            return False

        episode_identification = _svc_cls()._mkvmerge_identify_json(episode_mkv)
        episode_track_type_by_id: dict[int, str] = {}
        muxable_track_count = 0
        for track in episode_identification.get('tracks') or []:
            if not isinstance(track, dict):
                continue
            track_type = str(track.get('type') or '').strip().lower()
            track_type = 'subtitles' if track_type == 'subtitle' else track_type
            if track_type not in ('video', 'audio', 'subtitles'):
                continue
            muxable_track_count += 1
            try:
                episode_track_type_by_id[int(track.get('id'))] = track_type
            except Exception:
                continue

        cache_key = os.path.normcase(os.path.normpath(os.path.abspath(episode_mkv)))
        sp_mux_cache = getattr(self, '_episode_sp_mux_last_after_mux_map', None)
        if not isinstance(sp_mux_cache, dict):
            sp_mux_cache = {}
            self._episode_sp_mux_last_after_mux_map = sp_mux_cache
        previous_track_id_to_pid = sp_mux_cache.get(cache_key)
        cached_episode_baseline: Optional[dict[int, int]] = None
        if previous_track_id_to_pid and muxable_track_count == len(previous_track_id_to_pid):
            cached_episode_baseline = dict(previous_track_id_to_pid)

        sp_identification = _svc_cls()._mkvmerge_identify_json(sp_mpls_path)
        sp_track_id_to_pid: dict[int, int] = {}
        sp_track_type_by_id: dict[int, str] = {}
        for track in sp_identification.get('tracks') or []:
            if not isinstance(track, dict):
                continue
            try:
                track_id = int(track.get('id'))
            except Exception:
                continue
            track_type = str(track.get('type') or '').strip().lower()
            properties = track.get('properties') or {}
            if not isinstance(properties, dict):
                properties = {}
            transport_pid = SubtitleChapterPipelineMixin._mkvmerge_ident_transport_pid(properties)
            if transport_pid is None or track_type not in ('audio', 'subtitles', 'video'):
                continue
            sp_track_id_to_pid[track_id] = int(transport_pid)
            sp_track_type_by_id[track_id] = track_type

        selected_sp_pids: list[int] = []
        for track_id_text in selected_sp_audio_track_ids + selected_sp_subtitle_track_ids:
            try:
                track_id = int(str(track_id_text).strip())
            except Exception:
                track_id = -1
            transport_pid = sp_track_id_to_pid.get(track_id)
            if transport_pid is None:
                raise RuntimeError(
                    translate_text('Selected SP track has no transport PID: {track} ({path})').format(
                        track=track_id_text,
                        path=sp_mpls_path,
                    )
                )
            selected_sp_pids.append(transport_pid)

        main_track_id_to_pid = (
            dict(cached_episode_baseline)
            if cached_episode_baseline is not None
            else self._compute_mkv_id_to_m2ts_pid_for_main_mpls(normalized_main_mpls)
        )
        if not main_track_id_to_pid:
            return False
        episode_pid_to_track_id = {
            main_track_id_to_pid[track_id]: track_id
            for track_id in sorted(main_track_id_to_pid)
        }
        sp_pid_to_track_id: dict[int, int] = {}
        for track_id in sorted(sp_track_id_to_pid):
            sp_pid_to_track_id.setdefault(sp_track_id_to_pid[track_id], track_id)

        ordered_pids = sorted(set(main_track_id_to_pid.values()) | set(selected_sp_pids))
        track_order_parts: list[str] = []
        episode_audio_track_ids: list[str] = []
        episode_subtitle_track_ids: list[str] = []
        sp_audio_track_ids: list[str] = []
        sp_subtitle_track_ids: list[str] = []
        for transport_pid in ordered_pids:
            if transport_pid in episode_pid_to_track_id:
                track_id = episode_pid_to_track_id[transport_pid]
                track_order_parts.append(f'0:{track_id}')
                track_type = episode_track_type_by_id.get(track_id, '')
                if track_type == 'audio':
                    episode_audio_track_ids.append(str(track_id))
                elif track_type in ('subtitles', 'subtitle'):
                    episode_subtitle_track_ids.append(str(track_id))
                continue
            track_id = sp_pid_to_track_id.get(transport_pid)
            if track_id is None:
                return False
            track_order_parts.append(f'1:{track_id}')
            track_type = sp_track_type_by_id.get(track_id, '')
            if track_type == 'audio':
                sp_audio_track_ids.append(str(track_id))
            elif track_type in ('subtitles', 'subtitle'):
                sp_subtitle_track_ids.append(str(track_id))
        if not track_order_parts:
            return False
        track_order_argument = ','.join(track_order_parts)
        output_stem, output_extension = os.path.splitext(episode_mkv)
        temporary_output = f'{output_stem}.tmp{output_extension}'
        try:
            if os.path.isfile(temporary_output):
                force_remove_file(temporary_output)
        except Exception:
            pass

        mkvmerge_executable = MKV_MERGE_PATH or 'mkvmerge'
        ui_language_argument = mkvtoolnix_ui_language_arg().strip()
        command_parts: list[str] = [mkvmerge_executable]
        if ui_language_argument:
            command_parts.extend(ui_language_argument.split())
        command_parts.extend(['-o', temporary_output])
        if episode_audio_track_ids:
            command_parts.extend(['-a', ','.join(episode_audio_track_ids)])
        else:
            command_parts.append('-A')
        if episode_subtitle_track_ids:
            command_parts.extend(['-s', ','.join(episode_subtitle_track_ids)])
        else:
            command_parts.append('-S')
        command_parts.append(episode_mkv)
        sp_video_tracks = [
            str(track_id)
            for track_id, track_type in sp_track_type_by_id.items()
            if track_type == 'video' and f'1:{track_id}' in track_order_parts
        ]
        if sp_video_tracks:
            command_parts.extend(['-d', ','.join(sp_video_tracks)])
        else:
            command_parts.append('-D')
        if sp_audio_track_ids:
            command_parts.extend(['-a', ','.join(sp_audio_track_ids)])
        else:
            command_parts.append('-A')
        if sp_subtitle_track_ids:
            command_parts.extend(['-s', ','.join(sp_subtitle_track_ids)])
        else:
            command_parts.append('-S')
        for track_id, language in language_by_sp_track_id.items():
            command_parts.extend(['--language', f'{track_id}:{language}'])
        command_parts.append(sp_mpls_path)
        command_parts.extend(['--track-order', track_order_argument])
        print(f'[episode-sp-mux] mkvmerge: {subprocess.list2cmdline(command_parts)}')

        chapter_backup = ''
        chapters_saved = False
        try:
            file_descriptor, chapter_backup = tempfile.mkstemp(suffix='.xml', prefix='ep_sp_chapters_')
            os.close(file_descriptor)
            mkvextract_executable = MKV_EXTRACT_PATH or 'mkvextract'
            extraction_ui_argument = mkvtoolnix_ui_language_arg().strip()
            extraction_command = [mkvextract_executable]
            if extraction_ui_argument:
                extraction_command.extend(extraction_ui_argument.split())
            extraction_command.extend([episode_mkv, 'chapters', '--simple', chapter_backup])
            if run_command(extraction_command).returncode == 0:
                if os.path.isfile(chapter_backup) and os.path.getsize(chapter_backup) > 0:
                    chapters_saved = True
            if not chapters_saved:
                try:
                    force_remove_file(chapter_backup)
                except Exception:
                    pass
                chapter_backup = ''
        except Exception:
            chapter_backup = ''
            chapters_saved = False

        if cancel_event and cancel_event.is_set():
            if chapter_backup:
                try:
                    force_remove_file(chapter_backup)
                except Exception:
                    pass
            raise TaskCancelled()
        return_code = run_command(command_parts).returncode
        if return_code not in (0, 1) or not os.path.isfile(temporary_output):
            if os.path.isfile(temporary_output):
                force_remove_file(temporary_output)
            if chapter_backup and os.path.isfile(chapter_backup):
                force_remove_file(chapter_backup)
            return False

        merged_track_id_to_pid = self._merged_mkv_id_to_m2ts_pid_episode_sp(main_track_id_to_pid, selected_sp_pids)
        try:
            if chapters_saved and chapter_backup and os.path.isfile(chapter_backup):
                propedit_command = [MKV_PROP_EDIT_PATH or 'mkvpropedit']
                propedit_ui_argument = mkvtoolnix_ui_language_arg().strip()
                if propedit_ui_argument:
                    propedit_command.extend(propedit_ui_argument.split())
                propedit_command.extend([temporary_output, '--chapters', chapter_backup])
                if run_command(propedit_command).returncode not in (0, 1):
                    return False

            main_pids = set(main_track_id_to_pid.values())
            desired_language_by_pid = {
                sp_track_id_to_pid[int(track_id)]: language
                for track_id, language in language_by_sp_track_id.items()
                if int(track_id) in sp_track_id_to_pid and sp_track_id_to_pid[int(track_id)] not in main_pids
            }
            if desired_language_by_pid:
                identified_tracks = _svc_cls()._mkvmerge_identify_json(temporary_output).get('tracks') or []
                identified_by_id = {
                    int(track.get('id')): track
                    for track in identified_tracks
                    if isinstance(track, dict) and str(track.get('id', '')).isdigit()
                }
                for output_track_id, source_pid in merged_track_id_to_pid.items():
                    desired_language = desired_language_by_pid.get(source_pid)
                    if not desired_language:
                        continue
                    properties = (identified_by_id.get(output_track_id) or {}).get('properties') or {}
                    actual_languages = {
                        str(properties.get(name) or '').strip().lower()
                        for name in ('language', 'language_ietf')
                        if str(properties.get(name) or '').strip()
                    }
                    if desired_language.lower() not in actual_languages:
                        return False
            os.replace(temporary_output, episode_mkv)
        except Exception:
            print_exc_terminal()
            return False
        finally:
            if os.path.isfile(temporary_output):
                force_remove_file(temporary_output)
            if chapter_backup and os.path.isfile(chapter_backup):
                force_remove_file(chapter_backup)

        sp_mux_cache[cache_key] = dict(merged_track_id_to_pid)
        return True

    def _build_sp_outputs(
            self,
            jobs: list[SpJob],
            cancel_event: Optional[threading.Event] = None,
            progress_cb: Optional[Callable[[int, str], None]] = None,
    ) -> list[tuple[int, str]]:
        """Execute the preflighted SP rows in visible order and require every planned output."""
        created_outputs: list[tuple[int, str]] = []
        for job in jobs:
            if cancel_event and cancel_event.is_set():
                raise TaskCancelled()
            entry = job.entry
            output_path = job.output_path
            output_is_episode = bool(job.episode_main_mpls_path)
            temporary_folder = ''
            try:
                source_path = job.source_path
                use_mpls_chapters = bool(entry.mpls_file)
                looping_playlist = (
                    _svc_cls()._detect_sp_looping_mpls(source_path)
                    if entry.mpls_file else None
                )
                if entry.mpls_file:
                    repeated_menu, repeated_m2ts = _svc_cls()._detect_repeated_single_m2ts_mpls(
                        source_path
                    )
                    if repeated_menu and repeated_m2ts:
                        source_path = os.path.join(
                            os.path.dirname(job.first_m2ts_path),
                            repeated_m2ts,
                        )
                        use_mpls_chapters = False

                audio_tracks = list(job.audio_tracks)
                subtitle_tracks = list(job.subtitle_tracks)
                mapped_audio_tracks = list(audio_tracks)
                mapped_subtitle_tracks = list(subtitle_tracks)
                if source_path.lower().endswith('.mpls'):
                    mapped_audio_tracks, mapped_subtitle_tracks = (
                        _svc_cls()._map_selected_tracks_to_mpls_track_ids(
                            source_path,
                            audio_tracks,
                            subtitle_tracks,
                        )
                    )

                if output_is_episode:
                    language_by_track_id: dict[str, str] = {}
                    language_overrides = dict(job.track_language_overrides)
                    for source_track, mapped_track in zip(audio_tracks, mapped_audio_tracks):
                        if source_track in language_overrides:
                            language_by_track_id[mapped_track] = language_overrides[source_track]
                    for source_track, mapped_track in zip(subtitle_tracks, mapped_subtitle_tracks):
                        if source_track in language_overrides:
                            language_by_track_id[mapped_track] = language_overrides[source_track]
                    if not self._mux_episode_linked_sp_mkvmerge(
                            episode_mkv=output_path,
                            sp_mpls_path=job.source_path,
                            episode_main_mpls=job.episode_main_mpls_path,
                            selected_sp_audio_track_ids=mapped_audio_tracks,
                            selected_sp_subtitle_track_ids=mapped_subtitle_tracks,
                            language_by_sp_track_id=language_by_track_id,
                            cancel_event=cancel_event,
                    ):
                        raise RuntimeError(
                            translate_text('SP processing failed in row {row}: {path}').format(
                                row=job.entry_index,
                                path=job.source_path,
                            )
                        )
                    created_outputs.append((job.entry_index, output_path))
                    if progress_cb:
                        progress_cb(job.entry_index, output_path)
                    continue

                is_image_output = (
                    output_path.lower().endswith('.png')
                    or not os.path.splitext(os.path.basename(output_path))[1]
                )
                if is_image_output:
                    image_sources = [
                        os.path.join(os.path.dirname(job.first_m2ts_path), filename)
                        for filename in entry.m2ts_files
                    ] or [job.first_m2ts_path]
                    if output_path.lower().endswith('.png') and len(image_sources) != 1:
                        raise ValueError(
                            translate_text('SP row {row} has an invalid image output path: {path}').format(
                                row=job.entry_index,
                                path=output_path,
                            )
                        )
                    if output_path.lower().endswith('.png'):
                        os.makedirs(os.path.dirname(output_path), exist_ok=True)
                        result = run_command([
                            FFMPEG_PATH or 'ffmpeg', '-y', '-i', image_sources[0],
                            '-frames:v', '1', '-update', '1', output_path,
                        ])
                        if result.returncode != 0 or not os.path.isfile(output_path):
                            raise RuntimeError(
                                translate_text('SP processing failed in row {row}: {path}').format(
                                    row=job.entry_index, path=job.source_path,
                                )
                            )
                    else:
                        os.makedirs(output_path, exist_ok=False)
                        if entry.m2ts_type == 'igs_menu' and len(image_sources) == 1:
                            M2TS(image_sources[0]).extract_igs_menu_png(output_path)
                            if not any(os.scandir(output_path)):
                                raise RuntimeError(
                                    translate_text('SP processing failed in row {row}: {path}').format(
                                        row=job.entry_index, path=job.source_path,
                                    )
                                )
                        else:
                            width = max(2, len(str(len(image_sources))))
                            for image_index, image_source in enumerate(image_sources, start=1):
                                image_name = (
                                    f'{str(image_index).zfill(width)}-'
                                    f'{os.path.splitext(os.path.basename(image_source))[0]}.png'
                                )
                                image_output = os.path.join(output_path, image_name)
                                result = run_command([
                                    FFMPEG_PATH or 'ffmpeg', '-y', '-i', image_source,
                                    '-frames:v', '1', '-update', '1', image_output,
                                ])
                                if result.returncode != 0 or not os.path.isfile(image_output):
                                    raise RuntimeError(
                                        translate_text('SP processing failed in row {row}: {path}').format(
                                            row=job.entry_index, path=image_source,
                                        )
                                    )
                    created_outputs.append((job.entry_index, output_path))
                    if progress_cb:
                        progress_cb(job.entry_index, output_path)
                    continue

                output_extension = os.path.splitext(output_path)[1].lower()
                if output_extension not in ('.mkv', '.mka', '.mks'):
                    if len(audio_tracks) == 1 and not subtitle_tracks:
                        if output_extension == '.flac':
                            extraction_ok = _svc_cls()._compress_audio_stream_to_flac(
                                job.first_m2ts_path, audio_tracks[0], output_path,
                            )
                        else:
                            os.makedirs(os.path.dirname(output_path), exist_ok=True)
                            extraction_ok = run_command([
                                FFMPEG_PATH or 'ffmpeg', '-y', '-i', source_path,
                                '-map', f'0:{audio_tracks[0]}', '-c', 'copy', output_path,
                            ]).returncode == 0
                    elif len(subtitle_tracks) == 1 and not audio_tracks:
                        os.makedirs(os.path.dirname(output_path), exist_ok=True)
                        extraction_ok = run_command([
                            FFMPEG_PATH or 'ffmpeg', '-y', '-i', source_path,
                            '-map', f'0:{subtitle_tracks[0]}', '-c', 'copy', output_path,
                        ]).returncode == 0
                    else:
                        extraction_ok = False
                    if not extraction_ok or not os.path.isfile(output_path):
                        raise RuntimeError(
                            translate_text('SP processing failed in row {row}: {path}').format(
                                row=job.entry_index, path=job.source_path,
                            )
                        )
                    created_outputs.append((job.entry_index, output_path))
                    if progress_cb:
                        progress_cb(job.entry_index, output_path)
                    continue

                output_folder = os.path.dirname(output_path)
                os.makedirs(output_folder, exist_ok=True)
                temporary_folder = tempfile.mkdtemp(prefix='_sp_mux_', dir=output_folder)
                primary_output = os.path.join(temporary_folder, os.path.basename(output_path))
                chapter_path = os.path.join(
                    temporary_folder,
                    f'{os.path.splitext(os.path.basename(output_path))[0]}.chapter.txt',
                )
                split_parts = ''
                custom_chapter_match = re.search(
                    r'(beginning|chapter_\d+)_to_(chapter_\d+|ending)',
                    entry.output_name,
                    re.IGNORECASE,
                )
                if custom_chapter_match:
                    if not job.main_mpls_path or not os.path.isfile(job.main_mpls_path):
                        raise FileNotFoundError(
                            translate_text('SP row {row} has no matching main playlist').format(
                                row=job.entry_index
                            )
                        )
                    self._write_custom_chapter_for_segment(
                        job.main_mpls_path, chapter_path, entry.output_name,
                    )
                    main_chapter = Chapter(job.main_mpls_path)
                    _index_to_m2ts, index_to_offset = get_index_to_m2ts_and_offset(main_chapter)
                    total_end = sum(map(len, main_chapter.mark_info.values())) + 1
                    bounds = re.search(
                        r'(beginning|chapter_(\d+))_to_(chapter_(\d+)|ending)',
                        entry.output_name,
                        re.IGNORECASE,
                    )
                    if not bounds:
                        raise ValueError(
                            translate_text('SP row {row} has an invalid chapter range').format(
                                row=job.entry_index
                            )
                        )
                    start_index = 1 if bounds.group(1).lower() == 'beginning' else int(bounds.group(2))
                    end_index = total_end if bounds.group(3).lower() == 'ending' else int(bounds.group(4))
                    start_index = max(1, min(start_index, total_end))
                    end_index = max(start_index + 1, min(end_index, total_end))
                    start_time = get_time_str(float(index_to_offset.get(start_index, 0.0)))
                    end_time = get_time_str(float(
                        main_chapter.get_total_time()
                        if end_index >= total_end
                        else index_to_offset.get(end_index, main_chapter.get_total_time())
                    ))
                    split_parts = (
                        f'{"00:00:00.000" if start_time == "0" else start_time}-'
                        f'{"00:00:00.000" if end_time == "0" else end_time}'
                    )
                elif use_mpls_chapters:
                    chapter_offsets = self._write_chapter_txt_from_mpls(source_path, chapter_path)
                    if not chapter_offsets or (
                            len(chapter_offsets) == 1 and chapter_offsets[0] == 0.0
                    ):
                        force_remove_file(chapter_path)
                if looping_playlist and str(looping_playlist.get('split_parts') or '').strip():
                    split_parts = str(looping_playlist['split_parts']).strip()

                if source_path.lower().endswith('.mpls'):
                    self._set_dovi_mux_plan_for_mpls(source_path)
                identify_ok = (
                    not source_path.lower().endswith('.mpls')
                    or self._mkvmerge_identify_covers_remux_slots(
                        source_path, audio_tracks, subtitle_tracks,
                    )
                )
                primary_ok = False
                if identify_ok:
                    find_mkvtoolnix()
                    command = [MKV_MERGE_PATH or 'mkvmerge']
                    ui_language = mkvtoolnix_ui_language_arg().strip()
                    if ui_language:
                        command.extend(ui_language.split())
                    if split_parts:
                        command.extend(['--split', f'parts:{split_parts}'])
                    if source_path.lower().endswith('.mpls'):
                        command.extend(
                            _svc_cls()._mkvmerge_dovi_primary_video_opts(
                                source_path, getattr(self, '_dovi_mux_plan', None),
                            ).split()
                        )
                    command.extend(['-o', primary_output])
                    if source_path.lower().endswith('.m2ts'):
                        dovi_plan = getattr(self, '_dovi_mux_plan', None)
                        if not (isinstance(dovi_plan, dict) and dovi_plan.get('active')):
                            dovi_plan = None
                        video_ids, audio_ids, subtitle_ids = (
                            _svc_cls()._mkvmerge_das_flag_strings_for_m2ts(
                                source_path, audio_tracks, subtitle_tracks,
                                dovi_plan=dovi_plan,
                            )
                        )
                        if output_extension != '.mkv':
                            command.append('-D')
                        elif video_ids:
                            command.extend(['-d', video_ids])
                        command.extend(['-a', audio_ids] if audio_ids else ['-A'])
                        command.extend(['-s', subtitle_ids] if subtitle_ids else ['-S'])
                    else:
                        command.extend(
                            ['-a', ','.join(mapped_audio_tracks)]
                            if mapped_audio_tracks else ['-A']
                        )
                        if output_extension != '.mkv':
                            command.append('-D')
                        command.extend(
                            ['-s', ','.join(mapped_subtitle_tracks)]
                            if mapped_subtitle_tracks else ['-S']
                        )
                    command.append(source_path)
                    print(f'{self.t("Mux command: ")}{subprocess.list2cmdline(command)}')
                    result = run_command(command)
                    if result.returncode in (0, 1):
                        candidates = [
                            os.path.join(temporary_folder, filename)
                            for filename in os.listdir(temporary_folder)
                            if filename.lower().endswith(output_extension)
                        ]
                        if len(candidates) == 1:
                            os.replace(candidates[0], output_path)
                            primary_ok = True

                if not primary_ok and source_path.lower().endswith('.mpls') and not custom_chapter_match:
                    max_play_items = int((looping_playlist or {}).get('max_clips') or 0)
                    primary_ok = self._try_remux_mpls_track_aligned(
                        source_path,
                        output_path,
                        audio_tracks,
                        subtitle_tracks,
                        '',
                        cancel_event=cancel_event,
                        max_play_items=max_play_items or None,
                    )
                if not primary_ok or not os.path.isfile(output_path):
                    raise RuntimeError(
                        translate_text('SP processing failed in row {row}: {path}').format(
                            row=job.entry_index, path=job.source_path,
                        )
                    )

                if use_mpls_chapters:
                    propedit_command = [MKV_PROP_EDIT_PATH or 'mkvpropedit']
                    ui_language = mkvtoolnix_ui_language_arg().strip()
                    if ui_language:
                        propedit_command.extend(ui_language.split())
                    clear_result = run_command(propedit_command + [output_path, '--chapters', ''])
                    if clear_result.returncode not in (0, 1):
                        raise RuntimeError(
                            translate_text('mkvpropedit failed for: {path}').format(path=output_path)
                        )
                    if os.path.isfile(chapter_path):
                        chapter_result = run_command(propedit_command + [output_path, '--chapters', chapter_path])
                        if chapter_result.returncode not in (0, 1):
                            raise RuntimeError(
                                translate_text('mkvpropedit failed for: {path}').format(path=output_path)
                            )

                if job.track_language_overrides:
                    self._fix_output_track_languages_with_mkvpropedit(
                        output_path, job.first_m2ts_path, audio_tracks, subtitle_tracks,
                        dict(job.track_language_overrides),
                        getattr(self, '_dovi_mux_plan', None),
                    )
                created_outputs.append((job.entry_index, output_path))
                if progress_cb:
                    progress_cb(job.entry_index, output_path)
            except TaskCancelled:
                raise
            except Exception as error:
                if not output_is_episode:
                    if os.path.isdir(output_path):
                        shutil.rmtree(output_path, ignore_errors=True)
                    elif os.path.isfile(output_path):
                        force_remove_file(output_path)

                raise RuntimeError(
                    translate_text('SP processing failed in row {row}: {path}').format(
                        row=job.entry_index, path=job.source_path,
                    )
                ) from error
            finally:
                if temporary_folder:
                    shutil.rmtree(temporary_folder, ignore_errors=True)
        return created_outputs

    def _write_chapter_txt_from_mpls(self, mpls_path: str, chapter_txt_path: str) -> list[float]:
        chapter = Chapter(mpls_path)
        mark_info = chapter.mark_info
        in_out_time = chapter.in_out_time
        mpls_duration = chapter.get_total_time()

        offsets = []
        offset = 0
        for ref_to_play_item_id in range(len(in_out_time)):
            mark_timestamps = mark_info.get(ref_to_play_item_id) or []
            for mark_timestamp in mark_timestamps:
                off = offset + (mark_timestamp - in_out_time[ref_to_play_item_id][1]) / 45000
                if mpls_duration - off >= 0.001:
                    offsets.append(off)
            offset += (in_out_time[ref_to_play_item_id][2] - in_out_time[ref_to_play_item_id][1]) / 45000

        offs = []
        for off in offsets:
            if off not in offs:
                offs.append(off)

        lines: list[str] = []
        for i, off in enumerate(offs, start=1):
            append_ogm_chapter_lines(lines, i, off)
        os.makedirs(os.path.dirname(chapter_txt_path) or '.', exist_ok=True)
        with open(chapter_txt_path, 'w', encoding='utf-8-sig') as f:
            f.write('\n'.join(lines) + ('\n' if lines else ''))
        print(
            f'{self.t("[chapter-debug] ")}{self.t("full chapter file written: ")}{chapter_txt_path} '
            f'(mpls={os.path.basename(mpls_path)} entries={len(lines) // 2})'
        )
        return offs

    def _get_chapter_offsets(self, mpls_path: str) -> list[float]:
        chapter = Chapter(mpls_path)
        mark_info = chapter.mark_info
        in_out_time = chapter.in_out_time
        mpls_duration = chapter.get_total_time()

        offsets = []
        offset = 0
        for ref_to_play_item_id in range(len(in_out_time)):
            mark_timestamps = mark_info.get(ref_to_play_item_id) or []
            for mark_timestamp in mark_timestamps:
                off = offset + (mark_timestamp - in_out_time[ref_to_play_item_id][1]) / 45000
                if mpls_duration - off >= 0.001:
                    offsets.append(off)
            offset += (in_out_time[ref_to_play_item_id][2] - in_out_time[ref_to_play_item_id][1]) / 45000

        offs = []
        for off in offsets:
            if off not in offs:
                offs.append(off)
        return offs

    def _write_custom_chapter_for_segment(self, mpls_path: str, chapter_txt_path: str, output_name: str):
        """Parse SP suffix like beginning_to_chapter_4, chapter_33_to_chapter_40, chapter_33_to_ending; same bounds as --split parts."""
        if not (mpls_path and str(mpls_path).strip()):
            print(f'[sp-mux-debug] _write_custom_chapter_for_segment: empty mpls_path output_name={output_name!r}')
            return
        if not os.path.isfile(mpls_path):
            print(f'[sp-mux-debug] _write_custom_chapter_for_segment: not a file mpls_path={mpls_path!r}')
            return
        m = re.search(r'(beginning|chapter_(\d+))_to_(chapter_(\d+)|ending)', output_name, re.IGNORECASE)
        if not m:
            return
        chapter = Chapter(mpls_path)
        rows = sum(map(len, chapter.mark_info.values()))
        total_end = rows + 1
        start_idx = 1 if (m.group(1) or '').lower() == 'beginning' else int(m.group(2) or 1)
        g3 = (m.group(3) or '').lower()
        if g3 == 'ending':
            end_idx = total_end
        else:
            end_idx = int(m.group(4) or total_end)
        start_idx = max(1, min(start_idx, total_end))
        end_idx = max(start_idx + 1, min(end_idx, total_end))
        self._write_remux_segment_chapter_txt(mpls_path, start_idx, end_idx, chapter_txt_path)

    def _mkv_sort_key(self, p: str):
        name = os.path.basename(p)
        m = re.search(r'BD_Vol_(\d{3})', name)
        vol = int(m.group(1)) if m else 9999
        m2 = re.search(r'-(\d{3})\.mkv$', name, re.IGNORECASE)
        seg = int(m2.group(1)) if m2 else 0
        return vol, seg, name.lower()
