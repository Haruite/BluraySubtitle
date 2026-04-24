import os
import subprocess
from struct import unpack

from src.core import find_mkvtoolinx
from src.core import mkvtoolnix_ui_language_arg
from src.core import settings as core_settings
from src.core.i18n import translate_text


class MKV:
    def __init__(self, path: str):
        self.path = path
        find_mkvtoolinx()

    def get_duration(self):
        # Matroska IDs used by mkvinfo:
        # Segment: 0x18538067, Info: 0x1549A966,
        # TimecodeScale: 0x2AD7B1 (default 1000000 ns), Duration: 0x4489 (float)
        SEGMENT_ID = 0x18538067
        INFO_ID = 0x1549A966
        TIMECODE_SCALE_ID = 0x2AD7B1
        DURATION_ID = 0x4489
        DEFAULT_TIMECODE_SCALE = 1000000

        def read_vint(f, for_id: bool):
            first_b = f.read(1)
            if not first_b:
                return None, 0

            first = first_b[0]
            mask = 0x80
            length = 1
            while length <= 8 and (first & mask) == 0:
                mask >>= 1
                length += 1
            if length > 8:
                return None, 0

            rest = f.read(length - 1)
            if len(rest) != length - 1:
                return None, 0
            raw = first_b + rest

            if for_id:
                return int.from_bytes(raw, "big"), length

            value = first & (mask - 1)
            for idx in range(1, length):
                value = (value << 8) | raw[idx]

            unknown_size = value == (1 << (7 * length)) - 1
            return (None if unknown_size else value), length

        def parse_uint(buf: bytes) -> int:
            if not buf:
                return 0
            return int.from_bytes(buf, "big", signed=False)

        def parse_float(buf: bytes):
            if len(buf) == 4:
                return unpack(">f", buf)[0]
            if len(buf) == 8:
                return unpack(">d", buf)[0]
            return None

        def skip_bytes(f, n: int):
            if n <= 0:
                return
            f.seek(n, 1)

        def read_info_duration(f, info_end: int):
            duration = None
            timecode_scale = DEFAULT_TIMECODE_SCALE

            while f.tell() < info_end:
                el_id, id_len = read_vint(f, for_id=True)
                if id_len == 0:
                    break

                el_size, size_len = read_vint(f, for_id=False)
                if size_len == 0:
                    break

                payload_start = f.tell()
                payload_end = info_end if el_size is None else min(info_end, payload_start + el_size)
                if payload_end < payload_start:
                    break
                payload_len = payload_end - payload_start

                if el_id == TIMECODE_SCALE_ID:
                    payload = f.read(payload_len)
                    timecode_scale = parse_uint(payload) or DEFAULT_TIMECODE_SCALE
                elif el_id == DURATION_ID:
                    payload = f.read(payload_len)
                    duration = parse_float(payload)
                else:
                    skip_bytes(f, payload_len)

                f.seek(payload_end)
            if duration is None:
                return None
            return float(duration) * float(timecode_scale) / 1_000_000_000.0

        with open(self.path, "rb") as f:
            try:
                file_size = f.seek(0, 2)
                f.seek(0)
            except OSError:
                file_size = 1 << 63

            while f.tell() < file_size:
                el_id, id_len = read_vint(f, for_id=True)
                if id_len == 0:
                    break

                el_size, size_len = read_vint(f, for_id=False)
                if size_len == 0:
                    break

                payload_start = f.tell()
                payload_end = file_size if el_size is None else min(file_size, payload_start + el_size)
                if payload_end < payload_start:
                    break

                if el_id != SEGMENT_ID:
                    f.seek(payload_end)
                    continue

                while f.tell() < payload_end:
                    child_id, child_id_len = read_vint(f, for_id=True)
                    if child_id_len == 0:
                        break

                    child_size, child_size_len = read_vint(f, for_id=False)
                    if child_size_len == 0:
                        break

                    child_payload_start = f.tell()
                    child_end = payload_end if child_size is None else min(payload_end, child_payload_start + child_size)
                    if child_end < child_payload_start:
                        break

                    if child_id == INFO_ID:
                        duration_seconds = read_info_duration(f, child_end)
                        if duration_seconds is not None:
                            return duration_seconds

                    f.seek(child_end)
                break

        raise RuntimeError(f"Cannot parse MKV duration from EBML: {self.path}")

    def add_chapter(self, edit_file: bool):
        with open('chapter.txt', 'r', encoding='utf-8-sig') as f:
            content = f.read()
        if content == 'CHAPTER01=00:00:00.000\nCHAPTER01NAME=Chapter 01':
            print(f'{translate_text("[chapter-debug] ")}{translate_text("skip writing trivial single chapter for: ")}{self.path}')
            return
        if edit_file:
            print(f'{translate_text("[chapter-debug] ")}{translate_text("apply chapter.txt via mkvpropedit -> ")}{self.path}')
            subprocess.Popen(
                rf'"{core_settings.MKV_PROP_EDIT_PATH}" {mkvtoolnix_ui_language_arg()} "{self.path}" --chapters chapter.txt',
                shell=True,
            ).wait()
        else:
            new_path = os.path.join(os.path.dirname(self.path), 'output', os.path.basename(self.path))
            print(f'{translate_text("[chapter-debug] ")}{translate_text("mux with chapter.txt via mkvmerge -> ")}{new_path}')
            subprocess.Popen(
                rf'"{core_settings.MKV_MERGE_PATH}" {mkvtoolnix_ui_language_arg()} --chapters chapter.txt -o "{new_path}" "{self.path}"',
                shell=True,
            ).wait()


__all__ = ["MKV"]
