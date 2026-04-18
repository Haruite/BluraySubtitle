# 功能1：生成合并字幕
# 功能2：给mkv添加章节
# 功能3：原盘remux
# 功能4：原盘压制
# 功能234需要安装mkvtoolnix，指定FLAC_PATH和FLAC_THREADS(flac版本需大于等于1.5.0)
# 功能34需要指定FFMPEG_PATH和FFPROBE_PATH
# 功能4需要安装vapoursynth，并将vspipe(.exe)和x265(.exe)添加到系统path
# pip install pycountry PyQt6 librosa
import _io
import builtins
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
from urllib.parse import urlparse, unquote

try:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import librosa
import librosa.feature
import numpy as np
import pycountry
try:
    import soundfile
except Exception:
    soundfile = None
from PyQt6.QtCore import QCoreApplication, Qt, QPoint, QObject, QThread, QTimer, QEventLoop, QProcess, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QDragMoveEvent, QDropEvent, QPaintEvent, QDragEnterEvent, QFontMetrics
from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QFileDialog, QLabel, QToolButton, QLineEdit, \
    QMessageBox, QHBoxLayout, QGroupBox, QCheckBox, QProgressDialog, QProgressBar, QRadioButton, QButtonGroup, \
    QTableWidget, QTableWidgetItem, QDialog, QPushButton, QComboBox, QMenu, QAbstractItemView, QPlainTextEdit, QSizePolicy, QHeaderView, QInputDialog, QTabBar

if sys.platform == 'win32':
    import winreg


FLAC_PATH = r'C:\Downloads\flac-1.5.0-win\Win64\flac.exe'  # flac可执行文件路径
FLAC_THREADS = 20  # flac线程数
FFMPEG_PATH = r'C:\Downloads\ffmpeg-8.1-essentials_build\bin\ffmpeg.exe'  # ffmpeg可执行文件路径
FFPROBE_PATH = r'C:\Downloads\ffmpeg-8.1-essentials_build\bin\ffprobe.exe'  # ffprobe可执行文件路径
X265_PATH = r'C:\Software\x265.exe'  # x265可执行文件路径
VSEDIT_PATH = r'C:\Software\vapoursynth\vsedit.exe'  # vapoursynth editor 路径


def is_docker():
    path = '/proc/self/cgroup'
    return (
            os.path.exists('/.dockerenv') or
            os.path.isfile(path) and any('docker' in line for line in open(path))
    )


if sys.platform != 'win32':  # 不是 windows 平台
    FLAC_PATH = '/usr/bin/flac'  # flac可执行文件路径
    FFMPEG_PATH = '/usr/bin/ffmpeg'  # ffmpeg可执行文件路径
    FFPROBE_PATH = '/usr/bin/ffprobe'  # ffprobe可执行文件路径
    X265_PATH = '/usr/bin/x265'  # x265可执行文件路径
    PLUGIN_PATH = os.path.expanduser('~/plugins')  # 插件所在目录
    VSEDIT_PATH = r'/usr/bin/vsedit'  # vapoursynth editor 路径
    if is_docker():
        PLUGIN_PATH = '/app/plugins'


MKV_INFO_PATH = ''
MKV_MERGE_PATH = ''
MKV_PROP_EDIT_PATH = ''
MKV_EXTRACT_PATH = ''
BDMV_LABELS = ['path', 'size', 'info']
SUBTITLE_LABELS = ['select', 'path', 'sub_duration', 'ep_duration', 'bdmv_index', 'chapter_index', 'offset', 'warning']
MKV_LABELS = ['path', 'duration']
REMUX_LABELS = ['sub_path', 'language', 'ep_duration', 'bdmv_index', 'chapter_index', 'm2ts_file', 'output_name']
ENCODE_LABELS = ['sub_path', 'language', 'ep_duration', 'bdmv_index', 'chapter_index', 'm2ts_file', 'output_name', 'vpy_path', 'edit_vpy', 'preview_script']
ENCODE_SP_LABELS = ['bdmv_index', 'mpls_file', 'm2ts_file', 'duration', 'output_name', 'vpy_path', 'edit_vpy', 'preview_script']
CONFIGURATION = {}
CURRENT_UI_LANGUAGE = 'en'
APP_TITLE = 'BluraySubtitle v2.1+'


def get_mkvtoolnix_ui_language() -> str:
    if CURRENT_UI_LANGUAGE == 'zh':
        return 'zh_CN'
    return 'en' if sys.platform == 'win32' else 'en_US'


def mkvtoolnix_ui_language_arg() -> str:
    return f'--ui-language {get_mkvtoolnix_ui_language()}'

I18N_ZH_TO_EN = {
    'BluraySubtitle': 'BluraySubtitle',
    '语言': 'Language',
    '选择功能': 'Function',
    '剧集模式': 'Series mode',
    '电影模式': 'Movie mode',
    '每集时长大约（分钟）：': 'Approx. episode length (minutes):',
    '可能需要剧集模式': 'May require series mode',
    '添加后缀': 'Add suffix',
    '生成合并字幕': 'Merge Subtitles',
    '给mkv添加章节': 'Add Chapters To MKV',
    '原盘remux': 'Blu-ray Remux',
    '原盘压制': 'Blu-ray Encode',
    '原盘': 'Blu-ray',
    '字幕': 'Subtitles',
    '选择原盘所在的文件夹': 'Select the Blu-ray folder',
    '选择单集字幕所在的文件夹': 'Select the subtitle folder',
    '选择单集字幕所在的文件夹：': 'Select the subtitle folder:',
    '选择mkv文件所在的文件夹': 'Select the MKV folder',
    '选择字幕文件所在的文件夹（可选）': 'Select the subtitle folder (optional)',
    '补全蓝光目录': 'Complete Blu-ray Folder',
    '直接编辑原文件': 'Edit Original File Directly',
    '输出文件夹': 'Output Folder',
    '选择': 'Select',
    '打开': 'Open',
    '生成字幕': 'Generate Subtitles',
    '添加章节': 'Add Chapters',
    '开始remux': 'Start Remux',
    '开始压制': 'Start Encode',
    '压制': 'Encode',
    '字幕封装方式：': 'Subtitle Packaging:',
    '外挂': 'External',
    '内挂': 'Softsub',
    '内嵌': 'Hardsub',
    '程序自带': 'Built-in',
    '系统': 'System',
    '快速': 'Fast',
    '均衡': 'Balanced',
    '高质': 'High Quality',
    '极限': 'Extreme',
    '自订': 'Custom',
    'x265参数：': 'x265 Params:',
    '准备中': 'Preparing',
    '正在取消...': 'Canceling...',
    '完成': 'Done',
    '读取字幕中': 'Reading Subtitles',
    '读取MKV中': 'Reading MKV',
    '生成配置': 'Generating Configuration',
    '字幕生成中': 'Generating Subtitles',
    '写入章节中': 'Writing Chapters',
    '写入字幕文件': 'Writing Subtitle File',
    '合并中 ': 'Merging ',
    '混流中': 'Muxing',
    '编辑中': 'Editing',
    '处理完成: ': 'Completed: ',
    '原盘remux成功！': 'Blu-ray remux completed!',
    '原盘压制成功！': 'Blu-ray encode completed!',
    '生成字幕成功！': 'Subtitle generation completed!',
    '添加章节成功，mkv章节已添加': 'Chapters added to MKV successfully',
    '添加章节成功，生成的新mkv文件在output文件夹下': 'Chapters added successfully, new MKV is in output folder',
    '未填写文件夹路径': 'Folder path is empty',
    '文件夹不存在：': 'Folder does not exist:',
    '文件不存在：': 'File does not exist:',
    '无法打开文件夹：': 'Cannot open folder:',
    '打开文件夹失败': 'Open Folder Failed',
    '未选择输出文件夹': 'Output folder is not selected',
    '输出文件夹不存在': 'Output folder does not exist',
    '未选择原盘主mpls': 'Main MPLS is not selected',
    '未选择字幕文件': 'Subtitle file is not selected',
    '提示': 'Prompt',
    '取消': 'Cancel',
    '（点击取消）': '(click to cancel)',
    '选择m2ts文件': 'Select M2TS File',
    '检测到多个 m2ts 文件，请选择要预览的文件：': 'Multiple M2TS files detected, choose one for preview:',
    '检测到多个字幕文件，请选择要预览的文件：': 'Multiple subtitle files detected, choose one for preview:',
    '选择vpy文件': 'Select VPy File',
    '选择文件夹': 'Select Folder',
    '选择输出文件夹': 'Select Output Folder',
    'vpy路径为空': 'VPy path is empty',
    '启动 vsedit 失败': 'Failed to launch vsedit',
    '打开 vsedit 失败：': 'Failed to open vsedit:',
    '预览脚本失败：': 'Preview script failed:',
    '未找到 vsedit，请检查 VSEDIT_PATH 或系统 PATH': 'vsedit not found, check VSEDIT_PATH or system PATH',
    '执行命令: ': 'Run command: ',
    '压制命令：': 'Encode command:',
    '混流命令：': 'Mux command:',
    '混流命令: ': 'Mux command: ',
    '正在分析mpls的第一个文件 ｢': 'Analyzing first stream file in mpls ｢',
    '｣ 的轨道': '｣ tracks',
    '选择音频轨道 ': 'Selected audio tracks ',
    '，字幕轨道 ': ', subtitle tracks ',
    '找到封面图片 ｢': 'Found cover image ｢',
    '输出文件名': 'Output filename ',
    '\x1b[31m错误,｢': '\x1b[31mError,｢',
    '\x1b[31m错误，ffmpeg压缩也失败\x1b[0m': '\x1b[31mError: ffmpeg compression also failed\x1b[0m',
    '\x1b[31m错误，电影混流失败，请检查任务输出\x1b[0m': '\x1b[31mError: muxing failed, please check task output\x1b[0m',
    ' dB，已删除': ' dB, deleted',
    ', 时长: ': ', duration: ',
    'FFmpeg 执行出错: ': 'FFmpeg error: ',
    'ffmpeg 压缩的flac文件比原音轨大，将删除 ｢': 'ffmpeg-compressed FLAC is larger than the original track, deleting ｢',
    'flac 压缩 wav 文件 ｢': 'flac compressing wav file ｢',
    'flac 文件比原音轨大，将删除 ｢': 'FLAC is larger than the original track, deleting ｢',
    '多进程加载失败，切换到单进程: ': 'Multiprocess load failed, switching to single process: ',
    '字幕拖入处理失败，请检查字幕文件和原盘路径': 'Subtitle drag-in failed, please check the subtitle files and Blu-ray path',
    '字幕文件 ｢': 'Subtitle file ｢',
    '字幕文件加载失败 ｢': 'Failed to load subtitle file ｢',
    '字幕文件加载失败: ': 'Failed to load subtitle file: ',
    '字幕文件加载成功 ｢': 'Subtitle file loaded ｢',
    '将音轨 ｢': 'Track ｢',
    '找到一个重复音轨 ｢': 'Found a duplicate audio track ｢',
    '拖入字幕处理失败: ': 'Subtitle drag-in failed: ',
    '检测到文件 ｢': 'Detected file ｢',
    '检测到空音轨 ｢': 'Detected empty audio track ｢',
    '正在压缩音轨 ｢': 'Compressing audio track ｢',
    '正在提取无损音轨，命令: ': 'Extracting lossless tracks, command: ',
    '生成配置失败: ': 'Failed to generate configuration: ',
    '获取字幕时长失败: ': 'Failed to get subtitle duration: ',
    '转换完成: ｢': 'Conversion completed: ｢',
    '集数：': 'Episode: ',
    '｣ 中的m2ts文件 ｢': '｣ m2ts file in ｢',
    '｣ 压缩成flac，减小体积 ': '｣ compressed to FLAC to reduce size ',
    '｣ 失败，将使用 ffmpeg 压缩': '｣ failed, will use ffmpeg to compress',
    '｣ 实际有效位深为 ': '｣ actual effective bit depth is ',
    '｣ 平均 ': '｣ average ',
    '｣ 有延迟 ': '｣ has delay ',
    '｣ 有效位深较低，正在优化为 16-bit...': '｣ effective bit depth is low, optimizing to 16-bit...',
    '｣ 未找到\x1b[0m': '｣ not found\x1b[0m',
    '｣ 用ffmpeg压缩成flac，减小体积 ': '｣ compressed to FLAC with ffmpeg to reduce size ',
    '｣ 解析失败: ': '｣ parse failed: ',
    '｣，已删除': '｣, deleted',
    '多进程模式解析字幕': 'Parsing subtitles in multiprocessing mode',
    '单进程模式解析字幕': 'Parsing subtitles in single-process mode',
    '解析字幕': 'Parsing Subtitles',
    '（已加载 ': ' (loaded ',
    '）': ')',
    '尝试多进程解析，失败时回退到单进程': 'Trying multiprocessing, fallback to single-process on failure',
    '字幕文件全部加载失败': 'Failed to load all subtitle files',
    '成功加载 ': 'Loaded successfully ',
    ' 个字幕文件': ' subtitle files',
    '多进程解析失败，切换到单进程模式: ': 'Multiprocessing parse failed, switching to single-process: ',
    '配置为空，跳过更新': 'Configuration is empty, skipping update',
    '章节': 'Chapters',
    '编辑字幕': 'Edit Subtitle',
    '查看章节': 'view chapters',
    '播放': 'play',
    '预览': 'preview',
    '编辑vpy': 'edit_vpy',
    '编辑': 'edit',
}
I18N_EN_TO_ZH = {v: k for k, v in I18N_ZH_TO_EN.items()}


def translate_text(text: str, language: Optional[str] = None) -> str:
    if not isinstance(text, str):
        return text
    lang = language or CURRENT_UI_LANGUAGE
    mapping = I18N_ZH_TO_EN if lang == 'en' else I18N_EN_TO_ZH
    if text in mapping:
        return mapping[text]
    result = text
    for src in sorted(mapping.keys(), key=len, reverse=True):
        if src and src in result:
            result = result.replace(src, mapping[src])
    return result


_ORIGINAL_PRINT = builtins.print


def print(*args, **kwargs):
    translated_args = [translate_text(a) if isinstance(a, str) else a for a in args]
    _ORIGINAL_PRINT(*translated_args, **kwargs)


_ORIG_QMSG_INFORMATION = QMessageBox.information
_ORIG_QMSG_WARNING = QMessageBox.warning


def _localized_qmsg_information(parent, title, text, *args, **kwargs):
    return _ORIG_QMSG_INFORMATION(parent, translate_text(str(title)), translate_text(str(text)), *args, **kwargs)


def _localized_qmsg_warning(parent, title, text, *args, **kwargs):
    return _ORIG_QMSG_WARNING(parent, translate_text(str(title)), translate_text(str(text)), *args, **kwargs)


QMessageBox.information = staticmethod(_localized_qmsg_information)
QMessageBox.warning = staticmethod(_localized_qmsg_warning)


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
            subprocess.Popen(rf'"{MKV_PROP_EDIT_PATH}" {mkvtoolnix_ui_language_arg()} "{self.path}" --chapters chapter.txt', shell=True).wait()
        else:
            new_path = os.path.join(os.path.dirname(self.path), 'output', os.path.basename(self.path))
            subprocess.Popen(rf'"{MKV_MERGE_PATH}" {mkvtoolnix_ui_language_arg()} --chapters chapter.txt -o "{new_path}" "{self.path}"', shell=True).wait()


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
                 progress_dialog: Optional[object] = None,
                 approx_episode_duration_seconds: float = 24 * 60,
                 movie_mode: bool = False):
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
        self.movie_mode = bool(movie_mode)
        try:
            val = float(approx_episode_duration_seconds)
            self.approx_episode_duration_seconds = val if val > 0 else 24 * 60
        except Exception:
            self.approx_episode_duration_seconds = 24 * 60

    def _progress(self, value: Optional[int] = None, text: Optional[str] = None):
        if self.progress_dialog is None:
            return
        if callable(self.progress_dialog):
            try:
                self.progress_dialog(value, text)
            except TypeError:
                if value is not None:
                    self.progress_dialog(value)
        else:
            if text is not None and hasattr(self.progress_dialog, 'setLabelText'):
                self.progress_dialog.setLabelText(translate_text(text))
            if value is not None and hasattr(self.progress_dialog, 'setValue'):
                self.progress_dialog.setValue(int(value))
        app = QCoreApplication.instance()
        if app and QThread.currentThread() == app.thread():
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

    def _resolve_disc_output_name(self, selected_mpls_no_ext: str) -> str:
        cache = getattr(self, '_disc_output_name_cache', None)
        if cache is None:
            cache = {}
            self._disc_output_name_cache = cache
        if selected_mpls_no_ext in cache:
            return cache[selected_mpls_no_ext]

        mpls_path = selected_mpls_no_ext + '.mpls'
        meta_folder = os.path.join(os.path.join(mpls_path[:-19], 'META', 'DL'))
        output_name = ''
        if not os.path.exists(meta_folder):
            output_name = os.path.split(mpls_path[:-24])[-1]
        else:
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
            '?': '？', '*': '★', '<': '《', '>': '》', ':': '：', '"': "'", '/': '／', '\\': '／', '|': '￨'
        }
        output_name = ''.join(char_map.get(char) or char for char in output_name)
        cache[selected_mpls_no_ext] = output_name
        return output_name

    def generate_configuration(self, table: QTableWidget,
                               sub_combo_index: Optional[dict[int, int]] = None,
                               subtitle_index: Optional[int] = None) -> dict[int, dict[str, int | str]]:
        configuration = {}
        sub_index = 0
        bdmv_index = 0
        global CONFIGURATION
        approx_end_time = float(getattr(self, 'approx_episode_duration_seconds', 24 * 60) or (24 * 60))
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
                disc_output_name = self._resolve_disc_output_name(selected_mpls)
                for bdmv_index in range(table.rowCount()):
                    if  table.item(bdmv_index, 0).text() == folder:
                        break
                bdmv_index += 1
                offset = 0
                j = 1
                left_time = chapter.get_total_time()
                sub_end_time = sub_max_end[sub_index] if self.sub_files else approx_end_time
                for i, play_item_in_out_time in enumerate(chapter.in_out_time):
                    play_item_marks = chapter.mark_info.get(i)
                    if sub_index <= subtitle_index and j == chapter_index:
                        sub_end_time = offset + (sub_max_end[sub_index] if self.sub_files else approx_end_time)
                        configuration[sub_index] = {'folder': folder, 'selected_mpls': selected_mpls,
                                                    'bdmv_index': bdmv_index, 'chapter_index': j,
                                                    'offset': get_time_str(offset), 'disc_output_name': disc_output_name}
                        sub_index += 1
                        if sub_combo_index.get(sub_index):
                            chapter_index = sub_combo_index[sub_index]
                    elif sub_index > subtitle_index:
                        if offset > sub_end_time - 300 or offset == 0:
                            if (((sub_index + 1 < len(self.sub_files)) if self.sub_files else True)
                                    and left_time > (sub_max_end[sub_index + 1] if self.sub_files else approx_end_time) - 180):
                                sub_end_time = offset + (sub_max_end[sub_index] if self.sub_files else approx_end_time)
                                configuration[sub_index] = {'folder': folder, 'selected_mpls': selected_mpls,
                                                            'bdmv_index': bdmv_index, 'chapter_index': j,
                                                            'offset': get_time_str(offset), 'disc_output_name': disc_output_name}
                                sub_index += 1
                    if play_item_marks:
                        for mark in play_item_marks:
                            time_shift = offset + (mark - play_item_in_out_time[1]) / 45000
                            if sub_index <= subtitle_index and j == chapter_index:
                                sub_end_time = time_shift + (sub_max_end[sub_index] if self.sub_files else approx_end_time)
                                configuration[sub_index] = {'folder': folder, 'selected_mpls': selected_mpls,
                                                            'bdmv_index': bdmv_index, 'chapter_index': j,
                                                            'offset': get_time_str(time_shift), 'disc_output_name': disc_output_name}
                                sub_index += 1
                                if sub_combo_index.get(sub_index):
                                    chapter_index = sub_combo_index[sub_index]
                            elif sub_index > subtitle_index:
                                if time_shift > sub_end_time and (
                                        play_item_in_out_time[2] - mark) / 45000 > 1200:
                                    sub_end_time = time_shift + (sub_max_end[sub_index] if self.sub_files else approx_end_time)
                                    configuration[sub_index] = {'folder': folder, 'selected_mpls': selected_mpls,
                                                                'bdmv_index': bdmv_index, 'chapter_index': j,
                                                                'offset': get_time_str(time_shift), 'disc_output_name': disc_output_name}
                                    sub_index += 1
                            j += 1
                    offset += (play_item_in_out_time[2] - play_item_in_out_time[1]) / 45000
                    left_time += (play_item_in_out_time[1] - play_item_in_out_time[2]) / 45000
            CONFIGURATION = configuration
            return configuration
        for folder, chapter, selected_mpls in self.select_mpls_from_table(table):
            disc_output_name = self._resolve_disc_output_name(selected_mpls)
            for bdmv_index in range(table.rowCount()):
                if table.item(bdmv_index, 0).text() == folder:
                    break
            bdmv_index += 1
            start_time = 0
            sub_end_time = sub_max_end[sub_index] if self.sub_files else approx_end_time
            left_time = chapter.get_total_time()
            configuration[sub_index] = {'folder': folder, 'selected_mpls': selected_mpls,
                                        'bdmv_index': bdmv_index, 'chapter_index': 1, 'offset': '0',
                                        'disc_output_name': disc_output_name}
            j = 1
            for i, play_item_in_out_time in enumerate(chapter.in_out_time):
                play_item_marks = chapter.mark_info.get(i)
                chapter_num = len(play_item_marks or [])
                if play_item_marks:
                    play_item_duration_time = play_item_in_out_time[2] - play_item_in_out_time[1]
                    time_shift = (start_time + play_item_marks[0] - play_item_in_out_time[1]) / 45000
                    if time_shift > sub_end_time - 300:
                        if (((sub_index + 1 < len(self.sub_files)) if self.sub_files else True)
                                and left_time > (sub_max_end[sub_index + 1] if self.sub_files else approx_end_time) - 180):
                            sub_index += 1
                            sub_end_time = (time_shift + (sub_max_end[sub_index] if self.sub_files else approx_end_time))
                            configuration[sub_index] = {'folder': folder, 'selected_mpls': selected_mpls,
                                                        'bdmv_index': bdmv_index, 'chapter_index': j,
                                                        'offset': get_time_str(time_shift), 'disc_output_name': disc_output_name}

                    if play_item_duration_time / 45000 > 2600 and sub_end_time - time_shift < 1800:
                        k = j
                        for mark in play_item_marks[1:]:
                            k += 1
                            time_shift = (start_time + mark - play_item_in_out_time[1]) / 45000
                            if time_shift > sub_end_time and (
                                    play_item_in_out_time[2] - mark) / 45000 > 1200:
                                sub_index += 1
                                sub_end_time = (time_shift + (sub_max_end[sub_index] if self.sub_files else approx_end_time))
                                configuration[sub_index] = {'folder': folder, 'selected_mpls': selected_mpls,
                                                            'bdmv_index': bdmv_index, 'chapter_index': k,
                                                            'offset': get_time_str(time_shift), 'disc_output_name': disc_output_name}

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
        approx_end_time = float(getattr(self, 'approx_episode_duration_seconds', 24 * 60) or (24 * 60))

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
                disc_output_name = self._resolve_disc_output_name(selected_mpls_no_ext)
                chapter = Chapter(selected_mpls_no_ext + '.mpls')
                offset = 0
                j = 1
                left_time = chapter.get_total_time()
                sub_end_time = sub_max_end[sub_index] if self.sub_files else approx_end_time
                for i, play_item_in_out_time in enumerate(chapter.in_out_time):
                    play_item_marks = chapter.mark_info.get(i)
                    if sub_index <= subtitle_index and j == chapter_index:
                        sub_end_time = offset + (sub_max_end[sub_index] if self.sub_files else approx_end_time)
                        configuration[sub_index] = {'folder': folder, 'selected_mpls': selected_mpls_no_ext,
                                                    'bdmv_index': bdmv_index, 'chapter_index': j,
                                                    'offset': get_time_str(offset), 'disc_output_name': disc_output_name}
                        sub_index += 1
                        if sub_combo_index.get(sub_index):
                            chapter_index = sub_combo_index[sub_index]
                    elif sub_index > subtitle_index:
                        if offset > sub_end_time - 300 or offset == 0:
                            if (((sub_index + 1 < len(self.sub_files)) if self.sub_files else True)
                                    and left_time > (sub_max_end[sub_index + 1] if self.sub_files else approx_end_time) - 180):
                                sub_end_time = offset + (sub_max_end[sub_index] if self.sub_files else approx_end_time)
                                configuration[sub_index] = {'folder': folder, 'selected_mpls': selected_mpls_no_ext,
                                                            'bdmv_index': bdmv_index, 'chapter_index': j,
                                                            'offset': get_time_str(offset), 'disc_output_name': disc_output_name}
                                sub_index += 1
                    if play_item_marks:
                        for mark in play_item_marks:
                            time_shift = offset + (mark - play_item_in_out_time[1]) / 45000
                            if sub_index <= subtitle_index and j == chapter_index:
                                sub_end_time = time_shift + (sub_max_end[sub_index] if self.sub_files else approx_end_time)
                                configuration[sub_index] = {'folder': folder, 'selected_mpls': selected_mpls_no_ext,
                                                            'bdmv_index': bdmv_index, 'chapter_index': j,
                                                            'offset': get_time_str(time_shift), 'disc_output_name': disc_output_name}
                                sub_index += 1
                                if sub_combo_index.get(sub_index):
                                    chapter_index = sub_combo_index[sub_index]
                            elif sub_index > subtitle_index:
                                if time_shift > sub_end_time and (
                                        play_item_in_out_time[2] - mark) / 45000 > 1200:
                                    sub_end_time = time_shift + (sub_max_end[sub_index] if self.sub_files else approx_end_time)
                                    configuration[sub_index] = {'folder': folder, 'selected_mpls': selected_mpls_no_ext,
                                                                'bdmv_index': bdmv_index, 'chapter_index': j,
                                                                'offset': get_time_str(time_shift), 'disc_output_name': disc_output_name}
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
            disc_output_name = self._resolve_disc_output_name(selected_mpls_no_ext)
            chapter = Chapter(selected_mpls_no_ext + '.mpls')
            start_time = 0
            sub_end_time = sub_max_end[sub_index] if self.sub_files else approx_end_time
            left_time = chapter.get_total_time()
            configuration[sub_index] = {'folder': folder, 'selected_mpls': selected_mpls_no_ext,
                                        'bdmv_index': bdmv_index, 'chapter_index': 1, 'offset': '0',
                                        'disc_output_name': disc_output_name}
            j = 1
            for i, play_item_in_out_time in enumerate(chapter.in_out_time):
                play_item_marks = chapter.mark_info.get(i)
                chapter_num = len(play_item_marks or [])
                if play_item_marks:
                    play_item_duration_time = play_item_in_out_time[2] - play_item_in_out_time[1]
                    time_shift = (start_time + play_item_marks[0] - play_item_in_out_time[1]) / 45000
                    if time_shift > sub_end_time - 300:
                        if (((sub_index + 1 < len(self.sub_files)) if self.sub_files else True)
                                and left_time > (sub_max_end[sub_index + 1] if self.sub_files else approx_end_time) - 180):
                            sub_index += 1
                            sub_end_time = (time_shift + (sub_max_end[sub_index] if self.sub_files else approx_end_time))
                            configuration[sub_index] = {'folder': folder, 'selected_mpls': selected_mpls_no_ext,
                                                        'bdmv_index': bdmv_index, 'chapter_index': j,
                                                        'offset': get_time_str(time_shift), 'disc_output_name': disc_output_name}

                    if play_item_duration_time / 45000 > 2600 and sub_end_time - time_shift < 1800:
                        k = j
                        for mark in play_item_marks[1:]:
                            k += 1
                            time_shift = (start_time + mark - play_item_in_out_time[1]) / 45000
                            if time_shift > sub_end_time and (
                                    play_item_in_out_time[2] - mark) / 45000 > 1200:
                                sub_index += 1
                                sub_end_time = (time_shift + (sub_max_end[sub_index] if self.sub_files else approx_end_time))
                                configuration[sub_index] = {'folder': folder, 'selected_mpls': selected_mpls_no_ext,
                                                            'bdmv_index': bdmv_index, 'chapter_index': k,
                                                            'offset': get_time_str(time_shift), 'disc_output_name': disc_output_name}

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
                        suffix = str(getattr(self, 'subtitle_suffix', '') or '')
                        sub.dump(conf['folder'] + suffix, conf['selected_mpls'] + suffix)
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
            suffix = str(getattr(self, 'subtitle_suffix', '') or '')
            sub.dump(conf['folder'] + suffix, conf['selected_mpls'] + suffix)
        self._progress(1000)

    def add_chapter_to_mkv(self, mkv_files, table: Optional[QTableWidget] = None,
                           selected_mpls: Optional[list[tuple[str, str]]] = None,
                           cancel_event: Optional[threading.Event] = None):
        mkv_index = 0
        if selected_mpls is not None:
            iterator = ((folder, Chapter(selected_mpls_no_ext + '.mpls'), selected_mpls_no_ext)
                        for folder, selected_mpls_no_ext in selected_mpls)
        else:
            if table is None:
                return
            iterator = self.select_mpls_from_table(table)

        for folder, chapter, selected_mpls in iterator:
            if cancel_event and cancel_event.is_set():
                raise _Cancelled()
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
                if cancel_event and cancel_event.is_set():
                    raise _Cancelled()
                clip_information_filename, in_time, out_time = chapter.in_out_time[ref_to_play_item_id]
                for mark_timestamp in mark_timestamps:
                    if cancel_event and cancel_event.is_set():
                        raise _Cancelled()
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

    def _create_sp_mkvs_from_entries(
        self,
        bdmv_index_conf: dict[int, list[dict[str, int | str]]],
        sp_entries: list[dict[str, int | str]],
        sps_folder: str,
        cancel_event: Optional[threading.Event] = None,
    ) -> list[tuple[int, str]]:
        sp_index_by_bdmv: dict[int, int] = {}
        created: list[tuple[int, str]] = []
        single_volume = bool(getattr(self, 'movie_mode', False) and len(bdmv_index_conf) == 1)
        for entry_idx, entry in enumerate(sp_entries, start=1):
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
            output_name = str(entry.get('output_name') or '').strip()

            sp_mkv_path = ''
            src_path = ''
            use_chapter_language = False
            if mpls_file:
                sp_index_by_bdmv[sp_bdmv_index] = sp_index_by_bdmv.get(sp_bdmv_index, 0) + 1
                sp_mkv_path = os.path.join(sps_folder, f'BD_Vol_{bdmv_vol}_SP0{sp_index_by_bdmv[sp_bdmv_index]}.mkv')
                src_path = os.path.join(playlist_dir, mpls_file)
                use_chapter_language = True
            else:
                m2ts_files = [x.strip() for x in m2ts_file.split(',') if x.strip()]
                if m2ts_files:
                    m2ts_name = m2ts_files[0]
                    sp_mkv_path = os.path.join(sps_folder, f'BD_Vol_{bdmv_vol}_{m2ts_name[:-5]}.mkv')
                    src_path = os.path.join(stream_dir, m2ts_name)

            if not src_path or not sp_mkv_path:
                continue
            if output_name:
                if not output_name.lower().endswith('.mkv'):
                    output_name += '.mkv'
                if single_volume:
                    output_name = re.sub(rf'(?i)^BD_Vol_{bdmv_vol}_', '', output_name)
                sp_mkv_path = os.path.join(sps_folder, output_name)
            if single_volume:
                base_name = os.path.basename(sp_mkv_path)
                base_name = re.sub(rf'(?i)^BD_Vol_{bdmv_vol}_', '', base_name)
                sp_mkv_path = os.path.join(sps_folder, base_name)

            if use_chapter_language:
                cmd = f'"{MKV_MERGE_PATH}" {mkvtoolnix_ui_language_arg()} --chapter-language eng -o "{sp_mkv_path}" "{src_path}"'
            else:
                cmd = f'"{MKV_MERGE_PATH}" {mkvtoolnix_ui_language_arg()} -o "{sp_mkv_path}" "{src_path}"'
            subprocess.Popen(cmd, shell=True).wait()
            if os.path.exists(sp_mkv_path):
                created.append((entry_idx, sp_mkv_path))
        return created

    def _mkv_sort_key(self, p: str):
        name = os.path.basename(p)
        m = re.search(r'BD_Vol_(\d{3})', name)
        vol = int(m.group(1)) if m else 9999
        m2 = re.search(r'-(\d{3})\.mkv$', name, re.IGNORECASE)
        seg = int(m2.group(1)) if m2 else 0
        return vol, seg, name.lower()

    def _prepare_episode_run(
        self,
        table: Optional[QTableWidget],
        folder_path: str,
        configuration: Optional[dict[int, dict[str, int | str]]],
        ensure_tools: bool,
    ) -> tuple[str, set[str], dict[int, list[dict[str, int | str]]]]:
        if configuration is not None:
            self.configuration = configuration
        elif not CONFIGURATION:
            if table is None:
                self.configuration = {}
            else:
                self.configuration = self.generate_configuration(table)
        else:
            self.configuration = CONFIGURATION

        dst_folder = os.path.join(folder_path, os.path.basename(self.bdmv_path))
        if not os.path.exists(dst_folder):
            os.mkdir(dst_folder)

        try:
            mkv_files_before = {f for f in os.listdir(dst_folder) if f.lower().endswith('.mkv')}
        except Exception:
            mkv_files_before = set()

        bdmv_index_conf: dict[int, list[dict[str, int | str]]] = {}
        for _, conf in self.configuration.items():
            bdmv_index = int(conf['bdmv_index'])
            if bdmv_index in bdmv_index_conf:
                bdmv_index_conf[bdmv_index].append(conf)
            else:
                bdmv_index_conf[bdmv_index] = [conf]

        if ensure_tools:
            find_mkvtoolinx()

        return dst_folder, mkv_files_before, bdmv_index_conf

    def _collect_target_mkv_files(self, dst_folder: str, mkv_files_before: set[str]) -> list[str]:
        try:
            mkv_files_after = [f for f in os.listdir(dst_folder) if f.lower().endswith('.mkv')]
        except Exception:
            mkv_files_after = []
        created = [os.path.join(dst_folder, f) for f in mkv_files_after if f not in mkv_files_before]
        if created:
            return sorted(created, key=self._mkv_sort_key)
        return sorted([os.path.join(dst_folder, f) for f in mkv_files_after], key=self._mkv_sort_key)

    def _apply_episode_output_names(self, mkv_files: list[str], output_names: Optional[list[str]] = None) -> list[str]:
        total = len(mkv_files)
        if total <= 0:
            return mkv_files
        planned = output_names or []
        updated: list[str] = []
        for i, p in enumerate(mkv_files, start=1):
            folder = os.path.dirname(p)
            base = os.path.basename(p)
            user_name = planned[i - 1].strip() if i - 1 < len(planned) and isinstance(planned[i - 1], str) else ''
            new_base = user_name if user_name else base
            if not new_base.lower().endswith('.mkv'):
                new_base += '.mkv'
            new_path = os.path.join(folder, new_base)
            if os.path.normcase(p) == os.path.normcase(new_path):
                updated.append(p)
                continue
            if not os.path.exists(p):
                updated.append(p)
                continue
            if os.path.exists(new_path):
                stem, ext = os.path.splitext(new_base)
                k = 1
                candidate = new_path
                while os.path.exists(candidate):
                    candidate = os.path.join(folder, f'{stem} ({k}){ext}')
                    k += 1
                new_path = candidate
            try:
                os.rename(p, new_path)
                updated.append(new_path)
            except Exception:
                updated.append(p)
        return updated

    def _build_main_episode_mkvs(
        self,
        bdmv_index_conf: dict[int, list[dict[str, int | str]]],
        dst_folder: str,
        cancel_event: Optional[threading.Event] = None,
    ) -> None:
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
                        if not selected_eng_audio_track[1] or audio_type_weight[codec_name] > audio_type_weight[selected_eng_audio_track[1]]:
                            selected_eng_audio_track = [str(stream_info['index']), codec_name]
                    elif lang == 'zho':
                        if not selected_zho_audio_track[1] or audio_type_weight[codec_name] > audio_type_weight[selected_zho_audio_track[1]]:
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
            if os.path.exists(meta_folder):
                for filename in os.listdir(meta_folder):
                    if filename.endswith('.jpg') or filename.endswith('.JPG') or filename.endswith('.JPEG') or filename.endswith('.jpeg') or filename.endswith('.png') or filename.endswith('.PNG'):
                        if os.path.getsize(os.path.join(meta_folder, filename)) > cover_size:
                            cover = os.path.join(meta_folder, filename)
                            cover_size = os.path.getsize(os.path.join(meta_folder, filename))
            output_name = ''
            try:
                output_name = str(confs[0].get('disc_output_name') or '').strip()
            except Exception:
                output_name = ''
            if not output_name:
                output_name = self._resolve_disc_output_name(confs[0]['selected_mpls'])
            if cover:
                print(f"找到封面图片 ｢{cover}｣")
            print(f'输出文件名{output_name}.mkv')

            bdmv_vol = '0' * (3 - len(str(bdmv_index))) + str(bdmv_index)
            if getattr(self, 'movie_mode', False):
                output_name_from_conf = ''
                try:
                    output_name_from_conf = str(confs[0].get('output_name') or '').strip()
                except Exception:
                    output_name_from_conf = ''
                if output_name_from_conf:
                    base = output_name_from_conf
                    if not base.lower().endswith('.mkv'):
                        base += '.mkv'
                    output_file = base if os.path.isabs(base) else os.path.join(dst_folder, base)
                else:
                    output_file = f'{os.path.join(dst_folder, output_name)}_BD_Vol_{bdmv_vol}.mkv'
                if len(bdmv_index_conf) == 1:
                    out_dir = os.path.dirname(output_file)
                    out_base = os.path.basename(output_file)
                    out_base = re.sub(rf'(?i)^BD_Vol_{bdmv_vol}_', '', out_base)
                    out_base = re.sub(rf'(?i)_BD_Vol_{bdmv_vol}(?=\.mkv$)', '', out_base)
                    output_file = os.path.join(out_dir, out_base)
                remux_cmd = (f'"{MKV_MERGE_PATH}" {mkvtoolnix_ui_language_arg()} --chapter-language eng -o "{output_file}" '
                             f'{("-a " + ",".join(copy_audio_track)) if copy_audio_track else ""} '
                             f'{("-s " + ",".join(copy_sub_track)) if copy_sub_track else ""} '
                             f'{(" --attachment-name Cover.jpg" + " --attach-file " + "\"" + cover + "\"") if cover else ""}  '
                             f'"{mpls_path}"')
            else:
                chapter_split = ','.join(map(str, [conf['chapter_index'] for conf in confs]))
                output_file = f'{os.path.join(dst_folder, output_name)}_BD_Vol_{bdmv_vol}.mkv'
                remux_cmd = (f'"{MKV_MERGE_PATH}" {mkvtoolnix_ui_language_arg()} --split chapters:{chapter_split} -o "{output_file}" '
                             f'{("-a " + ",".join(copy_audio_track)) if copy_audio_track else ""} '
                             f'{("-s " + ",".join(copy_sub_track)) if copy_sub_track else ""} '
                             f'{(" --attachment-name Cover.jpg" + " --attach-file " + "\"" + cover + "\"") if cover else ""}  '
                             f'"{mpls_path}"')
            print(f'混流命令: {remux_cmd}')
            self._progress(text=f'混流中：BD_Vol_{bdmv_vol}')
            subprocess.Popen(remux_cmd, shell=True).wait()
            self._progress(int(idx / max(len(bdmv_index_list), 1) * 300))

    def episodes_remux(self, table: Optional[QTableWidget], folder_path: str,
                       selected_mpls: Optional[list[tuple[str, str]]] = None,
                       configuration: Optional[dict[int, dict[str, int | str]]] = None,
                       cancel_event: Optional[threading.Event] = None,
                       ensure_tools: bool = True,
                       sp_entries: Optional[list[dict[str, int | str]]] = None,
                       episode_output_names: Optional[list[str]] = None,
                       episode_subtitle_languages: Optional[list[str]] = None):
        dst_folder, mkv_files_before, bdmv_index_conf = self._prepare_episode_run(
            table, folder_path, configuration, ensure_tools
        )

        self._build_main_episode_mkvs(bdmv_index_conf, dst_folder, cancel_event=cancel_event)

        self.checked = True
        self.episode_subtitle_languages = episode_subtitle_languages or []
        mkv_files = self._collect_target_mkv_files(dst_folder, mkv_files_before)
        mkv_files = self._apply_episode_output_names(mkv_files, episode_output_names)
        if cancel_event and cancel_event.is_set():
            raise _Cancelled()
        if not getattr(self, 'movie_mode', False):
            self._progress(310, '写入章节中')
            self.add_chapter_to_mkv(mkv_files, table, selected_mpls=selected_mpls, cancel_event=cancel_event)
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

        if sp_entries is not None:
            self._create_sp_mkvs_from_entries(bdmv_index_conf, sp_entries, sps_folder, cancel_event=cancel_event)
        else:
            single_volume = bool(getattr(self, 'movie_mode', False) and len(bdmv_index_conf) == 1)
            for bdmv_index in sorted(bdmv_index_conf.keys()):
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
                        if set(index_to_m2ts.values()).issubset(main_m2ts_files):
                            continue
                        if len(index_to_m2ts) > 1:
                            sp_index += 1
                            out_name = (f'SP0{sp_index}.mkv'
                                        if single_volume else f'BD_Vol_{bdmv_vol}_SP0{sp_index}.mkv')
                            subprocess.Popen(f'"{MKV_MERGE_PATH}" {mkvtoolnix_ui_language_arg()} '
                                             f'--chapter-language eng -o "{os.path.join(sps_folder, out_name)}" "{mpls_file_path}"',
                                             shell=True).wait()
                            parsed_m2ts_files |= set(index_to_m2ts.values())
                stream_folder = os.path.dirname(mpls_path).removesuffix('PLAYLIST') + 'STREAM'
                for stream_file in sorted(os.listdir(stream_folder)):
                    if cancel_event and cancel_event.is_set():
                        raise _Cancelled()
                    if stream_file not in parsed_m2ts_files and stream_file.endswith('.m2ts'):
                        if M2TS(os.path.join(stream_folder, stream_file)).get_duration() > 30 * 90000:
                            out_name = (f'{stream_file[:-5]}.mkv'
                                        if single_volume else f'BD_Vol_{bdmv_vol}_{stream_file[:-5]}.mkv')
                            subprocess.Popen(
                                f'"{MKV_MERGE_PATH}" {mkvtoolnix_ui_language_arg()} -o "{os.path.join(sps_folder, out_name)}" '
                                f'"{os.path.join(stream_folder, stream_file)}"',
                                shell=True
                            ).wait()
        sp_files = [sp for sp in os.listdir(sps_folder) if sp.lower().endswith('.mkv')]
        sp_files.sort()
        total_sp = len(sp_files) or 1
        self._progress(900, '处理 SPs 音轨')
        for idx, sp in enumerate(sp_files, start=1):
            if cancel_event and cancel_event.is_set():
                raise _Cancelled()
            self._progress(900 + int(90 * idx / total_sp), f'处理 SPs 音轨 {idx}/{total_sp}：{sp}')
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
                        episode_output_names: Optional[list[str]] = None,
                        episode_subtitle_languages: Optional[list[str]] = None,
                        vspipe_mode: str = 'bundle',
                        x265_mode: str = 'bundle',
                        x265_params: str = '',
                        sub_pack_mode: str = 'external'):
        dst_folder, mkv_files_before, bdmv_index_conf = self._prepare_episode_run(
            table, folder_path, configuration, ensure_tools
        )

        self._build_main_episode_mkvs(bdmv_index_conf, dst_folder, cancel_event=cancel_event)

        self.checked = True
        self.episode_subtitle_languages = episode_subtitle_languages or []
        mkv_files = self._collect_target_mkv_files(dst_folder, mkv_files_before)
        mkv_files = self._apply_episode_output_names(mkv_files, episode_output_names)
        if cancel_event and cancel_event.is_set():
            raise _Cancelled()
        if not getattr(self, 'movie_mode', False):
            self._progress(310, '写入章节中')
            self.add_chapter_to_mkv(mkv_files, table, selected_mpls=selected_mpls, cancel_event=cancel_event)
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

        if sp_entries is not None:
            created_sp = self._create_sp_mkvs_from_entries(bdmv_index_conf, sp_entries, sps_folder, cancel_event=cancel_event)
            total_sp = len(created_sp) or 1
            for idx, (entry_idx, sp_mkv_path) in enumerate(created_sp, start=1):
                if cancel_event and cancel_event.is_set():
                    raise _Cancelled()
                self._progress(text=f'压制并混流 SPs：{os.path.basename(sp_mkv_path)}')
                if sp_vpy_paths and 0 <= (entry_idx - 1) < len(sp_vpy_paths) and sp_vpy_paths[entry_idx - 1]:
                    cur_sp_vpy = str(sp_vpy_paths[entry_idx - 1])
                else:
                    cur_sp_vpy = os.path.join(os.getcwd(), 'vpy.vpy')
                self.encode_task(sp_mkv_path, sps_folder, -1, cur_sp_vpy, vspipe_mode, x265_mode, x265_params, 'external')
                self._progress(900 + int(90 * idx / total_sp))
        else:
            single_volume = bool(getattr(self, 'movie_mode', False) and len(bdmv_index_conf) == 1)
            for bdmv_index, confs in bdmv_index_conf.items():
                if cancel_event and cancel_event.is_set():
                    raise _Cancelled()
                bdmv_vol = '0' * (3 - len(str(bdmv_index))) + str(bdmv_index)
                mpls_path = confs[0]['selected_mpls'] + '.mpls'
                index_to_m2ts, index_to_offset = get_index_to_m2ts_and_offset(Chapter(mpls_path))
                main_m2ts_files = set(index_to_m2ts.values())
                parsed_m2ts_files = set(main_m2ts_files)
                sp_index = 0
                for mpls_file in os.listdir(os.path.dirname(mpls_path)):
                    if cancel_event and cancel_event.is_set():
                        raise _Cancelled()
                    if not mpls_file.endswith('.mpls'):
                        continue
                    mpls_file_path = os.path.join(os.path.dirname(mpls_path), mpls_file)
                    if mpls_file_path != mpls_path:
                        index_to_m2ts, index_to_offset = get_index_to_m2ts_and_offset(Chapter(mpls_file_path))
                        if set(index_to_m2ts.values()).issubset(main_m2ts_files):
                            continue
                        if len(index_to_m2ts) > 1:
                            sp_index += 1
                            out_name = (f'SP0{sp_index}.mkv'
                                        if single_volume else f'BD_Vol_{bdmv_vol}_SP0{sp_index}.mkv')
                            subprocess.Popen(f'"{MKV_MERGE_PATH}" {mkvtoolnix_ui_language_arg()} '
                                             f'--chapter-language eng -o "{os.path.join(sps_folder, out_name)}" "{mpls_file_path}"',
                                             shell=True).wait()
                            parsed_m2ts_files |= set(index_to_m2ts.values())
                stream_folder = os.path.dirname(mpls_path).removesuffix('PLAYLIST') + 'STREAM'
                for stream_file in os.listdir(stream_folder):
                    if cancel_event and cancel_event.is_set():
                        raise _Cancelled()
                    if stream_file not in parsed_m2ts_files and stream_file.endswith('.m2ts'):
                        if M2TS(os.path.join(stream_folder, stream_file)).get_duration() > 30 * 90000:
                            out_name = (f'{stream_file[:-5]}.mkv'
                                        if single_volume else f'BD_Vol_{bdmv_vol}_{stream_file[:-5]}.mkv')
                            subprocess.Popen(
                                f'"{MKV_MERGE_PATH}" {mkvtoolnix_ui_language_arg()} -o "{os.path.join(sps_folder, out_name)}" '
                                f'"{os.path.join(stream_folder, stream_file)}"',
                                shell=True
                            ).wait()
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
                lang = 'chi'
                try:
                    langs = getattr(self, 'episode_subtitle_languages', None) or []
                    if 0 <= (i - 1) < len(langs) and str(langs[i - 1]).strip():
                        lang = str(langs[i - 1]).strip()
                except Exception:
                    lang = 'chi'
                remux_cmd += f' --language 0:{lang} "{self.sub_files[i - 1]}"'
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
                    lang = 'chi'
                    try:
                        langs = getattr(self, 'episode_subtitle_languages', None) or []
                        if 0 <= (i - 1) < len(langs) and str(langs[i - 1]).strip():
                            lang = str(langs[i - 1]).strip()
                    except Exception:
                        lang = 'chi'
                    remux_cmd += f' --language 0:{lang} "{self.sub_files[i - 1]}"'
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
            return (f'"{MKV_MERGE_PATH}" {mkvtoolnix_ui_language_arg()} -o "{output_file}" --track-order {tracker_order} '
                    f'-a {audio_tracks} "{mkv_file}" {language_options}')
        else:
            tracker_order = f'{audio_track_num + 1}:0,{tracker_order}'
            return (f'"{MKV_MERGE_PATH}" {mkvtoolnix_ui_language_arg()} -o "{output_file}" --track-order {tracker_order} '
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
            extract_cmd = f'"{MKV_EXTRACT_PATH}" {mkvtoolnix_ui_language_arg()} "{mkv_file}" tracks {" ".join(extract_info)}'
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
                 cancel_event: threading.Event, sp_entries: list[dict[str, int | str]],
                 episode_output_names: list[str], episode_subtitle_languages: list[str],
                 movie_mode: bool = False):
        super().__init__()
        self.bdmv_path = bdmv_path
        self.sub_files = sub_files
        self.checked = checked
        self.output_folder = output_folder
        self.configuration = configuration
        self.selected_mpls = selected_mpls
        self.cancel_event = cancel_event
        self.sp_entries = sp_entries
        self.episode_output_names = episode_output_names
        self.episode_subtitle_languages = episode_subtitle_languages
        self.movie_mode = bool(movie_mode)

    def run(self):
        try:
            def progress_cb(value: Optional[int] = None, text: Optional[str] = None):
                if value is not None:
                    self.progress.emit(int(value))
                if text:
                    self.label.emit(str(text))
                if self.cancel_event.is_set():
                    raise _Cancelled()

            bs = BluraySubtitle(self.bdmv_path, self.sub_files, self.checked, progress_cb, movie_mode=self.movie_mode)
            bs.configuration = self.configuration
            bs.episodes_remux(
                None,
                self.output_folder,
                selected_mpls=self.selected_mpls,
                configuration=self.configuration,
                cancel_event=self.cancel_event,
                ensure_tools=False,
                sp_entries=self.sp_entries,
                episode_output_names=self.episode_output_names,
                episode_subtitle_languages=self.episode_subtitle_languages
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
                 episode_output_names: list[str], episode_subtitle_languages: list[str],
                 vspipe_mode: str, x265_mode: str, x265_params: str, sub_pack_mode: str,
                 movie_mode: bool = False):
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
        self.episode_output_names = episode_output_names
        self.episode_subtitle_languages = episode_subtitle_languages
        self.vspipe_mode = vspipe_mode
        self.x265_mode = x265_mode
        self.x265_params = x265_params
        self.sub_pack_mode = sub_pack_mode
        self.movie_mode = bool(movie_mode)

    def run(self):
        try:
            def progress_cb(value: Optional[int] = None, text: Optional[str] = None):
                if value is not None:
                    self.progress.emit(int(value))
                if text:
                    self.label.emit(str(text))
                if self.cancel_event.is_set():
                    raise _Cancelled()

            bs = BluraySubtitle(self.bdmv_path, self.sub_files, self.checked, progress_cb, movie_mode=self.movie_mode)
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
                episode_output_names=self.episode_output_names,
                episode_subtitle_languages=self.episode_subtitle_languages,
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
                 selected_mpls: list[tuple[str, str]], cancel_event: threading.Event,
                 subtitle_suffix: str = ''):
        super().__init__()
        self.bdmv_path = bdmv_path
        self.sub_files = sub_files
        self.checked = checked
        self.selected_mpls = selected_mpls
        self.cancel_event = cancel_event
        self.movie_tasks: list[tuple[str, str, str]] = []
        self.subtitle_suffix = str(subtitle_suffix or '')

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
            if self.movie_tasks:
                total = len(self.movie_tasks) or 1
                suffix = self.subtitle_suffix
                for idx, (sub_path, folder, selected_mpls_no_ext) in enumerate(self.movie_tasks, start=1):
                    if self.cancel_event.is_set():
                        raise _Cancelled()
                    progress_cb(int((idx - 1) / total * 1000), f'写入字幕文件 {idx}/{total}')
                    sub = Subtitle(sub_path)
                    if hasattr(sub, 'content'):
                        sub.dump(folder + suffix, selected_mpls_no_ext + suffix)
                progress_cb(1000, '完成')
            else:
                bs = BluraySubtitle(self.bdmv_path, self.sub_files, self.checked, progress_cb)
                bs.subtitle_suffix = self.subtitle_suffix
            
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
                 selected_mpls: list[tuple[str, str]], cancel_event: threading.Event,
                 movie_mode: bool = False):
        super().__init__()
        self.seq = seq
        self.mode = mode
        self.subtitle_folder = subtitle_folder
        self.bdmv_path = bdmv_path
        self.checked = checked
        self.selected_mpls = selected_mpls
        self.cancel_event = cancel_event
        self.movie_mode = bool(movie_mode)

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

            configuration = {}
            if not (self.movie_mode and self.mode in (1, 3, 4)):
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

    def t(self, text: str) -> str:
        return translate_text(str(text), getattr(self, '_language_code', CURRENT_UI_LANGUAGE))

    def _refresh_language_combo(self):
        if not hasattr(self, 'language_label') or not hasattr(self, 'language_combo'):
            return
        current_code = self.language_combo.currentData() or 'en'
        self.language_label.setText(self.t('语言'))
        self.language_combo.blockSignals(True)
        self.language_combo.setItemText(0, 'English')
        self.language_combo.setItemText(1, '简体中文')
        idx = 0 if current_code == 'en' else 1
        self.language_combo.setCurrentIndex(idx)
        self.language_combo.blockSignals(False)

    def _translate_widget_texts(self):
        for widget in self.findChildren(QWidget):
            if widget is getattr(self, 'language_combo', None):
                continue
            if widget is getattr(self, 'subtitle_suffix_combo', None):
                continue
            if isinstance(widget, (QLineEdit, QPlainTextEdit)):
                continue
            if isinstance(widget, QGroupBox):
                title_getter = getattr(widget, 'title', None)
                title_text = title_getter() if callable(title_getter) else ''
                if title_text:
                    widget.setTitle(self.t(title_text))
            if isinstance(widget, QTabBar):
                widget.blockSignals(True)
                try:
                    for i in range(widget.count()):
                        widget.setTabText(i, self.t(widget.tabText(i)))
                finally:
                    widget.blockSignals(False)
            if isinstance(widget, QComboBox):
                widget.blockSignals(True)
                try:
                    for i in range(widget.count()):
                        widget.setItemText(i, self.t(widget.itemText(i)))
                finally:
                    widget.blockSignals(False)
            if hasattr(widget, 'text') and hasattr(widget, 'setText'):
                try:
                    txt = widget.text()
                    if isinstance(txt, str) and txt:
                        widget.setText(self.t(txt))
                except Exception:
                    pass

    def _apply_language(self, language_code: str):
        global CURRENT_UI_LANGUAGE
        code = 'zh' if language_code == 'zh' else 'en'
        self._language_code = code
        CURRENT_UI_LANGUAGE = code
        self._language_updating = True
        try:
            self.setWindowTitle(APP_TITLE)
            self._translate_widget_texts()
            self._refresh_subtitle_suffix_options()
            self._refresh_language_combo()
            self._refresh_all_table_headers()
            self._refresh_language_dependent_sizes()
            self.on_select_function(force=True, keep_inputs=True, keep_state=True)
            self._refresh_language_dependent_sizes()
            self._refresh_language_column_defaults()
        finally:
            self._language_updating = False

    def _refresh_subtitle_suffix_options(self):
        combo = getattr(self, 'subtitle_suffix_combo', None)
        if not isinstance(combo, QComboBox):
            return
        current = (combo.currentText() or '').strip()
        combo.blockSignals(True)
        try:
            combo.clear()
            if getattr(self, '_language_code', CURRENT_UI_LANGUAGE) == 'zh':
                items = ["", ".zh-Hans", ".zh-Hant", ".chs", ".cht", ".sc", ".tc", ".big5", ".gb"]
            else:
                items = ["", "en", "eng", "en_US", "jpn", "jp", "kor"]
            combo.addItems(items)
            combo.setCurrentText(current if current != '' else '')
        finally:
            combo.blockSignals(False)

    def _get_subtitle_suffix(self) -> str:
        combo = getattr(self, 'subtitle_suffix_combo', None)
        if isinstance(combo, QComboBox):
            return (combo.currentText() or '').strip()
        return ''

    def _on_language_changed(self):
        code = self.language_combo.currentData() or 'en'
        self._apply_language(str(code))

    def _localized_headers_for_keys(self, keys: list[str]) -> list[str]:
        if getattr(self, '_language_code', CURRENT_UI_LANGUAGE) != 'zh':
            return list(keys)
        zh = {
            'path': '路径',
            'size': '大小',
            'info': '信息',
            'select': '选择',
            'sub_duration': '字幕时长',
            'warning': '提示',
            'bdmv_index': '原盘序号',
            'chapter_index': '章节序号',
            'offset': '偏移',
            'duration': '时长',
            'sub_path': '字幕路径',
            'ep_duration': '单集时长',
            'm2ts_file': 'm2ts 文件',
            'language': '语言',
            'output_name': '输出文件名',
            'vpy_path': 'vpy 路径',
            'edit_vpy': '编辑 vpy',
            'preview_script': '预览',
            'mpls_file': 'mpls 文件',
            'chapters': '章节',
            'main': '主播放列表',
            'play': '播放',
            'file': '文件',
            'index': '序号',
            'start': '开始',
            'end': '结束',
            'text': '内容',
        }
        return [zh.get(k, str(k).replace('_', ' ')) for k in keys]

    def _set_table_headers(self, table: QTableWidget, keys: list[str]):
        try:
            table.setHorizontalHeaderLabels(self._localized_headers_for_keys(keys))
        except Exception:
            pass

    def _refresh_all_table_headers(self):
        try:
            if hasattr(self, 'table1') and self.table1:
                self._set_table_headers(self.table1, BDMV_LABELS)
        except Exception:
            pass

        try:
            if hasattr(self, 'table2') and self.table2:
                function_id = self.get_selected_function_id()
                if function_id == 1:
                    self._set_table_headers(self.table2, SUBTITLE_LABELS)
                elif function_id == 2:
                    self._set_table_headers(self.table2, MKV_LABELS)
                elif function_id == 3:
                    self._set_table_headers(self.table2, REMUX_LABELS)
                elif function_id == 4:
                    self._set_table_headers(self.table2, ENCODE_LABELS)
        except Exception:
            pass

        try:
            if hasattr(self, 'table3') and self.table3:
                self._set_table_headers(self.table3, ENCODE_SP_LABELS)
        except Exception:
            pass

        try:
            if hasattr(self, 'table1') and self.table1:
                for r in range(self.table1.rowCount()):
                    info_table = self.table1.cellWidget(r, 2)
                    if isinstance(info_table, QTableWidget):
                        self._set_table_headers(info_table, ['mpls_file', 'duration', 'chapters', 'main', 'play'])
        except Exception:
            pass

    def _adjust_combo_width_to_contents(self, combo: QComboBox, padding: int = 44, min_width: int = 80, max_width: int = 520):
        if not combo:
            return
        try:
            fm = QFontMetrics(combo.font())
            longest = 0
            for i in range(combo.count()):
                longest = max(longest, fm.horizontalAdvance(combo.itemText(i)))
            w = int(longest + padding)
            w = max(min_width, min(max_width, w))
            combo.setFixedWidth(w)
        except Exception:
            pass

    def _resize_table_columns_for_language(self, table: QTableWidget):
        if not table:
            return
        try:
            table.resizeColumnsToContents()
        except Exception:
            pass
        try:
            header = table.horizontalHeader()
            fm = QFontMetrics(header.font())
            for col in range(table.columnCount()):
                item = table.horizontalHeaderItem(col)
                txt = item.text() if item else ''
                if not txt:
                    continue
                min_w = int(fm.horizontalAdvance(txt) + 24)
                if table.columnWidth(col) < min_w:
                    table.setColumnWidth(col, min_w)
        except Exception:
            pass
        try:
            if table is getattr(self, 'table2', None):
                function_id = self.get_selected_function_id()
                if function_id == 3:
                    col = REMUX_LABELS.index('output_name')
                elif function_id == 4:
                    col = ENCODE_LABELS.index('output_name')
                else:
                    col = -1
                if col >= 0:
                    header = table.horizontalHeader()
                    header.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
                    fixed_limit = 160
                    fm_h = QFontMetrics(header.font())
                    header_item = table.horizontalHeaderItem(col)
                    max_w = fm_h.horizontalAdvance(header_item.text()) if header_item and header_item.text() else 0
                    fm_c = QFontMetrics(table.font())
                    for r in range(table.rowCount()):
                        it = table.item(r, col)
                        if it and it.text():
                            max_w = max(max_w, fm_c.horizontalAdvance(it.text()))
                    desired = min(fixed_limit, int(max_w + 24))
                    table.setColumnWidth(col, max(60, desired))
            elif table is getattr(self, 'table3', None):
                col = ENCODE_SP_LABELS.index('output_name')
                header = table.horizontalHeader()
                header.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
                fixed_limit = 160
                fm_h = QFontMetrics(header.font())
                header_item = table.horizontalHeaderItem(col)
                max_w = fm_h.horizontalAdvance(header_item.text()) if header_item and header_item.text() else 0
                fm_c = QFontMetrics(table.font())
                for r in range(table.rowCount()):
                    it = table.item(r, col)
                    if it and it.text():
                        max_w = max(max_w, fm_c.horizontalAdvance(it.text()))
                desired = min(fixed_limit, int(max_w + 24))
                table.setColumnWidth(col, max(60, desired))
        except Exception:
            pass

    def _refresh_language_dependent_sizes(self):
        lang = getattr(self, '_language_code', CURRENT_UI_LANGUAGE)
        try:
            if hasattr(self, 'table1') and self.table1:
                self.table1.setColumnWidth(2, 420 if lang == 'zh' else 370)
                for r in range(self.table1.rowCount()):
                    info_table = self.table1.cellWidget(r, 2)
                    if isinstance(info_table, QTableWidget):
                        info_table.resizeColumnsToContents()
        except Exception:
            pass

        try:
            if hasattr(self, 'x265_preset_combo') and self.x265_preset_combo:
                self._adjust_combo_width_to_contents(self.x265_preset_combo)
        except Exception:
            pass

        try:
            if hasattr(self, 'approx_episode_minutes_combo') and self.approx_episode_minutes_combo:
                self._adjust_combo_width_to_contents(self.approx_episode_minutes_combo, padding=54, min_width=120, max_width=220)
        except Exception:
            pass

        try:
            if hasattr(self, 'table2') and self.table2:
                self._resize_table_columns_for_language(self.table2)
        except Exception:
            pass

        try:
            if hasattr(self, 'table3') and self.table3:
                self._resize_table_columns_for_language(self.table3)
        except Exception:
            pass

        try:
            if hasattr(self, 'table1') and self.table1:
                for r in range(self.table1.rowCount()):
                    info_table = self.table1.cellWidget(r, 2)
                    if isinstance(info_table, QTableWidget):
                        self._resize_table_columns_for_language(info_table)
        except Exception:
            pass

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

    def _normalize_path_input(self, text: str) -> str:
        s = str(text or '').strip()
        if not s:
            return ''
        if s.startswith('file://'):
            try:
                parsed = urlparse(s)
                path = unquote(parsed.path or '')
                if sys.platform == 'win32' and re.match(r'^/[A-Za-z]:/', path):
                    path = path[1:]
                s = path or s
            except Exception:
                pass
        return os.path.normpath(os.path.expanduser(s))

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

    def _set_compact_table(self, table: QTableWidget, row_height: int = 22, header_height: int = 22):
        table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        table.verticalHeader().setDefaultSectionSize(row_height)
        table.verticalHeader().setMinimumSectionSize(row_height)
        table.horizontalHeader().setFixedHeight(header_height)

    def _scroll_table_h_to_right(self, table: QTableWidget):
        def scroll():
            bar = table.horizontalScrollBar()
            bar.setValue(bar.maximum())
        # Execute multiple times to ensure it works in slower environments like Docker
        QTimer.singleShot(0, scroll)
        QTimer.singleShot(50, scroll)
        QTimer.singleShot(100, scroll)
        QTimer.singleShot(200, scroll)

    def _update_exe_button_progress(self, value: Optional[int] = None, text: Optional[str] = None):
        if not hasattr(self, 'exe_button') or not self.exe_button:
            return
        if not hasattr(self, '_exe_button_default_text'):
            self._exe_button_default_text = self.exe_button.text()
        if value is not None:
            self._exe_button_progress_value = int(value)
        if text is not None:
            self._exe_button_progress_text = self.t(str(text))

        v = int(getattr(self, '_exe_button_progress_value', 0))
        t = str(getattr(self, '_exe_button_progress_text', '')).strip()
        ratio = max(0.0, min(1.0, v / 1000.0))
        stop1 = f"{ratio:.3f}"
        stop2 = f"{min(1.0, ratio + 0.001):.3f}"
        percent = ratio * 100

        cancel_suffix = self.t("（点击取消）") if getattr(self, '_current_cancel_event', None) is not None and t != self.t('正在取消...') else ""
        if t:
            self.exe_button.setText(f"{t}{cancel_suffix} {percent:.1f}%")
        else:
            self.exe_button.setText(f"{percent:.1f}%")
        self.exe_button.setStyleSheet(
            "QPushButton{"
            f"background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #AAAAAA,stop:{stop1} #AAAAAA,stop:{stop2} #CCCCCC,stop:1 #CCCCCC);"
            "color:white;border:none;border-radius:5px;padding:2px 6px;"
            "}"
            "QPushButton:disabled{color:white;}"
        )

    def _on_exe_button_progress_value(self, value: int):
        self._update_exe_button_progress(value=value)

    def _on_exe_button_progress_text(self, text: str):
        self._update_exe_button_progress(text=self.t(text))

    def _reset_exe_button(self):
        if not hasattr(self, 'exe_button') or not self.exe_button:
            return
        default_text = getattr(self, '_exe_button_default_text', None)
        if default_text:
            self.exe_button.setText(default_text)
        self.exe_button.setStyleSheet('')
        self.exe_button.setEnabled(True)

    def _show_bottom_message(self, text: str, duration_ms: int = 10000):
        if not hasattr(self, 'bottom_message_label') or not self.bottom_message_label:
            return
            
        self._bottom_message_text = self.t(text)
        self._bottom_message_remaining = duration_ms // 1000
        
        self.bottom_message_label.setText(f"{self._bottom_message_text} ({self._bottom_message_remaining}s)")
        self.bottom_message_label.setVisible(True)
        
        if not hasattr(self, '_bottom_message_timer') or not self._bottom_message_timer:
            self._bottom_message_timer = QTimer(self)
            self._bottom_message_timer.setInterval(1000)
            
            def update_countdown():
                self._bottom_message_remaining -= 1
                if self._bottom_message_remaining <= 0:
                    self.bottom_message_label.setVisible(False)
                    self.bottom_message_label.setText('')
                    self._bottom_message_timer.stop()
                else:
                    self.bottom_message_label.setText(f"{self._bottom_message_text} ({self._bottom_message_remaining}s)")
                    
            self._bottom_message_timer.timeout.connect(update_countdown)
            
        self._bottom_message_timer.stop()
        self._bottom_message_timer.start()

    def _set_table_column_visual_order(self, table: QTableWidget, order: list[int]):
        header = table.horizontalHeader()
        for desired_visual_index, logical_index in enumerate(order):
            if logical_index < 0 or logical_index >= table.columnCount():
                continue
            current_visual_index = header.visualIndex(logical_index)
            if current_visual_index != desired_visual_index:
                header.moveSection(current_visual_index, desired_visual_index)

    def _set_table2_default_column_order(self):
        self._set_table_column_visual_order(self.table2, list(range(self.table2.columnCount())))

    def _set_table2_subtitle_column_order(self):
        if self.table2.columnCount() < 2:
            return
        order = list(range(self.table2.columnCount()))
        order[0], order[1] = order[1], order[0]
        self._set_table_column_visual_order(self.table2, order)

    def create_vpy_path_widget(self, initial_path: Optional[str] = None, parent: Optional[QWidget] = None) -> QWidget:
        widget = QWidget(parent or self.table2)
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        widget.setLayout(layout)

        line_edit = QLineEdit(widget)
        line_edit.setText(initial_path or self.get_default_vpy_path())

        button = QPushButton(self.t('选择'), widget)

        def select_file():
            start_dir = os.path.dirname(line_edit.text()) if line_edit.text() else os.getcwd()
            path, _ = QFileDialog.getOpenFileName(
                self,
                self.t("选择vpy文件"),
                start_dir,
                "Python/VapourSynth (*.py *.vpy)"
            )
            if path:
                line_edit.setText(os.path.normpath(path))

        button.clicked.connect(select_file)
        layout.addWidget(line_edit)
        layout.addWidget(button)
        return widget

    def create_language_combo(self, initial: str = 'chi') -> QComboBox:
        combo = QComboBox()
        combo.setEditable(True)
        combo.addItems(['chi', 'zho', 'jpn', 'eng', 'kor', 'und'])
        auto_lang = 'eng' if getattr(self, '_language_code', CURRENT_UI_LANGUAGE) != 'zh' else 'chi'
        combo.setCurrentText((initial or auto_lang).strip() or auto_lang)
        combo._auto_lang = auto_lang
        return combo

    def _refresh_language_column_defaults(self):
        function_id = self.get_selected_function_id()
        if function_id not in (3, 4) or not hasattr(self, 'table2') or not self.table2:
            return
        labels = ENCODE_LABELS if function_id == 4 else REMUX_LABELS
        try:
            lang_col = labels.index('language')
        except Exception:
            return
        auto_lang = 'eng' if getattr(self, '_language_code', CURRENT_UI_LANGUAGE) != 'zh' else 'chi'
        for r in range(self.table2.rowCount()):
            w = self.table2.cellWidget(r, lang_col)
            if not isinstance(w, QComboBox):
                continue
            prev_auto = str(getattr(w, '_auto_lang', auto_lang) or auto_lang)
            prev_text = w.currentText().strip()
            if (not prev_text) or (prev_text == prev_auto):
                w.setCurrentText(auto_lang)
            w._auto_lang = auto_lang
        self._update_language_combo_enabled_state()

    def _update_language_combo_enabled_state(self):
        function_id = self.get_selected_function_id()
        if function_id not in (3, 4) or not hasattr(self, 'table2') or not self.table2:
            return
        labels = ENCODE_LABELS if function_id == 4 else REMUX_LABELS
        try:
            sub_col = labels.index('sub_path')
            lang_col = labels.index('language')
        except Exception:
            return
        auto_lang = 'eng' if getattr(self, '_language_code', CURRENT_UI_LANGUAGE) != 'zh' else 'chi'
        for r in range(self.table2.rowCount()):
            sub_item = self.table2.item(r, sub_col)
            has_sub = bool(sub_item and sub_item.text() and sub_item.text().strip())
            w = self.table2.cellWidget(r, lang_col)
            if isinstance(w, QComboBox):
                w.setEnabled(has_sub)
                if not has_sub:
                    w.setCurrentText(auto_lang)
                    w._auto_lang = auto_lang

    def get_vpy_path_from_row(self, row_index: int) -> str:
        if self.get_selected_function_id() != 4:
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

    def open_vpy_in_vsedit(self, path: str) -> Optional[QProcess]:
        path = str(path or '').strip()
        if not path:
            QMessageBox.information(self, "提示", "vpy路径为空")
            return None
        if not os.path.exists(path):
            QMessageBox.information(self, "提示", f"文件不存在：{path}")
            return None

        vsedit_exe = VSEDIT_PATH
        if not vsedit_exe or not os.path.exists(vsedit_exe):
            vsedit_exe = shutil.which('vsedit') or ''
        if not vsedit_exe:
            QMessageBox.information(self, "提示", "未找到 vsedit，请检查 VSEDIT_PATH 或系统 PATH")
            return None

        try:
            proc = QProcess(self)
            proc.setProgram(vsedit_exe)
            proc.setArguments([os.path.normpath(path)])
            proc.start()
            if not proc.waitForStarted(2000):
                QMessageBox.warning(self, "提示", "启动 vsedit 失败")
                try:
                    proc.kill()
                except Exception:
                    pass
                proc.deleteLater()
                return None
            return proc
        except Exception as e:
            QMessageBox.warning(self, "提示", f"打开 vsedit 失败：{e}")
            return None

    def _restore_default_vpy_after_preview(self, mapping: dict[str, tuple[str, str]]):
        try:
            vpy_path = self.get_default_vpy_path()
            if not os.path.exists(vpy_path):
                return
            with open(vpy_path, 'r', encoding='utf-8') as fp:
                lines = fp.readlines()

            def norm(s: str) -> str:
                return s.rstrip('\r\n')

            restore_by_modified = {norm(mod): orig for orig, mod in mapping.values() if orig is not None and mod is not None}

            changed = False
            for idx, line in enumerate(lines):
                key = norm(line)
                if key in restore_by_modified:
                    lines[idx] = restore_by_modified[key] + '\n'
                    changed = True

            if changed:
                with open(vpy_path, 'w', encoding='utf-8') as fp:
                    fp.writelines(lines)
        except Exception:
            pass

    def _split_m2ts_files(self, text: str) -> list[str]:
        if not text:
            return []
        parts = re.split(r'[,\n;]+', str(text))
        return [p.strip() for p in parts if p and p.strip()]

    def _get_stream_dir_for_bdmv_index(self, bdmv_index: int) -> str:
        root = ''
        try:
            idx = int(bdmv_index)
        except Exception:
            idx = -1
        if idx < 0:
            return ''

        try:
            root_item = self.table1.item(idx, 0)
            root = root_item.text().strip() if root_item else ''
        except Exception:
            root = ''

        if not root and idx > 0:
            try:
                root_item = self.table1.item(idx - 1, 0)
                root = root_item.text().strip() if root_item else ''
            except Exception:
                root = ''
        if not root:
            return ''
        return os.path.normpath(os.path.join(root, 'BDMV', 'STREAM'))

    def _select_video_path(self, bdmv_index: int, m2ts_files: list[str]) -> str:
        if not m2ts_files:
            return ''
        stream_dir = self._get_stream_dir_for_bdmv_index(bdmv_index)
        if not stream_dir:
            return ''

        if len(m2ts_files) == 1:
            return os.path.normpath(os.path.join(stream_dir, m2ts_files[0]))

        item, ok = QInputDialog.getItem(
            self,
            self.t("选择m2ts文件"),
            self.t("检测到多个 m2ts 文件，请选择要预览的文件："),
            m2ts_files,
            0,
            False
        )
        if not ok or not item:
            return ''
        return os.path.normpath(os.path.join(stream_dir, str(item)))

    def _get_first_subtitle_path_for_bdmv_index(self, bdmv_index: int) -> str:
        if self.get_selected_function_id() != 4:
            return ''
        try:
            bdmv_col = ENCODE_LABELS.index('bdmv_index')
        except Exception:
            bdmv_col = 2
        for r in range(self.table2.rowCount()):
            item = self.table2.item(r, bdmv_col)
            if not item or not item.text().strip():
                continue
            try:
                if int(item.text().strip()) != int(bdmv_index):
                    continue
            except Exception:
                continue
            sub_item = self.table2.item(r, 0)
            if sub_item and sub_item.text().strip():
                return sub_item.text().strip()
        return ''

    def _vpy_raw_string(self, path: str) -> str:
        s = str(path or '')
        s = s.replace('\\', '\\\\').replace('"', '\\"')
        return f'r"{s}"'

    def _update_default_vpy_paths(self, video_path: str, subtitle_path: str) -> dict[str, tuple[str, str]]:
        self.ensure_default_vpy_file()
        vpy_path = self.get_default_vpy_path()
        if not os.path.exists(vpy_path):
            raise FileNotFoundError(vpy_path)

        with open(vpy_path, 'r', encoding='utf-8') as fp:
            lines = fp.readlines()

        def norm(s: str) -> str:
            return s.rstrip('\r\n')

        mapping: dict[str, tuple[str, str]] = {}
        changed = False
        for idx, line in enumerate(lines):
            raw = norm(line)
            m_a = re.match(r'^(\s*)(#\s*)?(a\s*=\s*)r?[\'"].*?[\'"](\s*(#.*)?)$', raw)
            if m_a:
                indent = m_a.group(1)
                expr = m_a.group(3)
                suffix = m_a.group(4) or ''
                new_raw = f'{indent}{expr}{self._vpy_raw_string(video_path)}{suffix}'
                if new_raw != raw:
                    lines[idx] = new_raw + '\n'
                    changed = True
                mapping['a'] = (raw, new_raw)
                continue

            m_s = re.match(r'^(\s*)(#\s*)?(sub_file\s*=\s*)r?[\'"].*?[\'"](\s*(#.*)?)$', raw)
            if m_s:
                indent = m_s.group(1)
                expr = m_s.group(3)
                suffix = m_s.group(4) or ''
                want_commented = not bool(subtitle_path)
                comment_prefix = '# ' if want_commented else ''
                rhs = self._vpy_raw_string(subtitle_path or '')
                new_raw = f'{indent}{comment_prefix}{expr}{rhs}{suffix}'
                if new_raw != raw:
                    lines[idx] = new_raw + '\n'
                    changed = True
                mapping['sub_file'] = (raw, new_raw)
                continue

            m_t = re.match(r'^(\s*)(#\s*)?(res\s*=\s*core\.assrender\.TextSub\(\s*res\s*,\s*file\s*=\s*sub_file\s*\))(\s*(#.*)?)$', raw)
            if m_t:
                indent = m_t.group(1)
                expr = m_t.group(3)
                suffix = m_t.group(4) or ''
                want_commented = not bool(subtitle_path)
                comment_prefix = '# ' if want_commented else ''
                new_raw = f'{indent}{comment_prefix}{expr}{suffix}'
                if new_raw != raw:
                    lines[idx] = new_raw + '\n'
                    changed = True
                mapping['textsub'] = (raw, new_raw)
                continue

        if changed:
            with open(vpy_path, 'w', encoding='utf-8') as fp:
                fp.writelines(lines)
        return mapping

    def _create_temp_preview_vpy_from_default(self, video_path: str, subtitle_path: str) -> str:
        self.ensure_default_vpy_file()
        default_vpy = self.get_default_vpy_path()
        if not os.path.exists(default_vpy):
            return ''
        try:
            with open(default_vpy, 'r', encoding='utf-8') as fp:
                lines = fp.readlines()

            out: list[str] = []
            for line in lines:
                raw = line.rstrip('\r\n')

                if not raw.lstrip().startswith('#'):
                    m_a = re.match(r'^(\s*a\s*=\s*)r?[\'"].*?[\'"](\s*(#.*)?)$', raw)
                    if m_a:
                        out.append(f'{m_a.group(1)}{self._vpy_raw_string(video_path)}{m_a.group(2)}\n')
                        continue

                m_s = re.match(r'^(\s*)(#\s*)?(sub_file\s*=\s*)r?[\'"].*?[\'"](\s*(#.*)?)$', raw)
                if m_s:
                    indent = m_s.group(1)
                    expr = m_s.group(3)
                    suffix = m_s.group(4) or ''
                    comment = '' if subtitle_path else '# '
                    out.append(f'{indent}{comment}{expr}{self._vpy_raw_string(subtitle_path or "")}{suffix}\n')
                    continue

                m_t = re.match(r'^(\s*)(#\s*)?(res\s*=\s*core\.assrender\.TextSub\(\s*res\s*,\s*file\s*=\s*sub_file\s*\))(\s*(#.*)?)$', raw)
                if m_t:
                    indent = m_t.group(1)
                    expr = m_t.group(3)
                    suffix = m_t.group(4) or ''
                    comment = '' if subtitle_path else '# '
                    out.append(f'{indent}{comment}{expr}{suffix}\n')
                    continue

                if raw.strip() == 'dbed = mvf.LimitFilter(dbed, nr16, thr=0.55, elast=1.5, planes=[0, 1, 2])':
                    out.extend([
                        'try:\n',
                        '    dbed = mvf.LimitFilter(dbed, nr16, thr=0.55, elast=1.5, planes=[0, 1, 2])\n',
                        'except Exception:\n',
                        '    dbed = nr16\n',
                    ])
                    continue

                if raw.strip() == 'mergedY = mvf.LimitFilter(dbedY, aaedY, thr=1.0, elast=1.5)':
                    out.extend([
                        'try:\n',
                        '    mergedY = mvf.LimitFilter(dbedY, aaedY, thr=1.0, elast=1.5)\n',
                        'except Exception:\n',
                        '    mergedY = aaedY\n',
                    ])
                    continue

                out.append(line if line.endswith('\n') else line + '\n')

            fd, temp_vpy = tempfile.mkstemp(prefix='bluraysubtitle_preview_', suffix='.vpy')
            os.close(fd)
            with open(temp_vpy, 'w', encoding='utf-8') as fp:
                fp.writelines(out)
            return temp_vpy
        except Exception:
            traceback.print_exc()
            return ''

    def _preview_script_for_row(self, vpy_path: str, video_path: str, subtitle_path: str):
        if not video_path:
            QMessageBox.information(self, "提示", "无法确定视频文件路径")
            return

        vpy_path = (vpy_path or '').strip()
        default_vpy = self.get_default_vpy_path()
        is_default = False
        if vpy_path:
            try:
                is_default = os.path.normcase(os.path.abspath(os.path.normpath(vpy_path))) == os.path.normcase(os.path.abspath(os.path.normpath(default_vpy)))
            except Exception:
                is_default = False
        else:
            is_default = True
            vpy_path = default_vpy

        try:
            if is_default:
                if sys.platform != 'win32':
                    temp_vpy = self._create_temp_preview_vpy_from_default(video_path=video_path, subtitle_path=subtitle_path or '')
                    if not temp_vpy:
                        QMessageBox.warning(self, "提示", "生成预览脚本失败")
                        return
                    proc = self.open_vpy_in_vsedit(temp_vpy)
                    if not proc:
                        try:
                            os.remove(temp_vpy)
                        except Exception:
                            pass
                        return

                    def cleanup_temp_vpy(*_):
                        try:
                            os.remove(temp_vpy)
                        except Exception:
                            pass
                        try:
                            proc.deleteLater()
                        except Exception:
                            pass

                    proc.finished.connect(cleanup_temp_vpy)
                    proc.errorOccurred.connect(cleanup_temp_vpy)
                    return

                mapping = self._update_default_vpy_paths(video_path=video_path, subtitle_path=subtitle_path or '')

                proc = self.open_vpy_in_vsedit(default_vpy)
                if not proc:
                    self._restore_default_vpy_after_preview(mapping=mapping)
                    return

                if not hasattr(self, '_vsedit_preview_sessions'):
                    self._vsedit_preview_sessions = {}
                self._vsedit_preview_sessions[proc] = mapping

                def restore_and_cleanup(*_):
                    try:
                        sess = self._vsedit_preview_sessions.pop(proc, None)
                    except Exception:
                        sess = None
                    if not sess:
                        return
                    self._restore_default_vpy_after_preview(mapping=sess)
                    try:
                        proc.deleteLater()
                    except Exception:
                        pass

                proc.finished.connect(restore_and_cleanup)
                proc.errorOccurred.connect(restore_and_cleanup)
            else:
                self.open_vpy_in_vsedit(vpy_path)
        except Exception as e:
            QMessageBox.warning(self, "提示", f"预览脚本失败：{e}")

    def on_edit_vpy_clicked(self):
        if self.get_selected_function_id() != 4:
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

    def on_preview_script_clicked(self):
        if self.get_selected_function_id() != 4:
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

        try:
            bdmv_col = ENCODE_LABELS.index('bdmv_index')
            m2ts_col = ENCODE_LABELS.index('m2ts_file')
        except Exception:
            bdmv_col, m2ts_col = 2, 4

        bdmv_item = self.table2.item(row_index, bdmv_col)
        m2ts_item = self.table2.item(row_index, m2ts_col)
        sub_item = self.table2.item(row_index, 0)

        try:
            bdmv_index = int(bdmv_item.text().strip()) if bdmv_item and bdmv_item.text().strip() else -1
        except Exception:
            bdmv_index = -1

        m2ts_files = self._split_m2ts_files(m2ts_item.text() if m2ts_item else '')
        video_path = self._select_video_path(bdmv_index, m2ts_files)
        should_load_subtitle = False
        try:
            should_load_subtitle = bool(getattr(self, 'sub_pack_hard_radio', None) and self.sub_pack_hard_radio.isChecked())
        except Exception:
            should_load_subtitle = False
        subtitle_path = sub_item.text().strip() if should_load_subtitle and sub_item and sub_item.text().strip() else ''

        vpy_path = self.get_vpy_path_from_row(row_index)
        self._preview_script_for_row(vpy_path=vpy_path, video_path=video_path, subtitle_path=subtitle_path)

    def ensure_encode_row_widgets(self, row_index: int):
        if self.get_selected_function_id() != 4:
            return
        vpy_col = ENCODE_LABELS.index('vpy_path')
        edit_col = ENCODE_LABELS.index('edit_vpy')
        preview_col = ENCODE_LABELS.index('preview_script')

        if not self.table2.cellWidget(row_index, vpy_col):
            self.table2.setCellWidget(row_index, vpy_col, self.create_vpy_path_widget(parent=self.table2))

        if not self.table2.cellWidget(row_index, edit_col):
            btn = QToolButton(self.table2)
            btn.setText(self.t('edit'))
            btn.clicked.connect(self.on_edit_vpy_clicked)
            self.table2.setCellWidget(row_index, edit_col, btn)

        if not self.table2.cellWidget(row_index, preview_col):
            btn = QToolButton(self.table2)
            btn.setText(self.t('preview'))
            btn.clicked.connect(self.on_preview_script_clicked)
            self.table2.setCellWidget(row_index, preview_col, btn)

    def get_sp_vpy_path_from_row(self, row_index: int) -> str:
        if self.get_selected_function_id() != 4:
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
        if self.get_selected_function_id() != 4:
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

    def on_preview_sp_scripts_clicked(self):
        if self.get_selected_function_id() != 4:
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

        try:
            bdmv_col = ENCODE_SP_LABELS.index('bdmv_index')
            m2ts_col = ENCODE_SP_LABELS.index('m2ts_file')
        except Exception:
            bdmv_col, m2ts_col = 0, 2

        bdmv_item = self.table3.item(row_index, bdmv_col)
        m2ts_item = self.table3.item(row_index, m2ts_col)
        try:
            bdmv_index = int(bdmv_item.text().strip()) if bdmv_item and bdmv_item.text().strip() else -1
        except Exception:
            bdmv_index = -1

        m2ts_files = self._split_m2ts_files(m2ts_item.text() if m2ts_item else '')
        video_path = self._select_video_path(bdmv_index, m2ts_files)
        subtitle_path = ''

        vpy_path = self.get_sp_vpy_path_from_row(row_index)
        self._preview_script_for_row(vpy_path=vpy_path, video_path=video_path, subtitle_path=subtitle_path)

    def _resolve_output_name_from_mpls(self, mpls_no_ext: str) -> str:
        mpls_path = mpls_no_ext + '.mpls'
        meta_folder = os.path.join(os.path.join(mpls_path[:-19], 'META', 'DL'))
        output_name = ''
        if not os.path.exists(meta_folder):
            output_name = os.path.split(mpls_path[:-24])[-1]
        else:
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
            '?': '？', '*': '★', '<': '《', '>': '》', ':': '：', '"': "'", '/': '／', '\\': '／', '|': '￨'
        }
        return ''.join(char_map.get(char) or char for char in output_name)

    def _build_episode_output_name_map(self, configuration: dict[int, dict[str, int | str]]) -> dict[int, str]:
        if not configuration:
            return {}
        total = len(configuration)
        width = len(str(total))
        by_bdmv: dict[int, list[int]] = {}
        for sub_index, con in configuration.items():
            try:
                bdmv_index = int(con.get('bdmv_index') or 0)
            except Exception:
                bdmv_index = 0
            by_bdmv.setdefault(bdmv_index, []).append(sub_index)
        for bdmv_index in by_bdmv:
            by_bdmv[bdmv_index].sort(key=lambda i: int(configuration[i].get('chapter_index') or 0))

        result: dict[int, str] = {}
        for sub_index in sorted(configuration.keys()):
            con = configuration[sub_index]
            try:
                bdmv_index = int(con.get('bdmv_index') or 0)
            except Exception:
                bdmv_index = 0
            bdmv_vol = f'{bdmv_index:03d}'
            rows_in_vol = by_bdmv.get(bdmv_index, [])
            try:
                seq_in_vol = rows_in_vol.index(sub_index) + 1
            except Exception:
                seq_in_vol = 1
            output_name = str(con.get('disc_output_name') or '').strip()
            if not output_name:
                output_name = self._resolve_output_name_from_mpls(str(con.get('selected_mpls') or ''))
            ep_no = f'EP{str(sub_index + 1).zfill(width)}'
            result[sub_index] = f'{ep_no} {output_name}_BD_Vol_{bdmv_vol}-{seq_in_vol:03d}.mkv'
        return result

    def _get_episode_output_names_from_table2(self) -> list[str]:
        names: list[str] = []
        function_id = self.get_selected_function_id()
        if function_id == 3:
            col = REMUX_LABELS.index('output_name')
        elif function_id == 4:
            col = ENCODE_LABELS.index('output_name')
        else:
            return names
        for i in range(self.table2.rowCount()):
            item = self.table2.item(i, col)
            names.append(item.text().strip() if item and item.text() else '')
        return names

    def _get_episode_subtitle_languages_from_table2(self) -> list[str]:
        langs: list[str] = []
        function_id = self.get_selected_function_id()
        if function_id == 3:
            col = REMUX_LABELS.index('language')
        elif function_id == 4:
            col = ENCODE_LABELS.index('language')
        else:
            return langs
        default_lang = 'eng' if getattr(self, '_language_code', CURRENT_UI_LANGUAGE) != 'zh' else 'chi'
        for i in range(self.table2.rowCount()):
            w = self.table2.cellWidget(i, col)
            if isinstance(w, QComboBox):
                v = w.currentText().strip()
            else:
                it = self.table2.item(i, col)
                v = it.text().strip() if it and it.text() else ''
            langs.append(v or default_lang)
        return langs

    def refresh_sp_table(self, configuration: dict[int, dict[str, int | str]]):
        function_id = self.get_selected_function_id()
        if function_id not in (3, 4) or not configuration:
            if hasattr(self, 'table3'):
                self.table3.setRowCount(0)
            return
        try:
            bdmv_index_conf: dict[int, list[dict[str, int | str]]] = {}
            for _, conf in configuration.items():
                bdmv_index_conf.setdefault(int(conf['bdmv_index']), []).append(conf)

            entries: list[tuple[int, str, list[str], int, str]] = []
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
                main_m2ts_files = set(index_to_m2ts.values())
                parsed_m2ts_files = set(main_m2ts_files)
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
                    m2ts_set = set(idx_to_m2ts.values())
                    if m2ts_set.issubset(main_m2ts_files):
                        continue
                    if len(idx_to_m2ts) > 1 and not m2ts_set.issubset(parsed_m2ts_files):
                        entries.append((
                            bdmv_index,
                            os.path.basename(mpls_file_path),
                            sorted(list(m2ts_set)),
                            ch.get_total_time(),
                            ''
                        ))
                        parsed_m2ts_files |= m2ts_set

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
                        entries.append((bdmv_index, '', [stream_file], dur, ''))

            sp_counts: dict[int, int] = {}
            for i, (bdmv_index, mpls_file, m2ts_files, dur, _) in enumerate(entries):
                bdmv_vol = f'{bdmv_index:03d}'
                if mpls_file:
                    sp_counts[bdmv_index] = sp_counts.get(bdmv_index, 0) + 1
                    out_name = f'BD_Vol_{bdmv_vol}_SP{sp_counts[bdmv_index]:02d}.mkv'
                else:
                    stream_index = os.path.splitext(m2ts_files[0])[0] if m2ts_files else '00000'
                    out_name = f'BD_Vol_{bdmv_vol}_{stream_index}.mkv'
                entries[i] = (bdmv_index, mpls_file, m2ts_files, dur, out_name)

            old_sorting = self.table3.isSortingEnabled()
            self.table3.setSortingEnabled(False)
            try:
                old_name_map: dict[tuple[int, str, str], tuple[str, Optional[str]]] = {}
                out_col = ENCODE_SP_LABELS.index('output_name')
                for r in range(self.table3.rowCount()):
                    bdmv_item = self.table3.item(r, 0)
                    mpls_item = self.table3.item(r, 1)
                    m2ts_item = self.table3.item(r, 2)
                    out_item = self.table3.item(r, out_col)
                    if bdmv_item and out_item and out_item.text():
                        key = (int(bdmv_item.text() or 0), mpls_item.text() if mpls_item else '', m2ts_item.text() if m2ts_item else '')
                        old_name_map[key] = (out_item.text().strip(), out_item.data(Qt.ItemDataRole.UserRole) if out_item else None)

                self.table3.setRowCount(len(entries))
                for i, (bdmv_index, mpls_file, m2ts_files, dur, auto_out_name) in enumerate(entries):
                    self.table3.setItem(i, 0, QTableWidgetItem(str(bdmv_index)))
                    self.table3.setItem(i, 1, QTableWidgetItem(mpls_file))
                    self.table3.setItem(i, 2, QTableWidgetItem(','.join(m2ts_files)))
                    self.table3.setItem(i, 3, QTableWidgetItem(get_time_str(dur)))
                    key = (bdmv_index, mpls_file, ','.join(m2ts_files))
                    prev = old_name_map.get(key)
                    prev_text = prev[0] if prev else ''
                    prev_auto = prev[1] if prev else None
                    if prev_text and isinstance(prev_auto, str) and prev_text != prev_auto:
                        final_text = prev_text
                    else:
                        final_text = auto_out_name
                    out_item = QTableWidgetItem(final_text)
                    out_item.setData(Qt.ItemDataRole.UserRole, auto_out_name)
                    self.table3.setItem(i, out_col, out_item)
                    if function_id == 4:
                        vpy_col = ENCODE_SP_LABELS.index('vpy_path')
                        edit_col = ENCODE_SP_LABELS.index('edit_vpy')
                        preview_col = ENCODE_SP_LABELS.index('preview_script')
                        self.table3.setCellWidget(i, vpy_col, self.create_vpy_path_widget(parent=self.table3))
                        btn = QToolButton(self.table3)
                        btn.setText(self.t('edit'))
                        btn.clicked.connect(self.on_edit_sp_vpy_clicked)
                        self.table3.setCellWidget(i, edit_col, btn)
                        btn2 = QToolButton(self.table3)
                        btn2.setText(self.t('preview'))
                        btn2.clicked.connect(self.on_preview_sp_scripts_clicked)
                        self.table3.setCellWidget(i, preview_col, btn2)
                    else:
                        for col in range(5, len(ENCODE_SP_LABELS)):
                            self.table3.setItem(i, col, None)
                            self.table3.setCellWidget(i, col, None)
                self.table3.resizeColumnsToContents()
                self._resize_table_columns_for_language(self.table3)
                self._scroll_table_h_to_right(self.table3)
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
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.encode_box.setLayout(layout)

        tools_row = QWidget(self.encode_box)
        tools_layout = QHBoxLayout()
        tools_layout.setContentsMargins(0, 0, 0, 0)
        tools_layout.setSpacing(4)
        tools_row.setLayout(tools_layout)

        tools_layout.addWidget(QLabel('vspipe：', tools_row))
        self.vspipe_mode_combo = QComboBox(tools_row)
        self.vspipe_mode_combo.addItems(['程序自带', '系统'])
        tools_layout.addWidget(self.vspipe_mode_combo)

        tools_layout.addWidget(QLabel('x265：', tools_row))
        self.x265_mode_combo = QComboBox(tools_row)
        self.x265_mode_combo.addItems(['程序自带', '系统'])
        tools_layout.addWidget(self.x265_mode_combo)

        is_pyinstaller_bundle = bool(getattr(sys, 'frozen', False)) and hasattr(sys, '_MEIPASS')
        if not is_pyinstaller_bundle:
            self.vspipe_mode_combo.setCurrentText('系统')
            self.vspipe_mode_combo.setEnabled(False)
            self.x265_mode_combo.setCurrentText('系统')
            self.x265_mode_combo.setEnabled(False)
        elif is_docker():
            self.vspipe_mode_combo.setCurrentText('系统')
            self.x265_mode_combo.setCurrentText('系统')

        tools_layout.addWidget(QLabel('x265参数：', tools_row))
        self.x265_preset_combo = QComboBox(tools_row)
        self.x265_preset_combo.addItems(list(self._encode_preset_params.keys()))
        self.x265_preset_combo.setCurrentText('均衡')
        self._adjust_combo_width_to_contents(self.x265_preset_combo)
        tools_layout.addWidget(self.x265_preset_combo)

        tools_layout.addStretch(1)
        layout.addWidget(tools_row)

        self.x265_params_edit = QPlainTextEdit(self.encode_box)
        self.x265_params_edit.setFixedHeight(46)
        self.x265_params_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
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
        sub_pack_layout.setSpacing(4)
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
            if self.get_selected_function_id() != 4:
                return
            if not self.subtitle_folder_path.text().strip():
                return
            self.set_vpy_hardsub_enabled(self.sub_pack_hard_radio.isChecked())

        self.sub_pack_external_radio.toggled.connect(on_sub_pack_changed)
        self.sub_pack_soft_radio.toggled.connect(on_sub_pack_changed)
        self.sub_pack_hard_radio.toggled.connect(on_sub_pack_changed)

        def update_sub_pack_enabled_state():
            enabled = self.get_selected_function_id() == 4 and bool(self.subtitle_folder_path.text().strip())
            self._sub_pack_row.setEnabled(enabled)
            if not enabled:
                self.sub_pack_external_radio.setChecked(True)
                self.set_vpy_hardsub_enabled(False)

        self.subtitle_folder_path.textChanged.connect(lambda _=None: update_sub_pack_enabled_state())
        update_sub_pack_enabled_state()

    def init_ui(self):
        self.setWindowTitle(APP_TITLE)
        self.setMinimumWidth(860)
        self.setMinimumHeight(820)
        self.resize(1000, 1000)
        self._geometry = self.saveGeometry()
        self._language_code = 'en'
        global CURRENT_UI_LANGUAGE
        CURRENT_UI_LANGUAGE = 'en'

        app = QApplication.instance()
        if app:
            app.aboutToQuit.connect(self.delete_default_vpy_file)

        self.layout = QVBoxLayout()
        self.layout.setContentsMargins(8, 8, 8, 8)
        self.layout.setSpacing(6)

        language_row = QWidget(self)
        language_layout = QHBoxLayout()
        language_layout.setContentsMargins(8, 0, 8, 0)
        language_layout.setSpacing(6)
        language_row.setLayout(language_layout)
        self.language_label = QLabel('语言', language_row)
        self.language_combo = QComboBox(language_row)
        self.language_combo.addItem('English', 'en')
        self.language_combo.addItem('简体中文', 'zh')
        self.language_combo.setCurrentIndex(0)
        self.language_combo.currentIndexChanged.connect(lambda _=None: self._on_language_changed())
        language_layout.addWidget(self.language_label)
        language_layout.addWidget(self.language_combo)
        language_layout.addStretch(1)
        self.layout.addWidget(language_row)

        function_button = QGroupBox(self.t('选择功能'), self)
        self.function_button = function_button
        h_layout = QHBoxLayout()
        h_layout.setContentsMargins(8, 10, 8, 6)
        h_layout.setSpacing(12)
        function_button.setLayout(h_layout)
        self.subtitle_folder_path = QLineEdit()
        self.subtitle_folder_path.setMinimumWidth(200)

        self.function_tabbar = QTabBar(function_button)
        self.function_tabbar.setExpanding(True)
        self.function_tabbar.setMovable(False)
        self.function_tabbar.setDocumentMode(True)
        self.function_tabbar.addTab(self.t("生成合并字幕"))
        self.function_tabbar.addTab(self.t("给mkv添加章节"))
        self.function_tabbar.addTab(self.t("原盘remux"))
        self.function_tabbar.addTab(self.t("原盘压制"))
        self.function_tabbar.setCurrentIndex(0)
        self._selected_function_id = 1
        self.function_tabbar.currentChanged.connect(lambda _=None: self.on_select_function())
        h_layout.addWidget(self.function_tabbar)
        self.layout.addWidget(function_button)

        mode_row = QWidget(self)
        mode_row.setProperty("noMargin", True)
        mode_layout = QHBoxLayout()
        mode_layout.setContentsMargins(8, 0, 8, 0)
        mode_layout.setSpacing(6)
        mode_row.setLayout(mode_layout)

        self.series_mode_radio = QRadioButton("剧集模式", mode_row)
        self.movie_mode_radio = QRadioButton("电影模式", mode_row)
        self.series_mode_radio.setChecked(True)

        mode_layout.addWidget(self.series_mode_radio)

        self.episode_length_container = QWidget(mode_row)
        episode_length_layout = QHBoxLayout()
        episode_length_layout.setContentsMargins(0, 0, 0, 0)
        episode_length_layout.setSpacing(4)
        self.episode_length_container.setLayout(episode_length_layout)
        episode_length_layout.addWidget(QLabel("（", self.episode_length_container))
        episode_length_layout.addWidget(QLabel("每集时长大约（分钟）：", self.episode_length_container))
        self.approx_episode_minutes_combo = QComboBox(self.episode_length_container)
        self.approx_episode_minutes_combo.setEditable(True)
        self.approx_episode_minutes_combo.addItems(["3", "24", "50"])
        self.approx_episode_minutes_combo.setCurrentText("24")
        self.approx_episode_minutes_combo.setMinimumWidth(120)
        self._adjust_combo_width_to_contents(self.approx_episode_minutes_combo, padding=54, min_width=120, max_width=220)
        episode_length_layout.addWidget(self.approx_episode_minutes_combo)
        episode_length_layout.addWidget(QLabel("）", self.episode_length_container))
        mode_layout.addWidget(self.episode_length_container)

        mode_layout.addSpacing(8)
        mode_layout.addWidget(self.movie_mode_radio)
        mode_layout.addStretch(1)

        mode_group = QButtonGroup(mode_row)
        mode_group.addButton(self.series_mode_radio)
        mode_group.addButton(self.movie_mode_radio)
        self._mode_group = mode_group

        def update_episode_length_enabled_state():
            enabled = self.series_mode_radio.isChecked()
            self.approx_episode_minutes_combo.setEnabled(enabled)
            self._apply_episode_mode_to_table2()

        self.series_mode_radio.toggled.connect(update_episode_length_enabled_state)
        self.movie_mode_radio.toggled.connect(update_episode_length_enabled_state)
        update_episode_length_enabled_state()

        self.episode_mode_row = mode_row
        self.episode_mode_row.setVisible(self.get_selected_function_id() in (1, 3, 4))
        self.approx_episode_minutes_combo.currentTextChanged.connect(lambda _=None: self._rebuild_configuration_for_function_34())
        self.layout.addWidget(self.episode_mode_row)

        bdmv = QGroupBox()
        bdmv.setProperty("noTitle", True)
        v_layout = QVBoxLayout()
        v_layout.setContentsMargins(8, 2, 8, 6)
        v_layout.setSpacing(4)
        bdmv.setLayout(v_layout)
        bluray_path_box = CustomBox('原盘', self)
        bluray_path_box.setProperty("noMargin", True)
        h_layout = QHBoxLayout()
        h_layout.setContentsMargins(0, 0, 0, 0)
        h_layout.setSpacing(4)
        bluray_path_box.setLayout(h_layout)
        self.label1 = QLabel("选择原盘所在的文件夹", self)
        self.bdmv_folder_path = QLineEdit()
        self.bdmv_folder_path.setMinimumWidth(200)
        self.bdmv_folder_path.setAcceptDrops(False)
        button1 = QPushButton("选择")
        button1.clicked.connect(self.select_bdmv_folder)
        button1_open = QPushButton("打开")
        button1_open.clicked.connect(lambda _=None: self.open_folder_path(self.bdmv_folder_path.text()))
        h_layout.addWidget(self.bdmv_folder_path)
        h_layout.addWidget(button1)
        h_layout.addWidget(button1_open)
        v_layout.addWidget(bluray_path_box)

        label1_container = QWidget(self)
        label1_layout = QVBoxLayout()
        label1_layout.setContentsMargins(0, 0, 0, 0)
        label1_layout.setSpacing(0)
        label1_container.setLayout(label1_layout)
        label1_layout.addWidget(self.label1)
        label1_layout.addWidget(bdmv)

        self.table1 = QTableWidget()
        self.table1.setColumnCount(len(BDMV_LABELS))
        self._set_table_headers(self.table1, BDMV_LABELS)
        self.table1.setSortingEnabled(True)
        self.table1.horizontalHeader().setSortIndicatorShown(True)
        self.bdmv_folder_path.textChanged.connect(self.on_bdmv_folder_path_change)
        v_layout.addWidget(self.table1)
        self.layout.addWidget(label1_container)

        subtitle = QGroupBox()
        subtitle.setProperty("noTitle", True)
        v_layout = QVBoxLayout()
        v_layout.setContentsMargins(8, 2, 8, 6)
        v_layout.setSpacing(4)
        subtitle.setLayout(v_layout)
        subtitle_path_box = CustomBox('字幕', self)
        subtitle_path_box.setProperty("noMargin", True)
        h_layout = QHBoxLayout()
        h_layout.setContentsMargins(0, 0, 0, 0)
        h_layout.setSpacing(4)
        subtitle_path_box.setLayout(h_layout)
        self.label2 = QLabel("选择单集字幕所在的文件夹：", self)
        self.subtitle_folder_path = QLineEdit()
        self.subtitle_folder_path.setMinimumWidth(200)
        self.subtitle_folder_path.setAcceptDrops(False)
        button2 = QPushButton("选择")
        button2.clicked.connect(self.select_subtitle_folder)
        button2_open = QPushButton("打开")
        button2_open.clicked.connect(lambda _=None: self.open_folder_path(self.subtitle_folder_path.text()))
        h_layout.addWidget(self.subtitle_folder_path)
        h_layout.addWidget(button2)
        h_layout.addWidget(button2_open)
        v_layout.addWidget(subtitle_path_box)

        label2_container = QWidget(self)
        label2_layout = QVBoxLayout()
        label2_layout.setContentsMargins(0, 0, 0, 0)
        label2_layout.setSpacing(0)
        label2_container.setLayout(label2_layout)
        label2_layout.addWidget(self.label2)
        label2_layout.addWidget(subtitle)

        self.table2 = CustomTableWidget(self, self.on_subtitle_drop)
        self._set_compact_table(self.table2, row_height=22, header_height=22)
        self.table2.setColumnCount(len(SUBTITLE_LABELS))
        self._set_table_headers(self.table2, SUBTITLE_LABELS)
        self._set_table2_subtitle_column_order()
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
        self._set_compact_table(self.table3, row_height=22, header_height=22)
        self.table3.setColumnCount(len(ENCODE_SP_LABELS))
        self._set_table_headers(self.table3, ENCODE_SP_LABELS)
        self.table3.setSortingEnabled(True)
        self.table3.horizontalHeader().setSortIndicatorShown(True)
        self.table3.setVisible(False)
        v_layout.addWidget(self.table3)
        self.layout.addWidget(label2_container)

        self.encode_box = QGroupBox('压制', self)
        self.encode_box.setProperty("tightGroup", True)
        self.encode_box.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.encode_box.setVisible(False)
        self.init_encode_box()
        self.layout.addWidget(self.encode_box)

        self.checkbox1 = QCheckBox("补全蓝光目录")
        self.checkbox1.setChecked(True)
        merge_options_row = QWidget(self)
        merge_options_row.setProperty("noMargin", True)
        merge_options_layout = QHBoxLayout()
        merge_options_layout.setContentsMargins(8, 0, 8, 0)
        merge_options_layout.setSpacing(6)
        merge_options_row.setLayout(merge_options_layout)
        merge_options_layout.addWidget(self.checkbox1)
        merge_options_layout.addSpacing(12)

        self.subtitle_suffix_label = QLabel("后缀", merge_options_row)
        merge_options_layout.addWidget(self.subtitle_suffix_label)
        self.subtitle_suffix_combo = QComboBox(merge_options_row)
        self.subtitle_suffix_combo.setEditable(True)
        self.subtitle_suffix_combo.setMinimumWidth(160)
        merge_options_layout.addWidget(self.subtitle_suffix_combo)
        merge_options_layout.addStretch(1)
        self.merge_options_row = merge_options_row
        self.merge_options_row.setVisible(self.get_selected_function_id() == 1)
        self._refresh_subtitle_suffix_options()
        self.layout.addWidget(self.merge_options_row)
        output_path_row = QWidget(self)
        output_path_row.setProperty("noMargin", True)
        output_path_layout = QHBoxLayout()
        output_path_layout.setContentsMargins(8, 0, 8, 0)
        output_path_layout.setSpacing(4)
        output_path_row.setLayout(output_path_layout)
        output_path_layout.addWidget(QLabel("输出文件夹", self))
        self.output_folder_path = QLineEdit()
        self.output_folder_path.setMinimumWidth(200)
        self.output_folder_path.setAcceptDrops(False)
        self._auto_output_folder = ''
        self.output_folder_path.textEdited.connect(lambda _: setattr(self, '_output_folder_user_edited', True))
        button_output = QPushButton("选择")
        button_output.clicked.connect(self.select_output_folder)
        button_output_open = QPushButton("打开")
        button_output_open.clicked.connect(lambda _=None: self.open_folder_path(self.output_folder_path.text()))
        output_path_layout.addWidget(self.output_folder_path)
        output_path_layout.addWidget(button_output)
        output_path_layout.addWidget(button_output_open)
        self.output_folder_row = output_path_row
        self.output_folder_row.setVisible(self.get_selected_function_id() in (3, 4))
        self.layout.addWidget(self.output_folder_row)
        self.exe_button = QPushButton("生成字幕")
        self.exe_button.clicked.connect(self.main)
        self.exe_button.setMinimumHeight(38)
        self.layout.addWidget(self.exe_button)
        self.bottom_message_label = QLabel('', self)
        self.bottom_message_label.setStyleSheet('color: #007BFF;')
        self.bottom_message_label.setVisible(False)
        self.layout.addWidget(self.bottom_message_label)

        self.setLayout(self.layout)
        self._apply_language('en')

    def on_bdmv_folder_path_change(self):
        raw = self.bdmv_folder_path.text()
        bdmv_path = self._normalize_path_input(raw)
        if raw.strip().startswith('file://') and bdmv_path and bdmv_path != raw.strip():
            try:
                self.bdmv_folder_path.blockSignals(True)
                self.bdmv_folder_path.setText(bdmv_path)
            finally:
                self.bdmv_folder_path.blockSignals(False)
        try:
            if hasattr(self, 'output_folder_path') and self.output_folder_path:
                auto_output = os.path.normpath(os.path.dirname(bdmv_path)) if bdmv_path else ''
                current_output = self.output_folder_path.text().strip()
                last_auto = getattr(self, '_auto_output_folder', '')
                if current_output == '' or current_output == last_auto:
                    self._auto_output_folder = auto_output
                    if auto_output:
                        self.output_folder_path.setText(auto_output)
                    else:
                        self.output_folder_path.clear()
        except Exception:
            pass
        table_ok = False
        if bdmv_path:
            try:
                self.table1.setColumnCount(len(BDMV_LABELS))
                self._set_table_headers(self.table1, BDMV_LABELS)
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
                        self._set_compact_table(table_widget, row_height=20, header_height=20)
                        table_widget.setColumnCount(5)
                        self._set_table_headers(table_widget, ['mpls_file', 'duration', 'chapters', 'main', 'play'])
                        mpls_files = sorted([f for f in os.listdir(os.path.join(root, 'BDMV', 'PLAYLIST')) if f.endswith('.mpls')])
                        table_widget.setRowCount(len(mpls_files))
                        mpls_n = 0
                        checked = False
                        if self.get_selected_function_id() == 1:
                            stream_dir = os.path.join(root, 'BDMV', 'STREAM')
                            if not os.path.isdir(stream_dir):
                                checked = True
                            else:
                                try:
                                    checked = not any(
                                        f.lower().endswith('.m2ts') for f in os.listdir(stream_dir)
                                    )
                                except Exception:
                                    checked = True
                        selected_mpls = os.path.normpath(BluraySubtitle(root).get_main_mpls(root, checked))
                        for mpls_file in mpls_files:
                                table_widget.setItem(mpls_n, 0, QTableWidgetItem(mpls_file))
                                mpls_path = os.path.normpath(os.path.join(root, 'BDMV', 'PLAYLIST', mpls_file))
                                total_time = Chapter(mpls_path).get_total_time()
                                total_time_str = get_time_str(total_time)
                                table_widget.setItem(mpls_n, 1, QTableWidgetItem(total_time_str))
                                btn1 = QToolButton()
                                btn1.setText(self.t('view chapters'))
                                btn1.clicked.connect(partial(self.on_button_click, mpls_path))
                                table_widget.setCellWidget(mpls_n, 2, btn1)
                                btn2 = QToolButton()
                                btn2.setCheckable(True)
                                btn2.setChecked(mpls_path == selected_mpls)
                                btn2.clicked.connect(partial(self.on_button_main, mpls_path))
                                table_widget.setCellWidget(mpls_n, 3, btn2)
                                btn3 = QToolButton()
                                btn3.setText(self.t('play'))
                                btn3.setProperty('action', 'play')
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
                self.table1.setColumnWidth(2, 420 if getattr(self, '_language_code', CURRENT_UI_LANGUAGE) == 'zh' else 370)
                self._scroll_table_h_to_right(self.table1)
                table_ok = True
            except Exception as e:
                self.table1.clear()
                self.table1.setColumnCount(len(BDMV_LABELS))
                self._set_table_headers(self.table1, BDMV_LABELS)
                self.table1.setRowCount(0)
        self.altered = True
        if self.get_selected_function_id() in (3, 4) and bdmv_path and table_ok:
            if self._is_movie_mode():
                self._refresh_movie_table2()
            else:
                configuration = BluraySubtitle(
                    self.bdmv_folder_path.text(),
                    [],
                    self.checkbox1.isChecked(),
                    None,
                    approx_episode_duration_seconds=self._get_approx_episode_duration_seconds()
                ).generate_configuration(self.table1)
                self.on_configuration(configuration)

    def on_subtitle_folder_path_change(self):
        raw = self.subtitle_folder_path.text()
        folder = self._normalize_path_input(raw)
        if raw.strip().startswith('file://') and folder and folder != raw.strip():
            try:
                self.subtitle_folder_path.blockSignals(True)
                self.subtitle_folder_path.setText(folder)
            finally:
                self.subtitle_folder_path.blockSignals(False)
        self._pending_subtitle_folder = folder
        self._update_language_combo_enabled_state()
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

        function_id = self.get_selected_function_id()
        if function_id == 1:
            mode = 1
            title = '读取字幕中'
        elif function_id == 2:
            mode = 2
            title = '读取MKV中'
        elif function_id == 3:
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

        progress_dialog = QProgressDialog(self.t(title), self.t('取消'), 0, 1000, self)
        progress_dialog.setMinimumWidth(400)
        bar = QProgressBar(progress_dialog)
        bar.setRange(0, 1000)
        bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        progress_dialog.setBar(bar)
        def update_bar_format(val):
            bar.setFormat(f"{val / 10.0:.1f}%")
        bar.valueChanged.connect(update_bar_format)
        update_bar_format(0)
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
            cancel_event,
            movie_mode=self._is_movie_mode()
        )
        self._subtitle_scan_worker.moveToThread(self._subtitle_scan_thread)
        self._subtitle_scan_thread.started.connect(self._subtitle_scan_worker.run)
        self._subtitle_scan_worker.progress.connect(progress_dialog.setValue)
        self._subtitle_scan_worker.label.connect(lambda text: progress_dialog.setLabelText(self.t(text)))

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
            if payload.get('mode') == 1 and self._is_movie_mode():
                self._refresh_movie_subtitle_table2(payload.get('rows') or [])
                self._update_main_row_play_button()
                return
            if payload.get('mode') in (3, 4) and self._is_movie_mode():
                rows = payload.get('rows') or []
                for i, (path, _dur) in enumerate(rows):
                    if i < self.table2.rowCount():
                        self.table2.setItem(i, 0, FilePathTableWidgetItem(path))
                self.table2.resizeColumnsToContents()
                self._scroll_table_h_to_right(self.table2)
                self._refresh_movie_table2()
                self._update_main_row_play_button()
                return
            if payload.get('mode') == 2:
                self.table2.clear()
                self.table2.setColumnCount(len(MKV_LABELS))
                self._set_table_headers(self.table2, MKV_LABELS)
                self._set_table2_default_column_order()
                rows = payload.get('rows') or []
                self.table2.setRowCount(len(rows))
                for i, (path, dur) in enumerate(rows):
                    self.table2.setItem(i, 0, FilePathTableWidgetItem(path))
                    self.table2.setItem(i, 1, QTableWidgetItem(dur))
                self.table2.resizeColumnsToContents()
                self._scroll_table_h_to_right(self.table2)
                return

            rows = payload.get('rows') or []
            if payload.get('mode') == 3:
                self.table2.clear()
                self.table2.setColumnCount(len(REMUX_LABELS))
                self._set_table_headers(self.table2, REMUX_LABELS)
                self._set_table2_default_column_order()
                self.table2.setRowCount(len(rows))
                for i, (path, dur) in enumerate(rows):
                    self.table2.setItem(i, 0, FilePathTableWidgetItem(path))
                    self.table2.setItem(i, 1, QTableWidgetItem(dur))
                self.table2.resizeColumnsToContents()
                self._scroll_table_h_to_right(self.table2)
            elif payload.get('mode') == 4:
                self.table2.clear()
                self.table2.setColumnCount(len(ENCODE_LABELS))
                self._set_table_headers(self.table2, ENCODE_LABELS)
                self._set_table2_default_column_order()
                self.table2.setRowCount(len(rows))
                for i, (path, dur) in enumerate(rows):
                    self.table2.setItem(i, 0, FilePathTableWidgetItem(path))
                    self.table2.setItem(i, 1, QTableWidgetItem(dur))
                    self.ensure_encode_row_widgets(i)
                self.table2.resizeColumnsToContents()
                self._scroll_table_h_to_right(self.table2)
            else:
                self.table2.clear()
                self.table2.setColumnCount(len(SUBTITLE_LABELS))
                self._set_table_headers(self.table2, SUBTITLE_LABELS)
                self._set_table2_subtitle_column_order()
                self.table2.setRowCount(len(rows))
                for i, (path, dur) in enumerate(rows):
                    check_item = QTableWidgetItem()
                    check_item.setFlags(check_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    check_item.setCheckState(Qt.CheckState.Checked)
                    self.table2.setItem(i, 0, check_item)
                    self.table2.setItem(i, 1, FilePathTableWidgetItem(path))
                    self.table2.setItem(i, SUBTITLE_LABELS.index('sub_duration'), QTableWidgetItem(dur))

                self._update_main_row_play_button()
                for bdmv_index in range(self.table1.rowCount()):
                    info: QTableWidget = self.table1.cellWidget(bdmv_index, 2)
                    if info:
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
                self.table2.resizeColumnsToContents()
                self._scroll_table_h_to_right(self.table2)

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
            if self.get_selected_function_id() in (3, 4) and self._is_movie_mode():
                self._refresh_movie_table2()
                return
            if self.get_selected_function_id() in (3, 4):
                sub_files = [self.table2.item(sub_index, 0).text() for sub_index in range(self.table2.rowCount())
                             if self.table2.item(sub_index, 0)]
            else:
                sub_files = [self.table2.item(sub_index, 1).text() for sub_index in range(self.table2.rowCount())
                             if self.table2.item(sub_index, 0) and self.table2.item(sub_index, 0).checkState() == 2]
            bs = BluraySubtitle(
                self.bdmv_folder_path.text(),
                sub_files,
                self.checkbox1.isChecked(),
                None,
                approx_episode_duration_seconds=self._get_approx_episode_duration_seconds()
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
        if self.get_selected_function_id() == 2:
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
        if self.get_selected_function_id() == 2:
            if logicalIndex != 0:
                return
            # For radio2, just update the duration column after sorting
            for i in range(self.table2.rowCount()):
                item = self.table2.item(i, 0)
                if item and os.path.exists(item.text()):
                    self.table2.setItem(i, 1, QTableWidgetItem(get_time_str(MKV(item.text()).get_duration())))
            return
        else:
            sort_col = 0 if (self.get_selected_function_id() in (3, 4)) else 1
            if logicalIndex != sort_col:
                return
        
        if self.table2.rowCount() == 0:
            return
        try:
            # update row-specific computed columns
            if self.get_selected_function_id() == 1:
                if self._is_movie_mode():
                    return
                for i in range(self.table2.rowCount()):
                    item = self.table2.item(i, 1)
                    if item and os.path.exists(item.text()):
                        self.table2.setItem(i, SUBTITLE_LABELS.index('sub_duration'), QTableWidgetItem(get_time_str(Subtitle(item.text()).max_end_time())))

            if self.get_selected_function_id() in (3, 4) and self._is_movie_mode():
                return

            # Rebuild configuration after sorting
            if self.get_selected_function_id() in (3, 4):
                sub_files = [self.table2.item(sub_index, 0).text() for sub_index in range(self.table2.rowCount())
                             if self.table2.item(sub_index, 0) and self.table2.item(sub_index, 0).text()]
            else:
                sub_files = [self.table2.item(sub_index, 1).text() for sub_index in range(self.table2.rowCount())
                             if self.table2.item(sub_index, 0) and self.table2.item(sub_index, 0).checkState() == 2]
            bs = BluraySubtitle(
                self.bdmv_folder_path.text(),
                sub_files,
                self.checkbox1.isChecked(),
                None,
                approx_episode_duration_seconds=self._get_approx_episode_duration_seconds()
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
            if self.get_selected_function_id() == 1 and self._is_movie_mode():
                return
            sub_files = [self.table2.item(sub_index, 1).text() for sub_index in range(self.table2.rowCount())
                         if self.sub_check_state[sub_index] == 2]
            bs = BluraySubtitle(
                self.bdmv_folder_path.text(),
                sub_files,
                self.checkbox1.isChecked(),
                None,
                approx_episode_duration_seconds=self._get_approx_episode_duration_seconds()
            )
            selected_mpls = self.get_selected_mpls_no_ext()
            if selected_mpls:
                configuration = bs.generate_configuration_from_selected_mpls(selected_mpls)
            else:
                configuration = bs.generate_configuration(self.table1)
            self.on_configuration(configuration)
        for sub_index, check_state in enumerate(self.sub_check_state):
            if check_state != 2:
                bdmv_col = SUBTITLE_LABELS.index('bdmv_index')
                chapter_col = SUBTITLE_LABELS.index('chapter_index')
                offset_col = SUBTITLE_LABELS.index('offset')
                ep_duration_col = SUBTITLE_LABELS.index('ep_duration')
                self.table2.setItem(sub_index, bdmv_col, None)
                self.table2.setItem(sub_index, ep_duration_col, None)
                self.table2.setCellWidget(sub_index, chapter_col, None)
                self.table2.setItem(sub_index, offset_col, None)

    def on_configuration(self, configuration: dict[int, dict[str, int | str]]):
        try:
            if not configuration:
                print('配置为空，跳过更新')
                return
            function_id = self.get_selected_function_id()
            if function_id in (3, 4):
                self._last_configuration_34 = configuration
                old_sorting = self.table2.isSortingEnabled()
                self.table2.setSortingEnabled(False)
                labels = ENCODE_LABELS if function_id == 4 else REMUX_LABELS
                duration_col = labels.index('ep_duration')
                bdmv_col = labels.index('bdmv_index')
                chapter_col = labels.index('chapter_index')
                m2ts_col = labels.index('m2ts_file')
                language_col = labels.index('language')
                output_col = labels.index('output_name')
                auto_output_name_map = self._build_episode_output_name_map(configuration)
                if self._is_movie_mode():
                    by_bdmv: dict[int, list[int]] = {}
                    for sub_index, con in configuration.items():
                        try:
                            bdmv_index = int(con.get('bdmv_index') or 0)
                        except Exception:
                            bdmv_index = 0
                        by_bdmv.setdefault(bdmv_index, []).append(sub_index)
                    for bdmv_index in by_bdmv:
                        by_bdmv[bdmv_index].sort(key=lambda i: int(configuration[i].get('chapter_index') or 0))

                    prev_lang_by_bdmv: dict[int, str] = {}
                    prev_auto_lang_by_bdmv: dict[int, str] = {}
                    prev_name_by_bdmv: dict[int, tuple[str, str]] = {}
                    try:
                        for r in range(self.table2.rowCount()):
                            bdmv_item = self.table2.item(r, bdmv_col)
                            if not bdmv_item or not bdmv_item.text().strip():
                                continue
                            try:
                                bdmv_index = int(bdmv_item.text().strip())
                            except Exception:
                                continue
                            w = self.table2.cellWidget(r, language_col)
                            if isinstance(w, QComboBox):
                                prev_lang_by_bdmv[bdmv_index] = w.currentText().strip()
                                prev_auto_lang_by_bdmv[bdmv_index] = str(getattr(w, '_auto_lang', '') or '')
                            it = self.table2.item(r, output_col)
                            if it and it.text():
                                auto = it.data(Qt.ItemDataRole.UserRole)
                                prev_name_by_bdmv[bdmv_index] = (it.text().strip(), auto if isinstance(auto, str) else '')
                    except Exception:
                        pass

                    disc_rows = [k for k in sorted(by_bdmv.keys()) if k != 0] + ([0] if 0 in by_bdmv else [])
                    self.table2.setRowCount(len(disc_rows))

                    auto_lang = 'eng' if getattr(self, '_language_code', CURRENT_UI_LANGUAGE) != 'zh' else 'chi'

                    sub_files_in_folder: list[str] = []
                    if self.subtitle_folder_path.text().strip():
                        try:
                            for file in sorted(os.listdir(self.subtitle_folder_path.text().strip())):
                                if (file.endswith(".ass") or file.endswith(".ssa") or
                                        file.endswith('srt') or file.endswith('.sup')):
                                    sub_files_in_folder.append(os.path.normpath(os.path.join(self.subtitle_folder_path.text().strip(), file)))
                        except Exception:
                            pass

                    for row_i, bdmv_index in enumerate(disc_rows):
                        sub_indexes = by_bdmv.get(bdmv_index, [])
                        if not sub_indexes:
                            continue
                        first_sub_index = sub_indexes[0]
                        con0 = configuration[first_sub_index]
                        self.table2.setItem(row_i, bdmv_col, QTableWidgetItem(str(bdmv_index)))

                        chapter_combo = QComboBox()
                        chapter_combo.addItems(['1'])
                        chapter_combo.setCurrentIndex(0)
                        chapter_combo.setEnabled(False)
                        self.table2.setCellWidget(row_i, chapter_col, chapter_combo)

                        chapter = Chapter(str(con0['selected_mpls']) + '.mpls')
                        total_time = chapter.get_total_time()
                        self.table2.setItem(row_i, duration_col, QTableWidgetItem(get_time_str(total_time)))

                        index_to_m2ts, _index_to_offset = get_index_to_m2ts_and_offset(chapter)
                        try:
                            rows = sum(map(len, chapter.mark_info.values()))
                            m2ts_files = sorted(list(set(index_to_m2ts[i] for i in range(1, rows + 1) if i in index_to_m2ts)))
                        except Exception:
                            m2ts_files = sorted(list(set(index_to_m2ts.values())))
                        self.table2.setItem(row_i, m2ts_col, QTableWidgetItem(', '.join(m2ts_files)))

                        prev_lang = prev_lang_by_bdmv.get(bdmv_index, '').strip()
                        prev_auto_lang = prev_auto_lang_by_bdmv.get(bdmv_index, '').strip()
                        if prev_lang and prev_auto_lang and prev_lang != prev_auto_lang:
                            final_lang = prev_lang
                        elif prev_lang and not prev_auto_lang:
                            final_lang = prev_lang
                        else:
                            final_lang = auto_lang
                        lang_combo = self.create_language_combo(final_lang)
                        lang_combo._auto_lang = auto_lang
                        self.table2.setCellWidget(row_i, language_col, lang_combo)

                        auto_name = auto_output_name_map.get(first_sub_index, '')
                        if auto_name:
                            auto_name = re.sub(r'^(?i:EP)\s*\d+\s*', '', auto_name)
                            auto_name = re.sub(r'\s*-\d{3}(?=\.mkv$)', '', auto_name)
                        prev_name, prev_auto = prev_name_by_bdmv.get(bdmv_index, ('', ''))
                        if prev_name and prev_auto and prev_name != prev_auto:
                            final_text = prev_name
                        else:
                            final_text = auto_name
                        new_item = QTableWidgetItem(final_text)
                        new_item.setData(Qt.ItemDataRole.UserRole, auto_name)
                        self.table2.setItem(row_i, output_col, new_item)

                        if sub_files_in_folder:
                            idx = first_sub_index
                            if 0 <= idx < len(sub_files_in_folder):
                                self.table2.setItem(row_i, 0, FilePathTableWidgetItem(sub_files_in_folder[idx]))

                        self.ensure_encode_row_widgets(row_i)
                else:
                    self.table2.setRowCount(len(configuration))
                    for sub_index, con in configuration.items():
                        self.table2.setItem(sub_index, bdmv_col, QTableWidgetItem(str(con['bdmv_index'])))
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
                        self.table2.setCellWidget(sub_index, chapter_col, chapter_combo)
                        self.table2.setItem(sub_index, m2ts_col, QTableWidgetItem(', '.join(m2ts_files)))
                        self.table2.setItem(sub_index, duration_col, QTableWidgetItem(duration))

                        prev_lang_widget = self.table2.cellWidget(sub_index, language_col)
                        prev_lang = ''
                        prev_auto_lang = ''
                        if isinstance(prev_lang_widget, QComboBox):
                            prev_lang = prev_lang_widget.currentText().strip()
                            prev_auto_lang = str(getattr(prev_lang_widget, '_auto_lang', 'chi') or 'chi')
                        auto_lang = 'eng' if getattr(self, '_language_code', CURRENT_UI_LANGUAGE) != 'zh' else 'chi'
                        if prev_lang and prev_lang != prev_auto_lang:
                            final_lang = prev_lang
                        else:
                            final_lang = auto_lang
                        lang_combo = self.create_language_combo(final_lang)
                        lang_combo._auto_lang = auto_lang
                        self.table2.setCellWidget(sub_index, language_col, lang_combo)
                        auto_name = auto_output_name_map.get(sub_index, '')
                        prev_item = self.table2.item(sub_index, output_col)
                        prev_text = prev_item.text().strip() if prev_item and prev_item.text() else ''
                        prev_auto = prev_item.data(Qt.ItemDataRole.UserRole) if prev_item else None
                        if prev_text and isinstance(prev_auto, str) and prev_text != prev_auto:
                            final_text = prev_text
                        else:
                            final_text = auto_name
                        new_item = QTableWidgetItem(final_text)
                        new_item.setData(Qt.ItemDataRole.UserRole, auto_name)
                        self.table2.setItem(sub_index, output_col, new_item)
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
                            if (not self._is_movie_mode()) and i < len(configuration) and i < self.table2.rowCount():
                                self.table2.setItem(i, 0, FilePathTableWidgetItem(sub_file))
                self.table2.resizeColumnsToContents()
                self._resize_table_columns_for_language(self.table2)
                self._update_language_combo_enabled_state()
                if function_id in (3, 4):
                    self.refresh_sp_table(configuration)
                self.table2.setSortingEnabled(old_sorting)
            else:
                if self._is_movie_mode():
                    return
                sub_check_state = [self.table2.item(sub_index, 0).checkState().value for sub_index in
                                   range(self.table2.rowCount())]
                index_table = [sub_index for sub_index in range(len(sub_check_state)) if sub_check_state[sub_index] == 2]

                bdmv_col = SUBTITLE_LABELS.index('bdmv_index')
                chapter_col = SUBTITLE_LABELS.index('chapter_index')
                offset_col = SUBTITLE_LABELS.index('offset')
                ep_duration_col = SUBTITLE_LABELS.index('ep_duration')

                for subtitle_index, row in enumerate(index_table):
                    con = configuration.get(subtitle_index)
                    if con:
                        self.table2.setItem(row, bdmv_col, QTableWidgetItem(str(con['bdmv_index'])))

                        chapter = Chapter(str(con['selected_mpls']) + '.mpls')
                        rows = sum(map(len, chapter.mark_info.values()))
                        chapter_combo = QComboBox()
                        chapter_combo.addItems([str(r + 1) for r in range(rows)])
                        chapter_combo.setCurrentIndex(con['chapter_index'] - 1)
                        chapter_combo.currentIndexChanged.connect(partial(self.on_chapter_combo, subtitle_index))
                        self.table2.setCellWidget(row, chapter_col, chapter_combo)
                        self.table2.setItem(row, offset_col, QTableWidgetItem(con['offset']))

                        duration = 0
                        j1 = int(con['chapter_index'])
                        next_con = configuration.get(subtitle_index + 1)
                        if next_con and next_con.get('folder') == con.get('folder') and next_con.get('selected_mpls') == con.get('selected_mpls'):
                            j2 = int(next_con['chapter_index'])
                        else:
                            j2 = rows + 1
                        _index_to_m2ts, index_to_offset = get_index_to_m2ts_and_offset(chapter)
                        try:
                            if next_con and next_con.get('folder') == con.get('folder') and next_con.get('selected_mpls') == con.get('selected_mpls'):
                                duration = index_to_offset[j2] - index_to_offset[j1]
                            else:
                                duration = chapter.get_total_time() - index_to_offset[j1]
                        except Exception:
                            duration = chapter.get_total_time()
                        self.table2.setItem(row, ep_duration_col, QTableWidgetItem(get_time_str(duration)))
                    else:
                        self.table2.setItem(row, bdmv_col, None)
                        self.table2.setItem(row, ep_duration_col, None)
                        self.table2.setCellWidget(row, chapter_col, None)
                        self.table2.setItem(row, offset_col, None)
                self.table2.resizeColumnsToContents()
                self.altered = True
        except Exception:
            QMessageBox.information(self, " ", traceback.format_exc())
            if hasattr(self, 'table3'):
                self.table3.setRowCount(0)
            return

    def on_chapter_combo(self, subtitle_index: int):
        if self.get_selected_function_id() in (3, 4):
            sub_files = []
            if self.subtitle_folder_path.text().strip():
                for file in sorted(os.listdir(self.subtitle_folder_path.text().strip())):
                    if file.endswith(".ass") or file.endswith(".ssa") or file.endswith('srt') or file.endswith('.sup'):
                        sub_files.append(os.path.normpath(os.path.join(self.subtitle_folder_path.text().strip(), file)))
            sub_combo_index = {}
            labels = ENCODE_LABELS if self.get_selected_function_id() == 4 else REMUX_LABELS
            chapter_col = labels.index('chapter_index')
            for sub_index in range(self.table2.rowCount()):
                w = self.table2.cellWidget(sub_index, chapter_col)
                if isinstance(w, QComboBox):
                    sub_combo_index[sub_index] = w.currentIndex() + 1
            bs = BluraySubtitle(
                self.bdmv_folder_path.text(),
                sub_files,
                self.checkbox1.isChecked(),
                None,
                approx_episode_duration_seconds=self._get_approx_episode_duration_seconds()
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
                    chapter_col = SUBTITLE_LABELS.index('chapter_index')
                    w = self.table2.cellWidget(sub_index, chapter_col)
                    if isinstance(w, QComboBox) and w.isEnabled():
                        sub_combo_index[sub_index] = w.currentIndex() + 1
            bs = BluraySubtitle(
                self.bdmv_folder_path.text(),
                sub_files,
                self.checkbox1.isChecked(),
                None,
                approx_episode_duration_seconds=self._get_approx_episode_duration_seconds()
            )
            selected_mpls = self.get_selected_mpls_no_ext()
            if selected_mpls:
                configuration = bs.generate_configuration_from_selected_mpls(selected_mpls, sub_combo_index, subtitle_index)
            else:
                configuration = bs.generate_configuration(self.table1, sub_combo_index, subtitle_index)
            self.on_configuration(configuration)

    def on_button_play(self, mpls_path: str, btn: QToolButton):
        def _select_subtitle_file_for_mpls(mpls_path: str) -> Optional[str]:
            try:
                mpls_name = mpls_path[:-5]
                folder = os.path.dirname(mpls_name)
                base = os.path.basename(mpls_name)
                if not folder or not os.path.isdir(folder):
                    return None
                candidates = []
                for f in os.listdir(folder):
                    if not (f.endswith('.ass') or f.endswith('.srt') or f.endswith('.ssa')):
                        continue
                    if not f.startswith(base):
                        continue
                    candidates.append(os.path.normpath(os.path.join(folder, f)))
                candidates.sort()
                if not candidates:
                    return None
                if len(candidates) == 1:
                    return candidates[0]
                display = [os.path.basename(p) for p in candidates]
                item, ok = QInputDialog.getItem(
                    self,
                    self.t("选择字幕文件"),
                    self.t("检测到多个字幕文件，请选择要预览的文件："),
                    display,
                    0,
                    False
                )
                if not ok or not item:
                    return None
                try:
                    idx = display.index(str(item))
                except Exception:
                    return None
                return candidates[idx]
            except Exception:
                return None

        def mpv_play_mpls(mpls_path, mpv_path):
            sub_file = _select_subtitle_file_for_mpls(mpls_path)
            if sub_file:
                subprocess.Popen(
                    f'"{mpv_path}" --sub-file="{sub_file}" bd://mpls/{mpls_path[-10:-5]} --bluray-device="{mpls_path[:-25]}"',
                    shell=True).wait()
            else:
                subprocess.Popen(f'"{mpv_path}" bd://mpls/{mpls_path[-10:-5]} --bluray-device="{mpls_path[:-25]}"',
                                 shell=True).wait()
            return

        action = btn.property('action') or ''
        is_preview = (action == 'preview') or (btn.text() in ('preview', self.t('preview')))
        if is_preview and self.altered:
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
        elif is_preview:
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
                    sub_file = _select_subtitle_file_for_mpls(mpls_path)
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
        def has_subtitle_in_table2() -> bool:
            return self._has_subtitle_in_table2()

        for bdmv_index in range(self.table1.rowCount()):
            if mpls_path.startswith(self.table1.item(bdmv_index, 0).text()):
                info: QTableWidget = self.table1.cellWidget(bdmv_index, 2)
                for mpls_index in range(info.rowCount()):
                    if mpls_path.endswith(info.item(mpls_index, 0).text()):
                        checked = info.cellWidget(mpls_index, 3).isChecked()
                        if checked:
                            subtitle = has_subtitle_in_table2()
                            play_btn = info.cellWidget(mpls_index, 4)
                            if play_btn:
                                play_btn.setProperty('action', 'preview' if subtitle else 'play')
                                play_btn.setText(self.t('preview') if subtitle else self.t('play'))
                            for mpls_index_1 in range(info.rowCount()):
                                if not mpls_path.endswith(info.item(mpls_index_1, 0).text()):
                                    if info.cellWidget(mpls_index_1, 3).isChecked():
                                        info.cellWidget(mpls_index_1, 3).setChecked(False)
                                        other_play_btn = info.cellWidget(mpls_index_1, 4)
                                        if other_play_btn:
                                            other_play_btn.setProperty('action', 'play')
                                            other_play_btn.setText(self.t('play'))
                        else:
                            play_btn = info.cellWidget(mpls_index, 4)
                            if play_btn:
                                play_btn.setProperty('action', 'play')
                                play_btn.setText(self.t('play'))
        if self.get_selected_function_id() in (3, 4) and self._is_movie_mode():
            self._refresh_movie_table2()
        else:
            self.on_subtitle_folder_path_change()

    def _has_subtitle_in_table2(self) -> bool:
        try:
            function_id = self.get_selected_function_id()
            if self.table2.rowCount() <= 0:
                return False
            if function_id == 1:
                col = SUBTITLE_LABELS.index('path')
            elif function_id == 2:
                col = MKV_LABELS.index('path')
            elif function_id in (3, 4):
                labels = ENCODE_LABELS if function_id == 4 else REMUX_LABELS
                col = labels.index('sub_path')
            else:
                return False
            for r in range(self.table2.rowCount()):
                it = self.table2.item(r, col)
                if it and it.text() and it.text().strip():
                    return True
            return False
        except Exception:
            return False

    def _update_main_row_play_button(self):
        subtitle = self._has_subtitle_in_table2()
        for bdmv_index in range(self.table1.rowCount()):
            info: QTableWidget = self.table1.cellWidget(bdmv_index, 2)
            if not info:
                continue
            for mpls_index in range(info.rowCount()):
                main_btn: QToolButton = info.cellWidget(mpls_index, 3)
                if main_btn and main_btn.isChecked():
                    play_btn = info.cellWidget(mpls_index, 4)
                    if play_btn:
                        play_btn.setProperty('action', 'preview' if subtitle else 'play')
                        play_btn.setText(self.t('preview') if subtitle else self.t('play'))
                        info.resizeColumnsToContents()

    def on_button_click(self, mpls_path: str):
        class ChapterWindow(QDialog):
            def __init__(this):
                super(ChapterWindow, this).__init__()
                this.setWindowTitle(f"{self.t('章节')}: {mpls_path}")
                layout = QVBoxLayout()
                table_widget = QTableWidget()
                self._set_compact_table(table_widget, row_height=20, header_height=20)
                table_widget.setColumnCount(2)
                self._set_table_headers(table_widget, ['offset', 'file'])
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
                height = rows * 30 + 60
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
                this.setWindowTitle(f"{self.t('编辑字幕')}: {path}")
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

    def get_selected_function_id(self) -> int:
        try:
            tabbar = getattr(self, 'function_tabbar', None)
            if tabbar is not None:
                idx = int(tabbar.currentIndex())
                if idx >= 0:
                    return idx + 1
        except Exception:
            pass
        try:
            return int(getattr(self, '_selected_function_id', 1) or 1)
        except Exception:
            return 1

    def _get_approx_episode_duration_seconds(self) -> float:
        combo = getattr(self, 'approx_episode_minutes_combo', None)
        raw = ''
        if isinstance(combo, QComboBox):
            raw = (combo.currentText() or '').strip()
        try:
            minutes = float(raw)
            if minutes <= 0:
                minutes = 24.0
        except Exception:
            minutes = 24.0
        return minutes * 60.0

    def _is_movie_mode(self) -> bool:
        radio = getattr(self, 'movie_mode_radio', None)
        try:
            return bool(radio and radio.isChecked())
        except Exception:
            return False

    def _apply_episode_mode_to_table2(self):
        if not hasattr(self, '_subtitle_scan_debounce'):
            return
        function_id = self.get_selected_function_id()
        if function_id == 1:
            if self._is_movie_mode():
                self._refresh_movie_subtitle_table2()
            else:
                self.on_subtitle_folder_path_change()
            return
        if function_id not in (3, 4):
            return
        if self._is_movie_mode():
            self._refresh_movie_table2()
            return
        configuration = getattr(self, '_last_configuration_34', None)
        if isinstance(configuration, dict) and configuration:
            self.on_configuration(configuration)

    def _refresh_movie_subtitle_table2(self, rows: Optional[list[tuple[str, str]]] = None):
        if self.get_selected_function_id() != 1:
            return
        selected_mpls = self.get_selected_mpls_no_ext()
        if not selected_mpls:
            return

        folder_to_bdmv: dict[str, int] = {}
        discs: list[tuple[int, str]] = []
        for folder, mpls_no_ext in selected_mpls:
            if folder not in folder_to_bdmv:
                folder_to_bdmv[folder] = len(folder_to_bdmv) + 1
            discs.append((folder_to_bdmv[folder], mpls_no_ext))
        discs.sort(key=lambda x: x[0])

        def parse_time_str_to_seconds(s: str) -> Optional[float]:
            try:
                parts = [p for p in str(s or '').strip().split(':') if p != '']
                if not parts:
                    return None
                nums = [float(p) for p in parts]
                val = 0.0
                for n in nums:
                    val = val * 60.0 + float(n)
                return val
            except Exception:
                return None

        file_rows: list[tuple[str, str, Optional[float]]] = []
        if rows:
            for p, d in rows:
                if not p:
                    continue
                dur_str = str(d or '').strip()
                file_rows.append((str(p).strip(), dur_str, parse_time_str_to_seconds(dur_str)))
        else:
            folder = self.subtitle_folder_path.text().strip()
            if folder and os.path.isdir(folder):
                paths = []
                for f in sorted(os.listdir(folder)):
                    if f.endswith(".ass") or f.endswith(".ssa") or f.endswith('srt') or f.endswith('.sup'):
                        paths.append(os.path.normpath(os.path.join(folder, f)))
                for p in paths:
                    try:
                        sec = float(Subtitle(p).max_end_time())
                        file_rows.append((p, get_time_str(sec), sec))
                    except Exception:
                        file_rows.append((p, '未知', None))

        sub_duration_col = SUBTITLE_LABELS.index('sub_duration')
        ep_duration_col = SUBTITLE_LABELS.index('ep_duration')
        bdmv_col = SUBTITLE_LABELS.index('bdmv_index')
        chapter_col = SUBTITLE_LABELS.index('chapter_index')
        offset_col = SUBTITLE_LABELS.index('offset')
        warn_col = SUBTITLE_LABELS.index('warning')

        old_sorting = self.table2.isSortingEnabled()
        self.table2.setSortingEnabled(False)
        try:
            self.table2.clear()
            self.table2.setColumnCount(len(SUBTITLE_LABELS))
            self._set_table_headers(self.table2, SUBTITLE_LABELS)
            self._set_table2_subtitle_column_order()
            self.table2.setRowCount(len(discs))

            for i, (bdmv_index, mpls_no_ext) in enumerate(discs):
                check_item = QTableWidgetItem()
                check_item.setFlags(check_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                check_item.setCheckState(Qt.CheckState.Checked)
                self.table2.setItem(i, 0, check_item)

                if i < len(file_rows):
                    p, dur, sub_sec = file_rows[i]
                    self.table2.setItem(i, 1, FilePathTableWidgetItem(p))
                    self.table2.setItem(i, sub_duration_col, QTableWidgetItem(dur))
                else:
                    self.table2.setItem(i, 1, FilePathTableWidgetItem(''))
                    self.table2.setItem(i, sub_duration_col, QTableWidgetItem(''))
                    sub_sec = None

                try:
                    total_time = Chapter(mpls_no_ext + '.mpls').get_total_time()
                    self.table2.setItem(i, ep_duration_col, QTableWidgetItem(get_time_str(total_time)))
                except Exception:
                    self.table2.setItem(i, ep_duration_col, QTableWidgetItem('未知'))
                    total_time = None

                self.table2.setItem(i, bdmv_col, QTableWidgetItem(str(bdmv_index)))

                chapter_combo = QComboBox(self.table2)
                chapter_combo.addItems(['1'])
                chapter_combo.setCurrentIndex(0)
                chapter_combo.setEnabled(False)
                self.table2.setCellWidget(i, chapter_col, chapter_combo)

                self.table2.setItem(i, offset_col, QTableWidgetItem('0'))

                warn_item = QTableWidgetItem('')
                try:
                    if isinstance(sub_sec, (int, float)) and isinstance(total_time, (int, float)) and total_time > 0:
                        if float(sub_sec) <= float(total_time) / 2.0:
                            warn_item.setText('!')
                            warn_item.setToolTip(self.t('可能需要剧集模式'))
                except Exception:
                    pass
                self.table2.setItem(i, warn_col, warn_item)

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
        finally:
            self.table2.setSortingEnabled(old_sorting)

        self.table2.resizeColumnsToContents()
        self._resize_table_columns_for_language(self.table2)
        self._scroll_table_h_to_right(self.table2)
        self._update_main_row_play_button()

    def _rebuild_configuration_for_function_34(self):
        if self.get_selected_function_id() not in (3, 4):
            return
        if not self.bdmv_folder_path.text().strip():
            return
        if self.table1.rowCount() == 0:
            return
        if self._is_movie_mode():
            self._refresh_movie_table2()
            return
        try:
            sub_files = [self.table2.item(i, 0).text() for i in range(self.table2.rowCount()) if self.table2.item(i, 0)]
            bs = BluraySubtitle(
                self.bdmv_folder_path.text(),
                sub_files,
                self.checkbox1.isChecked(),
                None,
                approx_episode_duration_seconds=self._get_approx_episode_duration_seconds()
            )
            selected_mpls = self.get_selected_mpls_no_ext()
            if selected_mpls:
                configuration = bs.generate_configuration_from_selected_mpls(selected_mpls)
            else:
                configuration = bs.generate_configuration(self.table1)
            self.on_configuration(configuration)
        except Exception:
            traceback.print_exc()

    def _refresh_movie_table2(self):
        function_id = self.get_selected_function_id()
        if function_id not in (3, 4):
            return
        selected_mpls = self.get_selected_mpls_no_ext()
        labels = ENCODE_LABELS if function_id == 4 else REMUX_LABELS
        duration_col = labels.index('ep_duration')
        bdmv_col = labels.index('bdmv_index')
        chapter_col = labels.index('chapter_index')
        m2ts_col = labels.index('m2ts_file')
        language_col = labels.index('language')
        output_col = labels.index('output_name')

        prev_lang_by_bdmv: dict[int, str] = {}
        prev_auto_lang_by_bdmv: dict[int, str] = {}
        prev_name_by_bdmv: dict[int, tuple[str, str]] = {}
        try:
            for r in range(self.table2.rowCount()):
                bdmv_item = self.table2.item(r, bdmv_col)
                if not bdmv_item or not bdmv_item.text().strip():
                    continue
                try:
                    bdmv_index = int(bdmv_item.text().strip())
                except Exception:
                    continue
                w = self.table2.cellWidget(r, language_col)
                if isinstance(w, QComboBox):
                    prev_lang_by_bdmv[bdmv_index] = w.currentText().strip()
                    prev_auto_lang_by_bdmv[bdmv_index] = str(getattr(w, '_auto_lang', '') or '')
                it = self.table2.item(r, output_col)
                if it and it.text():
                    auto = it.data(Qt.ItemDataRole.UserRole)
                    prev_name_by_bdmv[bdmv_index] = (it.text().strip(), auto if isinstance(auto, str) else '')
        except Exception:
            pass

        folder_to_bdmv: dict[str, int] = {}
        disc_rows: list[tuple[int, str, str]] = []
        for folder, mpls_no_ext in selected_mpls:
            if folder not in folder_to_bdmv:
                folder_to_bdmv[folder] = len(folder_to_bdmv) + 1
            bdmv_index = folder_to_bdmv[folder]
            disc_rows.append((bdmv_index, folder, mpls_no_ext))
        disc_rows.sort(key=lambda x: x[0])
        single_volume = len(disc_rows) == 1

        sub_files_in_folder: list[str] = []
        if self.subtitle_folder_path.text().strip():
            try:
                for file in sorted(os.listdir(self.subtitle_folder_path.text().strip())):
                    if (file.endswith(".ass") or file.endswith(".ssa") or
                            file.endswith('srt') or file.endswith('.sup')):
                        sub_files_in_folder.append(os.path.normpath(os.path.join(self.subtitle_folder_path.text().strip(), file)))
            except Exception:
                pass

        auto_lang = 'eng' if getattr(self, '_language_code', CURRENT_UI_LANGUAGE) != 'zh' else 'chi'
        configuration: dict[int, dict[str, int | str]] = {}

        old_sorting = self.table2.isSortingEnabled()
        self.table2.setSortingEnabled(False)
        try:
            self.table2.setRowCount(len(disc_rows))
            for row_i, (bdmv_index, folder, mpls_no_ext) in enumerate(disc_rows):
                mpls_path = mpls_no_ext + '.mpls'
                chapter = Chapter(mpls_path)
                total_time = chapter.get_total_time()
                index_to_m2ts, _index_to_offset = get_index_to_m2ts_and_offset(chapter)
                m2ts_files = sorted(list(set(index_to_m2ts.values())))
                disc_name = self._resolve_output_name_from_mpls(mpls_no_ext)
                bdmv_vol = f'{bdmv_index:03d}'
                auto_name = f'{disc_name}.mkv' if single_volume else f'{disc_name}_BD_Vol_{bdmv_vol}.mkv'

                if sub_files_in_folder and row_i < len(sub_files_in_folder):
                    self.table2.setItem(row_i, 0, FilePathTableWidgetItem(sub_files_in_folder[row_i]))

                self.table2.setItem(row_i, bdmv_col, QTableWidgetItem(str(bdmv_index)))
                chapter_combo = QComboBox()
                chapter_combo.addItems(['1'])
                chapter_combo.setCurrentIndex(0)
                chapter_combo.setEnabled(False)
                self.table2.setCellWidget(row_i, chapter_col, chapter_combo)
                self.table2.setItem(row_i, m2ts_col, QTableWidgetItem(', '.join(m2ts_files)))
                self.table2.setItem(row_i, duration_col, QTableWidgetItem(get_time_str(total_time)))

                prev_lang = prev_lang_by_bdmv.get(bdmv_index, '').strip()
                prev_auto_lang = prev_auto_lang_by_bdmv.get(bdmv_index, '').strip()
                if prev_lang and prev_auto_lang and prev_lang != prev_auto_lang:
                    final_lang = prev_lang
                elif prev_lang and not prev_auto_lang:
                    final_lang = prev_lang
                else:
                    final_lang = auto_lang
                lang_combo = self.create_language_combo(final_lang)
                lang_combo._auto_lang = auto_lang
                self.table2.setCellWidget(row_i, language_col, lang_combo)

                prev_name, prev_auto = prev_name_by_bdmv.get(bdmv_index, ('', ''))
                if prev_name and prev_auto and prev_name != prev_auto:
                    final_text = prev_name
                else:
                    final_text = auto_name
                out_item = QTableWidgetItem(final_text)
                out_item.setData(Qt.ItemDataRole.UserRole, auto_name)
                self.table2.setItem(row_i, output_col, out_item)

                if function_id == 4:
                    self.ensure_encode_row_widgets(row_i)

                configuration[row_i] = {
                    'folder': folder,
                    'selected_mpls': mpls_no_ext,
                    'bdmv_index': bdmv_index,
                    'chapter_index': 1,
                    'offset': '0',
                    'disc_output_name': disc_name,
                    'output_name': final_text,
                }
        finally:
            self.table2.setSortingEnabled(old_sorting)

        self._movie_configuration = configuration
        if function_id in (3, 4):
            self.refresh_sp_table(configuration)
        self.table2.resizeColumnsToContents()
        self._resize_table_columns_for_language(self.table2)
        self._update_language_combo_enabled_state()

    def on_select_function(self, force: bool = False, keep_inputs: bool = False, keep_state: bool = False):
        if getattr(self, '_language_updating', False):
            keep_inputs = True
            keep_state = True
        function_id = self.get_selected_function_id()

        last_function_id = int(getattr(self, '_selected_function_id', 0) or 0)
        if (not force) and function_id and last_function_id == function_id:
            return
        self._selected_function_id = function_id

        if hasattr(self, 'output_folder_row') and self.output_folder_row:
            self.output_folder_row.setVisible(function_id in (3, 4))
        if hasattr(self, 'episode_mode_row') and self.episode_mode_row:
            self.episode_mode_row.setVisible(function_id in (1, 3, 4))
        if hasattr(self, 'table3'):
            self.table3.setVisible(function_id in (3, 4))
            try:
                vpy_col = ENCODE_SP_LABELS.index('vpy_path')
                edit_col = ENCODE_SP_LABELS.index('edit_vpy')
                preview_col = ENCODE_SP_LABELS.index('preview_script')
                is_encode = function_id == 4
                self.table3.setColumnHidden(vpy_col, not is_encode)
                self.table3.setColumnHidden(edit_col, not is_encode)
                self.table3.setColumnHidden(preview_col, not is_encode)
            except Exception:
                pass
        if function_id == 4:
            QTimer.singleShot(0, self.ensure_default_vpy_file)

        if function_id == 1:
            self.label2.setText(self.t("选择单集字幕所在的文件夹"))
            self.exe_button.setText(self.t("生成字幕"))
            self.encode_box.setVisible(False)
            if not self.checkbox1.isVisible():
                self.checkbox1.setVisible(True)
                if hasattr(self, '_geometry') and self._geometry is not None:
                    self.restoreGeometry(self._geometry)
            self.checkbox1.setText(self.t('补全蓝光目录'))
            if hasattr(self, 'merge_options_row') and self.merge_options_row:
                self.merge_options_row.setVisible(True)
            if not keep_state:
                self.table1.clear()
                self.table1.setRowCount(0)
                self.table1.setColumnCount(len(BDMV_LABELS))
                self._set_table_headers(self.table1, BDMV_LABELS)
                self.table2.clear()
                self.table2.setRowCount(0)
                self.table2.setColumnCount(len(SUBTITLE_LABELS))
                self._set_table_headers(self.table2, SUBTITLE_LABELS)
                self._set_table2_subtitle_column_order()

        if function_id == 2:
            self.label2.setText(self.t("选择mkv文件所在的文件夹"))
            self.exe_button.setText(self.t("添加章节"))
            self.encode_box.setVisible(False)
            if not self.checkbox1.isVisible():
                self.checkbox1.setVisible(True)
                if hasattr(self, '_geometry') and self._geometry is not None:
                    self.restoreGeometry(self._geometry)
            self.checkbox1.setText(self.t('直接编辑原文件'))
            if hasattr(self, 'merge_options_row') and self.merge_options_row:
                self.merge_options_row.setVisible(False)
            if not keep_state:
                self.table1.clear()
                self.table1.setRowCount(0)
                self.table1.setColumnCount(len(BDMV_LABELS))
                self._set_table_headers(self.table1, BDMV_LABELS)
                self.table2.clear()
                self.table2.setRowCount(0)
                self.table2.setColumnCount(len(MKV_LABELS))
                self._set_table_headers(self.table2, MKV_LABELS)
                self._set_table2_default_column_order()

        if function_id == 3:
            if not keep_state:
                self._geometry = self.saveGeometry()
            self.label2.setText(self.t("选择字幕文件所在的文件夹（可选）"))
            self.exe_button.setText(self.t("开始remux"))
            self.encode_box.setVisible(False)
            self.checkbox1.setVisible(False)
            if hasattr(self, 'merge_options_row') and self.merge_options_row:
                self.merge_options_row.setVisible(False)
            if not keep_state:
                self.table1.clear()
                self.table1.setRowCount(0)
                self.table1.setColumnCount(len(BDMV_LABELS))
                self._set_table_headers(self.table1, BDMV_LABELS)
                self.table2.clear()
                self.table2.setRowCount(0)
                self.table2.setColumnCount(len(REMUX_LABELS))
                self._set_table_headers(self.table2, REMUX_LABELS)
                self._set_table2_default_column_order()
                if hasattr(self, 'table3'):
                    self.table3.clear()
                    self.table3.setRowCount(0)
                    self.table3.setColumnCount(len(ENCODE_SP_LABELS))
                    self._set_table_headers(self.table3, ENCODE_SP_LABELS)

        if function_id == 4:
            if not keep_state:
                self._geometry = self.saveGeometry()
            self.label2.setText(self.t("选择字幕文件所在的文件夹（可选）"))
            self.exe_button.setText(self.t("开始压制"))
            self.checkbox1.setVisible(False)
            if hasattr(self, 'merge_options_row') and self.merge_options_row:
                self.merge_options_row.setVisible(False)
            self.encode_box.setVisible(True)
            if not keep_state:
                self.table1.clear()
                self.table1.setRowCount(0)
                self.table1.setColumnCount(len(BDMV_LABELS))
                self._set_table_headers(self.table1, BDMV_LABELS)
                self.table2.clear()
                self.table2.setRowCount(0)
                self.table2.setColumnCount(len(ENCODE_LABELS))
                self._set_table_headers(self.table2, ENCODE_LABELS)
                self._set_table2_default_column_order()
                if hasattr(self, 'table3'):
                    self.table3.clear()
                    self.table3.setRowCount(0)
                    self.table3.setColumnCount(len(ENCODE_SP_LABELS))
                    self._set_table_headers(self.table3, ENCODE_SP_LABELS)

        if not keep_inputs:
            self.bdmv_folder_path.clear()
            self.subtitle_folder_path.clear()

    def select_bdmv_folder(self):
        folder = QFileDialog.getExistingDirectory(self, self.t("选择文件夹"))
        self.bdmv_folder_path.setText(os.path.normpath(folder))

    def open_folder_path(self, path: str):
        path = self._normalize_path_input(path)
        if not path:
            QMessageBox.information(self, " ", "未填写文件夹路径")
            return

        normalized = path
        if os.path.isfile(normalized):
            normalized = os.path.normpath(os.path.dirname(normalized))

        if not os.path.isdir(normalized):
            QMessageBox.warning(self, "打开文件夹失败", f"文件夹不存在：\n{normalized}")
            return

        try:
            if sys.platform == 'win32':
                os.startfile(normalized)
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', normalized])
            else:
                subprocess.Popen(['xdg-open', normalized])
        except Exception as e:
            QMessageBox.warning(self, "打开文件夹失败", f"无法打开文件夹：\n{normalized}\n\n{e}")

    def select_subtitle_folder(self):
        folder = QFileDialog.getExistingDirectory(self, self.t("选择文件夹"))
        self.subtitle_folder_path.setText(os.path.normpath(folder))

    def select_output_folder(self):
        start = self.output_folder_path.text().strip() if hasattr(self, 'output_folder_path') else ''
        folder = QFileDialog.getExistingDirectory(self, self.t("选择输出文件夹"), start)
        if folder:
            self.output_folder_path.setText(os.path.normpath(folder))

    def main(self):
        if getattr(self, '_current_cancel_event', None) is not None:
            self._current_cancel_event.set()
            self.exe_button.setEnabled(False)
            self._update_exe_button_progress(text='正在取消...')
            return

        function_id = self.get_selected_function_id()
        if function_id == 1:
            self.generate_subtitle()
        if function_id == 2:
            self.add_chapters()
        if function_id == 3:
            self.remux_episodes()
        if function_id == 4:
            self.encode_bluray()

    def encode_bluray(self):
        output_folder = os.path.normpath(self.output_folder_path.text().strip()) if hasattr(self, 'output_folder_path') else ''
        if not output_folder:
            QMessageBox.information(self, " ", "未选择输出文件夹")
            return
        if not os.path.isdir(output_folder):
            QMessageBox.information(self, " ", "输出文件夹不存在")
            return
        self.ensure_default_vpy_file()
        find_mkvtoolinx()

        cancel_event = threading.Event()
        self._current_cancel_event = cancel_event
        self._exe_button_default_text = self.exe_button.text()
        self._update_exe_button_progress(0, '准备中')

        sub_files = [self.table2.item(i, 0).text() for i in range(0, self.table2.rowCount()) if self.table2.item(i, 0)]
        episode_output_names = self._get_episode_output_names_from_table2()
        episode_subtitle_languages = self._get_episode_subtitle_languages_from_table2()
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
                        'm2ts_file': m2ts_item.text().strip() if m2ts_item and m2ts_item.text() else '',
                        'output_name': (self.table3.item(i, ENCODE_SP_LABELS.index('output_name')).text().strip()
                                        if self.table3.item(i, ENCODE_SP_LABELS.index('output_name')) else '')
                    })
                except Exception:
                    sp_entries.append({'bdmv_index': 0, 'mpls_file': '', 'm2ts_file': '', 'output_name': ''})
        selected_mpls = self.get_selected_mpls_no_ext()
        if not selected_mpls:
            self._current_cancel_event = None
            self._reset_exe_button()
            self.exe_button.setEnabled(True)
            QMessageBox.information(self, " ", "未选择原盘主mpls")
            return
        configuration: dict[int, dict[str, int | str]] = {}
        if self._is_movie_mode():
            self._refresh_movie_table2()
            configuration = getattr(self, '_movie_configuration', {}) or {}
            if not configuration:
                self._current_cancel_event = None
                self._reset_exe_button()
                self.exe_button.setEnabled(True)
                QMessageBox.information(self, " ", "配置为空，跳过更新")
                return
        else:
            try:
                bs = BluraySubtitle(
                    self.bdmv_folder_path.text(),
                    sub_files,
                    self.checkbox1.isChecked(),
                    self._update_exe_button_progress,
                    approx_episode_duration_seconds=self._get_approx_episode_duration_seconds()
                )
                configuration = bs.generate_configuration_from_selected_mpls(selected_mpls, cancel_event=cancel_event)
            except _Cancelled:
                self._current_cancel_event = None
                self._reset_exe_button()
                self.exe_button.setEnabled(True)
                return
            except Exception as e:
                self._current_cancel_event = None
                self._reset_exe_button()
                self.exe_button.setEnabled(True)
                QMessageBox.information(self, " ", traceback.format_exc())
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
            episode_output_names,
            episode_subtitle_languages,
            vspipe_mode,
            x265_mode,
            x265_params,
            sub_pack_mode,
            movie_mode=self._is_movie_mode()
        )
        self._encode_worker.moveToThread(self._encode_thread)
        self._encode_thread.started.connect(self._encode_worker.run)
        self._encode_worker.progress.connect(self._on_exe_button_progress_value)
        self._encode_worker.label.connect(self._on_exe_button_progress_text)

        def cleanup():
            self._current_cancel_event = None
            self._reset_exe_button()
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
            self._show_bottom_message('原盘压制成功！')

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
        if self._is_movie_mode():
            selected_mpls = self.get_selected_mpls_no_ext()
            if not selected_mpls:
                if not silent_mode:
                    QMessageBox.information(self, " ", "未选择原盘主mpls")
                return False

            folder_to_bdmv: dict[str, int] = {}
            bdmv_to_info: dict[int, tuple[str, str]] = {}
            for folder, mpls_no_ext in selected_mpls:
                if folder not in folder_to_bdmv:
                    folder_to_bdmv[folder] = len(folder_to_bdmv) + 1
                bdmv_to_info[folder_to_bdmv[folder]] = (folder, mpls_no_ext)

            try:
                bdmv_col = SUBTITLE_LABELS.index('bdmv_index')
            except Exception:
                bdmv_col = 4

            tasks: list[tuple[str, str, str]] = []
            for r in range(self.table2.rowCount()):
                it = self.table2.item(r, 0)
                if not it or it.checkState() != Qt.CheckState.Checked:
                    continue
                p_item = self.table2.item(r, 1)
                if not p_item or not p_item.text().strip():
                    continue
                sub_path = p_item.text().strip()
                if not os.path.exists(sub_path):
                    continue
                bdmv_item = self.table2.item(r, bdmv_col)
                try:
                    bdmv_index = int(bdmv_item.text().strip()) if bdmv_item and bdmv_item.text().strip() else 0
                except Exception:
                    bdmv_index = 0
                info = bdmv_to_info.get(bdmv_index)
                if not info:
                    continue
                folder, mpls_no_ext = info
                tasks.append((sub_path, folder, mpls_no_ext))

            if not tasks:
                if not silent_mode:
                    QMessageBox.information(self, " ", "未选择字幕文件")
                return False

            cancel_event = threading.Event()
            self._current_cancel_event = cancel_event
            self._exe_button_default_text = self.exe_button.text()
            self._exe_button_progress_value = 0
            self._exe_button_progress_text = '字幕生成中'
            self._update_exe_button_progress(0, '字幕生成中')
            self._merge_thread = QThread(self)
            self._merge_worker = MergeWorker(
                self.bdmv_folder_path.text(),
                [],
                self.checkbox1.isChecked(),
                selected_mpls,
                cancel_event,
                subtitle_suffix=self._get_subtitle_suffix()
            )
            self._merge_worker.movie_tasks = tasks
            self._merge_worker.moveToThread(self._merge_thread)
            self._merge_thread.started.connect(self._merge_worker.run)
            self._merge_worker.progress.connect(self._on_exe_button_progress_value)
            self._merge_worker.label.connect(self._on_exe_button_progress_text)

            success = False

            def cleanup():
                self._current_cancel_event = None
                self._reset_exe_button()
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
                    self._show_bottom_message("生成字幕成功！", 10000)

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
            return True

        sub_files = []
        for sub_index in range(self.table2.rowCount()):
            if self.sub_check_state[sub_index] != 2:
                continue
            item = self.table2.item(sub_index, 1)
            if item and item.text():
                sub_files.append(item.text())
        if not sub_files:
            if not silent_mode:
                QMessageBox.information(self, " ", "未选择字幕文件")
            return False

        selected_mpls = self.get_selected_mpls_no_ext()
        if not selected_mpls:
            if not silent_mode:
                QMessageBox.information(self, " ", "未选择原盘主mpls")
            return False

        cancel_event = threading.Event()
        self._current_cancel_event = cancel_event
        self._exe_button_default_text = self.exe_button.text()
        self._exe_button_progress_value = 0
        self._exe_button_progress_text = '字幕生成中'
        self._update_exe_button_progress(0, '字幕生成中')
        self._merge_thread = QThread(self)
        self._merge_worker = MergeWorker(
            self.bdmv_folder_path.text(),
            sub_files,
            self.checkbox1.isChecked(),
            selected_mpls,
            cancel_event,
            subtitle_suffix=self._get_subtitle_suffix()
        )
        self._merge_worker.moveToThread(self._merge_thread)
        self._merge_thread.started.connect(self._merge_worker.run)
        self._merge_worker.progress.connect(self._on_exe_button_progress_value)
        self._merge_worker.label.connect(self._on_exe_button_progress_text)

        success = False

        def cleanup():
            self._current_cancel_event = None
            self._reset_exe_button()
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
                self._show_bottom_message("生成字幕成功！", 10000)

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
        cancel_event = threading.Event()
        self._current_cancel_event = cancel_event
        self._exe_button_default_text = self.exe_button.text()
        self._update_exe_button_progress(0, '编辑中' if self.checkbox1.isChecked() else '混流中')
        
        # Use sorted mkv files if table is sorted, otherwise use original order
        mkv_files = self.get_mkv_files_in_table_order()
        if not mkv_files:
            mkv_files = [self.table2.item(mkv_index, 0).text() for mkv_index in range(self.table2.rowCount())]
        try:
            bs = BluraySubtitle(
                self.bdmv_folder_path.text(),
                mkv_files,
                self.checkbox1.isChecked(),
                self._update_exe_button_progress
            )
            bs.add_chapter_to_mkv(mkv_files, self.table1, cancel_event=cancel_event)
            self._current_cancel_event = None
            self._reset_exe_button()
            self.exe_button.setEnabled(True)
            if self.checkbox1.isChecked():
                self._show_bottom_message('添加章节成功，mkv章节已添加')
            else:
                self._show_bottom_message('添加章节成功，生成的新mkv文件在output文件夹下')
        except _Cancelled:
            self._current_cancel_event = None
            self._reset_exe_button()
            self.exe_button.setEnabled(True)
        except Exception as e:
            self._current_cancel_event = None
            self._reset_exe_button()
            self.exe_button.setEnabled(True)
            QMessageBox.information(self, " ", traceback.format_exc())
        else:
            bs.completion()

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
        output_folder = os.path.normpath(self.output_folder_path.text().strip()) if hasattr(self, 'output_folder_path') else ''
        if not output_folder:
            QMessageBox.information(self, " ", "未选择输出文件夹")
            return
        if not os.path.isdir(output_folder):
            QMessageBox.information(self, " ", "输出文件夹不存在")
            return
        find_mkvtoolinx()

        cancel_event = threading.Event()
        self._current_cancel_event = cancel_event
        self._exe_button_default_text = self.exe_button.text()
        self._update_exe_button_progress(0, '准备中')

        sub_files = [self.table2.item(i, 0).text() for i in range(0, self.table2.rowCount()) if self.table2.item(i, 0)]
        episode_output_names = self._get_episode_output_names_from_table2()
        episode_subtitle_languages = self._get_episode_subtitle_languages_from_table2()
        sp_entries = []
        if hasattr(self, 'table3'):
            for i in range(self.table3.rowCount()):
                try:
                    bdmv_index_item = self.table3.item(i, 0)
                    mpls_item = self.table3.item(i, 1)
                    m2ts_item = self.table3.item(i, 2)
                    sp_entries.append({
                        'bdmv_index': int(bdmv_index_item.text()) if bdmv_index_item and bdmv_index_item.text() else 0,
                        'mpls_file': mpls_item.text().strip() if mpls_item and mpls_item.text() else '',
                        'm2ts_file': m2ts_item.text().strip() if m2ts_item and m2ts_item.text() else '',
                        'output_name': (self.table3.item(i, ENCODE_SP_LABELS.index('output_name')).text().strip()
                                        if self.table3.item(i, ENCODE_SP_LABELS.index('output_name')) else '')
                    })
                except Exception:
                    sp_entries.append({'bdmv_index': 0, 'mpls_file': '', 'm2ts_file': '', 'output_name': ''})
        selected_mpls = self.get_selected_mpls_no_ext()
        if not selected_mpls:
            self._current_cancel_event = None
            self._reset_exe_button()
            self.exe_button.setEnabled(True)
            QMessageBox.information(self, " ", "未选择原盘主mpls")
            return
        configuration: dict[int, dict[str, int | str]] = {}
        if self._is_movie_mode():
            self._refresh_movie_table2()
            configuration = getattr(self, '_movie_configuration', {}) or {}
            if not configuration:
                self._current_cancel_event = None
                self._reset_exe_button()
                self.exe_button.setEnabled(True)
                QMessageBox.information(self, " ", "配置为空，跳过更新")
                return
        else:
            try:
                bs = BluraySubtitle(
                    self.bdmv_folder_path.text(),
                    sub_files,
                    self.checkbox1.isChecked(),
                    self._update_exe_button_progress,
                    approx_episode_duration_seconds=self._get_approx_episode_duration_seconds()
                )
                configuration = bs.generate_configuration_from_selected_mpls(selected_mpls, cancel_event=cancel_event)
            except _Cancelled:
                self._current_cancel_event = None
                self._reset_exe_button()
                self.exe_button.setEnabled(True)
                return
            except Exception as e:
                self._current_cancel_event = None
                self._reset_exe_button()
                self.exe_button.setEnabled(True)
                QMessageBox.information(self, " ", traceback.format_exc())
                return

        self._remux_thread = QThread(self)
        self._remux_worker = RemuxWorker(
            self.bdmv_folder_path.text(),
            sub_files,
            self.checkbox1.isChecked(),
            output_folder,
            configuration,
            selected_mpls,
            cancel_event,
            sp_entries,
            episode_output_names,
            episode_subtitle_languages,
            movie_mode=self._is_movie_mode()
        )
        self._remux_worker.moveToThread(self._remux_thread)
        self._remux_thread.started.connect(self._remux_worker.run)
        self._remux_worker.progress.connect(self._on_exe_button_progress_value)
        self._remux_worker.label.connect(self._on_exe_button_progress_text)

        def cleanup():
            self._current_cancel_event = None
            self._reset_exe_button()
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
            self._show_bottom_message('原盘remux成功！')

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
        self.box_title = title

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            e.accept()
        else:
            e.ignore()

    def dropEvent(self, e: QDropEvent):
        if not e.mimeData().hasUrls():
            return
        url = e.mimeData().urls()[0]
        if not url.isLocalFile():
            return
        dropped_path = os.path.normpath(url.toLocalFile())

        w: Optional[QWidget] = self
        while w and not hasattr(w, 'bdmv_folder_path'):
            w = w.parentWidget()
        if not w:
            w = self.window()
        if not w:
            return

        if self.box_title == '原盘' and hasattr(w, 'bdmv_folder_path'):
            w.bdmv_folder_path.setText(dropped_path)
        if self.box_title == '字幕' and hasattr(w, 'subtitle_folder_path'):
            w.subtitle_folder_path.setText(dropped_path)


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
            MKV_INFO_PATH = QFileDialog.getOpenFileName(window, translate_text('选择mkvinfo的位置'), '', 'mkvinfo*')
    global MKV_MERGE_PATH
    if not MKV_MERGE_PATH:
        if sys.platform == 'win32':
            default_mkv_merge_path = r'C:\Program Files\MKVToolNix\mkvmerge.exe'
        else:
            default_mkv_merge_path = '/usr/bin/mkvmerge'
        if os.path.exists(default_mkv_merge_path):
            MKV_MERGE_PATH = default_mkv_merge_path
        else:
            MKV_MERGE_PATH = QFileDialog.getOpenFileName(window, translate_text('选择mkvmerge的位置'), '', 'mkvmerge*')
    global MKV_PROP_EDIT_PATH
    if not MKV_PROP_EDIT_PATH:
        if sys.platform == 'win32':
            default_mkv_prop_edit_path = r'C:\Program Files\MKVToolNix\mkvpropedit.exe'
        else:
            default_mkv_prop_edit_path = '/usr/bin/mkvpropedit'
        if os.path.exists(default_mkv_prop_edit_path):
            MKV_PROP_EDIT_PATH = default_mkv_prop_edit_path
        else:
            MKV_PROP_EDIT_PATH = QFileDialog.getOpenFileName(window, translate_text('选择mkvpropedit的位置'), '', 'mkvpropedit*')
    global MKV_EXTRACT_PATH
    if not MKV_EXTRACT_PATH:
        if sys.platform == 'win32':
            default_mkv_extract_path = r'C:\Program Files\MKVToolNix\mkvextract.exe'
        else:
            default_mkv_extract_path = '/usr/bin/mkvextract'
        if os.path.exists(default_mkv_extract_path):
            MKV_EXTRACT_PATH = default_mkv_extract_path
        else:
            MKV_EXTRACT_PATH = QFileDialog.getOpenFileName(window, translate_text('选择mkvextract的位置'), '', 'mkvextract*')


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
    base_font = app.font()
    base_font.setPointSize(8)
    app.setFont(base_font)
    app.setStyleSheet('''     
        QMainWindow {
            background-color: white;
        }

        QWidget {
            background-color: #F5F5F5;
        }

        * {
            font-size: 8pt;
        }

        QVBoxLayout, QHBoxLayout {
            spacing: 6px;
            margin: 0px;
        }

        QGroupBox {
            border: 1px solid #CCCCCC;
            margin-top: 10px;
            padding: 4px;
        }

        QGroupBox[noTitle="true"] {
            margin-top: 0px;
        }

        QGroupBox[noMargin="true"] {
            margin-top: 0px;
            padding: 0px;
        }

        QGroupBox[tightGroup="true"] {
            margin-top: 12px;
            padding: 10px 4px 4px 4px;
        }

        QGroupBox[compactTitle="true"] {
            margin-top: 6px;
            padding: 0px;
        }

        QGroupBox::title {
            subcontrol-origin: margin;
            subcontrol-position: top left;
            left: 8px;
            padding: 0 2px;
        }

        QLabel {
            margin: 0px;
            padding: 0px;
            font-size: 8pt;
        }

        QLineEdit {
            font-size: 8pt;
            padding: 1px;
            border: 1px solid #DDDDDD;
            border-radius: 3px;
        }

        QComboBox {
            font-size: 8pt;
            padding: 0px 3px;
        }

        QPlainTextEdit {
            font-size: 8pt;
            padding: 1px;
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
            padding: 2px 6px;
            font-size: 8pt;
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
            padding: 2px 4px;
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
            padding: 2px;
        }

        QTableView::item {
            padding: 0px 2px;
        }

        QTableView::item:selected {
            background-color: #BBBBBB;
            color: white;
        }   
        
        QCheckBox {
            spacing: 2px;
            font-size: 8pt;
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
            spacing: 2px;
            font-size: 8pt;
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
        
        QTableView::item:hover {
            background-color: #f0f0f0; /* 确保是一个实色，而不是半透明色 */
        }

        QTableView::indicator:hover {
            background-color: transparent; 
            border: none;
        }
                
        QMenu {
            font-size: 8pt;
        } 
        '''
                      )
    window = BluraySubtitleGUI()
    window.show()
    try:
        def fit_window_to_available_screen():
            screen = window.screen() or app.primaryScreen()
            if not screen:
                return
            avail = screen.availableGeometry()
            if avail.height() > 1200:
                return
            fg = window.frameGeometry()
            chrome_h = max(0, fg.height() - window.height())
            chrome_w = max(0, fg.width() - window.width())
            target_w = max(200, min(window.width(), max(200, avail.width() - chrome_w)))
            target_h = max(200, avail.height() - chrome_h)
            window.resize(target_w, target_h)

            fg2 = window.frameGeometry()
            x = min(max(fg2.x(), avail.left()), avail.right() - fg2.width() + 1)
            y = avail.top()
            window.move(x, y)

            fg3 = window.frameGeometry()
            if fg3.bottom() > avail.bottom():
                window.move(x, avail.bottom() - fg3.height() + 1)

        QTimer.singleShot(0, fit_window_to_available_screen)
    except Exception:
        pass
    sys.exit(app.exec())
