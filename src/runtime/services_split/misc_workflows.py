"""Auto-generated split target: misc_workflows."""
import os
import re
import threading
from typing import Optional

from src.bdmv import Chapter
from src.core import DEFAULT_APPROX_EPISODE_DURATION_SECONDS
from src.exports.utils import get_time_str
from .media_info_and_track_mapping import MediaInfoTrackMappingMixin
from .service_base import BluraySubtitleServiceBase
from ..services.cancelled import _Cancelled

_SP_ORPHAN_M2TS_SKIP_DURATION_BYTES = 512 * 1024
_MOVIE_SP_MAIN_DURATION_EPS = 0.001
_M2TS_DETAIL_SEGMENT_RE = re.compile(r'^(.+?)\(([^)]+)-([^)]+)\)\s*$')
_MOVIE_OUTPUT_CHAR_MAP = {
    '?': '？', '*': '★', '<': '《', '>': '》', ':': '：', '"': "'",
    '/': '／', '\\': '／', '|': '￨',
}


def _parse_m2ts_detail_time_to_seconds(s: str) -> float:
    try:
        parts = [p for p in str(s or '').strip().split(':') if p != '']
        if not parts:
            return 0.0
        val = 0.0
        for n in parts:
            val = val * 60.0 + float(n)
        return val
    except Exception:
        return 0.0


def _m2ts_file_detail_segments_contained_in(sp_detail: str, episode_detail: str, *, eps: float = 0.05) -> bool:
    sp_segs = _parse_m2ts_file_detail_segments(sp_detail)
    if not sp_segs:
        return False
    ep_segs = _parse_m2ts_file_detail_segments(episode_detail)
    if not ep_segs:
        return False
    for name, s0, s1 in sp_segs:
        if s1 <= s0 + eps:
            continue
        matched = False
        for en, a0, a1 in ep_segs:
            if en != name:
                continue
            if s0 + eps >= a0 and s1 <= a1 + eps:
                matched = True
                break
        if not matched:
            return False
    return True


def _parse_m2ts_file_detail_segments(detail: str) -> list[tuple[str, float, float]]:
    text = str(detail or '').strip()
    if not text:
        return []
    segments: list[tuple[str, float, float]] = []
    for part in text.split(','):
        piece = part.strip()
        if not piece:
            continue
        m = _M2TS_DETAIL_SEGMENT_RE.match(piece)
        if not m:
            return []
        name = m.group(1).strip()
        start_sec = _parse_m2ts_detail_time_to_seconds(m.group(2))
        end_sec = _parse_m2ts_detail_time_to_seconds(m.group(3))
        segments.append((name, start_sec, end_sec))
    return segments


def _movie_sp_duration_matches_main(sp_duration_sec: float, main_duration_sec: float) -> bool:
    """True when SP playlist duration equals main feature (movie mode default-uncheck)."""
    try:
        main_d = float(main_duration_sec)
        sp_d = float(sp_duration_sec)
    except Exception:
        return False
    if main_d < 0:
        return False
    return abs(sp_d - main_d) < _MOVIE_SP_MAIN_DURATION_EPS


def _movie_main_duration_by_bdmv_from_configuration(
        configuration: Optional[dict[int, dict[str, int | str]]],
        bdmv_path: str = '',
) -> dict[int, float]:
    """``Chapter.get_total_time()`` per ``bdmv_index`` for movie-mode main MPLS rows."""
    out: dict[int, float] = {}
    for _conf in (configuration or {}).values():
        try:
            bdmv_index = int(_conf.get('bdmv_index') or 0)
        except Exception:
            continue
        if bdmv_index <= 0 or bdmv_index in out:
            continue
        folder = str(_conf.get('folder') or bdmv_path or '').strip()
        sm = str(_conf.get('selected_mpls') or '').strip()
        mpls_full = _playlist_mpls_path(folder, sm)
        if not mpls_full or not os.path.isfile(mpls_full):
            continue
        try:
            out[bdmv_index] = float(Chapter(mpls_full).get_total_time())
        except Exception:
            continue
    return out


def _movie_main_duration_by_bdmv_from_mpls_paths(
        selected_main_by_bdmv: dict[int, list[str]],
) -> dict[int, float]:
    out: dict[int, float] = {}
    for bdmv_index, paths in (selected_main_by_bdmv or {}).items():
        try:
            bi = int(bdmv_index)
        except Exception:
            continue
        if bi <= 0 or bi in out:
            continue
        for p in paths or []:
            mp = os.path.normpath(str(p or ''))
            if not mp or not os.path.isfile(mp):
                continue
            try:
                out[bi] = float(Chapter(mp).get_total_time())
            except Exception:
                pass
            break
    return out


def _playlist_mpls_path(bdmv_root: str, selected_mpls: str) -> str:
    """Resolve configuration ``selected_mpls`` (stem or ``BDMV/PLAYLIST/stem``) to an absolute ``.mpls`` path."""
    raw = str(selected_mpls or '').strip()
    root = os.path.normpath(str(bdmv_root or '')).rstrip(os.sep)
    if not raw or not root:
        return ''
    if os.path.isfile(raw):
        return os.path.normpath(raw)
    norm = raw.replace('\\', '/')
    if norm.lower().endswith('.mpls'):
        if norm.lower().startswith('bdmv/playlist/'):
            return os.path.normpath(os.path.join(root, *norm.split('/')))
        return os.path.normpath(os.path.join(root, 'BDMV', 'PLAYLIST', os.path.basename(norm)))
    if norm.lower().startswith('bdmv/playlist/'):
        return os.path.normpath(os.path.join(root, *norm.split('/')) + '.mpls')
    stem = os.path.splitext(os.path.basename(norm))[0]
    return os.path.normpath(os.path.join(root, 'BDMV', 'PLAYLIST', f'{stem}.mpls'))


def _m2ts_has_video_or_audio(stream_path: str) -> bool:
    try:
        for s in MediaInfoTrackMappingMixin._m2ts_track_streams(stream_path) or []:
            if str(s.get('codec_type') or '') in ('video', 'audio'):
                return True
    except Exception:
        pass
    return False


def _filter_m2ts_file_detail_by_basenames(detail: str, basenames: list[str]) -> str:
    wanted = {
        os.path.basename(str(b or '')).strip().lower()
        for b in basenames
        if str(b or '').strip()
    }
    if not wanted:
        return str(detail or '').strip()
    parts: list[str] = []
    for part in str(detail or '').split(','):
        piece = part.strip()
        if not piece:
            continue
        head = piece.split('(', 1)[0].strip().lower()
        if head in wanted:
            parts.append(piece)
    return ','.join(parts)


class MiscWorkflowsMixin(BluraySubtitleServiceBase):
    @staticmethod
    def _group_selected_mpls_by_folder_runs(selected_mpls: list[tuple[str, str]]) -> list[list[tuple[str, str]]]:
        if not selected_mpls:
            return []
        groups: list[list[tuple[str, str]]] = []
        cur_fn = os.path.normpath(str(selected_mpls[0][0]))
        cur: list[tuple[str, str]] = [selected_mpls[0]]
        for t in selected_mpls[1:]:
            fn = os.path.normpath(str(t[0]))
            if fn == cur_fn:
                cur.append(t)
            else:
                groups.append(cur)
                cur_fn = fn
                cur = [t]
        groups.append(cur)
        return groups

    def _volume_configuration_no_sub_files(
            self,
            volume_selected: list[tuple[str, str]],
            cancel_event: Optional[threading.Event] = None,
    ) -> dict[int, dict[str, int | str]]:
        """Episode rows for one disc's selected main MPLS list (no subtitle files). Keys 0..n-1 local."""
        if self.sub_files:
            raise ValueError('_volume_configuration_no_sub_files requires empty sub_files')
        if not volume_selected:
            return {}
        configuration: dict[int, dict[str, int | str]] = {}
        sub_index = 0
        approx_end_time = float(
            getattr(self, 'approx_episode_duration_seconds', DEFAULT_APPROX_EPISODE_DURATION_SECONDS)
            or DEFAULT_APPROX_EPISODE_DURATION_SECONDS)
        folder_to_bdmv_index: dict[str, int] = {}
        for i, f in enumerate(getattr(self, 'bluray_folders', []) or []):
            try:
                folder_to_bdmv_index[os.path.normpath(str(f))] = int(i + 1)
            except Exception:
                pass
        for folder, selected_mpls_no_ext in volume_selected:
            if cancel_event and cancel_event.is_set():
                raise _Cancelled()
            folder_n = os.path.normpath(str(folder))
            if folder_n not in folder_to_bdmv_index:
                folder_to_bdmv_index[folder_n] = len(folder_to_bdmv_index) + 1
            bdmv_index = folder_to_bdmv_index[folder_n]
            disc_output_name = self._resolve_disc_output_name(selected_mpls_no_ext)
            chapter = Chapter(selected_mpls_no_ext + '.mpls')
            start_time = 0
            sub_end_time = approx_end_time
            left_time = chapter.get_total_time()
            configuration[sub_index] = {'folder': folder, 'selected_mpls': selected_mpls_no_ext,
                                        'bdmv_index': bdmv_index, 'chapter_index': 1, 'offset': '0',
                                        'disc_output_name': disc_output_name}
            j = 1
            for i, play_item_in_out_time in enumerate(chapter.in_out_time):
                play_item_marks = chapter.mark_info.get(i)
                chapter_num = len(play_item_marks or [])
                if play_item_marks:
                    play_item_duration_time = play_item_in_out_time[2] - play_item_in_out_time[1]
                    time_shift = (start_time + play_item_marks[0] - play_item_in_out_time[1]) / 45000
                    if time_shift > sub_end_time - 300:
                        if left_time > approx_end_time - 180:
                            sub_index += 1
                            sub_end_time = (time_shift + approx_end_time)
                            configuration[sub_index] = {'folder': folder, 'selected_mpls': selected_mpls_no_ext,
                                                        'bdmv_index': bdmv_index, 'chapter_index': j,
                                                        'offset': get_time_str(time_shift),
                                                        'disc_output_name': disc_output_name}

                    if play_item_duration_time / 45000 > 2600 and sub_end_time - time_shift < 1800:
                        k = j
                        for mark in play_item_marks[1:]:
                            k += 1
                            time_shift = (start_time + mark - play_item_in_out_time[1]) / 45000
                            if time_shift > sub_end_time and (
                                    play_item_in_out_time[2] - mark) / 45000 > 1200:
                                sub_index += 1
                                sub_end_time = (time_shift + approx_end_time)
                                configuration[sub_index] = {'folder': folder, 'selected_mpls': selected_mpls_no_ext,
                                                            'bdmv_index': bdmv_index, 'chapter_index': k,
                                                            'offset': get_time_str(time_shift),
                                                            'disc_output_name': disc_output_name}

                j += chapter_num
                start_time += play_item_in_out_time[2] - play_item_in_out_time[1]
                left_time += (play_item_in_out_time[1] - play_item_in_out_time[2]) / 45000

            sub_index += 1
        return configuration

    @staticmethod
    def _sanitize_movie_output_basename(name: str) -> str:
        text = str(name or '').strip()
        return ''.join(_MOVIE_OUTPUT_CHAR_MAP.get(ch, ch) for ch in text)

    def _sp_m2ts_detail_for_entry(self, bdmv_index: int, mpls_file: str, m2ts_files: list[str]) -> str:
        mpls_name = str(mpls_file or '').strip()
        playlist_dir = os.path.normpath(
            os.path.join(str(self.bdmv_path or ''), 'BDMV', 'PLAYLIST'))
        if mpls_name and os.path.isdir(playlist_dir):
            mpls_path = os.path.normpath(os.path.join(playlist_dir, mpls_name))
            if os.path.isfile(mpls_path):
                try:
                    detail = MediaInfoTrackMappingMixin.m2ts_file_detail_from_mpls_playlist(mpls_path).strip()
                    if detail and m2ts_files:
                        detail = _filter_m2ts_file_detail_by_basenames(detail, m2ts_files)
                    return detail
                except Exception:
                    return ''
        stream_dir = os.path.normpath(os.path.join(str(self.bdmv_path or ''), 'BDMV', 'STREAM'))
        paths: list[str] = []
        for bn in m2ts_files or []:
            bn = str(bn or '').strip()
            if bn and stream_dir:
                paths.append(os.path.normpath(os.path.join(stream_dir, bn)))
        if paths:
            try:
                return MediaInfoTrackMappingMixin.m2ts_file_detail_for_standalone_m2ts_paths(paths).strip()
            except Exception:
                pass
        return ''

    def _movie_sp_covered_by_table2(self, bdmv_index: int, sp_detail: str, table2_details: list[str]) -> bool:
        sp_detail = str(sp_detail or '').strip()
        if not sp_detail:
            return False
        for ep_detail in table2_details:
            ep_detail = str(ep_detail or '').strip()
            if not ep_detail:
                continue
            if sp_detail == ep_detail:
                return True
            if _m2ts_file_detail_segments_contained_in(sp_detail, ep_detail):
                return True
        return False

    def build_movie_mode_configuration(
        self, selected_mpls: list[tuple[str, str]],
    ) -> tuple[dict[int, dict[str, int | str]], list[str]]:
        """One table2 row per disc (movie mode), matching GUI ``_refresh_movie_table2``."""
        folder_to_bdmv: dict[str, int] = {}
        for i, f in enumerate(getattr(self, 'bluray_folders', []) or []):
            try:
                folder_to_bdmv[os.path.normpath(str(f))] = int(i + 1)
            except Exception:
                pass
        disc_rows: list[tuple[int, str, str]] = []
        for folder, mpls_no_ext in selected_mpls:
            folder_n = os.path.normpath(str(folder))
            if folder_n not in folder_to_bdmv:
                folder_to_bdmv[folder_n] = len(folder_to_bdmv) + 1
            disc_rows.append((folder_to_bdmv[folder_n], folder_n, str(mpls_no_ext or '').strip()))
        disc_rows.sort(key=lambda x: x[0])
        single_volume = len(disc_rows) == 1
        configuration: dict[int, dict[str, int | str]] = {}
        episode_output_names: list[str] = []
        for row_i, (bdmv_index, folder, mpls_no_ext) in enumerate(disc_rows):
            disc_name = self._resolve_disc_output_name(mpls_no_ext)
            bdmv_vol = f'{bdmv_index:03d}'
            auto_name = f'{disc_name}.mkv' if single_volume else f'{disc_name}_BD_Vol_{bdmv_vol}.mkv'
            output_name = self._sanitize_movie_output_basename(auto_name)
            mpls_path = os.path.normpath(os.path.join(folder, 'BDMV', 'PLAYLIST', f'{mpls_no_ext}.mpls'))
            chapter = Chapter(mpls_path if os.path.isfile(mpls_path) else f'{mpls_no_ext}.mpls')
            rows = sum(map(len, chapter.mark_info.values()))
            configuration[row_i] = {
                'folder': folder,
                'selected_mpls': mpls_no_ext,
                'bdmv_index': bdmv_index,
                'chapter_index': 1,
                'start_at_chapter': 1,
                'end_at_chapter': rows + 1,
                'offset': '0',
                'disc_output_name': disc_name,
                'output_name': output_name,
            }
            episode_output_names.append(output_name)
        return configuration, episode_output_names

    def _assign_movie_sp_output_names(self, entries: list[dict[str, object]]) -> None:
        selected_by_bdmv: dict[int, list[dict[str, object]]] = {}
        for e in entries:
            if not bool(e.get('selected', True)):
                continue
            try:
                bi = int(e.get('bdmv_index') or 0)
            except Exception:
                bi = 0
            if bi <= 0:
                continue
            selected_by_bdmv.setdefault(bi, []).append(e)
        for bdmv_index, items in selected_by_bdmv.items():
            digits = max(2, len(str(len(items))))
            for seq, e in enumerate(items, start=1):
                bdmv_vol = f'{int(bdmv_index):03d}'
                sp_no = str(seq).zfill(digits)
                mpls_file = str(e.get('mpls_file') or '').strip()
                m2ts_text = str(e.get('m2ts_file') or '').strip()
                m2ts_files = [x.strip() for x in m2ts_text.split(',') if x.strip()]
                if mpls_file:
                    e['output_name'] = f'SPs/BD_Vol_{bdmv_vol}_SP{sp_no}.mkv'
                    continue
                if not m2ts_files:
                    e['output_name'] = ''
                    e['selected'] = False
                    continue
                stem = os.path.splitext(os.path.basename(m2ts_files[0]))[0]
                stream_dir = os.path.normpath(os.path.join(str(self.bdmv_path or ''), 'BDMV', 'STREAM'))
                src = os.path.join(stream_dir, m2ts_files[0]) if stream_dir else ''
                ext = '.mka'
                if src and os.path.isfile(src):
                    try:
                        if not MediaInfoTrackMappingMixin._is_audio_only_media(src):
                            ext = '.mkv'
                    except Exception:
                        ext = '.mkv'
                e['output_name'] = f'SPs/BD_Vol_{bdmv_vol}_{stem}{ext}'

    def build_movie_mode_sp_entries(
        self, configuration: dict[int, dict[str, int | str]],
    ) -> list[dict[str, int | str]]:
        """Default table3 SP rows for movie remux (same rules as GUI refresh_sp_table)."""
        main_mpls_basenames: dict[int, str] = {}
        main_duration_by_bdmv = _movie_main_duration_by_bdmv_from_configuration(
            configuration, str(self.bdmv_path or ''))
        table2_detail_by_bdmv: dict[int, list[str]] = {}
        for _conf in (configuration or {}).values():
            try:
                bdmv_index = int(_conf.get('bdmv_index') or 0)
            except Exception:
                continue
            if bdmv_index <= 0:
                continue
            sm = str(_conf.get('selected_mpls') or '').strip()
            folder = str(_conf.get('folder') or self.bdmv_path or '').strip()
            mpls_full = _playlist_mpls_path(folder or str(self.bdmv_path or ''), sm)
            if sm and mpls_full and os.path.isfile(mpls_full):
                main_mpls_basenames[bdmv_index] = os.path.basename(mpls_full)
                try:
                    det = MediaInfoTrackMappingMixin.m2ts_file_detail_from_mpls_playlist(mpls_full).strip()
                    if det:
                        table2_detail_by_bdmv.setdefault(bdmv_index, []).append(det)
                except Exception:
                    pass

        playlist_dir = os.path.normpath(os.path.join(str(self.bdmv_path or ''), 'BDMV', 'PLAYLIST'))
        if not os.path.isdir(playlist_dir):
            return []
        selected_main_by_bdmv: dict[int, list[str]] = {}
        for bdmv_index, base in main_mpls_basenames.items():
            mpls_full = os.path.normpath(os.path.join(playlist_dir, base))
            if os.path.isfile(mpls_full):
                selected_main_by_bdmv[bdmv_index] = [mpls_full]

        entries: list[dict[str, object]] = []
        selected_main_basename_set = {
            os.path.basename(p) for paths in selected_main_by_bdmv.values() for p in paths
        }
        all_mpls_m2ts: set[str] = set()
        try:
            playlist_files = sorted(os.listdir(playlist_dir))
        except Exception:
            playlist_files = []
        for mpls_file in playlist_files:
            if not str(mpls_file).lower().endswith('.mpls'):
                continue
            mpls_file_path = os.path.join(playlist_dir, mpls_file)
            try:
                ch = Chapter(mpls_file_path)
                m2ts_files = list(MediaInfoTrackMappingMixin.m2ts_file_basenames_from_mpls_playlist(mpls_file_path))
            except Exception:
                continue
            for bn in m2ts_files:
                if bn:
                    all_mpls_m2ts.add(bn)
            if os.path.basename(mpls_file_path) in selected_main_basename_set:
                continue
            default_selected = True
            try:
                dur_for_select = float(ch.get_total_time_no_repeat())
            except Exception:
                dur_for_select = float(ch.get_total_time())
            if len(set(m2ts_files)) < 3 and dur_for_select < 30:
                default_selected = False
            main_dur = main_duration_by_bdmv.get(1)
            if default_selected and main_dur is not None and _movie_sp_duration_matches_main(
                    float(dur_for_select), main_dur):
                default_selected = False
            sp_detail = ''
            try:
                bdmv_index = 1
                sp_detail = self._sp_m2ts_detail_for_entry(
                    bdmv_index, os.path.basename(mpls_file_path), m2ts_files)
                if default_selected and self._movie_sp_covered_by_table2(
                        bdmv_index, sp_detail, table2_detail_by_bdmv.get(bdmv_index, [])):
                    default_selected = False
            except Exception:
                pass
            entries.append({
                'bdmv_index': 1,
                'mpls_file': os.path.basename(mpls_file_path),
                'm2ts_file': ','.join(m2ts_files),
                'm2ts_file_detail': sp_detail,
                'selected': bool(default_selected),
                'output_name': '',
                'bdmv_root': str(self.bdmv_path or ''),
            })

        stream_folder = os.path.normpath(os.path.join(str(self.bdmv_path or ''), 'BDMV', 'STREAM'))
        if os.path.isdir(stream_folder):
            try:
                stream_files = sorted(os.listdir(stream_folder))
            except Exception:
                stream_files = []
            for sf in stream_files:
                if not sf.endswith('.m2ts') or sf in all_mpls_m2ts:
                    continue
                m2ts_path = os.path.join(stream_folder, sf)
                try:
                    sz = os.path.getsize(m2ts_path)
                except Exception:
                    sz = 0
                if sz < _SP_ORPHAN_M2TS_SKIP_DURATION_BYTES:
                    dur = 0.0
                else:
                    try:
                        dur = MediaInfoTrackMappingMixin._m2ts_duration_90k(m2ts_path) / 90000.0
                    except Exception:
                        dur = 0.0
                orphan_selected = bool(dur >= 30.0) and _m2ts_has_video_or_audio(m2ts_path)
                main_dur = main_duration_by_bdmv.get(1)
                if orphan_selected and main_dur is not None and _movie_sp_duration_matches_main(
                        float(dur), main_dur):
                    orphan_selected = False
                orphan_detail = ''
                if orphan_selected:
                    try:
                        orphan_detail = self._sp_m2ts_detail_for_entry(1, '', [sf])
                        if self._movie_sp_covered_by_table2(1, orphan_detail, table2_detail_by_bdmv.get(1, [])):
                            orphan_selected = False
                    except Exception:
                        pass
                entries.append({
                    'bdmv_index': 1,
                    'mpls_file': '',
                    'm2ts_file': sf,
                    'm2ts_file_detail': orphan_detail,
                    'selected': bool(orphan_selected),
                    'output_name': '',
                    'bdmv_root': str(self.bdmv_path or ''),
                })

        self._assign_movie_sp_output_names(entries)
        return [dict(e) for e in entries]
