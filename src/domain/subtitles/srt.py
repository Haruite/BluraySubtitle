import _io
import re

from .timecode import parse_hhmmss_ms_to_seconds
from src.exports.utils import get_time_str


class SRT:
    def __init__(self, fp: _io.TextIOWrapper):
        self.raw = fp.read()
        self.delete_lines = set()
        self.lines = []
        added = True
        for line in self.raw.split('\n'):
            if re.match(r'^(\d+)$', line) and added:
                new_line = [int(line)]
                added = False
            elif (re.match(r'^(\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3})$', line)
                    or re.match(r'^(\d{2}:\d{2}:\d{2}.\d{3} --> \d{2}:\d{2}:\d{2}.\d{3})$', line)):
                new_line.append(line[0: 12])
                new_line.append(line[17: 29])
            elif line.strip():
                if len(new_line) == 3:
                    new_line.append(line)
                else:
                    new_line[3] += '\n' + line
            else:
                if not added:
                    self.lines.append(new_line)
                    added = True

    def dump_file(self, fp: _io.TextIOWrapper):
        for line in self.lines:
            if line[0] not in self.delete_lines:
                fp.write(str(line[0]) + '\n')
                fp.write(f'{line[1]} --> {line[2]}\n')
                fp.write(line[3] + '\n\n')

    def append_srt(self, other: 'SRT', shift_time: float):
        if not hasattr(other, 'lines') or not other.lines:
            return self

        index = self.lines[-1][0] if self.lines else 0
        for line in other.lines:
            start_time = parse_hhmmss_ms_to_seconds(line[1])
            end_time = parse_hhmmss_ms_to_seconds(line[2])
            self.lines.append([
                line[0] + index,
                get_time_str(start_time + shift_time),
                get_time_str(end_time + shift_time),
                line[3]
            ])
        return self

    def cut_srt(self, start_time: float, end_time: float):
        cut_lines = []
        for line in self.lines:
            line_start = parse_hhmmss_ms_to_seconds(line[1])
            line_end = parse_hhmmss_ms_to_seconds(line[2])
            if line_start < start_time or line_end > end_time:
                continue
            cut_lines.append([
                len(cut_lines) + 1,
                get_time_str(line_start - start_time),
                get_time_str(line_end - start_time),
                line[3],
            ])
        self.lines = cut_lines
        return self


__all__ = ["SRT"]
