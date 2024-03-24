import datetime
import os
import shutil
import sys
import traceback
from struct import unpack

import ass
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QFileDialog, QLabel, QPushButton, QLineEdit, QMessageBox


class Chapter:
    def __init__(self, file_path):
        self.in_out_time: list[tuple[str, int, int]] = []
        self.mark_info: list[tuple[int, int]] = []

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
                self.mark_info.append((ref_to_play_item_id, mark_timestamp))

    def _unpack_byte(self, n: int):
        formats: dict[int, str] = {1: '>B', 2: '>H', 4: '>I', 8: '>Q'}
        return unpack(formats[n], self.mpls_file.read(n))[0]

    def get_total_time(self):
        return sum(map(lambda x: (x[2] - x[1]) / 45000, self.in_out_time))

    def get_total_time_no_repeat(self):
        return sum({x[0]: (x[2] - x[1]) / 45000 for x in self.in_out_time}.values())


class ASS:
    def __init__(self, file_path):
        self.file_path = file_path
        with open(file_path, 'r', encoding='utf-8-sig') as f:
            self.content = ass.parse(f)

    def append_ass(self, new_file_path, time_shift):
        with open(new_file_path, 'r', encoding='utf-8-sig') as f:
            new_content = ass.parse(f)
        style_info = {repr(style) for style in self.content.styles}
        style_name_map = {}
        for style in new_content.styles:
            if repr(style) not in style_info:
                old_name = style.name
                flag = False
                while any(style.name == _style.name for _style in self.content.styles):
                    style.name += "1"
                    if repr(style) in style_info:
                        flag = True
                        break
                if flag:
                    continue
                style_name_map[old_name] = style.name
                self.content.styles.append(style)
                style_info.add(repr(style))

        time_shift = datetime.timedelta(seconds=time_shift)
        for event in new_content.events:
            event.start += time_shift
            event.end += time_shift
            if event.style in style_name_map:
                event.style = style_name_map[event.style]
            self.content.events.append(event)

    def dump(self, file_path):
        with open(file_path, "w", encoding='utf-8-sig') as f:
            self.content.dump_file(f)


class BluraySubtitle:
    def __init__(self, bluray_path, subtitle_path):
        self.bluray_folders = [root for root, dirs, files in os.walk(bluray_path) if 'BDMV' in dirs]
        self.subtitle_files = [os.path.join(subtitle_path, path) for path in os.listdir(subtitle_path)]
        self.ass_index = -1

    def select_playlist(self):
        for bluray_folder in self.bluray_folders:
            mpls_folder = os.path.join(bluray_folder, 'BDMV', 'PLAYLIST')
            selected_chapter = None
            max_indicator = 0
            for mpls_file_name in os.listdir(mpls_folder):
                mpls_file_path = os.path.join(mpls_folder, mpls_file_name)
                chapter = Chapter(mpls_file_path)
                indicator = chapter.get_total_time_no_repeat() * (1 + len(chapter.mark_info) / 5)
                if indicator > max_indicator:
                    max_indicator = indicator
                    selected_chapter = chapter

            yield bluray_folder, selected_chapter

    @staticmethod
    def completion(folder):
        bdmv = os.path.join(folder, 'BDMV')
        backup = os.path.join(bdmv, 'BACKUP')
        if os.path.exists(backup):
            for item in os.listdir(backup):
                if not os.path.exists(os.path.join(bdmv, item)):
                    shutil.copy(os.path.join(backup, item), os.path.join(bdmv, item))
        for item in 'AUXDATA', 'BDJO', 'JAR', 'META':
            if not os.path.exists(os.path.join(bdmv, item)):
                os.mkdir(os.path.join(bdmv, item))

    def generate_bluray_subtitle(self):
        for folder, chapter in self.select_playlist():
            self.ass_index += 1
            if self.ass_index >= len(self.subtitle_files):
                break
            ass_file = ASS(self.subtitle_files[self.ass_index])
            time_shift = 0
            play_item_duration_time = 0
            item_ids = set()
            for ref_to_play_item_id, mark_timestamp in chapter.mark_info:
                play_item_in_out_time = chapter.in_out_time[ref_to_play_item_id]
                if ref_to_play_item_id not in item_ids:
                    time_shift += play_item_duration_time
                    if (
                            play_item_in_out_time[2] - play_item_in_out_time[1] > 45000 * 300
                            and ref_to_play_item_id != chapter.mark_info[0][0]
                    ):
                        self.ass_index += 1
                        ass_file.append_ass(self.subtitle_files[self.ass_index],
                                            (time_shift + mark_timestamp - play_item_in_out_time[1]) / 45000)
                item_ids.add(ref_to_play_item_id)
                play_item_duration_time = play_item_in_out_time[2] - play_item_in_out_time[1]
            self.completion(folder)
            ass_file.dump(folder + '.ass')


class BluraySubtitleGUI(QWidget):
    def __init__(self):
        super().__init__()
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("BluraySubtitle")
        self.setGeometry(100, 100, 400, 200)

        layout = QVBoxLayout()

        label1 = CustomLabel("选择原盘所在的文件夹：", self)
        self.bdmv_folder_path = QLineEdit()
        self.bdmv_folder_path.setMinimumWidth(200)  # 设置选框宽度
        button1 = QPushButton("选择文件夹")
        button1.clicked.connect(self.select_bdmv_folder)
        layout.addWidget(label1)
        layout.addWidget(self.bdmv_folder_path)
        layout.addWidget(button1)

        label2 = CustomLabel("选择单集字幕所在的文件夹：", self)
        self.subtitle_folder_path = QLineEdit()
        self.subtitle_folder_path.setMinimumWidth(200)  # 设置选框宽度
        button2 = QPushButton("选择文件夹")
        button2.clicked.connect(self.select_subtitle_folder)
        layout.addWidget(label2)
        layout.addWidget(self.subtitle_folder_path)
        layout.addWidget(button2)

        test_button = QPushButton("生成字幕")
        test_button.clicked.connect(self.main)
        layout.addWidget(test_button)

        self.setLayout(layout)

    def select_bdmv_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择文件夹")
        self.bdmv_folder_path.setText(folder)

    def select_subtitle_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择文件夹")
        self.subtitle_folder_path.setText(folder)

    def main(self):
        try:
            BluraySubtitle(self.bdmv_folder_path.text(), self.subtitle_folder_path.text()).generate_bluray_subtitle()
            QMessageBox.information(self, " ", "生成字幕成功！")
        except Exception as e:
            QMessageBox.information(self, " ", traceback.format_exc())


class CustomLabel(QLabel):
    def __init__(self, title, parent):
        super().__init__(title, parent)
        self.setAcceptDrops(True)
        self.title = title

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.accept()
        else:
            e.ignore()

    def dropEvent(self, e):
        if self.title == '选择原盘所在的文件夹：':
            self.parent().bdmv_folder_path.setText(e.mimeData().urls()[0].toLocalFile())
        if self.title == '选择单集字幕所在的文件夹：':
            self.parent().subtitle_folder_path.setText(e.mimeData().urls()[0].toLocalFile())


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = BluraySubtitleGUI()
    window.show()
    sys.exit(app.exec_())
    