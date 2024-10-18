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
from functools import reduce
from struct import unpack

from PyQt6.QtCore import QCoreApplication
from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QFileDialog, QLabel, QPushButton, QLineEdit, \
    QMessageBox, QHBoxLayout, QGroupBox, QCheckBox, QProgressDialog, QRadioButton, QButtonGroup

MKV_INFO_PATH = ''
MKV_MERGE_PATH = ''
MKV_PROP_EDIT_PATH = ''


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

        fp.write('\n[V4+ Styles]\n'if self.script_type == 'v4.00+' else '\n[V4 Styles]\n')
        fp.write('Format: ' + ', '.join(self.style_attrs) + '\n')
        for style in self.styles:
            fp.write('Style: ' + ','.join(style.__dict__.values()) + '\n')

        fp.write('\n[Events]\n')
        fp.write(self.event_attrs[0] + ': ' + ', '.join(self.event_attrs[1:]) + '\n')
        for event in self.events:
            elements = []
            values = list(event.__dict__.values())
            keys = list(event.__dict__.keys())
            for i, value in enumerate(values):
                if i == 0:
                    _start = value + ': '
                else:
                    if keys[i].lower() in ('start', 'end'):
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


class Subtitle:
    def __init__(self, file_path: str):
        self.max_end = 0
        try:
            with open(file_path, 'r', encoding='utf-8-sig') as f:
                if file_path.endswith('.srt'):
                    self.content = ''
                    self.append_ass(file_path, 0)
                else:
                    self.content = Ass(f)
        except:
            with open(file_path, 'r', encoding='utf-16') as f:
                if file_path.endswith('.srt'):
                    self.content = ''
                    self.append_ass(file_path, 0)
                else:
                    self.content = Ass(f)

    def append_ass(self, new_file_path: str, time_shift: float):
        try:
            with open(new_file_path, 'r', encoding='utf-8-sig') as f:
                if new_file_path.endswith('.srt'):
                    new_content = f.read()
                else:
                    new_content = Ass(f)
        except:
            with open(new_file_path, 'r', encoding='utf-16') as f:
                if new_file_path.endswith('.srt'):
                    new_content = f.read()
                else:
                    new_content = Ass(f)
        if new_file_path.endswith('.srt'):
            index = int((re.findall(r'\n\n(\d+)\n', self.content) or ['0'])[-1])
            flag = 0
            new_lines = []
            for line in list(new_content.split('\n')):
                if not line:
                    flag = 0
                if flag == 1 and re.match(r'^(\d+)$', line):
                    new_lines.append(str(int(line) + index))
                elif flag in (1, 2):
                    if (re.match(r'^(\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3})$', line)
                            or re.match(r'^(\d{2}:\d{2}:\d{2}.\d{3} --> \d{2}:\d{2}:\d{2}.\d{3})$', line)):
                        start_time = int(line[0:2]) * 3600 + int(line[3:5]) * 60 + int(line[6:8]) + int(
                            line[9:12]) / 1000 + time_shift
                        end_time = int(line[17:19]) * 3600 + int(line[20:22]) * 60 + int(line[23:25]) + int(
                            line[26:29]) / 1000 + time_shift
                        if end_time > self.max_end:
                            self.max_end = end_time
                        start_time_str = str(datetime.timedelta(seconds=start_time))
                        start_time_str = (start_time_str[:-3] if "." in start_time_str else start_time_str + '.000'
                                          ).replace('.', ',')
                        # 当毫秒数为 0 时，timedelta 的 str 形式不会显示小数点及以后部分
                        end_time_str = str(datetime.timedelta(seconds=end_time))
                        end_time_str = (end_time_str[:-3] if "." in end_time_str else end_time_str + '.000'
                                        ).replace('.', ',')
                        if len(start_time_str) < 12:
                            start_time_str = '0' + start_time_str
                        if len(end_time_str) < 12:
                            end_time_str = '0' + end_time_str
                        new_lines.append(f'{start_time_str} --> {end_time_str}')
                    else:
                        new_lines.append(line)
                else:
                    new_lines.append(line)
                flag += 1
            self.content += '\n'.join(new_lines)
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
        if isinstance(self.content, str):
            with open(file_path + '.srt', "w", encoding='utf-8-sig') as f:
                f.write(self.content)
            with open(selected_mpls + '.srt', "w", encoding='utf-8-sig') as f:
                f.write(self.content)
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
        if self.max_end:
            return self.max_end
        end_set = set(map(lambda event: event.End.total_seconds(), self.content.events))
        max_end = max(end_set)
        end_set.remove(max_end)
        max_end_1 = max(end_set)
        if max_end_1 < max_end - 60:
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

    def add_chapter(self, edit_file):
        if edit_file:
            subprocess.Popen(rf'"{MKV_PROP_EDIT_PATH}" "{self.path}" --chapters chapter.txt').wait()
        else:
            new_path = os.path.join(os.path.dirname(self.path), 'output', os.path.basename(self.path))
            subprocess.Popen(rf'"{MKV_MERGE_PATH}" --chapters chapter.txt -o "{new_path}" "{self.path}"').wait()


class BluraySubtitle:
    def __init__(self, bluray_path, input_path: str, checked: bool, progress_dialog: QProgressDialog):
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

        self.bluray_folders = [root for root, dirs, files in os.walk(bluray_path) if 'BDMV' in dirs
                               and 'PLAYLIST' in os.listdir(os.path.join(root, 'BDMV'))]
        self.subtitle_files = [os.path.join(input_path, path) for path in os.listdir(input_path)
                               if path.endswith(".ass") or path.endswith(".ssa") or path.endswith('srt')]
        self.mkv_files = [os.path.join(input_path, path) for path in os.listdir(input_path)
                          if path.endswith("mkv")]
        self.sub_index = 0
        self.mkv_index = 0
        self.checked = checked
        self.progress_dialog = progress_dialog

    @staticmethod
    def get_available_drives():
        drives = []
        bitmask = ctypes.windll.kernel32.GetLogicalDrives()
        for letter in range(65, 91):
            if bitmask & 1:
                drives.append(chr(letter))
            bitmask >>= 1
        return set(drives)

    def select_playlist(self):  # 选择主播放列表
        for bluray_folder in self.bluray_folders:
            mpls_folder = os.path.join(bluray_folder, 'BDMV', 'PLAYLIST')
            selected_chapter = None
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
                    selected_chapter = chapter
                    selected_mpls = mpls_file_path[:-5]

            yield bluray_folder, selected_chapter, selected_mpls

    def generate_bluray_subtitle(self):
        for folder, chapter, selected_mpls in self.select_playlist():
            print(f'folder: {folder}')
            print(f'in_out_time: {chapter.in_out_time}')
            print(f'mark_info: {chapter.mark_info}')
            start_time = 0
            sub_file = Subtitle(self.subtitle_files[self.sub_index])
            left_time = chapter.get_total_time()
            print(f'集数：{self.sub_index + 1}, 偏移：0')

            for i, play_item_in_out_time in enumerate(chapter.in_out_time):
                play_item_marks = chapter.mark_info.get(i)
                if play_item_marks:
                    play_item_duration_time = play_item_in_out_time[2] - play_item_in_out_time[1]

                    time_shift = (start_time + play_item_marks[0] - play_item_in_out_time[1]) / 45000
                    if time_shift > sub_file.max_end_time() - 300:
                        if (self.sub_index + 1 < len(self.subtitle_files)
                                and left_time > Subtitle(self.subtitle_files[self.sub_index + 1]).max_end_time() - 180):
                            self.sub_index += 1
                            print(f'集数：{self.sub_index + 1}, 偏移：{time_shift}')
                            sub_file.append_ass(self.subtitle_files[self.sub_index], time_shift)
                            self.progress_dialog.setValue(int((self.sub_index + 1) / len(self.subtitle_files) * 1000))
                            QCoreApplication.processEvents()

                    if play_item_duration_time / 45000 > 2600 and sub_file.max_end_time() - time_shift < 1800:
                        # 连体盘，一个 m2ts 文件包含两集或以上
                        for mark in play_item_marks:
                            time_shift = (start_time + mark - play_item_in_out_time[1]) / 45000
                            if time_shift > sub_file.max_end_time() and (play_item_in_out_time[2] - mark) / 45000 > 1200:
                                self.sub_index += 1
                                print(f'集数：{self.sub_index + 1}, 偏移：{time_shift}')
                                sub_file.append_ass(self.subtitle_files[self.sub_index], time_shift)
                                self.progress_dialog.setValue(
                                    int((self.sub_index + 1) / len(self.subtitle_files) * 1000))
                                QCoreApplication.processEvents()

                start_time += play_item_in_out_time[2] - play_item_in_out_time[1]
                left_time += (play_item_in_out_time[1] - play_item_in_out_time[2]) / 45000

            sub_file.dump(folder, selected_mpls)
            self.completion(folder)
            self.sub_index += 1
            if self.sub_index == len(self.subtitle_files):
                break
        self.progress_dialog.setValue(1000)
        QCoreApplication.processEvents()

    def add_chapter_to_mkv(self):
        for folder, chapter, selected_mpls in self.select_playlist():
            duration = MKV(self.mkv_files[self.mkv_index]).get_duration()
            print(f'folder: {folder}')
            print(f'in_out_time: {chapter.in_out_time}')
            print(f'mark_info: {chapter.mark_info}')
            print(f'集数：{self.mkv_index + 1}, 时长: {duration}')

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
                        mkv = MKV(self.mkv_files[self.mkv_index])
                        mkv.add_chapter(self.checked)
                        self.progress_dialog.setValue(int((self.mkv_index + 1) / len(self.mkv_files) * 1000))
                        QCoreApplication.processEvents()
                        self.mkv_index += 1
                        duration = MKV(self.mkv_files[self.mkv_index]).get_duration()
                        print(f'集数：{self.mkv_index + 1}, 时长: {duration}')
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
            mkv = MKV(self.mkv_files[self.mkv_index])
            mkv.add_chapter(self.checked)
            self.progress_dialog.setValue(int((self.mkv_index + 1) / len(self.mkv_files) * 1000))
            QCoreApplication.processEvents()
            self.mkv_index += 1

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


class BluraySubtitleGUI(QWidget):
    def __init__(self):
        super().__init__()
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("BluraySubtitle")
        self.setGeometry(100, 100, 400, 200)

        layout = QVBoxLayout()

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
        self.radio2.move(100, 0)
        group = QButtonGroup(self)
        group.addButton(self.radio1)
        group.addButton(self.radio2)
        group.buttonClicked.connect(self.on_select_function)
        h_layout.addWidget(self.radio1)
        h_layout.addWidget(self.radio2)
        layout.addWidget(function_button)

        bluray_path_box = CustomBox('原盘', self)
        h_layout = QHBoxLayout()
        bluray_path_box.setLayout(h_layout)
        self.label1 = QLabel("选择原盘所在的文件夹：", self)
        self.bdmv_folder_path = QLineEdit()
        self.bdmv_folder_path.setMinimumWidth(200)
        button1 = QPushButton("选择文件夹")
        button1.clicked.connect(self.select_bdmv_folder)
        layout.addWidget(self.label1)
        h_layout.addWidget(self.bdmv_folder_path)
        h_layout.addWidget(button1)
        layout.addWidget(bluray_path_box)

        subtitle_path_box = CustomBox('字幕', self)
        h_layout = QHBoxLayout()
        subtitle_path_box.setLayout(h_layout)
        self.label2 = QLabel("选择单集字幕所在的文件夹：", self)
        self.subtitle_folder_path = QLineEdit()
        self.subtitle_folder_path.setMinimumWidth(200)
        button2 = QPushButton("选择文件夹")
        button2.clicked.connect(self.select_subtitle_folder)
        layout.addWidget(self.label2)
        h_layout.addWidget(self.subtitle_folder_path)
        h_layout.addWidget(button2)
        layout.addWidget(subtitle_path_box)

        self.checkbox1 = QCheckBox("补全蓝光目录")
        self.checkbox1.setChecked(True)
        layout.addWidget(self.checkbox1)
        self.exe_button = QPushButton("生成字幕")
        self.exe_button.clicked.connect(self.main)
        self.exe_button.setMinimumHeight(50)
        layout.addWidget(self.exe_button)

        self.setLayout(layout)

    def on_select_function(self):
        if self.radio1.isChecked():
            self.label2.setText("选择单集字幕所在的文件夹")
            self.exe_button.setText("生成字幕")
            self.checkbox1.setText('生成字幕')
        if self.radio2.isChecked():
            self.label2.setText("选择mkv文件所在的文件夹")
            self.exe_button.setText("添加章节")
            self.checkbox1.setText('直接编辑原文件')

    def select_bdmv_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择文件夹")
        self.bdmv_folder_path.setText(folder)

    def select_subtitle_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择文件夹")
        self.subtitle_folder_path.setText(folder)

    def main(self):
        if self.radio1.isChecked():
            self.generate_subtitle()
        if self.radio2.isChecked():
            self.add_chapters()

    def generate_subtitle(self):
        progress_dialog = QProgressDialog('字幕生成中', '取消', 0, 1000, self)
        progress_dialog.show()
        try:
            BluraySubtitle(
                self.bdmv_folder_path.text(),
                self.subtitle_folder_path.text(),
                self.checkbox1.isChecked(),
                progress_dialog
            ).generate_bluray_subtitle()
            QMessageBox.information(self, " ", "生成字幕成功！")
        except Exception as e:
            QMessageBox.information(self, " ", traceback.format_exc())
        progress_dialog.close()

    def add_chapters(self):
        if self.checkbox1.isChecked():
            progress_dialog = QProgressDialog('编辑中', '取消', 0, 1000, self)
        else:
            progress_dialog = QProgressDialog('混流中', '取消', 0, 1000, self)
        progress_dialog.show()
        try:
            BluraySubtitle(
                self.bdmv_folder_path.text(),
                self.subtitle_folder_path.text(),
                self.checkbox1.isChecked(),
                progress_dialog
            ).add_chapter_to_mkv()
            if self.checkbox1.isChecked():
                QMessageBox.information(self, " ", "添加章节成功，mkv章节已添加")
            else:
                QMessageBox.information(self, " ", "添加章节成功，生成的新mkv文件在output文件夹下")
        except Exception as e:
            QMessageBox.information(self, " ", traceback.format_exc())
        progress_dialog.close()


class CustomBox(QGroupBox):  # 为 Box 框提供拖拽文件夹的功能
    def __init__(self, title, parent):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.title = title

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.accept()
        else:
            e.ignore()

    def dropEvent(self, e):
        if self.title == '原盘':
            self.parent().bdmv_folder_path.setText(e.mimeData().urls()[0].toLocalFile())
        if self.title == '字幕':
            self.parent().subtitle_folder_path.setText(e.mimeData().urls()[0].toLocalFile())


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = BluraySubtitleGUI()
    window.show()
    sys.exit(app.exec())
