import copy
import datetime

from .ass_model import Ass
from .pgs import PGS
from .srt import SRT
from .timecode import parse_hhmmss_ms_to_seconds
from src.exports.utils import get_time_str

class Subtitle:
    def __init__(self, file_path: str):
        self.max_end = 0
        if file_path.endswith('.sup'):
            self.max_end = PGS(file_path).max_end
            return
        try:
            with open(file_path, 'r', encoding='utf-8-sig') as f:
                if file_path.endswith('.srt'):
                    self.content = SRT(f)
                else:
                    self.content = Ass(f)
        except:
            with open(file_path, 'r', encoding='utf-16') as f:
                if file_path.endswith('.srt'):
                    self.content = SRT(f)
                else:
                    self.content = Ass(f)

    @classmethod
    def from_parsed(cls, content, max_end: float = 0):
        obj = cls.__new__(cls)
        obj.max_end = max_end
        if content is not None:
            obj.content = content
        return obj

    def clone(self):
        if hasattr(self, 'content'):
            return Subtitle.from_parsed(copy.deepcopy(self.content), self.max_end)
        return Subtitle.from_parsed(None, self.max_end)

    def append_subtitle(self, other: 'Subtitle', time_shift: float):
        if not hasattr(other, 'content'):
            return
        if not hasattr(self, 'content'):
            self.content = copy.deepcopy(other.content)
            return
        if hasattr(self.content, 'lines'):
            if not hasattr(other.content, 'lines'):
                return
            index = self.content.lines[-1][0] if self.content.lines else 0
            shifted_lines = []
            for line in other.content.lines:
                new_line = [line[0] + index]
                start_time = parse_hhmmss_ms_to_seconds(line[1])
                end_time = parse_hhmmss_ms_to_seconds(line[2])
                new_line.append(get_time_str(start_time + time_shift))
                new_line.append(get_time_str(end_time + time_shift))
                new_line.append(line[3])
                shifted_lines.append(new_line)
            self.content.lines.extend(shifted_lines)
            return

        if hasattr(other.content, 'lines'):
            return

        style_attrs = getattr(self.content, 'style_attrs', None)
        if not style_attrs:
            self.content.styles.extend(copy.deepcopy(other.content.styles))
            self.content.events.extend(copy.deepcopy(other.content.events))
            return

        def style_key(style) -> tuple:
            return tuple(getattr(style, attr, '') for attr in style_attrs)

        existing_style_keys = {style_key(s): s for s in self.content.styles}
        existing_names = {getattr(s, 'Name', '') for s in self.content.styles}
        style_name_map = {}

        for style in other.content.styles:
            k = style_key(style)
            if k in existing_style_keys:
                continue
            style_copy = copy.deepcopy(style)
            old_name = getattr(style_copy, 'Name', '')
            new_name = old_name
            while new_name in existing_names:
                new_name += '1'
                setattr(style_copy, 'Name', new_name)
                k = style_key(style_copy)
                if k in existing_style_keys:
                    new_name = ''
                    break
            if not new_name:
                continue
            style_name_map[old_name] = new_name
            existing_names.add(new_name)
            existing_style_keys[k] = style_copy
            self.content.styles.append(style_copy)

        delta = datetime.timedelta(seconds=time_shift)
        for event in other.content.events:
            event_copy = copy.deepcopy(event)
            event_copy.Start += delta
            event_copy.End += delta
            if event_copy.Style in style_name_map:
                event_copy.Style = style_name_map[event_copy.Style]
            self.content.events.append(event_copy)

    def append_ass(self, new_file_path: str, time_shift: float):
        try:
            with open(new_file_path, 'r', encoding='utf-8-sig') as f:
                if new_file_path.endswith('.srt'):
                    new_content = SRT(f)
                else:
                    new_content = Ass(f)
        except:
            with open(new_file_path, 'r', encoding='utf-16') as f:
                if new_file_path.endswith('.srt'):
                    new_content = SRT(f)
                else:
                    new_content = Ass(f)
        self.append_subtitle(Subtitle.from_parsed(new_content), time_shift)

    def dump(self, file_path: str, selected_mpls: str):
        if hasattr(self.content, 'lines'):
            with open(file_path + '.srt', "w", encoding='utf-8-sig') as f:
                self.content.dump_file(f)
            with open(selected_mpls + '.srt', "w", encoding='utf-8-sig') as f:
                self.content.dump_file(f)
        elif self.content.script_type == 'v4.00+':
            with open(file_path + '.ass', "w", encoding='utf-8-sig') as f:
                self.content.dump_file(f)
            with open(selected_mpls + '.ass', "w", encoding='utf-8-sig') as f:
                self.content.dump_file(f)
        else:
            with open(file_path + '.ssa', "w", encoding='utf-8-sig') as f:
                self.content.dump_file(f)
            with open(selected_mpls + '.ssa', "w", encoding='utf-8-sig') as f:
                self.content.dump_file(f)

    def max_end_time(self):
        try:
            if hasattr(self, 'content') and hasattr(self.content, 'lines'):
                return max(map(lambda line: parse_hhmmss_ms_to_seconds(line[2]), self.content.lines)) if self.content.lines else 0
            if self.max_end:
                return self.max_end
            if hasattr(self, 'content') and hasattr(self.content, 'events') and self.content.events:
                end_set = set(map(lambda event: event.End.total_seconds(), self.content.events))
                if not end_set:
                    return 0
                max_end = max(end_set)
                end_set.remove(max_end)
                if end_set:  # ensure there are still candidate end times
                    max_end_1 = max(end_set)
                    if max_end_1 < max_end - 300:
                        return max_end_1  # cap abnormally long events (e.g., commentary stream exceeding episode end)
                return max_end
            return 0
        except Exception as e:
            print(f'Failed to get subtitle duration: {str(e)}')
            return 0


__all__ = ["Subtitle"]
