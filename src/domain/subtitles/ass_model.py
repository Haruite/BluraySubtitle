import _io
import copy
import datetime
import traceback
from functools import reduce

from .event_model import Event
from .style_model import Style


try:
    import _bluraysubtitle_ass as ass_native
except ModuleNotFoundError as error:
    if error.name != '_bluraysubtitle_ass':
        raise
    ass_native = None


_EVENT_BATCH_SIZE = 4096


def event_batches(count, check_cancel):
    for start in range(0, count, _EVENT_BATCH_SIZE):
        if check_cancel:
            check_cancel()
        yield start, min(start + _EVENT_BATCH_SIZE, count)


def _parse_timestamp(value: str) -> datetime.timedelta:
    parts = value.split(':')
    if len(parts) == 3:
        hours, minutes, seconds = map(float, parts)
        return datetime.timedelta(seconds=(hours * 60 + minutes) * 60 + seconds)
    return datetime.timedelta(seconds=reduce(lambda a, b: a * 60 + b, map(float, parts)))


def print_exception_terminal(exc: BaseException) -> None:
    try:
        traceback.print_exception(type(exc), exc, exc.__traceback__)
    except Exception:
        pass


class Ass:
    def __init__(self, fp: _io.TextIOWrapper, *, duration_only: bool = False, check_cancel=None):
        self.script_raw: list[str] = []
        self.garbage_raw: list[str] = []
        self.styles: list[Style] = []
        self.style_attrs: list[str] = []
        self.events: list[Event] = []
        self.event_attrs: list[str] = []
        self.script_type = ''
        self.delete_lines = set()
        maximum_end = None
        section = ''
        event_keys = ()
        time_fields = ()
        timing_split_limit = 0
        native_fields = ()
        native_columns = ()
        native_target = None if duration_only else self.events
        lines = iter(fp)
        line = next(lines, None)
        line_count = 0

        while line is not None:
            if check_cancel and line_count % _EVENT_BATCH_SIZE == 0:
                check_cancel()
            line_count += 1
            if (line.startswith('[') or line.startswith('; [')) and line.endswith(']\n'):
                section = line.lower()
                if 'style' in section:
                    self.script_type = 'v4.00+' if '+' in section else 'v4.00'
            elif line != '\n':
                if 'script' in section:
                    self.script_raw.append(line)
                elif 'garbage' in section:
                    self.garbage_raw.append(line)
                elif 'style' in section:
                    if not line.startswith(';'):
                        try:
                            elements = [attr.strip() for attr in line[line.index(':') + 1:].split(',')]
                            if not self.style_attrs:
                                self.style_attrs += elements
                            else:
                                style = Style()
                                for i, attr in enumerate(elements):
                                    setattr(style, self.style_attrs[i], attr)
                                self.styles.append(style)
                        except Exception as error:
                            print_exception_terminal(error)
                elif 'event' in section:
                    if not line.startswith(';'):
                        try:
                            record_type, fields = line.split(':', 1)
                            if not self.event_attrs:
                                self.event_attrs = [record_type] + [attr.strip() for attr in fields.split(',')]
                                event_keys = tuple(key.lower() for key in self.event_attrs)
                                time_fields = tuple(
                                    (index, key) for index, key in enumerate(event_keys[1:]) if key in ('start', 'end')
                                )
                                if time_fields:
                                    timing_split_limit = min(time_fields[-1][0] + 1, len(self.event_attrs) - 2)
                                if (ass_native and event_keys[0] == 'format' and event_keys[-1] == 'text'
                                        and all(not key.startswith('__') for key in event_keys)
                                        and event_keys.count('text') == 1
                                        and event_keys.count('start') == event_keys.count('end') == 1):
                                    native_fields = tuple(self.event_attrs)
                                    native_columns = event_keys.index('start'), event_keys.index('end')
                            elif duration_only:
                                values = fields.split(',', timing_split_limit)
                                end = None
                                for index, key in time_fields:
                                    timestamp = _parse_timestamp(values[index])
                                    if key == 'end':
                                        end = timestamp
                                if end is not None and (maximum_end is None or end > maximum_end):
                                    maximum_end = end
                            else:
                                event = Event()
                                # Text is the final field; its commas and whitespace are subtitle content.
                                elements = [record_type] + fields.rstrip('\r\n').split(',', len(self.event_attrs) - 2)
                                for i, attr in enumerate(elements):
                                    key = event_keys[i]
                                    if key != 'text':
                                        attr = attr.strip()
                                    if key in ('start', 'end'):
                                        attr = _parse_timestamp(attr)
                                    setattr(event, self.event_attrs[i], attr)
                                self.events.append(event)
                        except Exception as error:
                            print_exception_terminal(error)
                    if native_columns:
                        while True:
                            if check_cancel:
                                check_cancel()
                            line, latest, more = ass_native.parse_events(
                                lines, native_fields, *native_columns, native_target, Event, _EVENT_BATCH_SIZE,
                            )
                            if latest is not None and (maximum_end is None or latest > maximum_end):
                                maximum_end = latest
                            if not more:
                                break
                        continue
            line = next(lines, None)
        if duration_only:
            self.duration = maximum_end.total_seconds() if maximum_end is not None else 0.0

    def clone(self):
        duplicate = copy.copy(self)
        duplicate.script_raw = self.script_raw.copy()
        duplicate.garbage_raw = self.garbage_raw.copy()
        duplicate.styles = copy.deepcopy(self.styles)
        duplicate.style_attrs = self.style_attrs.copy()
        duplicate.events = [Event.copy(event) for event in self.events]
        duplicate.event_attrs = self.event_attrs.copy()
        duplicate.delete_lines = self.delete_lines.copy()
        return duplicate

    def dump_file(self, fp: _io.TextIOWrapper, *, check_cancel=None):
        fp.write('[Script Info]\n')
        fp.write(''.join(self.script_raw))
        if self.garbage_raw:
            fp.write('\n[Aegisub Project Garbage]\n')
            fp.write(''.join(self.garbage_raw))

        fp.write('\n[V4+ Styles]\n' if self.script_type == 'v4.00+' else '\n[V4 Styles]\n')
        fp.write('Format: ' + ', '.join(self.style_attrs) + '\n')
        for style in self.styles:
            fp.write('Style: ' + ','.join(str(getattr(style, attr, '')) for attr in self.style_attrs) + '\n')

        fp.write('\n[Events]\n')
        fp.write(self.event_attrs[0] + ': ' + ', '.join(self.event_attrs[1:]) + '\n')
        event_fields = tuple((key, key.lower() in ('start', 'end')) for key in self.event_attrs[1:])
        if ass_native:
            attributes = tuple(self.event_attrs)
            timing = (False,) + tuple(is_time for _, is_time in event_fields)
            for start, end in event_batches(len(self.events), check_cancel):
                fp.write(ass_native.render_events(self.events, attributes, timing, self.delete_lines, start, end))
            return

        for start, end in event_batches(len(self.events), check_cancel):
            for i in range(start, end):
                if i in self.delete_lines:
                    continue
                event = self.events[i]
                elements = []
                _start = str(getattr(event, self.event_attrs[0], 'Dialogue')) + ': '
                for key, is_time in event_fields:
                    value = str(getattr(event, key, ''))
                    if is_time:
                        d_len = len(value.rsplit(':', 1)[-1])
                        if d_len > 5:
                            value = value[:5 - d_len]
                        elif d_len < 5:
                            value += '.00'
                    elements.append(value)
                fp.write(_start + ','.join(elements) + '\n')


__all__ = ["Ass"]
