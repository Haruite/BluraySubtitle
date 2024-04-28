import _io
import ctypes
import datetime
import os
import re
import shutil
import sys
import traceback
from dataclasses import dataclass
from functools import reduce
from struct import unpack

from PyQt5.QtCore import QCoreApplication
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QFileDialog, QLabel, QPushButton, QLineEdit, \
    QMessageBox, QHBoxLayout, QGroupBox, QCheckBox, QProgressDialog


class Chapter:
    def __init__(self, file_path: str):
        self.in_out_time: list[tuple[str, int, int]] = []
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

    def get_total_time(self):
        return sum(map(lambda x: (x[2] - x[1]) / 45000, self.in_out_time))

    def get_total_time_no_repeat(self):
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
    sections = 'script', 'garbage', 'style', 'events'

    def __init__(self, content: str):
        self.content = content
        for section in self.sections:
            setattr(self, section + "_raw", [])
        self.styles: list[Style] = []
        self.events: list[Event] = []
        self.script_type = ''

    def parse(self):
        lines = self.content.splitlines()

        for line in lines:
            if line.startswith('[') and line.endswith(']'):
                for section in self.sections:
                    if section in line.lower():
                        raw = getattr(self, section + "_raw")
                        if section == 'style':
                            self.script_type = 'v4.00+' if '+' in line else 'v4.00'
            elif line:
                raw.append(line)

        for index, line in enumerate(self.style_raw):
            values = list(map(lambda attr: attr.strip(), line[line.index(":") + 1:].split(',')))
            if index == 0:
                attrs = values
            else:
                style = Style()
                for i, value in enumerate(values):
                    setattr(style, attrs[i], value)
                self.styles.append(style)

        for index, line in enumerate(self.events_raw):
            values = list(map(lambda attr: attr.strip(), line[line.index(":") + 1:].split(',')))
            if index == 0:
                attrs = ['Format'] + values
            else:
                event = Event()
                event.Format = line[:line.index(":")]
                if len(values) > len(attrs) - 1:
                    values = values[:len(attrs) - 2] + [','.join(values[len(attrs) - 2:])]
                for i, value in enumerate(values):
                    if attrs[i + 1].lower() in ('start', 'end'):
                        value = datetime.timedelta(seconds=reduce(lambda a, b: a * 60 + b, map(float, value.split(':'))))
                    setattr(event, attrs[i + 1], value)
                self.events.append(event)

        return self

    def dump_file(self, fp: _io.TextIOWrapper):
        fp.write('[Script Info]\n')
        fp.write('\n'.join(self.script_raw))
        if self.garbage_raw:
            fp.write('\n\n[Aegisub Project Garbage]\n')
            fp.write('\n'.join(self.garbage_raw))

        fp.write('\n\n[V4+ Styles]\n'if self.script_type == 'v4.00+' else '\n\n[V4 Styles]\n')
        fp.write('Format: ' + ', '.join(self.styles[0].__dict__.keys()) + '\n')
        for style in self.styles:
            fp.write('Style: ' + ','.join(style.__dict__.values()) + '\n')

        fp.write('\n[Events]\n')
        fp.write('Format: ' + ', '.join(list(self.events[0].__dict__.keys())[1:]) + '\n')
        for event in self.events:
            line = ''
            values = list(event.__dict__.values())
            keys = list(event.__dict__.keys())
            for i, value in enumerate(values):
                if i == 0:
                    line += value + ": "
                else:
                    if keys[i].lower() in ('start', 'end'):
                        d_len = len(str(value).split(':')[-1])
                        if d_len > 5:
                            line += str(value)[:5 - d_len] + ','
                        elif d_len == 5:
                            line += str(value) + ','
                        else:
                            line += str(value) + '.00' + ','
                    elif i == len(values) - 1:
                        line += value
                    else:
                        line += value + ','

            line += '\n'
            fp.write(line)


class Subtitle:
    def __init__(self, file_path: str):
        self.max_end = 0
        try:
            with open(file_path, 'r', encoding='utf-8-sig') as f:
                if file_path.endswith('.srt'):
                    self.content = ''
                    self.append_ass(file_path, 0)
                else:
                    self.content = Ass(f.read()).parse()
        except:
            with open(file_path, 'r', encoding='utf-16') as f:
                if file_path.endswith('.srt'):
                    self.content = ''
                    self.append_ass(file_path, 0)
                else:
                    self.content = Ass(f.read()).parse()

    def append_ass(self, new_file_path: str, time_shift: float):
        try:
            with open(new_file_path, 'r', encoding='utf-8-sig') as f:
                if new_file_path.endswith('.srt'):
                    new_content = f.read()
                else:
                    new_content = Ass(f.read()).parse()
        except:
            with open(new_file_path, 'r', encoding='utf-16') as f:
                if new_file_path.endswith('.srt'):
                    new_content = f.read()
                else:
                    new_content = Ass(f.read()).parse()
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
                        start_time_str = str(datetime.timedelta(seconds=start_time))[:-3].replace('.', ',')
                        end_time_str = str(datetime.timedelta(seconds=end_time))[:-3].replace('.', ',')
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
        else:
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

    def dump(self, file_path: str):
        if isinstance(self.content, str):
            with open(file_path + '.srt', "w", encoding='utf-8-sig') as f:
                f.write(self.content)
        elif self.content.script_type == 'v4.00+':
            with open(file_path + '.ass', "w", encoding='utf-8-sig') as f:
                self.content.dump_file(f)
        else:
            with open(file_path + '.ssa', "w", encoding='utf-8-sig') as f:
                self.content.dump_file(f)

    def max_end_time(self):
        if self.max_end:
            return self.max_end
        end_set = set(map(lambda event: event.End.total_seconds(), self.content.events))
        max_end = max(end_set)
        end_set.remove(max_end)
        max_end_1 = max(end_set)
        if max_end_1 < max_end - 60:
            return max_end_1
        else:
            return max_end


class ISO:
    def __init__(self, path: str):
        self.path = ctypes.c_wchar_p(path)

        class GUID(ctypes.Structure):
            _fields_ = (
                ("Data1", ctypes.c_ulong),
                ("Data2", ctypes.c_ushort),
                ("Data3", ctypes.c_ushort),
                ("Data4", ctypes.c_ubyte * 8),
            )

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
        ctypes.windll.virtdisk.AttachVirtualDisk(
            self.handle,
            None,
            0x00000001,
            0,
            None,
            None
        )

    def close(self):
        ctypes.windll.kernel32.CloseHandle(self.handle)


class BluraySubtitle:
    def __init__(self, bluray_path, subtitle_path: str, checked: bool, progress_dialog: QProgressDialog):
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

        self.bluray_folders = [root for root, dirs, files in os.walk(bluray_path) if 'BDMV' in dirs
                               and 'PLAYLIST' in os.listdir(os.path.join(root, 'BDMV'))]
        self.subtitle_files = [os.path.join(subtitle_path, path) for path in os.listdir(subtitle_path)
                               if path.endswith(".ass") or path.endswith(".ssa") or path.endswith('srt')]
        self.sub_index = 0
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

    def select_playlist(self):
        for bluray_folder in self.bluray_folders:
            mpls_folder = os.path.join(bluray_folder, 'BDMV', 'PLAYLIST')
            selected_chapter = None
            max_indicator = 0
            for mpls_file_name in os.listdir(mpls_folder):
                mpls_file_path = os.path.join(mpls_folder, mpls_file_name)
                chapter = Chapter(mpls_file_path)
                indicator = chapter.get_total_time_no_repeat() * (1 + sum(map(len, chapter.mark_info.values())) / 5)
                if indicator > max_indicator:
                    max_indicator = indicator
                    selected_chapter = chapter

            yield bluray_folder, selected_chapter

    def generate_bluray_subtitle(self):
        for folder, chapter in self.select_playlist():
            print(folder)
            start_time = 0
            ass_file = Subtitle(self.subtitle_files[self.sub_index])
            left_time = chapter.get_total_time()
            print(f'集数：{self.sub_index + 1}, 偏移：0')

            for i, play_item_in_out_time in enumerate(chapter.in_out_time):
                play_item_marks = chapter.mark_info.get(i)
                if play_item_marks:
                    play_item_duration_time = play_item_in_out_time[2] - play_item_in_out_time[1]

                    time_shift = (start_time + play_item_marks[0] - play_item_in_out_time[1]) / 45000
                    if time_shift > ass_file.max_end_time() - 300:
                        if (self.sub_index + 1 < len(self.subtitle_files)
                                and left_time > Subtitle(self.subtitle_files[self.sub_index + 1]).max_end_time() - 180):
                            self.sub_index += 1
                            print(f'集数：{self.sub_index + 1}, 偏移：{time_shift}')
                            ass_file.append_ass(self.subtitle_files[self.sub_index], time_shift)
                            self.progress_dialog.setValue(int((self.sub_index + 1) / len(self.subtitle_files) * 1000))
                            QCoreApplication.processEvents()

                    if play_item_duration_time / 45000 > 2600 and ass_file.max_end_time() - time_shift < 1800:
                        min_shift = play_item_duration_time / 45000 / 2
                        selected_mark = play_item_in_out_time[1]
                        for mark in play_item_marks:
                            if (mark - play_item_in_out_time[1]) / 45000 > (ass_file.max_end_time() - time_shift):
                                shift = abs(play_item_duration_time / 2 - mark + play_item_in_out_time[1]) / 45000
                                if shift < min_shift:
                                    min_shift = shift
                                    selected_mark = mark
                        time_shift = (start_time + selected_mark - play_item_in_out_time[1]) / 45000
                        self.sub_index += 1
                        print(f'集数：{self.sub_index + 1}, 偏移：{time_shift}')
                        ass_file.append_ass(self.subtitle_files[self.sub_index], time_shift)
                        self.progress_dialog.setValue(int((self.sub_index + 1) / len(self.subtitle_files) * 1000))
                        QCoreApplication.processEvents()

                start_time += play_item_in_out_time[2] - play_item_in_out_time[1]
                left_time += (play_item_in_out_time[1] - play_item_in_out_time[2]) / 45000

            ass_file.dump(folder)
            self.completion(folder)
            self.sub_index += 1
            if self.sub_index == len(self.subtitle_files):
                break
        self.progress_dialog.setValue(1000)
        QCoreApplication.processEvents()

    def completion(self, folder: str):
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


class BluraySubtitleGUI(QWidget):
    def __init__(self):
        super().__init__()
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("BluraySubtitle")
        self.setGeometry(100, 100, 400, 200)

        layout = QVBoxLayout()

        bluray_path_box = CustomBox('原盘', self)
        h_layout = QHBoxLayout()
        bluray_path_box.setLayout(h_layout)
        label1 = QLabel("选择原盘所在的文件夹：", self)
        self.bdmv_folder_path = QLineEdit()
        self.bdmv_folder_path.setMinimumWidth(200)
        button1 = QPushButton("选择文件夹")
        button1.clicked.connect(self.select_bdmv_folder)
        layout.addWidget(label1)
        h_layout.addWidget(self.bdmv_folder_path)
        h_layout.addWidget(button1)
        layout.addWidget(bluray_path_box)

        subtitle_path_box = CustomBox('字幕', self)
        h_layout = QHBoxLayout()
        subtitle_path_box.setLayout(h_layout)
        label2 = QLabel("选择单集字幕所在的文件夹：", self)
        self.subtitle_folder_path = QLineEdit()
        self.subtitle_folder_path.setMinimumWidth(200)
        button2 = QPushButton("选择文件夹")
        button2.clicked.connect(self.select_subtitle_folder)
        layout.addWidget(label2)
        h_layout.addWidget(self.subtitle_folder_path)
        h_layout.addWidget(button2)
        layout.addWidget(subtitle_path_box)

        self.checkbox1 = QCheckBox("补全蓝光目录")
        self.checkbox1.setChecked(True)
        layout.addWidget(self.checkbox1)
        exe_button = QPushButton("生成字幕")
        exe_button.clicked.connect(self.main)
        exe_button.setMinimumHeight(50)
        layout.addWidget(exe_button)

        self.setLayout(layout)

    def select_bdmv_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择文件夹")
        self.bdmv_folder_path.setText(folder)

    def select_subtitle_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择文件夹")
        self.subtitle_folder_path.setText(folder)

    def main(self):
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


class CustomBox(QGroupBox):
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
    sys.exit(app.exec_())
