import os
from typing import Optional

from .core import unpack_bytes

# Episode-mode optional trim: drop last MPLS play item if shorter than threshold (copyright bumper).
# Registered entries replace ``in_out_time`` / ``mark_info`` on subsequent ``Chapter(path)`` loads in-process.
_CHAPTER_TAIL_TRIM: dict[str, tuple[list[tuple[str, int, int]], dict[int, list[int]]]] = {}


def chapter_norm_mpls_key(path: str) -> str:
    try:
        return os.path.normcase(os.path.normpath(os.path.abspath(str(path or ''))))
    except Exception:
        return os.path.normcase(os.path.normpath(str(path or '')))


def chapter_tail_trim_clear() -> None:
    _CHAPTER_TAIL_TRIM.clear()


def chapter_tail_trim_active_for_path(mpls_path: str) -> bool:
    mp = str(mpls_path or '').strip()
    if not mp.lower().endswith('.mpls'):
        mp = f'{mp}.mpls'
    return chapter_norm_mpls_key(mp) in _CHAPTER_TAIL_TRIM


def _chapter_tail_trim_build(ch: 'Chapter', max_tail_sec: float) -> Optional[tuple[list[tuple[str, int, int]], dict[int, list[int]]]]:
    ios = list(ch.in_out_time or [])
    if len(ios) < 2:
        return None
    last = ios[-1]
    dur = (last[2] - last[1]) / 45000.0
    if dur + 1e-9 >= float(max_tail_sec):
        return None
    last_idx0 = len(ios) - 1
    new_ios = ios[:-1]
    # MPLS mark ref may be 0-based play-item index or 1-based id; drop marks on the removed tail item.
    rm_refs = {last_idx0, last_idx0 + 1}
    new_marks: dict[int, list[int]] = {}
    for k, v in (ch.mark_info or {}).items():
        try:
            ki = int(k)
        except (TypeError, ValueError):
            continue
        if ki in rm_refs:
            continue
        new_marks[ki] = list(v)
    return (new_ios, new_marks)


def chapter_tail_trim_register_path(mpls_path: str, max_tail_sec: float = 15.0) -> bool:
    """Load MPLS from disk, then if the last play item is shorter than ``max_tail_sec`` register a trim override.

    Returns True when a trim override is active for this path (including re-register of same trim).
    """
    mp = str(mpls_path or '').strip()
    if not mp.lower().endswith('.mpls'):
        mp = f'{mp}.mpls'
    if not mp or not os.path.isfile(mp):
        return False
    norm = chapter_norm_mpls_key(mp)
    _CHAPTER_TAIL_TRIM.pop(norm, None)
    ch = Chapter(mp)
    built = _chapter_tail_trim_build(ch, max_tail_sec)
    if built is None:
        return False
    _CHAPTER_TAIL_TRIM[norm] = built
    return True


def _apply_chapter_tail_trim_override(ch: 'Chapter') -> None:
    norm = chapter_norm_mpls_key(ch.file_path)
    tup = _CHAPTER_TAIL_TRIM.get(norm)
    if not tup:
        return
    ios, mi = tup
    ch.in_out_time = list(ios)
    ch.mark_info = {int(k): list(v) for k, v in mi.items()}


class Chapter:
    def __init__(self, file_path: str):
        # Reference: https://github.com/lw/BluRay/wiki/PlayItem
        self.in_out_time: list[tuple[str, int, int]] = []
        self.mark_info: dict[int, list[int]] = {}
        self.file_path: str = file_path
        self.pid_to_lang = {}

        with open(file_path, 'rb') as mpls_file:
            mpls_file.seek(8)
            playlist_start_address = unpack_bytes(mpls_file.read(4), 0, 4)
            playlist_mark_start_address = unpack_bytes(mpls_file.read(4), 0, 4)

            mpls_file.seek(playlist_start_address)
            mpls_file.read(6)
            nb_play_items = unpack_bytes(mpls_file.read(2), 0, 2)
            mpls_file.read(2)
            for _ in range(nb_play_items):
                pos = mpls_file.tell()
                length = unpack_bytes(mpls_file.read(2), 0, 2)
                if length != 0:
                    clip_information_filename = mpls_file.read(5).decode()
                    mpls_file.read(7)
                    in_time = unpack_bytes(mpls_file.read(4), 0, 4)
                    out_time = unpack_bytes(mpls_file.read(4), 0, 4)
                    self.in_out_time.append((clip_information_filename, in_time, out_time))
                mpls_file.seek(pos + length + 2)

            mpls_file.seek(playlist_mark_start_address)
            mpls_file.read(4)
            nb_playlist_marks = unpack_bytes(mpls_file.read(2), 0, 2)
            for _ in range(nb_playlist_marks):
                mpls_file.read(2)
                ref_to_play_item_id = unpack_bytes(mpls_file.read(2), 0, 2)
                mark_timestamp = unpack_bytes(mpls_file.read(4), 0, 4)
                mpls_file.read(6)
                if ref_to_play_item_id in self.mark_info:
                    self.mark_info[ref_to_play_item_id].append(mark_timestamp)
                else:
                    self.mark_info[ref_to_play_item_id] = [mark_timestamp]

        _apply_chapter_tail_trim_override(self)

    def get_total_time(self):
        return sum(map(lambda x: (x[2] - x[1]) / 45000, self.in_out_time))

    def get_total_time_no_repeat(self):
        return sum({x[0]: (x[2] - x[1]) / 45000 for x in self.in_out_time}.values())

    def get_pid_to_language(self):
        with open(self.file_path, 'rb') as mpls_file:
            mpls_file.seek(8)
            playlist_start_address = unpack_bytes(mpls_file.read(4), 0, 4)
            mpls_file.seek(playlist_start_address)
            mpls_file.read(6)
            nb_of_play_items = unpack_bytes(mpls_file.read(2), 0, 2)
            mpls_file.read(2)
            for _ in range(nb_of_play_items):
                mpls_file.read(12)
                is_multi_angle = (unpack_bytes(mpls_file.read(1), 0, 1) >> 4) % 2
                mpls_file.read(21)
                if is_multi_angle:
                    nb_of_angles = unpack_bytes(mpls_file.read(1), 0, 1)
                    mpls_file.read(1)
                    for _ in range(nb_of_angles - 1):
                        mpls_file.read(10)
                mpls_file.read(4)
                nb = []
                for _ in range(8):
                    nb.append(unpack_bytes(mpls_file.read(1), 0, 1))
                mpls_file.read(4)
                for _ in range(sum(nb)):
                    stream_entry_length = unpack_bytes(mpls_file.read(1), 0, 1)
                    stream_type = unpack_bytes(mpls_file.read(1), 0, 1)
                    if stream_type == 1:
                        stream_pid = unpack_bytes(mpls_file.read(2), 0, 2)
                        mpls_file.read(stream_entry_length - 3)
                    elif stream_type == 2:
                        mpls_file.read(2)
                        stream_pid = unpack_bytes(mpls_file.read(2), 0, 2)
                        mpls_file.read(stream_entry_length - 5)
                    elif stream_type == 3 or stream_type == 4:
                        mpls_file.read(1)
                        stream_pid = unpack_bytes(mpls_file.read(2), 0, 2)
                        mpls_file.read(stream_entry_length - 4)
                    stream_attributes_length = unpack_bytes(mpls_file.read(1), 0, 1)
                    stream_coding_type = unpack_bytes(mpls_file.read(1), 0, 1)
                    if stream_coding_type in (1, 2, 27, 36, 234):
                        self.pid_to_lang[stream_pid] = 'und'
                        mpls_file.read(stream_attributes_length - 1)
                    elif stream_coding_type in (3, 4, 128, 129, 130, 131, 132, 133, 134, 146, 161, 162):
                        mpls_file.read(1)
                        self.pid_to_lang[stream_pid] = mpls_file.read(3).decode()
                        mpls_file.read(stream_attributes_length - 5)
                    elif stream_coding_type in (144, 145):
                        self.pid_to_lang[stream_pid] = mpls_file.read(3).decode()
                        mpls_file.read(stream_attributes_length - 4)
                break


__all__ = [
    'Chapter',
    'chapter_norm_mpls_key',
    'chapter_tail_trim_clear',
    'chapter_tail_trim_active_for_path',
    'chapter_tail_trim_register_path',
]
