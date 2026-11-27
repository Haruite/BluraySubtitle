import copy
import datetime
import io
import os
from contextlib import ExitStack

from . import ass_model
from .ass_model import Ass, event_batches
from .event_model import Event
from .pgs import PGS
from .srt import SRT
from .timecode import format_srt_timestamp, parse_hhmmss_ms_to_seconds
from src.core.i18n import translate_text


ASS_EXTENSIONS = ('.ass', '.ssa')
SUBTITLE_EXTENSIONS = ASS_EXTENSIONS + ('.srt', '.sup')


def _read_text_subtitle(file_path, parse, data=None):
    def read(encoding):
        stream = (open(file_path, 'r', encoding=encoding) if data is None else
                  io.TextIOWrapper(io.BytesIO(data), encoding=encoding))
        with stream:
            return parse(stream)

    try:
        return read('utf-8-sig')
    except UnicodeDecodeError:
        return read('utf-16')


class _SubtitleOutputs:
    def __init__(self, files):
        self.files = files

    def write(self, data):
        for file in self.files:
            file.write(data)


def list_subtitle_files(folder: str) -> list[str]:
    with os.scandir(folder) as entries:
        return sorted(
            os.path.normpath(entry.path)
            for entry in entries
            if entry.is_file() and entry.name.lower().endswith(SUBTITLE_EXTENSIONS)
        )


class Subtitle:
    def __init__(self, file_path: str, *, check_cancel=None):
        self.max_end = 0
        file_extension = file_path.lower()
        if file_extension.endswith('.sup'):
            self.content = PGS(file_path)
            self.max_end = self.content.max_end
            return
        if file_extension.endswith('.srt'):
            self.content = _read_text_subtitle(file_path, SRT)
            return
        data = None
        if ass_model.ass_native:
            # Read one file in bulk so TextIOWrapper's small reads stay in memory.
            with open(file_path, 'rb') as stream:
                data = stream.read()
        self.content = _read_text_subtitle(file_path, lambda stream: Ass(stream, check_cancel=check_cancel), data)

    @classmethod
    def read_duration(cls, file_path: str, *, check_cancel=None) -> float:
        file_extension = file_path.lower()
        if file_extension.endswith(ASS_EXTENSIONS):
            data = None
            if ass_model.ass_native:
                with open(file_path, 'rb') as stream:
                    data = stream.read()
                duration = ass_model.ass_native.scan_duration(data)
                if check_cancel:
                    check_cancel()
                if duration is not None:
                    return duration
            return _read_text_subtitle(
                file_path, lambda stream: Ass(stream, duration_only=True, check_cancel=check_cancel).duration, data,
            )
        if file_extension.endswith('.sup'):
            return PGS.read_duration(file_path)
        return cls(file_path).max_end_time()

    @classmethod
    def from_parsed(cls, content, max_end: float = 0):
        obj = cls.__new__(cls)
        obj.max_end = max_end
        if content is not None:
            obj.content = content
        return obj

    def clone(self):
        content = getattr(self, 'content', None)
        if isinstance(content, Ass):
            duplicate = content.clone()
        elif isinstance(content, PGS):
            duplicate = copy.copy(content)
        else:
            duplicate = copy.deepcopy(content)
        return Subtitle.from_parsed(duplicate, self.max_end)

    def shift(self, time_shift: float, *, check_cancel=None):
        if not time_shift or not hasattr(self, 'content'):
            return self
        if hasattr(self.content, 'lines'):
            for line in self.content.lines:
                line[1] = format_srt_timestamp(parse_hhmmss_ms_to_seconds(line[1]) + time_shift)
                line[2] = format_srt_timestamp(parse_hhmmss_ms_to_seconds(line[2]) + time_shift)
            return self
        if isinstance(self.content, PGS):
            self.content.shift(time_shift)
            self.max_end = self.content.max_end
            return self
        delta = datetime.timedelta(seconds=time_shift)
        events = self.content.events
        if ass_model.ass_native and isinstance(self.content, Ass):
            for start, end in event_batches(len(events), check_cancel):
                ass_model.ass_native.shift_events(events, delta, 'Start', 'End', start, end)
        else:
            for event in events:
                event.Start += delta
                event.End += delta
        return self

    def append_subtitle(self, other: 'Subtitle', time_shift: float, *, check_cancel=None):
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
                new_line.append(format_srt_timestamp(start_time + time_shift))
                new_line.append(format_srt_timestamp(end_time + time_shift))
                new_line.append(line[3])
                shifted_lines.append(new_line)
            self.content.lines.extend(shifted_lines)
            return

        if hasattr(other.content, 'lines'):
            return

        if isinstance(self.content, PGS):
            if isinstance(other.content, PGS):
                self.content.append_pgs(other.content, time_shift)
                self.max_end = self.content.max_end
            return
        if isinstance(other.content, PGS):
            return

        if not getattr(self.content, 'style_attrs', None) and getattr(other.content, 'style_attrs', None):
            self.content.style_attrs = copy.deepcopy(other.content.style_attrs)
        if not getattr(self.content, 'event_attrs', None) and getattr(other.content, 'event_attrs', None):
            self.content.event_attrs = copy.deepcopy(other.content.event_attrs)
        style_attrs = getattr(self.content, 'style_attrs', None)

        def style_key(style) -> tuple:
            return tuple(getattr(style, attr, '') for attr in style_attrs)

        style_name_map = {}
        if style_attrs:
            existing_style_keys = {style_key(s): s for s in self.content.styles}
            existing_names = {getattr(s, 'Name', '') for s in self.content.styles}
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
                        style_name_map[old_name] = new_name
                        new_name = ''
                        break
                if not new_name:
                    continue
                style_name_map[old_name] = new_name
                existing_names.add(new_name)
                existing_style_keys[k] = style_copy
                self.content.styles.append(style_copy)
        else:
            self.content.styles.extend(copy.deepcopy(other.content.styles))

        delta = datetime.timedelta(seconds=time_shift)
        events = other.content.events
        if ass_model.ass_native and isinstance(self.content, Ass) and isinstance(other.content, Ass):
            for start, end in event_batches(len(events), check_cancel):
                ass_model.ass_native.append_events(
                    self.content.events, events, delta, style_name_map, Event, 'Start', 'End', 'Style', start, end,
                )
        else:
            for event in events:
                event_copy = Event.copy(event)
                event_copy.Start += delta
                event_copy.End += delta
                if event_copy.Style in style_name_map:
                    event_copy.Style = style_name_map[event_copy.Style]
                self.content.events.append(event_copy)

    def output_extension(self) -> str:
        if hasattr(self.content, 'lines'):
            return '.srt'
        if isinstance(self.content, PGS):
            return '.sup'
        if getattr(self.content, 'script_type', '') == 'v4.00+':
            return '.ass'
        if getattr(self.content, 'script_type', ''):
            return '.ssa'
        raise ValueError(translate_text('Unsupported subtitle content'))

    def dump(self, file_path: str, selected_mpls: str | None = None, *, check_cancel=None):
        extension = self.output_extension()
        created_paths = []
        try:
            output_bases = (file_path, selected_mpls) if selected_mpls is not None else (file_path,)
            with ExitStack() as stack:
                files = []
                for base in output_bases:
                    output_path = base + extension
                    file = (open(output_path, 'xb') if extension == '.sup' else
                            open(output_path, 'x', encoding='utf-8-sig'))
                    created_paths.append(output_path)
                    files.append(stack.enter_context(file))
                output = files[0] if len(files) == 1 else _SubtitleOutputs(files)
                if isinstance(self.content, Ass):
                    self.content.dump_file(output, check_cancel=check_cancel)
                else:
                    self.content.dump_file(output)
        except Exception:
            for output_path in reversed(created_paths):
                try:
                    os.remove(output_path)
                except OSError:
                    pass
            raise

    def max_end_time(self) -> float:
        if not hasattr(self, 'content'):
            return 0.0
        if hasattr(self.content, 'lines'):
            return max(
                (parse_hhmmss_ms_to_seconds(line[2]) for line in self.content.lines),
                default=0.0,
            )
        if isinstance(self.content, PGS):
            return self.max_end
        return max((event.End.total_seconds() for event in self.content.events), default=0.0)


__all__ = ["ASS_EXTENSIONS", "SUBTITLE_EXTENSIONS", "Subtitle", "list_subtitle_files"]
