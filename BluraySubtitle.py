import _io
import ctypes
import datetime
import os
import re
import shutil
import subprocess
import sys
import traceback
from dataclasses import dataclass
from functools import reduce, partial
from struct import unpack
from typing import Optional, Generator, Callable

from PyQt6.QtCore import QCoreApplication, Qt, QPoint
from PyQt6.QtGui import QPainter, QColor, QDragMoveEvent, QDropEvent, QPaintEvent, QDragEnterEvent
from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QFileDialog, QLabel, QToolButton, QLineEdit, \
    QMessageBox, QHBoxLayout, QGroupBox, QCheckBox, QProgressDialog, QRadioButton, QButtonGroup, \
    QTableWidget, QTableWidgetItem, QDialog, QPushButton, QComboBox, QMenu, QAbstractItemView

MKV_INFO_PATH = ''
MKV_MERGE_PATH = ''
MKV_PROP_EDIT_PATH = ''
BDMV_LABELS = ['path', 'size', 'info']
SUBTITLE_LABELS = ['select', 'path', 'duration', 'bdmv_index', 'chapter_index', 'offset']
MKV_LABELS = ['path', 'duration']
CONFIGURATION = {}


class Chapter:
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
        formats: dict[int, str] = {1: '>B', 2: '>H', 4: '>I', 8: '>Q'}
        return unpack(formats[n], self.mpls_file.read(n))[0]

    def get_total_time(self):  # 获取播放列表的总时长
        return sum(map(lambda x: (x[2] - x[1]) / 45000, self.in_out_time))

    def get_total_time_no_repeat(self):  # 获取播放列表中时长，重复播放同一文件只计算一次
        return sum({x[0]: (x[2] - x[1]) / 45000 for x in self.in_out_time}.values())


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
        for line in self.raw.split('\n'):
            if re.match(r'^(\d+)$', line):
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


class Subtitle:
    def __init__(self, file_path: str):
        self.max_end = 0
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
        if new_file_path.endswith('.srt'):
            index = self.content.lines[-1][0]
            for line in new_content.lines:
                line[0] += index
                start_time = reduce(lambda a, b: a * 60 + b, map(float, line[1].replace(',', '.').split(':')))
                end_time = reduce(lambda a, b: a * 60 + b, map(float, line[2].replace(',', '.').split(':')))
                line[1] = get_time_str(start_time + time_shift)
                line[2] = get_time_str(end_time + time_shift)
            self.content.lines.extend(new_content.lines)
        else:  # ass 字幕合并，需要注意如果存在同名 Style 但实际 Style 样式不同时，需要将另一个同名 Style 改名
            style_info = {repr(style) for style in self.content.styles}
            style_name_map = {}
            for style in new_content.styles:
                if repr(style) not in style_info:
                    old_name = style.Name
                    flag = False
                    while any(style.Name == _style.Name for _style in self.content.styles):
                        style.Name += "1"
                        if repr(style) in style_info:
                            flag = True
                            break
                    if flag:
                        continue
                    style_name_map[old_name] = style.Name
                    self.content.styles.append(style)
                    style_info.add(repr(style))

            time_shift = datetime.timedelta(seconds=time_shift)
            for event in new_content.events:
                event.Start += time_shift
                event.End += time_shift
                if event.Style in style_name_map:
                    event.Style = style_name_map[event.Style]
                self.content.events.append(event)

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
        if hasattr(self.content, 'lines'):
            return max(
                map(
                    lambda line: reduce(lambda a, b: a * 60 + b, map(float, line[2].replace(',', '.').split(':'))),
                    self.content.lines
                )
            )
        if self.max_end:
            return self.max_end
        end_set = set(map(lambda event: event.End.total_seconds(), self.content.events))
        max_end = max(end_set)
        end_set.remove(max_end)
        max_end_1 = max(end_set)
        if max_end_1 < max_end - 300:
            return max_end_1  # 防止个别 Event 结束时间超长(比如评论音轨超出那一集的结束时间)
        else:
            return max_end


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

    def get_duration(self):
        subprocess.Popen(rf'"{MKV_INFO_PATH}" "{self.path}" -r mkvinfo.txt --ui-language en').wait()
        pattern = '| + Duration: '
        duration = 0
        with open('mkvinfo.txt', 'r', encoding='utf-8-sig') as f:
            for line in f:
                if line[:len(pattern)] == pattern:
                    time_str = line[len(pattern):]
                    duration = int(time_str[:2]) * 3600 + int(time_str[3:5]) * 60 + float(time_str[6:])
        return duration

    def add_chapter(self, edit_file: bool):
        if edit_file:
            subprocess.Popen(rf'"{MKV_PROP_EDIT_PATH}" "{self.path}" --chapters chapter.txt').wait()
        else:
            new_path = os.path.join(os.path.dirname(self.path), 'output', os.path.basename(self.path))
            subprocess.Popen(rf'"{MKV_MERGE_PATH}" --chapters chapter.txt -o "{new_path}" "{self.path}"').wait()


class BluraySubtitle:
    def __init__(self, bluray_path:str, sub_files: list[str] = None, checked: bool = True,
                 progress_dialog: Optional[QProgressDialog] = None):
        self.tmp_folders = []
        if sys.platform == 'win32':
            for root, dirs, files in os.walk(bluray_path):
                for file in files:
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
        self.bluray_folders = [root for root, dirs, files in os.walk(bluray_path) if 'BDMV' in dirs
                               and 'PLAYLIST' in os.listdir(os.path.join(root, 'BDMV'))]
        self.checked = checked
        self.progress_dialog = progress_dialog
        self.configuration = {}

    @staticmethod
    def get_available_drives():
        drives = []
        bitmask = ctypes.windll.kernel32.GetLogicalDrives()
        for letter in range(65, 91):
            if bitmask & 1:
                drives.append(chr(letter))
            bitmask >>= 1
        return set(drives)

    def get_main_mpls(self, bluray_folder: str) -> str:
        mpls_folder = os.path.join(bluray_folder, 'BDMV', 'PLAYLIST')
        selected_mpls = None
        max_indicator = 0
        for mpls_file_name in os.listdir(mpls_folder):
            if mpls_file_name[-5:].lower() != '.mpls':
                continue
            mpls_file_path = os.path.join(mpls_folder, mpls_file_name)
            chapter = Chapter(mpls_file_path)
            indicator = chapter.get_total_time_no_repeat() * (1 + sum(map(len, chapter.mark_info.values())) / 5)
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
        if sub_combo_index:
            chapter_index = sub_combo_index[sub_index]
            for folder, chapter, selected_mpls in self.select_mpls_from_table(table):
                for bdmv_index in range(table.rowCount()):
                    bluray_folder = table.item(bdmv_index, 0).text()
                    if bluray_folder == folder:
                        break
                bdmv_index += 1
                offset = 0
                j = 1
                left_time = chapter.get_total_time()
                sub_end_time = Subtitle(self.sub_files[sub_index]).max_end_time()
                for i, play_item_in_out_time in enumerate(chapter.in_out_time):
                    play_item_marks = chapter.mark_info.get(i)
                    if sub_index <= subtitle_index and j == chapter_index:
                        sub_end_time = offset + Subtitle(self.sub_files[sub_index]).max_end_time()
                        configuration[sub_index] = {'folder': folder, 'selected_mpls': selected_mpls,
                                                    'bdmv_index': bdmv_index, 'chapter_index': j,
                                                    'offset': get_time_str(offset)}
                        sub_index += 1
                        if sub_combo_index.get(sub_index):
                            chapter_index = sub_combo_index[sub_index]
                    elif sub_index > subtitle_index:
                        if offset > sub_end_time - 300 or offset == 0:
                            if (sub_index + 1 < len(self.sub_files)
                                    and left_time > Subtitle(self.sub_files[sub_index + 1]).max_end_time() - 180):
                                sub_end_time = offset + Subtitle(self.sub_files[sub_index]).max_end_time()
                                configuration[sub_index] = {'folder': folder, 'selected_mpls': selected_mpls,
                                                            'bdmv_index': bdmv_index, 'chapter_index': j,
                                                            'offset': get_time_str(offset)}
                                sub_index += 1
                    if play_item_marks:
                        for mark in play_item_marks:
                            time_shift = offset + (mark - play_item_in_out_time[1]) / 45000
                            if sub_index <= subtitle_index and j == chapter_index:
                                sub_end_time = time_shift + Subtitle(self.sub_files[sub_index]).max_end_time()
                                configuration[sub_index] = {'folder': folder, 'selected_mpls': selected_mpls,
                                                            'bdmv_index': bdmv_index, 'chapter_index': j,
                                                            'offset': get_time_str(time_shift)}
                                sub_index += 1
                                if sub_combo_index.get(sub_index):
                                    chapter_index = sub_combo_index[sub_index]
                            elif sub_index > subtitle_index:
                                if time_shift > sub_end_time and (
                                        play_item_in_out_time[2] - mark) / 45000 > 1200:
                                    sub_end_time = time_shift + Subtitle(self.sub_files[sub_index]).max_end_time()
                                    configuration[sub_index] = {'folder': folder, 'selected_mpls': selected_mpls,
                                                                'bdmv_index': bdmv_index, 'chapter_index': j,
                                                                'offset': get_time_str(time_shift)}
                                    sub_index += 1
                            j += 1
                    offset += (play_item_in_out_time[2] - play_item_in_out_time[1]) / 45000
                    left_time += (play_item_in_out_time[1] - play_item_in_out_time[2]) / 45000
            CONFIGURATION = configuration
            return configuration
        else:
            for folder, chapter, selected_mpls in self.select_mpls_from_table(table):
                for bdmv_index in range(table.rowCount()):
                    bluray_folder = table.item(bdmv_index, 0).text()
                    if bluray_folder == folder:
                        break
                bdmv_index += 1
                start_time = 0
                sub_end_time = Subtitle(self.sub_files[sub_index]).max_end_time()
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
                            if (sub_index + 1 < len(self.sub_files)
                                    and left_time > Subtitle(self.sub_files[sub_index + 1]).max_end_time() - 180):
                                sub_index += 1
                                sub_end_time = time_shift + Subtitle(self.sub_files[sub_index]).max_end_time()
                                configuration[sub_index] = {'folder': folder, 'selected_mpls': selected_mpls,
                                                            'bdmv_index': bdmv_index, 'chapter_index': j,
                                                            'offset': get_time_str(time_shift)}

                        if play_item_duration_time / 45000 > 2600 and sub_end_time - time_shift < 1800:
                            k = j
                            for mark in play_item_marks:
                                k += 1
                                time_shift = (start_time + mark - play_item_in_out_time[1]) / 45000
                                if time_shift > sub_end_time and (
                                        play_item_in_out_time[2] - mark) / 45000 > 1200:
                                    sub_index += 1
                                    sub_end_time = time_shift + Subtitle(self.sub_files[sub_index]).max_end_time()
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

    def generate_bluray_subtitle(self, table: QTableWidget):
        if not CONFIGURATION:
            self.configuration = self.generate_configuration(table)
        else:
            self.configuration = CONFIGURATION
        sub = Subtitle(self.sub_files[0])
        bdmv_index = 0
        conf = self.configuration[0]
        for sub_index, conf_tmp in self.configuration.items():
            self.progress_dialog.setValue(int((sub_index + 1) / len(self.sub_files) * 1000))
            QCoreApplication.processEvents()
            if conf_tmp['bdmv_index'] != bdmv_index:
                if bdmv_index > 0:
                    sub.dump(conf['folder'], conf['selected_mpls'])
                    sub = Subtitle(self.sub_files[sub_index])
                bdmv_index = conf_tmp['bdmv_index']
            else:
                sub.append_ass(self.sub_files[sub_index],
                               reduce(lambda a, b: a * 60 + b, map(float, conf_tmp['offset'].split(':'))))
            conf = conf_tmp
        sub.dump(conf['folder'], conf['selected_mpls'])
        self.progress_dialog.setValue(1000)
        QCoreApplication.processEvents()

    def add_chapter_to_mkv(self, table: QTableWidget):
        mkv_files = self.sub_files
        mkv_index = 0
        for folder, chapter, selected_mpls in self.select_mpls_from_table(table):
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
                        self.progress_dialog.setValue(int((mkv_index + 1) / len(mkv_files) * 1000))
                        QCoreApplication.processEvents()
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
            self.progress_dialog.setValue(int((mkv_index + 1) / len(mkv_files) * 1000))
            QCoreApplication.processEvents()
            mkv_index += 1

        self.progress_dialog.setValue(1000)
        QCoreApplication.processEvents()

    def completion(self, folder: str):  # 补全蓝光目录；删除临时文件
        if self.checked:
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
                shutil.rmtree(tmp_folder)
            except:
                pass
        if os.path.exists('chapter.txt'):
            try:
                os.remove('chapter.txt')
            except:
                pass
        if os.path.exists('mkvinfo.txt'):
            try:
                os.remove('mkvinfo.txt')
            except:
                pass


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


class BluraySubtitleGUI(QWidget):
    def __init__(self):
        super().__init__()
        self.init_ui()
        self.altered = False

    def init_ui(self):
        self.setWindowTitle("BluraySubtitle")
        self.setMinimumWidth(860)
        self.setMinimumHeight(1000)

        self.layout = QVBoxLayout()

        function_button = QGroupBox('选择功能', self)
        h_layout = QHBoxLayout()
        function_button.setLayout(h_layout)
        self.subtitle_folder_path = QLineEdit()
        self.subtitle_folder_path.setMinimumWidth(200)

        self.radio1 = QRadioButton(self)
        self.radio1.setText("生成合并字幕")
        self.radio1.setChecked(True)
        self.radio2 = QRadioButton(self)
        self.radio2.setText("给mkv添加章节")
        group = QButtonGroup(self)
        group.addButton(self.radio1)
        group.addButton(self.radio2)
        group.buttonClicked.connect(self.on_select_function)
        h_layout.addWidget(self.radio1)
        h_layout.addWidget(self.radio2)
        self.layout.addWidget(function_button)

        bdmv = QGroupBox()
        v_layout = QVBoxLayout()
        bdmv.setLayout(v_layout)
        bluray_path_box = CustomBox('原盘', self)
        h_layout = QHBoxLayout()
        bluray_path_box.setLayout(h_layout)
        self.label1 = QLabel("选择原盘所在的文件夹：", self)
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
        self.subtitle_folder_path.textChanged.connect(self.on_subtitle_folder_path_change)
        v_layout.addWidget(self.table2)
        self.layout.addWidget(subtitle)

        self.checkbox1 = QCheckBox("补全蓝光目录")
        self.checkbox1.setChecked(True)
        self.layout.addWidget(self.checkbox1)
        self.exe_button = QPushButton("生成字幕")
        self.exe_button.clicked.connect(self.main)
        self.exe_button.setMinimumHeight(50)
        self.layout.addWidget(self.exe_button)

        self.setLayout(self.layout)

    def on_bdmv_folder_path_change(self):
        if self.bdmv_folder_path.text().strip():
            try:
                self.table1.setColumnCount(len(BDMV_LABELS))
                self.table1.setHorizontalHeaderLabels(BDMV_LABELS)
                i = 0
                for root, dirs, files in os.walk(self.bdmv_folder_path.text().strip()):
                    if 'BDMV' in dirs and 'PLAYLIST' in os.listdir(os.path.join(root, 'BDMV')):
                        i += 1
                self.table1.setRowCount(i)
                i = 0
                for root, dirs, files in os.walk(self.bdmv_folder_path.text().strip()):
                    if 'BDMV' in dirs and 'PLAYLIST' in os.listdir(os.path.join(root, 'BDMV')):
                        table_widget = QTableWidget()
                        table_widget.setColumnCount(5)
                        table_widget.setHorizontalHeaderLabels(['mpls_file', 'duration', 'chapters', 'main', 'play'])
                        mpls_n = 0
                        for mpls_file in os.listdir(os.path.join(root, 'BDMV', 'PLAYLIST')):
                            if mpls_file.endswith('.mpls'):
                                mpls_n += 1
                        table_widget.setRowCount(mpls_n)
                        mpls_n = 0
                        selected_mpls = os.path.normpath(BluraySubtitle(root).get_main_mpls(root))
                        for mpls_file in os.listdir(os.path.join(root, 'BDMV', 'PLAYLIST')):
                            if mpls_file.endswith('.mpls'):
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
                        self.table1.setItem(i, 0, QTableWidgetItem(os.path.normpath(root)))
                        self.table1.setItem(i, 1, QTableWidgetItem(get_folder_size(root)))
                        self.table1.setCellWidget(i, 2, table_widget)
                        self.table1.setRowHeight(i, 100)
                        i += 1
                self.table1.resizeColumnsToContents()
                self.table1.setColumnWidth(2, 410)
            except Exception as e:
                self.table1.clear()
                self.table1.setColumnCount(len(BDMV_LABELS))
                self.table1.setHorizontalHeaderLabels(BDMV_LABELS)
        self.altered = True

    def on_subtitle_folder_path_change(self):
        if self.radio1.isChecked():
            if self.subtitle_folder_path.text().strip():
                try:
                    subtitle_folder = self.subtitle_folder_path.text()
                    n = 0
                    for path in os.listdir(subtitle_folder):
                        if path.endswith(".ass") or path.endswith(".ssa") or path.endswith('srt'):
                            n += 1
                    self.table2.setColumnCount(len(SUBTITLE_LABELS))
                    self.table2.setHorizontalHeaderLabels(SUBTITLE_LABELS)
                    self.table2.setRowCount(n)
                    n = 0
                    for path in os.listdir(subtitle_folder):
                        if path.endswith(".ass") or path.endswith(".ssa") or path.endswith('srt'):
                            pth = os.path.normpath(os.path.join(subtitle_folder, path))
                            check_item = QTableWidgetItem()
                            check_item.setFlags(check_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                            check_item.setCheckState(Qt.CheckState.Checked)
                            self.table2.setItem(n, 0, check_item)
                            self.table2.setItem(n, 1, QTableWidgetItem(pth))
                            self.table2.setItem(n, 2, QTableWidgetItem(get_time_str(Subtitle(pth).max_end_time())))
                            n += 1
                    for bdmv_index in range(self.table1.rowCount()):
                        info: QTableWidget = self.table1.cellWidget(bdmv_index, 2)
                        for mpls_index in range(info.rowCount()):
                            main_btn: QToolButton = info.cellWidget(mpls_index, 3)
                            if main_btn.isChecked():
                                info.cellWidget(mpls_index, 4).setText('preview')
                        info.resizeColumnsToContents()
                    self.sub_check_state = [self.table2.item(sub_index, 0).checkState().value for sub_index in
                                            range(self.table2.rowCount())]
                    sub_files = [self.table2.item(sub_index, 1).text() for sub_index in range(self.table2.rowCount())
                                 if self.sub_check_state[sub_index] == 2]
                    configuration = BluraySubtitle(
                        self.bdmv_folder_path.text(),
                        sub_files,
                        self.checkbox1.isChecked(),
                        None
                    ).generate_configuration(self.table1)
                    self.on_configuration(configuration)
                    self.sub_check_state = [2 for sub_index in range(self.table2.rowCount())]
                    self.table2.cellClicked.connect(self.on_subtitle_select)
                    self.table2.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
                    self.table2.customContextMenuRequested.connect(self.on_subtitle_menu)
                except:
                    traceback.print_exc()
                    self.table2.clear()
                    self.table2.setColumnCount(len(SUBTITLE_LABELS))
                    self.table2.setHorizontalHeaderLabels(SUBTITLE_LABELS)
        else:
            if self.subtitle_folder_path.text().strip():
                try:
                    root = self.subtitle_folder_path.text().strip()
                    mkv_path = [os.path.normpath(os.path.join(root, file))
                                for file in os.listdir(root) if file.endswith('.mkv')]
                    self.table2.setRowCount(len(mkv_path))
                    for i in range(len(mkv_path)):
                        self.table2.setItem(i, 0, QTableWidgetItem(mkv_path[i]))
                        self.table2.setItem(i, 1, QTableWidgetItem(get_time_str(MKV(mkv_path[i]).get_duration())))
                    self.table2.resizeColumnsToContents()
                except:
                    traceback.print_exc()
                    self.table2.clear()
                    self.table2.setColumnCount(len(MKV_LABELS))
                    self.table2.setHorizontalHeaderLabels(MKV_LABELS)

    def on_subtitle_drop(self):
        sub_files = [self.table2.item(sub_index, 1).text() for sub_index in range(self.table2.rowCount())
                     if self.sub_check_state[sub_index] == 2]
        configuration = BluraySubtitle(
            self.bdmv_folder_path.text(),
            sub_files,
            self.checkbox1.isChecked(),
            None
        ).generate_configuration(self.table1)
        self.on_configuration(configuration)

    def on_subtitle_select(self):
        sub_check_state = [self.table2.item(sub_index, 0).checkState().value for sub_index in
                           range(self.table2.rowCount())]
        if sub_check_state != self.sub_check_state:
            self.sub_check_state = sub_check_state
            sub_files = [self.table2.item(sub_index, 1).text() for sub_index in range(self.table2.rowCount())
                         if self.sub_check_state[sub_index] == 2]
            configuration = BluraySubtitle(
                self.bdmv_folder_path.text(),
                sub_files,
                self.checkbox1.isChecked(),
                None
            ).generate_configuration(self.table1)
            self.on_configuration(configuration)
        for sub_index, check_state in enumerate(self.sub_check_state):
            if check_state != 2:
                self.table2.setItem(sub_index, 3, None)
                self.table2.setCellWidget(sub_index, 4, None)
                self.table2.setItem(sub_index, 5, None)

    def on_configuration(self, configuration: dict[int, dict[str, int | str]]):
        for subtitle_index in range(self.table2.rowCount()):
            con = configuration.get(subtitle_index)
            sub_check_state = [self.table2.item(sub_index, 0).checkState().value for sub_index in
                               range(self.table2.rowCount())]
            index_table = [sub_index for sub_index in range(len(sub_check_state)) if sub_check_state[sub_index] == 2]
            if con:
                self.table2.setItem(index_table[subtitle_index], 3, QTableWidgetItem(str(con['bdmv_index'])))
                chapter_combo = QComboBox()
                for bi in range(self.table1.rowCount()):
                    if bi + 1 == con['bdmv_index']:
                        info: QTableWidget = self.table1.cellWidget(bi, 2)
                        for mi in range(info.rowCount()):
                            main_btn: QToolButton = info.cellWidget(mi, 3)
                            if main_btn.isChecked():
                                mpls_file = info.item(mi, 0).text()
                                root = self.table1.item(bi, 0).text()
                                select_mpls = os.path.join(root, 'BDMV', 'PLAYLIST', mpls_file)
                                rows = sum(map(len, Chapter(select_mpls).mark_info.values()))
                                chapter_combo.addItems([str(r + 1) for r in range(rows)])
                                chapter_combo.setCurrentIndex(con['chapter_index'] - 1)
                                chapter_combo.currentIndexChanged.connect(
                                    partial(self.on_chapter_combo, subtitle_index))
                self.table2.setCellWidget(index_table[subtitle_index], 4, chapter_combo)
                self.table2.setItem(index_table[subtitle_index], 5, QTableWidgetItem(con['offset']))
            elif subtitle_index <= len(index_table) - 1:
                self.table2.setItem(index_table[subtitle_index], 3, None)
                self.table2.setCellWidget(index_table[subtitle_index], 4, None)
                self.table2.setItem(index_table[subtitle_index], 5, None)
        self.table2.resizeColumnsToContents()
        self.altered = True

    def on_chapter_combo(self, subtitle_index: int):
        sub_files = [self.table2.item(sub_index, 1).text() for sub_index in range(self.table2.rowCount()) if
                     self.sub_check_state[sub_index] == 2]
        sub_combo_index = {}
        for sub_index in range(self.table2.rowCount()):
            if self.sub_check_state[sub_index] == 2:
                if self.table2.cellWidget(sub_index, 4):
                    sub_combo_index[sub_index] = self.table2.cellWidget(sub_index, 4).currentIndex() + 1
        try:
            configuration = BluraySubtitle(
                self.bdmv_folder_path.text(),
                sub_files,
                self.checkbox1.isChecked(),
                None
            ).generate_configuration(self.table1, sub_combo_index, subtitle_index)
            self.on_configuration(configuration)
        except Exception as e:
            traceback.print_exc()

    def on_button_play(self, mpls_path: str, btn: QToolButton):
        if btn.text() == 'preview' and self.altered:
            self.generate_subtitle()
        os.startfile(mpls_path)

    def on_button_main(self, mpls_path: str):
        for bdmv_index in range(self.table1.rowCount()):
            if mpls_path.startswith(self.table1.item(bdmv_index, 0).text()):
                info: QTableWidget = self.table1.cellWidget(bdmv_index, 2)
                for mpls_index in range(info.rowCount()):
                    if mpls_path.endswith(info.item(mpls_index, 0).text()):
                        checked = info.cellWidget(mpls_index, 3).isChecked()
                        if checked:
                            subtitle = bool(self.table2.rowCount() > 0 and self.table2.item(0, 0).text())
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
        if self.radio1.isChecked():
            self.label2.setText("选择单集字幕所在的文件夹")
            self.exe_button.setText("生成字幕")
            self.checkbox1.setText('补全蓝光目录')
            self.table1.clear()
            self.table1.setColumnCount(len(BDMV_LABELS))
            self.table1.setHorizontalHeaderLabels(BDMV_LABELS)
            self.table2.clear()
            self.table2.setColumnCount(len(SUBTITLE_LABELS))
            self.table2.setHorizontalHeaderLabels(SUBTITLE_LABELS)
        if self.radio2.isChecked():
            self.label2.setText("选择mkv文件所在的文件夹")
            self.exe_button.setText("添加章节")
            self.checkbox1.setText('直接编辑原文件')
            self.table1.clear()
            self.table1.setColumnCount(len(BDMV_LABELS))
            self.table1.setHorizontalHeaderLabels(BDMV_LABELS)
            self.table2.clear()
            self.table2.setColumnCount(len(MKV_LABELS))
            self.table2.setHorizontalHeaderLabels(MKV_LABELS)
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

    def generate_subtitle(self):
        progress_dialog = QProgressDialog('字幕生成中', '取消', 0, 1000, self)
        progress_dialog.show()
        sub_files = [self.table2.item(sub_index, 1).text() for sub_index in range(self.table2.rowCount()) if
                     self.sub_check_state[sub_index] == 2]
        try:
            BluraySubtitle(
                self.bdmv_folder_path.text(),
                sub_files,
                self.checkbox1.isChecked(),
                progress_dialog
            ).generate_bluray_subtitle(self.table1)
            QMessageBox.information(self, " ", "生成字幕成功！")
        except Exception as e:
            QMessageBox.information(self, " ", traceback.format_exc())
        progress_dialog.close()
        self.altered = False

    def add_chapters(self):
        if self.checkbox1.isChecked():
            progress_dialog = QProgressDialog('编辑中', '取消', 0, 1000, self)
        else:
            progress_dialog = QProgressDialog('混流中', '取消', 0, 1000, self)
        progress_dialog.show()
        mkv_files = [self.table2.item(mkv_index, 0).text() for mkv_index in range(self.table2.rowCount())]
        try:
            BluraySubtitle(
                self.bdmv_folder_path.text(),
                mkv_files,
                self.checkbox1.isChecked(),
                progress_dialog
            ).add_chapter_to_mkv(self.table1)
            if self.checkbox1.isChecked():
                QMessageBox.information(self, " ", "添加章节成功，mkv章节已添加")
            else:
                QMessageBox.information(self, " ", "添加章节成功，生成的新mkv文件在output文件夹下")
        except Exception as e:
            QMessageBox.information(self, " ", traceback.format_exc())
        progress_dialog.close()


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
    hours, dur = divmod(duration, 3600)
    minutes, seconds = divmod(dur, 60)
    seconds = round(seconds, 3)
    hs = '0' + str(int(hours)) if len(str(int(hours))) == 1 else str(int(hours))
    ms = '0' + str(int(minutes)) if len(str(int(minutes))) == 1 else str(int(minutes))
    s1, s2 = str(seconds).split('.')
    ss = ('0' + s1 if len(s1) == 1 else s1) + '.' + (s2 + (3 - len(s2)) * '0' if len(s2) < 3 else s2)
    return f'{hs}:{ms}:{ss}'


if __name__ == "__main__":
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
            padding: 8px;
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
        
        QMenu {
            font-size: 14px;
        } 
        '''
                      )
    window = BluraySubtitleGUI()
    window.show()
    sys.exit(app.exec())
