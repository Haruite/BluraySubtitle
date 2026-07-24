import os
from struct import unpack

from src.core import find_mkvtoolnix, get_mkvtoolnix_ui_language
from src.core import settings as core_settings
from src.core.i18n import translate_text
from src.exports.utils import run_command


class MKV:
    def __init__(self, path: str):
        self.path = path
        find_mkvtoolnix()

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


        def parse_float(buf: bytes):
            if len(buf) == 4:
                return unpack(">f", buf)[0]
            if len(buf) == 8:
                return unpack(">d", buf)[0]
            return None


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
                    timecode_scale = (int.from_bytes(payload, "big", signed=False) if payload else 0) or DEFAULT_TIMECODE_SCALE
                elif el_id == DURATION_ID:
                    payload = f.read(payload_len)
                    duration = parse_float(payload)

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

    def add_chapter(
            self,
            edit_file: bool,
            chapter_path: str = 'chapter.txt',
            output_path: str | None = None,
    ) -> None:
        with open(chapter_path, 'r', encoding='utf-8-sig') as chapter_file:
            chapter_text = chapter_file.read()
        normalized_text = chapter_text.replace('\r\n', '\n').strip()
        trivial_chapter = 'CHAPTER01=00:00:00.000\nCHAPTER01NAME=Chapter 01'
        has_meaningful_chapters = bool(normalized_text) and normalized_text != trivial_chapter

        ui_language = get_mkvtoolnix_ui_language()
        if edit_file:
            if not has_meaningful_chapters:
                return
            executable = core_settings.MKV_PROP_EDIT_PATH
            if not executable or not os.path.isfile(executable):
                raise FileNotFoundError(translate_text('mkvpropedit not found'))
            command = [
                executable,
                '--ui-language', ui_language,
                self.path,
                '--chapters', chapter_path,
            ]
            failed_message = translate_text('mkvpropedit failed for: {path}').format(path=self.path)
            failed_output = None
        else:
            executable = core_settings.MKV_MERGE_PATH
            if not executable or not os.path.isfile(executable):
                raise FileNotFoundError(translate_text('mkvmerge not found'))
            new_path = output_path or os.path.join(
                os.path.dirname(self.path), 'output', os.path.basename(self.path)
            )
            if os.path.exists(new_path):
                raise FileExistsError(
                    translate_text('Output file already exists: {path}').format(path=new_path)
                )
            output_directory = os.path.dirname(new_path)
            if output_directory:
                os.makedirs(output_directory, exist_ok=True)
            command = [executable, '--ui-language', ui_language]
            if has_meaningful_chapters:
                command.extend(['--chapters', chapter_path])
            command.extend(['-o', new_path, self.path])
            failed_message = translate_text('mkvmerge failed for: {path}').format(path=self.path)
            failed_output = new_path

        result = run_command(command)
        if result.returncode in (0, 1):
            return
        if failed_output and os.path.exists(failed_output):
            try:
                os.remove(failed_output)
            except OSError:
                pass
        raise RuntimeError(failed_message)


__all__ = ["MKV"]
