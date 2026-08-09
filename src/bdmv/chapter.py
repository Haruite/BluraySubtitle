import os
from typing import Optional

from .clpi import CLPI
from .core import unpack_bytes


def chapter_play_item_file_ranges(
        chapter: 'Chapter',
) -> list[tuple[str, int, int, Optional[int], Optional[int]]]:
    """Return MPLS play-item timing with the corresponding CLPI file range."""
    cached = getattr(chapter, '_play_item_file_ranges_cache', None)
    if cached is not None:
        return list(cached)
    bdmv_dir = os.path.dirname(os.path.dirname(os.path.normpath(chapter.file_path)))
    ranges: list[tuple[str, int, int, Optional[int], Optional[int]]] = []
    for clip_name, in_time, out_time in chapter.in_out_time:
        file_start: Optional[int] = None
        file_end: Optional[int] = None
        clpi_path = os.path.join(bdmv_dir, 'CLIPINF', f'{clip_name}.clpi')
        if not os.path.isfile(clpi_path):
            clpi_path = os.path.join(bdmv_dir, 'BACKUP', 'CLIPINF', f'{clip_name}.clpi')
        try:
            sequence_info = CLPI(clpi_path).data.get('SequenceInfo') or {}
            atc_sequences = sequence_info.get('ATCSequences') or []
            stc_sequences = (atc_sequences[0].get('STCSequences') or []) if atc_sequences else []
            if stc_sequences:
                file_start = int(stc_sequences[0].get('PresentationStartTime'))
                file_end = int(stc_sequences[0].get('PresentationEndTime'))
        except (AttributeError, OSError, IndexError, KeyError, TypeError, ValueError):
            file_start = None
            file_end = None
        ranges.append((str(clip_name), int(in_time), int(out_time), file_start, file_end))
    chapter._play_item_file_ranges_cache = tuple(ranges)
    return ranges


def episode_tail_trim_plan(
        chapter: 'Chapter',
        episode_start: float,
        episode_end: float,
        max_tail_seconds: float = 30.0,
) -> tuple[float, tuple[str, ...]]:
    """Trim complete trailing play items only when the episode ends at the current clip's file end."""
    start = max(0.0, float(episode_start))
    end = max(start, float(episode_end))
    window_start = max(start, end - max(0.0, float(max_tail_seconds)))
    epsilon = 1.0 / 45000.0
    timeline: list[tuple[float, float, str, int, Optional[int]]] = []
    offset = 0.0
    for clip_name, in_time, out_time, _file_start, file_end in chapter_play_item_file_ranges(chapter):
        item_start = offset
        item_end = item_start + max(0.0, (out_time - in_time) / 45000.0)
        timeline.append((item_start, item_end, clip_name, out_time, file_end))
        offset = item_end

    last_index = next(
        (index for index in range(len(timeline) - 1, -1, -1)
         if abs(timeline[index][1] - end) <= epsilon),
        -1,
    )
    if last_index < 0:
        return end, ()
    _item_start, _item_end, _clip_name, item_out_time, file_end = timeline[last_index]
    if file_end is None or item_out_time != file_end:
        return end, ()

    trim_end = end
    removed_indexes: list[int] = []
    index = last_index
    while index >= 0:
        item_start, item_end, _clip_name, _item_out_time, _file_end = timeline[index]
        if abs(item_end - trim_end) > epsilon or item_start < window_start - epsilon:
            break
        if not any(previous_end > start + epsilon for _, previous_end, *_ in timeline[:index]):
            break
        removed_indexes.append(index)
        trim_end = item_start
        index -= 1

    retained_names = {
        clip_name
        for item_start, item_end, clip_name, _item_out_time, _file_end in timeline
        if item_end > start + epsilon and item_start < trim_end - epsilon
    }
    removed_names = tuple(dict.fromkeys(
        f'{timeline[index][2]}.m2ts'
        for index in reversed(removed_indexes)
        if timeline[index][2] not in retained_names
    ))
    return trim_end, removed_names


class Chapter:
    def __init__(self, file_path: str):
        # Reference: https://github.com/lw/BluRay/wiki/PlayItem
        self.in_out_time: list[tuple[str, int, int]] = []
        self.mark_info: dict[int, list[int]] = {}
        self.file_path: str = file_path
        self.pid_to_lang = {}
        self._play_item_file_ranges_cache: Optional[
            tuple[tuple[str, int, int, Optional[int], Optional[int]], ...]
        ] = None

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
    'chapter_play_item_file_ranges',
    'episode_tail_trim_plan',
]
