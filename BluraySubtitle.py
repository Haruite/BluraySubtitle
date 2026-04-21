# Feature 1: generate merged subtitles
# Feature 2: add chapters to MKV files
# Feature 3: Blu-ray remux
# Feature 4: Blu-ray encode
# Features 2/3/4 require mkvtoolnix and FLAC_PATH/FLAC_THREADS (flac >= 1.5.0)
# Features 3/4 require FFMPEG_PATH and FFPROBE_PATH
# Feature 4 requires vapoursynth and vspipe(.exe)/x265(.exe) in PATH
# pip install pycountry PyQt6 librosa
import _io
import builtins
import copy
import ctypes
import datetime
import time
import json
import locale
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
from typing import BinaryIO, Callable, Generator, Optional
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
from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QFileDialog, QLabel, QToolButton, QLineEdit,
    QMessageBox, QHBoxLayout, QGroupBox, QCheckBox, QProgressDialog, QProgressBar, QRadioButton, QButtonGroup,
    QTableWidget, QTableWidgetItem, QDialog, QPushButton, QComboBox, QMenu, QAbstractItemView, QPlainTextEdit,
    QSizePolicy, QHeaderView, QInputDialog, QTabBar, QSlider, QSplitter)

if sys.platform == 'win32':
    import winreg


FLAC_PATH = r'C:\Downloads\flac-1.5.0-win\Win64\flac.exe'  # flac executable path
FLAC_THREADS = 20  # flac thread count
FFMPEG_PATH = r'C:\Downloads\ffmpeg-8.1-essentials_build\bin\ffmpeg.exe'  # ffmpeg executable path
FFPROBE_PATH = r'C:\Downloads\ffmpeg-8.1-essentials_build\bin\ffprobe.exe'  # ffprobe executable path
X265_PATH = r'C:\Software\x265.exe'  # x265 executable path
VSEDIT_PATH = r'C:\Software\vapoursynth\vsedit.exe'  # vapoursynth editor path


def is_docker():
    path = '/proc/self/cgroup'
    return (
            os.path.exists('/.dockerenv') or
            os.path.isfile(path) and any('docker' in line for line in open(path))
    )


if sys.platform != 'win32':  # non-Windows platform defaults
    FLAC_PATH = '/usr/bin/flac'  # flac executable path
    FFMPEG_PATH = '/usr/bin/ffmpeg'  # ffmpeg executable path
    FFPROBE_PATH = '/usr/bin/ffprobe'  # ffprobe executable path
    X265_PATH = '/usr/bin/x265'  # x265 executable path
    PLUGIN_PATH = os.path.expanduser('~/plugins')  # plugin directory
    VSEDIT_PATH = r'/usr/bin/vsedit'  # vapoursynth editor path
    if is_docker():
        PLUGIN_PATH = '/app/plugins'


MKV_INFO_PATH = ''
MKV_MERGE_PATH = ''
MKV_PROP_EDIT_PATH = ''
MKV_EXTRACT_PATH = ''
BDMV_LABELS = ['path', 'size', 'info', 'remux_cmd']
SUBTITLE_LABELS = ['select', 'path', 'sub_duration', 'ep_duration', 'bdmv_index', 'chapter_index', 'offset', 'warning']
MKV_LABELS = ['path', 'duration']
REMUX_LABELS = ['sub_path', 'language', 'ep_duration', 'bdmv_index', 'start_at_chapter', 'end_at_chapter', 'm2ts_file', 'output_name', 'play']
ENCODE_LABELS = ['sub_path', 'language', 'ep_duration', 'bdmv_index', 'start_at_chapter', 'end_at_chapter', 'm2ts_file', 'output_name', 'vpy_path', 'edit_vpy', 'preview_script', 'play']
ENCODE_SP_LABELS = ['select', 'bdmv_index', 'mpls_file', 'm2ts_file', 'duration', 'output_name', 'tracks', 'vpy_path', 'edit_vpy', 'preview_script', 'play']
ENCODE_REMUX_LABELS = ['sub_path', 'language', 'ep_duration', 'output_name', 'vpy_path', 'edit_vpy', 'preview_script', 'play', 'edit_tracks', 'edit_chapters', 'edit_attachments']
ENCODE_REMUX_SP_LABELS = ['duration', 'output_name', 'vpy_path', 'edit_vpy', 'preview_script', 'play', 'edit_tracks', 'edit_chapters', 'edit_attachments']
CONFIGURATION = {}
DEFAULT_APPROX_EPISODE_DURATION_SECONDS = 24 * 60  # default approx. minutes→seconds for episode split heuristics
CURRENT_UI_LANGUAGE = 'en'
APP_TITLE = 'BluraySubtitle v3.1+'


def get_mkvtoolnix_ui_language() -> str:
    if CURRENT_UI_LANGUAGE == 'zh':
        return 'zh_CN'
    return 'en' if sys.platform == 'win32' else 'en_US'


def mkvtoolnix_ui_language_arg() -> str:
    return f'--ui-language {get_mkvtoolnix_ui_language()}'

I18N_ZH_TO_EN = {
    'BluraySubtitle': 'BluraySubtitle',
    '语言': 'Language',
    '模式': 'Mode',
    '浅色': 'Light',
    '深色': 'Dark',
    '彩色': 'Colorful',
    '透明度': 'Opacity',
    '选择功能': 'Function',
    '剧集模式': 'Series mode',
    '电影模式': 'Movie mode',
    '每集时长大约（分钟）：': 'Approx. episode length (minutes):',
    '可能需要剧集模式': 'May require series mode',
    '添加后缀': 'Add suffix',
    '编辑轨道': 'edit tracks',
    '编辑章节': 'edit chapters',
    '编辑附件': 'edit attachments',
    '选择所有轨道': 'Select all tracks',
    'Select all tracks': 'Select all tracks',
    '全选': 'Select all',
    '提取': 'extract',
    '生成合并字幕': 'Merge Subtitles',
    '给mkv添加章节': 'Add Chapters To MKV',
    '原盘remux': 'Blu-ray Remux',
    '原盘压制': 'Blu-ray Encode',
    '原盘': 'Blu-ray',
    '字幕': 'Subtitles',
    '选择原盘所在的文件夹': 'Select the Blu-ray folder',
    '选择 remux 所在的文件夹': 'Select the remux folder',
    '选择文件夹': 'Select folder',
    '选择单集字幕所在的文件夹': 'Select the subtitle folder',
    '选择单集字幕所在的文件夹：': 'Select the subtitle folder:',
    '选择mkv文件所在的文件夹': 'Select the MKV folder',
    '选择字幕文件所在的文件夹（可选）': 'Select the subtitle folder (optional)',
    '补全蓝光目录': 'Complete Blu-ray Folder',
    '直接编辑原文件': 'Edit Original File Directly',
    '输出文件夹': 'Output Folder',
    '选择': 'Select',
    '确定': 'OK',
    '取消': 'Cancel',
    '保存': 'Save',
    '关闭': 'Close',
    '复制信息': 'Copy Info',
    '保存失败，请检查': 'Save failed, please check',
    '保存章节成功！': 'Chapters saved!',
    '打开': 'Open',
    '添加附件': 'Add Attachment',
    '替换': 'Replace',
    '更新': 'Update',
    '删除': 'Delete',
    '刷新': 'Refresh',
    '请选择附件': 'Select attachment file',
    '未找到 mkvpropedit': 'mkvpropedit not found',
    '附件操作成功！': 'Attachment updated!',
    '附件操作失败，请检查': 'Attachment update failed, please check',
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
    '（点击取消）': '(click to cancel)',
    '选择m2ts文件': 'Select M2TS File',
    '检测到多个 m2ts 文件，请选择要预览的文件：': 'Multiple M2TS files detected, choose one for preview:',
    '检测到多个字幕文件，请选择要预览的文件：': 'Multiple subtitle files detected, choose one for preview:',
    '选择vpy文件': 'Select VPy File',
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
    '分析轨道：': 'Analyzing tracks: ',
    '混流中：': 'Muxing: ',
    '多集分片回退：': 'Multi-episode split fallback: ',
    '混流回退（多集分片对齐）：': 'Mux fallback (multi-episode split aligned): ',
    '多集分片回退失败：': 'Multi-episode split fallback failed: ',
    '（见终端 [remux-fallback-split]）': ' (see terminal [remux-fallback-split])',
    '混流回退（多 m2ts 对齐）：': 'Mux fallback (multi-m2ts aligned): ',
    '压缩音轨：': 'Compressing audio: ',
    '压制并混流：': 'Encode and mux: ',
    '压制并混流 SPs：': 'Encode and mux SPs: ',
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
    '时长: ': 'Duration: ',
    'FFmpeg 执行出错: ': 'FFmpeg error: ',
    'ffmpeg 压缩的flac文件比原音轨大，将删除 ｢': 'ffmpeg-compressed FLAC is larger than the original track, deleting ｢',
    'flac 压缩 wav 文件 ｢': 'flac compressing wav file ｢',
    'flac 文件比原音轨大，将删除 ｢': 'FLAC is larger than the original track, deleting ｢',
    '多进程加载失败，切换到单进程: ': 'Multiprocess load failed, switching to single process: ',
    '字幕拖入处理失败，请检查字幕文件和原盘路径': 'Subtitle drag-in failed, please check the subtitle files and Blu-ray path',
    '字幕文件 ｢': 'Subtitle file ｢',
    '字幕文件加载失败 ｢': 'Failed to load subtitle file ｢',
    '字幕文件加载失败': 'Failed to load subtitle file',
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
    ' 个': ' items',
    ' 个字幕文件': ' subtitle files',
    '多进程解析失败，切换到单进程模式: ': 'Multiprocessing parse failed, switching to single-process: ',
    '多进程解析失败，切换到单进程模式（mode）: ': 'Multiprocessing parse failed, switching to single-process mode: ',
    '配置为空，跳过更新': 'Configuration is empty, skipping update',
    '章节': 'Chapters',
    '编辑字幕': 'Edit Subtitle',
    '查看章节': 'view chapters',
    '播放': 'play',
    '预览': 'preview',
    '编辑vpy': 'edit_vpy',
    '编辑': 'edit',
    '目录: ': 'folder: ',
    '切片时间: ': 'in_out_time: ',
    '章节标记: ': 'mark_info: ',
    '章节写入: BD卷 ': 'add_chapter_to_mkv: BD Vol ',
    ' MKV数(': ' MKV 数 (',
    ') 与配置集数(': ') 与配置集数 (',
    ') 不一致，处理前 ': ') 不一致，处理前 ',
    '[M2TS.get_first_pts] PID 0x': '[M2TS.get_first_pts] first PTS from PID 0x',
    '[语言修正] 未找到 mkvpropedit，跳过: ': '[lang-fix] mkvpropedit not found, skip: ',
    '[语言修正] 输入 identify 为空: ': '[lang-fix] input identify empty: ',
    '[语言修正] 输出 identify 为空: ': '[lang-fix] output identify empty: ',
    '[语言修正] ': '[lang-fix] ',
    '[语言修正] mkvpropedit 失败 rc=': '[lang-fix] mkvpropedit failed rc=',
    '[语言修正] 标准输出:\n': '[lang-fix] stdout:\n',
    '[语言修正] 标准错误:\n': '[lang-fix] stderr:\n',
    '[语言修正] shell 回退失败 rc=': '[lang-fix] shell fallback failed rc=',
    '[语言修正] 异常回退失败 rc=': '[lang-fix] exception fallback failed rc=',
    '[混流回退] 丢弃非公共轨位: ': '[remux-fallback] drop non-common slots: ',
    '[混流回退] 缺少首个m2ts: ': '[remux-fallback] missing first m2ts: ',
    '[混流回退] 首个m2ts没有可参考轨位': '[remux-fallback] no reference track slots from ffprobe on first m2ts',
    '[混流回退] 缺少m2ts: ': '[remux-fallback] missing m2ts: ',
    '[混流回退] 无法映射 ffprobe PID 到 mkvmerge 轨道ID: ': '[remux-fallback] could not map ffprobe PIDs to mkvmerge ids for ',
    '[混流回退] 缺少参考音轨 pid=0x': '[remux-fallback] missing reference audio stream for pid=0x',
    '[混流回退] 生成静音轨失败 pid=0x': '[remux-fallback] failed creating silence track for pid=0x',
    '[混流回退] 分片混流失败 rc=': '[remux-fallback] part mux failed rc=',
    ' 索引=': ' idx=',
    '[混流回退] 分片输出缺失: ': '[remux-fallback] missing part output after mux: ',
    '[混流回退] 拼接命令: ': '[remux-fallback] concat: ',
    '[混流回退] 拼接失败 rc=': '[remux-fallback] concat failed rc=',
    '[分片回退] 跳过: 输出路径为空或电影模式': '[remux-fallback-split] skip: empty output path or movie_mode',
    '[分片回退] 跳过: 播放列表仅有 ': '[remux-fallback-split] skip: playlist has only ',
    ' 个 clip': ' clip(s)',
    '[分片回退] 缺少首个m2ts: ': '[remux-fallback-split] missing first m2ts: ',
    '[分片回退] 首个m2ts没有可参考轨位': '[remux-fallback-split] no reference track slots from ffprobe on first m2ts',
    '[分片回退] 缺少m2ts: ': '[remux-fallback-split] missing m2ts: ',
    '[分片回退] 无法映射 ffprobe PID: ': '[remux-fallback-split] could not map ffprobe PIDs for ',
    '[分片回退] 缺少参考音轨 pid=0x': '[remux-fallback-split] missing reference audio stream for pid=0x',
    '[分片回退] 生成静音失败 pid=0x': '[remux-fallback-split] failed creating silence for pid=0x',
    '[分片回退] 分片混流失败 rc=': '[remux-fallback-split] part mux failed rc=',
    ' 集=': ' seg=',
    ' 片段=': ' clip=',
    '[分片回退] 分片输出缺失: ': '[remux-fallback-split] missing part after mux: ',
    '[分片回退] 第 ': '[remux-fallback-split] segment ',
    ' 段拼接: ': ': ',
    '[分片回退] 分段拼接失败 rc=': '[remux-fallback-split] segment concat failed rc=',
    '[分片回退] 输出缺失: ': '[remux-fallback-split] missing output: ',
    '[分片回退] BD卷 ': '[remux-fallback-split] failed for BD_Vol_',
    ' 回退失败（见上方日志）': ' (see logs above)',
    '[分片回退] 跳过: 需要至少2个分段; ': '[remux-fallback-split] skip: need 2+ episode segments; ',
    '分段数=': 'segments=',
    ' 预期文件数=': ' expected_files=',
    '[分片回退] 开始: ': '[remux-fallback-split] start: ',
    ' 集 -> ': ' episodes -> ',
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
        if not src or src not in result:
            continue
        # For plain ASCII words, only replace whole tokens (e.g. avoid "mkvextract" -> "mkv extract").
        if re.fullmatch(r'[A-Za-z0-9_]+', src):
            result = re.sub(rf'(?<![A-Za-z0-9_]){re.escape(src)}(?![A-Za-z0-9_])', mapping[src], result)
        else:
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
        # Reference: https://github.com/lw/BluRay/wiki/PlayItem

        # in_out_time is an ordered list of tuples for playback items.
        # tuple[0] is clip filename, tuple[1] is in_time, tuple[2] is out_time.
        # Clip playback duration is (out_time - in_time) / 45000.
        self.in_out_time: list[tuple[str, int, int]] = []

        # mark_info is a dict where:
        # key ref_to_play_item_id maps to an index in in_out_time,
        # value is a list of chapter mark timestamps mark_timestamp.
        # Timeline offset in MPLS is:
        # (mark_timestamp - in_time) / 45000 + sum(previous clip durations).
        # Example (from BanG Dream! It's MyGO!!!!! Blu-ray vol.1):
        # in_out_time = [('00000', 1647000000, 1711414350), ('00001', 1647000000, 1710963900), ...]
        # mark_info = {0: [1647000000, 1655188805, 1689886593, 1706626441, 1710676738],
        # 1: [1647000000, 1649522520, 1653570939, 1685023610, 1706174115, 1710224411], ...}
        # For mark_info key=1, timestamp 1649522520:
        # ref_to_play_item_id=1 => in_out_time[1] is ('00001', 1647000000, 1710963900).
        # Local offset is (1649522520 - 1647000000) / 45000 = 56.056s.
        # Previous clip duration is (1711414350 - 1647000000) / 45000 = 1431.43s.
        # Final playlist position is 1431.43 + 56.056 = 1487.486s (24:47.486).
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

    def get_total_time(self):  # total playlist duration
        return sum(map(lambda x: (x[2] - x[1]) / 45000, self.in_out_time))

    def get_total_time_no_repeat(self):  # playlist duration counting repeated clips only once
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
                    try:  # parse each line defensively to avoid failing whole merge on malformed rows
                        elements = ([line[:line.index(':')]]
                                    + list(map(lambda _attr: _attr.strip(), line[line.index(':') + 1:].split(','))))
                        if not self.event_attrs:
                            self.event_attrs += elements
                        else:
                            event = Event()
                            if len(elements) > len(self.event_attrs):  # subtitle text itself contains commas
                                elements = (elements[:len(self.event_attrs) - 1] +
                                            [','.join(elements[len(self.event_attrs) - 1:])])
                            for i, attr in enumerate(elements):
                                key = self.event_attrs[i]
                                if key.lower() in ('start', 'end'):  # convert Start/End timestamp text to timedelta
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
                if end_set:  # ensure there are still candidate end times
                    max_end_1 = max(end_set)
                    if max_end_1 < max_end - 300:
                        return max_end_1  # cap abnormally long events (e.g., commentary stream exceeding episode end)
                return max_end
            return 0
        except Exception as e:
            print(f'Failed to get subtitle duration: {str(e)}')
            return 0


def _parse_subtitle_worker(file_path: str) -> tuple[str, Subtitle | None]:
    try:
        return file_path, Subtitle(file_path)
    except Exception as e:
        print(f'Subtitle file ｢{file_path}｣ parse failed: {str(e)}')
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
    frame_size = 192
    _TS_PACKET = 188
    _SYNC = 0x47

    def __init__(self, filename: str):
        self.filename = filename

    @staticmethod
    def _pts_from_pes_header(p: bytes) -> int:
        pts = ((p[0] >> 1) & 0x07) << 30
        val = p[1] << 8 | p[2]
        pts |= (val >> 1) << 15
        val = p[3] << 8 | p[4]
        pts |= val >> 1
        return pts

    @staticmethod
    def _pes_payload_after_pointer(payload: bytes) -> bytes:
        if not payload:
            return b''
        pf = payload[0]
        after = payload[1 + pf:]
        if after.startswith(b'\x00\x00\x01'):
            return after
        if payload.startswith(b'\x00\x00\x01'):
            return payload
        return after

    @staticmethod
    def _ts_payload(pkt: bytes) -> tuple[Optional[bytes], int, bool]:
        if len(pkt) < M2TS._TS_PACKET or pkt[0] != M2TS._SYNC:
            return None, -1, False
        if pkt[1] & 0x80:
            pass
        pid = ((pkt[1] & 0x1F) << 8) | pkt[2]
        pusi = (pkt[1] & 0x40) != 0
        afc = (pkt[3] & 0x30) >> 4
        off = 4
        if afc & 2:
            if off >= len(pkt):
                return None, pid, pusi
            adapt_len = pkt[4]
            off = 5 + adapt_len
            if off > len(pkt):
                return None, pid, pusi
        if (afc & 1) == 0:
            return None, pid, pusi
        return pkt[off:M2TS._TS_PACKET], pid, pusi

    @staticmethod
    def _file_size(stream: BinaryIO) -> int:
        try:
            pos = stream.tell()
            stream.seek(0, os.SEEK_END)
            n = stream.tell()
            stream.seek(pos)
            return int(n)
        except OSError:
            return 256 * 1024

    @staticmethod
    def _score_alignment(buf: bytes, phase: int, stride: int, sync_off: int) -> int:
        c = 0
        pos = phase + sync_off
        while pos + M2TS._TS_PACKET <= len(buf):
            if buf[pos] == M2TS._SYNC:
                c += 1
            pos += stride
        return c

    @staticmethod
    def _best_phase_for_params(buf: bytes, stride: int, sync_off: int) -> tuple[int, int]:
        best_p, best_s = 0, -1
        for phase in range(stride):
            s = M2TS._score_alignment(buf, phase, stride, sync_off)
            if s > best_s:
                best_s = s
                best_p = phase
        return best_p, best_s

    @staticmethod
    def _choose_transport_layout(stream: BinaryIO, m2ts: Optional[bool]) -> tuple[int, int, int]:
        pos = stream.tell()
        sample = stream.read(min(512 * 1024, max(M2TS._file_size(stream), 512 * 1024)))
        stream.seek(pos)

        if m2ts is not None:
            stride, off = (M2TS.frame_size, 4) if m2ts else (M2TS._TS_PACKET, 0)
            phase, _ = M2TS._best_phase_for_params(sample, stride, off)
            return phase, stride, off

        best: tuple[int, int, int, int] = (-1, 0, M2TS.frame_size, 4)
        for stride, sync_off in ((M2TS.frame_size, 4), (M2TS._TS_PACKET, 0), (M2TS.frame_size, 0)):
            phase, score = M2TS._best_phase_for_params(sample, stride, sync_off)
            if score > best[0]:
                best = (score, phase, stride, sync_off)
        return best[1], best[2], best[3]

    @staticmethod
    def _scan_first_pts(
        stream: BinaryIO,
        *,
        m2ts: Optional[bool] = None,
        max_bytes: Optional[int] = None,
        skip_pids: Optional[set[int]] = None,
        debug: bool = False,
    ) -> Optional[int]:
        skip = skip_pids or set()
        skip |= {0x0000, 0x1FFF}

        start_phase, spacing, sync_off = M2TS._choose_transport_layout(stream, m2ts)
        stream.seek(start_phase)
        if debug:
            print(
                f'[M2TS.get_first_pts] seek={start_phase} stride={spacing} sync_off={sync_off}',
                file=sys.stderr,
            )

        pending: dict[int, bytearray] = {}
        total_read = 0
        pending_max = 256 * 1024

        while True:
            block = stream.read(spacing)
            if len(block) < spacing:
                break
            total_read += len(block)
            if max_bytes is not None and total_read > max_bytes:
                break
            if sync_off + M2TS._TS_PACKET > len(block):
                break
            pkt = block[sync_off:sync_off + M2TS._TS_PACKET]
            if pkt[0] != M2TS._SYNC:
                continue

            payload, pid, pusi = M2TS._ts_payload(pkt)
            if payload is None or pid in skip:
                continue

            if pusi:
                if not payload:
                    pending.pop(pid, None)
                    continue
                pf = payload[0]
                if not payload.startswith(b'\x00\x00\x01') and 1 + pf > len(payload):
                    pending.pop(pid, None)
                    continue
                pending[pid] = bytearray(M2TS._pes_payload_after_pointer(payload))
            else:
                if pid not in pending:
                    continue
                pending[pid].extend(payload)
                if len(pending[pid]) > pending_max:
                    pending.pop(pid, None)
                    continue

            buf = pending.get(pid)
            if not buf or len(buf) < 9:
                continue

            if buf[0:3] != b'\x00\x00\x01':
                pending.pop(pid, None)
                continue

            flags_hi = buf[6]
            if (flags_hi & 0xC0) != 0x80:
                pending.pop(pid, None)
                continue

            flags_lo = buf[7]
            pes_hdr_remain = buf[8]
            need = 9 + pes_hdr_remain
            if len(buf) < need:
                continue

            if (flags_lo & 0xC0) == 0:
                pending.pop(pid, None)
                continue

            if len(buf) < 14:
                continue

            pts = M2TS._pts_from_pes_header(bytes(buf[9:14]))
            pending.pop(pid, None)
            if debug:
                print(
                    f'{translate_text("[M2TS.get_first_pts] first PTS from PID 0x")}{pid:04x}'
                    f'{translate_text(" = ")}{pts}',
                    file=sys.stderr
                )
            return pts

        return None

    def get_first_pts(
        self,
        *,
        m2ts: Optional[bool] = None,
        max_bytes: Optional[int] = None,
        skip_pids: Optional[set[int]] = None,
        debug: bool = False,
    ) -> Optional[int]:
        """First presentation timestamp (90 kHz units) from elementary streams, or None."""
        with open(self.filename, 'rb') as f:
            pts = M2TS._scan_first_pts(f, m2ts=m2ts, max_bytes=max_bytes, skip_pids=skip_pids, debug=debug)
        if pts is not None:
            return pts
        if m2ts is not None:
            return None
        for forced in (True, False):
            with open(self.filename, 'rb') as f:
                pts = M2TS._scan_first_pts(f, m2ts=forced, max_bytes=max_bytes, skip_pids=skip_pids, debug=debug)
            if pts is not None:
                return pts
        return None

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
                 approx_episode_duration_seconds: float = DEFAULT_APPROX_EPISODE_DURATION_SECONDS,
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
        self._sp_index_by_bdmv: dict[int, int] = {}
        try:
            val = float(approx_episode_duration_seconds)
            self.approx_episode_duration_seconds = val if val > 0 else DEFAULT_APPROX_EPISODE_DURATION_SECONDS
        except Exception:
            self.approx_episode_duration_seconds = DEFAULT_APPROX_EPISODE_DURATION_SECONDS

    def t(self, text: str) -> str:
        return translate_text(str(text), getattr(self, '_language_code', CURRENT_UI_LANGUAGE))

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
        """Preload subtitles into cache with platform-aware fallback strategy."""
        if not file_paths:
            return
        missing = [p for p in file_paths if p and p not in self._subtitle_cache]
        if not missing:
            return
        
        # Choose loading strategy by platform.
        if sys.platform == 'win32':
            # Windows: use multiprocessing directly.
            self._preload_subtitles_multiprocess(missing, cancel_event)
        else:
            # Linux: try multiprocessing first, then fall back to single process.
            try:
                self._preload_subtitles_multiprocess(missing, cancel_event)
            except Exception as e:
                print(f'Multiprocessing parse failed, switching to single-process mode: {str(e)}')
                self._preload_subtitles_single(missing, cancel_event)
    
    def _preload_subtitles_single(self, file_paths: list[str], cancel_event: Optional[threading.Event] = None):
        """Parse subtitles in single-process mode."""
        for p in file_paths:
            if cancel_event and cancel_event.is_set():
                raise _Cancelled()
            try:
                self._subtitle_cache[p] = Subtitle(p)
            except Exception as e:
                print(f'Failed to load subtitle file ｢{p}｣: {str(e)}')
    
    def _preload_subtitles_multiprocess(self, file_paths: list[str], cancel_event: Optional[threading.Event] = None):
        """Parse subtitles in multiprocessing mode."""
        if len(file_paths) == 1:
            p = file_paths[0]
            try:
                self._subtitle_cache[p] = Subtitle(p)
            except Exception as e:
                print(f'Failed to load subtitle file ｢{p}｣: {str(e)}')
            return

        # On Linux, exit in worker subprocess to avoid recursive window spawning.
        if sys.platform != 'win32' and multiprocessing.current_process().name != 'MainProcess':
            return

        max_workers = min(len(file_paths), os.cpu_count() or 1)

        # Select multiprocessing context for Linux/Windows compatibility.
        if sys.platform == 'win32':
            mp_context = multiprocessing.get_context('spawn')
        else:
            # Linux defaults to fork; more stable for GUI, but requires __main__ guard.
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
                            print(f'Failed to load subtitle file ｢{p}｣: {str(e)}')
                        else:
                            print(f'Failed to load subtitle file: {str(e)}')
        except Exception as e:
            # Propagate exception so caller can decide fallback behavior.
            raise Exception(f'Multiprocessing parse failed: {str(e)}')

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
                            print(f'\033[31mError, m2ts file ｢{m2ts_file}｣ in ｢{mpls_file_path}｣ not found\033[0m')
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
        # 1) Find first audio language from the first m2ts of selected main mpls.
        first_audio_lang = ''
        try:
            chapter = Chapter(mpls_path)
            if chapter.in_out_time:
                first_m2ts = os.path.join(os.path.dirname(os.path.dirname(mpls_path)), 'STREAM', chapter.in_out_time[0][0] + '.m2ts')
                mkvmerge_info = BluraySubtitle._pid_lang_from_mkvmerge_json(first_m2ts)
                if mkvmerge_info:
                    exe = MKV_MERGE_PATH if MKV_MERGE_PATH else 'mkvmerge'
                    p = subprocess.run(
                        [exe, "--identify", "--identification-format", "json", first_m2ts],
                        capture_output=True,
                        text=True,
                        encoding='utf-8',
                        errors='ignore',
                        shell=False
                    )
                    data = json.loads(p.stdout or "{}")
                    tracks = data.get('tracks') or []
                    for tr in tracks:
                        if isinstance(tr, dict) and str(tr.get('type') or '') == 'audio':
                            props = tr.get('properties') or {}
                            if isinstance(props, dict):
                                first_audio_lang = str(props.get('language') or '').strip().lower()
                            break
        except Exception:
            first_audio_lang = ''

        def _read_xml_title(xml_path: str) -> str:
            try:
                tree = et.parse(xml_path)
                _folder = tree.getroot()
                ns = {'di': 'urn:BDA:bdmv;discinfo'}
                node = _folder.find('.//di:name', ns)
                return (node.text or '').strip() if node is not None else ''
            except Exception:
                return ''

        if os.path.isdir(meta_folder):
            xml_files = sorted([f for f in os.listdir(meta_folder) if f.lower().endswith('.xml')])
            xml_map = {f.lower(): f for f in xml_files}
            # 2) Prefer XML title matching first-audio language.
            lang_candidates = []
            if first_audio_lang:
                lang_candidates.append(first_audio_lang)
                if first_audio_lang == 'jpn':
                    lang_candidates += ['ja', 'jpn']
                if first_audio_lang in ('zho', 'chi'):
                    lang_candidates += ['zh', 'zho', 'chi']
                if first_audio_lang == 'eng':
                    lang_candidates += ['en', 'eng']
            for lang in lang_candidates:
                for f in xml_files:
                    low = f.lower()
                    if low.startswith('bdmt_') and (low.endswith(f'_{lang}.xml') or low == f'bdmt_{lang}.xml'):
                        output_name = _read_xml_title(os.path.join(meta_folder, f))
                        if output_name:
                            break
                if output_name:
                    break
            # 3) Fallback by system language preference.
            if not output_name:
                try:
                    loc = locale.getlocale()
                    sys_lang = (loc[0] or '').lower() if isinstance(loc, tuple) and loc else ''
                except Exception:
                    sys_lang = ''
                prefer = ['zho', 'chi', 'zh'] if sys_lang.startswith('zh') else ['eng', 'en']
                for lang in prefer:
                    f = xml_map.get(f'bdmt_{lang}.xml')
                    if f:
                        output_name = _read_xml_title(os.path.join(meta_folder, f))
                        if output_name:
                            break
            # 4) Fallback first xml title.
            if not output_name:
                for f in xml_files:
                    output_name = _read_xml_title(os.path.join(meta_folder, f))
                    if output_name:
                        break
        # 5) No xml title -> use outer folder name of selected bluray input path.
        if not output_name:
            try:
                base = os.path.basename(os.path.normpath(str(getattr(self, 'bdmv_path', '') or '')).rstrip(os.sep))
                output_name = base or os.path.split(mpls_path[:-24])[-1]
            except Exception:
                output_name = os.path.split(mpls_path[:-24])[-1]
        char_map = {
            '?': '？', '*': '★', '<': '《', '>': '》', ':': '：', '"': "'", '/': '／', '\\': '／', '|': '￨'
        }
        output_name = ''.join(char_map.get(char) or char for char in output_name)
        cache[selected_mpls_no_ext] = output_name
        return output_name

    @staticmethod
    def _configuration_default_chapter_segments_checked(
        configuration: dict[int, dict[str, int | str]],
    ) -> None:
        for v in configuration.values():
            v.setdefault('chapter_segments_fully_checked', True)

    def generate_configuration(self, table: QTableWidget,
                               sub_combo_index: Optional[dict[int, int]] = None,
                               subtitle_index: Optional[int] = None) -> dict[int, dict[str, int | str]]:
        configuration = {}
        sub_index = 0
        bdmv_index = 0
        global CONFIGURATION
        approx_end_time = float(getattr(self, 'approx_episode_duration_seconds', DEFAULT_APPROX_EPISODE_DURATION_SECONDS)
                                or DEFAULT_APPROX_EPISODE_DURATION_SECONDS)
        if self.sub_files:
            # Always use single process in main thread to avoid multiprocessing edge cases.
            missing = [p for p in self.sub_files if p and p not in self._subtitle_cache]
            if missing:
                # Use single-process loading directly in main thread.
                for p in missing:
                    try:
                        self._subtitle_cache[p] = Subtitle(p)
                    except Exception as e:
                        print(f'Failed to load subtitle file ｢{p}｣: {str(e)}')
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
            self._configuration_default_chapter_segments_checked(configuration)
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
        self._configuration_default_chapter_segments_checked(configuration)
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
        approx_end_time = float(getattr(self, 'approx_episode_duration_seconds', DEFAULT_APPROX_EPISODE_DURATION_SECONDS)
                                or DEFAULT_APPROX_EPISODE_DURATION_SECONDS)

        if self.sub_files:
            # Always use single process in main thread to avoid multiprocessing edge cases.
            missing = [p for p in self.sub_files if p and p not in self._subtitle_cache]
            if missing:
                # Use single-process loading directly in main thread.
                for p in missing:
                    try:
                        self._subtitle_cache[p] = Subtitle(p)
                    except Exception as e:
                        print(f'Failed to load subtitle file ｢{p}｣: {str(e)}')
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
            self._configuration_default_chapter_segments_checked(configuration)
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
        self._configuration_default_chapter_segments_checked(configuration)
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
                    self._progress(text='Writing Subtitle File')
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
        self._progress(text='Writing Subtitle File')
        if hasattr(sub, 'content'):
            suffix = str(getattr(self, 'subtitle_suffix', '') or '')
            sub.dump(conf['folder'] + suffix, conf['selected_mpls'] + suffix)
        self._progress(1000)

    def _group_mkv_paths_by_bdmv(self, sorted_paths: list[str], bdmv_keys: list[int]) -> dict[int, list[str]]:
        """Map episode MKV paths to configuration bdmv_index (from BD_Vol_XXX in filename)."""
        if not sorted_paths:
            return {k: [] for k in bdmv_keys}
        if len(bdmv_keys) == 1:
            return {bdmv_keys[0]: list(sorted_paths)}
        out: dict[int, list[str]] = {k: [] for k in bdmv_keys}
        for p in sorted_paths:
            m = re.search(r'BD_Vol_(\d{3})', os.path.basename(p or ''), re.I)
            if m:
                try:
                    v = int(m.group(1))
                except Exception:
                    continue
                if v in out:
                    out[v].append(p)
        return out

    def _write_remux_segment_chapter_txt(
        self,
        mpls_path: str,
        start_chapter: int,
        end_chapter: int,
        out_path: str,
    ) -> None:
        """Write OGM chapter file for one episode remux segment.

        Episode covers MPLS chapter marks with indices ``start_chapter`` .. ``end_chapter - 1``
        (same half-open interval as split). For each original mark ``j`` in that range:
        new index is ``j - start_chapter + 1`` (e.g. start 11 → new 01..06 for j=11..16),
        timestamp is ``offset(j) - offset(start_chapter)`` (first chapter is always 0).
        """
        chapter = Chapter(mpls_path)
        _, index_to_offset = get_index_to_m2ts_and_offset(chapter)
        rows = sum(map(len, chapter.mark_info.values()))
        total_end = rows + 1
        s = max(1, min(int(start_chapter), total_end))
        e = max(s + 1, min(int(end_chapter), total_end))
        t0 = float(index_to_offset.get(s, 0.0))

        lines: list[str] = []
        for j in range(s, e):
            if j > rows:
                break
            new_idx = j - s + 1
            off = float(index_to_offset.get(j, 0.0))
            rel = max(0.0, off - t0)
            append_ogm_chapter_lines(lines, new_idx, rel)
        out_dir = os.path.dirname(out_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(out_path, 'w', encoding='utf-8-sig') as f:
            f.write('\n'.join(lines) + ('\n' if lines else ''))

    def _ordered_episode_confs_by_bdmv(
        self, configuration: dict[int, dict[str, int | str]]
    ) -> dict[int, list[dict[str, int | str]]]:
        by_bdmv: dict[int, list[dict[str, int | str]]] = {}
        for _, conf in (configuration or {}).items():
            bdmv_index = int(conf.get('bdmv_index') or 0)
            by_bdmv.setdefault(bdmv_index, []).append(conf)
        for bdmv_index, confs in by_bdmv.items():
            try:
                confs.sort(key=lambda c: int(c.get('chapter_index') or c.get('start_at_chapter') or 0))
            except Exception:
                pass
            by_bdmv[bdmv_index] = confs
        return by_bdmv

    def _add_chapter_to_mkv_from_configuration(
        self,
        mkv_files: list[str],
        configuration: dict[int, dict[str, int | str]],
        cancel_event: Optional[threading.Event] = None,
    ) -> None:
        by_bdmv = self._ordered_episode_confs_by_bdmv(configuration)
        bdmv_keys = sorted(by_bdmv.keys())
        sorted_paths = sorted(mkv_files, key=self._mkv_sort_key)
        grouped = self._group_mkv_paths_by_bdmv(sorted_paths, bdmv_keys)
        total_mkv = sum(len(grouped.get(b, [])) for b in bdmv_keys)
        done = 0
        chapter_txt = os.path.join(os.getcwd(), 'chapter.txt')
        for bdmv_index in bdmv_keys:
            paths = grouped.get(bdmv_index, [])
            confs = by_bdmv.get(bdmv_index, [])
            n = min(len(paths), len(confs))
            if len(paths) != len(confs):
                print(
                    f'{self.t("章节写入: BD卷 ")}{bdmv_index}'
                    f'{self.t(" MKV数(")}{len(paths)}'
                    f'{self.t(") 与配置集数(")}{len(confs)}'
                    f'{self.t(") 不一致，处理前 ")}{n}{self.t(" 个")}'
                )
            rows_cache: dict[str, int] = {}
            for i in range(n):
                if cancel_event and cancel_event.is_set():
                    raise _Cancelled()
                conf = confs[i]
                mkv_path = paths[i]
                mpls_key = str(conf.get('selected_mpls') or '').strip()
                if not mpls_key:
                    continue
                mpls_path = mpls_key if mpls_key.lower().endswith('.mpls') else mpls_key + '.mpls'
                if mpls_key not in rows_cache:
                    ch = Chapter(mpls_path)
                    rows_cache[mpls_key] = sum(map(len, ch.mark_info.values()))
                rows = rows_cache[mpls_key]
                total_end = rows + 1
                s = int(conf.get('start_at_chapter') or conf.get('chapter_index') or 1)
                if conf.get('end_at_chapter'):
                    e = int(conf.get('end_at_chapter') or total_end)
                elif i + 1 < len(confs):
                    e = int(confs[i + 1].get('start_at_chapter') or confs[i + 1].get('chapter_index') or total_end)
                else:
                    e = total_end
                s = max(1, min(s, total_end))
                e = max(s + 1, min(e, total_end))
                self._write_remux_segment_chapter_txt(mpls_path, s, e, chapter_txt)
                MKV(mkv_path).add_chapter(self.checked)
                done += 1
                self._progress(int(done / max(total_mkv, 1) * 1000))
        self._progress(1000)

    def _add_chapter_to_mkv_by_duration(
        self,
        mkv_files: list[str],
        table: Optional[QTableWidget] = None,
        selected_mpls: Optional[list[tuple[str, str]]] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> None:
        mkv_index = 0
        def _vol_from_name(p: str) -> Optional[int]:
            m = re.search(r'BD_Vol_(\d{3})', os.path.basename(p or ''))
            if not m:
                return None
            try:
                return int(m.group(1))
            except Exception:
                return None
        mkv_files = sorted(mkv_files, key=self._mkv_sort_key)
        current_target_vol = _vol_from_name(mkv_files[0]) if mkv_files else None
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
            while mkv_index < len(mkv_files):
                v = _vol_from_name(mkv_files[mkv_index])
                if current_target_vol is None or v is None or v == current_target_vol:
                    break
                mkv_index += 1
            if mkv_index >= len(mkv_files):
                break
            duration = MKV(mkv_files[mkv_index]).get_duration()
            print(f'{self.t("folder: ")}{folder}')
            print(f'{self.t("in_out_time: ")}{chapter.in_out_time}')
            print(f'{self.t("mark_info: ")}{chapter.mark_info}')
            print(f'{self.t("Episode: ")}{mkv_index + 1}, {self.t("Duration: ")}{duration}')

            play_item_duration_time_sum = 0
            episode_duration_time_sum = 0
            chapter_id = 0
            chapter_text = []
            volume_done = False
            for ref_to_play_item_id, mark_timestamps in chapter.mark_info.items():
                if volume_done:
                    break
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
                        if mkv_index >= len(mkv_files):
                            volume_done = True
                            break
                        next_vol = _vol_from_name(mkv_files[mkv_index])
                        if current_target_vol is not None and next_vol is not None and next_vol != current_target_vol:
                            volume_done = True
                            break
                        duration = MKV(mkv_files[mkv_index]).get_duration()
                        print(f'{self.t("Episode: ")}{mkv_index + 1}, {self.t("Duration: ")}{duration}')
                        chapter_text.clear()

                    chapter_id += 1
                    append_ogm_chapter_lines(chapter_text, chapter_id, max(0.0, float(real_time)))
                play_item_duration_time_sum += (out_time - in_time) / 45000

            with open(f'chapter.txt', 'w', encoding='utf-8-sig') as f:
                f.write('\n'.join(chapter_text))
            if mkv_index < len(mkv_files):
                this_vol = _vol_from_name(mkv_files[mkv_index])
                if current_target_vol is None or this_vol is None or this_vol == current_target_vol:
                    mkv = MKV(mkv_files[mkv_index])
                    mkv.add_chapter(self.checked)
                    self._progress(int((mkv_index + 1) / len(mkv_files) * 1000))
                    mkv_index += 1
            current_target_vol = None
            if mkv_index < len(mkv_files):
                current_target_vol = _vol_from_name(mkv_files[mkv_index])

        self._progress(1000)

    def add_chapter_to_mkv(
        self,
        mkv_files,
        table: Optional[QTableWidget] = None,
        selected_mpls: Optional[list[tuple[str, str]]] = None,
        cancel_event: Optional[threading.Event] = None,
        configuration: Optional[dict[int, dict[str, int | str]]] = None,
    ):
        """Apply chapters to each episode MKV from configuration (remux / encode).

        For an episode with ``start_at_chapter=11`` and ``end_at_chapter=17``, writes six
        entries ``Chapter 01``..``Chapter 06`` at times 0 and ``offset(j)-offset(11)`` for
        MPLS marks ``j`` = 11..16 (new ordinal = ``j - 10`` in that example).
        """
        cfg = configuration if configuration is not None else self.configuration
        if cfg:
            self._add_chapter_to_mkv_from_configuration(mkv_files, cfg, cancel_event=cancel_event)
        else:
            self._add_chapter_to_mkv_by_duration(mkv_files, table, selected_mpls, cancel_event=cancel_event)

    def completion(self):  # complete Blu-ray folder; remove temporary files
        """Finalize folder layout after processing and clean temporary artifacts."""
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
        selected_counts: dict[int, int] = {}
        for e in sp_entries:
            try:
                b = int(e.get('bdmv_index') or 0)
            except Exception:
                b = 0
            if b <= 0:
                continue
            if not bool(e.get('selected', True)):
                continue
            selected_counts[b] = selected_counts.get(b, 0) + 1
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
            selected = bool(entry.get('selected', True))
            if (not selected) or (not output_name):
                continue

            sp_mkv_path = ''
            src_path = ''
            first_m2ts_for_lang = ''
            use_chapter_language = False
            if mpls_file:
                sp_index_by_bdmv[sp_bdmv_index] = sp_index_by_bdmv.get(sp_bdmv_index, 0) + 1
                width = max(2, len(str(max(selected_counts.get(sp_bdmv_index, 1), 1))))
                sp_no = str(sp_index_by_bdmv[sp_bdmv_index]).zfill(width)
                sp_mkv_path = os.path.join(sps_folder, f'BD_Vol_{bdmv_vol}_SP{sp_no}.mkv')
                src_path = os.path.join(playlist_dir, mpls_file)
                use_chapter_language = True
                try:
                    ch_lang = Chapter(src_path)
                    index_to_m2ts, _ = get_index_to_m2ts_and_offset(ch_lang)
                    if index_to_m2ts:
                        first_key = sorted(index_to_m2ts.keys())[0]
                        first_m2ts_for_lang = os.path.join(stream_dir, index_to_m2ts[first_key])
                except Exception:
                    first_m2ts_for_lang = ''
            else:
                m2ts_files = [x.strip() for x in m2ts_file.split(',') if x.strip()]
                if m2ts_files:
                    m2ts_name = m2ts_files[0]
                    src_path = os.path.join(stream_dir, m2ts_name)
                    ext = '.mka' if BluraySubtitle._is_audio_only_media(src_path) else '.mkv'
                    sp_mkv_path = os.path.join(sps_folder, f'BD_Vol_{bdmv_vol}_{m2ts_name[:-5]}{ext}')
                    first_m2ts_for_lang = src_path

            if not src_path or not sp_mkv_path:
                continue
            config_key = BluraySubtitle._sp_track_key_from_entry(entry)
            try:
                tracks_cfg = getattr(self, 'track_selection_config', {}) or {}
                if (isinstance(tracks_cfg, dict)
                        and mpls_file
                        and config_key not in tracks_cfg):
                    main_key = f'main::{os.path.normpath(main_mpls_path)}'
                    if main_key in tracks_cfg:
                        mcfg = tracks_cfg.get(main_key) or {}
                        tracks_cfg[config_key] = {
                            'audio': list(mcfg.get('audio') or []),
                            'subtitle': list(mcfg.get('subtitle') or []),
                        }
            except Exception:
                pass
            pid_to_lang: dict[int, str] = {}
            if use_chapter_language:
                try:
                    ch_pid = Chapter(src_path)
                    ch_pid.get_pid_to_language()
                    pid_to_lang = ch_pid.pid_to_lang
                except Exception:
                    pid_to_lang = {}
            copy_audio_track, copy_sub_track = self._select_tracks_for_source(
                src_path,
                pid_to_lang,
                config_key=config_key
            )
            if output_name:
                if single_volume:
                    output_name = re.sub(rf'(?i)^BD_Vol_{bdmv_vol}_', '', output_name)
                sp_mkv_path = os.path.join(sps_folder, output_name)
            if single_volume:
                base_name = os.path.basename(sp_mkv_path)
                base_name = re.sub(rf'(?i)^BD_Vol_{bdmv_vol}_', '', base_name)
                sp_mkv_path = os.path.join(sps_folder, base_name)

            # Special image output modes from UI output name.
            if output_name.lower().endswith('.png') or ('.' not in os.path.basename(output_name)):
                m2ts_list = [x.strip() for x in m2ts_file.split(',') if x.strip()]
                if use_chapter_language:
                    try:
                        ch = Chapter(src_path)
                        idx_to_m2ts, _ = get_index_to_m2ts_and_offset(ch)
                        m2ts_list = [v for _, v in sorted(idx_to_m2ts.items())]
                    except Exception:
                        m2ts_list = []
                stream_dir = os.path.join(os.path.dirname(playlist_dir), 'STREAM')
                if output_name.lower().endswith('.png'):
                    if m2ts_list:
                        src_frame = os.path.join(stream_dir, m2ts_list[0])
                        subprocess.Popen(
                            f'"{FFMPEG_PATH}" -y -i "{src_frame}" -frames:v 1 -update 1 "{sp_mkv_path}"',
                            shell=True
                        ).wait()
                        if os.path.exists(sp_mkv_path):
                            created.append((entry_idx, sp_mkv_path))
                    continue
                folder_out = sp_mkv_path
                os.makedirs(folder_out, exist_ok=True)
                width = max(2, len(str(max(len(m2ts_list), 1))))
                for n, m2 in enumerate(m2ts_list, start=1):
                    src_frame = os.path.join(stream_dir, m2)
                    stem = os.path.splitext(os.path.basename(m2))[0]
                    out_png = os.path.join(folder_out, f'{str(n).zfill(width)}-{stem}.png')
                    subprocess.Popen(
                        f'"{FFMPEG_PATH}" -y -i "{src_frame}" -frames:v 1 -update 1 "{out_png}"',
                        shell=True
                    ).wait()
                created.append((entry_idx, folder_out))
                continue

            # Single selected audio track with raw extension: extract directly.
            out_ext = os.path.splitext(sp_mkv_path)[1].lower()
            if out_ext not in ('.mkv', '.mka'):
                if len(copy_audio_track) == 1 and len(copy_sub_track) == 0:
                    map_idx = str(copy_audio_track[0]).strip()
                    if out_ext == '.flac':
                        src_for_flac = first_m2ts_for_lang or src_path
                        BluraySubtitle._compress_audio_stream_to_flac(src_for_flac, map_idx, sp_mkv_path)
                    else:
                        subprocess.Popen(
                            f'"{FFMPEG_PATH}" -y -i "{src_path}" -map 0:{map_idx} -c copy "{sp_mkv_path}"',
                            shell=True
                        ).wait()
                    if os.path.exists(sp_mkv_path):
                        created.append((entry_idx, sp_mkv_path))
                continue

            chapter_txt = os.path.join(sps_folder, f'{os.path.splitext(os.path.basename(sp_mkv_path))[0]}.chapter.txt')
            
            # Check if this is a custom chapter segment (e.g. chapter_3_to_chapter_6, beginning_to_chapter_4, chapter_33_to_ending)
            custom_chapter = False
            custom_parts = ''
            if re.search(r'(beginning|chapter_\d+)_to_(chapter_\d+|ending)', output_name, re.IGNORECASE):
                custom_chapter = True
                # Generate custom chapter file
                self._write_custom_chapter_for_segment(main_mpls_path, chapter_txt, output_name)
                try:
                    ch_tmp = Chapter(main_mpls_path)
                    _i2m, i2o = get_index_to_m2ts_and_offset(ch_tmp)
                    rows_tmp = sum(map(len, ch_tmp.mark_info.values()))
                    total_end = rows_tmp + 1
                    m = re.search(r'(beginning|chapter_(\d+))_to_(chapter_(\d+)|ending)', output_name, re.IGNORECASE)
                    if m:
                        start_idx = 1 if (m.group(1) or '').lower() == 'beginning' else int(m.group(2) or 1)
                        end_idx = total_end if (m.group(3) or '').lower() == 'ending' else int(m.group(4) or total_end)
                        start_idx = max(1, min(start_idx, total_end))
                        end_idx = max(start_idx + 1, min(end_idx, total_end))
                        st = get_time_str(float(i2o.get(start_idx, 0.0)))
                        ed = get_time_str(float(ch_tmp.get_total_time() if end_idx >= total_end else i2o.get(end_idx, ch_tmp.get_total_time())))
                        if st == '0':
                            st = '00:00:00.000'
                        if ed == '0':
                            ed = '00:00:00.000'
                        custom_parts = f'{st}-{ed}'
                except Exception:
                    custom_parts = ''
            
            if use_chapter_language or custom_chapter:
                if not custom_chapter:
                    try:
                        offs = self._write_chapter_txt_from_mpls(src_path, chapter_txt)
                        if not offs or len(offs) == 1 and offs[0] == 0.0:
                            force_remove_file(chapter_txt)
                    except Exception:
                        traceback.print_exc()
                split_custom = (f'--split parts:{custom_parts} ' if custom_parts else '')
                cmd = (f'"{MKV_MERGE_PATH}" {mkvtoolnix_ui_language_arg()} '
                       f'{split_custom}'
                       f'--chapters "{chapter_txt}" '
                       f'-o "{sp_mkv_path}" '
                       f'{("-a " + ",".join(copy_audio_track)) if copy_audio_track else ""} '
                       f'{("-s " + ",".join(copy_sub_track)) if copy_sub_track else ""} '
                       f'"{src_path}"')
            else:
                cmd = (f'"{MKV_MERGE_PATH}" {mkvtoolnix_ui_language_arg()} -o "{sp_mkv_path}" '
                       f'{("-a " + ",".join(copy_audio_track)) if copy_audio_track else ""} '
                       f'{("-s " + ",".join(copy_sub_track)) if copy_sub_track else ""} '
                       f'"{src_path}"')
            ret_sp = subprocess.Popen(cmd, shell=True).wait()
            sp_ok = os.path.isfile(sp_mkv_path)
            if not sp_ok and (use_chapter_language or custom_chapter):
                stem_out, ext_out = os.path.splitext(sp_mkv_path)
                for suf in ('-001', '-01'):
                    alt_out = f'{stem_out}{suf}{ext_out}'
                    if os.path.isfile(alt_out):
                        sp_ok = True
                        break
            mux_failed = (ret_sp != 0 or not sp_ok)
            if mux_failed and str(src_path).lower().endswith('.mpls'):
                try:
                    n_fc = len(Chapter(src_path).in_out_time or [])
                except Exception:
                    n_fc = 0
                # Full-playlist concat does not reproduce ``--split parts:custom_parts`` windows from main MPLS.
                if n_fc > 1 and not (custom_chapter and str(custom_parts).strip()):
                    cover_sp = ''
                    try:
                        meta_folder = os.path.join(src_path[:-19], 'META', 'DL')
                        if os.path.isdir(meta_folder):
                            c_sz = 0
                            for fn in os.listdir(meta_folder):
                                if fn.lower().endswith(('.jpg', '.jpeg', '.png', '.bmp', '.webp')):
                                    fp = os.path.join(meta_folder, fn)
                                    try:
                                        sz = os.path.getsize(fp)
                                        if sz > c_sz:
                                            cover_sp, c_sz = fp, sz
                                    except Exception:
                                        pass
                    except Exception:
                        cover_sp = ''
                    if self._try_remux_mpls_track_aligned_concat(
                        os.path.normpath(src_path),
                        os.path.normpath(sp_mkv_path),
                        copy_audio_track,
                        copy_sub_track,
                        cover_sp,
                        cancel_event=cancel_event,
                    ):
                        sp_ok = os.path.isfile(sp_mkv_path)
                        mux_failed = not sp_ok
            if mux_failed:
                try:
                    force_remove_file(chapter_txt)
                except Exception:
                    pass
                continue
            if use_chapter_language and sp_mkv_path.lower().endswith('.mkv') and os.path.exists(sp_mkv_path):
                try:
                    subprocess.Popen(f'"{MKV_PROP_EDIT_PATH}" {mkvtoolnix_ui_language_arg()} "{sp_mkv_path}" --chapters ""', shell=True).wait()
                    if os.path.exists(chapter_txt):
                        subprocess.Popen(f'"{MKV_PROP_EDIT_PATH}" {mkvtoolnix_ui_language_arg()} "{sp_mkv_path}" --chapters "{chapter_txt}"', shell=True).wait()
                        force_remove_file(chapter_txt)
                except:
                    pass
            try:
                if sp_mkv_path.lower().endswith(('.mkv', '.mka')) and first_m2ts_for_lang and pid_to_lang:
                    BluraySubtitle._fix_output_track_languages_with_mkvpropedit(
                        sp_mkv_path,
                        first_m2ts_for_lang,
                        pid_to_lang,
                        copy_audio_track,
                        copy_sub_track
                    )
            except Exception:
                pass
            if os.path.exists(sp_mkv_path):
                created.append((entry_idx, sp_mkv_path))
        return created

    def _write_chapter_txt_from_mpls(self, mpls_path: str, chapter_txt_path: str) -> list[float]:
        chapter = Chapter(mpls_path)
        mark_info = chapter.mark_info
        in_out_time = chapter.in_out_time
        mpls_duration = chapter.get_total_time()

        offsets = []
        offset = 0
        for ref_to_play_item_id, mark_timestamps in mark_info.items():
            for mark_timestamp in mark_timestamps:
                off = offset + (mark_timestamp - in_out_time[ref_to_play_item_id][1]) / 45000
                if mpls_duration - off >= 0.001:
                    offsets.append(off)
            offset += (in_out_time[ref_to_play_item_id][2] - in_out_time[ref_to_play_item_id][1]) / 45000

        offs = []
        for off in offsets:
            if off not in offs:
                offs.append(off)

        lines: list[str] = []
        for i, off in enumerate(offs, start=1):
            append_ogm_chapter_lines(lines, i, off)
        os.makedirs(os.path.dirname(chapter_txt_path) or '.', exist_ok=True)
        with open(chapter_txt_path, 'w', encoding='utf-8-sig') as f:
            f.write('\n'.join(lines) + ('\n' if lines else ''))
        return offs

    def _get_chapter_offsets(self, mpls_path: str) -> list[float]:
        chapter = Chapter(mpls_path)
        mark_info = chapter.mark_info
        in_out_time = chapter.in_out_time
        mpls_duration = chapter.get_total_time()

        offsets = []
        offset = 0
        for ref_to_play_item_id, mark_timestamps in mark_info.items():
            for mark_timestamp in mark_timestamps:
                off = offset + (mark_timestamp - in_out_time[ref_to_play_item_id][1]) / 45000
                if mpls_duration - off >= 0.001:
                    offsets.append(off)
            offset += (in_out_time[ref_to_play_item_id][2] - in_out_time[ref_to_play_item_id][1]) / 45000

        offs = []
        for off in offsets:
            if off not in offs:
                offs.append(off)
        return offs

    def _write_custom_chapter_for_segment(self, mpls_path: str, chapter_txt_path: str, output_name: str):
        """Parse SP suffix like beginning_to_chapter_4, chapter_33_to_chapter_40, chapter_33_to_ending; same bounds as --split parts."""
        m = re.search(r'(beginning|chapter_(\d+))_to_(chapter_(\d+)|ending)', output_name, re.IGNORECASE)
        if not m:
            return
        chapter = Chapter(mpls_path)
        rows = sum(map(len, chapter.mark_info.values()))
        total_end = rows + 1
        start_idx = 1 if (m.group(1) or '').lower() == 'beginning' else int(m.group(2) or 1)
        g3 = (m.group(3) or '').lower()
        if g3 == 'ending':
            end_idx = total_end
        else:
            end_idx = int(m.group(4) or total_end)
        start_idx = max(1, min(start_idx, total_end))
        end_idx = max(start_idx + 1, min(end_idx, total_end))
        self._write_remux_segment_chapter_txt(mpls_path, start_idx, end_idx, chapter_txt_path)

    def _mkv_sort_key(self, p: str):
        name = os.path.basename(p)
        m = re.search(r'BD_Vol_(\d{3})', name)
        vol = int(m.group(1)) if m else 9999
        m2 = re.search(r'-(\d{3})\.mkv$', name, re.IGNORECASE)
        seg = int(m2.group(1)) if m2 else 0
        return vol, seg, name.lower()

    @staticmethod
    def _default_track_selection_from_streams(
        streams: list[dict[str, object]],
        pid_to_lang: Optional[dict[int, str]] = None
    ) -> tuple[list[str], list[str]]:
        streams = streams or []
        pid_lang = pid_to_lang or {}
        def _parse_pid(raw_id: object) -> Optional[int]:
            s = str(raw_id or '').strip()
            if not s:
                return None
            try:
                if s.lower().startswith('0x'):
                    return int(s, 16)
                if any(c in 'abcdefABCDEF' for c in s):
                    return int(s, 16)
                return int(s, 10)
            except Exception:
                try:
                    return int(s, 16)
                except Exception:
                    return None

        def _get_lang(stream_info: dict[str, object]) -> str:
            pid = _parse_pid(stream_info.get('id'))
            if pid is not None and pid in pid_lang:
                return str(pid_lang.get(pid, 'und') or 'und')
            try:
                idx = int(str(stream_info.get('index') or '').strip())
                if idx in pid_lang:
                    return str(pid_lang.get(idx, 'und') or 'und')
            except Exception:
                pass
            return 'und'

        audio_type_weight = {'': -1, 'aac': 1, 'ac3': 2, 'eac3': 3, 'lpcm': 4, 'dts': 5, 'dts_hd_ma': 6, 'truehd': 7}
        selected_eng_audio_track = ['', '']
        selected_zho_audio_track = ['', '']
        copy_sub_track: list[str] = []
        for stream_info in streams:
            codec_type = str(stream_info.get('codec_type') or '')
            if codec_type == 'audio':
                codec_name = str(stream_info.get('codec_name') or '')
                if codec_name == 'dts' and str(stream_info.get('profile') or '') == 'DTS-HD MA':
                    codec_name = 'dts_hd_ma'
                lang = _get_lang(stream_info)
                idx = str(stream_info.get('index') or '')
                if lang == 'eng':
                    if not selected_eng_audio_track[1] or audio_type_weight.get(codec_name, -1) > audio_type_weight.get(selected_eng_audio_track[1], -1):
                        selected_eng_audio_track = [idx, codec_name]
                elif lang == 'zho':
                    if not selected_zho_audio_track[1] or audio_type_weight.get(codec_name, -1) > audio_type_weight.get(selected_zho_audio_track[1], -1):
                        selected_zho_audio_track = [idx, codec_name]
            elif codec_type == 'subtitle':
                lang = _get_lang(stream_info)
                if lang in ['eng', 'zho']:
                    copy_sub_track.append(str(stream_info.get('index') or ''))
        if not copy_sub_track:
            for stream_info in streams:
                if str(stream_info.get('codec_type') or '') == 'subtitle':
                    copy_sub_track.append(str(stream_info.get('index') or ''))
                    break
        if not selected_zho_audio_track[0] and not selected_eng_audio_track[0]:
            copy_audio_track: list[str] = []
            for stream_info in streams:
                if str(stream_info.get('codec_type') or '') == 'audio':
                    copy_audio_track.append(str(stream_info.get('index') or ''))
                    break
            for stream_info in streams:
                if str(stream_info.get('codec_type') or '') == 'audio':
                    lang = _get_lang(stream_info)
                    idx = str(stream_info.get('index') or '')
                    if lang == 'jpn' and idx not in copy_audio_track:
                        copy_audio_track.append(idx)
        else:
            if selected_eng_audio_track[0] and selected_zho_audio_track[0]:
                copy_audio_track = [selected_eng_audio_track[0], selected_zho_audio_track[0]]
            elif not selected_eng_audio_track[0]:
                copy_audio_track = [selected_zho_audio_track[0]]
            else:
                copy_audio_track = [selected_eng_audio_track[0]]
            first_audio_index = 1
            for stream_info in streams:
                if str(stream_info.get('codec_type') or '') == 'audio':
                    first_audio_index = stream_info.get('index') or 1
                    break
            if str(first_audio_index) not in (selected_zho_audio_track[0], selected_eng_audio_track[0]):
                copy_audio_track.append(str(first_audio_index))
        return [x for x in copy_audio_track if x != ''], [x for x in copy_sub_track if x != '']

    @staticmethod
    def _ffprobe_streams(media_path: str) -> list[dict[str, object]]:
        if not media_path or not os.path.exists(media_path):
            return []
        exe = FFPROBE_PATH if FFPROBE_PATH else 'ffprobe'
        try:
            p = subprocess.run(
                [exe, "-v", "error", "-show_streams", "-of", "json", media_path],
                capture_output=True,
                text=True,
                shell=False
            )
        except Exception:
            return []
        if p.returncode != 0:
            return []
        try:
            data = json.loads(p.stdout or "{}")
            streams = data.get('streams') or []
            return streams if isinstance(streams, list) else []
        except Exception:
            return []

    @staticmethod
    def _ffprobe_stream_service_id(stream: dict) -> Optional[int]:
        """MPEG-TS elementary stream id from ffprobe ``streams[]`` (field ``id``, e.g. ``0x1011``)."""
        if not isinstance(stream, dict):
            return None
        raw = stream.get('id')
        if raw is None:
            return None
        try:
            if isinstance(raw, int):
                return int(raw) & 0xFFFF
            s = str(raw).strip()
            if s.lower().startswith('0x'):
                return int(s, 16)
            return int(s, 0)
        except Exception:
            return None

    @staticmethod
    def _ffprobe_stream_index_to_service_pid(m2ts_path: str) -> dict[int, int]:
        """Map ffprobe / mkvmerge stream index (0,1,…) → TS PID from ``streams[].id``. m2ts has no reliable language tags."""
        out: dict[int, int] = {}
        for s in BluraySubtitle._ffprobe_streams(m2ts_path) or []:
            if not isinstance(s, dict):
                continue
            if str(s.get('codec_type') or '') not in ('video', 'audio', 'subtitle', 'subtitles'):
                continue
            try:
                idx = int(s.get('index'))
            except Exception:
                continue
            pid = BluraySubtitle._ffprobe_stream_service_id(s)
            if pid is not None:
                out[idx] = pid
        return out

    @staticmethod
    def _ffprobe_video_frame_count_static(media_path: str) -> int:
        if not media_path or not os.path.exists(media_path):
            return -1
        exe = FFPROBE_PATH if FFPROBE_PATH else 'ffprobe'
        cmd = [exe, "-v", "error", "-count_frames", "-select_streams", "v:0",
               "-show_entries", "stream=nb_read_frames,nb_frames", "-of", "json", media_path]
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore', shell=False)
        except Exception:
            return -1
        if p.returncode != 0:
            return -1
        try:
            data = json.loads(p.stdout or "{}")
        except Exception:
            return -1
        streams = data.get('streams') or []
        if not streams:
            return -2
        s0 = streams[0] if isinstance(streams[0], dict) else {}
        for k in ('nb_read_frames', 'nb_frames'):
            try:
                v = int(str(s0.get(k) or '').strip())
                if v >= 0:
                    return v
            except Exception:
                pass
        return -1

    @staticmethod
    def _is_audio_only_media(media_path: str) -> bool:
        streams = BluraySubtitle._ffprobe_streams(media_path)
        if not streams:
            return False
        has_audio = False
        has_video = False
        for s in streams:
            c = str(s.get('codec_type') or '')
            if c == 'audio':
                has_audio = True
            elif c == 'video':
                has_video = True
        return has_audio and (not has_video)

    @staticmethod
    def _extract_single_audio_from_mka(output_file: str):
        if not output_file or not os.path.exists(output_file):
            return
        if not str(output_file).lower().endswith('.mka'):
            return
        streams = BluraySubtitle._ffprobe_streams(output_file)
        audio_streams = [s for s in streams if str(s.get('codec_type') or '') == 'audio']
        if len(audio_streams) != 1:
            return
        codec = str(audio_streams[0].get('codec_name') or '').lower()
        ext_map = {
            'flac': 'flac',
            'wav': 'wav',
            'pcm_s16le': 'wav',
            'pcm_s24le': 'wav',
            'pcm_s32le': 'wav',
            'pcm_bluray': 'wav',
            'dts': 'dts',
            'truehd': 'thd',
            'mlp': 'thd',
            'ac3': 'ac3',
            'eac3': 'eac3',
            'aac': 'm4a',
            'opus': 'opus',
        }
        ext = ext_map.get(codec, codec or 'audio')
        if ext == 'mka':
            return
        dst = os.path.splitext(output_file)[0] + f'.{ext}'
        cmd = f'"{FFMPEG_PATH}" -hide_banner -loglevel error -y -i "{output_file}" -map 0:a:0 -c copy "{dst}"'
        try:
            p = subprocess.run(cmd, shell=True, capture_output=True, text=True, encoding='utf-8', errors='ignore')
            if p.returncode == 0 and os.path.exists(dst):
                os.remove(output_file)
        except Exception:
            pass

    @staticmethod
    def _is_silent_audio_file(path: str, threshold_db: float = -60.0) -> tuple[bool, float]:
        y = None
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
                    f'"{FFMPEG_PATH}" -hide_banner -loglevel error -y -i "{path}" -ac 1 -ar 22050 -c:a pcm_s16le "{tmp}"',
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

    @staticmethod
    def _compress_audio_stream_to_flac(input_media: str, map_idx: str, out_flac: str) -> bool:
        if not input_media or not os.path.exists(input_media):
            return False
        if not out_flac:
            return False
        os.makedirs(os.path.dirname(out_flac) or '.', exist_ok=True)
        owns_tmp = True
        lower = str(input_media).lower()
        if lower.endswith(('.wav', '.w64')):
            tmp_wav = input_media
            owns_tmp = False
        else:
            fd, tmp_wav = tempfile.mkstemp(prefix=f"sp_audio_{os.getpid()}_", suffix=".wav")
            os.close(fd)
        tmp_wav2 = ''
        try:
            if owns_tmp:
                subprocess.Popen(
                    f'"{FFMPEG_PATH}" -hide_banner -loglevel error -y -i "{input_media}" -map 0:{map_idx} -c:a pcm_s24le -f w64 "{tmp_wav}"',
                    shell=True
                ).wait()
                if not os.path.exists(tmp_wav) or os.path.getsize(tmp_wav) <= 0:
                    return False
            try:
                silent, avg_db = BluraySubtitle._is_silent_audio_file(tmp_wav, -60.0)
            except Exception:
                silent, avg_db = False, 0.0
            if silent:
                if owns_tmp:
                    try:
                        os.remove(tmp_wav)
                    except Exception:
                        pass
                return False
            try:
                effective_bits = get_effective_bit_depth(tmp_wav)
            except Exception:
                effective_bits = 24
            if effective_bits <= 16:
                fd2, tmp_wav2 = tempfile.mkstemp(prefix=f"sp_audio16_{os.getpid()}_", suffix=".wav")
                os.close(fd2)
                subprocess.Popen(
                    f'"{FFMPEG_PATH}" -hide_banner -loglevel error -y -i "{tmp_wav}" -c:a pcm_s16le "{tmp_wav2}"',
                    shell=True
                ).wait()
                if os.path.exists(tmp_wav2) and os.path.getsize(tmp_wav2) > 0:
                    if owns_tmp:
                        try:
                            os.remove(tmp_wav)
                        except Exception:
                            pass
                    tmp_wav = tmp_wav2
                    owns_tmp = True
                    tmp_wav2 = ''
            ok = False
            if FLAC_PATH:
                try:
                    subprocess.Popen(f'"{FLAC_PATH}" -8 -j {FLAC_THREADS} "{tmp_wav}" -o "{out_flac}"', shell=True).wait()
                    ok = os.path.exists(out_flac) and os.path.getsize(out_flac) > 0
                except Exception:
                    ok = False
            if not ok:
                try:
                    subprocess.Popen(
                        f'"{FFMPEG_PATH}" -hide_banner -loglevel error -y -i "{tmp_wav}" -c:a flac "{out_flac}"',
                        shell=True
                    ).wait()
                    ok = os.path.exists(out_flac) and os.path.getsize(out_flac) > 0
                except Exception:
                    ok = False
            return ok
        finally:
            if tmp_wav2 and os.path.exists(tmp_wav2):
                try:
                    os.remove(tmp_wav2)
                except Exception:
                    pass
            if owns_tmp and tmp_wav and os.path.exists(tmp_wav):
                try:
                    os.remove(tmp_wav)
                except Exception:
                    pass

    @staticmethod
    def _pid_lang_from_mkvmerge_json(media_path: str) -> dict[int, str]:
        if not media_path or not os.path.exists(media_path):
            return {}
        try:
            find_mkvtoolinx()
        except Exception:
            pass
        exe = MKV_MERGE_PATH if MKV_MERGE_PATH else 'mkvmerge'
        try:
            p = subprocess.run(
                [exe, "--identify", "--identification-format", "json", media_path],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='ignore',
                shell=False
            )
        except Exception:
            return {}
        if p.returncode != 0:
            return {}
        try:
            data = json.loads(p.stdout or "{}")
        except Exception:
            return {}
        out: dict[int, str] = {}
        tracks = data.get('tracks') or []
        if not isinstance(tracks, list):
            return {}
        for t in tracks:
            if not isinstance(t, dict):
                continue
            props = t.get('properties') or {}
            if not isinstance(props, dict):
                props = {}
            lang = str(props.get('language') or 'und')
            if not lang:
                lang = 'und'
            for key in ('id',):
                try:
                    out[int(t.get(key))] = lang
                except Exception:
                    pass
            for key in ('stream_id', 'number'):
                try:
                    out[int(props.get(key))] = lang
                except Exception:
                    pass
        return out

    @staticmethod
    def _mkvmerge_identify_json(media_path: str) -> dict[str, object]:
        if not media_path or not os.path.exists(media_path):
            return {}
        try:
            find_mkvtoolinx()
        except Exception:
            pass
        exe = MKV_MERGE_PATH if MKV_MERGE_PATH else 'mkvmerge'
        try:
            p = subprocess.run(
                [exe, "--identify", "--identification-format", "json", media_path],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='ignore',
                shell=False
            )
        except Exception:
            return {}
        if p.returncode != 0:
            return {}
        try:
            data = json.loads(p.stdout or "{}")
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _fix_output_track_languages_with_mkvpropedit(
        output_mkv_path: str,
        input_m2ts_path: str,
        pid_to_lang: dict[int, str],
        selected_audio_ids: list[str],
        selected_sub_ids: list[str],
    ):
        if not output_mkv_path or not os.path.exists(output_mkv_path):
            return
        try:
            find_mkvtoolinx()
        except Exception:
            pass
        exe = MKV_PROP_EDIT_PATH or shutil.which('mkvpropedit') or 'mkvpropedit'
        if not exe:
            print(f'[lang-fix] mkvpropedit not found, skip: {output_mkv_path}')
            return

        def _norm_lang(v: str) -> str:
            v = (v or '').strip().lower()
            if re.fullmatch(r'[a-z]{3}', v):
                return v
            return 'und'

        idx_to_pid = BluraySubtitle._ffprobe_stream_index_to_service_pid(input_m2ts_path)
        input_info = BluraySubtitle._mkvmerge_identify_json(input_m2ts_path)
        in_tracks = input_info.get('tracks') or []
        if not isinstance(in_tracks, list):
            in_tracks = []
        if not in_tracks:
            print(f'[lang-fix] input identify empty: {input_m2ts_path}')
        sel_a: set[int] = set()
        sel_s: set[int] = set()
        for x in selected_audio_ids or []:
            try:
                sel_a.add(int(str(x).strip()))
            except Exception:
                pass
        for x in selected_sub_ids or []:
            try:
                sel_s.add(int(str(x).strip()))
            except Exception:
                pass

        expected_by_type: dict[str, list[str]] = {'video': [], 'audio': [], 'subtitles': []}
        for t in in_tracks:
            if not isinstance(t, dict):
                continue
            t_type = str(t.get('type') or '')
            try:
                tid = int(t.get('id'))
            except Exception:
                continue
            include = False
            if t_type == 'video':
                include = True
            elif t_type == 'audio':
                include = tid in sel_a
            elif t_type == 'subtitles':
                include = tid in sel_s
            if not include:
                continue
            pid = idx_to_pid.get(tid)
            if pid is None:
                props = t.get('properties') or {}
                if isinstance(props, dict):
                    for k in ('stream_id', 'number'):
                        v = props.get(k)
                        if v is None:
                            continue
                        try:
                            if isinstance(v, str) and v.strip().lower().startswith('0x'):
                                pid = int(v.strip(), 16)
                            else:
                                pid = int(v)
                            break
                        except Exception:
                            pid = None
            lang = 'und'
            if pid is not None:
                lang = str(pid_to_lang.get(pid) or 'und')
            expected_by_type[t_type].append(_norm_lang(lang))

        out_info = BluraySubtitle._mkvmerge_identify_json(output_mkv_path)
        out_tracks = out_info.get('tracks') or []
        if not isinstance(out_tracks, list) or not out_tracks:
            print(f'[lang-fix] output identify empty: {output_mkv_path}')
            return

        edit_specs: list[tuple[str, str, str, str]] = []
        used = {'video': 0, 'audio': 0, 'subtitles': 0}
        for i, t in enumerate(out_tracks):
            if not isinstance(t, dict):
                continue
            t_type = str(t.get('type') or '')
            if t_type not in used:
                continue
            idx = used[t_type]
            used[t_type] += 1
            expected_list = expected_by_type.get(t_type) or []
            expected = expected_list[idx] if idx < len(expected_list) else 'und'
            props = t.get('properties') or {}
            if not isinstance(props, dict):
                props = {}
            actual = _norm_lang(str(props.get('language') or 'und'))
            expected = _norm_lang(expected)
            if actual != expected:
                try:
                    track_id = t.get("id") + 1
                except:
                    track_id = i + 1
                selector = f'track:{track_id}'
                edit_specs.append((selector, expected, actual, t_type))

        if not edit_specs:
            return
        print(f'[lang-fix] {output_mkv_path}')
        for selector, expected, actual, t_type in edit_specs:
            print(f'[lang-fix]   {selector} ({t_type}) {actual} -> {expected}')
        args: list[str] = [exe]
        try:
            ui = get_mkvtoolnix_ui_language()
            if ui:
                args += ['--ui-language', ui]
        except Exception:
            pass
        args.append(output_mkv_path)
        for selector, expected, _actual, _t_type in edit_specs:
            args += ['--edit', selector, '--set', f'language={expected}']
        try:
            p = subprocess.run(args, capture_output=True, text=True, encoding='utf-8', errors='ignore', shell=False)
            if p.returncode != 0:
                print(f'[lang-fix] mkvpropedit failed rc={p.returncode}')
                if (p.stdout or '').strip():
                    print(f'[lang-fix] stdout:\n{p.stdout}')
                if (p.stderr or '').strip():
                    print(f'[lang-fix] stderr:\n{p.stderr}')
                cmd = ' '.join([f'"{a}"' if (' ' in a or '\t' in a) else a for a in args])
                p2 = subprocess.run(cmd, shell=True, capture_output=True, text=True, encoding='utf-8', errors='ignore')
                if p2.returncode != 0:
                    print(f'[lang-fix] shell fallback failed rc={p2.returncode}')
                    if (p2.stdout or '').strip():
                        print(f'[lang-fix] stdout:\n{p2.stdout}')
                    if (p2.stderr or '').strip():
                        print(f'[lang-fix] stderr:\n{p2.stderr}')
        except Exception:
            try:
                cmd = ' '.join([f'"{a}"' if (' ' in a or '\t' in a) else a for a in args])
                p3 = subprocess.run(cmd, shell=True, capture_output=True, text=True, encoding='utf-8', errors='ignore')
                if p3.returncode != 0:
                    print(f'[lang-fix] exception fallback failed rc={p3.returncode}')
                    if (p3.stdout or '').strip():
                        print(f'[lang-fix] stdout:\n{p3.stdout}')
                    if (p3.stderr or '').strip():
                        print(f'[lang-fix] stderr:\n{p3.stderr}')
            except Exception:
                pass

    @staticmethod
    def _ordered_ffprobe_track_slots_for_remux(
        m2ts_path: str,
        copy_audio_track: list[str],
        copy_sub_track: list[str],
    ) -> list[dict[str, object]]:
        """Reference order: first video, then selected audios / subs by ffprobe ``index``; PID from ``id`` hex."""
        streams = [s for s in (BluraySubtitle._ffprobe_streams(m2ts_path) or []) if isinstance(s, dict)]
        out: list[dict[str, object]] = []
        for s in streams:
            if str(s.get('codec_type') or '') != 'video':
                continue
            pid = BluraySubtitle._ffprobe_stream_service_id(s)
            if pid is not None:
                out.append({'type': 'video', 'pid': pid})
            break
        for aid in copy_audio_track or []:
            try:
                want_idx = int(str(aid).strip())
            except Exception:
                continue
            for s in streams:
                if str(s.get('codec_type') or '') != 'audio':
                    continue
                try:
                    if int(s.get('index')) != want_idx:
                        continue
                except Exception:
                    continue
                pid = BluraySubtitle._ffprobe_stream_service_id(s)
                if pid is not None:
                    out.append({'type': 'audio', 'pid': pid})
                break
        for sid in copy_sub_track or []:
            try:
                want_idx = int(str(sid).strip())
            except Exception:
                continue
            for s in streams:
                if str(s.get('codec_type') or '') not in ('subtitle', 'subtitles'):
                    continue
                try:
                    if int(s.get('index')) != want_idx:
                        continue
                except Exception:
                    continue
                pid = BluraySubtitle._ffprobe_stream_service_id(s)
                if pid is not None:
                    out.append({'type': 'subtitles', 'pid': pid})
                break
        return out

    @staticmethod
    def _mkvmerge_tid_for_ffprobe_pid(m2ts_path: str, pid: int, slot_type: str) -> Optional[int]:
        """mkvmerge track id for this m2ts = ffprobe stream ``index`` of the stream with matching ``id`` (PID)."""
        streams = [s for s in (BluraySubtitle._ffprobe_streams(m2ts_path) or []) if isinstance(s, dict)]
        for s in streams:
            ct = str(s.get('codec_type') or '')
            if slot_type == 'video':
                if ct != 'video':
                    continue
            elif slot_type == 'audio':
                if ct != 'audio':
                    continue
            elif slot_type == 'subtitles':
                if ct not in ('subtitle', 'subtitles'):
                    continue
            else:
                continue
            spid = BluraySubtitle._ffprobe_stream_service_id(s)
            if spid != pid:
                continue
            try:
                return int(s.get('index'))
            except Exception:
                return None
        return None

    @staticmethod
    def _map_ffprobe_slots_to_mkvmerge_track_ids(
        ref_slots: list[dict[str, object]],
        m2ts_path: str,
    ) -> Optional[list[int]]:
        """Same slot order as ref_slots; each slot matched by ffprobe PID on ``m2ts_path``."""
        mapped: list[int] = []
        for slot in ref_slots:
            typ = str(slot.get('type') or '')
            try:
                pid = int(slot.get('pid'))
            except Exception:
                return None
            tid = BluraySubtitle._mkvmerge_tid_for_ffprobe_pid(m2ts_path, pid, typ)
            if tid is None:
                return None
            mapped.append(tid)
        return mapped

    @staticmethod
    def _track_lists_from_mkvmerge_cmd(cmd: str) -> tuple[Optional[list[str]], Optional[list[str]]]:
        """
        Best-effort parse of ``-a`` / ``-s`` track lists from a mkvmerge command line.
        Returns (audio_ids, subtitle_ids); each entry is None if that flag was not found
        (caller should keep defaults from ``_select_tracks_for_source``).
        Returns (None, None) only when neither flag appears.
        """
        if not (cmd or '').strip():
            return None, None

        def _last_flag(flag: str) -> Optional[list[str]]:
            line = re.sub(r'[\r\n]+', ' ', cmd)
            matches = list(re.finditer(rf'(?:^|[\s]){re.escape(flag)}\s+(\S+)', line))
            if not matches:
                return None
            tok = matches[-1].group(1).strip().strip('"').strip("'")
            if not tok or tok in ('*', '!'):
                return None
            parts = [p.strip() for p in tok.split(',') if p.strip()]
            return parts or None

        a = _last_flag('-a')
        s = _last_flag('-s')
        if a is None and s is None:
            return None, None
        return a, s

    @staticmethod
    def _fallback_track_lists(
        remux_cmd: str,
        copy_audio_track: list[str],
        copy_sub_track: list[str],
    ) -> tuple[list[str], list[str]]:
        pa, ps = BluraySubtitle._track_lists_from_mkvmerge_cmd(remux_cmd)
        fa = list(pa) if pa is not None else list(copy_audio_track)
        fs = list(ps) if ps is not None else list(copy_sub_track)
        return fa, fs

    @staticmethod
    def _split_segment_count_from_mkvmerge_cmd(cmd: str) -> Optional[int]:
        """
        Best-effort parse of mkvmerge ``--split``.
        Supports ``--split parts:...`` and ``--split chapters:...``.
        Returns segment count when recognizable; otherwise None.
        """
        raw = (cmd or '').strip()
        if not raw:
            return None
        text = re.sub(r'[\r\n]+', ' ', raw)
        m = re.search(r'--split\s+("([^"]+)"|\'([^\']+)\'|(\S+))', text)
        if not m:
            return None
        spec = (m.group(2) or m.group(3) or m.group(4) or '').strip()
        low = spec.lower()
        if low.startswith('parts:'):
            payload = spec[6:].strip()
            if not payload:
                return None
            segs = [x.strip() for x in payload.split(',') if x.strip()]
            return len(segs) if segs else None
        if low.startswith('chapters:'):
            payload = spec[9:].strip()
            if not payload:
                return None
            if payload.lower() in ('all',):
                return None
            cuts = [x.strip() for x in payload.split(',') if x.strip()]
            return (len(cuts) + 1) if cuts else 1
        return None

    @staticmethod
    def _m2ts_clip_time_window_sec(m2ts_path: str, in_time: int, out_time: int) -> tuple[bool, float, float]:
        """
        (needs_split, start_sec, end_sec) for one playlist item.
        start = (in_time*2 - first_pts)/90000
        end   = start + (out_time-in_time)/45000
        No split when start==0 and end ~= file duration.
        """
        clip_sec = max(0.0, (out_time - in_time) / 45000.0)
        pts: Optional[int] = None
        dur90: Optional[int] = None
        try:
            if m2ts_path and os.path.isfile(m2ts_path):
                m2 = M2TS(m2ts_path)
                pts = m2.get_first_pts(m2ts=True)
                try:
                    dur90 = int(m2.get_duration())
                except Exception:
                    dur90 = None
        except Exception:
            pts = None
            dur90 = None
        if pts is None:
            return False, 0.0, clip_sec
        start_sec = (in_time * 2 - pts) / 90000.0
        end_sec = start_sec + clip_sec
        file_dur_sec = (dur90 / 90000.0) if (dur90 is not None and dur90 > 0) else clip_sec
        if abs(start_sec) < 1e-3 and abs(end_sec - file_dur_sec) < 1e-3:
            return False, 0.0, file_dur_sec
        s = max(0.0, start_sec)
        e = max(0.0, end_sec)
        if e <= s + 1e-3:
            # Guard against producing --split parts:00:00:00.000-00:00:00.000
            return False, 0.0, file_dur_sec
        return True, s, e

    @staticmethod
    def _mkvmerge_track_order_arg(mapped_ids: list[int]) -> str:
        return ','.join(f'0:{tid}' for tid in mapped_ids)

    @staticmethod
    def _mkvmerge_select_flags_from_mapped(mapped_ids: list[int], cur_identify: dict[str, object]) -> tuple[str, str, str]:
        """Return (d_flags, a_flags, s_flags) for mkvmerge: enable only mapped ids per type."""
        cur_tracks = [t for t in (cur_identify.get('tracks') or []) if isinstance(t, dict)]
        v_ids = []
        a_ids = []
        s_ids = []
        want = set(int(x) for x in mapped_ids)
        for t in cur_tracks:
            try:
                tid = int(t.get('id'))
            except Exception:
                continue
            if tid not in want:
                continue
            typ = str(t.get('type') or '')
            if typ == 'video':
                v_ids.append(tid)
            elif typ == 'audio':
                a_ids.append(tid)
            elif typ == 'subtitles':
                s_ids.append(tid)
        d_f = ','.join(str(x) for x in v_ids) if v_ids else ''
        a_f = ','.join(str(x) for x in a_ids) if a_ids else ''
        s_f = ','.join(str(x) for x in s_ids) if s_ids else ''
        return d_f, a_f, s_f

    @staticmethod
    def _series_episode_segments_bounds(chapter: Chapter, confs: list[dict[str, int | str]]) -> list[tuple[int, int]]:
        """Same (start_chapter, end_chapter) pairs as the series branch of ``_make_main_mpls_remux_cmd``."""
        if not confs:
            return []
        confs_sorted = sorted(confs, key=lambda c: int(c.get('chapter_index') or c.get('start_at_chapter') or 1))
        rows = sum(map(len, chapter.mark_info.values()))
        total_end = rows + 1
        segments: list[tuple[int, int]] = []
        for i, c in enumerate(confs_sorted):
            s = int(c.get('start_at_chapter') or c.get('chapter_index') or 1)
            if c.get('end_at_chapter'):
                e = int(c.get('end_at_chapter') or total_end)
            elif i + 1 < len(confs_sorted):
                e = int(confs_sorted[i + 1].get('start_at_chapter') or confs_sorted[i + 1].get('chapter_index') or total_end)
            else:
                e = total_end
            s = max(1, min(s, total_end))
            e = max(s + 1, min(e, total_end))
            segments.append((s, e))
        return segments

    @staticmethod
    def _expected_mkvmerge_split_output_paths(output_norm: str, n_segments: int) -> list[str]:
        """Paths ``stem-001.mkv`` … mkvmerge writes when ``-o stem.mkv`` and ``--split parts:``."""
        if n_segments <= 1 or not output_norm:
            return []
        d = os.path.dirname(output_norm)
        base = os.path.basename(output_norm)
        stem, ext = os.path.splitext(base)
        ex = ext if ext else '.mkv'
        return [os.path.join(d, f'{stem}-{k + 1:03d}{ex}') for k in range(n_segments)]

    @staticmethod
    def _filter_ref_slots_common_across_playlist(
        ref_slots: list[dict[str, object]],
        stream_dir: str,
        rows: list[tuple[str, int, int]],
    ) -> Optional[list[dict[str, object]]]:
        """
        Keep only slots whose PID exists (same codec_type) in every m2ts of this playlist.
        This implements "drop extra / keep common" to avoid aborting concat on missing optional tracks.
        """
        if not ref_slots:
            return []
        clip_pid_sets: list[dict[str, set[int]]] = []
        for fname, _in_time, _out_time in rows:
            m2ts_path = os.path.join(stream_dir, f'{fname}.m2ts')
            if not os.path.isfile(m2ts_path):
                return None
            by_type: dict[str, set[int]] = {'video': set(), 'audio': set(), 'subtitles': set()}
            for s in BluraySubtitle._ffprobe_streams(m2ts_path) or []:
                if not isinstance(s, dict):
                    continue
                ct = str(s.get('codec_type') or '')
                if ct == 'video':
                    typ = 'video'
                elif ct == 'audio':
                    typ = 'audio'
                elif ct in ('subtitle', 'subtitles'):
                    typ = 'subtitles'
                else:
                    continue
                pid = BluraySubtitle._ffprobe_stream_service_id(s)
                if pid is not None:
                    by_type[typ].add(pid)
            clip_pid_sets.append(by_type)
        kept: list[dict[str, object]] = []
        dropped: list[tuple[str, int]] = []
        for slot in ref_slots:
            typ = str(slot.get('type') or '')
            try:
                pid = int(slot.get('pid'))
            except Exception:
                dropped.append((typ, -1))
                continue
            ok = True
            for ps in clip_pid_sets:
                if pid not in ps.get(typ, set()):
                    ok = False
                    break
            if ok:
                kept.append(slot)
            else:
                dropped.append((typ, pid))
        if dropped:
            msg = ', '.join(f'{t}:{("0x%X" % p) if p >= 0 else "?"}' for t, p in dropped)
            print(f'[remux-fallback] drop non-common slots: {msg}')
        has_video = any(str(x.get('type') or '') == 'video' for x in kept)
        if not has_video:
            return None
        return kept

    @staticmethod
    def _ffprobe_audio_stream_by_pid(m2ts_path: str, pid: int) -> Optional[dict[str, object]]:
        for s in BluraySubtitle._ffprobe_streams(m2ts_path) or []:
            if not isinstance(s, dict):
                continue
            if str(s.get('codec_type') or '') != 'audio':
                continue
            spid = BluraySubtitle._ffprobe_stream_service_id(s)
            if spid == pid:
                return s
        return None

    @staticmethod
    def _channel_layout_from_count(ch: int) -> str:
        if ch <= 1:
            return 'mono'
        if ch == 2:
            return 'stereo'
        if ch == 6:
            return '5.1'
        if ch == 8:
            return '7.1'
        return 'stereo'

    @staticmethod
    def _build_slot_mux_plan_with_silence(
        ref_slots: list[dict[str, object]],
        m2ts_path: str,
    ) -> Optional[list[dict[str, object]]]:
        """
        Resolve each reference slot to current m2ts track id.
        Missing audio slots are marked with ``needs_silence=True``; video/subtitle must exist.
        """
        out: list[dict[str, object]] = []
        for slot in ref_slots:
            typ = str(slot.get('type') or '')
            try:
                pid = int(slot.get('pid'))
            except Exception:
                return None
            tid = BluraySubtitle._mkvmerge_tid_for_ffprobe_pid(m2ts_path, pid, typ)
            if tid is None:
                if typ == 'audio':
                    out.append({'type': typ, 'pid': pid, 'tid': None, 'needs_silence': True})
                    continue
                return None
            out.append({'type': typ, 'pid': pid, 'tid': tid, 'needs_silence': False})
        return out

    @staticmethod
    def _create_silence_track_for_audio_slot(
        ref_audio_stream: dict[str, object],
        duration_sec: float,
        out_path: str,
    ) -> bool:
        if duration_sec <= 0.0:
            return False
        try:
            sr = int(float(ref_audio_stream.get('sample_rate') or 48000))
        except Exception:
            sr = 48000
        try:
            ch = int(ref_audio_stream.get('channels') or 2)
        except Exception:
            ch = 2
        try:
            bits = int(ref_audio_stream.get('bits_per_raw_sample') or 0)
            if bits <= 0:
                bits = 16
        except Exception:
            bits = 16
        layout = BluraySubtitle._channel_layout_from_count(ch)
        if bits >= 24:
            acodec = 'pcm_s24be'
        elif bits >= 20:
            acodec = 'pcm_s24be'
        else:
            acodec = 'pcm_s16be'
        ff = FFMPEG_PATH if FFMPEG_PATH else 'ffmpeg'
        cmd = (
            f'"{ff}" -y -f lavfi -i "anullsrc=r={sr}:cl={layout}" '
            f'-t {max(0.001, duration_sec):.6f} -c:a {acodec} "{out_path}"'
        )
        try:
            rc = subprocess.Popen(cmd, shell=True).wait()
        except Exception:
            return False
        return rc == 0 and os.path.isfile(out_path)

    def _try_remux_mpls_track_aligned_concat(
        self,
        mpls_path: str,
        output_file: str,
        copy_audio_track: list[str],
        copy_sub_track: list[str],
        cover: str,
        cancel_event: Optional[threading.Event] = None,
    ) -> bool:
        """
        Fallback when direct ``mkvmerge … mpls`` fails (e.g. different track counts across m2ts).
        Track identity uses ffprobe ``streams[].id`` (e.g. ``0x1011``) as PID; mkvmerge track id = ffprobe ``index``.
        Per-clip m2ts mux with ``--split parts`` if needed, ``--track-order`` aligned to first m2ts, then
        ``+`` concat with ``--append-mode track``. Languages: ``_fix_output_track_languages_with_mkvpropedit`` on caller.
        """
        try:
            find_mkvtoolinx()
        except Exception:
            pass
        exe = MKV_MERGE_PATH or shutil.which('mkvmerge') or 'mkvmerge'
        chapter = Chapter(mpls_path)
        chapter.get_pid_to_language()
        playlist_dir = os.path.dirname(os.path.normpath(mpls_path))
        stream_dir = os.path.normpath(os.path.join(playlist_dir, '..', 'STREAM'))
        rows = list(chapter.in_out_time or [])
        if len(rows) < 2:
            return False
        first_name, _it0, _ot0 = rows[0]
        first_m2ts = os.path.join(stream_dir, f'{first_name}.m2ts')
        if not os.path.isfile(first_m2ts):
            print(f'[remux-fallback] missing first m2ts: {first_m2ts}')
            return False
        ref_slots = BluraySubtitle._ordered_ffprobe_track_slots_for_remux(
            first_m2ts, copy_audio_track, copy_sub_track
        )
        if not ref_slots:
            print('[remux-fallback] no reference track slots from ffprobe on first m2ts')
            return False
        ui = ''
        try:
            ui = (mkvtoolnix_ui_language_arg() or '').strip()
        except Exception:
            pass
        out_dir = os.path.dirname(os.path.normpath(output_file)) or '.'
        os.makedirs(out_dir, exist_ok=True)
        part_dir = os.path.join(out_dir, f'_remux_align_{os.getpid()}_{int(time.time() * 1000) & 0xFFFFFF}')
        os.makedirs(part_dir, exist_ok=True)
        parts: list[str] = []
        try:
            for idx, (fname, in_time, out_time) in enumerate(rows):
                if cancel_event and cancel_event.is_set():
                    raise _Cancelled()
                m2ts_path = os.path.join(stream_dir, f'{fname}.m2ts')
                if not os.path.isfile(m2ts_path):
                    print(f'[remux-fallback] missing m2ts: {m2ts_path}')
                    return False
                cur_ident = BluraySubtitle._mkvmerge_identify_json(m2ts_path)
                slot_plan = BluraySubtitle._build_slot_mux_plan_with_silence(ref_slots, m2ts_path)
                if slot_plan is None:
                    print(f'[remux-fallback] could not map ffprobe PIDs to mkvmerge ids for {m2ts_path}')
                    return False
                mapped = [int(x.get('tid')) for x in slot_plan if not bool(x.get('needs_silence'))]
                d_f, a_f, s_f = BluraySubtitle._mkvmerge_select_flags_from_mapped(mapped, cur_ident)
                part_out = os.path.join(part_dir, f'part_{idx:03d}.mkv')
                needs_split, t0, t1 = BluraySubtitle._m2ts_clip_time_window_sec(m2ts_path, in_time, out_time)
                split_arg = ''
                clip_duration_sec = max(0.0, (out_time - in_time) / 45000.0)
                if needs_split:
                    st = get_time_str(t0)
                    ed = get_time_str(t1)
                    if st == '0':
                        st = '00:00:00.000'
                    if ed == '0':
                        ed = '00:00:00.000'
                    split_arg = f'--split parts:{st}-{ed}'
                    clip_duration_sec = max(0.0, float(t1) - float(t0))
                inputs: list[str] = [f'"{m2ts_path}"']
                track_order_parts: list[str] = []
                silent_idx = 0
                for slot in slot_plan:
                    if bool(slot.get('needs_silence')):
                        pid = int(slot.get('pid'))
                        ref_stream = BluraySubtitle._ffprobe_audio_stream_by_pid(first_m2ts, pid)
                        if not isinstance(ref_stream, dict):
                            print(f'[remux-fallback] missing reference audio stream for pid=0x{pid:X}')
                            return False
                        silent_path = os.path.join(part_dir, f'part_{idx:03d}_sil_{pid:04x}.mka')
                        if not BluraySubtitle._create_silence_track_for_audio_slot(ref_stream, clip_duration_sec, silent_path):
                            print(f'[remux-fallback] failed creating silence track for pid=0x{pid:X}')
                            return False
                        silent_idx += 1
                        inputs.append(f'"{silent_path}"')
                        track_order_parts.append(f'{silent_idx}:0')
                    else:
                        track_order_parts.append(f'0:{int(slot.get("tid"))}')
                to_arg = ','.join(track_order_parts)
                bits: list[str] = [f'"{exe}"']
                if ui:
                    bits.append(ui)
                if split_arg:
                    bits.append(split_arg)
                bits += [f'--track-order {to_arg}', '-o', f'"{part_out}"']
                if d_f:
                    bits += ['-d', d_f]
                if a_f:
                    bits += ['-a', a_f]
                if s_f:
                    bits += ['-s', s_f]
                bits += inputs
                cmd = ' '.join(bits)
                print(f'[remux-fallback] {cmd}')
                rc = self._run_single_command(cmd)
                if rc != 0:
                    print(f'[remux-fallback] part mux failed rc={rc} idx={idx}')
                    return False
                actual_part = part_out
                if not os.path.isfile(actual_part):
                    prefix = f'part_{idx:03d}'
                    try:
                        cands = sorted(
                            os.path.join(part_dir, fn)
                            for fn in os.listdir(part_dir)
                            if fn.startswith(prefix) and fn.lower().endswith('.mkv')
                        )
                    except Exception:
                        cands = []
                    if not cands:
                        print(f'[remux-fallback] missing part output after mux: {part_out}')
                        return False
                    actual_part = cands[0]
                parts.append(actual_part)
            if not parts:
                return False
            if cancel_event and cancel_event.is_set():
                raise _Cancelled()
            cover_arg = ''
            if cover and os.path.isfile(cover):
                cover_arg = f'--attachment-name Cover.jpg --attach-file "{cover}"'
            concat_bits: list[str] = [f'"{exe}"']
            if ui:
                concat_bits.append(ui)
            concat_bits += ['--append-mode', 'track', '-o', f'"{output_file}"', f'"{parts[0]}"']
            for p in parts[1:]:
                concat_bits.append('+')
                concat_bits.append(f'"{p}"')
            if cover_arg:
                concat_bits.append(cover_arg)
            ccmd = ' '.join(concat_bits)
            while '  ' in ccmd:
                ccmd = ccmd.replace('  ', ' ')
            print(f'[remux-fallback] concat: {ccmd}')
            rc2 = self._run_single_command(ccmd)
            if rc2 != 0:
                print(f'[remux-fallback] concat failed rc={rc2}')
                return False
            return os.path.isfile(output_file)
        except _Cancelled:
            raise
        except Exception:
            traceback.print_exc()
            return False
        finally:
            try:
                shutil.rmtree(part_dir, ignore_errors=True)
            except Exception:
                pass

    def _try_remux_mpls_split_outputs_track_aligned(
        self,
        mpls_path: str,
        output_file: str,
        confs: list[dict[str, int | str]],
        copy_audio_track: list[str],
        copy_sub_track: list[str],
        cover: str,
        cancel_event: Optional[threading.Event] = None,
    ) -> bool:
        """
        Fallback when ``mkvmerge mpls`` with ``--split parts`` fails but multiple episode MKVs are required.
        For each episode window on the MPLS timeline, mux overlapping m2ts slices with ffprobe PID-aligned
        ``--track-order``, then ``+`` concat slices; writes ``basename-001.mkv``, ``-002.mkv``, … like mkvmerge.
        """
        out_norm = os.path.normpath(output_file) if output_file else ''
        if not out_norm or getattr(self, 'movie_mode', False):
            print('[remux-fallback-split] skip: empty output path or movie_mode')
            return False
        try:
            find_mkvtoolinx()
        except Exception:
            pass
        exe = MKV_MERGE_PATH or shutil.which('mkvmerge') or 'mkvmerge'
        chapter = Chapter(mpls_path)
        chapter.get_pid_to_language()
        segments = BluraySubtitle._series_episode_segments_bounds(chapter, confs)
        expected = BluraySubtitle._expected_mkvmerge_split_output_paths(out_norm, len(segments))
        if len(segments) <= 1 or len(expected) != len(segments):
            print(
                f'[remux-fallback-split] skip: need 2+ episode segments; '
                f'segments={len(segments)} expected_files={len(expected)}'
            )
            return False
        playlist_dir = os.path.dirname(os.path.normpath(mpls_path))
        stream_dir = os.path.normpath(os.path.join(playlist_dir, '..', 'STREAM'))
        play_rows = list(chapter.in_out_time or [])
        if len(play_rows) < 2:
            print(f'[remux-fallback-split] skip: playlist has only {len(play_rows)} clip(s)')
            return False
        first_name, _it0, _ot0 = play_rows[0]
        first_m2ts = os.path.join(stream_dir, f'{first_name}.m2ts')
        if not os.path.isfile(first_m2ts):
            print(f'[remux-fallback-split] missing first m2ts: {first_m2ts}')
            return False
        ref_slots = BluraySubtitle._ordered_ffprobe_track_slots_for_remux(
            first_m2ts, copy_audio_track, copy_sub_track
        )
        if not ref_slots:
            print('[remux-fallback-split] no reference track slots from ffprobe on first m2ts')
            return False
        ui = ''
        try:
            ui = (mkvtoolnix_ui_language_arg() or '').strip()
        except Exception:
            pass
        out_dir = os.path.dirname(out_norm) or '.'
        os.makedirs(out_dir, exist_ok=True)
        part_dir = os.path.join(out_dir, f'_remux_split_align_{os.getpid()}_{int(time.time() * 1000) & 0xFFFFFF}')
        os.makedirs(part_dir, exist_ok=True)
        rows = sum(map(len, chapter.mark_info.values()))
        total_end = rows + 1
        _, index_to_offset = get_index_to_m2ts_and_offset(chapter)

        def _off(idx: int) -> float:
            if idx >= total_end:
                return chapter.get_total_time()
            return float(index_to_offset.get(idx, 0.0))

        eps = 1e-5
        try:
            print(
                f'[remux-fallback-split] start: {len(segments)} episodes -> '
                f'{", ".join(os.path.basename(p) for p in expected)}'
            )
            try:
                self._progress(text=f'Multi-episode split fallback: {len(segments)} MKV...')
            except Exception:
                pass
            for seg_idx, ((cs, ce), dest_path) in enumerate(zip(segments, expected)):
                if cancel_event and cancel_event.is_set():
                    raise _Cancelled()
                w0 = float(_off(cs))
                w1 = float(_off(ce))
                pieces: list[str] = []
                acc = 0.0
                for clip_idx, (fname, in_time, out_time) in enumerate(play_rows):
                    if cancel_event and cancel_event.is_set():
                        raise _Cancelled()
                    clip_acc = acc
                    dur = max(0.0, (out_time - in_time) / 45000.0)
                    seg_lo = max(w0, clip_acc)
                    seg_hi = min(w1, clip_acc + dur)
                    acc = clip_acc + dur
                    if dur <= eps or seg_lo + eps >= seg_hi:
                        continue
                    m2ts_path = os.path.join(stream_dir, f'{fname}.m2ts')
                    if not os.path.isfile(m2ts_path):
                        print(f'[remux-fallback-split] missing m2ts: {m2ts_path}')
                        return False
                    need, a, b = BluraySubtitle._m2ts_clip_time_window_sec(m2ts_path, in_time, out_time)
                    full_lo = 0.0 if not need else float(a)
                    full_hi = float(b)
                    span = max(0.0, full_hi - full_lo)
                    if span <= eps:
                        continue
                    p0 = (seg_lo - clip_acc) / dur
                    p1 = (seg_hi - clip_acc) / dur
                    p0 = min(1.0, max(0.0, p0))
                    p1 = min(1.0, max(0.0, p1))
                    if p1 <= p0 + eps / max(dur, eps):
                        continue
                    slice_start = full_lo + p0 * span
                    slice_end = full_lo + p1 * span
                    if slice_end <= slice_start + eps:
                        continue
                    is_full_window = (slice_start <= full_lo + eps) and (slice_end >= full_hi - eps)
                    if is_full_window and not need:
                        split_arg = ''
                    elif is_full_window and need:
                        st = get_time_str(a)
                        ed = get_time_str(b)
                        if st == '0':
                            st = '00:00:00.000'
                        if ed == '0':
                            ed = '00:00:00.000'
                        split_arg = f'--split parts:{st}-{ed}'
                    else:
                        st = get_time_str(slice_start)
                        ed = get_time_str(slice_end)
                        if st == '0':
                            st = '00:00:00.000'
                        if ed == '0':
                            ed = '00:00:00.000'
                        split_arg = f'--split parts:{st}-{ed}'
                    cur_ident = BluraySubtitle._mkvmerge_identify_json(m2ts_path)
                    slot_plan = BluraySubtitle._build_slot_mux_plan_with_silence(ref_slots, m2ts_path)
                    if slot_plan is None:
                        print(f'[remux-fallback-split] could not map ffprobe PIDs for {m2ts_path}')
                        return False
                    mapped = [int(x.get('tid')) for x in slot_plan if not bool(x.get('needs_silence'))]
                    d_f, a_f, s_f = BluraySubtitle._mkvmerge_select_flags_from_mapped(mapped, cur_ident)
                    clip_duration_sec = max(0.0, slice_end - slice_start)
                    inputs: list[str] = [f'"{m2ts_path}"']
                    track_order_parts: list[str] = []
                    silent_idx = 0
                    for slot in slot_plan:
                        if bool(slot.get('needs_silence')):
                            pid = int(slot.get('pid'))
                            ref_stream = BluraySubtitle._ffprobe_audio_stream_by_pid(first_m2ts, pid)
                            if not isinstance(ref_stream, dict):
                                print(f'[remux-fallback-split] missing reference audio stream for pid=0x{pid:X}')
                                return False
                            silent_path = os.path.join(part_dir, f'ep{seg_idx:03d}_c{clip_idx:03d}_sil_{pid:04x}.mka')
                            if not BluraySubtitle._create_silence_track_for_audio_slot(ref_stream, clip_duration_sec, silent_path):
                                print(f'[remux-fallback-split] failed creating silence for pid=0x{pid:X}')
                                return False
                            silent_idx += 1
                            inputs.append(f'"{silent_path}"')
                            track_order_parts.append(f'{silent_idx}:0')
                        else:
                            track_order_parts.append(f'0:{int(slot.get("tid"))}')
                    to_arg = ','.join(track_order_parts)
                    part_out = os.path.join(part_dir, f'ep{seg_idx:03d}_c{clip_idx:03d}.mkv')
                    bits: list[str] = [f'"{exe}"']
                    if ui:
                        bits.append(ui)
                    if split_arg:
                        bits.append(split_arg)
                    bits += [f'--track-order {to_arg}', '-o', f'"{part_out}"']
                    if d_f:
                        bits += ['-d', d_f]
                    if a_f:
                        bits += ['-a', a_f]
                    if s_f:
                        bits += ['-s', s_f]
                    bits += inputs
                    cmd = ' '.join(bits)
                    print(f'[remux-fallback-split] {cmd}')
                    rc = self._run_single_command(cmd)
                    if rc != 0:
                        print(f'[remux-fallback-split] part mux failed rc={rc} seg={seg_idx} clip={clip_idx}')
                        return False
                    actual_part = part_out
                    if not os.path.isfile(actual_part):
                        prefix = f'ep{seg_idx:03d}_c{clip_idx:03d}'
                        try:
                            cands = sorted(
                                os.path.join(part_dir, fn)
                                for fn in os.listdir(part_dir)
                                if fn.startswith(prefix) and fn.lower().endswith('.mkv')
                            )
                        except Exception:
                            cands = []
                        if not cands:
                            print(f'[remux-fallback-split] missing part after mux: {part_out}')
                            return False
                        actual_part = cands[0]
                    pieces.append(actual_part)
                if not pieces:
                    print(
                        f'[remux-fallback-split] no m2ts pieces for segment {seg_idx} '
                        f'(time window {w0:.3f}s .. {w1:.3f}s)'
                    )
                    return False
                if cancel_event and cancel_event.is_set():
                    raise _Cancelled()
                cover_arg = ''
                if cover and os.path.isfile(cover):
                    cover_arg = f'--attachment-name Cover.jpg --attach-file "{cover}"'
                if len(pieces) == 1:
                    concat_bits = [f'"{exe}"']
                    if ui:
                        concat_bits.append(ui)
                    concat_bits += ['-o', f'"{dest_path}"', f'"{pieces[0]}"']
                    if cover_arg:
                        concat_bits.append(cover_arg)
                else:
                    concat_bits = [f'"{exe}"']
                    if ui:
                        concat_bits.append(ui)
                    concat_bits += ['--append-mode', 'track', '-o', f'"{dest_path}"', f'"{pieces[0]}"']
                    for p in pieces[1:]:
                        concat_bits.append('+')
                        concat_bits.append(f'"{p}"')
                    if cover_arg:
                        concat_bits.append(cover_arg)
                ccmd = ' '.join(concat_bits)
                while '  ' in ccmd:
                    ccmd = ccmd.replace('  ', ' ')
                print(f'[remux-fallback-split] segment {seg_idx + 1}: {ccmd}')
                rc2 = self._run_single_command(ccmd)
                if rc2 != 0:
                    print(f'[remux-fallback-split] segment concat failed rc={rc2} seg={seg_idx}')
                    return False
                if not os.path.isfile(dest_path):
                    print(f'[remux-fallback-split] missing output: {dest_path}')
                    return False
            return all(os.path.isfile(p) for p in expected)
        except _Cancelled:
            raise
        except Exception:
            traceback.print_exc()
            return False
        finally:
            try:
                shutil.rmtree(part_dir, ignore_errors=True)
            except Exception:
                pass

    def _select_tracks_for_source(
        self,
        source_path: str,
        pid_to_lang: Optional[dict[int, str]] = None,
        config_key: Optional[str] = None
    ) -> tuple[list[str], list[str]]:
        tracks_cfg = getattr(self, 'track_selection_config', {}) or {}
        if config_key and isinstance(tracks_cfg, dict) and config_key in tracks_cfg:
            cfg = tracks_cfg.get(config_key) or {}
            return list(cfg.get('audio') or []), list(cfg.get('subtitle') or [])
        probe_path = source_path
        if str(source_path).lower().endswith('.mpls') and os.path.exists(source_path):
            try:
                chapter = Chapter(source_path)
                index_to_m2ts, _ = get_index_to_m2ts_and_offset(chapter)
                if index_to_m2ts:
                    first_key = sorted(index_to_m2ts.keys())[0]
                    playlist_dir = os.path.dirname(source_path)
                    stream_dir = os.path.join(os.path.dirname(playlist_dir), 'STREAM')
                    m2ts_path = os.path.join(stream_dir, index_to_m2ts[first_key])
                    if os.path.exists(m2ts_path):
                        probe_path = m2ts_path
            except Exception:
                pass
        streams = BluraySubtitle._ffprobe_streams(probe_path)
        pid_lang = pid_to_lang or {}
        if not pid_lang:
            out: dict[int, str] = {}
            for s in streams or []:
                lang = 'und'
                try:
                    direct = s.get('lang') or s.get('language')
                    if direct:
                        lang = str(direct)
                    else:
                        tags = s.get('tags') or {}
                        if isinstance(tags, dict):
                            tag_lang = tags.get('lang') or tags.get('language')
                            if tag_lang:
                                lang = str(tag_lang)
                except Exception:
                    lang = 'und'
                try:
                    if len(lang) == 2:
                        language = pycountry.languages.get(alpha_2=lang.lower())
                        if language:
                            lang = getattr(language, "bibliographic", getattr(language, "alpha_3", None)) or lang
                except Exception:
                    pass
                try:
                    idx = int(str(s.get('index') or '').strip())
                    out[idx] = lang
                except Exception:
                    pass
                try:
                    sid = str(s.get('id') or '').strip()
                    if sid:
                        if sid.lower().startswith('0x'):
                            out[int(sid, 16)] = lang
                        elif any(c in 'abcdefABCDEF' for c in sid):
                            out[int(sid, 16)] = lang
                        else:
                            out[int(sid, 10)] = lang
                except Exception:
                    pass
            pid_lang = out
        return BluraySubtitle._default_track_selection_from_streams(streams, pid_lang)

    @staticmethod
    def _sp_track_key_from_entry(entry: dict[str, int | str]) -> str:
        try:
            bdmv_index = int(entry.get('bdmv_index') or 0)
        except Exception:
            bdmv_index = 0
        mpls_file = str(entry.get('mpls_file') or '').strip()
        m2ts_file = str(entry.get('m2ts_file') or '').strip()
        if mpls_file:
            return f'sp::{bdmv_index}::mpls::{mpls_file}'
        first_m2ts = m2ts_file.split(',')[0].strip() if m2ts_file else ''
        return f'sp::{bdmv_index}::m2ts::{first_m2ts}'

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
            mkv_files_before = {f for f in os.listdir(dst_folder) if f.lower().endswith(('.mkv', '.mka'))}
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
            mkv_files_after = [f for f in os.listdir(dst_folder) if f.lower().endswith(('.mkv', '.mka'))]
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
        char_map = {
            '?': '？', '*': '★', '<': '《', '>': '》', ':': '：', '"': "'", '/': '／', '\\': '／', '|': '￨'
        }
        for i, p in enumerate(mkv_files, start=1):
            folder = os.path.dirname(p)
            base = os.path.basename(p)
            user_name = planned[i - 1].strip() if i - 1 < len(planned) and isinstance(planned[i - 1], str) else ''
            new_base = user_name if user_name else base
            if new_base:
                new_base = ''.join(char_map.get(char) or char for char in new_base)
                new_base = new_base.strip().rstrip('.')
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
            confs = list(bdmv_index_conf[bdmv_index])
            try:
                confs = sorted(
                    confs,
                    key=lambda c: int(c.get('chapter_index') or c.get('start_at_chapter') or 1),
                )
            except Exception:
                pass
            remux_cmd, m2ts_file, bdmv_vol, output_file, mpls_path, pid_to_lang, copy_audio_track, copy_sub_track = self._make_main_mpls_remux_cmd(
                confs=confs,
                dst_folder=dst_folder,
                bdmv_index=bdmv_index,
                disc_count=len(bdmv_index_conf),
                ensure_disc_out_dir=True,
            )
            if m2ts_file:
                print(f'{self.t("Analyzing first stream file in mpls ｢")}{m2ts_file}{self.t("｣ tracks")}')
                self._progress(text=f'{self.t("分析轨道：")}{os.path.basename(m2ts_file)}')
            print(f'{self.t("Mux command: ")}{remux_cmd}')
            self._progress(text=f'{self.t("混流中：")}BD_Vol_{bdmv_vol}')
            ret = self._run_shell_command(remux_cmd)
            try:
                ch_tmp = Chapter(mpls_path)
                n_clips = len(ch_tmp.in_out_time or [])
            except Exception:
                n_clips = 0
            cover = ''
            if n_clips > 1:
                try:
                    meta_folder = os.path.join(mpls_path[:-19], 'META', 'DL')
                    cover_size = 0
                    if os.path.exists(meta_folder):
                        for filename in os.listdir(meta_folder):
                            if filename.endswith(('.jpg', '.JPG', '.JPEG', '.jpeg', '.png', '.PNG')):
                                fp = os.path.join(meta_folder, filename)
                                sz = os.path.getsize(fp)
                                if sz > cover_size:
                                    cover = fp
                                    cover_size = sz
                except Exception:
                    cover = ''
            out_n = os.path.normpath(output_file) if output_file else ''
            out_exists = bool(out_n and os.path.isfile(out_n))
            expected_split_paths: list[str] = []
            if (not getattr(self, 'movie_mode', False)) and out_n and confs:
                try:
                    ch_seg = Chapter(mpls_path)
                    segs_b = BluraySubtitle._series_episode_segments_bounds(ch_seg, confs)
                    expected_split_paths = BluraySubtitle._expected_mkvmerge_split_output_paths(out_n, len(segs_b))
                except Exception:
                    expected_split_paths = []
            try:
                cmd_split_count = BluraySubtitle._split_segment_count_from_mkvmerge_cmd(remux_cmd)
            except Exception:
                cmd_split_count = None
            if out_n and isinstance(cmd_split_count, int) and cmd_split_count > 1:
                expected_from_cmd = BluraySubtitle._expected_mkvmerge_split_output_paths(out_n, cmd_split_count)
                if len(expected_from_cmd) >= len(expected_split_paths):
                    expected_split_paths = expected_from_cmd
            split_by_config = len(expected_split_paths) > 1
            stem_base, ext_base = os.path.splitext(os.path.basename(out_n)) if out_n else ('', '.mkv')
            alt001 = os.path.join(os.path.dirname(out_n), f'{stem_base}-001{ext_base or ".mkv"}') if out_n else ''
            if split_by_config:
                primary_ok = (ret == 0) and all(os.path.isfile(p) for p in expected_split_paths)
            elif out_n and expected_split_paths:
                primary_ok = (ret == 0) and (out_exists or (bool(alt001) and os.path.isfile(alt001)))
            else:
                primary_ok = (ret == 0) and out_exists
            fb_audio, fb_sub = BluraySubtitle._fallback_track_lists(remux_cmd, copy_audio_track, copy_sub_track)
            if n_clips > 1 and not primary_ok:
                if split_by_config:
                    self._progress(text=f'Mux fallback (multi-episode split aligned): BD_Vol_{bdmv_vol}')
                    split_ok = self._try_remux_mpls_split_outputs_track_aligned(
                        mpls_path,
                        out_n,
                        confs,
                        fb_audio,
                        fb_sub,
                        cover,
                        cancel_event=cancel_event,
                    )
                    if split_ok:
                        ret = 0
                        primary_ok = all(os.path.isfile(p) for p in expected_split_paths)
                    else:
                        print(f'[remux-fallback-split] failed for BD_Vol_{bdmv_vol} (see logs above)')
                        self._progress(text=f'Multi-episode split fallback failed: BD_Vol_{bdmv_vol} (see terminal [remux-fallback-split])')
                if n_clips > 1 and not primary_ok and (not split_by_config):
                    self._progress(text=f'Mux fallback (multi-m2ts aligned): BD_Vol_{bdmv_vol}')
                    if self._try_remux_mpls_track_aligned_concat(
                        mpls_path,
                        out_n,
                        fb_audio,
                        fb_sub,
                        cover,
                        cancel_event=cancel_event,
                    ):
                        ret = 0
            try:
                targets: list[str] = []
                out = os.path.normpath(output_file) if output_file else ''
                if out:
                    out_dir = os.path.dirname(out)
                    base_stem = os.path.splitext(os.path.basename(out))[0]
                    if out_dir and os.path.isdir(out_dir):
                        for fn in os.listdir(out_dir):
                            low = fn.lower()
                            if (fn.startswith(base_stem)) and low.endswith(('.mkv', '.mka')):
                                fp = os.path.normpath(os.path.join(out_dir, fn))
                                if os.path.isfile(fp):
                                    targets.append(fp)
                    if os.path.exists(out):
                        targets.append(out)
                targets = sorted(list(dict.fromkeys(targets)))
                for t in targets:
                    BluraySubtitle._fix_output_track_languages_with_mkvpropedit(
                        t,
                        m2ts_file,
                        pid_to_lang,
                        copy_audio_track,
                        copy_sub_track
                    )
            except Exception:
                pass
            self._progress(int(idx / max(len(bdmv_index_list), 1) * 300))

    def _run_shell_command(self, cmd: str) -> int:
        # Split multi-line commands and execute them sequentially
        commands = [line.strip() for line in cmd.split('\n') if line.strip()]
        if len(commands) <= 1:
            # Single command, execute as before
            return self._run_single_command(cmd)
        else:
            # Multiple commands, execute sequentially
            for single_cmd in commands:
                ret = self._run_single_command(single_cmd)
                if ret != 0:
                    return ret
            return 0

    def _run_single_command(self, cmd: str) -> int:
        if sys.platform == 'win32':
            return subprocess.Popen(cmd, shell=True).wait()
        def _fix_rm_glob(raw: str) -> str:
            # Convert rm "dir/*-007.mkv" -> rm "dir/"*-007.mkv so glob can expand.
            def _fix_quoted_token(m):
                token = m.group(1)
                if '*' not in token or '/' not in token:
                    return m.group(0)
                i = token.rfind('/')
                if i < 0:
                    return m.group(0)
                prefix = token[:i + 1]
                suffix = token[i + 1:]
                if '*' not in suffix:
                    return m.group(0)
                return f'"{prefix}"{suffix}'
            out = re.sub(r'"([^"]*\*[^"]*)"', _fix_quoted_token, raw)
            # If user chains cleanup with '&& rm', mkvmerge may return non-zero even when files are created,
            # so run cleanup unconditionally.
            out = re.sub(r'\s*&&\s*rm\b', r'; rm -f', out)
            return out
        cmd = _fix_rm_glob(cmd)
        try:
            return subprocess.Popen(['bash', '-lc', cmd]).wait()
        except Exception:
            return subprocess.Popen(cmd, shell=True).wait()

    def _make_main_mpls_remux_cmd(
        self,
        confs: list[dict[str, int | str]],
        dst_folder: str,
        bdmv_index: int,
        disc_count: int,
        *,
        ensure_disc_out_dir: bool = False,
    ) -> tuple[str, str, str, str, str, dict[int, str], list[str], list[str]]:
        mpls_path = confs[0]['selected_mpls'] + '.mpls'
        disc_name = ''
        try:
            disc_name = os.path.basename(os.path.normpath(str(getattr(self, 'bdmv_path', '') or '')).rstrip(os.sep))
        except Exception:
            disc_name = ''
        disc_name = disc_name or 'BDMV'
        disc_out_dir = ''
        if dst_folder:
            try:
                if os.path.basename(os.path.normpath(dst_folder).rstrip(os.sep)) == disc_name:
                    disc_out_dir = dst_folder
                else:
                    disc_out_dir = os.path.join(dst_folder, disc_name)
            except Exception:
                disc_out_dir = os.path.join(dst_folder, disc_name)
        if disc_out_dir and ensure_disc_out_dir:
            try:
                os.makedirs(disc_out_dir, exist_ok=True)
            except Exception:
                disc_out_dir = dst_folder

        chapter = Chapter(mpls_path)
        chapter.get_pid_to_language()
        m2ts_file = os.path.join(os.path.join(mpls_path[:-19], 'STREAM'), chapter.in_out_time[0][0] + '.m2ts')
        copy_audio_track, copy_sub_track = self._select_tracks_for_source(
            m2ts_file,
            chapter.pid_to_lang,
            config_key=f'main::{os.path.normpath(mpls_path)}'
        )
        meta_folder = os.path.join(os.path.join(mpls_path[:-19], 'META', 'DL'))
        cover = ''
        cover_size = 0
        if os.path.exists(meta_folder):
            for filename in os.listdir(meta_folder):
                if filename.endswith('.jpg') or filename.endswith('.JPG') or filename.endswith('.JPEG') or filename.endswith('.jpeg') or filename.endswith('.png') or filename.endswith('.PNG'):
                    if os.path.getsize(os.path.join(meta_folder, filename)) > cover_size:
                        cover = os.path.join(meta_folder, filename)
                        cover_size = os.path.getsize(os.path.join(meta_folder, filename))
        try:
            output_name = str(confs[0].get('disc_output_name') or '').strip()
        except Exception:
            output_name = ''
        if not output_name:
            output_name = self._resolve_disc_output_name(confs[0]['selected_mpls'])

        bdmv_vol = '0' * (3 - len(str(bdmv_index))) + str(bdmv_index)
        if getattr(self, 'movie_mode', False):
            try:
                output_name_from_conf = str(confs[0].get('output_name') or '').strip()
            except Exception:
                output_name_from_conf = ''
            if output_name_from_conf:
                base = output_name_from_conf
                if not base.lower().endswith('.mkv'):
                    base += '.mkv'
                output_file = base if os.path.isabs(base) else os.path.join(disc_out_dir or dst_folder, base)
            else:
                output_file = f'{os.path.join(disc_out_dir or dst_folder, output_name)}_BD_Vol_{bdmv_vol}.mkv'
            if disc_count == 1:
                out_dir = os.path.dirname(output_file)
                out_base = os.path.basename(output_file)
                out_base = re.sub(rf'(?i)^BD_Vol_{bdmv_vol}_', '', out_base)
                out_base = re.sub(rf'(?i)_BD_Vol_{bdmv_vol}(?=\.mkv$)', '', out_base)
                output_file = os.path.join(out_dir, out_base)
            default_audio_opts = (f'-a {",".join(copy_audio_track)}' if copy_audio_track else '')
            default_sub_opts = (f'-s {",".join(copy_sub_track)}' if copy_sub_track else '')
            default_cover_opts = (f'--attachment-name Cover.jpg --attach-file "{cover}"' if cover else '')
            default_cmd = (f'"{MKV_MERGE_PATH}" {mkvtoolnix_ui_language_arg()} --chapter-language eng -o "{output_file}" '
                           f'{default_audio_opts} {default_sub_opts} {default_cover_opts} "{mpls_path}"').strip()
            custom_cmd = str(confs[0].get('main_remux_cmd') or '').strip()
            if custom_cmd:
                remux_cmd = (custom_cmd
                             .replace('{output_file}', output_file)
                             .replace('{mpls_path}', mpls_path)
                             .replace('{audio_opts}', default_audio_opts)
                             .replace('{sub_opts}', default_sub_opts)
                             .replace('{cover_opts}', default_cover_opts)
                             .replace('{chapter_split}', ''))
            else:
                remux_cmd = default_cmd
        else:
            confs_sorted = sorted(confs, key=lambda c: int(c.get('chapter_index') or c.get('start_at_chapter') or 1))
            rows = sum(map(len, chapter.mark_info.values()))
            total_end = rows + 1
            segments = BluraySubtitle._series_episode_segments_bounds(chapter, confs)
            chapter_starts = [int(c.get('start_at_chapter') or c.get('chapter_index') or 1) for c in confs_sorted]
            chapter_after_first = [s for s in chapter_starts[1:] if 1 < s <= rows]
            chapter_split = ','.join(map(str, chapter_after_first))
            use_split_parts = not bool(confs[0].get('chapter_segments_fully_checked', True)) if confs else False
            index_to_m2ts, index_to_offset = get_index_to_m2ts_and_offset(chapter)
            def _off(idx: int) -> float:
                if idx >= total_end:
                    return chapter.get_total_time()
                return float(index_to_offset.get(idx, 0.0))
            parts_list: list[str] = []
            for s, e in segments:
                st = get_time_str(_off(s))
                ed = get_time_str(_off(e))
                if st == '0':
                    st = '00:00:00.000'
                if ed == '0':
                    ed = '00:00:00.000'
                parts_list.append(f'{st}-{ed}')
            parts_split = ','.join(parts_list)
            output_file = f'{os.path.join(disc_out_dir or dst_folder, output_name)}_BD_Vol_{bdmv_vol}.mkv'
            default_audio_opts = (f'-a {",".join(copy_audio_track)}' if copy_audio_track else '')
            default_sub_opts = (f'-s {",".join(copy_sub_track)}' if copy_sub_track else '')
            default_cover_opts = (f'--attachment-name Cover.jpg --attach-file "{cover}"' if cover else '')
            if use_split_parts:
                split_arg = (f'--split parts:{parts_split}' if parts_split else '')
            else:
                split_arg = (f'--split chapters:{chapter_split}' if chapter_split else '')
            default_cmd = (f'"{MKV_MERGE_PATH}" {mkvtoolnix_ui_language_arg()} {split_arg} -o "{output_file}" '
                           f'{default_audio_opts} {default_sub_opts} {default_cover_opts} "{mpls_path}"').strip()
            custom_cmd = str(confs[0].get('main_remux_cmd') or '').strip()
            if custom_cmd:
                remux_cmd = (custom_cmd
                             .replace('{output_file}', output_file)
                             .replace('{mpls_path}', mpls_path)
                             .replace('{audio_opts}', default_audio_opts)
                             .replace('{sub_opts}', default_sub_opts)
                             .replace('{cover_opts}', default_cover_opts)
                             .replace('{chapter_split}', chapter_split)
                             .replace('{parts_split}', parts_split))
            else:
                remux_cmd = default_cmd
        return remux_cmd, m2ts_file, bdmv_vol, output_file, mpls_path, chapter.pid_to_lang, copy_audio_track, copy_sub_track

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
            self.add_chapter_to_mkv(
                mkv_files, table, selected_mpls=selected_mpls, cancel_event=cancel_event,
                configuration=self.configuration,
            )
            self._progress(400)

        i = 0
        for mkv_file in mkv_files:
            if cancel_event and cancel_event.is_set():
                raise _Cancelled()
            i += 1
            self._progress(text=f'Compressing audio: {os.path.basename(mkv_file)}')
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
                            entry = {'bdmv_index': bdmv_index, 'mpls_file': mpls_file, 'm2ts_file': '', 'output_name': out_name}
                            key = BluraySubtitle._sp_track_key_from_entry(entry)
                            copy_audio_track, copy_sub_track = self._select_tracks_for_source(mpls_file_path, {}, key)
                            chapter_txt = os.path.join(sps_folder, f'{os.path.splitext(out_name)[0]}.chapter.txt')
                            try:
                                offs = self._write_chapter_txt_from_mpls(mpls_file_path, chapter_txt)
                                if len(offs) == 1 and offs[0] == 0.0:
                                    force_remove_file(chapter_txt)
                            except Exception:
                                traceback.print_exc()
                                chapter_txt = ''
                            subprocess.Popen(f'"{MKV_MERGE_PATH}" {mkvtoolnix_ui_language_arg()} '
                                             f'{("--chapters " + "\"" + chapter_txt + "\"") if chapter_txt else ""} '
                                             f'-o "{os.path.join(sps_folder, out_name)}" '
                                             f'{("-a " + ",".join(copy_audio_track)) if copy_audio_track else ""} '
                                             f'{("-s " + ",".join(copy_sub_track)) if copy_sub_track else ""} '
                                             f'"{mpls_file_path}"',
                                             shell=True).wait()
                            if chapter_txt:
                                try:
                                    force_remove_file(chapter_txt)
                                except Exception:
                                    pass
                            parsed_m2ts_files |= set(index_to_m2ts.values())
                stream_folder = os.path.dirname(mpls_path).replace('PLAYLIST', '') + 'STREAM'
                for stream_file in sorted(os.listdir(stream_folder)):
                    if cancel_event and cancel_event.is_set():
                        raise _Cancelled()
                    if stream_file not in parsed_m2ts_files and stream_file.endswith('.m2ts'):
                        if M2TS(os.path.join(stream_folder, stream_file)).get_duration() > 30 * 90000:
                            src_stream = os.path.join(stream_folder, stream_file)
                            ext = '.mka' if BluraySubtitle._is_audio_only_media(src_stream) else '.mkv'
                            out_name = (f'{stream_file[:-5]}{ext}'
                                        if single_volume else f'BD_Vol_{bdmv_vol}_{stream_file[:-5]}{ext}')
                            entry = {'bdmv_index': bdmv_index, 'mpls_file': '', 'm2ts_file': stream_file, 'output_name': out_name}
                            key = BluraySubtitle._sp_track_key_from_entry(entry)
                            copy_audio_track, copy_sub_track = self._select_tracks_for_source(
                                os.path.join(stream_folder, stream_file), {}, key
                            )
                            subprocess.Popen(
                                f'"{MKV_MERGE_PATH}" {mkvtoolnix_ui_language_arg()} -o "{os.path.join(sps_folder, out_name)}" '
                                f'{("-a " + ",".join(copy_audio_track)) if copy_audio_track else ""} '
                                f'{("-s " + ",".join(copy_sub_track)) if copy_sub_track else ""} '
                                f'"{os.path.join(stream_folder, stream_file)}"',
                                shell=True
                            ).wait()
        sp_files = [sp for sp in os.listdir(sps_folder) if sp.lower().endswith(('.mkv', '.mka'))]
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
            self.add_chapter_to_mkv(
                mkv_files, table, selected_mpls=selected_mpls, cancel_event=cancel_event,
                configuration=self.configuration,
            )
            self._progress(400)

        i = 0
        for mkv_file in mkv_files:
            if cancel_event and cancel_event.is_set():
                raise _Cancelled()
            i += 1
            self._progress(text=f'Encode and mux: {os.path.basename(mkv_file)}')
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
                self._progress(text=f'Encode and mux SPs: {os.path.basename(sp_mkv_path)}')
                if os.path.isdir(sp_mkv_path) or (not os.path.exists(sp_mkv_path)):
                    self._progress(900 + int(90 * idx / total_sp))
                    continue
                low = sp_mkv_path.lower()
                if low.endswith('.mka'):
                    self.flac_task(sp_mkv_path, sps_folder, -1)
                    self._progress(900 + int(90 * idx / total_sp))
                    continue
                if (not low.endswith('.mkv')):
                    self._progress(900 + int(90 * idx / total_sp))
                    continue
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
                            entry = {'bdmv_index': bdmv_index, 'mpls_file': mpls_file, 'm2ts_file': '', 'output_name': out_name}
                            key = BluraySubtitle._sp_track_key_from_entry(entry)
                            copy_audio_track, copy_sub_track = self._select_tracks_for_source(mpls_file_path, {}, key)
                            chapter_txt = os.path.join(sps_folder, f'{os.path.splitext(out_name)[0]}.chapter.txt')
                            try:
                                offs = self._write_chapter_txt_from_mpls(mpls_file_path, chapter_txt)
                                if len(offs) == 1 and offs[0] == 0.0:
                                    force_remove_file(chapter_txt)
                            except Exception:
                                traceback.print_exc()
                                chapter_txt = ''
                            subprocess.Popen(f'"{MKV_MERGE_PATH}" {mkvtoolnix_ui_language_arg()} '
                                             f'{("--chapters " + "\"" + chapter_txt + "\"") if chapter_txt else ""} '
                                             f'-o "{os.path.join(sps_folder, out_name)}" '
                                             f'{("-a " + ",".join(copy_audio_track)) if copy_audio_track else ""} '
                                             f'{("-s " + ",".join(copy_sub_track)) if copy_sub_track else ""} '
                                             f'"{mpls_file_path}"',
                                             shell=True).wait()
                            if chapter_txt:
                                try:
                                    force_remove_file(chapter_txt)
                                except Exception:
                                    pass
                            parsed_m2ts_files |= set(index_to_m2ts.values())
                stream_folder = os.path.dirname(mpls_path).replace('PLAYLIST', '') + 'STREAM'
                for stream_file in os.listdir(stream_folder):
                    if cancel_event and cancel_event.is_set():
                        raise _Cancelled()
                    if stream_file not in parsed_m2ts_files and stream_file.endswith('.m2ts'):
                        if M2TS(os.path.join(stream_folder, stream_file)).get_duration() > 30 * 90000:
                            src_stream = os.path.join(stream_folder, stream_file)
                            ext = '.mka' if BluraySubtitle._is_audio_only_media(src_stream) else '.mkv'
                            out_name = (f'{stream_file[:-5]}{ext}'
                                        if single_volume else f'BD_Vol_{bdmv_vol}_{stream_file[:-5]}{ext}')
                            entry = {'bdmv_index': bdmv_index, 'mpls_file': '', 'm2ts_file': stream_file, 'output_name': out_name}
                            key = BluraySubtitle._sp_track_key_from_entry(entry)
                            copy_audio_track, copy_sub_track = self._select_tracks_for_source(
                                os.path.join(stream_folder, stream_file), {}, key
                            )
                            subprocess.Popen(
                                f'"{MKV_MERGE_PATH}" {mkvtoolnix_ui_language_arg()} -o "{os.path.join(sps_folder, out_name)}" '
                                f'{("-a " + ",".join(copy_audio_track)) if copy_audio_track else ""} '
                                f'{("-s " + ",".join(copy_sub_track)) if copy_sub_track else ""} '
                                f'"{os.path.join(stream_folder, stream_file)}"',
                                shell=True
                            ).wait()
            sp_files = [os.path.join(sps_folder, sp) for sp in os.listdir(sps_folder) if sp.lower().endswith(('.mkv', '.mka'))]
            sp_files.sort()
            total_sp = len(sp_files) or 1
            for idx, sp_path in enumerate(sp_files, start=1):
                if cancel_event and cancel_event.is_set():
                    raise _Cancelled()
                self._progress(text=f'Encode and mux SPs: {os.path.basename(sp_path)}')
                if sp_path.lower().endswith('.mka'):
                    self.flac_task(sp_path, sps_folder, -1)
                else:
                    if sp_vpy_paths and 0 <= (idx - 1) < len(sp_vpy_paths) and sp_vpy_paths[idx - 1]:
                        cur_sp_vpy = sp_vpy_paths[idx - 1]
                    else:
                        cur_sp_vpy = os.path.join(os.getcwd(), 'vpy.vpy')
                    self.encode_task(sp_path, sps_folder, -1, cur_sp_vpy, vspipe_mode, x265_mode, x265_params, 'external')
                self._progress(900 + int(90 * idx / total_sp))

        self.completion()
        self._progress(1000, '完成')

    def process_audio_to_flac(self, output_file, dst_folder, i, source_file: Optional[str] = None) -> tuple[int, dict[int, str], list[str]]:
        dolby_truehd_tracks = []
        track_bits = {}
        track_id_delay_map = {}
        duplicate_track_source: dict[int, int] = {}
        self._track_flac_map = {}
        self._audio_tracks_to_exclude = set()
        flac_files = []
        src_mkv = os.path.normpath(source_file) if source_file else os.path.normpath(output_file)
        def _track_id_from_path(p: str) -> Optional[int]:
            name = os.path.basename(p or '')
            m = re.search(r'(?i)\.track(\d+)', name)
            if not m:
                return None
            try:
                return int(m.group(1))
            except Exception:
                return None
        if os.path.exists(src_mkv):
            subprocess.Popen(f'"{FFPROBE_PATH}" -v error -show_streams -show_format -of json "{src_mkv}" >info.json 2>&1',
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
            print('\033[31mError: movie mux failed, please check task output\033[0m')
        base = os.path.join(dst_folder, os.path.splitext(os.path.basename(output_file))[0])
        track_count, track_info = self.extract_lossless(src_mkv, dolby_truehd_tracks, output_base=base)
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
                    fns = sorted(fns, key=lambda p: (_track_id_from_path(p) if _track_id_from_path(p) is not None else 10**9, p))
                    fpts: list[tuple[np.ndarray, int, str]] = []
                    for fn in fns:
                        tmp_wav = None
                        fp_source = fn
                        track_id = _track_id_from_path(fn)
                        track_id_val = int(track_id) if track_id is not None else -1
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
                            if y is None or len(y) == 0 or float(np.max(np.abs(y))) < 1e-8:
                                raise Exception('silent')
                            chroma = librosa.feature.chroma_stft(y=y, sr=sr, tuning=0.0)
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
                        for j, (_fpt, _src_track_id, _src_fn) in enumerate(list(fpts)):
                            denom = (np.linalg.norm(fpt) * np.linalg.norm(_fpt))
                            sim = (np.dot(fpt, _fpt) / denom) if denom else 0.0
                            if sim > 0.9997:
                                # Keep smaller track id when two tracks are considered duplicated.
                                keep_current = False
                                if track_id_val > -1 and _src_track_id > -1 and track_id_val < _src_track_id:
                                    keep_current = True
                                if keep_current:
                                    try:
                                        os.remove(_src_fn)
                                    except Exception:
                                        pass
                                    if _src_track_id > -1 and track_id_val > -1:
                                        duplicate_track_source[_src_track_id] = track_id_val
                                        self._audio_tracks_to_exclude.add(_src_track_id)
                                        track_info.pop(_src_track_id, None)
                                    fpts[j] = (fpt, track_id_val, fn)
                                    print(f'Found duplicate audio track ｢{_src_fn}｣, deleted')
                                else:
                                    os.remove(fn)
                                    if track_id_val > -1 and _src_track_id > -1:
                                        duplicate_track_source[track_id_val] = _src_track_id
                                        self._audio_tracks_to_exclude.add(track_id_val)
                                        track_info.pop(track_id_val, None)
                                    print(f'Found duplicate audio track ｢{fn}｣, deleted')
                                duplicate_track = True
                                break
                        if not duplicate_track:
                            fpts.append((fpt, track_id_val, fn))

            def _is_silent_audio(path: str, threshold_db: float = -60.0) -> tuple[bool, float]:
                try:
                    proc = subprocess.run(
                        f'"{FFMPEG_PATH}" -hide_banner -nostats -i "{path}" -af volumedetect -f null -',
                        shell=True,
                        capture_output=True,
                        text=True,
                        encoding='utf-8',
                        errors='ignore'
                    )
                    text_out = (proc.stderr or '') + '\n' + (proc.stdout or '')
                    m_mean = re.search(r'mean_volume:\s*([-\d\.]+)\s*dB', text_out)
                    m_max = re.search(r'max_volume:\s*([-\d\.]+)\s*dB', text_out)
                    mean_db = float(m_mean.group(1)) if m_mean else float('-inf')
                    max_db = float(m_max.group(1)) if m_max else float('-inf')
                    if mean_db == float('-inf') and max_db == float('-inf'):
                        return True, float('-inf')
                    return (max_db < threshold_db), mean_db
                except Exception:
                    pass
                y = None
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
                if y is None or len(y) == 0:
                    return True, float('-inf')
                if float(np.max(np.abs(y))) < 1e-8:
                    return True, float('-inf')
                rms = librosa.feature.rms(y=y)
                db = librosa.amplitude_to_db(rms, ref=np.max)
                avg_db = float(np.mean(db)) if db.size else float('-inf')
                if avg_db != avg_db:
                    return True, float('-inf')
                return avg_db < threshold_db, avg_db

            for file1 in os.listdir(dst_folder):
                file1_path = os.path.join(dst_folder, file1)
                if not os.path.isfile(file1_path):
                    continue
                track_id = _track_id_from_path(file1_path)
                if track_id is None:
                    continue
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
                            track_id = _track_id_from_path(file1_path)
                            if track_id is not None:
                                track_info.pop(int(track_id), None)
                                self._audio_tracks_to_exclude.add(int(track_id))
                        except Exception:
                            pass
                        print(f'{translate_text("Detected empty audio track ｢")}{file1_path}{translate_text("｣ average ")}{avg_db:.1f}{translate_text(" dB, deleted")}')
                        continue
                    print(f'{translate_text("Compressing audio track ｢")}{file1_path}{translate_text("｣")}')
                    track_id = int(track_id)
                    if track_id in track_id_delay_map:
                        delay_sec = track_id_delay_map[track_id]
                        delay_ms = int(round(delay_sec * 1000.0))
                        print(f'{translate_text("Detected file ｢")}{file1_path}{translate_text("｣ has delay ")}{delay_ms} ms')
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
                            print(f'{translate_text("Detected file ｢")}{file1_path}{translate_text("｣ effective bit depth is low, optimizing to 16-bit...")}')
                            codec = "pcm_s16le"
                            output_fn = os.path.splitext(file1_path)[0] + '(1).wav'
                            cmd = f'"{FFMPEG_PATH}" -hide_banner -loglevel error -i "{file1_path}" -c:a {codec} "{output_fn}" -y'
                            subprocess.run(cmd, shell=True, check=True)
                            if os.path.exists(output_fn):
                                print(f'{translate_text("Conversion completed: ｢")}{output_fn}{translate_text("｣")}')
                                os.remove(file1_path)
                                os.rename(output_fn, file1_path)

                        flac_file = os.path.splitext(file1_path)[0] + '.flac'
                        subprocess.Popen(f'"{FLAC_PATH}" -8 -j {FLAC_THREADS} "{file1_path}" -o "{flac_file}"', shell=True).wait()
                        if os.path.exists(flac_file):
                            delta = os.path.getsize(file1_path) - os.path.getsize(flac_file)
                            os.remove(file1_path)
                            print(f'{translate_text("Track ｢")}{file1_path}{translate_text("｣ compressed to FLAC to reduce size ")}{delta / 1024 ** 2:.3f} MiB')
                            self._audio_tracks_to_exclude.add(track_id)
                        else:
                            subprocess.Popen(f'{FFMPEG_PATH} -i "{file1_path}" -c:a flac "{flac_file}"', shell=True).wait()
                            if os.path.exists(flac_file):
                                delta = os.path.getsize(file1_path) - os.path.getsize(flac_file)
                                os.remove(file1_path)
                                print(f'{translate_text("Track ｢")}{file1_path}{translate_text("｣ compressed to FLAC with ffmpeg to reduce size ")}{delta / 1024 ** 2:.3f} MiB')
                                self._audio_tracks_to_exclude.add(track_id)
                    else:
                        bits = track_bits.get(track_id, 24)
                        effective_bits = get_compressed_effective_depth(file1_path)
                        if effective_bits < bits:
                            print(f'{translate_text("Detected file ｢")}{file1_path}{translate_text("｣ actual effective bit depth is ")}{effective_bits} bits')
                        wav_file = os.path.splitext(file1_path)[0] + '.wav'
                        subprocess.Popen(f'{FFMPEG_PATH} -i "{file1_path}"  -c:a pcm_s{effective_bits}le -f w64 "{wav_file}"', shell=True).wait()
                        flac_file = os.path.splitext(file1_path)[0] + '.flac'
                        subprocess.Popen(f'{FLAC_PATH} -8 -j {FLAC_THREADS} "{wav_file}" -o "{flac_file}"', shell=True).wait()
                        if os.path.exists(flac_file):
                            if os.path.getsize(flac_file) > os.path.getsize(file1_path):
                                print(f'{translate_text("FLAC is larger than the original track, deleting ｢")}{flac_file}{translate_text("｣")}')
                                os.remove(flac_file)
                            else:
                                delta = os.path.getsize(file1_path) - os.path.getsize(flac_file)
                                print(f'{translate_text("Track ｢")}{file1_path}{translate_text("｣ compressed to FLAC to reduce size ")}{delta / 1024 ** 2:.3f} MiB')
                                self._audio_tracks_to_exclude.add(track_id)
                        else:
                            subprocess.Popen(f'{FFMPEG_PATH} -i "{wav_file}" -c:a flac "{flac_file}"', shell=True).wait()
                            if os.path.exists(flac_file):
                                if os.path.getsize(flac_file) > os.path.getsize(file1_path):
                                    print(f'{translate_text("ffmpeg-compressed FLAC is larger than the original track, deleting ｢")}{flac_file}{translate_text("｣")}')
                                    os.remove(flac_file)
                                else:
                                    delta = os.path.getsize(file1_path) - os.path.getsize(flac_file)
                                    print(f'{translate_text("Track ｢")}{file1_path}{translate_text("｣ compressed to FLAC with ffmpeg to reduce size ")}{delta / 1024 ** 2:.3f} MiB')
                                    self._audio_tracks_to_exclude.add(track_id)
                            else:
                                print('\033[31mError: ffmpeg compression also failed\033[0m')
                        os.remove(file1_path)
                        os.remove(wav_file)
            flac_files = []
            base_prefix = os.path.splitext(os.path.basename(output_file or ''))[0]
            for file1 in os.listdir(dst_folder):
                file1_path = os.path.join(dst_folder, file1)
                if not (os.path.isfile(file1_path) and file1_path.endswith('.flac')):
                    continue
                if base_prefix and (not file1.startswith(base_prefix)):
                    continue
                if '.track' not in file1.lower():
                    continue
                flac_files.append(file1_path)
            if not flac_files:
                for file1 in os.listdir(dst_folder):
                    file1_path = os.path.join(dst_folder, file1)
                    if file1_path != output_file:
                        if file1_path.endswith('.wav') and (base_prefix and os.path.basename(file1_path).startswith(base_prefix)) and ('.track' in os.path.basename(file1_path).lower()):
                            n = len(os.listdir(dst_folder))
                            print(f'{translate_text("flac compressing wav file ｢")}{file1_path}{translate_text("｣ failed, will use ffmpeg to compress")}')
                            subprocess.Popen(
                                f'{FFMPEG_PATH} -i "{file1_path}" -c:a flac "{file1_path[:-4] + ".flac"}"', shell=True).wait()
                            if len(os.listdir(dst_folder)) > n:
                                os.remove(file1_path)
                for file1 in os.listdir(dst_folder):
                    file1_path = os.path.join(dst_folder, file1)
                    if not (os.path.isfile(file1_path) and file1_path.endswith('.flac')):
                        continue
                    if base_prefix and (not file1.startswith(base_prefix)):
                        continue
                    if '.track' not in file1.lower():
                        continue
                    flac_files.append(file1_path)
            track_flac_map: dict[int, str] = {}
            for flac in flac_files:
                tid = _track_id_from_path(flac)
                if tid is not None:
                    track_flac_map[int(tid)] = flac
            self._track_flac_map = track_flac_map
            for tid in track_info.keys():
                try:
                    self._audio_tracks_to_exclude.add(int(tid))
                except Exception:
                    pass
        return track_count, track_info, flac_files

    def flac_task(self, output_file, dst_folder, i, source_file: Optional[str] = None):
        track_count, track_info, flac_files = self.process_audio_to_flac(output_file, dst_folder, i, source_file=source_file)
        if flac_files:
            src_mkv = os.path.normpath(source_file) if source_file else os.path.normpath(output_file)
            same_mkv = os.path.normpath(output_file) == src_mkv
            output_file1 = (os.path.splitext(output_file)[0] + '.tmp.mkv') if same_mkv else output_file
            remux_cmd = self.generate_remux_cmd(track_count, track_info, flac_files, output_file1, src_mkv)
            if self.sub_files and len(self.sub_files) >= i and i > -1:
                lang = 'chi'
                try:
                    langs = getattr(self, 'episode_subtitle_languages', None) or []
                    if 0 <= (i - 1) < len(langs) and str(langs[i - 1]).strip():
                        lang = str(langs[i - 1]).strip()
                except Exception:
                    lang = 'chi'
                remux_cmd += f' --language 0:{lang} "{self.sub_files[i - 1]}"'
            print(f'{translate_text("Mux command:")}{remux_cmd}')
            subprocess.Popen(remux_cmd, shell=True).wait()
            if same_mkv:
                if os.path.getsize(output_file1) > os.path.getsize(output_file):
                    os.remove(output_file1)
                else:
                    os.remove(output_file)
                    os.rename(output_file1, output_file)
            for flac_file in flac_files:
                os.remove(flac_file)
        BluraySubtitle._extract_single_audio_from_mka(output_file)

    def encode_task(self, output_file, dst_folder, i, vpy_path: str, vspipe_mode: str, x265_mode: str, x265_params: str, sub_pack_mode: str, source_file: Optional[str] = None):
        src_mkv = os.path.normpath(source_file) if source_file else os.path.normpath(output_file)
        def update_vpy_script():
            if not os.path.exists(vpy_path):
                return
            try:
                with open(vpy_path, 'r', encoding='utf-8') as fp:
                    lines = fp.readlines()
            except Exception:
                traceback.print_exc()
                return

            mkv_real_path = os.path.normpath(src_mkv)
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
        print(f'{translate_text("Encode command:")}{cmd}')
        subprocess.Popen(cmd, shell=True, env=vspipe_env).wait()
        cleanup_lwi_for_source(src_mkv)
        track_count, track_info, flac_files = self.process_audio_to_flac(output_file, dst_folder, i, source_file=src_mkv)
        if flac_files or os.path.exists(hevc_file):
            same_mkv = os.path.normpath(output_file) == src_mkv
            output_file1 = (os.path.splitext(output_file)[0] + '.tmp.mkv') if same_mkv else output_file
            if not same_mkv and os.path.exists(output_file1):
                force_remove_file(output_file1)
            remux_cmd = self.generate_remux_cmd(track_count, track_info, flac_files, output_file1, src_mkv,
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
            print(f'{translate_text("Mux command:")}{remux_cmd}')
            subprocess.Popen(remux_cmd, shell=True).wait()
            if same_mkv:
                if os.path.getsize(output_file1) > os.path.getsize(output_file):
                    os.remove(output_file1)
                else:
                    os.remove(output_file)
                    os.rename(output_file1, output_file)
            for flac_file in flac_files:
                os.remove(flac_file)
            if os.path.exists(hevc_file):
                os.remove(hevc_file)
        cleanup_lwi_for_source(src_mkv)

    def generate_remux_cmd(self, track_count, track_info, flac_files, output_file, mkv_file, hevc_file: Optional[str] = None):
        copy_audio_track = list(getattr(self, '_active_copy_audio_track', []) or [])
        copy_sub_track = list(getattr(self, '_active_copy_sub_track', []) or [])
        track_flac_map = getattr(self, '_track_flac_map', {}) or {}
        audio_tracks_to_exclude = sorted({int(x) for x in (getattr(self, '_audio_tracks_to_exclude', set()) or set()) if str(x).strip() != ''})
        tracker_order = []
        audio_tracks = []
        pcm_track_count = 0
        language_options = []
        for _ in range(track_count + 1):
            if _ in track_info:
                pcm_track_count += 1
                flac_src = track_flac_map.get(_)
                if not flac_src:
                    try:
                        flac_src = flac_files[pcm_track_count - 1]
                    except IndexError:
                        continue
                language_options.append(f'--language 0:{track_info[_]} "{flac_src}"')
                tracker_order.append(f'{pcm_track_count}:0')
            elif _ in audio_tracks_to_exclude:
                continue
            else:
                tracker_order.append(f'0:{_}')
        tracker_order = ','.join(tracker_order)
        audio_tracks = ('!' + ','.join([str(x) for x in audio_tracks_to_exclude])) if audio_tracks_to_exclude else ''
        language_options = ' '.join(language_options)
        if not hevc_file:
            return (f'"{MKV_MERGE_PATH}" {mkvtoolnix_ui_language_arg()} -o "{output_file}" --track-order {tracker_order} '
                    f'{("-a " + ",".join(copy_audio_track)) if copy_audio_track else ""} '
                    f'{("-s " + ",".join(copy_sub_track)) if copy_sub_track else ""} '
                    f'{"-a " + audio_tracks if audio_tracks else ""} "{mkv_file}" {language_options}')
        else:
            tracker_order = f'{pcm_track_count + 1}:0,{tracker_order}'
            return (f'"{MKV_MERGE_PATH}" {mkvtoolnix_ui_language_arg()} -o "{output_file}" --track-order {tracker_order} '
                    f'{("-a " + ",".join(copy_audio_track)) if copy_audio_track else ""} '
                    f'{("-s " + ",".join(copy_sub_track)) if copy_sub_track else ""} '
                    f'-d !0 {"-a " + audio_tracks if audio_tracks else ""} "{mkv_file}" {language_options} "{hevc_file}"')

    def extract_lossless(self, mkv_file: str, dolby_truehd_tracks: list[int], output_base: Optional[str] = None) -> tuple[int, dict[int, str]]:
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
            base = output_base if output_base else mkv_file[:-4]
            for track_id, lang in track_info.items():
                extract_info.append(
                    f'{track_id}:"{base}.track{track_id}.{track_suffix_info[track_id]}"')
            extract_cmd = f'"{MKV_EXTRACT_PATH}" {mkvtoolnix_ui_language_arg()} "{mkv_file}" tracks {" ".join(extract_info)}'
            print(f'{translate_text("Extracting lossless tracks, command: ")}{extract_cmd}')
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
                 movie_mode: bool = False,
                 track_selection_config: Optional[dict[str, dict[str, list[str]]]] = None):
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
        self.track_selection_config = track_selection_config or {}

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
            bs.track_selection_config = self.track_selection_config
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
                 movie_mode: bool = False,
                 track_selection_config: Optional[dict[str, dict[str, list[str]]]] = None):
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
        self.track_selection_config = track_selection_config or {}

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
            bs.track_selection_config = self.track_selection_config
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


class EncodeMkvFolderWorker(QObject):
    progress = pyqtSignal(int)
    label = pyqtSignal(str)
    finished = pyqtSignal()
    canceled = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(
        self,
        mkv_rows: list[dict[str, str]],
        sp_rows: list[dict[str, str]],
        remux_folder: str,
        output_folder: str,
        cancel_event: threading.Event,
        vspipe_mode: str,
        x265_mode: str,
        x265_params: str,
        sub_pack_mode: str,
    ):
        super().__init__()
        self.mkv_rows = mkv_rows
        self.sp_rows = sp_rows
        self.remux_folder = str(remux_folder or '')
        self.output_folder = output_folder
        self.cancel_event = cancel_event
        self.vspipe_mode = vspipe_mode
        self.x265_mode = x265_mode
        self.x265_params = x265_params
        self.sub_pack_mode = sub_pack_mode

    def _link_or_copy(self, src: str, dst: str):
        if os.path.exists(dst):
            force_remove_file(dst)
        try:
            os.link(src, dst)
            return
        except Exception:
            pass
        shutil.copy2(src, dst)

    def _copy_non_mkv_from_remux_folder(self, src_root: str, dst_root: str):
        if not src_root or not os.path.isdir(src_root):
            return
        src_root = os.path.normpath(src_root)
        dst_root = os.path.normpath(dst_root)
        for cur, dirs, files in os.walk(src_root):
            if self.cancel_event.is_set():
                raise _Cancelled()
            rel = os.path.relpath(cur, src_root)
            if rel == '.':
                rel = ''
            dst_dir = os.path.join(dst_root, rel) if rel else dst_root
            os.makedirs(dst_dir, exist_ok=True)
            for d in dirs:
                os.makedirs(os.path.join(dst_dir, d), exist_ok=True)
            for fn in files:
                if fn.lower().endswith('.mkv'):
                    continue
                src = os.path.join(cur, fn)
                dst = os.path.join(dst_dir, fn)
                if os.path.exists(dst):
                    continue
                try:
                    shutil.copy2(src, dst)
                except Exception:
                    pass

    def run(self):
        try:
            def progress_cb(value: Optional[int] = None, text: Optional[str] = None):
                if value is not None:
                    self.progress.emit(int(value))
                if text:
                    self.label.emit(str(text))
                if self.cancel_event.is_set():
                    raise _Cancelled()

            dst_folder = os.path.normpath(self.output_folder)
            os.makedirs(dst_folder, exist_ok=True)

            sub_files = [str(r.get('sub_path') or '') for r in self.mkv_rows]
            episode_subtitle_languages = [str(r.get('language') or '') for r in self.mkv_rows]

            bs = BluraySubtitle('', sub_files, True, progress_cb, movie_mode=True)
            bs.episode_subtitle_languages = episode_subtitle_languages

            total = max(1, len(self.mkv_rows) + len(self.sp_rows))
            done = 0
            for i, row in enumerate(self.mkv_rows):
                progress_cb(int(done / total * 1000), f'压制中 {done + 1}/{total}')
                src = os.path.normpath(str(row.get('src_path') or ''))
                out_name = str(row.get('output_name') or '').strip() or os.path.basename(src)
                if not out_name.lower().endswith('.mkv'):
                    out_name += '.mkv'
                dst = os.path.join(dst_folder, out_name)
                vpy_path = str(row.get('vpy_path') or '').strip()
                bs.encode_task(
                    dst,
                    dst_folder,
                    i + 1,
                    vpy_path,
                    self.vspipe_mode,
                    self.x265_mode,
                    self.x265_params,
                    self.sub_pack_mode,
                    source_file=src
                )
                done += 1

            sps_out = None
            for row in self.sp_rows:
                progress_cb(int(done / total * 1000), f'压制中 {done + 1}/{total}')
                src = os.path.normpath(str(row.get('src_path') or ''))
                out_name = str(row.get('output_name') or '').strip() or os.path.basename(src)
                if not out_name.lower().endswith('.mkv'):
                    out_name += '.mkv'
                if sps_out is None:
                    sps_out = os.path.join(dst_folder, 'SPs')
                    os.makedirs(sps_out, exist_ok=True)
                dst = os.path.join(sps_out, out_name)
                vpy_path = str(row.get('vpy_path') or '').strip()
                bs.encode_task(
                    dst,
                    sps_out,
                    -1,
                    vpy_path,
                    self.vspipe_mode,
                    self.x265_mode,
                    self.x265_params,
                    self.sub_pack_mode,
                    source_file=src
                )
                done += 1

            try:
                progress_cb(int(done / total * 1000), '复制非MKV文件')
                self._copy_non_mkv_from_remux_folder(self.remux_folder, dst_folder)
            except Exception:
                pass

            progress_cb(1000, '完成')
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
            
                # Select subtitle preload strategy by platform.
                if self.sub_files:
                    progress_cb(text='加载字幕')
                    if sys.platform == 'win32':
                        # Windows: prefer multiprocessing.
                        try:
                            bs._preload_subtitles_multiprocess(self.sub_files, self.cancel_event)
                        except Exception as e:
                            print(f'{translate_text("Multiprocess load failed, switching to single process: ")}{str(e)}')
                            # Fallback to single-process loading.
                            for p in self.sub_files:
                                if self.cancel_event.is_set():
                                    raise _Cancelled()
                                try:
                                    bs._subtitle_cache[p] = Subtitle(p)
                                except Exception as e2:
                                    print(f'{translate_text("Failed to load subtitle file ｢")}{p}{translate_text("｣: ")}{str(e2)}')
                    else:
                        # Linux: try multiprocessing, then fallback to single process on failure.
                        try:
                            bs._preload_subtitles_multiprocess(self.sub_files, self.cancel_event)
                        except Exception as e:
                            print(f'{translate_text("Multiprocess load failed, switching to single process: ")}{str(e)}')
                            # Fallback to single-process loading.
                            for p in self.sub_files:
                                if self.cancel_event.is_set():
                                    raise _Cancelled()
                                try:
                                    bs._subtitle_cache[p] = Subtitle(p)
                                except Exception as e2:
                                    print(f'{translate_text("Failed to load subtitle file ｢")}{p}{translate_text("｣: ")}{str(e2)}')
                
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
            
            # Choose subtitle parsing strategy by platform.
            if sys.platform == 'win32':
                # Windows: use multiprocessing.
                subtitle_cache = self._parse_subtitles_multiprocess(files)
            else:
                # Linux: try multiprocessing, then fallback to single process on failure.
                try:
                    subtitle_cache = self._parse_subtitles_multiprocess(files)
                except Exception as e:
                    print(f'{translate_text("Multiprocessing parse failed, switching to single-process mode: ")}{str(e)}')
                    subtitle_cache = self._parse_subtitles_single(files)
            
            if not subtitle_cache:
                print(translate_text('Failed to load all subtitle files'))
                self.result.emit({'seq': self.seq, 'mode': self.mode, 'rows': [], 'configuration': {}})
                return
            
            print(f'{translate_text("Loaded successfully ")}{len(subtitle_cache)}{translate_text(" subtitle files")}')
            
            successful_files = [p for p in files if p in subtitle_cache]

            try:
                rows = [(p, get_time_str(subtitle_cache[p].max_end_time())) for p in successful_files]
            except Exception as e:
                print(f'{translate_text("Failed to get subtitle duration: ")}{str(e)}')
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
                    print(f'{translate_text("Failed to generate configuration: ")}{str(e)}')
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
        """Try multiprocessing subtitle parsing and fall back to single process on failure."""
        subtitle_cache: dict[str, Subtitle] = {}
        try:
            return self._parse_subtitles_multiprocess(files)
        except Exception as e:
            print(f'{translate_text("Multiprocessing parse failed, switching to single-process mode: ")}{str(e)}')
            return self._parse_subtitles_single(files)
    
    def _parse_subtitles_single(self, files: list[str]) -> dict[str, Subtitle]:
        """Parse subtitles in single-process mode."""
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
                print(f'{translate_text("Subtitle file loaded ｢")}{p}{translate_text("｣")}')
            except Exception as e:
                print(f'{translate_text("Failed to load subtitle file ｢")}{p}{translate_text("｣: ")}{type(e).__name__}: {str(e)}')
                import traceback
                traceback.print_exc()
            self.label.emit(f'解析字幕 {i + 1}/{total}（已加载 {loaded_count}）')
            self.progress.emit(int((i + 1) / total * 700))
        return subtitle_cache
    
    def _parse_subtitles_multiprocess(self, files: list[str]) -> dict[str, Subtitle]:
        """Parse subtitles in multiprocessing mode."""
        if len(files) == 1:
            # For a single file, use single-process directly.
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
                            print(f'{translate_text("Failed to load subtitle file ｢")}{p}{translate_text("｣: ")}{str(e)}')
                        else:
                            print(f'{translate_text("Failed to load subtitle file: ")}{str(e)}')
                    done += 1
                    self.label.emit(f'解析字幕 {done}/{total}')
                    self.progress.emit(int(done / total * 700))
        except Exception as e:
            # Propagate exception so the caller can handle fallback.
            raise Exception(f'Multiprocessing parse failed: {str(e)}')
        return subtitle_cache


class SpTableScanWorker(QObject):
    result = pyqtSignal(int, bool, str, object)
    finished = pyqtSignal()
    canceled = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, rows: list[dict[str, object]], cancel_event: threading.Event):
        super().__init__()
        self._rows = rows
        self._cancel_event = cancel_event

    def run(self):
        try:
            for r in self._rows:
                if self._cancel_event.is_set():
                    self.canceled.emit()
                    return
                row = int(r.get('row') or 0)
                m2ts_paths: list[str] = list(r.get('m2ts_paths') or [])
                mpls_path = str(r.get('mpls_path') or '').strip()
                sp_key = str(r.get('sp_key') or '').strip()
                force_disabled = bool(r.get('force_disabled') or False)
                select_all = bool(r.get('select_all') or False)
                disabled = False
                special = ''
                select_override = None
                tracks_payload: dict[str, list[str]] = {}

                if force_disabled:
                    disabled = True
                elif not m2ts_paths:
                    disabled = True
                else:
                    first = m2ts_paths[0]
                    if (not first) or (not os.path.exists(first)):
                        disabled = True
                    else:
                        try:
                            if not BluraySubtitle._ffprobe_streams(first):
                                disabled = True
                        except Exception:
                            disabled = True

                if not disabled:
                    try:
                        if mpls_path and os.path.exists(mpls_path) and m2ts_paths:
                            try:
                                ch = Chapter(mpls_path)
                                ch.get_pid_to_language()
                                pid_to_lang = ch.pid_to_lang
                            except Exception:
                                pid_to_lang = {}
                            try:
                                streams = BluraySubtitle._ffprobe_streams(m2ts_paths[0])
                            except Exception:
                                streams = []
                            try:
                                if select_all:
                                    a = [str(x.get('index', '')).strip() for x in streams if str(x.get('codec_type') or '') == 'audio' and str(x.get('index', '')).strip() != '']
                                    s = [str(x.get('index', '')).strip() for x in streams if str(x.get('codec_type') or '') == 'subtitle' and str(x.get('index', '')).strip() != '']
                                else:
                                    a, s = BluraySubtitle._default_track_selection_from_streams(streams, pid_to_lang)
                                tracks_payload = {'audio': a, 'subtitle': s}
                            except Exception:
                                tracks_payload = {}
                        elif m2ts_paths:
                            try:
                                streams = BluraySubtitle._ffprobe_streams(m2ts_paths[0])
                            except Exception:
                                streams = []
                            try:
                                if select_all:
                                    a = [str(x.get('index', '')).strip() for x in streams if str(x.get('codec_type') or '') == 'audio' and str(x.get('index', '')).strip() != '']
                                    s = [str(x.get('index', '')).strip() for x in streams if str(x.get('codec_type') or '') == 'subtitle' and str(x.get('index', '')).strip() != '']
                                else:
                                    a, s = BluraySubtitle._default_track_selection_from_streams(streams, {})
                                tracks_payload = {'audio': a, 'subtitle': s}
                            except Exception:
                                tracks_payload = {}
                        sizes_ok = True
                        for p in m2ts_paths:
                            if (not p) or (not os.path.exists(p)):
                                sizes_ok = False
                                break
                            if os.path.getsize(p) > 10 * 1024 * 1024:
                                sizes_ok = False
                                break
                        if sizes_ok:
                            frame_counts: list[int] = []
                            any_video = False
                            for p in m2ts_paths:
                                if BluraySubtitle._is_audio_only_media(p):
                                    frame_counts = []
                                    any_video = False
                                    break
                                c = BluraySubtitle._ffprobe_video_frame_count_static(p)
                                if c == -2:
                                    frame_counts = []
                                    any_video = False
                                    break
                                if c < 0:
                                    disabled = True
                                    break
                                any_video = True
                                frame_counts.append(c)
                            if (not disabled) and any_video and frame_counts:
                                if len(m2ts_paths) == 1 and frame_counts[0] <= 1:
                                    special = 'single_frame'
                                    select_override = True
                                elif len(m2ts_paths) > 1 and all(x <= 1 for x in frame_counts):
                                    special = 'multi_frame'
                                    select_override = True
                    except Exception:
                        pass

                self.result.emit(row, bool(disabled), str(special or ''), {
                    'select_override': select_override,
                    'sp_key': sp_key,
                    'tracks': tracks_payload,
                    'mpls_path': mpls_path,
                })

            self.finished.emit()
        except Exception:
            self.failed.emit(traceback.format_exc())

class BluraySubtitleGUI(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName('mainWindow')
        self.altered = False
        self._sp_index_by_bdmv: dict[int, int] = {}
        self._chapter_checkbox_states: dict[str, list[bool]] = {}  # Save chapter checkbox states
        self._last_config_inputs: dict[str, object] = {}
        self.init_ui()

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

    def _refresh_theme_combo(self):
        if not hasattr(self, 'theme_label') or not hasattr(self, 'theme_combo'):
            return
        current_mode = self.theme_combo.currentData() or getattr(self, '_theme_mode', 'light')
        self.theme_label.setText(self.t('模式'))
        self.theme_combo.blockSignals(True)
        try:
            self.theme_combo.clear()
            self.theme_combo.addItem(self.t('浅色'), 'light')
            self.theme_combo.addItem(self.t('深色'), 'dark')
            self.theme_combo.addItem(self.t('彩色'), 'colorful')
            if str(current_mode) == 'dark':
                idx = 1
            elif str(current_mode) == 'colorful':
                idx = 2
            else:
                idx = 0
            self.theme_combo.setCurrentIndex(idx)
        finally:
            self.theme_combo.blockSignals(False)
        self._refresh_opacity_controls()

    def _refresh_opacity_controls(self):
        label = getattr(self, 'opacity_label', None)
        slider = getattr(self, 'opacity_slider', None)
        visible = getattr(self, '_theme_mode', 'light') == 'colorful'
        if isinstance(label, QLabel):
            label.setText(self.t('透明度'))
            label.setVisible(visible)
        if isinstance(slider, QSlider):
            slider.setVisible(visible)

    def _apply_theme(self, mode: str):
        m = str(mode or 'light')
        if m == 'dark':
            self._theme_mode = 'dark'
        elif m == 'colorful':
            self._theme_mode = 'colorful'
        else:
            self._theme_mode = 'light'
        app = QApplication.instance()
        if not app:
            return
        if self._theme_mode == 'light':
            try:
                self.setWindowOpacity(1.0)
            except Exception:
                pass
            app.setStyleSheet(
                "QTabBar::tab:selected{background:#e6e6e6;color:#000000;border:1px solid #c8c8c8;}"
            )
            self._refresh_function_tabbar_theme()
            self._refresh_opacity_controls()
            return
        if self._theme_mode == 'colorful':
            opacity = float(getattr(self, '_colorful_opacity', 0.94) or 0.94)
            opacity = min(1.0, max(0.6, opacity))
            self._colorful_opacity = opacity
            try:
                self.setWindowOpacity(opacity)
            except Exception:
                pass
            app.setStyleSheet(
                "QWidget{background:transparent;color:#1f2330;}"
                "QWidget#mainWindow{background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #fff3c4,stop:0.55 #fffdf3,stop:1 #eef6ff);}"
                "QDialog{background:rgba(255,255,255,235);border:1px solid rgba(214,217,230,220);}"
                "QWidget:disabled{color:#8b92a8;}"
                "QLineEdit,QPlainTextEdit,QTextEdit{background:rgba(255,255,255,220);color:#1f2330;border:1px solid rgba(214,217,230,220);border-radius:4px;}"
                "QLineEdit:disabled,QPlainTextEdit:disabled,QTextEdit:disabled{background:#f3f4f8;color:#8b92a8;border:1px solid #dde0ea;}"
                "QComboBox{background:rgba(255,255,255,220);color:#1f2330;border:1px solid rgba(214,217,230,220);border-radius:4px;padding:2px 6px;}"
                "QComboBox:disabled{background:#f3f4f8;color:#8b92a8;border:1px solid #dde0ea;}"
                "QComboBox QAbstractItemView{background:#ffffff;color:#1f2330;selection-background-color:#7c3aed;selection-color:#ffffff;}"
                "QGroupBox{background:rgba(255,255,255,190);border:1px solid rgba(214,217,230,220);border-radius:8px;margin-top:10px;}"
                "QGroupBox::title{subcontrol-origin:margin;left:8px;padding:0 6px;color:#7c3aed;}"
                "QRadioButton{color:#1f2330;}"
                "QRadioButton:disabled{color:#8b92a8;}"
                "QRadioButton::indicator{width:14px;height:14px;border-radius:7px;border:2px solid #7c3aed;background:rgba(255,255,255,220);}"
                "QRadioButton::indicator:checked{background:#7c3aed;border:2px solid #6d28d9;}"
                "QRadioButton::indicator:checked:hover{background:#6d28d9;}"
                "QRadioButton::indicator:unchecked:hover{border:2px solid #6d28d9;}"
                "QRadioButton::indicator:disabled{border:2px solid #c7cbe0;background:rgba(243,244,248,220);}"
                "QRadioButton::indicator:checked:disabled{border:2px solid #c7cbe0;background:rgba(199,203,224,220);}"
                "QCheckBox{color:#1f2330;}"
                "QCheckBox:disabled{color:#8b92a8;}"
                "QCheckBox::indicator{width:14px;height:14px;border-radius:3px;border:1px solid #7c3aed;background:#ffffff;}"
                "QCheckBox::indicator:checked{border:1px solid #6d28d9;background:#7c3aed;}"
                "QCheckBox::indicator:checked:hover{background:#6d28d9;}"
                "QCheckBox::indicator:disabled{border:1px solid #b8bfd6;background:#e5e7ef;}"
                "QSlider{background:transparent;}"
                "QSlider::groove:horizontal{height:6px;background:rgba(214,217,230,180);border-radius:3px;margin:0px;}"
                "QSlider::sub-page:horizontal{background:#7c3aed;border-radius:3px;}"
                "QSlider::add-page:horizontal{background:rgba(214,217,230,120);border-radius:3px;}"
                "QSlider::handle:horizontal{background:#ffffff;border:1px solid rgba(124,58,237,180);width:14px;margin:-6px 0px;border-radius:7px;}"
                "QSlider::handle:horizontal:hover{border:1px solid #6d28d9;}"
                "QTableWidget{gridline-color:#e2e4f0;background:rgba(255,255,255,210);alternate-background-color:rgba(246,244,255,210);selection-background-color:#34d399;selection-color:#0b1220;border-radius:6px;}"
                "QTableView::indicator{width:14px;height:14px;border-radius:3px;}"
                "QTableView::indicator:unchecked{border:1px solid #7c3aed;background:#ffffff;}"
                "QTableView::indicator:checked{border:1px solid #6d28d9;background:#7c3aed;}"
                "QTableView::indicator:disabled{border:1px solid #b8bfd6;background:#e5e7ef;}"
                "QTableWidget#table1{background:rgba(234,243,255,220);alternate-background-color:rgba(214,233,255,220);}"
                "QTableWidget#table2{background:rgba(240,255,246,220);alternate-background-color:rgba(220,250,232,220);}"
                "QTableWidget#table3{background:rgba(255,248,236,220);alternate-background-color:rgba(255,235,213,220);}"
                "QHeaderView::section{background:rgba(240,243,255,235);color:#1f2330;border:1px solid rgba(214,217,230,220);padding:4px;}"
                "QPushButton,QToolButton{background:rgba(255,255,255,220);color:#1f2330;border:1px solid rgba(214,217,230,220);border-radius:8px;padding:4px 10px;}"
                "QPushButton:hover,QToolButton:hover{border:1px solid #7c3aed;}"
                "QPushButton:pressed,QToolButton:pressed{background:#f2e9ff;}"
                "QToolButton:checked{background:#ffedd5;border:1px solid #fb923c;color:#7c2d12;}"
                "QToolButton:checked:hover{background:#fed7aa;}"
                "QPushButton:disabled,QToolButton:disabled{background:#f3f4f8;color:#8b92a8;border:1px solid #dde0ea;}"
                "QScrollBar:horizontal{background:#fbfbff;height:12px;margin:0px 14px 0px 14px;border:1px solid #d6d9e6;border-radius:5px;}"
                "QScrollBar::handle:horizontal{background:#a78bfa;min-width:24px;border-radius:4px;}"
                "QScrollBar::handle:horizontal:hover{background:#7c3aed;}"
                "QScrollBar::add-line:horizontal{background:#f0f3ff;width:14px;subcontrol-position:right;subcontrol-origin:margin;border:1px solid #d6d9e6;}"
                "QScrollBar::sub-line:horizontal{background:#f0f3ff;width:14px;subcontrol-position:left;subcontrol-origin:margin;border:1px solid #d6d9e6;}"
                "QScrollBar::add-page:horizontal,QScrollBar::sub-page:horizontal{background:none;}"
                "QScrollBar:vertical{background:#fbfbff;width:12px;margin:14px 0px 14px 0px;border:1px solid #d6d9e6;border-radius:5px;}"
                "QScrollBar::handle:vertical{background:#a78bfa;min-height:24px;border-radius:4px;}"
                "QScrollBar::handle:vertical:hover{background:#7c3aed;}"
                "QScrollBar::add-line:vertical{background:#f0f3ff;height:14px;subcontrol-position:bottom;subcontrol-origin:margin;border:1px solid #d6d9e6;}"
                "QScrollBar::sub-line:vertical{background:#f0f3ff;height:14px;subcontrol-position:top;subcontrol-origin:margin;border:1px solid #d6d9e6;}"
                "QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical{background:none;}"
                "QTableWidget#table1 QScrollBar::handle:horizontal{background:#60a5fa;}"
                "QTableWidget#table1 QScrollBar::handle:horizontal:hover{background:#2563eb;}"
                "QTableWidget#table1 QScrollBar::handle:vertical{background:#60a5fa;}"
                "QTableWidget#table1 QScrollBar::handle:vertical:hover{background:#2563eb;}"
                "QTableWidget#table2 QScrollBar::handle:horizontal{background:#34d399;}"
                "QTableWidget#table2 QScrollBar::handle:horizontal:hover{background:#059669;}"
                "QTableWidget#table2 QScrollBar::handle:vertical{background:#34d399;}"
                "QTableWidget#table2 QScrollBar::handle:vertical:hover{background:#059669;}"
                "QTableWidget#table3 QScrollBar::handle:horizontal{background:#fb923c;}"
                "QTableWidget#table3 QScrollBar::handle:horizontal:hover{background:#ea580c;}"
                "QTableWidget#table3 QScrollBar::handle:vertical{background:#fb923c;}"
                "QTableWidget#table3 QScrollBar::handle:vertical:hover{background:#ea580c;}"
                "QMenu{background:#ffffff;color:#1f2330;border:1px solid #d6d9e6;}"
                "QMenu::item:selected{background:#7c3aed;color:#ffffff;}"
                "QProgressBar{background:#ffffff;border:1px solid #d6d9e6;border-radius:6px;text-align:center;color:#1f2330;}"
                "QProgressBar::chunk{background:#34d399;border-radius:6px;}"
                "QTabBar::tab{background:#f0f3ff;color:#1f2330;border:1px solid #d6d9e6;border-bottom:none;padding:6px 10px;border-top-left-radius:6px;border-top-right-radius:6px;}"
                "QTabBar::tab:selected{background:#7c3aed;color:#ffffff;border:1px solid #6d28d9;border-bottom:none;}"
                "QToolTip{background:#1f2330;color:#ffffff;border:1px solid #7c3aed;}"
            )
            self._refresh_function_tabbar_theme()
            self._refresh_opacity_controls()
            return
        try:
            self.setWindowOpacity(1.0)
        except Exception:
            pass
        app.setStyleSheet(
            "QWidget{background:#1f1f1f;color:#e6e6e6;}"
            "QLineEdit,QPlainTextEdit,QTextEdit{background:#2a2a2a;color:#e6e6e6;border:1px solid #3a3a3a;}"
            "QComboBox{background:#2a2a2a;color:#e6e6e6;border:1px solid #3a3a3a;padding:2px 6px;}"
            "QComboBox QAbstractItemView{background:#2a2a2a;color:#e6e6e6;selection-background-color:#3a5fcd;}"
            "QRadioButton{color:#e6e6e6;}"
            "QRadioButton::indicator{width:14px;height:14px;border-radius:7px;border:2px solid #5b7fff;background:#2a2a2a;}"
            "QRadioButton::indicator:checked{background:#3a5fcd;border:2px solid #5b7fff;}"
            "QRadioButton::indicator:checked:hover{background:#4a6fe0;}"
            "QRadioButton::indicator:unchecked:hover{border:2px solid #7a93ff;}"
            "QRadioButton:disabled{color:#9aa0b3;}"
            "QRadioButton::indicator:disabled{border:2px solid #555a6b;background:#252525;}"
            "QRadioButton::indicator:checked:disabled{border:2px solid #555a6b;background:#555a6b;}"
            "QPushButton,QToolButton{background:#2a2a2a;color:#e6e6e6;border:1px solid #3a3a3a;padding:4px 8px;}"
            "QPushButton:hover,QToolButton:hover{background:#333333;}"
            "QPushButton:pressed,QToolButton:pressed{background:#3a3a3a;}"
            "QToolButton:checked{background:#3a5fcd;border:1px solid #5b7fff;color:#ffffff;}"
            "QToolButton:checked:hover{background:#4a6fe0;}"
            "QGroupBox{border:1px solid #3a3a3a;margin-top:10px;}"
            "QGroupBox::title{subcontrol-origin:margin;left:8px;padding:0 4px;}"
            "QTableWidget{gridline-color:#3a3a3a;background:#202020;alternate-background-color:#242424;}"
            "QHeaderView::section{background:#2a2a2a;color:#e6e6e6;border:1px solid #3a3a3a;padding:4px;}"
            "QScrollBar:horizontal{background:#1f1f1f;height:12px;margin:0px 14px 0px 14px;border:1px solid #2b2b2b;}"
            "QScrollBar::handle:horizontal{background:#555555;min-width:24px;border-radius:4px;}"
            "QScrollBar::handle:horizontal:hover{background:#666666;}"
            "QScrollBar::add-line:horizontal{background:#2a2a2a;width:14px;subcontrol-position:right;subcontrol-origin:margin;border:1px solid #3a3a3a;}"
            "QScrollBar::sub-line:horizontal{background:#2a2a2a;width:14px;subcontrol-position:left;subcontrol-origin:margin;border:1px solid #3a3a3a;}"
            "QScrollBar::add-page:horizontal,QScrollBar::sub-page:horizontal{background:none;}"
            "QScrollBar:vertical{background:#1f1f1f;width:12px;margin:14px 0px 14px 0px;border:1px solid #2b2b2b;}"
            "QScrollBar::handle:vertical{background:#555555;min-height:24px;border-radius:4px;}"
            "QScrollBar::handle:vertical:hover{background:#666666;}"
            "QScrollBar::add-line:vertical{background:#2a2a2a;height:14px;subcontrol-position:bottom;subcontrol-origin:margin;border:1px solid #3a3a3a;}"
            "QScrollBar::sub-line:vertical{background:#2a2a2a;height:14px;subcontrol-position:top;subcontrol-origin:margin;border:1px solid #3a3a3a;}"
            "QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical{background:none;}"
            "QMenu{background:#2a2a2a;color:#e6e6e6;border:1px solid #3a3a3a;}"
            "QMenu::item:selected{background:#3a5fcd;}"
            "QProgressBar{background:#2a2a2a;border:1px solid #3a3a3a;text-align:center;color:#e6e6e6;}"
            "QProgressBar::chunk{background:#3a5fcd;}"
            "QToolTip{background:#2a2a2a;color:#e6e6e6;border:1px solid #3a3a3a;}"
        )
        self._refresh_function_tabbar_theme()
        self._refresh_opacity_controls()

    def _on_opacity_changed(self, value: int):
        try:
            v = int(value)
        except Exception:
            v = 96
        opacity = min(100, max(60, v)) / 100.0
        self._colorful_opacity = opacity
        if getattr(self, '_theme_mode', 'light') == 'colorful':
            try:
                self.setWindowOpacity(opacity)
            except Exception:
                pass

    def _refresh_function_tabbar_theme(self):
        tabbar = getattr(self, 'function_tabbar', None)
        if not isinstance(tabbar, QTabBar):
            return
        if getattr(self, '_theme_mode', 'light') != 'colorful':
            tabbar.setStyleSheet('')
            return
        fid = self.get_selected_function_id() if hasattr(self, 'get_selected_function_id') else 1
        accent = {
            1: ('#0ea5e9', '#0284c7'),
            2: ('#14b8a6', '#0f766e'),
            3: ('#f59e0b', '#b45309'),
            4: ('#ef4444', '#b91c1c'),
        }.get(int(fid), ('#7c3aed', '#6d28d9'))
        tabbar.setStyleSheet(
            "QTabBar::tab{background:#f0f3ff;color:#1f2330;border:1px solid #d6d9e6;border-bottom:none;padding:6px 10px;border-top-left-radius:6px;border-top-right-radius:6px;}"
            f"QTabBar::tab:selected{{background:{accent[0]};color:#ffffff;border:1px solid {accent[1]};border-bottom:none;font-weight:600;}}"
        )

    def _on_theme_changed(self):
        mode = self.theme_combo.currentData() if hasattr(self, 'theme_combo') else 'light'
        self._apply_theme(str(mode))

    def _translate_widget_texts(self):
        for widget in self.findChildren(QWidget):
            if widget is getattr(self, 'language_combo', None):
                continue
            if widget is getattr(self, 'theme_combo', None):
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
            self._refresh_theme_combo()
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
            en = {
                'edit_tracks': 'tracks',
                'extract': 'extract',
                'edit_chapters': 'chapters',
                'edit_attachments': 'attachments',
                'remux_cmd': 'remux cmd',
            }
            return [en.get(k, k) for k in keys]
        zh = {
            'path': '路径',
            'size': '大小',
            'info': '信息',
            'remux_cmd': '混流命令',
            'select': '选择',
            'sub_duration': '字幕时长',
            'warning': '提示',
            'tracks': '轨道',
            'bdmv_index': '原盘序号',
            'chapter_index': '章节序号',
            'start_at_chapter': '起始章节',
            'end_at_chapter': '结束章节',
            'offset': '偏移',
            'duration': '时长',
            'sub_path': '字幕路径',
            'ep_duration': '单集时长',
            'm2ts_file': 'm2ts 文件',
            'language': '语言',
            'lang': '语言',
            'track_number': '轨道号',
            'track_uid': 'UID',
            'track_type': '类型',
            'codec_id': 'Codec ID',
            'channels': '声道',
            'bit_depth': '位深',
            'sampling_frequency': '采样率',
            'pixel_width': '宽度',
            'pixel_height': '高度',
            'default_duration': '默认时长',
            'extract': '提取',
            'edit_chapters': '编辑章节',
            'edit_attachments': '编辑附件',
            'filename': '文件名',
            'mime_type': 'MIME 类型',
            'uid': 'UID',
            'file_size': '文件大小',
            'id': 'ID',
            'output_name': '输出文件名',
            'vpy_path': 'vpy 路径',
            'edit_vpy': '编辑 vpy',
            'preview_script': '预览',
            'edit_tracks': '编辑轨道',
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
                    labels = ENCODE_REMUX_LABELS if getattr(self, '_encode_input_mode', 'bdmv') == 'remux' else ENCODE_LABELS
                    self._set_table_headers(self.table2, labels)
                self._resize_table_columns_for_language(self.table2)
                self._scroll_table_h_to_right(self.table2)
        except Exception:
            pass

        try:
            if hasattr(self, 'table3') and self.table3:
                labels = ENCODE_REMUX_SP_LABELS if getattr(self, '_encode_input_mode', 'bdmv') == 'remux' else ENCODE_SP_LABELS
                self._set_table_headers(self.table3, labels)
                self._resize_table_columns_for_language(self.table3)
                self._scroll_table_h_to_right(self.table3)
        except Exception:
            pass

        try:
            if hasattr(self, 'table1') and self.table1:
                for r in range(self.table1.rowCount()):
                    info_table = self.table1.cellWidget(r, 2)
                    if isinstance(info_table, QTableWidget):
                        info_keys = ['mpls_file', 'duration', 'chapters', 'main', 'play']
                        try:
                            if info_table.columnCount() > len(info_keys):
                                info_keys.append('tracks')
                        except Exception:
                            pass
                        self._set_table_headers(info_table, info_keys)
                        self._resize_table_columns_for_language(info_table)
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
                function_id = self.get_selected_function_id() if hasattr(self, 'get_selected_function_id') else 0
                if function_id in (3, 4):
                    self.table1.setColumnWidth(2, 620 if lang == 'zh' else 560)
                else:
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
            'a = r""  # optional, auto-generated by app\n'
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
            '# sub_file = ""  # optional, auto-generated by app\n'
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

        target_1 = 'sub_file = \"\"  # optional, auto-generated by app'
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
        try:
            if os.path.exists('info.json'):
                force_remove_file('info.json')
        except Exception:
            pass
        return super().closeEvent(event)

    def _cleanup_info_json_if_needed(self):
        try:
            if os.path.exists('info.json'):
                force_remove_file('info.json')
        except Exception:
            pass

    def _set_compact_table(self, table: QTableWidget, row_height: int = 22, header_height: int = 22):
        table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        table.verticalHeader().setDefaultSectionSize(row_height)
        table.verticalHeader().setMinimumSectionSize(row_height)
        table.horizontalHeader().setFixedHeight(header_height)

    def _scroll_table_h_to_right(self, table: QTableWidget):
        token = int(getattr(table, '_auto_scroll_token', 0) or 0) + 1
        table._auto_scroll_token = token

        def scroll(expected_token: int = token):
            if int(getattr(table, '_auto_scroll_token', 0) or 0) != int(expected_token):
                return
            bar = table.horizontalScrollBar()
            if bar.isSliderDown():
                return
            bar.setValue(bar.maximum())

        QTimer.singleShot(0, scroll)
        QTimer.singleShot(80, scroll)
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

    def create_language_combo(self, initial: str = 'chi', parent: Optional[QWidget] = None) -> QComboBox:
        combo = QComboBox(parent)
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
        if function_id == 4 and getattr(self, '_encode_input_mode', 'bdmv') == 'remux':
            labels = ENCODE_REMUX_LABELS
        else:
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
        if function_id == 4 and getattr(self, '_encode_input_mode', 'bdmv') == 'remux':
            labels = ENCODE_REMUX_LABELS
        else:
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
        labels = ENCODE_REMUX_LABELS if getattr(self, '_encode_input_mode', 'bdmv') == 'remux' else ENCODE_LABELS
        vpy_col = labels.index('vpy_path')
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
        root = self._get_disc_root_for_bdmv_index(bdmv_index)
        if not root:
            return ''
        return os.path.normpath(os.path.join(root, 'BDMV', 'STREAM'))

    def _get_playlist_dir_for_bdmv_index(self, bdmv_index: int) -> str:
        root = self._get_disc_root_for_bdmv_index(bdmv_index)
        if not root:
            return ''
        return os.path.normpath(os.path.join(root, 'BDMV', 'PLAYLIST'))

    def _get_disc_root_for_bdmv_index(self, bdmv_index: int) -> str:
        try:
            idx = int(bdmv_index)
        except Exception:
            idx = -1
        if not hasattr(self, 'table1') or not self.table1:
            return ''
        row_count = self.table1.rowCount()
        if row_count <= 0:
            return ''
        candidates: list[int] = []
        if idx > 0:
            candidates.extend([idx - 1, idx])
        else:
            candidates.append(0)
        candidates.extend([0, row_count - 1])
        seen: set[int] = set()
        for r in candidates:
            if r in seen:
                continue
            seen.add(r)
            if r < 0 or r >= row_count:
                continue
            try:
                root_item = self.table1.item(r, 0)
                root = root_item.text().strip() if root_item else ''
            except Exception:
                root = ''
            if not root:
                continue
            bdmv_dir = os.path.join(root, 'BDMV')
            playlist_dir = os.path.join(bdmv_dir, 'PLAYLIST')
            stream_dir = os.path.join(bdmv_dir, 'STREAM')
            if os.path.isdir(playlist_dir) and os.path.isdir(stream_dir):
                return os.path.normpath(root)
            if os.path.isdir(bdmv_dir):
                return os.path.normpath(root)
        return ''

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

    def _play_mpls_path(self, mpls_path: str):
        btn = QToolButton()
        btn.setText(self.t('play'))
        btn.setProperty('action', 'play')
        self.on_button_play(mpls_path, btn)

    def _play_m2ts_path(self, m2ts_path: str):
        if not m2ts_path or not os.path.exists(m2ts_path):
            QMessageBox.information(self, " ", f"未找到 m2ts 文件：\n{m2ts_path}")
            return
        if sys.platform == 'win32':
            mp4_exe_path = get_mpv_safe_path(".mp4")
            if mp4_exe_path and str(mp4_exe_path).lower().endswith('mpv.exe'):
                subprocess.Popen(f'"{mp4_exe_path}" "{m2ts_path}"', shell=True).wait()
                return
        self.open_file_path(m2ts_path)

    def on_play_table2_disc_row(self, row_index: int, bdmv_col: int, m2ts_col: int):
        try:
            bdmv_item = self.table2.item(row_index, bdmv_col)
            try:
                bdmv_index = int(bdmv_item.text().strip()) if bdmv_item and bdmv_item.text().strip() else 0
            except Exception:
                bdmv_index = 0
            m2ts_item = self.table2.item(row_index, m2ts_col)
            m2ts_files = self._split_m2ts_files(m2ts_item.text() if m2ts_item else '')
            video_path = self._select_video_path(bdmv_index, m2ts_files)
            if video_path:
                self._play_m2ts_path(video_path)
        except Exception:
            self._show_error_dialog(traceback.format_exc())

    def on_play_sp_table_row(self, row_index: int, bdmv_col: int, mpls_col: int, m2ts_col: int):
        try:
            bdmv_item = self.table3.item(row_index, bdmv_col)
            try:
                bdmv_index = int(bdmv_item.text().strip()) if bdmv_item and bdmv_item.text().strip() else 0
            except Exception:
                bdmv_index = 0
            mpls_item = self.table3.item(row_index, mpls_col)
            mpls_file = (mpls_item.text().strip() if mpls_item and mpls_item.text() else '')
            if mpls_file:
                playlist_dir = self._get_playlist_dir_for_bdmv_index(bdmv_index)
                if not playlist_dir:
                    QMessageBox.information(self, " ", f"未找到对应的蓝光目录（bdmv_index={bdmv_index}），无法定位 mpls 文件")
                    return
                mpls_path = os.path.normpath(os.path.join(playlist_dir, mpls_file))
                if os.path.exists(mpls_path):
                    self._play_mpls_path(mpls_path)
                    return
                QMessageBox.information(self, " ", f"未找到 mpls 文件：\n{mpls_path}")
                return
            m2ts_item = self.table3.item(row_index, m2ts_col)
            m2ts_files = self._split_m2ts_files(m2ts_item.text() if m2ts_item else '')
            video_path = self._select_video_path(bdmv_index, m2ts_files)
            if video_path:
                self._play_m2ts_path(video_path)
        except Exception:
            self._show_error_dialog(traceback.format_exc())

    def _on_play_sp_table_row_clicked(self):
        try:
            sender = self.sender()
            if sender is None or not hasattr(self, 'table3') or not self.table3:
                return
            row_index = self.table3.indexAt(sender.pos()).row()
            if row_index < 0:
                return
            bdmv_col = ENCODE_SP_LABELS.index('bdmv_index')
            mpls_col = ENCODE_SP_LABELS.index('mpls_file')
            m2ts_col = ENCODE_SP_LABELS.index('m2ts_file')
            self.on_play_sp_table_row(row_index, bdmv_col, mpls_col, m2ts_col)
        except Exception:
            self._show_error_dialog(traceback.format_exc())

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

    def _update_vpy_paths_in_file(self, vpy_path: str, video_path: str, subtitle_path: str) -> bool:
        """Update a=/sub_file=/TextSub toggle in target vpy file for preview context."""
        vpy_path = os.path.normpath(str(vpy_path or '').strip())
        if not vpy_path or not os.path.exists(vpy_path):
            raise FileNotFoundError(vpy_path)

        with open(vpy_path, 'r', encoding='utf-8') as fp:
            lines = fp.readlines()

        def norm(s: str) -> str:
            return s.rstrip('\r\n')

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
                continue

        if changed:
            with open(vpy_path, 'w', encoding='utf-8') as fp:
                fp.writelines(lines)
        return changed

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

    def _create_temp_edit_vpy_from_default(self, video_path: str, subtitle_path: str) -> str:
        """Create a temporary editable copy of default vpy with row-specific a/sub_file values."""
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

                m_a = re.match(r'^(\s*)(#\s*)?(a\s*=\s*)r?[\'"].*?[\'"](\s*(#.*)?)$', raw)
                if m_a:
                    indent = m_a.group(1)
                    expr = m_a.group(3)
                    suffix = m_a.group(4) or ''
                    out.append(f'{indent}{expr}{self._vpy_raw_string(video_path)}{suffix}\n')
                    continue

                m_s = re.match(r'^(\s*)(#\s*)?(sub_file\s*=\s*)r?[\'"].*?[\'"](\s*(#.*)?)$', raw)
                if m_s:
                    indent = m_s.group(1)
                    expr = m_s.group(3)
                    suffix = m_s.group(4) or ''
                    comment = '' if subtitle_path else '# '
                    out.append(f'{indent}{comment}{expr}{self._vpy_raw_string(subtitle_path or "")}{suffix}\n')
                    continue

                out.append(line if line.endswith('\n') else line + '\n')

            fd, temp_vpy = tempfile.mkstemp(prefix='bluraysubtitle_edit_', suffix='.vpy')
            os.close(fd)
            with open(temp_vpy, 'w', encoding='utf-8') as fp:
                fp.writelines(out)
            return temp_vpy
        except Exception:
            traceback.print_exc()
            return ''

    def _merge_temp_edit_back_to_default_vpy(self, temp_vpy: str):
        """Write edited temp script back into default vpy, preserving a=/sub_file= lines in default."""
        default_vpy = self.get_default_vpy_path()
        if not (temp_vpy and os.path.exists(temp_vpy) and os.path.exists(default_vpy)):
            return
        try:
            with open(default_vpy, 'r', encoding='utf-8') as fp:
                default_lines = fp.readlines()
            with open(temp_vpy, 'r', encoding='utf-8') as fp:
                temp_lines = fp.readlines()

            def _find_runtime_line(lines: list[str], key: str) -> Optional[str]:
                pat = re.compile(rf'^(\s*)(#\s*)?({re.escape(key)}\s*=\s*)r?[\'"].*?[\'"](\s*(#.*)?)$')
                for ln in lines:
                    raw = ln.rstrip('\r\n')
                    if pat.match(raw):
                        return ln if ln.endswith('\n') else ln + '\n'
                return None

            keep_a = _find_runtime_line(default_lines, 'a')
            keep_sub = _find_runtime_line(default_lines, 'sub_file')
            pat_a = re.compile(r'^(\s*)(#\s*)?(a\s*=\s*)r?[\'"].*?[\'"](\s*(#.*)?)$')
            pat_sub = re.compile(r'^(\s*)(#\s*)?(sub_file\s*=\s*)r?[\'"].*?[\'"](\s*(#.*)?)$')

            merged: list[str] = []
            for ln in temp_lines:
                raw = ln.rstrip('\r\n')
                if pat_a.match(raw) and keep_a is not None:
                    merged.append(keep_a)
                    continue
                if pat_sub.match(raw) and keep_sub is not None:
                    merged.append(keep_sub)
                    continue
                merged.append(ln if ln.endswith('\n') else ln + '\n')

            with open(default_vpy, 'w', encoding='utf-8') as fp:
                fp.writelines(merged)
        except Exception:
            traceback.print_exc()

    def _normalize_default_vpy_runtime_lines(self):
        """Ensure default vpy keeps empty runtime placeholders for a= and sub_file=."""
        default_vpy = self.get_default_vpy_path()
        if not os.path.exists(default_vpy):
            return
        try:
            with open(default_vpy, 'r', encoding='utf-8') as fp:
                lines = fp.readlines()
            changed = False
            out: list[str] = []
            for ln in lines:
                raw = ln.rstrip('\r\n')
                m_a = re.match(r'^(\s*)(#\s*)?(a\s*=\s*)r?[\'"].*?[\'"](\s*(#.*)?)$', raw)
                if m_a:
                    indent = m_a.group(1)
                    expr = m_a.group(3)
                    suffix = m_a.group(4) or ''
                    out.append(f'{indent}{expr}r""{suffix}\n')
                    changed = True
                    continue
                m_s = re.match(r'^(\s*)(#\s*)?(sub_file\s*=\s*)r?[\'"].*?[\'"](\s*(#.*)?)$', raw)
                if m_s:
                    indent = m_s.group(1)
                    expr = m_s.group(3)
                    suffix = m_s.group(4) or ''
                    out.append(f'{indent}# {expr}""{suffix}\n')
                    changed = True
                    continue
                out.append(ln if ln.endswith('\n') else ln + '\n')
            if changed:
                with open(default_vpy, 'w', encoding='utf-8') as fp:
                    fp.writelines(out)
        except Exception:
            traceback.print_exc()

    def _edit_vpy_with_default_sync(self, video_path: str, subtitle_path: str):
        """Open editable temp script and sync edits back to default vpy (except a=/sub_file=)."""
        temp_vpy = self._create_temp_edit_vpy_from_default(video_path=video_path or '', subtitle_path=subtitle_path or '')
        if not temp_vpy:
            self.open_vpy_in_editor(self.get_default_vpy_path())
            return
        proc = self.open_vpy_in_vsedit(temp_vpy)
        if not proc:
            try:
                os.remove(temp_vpy)
            except Exception:
                pass
            self.open_vpy_in_editor(self.get_default_vpy_path())
            return
        if not hasattr(self, '_vsedit_edit_sessions'):
            self._vsedit_edit_sessions = {}
        self._vsedit_edit_sessions[proc] = temp_vpy

        def sync_and_cleanup(*_):
            try:
                sess_temp = self._vsedit_edit_sessions.pop(proc, '')
            except Exception:
                sess_temp = ''
            if sess_temp:
                self._merge_temp_edit_back_to_default_vpy(sess_temp)
                try:
                    os.remove(sess_temp)
                except Exception:
                    pass
            try:
                proc.deleteLater()
            except Exception:
                pass

        proc.finished.connect(sync_and_cleanup)
        proc.errorOccurred.connect(sync_and_cleanup)

    def _resolve_table2_row_edit_context(self, row_index: int) -> tuple[str, str]:
        """Return (video_path, subtitle_path) for table2 edit-vpy action."""
        if getattr(self, '_encode_input_mode', 'bdmv') == 'remux':
            video_path = self._get_remux_source_path_from_table2_row(row_index)
            subtitle_path = ''
            try:
                should_load_subtitle = bool(getattr(self, 'sub_pack_hard_radio', None) and self.sub_pack_hard_radio.isChecked())
            except Exception:
                should_load_subtitle = False
            try:
                sub_col = ENCODE_REMUX_LABELS.index('sub_path')
                sub_item = self.table2.item(row_index, sub_col)
                subtitle_path = sub_item.text().strip() if should_load_subtitle and sub_item and sub_item.text().strip() else ''
            except Exception:
                subtitle_path = ''
            return video_path, subtitle_path

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
        try:
            should_load_subtitle = bool(getattr(self, 'sub_pack_hard_radio', None) and self.sub_pack_hard_radio.isChecked())
        except Exception:
            should_load_subtitle = False
        subtitle_path = sub_item.text().strip() if should_load_subtitle and sub_item and sub_item.text().strip() else ''
        return video_path, subtitle_path

    def _resolve_table3_row_edit_context(self, row_index: int) -> tuple[str, str]:
        """Return (video_path, subtitle_path) for table3 edit-vpy action."""
        if getattr(self, '_encode_input_mode', 'bdmv') == 'remux':
            return self._get_remux_source_path_from_table3_row(row_index), ''
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
        return self._select_video_path(bdmv_index, m2ts_files), ''

    def _preview_script_for_row(self, vpy_path: str, video_path: str, subtitle_path: str):
        if not video_path:
            QMessageBox.information(self, "提示", "无法确定视频文件路径")
            return

        vpy_path = (vpy_path or '').strip()
        default_vpy = self.get_default_vpy_path()
        if not vpy_path:
            vpy_path = default_vpy

        try:
            try:
                is_default = os.path.normcase(os.path.abspath(os.path.normpath(vpy_path))) == os.path.normcase(os.path.abspath(os.path.normpath(default_vpy)))
            except Exception:
                is_default = False
            if is_default:
                self.ensure_default_vpy_file()
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
                if not hasattr(self, '_vsedit_preview_sessions'):
                    self._vsedit_preview_sessions = {}
                self._vsedit_preview_sessions[proc] = temp_vpy

                def sync_and_cleanup(*_):
                    try:
                        sess_temp = self._vsedit_preview_sessions.pop(proc, '')
                    except Exception:
                        sess_temp = ''
                    if sess_temp:
                        self._merge_temp_edit_back_to_default_vpy(sess_temp)
                        self._normalize_default_vpy_runtime_lines()
                        try:
                            os.remove(sess_temp)
                        except Exception:
                            pass
                    try:
                        proc.deleteLater()
                    except Exception:
                        pass

                proc.finished.connect(sync_and_cleanup)
                proc.errorOccurred.connect(sync_and_cleanup)
            else:
                self._update_vpy_paths_in_file(vpy_path=vpy_path, video_path=video_path, subtitle_path=subtitle_path or '')
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
        path = self.get_vpy_path_from_row(row_index)
        if not path:
            path = self.get_default_vpy_path()
            self.ensure_default_vpy_file()
        self.open_vpy_in_editor(path)

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

        if getattr(self, '_encode_input_mode', 'bdmv') == 'remux':
            video_path = self._get_remux_source_path_from_table2_row(row_index)
            should_load_subtitle = False
            try:
                should_load_subtitle = bool(getattr(self, 'sub_pack_hard_radio', None) and self.sub_pack_hard_radio.isChecked())
            except Exception:
                should_load_subtitle = False
            subtitle_path = ''
            try:
                sub_col = ENCODE_REMUX_LABELS.index('sub_path')
                sub_item = self.table2.item(row_index, sub_col)
                subtitle_path = sub_item.text().strip() if should_load_subtitle and sub_item and sub_item.text().strip() else ''
            except Exception:
                subtitle_path = ''
            vpy_path = self.get_vpy_path_from_row(row_index)
            self._preview_script_for_row(vpy_path=vpy_path, video_path=video_path, subtitle_path=subtitle_path)
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
        labels = ENCODE_REMUX_LABELS if getattr(self, '_encode_input_mode', 'bdmv') == 'remux' else ENCODE_LABELS
        vpy_col = labels.index('vpy_path')
        edit_col = labels.index('edit_vpy')
        preview_col = labels.index('preview_script')

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
        labels = ENCODE_REMUX_SP_LABELS if getattr(self, '_encode_input_mode', 'bdmv') == 'remux' else ENCODE_SP_LABELS
        vpy_col = labels.index('vpy_path')
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
        if not path:
            path = self.get_default_vpy_path()
            self.ensure_default_vpy_file()
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

        if getattr(self, '_encode_input_mode', 'bdmv') == 'remux':
            video_path = self._get_remux_source_path_from_table3_row(row_index)
            vpy_path = self.get_sp_vpy_path_from_row(row_index)
            self._preview_script_for_row(vpy_path=vpy_path, video_path=video_path, subtitle_path='')
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
        auto_name_map: dict[int, str] = {}
        try:
            if function_id in (3, 4) and (not self._is_movie_mode()):
                conf = getattr(self, '_last_configuration_34', None)
                if isinstance(conf, dict) and conf:
                    auto_name_map = self._build_episode_output_name_map(conf)
        except Exception:
            auto_name_map = {}
        for i in range(self.table2.rowCount()):
            item = self.table2.item(i, col)
            text = item.text().strip() if item and item.text() else ''
            if (not text) and i in auto_name_map:
                text = auto_name_map.get(i, '')
            names.append(text)
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

    def _ffprobe_video_frame_count(self, media_path: str) -> int:
        if not media_path or not os.path.exists(media_path):
            return -1
        cmd = (f'"{FFPROBE_PATH}" -v error -count_frames -select_streams v:0 '
               f'-show_entries stream=nb_read_frames,nb_frames -of json "{media_path}"')
        try:
            p = subprocess.run(cmd, shell=True, capture_output=True, text=True, encoding='utf-8', errors='ignore')
            if p.returncode != 0:
                return -1
            data = json.loads(p.stdout or '{}')
            streams = data.get('streams') or []
            if not streams:
                return 0
            s0 = streams[0] if isinstance(streams[0], dict) else {}
            for k in ('nb_read_frames', 'nb_frames'):
                try:
                    v = int(str(s0.get(k) or '').strip())
                    if v >= 0:
                        return v
                except Exception:
                    pass
        except Exception:
            pass
        return -1

    def _table3_get_sp_entry_for_row(self, row: int) -> dict[str, int | str]:
        bdmv_col = ENCODE_SP_LABELS.index('bdmv_index')
        mpls_col = ENCODE_SP_LABELS.index('mpls_file')
        m2ts_col = ENCODE_SP_LABELS.index('m2ts_file')
        out_col = ENCODE_SP_LABELS.index('output_name')
        sel_col = ENCODE_SP_LABELS.index('select')
        bdmv_item = self.table3.item(row, bdmv_col)
        mpls_item = self.table3.item(row, mpls_col)
        m2ts_item = self.table3.item(row, m2ts_col)
        out_item = self.table3.item(row, out_col)
        sel_item = self.table3.item(row, sel_col)
        return {
            'bdmv_index': int(bdmv_item.text()) if bdmv_item and bdmv_item.text() else 0,
            'mpls_file': mpls_item.text().strip() if mpls_item and mpls_item.text() else '',
            'm2ts_file': m2ts_item.text().strip() if m2ts_item and m2ts_item.text() else '',
            'output_name': out_item.text().strip() if out_item and out_item.text() else '',
            'selected': bool(sel_item and sel_item.flags() & Qt.ItemFlag.ItemIsEnabled and sel_item.checkState() == Qt.CheckState.Checked),
        }

    def _recompute_sp_output_names(self):
        if not hasattr(self, 'table3') or not self.table3:
            return
        out_col = ENCODE_SP_LABELS.index('output_name')
        sel_col = ENCODE_SP_LABELS.index('select')
        bdmv_col = ENCODE_SP_LABELS.index('bdmv_index')
        mpls_col = ENCODE_SP_LABELS.index('mpls_file')
        m2ts_col = ENCODE_SP_LABELS.index('m2ts_file')
        rows_by_vol: dict[int, list[int]] = {}
        for r in range(self.table3.rowCount()):
            try:
                bdmv_index = int(self.table3.item(r, bdmv_col).text().strip())
            except Exception:
                bdmv_index = 0
            rows_by_vol.setdefault(bdmv_index, []).append(r)
        for bdmv_index, rows in rows_by_vol.items():
            selected_rows = []
            for r in rows:
                it = self.table3.item(r, sel_col)
                if it and it.flags() & Qt.ItemFlag.ItemIsEnabled and it.checkState() == Qt.CheckState.Checked:
                    selected_rows.append(r)
            digits = max(2, len(str(max(len(selected_rows), 1))))
            seq = 0
            for r in rows:
                out_item = self.table3.item(r, out_col)
                if not out_item:
                    out_item = QTableWidgetItem('')
                    self.table3.setItem(r, out_col, out_item)
                sel_it = self.table3.item(r, sel_col)
                selected = bool(sel_it and sel_it.flags() & Qt.ItemFlag.ItemIsEnabled and sel_it.checkState() == Qt.CheckState.Checked)
                if not selected:
                    out_item.setText('')
                    continue
                seq += 1
                sp_no = str(seq).zfill(digits)
                bdmv_vol = f'{bdmv_index:03d}'
                special = str(out_item.data(Qt.ItemDataRole.UserRole + 2) or '')
                name_suffix = str(out_item.data(Qt.ItemDataRole.UserRole + 3) or '')
                mpls_file = self.table3.item(r, mpls_col).text().strip() if self.table3.item(r, mpls_col) else ''
                m2ts_text = self.table3.item(r, m2ts_col).text().strip() if self.table3.item(r, m2ts_col) else ''
                m2ts_files = [x.strip() for x in m2ts_text.split(',') if x.strip()]
                base_name = f'BD_Vol_{bdmv_vol}_SP{sp_no}'
                if not mpls_file and m2ts_files:
                    base_name = f'BD_Vol_{bdmv_vol}_{os.path.splitext(os.path.basename(m2ts_files[0]))[0]}'
                # Preserve custom suffix (e.g. chapter range suffix) across track edits and recompute.
                if (not name_suffix) and mpls_file:
                    try:
                        cur_name = out_item.text().strip()
                        cur_stem = os.path.splitext(cur_name)[0]
                        m = re.match(r'^BD_Vol_\d+_SP\d+(.*)$', cur_stem)
                        if m and m.group(1):
                            name_suffix = m.group(1)
                            out_item.setData(Qt.ItemDataRole.UserRole + 3, name_suffix)
                    except Exception:
                        pass
                base_with_suffix = f'{base_name}{name_suffix}'
                if special == 'single_frame':
                    out_item.setText(f'{base_with_suffix}.png')
                    continue
                if special == 'multi_frame':
                    out_item.setText(f'{base_with_suffix}')
                    continue
                key = BluraySubtitle._sp_track_key_from_entry(self._table3_get_sp_entry_for_row(r))
                cfg = getattr(self, '_track_selection_config', {}) or {}
                if not (isinstance(cfg, dict) and key in cfg):
                    out_item.setText(f'{base_with_suffix}.mkv')
                    continue
                tr = cfg.get(key, {}) if isinstance(cfg, dict) else {}
                sel_audio = list(tr.get('audio') or [])
                sel_sub = list(tr.get('subtitle') or [])
                if (not sel_audio) and (not sel_sub):
                    out_item.setText('')
                    continue
                is_audio_only = False
                if m2ts_files:
                    src = os.path.join(self._get_stream_dir_for_bdmv_index(bdmv_index), m2ts_files[0])
                    is_audio_only = BluraySubtitle._is_audio_only_media(src)
                if len(sel_audio) == 1 and len(sel_sub) == 0 and is_audio_only:
                    # Single audio -> extract raw elementary stream.
                    ext = 'audio'
                    if m2ts_files:
                        src = os.path.join(self._get_stream_dir_for_bdmv_index(bdmv_index), m2ts_files[0])
                        streams = self._read_ffprobe_streams(src)
                        for s in streams:
                            if str(s.get('codec_type') or '') != 'audio':
                                continue
                            if str(s.get('index', '')) == str(sel_audio[0]):
                                c = str(s.get('codec_name') or '').lower()
                                if c in ('pcm_bluray', 'pcm_s16le', 'pcm_s24le', 'pcm_s32le', 'dts', 'truehd', 'mlp'):
                                    ext = 'flac'
                                else:
                                    ext = {'aac': 'm4a'}.get(c, c or 'audio')
                                break
                    out_item.setText(f'{base_with_suffix}.{ext}')
                    continue
                if len(sel_audio) > 1 and len(sel_sub) == 0 and is_audio_only:
                    out_item.setText(f'{base_with_suffix}.mka')
                    continue
                out_item.setText(f'{base_with_suffix}.mkv')

    def _all_track_ids_from_streams(self, streams: list[dict[str, object]]) -> tuple[list[str], list[str]]:
        audio: list[str] = []
        subtitle: list[str] = []
        for s in streams or []:
            idx = str(s.get('index', '')).strip()
            if idx == '':
                continue
            ctype = str(s.get('codec_type') or '')
            if ctype == 'audio':
                audio.append(idx)
            elif ctype == 'subtitle':
                subtitle.append(idx)
        return audio, subtitle

    def _apply_select_all_tracks_to_main_and_sp(self):
        if not hasattr(self, '_track_selection_config') or not isinstance(getattr(self, '_track_selection_config', None), dict):
            self._track_selection_config = {}
        if not getattr(self, 'select_all_tracks_checkbox', None) or (not self.select_all_tracks_checkbox.isChecked()):
            return
        if self.get_selected_function_id() == 4 and getattr(self, '_encode_input_mode', 'bdmv') == 'remux':
            try:
                for r in range(self.table2.rowCount()):
                    src = self._get_remux_source_path_from_table2_row(r)
                    if not src or not os.path.exists(src):
                        continue
                    streams = self._read_mkvinfo_tracks(src)
                    a, s = self._all_track_ids_from_streams(streams)
                    self._track_selection_config[f'mkv::{os.path.normpath(src)}'] = {'audio': a, 'subtitle': s}
            except Exception:
                pass
            try:
                if hasattr(self, 'table3') and self.table3:
                    for r in range(self.table3.rowCount()):
                        src = self._get_remux_source_path_from_table3_row(r)
                        if not src or not os.path.exists(src):
                            continue
                        streams = self._read_mkvinfo_tracks(src)
                        a, s = self._all_track_ids_from_streams(streams)
                        self._track_selection_config[f'mkvsp::{os.path.normpath(src)}'] = {'audio': a, 'subtitle': s}
            except Exception:
                pass
            return
        try:
            for row in range(self.table1.rowCount()):
                root_item = self.table1.item(row, 0)
                root = root_item.text().strip() if root_item and root_item.text() else ''
                if not root:
                    continue
                info = self.table1.cellWidget(row, 2)
                if not isinstance(info, QTableWidget):
                    continue
                selected_mpls_path = ''
                for i in range(info.rowCount()):
                    main_btn = info.cellWidget(i, 3)
                    if isinstance(main_btn, QToolButton) and main_btn.isChecked():
                        mpls_item = info.item(i, 0)
                        if mpls_item and mpls_item.text().strip():
                            selected_mpls_path = os.path.normpath(os.path.join(root, 'BDMV', 'PLAYLIST', mpls_item.text().strip()))
                        break
                if not selected_mpls_path:
                    continue
                m2ts_path = self._get_first_m2ts_for_mpls(selected_mpls_path)
                if not m2ts_path:
                    continue
                streams = self._read_ffprobe_streams(m2ts_path)
                a, s = self._all_track_ids_from_streams(streams)
                self._track_selection_config[f'main::{os.path.normpath(selected_mpls_path)}'] = {'audio': a, 'subtitle': s}
        except Exception:
            pass

        try:
            if hasattr(self, 'table3') and self.table3 and self.table3.isVisible() and ('select' in ENCODE_SP_LABELS):
                sel_col = ENCODE_SP_LABELS.index('select')
                bdmv_col = ENCODE_SP_LABELS.index('bdmv_index')
                m2ts_col = ENCODE_SP_LABELS.index('m2ts_file')
                mpls_col = ENCODE_SP_LABELS.index('mpls_file')
                for r in range(self.table3.rowCount()):
                    it = self.table3.item(r, sel_col)
                    if not (it and it.flags() & Qt.ItemFlag.ItemIsEnabled and it.checkState() == Qt.CheckState.Checked):
                        continue
                    try:
                        bdmv_index = int(self.table3.item(r, bdmv_col).text().strip())
                    except Exception:
                        continue
                    stream_dir = self._get_stream_dir_for_bdmv_index(bdmv_index)
                    m2ts_text = self.table3.item(r, m2ts_col).text().strip() if self.table3.item(r, m2ts_col) else ''
                    m2ts_files = self._split_m2ts_files(m2ts_text)
                    if not (stream_dir and m2ts_files):
                        continue
                    first_m2ts = os.path.normpath(os.path.join(stream_dir, m2ts_files[0]))
                    streams = self._read_ffprobe_streams(first_m2ts)
                    a, s = self._all_track_ids_from_streams(streams)
                    entry = self._table3_get_sp_entry_for_row(r)
                    key = BluraySubtitle._sp_track_key_from_entry(entry)
                    self._track_selection_config[key] = {'audio': a, 'subtitle': s}
        except Exception:
            pass

        try:
            self._refresh_table1_remux_cmds()
        except Exception:
            pass
        try:
            self._recompute_sp_output_names()
        except Exception:
            pass

    def _on_select_all_tracks_toggled(self, checked: bool):
        try:
            if checked:
                self._apply_select_all_tracks_to_main_and_sp()
        except Exception:
            pass

    def _on_table3_item_changed(self, item: QTableWidgetItem):
        if getattr(self, '_updating_sp_table', False):
            return
        if not item:
            return
        try:
            if item.column() == ENCODE_SP_LABELS.index('select'):
                try:
                    item.setData(Qt.ItemDataRole.UserRole, 'user')
                except Exception:
                    pass
                self._recompute_sp_output_names()
                try:
                    if getattr(self, 'select_all_tracks_checkbox', None) and self.select_all_tracks_checkbox.isChecked():
                        self._apply_select_all_tracks_to_main_and_sp()
                except Exception:
                    pass
        except Exception:
            pass

    def _start_sp_table_scan(self):
        try:
            if hasattr(self, '_sp_scan_cancel_event') and isinstance(self._sp_scan_cancel_event, threading.Event):
                self._sp_scan_cancel_event.set()
        except Exception:
            pass
        try:
            if hasattr(self, '_sp_scan_thread') and isinstance(self._sp_scan_thread, QThread) and self._sp_scan_thread.isRunning():
                self._sp_scan_thread.quit()
                self._sp_scan_thread.wait(200)
        except Exception:
            pass

        bdmv_col = ENCODE_SP_LABELS.index('bdmv_index')
        mpls_col = ENCODE_SP_LABELS.index('mpls_file')
        m2ts_col = ENCODE_SP_LABELS.index('m2ts_file')
        rows: list[dict[str, object]] = []
        select_all = bool(getattr(self, 'select_all_tracks_checkbox', None) and self.select_all_tracks_checkbox.isChecked())
        for r in range(self.table3.rowCount()):
            try:
                bdmv_index = int(self.table3.item(r, bdmv_col).text().strip())
            except Exception:
                continue
            stream_dir = self._get_stream_dir_for_bdmv_index(bdmv_index)
            playlist_dir = self._get_playlist_dir_for_bdmv_index(bdmv_index)
            mpls_file = self.table3.item(r, mpls_col).text().strip() if self.table3.item(r, mpls_col) else ''
            mpls_path = os.path.normpath(os.path.join(playlist_dir, mpls_file)) if playlist_dir and mpls_file else ''
            m2ts_text = self.table3.item(r, m2ts_col).text().strip() if self.table3.item(r, m2ts_col) else ''
            m2ts_files = self._split_m2ts_files(m2ts_text)
            m2ts_paths = [os.path.normpath(os.path.join(stream_dir, f)) for f in m2ts_files] if stream_dir else []
            entry = {'bdmv_index': bdmv_index, 'mpls_file': mpls_file, 'm2ts_file': ','.join(m2ts_files), 'output_name': ''}
            sp_key = BluraySubtitle._sp_track_key_from_entry(entry)
            sel_item = self.table3.item(r, ENCODE_SP_LABELS.index('select'))
            force_disabled = bool((not sel_item) or (not (sel_item.flags() & Qt.ItemFlag.ItemIsEnabled)))
            rows.append({'row': r, 'm2ts_paths': m2ts_paths, 'mpls_path': mpls_path, 'sp_key': sp_key, 'force_disabled': force_disabled, 'select_all': select_all})

        cancel_event = threading.Event()
        self._sp_scan_cancel_event = cancel_event
        thread = QThread(self)
        worker = SpTableScanWorker(rows, cancel_event)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.result.connect(self._on_sp_table_scan_result)

        def cleanup():
            try:
                worker.deleteLater()
            except Exception:
                pass
            try:
                thread.quit()
                thread.wait(200)
                thread.deleteLater()
            except Exception:
                pass

        worker.finished.connect(cleanup)
        worker.canceled.connect(cleanup)
        worker.failed.connect(lambda msg: (cleanup(), self._show_error_dialog(msg)))
        self._sp_scan_thread = thread
        self._sp_scan_worker = worker
        thread.start()

    def _on_sp_table_scan_result(self, row: int, disabled: bool, special: str, payload: object):
        try:
            sel_col = ENCODE_SP_LABELS.index('select')
            out_col = ENCODE_SP_LABELS.index('output_name')
            tracks_col = ENCODE_SP_LABELS.index('tracks')
            play_col = ENCODE_SP_LABELS.index('play') if 'play' in ENCODE_SP_LABELS else -1
        except Exception:
            return
        if row < 0 or row >= self.table3.rowCount():
            return
        select_override = None
        sp_key = ''
        tracks_payload = {}
        if isinstance(payload, dict):
            select_override = payload.get('select_override')
            sp_key = str(payload.get('sp_key') or '').strip()
            tracks_payload = payload.get('tracks') or {}
        try:
            self._updating_sp_table = True
            sel_item = self.table3.item(row, sel_col)
            if not sel_item:
                sel_item = QTableWidgetItem('')
                self.table3.setItem(row, sel_col, sel_item)
            user_flag = sel_item.data(Qt.ItemDataRole.UserRole)
            if disabled:
                sel_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsSelectable)
                sel_item.setCheckState(Qt.CheckState.Unchecked)
                sel_item.setData(Qt.ItemDataRole.UserRole, 'auto')
            else:
                sel_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsSelectable)
                if bool(select_override) and user_flag != 'user':
                    sel_item.setCheckState(Qt.CheckState.Checked)
            out_item = self.table3.item(row, out_col)
            if out_item:
                out_item.setData(Qt.ItemDataRole.UserRole + 2, str(special or ''))
            btn_tracks = self.table3.cellWidget(row, tracks_col)
            if isinstance(btn_tracks, QToolButton):
                btn_tracks.setEnabled(not disabled)
            if play_col >= 0:
                btn_play = self.table3.cellWidget(row, play_col)
                if isinstance(btn_play, QToolButton):
                    btn_play.setEnabled(not disabled)
            try:
                select_all = bool(getattr(self, 'select_all_tracks_checkbox', None) and self.select_all_tracks_checkbox.isChecked())
                if sp_key and isinstance(tracks_payload, dict) and tracks_payload and (not disabled):
                    cfg = getattr(self, '_track_selection_config', None)
                    if not isinstance(cfg, dict):
                        self._track_selection_config = {}
                        cfg = self._track_selection_config
                    if select_all:
                        cfg[sp_key] = {'audio': list(tracks_payload.get('audio') or []),
                                       'subtitle': list(tracks_payload.get('subtitle') or [])}
                    elif sp_key not in cfg:
                        bdmv_item = self.table3.item(row, ENCODE_SP_LABELS.index('bdmv_index'))
                        mpls_item = self.table3.item(row, ENCODE_SP_LABELS.index('mpls_file'))
                        try:
                            bdmv_index = int(bdmv_item.text().strip()) if bdmv_item and bdmv_item.text() else 0
                        except Exception:
                            bdmv_index = 0
                        mpls_file = mpls_item.text().strip() if mpls_item and mpls_item.text() else ''
                        self._inherit_main_track_config_for_sp_key(bdmv_index, mpls_file, sp_key)
                        if sp_key not in cfg:
                            cfg[sp_key] = {'audio': list(tracks_payload.get('audio') or []),
                                           'subtitle': list(tracks_payload.get('subtitle') or [])}
            except Exception:
                pass
        finally:
            self._updating_sp_table = False
        try:
            self._recompute_sp_output_names()
        except Exception:
            pass

    @staticmethod
    def _parse_display_time_to_seconds(s: str) -> float:
        try:
            parts = [p for p in str(s or '').strip().split(':') if p != '']
            if not parts:
                return 0.0
            val = 0.0
            for n in parts:
                val = val * 60.0 + float(n)
            return val
        except Exception:
            return 0.0

    @staticmethod
    def _is_auto_chapter_segment_sp_item(out_item: Optional[QTableWidgetItem]) -> bool:
        """SP rows derived from main-mpls chapter inclusion (checkbox / end_at_chapter tail). Not merged from refresh snapshot."""
        if not out_item:
            return False
        if out_item.data(Qt.ItemDataRole.UserRole + 4) == 'chapter_segment_sp':
            return True
        suf = str(out_item.data(Qt.ItemDataRole.UserRole + 3) or '').strip()
        if not suf:
            return False
        return bool(re.search(r'^_(beginning|chapter_\d+)_to_(chapter_\d+|ending)$', suf, re.I))

    def _filtered_chapter_visible_layout(self, mpls_path: str) -> tuple[list[int], dict[int, str]]:
        """Match ChapterWindow: visible chapter rows and chapter_to_m2ts (1-based keys in filtered order)."""
        chapter = Chapter(mpls_path)
        mark_info = chapter.mark_info
        in_out_time = chapter.in_out_time
        mpls_duration = chapter.get_total_time()
        chapter_to_m2ts: dict[int, str] = {}
        filtered_to_unfiltered: list[int] = []
        offset = 0
        ch_idx = 1
        unfiltered_c = 0
        for ref_to_play_item_id, mark_timestamps in mark_info.items():
            m2ts_base = in_out_time[ref_to_play_item_id][0] + '.m2ts'
            for mark_timestamp in mark_timestamps:
                unfiltered_c += 1
                off = offset + (mark_timestamp - in_out_time[ref_to_play_item_id][1]) / 45000
                if mpls_duration - off >= 0.001:
                    filtered_to_unfiltered.append(unfiltered_c)
                    chapter_to_m2ts[ch_idx] = m2ts_base
                    ch_idx += 1
            offset += (in_out_time[ref_to_play_item_id][2] - in_out_time[ref_to_play_item_id][1]) / 45000
        return filtered_to_unfiltered, chapter_to_m2ts

    def _unchecked_segments_from_checkbox_states(self, mpls_path: str) -> tuple[list[tuple[int, int]], dict[int, str]]:
        """Filtered table row indices (same as ChapterWindow.get_unchecked_segments) from _chapter_checkbox_states."""
        path = mpls_path if str(mpls_path).lower().endswith('.mpls') else f'{mpls_path}.mpls'
        filtered_map, chapter_to_m2ts = self._filtered_chapter_visible_layout(path)
        if not filtered_map:
            return [], chapter_to_m2ts
        chapter = Chapter(path)
        rows = sum(map(len, chapter.mark_info.values()))
        states = list(self._chapter_checkbox_states.get(path, []))
        if len(states) < rows:
            states += [True] * (rows - len(states))
        unchecked_rows: list[int] = []
        for r, c in enumerate(filtered_map):
            if 1 <= c <= len(states) and (not states[c - 1]):
                unchecked_rows.append(r)
        segments: list[tuple[int, int]] = []
        if unchecked_rows:
            start = unchecked_rows[0]
            prev = unchecked_rows[0]
            for row_i in unchecked_rows[1:]:
                if row_i == prev + 1:
                    prev = row_i
                else:
                    segments.append((start, prev))
                    start = row_i
                    prev = row_i
            segments.append((start, prev))
        return segments, chapter_to_m2ts

    def _max_sp_serial_for_bdmv(self, bdmv_index: int) -> int:
        mmax = 0
        if not hasattr(self, 'table3') or not self.table3:
            return 0
        try:
            bdmv_col = ENCODE_SP_LABELS.index('bdmv_index')
            out_col = ENCODE_SP_LABELS.index('output_name')
        except Exception:
            return 0
        for r in range(self.table3.rowCount()):
            try:
                b = int(self.table3.item(r, bdmv_col).text().strip())
            except Exception:
                continue
            if b != bdmv_index:
                continue
            it = self.table3.item(r, out_col)
            t = it.text().strip() if it and it.text() else ''
            m = re.search(r'(?i)BD_Vol_\d+_SP(\d+)', t)
            if m:
                mmax = max(mmax, int(m.group(1)))
        return mmax

    def _remove_table3_auto_chapter_sp_rows(self, bdmv_index: int, mpls_basename: str):
        if not hasattr(self, 'table3') or not self.table3:
            return
        if self.table3.columnCount() != len(ENCODE_SP_LABELS):
            return
        try:
            bdmv_col = ENCODE_SP_LABELS.index('bdmv_index')
            mpls_col = ENCODE_SP_LABELS.index('mpls_file')
            out_col = ENCODE_SP_LABELS.index('output_name')
        except Exception:
            return
        target = (mpls_basename or '').strip()
        for r in range(self.table3.rowCount() - 1, -1, -1):
            try:
                b = int(self.table3.item(r, bdmv_col).text().strip())
            except Exception:
                continue
            if b != bdmv_index:
                continue
            m_item = self.table3.item(r, mpls_col)
            m_val = m_item.text().strip() if m_item and m_item.text() else ''
            if m_val != target:
                continue
            out_item = self.table3.item(r, out_col)
            if not self._is_auto_chapter_segment_sp_item(out_item):
                continue
            self.table3.removeRow(r)

    def _sync_chapter_checkbox_sp_for_mpls(self, mpls_path: str, bdmv_index: int):
        if self.get_selected_function_id() not in (3, 4):
            return
        path = mpls_path if str(mpls_path).lower().endswith('.mpls') else f'{mpls_path}.mpls'
        if not os.path.exists(path):
            return
        self._remove_table3_auto_chapter_sp_rows(bdmv_index, os.path.basename(path))
        self._sp_index_by_bdmv[bdmv_index] = self._max_sp_serial_for_bdmv(bdmv_index)
        segments, c2m = self._unchecked_segments_from_checkbox_states(path)
        if segments:
            self._add_sp_entries_for_unchecked_segments(path, segments, bdmv_index, c2m)

    def _sync_chapter_checkbox_sp_rows_all_volumes(self, configuration: dict[int, dict[str, int | str]]):
        if self.get_selected_function_id() not in (3, 4) or not configuration:
            return
        selected_mpls = self.get_selected_mpls_no_ext()
        if not selected_mpls:
            return
        folder_to_bdmv: dict[str, int] = {}
        bdmv_to_mpls: dict[int, str] = {}
        for folder, mpls_no_ext in selected_mpls:
            if folder not in folder_to_bdmv:
                folder_to_bdmv[folder] = len(folder_to_bdmv) + 1
            bdmv_to_mpls[folder_to_bdmv[folder]] = mpls_no_ext
        for bdmv_index, mpls_no_ext in sorted(bdmv_to_mpls.items(), key=lambda x: x[0]):
            self._sync_chapter_checkbox_sp_for_mpls(mpls_no_ext + '.mpls', bdmv_index)

    def _snapshot_chapter_segment_sp_entries(self) -> list[dict[str, object]]:
        """Preserve ad-hoc SP rows across refresh; auto chapter-segment rows are re-applied via _sync_chapter_checkbox_sp_rows_all_volumes."""
        if not hasattr(self, 'table3') or not self.table3:
            return []
        if self.table3.columnCount() != len(ENCODE_SP_LABELS):
            return []
        try:
            sel_col = ENCODE_SP_LABELS.index('select')
            bdmv_col = ENCODE_SP_LABELS.index('bdmv_index')
            mpls_col = ENCODE_SP_LABELS.index('mpls_file')
            m2ts_col = ENCODE_SP_LABELS.index('m2ts_file')
            dur_col = ENCODE_SP_LABELS.index('duration')
            out_col = ENCODE_SP_LABELS.index('output_name')
        except Exception:
            return []
        out: list[dict[str, object]] = []
        for r in range(self.table3.rowCount()):
            out_item = self.table3.item(r, out_col)
            if not out_item:
                continue
            if self._is_auto_chapter_segment_sp_item(out_item):
                continue
            suffix = str(out_item.data(Qt.ItemDataRole.UserRole + 3) or '').strip()
            if not suffix:
                continue
            try:
                bdmv_index = int(self.table3.item(r, bdmv_col).text().strip())
            except Exception:
                continue
            mpls_item = self.table3.item(r, mpls_col)
            m2ts_item = self.table3.item(r, m2ts_col)
            mpls_file = mpls_item.text().strip() if mpls_item and mpls_item.text() else ''
            m2ts_text = m2ts_item.text().strip() if m2ts_item and m2ts_item.text() else ''
            m2ts_files = [x.strip() for x in m2ts_text.split(',') if x.strip()]
            dur_item = self.table3.item(r, dur_col)
            dur = self._parse_display_time_to_seconds(dur_item.text() if dur_item else '')
            sel_item = self.table3.item(r, sel_col)
            default_selected = bool(sel_item and sel_item.checkState() == Qt.CheckState.Checked)
            is_disabled = bool((not sel_item) or (not (sel_item.flags() & Qt.ItemFlag.ItemIsEnabled)))
            special = str(out_item.data(Qt.ItemDataRole.UserRole + 2) or '')
            out.append({
                'bdmv_index': bdmv_index,
                'mpls_file': mpls_file,
                'm2ts_files': m2ts_files,
                'duration': dur,
                'default_selected': default_selected,
                'disabled': is_disabled,
                'special': special,
                'preserve_chapter_sp': True,
                'name_suffix': suffix,
            })
        return out

    def refresh_sp_table(self, configuration: dict[int, dict[str, int | str]]):
        function_id = self.get_selected_function_id()
        if function_id not in (3, 4) or not configuration:
            if hasattr(self, 'table3'):
                self.table3.setRowCount(0)
            return
        try:
            if self.table3.columnCount() != len(ENCODE_SP_LABELS):
                self.table3.setColumnCount(len(ENCODE_SP_LABELS))
                self._set_table_headers(self.table3, ENCODE_SP_LABELS)
            bdmv_index_conf: dict[int, list[dict[str, int | str]]] = {}
            for _, conf in configuration.items():
                bdmv_index_conf.setdefault(int(conf['bdmv_index']), []).append(conf)

            entries: list[dict[str, object]] = []
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
                playlist_dir = os.path.dirname(mpls_path)

                try:
                    playlist_files = os.listdir(playlist_dir)
                except Exception:
                    traceback.print_exc()
                    playlist_files = []

                for mpls_file in sorted(playlist_files):
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
                    ordered: list[str] = []
                    try:
                        for k in sorted(idx_to_m2ts.keys()):
                            v = str(idx_to_m2ts.get(k) or '').strip()
                            if v and v not in ordered:
                                ordered.append(v)
                    except Exception:
                        ordered = [str(x).strip() for x in idx_to_m2ts.values() if str(x).strip()]
                    m2ts_files = ordered
                    m2ts_set = set(m2ts_files)
                    default_selected = True
                    if m2ts_set and m2ts_set.issubset(main_m2ts_files):
                        default_selected = False
                    dur = ch.get_total_time()
                    if dur < 30:
                        default_selected = False
                    entries.append({
                        'bdmv_index': bdmv_index,
                        'mpls_file': os.path.basename(mpls_file_path),
                        'm2ts_files': m2ts_files,
                        'duration': dur,
                        'default_selected': bool(default_selected),
                        'disabled': False,
                        'special': '',
                    })

                # Add remaining m2ts not referenced by any playlist mpls.
                all_mpls_m2ts: set[str] = set()
                for pf in playlist_files:
                    if not pf.endswith('.mpls'):
                        continue
                    try:
                        ch2 = Chapter(os.path.join(playlist_dir, pf))
                        idx2, _ = get_index_to_m2ts_and_offset(ch2)
                        for _, v in idx2.items():
                            vv = str(v or '').strip()
                            if vv:
                                all_mpls_m2ts.add(vv)
                    except Exception:
                        continue
                stream_folder = os.path.join(os.path.dirname(playlist_dir), 'STREAM')
                if os.path.isdir(stream_folder):
                    try:
                        stream_files = sorted(os.listdir(stream_folder))
                    except Exception:
                        stream_files = []
                    for sf in stream_files:
                        if not sf.endswith('.m2ts'):
                            continue
                        if sf in all_mpls_m2ts:
                            continue
                        try:
                            dur = M2TS(os.path.join(stream_folder, sf)).get_duration() / 90000.0
                        except Exception:
                            dur = 0.0
                        entries.append({
                            'bdmv_index': bdmv_index,
                            'mpls_file': '',
                            'm2ts_files': [sf],
                            'duration': dur,
                            'default_selected': bool(dur >= 30.0),
                            'disabled': bool(dur <= 0.0),
                            'special': '',
                        })

            def _sp_entry_sort_key(e: dict[str, object]):
                return (
                    int(e.get('bdmv_index') or 0),
                    1 if not str(e.get('mpls_file') or '').strip() else 0,
                    str(e.get('mpls_file') or ''),
                    ','.join([str(x) for x in (e.get('m2ts_files') or [])]),
                )

            def _sp_entry_key_tuple(e: dict[str, object]):
                return (
                    int(e.get('bdmv_index') or 0),
                    str(e.get('mpls_file') or ''),
                    ','.join([str(x) for x in (e.get('m2ts_files') or [])]),
                )

            entries = sorted(entries, key=_sp_entry_sort_key)
            preserved_sp = self._snapshot_chapter_segment_sp_entries()
            if preserved_sp:
                by_key: dict[tuple[int, str, str], dict[str, object]] = {}
                for e in entries:
                    by_key[_sp_entry_key_tuple(e)] = e
                for pe in preserved_sp:
                    by_key[_sp_entry_key_tuple(pe)] = pe
                entries = sorted(by_key.values(), key=_sp_entry_sort_key)

            old_sorting = self.table3.isSortingEnabled()
            old_current_row = self.table3.currentRow()
            old_current_col = self.table3.currentColumn()
            old_h_scroll = self.table3.horizontalScrollBar().value() if self.table3.horizontalScrollBar() else 0
            old_v_scroll = self.table3.verticalScrollBar().value() if self.table3.verticalScrollBar() else 0
            self.table3.setSortingEnabled(False)
            try:
                self._updating_sp_table = True
                old_name_map: dict[tuple[int, str, str], tuple[str, Optional[str]]] = {}
                sel_col = ENCODE_SP_LABELS.index('select')
                bdmv_col = ENCODE_SP_LABELS.index('bdmv_index')
                mpls_col = ENCODE_SP_LABELS.index('mpls_file')
                m2ts_col = ENCODE_SP_LABELS.index('m2ts_file')
                dur_col = ENCODE_SP_LABELS.index('duration')
                out_col = ENCODE_SP_LABELS.index('output_name')
                for r in range(self.table3.rowCount()):
                    bdmv_item = self.table3.item(r, bdmv_col)
                    mpls_item = self.table3.item(r, mpls_col)
                    m2ts_item = self.table3.item(r, m2ts_col)
                    out_item = self.table3.item(r, out_col)
                    if bdmv_item and out_item and out_item.text():
                        key = (int(bdmv_item.text() or 0), mpls_item.text() if mpls_item else '', m2ts_item.text() if m2ts_item else '')
                        old_name_map[key] = (out_item.text().strip(), out_item.data(Qt.ItemDataRole.UserRole) if out_item else None)

                self.table3.setRowCount(len(entries))
                for i, e in enumerate(entries):
                    bdmv_index = int(e.get('bdmv_index') or 0)
                    mpls_file = str(e.get('mpls_file') or '')
                    m2ts_files = [str(x) for x in (e.get('m2ts_files') or [])]
                    dur = float(e.get('duration') or 0.0)
                    auto_out_name = ''
                    is_disabled = bool(e.get('disabled'))
                    default_selected = bool(e.get('default_selected'))
                    special = str(e.get('special') or '')
                    sel_item = QTableWidgetItem('')
                    sel_item.setCheckState(Qt.CheckState.Checked if default_selected else Qt.CheckState.Unchecked)
                    if is_disabled:
                        sel_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsSelectable)
                        sel_item.setCheckState(Qt.CheckState.Unchecked)
                    else:
                        sel_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsSelectable)
                    sel_item.setData(Qt.ItemDataRole.UserRole, 'auto')
                    self.table3.setItem(i, sel_col, sel_item)
                    self.table3.setItem(i, bdmv_col, QTableWidgetItem(str(bdmv_index)))
                    self.table3.setItem(i, mpls_col, QTableWidgetItem(mpls_file))
                    self.table3.setItem(i, m2ts_col, QTableWidgetItem(','.join(m2ts_files)))
                    self.table3.setItem(i, dur_col, QTableWidgetItem(get_time_str(dur)))
                    tracks_col = ENCODE_SP_LABELS.index('tracks')
                    btn_tracks = QToolButton(self.table3)
                    btn_tracks.setText(self.t('edit tracks'))
                    btn_tracks.clicked.connect(self._on_edit_tracks_from_sp_table_clicked)
                    btn_tracks.setEnabled(not is_disabled)
                    self.table3.setCellWidget(i, tracks_col, btn_tracks)
                    play_col = ENCODE_SP_LABELS.index('play') if 'play' in ENCODE_SP_LABELS else -1
                    if play_col >= 0:
                        btn_play = QToolButton(self.table3)
                        btn_play.setText(self.t('play'))
                        btn_play.clicked.connect(self._on_play_sp_table_row_clicked)
                        btn_play.setEnabled(not is_disabled)
                        self.table3.setCellWidget(i, play_col, btn_play)
                    key = (bdmv_index, mpls_file, ','.join(m2ts_files))
                    prev = old_name_map.get(key)
                    prev_text = prev[0] if prev else ''
                    prev_auto = prev[1] if prev else None
                    if e.get('preserve_chapter_sp'):
                        out_item = QTableWidgetItem('')
                        out_item.setData(Qt.ItemDataRole.UserRole, '')
                        out_item.setData(Qt.ItemDataRole.UserRole + 2, special)
                        out_item.setData(Qt.ItemDataRole.UserRole + 3, str(e.get('name_suffix') or ''))
                    else:
                        if prev_text and isinstance(prev_auto, str) and prev_text != prev_auto:
                            final_text = prev_text
                        else:
                            final_text = auto_out_name
                        out_item = QTableWidgetItem(final_text)
                        out_item.setData(Qt.ItemDataRole.UserRole, auto_out_name)
                        out_item.setData(Qt.ItemDataRole.UserRole + 2, special)
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
                        for key in ('vpy_path', 'edit_vpy', 'preview_script'):
                            try:
                                col = ENCODE_SP_LABELS.index(key)
                            except Exception:
                                continue
                            self.table3.setItem(i, col, None)
                            self.table3.setCellWidget(i, col, None)
                self._recompute_sp_output_names()
                try:
                    self._sync_chapter_checkbox_sp_rows_all_volumes(configuration)
                except Exception:
                    traceback.print_exc()
                self._recompute_sp_output_names()
                self.table3.resizeColumnsToContents()
                self._resize_table_columns_for_language(self.table3)
                try:
                    if 0 <= old_current_row < self.table3.rowCount() and 0 <= old_current_col < self.table3.columnCount():
                        self.table3.setCurrentCell(old_current_row, old_current_col)
                    else:
                        self.table3.clearSelection()
                    if self.table3.horizontalScrollBar():
                        self.table3.horizontalScrollBar().setValue(old_h_scroll)
                    if self.table3.verticalScrollBar():
                        self.table3.verticalScrollBar().setValue(old_v_scroll)
                except Exception:
                    pass
            finally:
                self._updating_sp_table = False
                self.table3.setSortingEnabled(old_sorting)
            try:
                self._start_sp_table_scan()
            except Exception:
                pass
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
        self.x265_preset_combo.addItem('快速', '快速')
        self.x265_preset_combo.addItem('均衡', '均衡')
        self.x265_preset_combo.addItem('高质', '高质')
        self.x265_preset_combo.addItem('极限', '极限')
        self.x265_preset_combo.addItem('自订', '自订')
        idx_balanced = self.x265_preset_combo.findData('均衡')
        self.x265_preset_combo.setCurrentIndex(0 if idx_balanced < 0 else idx_balanced)
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
            preset = str(self.x265_preset_combo.currentData() or self.x265_preset_combo.currentText() or '')
            if preset == '自订':
                return
            set_params_for_preset(preset)

        def on_params_edited():
            if self._encode_setting_updating:
                return
            if str(self.x265_preset_combo.currentData() or '') != '自订':
                idx_custom = self.x265_preset_combo.findData('自订')
                if idx_custom >= 0:
                    self.x265_preset_combo.setCurrentIndex(idx_custom)

        self.x265_preset_combo.currentIndexChanged.connect(on_preset_changed)
        self.x265_params_edit.textChanged.connect(on_params_edited)
        set_params_for_preset(str(self.x265_preset_combo.currentData() or '均衡'))

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
        language_layout.addSpacing(12)
        self.theme_label = QLabel('模式', language_row)
        self.theme_combo = QComboBox(language_row)
        self.theme_combo.addItem('浅色', 'light')
        self.theme_combo.addItem('深色', 'dark')
        self.theme_combo.addItem('彩色', 'colorful')
        self.theme_combo.setCurrentIndex(0)
        self.theme_combo.currentIndexChanged.connect(lambda _=None: self._on_theme_changed())
        language_layout.addWidget(self.theme_label)
        language_layout.addWidget(self.theme_combo)
        language_layout.addSpacing(12)
        self.opacity_label = QLabel('透明度', language_row)
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal, language_row)
        self.opacity_slider.setRange(60, 100)
        self.opacity_slider.setValue(int(getattr(self, '_colorful_opacity', 0.94) * 100))
        self.opacity_slider.setFixedWidth(140)
        self.opacity_slider.valueChanged.connect(self._on_opacity_changed)
        self.opacity_slider.sliderReleased.connect(
            lambda: self.opacity_slider.setValue(100 if self.opacity_slider.value() >= 99 else self.opacity_slider.value())
        )
        language_layout.addWidget(self.opacity_label)
        language_layout.addWidget(self.opacity_slider)
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
        self.function_tabbar.setObjectName('functionTabbar')
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
            if self.get_selected_function_id() in (3, 4):
                try:
                    self._refresh_table1_remux_cmds()
                except Exception:
                    pass

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
        self.bluray_path_box = bluray_path_box
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

        remux_path_box = CustomBox('Remux', self)
        remux_path_box.setProperty("noMargin", True)
        remux_layout = QHBoxLayout()
        remux_layout.setContentsMargins(0, 0, 0, 0)
        remux_layout.setSpacing(4)
        remux_path_box.setLayout(remux_layout)
        self.remux_folder_path = QLineEdit()
        self.remux_folder_path.setMinimumWidth(200)
        self.remux_folder_path.setAcceptDrops(False)
        self.remux_folder_path.textChanged.connect(lambda _=None: QTimer.singleShot(150, self._populate_encode_from_remux_folder))
        remux_btn = QPushButton("选择")
        remux_btn.clicked.connect(self.select_remux_folder)
        remux_btn_open = QPushButton("打开")
        remux_btn_open.clicked.connect(lambda _=None: self.open_folder_path(self.remux_folder_path.text()))
        remux_layout.addWidget(self.remux_folder_path)
        remux_layout.addWidget(remux_btn)
        remux_layout.addWidget(remux_btn_open)
        self.remux_path_box = remux_path_box
        self.remux_path_box.setVisible(False)
        v_layout.addWidget(remux_path_box)

        label1_container = QWidget(self)
        self.label1_container = label1_container
        label1_layout = QVBoxLayout()
        label1_layout.setContentsMargins(0, 0, 0, 0)
        label1_layout.setSpacing(0)
        label1_container.setLayout(label1_layout)
        self.label1.setText(self.t('选择文件夹'))

        encode_source_row = QWidget(self)
        encode_source_layout = QHBoxLayout()
        encode_source_layout.setContentsMargins(0, 0, 0, 0)
        encode_source_layout.setSpacing(8)
        encode_source_row.setLayout(encode_source_layout)
        encode_source_layout.addWidget(self.label1)
        self.encode_source_bdmv_radio = QRadioButton('原盘', encode_source_row)
        self.encode_source_remux_radio = QRadioButton('Remux', encode_source_row)
        self.encode_source_bdmv_radio.setChecked(True)
        encode_source_layout.addWidget(self.encode_source_bdmv_radio)
        encode_source_layout.addWidget(self.encode_source_remux_radio)
        encode_source_layout.addStretch(1)
        self.encode_source_row = encode_source_row
        self.encode_source_row.setVisible(self.get_selected_function_id() == 4)
        self._encode_input_mode = 'bdmv'

        def on_encode_source_changed():
            self._encode_input_mode = 'remux' if self.encode_source_remux_radio.isChecked() else 'bdmv'
            try:
                self._apply_encode_input_mode_ui()
            except Exception:
                traceback.print_exc()

        self.encode_source_bdmv_radio.toggled.connect(on_encode_source_changed)
        self.encode_source_remux_radio.toggled.connect(on_encode_source_changed)
        label1_layout.addWidget(bdmv)

        select_all_tracks_row = QWidget(self)
        select_all_tracks_layout = QHBoxLayout()
        select_all_tracks_layout.setContentsMargins(0, 0, 0, 0)
        select_all_tracks_layout.setSpacing(8)
        select_all_tracks_row.setLayout(select_all_tracks_layout)
        self.select_all_tracks_checkbox = QCheckBox(self.t('Select all tracks'), select_all_tracks_row)
        self.select_all_tracks_checkbox.setChecked(False)
        self.select_all_tracks_checkbox.toggled.connect(self._on_select_all_tracks_toggled)
        select_all_tracks_layout.addWidget(self.select_all_tracks_checkbox)
        select_all_tracks_layout.addStretch(1)
        self.select_all_tracks_row = select_all_tracks_row
        v_layout.addWidget(select_all_tracks_row)

        self.table1 = QTableWidget()
        self.table1.setObjectName('table1')
        self.table1.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.table1.setColumnCount(len(BDMV_LABELS))
        self._set_table_headers(self.table1, BDMV_LABELS)
        self.table1.setSortingEnabled(True)
        self.table1.horizontalHeader().setSortIndicatorShown(True)
        self.bdmv_folder_path.textChanged.connect(self.on_bdmv_folder_path_change)
        v_layout.addWidget(self.table1)
        v_layout.setStretch(v_layout.indexOf(self.table1), 1)
        try:
            idx = self.layout.indexOf(self.episode_mode_row)
            if idx >= 0:
                self.layout.insertWidget(idx, self.encode_source_row)
            else:
                self.layout.insertWidget(1, self.encode_source_row)
        except Exception:
            self.layout.insertWidget(1, self.encode_source_row)

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
        self.label2_container = label2_container
        label2_layout = QVBoxLayout()
        label2_layout.setContentsMargins(0, 0, 0, 0)
        label2_layout.setSpacing(0)
        label2_container.setLayout(label2_layout)
        label2_layout.addWidget(self.label2)
        label2_layout.addWidget(subtitle)

        self.table2 = CustomTableWidget(self, self.on_subtitle_drop)
        self.table2.setObjectName('table2')
        self.table2.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
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
        self._chapter_combo_debounce = QTimer(self)
        self._chapter_combo_debounce.setSingleShot(True)
        self._chapter_combo_debounce.setInterval(120)
        self._chapter_combo_debounce.timeout.connect(self._run_chapter_combo_update)
        self._pending_chapter_combo_index = -1
        self.table3 = QTableWidget(self)
        self.table3.setObjectName('table3')
        self.table3.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._set_compact_table(self.table3, row_height=22, header_height=22)
        self.table3.setColumnCount(len(ENCODE_SP_LABELS))
        self._set_table_headers(self.table3, ENCODE_SP_LABELS)
        self.table3.setSortingEnabled(True)
        self.table3.horizontalHeader().setSortIndicatorShown(True)
        self._updating_sp_table = False
        self.table3.itemChanged.connect(self._on_table3_item_changed)
        self.table3.setVisible(False)
        self.subtitle_tables_splitter = QSplitter(Qt.Orientation.Vertical, subtitle)
        self.subtitle_tables_splitter.setObjectName('subtitleTablesSplitter')
        self.subtitle_tables_splitter.setChildrenCollapsible(False)
        self.subtitle_tables_splitter.addWidget(self.table2)
        self.subtitle_tables_splitter.addWidget(self.table3)
        self.subtitle_tables_splitter.setStretchFactor(0, 1)
        self.subtitle_tables_splitter.setStretchFactor(1, 1)
        self.subtitle_tables_splitter.setSizes([360, 360])
        v_layout.addWidget(self.subtitle_tables_splitter)
        v_layout.setStretch(v_layout.indexOf(self.subtitle_tables_splitter), 1)

        label1_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        label2_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        bdmv.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        subtitle.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        tables_splitter = QSplitter(Qt.Orientation.Vertical, self)
        self.tables_splitter = tables_splitter
        tables_splitter.setObjectName('tablesSplitter')
        tables_splitter.setChildrenCollapsible(False)
        tables_splitter.addWidget(label1_container)
        tables_splitter.addWidget(label2_container)
        tables_splitter.setStretchFactor(0, 1)
        tables_splitter.setStretchFactor(1, 1)
        tables_splitter.setSizes([480, 480])
        self.layout.addWidget(tables_splitter)
        self.layout.setStretch(self.layout.indexOf(tables_splitter), 1)

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

        self.subtitle_suffix_label = QLabel("添加后缀", merge_options_row)
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
        self._remux_cmd_refresh_timer = QTimer(self)
        self._remux_cmd_refresh_timer.setSingleShot(True)
        self._remux_cmd_refresh_timer.setInterval(300)
        self._remux_cmd_refresh_timer.timeout.connect(lambda: self._refresh_table1_remux_cmds() if self.get_selected_function_id() in (3, 4) else None)
        self.output_folder_path.textChanged.connect(lambda _=None: self._remux_cmd_refresh_timer.start())
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
        self._track_selection_config: dict[str, dict[str, list[str]]] = {}
        self._apply_language('en')
        self._apply_theme(getattr(self, '_theme_mode', 'light'))

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
                start_ts = time.time()
                progress_dialog = QProgressDialog(self.t('读取中'), '', 0, 1000, self)
                progress_dialog.setMinimumWidth(420)
                bar = QProgressBar(progress_dialog)
                bar.setRange(0, 1000)
                bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
                progress_dialog.setBar(bar)
                progress_dialog.setCancelButton(None)
                progress_dialog.setMinimumDuration(0)
                progress_dialog.setAutoClose(False)
                progress_dialog.setAutoReset(False)
                progress_dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
                show_timer = QTimer(self)
                show_timer.setSingleShot(True)
                show_timer.setInterval(2000)

                def show_if_needed():
                    try:
                        if (time.time() - start_ts) >= 2.0:
                            progress_dialog.show()
                    except Exception:
                        pass

                show_timer.timeout.connect(show_if_needed)
                show_timer.start()
                self.table1.setColumnCount(len(BDMV_LABELS))
                self._set_table_headers(self.table1, BDMV_LABELS)
                i = 0
                for root, dirs, files in os.walk(bdmv_path):
                    dirs.sort()  # Sort dirs to ensure consistent order on all platforms
                    if 'BDMV' in dirs and 'PLAYLIST' in os.listdir(os.path.join(root, 'BDMV')):
                        i += 1
                    if (time.time() - start_ts) >= 2.0:
                        QCoreApplication.processEvents()
                self.table1.setRowCount(i)
                i = 0
                for root, dirs, files in os.walk(bdmv_path):
                    dirs.sort()  # Sort dirs to ensure consistent order on all platforms
                    if 'BDMV' in dirs and 'PLAYLIST' in os.listdir(os.path.join(root, 'BDMV')):
                        table_widget = QTableWidget()
                        self._set_compact_table(table_widget, row_height=20, header_height=20)
                        info_headers = ['mpls_file', 'duration', 'chapters', 'main', 'play']
                        if self.get_selected_function_id() in (3, 4):
                            info_headers.append('tracks')
                        table_widget.setColumnCount(len(info_headers))
                        self._set_table_headers(table_widget, info_headers)
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
                                btn1.clicked.connect(partial(self.on_button_click, mpls_path, mpls_path == selected_mpls, i + 1))
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
                                if self.get_selected_function_id() in (3, 4):
                                    if mpls_path == selected_mpls:
                                        btn4 = QToolButton()
                                        btn4.setText(self.t('编辑轨道'))
                                        btn4.clicked.connect(partial(self.on_edit_tracks_from_mpls, mpls_path))
                                        table_widget.setCellWidget(mpls_n, 5, btn4)
                                    else:
                                        table_widget.setItem(mpls_n, 5, QTableWidgetItem(''))
                                table_widget.resizeColumnsToContents()
                                mpls_n += 1
                                if (time.time() - start_ts) >= 2.0:
                                    QCoreApplication.processEvents()
                        self.table1.setItem(i, 0, FilePathTableWidgetItem(os.path.normpath(root)))
                        self.table1.setItem(i, 1, QTableWidgetItem(get_folder_size(root)))
                        self.table1.setCellWidget(i, 2, table_widget)
                        if self.get_selected_function_id() in (3, 4):
                            resolved_bdmv_index = self._resolve_bdmv_index_for_main_mpls(selected_mpls, i + 1)
                            cmd_text = self._build_main_remux_cmd_template(selected_mpls, resolved_bdmv_index, root)
                            self.table1.setCellWidget(i, BDMV_LABELS.index('remux_cmd'),
                                                      self._create_main_remux_cmd_editor(cmd_text, self.table1))
                        else:
                            self.table1.setItem(i, BDMV_LABELS.index('remux_cmd'), QTableWidgetItem(''))
                        self.table1.setRowHeight(i, 100)
                        i += 1
                        if (time.time() - start_ts) >= 2.0:
                            QCoreApplication.processEvents()
                self.table1.resizeColumnsToContents()
                if self.get_selected_function_id() in (3, 4):
                    self.table1.setColumnWidth(2, 620 if getattr(self, '_language_code', CURRENT_UI_LANGUAGE) == 'zh' else 560)
                    self.table1.setColumnWidth(3, 420 if getattr(self, '_language_code', CURRENT_UI_LANGUAGE) == 'zh' else 380)
                else:
                    self.table1.setColumnWidth(2, 420 if getattr(self, '_language_code', CURRENT_UI_LANGUAGE) == 'zh' else 370)
                    self.table1.setColumnWidth(3, 0)
                self._scroll_table_h_to_right(self.table1)
                table_ok = True
                try:
                    show_timer.stop()
                    progress_dialog.close()
                    progress_dialog.deleteLater()
                except Exception:
                    pass
            except Exception as e:
                try:
                    show_timer.stop()
                    progress_dialog.close()
                    progress_dialog.deleteLater()
                except Exception:
                    pass
                self.table1.clear()
                self.table1.setColumnCount(len(BDMV_LABELS))
                self._set_table_headers(self.table1, BDMV_LABELS)
                self.table1.setRowCount(0)
        if bdmv_path and table_ok and self.get_selected_function_id() in (3, 4):
            self._refresh_track_selection_config_for_selected_main()
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
            elif self.get_selected_function_id() in (3, 4) and (not self._is_movie_mode()):
                self.table2.setRowCount(0)
                self.refresh_sp_table({})

        def on_canceled():
            cleanup()

        def on_failed(message: str):
            cleanup()
            self._show_error_dialog(message)

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
            print(f'{translate_text("Subtitle drag-in failed: ")}{str(e)}')
            import traceback
            traceback.print_exc()
            # Log error information without showing a popup dialog.
            print(translate_text('Subtitle drag-in failed, please check the subtitle files and Blu-ray path'))

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

    def _chapter_label_text(self, value: int, rows: int, has_beginning: bool, for_end: bool = False) -> str:
        if for_end and value >= rows + 1:
            return 'ending'
        if for_end and has_beginning and value == 1:
            return 'chapter 01'
        if has_beginning and value == 1:
            return 'beginning'
        chapter_no = value - 1 if has_beginning else value
        if chapter_no < 1:
            chapter_no = 1
        return f'chapter {chapter_no:02d}'

    def _build_start_chapter_options(self, rows: int, has_beginning: bool) -> list[tuple[int, str]]:
        return [(v, self._chapter_label_text(v, rows, has_beginning, for_end=False)) for v in range(1, rows + 1)]

    def _build_end_chapter_combo(self, rows: int, has_beginning: bool, start_value: int, selected_value: int = 0) -> QComboBox:
        combo = QComboBox()
        for v in range(1, rows + 2):
            combo.addItem(self._chapter_label_text(v, rows, has_beginning, for_end=True), v)
        self._apply_end_combo_min_constraint(combo, max(1, int(start_value) + 1))
        if selected_value <= 0:
            selected_value = max(1, int(start_value) + 1)
        selected_idx = -1
        for i in range(combo.count()):
            if int(combo.itemData(i) or 0) == int(selected_value):
                selected_idx = i
                break
        if selected_idx < 0:
            for i in range(combo.count()):
                v = int(combo.itemData(i) or 0)
                if v >= max(1, int(start_value) + 1):
                    selected_idx = i
                    break
        if selected_idx >= 0:
            combo.setCurrentIndex(selected_idx)
        combo._prev_end_value = int(combo.currentData() or (combo.currentIndex() + 1))
        return combo

    def _apply_end_combo_min_constraint(self, combo: QComboBox, min_allowed: int):
        model = combo.model()
        ending_value = int(combo.itemData(combo.count() - 1) or (combo.count()))
        for i in range(combo.count()):
            v = int(combo.itemData(i) or (i + 1))
            item = model.item(i) if hasattr(model, 'item') else None
            if item is not None:
                item.setEnabled((v >= min_allowed) or (v == ending_value))
        cur_v = int(combo.currentData() or (combo.currentIndex() + 1))
        if cur_v < min_allowed and cur_v != ending_value:
            for i in range(combo.count()):
                v = int(combo.itemData(i) or (i + 1))
                if (v >= min_allowed) or (v == ending_value):
                    combo.blockSignals(True)
                    combo.setCurrentIndex(i)
                    combo.blockSignals(False)
                    break

    def _set_segment_states_for_range(self, mpls_no_ext: str, start_idx: int, end_idx: int, checked: bool):
        if not mpls_no_ext:
            return
        mpls_path = mpls_no_ext + '.mpls'
        try:
            rows = int(self._chapter_node_data(mpls_no_ext).get('rows') or 0)
        except Exception:
            rows = 0
        if rows <= 0:
            return
        states = list(self._chapter_checkbox_states.get(mpls_path, []))
        if len(states) < rows:
            states += [True] * (rows - len(states))
        s = max(1, min(int(start_idx), rows))
        e = max(1, min(int(end_idx), rows))
        if s > e:
            s, e = e, s
        for i in range(s, e + 1):
            states[i - 1] = bool(checked)
        self._chapter_checkbox_states[mpls_path] = states

    def _apply_start_chapter_constraints(self, labels: list[str]):
        if 'start_at_chapter' not in labels:
            return
        start_col = labels.index('start_at_chapter')
        end_col = labels.index('end_at_chapter') if 'end_at_chapter' in labels else -1
        bdmv_col = labels.index('bdmv_index')
        selected_mpls = self.get_selected_mpls_no_ext()
        folder_to_bdmv_index: dict[str, int] = {}
        bdmv_to_mpls: dict[int, str] = {}
        for folder, mpls_no_ext in selected_mpls:
            if folder not in folder_to_bdmv_index:
                folder_to_bdmv_index[folder] = len(folder_to_bdmv_index) + 1
            bdmv_to_mpls[folder_to_bdmv_index[folder]] = mpls_no_ext
        prev_end_by_bdmv: dict[int, int] = {}
        for r in range(self.table2.rowCount()):
            b_item = self.table2.item(r, bdmv_col)
            try:
                bdmv_index = int(b_item.text().strip()) if b_item and b_item.text() else 0
            except Exception:
                bdmv_index = 0
            combo = self.table2.cellWidget(r, start_col)
            if not isinstance(combo, QComboBox):
                continue
            min_allowed = prev_end_by_bdmv.get(bdmv_index, 1)
            mpls_no_ext = bdmv_to_mpls.get(bdmv_index, '')
            checked_states: list[bool] = []
            if mpls_no_ext:
                mpls_path = mpls_no_ext + '.mpls'
                checked_states = list(self._chapter_checkbox_states.get(mpls_path, []))
            # Make sure every item has stable numeric value data.
            for i in range(combo.count()):
                if combo.itemData(i) is None:
                    combo.setItemData(i, i + 1)
            model = combo.model()
            for i in range(combo.count()):
                v = int(combo.itemData(i) or (i + 1))
                item = model.item(i) if hasattr(model, 'item') else None
                if item is not None:
                    enabled_by_segment = True
                    if checked_states and 1 <= v <= len(checked_states):
                        enabled_by_segment = bool(checked_states[v - 1])
                    item.setEnabled((v >= min_allowed) and enabled_by_segment)
            cur_v = int(combo.currentData() or (combo.currentIndex() + 1))
            if cur_v < min_allowed:
                for i in range(combo.count()):
                    v = int(combo.itemData(i) or (i + 1))
                    if v >= min_allowed:
                        combo.blockSignals(True)
                        combo.setCurrentIndex(i)
                        combo.blockSignals(False)
                        cur_v = v
                        break
            if end_col >= 0:
                end_val = 0
                end_combo = self.table2.cellWidget(r, end_col)
                if isinstance(end_combo, QComboBox):
                    try:
                        end_val = int(end_combo.currentData() or 0)
                    except Exception:
                        end_val = 0
                else:
                    end_item = self.table2.item(r, end_col)
                    if end_item:
                        try:
                            end_val = int(end_item.data(Qt.ItemDataRole.UserRole + 1) or 0)
                        except Exception:
                            end_val = 0
                prev_end_by_bdmv[bdmv_index] = end_val if end_val > 0 else cur_v
            else:
                prev_end_by_bdmv[bdmv_index] = cur_v

    def _on_end_chapter_combo_changed(self, row: int, labels: list[str]):
        if row < 0 or row >= self.table2.rowCount():
            return
        start_col = labels.index('start_at_chapter')
        end_col = labels.index('end_at_chapter')
        start_combo = self.table2.cellWidget(row, start_col)
        end_combo = self.table2.cellWidget(row, end_col)
        if isinstance(start_combo, QComboBox) and isinstance(end_combo, QComboBox):
            start_v = int(start_combo.currentData() or (start_combo.currentIndex() + 1))
            old_v = int(getattr(end_combo, '_prev_end_value', end_combo.currentData() or (end_combo.currentIndex() + 1)))
            self._apply_end_combo_min_constraint(end_combo, start_v + 1)
            new_v = int(end_combo.currentData() or (end_combo.currentIndex() + 1))
            if new_v < old_v:
                bdmv_col = labels.index('bdmv_index')
                b_item = self.table2.item(row, bdmv_col)
                try:
                    bdmv_index = int(b_item.text().strip()) if b_item and b_item.text() else 0
                except Exception:
                    bdmv_index = 0
                selected_mpls = self.get_selected_mpls_no_ext()
                folder_to_bdmv_index: dict[str, int] = {}
                bdmv_to_mpls: dict[int, str] = {}
                for folder, mpls_no_ext in selected_mpls:
                    if folder not in folder_to_bdmv_index:
                        folder_to_bdmv_index[folder] = len(folder_to_bdmv_index) + 1
                    bdmv_to_mpls[folder_to_bdmv_index[folder]] = mpls_no_ext
                mpls_no_ext = bdmv_to_mpls.get(bdmv_index, '')
                # Next episode start must be on the *same* main MPLS (not the next table row when it is another disc/volume).
                next_start_same_mpls = 0
                for r2 in range(row + 1, self.table2.rowCount()):
                    b2 = self.table2.item(r2, bdmv_col)
                    try:
                        b2i = int(b2.text().strip()) if b2 and b2.text() else 0
                    except Exception:
                        b2i = 0
                    if bdmv_to_mpls.get(b2i, '') != mpls_no_ext:
                        continue
                    nxc = self.table2.cellWidget(r2, start_col)
                    if isinstance(nxc, QComboBox):
                        next_start_same_mpls = int(nxc.currentData() or (nxc.currentIndex() + 1))
                    break
                if next_start_same_mpls > 0 and next_start_same_mpls > new_v:
                    self._set_segment_states_for_range(mpls_no_ext, new_v, next_start_same_mpls - 1, False)
                elif next_start_same_mpls <= 0 and mpls_no_ext:
                    # Last episode on this MPLS: uncheck from new end through last chapter mark.
                    try:
                        total_rows = int(self._chapter_node_data(mpls_no_ext).get('rows') or 0)
                    except Exception:
                        total_rows = 0
                    if total_rows > 0 and new_v <= total_rows:
                        self._set_segment_states_for_range(mpls_no_ext, new_v, total_rows, False)
            end_combo._prev_end_value = int(end_combo.currentData() or (end_combo.currentIndex() + 1))
        self._apply_start_chapter_constraints(labels)
        # End changes also trigger configuration regeneration.
        self.on_chapter_combo(row)

    def _sync_end_chapter_min_constraints(self, labels: list[str]):
        if 'start_at_chapter' not in labels or 'end_at_chapter' not in labels:
            return
        start_col = labels.index('start_at_chapter')
        end_col = labels.index('end_at_chapter')
        bdmv_col = labels.index('bdmv_index')
        selected_mpls = self.get_selected_mpls_no_ext()
        folder_to_bdmv_index: dict[str, int] = {}
        bdmv_to_mpls: dict[int, str] = {}
        for folder, mpls_no_ext in selected_mpls:
            if folder not in folder_to_bdmv_index:
                folder_to_bdmv_index[folder] = len(folder_to_bdmv_index) + 1
            bdmv_to_mpls[folder_to_bdmv_index[folder]] = mpls_no_ext
        for r in range(self.table2.rowCount()):
            s = self.table2.cellWidget(r, start_col)
            e = self.table2.cellWidget(r, end_col)
            if isinstance(s, QComboBox) and isinstance(e, QComboBox):
                start_v = int(s.currentData() or (s.currentIndex() + 1))
                self._apply_end_combo_min_constraint(e, start_v + 1)
                b_item = self.table2.item(r, bdmv_col)
                try:
                    bdmv_index = int(b_item.text().strip()) if b_item and b_item.text() else 0
                except Exception:
                    bdmv_index = 0
                mpls_no_ext = bdmv_to_mpls.get(bdmv_index, '')
                checked_states: list[bool] = []
                if mpls_no_ext:
                    checked_states = list(self._chapter_checkbox_states.get(mpls_no_ext + '.mpls', []))
                if checked_states:
                    model = e.model()
                    ending_value = int(e.itemData(e.count() - 1) or e.count())
                    last_chapter_checked = bool(checked_states[-1]) if checked_states else True
                    for i in range(e.count()):
                        v = int(e.itemData(i) or (i + 1))
                        item = model.item(i) if hasattr(model, 'item') else None
                        if item is None:
                            continue
                        if v == ending_value:
                            item.setEnabled(bool(last_chapter_checked))
                        elif 1 <= v <= len(checked_states):
                            item.setEnabled(item.isEnabled() and bool(checked_states[v - 1]))

    def on_configuration(self, configuration: dict[int, dict[str, int | str]], update_sp_table: bool = True):
        try:
            if not configuration:
                print(translate_text('Configuration is empty, skipping update'))
                return
            function_id = self.get_selected_function_id()
            if function_id in (3, 4):
                self._last_configuration_34 = configuration
                old_sorting = self.table2.isSortingEnabled()
                self.table2.setSortingEnabled(False)
                labels = ENCODE_LABELS if function_id == 4 else REMUX_LABELS
                duration_col = labels.index('ep_duration')
                bdmv_col = labels.index('bdmv_index')
                start_col = labels.index('start_at_chapter')
                end_col = labels.index('end_at_chapter')
                m2ts_col = labels.index('m2ts_file')
                language_col = labels.index('language')
                output_col = labels.index('output_name')
                play_col = labels.index('play') if 'play' in labels else -1
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
                        chapter_combo.addItem('chapter 01', 1)
                        chapter_combo.setCurrentIndex(0)
                        chapter_combo._prev_start_value = int(chapter_combo.currentData() or 1)
                        chapter_combo.setEnabled(False)
                        self.table2.setCellWidget(row_i, start_col, chapter_combo)
                        end_combo = self._build_end_chapter_combo(1, False, 1, 2)
                        end_combo.currentIndexChanged.connect(partial(self._on_end_chapter_combo_changed, row_i, labels))
                        self.table2.setCellWidget(row_i, end_col, end_combo)

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
                        if play_col >= 0:
                            btn_play = QToolButton(self.table2)
                            btn_play.setText(self.t('play'))
                            btn_play.clicked.connect(partial(self.on_play_table2_disc_row, row_i, bdmv_col, m2ts_col))
                            self.table2.setCellWidget(row_i, play_col, btn_play)
                else:
                    self.table2.setRowCount(len(configuration))
                    for sub_index, con in configuration.items():
                        self.table2.setItem(sub_index, bdmv_col, QTableWidgetItem(str(con['bdmv_index'])))
                        chapter_combo = QComboBox()
                        duration = 0
                        chapter = Chapter(str(con['selected_mpls']) + '.mpls')
                        rows = sum(map(len, chapter.mark_info.values()))
                        j1 = int(con.get('chapter_index') or 1)
                        next_con = configuration.get(sub_index + 1)
                        if con.get('end_at_chapter'):
                            j2 = int(con.get('end_at_chapter') or 0)
                        elif next_con and next_con.get('folder') == con.get('folder') and next_con.get('selected_mpls') == con.get('selected_mpls'):
                            j2 = int(next_con.get('chapter_index') or 0)
                        else:
                            j2 = rows + 1
                        # Clamp bounds to avoid invalid chapter indices (e.g. rows+1 start).
                        j1 = max(1, min(j1, rows + 1))
                        j2 = max(j1 + 1, min(j2, rows + 1))
                        index_to_m2ts, index_to_offset = get_index_to_m2ts_and_offset(chapter)
                        m2ts_files = sorted(list(set([index_to_m2ts[i] for i in range(j1, j2) if i in index_to_m2ts])))
                        has_beginning = False
                        try:
                            has_beginning = bool(float(index_to_offset.get(1, 0.0) or 0.0) > 0.001)
                        except Exception:
                            has_beginning = False
                        options = self._build_start_chapter_options(rows, has_beginning)
                        for v, txt in options:
                            chapter_combo.addItem(txt, v)
                        selected_idx = 0
                        for i_opt in range(chapter_combo.count()):
                            if int(chapter_combo.itemData(i_opt) or 0) == int(con['chapter_index']):
                                selected_idx = i_opt
                                break
                        chapter_combo.setCurrentIndex(selected_idx)
                        chapter_combo._prev_start_value = int(chapter_combo.currentData() or (chapter_combo.currentIndex() + 1))
                        chapter_combo.currentIndexChanged.connect(partial(self.on_chapter_combo, sub_index))
                        start_off = float(index_to_offset.get(j1, chapter.get_total_time()))
                        end_off = float(index_to_offset.get(j2, chapter.get_total_time()))
                        if end_off < start_off:
                            end_off = start_off
                        duration = end_off - start_off
                        duration = get_time_str(duration)
                        self.table2.setCellWidget(sub_index, start_col, chapter_combo)
                        end_combo = self._build_end_chapter_combo(rows, has_beginning, int(j1), int(j2))
                        end_combo.currentIndexChanged.connect(partial(self._on_end_chapter_combo_changed, sub_index, labels))
                        self.table2.setCellWidget(sub_index, end_col, end_combo)
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
                        if play_col >= 0:
                            btn_play = QToolButton(self.table2)
                            btn_play.setText(self.t('play'))
                            btn_play.clicked.connect(partial(self.on_play_table2_disc_row, sub_index, bdmv_col, m2ts_col))
                            self.table2.setCellWidget(sub_index, play_col, btn_play)
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
                self._sync_end_chapter_min_constraints(labels)
                self._apply_start_chapter_constraints(labels)
                self._scroll_table_h_to_right(self.table2)
                if function_id in (3, 4):
                    if update_sp_table:
                        self.refresh_sp_table(configuration)
                    try:
                        self._refresh_table1_remux_cmds()
                    except Exception:
                        pass
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
            self._show_error_dialog(traceback.format_exc())
            if hasattr(self, 'table3'):
                self.table3.setRowCount(0)
            return

    def on_chapter_combo(self, subtitle_index: int):
        if self.get_selected_function_id() in (3, 4):
            labels = ENCODE_LABELS if self.get_selected_function_id() == 4 else REMUX_LABELS
            try:
                row = int(subtitle_index)
            except Exception:
                row = -1
            if 0 <= row < self.table2.rowCount():
                start_col = labels.index('start_at_chapter')
                end_col = labels.index('end_at_chapter')
                bdmv_col = labels.index('bdmv_index')
                start_combo = self.table2.cellWidget(row, start_col)
                if isinstance(start_combo, QComboBox):
                    new_start = int(start_combo.currentData() or (start_combo.currentIndex() + 1))
                    old_start = int(getattr(start_combo, '_prev_start_value', new_start))
                    if (new_start > old_start) and (row > 0):
                        prev_end_combo = self.table2.cellWidget(row - 1, end_col)
                        prev_end = int(prev_end_combo.currentData() or (prev_end_combo.currentIndex() + 1)) if isinstance(prev_end_combo, QComboBox) else 0
                        b_cur = self.table2.item(row, bdmv_col)
                        b_prev = self.table2.item(row - 1, bdmv_col)
                        try:
                            bdmv_cur = int(b_cur.text().strip()) if b_cur and b_cur.text() else 0
                        except Exception:
                            bdmv_cur = 0
                        try:
                            bdmv_prev = int(b_prev.text().strip()) if b_prev and b_prev.text() else 0
                        except Exception:
                            bdmv_prev = 0
                        if (bdmv_cur == bdmv_prev) and prev_end > 0 and new_start > prev_end:
                            selected_mpls = self.get_selected_mpls_no_ext()
                            folder_to_bdmv_index: dict[str, int] = {}
                            bdmv_to_mpls: dict[int, str] = {}
                            for folder, mpls_no_ext in selected_mpls:
                                if folder not in folder_to_bdmv_index:
                                    folder_to_bdmv_index[folder] = len(folder_to_bdmv_index) + 1
                                bdmv_to_mpls[folder_to_bdmv_index[folder]] = mpls_no_ext
                            mpls_no_ext = bdmv_to_mpls.get(bdmv_cur, '')
                            self._set_segment_states_for_range(mpls_no_ext, prev_end, new_start - 1, False)
                    start_combo._prev_start_value = new_start
            self._sync_end_chapter_min_constraints(labels)
            self._pending_chapter_combo_index = int(subtitle_index)
            if hasattr(self, '_chapter_combo_debounce') and isinstance(self._chapter_combo_debounce, QTimer):
                self._chapter_combo_debounce.start()
            else:
                self._run_chapter_combo_update()
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

    def _run_chapter_combo_update(self):
        if self.get_selected_function_id() not in (3, 4):
            return
        try:
            configuration = self._generate_configuration_from_ui_inputs()
            # start/end chapter edits (e.g. last episode end_at_chapter) change episode bounds; keep SP table in sync.
            self.on_configuration(configuration, update_sp_table=True)
        except Exception:
            self._show_error_dialog(traceback.format_exc())

    def _chapter_node_data(self, mpls_path_no_ext: str) -> dict[str, object]:
        chapter = Chapter(mpls_path_no_ext + '.mpls')
        index_to_m2ts, index_to_offset = get_index_to_m2ts_and_offset(chapter)
        rows = sum(map(len, chapter.mark_info.values()))
        offsets: dict[int, float] = {}
        for i in range(1, rows + 1):
            offsets[i] = float(index_to_offset.get(i, 0.0))
        offsets[rows + 1] = float(chapter.get_total_time())
        m2ts_map: dict[int, str] = {}
        for i in range(1, rows + 1):
            m2ts_map[i] = str(index_to_m2ts.get(i) or '')
        has_beginning = bool(offsets.get(1, 0.0) > 0.001)
        return {'rows': rows, 'offsets': offsets, 'm2ts': m2ts_map, 'has_beginning': has_beginning}

    def _collect_config_inputs(self) -> dict[str, object]:
        labels = ENCODE_LABELS if self.get_selected_function_id() == 4 else REMUX_LABELS
        start_col = labels.index('start_at_chapter')
        end_col = labels.index('end_at_chapter')
        bdmv_col = labels.index('bdmv_index')
        selected_mpls = self.get_selected_mpls_no_ext()
        folder_to_bdmv_index: dict[str, int] = {}
        bdmv_to_mpls: dict[int, str] = {}
        for folder, mpls_no_ext in selected_mpls:
            if folder not in folder_to_bdmv_index:
                folder_to_bdmv_index[folder] = len(folder_to_bdmv_index) + 1
            bdmv_to_mpls[folder_to_bdmv_index[folder]] = mpls_no_ext
        start_values: dict[int, int] = {}
        end_values: dict[int, int] = {}
        row_bdmv: dict[int, int] = {}
        for r in range(self.table2.rowCount()):
            b_item = self.table2.item(r, bdmv_col)
            try:
                bdmv = int(b_item.text().strip()) if b_item and b_item.text() else 0
            except Exception:
                bdmv = 0
            row_bdmv[r] = bdmv
            s = self.table2.cellWidget(r, start_col)
            e = self.table2.cellWidget(r, end_col)
            start_values[r] = int(s.currentData() or (s.currentIndex() + 1)) if isinstance(s, QComboBox) else 1
            if isinstance(e, QComboBox):
                end_values[r] = int(e.currentData() or (e.currentIndex() + 1))
            else:
                it = self.table2.item(r, end_col)
                end_values[r] = int(it.data(Qt.ItemDataRole.UserRole + 1) or 0) if it else 0
        segment_states: dict[str, list[bool]] = {}
        for _, mpls_no_ext in selected_mpls:
            mpls_path = mpls_no_ext + '.mpls'
            nd = self._chapter_node_data(mpls_no_ext)
            rows = int(nd['rows'])
            saved = list(self._chapter_checkbox_states.get(mpls_path, []))
            if len(saved) < rows:
                saved += [True] * (rows - len(saved))
            segment_states[mpls_no_ext] = saved[:rows]
        return {
            'selected_mpls': selected_mpls,
            'bdmv_to_mpls': bdmv_to_mpls,
            'row_bdmv': row_bdmv,
            'start': start_values,
            'end': end_values,
            'segments': segment_states,
        }

    def _diff_config_inputs(self, prev: dict[str, object], cur: dict[str, object]) -> tuple[str, int]:
        p_seg = prev.get('segments', {}) if isinstance(prev, dict) else {}
        c_seg = cur.get('segments', {})
        if p_seg != c_seg:
            return 'segments', 0
        p_start = prev.get('start', {}) if isinstance(prev, dict) else {}
        c_start = cur.get('start', {})
        changed_rows = sorted([r for r in c_start.keys() if int(p_start.get(r, c_start[r])) != int(c_start[r])])
        if changed_rows:
            return 'start', int(changed_rows[0])
        p_end = prev.get('end', {}) if isinstance(prev, dict) else {}
        c_end = cur.get('end', {})
        changed_rows = sorted([r for r in c_end.keys() if int(p_end.get(r, c_end[r])) != int(c_end[r])])
        if changed_rows:
            return 'end', int(changed_rows[0])
        return 'none', -1

    def _closest_endpoint(self, start_idx: int, target_sec: float, rows: int, offsets: dict[int, float], m2ts: dict[int, str], checked: list[bool]) -> int:
        candidates = [i for i in range(start_idx + 1, rows + 2) if (i == rows + 1) or checked[i - 1]]
        if not candidates:
            return min(rows + 1, start_idx + 1)
        chapter_end = min(candidates, key=lambda e: abs((offsets.get(e, offsets[rows + 1]) - offsets.get(start_idx, 0.0)) - target_sec))
        file_candidates = []
        for e in candidates:
            if e == rows + 1:
                file_candidates.append(e)
                continue
            prev_f = m2ts.get(e - 1, '')
            cur_f = m2ts.get(e, '')
            if e == 1 or cur_f != prev_f:
                file_candidates.append(e)
        if not file_candidates:
            return chapter_end
        file_end = min(file_candidates, key=lambda e: abs((offsets.get(e, offsets[rows + 1]) - offsets.get(start_idx, 0.0)) - target_sec))
        diff_file = (offsets.get(file_end, offsets[rows + 1]) - offsets.get(start_idx, 0.0)) - target_sec
        if (-target_sec * 0.25) <= diff_file <= (target_sec * 0.5):
            return file_end
        diff_ch = (offsets.get(chapter_end, offsets[rows + 1]) - offsets.get(start_idx, 0.0)) - target_sec
        score_file = diff_file if diff_file >= 0 else (-2.0 * diff_file)
        score_ch = diff_ch if diff_ch >= 0 else (-2.0 * diff_ch)
        return file_end if score_file <= score_ch else chapter_end

    def _generate_configuration_from_ui_inputs(self) -> dict[int, dict[str, int | str]]:
        inputs = self._collect_config_inputs()
        mode, changed_row = self._diff_config_inputs(getattr(self, '_last_config_inputs', {}), inputs)
        self._last_config_inputs = inputs
        selected_mpls = list(inputs.get('selected_mpls') or [])
        if not selected_mpls:
            return {}
        bdmv_to_mpls = dict(inputs.get('bdmv_to_mpls') or {})
        row_bdmv = dict(inputs.get('row_bdmv') or {})
        starts = dict(inputs.get('start') or {})
        ends = dict(inputs.get('end') or {})
        segments = dict(inputs.get('segments') or {})
        prev_conf = dict(getattr(self, '_last_configuration_34', {}) or {})
        approx_end_time = float(getattr(self, 'approx_episode_duration_seconds', DEFAULT_APPROX_EPISODE_DURATION_SECONDS)
                                or DEFAULT_APPROX_EPISODE_DURATION_SECONDS)
        gui_sub_files: list[str] = []
        try:
            for i in range(self.table2.rowCount()):
                it = self.table2.item(i, 0)
                p = it.text().strip() if it and it.text() else ''
                if p and (p.endswith('.ass') or p.endswith('.ssa') or p.endswith('.srt') or p.endswith('.sup')):
                    gui_sub_files.append(p)
        except Exception:
            gui_sub_files = []
        if gui_sub_files:
            missing = [p for p in gui_sub_files if p and p not in self._subtitle_cache]
            for p in missing:
                try:
                    self._subtitle_cache[p] = Subtitle(p)
                except Exception:
                    pass
            sub_max_end = [self._subtitle_cache[p].max_end_time() if p in self._subtitle_cache else approx_end_time for p in gui_sub_files]
        else:
            sub_max_end = []
        conf: dict[int, dict[str, int | str]] = {}
        rows = self.table2.rowCount()
        for r in range(rows):
            bdmv_index = int(row_bdmv.get(r, 0) or 0)
            mpls_no_ext = bdmv_to_mpls.get(bdmv_index, '')
            if not mpls_no_ext:
                continue
            node = self._chapter_node_data(mpls_no_ext)
            total_rows = int(node['rows'])
            offsets = dict(node['offsets'])
            m2ts = dict(node['m2ts'])
            checked = list(segments.get(mpls_no_ext, [True] * total_rows))
            if len(checked) < total_rows:
                checked += [True] * (total_rows - len(checked))
            prev_same_mpls = bool((r - 1) in conf and str(conf[r - 1].get('selected_mpls') or '') == mpls_no_ext)
            if r < changed_row and mode in ('start', 'end') and r in prev_conf:
                conf[r] = dict(prev_conf[r])
                conf[r]['chapter_segments_fully_checked'] = all(checked[:total_rows])
                continue
            start_idx = int(starts.get(r, 1) or 1)
            start_idx = max(1, min(total_rows, start_idx))
            while start_idx <= total_rows and not checked[start_idx - 1]:
                start_idx += 1
            if start_idx > total_rows:
                start_idx = total_rows
            if mode == 'segments':
                first_checked = next((i for i in range(1, total_rows + 1) if checked[i - 1]), 1)
                if not prev_same_mpls:
                    start_idx = first_checked
                elif prev_same_mpls:
                    start_idx = int(conf[r - 1].get('end_at_chapter') or start_idx)
                    if start_idx <= total_rows and not checked[start_idx - 1]:
                        start_idx = next((i for i in range(start_idx, total_rows + 1) if checked[i - 1]), first_checked)
            if mode == 'end' and r > changed_row and changed_row in conf:
                changed_bdmv = int(row_bdmv.get(changed_row, 0) or 0)
                changed_mpls = bdmv_to_mpls.get(changed_bdmv, '')
                if changed_mpls != mpls_no_ext:
                    # End change in another mpls should not affect this row.
                    if r in prev_conf:
                        conf[r] = dict(prev_conf[r])
                        conf[r]['chapter_segments_fully_checked'] = all(checked[:total_rows])
                        continue
                prev_end_new = int(conf[changed_row].get('end_at_chapter') or start_idx)
                prev_end_old = int(prev_conf.get(changed_row, {}).get('end_at_chapter') or prev_end_new)
                if prev_end_new <= prev_end_old:
                    if r in prev_conf:
                        conf[r] = dict(prev_conf[r])
                        conf[r]['chapter_segments_fully_checked'] = all(checked[:total_rows])
                        continue
                start_idx = prev_end_new
            target_sec = float(sub_max_end[r] if r < len(sub_max_end) else approx_end_time)
            chosen_end = int(ends.get(r, 0) or 0)
            if chosen_end <= start_idx:
                chosen_end = self._closest_endpoint(start_idx, target_sec, total_rows, offsets, m2ts, checked)
            if chosen_end > total_rows + 1:
                chosen_end = total_rows + 1
            # If unchecked region starts before chosen end, cut here.
            for k in range(start_idx, min(chosen_end, total_rows + 1)):
                if k <= total_rows and not checked[k - 1]:
                    chosen_end = k
                    break
            dur = max(0.0, float(offsets.get(chosen_end, offsets.get(total_rows + 1, 0.0))) - float(offsets.get(start_idx, 0.0)))
            folder = selected_mpls[min(max(bdmv_index - 1, 0), len(selected_mpls) - 1)][0] if selected_mpls else ''
            disc_output_name = ''
            try:
                prev_row_conf = prev_conf.get(r, {}) if isinstance(prev_conf, dict) else {}
                if str(prev_row_conf.get('selected_mpls') or '') == mpls_no_ext:
                    disc_output_name = str(prev_row_conf.get('disc_output_name') or '').strip()
                if not disc_output_name and isinstance(prev_conf, dict):
                    for _, pc in prev_conf.items():
                        if str(pc.get('selected_mpls') or '') == mpls_no_ext:
                            disc_output_name = str(pc.get('disc_output_name') or '').strip()
                            if disc_output_name:
                                break
            except Exception:
                disc_output_name = ''
            if not disc_output_name:
                disc_output_name = self._resolve_output_name_from_mpls(mpls_no_ext)
            conf[r] = {
                'folder': folder,
                'selected_mpls': mpls_no_ext,
                'bdmv_index': bdmv_index,
                'chapter_index': int(start_idx),
                'start_at_chapter': int(start_idx),
                'end_at_chapter': int(chosen_end),
                'offset': get_time_str(float(offsets.get(start_idx, 0.0))),
                'ep_duration': get_time_str(dur),
                'disc_output_name': disc_output_name,
                'chapter_segments_fully_checked': all(checked[:total_rows]),
            }
        global CONFIGURATION
        CONFIGURATION = conf
        return conf

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
            # Generate subtitles only when no subtitle file exists.
            mpls_name = mpls_path[:-5]
            has_subtitle = (os.path.exists(mpls_name + '.ass') or 
                          os.path.exists(mpls_name + '.srt') or
                          os.path.exists(mpls_name + '.ssa'))
            if not has_subtitle:
                success = self.generate_subtitle(silent_mode=True)
                if success:
                    # Re-check subtitle existence after generation.
                    has_subtitle = (os.path.exists(mpls_name + '.ass') or 
                                  os.path.exists(mpls_name + '.srt') or
                                  os.path.exists(mpls_name + '.ssa'))
            if not has_subtitle:
                # Still allow playback even if subtitle generation failed.
                QMessageBox.information(self, "提示", "字幕文件不存在，将播放无字幕版本")
        elif is_preview:
            # Check whether subtitle file exists.
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
                # Enable Blu-ray support in Linux mpv build by running in source directory:
                # echo "--enable-libbluray" > ffmpeg_options
                # and
                # echo "-Dlibbluray=enabled" > mpv_options
                if 'mpv' in desktop_file:
                    mpv_play_mpls(mpls_path, 'mpv')
            except:
                pass
            subprocess.run(['xdg-open', mpls_path])

    def _is_mpls_currently_main(self, mpls_path: str) -> bool:
        """True if this playlist file is the checked main MPLS for its disc row in table1."""
        try:
            norm_target = os.path.normpath(mpls_path)
        except Exception:
            return False
        if not norm_target.lower().endswith('.mpls'):
            norm_target = norm_target + '.mpls'
        for bdmv_index in range(self.table1.rowCount()):
            root_item = self.table1.item(bdmv_index, 0)
            if not root_item or not str(root_item.text() or '').strip():
                continue
            root = os.path.normpath(root_item.text().strip())
            info = self.table1.cellWidget(bdmv_index, 2)
            if not isinstance(info, QTableWidget):
                continue
            for mpls_i in range(info.rowCount()):
                it0 = info.item(mpls_i, 0)
                if not it0 or not str(it0.text() or '').strip():
                    continue
                row_mpls = os.path.normpath(os.path.join(root, 'BDMV', 'PLAYLIST', it0.text().strip()))
                if row_mpls != norm_target:
                    continue
                main_btn = info.cellWidget(mpls_i, 3)
                return isinstance(main_btn, QToolButton) and main_btn.isChecked()
        return False

    def _resync_episode_tables_from_main_mpls_selection(self) -> None:
        """After main MPLS toggles, refresh table2 / table3 so deselected discs disappear."""
        if self.get_selected_function_id() not in (3, 4) or self._is_movie_mode():
            return
        raw = (self.subtitle_folder_path.text() or '').strip()
        sub_folder = self._normalize_path_input(raw) if raw else ''
        if sub_folder and os.path.isdir(sub_folder):
            self._pending_subtitle_folder = sub_folder
            self._subtitle_scan_debounce.stop()
            self._subtitle_scan_debounce.start()
            return
        try:
            selected = self.get_selected_mpls_no_ext()
            bs = BluraySubtitle(
                self.bdmv_folder_path.text(),
                [],
                self.checkbox1.isChecked(),
                None,
                approx_episode_duration_seconds=self._get_approx_episode_duration_seconds(),
            )
            if not selected:
                self.table2.setRowCount(0)
                self.refresh_sp_table({})
                return
            configuration = bs.generate_configuration_from_selected_mpls(selected)
            if configuration:
                self.on_configuration(configuration, update_sp_table=True)
            else:
                self.table2.setRowCount(0)
                self.refresh_sp_table({})
        except Exception:
            traceback.print_exc()

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
                            if self.get_selected_function_id() in (3, 4) and info.columnCount() > 5:
                                btn_tracks = QToolButton()
                                btn_tracks.setText(self.t('编辑轨道'))
                                btn_tracks.clicked.connect(partial(self.on_edit_tracks_from_mpls, mpls_path))
                                info.setCellWidget(mpls_index, 5, btn_tracks)
                            for mpls_index_1 in range(info.rowCount()):
                                if not mpls_path.endswith(info.item(mpls_index_1, 0).text()):
                                    if info.cellWidget(mpls_index_1, 3).isChecked():
                                        info.cellWidget(mpls_index_1, 3).setChecked(False)
                                        other_play_btn = info.cellWidget(mpls_index_1, 4)
                                        if other_play_btn:
                                            other_play_btn.setProperty('action', 'play')
                                            other_play_btn.setText(self.t('play'))
                                        if self.get_selected_function_id() in (3, 4) and info.columnCount() > 5:
                                            info.setCellWidget(mpls_index_1, 5, None)
                                            info.setItem(mpls_index_1, 5, QTableWidgetItem(''))
                        else:
                            play_btn = info.cellWidget(mpls_index, 4)
                            if play_btn:
                                play_btn.setProperty('action', 'play')
                                play_btn.setText(self.t('play'))
                            if self.get_selected_function_id() in (3, 4) and info.columnCount() > 5:
                                info.setCellWidget(mpls_index, 5, None)
                                info.setItem(mpls_index, 5, QTableWidgetItem(''))
        if self.get_selected_function_id() in (3, 4):
            self._refresh_track_selection_config_for_selected_main()
            try:
                self._refresh_table1_remux_cmds()
            except Exception:
                pass
        if self.get_selected_function_id() in (3, 4) and self._is_movie_mode():
            self._refresh_movie_table2()
        else:
            self._resync_episode_tables_from_main_mpls_selection()

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

    def _get_root_for_bdmv_index(self, bdmv_index: int) -> str:
        try:
            idx = int(bdmv_index) - 1
        except Exception:
            return ''
        if idx < 0 or idx >= self.table1.rowCount():
            return ''
        it = self.table1.item(idx, 0)
        return it.text().strip() if it and it.text() else ''

    def _get_first_m2ts_for_mpls(self, mpls_path: str) -> str:
        try:
            chapter = Chapter(mpls_path)
            index_to_m2ts, _ = get_index_to_m2ts_and_offset(chapter)
            if not index_to_m2ts:
                return ''
            first_key = sorted(index_to_m2ts.keys())[0]
            m2ts_name = index_to_m2ts.get(first_key) or ''
            playlist_dir = os.path.dirname(mpls_path)
            bdmv_dir = os.path.dirname(playlist_dir)
            stream_dir = os.path.join(bdmv_dir, 'STREAM')
            return os.path.normpath(os.path.join(stream_dir, str(m2ts_name)))
        except Exception:
            return ''

    def _read_ffprobe_streams(self, media_path: str) -> list[dict[str, object]]:
        if not media_path or not os.path.exists(media_path):
            return []
        exe = FFPROBE_PATH if FFPROBE_PATH else 'ffprobe'
        try:
            p = subprocess.run(
                [exe, "-v", "error", "-show_streams", "-of", "json", media_path],
                capture_output=True,
                text=True,
                shell=False
            )
        except Exception:
            return []
        if p.returncode != 0:
            return []
        try:
            data = json.loads(p.stdout or "{}")
            streams = data.get("streams") or []
            return streams if isinstance(streams, list) else []
        except Exception:
            return []

    def _codec_name_from_codec_id(self, codec_id: str) -> str:
        cid = str(codec_id or '').strip()
        if cid.startswith('A_DTS'):
            return 'dts'
        if cid in ('A_TRUEHD', 'A_MLP'):
            return 'truehd'
        if cid in ('A_PCM/INT/LIT', 'A_PCM/INT/BIG'):
            return 'lpcm'
        if cid == 'A_AC3':
            return 'ac3'
        if cid == 'A_EAC3':
            return 'eac3'
        if cid == 'A_FLAC':
            return 'flac'
        if cid.startswith('A_MPEG/L3'):
            return 'mp3'
        if cid.startswith('A_MPEG/L2'):
            return 'mp2'
        if cid.startswith('A_AAC'):
            return 'aac'
        return cid.lower() or ''

    def _mkvextract_ext_from_codec_id(self, codec_id: str) -> str:
        cid = str(codec_id or '').strip()
        if cid.startswith('A_AAC') or cid == 'A_AAC':
            return '.aac'
        if cid in ('A_AC3', 'A_EAC3'):
            return '.ac3'
        if cid == 'A_ALAC':
            return '.caf'
        if cid == 'A_DTS':
            return '.dts'
        if cid == 'A_FLAC':
            return '.flac'
        if cid == 'A_MPEG/L2':
            return '.mp2'
        if cid == 'A_MPEG/L3':
            return '.mp3'
        if cid == 'A_OPUS':
            return '.opus'
        if cid in ('A_PCM/INT/LIT', 'A_PCM/INT/BIG'):
            return '.wav'
        if cid in ('A_TRUEHD', 'A_MLP'):
            return '.thd'
        if cid == 'A_TTA1':
            return '.tta'
        if cid == 'A_VORBIS':
            return '.ogg'
        if cid == 'A_WAVPACK4':
            return '.wv'
        if cid == 'S_HDMV/PGS':
            return '.sup'
        if cid == 'S_HDMV/TEXTST':
            return '.textst'
        if cid in ('S_TEXT/SSA', 'S_TEXT/ASS', 'S_SSA', 'S_ASS'):
            return '.ass'
        if cid in ('S_TEXT/UTF8', 'S_TEXT/ASCII'):
            return '.srt'
        if cid == 'S_VOBSUB':
            return '.sub'
        if cid == 'S_TEXT/USF':
            return '.usf'
        if cid == 'S_TEXT/WEBVTT':
            return '.vtt'
        if cid in ('V_MPEG1', 'V_MPEG2'):
            return '.mpg'
        if cid == 'V_MPEG4/ISO/AVC':
            return '.h264'
        if cid == 'V_MPEG4/ISO/HEVC':
            return '.h265'
        if cid == 'V_MS/VFW/FOURCC':
            return '.avi'
        if cid.startswith('V_REAL/'):
            return '.rm'
        if cid == 'V_THEORA':
            return '.ogg'
        if cid in ('V_VP8', 'V_VP9'):
            return '.ivf'
        return '.bin'

    def _read_mkvinfo_tracks(self, mkv_path: str) -> list[dict[str, object]]:
        if not mkv_path or not os.path.exists(mkv_path):
            return []
        try:
            find_mkvtoolinx()
        except Exception:
            pass
        if not MKV_INFO_PATH:
            return []
        try:
            ui_lang = 'en' if sys.platform == 'win32' else 'en_US'
            p = subprocess.run(
                [MKV_INFO_PATH, mkv_path, "--ui-language", ui_lang],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='ignore',
                shell=False
            )
        except Exception:
            return []
        stdout = p.stdout or ''
        tracks: list[dict[str, object]] = []
        cur: Optional[dict[str, object]] = None

        def flush():
            nonlocal cur
            if not cur:
                return
            track_id = cur.get('track_id')
            if track_id is None:
                cur = None
                return
            lang = cur.get('language') or cur.get('lang') or ''
            bcp = cur.get('bcp47') or ''
            if not lang and bcp:
                language = pycountry.languages.get(alpha_2=str(bcp).split('-')[0])
                if language is None:
                    language = pycountry.languages.get(alpha_3=str(bcp).split('-')[0])
                if language:
                    lang = getattr(language, "bibliographic", getattr(language, "alpha_3", None))
            cur['language'] = str(lang or 'und')
            cur['lang'] = cur['language']
            t = str(cur.get('track_type') or '').strip().lower()
            if t == 'audio':
                cur['codec_type'] = 'audio'
            elif t in ('subtitles', 'subtitle'):
                cur['codec_type'] = 'subtitle'
            else:
                cur['codec_type'] = t or 'und'
            cur['codec_id'] = str(cur.get('codec_id') or '')
            cur['codec_name'] = self._codec_name_from_codec_id(str(cur.get('codec_id') or ''))
            cur['index'] = str(track_id)
            cur['track_number'] = int(track_id)
            tracks.append(cur)
            cur = None

        for raw in stdout.splitlines():
            line = raw.strip()
            if line in ('|+ Track', '| + Track', '|  + Track'):
                flush()
                cur = {}
                continue
            if cur is None:
                continue
            if line.startswith('|  + Track number: ') or line.startswith('| + Track number: ') or line.startswith('|+ Track number: '):
                nums = re.findall(r'\d+', line)
                if len(nums) >= 2:
                    cur['track_number_1based'] = int(nums[0])
                    cur['track_id'] = int(nums[1])
                elif len(nums) == 1:
                    cur['track_number_1based'] = int(nums[0])
                    cur['track_id'] = int(nums[0]) - 1
                continue
            if line.startswith('|  + Track UID: ') or line.startswith('| + Track UID: ') or line.startswith('|+ Track UID: '):
                v = re.findall(r'\d+', line)
                cur['track_uid'] = v[0] if v else ''
                continue
            if line.startswith('|  + Track type: ') or line.startswith('| + Track type: ') or line.startswith('|+ Track type: '):
                cur['track_type'] = line.split(':', 1)[1].strip()
                continue
            if line.startswith('|  + Language (IETF BCP 47): ') or line.startswith('| + Language (IETF BCP 47): ') or line.startswith('|+ Language (IETF BCP 47): '):
                cur['bcp47'] = line.split(':', 1)[1].strip()
                continue
            if (line.startswith('|  + Language: ') or line.startswith('| + Language: ') or line.startswith('|+ Language: ')) and ('Language (IETF BCP 47):' not in line):
                cur['language'] = line.split(':', 1)[1].strip()
                continue
            if line.startswith('|  + Codec ID: ') or line.startswith('| + Codec ID: ') or line.startswith('|+ Codec ID: '):
                cur['codec_id'] = line.split(':', 1)[1].strip()
                continue
            if line.startswith('|  + Default duration: ') or line.startswith('| + Default duration: ') or line.startswith('|+ Default duration: '):
                cur['default_duration'] = line.split(':', 1)[1].strip()
                continue
            if line.startswith('|   + Sampling frequency: ') or line.startswith('|  + Sampling frequency: ') or line.startswith('| + Sampling frequency: '):
                v = re.findall(r'[\d.]+', line)
                cur['sampling_frequency'] = v[0] if v else ''
                continue
            if line.startswith('|   + Channels: ') or line.startswith('|  + Channels: ') or line.startswith('| + Channels: '):
                v = re.findall(r'\d+', line)
                cur['channels'] = v[0] if v else ''
                continue
            if line.startswith('|   + Bit depth: ') or line.startswith('|  + Bit depth: ') or line.startswith('| + Bit depth: '):
                v = re.findall(r'\d+', line)
                cur['bit_depth'] = v[0] if v else ''
                continue
            if line.startswith('|   + Pixel width: ') or line.startswith('|  + Pixel width: ') or line.startswith('| + Pixel width: '):
                v = re.findall(r'\d+', line)
                cur['pixel_width'] = v[0] if v else ''
                continue
            if line.startswith('|   + Pixel height: ') or line.startswith('|  + Pixel height: ') or line.startswith('| + Pixel height: '):
                v = re.findall(r'\d+', line)
                cur['pixel_height'] = v[0] if v else ''
                continue

        flush()
        return tracks

    def _extract_track_to_temp_and_open(self, mkv_path: str, track_id: int, codec_id: str):
        try:
            find_mkvtoolinx()
        except Exception:
            pass
        if not MKV_EXTRACT_PATH:
            return
        tmp_dir = tempfile.mkdtemp(prefix='BluraySubtitle_extract_')
        ext = self._mkvextract_ext_from_codec_id(codec_id)
        out_path = os.path.join(tmp_dir, f'track{track_id}{ext}')
        cmd = f'"{MKV_EXTRACT_PATH}" {mkvtoolnix_ui_language_arg()} "{mkv_path}" tracks {track_id}:"{out_path}"'
        subprocess.Popen(cmd, shell=True).wait()
        try:
            self.open_folder_path(tmp_dir)
        except Exception:
            pass

    def _show_tracks_dialog(
        self,
        title: str,
        streams: list[dict[str, object]],
        selected_indexes: Optional[set[str]] = None,
        pid_lang: Optional[dict[int, str]] = None,
        source_mkv: Optional[str] = None
    ) -> Optional[set[str]]:
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        layout = QVBoxLayout()
        dlg.setLayout(layout)
        table = QTableWidget(dlg)
        self._set_compact_table(table, row_height=22, header_height=22)
        is_mkvinfo = any(('codec_id' in (s or {})) or ('track_id' in (s or {})) for s in (streams or []))
        if is_mkvinfo:
            cols = ['track_number', 'select', 'track_uid', 'track_type', 'language', 'codec_id', 'extract']
        else:
            cols = ['index', 'select', 'id', 'language', 'codec_type', 'codec_name', 'start_time']
        table.setColumnCount(len(cols))
        self._set_table_headers(table, cols)
        table.setRowCount(len(streams))
        selected = selected_indexes or set()
        pid_to_lang = pid_lang or {}
        original_languages: list[str] = []
        for r, s in enumerate(streams):
            idx_text = str(s.get('index', ''))
            codec_type = str(s.get('codec_type') or '')
            select_btn = QToolButton(table)
            select_btn.setCheckable(True)
            is_selected = (codec_type == 'video') or (idx_text in selected)
            select_btn.setChecked(is_selected)
            if codec_type == 'video':
                select_btn.setEnabled(False)
            table.setCellWidget(r, cols.index('select'), select_btn)
            for c, key in enumerate(cols):
                if key == 'select':
                    continue
                if key == 'extract':
                    if source_mkv and is_mkvinfo:
                        btn = QToolButton(table)
                        btn.setText(self.t('提取'))
                        try:
                            tid = int(str(s.get('track_id') or s.get('index') or '').strip())
                        except Exception:
                            tid = -1
                        cid = str(s.get('codec_id') or '')
                        if tid >= 0:
                            btn.clicked.connect(partial(self._extract_track_to_temp_and_open, source_mkv, tid, cid))
                            table.setCellWidget(r, c, btn)
                        else:
                            table.setItem(r, c, QTableWidgetItem(''))
                    else:
                        table.setItem(r, c, QTableWidgetItem(''))
                    continue
                if key == 'track_number' and is_mkvinfo:
                    v = s.get('track_number', s.get('track_id', ''))
                elif key == 'language':
                    if is_mkvinfo:
                        v = s.get('language', s.get('lang', 'und'))
                    else:
                        v = 'und'
                        try:
                            pid = self._parse_stream_pid(s.get('id'))
                            if pid is not None and pid in pid_to_lang:
                                v = pid_to_lang.get(pid, 'und')
                            else:
                                try:
                                    idx = int(str(s.get('index') or '').strip())
                                    v = pid_to_lang.get(idx, 'und')
                                except Exception:
                                    v = 'und'
                        except Exception:
                            v = 'und'
                    item = QTableWidgetItem('' if v is None else str(v))
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
                    item.setBackground(QColor('#e0f0ff'))
                    table.setItem(r, c, item)
                    original_languages.append('' if v is None else str(v))
                    continue
                else:
                    v = s.get(key, '')
                table.setItem(r, c, QTableWidgetItem('' if v is None else str(v)))
        table.resizeColumnsToContents()
        layout.addWidget(table)
        btn_row = QWidget(dlg)
        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_row.setLayout(btn_layout)
        btn_ok = QPushButton(self.t('选择'), dlg)
        btn_cancel = QPushButton(self.t('取消'), dlg)
        btn_cancel.clicked.connect(dlg.reject)
        status_label = QLabel(dlg)
        status_label.setVisible(False)
        
        def apply_and_accept():
            if source_mkv and is_mkvinfo and len(streams) == table.rowCount():
                lang_col = cols.index('language') if 'language' in cols else -1
                if lang_col >= 0:
                    changed: list[tuple[int, str]] = []
                    for r, s in enumerate(streams):
                        item = table.item(r, lang_col)
                        if not item:
                            continue
                        new_lang = str(item.text()).strip()
                        old_lang = original_languages[r] if r < len(original_languages) else ''
                        if not new_lang or new_lang == old_lang:
                            continue
                        try:
                            track_num = int(s.get('track_number_1based') or s.get('track_id') + 1)
                        except Exception:
                            try:
                                track_num = int(str(s.get('track_id') or '').strip()) + 1
                            except Exception:
                                try:
                                    track_num = int(str(s.get('index') or '').strip()) + 1
                                except Exception:
                                    track_num = r + 1
                        changed.append((track_num, new_lang))
                    if changed:
                        try:
                            find_mkvtoolinx()
                        except Exception:
                            pass
                        exe = MKV_PROP_EDIT_PATH or shutil.which('mkvpropedit') or 'mkvpropedit'
                        if exe:
                            args = [exe]
                            try:
                                ui = get_mkvtoolnix_ui_language()
                                if ui:
                                    args += ['--ui-language', ui]
                            except Exception:
                                pass
                            args.append(source_mkv)
                            for track_num, lang in changed:
                                args += ['--edit', f'track:{track_num}', '--set', f'language={lang}']
                            try:
                                p = subprocess.run(args, capture_output=True, text=True, encoding='utf-8', errors='ignore', shell=False)
                                if p.returncode == 0:
                                    try:
                                        updated_streams = self._read_mkvinfo_tracks(source_mkv)
                                        for r, s in enumerate(streams):
                                            if r < len(updated_streams):
                                                new_lang_value = str(updated_streams[r].get('language', updated_streams[r].get('lang', 'und')))
                                                lang_item = table.item(r, lang_col)
                                                if lang_item:
                                                    lang_item.setText(new_lang_value)
                                    except Exception:
                                        pass
                                    status_label.setText(self.t('语言修改成功！'))
                                    status_label.setStyleSheet('color:#16a34a;font-weight:bold;')
                                    status_label.setVisible(True)
                                    def on_success_timeout():
                                        status_label.setVisible(False)
                                        dlg.accept()
                                    QTimer.singleShot(3000, on_success_timeout)
                                else:
                                    error_msg = f'mkvpropedit failed: {p.returncode}'
                                    if p.stdout or p.stderr:
                                        error_msg += f'\n{(p.stdout or "").strip()}\n{(p.stderr or "").strip()}'
                                    status_label.setText(error_msg)
                                    status_label.setStyleSheet('color:#dc2626;font-weight:bold;')
                                    status_label.setVisible(True)
                                    QTimer.singleShot(3000, lambda: status_label.setVisible(False))
                            except Exception as e:
                                status_label.setText(f'Error: {str(e)}')
                                status_label.setStyleSheet('color:#dc2626;font-weight:bold;')
                                status_label.setVisible(True)
                                QTimer.singleShot(3000, lambda: status_label.setVisible(False))
                        else:
                            status_label.setText(self.t('未找到 mkvpropedit'))
                            status_label.setStyleSheet('color:#dc2626;font-weight:bold;')
                            status_label.setVisible(True)
                            QTimer.singleShot(3000, lambda: status_label.setVisible(False))
            else:
                dlg.accept()
        
        btn_ok.clicked.connect(apply_and_accept)
        btn_layout.addStretch(1)
        btn_layout.addWidget(btn_ok)
        btn_layout.addWidget(btn_cancel)
        layout.addWidget(btn_row)
        layout.addWidget(status_label)
        dlg.resize(720, 420)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return None
        selected_after: set[str] = set()
        for r, s in enumerate(streams):
            codec_type = str(s.get('codec_type') or '')
            idx_text = str(s.get('index', ''))
            btn = table.cellWidget(r, cols.index('select'))
            checked = isinstance(btn, QToolButton) and btn.isChecked()
            if codec_type == 'video' or checked:
                selected_after.add(idx_text)
        return selected_after

    def _get_selected_main_mpls_paths(self) -> list[str]:
        out: list[str] = []
        for bdmv_index in range(self.table1.rowCount()):
            info = self.table1.cellWidget(bdmv_index, 2)
            if not isinstance(info, QTableWidget):
                continue
            root_item = self.table1.item(bdmv_index, 0)
            root = root_item.text().strip() if root_item and root_item.text() else ''
            if not root:
                continue
            for mpls_index in range(info.rowCount()):
                main_btn = info.cellWidget(mpls_index, 3)
                if isinstance(main_btn, QToolButton) and main_btn.isChecked():
                    mpls_item = info.item(mpls_index, 0)
                    if mpls_item and mpls_item.text():
                        out.append(os.path.normpath(os.path.join(root, 'BDMV', 'PLAYLIST', mpls_item.text().strip())))
        return out

    def _get_main_mpls_path_for_bdmv_index(self, bdmv_index: int) -> str:
        try:
            idx = int(bdmv_index) - 1
        except Exception:
            return ''
        if idx < 0 or idx >= self.table1.rowCount():
            return ''
        info = self.table1.cellWidget(idx, 2)
        if not isinstance(info, QTableWidget):
            return ''
        root_item = self.table1.item(idx, 0)
        root = root_item.text().strip() if root_item and root_item.text() else ''
        if not root:
            return ''
        for mpls_index in range(info.rowCount()):
            main_btn = info.cellWidget(mpls_index, 3)
            if isinstance(main_btn, QToolButton) and main_btn.isChecked():
                mpls_item = info.item(mpls_index, 0)
                if mpls_item and mpls_item.text():
                    return os.path.normpath(os.path.join(root, 'BDMV', 'PLAYLIST', mpls_item.text().strip()))
        return ''

    def _ensure_default_track_config_for_main(self, mpls_path: str):
        cfg = getattr(self, '_track_selection_config', None)
        if not isinstance(cfg, dict):
            self._track_selection_config = {}
            cfg = self._track_selection_config
        key = f'main::{os.path.normpath(mpls_path)}'
        if key in cfg:
            return
        m2ts_path = self._get_first_m2ts_for_mpls(mpls_path)
        if not m2ts_path:
            return
        chapter = Chapter(mpls_path)
        chapter.get_pid_to_language()
        streams = self._read_ffprobe_streams(m2ts_path)
        copy_audio_track, copy_sub_track = BluraySubtitle._default_track_selection_from_streams(
            streams,
            chapter.pid_to_lang
        )
        cfg[key] = {'audio': copy_audio_track, 'subtitle': copy_sub_track}

    def _inherit_main_track_config_for_sp_key(self, bdmv_index: int, mpls_file: str, sp_key: str):
        if not sp_key:
            return
        cfg = getattr(self, '_track_selection_config', None)
        if not isinstance(cfg, dict):
            self._track_selection_config = {}
            cfg = self._track_selection_config
        if sp_key in cfg:
            return
        mpls_name = str(mpls_file or '').strip()
        if not mpls_name:
            return
        main_mpls_path = self._get_main_mpls_path_for_bdmv_index(bdmv_index)
        if main_mpls_path:
            main_key = f'main::{os.path.normpath(main_mpls_path)}'
            if main_key in cfg:
                main_cfg = cfg.get(main_key) or {}
                cfg[sp_key] = {
                    'audio': list(main_cfg.get('audio') or []),
                    'subtitle': list(main_cfg.get('subtitle') or []),
                }
                return
        playlist_dir = self._get_playlist_dir_for_bdmv_index(bdmv_index)
        if playlist_dir:
            mpls_path = os.path.normpath(os.path.join(playlist_dir, mpls_name))
            alt_key = f'main::{mpls_path}'
            if alt_key in cfg:
                main_cfg = cfg.get(alt_key) or {}
                cfg[sp_key] = {
                    'audio': list(main_cfg.get('audio') or []),
                    'subtitle': list(main_cfg.get('subtitle') or []),
                }

    def _refresh_track_selection_config_for_selected_main(self):
        if self.get_selected_function_id() not in (3, 4):
            return
        for mpls_path in self._get_selected_main_mpls_paths():
            try:
                self._ensure_default_track_config_for_main(mpls_path)
            except Exception:
                pass

    def _create_main_remux_cmd_editor(self, text: str, parent: Optional[QWidget] = None) -> QPlainTextEdit:
        editor = QPlainTextEdit(parent if parent is not None else self.table1)
        editor._auto_cmd = text or ''
        editor._user_modified = False
        editor._updating_cmd = True
        editor.setPlainText(text or '')
        editor._updating_cmd = False
        editor.setReadOnly(False)
        editor.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        editor.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        editor.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        def mark_modified():
            if getattr(editor, '_updating_cmd', False):
                return
            editor._user_modified = True
        editor.textChanged.connect(mark_modified)
        return editor

    def _build_main_remux_cmd_template(self, mpls_path: str, bdmv_index: int, root: str) -> str:
        try:
            find_mkvtoolinx()
        except Exception:
            pass
        try:
            output_folder = os.path.normpath(self.output_folder_path.text().strip()) if hasattr(self, 'output_folder_path') else ''
        except Exception:
            output_folder = ''
        confs: list[dict[str, int | str]] = []
        try:
            latest = getattr(self, '_last_configuration_34', {}) or {}
            for _, conf in latest.items():
                try:
                    if int(conf.get('bdmv_index') or 0) == int(bdmv_index):
                        confs.append(conf)
                except Exception:
                    pass
        except Exception:
            confs = []
        disc_count = 1
        try:
            latest = getattr(self, '_last_configuration_34', {}) or {}
            disc_count = len({int(v.get('bdmv_index') or 0) for v in latest.values() if isinstance(v, dict)}) or 1
        except Exception:
            disc_count = 1
        if not confs:
            confs = [{'selected_mpls': mpls_path[:-5], 'chapter_index': 1}]
        try:
            confs = sorted(confs, key=lambda c: int(c.get('chapter_index') or 0))
        except Exception:
            pass
        try:
            top = ''
            try:
                top = os.path.normpath(self.bdmv_folder_path.text().strip()) if hasattr(self, 'bdmv_folder_path') else ''
            except Exception:
                top = ''
            bs = BluraySubtitle(top or root, [], False, None, movie_mode=self._is_movie_mode())
            bs.track_selection_config = getattr(self, '_track_selection_config', {}) or {}
            bs.movie_mode = bool(self._is_movie_mode())
            cmd, _m2ts, _vol, _out, _mpls, _pid, _a, _s = bs._make_main_mpls_remux_cmd(confs, output_folder or '', int(bdmv_index), disc_count)
            return cmd
        except Exception:
            try:
                mkvmerge_exe = MKV_MERGE_PATH if MKV_MERGE_PATH else 'mkvmerge'
                return f'"{mkvmerge_exe}" {mkvtoolnix_ui_language_arg()} -o "{output_folder}" "{mpls_path}"'
            except Exception:
                return ''

    def _resolve_bdmv_index_for_main_mpls(self, mpls_path: str, fallback_index: int) -> int:
        """Resolve bdmv_index from latest configuration using selected main mpls path."""
        try:
            target = os.path.normpath(str(mpls_path or '').strip())
        except Exception:
            target = ''
        if not target:
            return int(fallback_index)
        try:
            latest = getattr(self, '_last_configuration_34', {}) or {}
            for conf in latest.values():
                if not isinstance(conf, dict):
                    continue
                conf_mpls = os.path.normpath(str(conf.get('selected_mpls') or '') + '.mpls')
                if conf_mpls == target:
                    val = int(conf.get('bdmv_index') or 0)
                    if val > 0:
                        return val
        except Exception:
            pass
        return int(fallback_index)

    def _collect_main_remux_cmd_map_from_table1(self) -> dict[str, str]:
        out: dict[str, str] = {}
        if not hasattr(self, 'table1') or not self.table1:
            return out
        cmd_col = BDMV_LABELS.index('remux_cmd') if 'remux_cmd' in BDMV_LABELS else -1
        if cmd_col < 0:
            return out
        for r in range(self.table1.rowCount()):
            root_item = self.table1.item(r, 0)
            if not root_item:
                continue
            root = root_item.text().strip()
            info = self.table1.cellWidget(r, 2)
            if not isinstance(info, QTableWidget):
                continue
            mpls_path = ''
            for i in range(info.rowCount()):
                btn = info.cellWidget(i, 3)
                if isinstance(btn, QToolButton) and btn.isChecked():
                    item = info.item(i, 0)
                    if item and item.text().strip():
                        mpls_path = os.path.normpath(os.path.join(root, 'BDMV', 'PLAYLIST', item.text().strip()))
                    break
            if not mpls_path:
                continue
            editor = self.table1.cellWidget(r, cmd_col)
            if isinstance(editor, QPlainTextEdit):
                txt = editor.toPlainText().strip()
                if txt:
                    out[mpls_path] = txt
        return out

    def _apply_main_remux_cmds_to_configuration(self, configuration: dict[int, dict[str, int | str]]):
        cmd_map = self._collect_main_remux_cmd_map_from_table1()
        if not cmd_map:
            return
        for _, conf in configuration.items():
            try:
                mpls_path = os.path.normpath(str(conf.get('selected_mpls') or '') + '.mpls')
            except Exception:
                continue
            cmd = cmd_map.get(mpls_path, '')
            if cmd:
                conf['main_remux_cmd'] = cmd

    def _refresh_table1_remux_cmds(self):
        if not hasattr(self, 'table1') or not self.table1:
            return
        if 'remux_cmd' not in BDMV_LABELS:
            return
        cmd_col = BDMV_LABELS.index('remux_cmd')
        for row in range(self.table1.rowCount()):
            root_item = self.table1.item(row, 0)
            root = root_item.text().strip() if root_item and root_item.text() else ''
            if not root:
                continue
            info = self.table1.cellWidget(row, 2)
            if not isinstance(info, QTableWidget):
                continue
            selected_mpls_path = ''
            for i in range(info.rowCount()):
                main_btn = info.cellWidget(i, 3)
                if isinstance(main_btn, QToolButton) and main_btn.isChecked():
                    mpls_item = info.item(i, 0)
                    if mpls_item and mpls_item.text().strip():
                        selected_mpls_path = os.path.normpath(os.path.join(root, 'BDMV', 'PLAYLIST', mpls_item.text().strip()))
                    break
            editor = self.table1.cellWidget(row, cmd_col)
            if not isinstance(editor, QPlainTextEdit):
                editor = self._create_main_remux_cmd_editor('', self.table1)
                self.table1.setCellWidget(row, cmd_col, editor)
                self.table1.setRowHeight(row, max(self.table1.rowHeight(row), 100))
            if not selected_mpls_path:
                editor._updating_cmd = True
                editor._auto_cmd = ''
                editor._user_modified = False
                editor.setPlainText('')
                editor._updating_cmd = False
                continue
            resolved_bdmv_index = self._resolve_bdmv_index_for_main_mpls(selected_mpls_path, row + 1)
            auto_cmd = self._build_main_remux_cmd_template(selected_mpls_path, resolved_bdmv_index, root)
            cur_txt = editor.toPlainText()
            if (not getattr(editor, '_user_modified', False)) or (not cur_txt.strip()) or (cur_txt == getattr(editor, '_auto_cmd', '')):
                editor._updating_cmd = True
                editor._auto_cmd = auto_cmd
                editor.setPlainText(auto_cmd)
                editor._updating_cmd = False

    def on_edit_tracks_from_mpls(self, mpls_path: str):
        try:
            m2ts_path = self._get_first_m2ts_for_mpls(mpls_path)
            if not m2ts_path:
                QMessageBox.information(self, " ", "未找到 m2ts 文件")
                return
            self._ensure_default_track_config_for_main(mpls_path)
            chapter = Chapter(mpls_path)
            chapter.get_pid_to_language()
            streams = self._read_ffprobe_streams(m2ts_path)
            pid_lang = chapter.pid_to_lang
            key = f'main::{os.path.normpath(mpls_path)}'
            cfg = getattr(self, '_track_selection_config', {}).get(key, {})
            selected = set((cfg.get('audio') or []) + (cfg.get('subtitle') or []))
            selected_after = self._show_tracks_dialog(self.t('编辑轨道'), streams, selected, pid_lang)
            if selected_after is None:
                return
            audio: list[str] = []
            subtitle: list[str] = []
            for s in streams:
                idx = str(s.get('index', ''))
                if idx not in selected_after:
                    continue
                ctype = str(s.get('codec_type') or '')
                if ctype == 'audio':
                    audio.append(idx)
                elif ctype == 'subtitle':
                    subtitle.append(idx)
            self._track_selection_config[key] = {'audio': audio, 'subtitle': subtitle}
            self._refresh_table1_remux_cmds()
        except Exception:
            self._show_error_dialog(traceback.format_exc())

    def on_edit_tracks_from_sp_table(self, row: int):
        try:
            if row < 0 or row >= self.table3.rowCount():
                sender = self.sender()
                if sender is not None and hasattr(self, 'table3') and self.table3:
                    try:
                        row = self.table3.indexAt(sender.pos()).row()
                    except Exception:
                        row = -1
            if row < 0 or row >= self.table3.rowCount():
                return
            bdmv_item = self.table3.item(row, ENCODE_SP_LABELS.index('bdmv_index'))
            bdmv_index = int(bdmv_item.text().strip()) if bdmv_item and bdmv_item.text().strip() else 0
            mpls_item = self.table3.item(row, ENCODE_SP_LABELS.index('mpls_file'))
            mpls_file = mpls_item.text().strip() if mpls_item and mpls_item.text() else ''
            m2ts_item = self.table3.item(row, ENCODE_SP_LABELS.index('m2ts_file'))
            m2ts_text = m2ts_item.text().strip() if m2ts_item and m2ts_item.text() else ''
            entry = {'bdmv_index': bdmv_index, 'mpls_file': mpls_file, 'm2ts_file': m2ts_text, 'output_name': ''}
            key = BluraySubtitle._sp_track_key_from_entry(entry)
            cfg = getattr(self, '_track_selection_config', None)
            if not isinstance(cfg, dict):
                self._track_selection_config = {}
                cfg = self._track_selection_config

            pid_lang: dict[int, str] = {}
            streams: list[dict[str, object]] = []
            if mpls_file:
                playlist_dir = self._get_playlist_dir_for_bdmv_index(bdmv_index)
                if not playlist_dir:
                    QMessageBox.information(self, " ", f"未找到对应的蓝光目录（bdmv_index={bdmv_index}），无法定位 mpls 文件")
                    return
                mpls_path = os.path.normpath(os.path.join(playlist_dir, mpls_file))
                if not os.path.exists(mpls_path):
                    QMessageBox.information(self, " ", f"未找到 mpls 文件：\n{mpls_path}")
                    return
                m2ts_path = self._get_first_m2ts_for_mpls(mpls_path)
                if not m2ts_path:
                    QMessageBox.information(self, " ", "未找到 m2ts 文件")
                    return
                chapter = Chapter(mpls_path)
                chapter.get_pid_to_language()
                streams = self._read_ffprobe_streams(m2ts_path)
                pid_lang = chapter.pid_to_lang
            else:
                m2ts_files = self._split_m2ts_files(m2ts_text)
                if not m2ts_files:
                    QMessageBox.information(self, " ", "未找到 m2ts 文件")
                    return
                stream_dir = self._get_stream_dir_for_bdmv_index(bdmv_index)
                if not stream_dir:
                    QMessageBox.information(self, " ", f"未找到对应的蓝光目录（bdmv_index={bdmv_index}），无法定位 m2ts 文件")
                    return
                m2ts_path = os.path.normpath(os.path.join(stream_dir, m2ts_files[0]))
                if not os.path.exists(m2ts_path):
                    QMessageBox.information(self, " ", f"未找到 m2ts 文件：\n{m2ts_path}")
                    return
                streams = self._read_ffprobe_streams(m2ts_path)
                pid_lang = self._pid_lang_from_ffprobe_streams(streams)

            if key not in cfg:
                self._inherit_main_track_config_for_sp_key(bdmv_index, mpls_file, key)
            if key not in cfg:
                a, s = BluraySubtitle._default_track_selection_from_streams(streams, pid_lang)
                cfg[key] = {'audio': a, 'subtitle': s}
            cur = cfg.get(key, {})
            selected = set((cur.get('audio') or []) + (cur.get('subtitle') or []))
            selected_after = self._show_tracks_dialog(self.t('编辑轨道'), streams, selected, pid_lang)
            if selected_after is None:
                return
            audio: list[str] = []
            subtitle: list[str] = []
            for st in streams:
                idx = str(st.get('index', ''))
                if idx not in selected_after:
                    continue
                ctype = str(st.get('codec_type') or '')
                if ctype == 'audio':
                    audio.append(idx)
                elif ctype == 'subtitle':
                    subtitle.append(idx)
            cfg[key] = {'audio': audio, 'subtitle': subtitle}
            if mpls_file:
                try:
                    playlist_dir = self._get_playlist_dir_for_bdmv_index(bdmv_index)
                    if playlist_dir:
                        main_key = f'main::{os.path.normpath(os.path.join(playlist_dir, mpls_file))}'
                        cfg[main_key] = {'audio': list(audio), 'subtitle': list(subtitle)}
                    selected_main_path = self._get_main_mpls_path_for_bdmv_index(bdmv_index)
                    if selected_main_path:
                        selected_main_key = f'main::{os.path.normpath(selected_main_path)}'
                        cfg[selected_main_key] = {'audio': list(audio), 'subtitle': list(subtitle)}
                except Exception:
                    pass
            keep_row = row
            keep_col = ENCODE_SP_LABELS.index('output_name')
            keep_h_scroll = self.table3.horizontalScrollBar().value() if self.table3.horizontalScrollBar() else 0
            keep_v_scroll = self.table3.verticalScrollBar().value() if self.table3.verticalScrollBar() else 0
            self._recompute_sp_output_names()
            try:
                if self.table3.horizontalScrollBar():
                    self.table3.horizontalScrollBar().setValue(keep_h_scroll)
                if self.table3.verticalScrollBar():
                    self.table3.verticalScrollBar().setValue(keep_v_scroll)
                if 0 <= keep_row < self.table3.rowCount():
                    keep_item = self.table3.item(keep_row, keep_col) or self.table3.item(keep_row, 0)
                    if keep_item:
                        self.table3.setCurrentItem(keep_item)
            except Exception:
                pass
            try:
                self._refresh_table1_remux_cmds()
            except Exception:
                pass
        except Exception:
            self._show_error_dialog(traceback.format_exc())

    def _on_edit_tracks_from_sp_table_clicked(self):
        self.on_edit_tracks_from_sp_table(-1)

    def on_button_click(self, mpls_path: str, is_main_at_build: bool = True, bdmv_index: int = 0):
        is_main = self._is_mpls_currently_main(mpls_path)
        class ChapterWindow(QDialog):
            def __init__(this):
                super(ChapterWindow, this).__init__()
                this.setWindowTitle(f"{self.t('章节')}: {mpls_path}")
                layout = QVBoxLayout()
                this.table_widget = QTableWidget()
                self._set_compact_table(this.table_widget, row_height=20, header_height=20)
                this.table_widget.setColumnCount(4)
                self._set_table_headers(this.table_widget, ['select', 'start', 'end', 'file'])
                chapter = Chapter(mpls_path)
                this.chapter = chapter
                mark_info = chapter.mark_info
                in_out_time = chapter.in_out_time
                mpls_duration = chapter.get_total_time()

                offs = []
                offset = 0
                chapter_to_m2ts = {}
                ch_idx = 1
                for ref_to_play_item_id, mark_timestamps in mark_info.items():
                    m2ts = in_out_time[ref_to_play_item_id][0] + '.m2ts'
                    for mark_timestamp in mark_timestamps:
                        off = offset + (mark_timestamp - in_out_time[ref_to_play_item_id][1]) / 45000
                        if mpls_duration - off >= 0.001:
                            offs.append(off)
                            chapter_to_m2ts[ch_idx] = m2ts
                            ch_idx += 1
                    offset += (in_out_time[ref_to_play_item_id][2] - in_out_time[ref_to_play_item_id][1]) / 45000

                this.chapter_to_m2ts = chapter_to_m2ts
                this.table_widget.setRowCount(len(offs))
                
                # Get saved checkbox states for this mpls_path
                saved_states = self._chapter_checkbox_states.get(mpls_path, [])
                
                for i, off in enumerate(offs):
                    item = QTableWidgetItem(f'Chapter {i+1:02d} - {get_time_str(off)}')
                    this.table_widget.setItem(i, 1, item)
                    item = QTableWidgetItem()
                    if is_main:
                        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
                        # Restore saved state or default to Checked
                        if i < len(saved_states):
                            item.setCheckState(Qt.CheckState.Checked if saved_states[i] else Qt.CheckState.Unchecked)
                        else:
                            item.setCheckState(Qt.CheckState.Checked)
                    else:
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
                        item.setCheckState(Qt.CheckState.Unchecked)
                    this.table_widget.setItem(i, 0, item)
                    this.table_widget.setItem(i, 3, QTableWidgetItem(chapter_to_m2ts.get(i+1, '')))
                for i in range(len(offs)-1):
                    this.table_widget.setItem(i, 2, QTableWidgetItem(f'Chapter {i+2:02d} - {get_time_str(offs[i+1])}'))
                if offs:
                    this.table_widget.setItem(len(offs)-1, 2, QTableWidgetItem(f'Ending - {get_time_str(mpls_duration)}'))
                this.table_widget.resizeColumnsToContents()
                layout.addWidget(this.table_widget)
                
                # Add OK and Cancel buttons
                button_layout = QHBoxLayout()
                select_all_button = QPushButton(self.t('全选'))
                ok_button = QPushButton(self.t('确定') if is_main else self.t('关闭'))
                cancel_button = QPushButton(self.t('取消'))
                select_all_button.setEnabled(bool(is_main))
                select_all_button.clicked.connect(this.select_all_chapters)
                button_layout.addWidget(select_all_button)
                ok_button.clicked.connect(this.accept)
                cancel_button.clicked.connect(this.reject)
                if not is_main:
                    cancel_button.setVisible(False)
                button_layout.addWidget(ok_button)
                button_layout.addWidget(cancel_button)
                layout.addLayout(button_layout)
                
                this.setLayout(layout)
                this.setMinimumWidth(500)
                height = len(offs) * 30 + 100
                height = 1000 if height > 1000 else height
                if len(offs) > 1:
                    this.setMinimumHeight(height)

            def get_unchecked_segments(this):
                unchecked_rows = []
                for row in range(this.table_widget.rowCount()):
                    item = this.table_widget.item(row, 0)
                    if item and item.checkState() == Qt.CheckState.Unchecked:
                        unchecked_rows.append(row)
                # Find consecutive segments
                segments = []
                if unchecked_rows:
                    start = unchecked_rows[0]
                    prev = unchecked_rows[0]
                    for r in unchecked_rows[1:]:
                        if r == prev + 1:
                            prev = r
                        else:
                            segments.append((start, prev))
                            start = r
                            prev = r
                    segments.append((start, prev))
                return segments

            def select_all_chapters(this):
                for row in range(this.table_widget.rowCount()):
                    item = this.table_widget.item(row, 0)
                    if not item:
                        continue
                    if item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                        item.setCheckState(Qt.CheckState.Checked)

        chapter_window = ChapterWindow()
        result = chapter_window.exec()
        if result == QDialog.DialogCode.Accepted:
            if not self._is_mpls_currently_main(mpls_path):
                return
            # Save checkbox states for this mpls_path
            states = []
            for row in range(chapter_window.table_widget.rowCount()):
                item = chapter_window.table_widget.item(row, 0)
                if item:
                    states.append(item.checkState() == Qt.CheckState.Checked)
            self._chapter_checkbox_states[mpls_path] = states
            try:
                if self.get_selected_function_id() in (3, 4):
                    cfg = self._generate_configuration_from_ui_inputs()
                    self.on_configuration(cfg, update_sp_table=False)
            except Exception:
                self._show_error_dialog(traceback.format_exc())
            try:
                if self.get_selected_function_id() in (3, 4):
                    self._sync_chapter_checkbox_sp_for_mpls(mpls_path, bdmv_index)
                    self._recompute_sp_output_names()
                    self._start_sp_table_scan()
            except Exception:
                self._show_error_dialog(traceback.format_exc())

    def _add_sp_entries_for_unchecked_segments(self, mpls_path: str, segments: list[tuple[int, int]], bdmv_index: int, chapter_to_m2ts: dict = None):
        chapter = Chapter(mpls_path)
        mark_info = chapter.mark_info
        in_out_time = chapter.in_out_time
        
        if chapter_to_m2ts is None:
            chapter_to_m2ts = {}

        # Get current sp_index for this bdmv_index
        sp_index = self._sp_index_by_bdmv.get(bdmv_index, 0)

        def _chapter_sort_value(name: str) -> int:
            s = str(name or '')
            if re.search(r'_beginning_to_', s, re.I):
                return 0
            m = re.search(r'_chapter_(\d+)_to_', s, re.I)
            return int(m.group(1)) if m else 10 ** 9

        def _find_insert_row(target_bdmv: int, target_mpls: str, target_start_chapter: int) -> int:
            if not hasattr(self, 'table3') or not self.table3:
                return 0
            bdmv_col = ENCODE_SP_LABELS.index('bdmv_index')
            mpls_col = ENCODE_SP_LABELS.index('mpls_file')
            out_col = ENCODE_SP_LABELS.index('output_name')
            total = self.table3.rowCount()
            first_target_bdmv = -1
            for r in range(total):
                b_item = self.table3.item(r, bdmv_col)
                m_item = self.table3.item(r, mpls_col)
                o_item = self.table3.item(r, out_col)
                try:
                    b_val = int(b_item.text().strip()) if b_item and b_item.text() else 0
                except Exception:
                    b_val = 0
                m_val = m_item.text().strip() if m_item and m_item.text() else ''
                out_val = o_item.text().strip() if o_item and o_item.text() else ''
                if b_val == target_bdmv and first_target_bdmv < 0:
                    first_target_bdmv = r
                if b_val > target_bdmv:
                    return r
                if b_val < target_bdmv:
                    continue
                target_mpls_norm = str(target_mpls or '').strip()
                m_val_norm = str(m_val or '').strip()
                target_sort = (1 if not target_mpls_norm else 0, target_mpls_norm.lower())
                cur_sort = (1 if not m_val_norm else 0, m_val_norm.lower())
                if cur_sort > target_sort:
                    return r
                if cur_sort < target_sort:
                    continue
                if m_val_norm != target_mpls_norm:
                    continue
                cur_start = _chapter_sort_value(out_val)
                if target_start_chapter <= cur_start:
                    return r
            if first_target_bdmv >= 0:
                # Append after all rows of this bdmv when no same-mpls chapter slot is found.
                last = first_target_bdmv
                while last + 1 < total:
                    b_item2 = self.table3.item(last + 1, bdmv_col)
                    try:
                        b_val2 = int(b_item2.text().strip()) if b_item2 and b_item2.text() else 0
                    except Exception:
                        b_val2 = 0
                    if b_val2 != target_bdmv:
                        break
                    last += 1
                return last + 1
            return total

        # Visible chapter boundaries must match ChapterWindow (filter marks too close to MPLS end).
        mpls_duration = chapter.get_total_time()
        chapter_bounds: list[float] = []
        offset = 0
        for ref_to_play_item_id, mark_timestamps in mark_info.items():
            for mark_timestamp in mark_timestamps:
                off = offset + (mark_timestamp - in_out_time[ref_to_play_item_id][1]) / 45000
                if mpls_duration - off >= 0.001:
                    chapter_bounds.append(off)
            offset += (in_out_time[ref_to_play_item_id][2] - in_out_time[ref_to_play_item_id][1]) / 45000
        chapter_bounds.append(mpls_duration)

        for start_row, end_row in segments:
            if start_row < 0 or end_row < 0:
                continue
            if start_row >= len(chapter_bounds) - 1 or end_row >= len(chapter_bounds) - 1:
                continue
            sp_index += 1
            start_chapter = start_row + 1  # 1-based
            end_chapter = end_row + 2     # end is the next chapter

            # Calculate duration (indices align with view-chapters table rows)
            start_time = float(chapter_bounds[start_row])
            end_time = float(chapter_bounds[end_row + 1])
            duration = end_time - start_time

            # Collect m2ts files
            m2ts_files = []
            for i in range(start_row, end_row + 1):
                m2ts = chapter_to_m2ts.get(i + 1)  # i+1 because chapter indices are 1-based
                if m2ts:
                    m2ts_files.append(m2ts)
            
            m2ts_files = list(dict.fromkeys(m2ts_files))  # Remove duplicates while preserving order

            # Generate output name
            bdmv_vol = '0' * (3 - len(str(bdmv_index))) + str(bdmv_index)
            sp_no = str(sp_index).zfill(2)
            total_rows = len(chapter_bounds) - 1
            start_tag = f'chapter_{start_chapter}'
            end_tag = f'chapter_{end_chapter}'
            if start_row == 0:
                start_tag = 'beginning'
            if end_row == total_rows - 1:
                end_tag = 'ending'
            suffix = f'_{start_tag}_to_{end_tag}'
            out_name = f'BD_Vol_{bdmv_vol}_SP{sp_no}{suffix}.mkv'

            # Add to table3
            if hasattr(self, 'table3') and self.table3:
                row = _find_insert_row(bdmv_index, os.path.basename(mpls_path), start_chapter)
                self.table3.insertRow(row)
                sel_col = ENCODE_SP_LABELS.index('select')
                bdmv_col = ENCODE_SP_LABELS.index('bdmv_index')
                mpls_col = ENCODE_SP_LABELS.index('mpls_file')
                m2ts_col = ENCODE_SP_LABELS.index('m2ts_file')
                dur_col = ENCODE_SP_LABELS.index('duration')
                out_col = ENCODE_SP_LABELS.index('output_name')
                tracks_col = ENCODE_SP_LABELS.index('tracks')
                play_col = ENCODE_SP_LABELS.index('play')

                # Select checkbox
                sel_item = QTableWidgetItem()
                sel_item.setFlags(sel_item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
                sel_item.setCheckState(Qt.CheckState.Checked if duration >= 30.0 else Qt.CheckState.Unchecked)
                self.table3.setItem(row, sel_col, sel_item)

                self.table3.setItem(row, bdmv_col, QTableWidgetItem(str(bdmv_index)))
                self.table3.setItem(row, mpls_col, QTableWidgetItem(os.path.basename(mpls_path)))
                self.table3.setItem(row, m2ts_col, QTableWidgetItem(','.join(m2ts_files)))
                self.table3.setItem(row, dur_col, QTableWidgetItem(get_time_str(duration)))
                out_item = QTableWidgetItem(out_name)
                out_item.setData(Qt.ItemDataRole.UserRole + 3, suffix)
                out_item.setData(Qt.ItemDataRole.UserRole + 4, 'chapter_segment_sp')
                self.table3.setItem(row, out_col, out_item)
                
                # Set tracks button
                btn_tracks = QToolButton(self.table3)
                btn_tracks.setText(self.t('编辑轨道'))
                btn_tracks.clicked.connect(self._on_edit_tracks_from_sp_table_clicked)
                self.table3.setCellWidget(row, tracks_col, btn_tracks)
                
                # Set play button
                btn_play = QToolButton(self.table3)
                btn_play.setText(self.t('play'))
                btn_play.clicked.connect(self._on_play_sp_table_row_clicked)
                self.table3.setCellWidget(row, play_col, btn_play)

        # Update sp_index
        self._sp_index_by_bdmv[bdmv_index] = sp_index
        
        # Make table3 visible after adding entries
        if self.table3.rowCount() > 0:
            self.table3.setVisible(True)
        
        # Refresh sorting after adding entries (do not auto-scroll).
        if hasattr(self, 'table3') and self.table3:
            was_sorting = self.table3.isSortingEnabled()
            self.table3.setSortingEnabled(False)
            self.table3.setSortingEnabled(was_sorting)

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
                minutes = DEFAULT_APPROX_EPISODE_DURATION_SECONDS / 60.0
        except Exception:
            minutes = DEFAULT_APPROX_EPISODE_DURATION_SECONDS / 60.0
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
        chapter_col = labels.index('start_at_chapter')
        end_col = labels.index('end_at_chapter')
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
                chapter_combo.addItem('chapter 01', 1)
                chapter_combo.setCurrentIndex(0)
                chapter_combo._prev_start_value = int(chapter_combo.currentData() or 1)
                chapter_combo.setEnabled(False)
                self.table2.setCellWidget(row_i, chapter_col, chapter_combo)
                end_combo = self._build_end_chapter_combo(1, False, 1, 2)
                end_combo.currentIndexChanged.connect(partial(self._on_end_chapter_combo_changed, row_i, labels))
                self.table2.setCellWidget(row_i, end_col, end_combo)
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
        self._sync_end_chapter_min_constraints(labels)
        self._apply_start_chapter_constraints(labels)
        self._scroll_table_h_to_right(self.table2)

    def on_select_function(self, force: bool = False, keep_inputs: bool = False, keep_state: bool = False):
        if getattr(self, '_language_updating', False):
            keep_inputs = True
            keep_state = True
        function_id = self.get_selected_function_id()
        if function_id not in (3, 4):
            self._cleanup_info_json_if_needed()

        last_function_id = int(getattr(self, '_selected_function_id', 0) or 0)
        if (not force) and function_id and last_function_id == function_id:
            return
        self._selected_function_id = function_id
        self._refresh_function_tabbar_theme()

        if hasattr(self, 'output_folder_row') and self.output_folder_row:
            self.output_folder_row.setVisible(function_id in (3, 4))
        if hasattr(self, 'select_all_tracks_row') and self.select_all_tracks_row:
            visible = function_id in (3, 4)
            self.select_all_tracks_row.setVisible(visible)
        if hasattr(self, 'episode_mode_row') and self.episode_mode_row:
            self.episode_mode_row.setVisible(function_id in (1, 3, 4))
        if hasattr(self, 'encode_source_row') and self.encode_source_row:
            self.encode_source_row.setVisible(function_id == 4)
        if hasattr(self, 'table3'):
            self.table3.setVisible(function_id in (3, 4))
            try:
                labels = ENCODE_SP_LABELS
                if function_id == 4 and getattr(self, '_encode_input_mode', 'bdmv') == 'remux':
                    labels = ENCODE_REMUX_SP_LABELS
                if self.table3.columnCount() != len(labels):
                    self.table3.setColumnCount(len(labels))
                    self._set_table_headers(self.table3, labels)
                is_encode = function_id == 4
                if 'vpy_path' in labels:
                    self.table3.setColumnHidden(labels.index('vpy_path'), not is_encode)
                if 'edit_vpy' in labels:
                    self.table3.setColumnHidden(labels.index('edit_vpy'), not is_encode)
                if 'preview_script' in labels:
                    self.table3.setColumnHidden(labels.index('preview_script'), not is_encode)
                self._scroll_table_h_to_right(self.table3)
            except Exception:
                pass

        if function_id in (3, 4):
            try:
                if self.table1.columnCount() != len(BDMV_LABELS):
                    self.table1.setColumnCount(len(BDMV_LABELS))
                    self._set_table_headers(self.table1, BDMV_LABELS)
                cmd_col = BDMV_LABELS.index('remux_cmd') if 'remux_cmd' in BDMV_LABELS else -1
                if cmd_col >= 0:
                    self.table1.setColumnWidth(cmd_col, 420 if getattr(self, '_language_code', CURRENT_UI_LANGUAGE) == 'zh' else 380)
                    self._refresh_table1_remux_cmds()
            except Exception:
                pass
        if function_id != 4:
            self._encode_input_mode = 'bdmv'
            try:
                if hasattr(self, 'encode_source_bdmv_radio') and self.encode_source_bdmv_radio:
                    self.encode_source_bdmv_radio.setChecked(True)
            except Exception:
                pass
        try:
            self._apply_encode_input_mode_ui()
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
            if hasattr(self, 'subtitle_suffix_label') and self.subtitle_suffix_label:
                self.subtitle_suffix_label.setVisible(True)
            if hasattr(self, 'subtitle_suffix_combo') and self.subtitle_suffix_combo:
                self.subtitle_suffix_combo.setVisible(True)
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
                self.merge_options_row.setVisible(True)
            if hasattr(self, 'subtitle_suffix_label') and self.subtitle_suffix_label:
                self.subtitle_suffix_label.setVisible(False)
            if hasattr(self, 'subtitle_suffix_combo') and self.subtitle_suffix_combo:
                self.subtitle_suffix_combo.setVisible(False)
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
        self._refresh_function_tabbar_theme()

    def select_bdmv_folder(self):
        folder = QFileDialog.getExistingDirectory(self, self.t("选择文件夹"))
        self.bdmv_folder_path.setText(os.path.normpath(folder))

    def select_remux_folder(self):
        folder = QFileDialog.getExistingDirectory(self, self.t("选择文件夹"))
        if folder and hasattr(self, 'remux_folder_path'):
            self.remux_folder_path.setText(os.path.normpath(folder))

    def _apply_encode_input_mode_ui(self):
        if self.get_selected_function_id() != 4:
            try:
                if hasattr(self, 'remux_path_box') and self.remux_path_box:
                    self.remux_path_box.setVisible(False)
                if hasattr(self, 'bluray_path_box') and self.bluray_path_box:
                    self.bluray_path_box.setVisible(True)
                if hasattr(self, 'table1') and self.table1:
                    self.table1.setVisible(True)
                if hasattr(self, 'series_mode_radio') and self.series_mode_radio:
                    self.series_mode_radio.setEnabled(True)
                if hasattr(self, 'movie_mode_radio') and self.movie_mode_radio:
                    self.movie_mode_radio.setEnabled(True)
                if hasattr(self, 'approx_episode_minutes_combo') and self.approx_episode_minutes_combo:
                    self.approx_episode_minutes_combo.setEnabled(self.series_mode_radio.isChecked() if hasattr(self, 'series_mode_radio') else True)
            except Exception:
                pass
            return

        remux_mode = getattr(self, '_encode_input_mode', 'bdmv') == 'remux'
        try:
            self.label1.setText(self.t("选择文件夹"))
        except Exception:
            pass

        try:
            if hasattr(self, 'bluray_path_box') and self.bluray_path_box:
                self.bluray_path_box.setVisible(not remux_mode)
            if hasattr(self, 'remux_path_box') and self.remux_path_box:
                self.remux_path_box.setVisible(remux_mode)
            if hasattr(self, 'table1') and self.table1:
                self.table1.setVisible(not remux_mode)
            if hasattr(self, 'select_all_tracks_row') and self.select_all_tracks_row:
                self.select_all_tracks_row.setVisible(True)
        except Exception:
            pass
        try:
            if hasattr(self, 'tables_splitter') and self.tables_splitter:
                if remux_mode:
                    total_h = max(320, self.tables_splitter.height() or self.height())
                    top_h = max(44, min(96, int(total_h * 0.12)))
                    if hasattr(self, 'label1_container') and self.label1_container:
                        try:
                            self.label1_container.adjustSize()
                            content_h = int(self.label1_container.sizeHint().height())
                        except Exception:
                            content_h = top_h
                        top_h = max(40, min(120, content_h + 2))
                        self.label1_container.setMinimumHeight(top_h)
                        self.label1_container.setMaximumHeight(top_h)
                        self.label1_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
                    if hasattr(self, 'label2_container') and self.label2_container:
                        self.label2_container.setMinimumHeight(0)
                        self.label2_container.setMaximumHeight(16777215)
                        self.label2_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
                    self.tables_splitter.setStretchFactor(0, 0)
                    self.tables_splitter.setStretchFactor(1, 1)
                    self.tables_splitter.setSizes([top_h, max(220, total_h - top_h)])
                else:
                    total_h = max(320, self.tables_splitter.height() or self.height())
                    half = max(160, int(total_h * 0.5))
                    if hasattr(self, 'label1_container') and self.label1_container:
                        self.label1_container.setMinimumHeight(0)
                        self.label1_container.setMaximumHeight(16777215)
                        self.label1_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
                    if hasattr(self, 'label2_container') and self.label2_container:
                        self.label2_container.setMinimumHeight(0)
                        self.label2_container.setMaximumHeight(16777215)
                        self.label2_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
                    self.tables_splitter.setStretchFactor(0, 1)
                    self.tables_splitter.setStretchFactor(1, 1)
                    self.tables_splitter.setSizes([half, max(160, total_h - half)])
        except Exception:
            pass

        try:
            if hasattr(self, 'series_mode_radio') and self.series_mode_radio:
                self.series_mode_radio.setEnabled(not remux_mode)
                if remux_mode:
                    self.series_mode_radio.setChecked(True)
            if hasattr(self, 'movie_mode_radio') and self.movie_mode_radio:
                self.movie_mode_radio.setEnabled(not remux_mode)
            if hasattr(self, 'approx_episode_minutes_combo') and self.approx_episode_minutes_combo:
                self.approx_episode_minutes_combo.setEnabled((not remux_mode) and bool(self.series_mode_radio.isChecked()))
        except Exception:
            pass

        if remux_mode:
            self.table2.setColumnCount(len(ENCODE_REMUX_LABELS))
            self._set_table_headers(self.table2, ENCODE_REMUX_LABELS)
            self.table3.setColumnCount(len(ENCODE_REMUX_SP_LABELS))
            self._set_table_headers(self.table3, ENCODE_REMUX_SP_LABELS)
            self._update_language_combo_enabled_state()
            if getattr(self, '_language_updating', False):
                self.table2.resizeColumnsToContents()
                self._resize_table_columns_for_language(self.table2)
                self._scroll_table_h_to_right(self.table2)
                self.table3.resizeColumnsToContents()
                self._resize_table_columns_for_language(self.table3)
                self._scroll_table_h_to_right(self.table3)
            else:
                self.table2.setRowCount(0)
                self.table3.setRowCount(0)
                try:
                    self._populate_encode_from_remux_folder()
                except Exception:
                    pass
        else:
            self.table2.setColumnCount(len(ENCODE_LABELS))
            self._set_table_headers(self.table2, ENCODE_LABELS)
            self.table3.setColumnCount(len(ENCODE_SP_LABELS))
            self._set_table_headers(self.table3, ENCODE_SP_LABELS)

    def _parse_stream_pid(self, raw_id: object) -> Optional[int]:
        s = str(raw_id or '').strip()
        if not s:
            return None
        try:
            if s.lower().startswith('0x'):
                return int(s, 16)
            if any(c in 'abcdefABCDEF' for c in s):
                return int(s, 16)
            return int(s, 10)
        except Exception:
            try:
                return int(s, 16)
            except Exception:
                return None

    def _get_remux_source_path_from_table2_row(self, row_index: int) -> str:
        try:
            out_col = ENCODE_REMUX_LABELS.index('output_name')
        except Exception:
            out_col = 3
        item = self.table2.item(row_index, out_col)
        if item:
            data = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(data, str) and data:
                return os.path.normpath(data)
        if hasattr(self, 'remux_folder_path'):
            folder = self._normalize_path_input(self.remux_folder_path.text())
            if folder and item and item.text().strip():
                return os.path.normpath(os.path.join(folder, item.text().strip()))
        return ''

    def _get_remux_source_path_from_table3_row(self, row_index: int) -> str:
        try:
            out_col = ENCODE_REMUX_SP_LABELS.index('output_name')
        except Exception:
            out_col = 1
        item = self.table3.item(row_index, out_col)
        if item:
            data = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(data, str) and data:
                return os.path.normpath(data)
        if hasattr(self, 'remux_folder_path'):
            folder = self._normalize_path_input(self.remux_folder_path.text())
            sp_folder = os.path.join(folder, 'SPs') if folder else ''
            if sp_folder and item and item.text().strip():
                return os.path.normpath(os.path.join(sp_folder, item.text().strip()))
        return ''

    def _pid_lang_from_ffprobe_streams(self, streams: list[dict[str, object]]) -> dict[int, str]:
        out: dict[int, str] = {}
        for s in streams or []:
            lang = 'und'
            try:
                direct = s.get('lang') or s.get('language')
                if direct:
                    lang = str(direct)
                else:
                    tags = s.get('tags') or {}
                    if isinstance(tags, dict):
                        tag_lang = tags.get('lang') or tags.get('language')
                        if tag_lang:
                            lang = str(tag_lang)
            except Exception:
                lang = 'und'
            pid = self._parse_stream_pid(s.get('id'))
            if pid is not None:
                out[pid] = lang
            try:
                idx = int(str(s.get('index') or '').strip())
                out[idx] = lang
            except Exception:
                pass
        return out

    def on_edit_tracks_from_mkv_row(self, table: QTableWidget, row_index: int):
        try:
            if table is self.table2:
                src = self._get_remux_source_path_from_table2_row(row_index)
                key = f'mkv::{os.path.normpath(src)}'
            else:
                src = self._get_remux_source_path_from_table3_row(row_index)
                key = f'mkvsp::{os.path.normpath(src)}'
            if not src or not os.path.exists(src):
                QMessageBox.information(self, " ", "未找到 mkv 文件")
                return
            streams = self._read_mkvinfo_tracks(src)
            pid_lang = {}
            for s in streams:
                try:
                    tid = int(str(s.get('track_id') or s.get('index') or '').strip())
                    pid_lang[tid] = str(s.get('language') or s.get('lang') or 'und')
                except Exception:
                    pass
            cfg = getattr(self, '_track_selection_config', {})
            if key not in cfg:
                a, s = BluraySubtitle._default_track_selection_from_streams(streams, pid_lang)
                cfg[key] = {'audio': a, 'subtitle': s}
            selected = set((cfg.get(key, {}).get('audio') or []) + (cfg.get(key, {}).get('subtitle') or []))
            selected_after = self._show_tracks_dialog(self.t('编辑轨道'), streams, selected, pid_lang, source_mkv=src)
            if selected_after is None:
                return
            audio: list[str] = []
            subtitle: list[str] = []
            for st in streams:
                idx = str(st.get('index', ''))
                if idx not in selected_after:
                    continue
                ctype = str(st.get('codec_type') or '')
                if ctype == 'audio':
                    audio.append(idx)
                elif ctype == 'subtitle':
                    subtitle.append(idx)
            cfg[key] = {'audio': audio, 'subtitle': subtitle}
        except Exception:
            self._show_error_dialog(traceback.format_exc())

    def _edit_chapters_for_mkv(self, mkv_path: str):
        try:
            find_mkvtoolinx()
        except Exception:
            pass
        if not MKV_EXTRACT_PATH or not MKV_PROP_EDIT_PATH:
            QMessageBox.information(self, " ", "未找到 mkvextract 或 mkvpropedit")
            return
        tmp_dir = tempfile.mkdtemp(prefix='BluraySubtitle_chapters_')
        chapter_path = os.path.join(tmp_dir, 'chapter.txt')
        extract_cmd = f'"{MKV_EXTRACT_PATH}" {mkvtoolnix_ui_language_arg()} "{mkv_path}" chapters --simple "{chapter_path}"'
        subprocess.Popen(extract_cmd, shell=True).wait()
        try:
            with open(chapter_path, 'r', encoding='utf-8-sig') as fp:
                content = fp.read()
        except Exception:
            content = ''

        dlg = QDialog(self)
        dlg.setWindowTitle(self.t('编辑章节'))
        layout = QVBoxLayout()
        dlg.setLayout(layout)
        editor = QPlainTextEdit(dlg)
        editor.setPlainText(content)
        layout.addWidget(editor)
        btn_row = QWidget(dlg)
        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_row.setLayout(btn_layout)
        btn_save = QPushButton(self.t('保存'), dlg)
        btn_close = QPushButton(self.t('关闭'), dlg)
        btn_layout.addStretch(1)
        btn_layout.addWidget(btn_save)
        btn_layout.addWidget(btn_close)
        layout.addWidget(btn_row)
        status_label = QLabel('', dlg)
        status_label.setVisible(False)
        layout.addWidget(status_label)

        def on_save():
            try:
                with open(chapter_path, 'w', encoding='utf-8') as fp:
                    fp.write(editor.toPlainText())
            except Exception:
                self._show_error_dialog(traceback.format_exc())
                return
            edit_cmd = f'"{MKV_PROP_EDIT_PATH}" {mkvtoolnix_ui_language_arg()} "{mkv_path}" --chapters "{chapter_path}"'
            try:
                p = subprocess.run(edit_cmd, shell=True, capture_output=True, text=True, encoding='utf-8', errors='ignore')
                out = (p.stdout or '') + '\n' + (p.stderr or '')
            except Exception:
                out = traceback.format_exc()
            is_error = ('错误' in out) or ('error' in out.lower())
            if is_error:
                status_label.setText(self.t('保存失败，请检查'))
                status_label.setStyleSheet('color:#dc2626;')
            else:
                status_label.setText(self.t('保存章节成功！'))
                status_label.setStyleSheet('color:#16a34a;')
            status_label.setVisible(True)
            QTimer.singleShot(3000, lambda: status_label.setVisible(False))

        btn_save.clicked.connect(on_save)
        btn_close.clicked.connect(dlg.accept)
        dlg.resize(820, 560)
        dlg.exec()

    def on_edit_chapters_from_mkv_row(self, table: QTableWidget, row_index: int):
        try:
            if table is self.table2:
                src = self._get_remux_source_path_from_table2_row(row_index)
            else:
                src = self._get_remux_source_path_from_table3_row(row_index)
            if not src or not os.path.exists(src):
                QMessageBox.information(self, " ", "未找到 mkv 文件")
                return
            self._edit_chapters_for_mkv(src)
        except Exception:
            self._show_error_dialog(traceback.format_exc())

    def _read_mkvinfo_attachments(self, mkv_path: str) -> list[dict[str, str]]:
        if not mkv_path or not os.path.exists(mkv_path):
            return []
        try:
            find_mkvtoolinx()
        except Exception:
            pass
        if not MKV_INFO_PATH:
            return []
        try:
            ui_lang = 'en' if sys.platform == 'win32' else 'en_US'
            p = subprocess.run(
                [MKV_INFO_PATH, mkv_path, "--ui-language", ui_lang],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='ignore',
                shell=False
            )
        except Exception:
            return []
        stdout = p.stdout or ''
        out: list[dict[str, str]] = []
        cur: Optional[dict[str, str]] = None
        in_attachments = False
        for raw in stdout.splitlines():
            line = raw.strip()
            if line in ('|+ Attachments', '| + Attachments', '|  + Attachments'):
                in_attachments = True
                continue
            if not in_attachments:
                continue
            if line in ('| + Attached', '|  + Attached', '|+ Attached'):
                if cur and cur.get('filename'):
                    out.append(cur)
                cur = {'filename': '', 'mime_type': '', 'uid': '', 'file_size': '', 'id': ''}
                continue
            if cur is None:
                continue
            if line.startswith('|  + File name: ') or line.startswith('| + File name: ') or line.startswith('|+ File name: '):
                cur['filename'] = line.split(':', 1)[1].strip()
                continue
            if line.startswith('|  + MIME type: ') or line.startswith('| + MIME type: ') or line.startswith('|+ MIME type: '):
                cur['mime_type'] = line.split(':', 1)[1].strip()
                continue
            if line.startswith('|  + File data: size ') or line.startswith('| + File data: size ') or line.startswith('|+ File data: size '):
                nums = re.findall(r'\d+', line)
                cur['file_size'] = nums[0] if nums else ''
                continue
            if line.startswith('|  + File UID: ') or line.startswith('| + File UID: ') or line.startswith('|+ File UID: '):
                nums = re.findall(r'\d+', line)
                cur['uid'] = nums[0] if nums else ''
                continue
            if line.startswith('|+ ') and line not in ('|+ Attached', '|+ Attachments'):
                if cur and cur.get('filename'):
                    out.append(cur)
                cur = None
                in_attachments = False
        if cur and cur.get('filename'):
            out.append(cur)
        return out

    def _read_mkvmerge_attachment_ids(self, mkv_path: str) -> dict[str, str]:
        if not mkv_path or not os.path.exists(mkv_path):
            return {}
        try:
            find_mkvtoolinx()
        except Exception:
            pass
        if not MKV_MERGE_PATH:
            return {}
        try:
            p = subprocess.run(
                [MKV_MERGE_PATH, "--identify", "--ui-language", "en", mkv_path],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='ignore',
                shell=False
            )
        except Exception:
            return {}
        out = {}
        for line in (p.stdout or '').splitlines():
            m = re.search(r"Attachment ID\s+(\d+):.*file name '([^']+)'", line)
            if not m:
                continue
            out[m.group(2)] = m.group(1)
        return out

    def _read_mkvmerge_attachment_rows(self, mkv_path: str) -> list[dict[str, str]]:
        if not mkv_path or not os.path.exists(mkv_path):
            return []
        try:
            find_mkvtoolinx()
        except Exception:
            pass
        if not MKV_MERGE_PATH:
            return []
        try:
            p = subprocess.run(
                [MKV_MERGE_PATH, "--identify", "--ui-language", "en", mkv_path],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='ignore',
                shell=False
            )
        except Exception:
            return []
        rows: list[dict[str, str]] = []
        for line in (p.stdout or '').splitlines():
            m = re.search(r"Attachment ID\s+(\d+):\s*type\s*'([^']+)',\s*size\s*(\d+)\s*bytes,\s*file name\s*'([^']+)'", line)
            if not m:
                continue
            rows.append({
                'filename': m.group(4),
                'mime_type': m.group(2),
                'uid': '',
                'file_size': m.group(3),
                'id': m.group(1),
            })
        return rows

    def _extract_attachment_to_temp_and_open(self, mkv_path: str, attachment_id: str, filename: str):
        try:
            find_mkvtoolinx()
        except Exception:
            pass
        if not MKV_EXTRACT_PATH:
            QMessageBox.information(self, " ", "未找到 mkvextract")
            return
        aid = str(attachment_id or '').strip()
        if not aid:
            QMessageBox.information(self, " ", "未找到附件 ID")
            return
        safe_name = os.path.basename(str(filename or '').strip()) or f'attachment_{aid}.bin'
        safe_name = safe_name.replace('\\', '_').replace('/', '_')
        tmp_dir = tempfile.mkdtemp(prefix='BluraySubtitle_attach_')
        out_path = os.path.join(tmp_dir, safe_name)
        cmd = f'"{MKV_EXTRACT_PATH}" {mkvtoolnix_ui_language_arg()} "{mkv_path}" attachments {aid}:"{out_path}"'
        try:
            p = subprocess.run(cmd, shell=True, capture_output=True, text=True, encoding='utf-8', errors='ignore')
            out = (p.stdout or '') + '\n' + (p.stderr or '')
            if p.returncode != 0:
                self._show_error_dialog(out.strip() or 'mkvextract failed')
                return
        except Exception:
            self._show_error_dialog(traceback.format_exc())
            return
        self.open_folder_path(tmp_dir)

    def _show_attachments_dialog(self, mkv_path: str):
        try:
            find_mkvtoolinx()
        except Exception:
            pass

        dlg = QDialog(self)
        dlg.setWindowTitle(self.t('编辑附件'))
        layout = QVBoxLayout()
        dlg.setLayout(layout)

        table = QTableWidget(dlg)
        self._set_compact_table(table, row_height=22, header_height=22)
        cols = ['filename', 'mime_type', 'uid', 'file_size', 'id', 'extract']
        table.setColumnCount(len(cols))
        self._set_table_headers(table, cols)
        layout.addWidget(table)

        form = QWidget(dlg)
        form_layout = QHBoxLayout()
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.setSpacing(6)
        form.setLayout(form_layout)
        form_layout.addWidget(QLabel(self.t('文件名'), form))
        name_edit = QLineEdit(form)
        name_edit.setMinimumWidth(160)
        form_layout.addWidget(name_edit)
        form_layout.addWidget(QLabel(self.t('MIME 类型'), form))
        mime_edit = QLineEdit(form)
        mime_edit.setMinimumWidth(150)
        form_layout.addWidget(mime_edit)
        form_layout.addWidget(QLabel(self.t('UID'), form))
        uid_edit = QLineEdit(form)
        uid_edit.setMinimumWidth(140)
        form_layout.addWidget(uid_edit)
        form_layout.addStretch(1)
        layout.addWidget(form)

        file_row = QWidget(dlg)
        file_layout = QHBoxLayout()
        file_layout.setContentsMargins(0, 0, 0, 0)
        file_layout.setSpacing(6)
        file_row.setLayout(file_layout)
        file_layout.addWidget(QLabel(self.t('请选择附件'), file_row))
        file_edit = QLineEdit(file_row)
        file_edit.setMinimumWidth(360)
        file_layout.addWidget(file_edit)
        btn_browse = QPushButton(self.t('选择'), file_row)
        file_layout.addWidget(btn_browse)
        layout.addWidget(file_row)

        status_label = QLabel('', dlg)
        status_label.setVisible(False)
        layout.addWidget(status_label)

        btn_row = QWidget(dlg)
        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.setSpacing(6)
        btn_row.setLayout(btn_layout)
        btn_add = QPushButton(self.t('添加附件'), dlg)
        btn_replace = QPushButton(self.t('替换'), dlg)
        btn_update = QPushButton(self.t('更新'), dlg)
        btn_delete = QPushButton(self.t('删除'), dlg)
        btn_refresh = QPushButton(self.t('刷新'), dlg)
        btn_close = QPushButton(self.t('关闭'), dlg)
        btn_layout.addWidget(btn_add)
        btn_layout.addWidget(btn_replace)
        btn_layout.addWidget(btn_update)
        btn_layout.addWidget(btn_delete)
        btn_layout.addWidget(btn_refresh)
        btn_layout.addStretch(1)
        btn_layout.addWidget(btn_close)
        layout.addWidget(btn_row)

        state = {'rows': []}

        def set_status(ok: bool, details: str):
            if ok:
                status_label.setText(self.t('附件操作成功！'))
                status_label.setStyleSheet('color:#16a34a;')
            else:
                status_label.setText(self.t('附件操作失败，请检查'))
                status_label.setStyleSheet('color:#dc2626;')
            status_label.setVisible(True)
            QTimer.singleShot(3000, lambda: status_label.setVisible(False))
            if (not ok) and details:
                self._show_error_dialog(details)

        def selector_for_row(r: dict[str, str]) -> str:
            aid = str(r.get('id') or '').strip()
            if aid:
                return aid
            uid = str(r.get('uid') or '').strip()
            if uid:
                return f'={uid}'
            fn = str(r.get('filename') or '').strip()
            if not fn:
                return ''
            fn = fn.replace(':', r'\c')
            return f'name:{fn}'

        def refresh():
            rows_merge = self._read_mkvmerge_attachment_rows(mkv_path)
            rows_info = self._read_mkvinfo_attachments(mkv_path)
            uid_by_name = {str(x.get('filename') or ''): str(x.get('uid') or '') for x in rows_info}
            if rows_merge:
                rows = rows_merge
                for rr in rows:
                    rr['uid'] = uid_by_name.get(str(rr.get('filename') or ''), str(rr.get('uid') or ''))
            else:
                rows = rows_info
                ids = self._read_mkvmerge_attachment_ids(mkv_path)
                for rr in rows:
                    fn = str(rr.get('filename') or '')
                    rr['id'] = ids.get(fn, '')
            state['rows'] = rows
            table.setRowCount(len(rows))
            for i, row in enumerate(rows):
                for c, key in enumerate(cols):
                    if key == 'extract':
                        btn = QToolButton(table)
                        btn.setText(self.t('提取'))
                        aid = str(row.get('id', '') or '')
                        fn = str(row.get('filename', '') or '')
                        btn.clicked.connect(partial(self._extract_attachment_to_temp_and_open, mkv_path, aid, fn))
                        table.setCellWidget(i, c, btn)
                    else:
                        table.setItem(i, c, QTableWidgetItem(str(row.get(key, '') or '')))
            table.resizeColumnsToContents()

        def on_select_row():
            r = table.currentRow()
            if r < 0 or r >= len(state['rows']):
                return
            row = state['rows'][r]
            name_edit.setText(str(row.get('filename') or ''))
            mime_edit.setText(str(row.get('mime_type') or ''))
            uid_edit.setText(str(row.get('uid') or ''))

        def browse_file():
            start = file_edit.text().strip()
            start_dir = os.path.dirname(start) if start else ''
            path = QFileDialog.getOpenFileName(dlg, self.t('选择'), start_dir)[0]
            if path:
                file_edit.setText(os.path.normpath(path))

        def run_propedit(args: list[str]) -> tuple[bool, str]:
            if not MKV_PROP_EDIT_PATH:
                return False, self.t('未找到 mkvpropedit')
            cmd = f'"{MKV_PROP_EDIT_PATH}" {mkvtoolnix_ui_language_arg()} "{mkv_path}" ' + ' '.join(args)
            try:
                p = subprocess.run(cmd, shell=True, capture_output=True, text=True, encoding='utf-8', errors='ignore')
                out = (p.stdout or '') + '\n' + (p.stderr or '')
            except Exception:
                return False, traceback.format_exc()
            is_error = ('错误' in out) or ('error' in out.lower()) or (p.returncode != 0)
            return (not is_error), out.strip()

        def apply_replace():
            r = table.currentRow()
            if r < 0 or r >= len(state['rows']):
                return
            src_file = self._normalize_path_input(file_edit.text())
            if not src_file or not os.path.isfile(src_file):
                QMessageBox.information(self, " ", self.t('请选择附件'))
                return
            row = state['rows'][r]
            sel = selector_for_row(row)
            if not sel:
                return
            args = []
            if name_edit.text().strip():
                args.append(f'--attachment-name "{name_edit.text().strip()}"')
            if mime_edit.text().strip():
                args.append(f'--attachment-mime-type "{mime_edit.text().strip()}"')
            if uid_edit.text().strip():
                args.append(f'--attachment-uid "{uid_edit.text().strip()}"')
            args.append(f'--replace-attachment {sel}:"{src_file}"')
            ok, details = run_propedit(args)
            set_status(ok, details if not ok else '')
            if ok:
                refresh()

        def apply_update():
            r = table.currentRow()
            if r < 0 or r >= len(state['rows']):
                return
            row = state['rows'][r]
            sel = selector_for_row(row)
            if not sel:
                return
            args = []
            if name_edit.text().strip():
                args.append(f'--attachment-name "{name_edit.text().strip()}"')
            if mime_edit.text().strip():
                args.append(f'--attachment-mime-type "{mime_edit.text().strip()}"')
            if uid_edit.text().strip():
                args.append(f'--attachment-uid "{uid_edit.text().strip()}"')
            args.append(f'--update-attachment {sel}')
            ok, details = run_propedit(args)
            set_status(ok, details if not ok else '')
            if ok:
                refresh()

        def apply_delete():
            r = table.currentRow()
            if r < 0 or r >= len(state['rows']):
                return
            row = state['rows'][r]
            sel = selector_for_row(row)
            if not sel:
                return
            ok, details = run_propedit([f'--delete-attachment {sel}'])
            set_status(ok, details if not ok else '')
            if ok:
                refresh()

        def apply_add():
            src_file = self._normalize_path_input(file_edit.text())
            if not src_file or not os.path.isfile(src_file):
                QMessageBox.information(self, " ", self.t('请选择附件'))
                return
            before_rows = list(state.get('rows') or [])
            before_set = {(str(x.get('id') or ''), str(x.get('filename') or '')) for x in before_rows}
            args = []
            if name_edit.text().strip():
                args.append(f'--attachment-name "{name_edit.text().strip()}"')
            if mime_edit.text().strip():
                args.append(f'--attachment-mime-type "{mime_edit.text().strip()}"')
            if uid_edit.text().strip():
                args.append(f'--attachment-uid "{uid_edit.text().strip()}"')
            args.append(f'--add-attachment "{src_file}"')
            ok, details = run_propedit(args)
            if ok:
                refresh()
                after_rows = list(state.get('rows') or [])
                after_set = {(str(x.get('id') or ''), str(x.get('filename') or '')) for x in after_rows}
                expected_name = (name_edit.text().strip() or os.path.basename(src_file)).strip()
                added = (len(after_set) > len(before_set)) or any(str(x.get('filename') or '') == expected_name for x in after_rows)
                if not added:
                    ok = False
                    details = (details + '\n\n' if details else '') + 'Attachment add verification failed.'
            set_status(ok, details if not ok else '')

        btn_browse.clicked.connect(browse_file)
        table.currentCellChanged.connect(lambda _r, _c, _pr, _pc: on_select_row())
        btn_refresh.clicked.connect(refresh)
        btn_add.clicked.connect(apply_add)
        btn_replace.clicked.connect(apply_replace)
        btn_update.clicked.connect(apply_update)
        btn_delete.clicked.connect(apply_delete)
        btn_close.clicked.connect(dlg.accept)

        refresh()
        if table.rowCount() > 0:
            table.setCurrentCell(0, 0)

        dlg.resize(980, 520)
        dlg.exec()

    def on_edit_attachments_from_mkv_row(self, table: QTableWidget, row_index: int):
        try:
            if table is self.table2:
                src = self._get_remux_source_path_from_table2_row(row_index)
            else:
                src = self._get_remux_source_path_from_table3_row(row_index)
            if not src or not os.path.exists(src):
                QMessageBox.information(self, " ", "未找到 mkv 文件")
                return
            self._show_attachments_dialog(src)
        except Exception:
            self._show_error_dialog(traceback.format_exc())

    def _populate_encode_from_remux_folder(self):
        if self.get_selected_function_id() != 4 or getattr(self, '_encode_input_mode', 'bdmv') != 'remux':
            return
        folder = self._normalize_path_input(self.remux_folder_path.text() if hasattr(self, 'remux_folder_path') else '')
        if not folder or not os.path.isdir(folder):
            return
        start_ts = time.time()
        progress_dialog = QProgressDialog(self.t('读取中'), '', 0, 1000, self)
        progress_dialog.setMinimumWidth(420)
        bar = QProgressBar(progress_dialog)
        bar.setRange(0, 1000)
        bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        progress_dialog.setBar(bar)
        progress_dialog.setCancelButton(None)
        progress_dialog.setMinimumDuration(0)
        progress_dialog.setAutoClose(False)
        progress_dialog.setAutoReset(False)
        progress_dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        show_timer = QTimer(self)
        show_timer.setSingleShot(True)
        show_timer.setInterval(2000)

        def show_if_needed():
            try:
                if (time.time() - start_ts) >= 2.0:
                    progress_dialog.show()
            except Exception:
                pass

        show_timer.timeout.connect(show_if_needed)
        show_timer.start()
        mkvs = [f for f in os.listdir(folder) if f.lower().endswith('.mkv') and os.path.isfile(os.path.join(folder, f))]
        mkvs.sort(key=lambda x: x.lower())
        self.table2.setSortingEnabled(False)
        self.table2.setRowCount(len(mkvs))
        for r, name in enumerate(mkvs):
            src = os.path.normpath(os.path.join(folder, name))
            sub_col = ENCODE_REMUX_LABELS.index('sub_path')
            lang_col = ENCODE_REMUX_LABELS.index('language')
            dur_col = ENCODE_REMUX_LABELS.index('ep_duration')
            out_col = ENCODE_REMUX_LABELS.index('output_name')
            play_col = ENCODE_REMUX_LABELS.index('play')
            tracks_col = ENCODE_REMUX_LABELS.index('edit_tracks')
            chapters_col = ENCODE_REMUX_LABELS.index('edit_chapters')
            attachments_col = ENCODE_REMUX_LABELS.index('edit_attachments')
            self.table2.setItem(r, sub_col, FilePathTableWidgetItem(''))
            combo = self.create_language_combo(parent=self.table2)
            self.table2.setCellWidget(r, lang_col, combo)
            try:
                dur = MKV(src).get_duration()
                self.table2.setItem(r, dur_col, QTableWidgetItem(get_time_str(dur)))
            except Exception:
                self.table2.setItem(r, dur_col, QTableWidgetItem(''))
            out_item = QTableWidgetItem(name)
            out_item.setData(Qt.ItemDataRole.UserRole, src)
            self.table2.setItem(r, out_col, out_item)
            btn_play = QToolButton(self.table2)
            btn_play.setText(self.t('play'))
            btn_play.clicked.connect(partial(self.open_file_path, src))
            self.table2.setCellWidget(r, play_col, btn_play)
            btn_tracks = QToolButton(self.table2)
            btn_tracks.setText(self.t('编辑轨道'))
            btn_tracks.clicked.connect(partial(self.on_edit_tracks_from_mkv_row, self.table2, r))
            self.table2.setCellWidget(r, tracks_col, btn_tracks)
            btn_chapters = QToolButton(self.table2)
            btn_chapters.setText(self.t('edit'))
            btn_chapters.clicked.connect(partial(self.on_edit_chapters_from_mkv_row, self.table2, r))
            self.table2.setCellWidget(r, chapters_col, btn_chapters)
            btn_attachments = QToolButton(self.table2)
            btn_attachments.setText(self.t('edit'))
            btn_attachments.clicked.connect(partial(self.on_edit_attachments_from_mkv_row, self.table2, r))
            self.table2.setCellWidget(r, attachments_col, btn_attachments)
            self.ensure_encode_row_widgets(r)
            if (time.time() - start_ts) >= 2.0:
                try:
                    bar.setValue(int((r + 1) / max(1, len(mkvs)) * 1000))
                except Exception:
                    pass
                QCoreApplication.processEvents()
        self.table2.resizeColumnsToContents()
        self._resize_table_columns_for_language(self.table2)
        self._scroll_table_h_to_right(self.table2)
        self._update_language_combo_enabled_state()
        self.table2.setSortingEnabled(True)
        try:
            show_timer.stop()
            progress_dialog.close()
            progress_dialog.deleteLater()
        except Exception:
            pass
        self._populate_encode_sps_from_remux_folder(folder)

    def _populate_encode_sps_from_remux_folder(self, folder: str):
        if self.get_selected_function_id() != 4 or getattr(self, '_encode_input_mode', 'bdmv') != 'remux':
            return
        sp_folder = os.path.join(folder, 'SPs')
        if not os.path.isdir(sp_folder):
            self.table3.setRowCount(0)
            return
        start_ts = time.time()
        progress_dialog = QProgressDialog(self.t('读取中'), '', 0, 1000, self)
        progress_dialog.setMinimumWidth(420)
        bar = QProgressBar(progress_dialog)
        bar.setRange(0, 1000)
        bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        progress_dialog.setBar(bar)
        progress_dialog.setCancelButton(None)
        progress_dialog.setMinimumDuration(0)
        progress_dialog.setAutoClose(False)
        progress_dialog.setAutoReset(False)
        progress_dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        show_timer = QTimer(self)
        show_timer.setSingleShot(True)
        show_timer.setInterval(2000)

        def show_if_needed():
            try:
                if (time.time() - start_ts) >= 2.0:
                    progress_dialog.show()
            except Exception:
                pass

        show_timer.timeout.connect(show_if_needed)
        show_timer.start()
        mkvs = [f for f in os.listdir(sp_folder) if f.lower().endswith('.mkv') and os.path.isfile(os.path.join(sp_folder, f))]
        mkvs.sort(key=lambda x: x.lower())
        self.table3.setSortingEnabled(False)
        self.table3.setRowCount(len(mkvs))
        for r, name in enumerate(mkvs):
            src = os.path.normpath(os.path.join(sp_folder, name))
            dur_col = ENCODE_REMUX_SP_LABELS.index('duration')
            out_col = ENCODE_REMUX_SP_LABELS.index('output_name')
            play_col = ENCODE_REMUX_SP_LABELS.index('play')
            tracks_col = ENCODE_REMUX_SP_LABELS.index('edit_tracks')
            chapters_col = ENCODE_REMUX_SP_LABELS.index('edit_chapters')
            attachments_col = ENCODE_REMUX_SP_LABELS.index('edit_attachments')
            try:
                dur = MKV(src).get_duration()
                self.table3.setItem(r, dur_col, QTableWidgetItem(get_time_str(dur)))
            except Exception:
                self.table3.setItem(r, dur_col, QTableWidgetItem(''))
            out_item = QTableWidgetItem(name)
            out_item.setData(Qt.ItemDataRole.UserRole, src)
            self.table3.setItem(r, out_col, out_item)
            btn_play = QToolButton(self.table3)
            btn_play.setText(self.t('play'))
            btn_play.clicked.connect(partial(self.open_file_path, src))
            self.table3.setCellWidget(r, play_col, btn_play)
            btn_tracks = QToolButton(self.table3)
            btn_tracks.setText(self.t('编辑轨道'))
            btn_tracks.clicked.connect(partial(self.on_edit_tracks_from_mkv_row, self.table3, r))
            self.table3.setCellWidget(r, tracks_col, btn_tracks)
            btn_chapters = QToolButton(self.table3)
            btn_chapters.setText(self.t('edit'))
            btn_chapters.clicked.connect(partial(self.on_edit_chapters_from_mkv_row, self.table3, r))
            self.table3.setCellWidget(r, chapters_col, btn_chapters)
            btn_attachments = QToolButton(self.table3)
            btn_attachments.setText(self.t('edit'))
            btn_attachments.clicked.connect(partial(self.on_edit_attachments_from_mkv_row, self.table3, r))
            self.table3.setCellWidget(r, attachments_col, btn_attachments)
            vpy_col = ENCODE_REMUX_SP_LABELS.index('vpy_path')
            edit_col = ENCODE_REMUX_SP_LABELS.index('edit_vpy')
            preview_col = ENCODE_REMUX_SP_LABELS.index('preview_script')
            if not self.table3.cellWidget(r, vpy_col):
                self.table3.setCellWidget(r, vpy_col, self.create_vpy_path_widget(parent=self.table3))
            if not self.table3.cellWidget(r, edit_col):
                btn = QToolButton(self.table3)
                btn.setText(self.t('edit'))
                btn.clicked.connect(self.on_edit_sp_vpy_clicked)
                self.table3.setCellWidget(r, edit_col, btn)
            if not self.table3.cellWidget(r, preview_col):
                btn = QToolButton(self.table3)
                btn.setText(self.t('preview'))
                btn.clicked.connect(self.on_preview_sp_scripts_clicked)
                self.table3.setCellWidget(r, preview_col, btn)
            if (time.time() - start_ts) >= 2.0:
                try:
                    bar.setValue(int((r + 1) / max(1, len(mkvs)) * 1000))
                except Exception:
                    pass
                QCoreApplication.processEvents()
        self.table3.resizeColumnsToContents()
        self._resize_table_columns_for_language(self.table3)
        self._scroll_table_h_to_right(self.table3)
        self.table3.setSortingEnabled(True)
        try:
            show_timer.stop()
            progress_dialog.close()
            progress_dialog.deleteLater()
        except Exception:
            pass

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

    def open_file_path(self, path: str):
        path = self._normalize_path_input(path)
        if not path:
            QMessageBox.information(self, " ", "未填写文件路径")
            return
        if not os.path.exists(path):
            QMessageBox.warning(self, "打开文件失败", f"文件不存在：\n{path}")
            return
        try:
            if sys.platform == 'win32':
                os.startfile(path)
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', path])
            else:
                subprocess.Popen(['xdg-open', path])
        except Exception as e:
            QMessageBox.warning(self, "打开文件失败", f"无法打开文件：\n{path}\n\n{e}")

    def _show_error_dialog(self, err_text: str):
        dlg = QDialog(self)
        dlg.setWindowTitle("Error")
        layout = QVBoxLayout()
        dlg.setLayout(layout)
        editor = QPlainTextEdit(dlg)
        editor.setReadOnly(True)
        editor.setPlainText(str(err_text or ''))
        layout.addWidget(editor)
        btn_row = QWidget(dlg)
        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_row.setLayout(btn_layout)
        btn_copy = QPushButton(self.t('复制信息'), dlg)
        btn_close = QPushButton(self.t('关闭'), dlg)
        btn_layout.addStretch(1)
        btn_layout.addWidget(btn_copy)
        btn_layout.addWidget(btn_close)
        layout.addWidget(btn_row)
        btn_copy.clicked.connect(lambda: QApplication.clipboard().setText(editor.toPlainText()))
        btn_close.clicked.connect(dlg.accept)
        dlg.resize(860, 520)
        dlg.exec()

    def select_subtitle_folder(self):
        folder = QFileDialog.getExistingDirectory(self, self.t("选择文件夹"))
        self.subtitle_folder_path.setText(os.path.normpath(folder))

    def _resolve_remux_output_folder(self, base_folder: str) -> str:
        if self.get_selected_function_id() == 4 and getattr(self, '_encode_input_mode', 'bdmv') == 'remux':
            remux_folder = self._normalize_path_input(self.remux_folder_path.text() if hasattr(self, 'remux_folder_path') else '')
            if remux_folder:
                folder_name = os.path.basename(remux_folder.rstrip(os.sep))
                if folder_name:
                    return os.path.join(base_folder, folder_name)
        return base_folder

    def select_output_folder(self):
        start = self.output_folder_path.text().strip() if hasattr(self, 'output_folder_path') else ''
        folder = QFileDialog.getExistingDirectory(self, self.t("选择输出文件夹"), start)
        if folder:
            self.output_folder_path.setText(os.path.normpath(folder))

    def main(self):
        if getattr(self, '_current_cancel_event', None) is not None:
            self._current_cancel_event.set()
            self.exe_button.setEnabled(False)
            self._update_exe_button_progress(text='Canceling...')
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

        if getattr(self, '_encode_input_mode', 'bdmv') == 'remux':
            folder = self._normalize_path_input(self.remux_folder_path.text() if hasattr(self, 'remux_folder_path') else '')
            if not folder or not os.path.isdir(folder):
                self._current_cancel_event = None
                self._reset_exe_button()
                self.exe_button.setEnabled(True)
                QMessageBox.information(self, " ", "未选择 remux 所在的文件夹")
                return
            try:
                remux_folder = os.path.normpath(folder)
                output_norm = os.path.normpath(output_folder)
                parent_of_remux = os.path.normpath(os.path.dirname(remux_folder.rstrip(os.sep)))
                if output_norm == parent_of_remux:
                    self._current_cancel_event = None
                    self._reset_exe_button()
                    self.exe_button.setEnabled(True)
                    QMessageBox.information(self, " ", "输出文件夹为输入文件夹的上级目录，请修改输出文件夹")
                    return
            except Exception:
                pass
            output_folder = self._resolve_remux_output_folder(output_folder)

            mkv_rows: list[dict[str, str]] = []
            for i in range(self.table2.rowCount()):
                src = self._get_remux_source_path_from_table2_row(i)
                if not src or not os.path.exists(src):
                    continue
                try:
                    out_col = ENCODE_REMUX_LABELS.index('output_name')
                    lang_col = ENCODE_REMUX_LABELS.index('language')
                    sub_col = ENCODE_REMUX_LABELS.index('sub_path')
                except Exception:
                    out_col, lang_col, sub_col = 3, 1, 0
                out_item = self.table2.item(i, out_col)
                out_name = out_item.text().strip() if out_item and out_item.text() else os.path.basename(src)
                sub_item = self.table2.item(i, sub_col)
                sub_path = sub_item.text().strip() if sub_item and sub_item.text() else ''
                lang = ''
                combo = self.table2.cellWidget(i, lang_col)
                if isinstance(combo, QComboBox):
                    lang = str(combo.currentData() or combo.currentText() or '').strip()
                vpy_path = self.get_vpy_path_from_row(i) or self.get_default_vpy_path()
                mkv_rows.append({
                    'src_path': src,
                    'output_name': out_name,
                    'sub_path': sub_path,
                    'language': lang,
                    'vpy_path': vpy_path,
                })

            sp_rows: list[dict[str, str]] = []
            if hasattr(self, 'table3'):
                for i in range(self.table3.rowCount()):
                    src = self._get_remux_source_path_from_table3_row(i)
                    if not src or not os.path.exists(src):
                        continue
                    try:
                        out_col = ENCODE_REMUX_SP_LABELS.index('output_name')
                    except Exception:
                        out_col = 1
                    out_item = self.table3.item(i, out_col)
                    out_name = out_item.text().strip() if out_item and out_item.text() else os.path.basename(src)
                    vpy_path = self.get_sp_vpy_path_from_row(i) or self.get_default_vpy_path()
                    sp_rows.append({
                        'src_path': src,
                        'output_name': out_name,
                        'vpy_path': vpy_path,
                    })

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
            self._encode_worker = EncodeMkvFolderWorker(
                mkv_rows=mkv_rows,
                sp_rows=sp_rows,
                remux_folder=remux_folder,
                output_folder=output_folder,
                cancel_event=cancel_event,
                vspipe_mode=vspipe_mode,
                x265_mode=x265_mode,
                x265_params=x265_params,
                sub_pack_mode=sub_pack_mode,
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
            return

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
                    bdmv_index_item = self.table3.item(i, ENCODE_SP_LABELS.index('bdmv_index'))
                    mpls_item = self.table3.item(i, ENCODE_SP_LABELS.index('mpls_file'))
                    m2ts_item = self.table3.item(i, ENCODE_SP_LABELS.index('m2ts_file'))
                    sel_item = self.table3.item(i, ENCODE_SP_LABELS.index('select'))
                    sp_entries.append({
                        'bdmv_index': int(bdmv_index_item.text()) if bdmv_index_item and bdmv_index_item.text() else 0,
                        'mpls_file': mpls_item.text().strip() if mpls_item and mpls_item.text() else '',
                        'm2ts_file': m2ts_item.text().strip() if m2ts_item and m2ts_item.text() else '',
                        'selected': bool(sel_item and sel_item.flags() & Qt.ItemFlag.ItemIsEnabled and sel_item.checkState() == Qt.CheckState.Checked),
                        'output_name': (self.table3.item(i, ENCODE_SP_LABELS.index('output_name')).text().strip()
                                        if self.table3.item(i, ENCODE_SP_LABELS.index('output_name')) else '')
                    })
                except Exception:
                    sp_entries.append({'bdmv_index': 0, 'mpls_file': '', 'm2ts_file': '', 'selected': False, 'output_name': ''})
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
                self._show_error_dialog(traceback.format_exc())
                return

        try:
            self._apply_main_remux_cmds_to_configuration(configuration)
        except Exception:
            pass

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
            movie_mode=self._is_movie_mode(),
            track_selection_config=getattr(self, '_track_selection_config', {})
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
            chapter_cfg: dict[int, dict[str, int | str]] = {}
            try:
                if not self._is_movie_mode():
                    chapter_cfg = self._generate_configuration_from_ui_inputs()
            except Exception:
                chapter_cfg = {}
            bs = BluraySubtitle(
                self.bdmv_folder_path.text(),
                mkv_files,
                self.checkbox1.isChecked(),
                self._update_exe_button_progress
            )
            bs.configuration = chapter_cfg
            bs.add_chapter_to_mkv(
                mkv_files, self.table1, cancel_event=cancel_event,
                configuration=chapter_cfg if chapter_cfg else None,
            )
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
            self._show_error_dialog(traceback.format_exc())
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
                    bdmv_index_item = self.table3.item(i, ENCODE_SP_LABELS.index('bdmv_index'))
                    mpls_item = self.table3.item(i, ENCODE_SP_LABELS.index('mpls_file'))
                    m2ts_item = self.table3.item(i, ENCODE_SP_LABELS.index('m2ts_file'))
                    sel_item = self.table3.item(i, ENCODE_SP_LABELS.index('select'))
                    sp_entries.append({
                        'bdmv_index': int(bdmv_index_item.text()) if bdmv_index_item and bdmv_index_item.text() else 0,
                        'mpls_file': mpls_item.text().strip() if mpls_item and mpls_item.text() else '',
                        'm2ts_file': m2ts_item.text().strip() if m2ts_item and m2ts_item.text() else '',
                        'selected': bool(sel_item and sel_item.flags() & Qt.ItemFlag.ItemIsEnabled and sel_item.checkState() == Qt.CheckState.Checked),
                        'output_name': (self.table3.item(i, ENCODE_SP_LABELS.index('output_name')).text().strip()
                                        if self.table3.item(i, ENCODE_SP_LABELS.index('output_name')) else '')
                    })
                except Exception:
                    sp_entries.append({'bdmv_index': 0, 'mpls_file': '', 'm2ts_file': '', 'selected': False, 'output_name': ''})
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
                self._show_error_dialog(traceback.format_exc())
                return
        try:
            self._apply_main_remux_cmds_to_configuration(configuration)
        except Exception:
            pass

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
            movie_mode=self._is_movie_mode(),
            track_selection_config=getattr(self, '_track_selection_config', {})
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


class CustomBox(QGroupBox):  # Drag-and-drop folder input helper for boxed rows.
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
        if self.box_title == 'Remux' and hasattr(w, 'remux_folder_path'):
            w.remux_folder_path.setText(dropped_path)


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


def format_ogm_chapter_timestamp(seconds: float) -> str:
    """Timestamp for OGM/Matroska simple chapter files: always ``HH:MM:SS.mmm``; zero is ``00:00:00.000``."""
    try:
        seconds = float(seconds)
    except Exception:
        seconds = 0.0
    if seconds <= 0.0:
        return '00:00:00.000'
    ts = get_time_str(seconds)
    return '00:00:00.000' if ts == '0' else ts


def append_ogm_chapter_lines(lines: list[str], chapter_index: int, time_seconds: float) -> None:
    """Append one chapter entry: ``CHAPTER01=00:00:00.000`` and ``CHAPTER01NAME=Chapter 01`` (1-based index)."""
    n = max(1, int(chapter_index))
    sid = f'{n:02d}'
    ts = format_ogm_chapter_timestamp(time_seconds)
    lines.append(f'CHAPTER{sid}={ts}')
    lines.append(f'CHAPTER{sid}NAME=Chapter {sid}')


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

        base_name = prog_id.split('\\')[-1]  # Remove registry path prefix.
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
    """Apply audio delay correction while preserving lossless output when possible."""
    # Quote paths to safely handle whitespace.
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
        # Positive delay: pad with silence.
        cmd = f'"{FFMPEG_PATH}" {common_opts} -i {input_file_q} {map_str} -af "adelay={delay_ms}:all=1" {codec_str} {output_file_q}'

    elif delay_ms < 0:
        # Negative delay: trim from the start.
        start_time = abs(delay_ms) / 1000.0
        # Keep -ss after -i for decode-level accuracy on HD audio codecs.
        cmd = f'"{FFMPEG_PATH}" {common_opts} -i {input_file_q} -ss {start_time} {map_str} {codec_str} {output_file_q}'

    else:
        # No delay.
        cmd = f'"{FFMPEG_PATH}" {common_opts} -i {input_file_q} {map_str} {codec_str} {output_file_q}'

    try:
        print(f"Run command: {cmd}")
        subprocess.run(cmd, shell=True, check=True)
        print(f"Completed: {output_file}")
    except subprocess.CalledProcessError as e:
        print(f"FFmpeg error: {e}")


def get_effective_bit_depth(file_path):
    if soundfile is None:
        return 24
    info = soundfile.info(file_path)
    frames = min(int(info.frames), int(info.samplerate) * 10)
    start = int(info.frames) // 2 if int(info.frames) > (frames * 2) else 0
    data, sr = soundfile.read(file_path, start=start, frames=frames, dtype='int32')
    return 16 if np.all(data % 65536 == 0) else 24


def get_audio_duration(file_path):
    """Return total audio duration in seconds using ffprobe metadata."""
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
    """Estimate effective bit depth from a middle sample window of compressed audio."""
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
    Resolve bundled vspipe path and runtime environment for nested package layout.
    """
    # 1) Resolve extracted bundle root.
    bundle_dir = getattr(sys, '_MEIPASS', os.path.abspath("."))

    # 2) Locate nested release folder.
    # Expected layout: _MEIPASS/vs_pkg/vspipe(.exe)
    vs_pkg_dir = os.path.join(bundle_dir, "vs_pkg")

    # 3) Build environment.
    env = os.environ.copy()

    # Remove parent-process Python variables to avoid runtime conflicts.
    env.pop('PYTHONHOME', None)
    env.pop('PYTHONPATH', None)

    if sys.platform == 'win32':
        vspipe_exe = os.path.join(vs_pkg_dir, "vspipe.exe")
        # python313.dll is in vs_pkg root; add it to PATH.
        env['PATH'] = f"{vs_pkg_dir};{env.get('PATH', '')}"
        # Point vspipe to the embedded Python home.
        env['PYTHONHOME'] = vs_pkg_dir
        # Plugin directory mirrors original release-x64 structure.
        env['VAPOURSYNTH_PLUGINS'] = os.path.join(vs_pkg_dir, "vapoursynth64", "coreplugins")

    else:  # Linux
        vspipe_exe = os.path.join(vs_pkg_dir, "vspipe")
        env['LD_LIBRARY_PATH'] = f"{vs_pkg_dir}:{env.get('LD_LIBRARY_PATH', '')}"
        env['PYTHONHOME'] = vs_pkg_dir
        env['PATH'] = f"{vs_pkg_dir}:{env.get('PATH', '')}"
        # Assume Linux plugin structure is consistent.
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
            background-color: #f0f0f0; /* keep solid color, avoid semi-transparency */
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
