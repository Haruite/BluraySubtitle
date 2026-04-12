# 功能1：生成合并字幕
# 功能2：给mkv添加章节
# 功能3：原盘remux
# 功能23需要安装mkvtoolnix，指定FLAC_PATH和FLAC_THREADS(flac版本需大于等于1.5.0)
# 功能3需要指定FFMPEG_PATH和FFPROBE_PATH
# pip install pycountry PyQt6 librosa
import _io
import copy
import ctypes
import datetime
import json
import multiprocessing
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import traceback
import xml.etree.ElementTree as et
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from functools import reduce, partial
from struct import unpack
from typing import Optional, Generator, Callable

import librosa
import librosa.feature
import numpy as np
import pycountry
try:
    import soundfile
except Exception:
    soundfile = None
from PyQt6.QtCore import QCoreApplication, Qt, QPoint, QObject, QThread, QTimer, QEventLoop, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QDragMoveEvent, QDropEvent, QPaintEvent, QDragEnterEvent
from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QFileDialog, QLabel, QToolButton, QLineEdit, \
    QMessageBox, QHBoxLayout, QGroupBox, QCheckBox, QProgressDialog, QRadioButton, QButtonGroup, \
    QTableWidget, QTableWidgetItem, QDialog, QPushButton, QComboBox, QMenu, QAbstractItemView, QPlainTextEdit

if sys.platform == 'win32':
    import winreg


FLAC_PATH = r'C:\Downloads\flac-1.5.0-win\Win64\flac.exe'  # flac可执行文件路径
FLAC_THREADS = 20  # flac线程数
FFMPEG_PATH = r'C:\Downloads\ffmpeg-8.1-full_build\bin\ffmpeg.exe'  # ffmpeg可执行文件路径
FFPROBE_PATH = r'C:\Downloads\ffmpeg-8.1-full_build\bin\ffprobe.exe'  # ffprobe可执行文件路径
X265_PATH = r'C:\Software\x265.exe'  # x265可执行文件路径
PLUGIN_PATH = ''


def is_docker():
    path = '/proc/self/cgroup'
    return (
            os.path.exists('/.dockerenv') or
            os.path.isfile(path) and any('docker' in line for line in open(path))
    )


if is_docker():
    FLAC_PATH = '/usr/bin/flac'  # flac可执行文件路径
    FFMPEG_PATH = '/usr/bin/ffmpeg'  # ffmpeg可执行文件路径
    FFPROBE_PATH = '/usr/bin/ffprobe'  # ffprobe可执行文件路径
    X265_PATH = '/usr/bin/x265'  # x265可执行文件路径
    PLUGIN_PATH = '/app/plugins'


MKV_INFO_PATH = ''
MKV_MERGE_PATH = ''
MKV_PROP_EDIT_PATH = ''
MKV_EXTRACT_PATH = ''
BDMV_LABELS = ['path', 'size', 'info']
SUBTITLE_LABELS = ['select', 'path', 'sub_duration', 'bdmv_index', 'chapter_index', 'offset']
MKV_LABELS = ['path', 'duration']
REMUX_LABELS = ['sub_path', 'ep_duration', 'bdmv_index', 'chapter_index', 'm2ts_file']
ENCODE_LABELS = ['sub_path', 'ep_duration', 'bdmv_index', 'chapter_index', 'm2ts_file', 'vpy_path', 'edit_vpy']
ENCODE_SP_LABELS = ['bdmv_index', 'mpls_file', 'm2ts_file', 'duration', 'vpy_path', 'edit_vpy']
CONFIGURATION = {}


class Chapter:
    formats: dict[int, str] = {1: '>B', 2: '>H', 4: '>I', 8: '>Q'}

    def __init__(self, file_path: str):
        # 参考 https://github.com/lw/BluRay/wiki/PlayItem

        # in_out_time 是一个列表，列表的每一项是一个元组，按照播放对应的顺序
        # 元组第一位为文件名，第二位是 in_time，第三位是 out_time
        # 对应 m2ts 文件的播放时长为 (out_time - in_time) / 45000
        self.in_out_time: list[tuple[str, int, int]] = []

        # mark_info 是一个字典
        # 字典的键 ref_to_play_item_id 对应 in_out_time 的索引
        # 字典的值为由章节标记对应的时间戳 mark_timestamp 组成的列表
        # 那么时间戳对应在 mpls 的播放时间为 (mark_timestamp - in_time) / 45000
        # + (0 ~ ref_to_play_item_id 所有文件对应的播放时长之和)
        # 举个例子 (来自 BanG Dream! It's MyGO!!!!! 原盘上卷)
        # in_out_time = [('00000', 1647000000, 1711414350), ('00001', 1647000000, 1710963900), ...]
        # mark_info = {0: [1647000000, 1655188805, 1689886593, 1706626441, 1710676738],
        # 1: [1647000000, 1649522520, 1653570939, 1685023610, 1706174115, 1710224411], ...}
        # mark_info 键 1 对应的时间戳列表中的 1649522520 对应的播放时间计算如下：
        # 首先 ref_to_play_item_id 为 1，对应 in_out_time 中索引为 1 的项，即 ('00001', 1647000000, 1710963900)
        # 由此可知 1649522520 这个时间戳相对文件开始的 in_time 的时间差为 (1649522520 - 1647000000) / 45000 = 56.056 秒
        # 文件索引为 1，那么前面有一个文件，其播放时长为 (1711414350 - 1647000000) / 45000 = 1431.43 秒
        # 所以 1649522520 这个时间戳在整个播放列表中的时间位置为 1431.43 + 56.056 = 1487.486 秒 即 24:47.486
        self.mark_info: dict[int, list[int]] = {}
        self.file_path: str = file_path
        self.pid_to_lang = {}

        with open(file_path, 'rb') as self.mpls_file:
            self.mpls_file.seek(8)
            playlist_start_address = self._unpack_byte(4)
            playlist_mark_start_address = self._unpack_byte(4)

            self.mpls_file.seek(playlist_start_address)
            self.mpls_file.read(6)
            nb_play_items = self._unpack_byte(2)
            self.mpls_file.read(2)
            for _ in range(nb_play_items):
                pos = self.mpls_file.tell()
                length = self._unpack_byte(2)
                if length != 0:
                    clip_information_filename = self.mpls_file.read(5).decode()
                    self.mpls_file.read(7)
                    in_time = self._unpack_byte(4)
                    out_time = self._unpack_byte(4)
                    self.in_out_time.append((clip_information_filename, in_time, out_time))
                self.mpls_file.seek(pos + length + 2)

            self.mpls_file.seek(playlist_mark_start_address)
            self.mpls_file.read(4)
            nb_playlist_marks = self._unpack_byte(2)
            for _ in range(nb_playlist_marks):
                self.mpls_file.read(2)
                ref_to_play_item_id = self._unpack_byte(2)
                mark_timestamp = self._unpack_byte(4)
                self.mpls_file.read(6)
                if ref_to_play_item_id in self.mark_info:
                    self.mark_info[ref_to_play_item_id].append(mark_timestamp)
                else:
                    self.mark_info[ref_to_play_item_id] = [mark_timestamp]

    def _unpack_byte(self, n: int):
        return unpack(self.formats[n], self.mpls_file.read(n))[0]

    def get_total_time(self):  # 获取播放列表的总时长
        return sum(map(lambda x: (x[2] - x[1]) / 45000, self.in_out_time))

    def get_total_time_no_repeat(self):  # 获取播放列表中时长，重复播放同一文件只计算一次
        return sum({x[0]: (x[2] - x[1]) / 45000 for x in self.in_out_time}.values())

    def get_pid_to_language(self):
        with open(self.file_path, 'rb') as self.mpls_file:
            self.mpls_file.seek(8)
            playlist_start_address = self._unpack_byte(4)
            self.mpls_file.seek(playlist_start_address)
            self.mpls_file.read(6)
            nb_of_play_items = self._unpack_byte(2)
            self.mpls_file.read(2)
            for _ in range(nb_of_play_items):
                self.mpls_file.read(12)
                is_multi_angle = (self._unpack_byte(1) >> 4) % 2
                self.mpls_file.read(21)
                if is_multi_angle:
                    nb_of_angles = self._unpack_byte(1)
                    self.mpls_file.read(1)
                    for _ in range(nb_of_angles - 1):
                        self.mpls_file.read(10)
                self.mpls_file.read(4)
                nb = []
                for _ in range(8):
                    nb.append(self._unpack_byte(1))
                self.mpls_file.read(4)
                for _ in range(sum(nb)):
                    stream_entry_length = self._unpack_byte(1)
                    stream_type = self._unpack_byte(1)
                    if stream_type == 1:
                        stream_pid = self._unpack_byte(2)
                        self.mpls_file.read(stream_entry_length - 3)
                    elif stream_type == 2:
                        self.mpls_file.read(2)
                        stream_pid = self._unpack_byte(2)
                        self.mpls_file.read(stream_entry_length - 5)
                    elif stream_type == 3 or stream_type == 4:
                        self.mpls_file.read(1)
                        stream_pid = self._unpack_byte(2)
                        self.mpls_file.read(stream_entry_length - 4)
                    stream_attributes_length = self._unpack_byte(1)
                    stream_coding_type = self._unpack_byte(1)
                    if stream_coding_type in (1, 2, 27, 36, 234):
                        self.pid_to_lang[stream_pid] = 'und'
                        self.mpls_file.read(stream_attributes_length - 1)
                    elif stream_coding_type in (3, 4, 128, 129, 130, 131, 132, 133, 134, 146, 161, 162):
                        self.mpls_file.read(1)
                        self.pid_to_lang[stream_pid] = self.mpls_file.read(3).decode()
                        self.mpls_file.read(stream_attributes_length - 5)
                    elif stream_coding_type in (144, 145):
                        self.pid_to_lang[stream_pid] = self.mpls_file.read(3).decode()
                        self.mpls_file.read(stream_attributes_length - 4)
                break


@dataclass
class Style:
    def __repr__(self):
        return str(self.__dict__)


@dataclass
class Event:
    def __repr__(self):
        return str(self.__dict__)


class Ass:
    def __init__(self, fp: _io.TextIOWrapper):
        self.script_raw: list[str] = []
        self.garbage_raw: list[str] = []
        self.styles: list[Style] = []
        self.style_attrs: list[str] = []
        self.events: list[Event] = []
        self.event_attrs: list[str] = []
        self.script_type = ''
        self.delete_lines = set()

        for line in fp:
            if (line.startswith('[') or line.startswith('; [')) and line.endswith(']\n'):
                section_title = line
                if 'style' in section_title.lower():
                    self.script_type = 'v4.00+' if '+' in section_title else 'v4.00'
            elif line != '\n':
                if 'script' in section_title.lower():
                    self.script_raw.append(line)
                elif 'garbage' in section_title.lower():
                    self.garbage_raw.append(line)
                elif 'style' in section_title.lower():
                    if line.startswith(';'):
                        continue
                    try:
                        elements = list(map(lambda _attr: _attr.strip(), line[line.index(":") + 1:].split(',')))
                        if not self.style_attrs:
                            self.style_attrs += elements
                        else:
                            style = Style()
                            for i, attr in enumerate(elements):
                                setattr(style, self.style_attrs[i], attr)
                            self.styles.append(style)
                    except Exception as e:
                        traceback.print_exception(e)
                elif 'event' in section_title.lower():
                    if line.startswith(';'):
                        continue
                    try:  # 每一行解析都加 try，防止个别行格式错误导致整个合并失败
                        elements = ([line[:line.index(':')]]
                                    + list(map(lambda _attr: _attr.strip(), line[line.index(':') + 1:].split(','))))
                        if not self.event_attrs:
                            self.event_attrs += elements
                        else:
                            event = Event()
                            if len(elements) > len(self.event_attrs):  # 字幕内容中包含 ','
                                elements = (elements[:len(self.event_attrs) - 1] +
                                            [','.join(elements[len(self.event_attrs) - 1:])])
                            for i, attr in enumerate(elements):
                                key = self.event_attrs[i]
                                if key.lower() in ('start', 'end'):  # 将 Start 和 End 两个时间字符串转换为 timedelta 格式
                                    attr = datetime.timedelta(
                                        seconds=reduce(lambda a, b: a * 60 + b, map(float, attr.split(':'))))
                                setattr(event, self.event_attrs[i], attr)
                            self.events.append(event)
                    except Exception as e:
                        traceback.print_exception(e)

    def dump_file(self, fp: _io.TextIOWrapper):
        fp.write('[Script Info]\n')
        fp.write(''.join(self.script_raw))
        if self.garbage_raw:
            fp.write('\n[Aegisub Project Garbage]\n')
            fp.write(''.join(self.garbage_raw))

        fp.write('\n[V4+ Styles]\n' if self.script_type == 'v4.00+' else '\n[V4 Styles]\n')
        fp.write('Format: ' + ', '.join(self.style_attrs) + '\n')
        for style in self.styles:
            fp.write('Style: ' + ','.join(style.__dict__.values()) + '\n')

        fp.write('\n[Events]\n')
        fp.write(self.event_attrs[0] + ': ' + ', '.join(self.event_attrs[1:]) + '\n')
        for i, event in enumerate(self.events):
            if i in self.delete_lines:
                continue
            elements = []
            values = list(event.__dict__.values())
            keys = list(event.__dict__.keys())
            for j, value in enumerate(values):
                if j == 0:
                    _start = value + ': '
                else:
                    if keys[j].lower() in ('start', 'end'):
                        d_len = len(str(value).split(':')[-1])
                        if d_len > 5:
                            elements.append(str(value)[:5 - d_len])
                        elif d_len == 5:
                            elements.append(str(value))
                        else:
                            elements.append(str(value) + '.00')
                    else:
                        elements.append(value)
            fp.write(_start + ','.join(elements) + '\n')


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


class PGS:
    def __init__(self, path):
        self.formats: dict[int, str] = {1: '>B', 2: '>H', 4: '>I', 8: '>Q'}
        with open(path, 'rb') as self.bytes:
            end_set = set(self.iter_timestamp())
            max_end = max(end_set)
            end_set.remove(max_end)
            max_end_1 = max(end_set)
            if max_end_1 < max_end - 300:
                self.max_end = max_end_1
            else:
                self.max_end = max_end

    def iter_timestamp(self):
        while True:
            if self.bytes.read(2) != b'PG':
                break
            presentation_timestamp = self._unpack_byte(4) / 90000
            self.bytes.read(5)
            segment_size = self._unpack_byte(2)
            self.bytes.read(segment_size)
            if presentation_timestamp < 18000:
                yield presentation_timestamp

    def _unpack_byte(self, n: int):
        return unpack(self.formats[n], self.bytes.read(n))[0]


def _parse_hhmmss_ms_to_seconds(ts: str) -> float:
    try:
        ts = ts.strip()
        if len(ts) < 12:
            return 0.0
        h = int(ts[0:2])
        m = int(ts[3:5])
        s = int(ts[6:8])
        ms = int(ts[9:12])
        return h * 3600 + m * 60 + s + ms / 1000
    except (ValueError, IndexError):
        return 0.0


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
                start_time = _parse_hhmmss_ms_to_seconds(line[1])
                end_time = _parse_hhmmss_ms_to_seconds(line[2])
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
                return max(map(lambda line: _parse_hhmmss_ms_to_seconds(line[2]), self.content.lines)) if self.content.lines else 0
            if self.max_end:
                return self.max_end
            if hasattr(self, 'content') and hasattr(self.content, 'events') and self.content.events:
                end_set = set(map(lambda event: event.End.total_seconds(), self.content.events))
                if not end_set:
                    return 0
                max_end = max(end_set)
                end_set.remove(max_end)
                if end_set:  # 确保还有其他元素
                    max_end_1 = max(end_set)
                    if max_end_1 < max_end - 300:
                        return max_end_1  # 防止个别 Event 结束时间超长(比如评论音轨超出那一集的结束时间)
                return max_end
            return 0
        except Exception as e:
            print(f'获取字幕时长失败: {str(e)}')
            return 0


def _parse_subtitle_worker(file_path: str) -> tuple[str, Subtitle | None]:
    try:
        return file_path, Subtitle(file_path)
    except Exception as e:
        print(f'字幕文件 ｢{file_path}｣ 解析失败: {str(e)}')
        return file_path, None


class ISO:
    def __init__(self, path: str):
        self.path = ctypes.c_wchar_p(path)

        # https://learn.microsoft.com/en-us/windows/win32/api/guiddef/ns-guiddef-guid
        class GUID(ctypes.Structure):
            _fields_ = (
                ("Data1", ctypes.c_ulong),
                ("Data2", ctypes.c_ushort),
                ("Data3", ctypes.c_ushort),
                ("Data4", ctypes.c_ubyte * 8),
            )

        # https://learn.microsoft.com/en-us/windows/win32/api/virtdisk/ns-virtdisk-virtual_storage_type
        class VIRTUAL_STORAGE_TYPE(ctypes.Structure):
            _fields_ = (
                ("DeviceId", ctypes.c_ulong),
                ("VendorId", GUID),
            )

        VIRTUAL_STORAGE_TYPE_VENDOR_MICROSOFT = GUID(
            0xEC984AEC, 0xA0F9, 0x47E9, (0x90, 0x1F, 0x71, 0x41, 0x5A, 0x66, 0x34, 0x5B)
        )
        self.virtual_storage_type = VIRTUAL_STORAGE_TYPE(1, VIRTUAL_STORAGE_TYPE_VENDOR_MICROSOFT)
        self.handle = ctypes.c_void_p()

    def open(self):
        # https://learn.microsoft.com/en-us/windows/win32/api/virtdisk/nf-virtdisk-openvirtualdisk
        ctypes.windll.virtdisk.OpenVirtualDisk(
            ctypes.byref(self.virtual_storage_type),
            self.path,
            0x000d0000,
            0x00000000,
            None,
            ctypes.byref(self.handle)
        )

    def mount(self):
        self.open()
        # https://learn.microsoft.com/en-us/windows/win32/api/virtdisk/nf-virtdisk-attachvirtualdisk
        ctypes.windll.virtdisk.AttachVirtualDisk(
            self.handle,
            None,
            0x00000001,
            0,
            None,
            None
        )

    def close(self):
        # https://learn.microsoft.com/en-us/windows/win32/api/handleapi/nf-handleapi-closehandle
        ctypes.windll.kernel32.CloseHandle(self.handle)


class MKV:
    def __init__(self, path: str):
        self.path = path
        find_mkvtoolinx()

    def get_duration(self):
        subprocess.Popen(rf'"{MKV_INFO_PATH}" "{self.path}" -r mkvinfo.txt --ui-language en_US', shell=True).wait()
        pattern = '| + Duration: '
        duration = 0
        with open('mkvinfo.txt', 'r', encoding='utf-8-sig') as f:
            for line in f:
                if line[:len(pattern)] == pattern:
                    time_str = line[len(pattern):]
                    duration = int(time_str[:2]) * 3600 + int(time_str[3:5]) * 60 + float(time_str[6:])
        if duration == 0:
            subprocess.Popen(rf'"{MKV_INFO_PATH}" "{self.path}" -r mkvinfo.txt --ui-language en', shell=True).wait()
            pattern = '| + Duration: '
            with open('mkvinfo.txt', 'r', encoding='utf-8-sig') as f:
                for line in f:
                    if line[:len(pattern)] == pattern:
                        time_str = line[len(pattern):]
                        duration = int(time_str[:2]) * 3600 + int(time_str[3:5]) * 60 + float(time_str[6:])
        return duration

    def add_chapter(self, edit_file: bool):
        with open('chapter.txt', 'r', encoding='utf-8-sig') as f:
            content = f.read()
        if content == 'CHAPTER01=00:00:00.000\nCHAPTER01NAME=Chapter 01':
            return
        if edit_file:
            subprocess.Popen(rf'"{MKV_PROP_EDIT_PATH}" "{self.path}" --chapters chapter.txt', shell=True).wait()
        else:
            new_path = os.path.join(os.path.dirname(self.path), 'output', os.path.basename(self.path))
            subprocess.Popen(rf'"{MKV_MERGE_PATH}" --chapters chapter.txt -o "{new_path}" "{self.path}"', shell=True).wait()


class M2TS:
    def __init__(self, filename: str):
        self.filename = filename
        self.frame_size = 192

    def get_duration(self) -> int:
        with open(self.filename, "rb") as self.m2ts_file:
            try:
                buffer_size = 256 * 1024
                buffer_size -= buffer_size % self.frame_size
                cur_pos = 0
                first_pcr_val = -1
                while cur_pos < buffer_size:
                    self.m2ts_file.read(7)
                    first_pcr_val = self.get_pcr_val()
                    self.m2ts_file.read(182)
                    if first_pcr_val != -1:
                        break

                buffer_size = 256 * 1024
                buffer_size -= buffer_size % self.frame_size
                last_pcr_val = self.get_last_pcr_val(buffer_size)
                buffer_size *= 4

                while last_pcr_val == -1 and buffer_size <= 1024 * 1024:
                    last_pcr_val = self.get_last_pcr_val(buffer_size)
                    buffer_size *= 4

                return 0 if  last_pcr_val == -1 else last_pcr_val - first_pcr_val
            except:
                return 0

    def get_last_pcr_val(self, buffer_size) -> int:
        last_pcr_val = -1
        file_size = os.path.getsize(self.filename)
        cur_pos = max(file_size - file_size % self.frame_size - buffer_size, 0)
        buffer_end = cur_pos + buffer_size
        while cur_pos <= buffer_end - self.frame_size:
            self.m2ts_file.seek(cur_pos + 7)
            _last_pcr_val = self.get_pcr_val()
            if _last_pcr_val != -1:
                last_pcr_val = _last_pcr_val
            cur_pos += self.frame_size
        return last_pcr_val

    def unpack_bytes(self, n: int) -> int:
        formats: dict[int, str] = {1: '>B', 2: '>H', 4: '>I', 8: '>Q'}
        return unpack(formats[n], self.m2ts_file.read(n))[0]

    def get_pcr_val(self) -> int:
        af_exists = (self.unpack_bytes(1) >> 5) % 2
        adaptive_field_length = self.unpack_bytes(1)
        pcr_exist = (self.unpack_bytes(1) >> 4) % 2
        if af_exists and adaptive_field_length and pcr_exist:
            tmp = []
            for _ in range(4):
                tmp.append(self.unpack_bytes(1))
            pcr = tmp[3] + (tmp[2] << 8) + (tmp[1] << 16) + (tmp[0] << 24)
            pcr_lo = self.unpack_bytes(1) >> 7
            pcr_val = (pcr << 1) + pcr_lo
            return pcr_val
        return -1


class BluraySubtitle:
    def __init__(self, bluray_path:str, sub_files: list[str] = None, checked: bool = True,
                 progress_dialog: Optional[object] = None):
        self.tmp_folders = []
        if sys.platform == 'win32':
            for root, dirs, files in os.walk(bluray_path):
                dirs.sort()  # Sort dirs to ensure consistent order on all platforms
                for file in sorted(files):  # Also sort files
                    if file.endswith(".iso") and os.path.getsize(os.path.join(root, file)) > 5 * 1024 ** 3:
                        iso_path = os.path.join(root, file)
                        drivers = self.get_available_drives()
                        iso = ISO(iso_path)
                        iso.mount()
                        drivers_1 = self.get_available_drives()
                        driver = tuple(drivers_1 - drivers)[0]
                        tmp_folder = iso_path[:-4]
                        try:
                            shutil.copytree(f'{driver}:\\BDMV\\PLAYLIST', f'{tmp_folder}\\BDMV\\PLAYLIST')
                        except:
                            pass
                        else:
                            self.tmp_folders.append(tmp_folder)
                        iso.close()
                        while len(self.get_available_drives()) == len(drivers_1):
                            pass
        self.sub_files = sub_files
        self.bdmv_path = bluray_path
        bluray_folders = []
        for root, dirs, files in os.walk(bluray_path):
            dirs.sort()  # Sort dirs to ensure consistent order on all platforms
            if 'BDMV' in dirs and 'PLAYLIST' in os.listdir(os.path.join(root, 'BDMV')):
                bluray_folders.append(root)
        self.bluray_folders = bluray_folders
        self.checked = checked
        self.progress_dialog = progress_dialog
        self.configuration = {}
        self._subtitle_cache: dict[str, Subtitle] = {}

    def _progress(self, value: Optional[int] = None, text: Optional[str] = None):
        if self.progress_dialog is None:
            return
        if callable(self.progress_dialog):
            try:
                self.progress_dialog(value, text)
            except TypeError:
                if value is not None:
                    self.progress_dialog(value)
            return
        if text is not None and hasattr(self.progress_dialog, 'setLabelText'):
            self.progress_dialog.setLabelText(text)
        if value is not None and hasattr(self.progress_dialog, 'setValue'):
            self.progress_dialog.setValue(int(value))
        QCoreApplication.processEvents()

    def _preload_subtitles(self, file_paths: list[str], cancel_event: Optional[threading.Event] = None):
        if not file_paths:
            return
        missing = [p for p in file_paths if p and p not in self._subtitle_cache]
        if not missing:
            return
        
        # 根据平台选择策略
        if sys.platform == 'win32':
            # Windows下直接使用多进程
            self._preload_subtitles_multiprocess(missing, cancel_event)
        else:
            # Linux下尝试多进程，失败则回退到单进程
            try:
                self._preload_subtitles_multiprocess(missing, cancel_event)
            except Exception as e:
                print(f'多进程解析失败，切换到单进程模式: {str(e)}')
                self._preload_subtitles_single(missing, cancel_event)
    
    def _preload_subtitles_single(self, file_paths: list[str], cancel_event: Optional[threading.Event] = None):
        """单进程模式解析字幕"""
        for p in file_paths:
            if cancel_event and cancel_event.is_set():
                raise _Cancelled()
            try:
                self._subtitle_cache[p] = Subtitle(p)
            except Exception as e:
                print(f'字幕文件加载失败 ｢{p}｣: {str(e)}')
    
    def _preload_subtitles_multiprocess(self, file_paths: list[str], cancel_event: Optional[threading.Event] = None):
        """多进程模式解析字幕"""
        if len(file_paths) == 1:
            p = file_paths[0]
            try:
                self._subtitle_cache[p] = Subtitle(p)
            except Exception as e:
                print(f'字幕文件加载失败 ｢{p}｣: {str(e)}')
            return

        # 在 Linux 下，如果发现是子进程在运行，直接退出，防止递归弹出窗口
        if sys.platform != 'win32' and multiprocessing.current_process().name != 'MainProcess':
            return

        max_workers = min(len(file_paths), os.cpu_count() or 1)

        # 适配 Linux/Windows 的上下文获取
        mp_context = None
        if sys.platform == 'win32':
            mp_context = multiprocessing.get_context('spawn')
        else:
            # Linux 默认使用 fork，在 GUI 中更稳定，但必须配合 if __name__ == "__main__"
            mp_context = multiprocessing.get_context('fork')

        try:
            with ProcessPoolExecutor(max_workers=max_workers, mp_context=mp_context) as ex:
                futures = [ex.submit(_parse_subtitle_worker, p) for p in file_paths]
                for fut in as_completed(futures):
                    if cancel_event and cancel_event.is_set():
                        for f in futures:
                            f.cancel()
                        raise _Cancelled()
                    p = None
                    try:
                        p, sub = fut.result()
                        if sub is not None:
                            self._subtitle_cache[p] = sub
                    except Exception as e:
                        if p:
                            print(f'字幕文件加载失败 ｢{p}｣: {str(e)}')
                        else:
                            print(f'字幕文件加载失败: {str(e)}')
        except Exception as e:
            # 多进程失败，抛出异常让上层处理
            raise Exception(f'多进程解析失败: {str(e)}')

    @staticmethod
    def get_available_drives():
        drives = []
        bitmask = ctypes.windll.kernel32.GetLogicalDrives()
        for letter in range(65, 91):
            if bitmask & 1:
                drives.append(chr(letter))
            bitmask >>= 1
        return set(drives)

    def get_main_mpls(self, bluray_folder: str, checked: bool) -> str:
        mpls_folder = os.path.join(bluray_folder, 'BDMV', 'PLAYLIST')
        stream_folder = os.path.join(bluray_folder, 'BDMV', 'STREAM')
        selected_mpls = None
        max_indicator = 0
        for mpls_file_name in os.listdir(mpls_folder):
            if mpls_file_name[-5:].lower() != '.mpls':
                continue
            mpls_file_path = os.path.join(mpls_folder, mpls_file_name)
            chapter = Chapter(mpls_file_path)
            if checked:
                total_size = 1
            else:
                total_size = 0
                stream_files = set()
                for in_out_time in chapter.in_out_time:
                    if in_out_time[0] not in stream_files:
                        m2ts_file = os.path.join(stream_folder, f'{in_out_time[0]}.m2ts')
                        if os.path.exists(m2ts_file):
                            total_size += os.path.getsize(m2ts_file)
                        else:
                            print(f'\033[31m错误,｢{mpls_file_path}｣ 中的m2ts文件 ｢{m2ts_file}｣ 未找到\033[0m')
                    stream_files.add(in_out_time[0])
            indicator = chapter.get_total_time_no_repeat() * (1 + sum(map(len, chapter.mark_info.values())) / 5
                                                              ) * os.path.getsize(mpls_file_path) * total_size
            if indicator > max_indicator:
                max_indicator = indicator
                selected_mpls = mpls_file_path
        return selected_mpls

    def select_mpls_from_table(self, table: QTableWidget) -> Generator[str, Chapter, str]:
        for bdmv_index in range(table.rowCount()):
            bluray_folder = table.item(bdmv_index, 0).text()
            info: QTableWidget = table.cellWidget(bdmv_index, 2)
            for mpls_index in range(info.rowCount()):
                main_btn: QToolButton = info.cellWidget(mpls_index, 3)
                if main_btn.isChecked():
                    mpls_file = info.item(mpls_index, 0).text()
                    selected_mpls = os.path.join(bluray_folder, 'BDMV', 'PLAYLIST', mpls_file)
                    yield bluray_folder, Chapter(selected_mpls), selected_mpls[:-5]

    def generate_configuration(self, table: QTableWidget,
                               sub_combo_index: Optional[dict[int, int]] = None,
                               subtitle_index: Optional[int] = None) -> dict[int, dict[str, int | str]]:
        configuration = {}
        sub_index = 0
        bdmv_index = 0
        global CONFIGURATION
        if self.sub_files:
            # 在主线程中总是使用单进程模式，避免多进程问题
            missing = [p for p in self.sub_files if p and p not in self._subtitle_cache]
            if missing:
                # 直接使用单进程加载，避免多进程在主线程中的问题
                for p in missing:
                    try:
                        self._subtitle_cache[p] = Subtitle(p)
                    except Exception as e:
                        print(f'字幕文件加载失败 ｢{p}｣: {str(e)}')
            sub_max_end = [self._subtitle_cache[p].max_end_time() for p in self.sub_files]
        else:
            sub_max_end = []
        if sub_combo_index:
            chapter_index = sub_combo_index[sub_index]
            for folder, chapter, selected_mpls in self.select_mpls_from_table(table):
                for bdmv_index in range(table.rowCount()):
                    if  table.item(bdmv_index, 0).text() == folder:
                        break
                bdmv_index += 1
                offset = 0
                j = 1
                left_time = chapter.get_total_time()
                sub_end_time = sub_max_end[sub_index] if self.sub_files else 1440
                for i, play_item_in_out_time in enumerate(chapter.in_out_time):
                    play_item_marks = chapter.mark_info.get(i)
                    if sub_index <= subtitle_index and j == chapter_index:
                        sub_end_time = offset + (sub_max_end[sub_index] if self.sub_files else 1440)
                        configuration[sub_index] = {'folder': folder, 'selected_mpls': selected_mpls,
                                                    'bdmv_index': bdmv_index, 'chapter_index': j,
                                                    'offset': get_time_str(offset)}
                        sub_index += 1
                        if sub_combo_index.get(sub_index):
                            chapter_index = sub_combo_index[sub_index]
                    elif sub_index > subtitle_index:
                        if offset > sub_end_time - 300 or offset == 0:
                            if (((sub_index + 1 < len(self.sub_files)) if self.sub_files else True)
                                    and left_time > (sub_max_end[sub_index + 1] if self.sub_files else 1440) - 180):
                                sub_end_time = offset + (sub_max_end[sub_index] if self.sub_files else 1440)
                                configuration[sub_index] = {'folder': folder, 'selected_mpls': selected_mpls,
                                                            'bdmv_index': bdmv_index, 'chapter_index': j,
                                                            'offset': get_time_str(offset)}
                                sub_index += 1
                    if play_item_marks:
                        for mark in play_item_marks:
                            time_shift = offset + (mark - play_item_in_out_time[1]) / 45000
                            if sub_index <= subtitle_index and j == chapter_index:
                                sub_end_time = time_shift + (sub_max_end[sub_index] if self.sub_files else 1440)
                                configuration[sub_index] = {'folder': folder, 'selected_mpls': selected_mpls,
                                                            'bdmv_index': bdmv_index, 'chapter_index': j,
                                                            'offset': get_time_str(time_shift)}
                                sub_index += 1
                                if sub_combo_index.get(sub_index):
                                    chapter_index = sub_combo_index[sub_index]
                            elif sub_index > subtitle_index:
                                if time_shift > sub_end_time and (
                                        play_item_in_out_time[2] - mark) / 45000 > 1200:
                                    sub_end_time = time_shift + (sub_max_end[sub_index] if self.sub_files else 1440)
                                    configuration[sub_index] = {'folder': folder, 'selected_mpls': selected_mpls,
                                                                'bdmv_index': bdmv_index, 'chapter_index': j,
                                                                'offset': get_time_str(time_shift)}
                                    sub_index += 1
                            j += 1
                    offset += (play_item_in_out_time[2] - play_item_in_out_time[1]) / 45000
                    left_time += (play_item_in_out_time[1] - play_item_in_out_time[2]) / 45000
            CONFIGURATION = configuration
            return configuration
        for folder, chapter, selected_mpls in self.select_mpls_from_table(table):
            for bdmv_index in range(table.rowCount()):
                if table.item(bdmv_index, 0).text() == folder:
                    break
            bdmv_index += 1
            start_time = 0
            sub_end_time = sub_max_end[sub_index] if self.sub_files else 1440
            left_time = chapter.get_total_time()
            configuration[sub_index] = {'folder': folder, 'selected_mpls': selected_mpls,
                                        'bdmv_index': bdmv_index, 'chapter_index': 1, 'offset': '0'}
            j = 1
            for i, play_item_in_out_time in enumerate(chapter.in_out_time):
                play_item_marks = chapter.mark_info.get(i)
                chapter_num = len(play_item_marks or [])
                if play_item_marks:
                    play_item_duration_time = play_item_in_out_time[2] - play_item_in_out_time[1]
                    time_shift = (start_time + play_item_marks[0] - play_item_in_out_time[1]) / 45000
                    if time_shift > sub_end_time - 300:
                        if (((sub_index + 1 < len(self.sub_files)) if self.sub_files else True)
                                and left_time > (sub_max_end[sub_index + 1] if self.sub_files else 1440) - 180):
                            sub_index += 1
                            sub_end_time = (time_shift + (sub_max_end[sub_index] if self.sub_files else 1440))
                            configuration[sub_index] = {'folder': folder, 'selected_mpls': selected_mpls,
                                                        'bdmv_index': bdmv_index, 'chapter_index': j,
                                                        'offset': get_time_str(time_shift)}

                    if play_item_duration_time / 45000 > 2600 and sub_end_time - time_shift < 1800:
                        k = j
                        for mark in play_item_marks[1:]:
                            k += 1
                            time_shift = (start_time + mark - play_item_in_out_time[1]) / 45000
                            if time_shift > sub_end_time and (
                                    play_item_in_out_time[2] - mark) / 45000 > 1200:
                                sub_index += 1
                                sub_end_time = (time_shift + (sub_max_end[sub_index] if self.sub_files else 1440))
                                configuration[sub_index] = {'folder': folder, 'selected_mpls': selected_mpls,
                                                            'bdmv_index': bdmv_index, 'chapter_index': k,
                                                            'offset': get_time_str(time_shift)}

                j += chapter_num
                start_time += play_item_in_out_time[2] - play_item_in_out_time[1]
                left_time += (play_item_in_out_time[1] - play_item_in_out_time[2]) / 45000

            sub_index += 1
            if sub_index == len(self.sub_files):
                break
        CONFIGURATION = configuration
        return configuration

    def generate_configuration_from_selected_mpls(self, selected_mpls: list[tuple[str, str]],
                                                  sub_combo_index: Optional[dict[int, int]] = None,
                                                  subtitle_index: Optional[int] = None,
                                                  cancel_event: Optional[threading.Event] = None
                                                  ) -> dict[int, dict[str, int | str]]:
        if not selected_mpls:
            return {}
        configuration = {}
        sub_index = 0
        global CONFIGURATION

        if self.sub_files:
            # 在主线程中总是使用单进程模式，避免多进程问题
            missing = [p for p in self.sub_files if p and p not in self._subtitle_cache]
            if missing:
                # 直接使用单进程加载，避免多进程在主线程中的问题
                for p in missing:
                    try:
                        self._subtitle_cache[p] = Subtitle(p)
                    except Exception as e:
                        print(f'字幕文件加载失败 ｢{p}｣: {str(e)}')
            sub_max_end = [self._subtitle_cache[p].max_end_time() for p in self.sub_files]
        else:
            sub_max_end = []

        folder_to_bdmv_index: dict[str, int] = {}

        if sub_combo_index:
            chapter_index = sub_combo_index[sub_index]
            for folder, selected_mpls_no_ext in selected_mpls:
                if cancel_event and cancel_event.is_set():
                    raise _Cancelled()
                if folder not in folder_to_bdmv_index:
                    folder_to_bdmv_index[folder] = len(folder_to_bdmv_index) + 1
                bdmv_index = folder_to_bdmv_index[folder]
                chapter = Chapter(selected_mpls_no_ext + '.mpls')
                offset = 0
                j = 1
                left_time = chapter.get_total_time()
                sub_end_time = sub_max_end[sub_index] if self.sub_files else 1440
                for i, play_item_in_out_time in enumerate(chapter.in_out_time):
                    play_item_marks = chapter.mark_info.get(i)
                    if sub_index <= subtitle_index and j == chapter_index:
                        sub_end_time = offset + (sub_max_end[sub_index] if self.sub_files else 1440)
                        configuration[sub_index] = {'folder': folder, 'selected_mpls': selected_mpls_no_ext,
                                                    'bdmv_index': bdmv_index, 'chapter_index': j,
                                                    'offset': get_time_str(offset)}
                        sub_index += 1
                        if sub_combo_index.get(sub_index):
                            chapter_index = sub_combo_index[sub_index]
                    elif sub_index > subtitle_index:
                        if offset > sub_end_time - 300 or offset == 0:
                            if (((sub_index + 1 < len(self.sub_files)) if self.sub_files else True)
                                    and left_time > (sub_max_end[sub_index + 1] if self.sub_files else 1440) - 180):
                                sub_end_time = offset + (sub_max_end[sub_index] if self.sub_files else 1440)
                                configuration[sub_index] = {'folder': folder, 'selected_mpls': selected_mpls_no_ext,
                                                            'bdmv_index': bdmv_index, 'chapter_index': j,
                                                            'offset': get_time_str(offset)}
                                sub_index += 1
                    if play_item_marks:
                        for mark in play_item_marks:
                            time_shift = offset + (mark - play_item_in_out_time[1]) / 45000
                            if sub_index <= subtitle_index and j == chapter_index:
                                sub_end_time = time_shift + (sub_max_end[sub_index] if self.sub_files else 1440)
                                configuration[sub_index] = {'folder': folder, 'selected_mpls': selected_mpls_no_ext,
                                                            'bdmv_index': bdmv_index, 'chapter_index': j,
                                                            'offset': get_time_str(time_shift)}
                                sub_index += 1
                                if sub_combo_index.get(sub_index):
                                    chapter_index = sub_combo_index[sub_index]
                            elif sub_index > subtitle_index:
                                if time_shift > sub_end_time and (
                                        play_item_in_out_time[2] - mark) / 45000 > 1200:
                                    sub_end_time = time_shift + (sub_max_end[sub_index] if self.sub_files else 1440)
                                    configuration[sub_index] = {'folder': folder, 'selected_mpls': selected_mpls_no_ext,
                                                                'bdmv_index': bdmv_index, 'chapter_index': j,
                                                                'offset': get_time_str(time_shift)}
                                    sub_index += 1
                            j += 1
                    offset += (play_item_in_out_time[2] - play_item_in_out_time[1]) / 45000
                    left_time += (play_item_in_out_time[1] - play_item_in_out_time[2]) / 45000
            CONFIGURATION = configuration
            return configuration

        for folder, selected_mpls_no_ext in selected_mpls:
            if cancel_event and cancel_event.is_set():
                raise _Cancelled()
            if folder not in folder_to_bdmv_index:
                folder_to_bdmv_index[folder] = len(folder_to_bdmv_index) + 1
            bdmv_index = folder_to_bdmv_index[folder]
            chapter = Chapter(selected_mpls_no_ext + '.mpls')
            start_time = 0
            sub_end_time = sub_max_end[sub_index] if self.sub_files else 1440
            left_time = chapter.get_total_time()
            configuration[sub_index] = {'folder': folder, 'selected_mpls': selected_mpls_no_ext,
                                        'bdmv_index': bdmv_index, 'chapter_index': 1, 'offset': '0'}
            j = 1
            for i, play_item_in_out_time in enumerate(chapter.in_out_time):
                play_item_marks = chapter.mark_info.get(i)
                chapter_num = len(play_item_marks or [])
                if play_item_marks:
                    play_item_duration_time = play_item_in_out_time[2] - play_item_in_out_time[1]
                    time_shift = (start_time + play_item_marks[0] - play_item_in_out_time[1]) / 45000
                    if time_shift > sub_end_time - 300:
                        if (((sub_index + 1 < len(self.sub_files)) if self.sub_files else True)
                                and left_time > (sub_max_end[sub_index + 1] if self.sub_files else 1440) - 180):
                            sub_index += 1
                            sub_end_time = (time_shift + (sub_max_end[sub_index] if self.sub_files else 1440))
                            configuration[sub_index] = {'folder': folder, 'selected_mpls': selected_mpls_no_ext,
                                                        'bdmv_index': bdmv_index, 'chapter_index': j,
                                                        'offset': get_time_str(time_shift)}

                    if play_item_duration_time / 45000 > 2600 and sub_end_time - time_shift < 1800:
                        k = j
                        for mark in play_item_marks[1:]:
                            k += 1
                            time_shift = (start_time + mark - play_item_in_out_time[1]) / 45000
                            if time_shift > sub_end_time and (
                                    play_item_in_out_time[2] - mark) / 45000 > 1200:
                                sub_index += 1
                                sub_end_time = (time_shift + (sub_max_end[sub_index] if self.sub_files else 1440))
                                configuration[sub_index] = {'folder': folder, 'selected_mpls': selected_mpls_no_ext,
                                                            'bdmv_index': bdmv_index, 'chapter_index': k,
                                                            'offset': get_time_str(time_shift)}

                j += chapter_num
                start_time += play_item_in_out_time[2] - play_item_in_out_time[1]
                left_time += (play_item_in_out_time[1] - play_item_in_out_time[2]) / 45000

            sub_index += 1
            if sub_index == len(self.sub_files):
                break
        CONFIGURATION = configuration
        return configuration

    def generate_bluray_subtitle(self, table: Optional[QTableWidget] = None,
                                 configuration: Optional[dict[int, dict[str, int | str]]] = None,
                                 cancel_event: Optional[threading.Event] = None):
        if configuration is not None:
            self.configuration = configuration
        elif CONFIGURATION:
            self.configuration = CONFIGURATION
        else:
            if table is None:
                raise ValueError('table is required when configuration is not provided')
            self.configuration = self.generate_configuration(table)
        if not self.sub_files:
            return
        self._preload_subtitles(self.sub_files, cancel_event=cancel_event)
        sub = self._subtitle_cache[self.sub_files[0]].clone()
        bdmv_index = 0
        conf = self.configuration[0]
        for sub_index, conf_tmp in self.configuration.items():
            self._progress(int((sub_index + 1) / len(self.sub_files) * 1000),
                           f'合并中 {sub_index + 1}/{len(self.sub_files)}')
            if conf_tmp['bdmv_index'] != bdmv_index:
                if bdmv_index > 0:
                    self._progress(text='写入字幕文件')
                    if hasattr(sub, 'content'):
                        sub.dump(conf['folder'], conf['selected_mpls'])
                    sub = self._subtitle_cache[self.sub_files[sub_index]].clone()
                bdmv_index = conf_tmp['bdmv_index']
            else:
                sub.append_subtitle(
                    self._subtitle_cache[self.sub_files[sub_index]],
                    reduce(lambda a, b: a * 60 + b, map(float, conf_tmp['offset'].split(':')))
                )
            conf = conf_tmp
            if cancel_event and cancel_event.is_set():
                raise _Cancelled()
        self._progress(text='写入字幕文件')
        if hasattr(sub, 'content'):
            sub.dump(conf['folder'], conf['selected_mpls'])
        self._progress(1000)

    def add_chapter_to_mkv(self, mkv_files, table: Optional[QTableWidget] = None,
                           selected_mpls: Optional[list[tuple[str, str]]] = None):
        mkv_index = 0
        if selected_mpls is not None:
            iterator = ((folder, Chapter(selected_mpls_no_ext + '.mpls'), selected_mpls_no_ext)
                        for folder, selected_mpls_no_ext in selected_mpls)
        else:
            if table is None:
                return
            iterator = self.select_mpls_from_table(table)

        for folder, chapter, selected_mpls in iterator:
            duration = MKV(mkv_files[mkv_index]).get_duration()
            print(f'folder: {folder}')
            print(f'in_out_time: {chapter.in_out_time}')
            print(f'mark_info: {chapter.mark_info}')
            print(f'集数：{mkv_index + 1}, 时长: {duration}')

            play_item_duration_time_sum = 0
            episode_duration_time_sum = 0
            chapter_id = 0
            chapter_text = []
            for ref_to_play_item_id, mark_timestamps in chapter.mark_info.items():
                clip_information_filename, in_time, out_time = chapter.in_out_time[ref_to_play_item_id]
                for mark_timestamp in mark_timestamps:
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
                        duration = MKV(mkv_files[mkv_index]).get_duration()
                        print(f'集数：{mkv_index + 1}, 时长: {duration}')
                        chapter_text.clear()

                    chapter_id += 1
                    chapter_id_str = ('0' if chapter_id < 10 else '') + str(chapter_id)
                    hours = int(real_time // 3600)
                    minutes = int((real_time % 3600) // 60)
                    seconds = real_time % 60
                    seconds_str = (('0' if seconds < 10 else '') + str(seconds))[:6]
                    seconds_str += '00.000'[len(seconds_str) - 6:]
                    real_time_str = (('0' if hours < 10 else '') + str(hours) + ':'
                                     + ('0' if minutes < 10 else '') + str(minutes) + ':'
                                     + seconds_str)
                    chapter_text.append(f'CHAPTER{chapter_id_str}={real_time_str}')
                    chapter_text.append(f'CHAPTER{chapter_id_str}NAME=Chapter {chapter_id_str}')
                play_item_duration_time_sum += (out_time - in_time) / 45000

            with open(f'chapter.txt', 'w', encoding='utf-8-sig') as f:
                f.write('\n'.join(chapter_text))
            mkv = MKV(mkv_files[mkv_index])
            mkv.add_chapter(self.checked)
            self._progress(int((mkv_index + 1) / len(mkv_files) * 1000))
            mkv_index += 1

        self._progress(1000)

    def completion(self):  # 补全蓝光目录；删除临时文件
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

    def episodes_remux(self, table: Optional[QTableWidget], folder_path: str,
                       selected_mpls: Optional[list[tuple[str, str]]] = None,
                       configuration: Optional[dict[int, dict[str, int | str]]] = None,
                       cancel_event: Optional[threading.Event] = None,
                       ensure_tools: bool = True):
        if configuration is not None:
            self.configuration = configuration
        elif not CONFIGURATION:
            if table is None:
                self.configuration = {}
            else:
                self.configuration = self.generate_configuration(table)
        else:
            self.configuration = CONFIGURATION
        if not os.path.exists(dst_folder := os.path.join(folder_path, os.path.basename(self.bdmv_path))):
            os.mkdir(dst_folder)
        mkv_files_before = set()
        try:
            mkv_files_before = {f for f in os.listdir(dst_folder) if f.lower().endswith('.mkv')}
        except Exception:
            mkv_files_before = set()
        bdmv_index_conf = {}
        for sub_index, conf in self.configuration.items():
            if conf['bdmv_index'] in bdmv_index_conf:
                bdmv_index_conf[conf['bdmv_index']].append(conf)
            else:
                bdmv_index_conf[conf['bdmv_index']] = [conf]
        if ensure_tools:
            find_mkvtoolinx()

        def mkv_sort_key(p: str):
            name = os.path.basename(p)
            m = re.search(r'BD_Vol_(\d{3})', name)
            vol = int(m.group(1)) if m else 9999
            m2 = re.search(r'-(\d{3})\.mkv$', name, re.IGNORECASE)
            seg = int(m2.group(1)) if m2 else 0
            return vol, seg, name.lower()

        bdmv_index_list = sorted(bdmv_index_conf.keys())
        for idx, bdmv_index in enumerate(bdmv_index_list, start=1):
            if cancel_event and cancel_event.is_set():
                raise _Cancelled()
            confs = bdmv_index_conf[bdmv_index]
            try:
                confs = sorted(confs, key=lambda c: int(c.get('chapter_index') or 0))
            except Exception:
                pass
            mpls_path = confs[0]['selected_mpls'] + '.mpls'

            chapter = Chapter(mpls_path)
            chapter.get_pid_to_language()
            m2ts_file = os.path.join(os.path.join(mpls_path[:-19], 'STREAM'), chapter.in_out_time[0][0] + '.m2ts')
            print(f'正在分析mpls的第一个文件 ｢{m2ts_file}｣ 的轨道')
            self._progress(text=f'分析轨道：{os.path.basename(m2ts_file)}')
            cmd = f'"{FFPROBE_PATH}" -v error -show_streams -show_format -of json "{m2ts_file}" >info.json 2>&1'
            subprocess.Popen(cmd, shell=True).wait()

            with open('info.json', 'r', encoding='utf-8') as fp:
                data = json.load(fp)
            audio_type_weight = {'': -1, 'aac': 1, 'ac3': 2, 'eac3': 3, 'lpcm': 4, 'dts': 5, 'dts_hd_ma': 6, 'truehd': 7}
            selected_eng_audio_track = ['', '']
            selected_zho_audio_track = ['', '']
            copy_sub_track = []
            for stream_info in data['streams']:

                if stream_info['codec_type'] == 'audio':
                    codec_name = stream_info['codec_name']
                    if codec_name == 'dts' and stream_info.get('profile') == 'DTS-HD MA':
                        codec_name = 'dts_hd_ma'
                    lang = chapter.pid_to_lang.get(int(stream_info['id'], 16), 'und')
                    if lang == 'eng':
                        if not selected_eng_audio_track[1] or audio_type_weight[codec_name] > audio_type_weight[
                            selected_eng_audio_track[1]]:
                            selected_eng_audio_track = [str(stream_info['index']), codec_name]
                    elif lang == 'zho':
                        if not selected_zho_audio_track[1] or audio_type_weight[codec_name] > audio_type_weight[
                            selected_zho_audio_track[1]]:
                            selected_zho_audio_track = [str(stream_info['index']), codec_name]
                elif stream_info['codec_type'] == 'subtitle':
                    lang = chapter.pid_to_lang.get(int(stream_info['id'], 16), 'und')
                    if lang in ['eng', 'zho']:
                        copy_sub_track.append(str(stream_info['index']))
            if not copy_sub_track:
                for stream_info in data['streams']:
                    if stream_info['codec_type'] == 'subtitle':
                        copy_sub_track.append(str(stream_info['index']))
                        break
            if not selected_zho_audio_track[0] and not selected_eng_audio_track[0]:
                copy_audio_track = []
                for stream_info in data['streams']:
                    if stream_info['codec_type'] == 'audio':
                        copy_audio_track.append(str(stream_info['index']))
                        break
                for stream_info in data['streams']:
                    if stream_info['codec_type'] == 'audio':
                        lang = chapter.pid_to_lang.get(int(stream_info['id'], 16), 'und')
                        if lang == 'jpn' and str(stream_info['index']) not in copy_audio_track:
                            copy_audio_track.append(str(stream_info['index']))
            else:
                if selected_eng_audio_track[0] and selected_zho_audio_track[0]:
                    copy_audio_track = [selected_eng_audio_track[0], selected_zho_audio_track[0]]
                elif not selected_eng_audio_track[0]:
                    copy_audio_track = [selected_zho_audio_track[0]]
                else:
                    copy_audio_track = [selected_eng_audio_track[0]]
                first_audio_index = 1
                for stream_info in data['streams']:
                    if stream_info['codec_type'] == 'audio':
                        first_audio_index = stream_info['index']
                        break
                if str(first_audio_index) not in (selected_zho_audio_track[0], selected_eng_audio_track[0]):
                    copy_audio_track.append(str(first_audio_index))
            print(f'选择音频轨道 {copy_audio_track}，字幕轨道 {copy_sub_track}')
            meta_folder = os.path.join(os.path.join(mpls_path[:-19], 'META', 'DL'))
            cover = ''
            cover_size = 0
            if not os.path.exists(meta_folder):
                output_name = os.path.split(mpls_path[:-24])[-1]
            else:
                for filename in os.listdir(meta_folder):
                    # 获取附件Cover
                    if filename.endswith('.jpg') or filename.endswith('.JPG') or filename.endswith(
                            '.JPEG') or filename.endswith('.jpeg') or filename.endswith('.png') or filename.endswith(
                        '.PNG'):
                        if os.path.getsize(os.path.join(meta_folder, filename)) > cover_size:
                            cover = os.path.join(meta_folder, filename)
                            cover_size = os.path.getsize(os.path.join(meta_folder, filename))
                # 获取输出文件名
                output_name = ''
                for filename in os.listdir(meta_folder):
                    if filename == 'bdmt_eng.xml':
                        try:
                            tree = et.parse(os.path.join(meta_folder, filename))
                            _folder = tree.getroot()
                            ns = {'di': 'urn:BDA:bdmv;discinfo'}
                            output_name = _folder.find('.//di:name', ns).text
                            break
                        except (et.ParseError, FileNotFoundError):
                            continue
                if not output_name:
                    for filename in os.listdir(meta_folder):
                        if filename == 'bdmt_zho.xml':
                            try:
                                tree = et.parse(os.path.join(meta_folder, filename))
                                _folder = tree.getroot()
                                ns = {'di': 'urn:BDA:bdmv;discinfo'}
                                output_name = _folder.find('.//di:name', ns).text
                                break
                            except (et.ParseError, FileNotFoundError):
                                continue
                if not output_name:
                    for filename in os.listdir(meta_folder):
                        try:
                            tree = et.parse(os.path.join(meta_folder, filename))
                            _folder = tree.getroot()
                            ns = {'di': 'urn:BDA:bdmv;discinfo'}
                            output_name = _folder.find('.//di:name', ns).text
                            break
                        except (et.ParseError, FileNotFoundError):
                            continue
                if not output_name:
                    output_name = os.path.split(mpls_path[:-24])[-1]
            char_map = {
                '?': '？',
                '*': '★',
                '<': '《',
                '>': '》',
                ':': '：',
                '"': "'",
                '/': '／',
                '\\': '／',
                '|': '￨'
            }
            output_name = ''.join(char_map.get(char) or char for char in output_name)
            if cover:
                print(f"找到封面图片 ｢{cover}｣")
            print(f'输出文件名{output_name}.mkv')

            chapter_split = ','.join(map(str, [conf['chapter_index'] for conf in confs]))
            bdmv_vol = '0' * (3 - len(str(bdmv_index))) + str(bdmv_index)
            output_file = f'{os.path.join(dst_folder, output_name)}_BD_Vol_{bdmv_vol}.mkv'
            remux_cmd = (f'"{MKV_MERGE_PATH}" --split chapters:{chapter_split} -o "{output_file}" '
                         f'{("-a " + ",".join(copy_audio_track)) if copy_audio_track else ""} '
                         f'{("-s " + ",".join(copy_sub_track)) if copy_sub_track else ""} '
                         f'{(" --attachment-name Cover.jpg" + " --attach-file " + "\"" + cover + "\"") if cover else ""}  '
                         f'"{mpls_path}"')
            print(f'混流命令: {remux_cmd}')
            self._progress(text=f'混流中：BD_Vol_{bdmv_vol}')
            subprocess.Popen(remux_cmd, shell=True).wait()
            self._progress(int(idx / max(len(bdmv_index_list), 1) * 300))

        self.checked = True
        mkv_files_after = []
        try:
            mkv_files_after = [f for f in os.listdir(dst_folder) if f.lower().endswith('.mkv')]
        except Exception:
            mkv_files_after = []
        created = [os.path.join(dst_folder, f) for f in mkv_files_after if f not in mkv_files_before]
        if created:
            mkv_files = sorted(created, key=mkv_sort_key)
        else:
            mkv_files = sorted([os.path.join(dst_folder, f) for f in mkv_files_after], key=mkv_sort_key)
        if cancel_event and cancel_event.is_set():
            raise _Cancelled()
        self._progress(310, '写入章节中')
        self.add_chapter_to_mkv(mkv_files, table, selected_mpls=selected_mpls)
        self._progress(400)

        i = 0
        for mkv_file in mkv_files:
            if cancel_event and cancel_event.is_set():
                raise _Cancelled()
            i += 1
            self._progress(text=f'压缩音轨：{os.path.basename(mkv_file)}')
            self.flac_task(mkv_file, dst_folder, i)
            self._progress(400 + int(400 * i / len(mkv_files)))

        sps_folder = dst_folder + os.sep + 'SPs'
        os.mkdir(sps_folder)
        for bdmv_index in bdmv_index_list:
            if cancel_event and cancel_event.is_set():
                raise _Cancelled()
            confs = bdmv_index_conf[bdmv_index]
            bdmv_vol = '0' * (3 - len(str(bdmv_index))) + str(bdmv_index)
            mpls_path = confs[0]['selected_mpls'] + '.mpls'
            index_to_m2ts, index_to_offset = get_index_to_m2ts_and_offset(Chapter(mpls_path))
            main_m2ts_files = set(index_to_m2ts.values())
            parsed_m2ts_files = set(main_m2ts_files)
            sp_index = 0
            for mpls_file in sorted(os.listdir(os.path.dirname(mpls_path))):
                if cancel_event and cancel_event.is_set():
                    raise _Cancelled()
                if not mpls_file.endswith('.mpls'):
                    continue
                mpls_file_path = os.path.join(os.path.dirname(mpls_path), mpls_file)
                if mpls_file_path != mpls_path:
                    index_to_m2ts, index_to_offset = get_index_to_m2ts_and_offset(Chapter(mpls_file_path))
                    if main_m2ts_files & set(index_to_m2ts.values()):
                        continue
                    if len(index_to_m2ts) > 1:
                        sp_index += 1
                        subprocess.Popen(f'"{MKV_MERGE_PATH}" -o "{sps_folder}{os.sep}BD_Vol_'
                                         f'{bdmv_vol}_SP0{sp_index}.mkv" "{mpls_file_path}"', shell=True).wait()
                        parsed_m2ts_files |= set(index_to_m2ts.values())
            stream_folder = os.path.dirname(mpls_path).removesuffix('PLAYLIST') + 'STREAM'
            for stream_file in sorted(os.listdir(stream_folder)):
                if cancel_event and cancel_event.is_set():
                    raise _Cancelled()
                if stream_file not in parsed_m2ts_files and stream_file.endswith('.m2ts'):
                    if M2TS(os.path.join(stream_folder, stream_file)).get_duration() > 30 * 90000:
                        subprocess.Popen(f'"{MKV_MERGE_PATH}" -o "{sps_folder}{os.sep}BD_Vol_'
                                         f'{bdmv_vol}_{stream_file[:-5]}.mkv" '
                                         f'"{os.path.join(stream_folder, stream_file)}"', shell=True).wait()
        self._progress(900, '处理 SPs 音轨')
        for sp in os.listdir(sps_folder):
            if cancel_event and cancel_event.is_set():
                raise _Cancelled()
            self.flac_task(sps_folder + os.sep + sp, sps_folder, -1)

        self.completion()
        self._progress(1000, '完成')

    def episodes_encode(self, table: Optional[QTableWidget], folder_path: str,
                        selected_mpls: Optional[list[tuple[str, str]]] = None,
                        configuration: Optional[dict[int, dict[str, int | str]]] = None,
                        cancel_event: Optional[threading.Event] = None,
                        ensure_tools: bool = True,
                        vpy_paths: Optional[list[str]] = None,
                        sp_vpy_paths: Optional[list[str]] = None,
                        sp_entries: Optional[list[dict[str, int | str]]] = None,
                        vspipe_mode: str = 'bundle',
                        x265_mode: str = 'bundle',
                        x265_params: str = '',
                        sub_pack_mode: str = 'external'):
        if configuration is not None:
            self.configuration = configuration
        elif not CONFIGURATION:
            if table is None:
                self.configuration = {}
            else:
                self.configuration = self.generate_configuration(table)
        else:
            self.configuration = CONFIGURATION
        if not os.path.exists(dst_folder := os.path.join(folder_path, os.path.basename(self.bdmv_path))):
            os.mkdir(dst_folder)
        mkv_files_before = set()
        try:
            mkv_files_before = {f for f in os.listdir(dst_folder) if f.lower().endswith('.mkv')}
        except Exception:
            mkv_files_before = set()
        bdmv_index_conf = {}
        for sub_index, conf in self.configuration.items():
            if conf['bdmv_index'] in bdmv_index_conf:
                bdmv_index_conf[conf['bdmv_index']].append(conf)
            else:
                bdmv_index_conf[conf['bdmv_index']] = [conf]
        if ensure_tools:
            find_mkvtoolinx()

        def mkv_sort_key(p: str):
            name = os.path.basename(p)
            m = re.search(r'BD_Vol_(\d{3})', name)
            vol = int(m.group(1)) if m else 9999
            m2 = re.search(r'-(\d{3})\.mkv$', name, re.IGNORECASE)
            seg = int(m2.group(1)) if m2 else 0
            return vol, seg, name.lower()

        bdmv_index_list = sorted(bdmv_index_conf.keys())
        for idx, bdmv_index in enumerate(bdmv_index_list, start=1):
            if cancel_event and cancel_event.is_set():
                raise _Cancelled()
            confs = bdmv_index_conf[bdmv_index]
            try:
                confs = sorted(confs, key=lambda c: int(c.get('chapter_index') or 0))
            except Exception:
                pass
            mpls_path = confs[0]['selected_mpls'] + '.mpls'

            chapter = Chapter(mpls_path)
            chapter.get_pid_to_language()
            m2ts_file = os.path.join(os.path.join(mpls_path[:-19], 'STREAM'), chapter.in_out_time[0][0] + '.m2ts')
            print(f'正在分析mpls的第一个文件 ｢{m2ts_file}｣ 的轨道')
            self._progress(text=f'分析轨道：{os.path.basename(m2ts_file)}')
            cmd = f'"{FFPROBE_PATH}" -v error -show_streams -show_format -of json "{m2ts_file}" >info.json 2>&1'
            subprocess.Popen(cmd, shell=True).wait()

            with open('info.json', 'r', encoding='utf-8') as fp:
                data = json.load(fp)
            audio_type_weight = {'': -1, 'aac': 1, 'ac3': 2, 'eac3': 3, 'lpcm': 4, 'dts': 5, 'dts_hd_ma': 6, 'truehd': 7}
            selected_eng_audio_track = ['', '']
            selected_zho_audio_track = ['', '']
            copy_sub_track = []
            for stream_info in data['streams']:

                if stream_info['codec_type'] == 'audio':
                    codec_name = stream_info['codec_name']
                    if codec_name == 'dts' and stream_info.get('profile') == 'DTS-HD MA':
                        codec_name = 'dts_hd_ma'
                    lang = chapter.pid_to_lang.get(int(stream_info['id'], 16), 'und')
                    if lang == 'eng':
                        if not selected_eng_audio_track[1] or audio_type_weight[codec_name] > audio_type_weight[
                            selected_eng_audio_track[1]]:
                            selected_eng_audio_track = [str(stream_info['index']), codec_name]
                    elif lang == 'zho':
                        if not selected_zho_audio_track[1] or audio_type_weight[codec_name] > audio_type_weight[
                            selected_zho_audio_track[1]]:
                            selected_zho_audio_track = [str(stream_info['index']), codec_name]
                elif stream_info['codec_type'] == 'subtitle':
                    lang = chapter.pid_to_lang.get(int(stream_info['id'], 16), 'und')
                    if lang in ['eng', 'zho']:
                        copy_sub_track.append(str(stream_info['index']))
            if not copy_sub_track:
                for stream_info in data['streams']:
                    if stream_info['codec_type'] == 'subtitle':
                        copy_sub_track.append(str(stream_info['index']))
                        break
            if not selected_zho_audio_track[0] and not selected_eng_audio_track[0]:
                copy_audio_track = []
                for stream_info in data['streams']:
                    if stream_info['codec_type'] == 'audio':
                        copy_audio_track.append(str(stream_info['index']))
                        break
                for stream_info in data['streams']:
                    if stream_info['codec_type'] == 'audio':
                        lang = chapter.pid_to_lang.get(int(stream_info['id'], 16), 'und')
                        if lang == 'jpn' and str(stream_info['index']) not in copy_audio_track:
                            copy_audio_track.append(str(stream_info['index']))
            else:
                if selected_eng_audio_track[0] and selected_zho_audio_track[0]:
                    copy_audio_track = [selected_eng_audio_track[0], selected_zho_audio_track[0]]
                elif not selected_eng_audio_track[0]:
                    copy_audio_track = [selected_zho_audio_track[0]]
                else:
                    copy_audio_track = [selected_eng_audio_track[0]]
                first_audio_index = 1
                for stream_info in data['streams']:
                    if stream_info['codec_type'] == 'audio':
                        first_audio_index = stream_info['index']
                        break
                if str(first_audio_index) not in (selected_zho_audio_track[0], selected_eng_audio_track[0]):
                    copy_audio_track.append(str(first_audio_index))
            print(f'选择音频轨道 {copy_audio_track}，字幕轨道 {copy_sub_track}')
            meta_folder = os.path.join(os.path.join(mpls_path[:-19], 'META', 'DL'))
            cover = ''
            cover_size = 0
            if not os.path.exists(meta_folder):
                output_name = os.path.split(mpls_path[:-24])[-1]
            else:
                for filename in os.listdir(meta_folder):
                    if filename.endswith('.jpg') or filename.endswith('.JPG') or filename.endswith(
                            '.JPEG') or filename.endswith('.jpeg') or filename.endswith('.png') or filename.endswith(
                        '.PNG'):
                        if os.path.getsize(os.path.join(meta_folder, filename)) > cover_size:
                            cover = os.path.join(meta_folder, filename)
                            cover_size = os.path.getsize(os.path.join(meta_folder, filename))
                output_name = ''
                for filename in os.listdir(meta_folder):
                    if filename == 'bdmt_eng.xml':
                        try:
                            tree = et.parse(os.path.join(meta_folder, filename))
                            _folder = tree.getroot()
                            ns = {'di': 'urn:BDA:bdmv;discinfo'}
                            output_name = _folder.find('.//di:name', ns).text
                            break
                        except (et.ParseError, FileNotFoundError):
                            continue
                if not output_name:
                    for filename in os.listdir(meta_folder):
                        if filename == 'bdmt_zho.xml':
                            try:
                                tree = et.parse(os.path.join(meta_folder, filename))
                                _folder = tree.getroot()
                                ns = {'di': 'urn:BDA:bdmv;discinfo'}
                                output_name = _folder.find('.//di:name', ns).text
                                break
                            except (et.ParseError, FileNotFoundError):
                                continue
                if not output_name:
                    for filename in os.listdir(meta_folder):
                        try:
                            tree = et.parse(os.path.join(meta_folder, filename))
                            _folder = tree.getroot()
                            ns = {'di': 'urn:BDA:bdmv;discinfo'}
                            output_name = _folder.find('.//di:name', ns).text
                            break
                        except (et.ParseError, FileNotFoundError):
                            continue
                if not output_name:
                    output_name = os.path.split(mpls_path[:-24])[-1]
            char_map = {
                '?': '？',
                '*': '★',
                '<': '《',
                '>': '》',
                ':': '：',
                '"': "'",
                '/': '／',
                '\\': '／',
                '|': '￨'
            }
            output_name = ''.join(char_map.get(char) or char for char in output_name)
            if cover:
                print(f"找到封面图片 ｢{cover}｣")
            print(f'输出文件名{output_name}.mkv')

            chapter_split = ','.join(map(str, [conf['chapter_index'] for conf in confs]))
            bdmv_vol = '0' * (3 - len(str(bdmv_index))) + str(bdmv_index)
            output_file = f'{os.path.join(dst_folder, output_name)}_BD_Vol_{bdmv_vol}.mkv'
            remux_cmd = (f'"{MKV_MERGE_PATH}" --split chapters:{chapter_split} -o "{output_file}" '
                         f'{("-a " + ",".join(copy_audio_track)) if copy_audio_track else ""} '
                         f'{("-s " + ",".join(copy_sub_track)) if copy_sub_track else ""} '
                         f'{(" --attachment-name Cover.jpg" + " --attach-file " + "\"" + cover + "\"") if cover else ""}  '
                         f'"{mpls_path}"')
            print(f'混流命令: {remux_cmd}')
            self._progress(text=f'混流中：BD_Vol_{bdmv_vol}')
            subprocess.Popen(remux_cmd, shell=True).wait()
            self._progress(int(idx / max(len(bdmv_index_list), 1) * 300))

        self.checked = True
        mkv_files_after = []
        try:
            mkv_files_after = [f for f in os.listdir(dst_folder) if f.lower().endswith('.mkv')]
        except Exception:
            mkv_files_after = []
        created = [os.path.join(dst_folder, f) for f in mkv_files_after if f not in mkv_files_before]
        if created:
            mkv_files = sorted(created, key=mkv_sort_key)
        else:
            mkv_files = sorted([os.path.join(dst_folder, f) for f in mkv_files_after], key=mkv_sort_key)
        if cancel_event and cancel_event.is_set():
            raise _Cancelled()
        self._progress(310, '写入章节中')
        self.add_chapter_to_mkv(mkv_files, table, selected_mpls=selected_mpls)
        self._progress(400)

        i = 0
        for mkv_file in mkv_files:
            if cancel_event and cancel_event.is_set():
                raise _Cancelled()
            i += 1
            self._progress(text=f'压制并混流：{os.path.basename(mkv_file)}')
            vpy_path = None
            if vpy_paths and 0 <= (i - 1) < len(vpy_paths):
                vpy_path = vpy_paths[i - 1]
            if not vpy_path:
                vpy_path = os.path.join(os.getcwd(), 'vpy.vpy')
            self.encode_task(mkv_file, dst_folder, i, vpy_path, vspipe_mode, x265_mode, x265_params, sub_pack_mode)
            if sub_pack_mode == 'external' and self.sub_files and len(self.sub_files) >= i and i > -1:
                sub_src = self.sub_files[i - 1]
                sub_ext = os.path.splitext(sub_src)[1].lower()
                if sub_ext in ('.ass', '.ssa', '.srt'):
                    video_base = os.path.splitext(os.path.basename(mkv_file))[0]
                    sub_dst = os.path.join(dst_folder, video_base + sub_ext)
                    try:
                        shutil.copy2(sub_src, sub_dst)
                    except Exception:
                        traceback.print_exc()
            self._progress(400 + int(400 * i / len(mkv_files)))

        sps_folder = dst_folder + os.sep + 'SPs'
        os.mkdir(sps_folder)
        self._progress(900, '处理 SPs 音轨')

        if sp_entries:
            sp_index_by_bdmv: dict[int, int] = {}
            total_sp = len(sp_entries) or 1
            for idx, entry in enumerate(sp_entries, start=1):
                if cancel_event and cancel_event.is_set():
                    raise _Cancelled()
                try:
                    sp_bdmv_index = int(entry.get('bdmv_index') or 0)
                except Exception:
                    sp_bdmv_index = 0
                if sp_bdmv_index <= 0 or sp_bdmv_index not in bdmv_index_conf:
                    continue
                bdmv_vol = '0' * (3 - len(str(sp_bdmv_index))) + str(sp_bdmv_index)
                confs = bdmv_index_conf[sp_bdmv_index]
                main_mpls_path = confs[0]['selected_mpls'] + '.mpls'
                playlist_dir = os.path.dirname(main_mpls_path)
                stream_dir = os.path.join(os.path.dirname(playlist_dir), 'STREAM')

                mpls_file = str(entry.get('mpls_file') or '').strip()
                m2ts_file = str(entry.get('m2ts_file') or '').strip()

                sp_mkv_path = None
                if mpls_file:
                    sp_index_by_bdmv[sp_bdmv_index] = sp_index_by_bdmv.get(sp_bdmv_index, 0) + 1
                    sp_mkv_path = os.path.join(sps_folder, f'BD_Vol_{bdmv_vol}_SP0{sp_index_by_bdmv[sp_bdmv_index]}.mkv')
                    mpls_file_path = os.path.join(playlist_dir, mpls_file)
                    subprocess.Popen(f'"{MKV_MERGE_PATH}" -o "{sp_mkv_path}" "{mpls_file_path}"', shell=True).wait()
                else:
                    m2ts_files = [x.strip() for x in m2ts_file.split(',') if x.strip()]
                    if m2ts_files:
                        m2ts_name = m2ts_files[0]
                        sp_mkv_path = os.path.join(sps_folder, f'BD_Vol_{bdmv_vol}_{m2ts_name[:-5]}.mkv')
                        subprocess.Popen(
                            f'"{MKV_MERGE_PATH}" -o "{sp_mkv_path}" "{os.path.join(stream_dir, m2ts_name)}"',
                            shell=True
                        ).wait()

                if not sp_mkv_path or not os.path.exists(sp_mkv_path):
                    continue
                self._progress(text=f'压制并混流 SPs：{os.path.basename(sp_mkv_path)}')
                if sp_vpy_paths and 0 <= (idx - 1) < len(sp_vpy_paths) and sp_vpy_paths[idx - 1]:
                    cur_sp_vpy = str(sp_vpy_paths[idx - 1])
                else:
                    cur_sp_vpy = os.path.join(os.getcwd(), 'vpy.vpy')
                self.encode_task(sp_mkv_path, sps_folder, -1, cur_sp_vpy, vspipe_mode, x265_mode, x265_params, 'external')
                self._progress(900 + int(90 * idx / total_sp))
        else:
            for bdmv_index, confs in bdmv_index_conf.items():
                if cancel_event and cancel_event.is_set():
                    raise _Cancelled()
                bdmv_vol = '0' * (3 - len(str(bdmv_index))) + str(bdmv_index)
                mpls_path = confs[0]['selected_mpls'] + '.mpls'
                index_to_m2ts, index_to_offset = get_index_to_m2ts_and_offset(Chapter(mpls_path))
                parsed_m2ts_files = set(index_to_m2ts.values())
                sp_index = 0
                for mpls_file in os.listdir(os.path.dirname(mpls_path)):
                    if cancel_event and cancel_event.is_set():
                        raise _Cancelled()
                    if not mpls_file.endswith('.mpls'):
                        continue
                    mpls_file_path = os.path.join(os.path.dirname(mpls_path), mpls_file)
                    if mpls_file_path != mpls_path:
                        index_to_m2ts, index_to_offset = get_index_to_m2ts_and_offset(Chapter(mpls_file_path))
                        if not (parsed_m2ts_files & set(index_to_m2ts.values())):
                            if len(index_to_m2ts) > 1:
                                sp_index += 1
                                subprocess.Popen(f'"{MKV_MERGE_PATH}" -o "{sps_folder}{os.sep}BD_Vol_'
                                                 f'{bdmv_vol}_SP0{sp_index}.mkv" "{mpls_file_path}"', shell=True).wait()
                                parsed_m2ts_files |= set(index_to_m2ts.values())
                stream_folder = os.path.dirname(mpls_path).removesuffix('PLAYLIST') + 'STREAM'
                for stream_file in os.listdir(stream_folder):
                    if cancel_event and cancel_event.is_set():
                        raise _Cancelled()
                    if stream_file not in parsed_m2ts_files and stream_file.endswith('.m2ts'):
                        if M2TS(os.path.join(stream_folder, stream_file)).get_duration() > 30 * 90000:
                            subprocess.Popen(f'"{MKV_MERGE_PATH}" -o "{sps_folder}{os.sep}BD_Vol_'
                                             f'{bdmv_vol}_{stream_file[:-5]}.mkv" '
                                             f'"{os.path.join(stream_folder, stream_file)}"', shell=True).wait()
            sp_files = [os.path.join(sps_folder, sp) for sp in os.listdir(sps_folder) if sp.endswith('.mkv')]
            sp_files.sort()
            total_sp = len(sp_files) or 1
            for idx, sp_path in enumerate(sp_files, start=1):
                if cancel_event and cancel_event.is_set():
                    raise _Cancelled()
                self._progress(text=f'压制并混流 SPs：{os.path.basename(sp_path)}')
                if sp_vpy_paths and 0 <= (idx - 1) < len(sp_vpy_paths) and sp_vpy_paths[idx - 1]:
                    cur_sp_vpy = sp_vpy_paths[idx - 1]
                else:
                    cur_sp_vpy = os.path.join(os.getcwd(), 'vpy.vpy')
                self.encode_task(sp_path, sps_folder, -1, cur_sp_vpy, vspipe_mode, x265_mode, x265_params, 'external')
                self._progress(900 + int(90 * idx / total_sp))

        self.completion()
        self._progress(1000, '完成')

    def process_audio_to_flac(self, output_file, dst_folder, i) -> tuple[int, dict[int, str], list[str]]:
        dolby_truehd_tracks = []
        track_bits = {}
        track_id_delay_map = {}
        if os.path.exists(output_file):
            subprocess.Popen(f'"{FFPROBE_PATH}" -v error -show_streams -show_format -of json "{output_file}" >info.json 2>&1',
                             shell=True).wait()
            with open('info.json', 'r', encoding='utf-8') as fp:
                data = json.load(fp)
            for stream in data['streams']:
                try:
                    delay_val = float(stream.get('start_time', 0.0))
                except Exception:
                    delay_val = 0.0
                if abs(delay_val) > 1e-6:
                    track_id_delay_map[stream['index']] = delay_val
                if stream['codec_name'] == 'truehd' and stream.get('profile') == 'Dolby TrueHD + Dolby Atmos':
                    dolby_truehd_tracks.append(stream['index'])
                if stream['codec_name'] in ('truehd', 'dts'):
                    track_bits[stream['index']] = int(stream.get('bits_per_raw_sample') or 24)
        else:
            print('\033[31m错误，电影混流失败，请检查任务输出\033[0m')
        track_count, track_info = self.extract_lossless(output_file, dolby_truehd_tracks)
        if track_info:
            ext_fn_map = {}
            for file1 in os.listdir(dst_folder):
                file1_path = os.path.join(dst_folder, file1)
                if file1_path != output_file and not file1_path.endswith('.mkv') and '.track' in file1:
                    ext = file1_path.split('.')[-1]
                    if ext in ext_fn_map:
                        ext_fn_map[ext].append(file1_path)
                    else:
                        ext_fn_map[ext] = [file1_path]
            for ext, fns in ext_fn_map.items():
                if len(fns) > 1:
                    fpts = []
                    for fn in fns:
                        tmp_wav = None
                        fp_source = fn
                        try:
                            if ext not in ('wav', 'w64', 'flac'):
                                tmp_wav = os.path.splitext(fn)[0] + '.fp.wav'
                                subprocess.Popen(
                                    f'"{FFMPEG_PATH}" -hide_banner -loglevel error -y -ss 60 -t 30 -i "{fn}" '
                                    f'-ac 1 -ar 11025 -c:a pcm_s16le "{tmp_wav}"',
                                    shell=True
                                ).wait()
                                if os.path.exists(tmp_wav):
                                    fp_source = tmp_wav
                            y, sr = librosa.load(fp_source, sr=None, mono=True)
                            chroma = librosa.feature.chroma_stft(y=y, sr=sr)
                            fpt = np.mean(chroma, axis=1)
                        except Exception:
                            if tmp_wav and os.path.exists(tmp_wav):
                                try:
                                    os.remove(tmp_wav)
                                except Exception:
                                    pass
                            continue
                        finally:
                            if tmp_wav and os.path.exists(tmp_wav):
                                try:
                                    os.remove(tmp_wav)
                                except Exception:
                                    pass
                        duplicate_track = False
                        for _fpt in fpts:
                            denom = (np.linalg.norm(fpt) * np.linalg.norm(_fpt))
                            if denom and (np.dot(fpt, _fpt) / denom) > 0.998:
                                os.remove(fn)
                                track_id = int(os.path.split(fn)[-1].split('.')[-2].removeprefix('track'))
                                track_info.pop(track_id, None)
                                print(f'找到一个重复音轨 ｢{fn}｣，已删除')
                                duplicate_track = True
                                break
                        if not duplicate_track:
                            fpts.append(fpt)

            def _is_silent_audio(path: str, threshold_db: float = -60.0) -> tuple[bool, float]:
                y = None
                sr = None
                if soundfile is not None:
                    try:
                        info = soundfile.info(path)
                        frames = min(int(info.frames), int(info.samplerate) * 30)
                        start = int(info.frames) // 2 if int(info.frames) > (frames * 2) else 0
                        data, sr = soundfile.read(path, start=start, frames=frames, dtype='float32', always_2d=True)
                        y = data.mean(axis=1)
                    except Exception:
                        y = None

                if y is None:
                    fd, tmp = tempfile.mkstemp(prefix=f"temp_sil_{os.getpid()}_", suffix=".wav")
                    os.close(fd)
                    try:
                        subprocess.run(
                            f'"{FFMPEG_PATH}" -hide_banner -loglevel error -y -i "{path}" '
                            f'-ac 1 -ar 22050 -c:a pcm_s16le "{tmp}"',
                            shell=True,
                            check=True
                        )
                        if soundfile is None:
                            y, sr = librosa.load(tmp, sr=None, mono=True)
                        else:
                            data, sr = soundfile.read(tmp, dtype='float32', always_2d=True)
                            y = data.mean(axis=1)
                    finally:
                        if os.path.exists(tmp):
                            try:
                                os.remove(tmp)
                            except Exception:
                                pass
                rms = librosa.feature.rms(y=y)
                db = librosa.amplitude_to_db(rms, ref=np.max)
                avg_db = float(np.mean(db))
                return avg_db < threshold_db, avg_db

            for file1 in os.listdir(dst_folder):
                file1_path = os.path.join(dst_folder, file1)
                if (file1_path != output_file and not file1_path.endswith('.mkv') and not file1_path.endswith('.lwi')
                        and not file1_path.endswith('.hevc') and not file1_path.endswith('.ass')
                        and not file1_path.endswith('.ssa') and not file1_path.endswith('.srt')):
                    try:
                        silent, avg_db = _is_silent_audio(file1_path, -60.0)
                    except Exception:
                        silent = False
                        avg_db = 0.0
                    if silent:
                        try:
                            os.remove(file1_path)
                        except Exception:
                            pass
                        try:
                            track_id = int(os.path.split(file1_path)[-1].split('.')[-2].removeprefix('track'))
                            track_info.pop(track_id, None)
                        except Exception:
                            pass
                        print(f'检测到空音轨 ｢{file1_path}｣ 平均 {avg_db:.1f} dB，已删除')
                        continue
                    print(f'正在压缩音轨 ｢{file1_path}｣')
                    track_id = int(os.path.split(file1_path)[-1].split('.')[-2].removeprefix('track'))
                    if track_id in track_id_delay_map:
                        delay_sec = track_id_delay_map[track_id]
                        delay_ms = int(round(delay_sec * 1000.0))
                        print(f'检测到文件 ｢{file1_path}｣ 有延迟 {delay_ms} ms')
                        output_fn = os.path.splitext(file1_path)[0] + '.delayfix.wav'
                        fix_audio_delay_to_lossless(file1_path, delay_ms, output_fn)
                        if os.path.exists(output_fn):
                            try:
                                os.remove(file1_path)
                            except Exception:
                                pass
                            file1_path = output_fn

                    if file1_path.endswith('.wav'):
                        bits = track_bits.get(track_id, 16)
                        effective_bits = get_effective_bit_depth(file1_path)
                        if effective_bits < bits:
                            print(f"检测到文件 ｢{file1_path}｣ 有效位深较低，正在优化为 16-bit...")
                            codec = "pcm_s16le"
                            output_fn = os.path.splitext(file1_path)[0] + '(1).wav'
                            cmd = f'"{FFMPEG_PATH}" -hide_banner -loglevel error -i "{file1_path}" -c:a {codec} "{output_fn}" -y'
                            subprocess.run(cmd, shell=True, check=True)
                            if os.path.exists(output_fn):
                                print(f"转换完成: ｢{output_fn}｣")
                                os.remove(file1_path)
                                os.rename(output_fn, file1_path)

                        flac_file = os.path.splitext(file1_path)[0] + '.flac'
                        subprocess.Popen(f'"{FLAC_PATH}" -8 -j {FLAC_THREADS} "{file1_path}" -o "{flac_file}"', shell=True).wait()
                        if os.path.exists(flac_file):
                            delta = os.path.getsize(file1_path) - os.path.getsize(flac_file)
                            os.remove(file1_path)
                            print(f'将音轨 ｢{file1_path}｣ 压缩成flac，减小体积 {delta / 1024 ** 2:.3f} MiB')
                        else:
                            subprocess.Popen(f'{FFMPEG_PATH} -i "{file1_path}" -c:a flac "{flac_file}"', shell=True).wait()
                            if os.path.exists(flac_file):
                                delta = os.path.getsize(file1_path) - os.path.getsize(flac_file)
                                os.remove(file1_path)
                                print(f'将音轨 ｢{file1_path}｣ 用ffmpeg压缩成flac，减小体积 {delta / 1024 ** 2:.3f} MiB')
                    else:
                        bits = track_bits.get(track_id, 24)
                        effective_bits = get_compressed_effective_depth(file1_path)
                        if effective_bits < bits:
                            print(f'检测到文件 ｢{file1_path}｣ 实际有效位深为 {effective_bits} bits')
                        wav_file = os.path.splitext(file1_path)[0] + '.wav'
                        subprocess.Popen(f'{FFMPEG_PATH} -i "{file1_path}"  -c:a pcm_s{effective_bits}le -f w64 "{wav_file}"', shell=True).wait()
                        flac_file = os.path.splitext(file1_path)[0] + '.flac'
                        subprocess.Popen(f'{FLAC_PATH} -8 -j {FLAC_THREADS} "{wav_file}" -o "{flac_file}"', shell=True).wait()
                        if os.path.exists(flac_file):
                            if os.path.getsize(flac_file) > os.path.getsize(file1_path):
                                print(f'flac 文件比原音轨大，将删除 ｢{flac_file}｣')
                                os.remove(flac_file)
                            else:
                                delta = os.path.getsize(file1_path) - os.path.getsize(flac_file)
                                print(f'将音轨 ｢{file1_path}｣ 压缩成flac，减小体积 {delta / 1024 ** 2:.3f} MiB')
                        else:
                            subprocess.Popen(f'{FFMPEG_PATH} -i "{wav_file}" -c:a flac "{flac_file}"', shell=True).wait()
                            if os.path.exists(flac_file):
                                if os.path.getsize(flac_file) > os.path.getsize(file1_path):
                                    print(f'ffmpeg 压缩的flac文件比原音轨大，将删除 ｢{flac_file}｣')
                                    os.remove(flac_file)
                                else:
                                    delta = os.path.getsize(file1_path) - os.path.getsize(flac_file)
                                    print(f'将音轨 ｢{file1_path}｣ 用ffmpeg压缩成flac，减小体积 {delta / 1024 ** 2:.3f} MiB')
                            else:
                                print('\033[31m错误，ffmpeg压缩也失败\033[0m')
                        os.remove(file1_path)
                        os.remove(wav_file)
            flac_files = []
            for file1 in os.listdir(dst_folder):
                file1_path = os.path.join(dst_folder, file1)
                if file1_path.endswith('.flac'):
                    flac_files.append(file1_path)
            if not flac_files:
                for file1 in os.listdir(dst_folder):
                    file1_path = os.path.join(dst_folder, file1)
                    if file1_path != output_file:
                        if file1_path.endswith('.wav'):
                            n = len(os.listdir(dst_folder))
                            print(f'flac 压缩 wav 文件 ｢{file1_path}｣ 失败，将使用 ffmpeg 压缩')
                            subprocess.Popen(
                                f'{FFMPEG_PATH} -i "{file1_path}" -c:a flac "{file1_path.removesuffix(".wav") + ".flac"}"', shell=True).wait()
                            if len(os.listdir(dst_folder)) > n:
                                os.remove(file1_path)
                for file1 in os.listdir(dst_folder):
                    file1_path = os.path.join(dst_folder, file1)
                    if file1_path.endswith('.flac'):
                        flac_files.append(file1_path)
        return track_count, track_info, flac_files

    def flac_task(self, output_file, dst_folder, i):
        track_count, track_info, flac_files = self.process_audio_to_flac(output_file, dst_folder, i)
        if flac_files:
            output_file1 = os.path.join(dst_folder, os.path.splitext(output_file)[0] + '(1).mkv')
            remux_cmd = self.generate_remux_cmd(track_count, track_info, flac_files, output_file1, output_file)
            if self.sub_files and len(self.sub_files) >= i and i > -1:
                remux_cmd += f' --language 0:chi "{self.sub_files[i - 1]}"'
            print(f'混流命令：{remux_cmd}')
            subprocess.Popen(remux_cmd, shell=True).wait()
            if os.path.getsize(output_file1) > os.path.getsize(output_file):
                os.remove(output_file1)
            else:
                os.remove(output_file)
                os.rename(output_file1, output_file)
            for flac_file in flac_files:
                os.remove(flac_file)

    def encode_task(self, output_file, dst_folder, i, vpy_path: str, vspipe_mode: str, x265_mode: str, x265_params: str, sub_pack_mode: str):
        def update_vpy_script():
            if not os.path.exists(vpy_path):
                return
            try:
                with open(vpy_path, 'r', encoding='utf-8') as fp:
                    lines = fp.readlines()
            except Exception:
                traceback.print_exc()
                return

            mkv_real_path = os.path.normpath(output_file)
            subtitle_real_path = None
            if self.sub_files and len(self.sub_files) >= i and i > -1:
                subtitle_real_path = os.path.normpath(self.sub_files[i - 1])

            def _to_py_r_string(value: str) -> str:
                return 'r"' + value.replace('"', '\\"') + '"'

            updated = False
            new_lines = []
            for line in lines:
                stripped = line.lstrip()
                if stripped.startswith('a ='):
                    indent = line[:len(line) - len(stripped)]
                    comment = ''
                    if '#' in stripped:
                        comment = ' #' + stripped.split('#', 1)[1].rstrip('\n')
                    new_lines.append(f'{indent}a = {_to_py_r_string(mkv_real_path)}{comment}\n')
                    updated = True
                    continue

                if subtitle_real_path and stripped.startswith('sub_file =') and not stripped.startswith('#'):
                    indent = line[:len(line) - len(stripped)]
                    comment = ''
                    if '#' in stripped:
                        comment = ' #' + stripped.split('#', 1)[1].rstrip('\n')
                    new_lines.append(f'{indent}sub_file = {_to_py_r_string(subtitle_real_path)}{comment}\n')
                    updated = True
                    continue

                new_lines.append(line)

            if not updated:
                return
            try:
                with open(vpy_path, 'w', encoding='utf-8') as fp:
                    fp.writelines(new_lines)
            except Exception:
                traceback.print_exc()

        update_vpy_script()

        def cleanup_lwi_for_source(source_path: str):
            for suffix in ('.lwi', '.lwi.lock'):
                try:
                    p = source_path + suffix
                    if os.path.exists(p) and os.path.isfile(p):
                        os.remove(p)
                except Exception:
                    traceback.print_exc()

        if vspipe_mode == 'bundle':
            vspipe_exe, vspipe_env = get_vspipe_context()
        else:
            vspipe_exe, vspipe_env = 'vspipe.exe', None
            if sys.platform != 'win32':
                vspipe_exe = 'vspipe'
        if x265_mode == 'bundle':
            x265_exe = X265_PATH
        else:
            x265_exe = 'x265.exe' if sys.platform == 'win32' else 'x265'
        hevc_file = os.path.join(dst_folder, os.path.splitext(os.path.basename(output_file))[0] + '.hevc')
        cmd = f'"{vspipe_exe}" --y4m "{vpy_path}" - | "{x265_exe}" {x265_params or ""} --y4m -D 10 -o "{hevc_file}" -'
        print(f'压制命令：{cmd}')
        subprocess.Popen(cmd, shell=True, env=vspipe_env).wait()
        cleanup_lwi_for_source(output_file)
        track_count, track_info, flac_files = self.process_audio_to_flac(output_file, dst_folder, i)
        if flac_files or os.path.exists(hevc_file):
            output_file1 = os.path.join(dst_folder, os.path.splitext(output_file)[0] + '(1).mkv')
            remux_cmd = self.generate_remux_cmd(track_count, track_info, flac_files, output_file1, output_file,
                                                hevc_file=hevc_file if os.path.exists(hevc_file) else None)
            if sub_pack_mode == 'soft':
                if self.sub_files and len(self.sub_files) >= i and i > -1:
                    remux_cmd += f' --language 0:chi "{self.sub_files[i - 1]}"'
            print(f'混流命令：{remux_cmd}')
            subprocess.Popen(remux_cmd, shell=True).wait()
            if os.path.getsize(output_file1) > os.path.getsize(output_file):
                os.remove(output_file1)
            else:
                os.remove(output_file)
                os.rename(output_file1, output_file)
            for flac_file in flac_files:
                os.remove(flac_file)
            if os.path.exists(hevc_file):
                os.remove(hevc_file)
        cleanup_lwi_for_source(output_file)

    def generate_remux_cmd(self, track_count, track_info, flac_files, output_file, mkv_file, hevc_file: Optional[str] = None):
        tracker_order = []
        audio_tracks = []
        pcm_track_count = 0
        language_options = []
        for _ in range(track_count + 1):
            if _ in track_info:
                pcm_track_count += 1
                try:
                    language_options.append(f'--language 0:{track_info[_]} "{flac_files[pcm_track_count - 1]}"')
                except IndexError:
                    continue
                audio_tracks.append(str(_))
                tracker_order.append(f'{pcm_track_count}:0')
            else:
                tracker_order.append(f'0:{_}')
        tracker_order = ','.join(tracker_order)
        audio_track_num = len(audio_tracks)
        audio_tracks = '!' + ','.join(audio_tracks)
        language_options = ' '.join(language_options)
        if not hevc_file:
            return (f'"{MKV_MERGE_PATH}" -o "{output_file}" --track-order {tracker_order} '
                    f'-a {audio_tracks} "{mkv_file}" {language_options}')
        else:
            tracker_order = f'{audio_track_num + 1}:0,{tracker_order}'
            return (f'"{MKV_MERGE_PATH}" -o "{output_file}" --track-order {tracker_order} '
                    f'-d !0 -a {audio_tracks} "{mkv_file}" {language_options} "{hevc_file}"')

    def extract_lossless(self, mkv_file: str, dolby_truehd_tracks: list[int]) -> tuple[int, dict[int, str]]:
        if sys.platform == 'win32':
            process = subprocess.Popen(f'"{MKV_INFO_PATH}" "{mkv_file}" --ui-language en',
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                       encoding='utf-8', errors='ignore', shell=True)
        else:
            process = subprocess.Popen(f'"{MKV_INFO_PATH}" "{mkv_file}" --ui-language en_US',
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                       encoding='utf-8', errors='ignore', shell=True)
        stdout, stderr = process.communicate()

        track_info = {}
        track_count = 0
        track_suffix_info = {}
        for line in stdout.splitlines():
            if line.startswith('|  + Track number: '):
                track_id = int(re.findall(r'\d+', line.removeprefix('|  + Track number: '))[0]) - 1
                track_count = max(track_count, track_id)
            if line.startswith('|  + Codec ID: '):
                codec_id = line.removeprefix('|  + Codec ID: ').strip()
                code_id_to_stream_type = {'A_DTS': 'DTS', 'A_PCM/INT/LIT': 'LPCM', 'A_PCM/INT/BIG': 'LPCM',
                                          'A_TRUEHD': 'TRUEHD', 'A_MLP': 'TRUEHD'}
                stream_type = code_id_to_stream_type.get(codec_id)
            if line.startswith('|  + Language (IETF BCP 47): '):
                bcp_47_code = line.removeprefix('|  + Language (IETF BCP 47): ').strip()
                language = pycountry.languages.get(alpha_2=bcp_47_code.split('-')[0])
                if language is None:
                    language = pycountry.languages.get(alpha_3=bcp_47_code.split('-')[0])
                if language:
                    lang = getattr(language, "bibliographic", getattr(language, "alpha_3", None))
                else:
                    lang = 'und'
                if stream_type in ('LPCM', 'DTS', 'TRUEHD'):
                    if track_id not in dolby_truehd_tracks:
                        track_info[track_id] = lang
                        if stream_type == 'LPCM':
                            track_suffix_info[track_id] = 'wav'
                        elif stream_type == 'DTS':
                            track_suffix_info[track_id] = 'dts'
                        else:
                            track_suffix_info[track_id] = 'thd'

        if track_info:
            extract_info = []
            for track_id, lang in track_info.items():
                extract_info.append(
                    f'{track_id}:"{mkv_file.removesuffix(".mkv")}.track{track_id}.{track_suffix_info[track_id]}"')
            extract_cmd = f'"{MKV_EXTRACT_PATH}" "{mkv_file}" tracks {" ".join(extract_info)}'
            print(f'正在提取无损音轨，命令: {extract_cmd}')
            subprocess.Popen(extract_cmd, shell=True).wait()

        return track_count, track_info


class FilePathTableWidgetItem(QTableWidgetItem):
    def __lt__(self, other):
        if isinstance(other, QTableWidgetItem):
            left = os.path.basename(self.text()).lower() if self.text() else ''
            right = os.path.basename(other.text()).lower() if other.text() else ''
            return left < right
        return super().__lt__(other)


class CustomTableWidget(QTableWidget):
    def __init__(self, parent: Optional[QWidget]=None, on_drop: Optional[Callable]=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragEnabled(True)
        self.setSelectionMode(self.selectionMode().MultiSelection)
        self.target_row = -1
        self.on_drop = on_drop

    def dragMoveEvent(self, event: QDragMoveEvent):
        if event.mimeData().hasFormat('application/x-qabstractitemmodeldatalist'):
            row = self.rowAt(int(event.position().y()))
            if row != self.target_row:
                self.target_row = row
                self.viewport().update()
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        if event.source() is self and event.mimeData().hasFormat('application/x-qabstractitemmodeldatalist'):
            drag_row = self.currentRow()
            drop_row = self.rowAt(int(event.position().y()))
            if drop_row < 0:
                drop_row = self.rowCount()
            if drag_row != drop_row:
                items = [self.takeItem(drag_row, col) for col in range(self.columnCount())]
                self.insertRow(drop_row)
                [self.setItem(drop_row, col, item) for col, item in enumerate(items) if item]
                self.removeRow(drag_row if drag_row < drop_row else drag_row + 1)
                self.target_row = -1
                self.viewport().update()
                event.acceptProposedAction()
            event.accept()
            self.on_drop()
        else:
            super().dropEvent(event)

    def paintEvent(self, event: QPaintEvent):
        super().paintEvent(event)
        if self.target_row >= 0:
            rect1 = self.visualRect(self.indexFromItem(self.item(self.target_row, 0)))
            rect2 = self.visualRect(self.indexFromItem(self.item(self.target_row, self.columnCount() - 1)))
            painter = QPainter(self.viewport())
            painter.setPen(QColor(10, 240, 10))
            painter.drawLine(rect1.topLeft().x(), rect1.topLeft().y(), rect2.bottomRight().x(), rect2.topLeft().y())


class _Cancelled(Exception):
    pass


class RemuxWorker(QObject):
    progress = pyqtSignal(int)
    label = pyqtSignal(str)
    finished = pyqtSignal()
    canceled = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, bdmv_path: str, sub_files: list[str], checked: bool, output_folder: str,
                 configuration: dict[int, dict[str, int | str]], selected_mpls: list[tuple[str, str]],
                 cancel_event: threading.Event):
        super().__init__()
        self.bdmv_path = bdmv_path
        self.sub_files = sub_files
        self.checked = checked
        self.output_folder = output_folder
        self.configuration = configuration
        self.selected_mpls = selected_mpls
        self.cancel_event = cancel_event

    def run(self):
        try:
            def progress_cb(value: Optional[int] = None, text: Optional[str] = None):
                if value is not None:
                    self.progress.emit(int(value))
                if text:
                    self.label.emit(str(text))
                if self.cancel_event.is_set():
                    raise _Cancelled()

            bs = BluraySubtitle(self.bdmv_path, self.sub_files, self.checked, progress_cb)
            bs.configuration = self.configuration
            bs.episodes_remux(
                None,
                self.output_folder,
                selected_mpls=self.selected_mpls,
                configuration=self.configuration,
                cancel_event=self.cancel_event,
                ensure_tools=False
            )
        except _Cancelled:
            self.canceled.emit()
        except Exception:
            self.failed.emit(traceback.format_exc())
        else:
            self.finished.emit()

class EncodeWorker(QObject):
    progress = pyqtSignal(int)
    label = pyqtSignal(str)
    finished = pyqtSignal()
    canceled = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, bdmv_path: str, sub_files: list[str], checked: bool, output_folder: str,
                 configuration: dict[int, dict[str, int | str]], selected_mpls: list[tuple[str, str]],
                 cancel_event: threading.Event, vpy_paths: list[str], sp_vpy_paths: list[str], sp_entries: list[dict[str, int | str]],
                 vspipe_mode: str, x265_mode: str, x265_params: str, sub_pack_mode: str):
        super().__init__()
        self.bdmv_path = bdmv_path
        self.sub_files = sub_files
        self.checked = checked
        self.output_folder = output_folder
        self.configuration = configuration
        self.selected_mpls = selected_mpls
        self.cancel_event = cancel_event
        self.vpy_paths = vpy_paths
        self.sp_vpy_paths = sp_vpy_paths
        self.sp_entries = sp_entries
        self.vspipe_mode = vspipe_mode
        self.x265_mode = x265_mode
        self.x265_params = x265_params
        self.sub_pack_mode = sub_pack_mode

    def run(self):
        try:
            def progress_cb(value: Optional[int] = None, text: Optional[str] = None):
                if value is not None:
                    self.progress.emit(int(value))
                if text:
                    self.label.emit(str(text))
                if self.cancel_event.is_set():
                    raise _Cancelled()

            bs = BluraySubtitle(self.bdmv_path, self.sub_files, self.checked, progress_cb)
            bs.configuration = self.configuration
            bs.episodes_encode(
                None,
                self.output_folder,
                selected_mpls=self.selected_mpls,
                configuration=self.configuration,
                cancel_event=self.cancel_event,
                ensure_tools=False,
                vpy_paths=self.vpy_paths,
                sp_vpy_paths=self.sp_vpy_paths,
                sp_entries=self.sp_entries,
                vspipe_mode=self.vspipe_mode,
                x265_mode=self.x265_mode,
                x265_params=self.x265_params,
                sub_pack_mode=self.sub_pack_mode
            )
        except _Cancelled:
            self.canceled.emit()
        except Exception:
            self.failed.emit(traceback.format_exc())
        else:
            self.finished.emit()


class MergeWorker(QObject):
    progress = pyqtSignal(int)
    label = pyqtSignal(str)
    finished = pyqtSignal()
    canceled = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, bdmv_path: str, sub_files: list[str], checked: bool,
                 selected_mpls: list[tuple[str, str]], cancel_event: threading.Event):
        super().__init__()
        self.bdmv_path = bdmv_path
        self.sub_files = sub_files
        self.checked = checked
        self.selected_mpls = selected_mpls
        self.cancel_event = cancel_event

    def run(self):
        try:
            def progress_cb(value: Optional[int] = None, text: Optional[str] = None):
                if value is not None:
                    self.progress.emit(int(value))
                if text:
                    self.label.emit(str(text))
                if self.cancel_event.is_set():
                    raise _Cancelled()

            progress_cb(text='准备中')
            bs = BluraySubtitle(self.bdmv_path, self.sub_files, self.checked, progress_cb)
            
            # 根据平台选择字幕加载策略
            if self.sub_files:
                progress_cb(text='加载字幕')
                if sys.platform == 'win32':
                    # Windows下使用多进程
                    try:
                        bs._preload_subtitles_multiprocess(self.sub_files, self.cancel_event)
                    except Exception as e:
                        print(f'多进程加载失败，切换到单进程: {str(e)}')
                        # 回退到单进程
                        for p in self.sub_files:
                            if self.cancel_event.is_set():
                                raise _Cancelled()
                            try:
                                bs._subtitle_cache[p] = Subtitle(p)
                            except Exception as e2:
                                print(f'字幕文件加载失败 ｢{p}｣: {str(e2)}')
                else:
                    # Linux下尝试多进程，失败则回退到单进程
                    try:
                        bs._preload_subtitles_multiprocess(self.sub_files, self.cancel_event)
                    except Exception as e:
                        print(f'多进程加载失败，切换到单进程: {str(e)}')
                        # 回退到单进程
                        for p in self.sub_files:
                            if self.cancel_event.is_set():
                                raise _Cancelled()
                            try:
                                bs._subtitle_cache[p] = Subtitle(p)
                            except Exception as e2:
                                print(f'字幕文件加载失败 ｢{p}｣: {str(e2)}')
            
            progress_cb(text='生成配置')
            configuration = bs.generate_configuration_from_selected_mpls(
                self.selected_mpls,
                cancel_event=self.cancel_event
            )
            progress_cb(text='合并字幕')
            bs.generate_bluray_subtitle(configuration=configuration, cancel_event=self.cancel_event)
            bs.completion()
        except _Cancelled:
            self.canceled.emit()
        except Exception:
            self.failed.emit(traceback.format_exc())
        else:
            self.finished.emit()


class SubtitleFolderScanWorker(QObject):
    progress = pyqtSignal(int)
    label = pyqtSignal(str)
    result = pyqtSignal(object)
    canceled = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, seq: int, mode: int, subtitle_folder: str, bdmv_path: str, checked: bool,
                 selected_mpls: list[tuple[str, str]], cancel_event: threading.Event):
        super().__init__()
        self.seq = seq
        self.mode = mode
        self.subtitle_folder = subtitle_folder
        self.bdmv_path = bdmv_path
        self.checked = checked
        self.selected_mpls = selected_mpls
        self.cancel_event = cancel_event

    def run(self):
        try:
            if self.mode == 2:
                root = self.subtitle_folder.strip()
                mkv_paths = [os.path.normpath(os.path.join(root, f)) for f in os.listdir(root) if f.endswith('.mkv')]
                mkv_paths.sort()
                rows = []
                total = len(mkv_paths) or 1
                for i, p in enumerate(mkv_paths):
                    if self.cancel_event.is_set():
                        raise _Cancelled()
                    self.label.emit(f'读取MKV {i + 1}/{len(mkv_paths)}')
                    rows.append((p, get_time_str(MKV(p).get_duration())))
                    self.progress.emit(int((i + 1) / total * 1000))
                self.result.emit({'seq': self.seq, 'mode': self.mode, 'rows': rows})
                return

            folder = self.subtitle_folder.strip()
            files = []
            for f in os.listdir(folder):
                if f.endswith(".ass") or f.endswith(".ssa") or f.endswith('srt') or f.endswith('.sup'):
                    files.append(os.path.normpath(os.path.join(folder, f)))
            files.sort()
            if not files:
                self.result.emit({'seq': self.seq, 'mode': self.mode, 'rows': [], 'configuration': {}})
                return

            self.label.emit('解析字幕 0/{}'.format(len(files)))
            self.progress.emit(0)
            
            # 根据平台选择字幕解析策略
            if sys.platform == 'win32':
                # Windows下使用多进程
                subtitle_cache = self._parse_subtitles_multiprocess(files)
            else:
                # Linux下尝试多进程，失败则回退到单进程
                try:
                    subtitle_cache = self._parse_subtitles_multiprocess(files)
                except Exception as e:
                    print(f'多进程解析失败，切换到单进程模式: {str(e)}')
                    subtitle_cache = self._parse_subtitles_single(files)
            
            if not subtitle_cache:
                print('字幕文件全部加载失败')
                self.result.emit({'seq': self.seq, 'mode': self.mode, 'rows': [], 'configuration': {}})
                return
            
            print(f'成功加载 {len(subtitle_cache)} 个字幕文件')
            
            successful_files = [p for p in files if p in subtitle_cache]

            try:
                rows = [(p, get_time_str(subtitle_cache[p].max_end_time())) for p in successful_files]
            except Exception as e:
                print(f'获取字幕时长失败: {str(e)}')
                rows = [(p, '未知') for p in successful_files]

            self.label.emit('生成配置')
            self.progress.emit(850)
            try:
                bs = BluraySubtitle(self.bdmv_path, successful_files, self.checked, None)
                bs._subtitle_cache = subtitle_cache
                configuration = bs.generate_configuration_from_selected_mpls(
                    self.selected_mpls,
                    cancel_event=self.cancel_event
                )
            except Exception as e:
                print(f'生成配置失败: {str(e)}')
                import traceback
                traceback.print_exc()
                configuration = {}
            
            self.progress.emit(1000)
            self.result.emit({'seq': self.seq, 'mode': self.mode, 'rows': rows, 'configuration': configuration, 'files': successful_files})
        except _Cancelled:
            self.canceled.emit()
        except Exception:
            self.failed.emit(traceback.format_exc())
    
    def _parse_subtitles_with_fallback(self, files: list[str]) -> dict[str, Subtitle]:
        """尝试多进程解析，失败时回退到单进程"""
        subtitle_cache: dict[str, Subtitle] = {}
        try:
            return self._parse_subtitles_multiprocess(files)
        except Exception as e:
            print(f'多进程解析失败，切换到单进程模式: {str(e)}')
            return self._parse_subtitles_single(files)
    
    def _parse_subtitles_single(self, files: list[str]) -> dict[str, Subtitle]:
        """单进程模式解析字幕"""
        subtitle_cache: dict[str, Subtitle] = {}
        total = len(files)
        loaded_count = 0
        for i, p in enumerate(files):
            if self.cancel_event.is_set():
                raise _Cancelled()
            try:
                sub = Subtitle(p)
                subtitle_cache[p] = sub
                loaded_count += 1
                print(f'字幕文件加载成功 ｢{p}｣')
            except Exception as e:
                print(f'字幕文件加载失败 ｢{p}｣: {type(e).__name__}: {str(e)}')
                import traceback
                traceback.print_exc()
            self.label.emit(f'解析字幕 {i + 1}/{total}（已加载 {loaded_count}）')
            self.progress.emit(int((i + 1) / total * 700))
        return subtitle_cache
    
    def _parse_subtitles_multiprocess(self, files: list[str]) -> dict[str, Subtitle]:
        """多进程模式解析字幕"""
        if len(files) == 1:
            # 单个文件直接使用单进程
            return self._parse_subtitles_single(files)
            
        subtitle_cache: dict[str, Subtitle] = {}
        max_workers = min(len(files), os.cpu_count() or 1)
        try:
            mp_context = multiprocessing.get_context('spawn')
        except ValueError:
            mp_context = None
        try:
            with ProcessPoolExecutor(max_workers=max_workers, mp_context=mp_context) as ex:
                futures = [ex.submit(_parse_subtitle_worker, p) for p in files]
                done = 0
                total = len(futures)
                for fut in as_completed(futures):
                    if self.cancel_event.is_set():
                        for f in futures:
                            f.cancel()
                        raise _Cancelled()
                    p = None
                    try:
                        p, sub = fut.result()
                        if sub is not None:
                            subtitle_cache[p] = sub
                    except Exception as e:
                        if p:
                            print(f'字幕文件加载失败 ｢{p}｣: {str(e)}')
                        else:
                            print(f'字幕文件加载失败: {str(e)}')
                    done += 1
                    self.label.emit(f'解析字幕 {done}/{total}')
                    self.progress.emit(int(done / total * 700))
        except Exception as e:
            # 多进程失败，抛出异常让上层处理
            raise Exception(f'多进程解析失败: {str(e)}')
        return subtitle_cache

class BluraySubtitleGUI(QWidget):
    def __init__(self):
        super().__init__()
        self.init_ui()
        self.altered = False

    def get_default_vpy_path(self) -> str:
        return os.path.normpath(os.path.abspath('vpy.vpy'))

    def ensure_default_vpy_file(self):
        path = self.get_default_vpy_path()
        if os.path.exists(path) and os.path.isfile(path):
            return
        deband_line = 'dbed = core.neo_f3kdb.Deband(nr16, 12, 72, 48, 48, 0, 0, output_depth=16).neo_f3kdb.Deband(24, 56, 32, 32, 0, 0, output_depth=16)\n'
        if sys.platform != 'win32':
            deband_line = 'dbed = core.placebo.Deband(nr16, planes=7, iterations=2, threshold=4.5, radius=16.0, grain=0.0)\n'
        plugin_line = '' if sys.platform == 'win32' else f'core.std.LoadAllPlugins("{PLUGIN_PATH}")\n'
        content = (
            'import vapoursynth as vs\n'
            'from vapoursynth import core\n'
            'import mvsfunc as mvf\n'
            + plugin_line +
            '\n'
            '\n'
            'a = r""  #（可以不填，程序会自动生成）\n'
            '\n'
            'src8 = core.lsmas.LWLibavSource(a)\n'
            'src16 = core.fmtc.bitdepth(src8, bits=16)\n'
            'nr16 = core.nlm_ispc.NLMeans(src16, d=0, wmode=3, h=3)\n'
            + deband_line +
            'dbed = mvf.LimitFilter(dbed, nr16, thr=0.55, elast=1.5, planes=[0, 1, 2])\n'
            'nr16Y = core.std.ShufflePlanes(nr16, 0, vs.GRAY)\n'
            'aa_nr16Y = core.eedi2.EEDI2(nr16Y, field=1, mthresh=10, lthresh=20, vthresh=20, maxd=24, nt=50)\n'
            'aa_nr16Y = core.fmtc.resample(aa_nr16Y, 1920, 1080, 0, -0.5).std.Transpose()\n'
            'aa_nr16Y = core.eedi2.EEDI2(aa_nr16Y, field=1, mthresh=10, lthresh=20, vthresh=20, maxd=24, nt=50)\n'
            'aa_nr16Y = core.fmtc.resample(aa_nr16Y, 1080, 1920, 0, -0.5).std.Transpose()\n'
            'aaedY = core.rgvs.Repair(aa_nr16Y, nr16Y, 2)\n'
            'dbedY = core.std.ShufflePlanes(dbed, 0, vs.GRAY)\n'
            'mergedY = mvf.LimitFilter(dbedY, aaedY, thr=1.0, elast=1.5)\n'
            'merged = core.std.ShufflePlanes([mergedY, dbed], [0,1,2], vs.YUV)\n'
            'res = merged\n'
            'Debug = False\n'
            'if Debug:\n'
            '    res = mvf.ToRGB(res, full=False, depth=8)\n'
            'else:\n'
            '    res = core.fmtc.bitdepth(res, bits=10)\n'
            '# sub_file = ""  #（可以不填，程序会自动生成）\n'
            '# res = core.assrender.TextSub(res, file=sub_file)\n'
            'res.set_output()\n'
            'src8.set_output(1)\n'
        )
        try:
            with open(path, 'w', encoding='utf-8') as fp:
                fp.write(content)
        except Exception:
            traceback.print_exc()

    def delete_default_vpy_file(self):
        path = self.get_default_vpy_path()
        try:
            if os.path.exists(path) and os.path.isfile(path):
                os.remove(path)
        except Exception:
            traceback.print_exc()

    def set_vpy_hardsub_enabled(self, enabled: bool):
        path = self.get_default_vpy_path()
        if enabled and not os.path.exists(path):
            self.ensure_default_vpy_file()
        if not os.path.exists(path):
            return

        target_1 = 'sub_file = \"\"  #（可以不填，程序会自动生成）'
        target_2 = 'res = core.assrender.TextSub(res, file=sub_file)'

        try:
            with open(path, 'r', encoding='utf-8') as fp:
                lines = fp.readlines()
        except Exception:
            traceback.print_exc()
            return

        updated = False
        new_lines: list[str] = []
        for line in lines:
            raw = line.rstrip('\n')
            stripped = raw.lstrip()
            uncommented = stripped
            if stripped.startswith('#'):
                uncommented = stripped[1:].lstrip()

            if uncommented == target_1 or uncommented == target_2:
                updated = True
                if enabled:
                    new_lines.append(uncommented + '\n')
                else:
                    new_lines.append('# ' + uncommented + '\n')
            else:
                new_lines.append(line)

        if not updated:
            return

        try:
            with open(path, 'w', encoding='utf-8') as fp:
                fp.writelines(new_lines)
        except Exception:
            traceback.print_exc()

    def closeEvent(self, event):
        self.delete_default_vpy_file()
        return super().closeEvent(event)

    def create_vpy_path_widget(self, initial_path: Optional[str] = None, parent: Optional[QWidget] = None) -> QWidget:
        widget = QWidget(parent or self.table2)
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        widget.setLayout(layout)

        line_edit = QLineEdit(widget)
        line_edit.setText(initial_path or self.get_default_vpy_path())

        button = QPushButton('选择', widget)

        def select_file():
            start_dir = os.path.dirname(line_edit.text()) if line_edit.text() else os.getcwd()
            path, _ = QFileDialog.getOpenFileName(
                self,
                "选择vpy文件",
                start_dir,
                "Python/VapourSynth (*.py *.vpy)"
            )
            if path:
                line_edit.setText(os.path.normpath(path))

        button.clicked.connect(select_file)
        layout.addWidget(line_edit)
        layout.addWidget(button)
        return widget

    def get_vpy_path_from_row(self, row_index: int) -> str:
        if not self.radio4.isChecked():
            return ''
        vpy_col = ENCODE_LABELS.index('vpy_path')
        w = self.table2.cellWidget(row_index, vpy_col)
        if w:
            line_edit = w.findChild(QLineEdit)
            if line_edit:
                return line_edit.text().strip()
        item = self.table2.item(row_index, vpy_col)
        return item.text().strip() if item else ''

    def open_vpy_in_editor(self, path: str):
        if not path:
            QMessageBox.information(self, "提示", "vpy路径为空")
            return
        if not os.path.exists(path):
            QMessageBox.information(self, "提示", f"文件不存在：{path}")
            return
        if sys.platform == 'win32':
            os.startfile(path)
        else:
            subprocess.Popen(['xdg-open', path])

    def on_edit_vpy_clicked(self):
        if not self.radio4.isChecked():
            return
        sender = self.sender()
        if not sender:
            return
        try:
            row_index = self.table2.indexAt(sender.pos()).row()
        except Exception:
            row_index = -1
        if row_index < 0:
            return
        self.open_vpy_in_editor(self.get_vpy_path_from_row(row_index))

    def ensure_encode_row_widgets(self, row_index: int):
        if not self.radio4.isChecked():
            return
        vpy_col = ENCODE_LABELS.index('vpy_path')
        edit_col = ENCODE_LABELS.index('edit_vpy')

        if not self.table2.cellWidget(row_index, vpy_col):
            self.table2.setCellWidget(row_index, vpy_col, self.create_vpy_path_widget(parent=self.table2))

        if not self.table2.cellWidget(row_index, edit_col):
            btn = QToolButton(self.table2)
            btn.setText('edit_vpy')
            btn.clicked.connect(self.on_edit_vpy_clicked)
            self.table2.setCellWidget(row_index, edit_col, btn)

    def get_sp_vpy_path_from_row(self, row_index: int) -> str:
        if not self.radio4.isChecked():
            return ''
        vpy_col = ENCODE_SP_LABELS.index('vpy_path')
        w = self.table3.cellWidget(row_index, vpy_col)
        if w:
            line_edit = w.findChild(QLineEdit)
            if line_edit:
                return line_edit.text().strip()
        item = self.table3.item(row_index, vpy_col)
        return item.text().strip() if item else ''

    def on_edit_sp_vpy_clicked(self):
        if not self.radio4.isChecked():
            return
        sender = self.sender()
        if not sender:
            return
        try:
            row_index = self.table3.indexAt(sender.pos()).row()
        except Exception:
            row_index = -1
        if row_index < 0:
            return
        path = self.get_sp_vpy_path_from_row(row_index)
        self.open_vpy_in_editor(path)

    def refresh_sp_table(self, configuration: dict[int, dict[str, int | str]]):
        if not self.radio4.isChecked() or not configuration:
            if hasattr(self, 'table3'):
                self.table3.setRowCount(0)
            return
        try:
            bdmv_index_conf: dict[int, list[dict[str, int | str]]] = {}
            for _, conf in configuration.items():
                bdmv_index_conf.setdefault(int(conf['bdmv_index']), []).append(conf)

            entries: list[tuple[int, str, list[str], int]] = []
            for bdmv_index, confs in bdmv_index_conf.items():
                mpls_path = confs[0]['selected_mpls'] + '.mpls'
                if not os.path.exists(mpls_path):
                    continue
                try:
                    chapter = Chapter(mpls_path)
                    index_to_m2ts, _ = get_index_to_m2ts_and_offset(chapter)
                except Exception:
                    traceback.print_exc()
                    continue

                parsed_m2ts_files = set(index_to_m2ts.values())
                playlist_dir = os.path.dirname(mpls_path)

                try:
                    playlist_files = os.listdir(playlist_dir)
                except Exception:
                    traceback.print_exc()
                    playlist_files = []

                for mpls_file in playlist_files:
                    if not mpls_file.endswith('.mpls'):
                        continue
                    mpls_file_path = os.path.join(playlist_dir, mpls_file)
                    if os.path.normpath(mpls_file_path) == os.path.normpath(mpls_path):
                        continue
                    try:
                        ch = Chapter(mpls_file_path)
                        idx_to_m2ts, _ = get_index_to_m2ts_and_offset(ch)
                    except Exception:
                        continue
                    if len(idx_to_m2ts) > 1 and not (parsed_m2ts_files & set(idx_to_m2ts.values())):
                        entries.append((
                            bdmv_index,
                            os.path.basename(mpls_file_path),
                            sorted(list(set(idx_to_m2ts.values()))),
                            ch.get_total_time()
                        ))
                        parsed_m2ts_files |= set(idx_to_m2ts.values())

                bdmv_dir = os.path.dirname(playlist_dir)
                stream_folder = os.path.join(bdmv_dir, 'STREAM')
                if not os.path.isdir(stream_folder):
                    continue
                try:
                    stream_files = os.listdir(stream_folder)
                except Exception:
                    traceback.print_exc()
                    continue

                for stream_file in stream_files:
                    if not stream_file.endswith('.m2ts'):
                        continue
                    if stream_file in parsed_m2ts_files:
                        continue
                    try:
                        dur = M2TS(os.path.join(stream_folder, stream_file)).get_duration() / 90000
                    except Exception:
                        continue
                    if dur > 30:
                        entries.append((bdmv_index, '', [stream_file], dur))

            old_sorting = self.table3.isSortingEnabled()
            self.table3.setSortingEnabled(False)
            try:
                self.table3.setRowCount(len(entries))
                for i, (bdmv_index, mpls_file, m2ts_files, dur) in enumerate(entries):
                    self.table3.setItem(i, 0, QTableWidgetItem(str(bdmv_index)))
                    self.table3.setItem(i, 1, QTableWidgetItem(mpls_file))
                    self.table3.setItem(i, 2, QTableWidgetItem(','.join(m2ts_files)))
                    self.table3.setItem(i, 3, QTableWidgetItem(get_time_str(dur)))
                    self.table3.setCellWidget(i, 4, self.create_vpy_path_widget(parent=self.table3))
                    btn = QToolButton(self.table3)
                    btn.setText('edit_vpy')
                    btn.clicked.connect(self.on_edit_sp_vpy_clicked)
                    self.table3.setCellWidget(i, 5, btn)
                self.table3.resizeColumnsToContents()
            finally:
                self.table3.setSortingEnabled(old_sorting)
        except Exception:
            traceback.print_exc()
            self.table3.setRowCount(0)

    def init_encode_box(self):
        self._encode_preset_params = {
            '快速': '--preset fast --crf 20 --aq-mode 2 --bframes 8 --ref 4 --me 2 --subme 2',
            '均衡': '--preset slower --crf 18 --aq-mode 3 --bframes 8 --ref 5 --me 3 --subme 4',
            '高质': '--preset slower --crf 16 --aq-mode 3 --bframes 8 --psy-rd 2.0 --psy-rdoq 1.0 --deblock -1:-1 --rc-lookahead 60 --ref 6 --subme 5',
            '极限': '--preset placebo --crf 14 --pme --pmode --aq-mode 3 --aq-strength 1.0 --cbqpoffs -2 --crqpoffs -2 --bframes 12 --b-adapt 2 --ref 6 --rc-lookahead 120 --lookahead-threads 0 --psy-rd 2.5 --psy-rdoq 2.0 --rdoq-level 2 --deblock -2:-2 --qcomp 0.65 --merange 57 --no-sao --no-strong-intra-smoothing',
            '自订': ''
        }
        self._encode_setting_updating = False

        layout = QVBoxLayout()
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        self.encode_box.setLayout(layout)

        tools_row = QWidget(self.encode_box)
        tools_layout = QHBoxLayout()
        tools_layout.setContentsMargins(0, 0, 0, 0)
        tools_layout.setSpacing(10)
        tools_row.setLayout(tools_layout)

        tools_layout.addWidget(QLabel('vspipe：', tools_row))
        self.vspipe_mode_combo = QComboBox(tools_row)
        self.vspipe_mode_combo.addItems(['程序自带', '系统'])
        tools_layout.addWidget(self.vspipe_mode_combo)

        tools_layout.addWidget(QLabel('x265：', tools_row))
        self.x265_mode_combo = QComboBox(tools_row)
        self.x265_mode_combo.addItems(['程序自带', '系统'])
        tools_layout.addWidget(self.x265_mode_combo)

        if is_docker():
            self.vspipe_mode_combo.setCurrentText('系统')
            self.x265_mode_combo.setCurrentText('系统')

        tools_layout.addWidget(QLabel('x265参数：', tools_row))
        self.x265_preset_combo = QComboBox(tools_row)
        self.x265_preset_combo.addItems(list(self._encode_preset_params.keys()))
        self.x265_preset_combo.setCurrentText('均衡')
        tools_layout.addWidget(self.x265_preset_combo)

        tools_layout.addStretch(1)
        layout.addWidget(tools_row)

        self.x265_params_edit = QPlainTextEdit(self.encode_box)
        self.x265_params_edit.setMaximumHeight(60)
        layout.addWidget(self.x265_params_edit)

        def set_params_for_preset(preset: str):
            params = self._encode_preset_params.get(preset, '')
            self._encode_setting_updating = True
            try:
                self.x265_params_edit.setPlainText(params)
            finally:
                self._encode_setting_updating = False

        def on_preset_changed():
            preset = self.x265_preset_combo.currentText()
            if preset == '自订':
                return
            set_params_for_preset(preset)

        def on_params_edited():
            if self._encode_setting_updating:
                return
            if self.x265_preset_combo.currentText() != '自订':
                self.x265_preset_combo.setCurrentText('自订')

        self.x265_preset_combo.currentIndexChanged.connect(on_preset_changed)
        self.x265_params_edit.textChanged.connect(on_params_edited)
        set_params_for_preset(self.x265_preset_combo.currentText())

        sub_pack_row = QWidget(self.encode_box)
        sub_pack_layout = QHBoxLayout()
        sub_pack_layout.setContentsMargins(0, 0, 0, 0)
        sub_pack_layout.setSpacing(10)
        sub_pack_row.setLayout(sub_pack_layout)

        sub_pack_layout.addWidget(QLabel('字幕封装方式：', sub_pack_row))
        self.sub_pack_external_radio = QRadioButton('外挂', sub_pack_row)
        self.sub_pack_soft_radio = QRadioButton('内挂', sub_pack_row)
        self.sub_pack_hard_radio = QRadioButton('内嵌', sub_pack_row)
        self.sub_pack_external_radio.setChecked(True)

        sub_pack_layout.addWidget(self.sub_pack_external_radio)
        sub_pack_layout.addWidget(self.sub_pack_soft_radio)
        sub_pack_layout.addWidget(self.sub_pack_hard_radio)
        sub_pack_layout.addStretch(1)
        layout.addWidget(sub_pack_row)

        sub_pack_group = QButtonGroup(sub_pack_row)
        sub_pack_group.addButton(self.sub_pack_external_radio)
        sub_pack_group.addButton(self.sub_pack_soft_radio)
        sub_pack_group.addButton(self.sub_pack_hard_radio)
        self._sub_pack_group = sub_pack_group
        self._sub_pack_row = sub_pack_row

        def on_sub_pack_changed():
            if not self.radio4.isChecked():
                return
            if not self.subtitle_folder_path.text().strip():
                return
            self.set_vpy_hardsub_enabled(self.sub_pack_hard_radio.isChecked())

        self.sub_pack_external_radio.toggled.connect(on_sub_pack_changed)
        self.sub_pack_soft_radio.toggled.connect(on_sub_pack_changed)
        self.sub_pack_hard_radio.toggled.connect(on_sub_pack_changed)

        def update_sub_pack_enabled_state():
            enabled = self.radio4.isChecked() and bool(self.subtitle_folder_path.text().strip())
            self._sub_pack_row.setEnabled(enabled)
            if not enabled:
                self.sub_pack_external_radio.setChecked(True)
                self.set_vpy_hardsub_enabled(False)

        self.subtitle_folder_path.textChanged.connect(lambda _=None: update_sub_pack_enabled_state())
        update_sub_pack_enabled_state()

    def init_ui(self):
        self.setWindowTitle("BluraySubtitle")
        self.setMinimumWidth(860)
        self.setMinimumHeight(1000)

        app = QApplication.instance()
        if app:
            app.aboutToQuit.connect(self.delete_default_vpy_file)

        self.layout = QVBoxLayout()

        function_button = QGroupBox('选择功能', self)
        h_layout = QHBoxLayout()
        h_layout.setContentsMargins(12, 18, 12, 8)
        h_layout.setSpacing(18)
        function_button.setLayout(h_layout)
        self.subtitle_folder_path = QLineEdit()
        self.subtitle_folder_path.setMinimumWidth(200)

        self.radio1 = QRadioButton(self)
        self.radio1.setText("生成合并字幕")
        self.radio1.setChecked(True)
        self.radio2 = QRadioButton(self)
        self.radio2.setText("给mkv添加章节")
        self.radio3 = QRadioButton(self)
        self.radio3.setText("原盘remux")
        self.radio4 = QRadioButton(self)
        self.radio4.setText("原盘压制")
        group = QButtonGroup(self)
        group.addButton(self.radio1)
        group.addButton(self.radio2)
        group.addButton(self.radio3)
        group.addButton(self.radio4)
        group.buttonClicked.connect(self.on_select_function)
        h_layout.addWidget(self.radio1)
        h_layout.addWidget(self.radio2)
        h_layout.addWidget(self.radio3)
        h_layout.addWidget(self.radio4)
        self.layout.addWidget(function_button)

        bdmv = QGroupBox()
        v_layout = QVBoxLayout()
        bdmv.setLayout(v_layout)
        bluray_path_box = CustomBox('原盘', self)
        h_layout = QHBoxLayout()
        bluray_path_box.setLayout(h_layout)
        self.label1 = QLabel("选择原盘所在的文件夹", self)
        self.bdmv_folder_path = QLineEdit()
        self.bdmv_folder_path.setMinimumWidth(200)
        button1 = QPushButton("选择文件夹")
        button1.clicked.connect(self.select_bdmv_folder)
        self.layout.addWidget(self.label1)
        h_layout.addWidget(self.bdmv_folder_path)
        h_layout.addWidget(button1)
        v_layout.addWidget(bluray_path_box)

        self.table1 = QTableWidget()
        self.table1.setColumnCount(len(BDMV_LABELS))
        self.table1.setHorizontalHeaderLabels(BDMV_LABELS)
        self.table1.setSortingEnabled(True)
        self.table1.horizontalHeader().setSortIndicatorShown(True)
        self.bdmv_folder_path.textChanged.connect(self.on_bdmv_folder_path_change)
        v_layout.addWidget(self.table1)
        self.layout.addWidget(bdmv)

        subtitle = QGroupBox()
        v_layout = QVBoxLayout()
        subtitle.setLayout(v_layout)
        subtitle_path_box = CustomBox('字幕', self)
        h_layout = QHBoxLayout()
        subtitle_path_box.setLayout(h_layout)
        self.label2 = QLabel("选择单集字幕所在的文件夹：", self)
        self.subtitle_folder_path = QLineEdit()
        self.subtitle_folder_path.setMinimumWidth(200)
        button2 = QPushButton("选择文件夹")
        button2.clicked.connect(self.select_subtitle_folder)
        self.layout.addWidget(self.label2)
        h_layout.addWidget(self.subtitle_folder_path)
        h_layout.addWidget(button2)
        v_layout.addWidget(subtitle_path_box)

        self.table2 = CustomTableWidget(self, self.on_subtitle_drop)
        self.table2.setColumnCount(len(SUBTITLE_LABELS))
        self.table2.setHorizontalHeaderLabels(SUBTITLE_LABELS)
        self.table2.setSortingEnabled(True)
        self.table2.horizontalHeader().setSortIndicatorShown(True)
        self.table2.horizontalHeader().sortIndicatorChanged.connect(self.on_subtitle_table_sorted)
        self.subtitle_folder_path.textChanged.connect(self.on_subtitle_folder_path_change)
        self._subtitle_scan_debounce = QTimer(self)
        self._subtitle_scan_debounce.setSingleShot(True)
        self._subtitle_scan_debounce.setInterval(250)
        self._subtitle_scan_debounce.timeout.connect(self._start_subtitle_folder_scan)
        self._pending_subtitle_folder = ''
        v_layout.addWidget(self.table2)
        self.table3 = QTableWidget(self)
        self.table3.setColumnCount(len(ENCODE_SP_LABELS))
        self.table3.setHorizontalHeaderLabels(ENCODE_SP_LABELS)
        self.table3.setSortingEnabled(True)
        self.table3.horizontalHeader().setSortIndicatorShown(True)
        self.table3.setVisible(False)
        v_layout.addWidget(self.table3)
        self.layout.addWidget(subtitle)

        self.encode_box = QGroupBox('压制', self)
        self.encode_box.setVisible(False)
        self.init_encode_box()
        self.layout.addWidget(self.encode_box)

        self.checkbox1 = QCheckBox("补全蓝光目录")
        self.checkbox1.setChecked(True)
        self.layout.addWidget(self.checkbox1)
        self.exe_button = QPushButton("生成字幕")
        self.exe_button.clicked.connect(self.main)
        self.exe_button.setMinimumHeight(50)
        self.layout.addWidget(self.exe_button)

        self.setLayout(self.layout)

    def on_bdmv_folder_path_change(self):
        bdmv_path = self.bdmv_folder_path.text().strip()
        table_ok = False
        if bdmv_path:
            try:
                self.table1.setColumnCount(len(BDMV_LABELS))
                self.table1.setHorizontalHeaderLabels(BDMV_LABELS)
                i = 0
                for root, dirs, files in os.walk(bdmv_path):
                    dirs.sort()  # Sort dirs to ensure consistent order on all platforms
                    if 'BDMV' in dirs and 'PLAYLIST' in os.listdir(os.path.join(root, 'BDMV')):
                        i += 1
                self.table1.setRowCount(i)
                i = 0
                for root, dirs, files in os.walk(bdmv_path):
                    dirs.sort()  # Sort dirs to ensure consistent order on all platforms
                    if 'BDMV' in dirs and 'PLAYLIST' in os.listdir(os.path.join(root, 'BDMV')):
                        table_widget = QTableWidget()
                        table_widget.setColumnCount(5)
                        table_widget.setHorizontalHeaderLabels(['mpls_file', 'duration', 'chapters', 'main', 'play'])
                        mpls_files = sorted([f for f in os.listdir(os.path.join(root, 'BDMV', 'PLAYLIST')) if f.endswith('.mpls')])
                        table_widget.setRowCount(len(mpls_files))
                        mpls_n = 0
                        selected_mpls = os.path.normpath(BluraySubtitle(root).get_main_mpls(root, False))
                        for mpls_file in mpls_files:
                                table_widget.setItem(mpls_n, 0, QTableWidgetItem(mpls_file))
                                mpls_path = os.path.normpath(os.path.join(root, 'BDMV', 'PLAYLIST', mpls_file))
                                total_time = Chapter(mpls_path).get_total_time()
                                total_time_str = get_time_str(total_time)
                                table_widget.setItem(mpls_n, 1, QTableWidgetItem(total_time_str))
                                btn1 = QToolButton()
                                btn1.setText('view chapters')
                                btn1.clicked.connect(partial(self.on_button_click, mpls_path))
                                table_widget.setCellWidget(mpls_n, 2, btn1)
                                btn2 = QToolButton()
                                btn2.setCheckable(True)
                                btn2.setChecked(mpls_path == selected_mpls)
                                btn2.clicked.connect(partial(self.on_button_main, mpls_path))
                                table_widget.setCellWidget(mpls_n, 3, btn2)
                                btn3 = QToolButton()
                                btn3.setText('play')
                                btn3.clicked.connect(partial(self.on_button_play, mpls_path, btn3))
                                table_widget.setCellWidget(mpls_n, 4, btn3)
                                table_widget.resizeColumnsToContents()
                                mpls_n += 1
                        self.table1.setItem(i, 0, FilePathTableWidgetItem(os.path.normpath(root)))
                        self.table1.setItem(i, 1, QTableWidgetItem(get_folder_size(root)))
                        self.table1.setCellWidget(i, 2, table_widget)
                        self.table1.setRowHeight(i, 100)
                        i += 1
                self.table1.resizeColumnsToContents()
                self.table1.setColumnWidth(2, 410)
                table_ok = True
            except Exception as e:
                self.table1.clear()
                self.table1.setColumnCount(len(BDMV_LABELS))
                self.table1.setHorizontalHeaderLabels(BDMV_LABELS)
                self.table1.setRowCount(0)
        self.altered = True
        if (self.radio3.isChecked() or self.radio4.isChecked()) and bdmv_path and table_ok:
            configuration = BluraySubtitle(
                self.bdmv_folder_path.text(),
                [],
                self.checkbox1.isChecked(),
                None
            ).generate_configuration(self.table1)
            self.on_configuration(configuration)

    def on_subtitle_folder_path_change(self):
        folder = self.subtitle_folder_path.text().strip()
        self._pending_subtitle_folder = folder
        if hasattr(self, '_subtitle_scan_cancel_event') and self._subtitle_scan_cancel_event:
            self._subtitle_scan_cancel_event.set()
        if not folder:
            self._subtitle_scan_debounce.stop()
            return
        self._subtitle_scan_debounce.stop()
        self._subtitle_scan_debounce.start()

    def _start_subtitle_folder_scan(self):
        folder = (self._pending_subtitle_folder or '').strip()
        if not folder or not os.path.isdir(folder):
            return

        if hasattr(self, '_subtitle_scan_cancel_event') and self._subtitle_scan_cancel_event:
            self._subtitle_scan_cancel_event.set()
        if hasattr(self, '_subtitle_scan_thread') and self._subtitle_scan_thread:
            try:
                self._subtitle_scan_thread.quit()
                self._subtitle_scan_thread.finished.connect(self._subtitle_scan_thread.deleteLater)
            except Exception:
                pass
            self._subtitle_scan_thread = None
        if hasattr(self, '_subtitle_scan_worker') and self._subtitle_scan_worker:
            try:
                self._subtitle_scan_worker.deleteLater()
            except Exception:
                pass
            self._subtitle_scan_worker = None

        if self.radio1.isChecked():
            mode = 1
            title = '读取字幕中'
        elif self.radio2.isChecked():
            mode = 2
            title = '读取MKV中'
        elif self.radio3.isChecked():
            mode = 3
            title = '读取字幕中'
        else:
            mode = 4
            title = '读取字幕中'

        if not hasattr(self, '_subtitle_scan_seq'):
            self._subtitle_scan_seq = 0
        self._subtitle_scan_seq += 1
        seq = self._subtitle_scan_seq
        cancel_event = threading.Event()
        self._subtitle_scan_cancel_event = cancel_event

        selected_mpls = self.get_selected_mpls_no_ext()

        progress_dialog = QProgressDialog(title, '取消', 0, 1000, self)
        progress_dialog.setMinimumDuration(0)
        progress_dialog.setAutoClose(False)
        progress_dialog.setAutoReset(False)
        progress_dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress_dialog.canceled.connect(cancel_event.set)
        self._subtitle_scan_progress_dialog = progress_dialog

        show_timer = QTimer(self)
        show_timer.setSingleShot(True)
        show_timer.setInterval(2000)
        self._subtitle_scan_show_timer = show_timer

        def show_if_still_running():
            if getattr(self, '_subtitle_scan_thread', None) and self._subtitle_scan_thread.isRunning():
                if getattr(self, '_subtitle_scan_progress_dialog', None):
                    self._subtitle_scan_progress_dialog.show()

        show_timer.timeout.connect(show_if_still_running)
        show_timer.start()

        self._subtitle_scan_thread = QThread(self)
        self._subtitle_scan_worker = SubtitleFolderScanWorker(
            seq,
            mode,
            folder,
            self.bdmv_folder_path.text(),
            self.checkbox1.isChecked(),
            selected_mpls,
            cancel_event
        )
        self._subtitle_scan_worker.moveToThread(self._subtitle_scan_thread)
        self._subtitle_scan_thread.started.connect(self._subtitle_scan_worker.run)
        self._subtitle_scan_worker.progress.connect(progress_dialog.setValue)
        self._subtitle_scan_worker.label.connect(progress_dialog.setLabelText)

        def cleanup():
            if getattr(self, '_subtitle_scan_show_timer', None):
                try:
                    self._subtitle_scan_show_timer.stop()
                except Exception:
                    pass
                self._subtitle_scan_show_timer = None
            if getattr(self, '_subtitle_scan_progress_dialog', None):
                try:
                    self._subtitle_scan_progress_dialog.close()
                    self._subtitle_scan_progress_dialog.deleteLater()
                except Exception:
                    pass
                self._subtitle_scan_progress_dialog = None
            if getattr(self, '_subtitle_scan_thread', None):
                try:
                    self._subtitle_scan_thread.quit()
                    self._subtitle_scan_thread.wait()
                    self._subtitle_scan_thread.deleteLater()
                except Exception:
                    pass
                self._subtitle_scan_thread = None
            if getattr(self, '_subtitle_scan_worker', None):
                try:
                    self._subtitle_scan_worker.deleteLater()
                except Exception:
                    pass
                self._subtitle_scan_worker = None
            self._subtitle_scan_cancel_event = None

        def on_result(payload: object):
            if not isinstance(payload, dict) or payload.get('seq') != seq:
                return
            cleanup()
            if payload.get('mode') == 2:
                self.table2.clear()
                self.table2.setColumnCount(len(MKV_LABELS))
                self.table2.setHorizontalHeaderLabels(MKV_LABELS)
                rows = payload.get('rows') or []
                self.table2.setRowCount(len(rows))
                for i, (path, dur) in enumerate(rows):
                    self.table2.setItem(i, 0, FilePathTableWidgetItem(path))
                    self.table2.setItem(i, 1, QTableWidgetItem(dur))
                self.table2.resizeColumnsToContents()
                return

            rows = payload.get('rows') or []
            if payload.get('mode') == 3:
                self.table2.clear()
                self.table2.setColumnCount(len(REMUX_LABELS))
                self.table2.setHorizontalHeaderLabels(REMUX_LABELS)
                self.table2.setRowCount(len(rows))
                for i, (path, dur) in enumerate(rows):
                    self.table2.setItem(i, 0, FilePathTableWidgetItem(path))
                    self.table2.setItem(i, 1, QTableWidgetItem(dur))
                self.table2.resizeColumnsToContents()
            elif payload.get('mode') == 4:
                self.table2.clear()
                self.table2.setColumnCount(len(ENCODE_LABELS))
                self.table2.setHorizontalHeaderLabels(ENCODE_LABELS)
                self.table2.setRowCount(len(rows))
                for i, (path, dur) in enumerate(rows):
                    self.table2.setItem(i, 0, FilePathTableWidgetItem(path))
                    self.table2.setItem(i, 1, QTableWidgetItem(dur))
                    self.ensure_encode_row_widgets(i)
                self.table2.resizeColumnsToContents()
            else:
                self.table2.clear()
                self.table2.setColumnCount(len(SUBTITLE_LABELS))
                self.table2.setHorizontalHeaderLabels(SUBTITLE_LABELS)
                self.table2.setRowCount(len(rows))
                for i, (path, dur) in enumerate(rows):
                    check_item = QTableWidgetItem()
                    check_item.setFlags(check_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    check_item.setCheckState(Qt.CheckState.Checked)
                    self.table2.setItem(i, 0, check_item)
                    self.table2.setItem(i, 1, FilePathTableWidgetItem(path))
                    self.table2.setItem(i, 2, QTableWidgetItem(dur))

                for bdmv_index in range(self.table1.rowCount()):
                    info: QTableWidget = self.table1.cellWidget(bdmv_index, 2)
                    if not info:
                        continue
                    for mpls_index in range(info.rowCount()):
                        main_btn: QToolButton = info.cellWidget(mpls_index, 3)
                        if main_btn and main_btn.isChecked():
                            play_btn = info.cellWidget(mpls_index, 4)
                            if play_btn:
                                play_btn.setText('preview')
                    info.resizeColumnsToContents()

                self.sub_check_state = [2 for _ in range(self.table2.rowCount())]
                try:
                    self.table2.cellClicked.disconnect(self.on_subtitle_select)
                except Exception:
                    pass
                self.table2.cellClicked.connect(self.on_subtitle_select)
                self.table2.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
                try:
                    self.table2.customContextMenuRequested.disconnect(self.on_subtitle_menu)
                except Exception:
                    pass
                self.table2.customContextMenuRequested.connect(self.on_subtitle_menu)

            configuration = payload.get('configuration') or {}
            if configuration:
                self.on_configuration(configuration)

        def on_canceled():
            cleanup()

        def on_failed(message: str):
            cleanup()
            QMessageBox.information(self, " ", message)

        self._subtitle_scan_worker.result.connect(on_result)
        self._subtitle_scan_worker.canceled.connect(on_canceled)
        self._subtitle_scan_worker.failed.connect(on_failed)
        self._subtitle_scan_thread.start()

    def on_subtitle_drop(self):
        try:
            if self.radio3.isChecked() or self.radio4.isChecked():
                sub_files = [self.table2.item(sub_index, 0).text() for sub_index in range(self.table2.rowCount())
                             if self.table2.item(sub_index, 0)]
            else:
                sub_files = [self.table2.item(sub_index, 1).text() for sub_index in range(self.table2.rowCount())
                             if self.table2.item(sub_index, 0) and self.table2.item(sub_index, 0).checkState() == 2]
            bs = BluraySubtitle(
                self.bdmv_folder_path.text(),
                sub_files,
                self.checkbox1.isChecked(),
                None
            )
            selected_mpls = self.get_selected_mpls_no_ext()
            if selected_mpls:
                configuration = bs.generate_configuration_from_selected_mpls(selected_mpls)
            else:
                configuration = bs.generate_configuration(self.table1)
            self.on_configuration(configuration)
        except Exception as e:
            print(f'拖入字幕处理失败: {str(e)}')
            import traceback
            traceback.print_exc()
            # 显示错误信息但不弹出对话框
            print('字幕拖入处理失败，请检查字幕文件和原盘路径')

    def get_mkv_files_in_table_order(self):
        """
        Get mkv files from table2 in the order they are displayed (respecting sorting).
        """
        mkv_files = []
        # Get the path column index based on selected function
        if self.radio2.isChecked():
            path_col = 0  # MKV_LABELS = ['path', 'duration']
            sort_col = 0
        else:
            path_col = 1  # SUBTITLE_LABELS = ['select', 'path', ...]
            sort_col = 1
        
        # Get all rows with their data
        rows_data = []
        for row_index in range(self.table2.rowCount()):
            item = self.table2.item(row_index, path_col)
            if item and item.text():
                rows_data.append((row_index, item.text()))
        
        # Check if table is sorted on path column
        sort_column = self.table2.horizontalHeader().sortIndicatorSection()
        sort_order = self.table2.horizontalHeader().sortIndicatorOrder()
        
        # If sorted on path column, sort rows_data accordingly
        if sort_column == sort_col:
            rows_data.sort(key=lambda x: x[1], reverse=(sort_order == Qt.SortOrder.DescendingOrder))
        
        # Extract the sorted mkv file paths
        for _, path in rows_data:
            if path:
                mkv_files.append(path)
        
        return mkv_files

    def on_subtitle_table_sorted(self, logicalIndex: int, order: Qt.SortOrder):
        # Handle path column sorting based on which function is selected
        # For radio2 (mkv chapters), path is at index 0 (MKV_LABELS) - no configuration rebuild needed
        # For radio3/4, path is at index 0 (REMUX_LABELS / ENCODE_LABELS)
        # For others, path is at index 1 (SUBTITLE_LABELS)
        if self.radio2.isChecked():
            if logicalIndex != 0:
                return
            # For radio2, just update the duration column after sorting
            for i in range(self.table2.rowCount()):
                item = self.table2.item(i, 0)
                if item and os.path.exists(item.text()):
                    self.table2.setItem(i, 1, QTableWidgetItem(get_time_str(MKV(item.text()).get_duration())))
            return
        else:
            sort_col = 0 if (self.radio3.isChecked() or self.radio4.isChecked()) else 1
            if logicalIndex != sort_col:
                return
        
        if self.table2.rowCount() == 0:
            return
        try:
            # update row-specific computed columns
            if self.radio1.isChecked():
                for i in range(self.table2.rowCount()):
                    item = self.table2.item(i, 1)
                    if item and os.path.exists(item.text()):
                        self.table2.setItem(i, 2, QTableWidgetItem(get_time_str(Subtitle(item.text()).max_end_time())))

            # Rebuild configuration after sorting
            if self.radio3.isChecked() or self.radio4.isChecked():
                sub_files = [self.table2.item(sub_index, 0).text() for sub_index in range(self.table2.rowCount())
                             if self.table2.item(sub_index, 0) and self.table2.item(sub_index, 0).text()]
            else:
                sub_files = [self.table2.item(sub_index, 1).text() for sub_index in range(self.table2.rowCount())
                             if self.table2.item(sub_index, 0) and self.table2.item(sub_index, 0).checkState() == 2]
            bs = BluraySubtitle(
                self.bdmv_folder_path.text(),
                sub_files,
                self.checkbox1.isChecked(),
                None
            )
            selected_mpls = self.get_selected_mpls_no_ext()
            if selected_mpls:
                configuration = bs.generate_configuration_from_selected_mpls(selected_mpls)
            else:
                configuration = bs.generate_configuration(self.table1)
            self.on_configuration(configuration)
        except Exception:
            traceback.print_exc()

    def on_subtitle_select(self):
        sub_check_state = [self.table2.item(sub_index, 0).checkState().value for sub_index in
                           range(self.table2.rowCount())]
        if sub_check_state != self.sub_check_state:
            self.sub_check_state = sub_check_state
            sub_files = [self.table2.item(sub_index, 1).text() for sub_index in range(self.table2.rowCount())
                         if self.sub_check_state[sub_index] == 2]
            bs = BluraySubtitle(
                self.bdmv_folder_path.text(),
                sub_files,
                self.checkbox1.isChecked(),
                None
            )
            selected_mpls = self.get_selected_mpls_no_ext()
            if selected_mpls:
                configuration = bs.generate_configuration_from_selected_mpls(selected_mpls)
            else:
                configuration = bs.generate_configuration(self.table1)
            self.on_configuration(configuration)
        for sub_index, check_state in enumerate(self.sub_check_state):
            if check_state != 2:
                self.table2.setItem(sub_index, 3, None)
                self.table2.setCellWidget(sub_index, 4, None)
                self.table2.setItem(sub_index, 5, None)

    def on_configuration(self, configuration: dict[int, dict[str, int | str]]):
        try:
            if not configuration:
                print('配置为空，跳过更新')
                return
            if self.radio3.isChecked() or self.radio4.isChecked():
                old_sorting = self.table2.isSortingEnabled()
                self.table2.setSortingEnabled(False)
                self.table2.setRowCount(len(configuration))
                for sub_index, con in configuration.items():
                    self.table2.setItem(sub_index, 2, QTableWidgetItem(str(con['bdmv_index'])))
                    chapter_combo = QComboBox()
                    duration = 0
                    chapter = Chapter(str(con['selected_mpls']) + '.mpls')
                    rows = sum(map(len, chapter.mark_info.values()))
                    j1 = con['chapter_index']
                    next_con = configuration.get(sub_index + 1)
                    if next_con and next_con.get('folder') == con.get('folder') and next_con.get('selected_mpls') == con.get('selected_mpls'):
                        j2 = next_con['chapter_index']
                    else:
                        j2 = rows + 1
                    index_to_m2ts, index_to_offset = get_index_to_m2ts_and_offset(chapter)
                    m2ts_files = sorted(list(set([index_to_m2ts[i] for i in range(j1, j2)])))
                    chapter_combo.addItems([str(r + 1) for r in range(rows)])
                    chapter_combo.setCurrentIndex(con['chapter_index'] - 1)
                    chapter_combo.currentIndexChanged.connect(partial(self.on_chapter_combo, sub_index))
                    if next_con and next_con.get('folder') == con.get('folder') and next_con.get('selected_mpls') == con.get('selected_mpls'):
                        duration = index_to_offset[next_con['chapter_index']] - index_to_offset[j1]
                    else:
                        duration = chapter.get_total_time() - index_to_offset[j1]
                    duration = get_time_str(duration)
                    self.table2.setCellWidget(sub_index, 3, chapter_combo)
                    self.table2.setItem(sub_index, 4, QTableWidgetItem(', '.join(m2ts_files)))
                    self.table2.setItem(sub_index, 1, QTableWidgetItem(duration))
                    self.ensure_encode_row_widgets(sub_index)
                if self.subtitle_folder_path.text().strip():
                    sub_files = []
                    try:
                        for file in sorted(os.listdir(self.subtitle_folder_path.text().strip())):
                            if (file.endswith(".ass") or file.endswith(".ssa") or
                                    file.endswith('srt') or file.endswith('.sup')):
                                sub_files.append(os.path.normpath(os.path.join(self.subtitle_folder_path.text().strip(), file)))
                    except Exception:
                        pass
                    if sub_files:
                        for i, sub_file in enumerate(sub_files):
                            if i < len(configuration) and i < self.table2.rowCount():
                                self.table2.setItem(i, 0, FilePathTableWidgetItem(sub_file))
                self.table2.resizeColumnsToContents()
                if self.radio4.isChecked():
                    self.refresh_sp_table(configuration)
                self.table2.setSortingEnabled(old_sorting)
            else:
                for subtitle_index in range(self.table2.rowCount()):
                    con = configuration.get(subtitle_index)
                    sub_check_state = [self.table2.item(sub_index, 0).checkState().value for sub_index in
                                       range(self.table2.rowCount())]
                    index_table = [sub_index for sub_index in range(len(sub_check_state)) if sub_check_state[sub_index] == 2]
                    if con:
                        self.table2.setItem(index_table[subtitle_index], 3, QTableWidgetItem(str(con['bdmv_index'])))
                        chapter_combo = QComboBox()
                        rows = sum(map(len, Chapter(str(con['selected_mpls']) + '.mpls').mark_info.values()))
                        chapter_combo.addItems([str(r + 1) for r in range(rows)])
                        chapter_combo.setCurrentIndex(con['chapter_index'] - 1)
                        chapter_combo.currentIndexChanged.connect(partial(self.on_chapter_combo, subtitle_index))
                        self.table2.setCellWidget(index_table[subtitle_index], 4, chapter_combo)
                        self.table2.setItem(index_table[subtitle_index], 5, QTableWidgetItem(con['offset']))
                    elif subtitle_index <= len(index_table) - 1:
                        self.table2.setItem(index_table[subtitle_index], 3, None)
                        self.table2.setCellWidget(index_table[subtitle_index], 4, None)
                        self.table2.setItem(index_table[subtitle_index], 5, None)
                self.table2.resizeColumnsToContents()
                self.altered = True
        except Exception:
            QMessageBox.information(self, " ", traceback.format_exc())
            if hasattr(self, 'table3'):
                self.table3.setRowCount(0)
            return

    def on_chapter_combo(self, subtitle_index: int):
        if self.radio3.isChecked() or self.radio4.isChecked():
            sub_files = []
            if self.subtitle_folder_path.text().strip():
                for file in sorted(os.listdir(self.subtitle_folder_path.text().strip())):
                    if file.endswith(".ass") or file.endswith(".ssa") or file.endswith('srt') or file.endswith('.sup'):
                        sub_files.append(os.path.normpath(os.path.join(self.subtitle_folder_path.text().strip(), file)))
            sub_combo_index = {}
            for sub_index in range(self.table2.rowCount()):
                sub_combo_index[sub_index] = self.table2.cellWidget(sub_index, 3).currentIndex() + 1
            bs = BluraySubtitle(
                self.bdmv_folder_path.text(),
                sub_files,
                self.checkbox1.isChecked(),
                None
            )
            selected_mpls = self.get_selected_mpls_no_ext()
            if selected_mpls:
                configuration = bs.generate_configuration_from_selected_mpls(selected_mpls, sub_combo_index, subtitle_index)
            else:
                configuration = bs.generate_configuration(self.table1, sub_combo_index, subtitle_index)
            self.on_configuration(configuration)
        else:
            sub_files = [self.table2.item(sub_index, 1).text() for sub_index in range(self.table2.rowCount()) if
                         self.sub_check_state[sub_index] == 2]
            sub_combo_index = {}
            for sub_index in range(self.table2.rowCount()):
                if self.sub_check_state[sub_index] == 2:
                    if self.table2.cellWidget(sub_index, 4):
                        sub_combo_index[sub_index] = self.table2.cellWidget(sub_index, 4).currentIndex() + 1
            bs = BluraySubtitle(
                self.bdmv_folder_path.text(),
                sub_files,
                self.checkbox1.isChecked(),
                None
            )
            selected_mpls = self.get_selected_mpls_no_ext()
            if selected_mpls:
                configuration = bs.generate_configuration_from_selected_mpls(selected_mpls, sub_combo_index, subtitle_index)
            else:
                configuration = bs.generate_configuration(self.table1, sub_combo_index, subtitle_index)
            self.on_configuration(configuration)

    def on_button_play(self, mpls_path: str, btn: QToolButton):
        def mpv_play_mpls(mpls_path, mpv_path):
            mpls_name = mpls_path[:-5]
            sub_file = None
            if os.path.exists(mpls_name + '.ass'):
                sub_file = mpls_name + '.ass'
            elif os.path.exists(mpls_name + '.srt'):
                sub_file = mpls_name + '.srt'
            if sub_file:
                subprocess.Popen(
                    f'"{mpv_path}" --sub-file="{sub_file}" bd://mpls/{mpls_path[-10:-5]} --bluray-device="{mpls_path[:-25]}"',
                    shell=True).wait()
            else:
                subprocess.Popen(f'"{mpv_path}" bd://mpls/{mpls_path[-10:-5]} --bluray-device="{mpls_path[:-25]}"',
                                 shell=True).wait()
            return

        if btn.text() == 'preview' and self.altered:
            # 只有在字幕文件不存在时才生成
            mpls_name = mpls_path[:-5]
            has_subtitle = (os.path.exists(mpls_name + '.ass') or 
                          os.path.exists(mpls_name + '.srt') or
                          os.path.exists(mpls_name + '.ssa'))
            if not has_subtitle:
                success = self.generate_subtitle(silent_mode=True)
                if success:
                    # 重新检查字幕文件是否存在
                    has_subtitle = (os.path.exists(mpls_name + '.ass') or 
                                  os.path.exists(mpls_name + '.srt') or
                                  os.path.exists(mpls_name + '.ssa'))
            if not has_subtitle:
                # 如果仍然没有字幕文件，显示提示但仍允许播放
                QMessageBox.information(self, "提示", "字幕文件不存在，将播放无字幕版本")
        elif btn.text() == 'preview':
            # 检查字幕文件是否存在
            mpls_name = mpls_path[:-5]
            has_subtitle = (os.path.exists(mpls_name + '.ass') or 
                          os.path.exists(mpls_name + '.srt') or
                          os.path.exists(mpls_name + '.ssa'))
            if not has_subtitle:
                QMessageBox.information(self, "提示", "字幕文件不存在，将播放无字幕版本")
        if sys.platform != 'linux':
            if sys.platform == 'win32':
                mp4_exe_path = get_mpv_safe_path(".mp4")
                if mp4_exe_path:
                    if mp4_exe_path.endswith('mpv.exe'):
                        mpv_play_mpls(mpls_path, mp4_exe_path)
                        return
            os.startfile(mpls_path)
        else:
            in_docker = False
            try:
                if os.path.exists('/.dockerenv'):
                    in_docker = True
            except Exception:
                pass
            if not in_docker:
                try:
                    with open('/proc/1/cgroup', 'r', encoding='utf-8', errors='ignore') as fp:
                        cg = fp.read()
                    if ('docker' in cg) or ('kubepods' in cg) or ('containerd' in cg):
                        in_docker = True
                except Exception:
                    pass
            if in_docker:
                try:
                    my_env = os.environ.copy()
                    my_env["LD_LIBRARY_PATH"] = "/usr/local/lib/mpv-bundle:" + my_env.get("LD_LIBRARY_PATH", "")
                    mpls_name = mpls_path[:-5]
                    sub_file = None
                    if os.path.exists(mpls_name + '.ass'):
                        sub_file = mpls_name + '.ass'
                    elif os.path.exists(mpls_name + '.srt'):
                        sub_file = mpls_name + '.srt'
                    if sub_file:
                        subprocess.Popen(
                            f'mpv --vo=x11 --profile=sw-fast --hwdec=no --framedrop=vo --sub-file="{sub_file}" bd://mpls/{mpls_path[-10:-5]} --bluray-device="{mpls_path[:-25]}"',
                            shell=True, env=my_env).wait()
                    else:
                        subprocess.Popen(
                            f'mpv --vo=x11 --profile=sw-fast --hwdec=no --framedrop=vo bd://mpls/{mpls_path[-10:-5]} --bluray-device="{mpls_path[:-25]}"',
                            shell=True, env=my_env).wait()
                    return
                except Exception:
                    pass
            try:
                output = subprocess.check_output(["xdg-mime", "query", "default", "x-content/video-bluray"])
                desktop_file = output.decode('utf-8').strip()
                if not desktop_file:
                    output = subprocess.check_output(["xdg-mime", "query", "default", "video/mp4"])
                    desktop_file = output.decode('utf-8').strip()
                # linux下mpv启用蓝光支持，请编译前在源文件夹执行命令
                # echo "--enable-libbluray" > ffmpeg_options
                # 和
                # echo "-Dlibbluray=enabled" > mpv_options
                if 'mpv' in desktop_file:
                    mpv_play_mpls(mpls_path, 'mpv')
            except:
                pass
            subprocess.run(['xdg-open', mpls_path])

    def on_button_main(self, mpls_path: str):
        for bdmv_index in range(self.table1.rowCount()):
            if mpls_path.startswith(self.table1.item(bdmv_index, 0).text()):
                info: QTableWidget = self.table1.cellWidget(bdmv_index, 2)
                for mpls_index in range(info.rowCount()):
                    if mpls_path.endswith(info.item(mpls_index, 0).text()):
                        checked = info.cellWidget(mpls_index, 3).isChecked()
                        if checked:
                            subtitle = bool(self.table2.rowCount() > 0 and self.table2.item(0, 0) and
                                            self.table2.item(0, 0).text()
                                            and not (self.radio3.isChecked() or self.radio4.isChecked()))
                            info.cellWidget(mpls_index, 4).setText('preview' if subtitle else 'play')
                            for mpls_index_1 in range(info.rowCount()):
                                if not mpls_path.endswith(info.item(mpls_index_1, 0).text()):
                                    if info.cellWidget(mpls_index_1, 3).isChecked():
                                        info.cellWidget(mpls_index_1, 3).setChecked(False)
                                        info.cellWidget(mpls_index_1, 4).setText('play')
                        else:
                            info.cellWidget(mpls_index, 4).setText('play')
        self.on_subtitle_folder_path_change()

    def on_button_click(self, mpls_path: str):
        class ChapterWindow(QDialog):
            def __init__(this):
                super(ChapterWindow, this).__init__()
                this.setWindowTitle(f'chapters of {mpls_path}')
                layout = QVBoxLayout()
                table_widget = QTableWidget()
                table_widget.setColumnCount(2)
                table_widget.setHorizontalHeaderLabels(['offset', 'file'])
                chapter = Chapter(mpls_path)
                mark_info = chapter.mark_info
                in_out_time = chapter.in_out_time
                rows = sum(map(len, mark_info.values()))
                table_widget.setRowCount(rows)
                r = 0
                offset = 0
                for ref_to_play_item_id, mark_timestamps in mark_info.items():
                    for mark_timestamp in mark_timestamps:
                        off = offset + (mark_timestamp - in_out_time[ref_to_play_item_id][1]) / 45000
                        table_widget.setItem(r, 0, QTableWidgetItem(get_time_str(off)))
                        table_widget.setItem(r, 1, QTableWidgetItem(in_out_time[ref_to_play_item_id][0] + '.m2ts'))
                        r += 1
                    offset += (in_out_time[ref_to_play_item_id][2] - in_out_time[ref_to_play_item_id][1]) / 45000
                layout.addWidget(table_widget)
                this.setLayout(layout)
                height = rows * 30 + 80
                height = 1000 if height > 1000 else height
                if rows > 1:
                    this.setMinimumHeight(height)

        chapter_window = ChapterWindow()
        chapter_window.exec()

    def on_subtitle_menu(self, pos: QPoint):
        row_indexes = [i.row() for i in self.table2.selectionModel().selection().indexes()]
        column_indexes = [i.column() for i in self.table2.selectionModel().selection().indexes()]
        if any(column_index == 1 for column_index in column_indexes):
            menu = QMenu()
            item = menu.addAction('edit')
            screen_pos = self.table2.mapToGlobal(pos)
            action = menu.exec(screen_pos)
            if action == item:
                for i, row_index in enumerate(row_indexes):
                    if column_indexes[i] == 1:
                        self.edit_subtitle(self.table2.item(row_index, 1).text())

    def edit_subtitle(self, path: str):
        class SubtitleEditDialog(QDialog):
            def __init__(this):
                super(SubtitleEditDialog, this).__init__()
                this.altered = False
                this.setWindowTitle(f'edit subtitle: {path}')
                layout = QVBoxLayout()
                this.table_widget = QTableWidget()
                this.table_widget.horizontalHeader().setSortIndicatorShown(True)
                this.table_widget.setSortingEnabled(True)
                if path.endswith('.ass') or path.endswith('.ssa'):
                    try:
                        with open(path, 'r', encoding='utf-8-sig') as fp:
                            this.subtitle = Ass(fp)
                    except Exception as e:
                        with open(path, 'r', encoding='utf-16') as fp:
                            this.subtitle = Ass(fp)
                    this.keys = list(this.subtitle.events[0].__dict__.keys())
                    this.table_widget.setColumnCount(len(this.keys) + 1)
                    this.table_widget.setHorizontalHeaderLabels(['index'] + this.keys)
                    this.table_widget.setRowCount(len(this.subtitle.events))
                    for i in range(len(this.subtitle.events)):
                        this.table_widget.setItem(i, 0, QTableWidgetItem(
                            ((len(str(len(this.subtitle.events)))) - len(str(i + 1))) * '0' + str(i + 1)))
                        for j in range(len(this.keys)):
                            item = getattr(this.subtitle.events[i], this.keys[j])
                            if isinstance(item, datetime.timedelta):
                                if len(str(item)) == 14:
                                    item = str(item)[:-3]
                                elif len(str(item)) == 7:
                                    item = f'{str(item)}.000'
                            item = str(item)
                            this.table_widget.setItem(i, j + 1, QTableWidgetItem(item))
                    this.table_widget.horizontalHeader().setSortIndicator(4, Qt.SortOrder.DescendingOrder)
                    this.setMinimumWidth(1000)
                    this.setMinimumHeight(800)
                elif path.endswith('.srt'):
                    try:
                        with open(path, 'r', encoding='utf-8-sig') as fp:
                            this.subtitle = SRT(fp)
                    except Exception as e:
                        with open(path, 'r', encoding='utf-16') as fp:
                            this.subtitle = SRT(fp)
                    this.table_widget.setColumnCount(4)
                    this.table_widget.setHorizontalHeaderLabels(['index', 'start', 'end', 'text'])
                    this.table_widget.setRowCount(len(this.subtitle.lines))
                    m_len = len(str(this.subtitle.lines[-1][0]))
                    for i, line in enumerate(this.subtitle.lines):
                        this.table_widget.setItem(i, 0,
                                                  QTableWidgetItem((m_len - len(str(line[0]))) * '0' + str(line[0])))
                        this.table_widget.setItem(i, 1, QTableWidgetItem(line[1]))
                        this.table_widget.setItem(i, 2, QTableWidgetItem(line[2]))
                        this.table_widget.setItem(i, 3, QTableWidgetItem(line[3]))
                    this.table_widget.horizontalHeader().setSortIndicator(2, Qt.SortOrder.DescendingOrder)
                    this.setMinimumWidth(600)
                    this.setMinimumHeight(600)

                this.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
                this.customContextMenuRequested.connect(this.on_subtitle_edit_menu)
                this.table_widget.resizeColumnsToContents()
                layout.addWidget(this.table_widget)
                this.save_button = QPushButton('save')
                this.save_button.clicked.connect(this.save_subtitle)
                layout.addWidget(this.save_button)
                this.setLayout(layout)
                this.table_widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
                this.table_widget.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked)
                this.table_widget.itemChanged.connect(this.on_subtitle_changed)

            def on_subtitle_edit_menu(this, pos: QPoint):
                row_indexes = {i.row() for i in this.table_widget.selectionModel().selection().indexes()}
                menu = QMenu()
                item = menu.addAction('remove')
                screen_pos = this.table_widget.mapToGlobal(pos)
                action = menu.exec(screen_pos)
                if action == item:
                    row_indexes = list(row_indexes)
                    row_indexes.sort()
                    if row_indexes:
                        this.altered = True
                    for i, row_index in enumerate(row_indexes):
                        if hasattr(this.subtitle, 'lines'):
                            this.subtitle.delete_lines.add(int(this.table_widget.item(row_index - i, 0).text()))
                        else:
                            this.subtitle.delete_lines.add(int(this.table_widget.item(row_index - i, 0).text()) - 1)
                        this.table_widget.removeRow(row_index - i)

            def on_subtitle_changed(this, item: QTableWidgetItem):
                if path.endswith('.ass') or path.endswith('.ssa'):
                    setattr(this.subtitle.events[int(this.table_widget.item(item.row(), 0).text()) - 1],
                            this.keys[item.column() - 1], item.text())
                    this.altered = True
                if path.endswith('.srt'):
                    this.subtitle.lines[item.row()][item.column()] = item.text()
                    this.altered = True

            def save_subtitle(this):
                if this.altered:
                    with open(path + '.bak', 'a', encoding='utf-8-sig') as fp:
                        this.subtitle.dump_file(fp)
                    os.remove(path)
                    os.rename(path + '.bak', path)
                self.on_subtitle_folder_path_change()
                this.altered = False


        subtitle_edit_dialog = SubtitleEditDialog()
        subtitle_edit_dialog.exec()

    def on_select_function(self):
        if self.radio4.isChecked():
            self.ensure_default_vpy_file()
            if hasattr(self, 'table3'):
                self.table3.setVisible(True)
        else:
            self.delete_default_vpy_file()
            if hasattr(self, 'table3'):
                self.table3.setVisible(False)

        if self.radio1.isChecked():
            self.label2.setText("选择单集字幕所在的文件夹")
            self.exe_button.setText("生成字幕")
            self.encode_box.setVisible(False)
            if not self.checkbox1.isVisible():
                self.checkbox1.setVisible(True)
                self.restoreGeometry(self._geometry)
            self.checkbox1.setText('补全蓝光目录')
            self.table1.clear()
            self.table1.setRowCount(0)
            self.table1.setColumnCount(len(BDMV_LABELS))
            self.table1.setHorizontalHeaderLabels(BDMV_LABELS)
            self.table2.clear()
            self.table2.setRowCount(0)
            self.table2.setColumnCount(len(SUBTITLE_LABELS))
            self.table2.setHorizontalHeaderLabels(SUBTITLE_LABELS)

        if self.radio2.isChecked():
            self.label2.setText("选择mkv文件所在的文件夹")
            self.exe_button.setText("添加章节")
            self.encode_box.setVisible(False)
            if not self.checkbox1.isVisible():
                self.checkbox1.setVisible(True)
                self.restoreGeometry(self._geometry)
            self.checkbox1.setText('直接编辑原文件')
            self.table1.clear()
            self.table1.setRowCount(0)
            self.table1.setColumnCount(len(BDMV_LABELS))
            self.table1.setHorizontalHeaderLabels(BDMV_LABELS)
            self.table2.clear()
            self.table2.setRowCount(0)
            self.table2.setColumnCount(len(MKV_LABELS))
            self.table2.setHorizontalHeaderLabels(MKV_LABELS)

        if self.radio3.isChecked():
            self._geometry = self.saveGeometry()
            self.label2.setText("选择字幕文件所在的文件夹（可选）")
            self.exe_button.setText("开始remux")
            self.encode_box.setVisible(False)
            self.checkbox1.setVisible(False)
            self.table1.clear()
            self.table1.setRowCount(0)
            self.table1.setColumnCount(len(BDMV_LABELS))
            self.table1.setHorizontalHeaderLabels(BDMV_LABELS)
            self.table2.clear()
            self.table2.setRowCount(0)
            self.table2.setColumnCount(len(REMUX_LABELS))
            self.table2.setHorizontalHeaderLabels(REMUX_LABELS)

        if self.radio4.isChecked():
            self._geometry = self.saveGeometry()
            self.label2.setText("选择字幕文件所在的文件夹（可选）")
            self.exe_button.setText("开始压制")
            self.checkbox1.setVisible(False)
            self.encode_box.setVisible(True)
            self.table1.clear()
            self.table1.setRowCount(0)
            self.table1.setColumnCount(len(BDMV_LABELS))
            self.table1.setHorizontalHeaderLabels(BDMV_LABELS)
            self.table2.clear()
            self.table2.setRowCount(0)
            self.table2.setColumnCount(len(ENCODE_LABELS))
            self.table2.setHorizontalHeaderLabels(ENCODE_LABELS)
            if hasattr(self, 'table3'):
                self.table3.clear()
                self.table3.setRowCount(0)
                self.table3.setColumnCount(len(ENCODE_SP_LABELS))
                self.table3.setHorizontalHeaderLabels(ENCODE_SP_LABELS)

        self.bdmv_folder_path.clear()
        self.subtitle_folder_path.clear()

    def select_bdmv_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择文件夹")
        self.bdmv_folder_path.setText(os.path.normpath(folder))

    def select_subtitle_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择文件夹")
        self.subtitle_folder_path.setText(os.path.normpath(folder))

    def main(self):
        if self.radio1.isChecked():
            self.generate_subtitle()
        if self.radio2.isChecked():
            self.add_chapters()
        if self.radio3.isChecked():
            self.remux_episodes()
        if self.radio4.isChecked():
            self.encode_bluray()

    def encode_bluray(self):
        output_folder = os.path.normpath(QFileDialog.getExistingDirectory(self, "选择输出文件夹"))
        if not output_folder:
            return
        find_mkvtoolinx()
        progress_dialog = QProgressDialog('操作中', '取消', 0, 1000, self)
        progress_dialog.setMinimumDuration(0)
        progress_dialog.setAutoClose(False)
        progress_dialog.setAutoReset(False)
        progress_dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress_dialog.show()
        cancel_event = threading.Event()
        progress_dialog.canceled.connect(cancel_event.set)

        sub_files = [self.table2.item(i, 0).text() for i in range(0, self.table2.rowCount()) if self.table2.item(i, 0)]
        vpy_paths = []
        for i in range(self.table2.rowCount()):
            try:
                vpy_paths.append(self.get_vpy_path_from_row(i))
            except Exception:
                vpy_paths.append(self.get_default_vpy_path())
        sp_vpy_paths = []
        sp_entries = []
        if hasattr(self, 'table3'):
            for i in range(self.table3.rowCount()):
                try:
                    sp_vpy_paths.append(self.get_sp_vpy_path_from_row(i))
                except Exception:
                    sp_vpy_paths.append(self.get_default_vpy_path())
                try:
                    bdmv_index_item = self.table3.item(i, 0)
                    mpls_item = self.table3.item(i, 1)
                    m2ts_item = self.table3.item(i, 2)
                    sp_entries.append({
                        'bdmv_index': int(bdmv_index_item.text()) if bdmv_index_item and bdmv_index_item.text() else 0,
                        'mpls_file': mpls_item.text().strip() if mpls_item and mpls_item.text() else '',
                        'm2ts_file': m2ts_item.text().strip() if m2ts_item and m2ts_item.text() else ''
                    })
                except Exception:
                    sp_entries.append({'bdmv_index': 0, 'mpls_file': '', 'm2ts_file': ''})
        selected_mpls = self.get_selected_mpls_no_ext()
        if not selected_mpls:
            progress_dialog.close()
            QMessageBox.information(self, " ", "未选择原盘主mpls")
            return
        try:
            bs = BluraySubtitle(self.bdmv_folder_path.text(), sub_files, self.checkbox1.isChecked(), None)
            configuration = bs.generate_configuration_from_selected_mpls(selected_mpls, cancel_event=cancel_event)
        except _Cancelled:
            progress_dialog.close()
            return
        except Exception as e:
            QMessageBox.information(self, " ", traceback.format_exc())
            progress_dialog.close()
            return

        vspipe_mode = 'bundle' if self.vspipe_mode_combo.currentText() == '程序自带' else 'system'
        x265_mode = 'bundle' if self.x265_mode_combo.currentText() == '程序自带' else 'system'
        x265_params = self.x265_params_edit.toPlainText().strip()
        if self.sub_pack_hard_radio.isChecked():
            sub_pack_mode = 'hard'
        elif self.sub_pack_soft_radio.isChecked():
            sub_pack_mode = 'soft'
        else:
            sub_pack_mode = 'external'

        self.exe_button.setEnabled(False)
        self._encode_thread = QThread(self)
        self._encode_worker = EncodeWorker(
            self.bdmv_folder_path.text(),
            sub_files,
            self.checkbox1.isChecked(),
            output_folder,
            configuration,
            selected_mpls,
            cancel_event,
            vpy_paths,
            sp_vpy_paths,
            sp_entries,
            vspipe_mode,
            x265_mode,
            x265_params,
            sub_pack_mode
        )
        self._encode_worker.moveToThread(self._encode_thread)
        self._encode_thread.started.connect(self._encode_worker.run)
        self._encode_worker.progress.connect(progress_dialog.setValue)
        self._encode_worker.label.connect(progress_dialog.setLabelText)

        def cleanup():
            progress_dialog.close()
            self.exe_button.setEnabled(True)
            if hasattr(self, '_encode_thread') and self._encode_thread:
                self._encode_thread.quit()
                self._encode_thread.wait()
                self._encode_thread.deleteLater()
                self._encode_thread = None
            if hasattr(self, '_encode_worker') and self._encode_worker:
                self._encode_worker.deleteLater()
                self._encode_worker = None

        def on_finished():
            cleanup()
            QMessageBox.information(self, " ", "原盘压制成功！")

        def on_canceled():
            cleanup()

        def on_failed(message: str):
            cleanup()
            QMessageBox.information(self, " ", message)

        self._encode_worker.finished.connect(on_finished)
        self._encode_worker.canceled.connect(on_canceled)
        self._encode_worker.failed.connect(on_failed)
        self._encode_thread.start()

    def generate_subtitle(self, silent_mode: bool = False):
        progress_dialog = QProgressDialog('字幕生成中', '取消', 0, 1000, self)
        progress_dialog.setMinimumDuration(0)
        progress_dialog.setAutoClose(False)
        progress_dialog.setAutoReset(False)
        progress_dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress_dialog.show()
        cancel_event = threading.Event()
        progress_dialog.canceled.connect(cancel_event.set)

        sub_files = []
        for sub_index in range(self.table2.rowCount()):
            if self.sub_check_state[sub_index] != 2:
                continue
            item = self.table2.item(sub_index, 1)
            if item and item.text():
                sub_files.append(item.text())
        if not sub_files:
            progress_dialog.close()
            if not silent_mode:
                QMessageBox.information(self, " ", "未选择字幕文件")
            return False

        selected_mpls = self.get_selected_mpls_no_ext()
        if not selected_mpls:
            progress_dialog.close()
            if not silent_mode:
                QMessageBox.information(self, " ", "未选择原盘主mpls")
            return False

        self.exe_button.setEnabled(False)
        self._merge_thread = QThread(self)
        self._merge_worker = MergeWorker(
            self.bdmv_folder_path.text(),
            sub_files,
            self.checkbox1.isChecked(),
            selected_mpls,
            cancel_event
        )
        self._merge_worker.moveToThread(self._merge_thread)
        self._merge_thread.started.connect(self._merge_worker.run)
        self._merge_worker.progress.connect(progress_dialog.setValue)
        self._merge_worker.label.connect(progress_dialog.setLabelText)

        success = False

        def cleanup():
            progress_dialog.close()
            self.exe_button.setEnabled(True)
            if hasattr(self, '_merge_thread') and self._merge_thread:
                self._merge_thread.quit()
                self._merge_thread.wait()
                self._merge_thread.deleteLater()
                self._merge_thread = None
            if hasattr(self, '_merge_worker') and self._merge_worker:
                self._merge_worker.deleteLater()
                self._merge_worker = None
            self.altered = False

        def on_finished():
            nonlocal success
            success = True
            cleanup()
            if not silent_mode:
                QMessageBox.information(self, " ", "生成字幕成功！")

        def on_canceled():
            cleanup()

        def on_failed(message: str):
            cleanup()
            if not silent_mode:
                QMessageBox.information(self, " ", message)

        self._merge_worker.finished.connect(on_finished)
        self._merge_worker.canceled.connect(on_canceled)
        self._merge_worker.failed.connect(on_failed)
        self._merge_thread.start()
        if silent_mode:
            loop = QEventLoop()

            def quit_loop():
                if loop.isRunning():
                    loop.quit()

            self._merge_worker.finished.connect(quit_loop)
            self._merge_worker.canceled.connect(quit_loop)
            self._merge_worker.failed.connect(quit_loop)
            loop.exec()
        return success

    def add_chapters(self):
        if self.checkbox1.isChecked():
            progress_dialog = QProgressDialog('编辑中', '取消', 0, 1000, self)
        else:
            progress_dialog = QProgressDialog('混流中', '取消', 0, 1000, self)
        progress_dialog.show()
        # Use sorted mkv files if table is sorted, otherwise use original order
        mkv_files = self.get_mkv_files_in_table_order()
        if not mkv_files:
            mkv_files = [self.table2.item(mkv_index, 0).text() for mkv_index in range(self.table2.rowCount())]
        try:
            bs = BluraySubtitle(
                self.bdmv_folder_path.text(),
                mkv_files,
                self.checkbox1.isChecked(),
                progress_dialog
            )
            bs.add_chapter_to_mkv(mkv_files, self.table1)
            if self.checkbox1.isChecked():
                QMessageBox.information(self, " ", "添加章节成功，mkv章节已添加")
            else:
                QMessageBox.information(self, " ", "添加章节成功，生成的新mkv文件在output文件夹下")
        except Exception as e:
            QMessageBox.information(self, " ", traceback.format_exc())
        else:
            bs.completion()
        progress_dialog.close()

    def get_selected_mpls_no_ext(self) -> list[tuple[str, str]]:
        selected = []
        for bdmv_index in range(self.table1.rowCount()):
            folder_item = self.table1.item(bdmv_index, 0)
            if not folder_item:
                continue
            info: QTableWidget = self.table1.cellWidget(bdmv_index, 2)
            if not info:
                continue
            for mpls_index in range(info.rowCount()):
                main_btn: QToolButton = info.cellWidget(mpls_index, 3)
                if main_btn and main_btn.isChecked():
                    mpls_item = info.item(mpls_index, 0)
                    if not mpls_item:
                        continue
                    mpls_file = mpls_item.text()
                    selected_mpls = os.path.normpath(os.path.join(folder_item.text(), 'BDMV', 'PLAYLIST', mpls_file))
                    if selected_mpls.lower().endswith('.mpls'):
                        selected.append((folder_item.text(), selected_mpls[:-5]))
                    else:
                        selected.append((folder_item.text(), selected_mpls))
        return selected

    def remux_episodes(self):
        output_folder = os.path.normpath(QFileDialog.getExistingDirectory(self, "选择输出文件夹"))
        if not output_folder:
            return
        find_mkvtoolinx()
        progress_dialog = QProgressDialog('操作中', '取消', 0, 1000, self)
        progress_dialog.setMinimumDuration(0)
        progress_dialog.setAutoClose(False)
        progress_dialog.setAutoReset(False)
        progress_dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress_dialog.show()
        cancel_event = threading.Event()
        progress_dialog.canceled.connect(cancel_event.set)
        sub_files = [self.table2.item(i, 0).text() for i in range(0, self.table2.rowCount()) if self.table2.item(i, 0)]
        selected_mpls = self.get_selected_mpls_no_ext()
        if not selected_mpls:
            progress_dialog.close()
            QMessageBox.information(self, " ", "未选择原盘主mpls")
            return
        try:
            bs = BluraySubtitle(self.bdmv_folder_path.text(), sub_files, self.checkbox1.isChecked(), None)
            configuration = bs.generate_configuration_from_selected_mpls(selected_mpls, cancel_event=cancel_event)
        except _Cancelled:
            progress_dialog.close()
            return
        except Exception as e:
            QMessageBox.information(self, " ", traceback.format_exc())
            progress_dialog.close()
            return

        self.exe_button.setEnabled(False)
        self._remux_thread = QThread(self)
        self._remux_worker = RemuxWorker(
            self.bdmv_folder_path.text(),
            sub_files,
            self.checkbox1.isChecked(),
            output_folder,
            configuration,
            selected_mpls,
            cancel_event
        )
        self._remux_worker.moveToThread(self._remux_thread)
        self._remux_thread.started.connect(self._remux_worker.run)
        self._remux_worker.progress.connect(progress_dialog.setValue)
        self._remux_worker.label.connect(progress_dialog.setLabelText)

        def cleanup():
            progress_dialog.close()
            self.exe_button.setEnabled(True)
            if hasattr(self, '_remux_thread') and self._remux_thread:
                self._remux_thread.quit()
                self._remux_thread.wait()
                self._remux_thread.deleteLater()
                self._remux_thread = None
            if hasattr(self, '_remux_worker') and self._remux_worker:
                self._remux_worker.deleteLater()
                self._remux_worker = None

        def on_finished():
            cleanup()
            QMessageBox.information(self, " ", "原盘remux成功！")

        def on_canceled():
            cleanup()

        def on_failed(message: str):
            cleanup()
            QMessageBox.information(self, " ", message)

        self._remux_worker.finished.connect(on_finished)
        self._remux_worker.canceled.connect(on_canceled)
        self._remux_worker.failed.connect(on_failed)
        self._remux_thread.start()
        return


class CustomBox(QGroupBox):  # 为 Box 框提供拖拽文件夹的功能
    def __init__(self, title: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.title = title

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            e.accept()
        else:
            e.ignore()

    def dropEvent(self, e: QDropEvent):
        if self.title == '原盘':
            self.parent().parent().bdmv_folder_path.setText(os.path.normpath(e.mimeData().urls()[0].toLocalFile()))
        if self.title == '字幕':
            self.parent().parent().subtitle_folder_path.setText(os.path.normpath(e.mimeData().urls()[0].toLocalFile()))


def get_folder_size(folder_path: str) -> str:
    byte = 0
    for root, dirs, files in os.walk(folder_path):
        for file in files:
            byte += os.path.getsize(os.path.join(root, file))
    units = {'B': 0, 'KiB': 1, 'MiB': 2, 'GiB': 3, 'TiB': 6, 'PiB': 9}
    for unit, digits in units.items():
        if byte >= 1024:
            byte /= 1024
        else:
            return f'{round(byte, digits)} {unit}'


def get_time_str(duration: float) -> str:
    if duration == 0:
        return '0'
    try:
        duration = float(duration)
    except Exception:
        duration = 0.0
    hours, dur = divmod(duration, 3600.0)
    minutes, seconds = divmod(dur, 60.0)
    seconds = round(seconds, 3)
    if seconds >= 60.0:
        seconds -= 60.0
        minutes += 1.0
    if minutes >= 60.0:
        minutes -= 60.0
        hours += 1.0
    hs = f'{int(hours):02d}'
    ms = f'{int(minutes):02d}'
    ss = f'{seconds:06.3f}'
    return f'{hs}:{ms}:{ss}'


def get_index_to_m2ts_and_offset(chapter: Chapter) -> tuple[dict[int, str], dict[int, float]]:
    j = 1
    rows = sum(map(len, chapter.mark_info.values()))
    index_to_m2ts = {}
    index_to_offset = {}
    offset = 0
    for ref_to_play_item_id, mark_timestamps in chapter.mark_info.items():
        for mark_timestamp in mark_timestamps:
            index_to_m2ts[j] = chapter.in_out_time[ref_to_play_item_id][0] + '.m2ts'
            off = offset + (mark_timestamp -
                            chapter.in_out_time[ref_to_play_item_id][1]) / 45000
            index_to_offset[j] = off
            j += 1
        offset += (chapter.in_out_time[ref_to_play_item_id][2] -
                   chapter.in_out_time[ref_to_play_item_id][1]) / 45000
        index_to_offset[rows + j] = offset
    return index_to_m2ts, index_to_offset


def find_mkvtoolinx():
    global MKV_INFO_PATH
    if not MKV_INFO_PATH:
        if sys.platform == 'win32':
            default_mkv_info_path = r'C:\Program Files\MKVToolNix\mkvinfo.exe'
        else:
            default_mkv_info_path = '/usr/bin/mkvinfo'
        if os.path.exists(default_mkv_info_path):
            MKV_INFO_PATH = default_mkv_info_path
        else:
            MKV_INFO_PATH = QFileDialog.getOpenFileName(window, '选择mkvinfo的位置', '', 'mkvinfo*')
    global MKV_MERGE_PATH
    if not MKV_MERGE_PATH:
        if sys.platform == 'win32':
            default_mkv_merge_path = r'C:\Program Files\MKVToolNix\mkvmerge.exe'
        else:
            default_mkv_merge_path = '/usr/bin/mkvmerge'
        if os.path.exists(default_mkv_merge_path):
            MKV_MERGE_PATH = default_mkv_merge_path
        else:
            MKV_MERGE_PATH = QFileDialog.getOpenFileName(window, '选择mkvmerge的位置', '', 'mkvmerge*')
    global MKV_PROP_EDIT_PATH
    if not MKV_PROP_EDIT_PATH:
        if sys.platform == 'win32':
            default_mkv_prop_edit_path = r'C:\Program Files\MKVToolNix\mkvpropedit.exe'
        else:
            default_mkv_prop_edit_path = '/usr/bin/mkvpropedit'
        if os.path.exists(default_mkv_prop_edit_path):
            MKV_PROP_EDIT_PATH = default_mkv_prop_edit_path
        else:
            MKV_PROP_EDIT_PATH = QFileDialog.getOpenFileName(window, '选择mkvpropedit的位置', '', 'mkvpropedit*')
    global MKV_EXTRACT_PATH
    if not MKV_EXTRACT_PATH:
        if sys.platform == 'win32':
            default_mkv_extract_path = r'C:\Program Files\MKVToolNix\mkvextract.exe'
        else:
            default_mkv_extract_path = '/usr/bin/mkvextract'
        if os.path.exists(default_mkv_extract_path):
            MKV_EXTRACT_PATH = default_mkv_extract_path
        else:
            MKV_EXTRACT_PATH = QFileDialog.getOpenFileName(window, '选择mkvextract的位置', '', 'mkvextract*')


def force_remove_folder(path):
    if sys.platform == 'win32':
        FILE_ATTRIBUTE_NORMAL = 0x80
        SetFileAttributesW = ctypes.windll.kernel32.SetFileAttributesW
        SetFileAttributesW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32]
        SetFileAttributesW.restype = ctypes.c_int
        for root, dirs, files in os.walk(path, topdown=False):
            for name in files:
                SetFileAttributesW(os.path.join(root, name), FILE_ATTRIBUTE_NORMAL)
            for name in dirs:
                SetFileAttributesW(os.path.join(root, name), FILE_ATTRIBUTE_NORMAL)
        SetFileAttributesW(path, FILE_ATTRIBUTE_NORMAL)
        long_path = r'\\?\\' + os.path.abspath(path)
        shutil.rmtree(long_path, ignore_errors=True)
    else:
        if os.path.exists(path):
            shutil.rmtree(path, ignore_errors=True)



def force_remove_file(file_path):
    if sys.platform == 'win32':
        FILE_ATTRIBUTE_NORMAL = 0x80
        SetFileAttributesW = ctypes.windll.kernel32.SetFileAttributesW
        SetFileAttributesW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32]
        SetFileAttributesW.restype = ctypes.c_int
        long_path = r'\\?\\' + os.path.abspath(file_path)
        SetFileAttributesW(long_path, FILE_ATTRIBUTE_NORMAL)
        os.remove(long_path)
    else:
        if os.path.exists(file_path):
            os.remove(file_path)


def get_mpv_safe_path(extension=".mp4"):
    def clean(path):
        if not path: return None
        path = os.path.expandvars(path).strip()
        if '"' in path:
            path = path.split('"')[1]
        else:
            path = path.split(' ')[0]
        if not os.path.isabs(path):
            path = shutil.which(path)
        return path if path and os.path.exists(path) else None

    try:
        choice_path = rf"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\{extension}\UserChoice"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, choice_path) as key:
            prog_id, _ = winreg.QueryValueEx(key, "ProgId")

        if prog_id.startswith("AppX") or "WMP11" in prog_id or "Windows.Photos" in prog_id:
            return None

        base_name = prog_id.split('\\')[-1] # 去掉路径前缀
        names_to_try = [base_name]
        if not base_name.lower().endswith(".exe"):
            names_to_try.append(base_name + ".exe")
        if "mpv" in base_name.lower() and "mpv.exe" not in names_to_try:
            names_to_try.append("mpv.exe")

        for name in names_to_try:
            try:
                with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, rf"{name}\shell\open\command") as key:
                    val, _ = winreg.QueryValueEx(key, "")
                    res = clean(val)
                    if res:
                        return res
            except:
                pass

            try:
                with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, rf"Applications\{name}\shell\open\command") as key:
                    val, _ = winreg.QueryValueEx(key, "")
                    res = clean(val)
                    if res:
                        return res
            except:
                pass

            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{name}") as key:
                    val, _ = winreg.QueryValueEx(key, "")
                    res = clean(val)
                    if res:
                        return res
            except:
                pass

    except Exception:
        pass

    return None


def fix_audio_delay_to_lossless(input_file, delay_ms, output_file, track_index=0):
    """处理音频延迟。"""
    # 处理路径：防止路径中有空格，统一加上双引号
    input_file_q = f'"{input_file}"'
    output_file_q = f'"{output_file}"'

    ext = os.path.splitext(output_file)[1].lower()
    codec = "pcm_s24le"
    if ext in [".truehd", ".mlp"]:
        codec = "truehd"
    elif ext == ".flac":
        codec = "flac"

    map_str = f"-map 0:a:{track_index}"
    codec_str = f"-c:a {codec}"
    common_opts = "-hide_banner -loglevel error -y"

    if delay_ms > 0:
        # 正延迟：补静音
        cmd = f'"{FFMPEG_PATH}" {common_opts} -i {input_file_q} {map_str} -af "adelay={delay_ms}:all=1" {codec_str} {output_file_q}'

    elif delay_ms < 0:
        # 负延迟：裁剪开头
        start_time = abs(delay_ms) / 1000.0
        # 注意：-ss 放在 -i 之后保证次世代音轨的解码级精确度
        cmd = f'"{FFMPEG_PATH}" {common_opts} -i {input_file_q} -ss {start_time} {map_str} {codec_str} {output_file_q}'

    else:
        # 无延迟
        cmd = f'"{FFMPEG_PATH}" {common_opts} -i {input_file_q} {map_str} {codec_str} {output_file_q}'

    try:
        print(f"执行命令: {cmd}")
        subprocess.run(cmd, shell=True, check=True)
        print(f"处理完成: {output_file}")
    except subprocess.CalledProcessError as e:
        print(f"FFmpeg 执行出错: {e}")


def get_effective_bit_depth(file_path):
    if soundfile is None:
        return 24
    info = soundfile.info(file_path)
    frames = min(int(info.frames), int(info.samplerate) * 10)
    start = int(info.frames) // 2 if int(info.frames) > (frames * 2) else 0
    data, sr = soundfile.read(file_path, start=start, frames=frames, dtype='int32')
    return 16 if np.all(data % 65536 == 0) else 24


def get_audio_duration(file_path):
    """获取音频总时长（秒）"""
    cmd = f'"{FFPROBE_PATH}" -v error -show_entries format=duration:stream=duration -of json "{file_path}"'
    try:
        proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, encoding='utf-8')
    except Exception:
        return 0.0
    if proc.returncode != 0 or not (proc.stdout or '').strip():
        return 0.0
    try:
        data = json.loads(proc.stdout)
    except Exception:
        return 0.0
    try:
        duration = (data.get('format') or {}).get('duration')
        if duration not in (None, '', 'N/A'):
            return float(duration)
    except Exception:
        pass
    try:
        streams = data.get('streams') or []
        if streams:
            duration = (streams[0] or {}).get('duration')
            if duration not in (None, '', 'N/A'):
                return float(duration)
    except Exception:
        pass
    return 0.0


def get_compressed_effective_depth(file_path, check_duration=10):
    """自适应长度的有效位深检测"""
    if soundfile is None:
        return 24
    total_duration = get_audio_duration(file_path)
    start_time = total_duration / 2 if total_duration > (check_duration * 2) else 0.0
    fd, temp_wav = tempfile.mkstemp(prefix=f"temp_depth_check_{os.getpid()}_", suffix=".wav")
    os.close(fd)

    try:
        cmd = f'"{FFMPEG_PATH}" -hide_banner -loglevel error -ss {start_time} -i "{file_path}" -t {check_duration} -map 0:a:0 -c:a pcm_s24le "{temp_wav}" -y'
        subprocess.run(cmd, shell=True, check=True)
        data, sr = soundfile.read(temp_wav, dtype='int32')
        is_16bit = np.all(data % 65536 == 0)
        return 16 if is_16bit else 24
    finally:
        if os.path.exists(temp_wav):
            os.remove(temp_wav)


def get_vspipe_context():
    """
    针对“整包嵌套”方案的路径获取函数。
    """
    # 1. 获取解压后的根目录
    bundle_dir = getattr(sys, '_MEIPASS', os.path.abspath("."))

    # 2. 定位嵌套的 release 文件夹
    # 路径结构：_MEIPASS/vs_pkg/vspipe.exe
    vs_pkg_dir = os.path.join(bundle_dir, "vs_pkg")

    # 3. 构造环境
    env = os.environ.copy()

    # 清理主程序的 Python 干扰
    env.pop('PYTHONHOME', None)
    env.pop('PYTHONPATH', None)

    if sys.platform == 'win32':
        vspipe_exe = os.path.join(vs_pkg_dir, "vspipe.exe")
        # 关键：由于 python313.dll 在 vs_pkg 根目录，我们要把 vs_pkg 加进 PATH
        env['PATH'] = f"{vs_pkg_dir};{env.get('PATH', '')}"
        # 告诉 vspipe 它的 Python 环境就在它所在的那个嵌套文件夹里
        env['PYTHONHOME'] = vs_pkg_dir
        # 插件路径：对应你 release-x64 里的原始结构
        env['VAPOURSYNTH_PLUGINS'] = os.path.join(vs_pkg_dir, "vapoursynth64", "coreplugins")

    else:  # Linux
        vspipe_exe = os.path.join(vs_pkg_dir, "vspipe")
        env['LD_LIBRARY_PATH'] = f"{vs_pkg_dir}:{env.get('LD_LIBRARY_PATH', '')}"
        env['PYTHONHOME'] = vs_pkg_dir
        env['PATH'] = f"{vs_pkg_dir}:{env.get('PATH', '')}"
        # 假设 Linux 下插件目录结构一致
        env['VAPOURSYNTH_PLUGINS'] = os.path.join(vs_pkg_dir, "plugins")

    return vspipe_exe, env


if __name__ == "__main__":
    multiprocessing.freeze_support()
    app = QApplication(sys.argv)
    app.setStyleSheet('''     
        QMainWindow {
            background-color: white;
        }

        QWidget {
            background-color: #F5F5F5;
        }

        QVBoxLayout, QHBoxLayout {
            spacing: 10px;
            margin: 5px;
        }

        QGroupBox {
            border: 1px solid #CCCCCC;
            margin-top: 14px;
            padding: 8px;
        }

        QGroupBox::title {
            subcontrol-origin: margin;
            subcontrol-position: top left;
            left: 10px;
            padding: 0 6px;
        }

        QLineEdit {
            font-size: 12px;
            padding: 4px;
            border: 1px solid #DDDDDD;
            border-radius: 4px;
        }

        QLineEdit:focus {
            border: 1px solid transparent;
            border-bottom: 1px solid #007BFF;
        }

        QPushButton {
            background-color: #CCCCCC;
            color: white;
            border: none;
            border-radius: 5px;
            padding: 5px;
            font-size: 14px;
        }

        QPushButton:hover {
            background-color: #AAAAAA;
        }

        QPushButton:pressed {
            background-color: #999999;
        }

        QPushButton:disabled {
            background-color: #CCCCCC;
            color: #999999;
        }

        QToolButton {
            background-color: white;
            border: none;
            border-radius: 5px;
            padding: 5px;
        }

        QToolButton:hover {
            background-color: #BBBBBB;
        }

        QToolButton:pressed {
            background-color: #AAAAAA;
        }

        QToolButton:checked {
            background-color: #CCCCCC;
            color: #999999;
        }

        QTableView {
            background-color: white;
            border: 1px solid #CCCCCC;
            border-radius: 3px;
            padding: 5px;
        }

        QTableView::item:selected {
            background-color: #BBBBBB;
            color: white;
        }   
        
        QCheckBox {
            spacing: 6px;
            font-size: 14px;
        }

        QCheckBox::indicator {
            width: 16px;
            height: 16px;
            border-radius: 3px;
        }

        QCheckBox::indicator:unchecked {
            border: 1px solid #999999;
            background-color: white;
        }

        QCheckBox::indicator:checked {
            border: 1px solid #888888;
            background-color: #888888;
        }

        QCheckBox::indicator:unchecked:hover {
            border: 1px solid #888888;
        }

        QRadioButton {
            spacing: 6px;
            font-size: 14px;
        }

        QRadioButton::indicator {
            width: 16px;
            height: 16px;
            border-radius: 8px;
            border: 1px solid #999999;
            background-color: white;
        }

        QRadioButton::indicator:checked {
            border: 1px solid #888888;
            background-color: #888888;
        }

        QRadioButton::indicator:checked:hover {
            border: 1px solid #666666;
            background-color: #666666;
        }

        QRadioButton::indicator:unchecked:hover {
            border: 1px solid #888888;
        }

        QTableView::indicator {
            width: 16px;
            height: 16px;
            border-radius: 3px;
        }
        QTableView::indicator:unchecked {
            border: 1px solid #999999;
            background-color: white;
        }
        QTableView::indicator:checked {
            border: 1px solid #888888;
            background-color: #888888;
        }
        QTableView::indicator:unchecked:hover {
            border: 1px solid #888888;
        }
        
        QMenu {
            font-size: 14px;
        } 
        '''
                      )
    window = BluraySubtitleGUI()
    window.show()
    sys.exit(app.exec())
