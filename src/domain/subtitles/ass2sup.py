import argparse
import atexit
import ctypes
import ctypes.util
import hashlib
import os
import shutil
import struct
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from multiprocessing import get_context
from concurrent.futures import ProcessPoolExecutor
from itertools import repeat
from typing import List, Optional, Tuple
import numpy as np
from PIL import Image

try:
    from src.core.i18n import translate_text
    from src.core.settings import LIBASS_PATH
except ModuleNotFoundError:
    # Direct script execution starts below the repository root, so expose the same shared configuration explicitly.
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
    from src.core.i18n import translate_text
    from src.core.settings import LIBASS_PATH

# Declare the incomplete ctypes structure first so its fields can contain a pointer to the same type.
class ASS_Image(ctypes.Structure):
    pass


ASS_Image._fields_ = [
    ("w", ctypes.c_int),
    ("h", ctypes.c_int),
    ("stride", ctypes.c_int),
    ("bitmap", ctypes.POINTER(ctypes.c_uint8)),
    ("color", ctypes.c_uint32),
    ("dst_x", ctypes.c_int),
    ("dst_y", ctypes.c_int),
    ("next", ctypes.POINTER(ASS_Image)),
    ("type", ctypes.c_int),
]


@dataclass
class Crop:
    x: int
    y: int
    w: int
    h: int


@dataclass
class Event:
    start_frame: int
    end_frame: int
    crop: Crop


@dataclass
class Segment:
    start_frame: int
    end_frame: int
    crop: Crop
    frame_hash: str


G_LIB = None
G_ASS_LIB = None
G_RENDERER = None
G_TRACK = None
G_WIDTH = 0
G_HEIGHT = 0
G_FPS_NUM = 0
G_FPS_DEN = 1
G_OUT_DIR = ""
G_ASS_LOG_CB = None


VIDEO_FORMATS = {
    '480i': (720, 480),
    '480p': (720, 480),
    '576i': (720, 576),
    '576p': (720, 576),
    '720p': (1280, 720),
    '1080i': (1920, 1080),
    '1080p': (1920, 1080),
    '1440p': (2560, 1440),
    '2k': (2560, 1440),
}

FPS_PRESETS = {
    "23.976": (24000, 1001, 24),
    "24": (24, 1, 24),
    "25": (25, 1, 25),
    "29.97": (30000, 1001, 30),
    "30": (30, 1, 30),
    "50": (50, 1, 50),
    "59.94": (60000, 1001, 60),
    "60": (60, 1, 60),
}

def parse_video_format(v: str) -> Tuple[int, int, str]:
    key = v.lower()
    if key in VIDEO_FORMATS:
        w, h = VIDEO_FORMATS[key]
        return w, h, key
    if "x" in key:
        parts = key.split("x", 1)
    elif "*" in key:
        parts = key.split("*", 1)
    else:
        raise ValueError(translate_text("Invalid video format: {value}").format(value=v))
    w = int(parts[0])
    h = int(parts[1])
    return w, h, f"{w}x{h}"


def parse_fps(fps_text: str) -> Tuple[int, int, int, str]:
    if fps_text in FPS_PRESETS:
        num, den, tc_fps = FPS_PRESETS[fps_text]
        return num, den, tc_fps, fps_text
    if "/" in fps_text:
        num_s, den_s = fps_text.split("/", 1)
        num = int(num_s)
        den = int(den_s)
        if num <= 0 or den <= 0:
            raise ValueError(translate_text("Invalid frame rate: {value}").format(value=fps_text))
        tc_fps = int(round(num / den))
        return num, den, tc_fps, fps_text
    val = float(fps_text)
    if val <= 0:
        raise ValueError(translate_text("Invalid frame rate: {value}").format(value=fps_text))
    num = int(round(val * 1000))
    den = 1000
    tc_fps = int(round(val))
    return num, den, tc_fps, fps_text


def estimate_total_frames(ass_path: str, fps_num: int, fps_den: int) -> int:
    max_end_ms = 0
    with open(ass_path, 'r', encoding='utf-8', errors='ignore') as subtitle_file:
        for raw_line in subtitle_file:
            line = raw_line.strip()
            if not line.startswith('Dialogue:'):
                continue
            fields = line[len('Dialogue:'):].split(',', 3)
            if len(fields) < 3:
                continue
            try:
                start_hms, start_centiseconds = fields[1].strip().split('.')
                end_hms, end_centiseconds = fields[2].strip().split('.')
                start_hour, start_minute, start_second = (int(value) for value in start_hms.split(':'))
                end_hour, end_minute, end_second = (int(value) for value in end_hms.split(':'))
                start_ms = (start_hour * 3600 + start_minute * 60 + start_second) * 1000 + int(start_centiseconds) * 10
                end_ms = (end_hour * 3600 + end_minute * 60 + end_second) * 1000 + int(end_centiseconds) * 10
            except (TypeError, ValueError):
                continue
            if end_ms >= start_ms:
                max_end_ms = max(max_end_ms, end_ms)
    return int(max_end_ms * fps_num / fps_den / 1000.0) + 1 if max_end_ms > 0 else 0

def mk_timecode(frame: int, fps: int) -> str:
    frames = frame % fps
    t = frame // fps
    s = t % 60
    t //= 60
    m = t % 60
    h = t // 60
    return f"{h:02d}:{m:02d}:{s:02d}:{frames:02d}"


def crop_rgba(image: np.ndarray) -> Optional[Tuple[Crop, np.ndarray]]:
    ys, xs = np.nonzero(image[:, :, 3])
    if ys.size == 0:
        return None
    min_y = int(ys.min())
    max_y = int(ys.max())
    min_x = int(xs.min())
    max_x = int(xs.max())
    out = image[min_y:max_y + 1, min_x:max_x + 1, :].copy()
    return Crop(min_x, min_y, out.shape[1], out.shape[0]), out


def blend_ass_image_chain(head: ctypes.POINTER(ASS_Image), width: int, height: int) -> np.ndarray:
    out = np.zeros((height, width, 4), dtype=np.uint8)
    node = head
    while bool(node):
        img = node.contents
        if img.w <= 0 or img.h <= 0:
            node = img.next
            continue

        start_x = max(0, img.dst_x)
        start_y = max(0, img.dst_y)
        end_x = min(width, img.dst_x + img.w)
        end_y = min(height, img.dst_y + img.h)
        if start_x >= end_x or start_y >= end_y:
            node = img.next
            continue

        src_x0 = start_x - img.dst_x
        src_y0 = start_y - img.dst_y

        c = img.color
        c1 = (c >> 24) & 0xFF
        c2 = (c >> 16) & 0xFF
        c3 = (c >> 8) & 0xFF
        a1 = 255 - (c & 0xFF)

        h = end_y - start_y
        w = end_x - start_x
        src2d = np.ctypeslib.as_array(img.bitmap, shape=(img.h, img.stride))
        src_alpha = src2d[src_y0:src_y0 + h, src_x0:src_x0 + w].astype(np.uint32)
        a = ((src_alpha * np.uint32(a1) + 127) // 255).astype(np.uint32)

        dst = out[start_y:end_y, start_x:end_x, :]
        da = dst[:, :, 3].astype(np.uint32)
        dsta = a * 255 + (255 - a) * da
        nz = a > 0
        both = nz & (da > 0)
        only_src = nz & (da == 0)

        if np.any(both):
            denom = np.where(dsta == 0, 1, dsta)
            color_rgb = np.array([c1, c2, c3], dtype=np.uint32).reshape(1, 1, 3)
            dst_rgb32 = dst[:, :, 0:3].astype(np.uint32)
            val_rgb = (
                a[:, :, None] * color_rgb * 255
                + da[:, :, None] * dst_rgb32 * (255 - a[:, :, None])
                + (dsta[:, :, None] >> 1)
            ) // denom[:, :, None]
            dst[:, :, 0:3] = np.where(both[:, :, None], val_rgb.astype(np.uint8), dst[:, :, 0:3])
            alpha_new = ((dsta + 127) // 255).astype(np.uint8)
            dst[:, :, 3] = np.where(both, alpha_new, dst[:, :, 3])

        if np.any(only_src):
            dst[:, :, 0] = np.where(only_src, c1, dst[:, :, 0])
            dst[:, :, 1] = np.where(only_src, c2, dst[:, :, 1])
            dst[:, :, 2] = np.where(only_src, c3, dst[:, :, 2])
            dst[:, :, 3] = np.where(only_src, a.astype(np.uint8), dst[:, :, 3])

        node = img.next
    return out


def write_bdn_xml(
    output_xml: str,
    events: List[Event],
    track_name: str,
    language: str,
    video_format: str,
    frame_rate_text: str,
    fps_tc: int,
    total_frames: int,
    png_rel_dir: str,
) -> None:
    first = events[0].start_frame if events else 0
    last = events[-1].end_frame if events else 0
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<BDN Version="0.93" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"',
        'xsi:noNamespaceSchemaLocation="BD-03-006-0093b BDN File Format.xsd">',
        "<Description>",
        f'<Name Title="{track_name}" Content=""/>',
        f'<Language Code="{language}"/>',
        f'<Format VideoFormat="{video_format}" FrameRate="{frame_rate_text}" DropFrame="false"/>',
        (
            f'<Events LastEventOutTC="{mk_timecode(last, fps_tc)}" '
            f'FirstEventInTC="{mk_timecode(first, fps_tc)}" '
            f'ContentInTC="00:00:00:00" ContentOutTC="{mk_timecode(total_frames, fps_tc)}" '
            f'NumberofEvents="{len(events)}" Type="Graphic"/>'
        ),
        "</Description>",
        "<Events>",
    ]
    for ev in events:
        lines.append(
            f'<Event Forced="False" InTC="{mk_timecode(ev.start_frame, fps_tc)}" OutTC="{mk_timecode(ev.end_frame, fps_tc)}">'
        )
        graphic_name = f"{ev.start_frame:08d}_0.png"
        if png_rel_dir:
            graphic_name = f"{png_rel_dir}/{graphic_name}"
        lines.append(
            f'<Graphic Width="{ev.crop.w}" Height="{ev.crop.h}" X="{ev.crop.x}" Y="{ev.crop.y}">'
            f"{graphic_name}</Graphic>"
        )
        lines.append("</Event>")
    lines += ["</Events>", "</BDN>"]
    with open(output_xml, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def load_libass():
    candidates = []
    if LIBASS_PATH:
        candidates.append(LIBASS_PATH)

    found = ctypes.util.find_library("ass")
    if found:
        candidates.append(found)

    if os.name == "nt":
        candidates.extend([
            "libass.dll",
            "ass.dll",
        ])
    elif sys.platform == "darwin":
        candidates.extend([
            "libass.dylib",
            "/opt/homebrew/lib/libass.dylib",
            "/usr/local/lib/libass.dylib",
        ])
    else:
        candidates.extend([
            "libass.so.9",
            "libass.so",
        ])

    tried = []
    lib = None
    for name in candidates:
        if not name:
            continue
        tried.append(name)
        try:
            lib = ctypes.CDLL(name)
            break
        except OSError:
            continue

    if lib is None:
        raise RuntimeError(translate_text("Failed to load libass; tried: {paths}").format(paths=tried))
    lib.ass_library_init.restype = ctypes.c_void_p
    lib.ass_library_done.argtypes = [ctypes.c_void_p]
    lib.ass_renderer_init.argtypes = [ctypes.c_void_p]
    lib.ass_renderer_init.restype = ctypes.c_void_p
    lib.ass_renderer_done.argtypes = [ctypes.c_void_p]
    lib.ass_set_storage_size.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
    lib.ass_set_frame_size.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
    lib.ass_set_fonts_dir.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    lib.ass_set_fonts.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
    lib.ass_read_file.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p]
    lib.ass_read_file.restype = ctypes.c_void_p
    lib.ass_free_track.argtypes = [ctypes.c_void_p]
    lib.ass_render_frame.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_longlong, ctypes.POINTER(ctypes.c_int)]
    lib.ass_render_frame.restype = ctypes.POINTER(ASS_Image)
    lib.ass_set_message_cb.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    return lib



def worker_cleanup():
    global G_LIB, G_ASS_LIB, G_RENDERER, G_TRACK
    if G_LIB is None:
        return
    if G_TRACK:
        G_LIB.ass_free_track(G_TRACK)
    if G_RENDERER:
        G_LIB.ass_renderer_done(G_RENDERER)
    if G_ASS_LIB:
        G_LIB.ass_library_done(G_ASS_LIB)
    G_TRACK = None
    G_RENDERER = None
    G_ASS_LIB = None
    G_LIB = None


def init_worker(in_path: str, out_dir: str, width: int, height: int, fps_num: int, fps_den: int, font_dir: Optional[str]):
    global G_LIB, G_ASS_LIB, G_RENDERER, G_TRACK, G_WIDTH, G_HEIGHT, G_FPS_NUM, G_FPS_DEN, G_OUT_DIR, G_ASS_LOG_CB
    G_LIB = load_libass()
    G_ASS_LIB = G_LIB.ass_library_init()
    callback_type = ctypes.CFUNCTYPE(None, ctypes.c_int, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_void_p)
    G_ASS_LOG_CB = callback_type(lambda _level, _format, _arguments, _data: None)
    G_LIB.ass_set_message_cb(G_ASS_LIB, G_ASS_LOG_CB, None)
    G_RENDERER = G_LIB.ass_renderer_init(G_ASS_LIB)
    G_LIB.ass_set_storage_size(G_RENDERER, width, height)
    G_LIB.ass_set_frame_size(G_RENDERER, width, height)
    if font_dir:
        G_LIB.ass_set_fonts_dir(G_ASS_LIB, font_dir.encode("utf-8"))
    G_LIB.ass_set_fonts(G_RENDERER, None, None, 1, None, 1)
    G_TRACK = G_LIB.ass_read_file(G_ASS_LIB, os.path.abspath(in_path).encode("utf-8"), b"UTF-8")
    if not G_TRACK:
        raise RuntimeError(translate_text("Worker failed to load subtitle track"))
    G_WIDTH = width
    G_HEIGHT = height
    G_FPS_NUM = fps_num
    G_FPS_DEN = fps_den
    G_OUT_DIR = out_dir
    atexit.register(worker_cleanup)


def render_range(frame_range: Tuple[int, int]) -> List[Segment]:
    start, end = frame_range
    segments: List[Segment] = []
    segment_start = 0
    previous_hash = ''
    previous_crop: Optional[Crop] = None
    previous_rgba: Optional[np.ndarray] = None
    changed_flag = ctypes.c_int(1)

    for frame_number in range(start, end):
        timestamp_ms = int(frame_number * G_FPS_DEN * 1000 / G_FPS_NUM)
        image_chain = G_LIB.ass_render_frame(G_RENDERER, G_TRACK, timestamp_ms, ctypes.byref(changed_flag))
        if changed_flag.value == 0:
            continue
        cropped = crop_rgba(blend_ass_image_chain(image_chain, G_WIDTH, G_HEIGHT))
        if cropped is None:
            if previous_crop is not None and previous_rgba is not None:
                Image.fromarray(previous_rgba).save(
                    os.path.join(G_OUT_DIR, f'{segment_start:08d}_0.png'), format='PNG', compress_level=3
                )
                segments.append(Segment(segment_start, frame_number, previous_crop, previous_hash))
            previous_hash, previous_crop, previous_rgba = '', None, None
            continue

        crop, rgba = cropped
        frame_hash = hashlib.blake2b(rgba.tobytes(), digest_size=16).hexdigest()
        if previous_crop is None:
            segment_start, previous_hash, previous_crop, previous_rgba = frame_number, frame_hash, crop, rgba
            continue
        if frame_hash == previous_hash and crop == previous_crop:
            continue
        if previous_rgba is not None:
            Image.fromarray(previous_rgba).save(
                os.path.join(G_OUT_DIR, f'{segment_start:08d}_0.png'), format='PNG', compress_level=3
            )
            segments.append(Segment(segment_start, frame_number, previous_crop, previous_hash))
        segment_start, previous_hash, previous_crop, previous_rgba = frame_number, frame_hash, crop, rgba

    if previous_crop is not None and previous_rgba is not None:
        Image.fromarray(previous_rgba).save(
            os.path.join(G_OUT_DIR, f'{segment_start:08d}_0.png'), format='PNG', compress_level=3
        )
        segments.append(Segment(segment_start, end, previous_crop, previous_hash))
    return segments


def merge_segments(chunks: List[List[Segment]]) -> List[Event]:
    merged: List[Segment] = []
    for chunk in chunks:
        for segment in chunk:
            if (
                merged and segment.start_frame <= merged[-1].end_frame
                and segment.frame_hash == merged[-1].frame_hash and segment.crop == merged[-1].crop
            ):
                merged[-1].end_frame = max(merged[-1].end_frame, segment.end_frame)
            else:
                merged.append(segment)
    return [Event(segment.start_frame, segment.end_frame, segment.crop) for segment in merged]

def main(argv: Optional[List[str]] = None, jobs: Optional[int] = None) -> int:
    parser = argparse.ArgumentParser(description=translate_text("ASS/SSA to BDN XML + PNG (Python + libass)"))
    parser.add_argument("input", help=translate_text("Input .ass/.ssa file"))
    parser.add_argument("-o", "--output", required=True, help=translate_text("Output BDN XML file"))
    parser.add_argument("-v", "--video-format", default="1080p", help=translate_text("720p, 1080p, 1440p, 2k, or WxH"))
    parser.add_argument("-f", "--fps", default="23.976", help=translate_text("For example: 23.976, 24, 25, or 30000/1001"))
    parser.add_argument("-g", "--font-dir", default=None, help=translate_text("Additional font directory for libass"))
    parser.add_argument("-t", "--trackname", default="Undefined", help=translate_text("BDN name title"))
    parser.add_argument("-l", "--language", default="und", help=translate_text("BDN language code"))
    args = parser.parse_args(argv)
    in_path = args.input
    out_xml = args.output
    xml_abs = os.path.abspath(out_xml)
    xml_dir = os.path.dirname(xml_abs) or "."
    xml_stem = os.path.splitext(os.path.basename(xml_abs))[0]
    png_dir_name = f"{xml_stem}_png"
    out_dir = os.path.join(xml_dir, png_dir_name)
    if not os.path.isfile(in_path):
        print(translate_text("Input file not found: {path}").format(path=in_path), file=sys.stderr)
        return 1
    os.makedirs(out_dir, exist_ok=True)

    width, height, vf_text = parse_video_format(args.video_format)
    fps_num, fps_den, tc_fps, fps_text = parse_fps(args.fps)
    total_frames = estimate_total_frames(in_path, fps_num, fps_den)
    if total_frames <= 0:
        print(translate_text("No dialogue events found"), file=sys.stderr)
        return 1

    jobs = max(1, min(jobs or (os.cpu_count() or 1), total_frames))
    # Very fine-grained chunks reduce tail latency from stragglers.
    # Use about ~1.5s per task (minimum 24 frames) for better end-phase core utilization.
    fps_float = fps_num / fps_den
    chunk_size = max(24, int(round(fps_float * 1.5)))
    tasks = []
    for s in range(0, total_frames, chunk_size):
        e = min(total_frames, s + chunk_size)
        if s >= e:
            break
        tasks.append((s, e))

    try:
        if len(tasks) == 1:
            init_worker(in_path, out_dir, width, height, fps_num, fps_den, args.font_dir)
            chunks = [render_range(tasks[0])]
            worker_cleanup()
        else:
            ctx = get_context("spawn")
            with ProcessPoolExecutor(
                max_workers=jobs,
                mp_context=ctx,
                initializer=init_worker,
                initargs=(in_path, out_dir, width, height, fps_num, fps_den, args.font_dir),
            ) as ex:
                chunks = list(ex.map(render_range, tasks, chunksize=1))
    except KeyboardInterrupt:
        print(translate_text("Interrupted; workers terminated"), file=sys.stderr)
        return 130

    events = merge_segments(chunks)

    write_bdn_xml(
        output_xml=out_xml,
        events=events,
        track_name=args.trackname,
        language=args.language,
        video_format=vf_text,
        frame_rate_text=fps_text,
        fps_tc=tc_fps,
        total_frames=total_frames,
        png_rel_dir=png_dir_name,
    )

    print(translate_text("Done: {count} events -> {path} (jobs={jobs}, chunks={chunks})").format(count=len(events), path=out_xml, jobs=jobs, chunks=len(tasks)))
    return 0


@dataclass
class BdnEvent:
    start_frame: int
    end_frame: int
    forced: bool
    x: int
    y: int
    png_path: str


@dataclass
class BdnDoc:
    width: int
    height: int
    fps: float
    events: List[BdnEvent]


def parse_bdn_xml(xml_path: str) -> BdnDoc:
    root = ET.parse(xml_path).getroot()
    format_node = root.find('./Description/Format')
    if format_node is None:
        raise ValueError(translate_text('Invalid BDN XML: missing Description/Format'))
    width, height, _ = parse_video_format(format_node.attrib.get('VideoFormat', '1080p'))
    fps_num, fps_den, nominal_fps, _ = parse_fps(format_node.attrib.get('FrameRate', '23.976'))
    fps = fps_num / fps_den
    base_directory = os.path.dirname(os.path.abspath(xml_path))
    events: List[BdnEvent] = []
    for event_node in root.findall('./Events/Event'):
        graphic = event_node.find('./Graphic')
        if graphic is None:
            continue
        start_values = [int(value) for value in event_node.attrib.get('InTC', '00:00:00:00').split(':')]
        end_values = [int(value) for value in event_node.attrib.get('OutTC', '00:00:00:00').split(':')]
        start_frame = (((start_values[0] * 60 + start_values[1]) * 60 + start_values[2]) * nominal_fps) + start_values[3]
        end_frame = (((end_values[0] * 60 + end_values[1]) * 60 + end_values[2]) * nominal_fps) + end_values[3]
        events.append(BdnEvent(
            start_frame=start_frame,
            end_frame=end_frame,
            forced=event_node.attrib.get('Forced', 'False').lower() == 'true',
            x=int(graphic.attrib.get('X', '0')),
            y=int(graphic.attrib.get('Y', '0')),
            png_path=os.path.join(base_directory, (graphic.text or '').strip()),
        ))
    return BdnDoc(width=width, height=height, fps=fps, events=events)


def fps_id_for(fps: float) -> int:
    frame_rates = (
        (24000.0 / 1001.0, 0x10), (24.0, 0x20), (25.0, 0x30), (30000.0 / 1001.0, 0x40),
        (30.0, 0x50), (50.0, 0x60), (60000.0 / 1001.0, 0x70), (60.0, 0x80),
    )
    matched_rate, frame_rate_id = min(frame_rates, key=lambda item: abs(item[0] - fps))
    if abs(matched_rate - fps) >= 0.01:
        raise ValueError(translate_text('Unsupported Blu-ray frame rate: {fps}').format(fps=fps))
    return frame_rate_id


def _min_pts_interval_for_fps(fps: float) -> int:
    # Spp2Pgs PgsWriter::MinPtsIntervalTable, indexed by the Blu-ray frame-rate identifier.
    return {0x10: 3750, 0x20: 3750, 0x30: 3600, 0x40: 3000, 0x50: 3000,
            0x60: 1800, 0x70: 1500, 0x80: 1500}[fps_id_for(fps)]


def frame_to_pts(frame_number: int, fps: float) -> int:
    return int(round(frame_number * 90000.0 / fps))

def image_to_indexed_and_palette(image: Image.Image) -> Tuple[np.ndarray, List[Tuple[int, int, int, int]]]:
    """Reserve palette index zero for transparency and retain one alpha value per encoded color."""
    if image.mode == 'P':
        indexed = np.array(image, dtype=np.uint8)
        raw_palette = image.getpalette() or []
        alpha = [255] * 256
        transparency = image.info.get('transparency')
        if isinstance(transparency, int):
            alpha[transparency] = 0
        elif isinstance(transparency, (bytes, bytearray, list, tuple)):
            for index, value in enumerate(transparency[:256]):
                alpha[index] = int(value)
        transparent_index = min(range(256), key=alpha.__getitem__)
        remap = np.arange(256, dtype=np.uint8)
        remap[transparent_index] = 0
        next_index = 1
        for index in range(256):
            if index != transparent_index:
                remap[index] = next_index
                next_index += 1
        palette = [(0, 0, 0, 0)] * 256
        for old_index in range(256):
            new_index = int(remap[old_index])
            if new_index:
                offset = old_index * 3
                palette[new_index] = (
                    raw_palette[offset] if offset < len(raw_palette) else 0,
                    raw_palette[offset + 1] if offset + 1 < len(raw_palette) else 0,
                    raw_palette[offset + 2] if offset + 2 < len(raw_palette) else 0,
                    alpha[old_index],
                )
        return remap[indexed], palette

    rgba = np.array(image.convert('RGBA'), dtype=np.uint8)
    alpha_channel = rgba[:, :, 3]
    quantized = Image.fromarray(rgba).quantize(colors=254, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE)
    indexed = np.array(quantized, dtype=np.uint8).astype(np.uint16) + 1
    indexed[alpha_channel == 0] = 0
    indexed = indexed.astype(np.uint8)
    raw_palette = quantized.getpalette() or []
    palette = [(0, 0, 0, 0)] * 256
    for quantized_index in range(254):
        palette_index = quantized_index + 1
        mask = indexed == palette_index
        offset = quantized_index * 3
        palette[palette_index] = (
            raw_palette[offset] if offset < len(raw_palette) else 0,
            raw_palette[offset + 1] if offset + 1 < len(raw_palette) else 0,
            raw_palette[offset + 2] if offset + 2 < len(raw_palette) else 0,
            int(alpha_channel[mask].max()) if np.any(mask) else 0,
        )
    return indexed, palette


def rgb_to_ycrcb(red: int, green: int, blue: int, image_height: int) -> Tuple[int, int, int]:
    # Spp2Pgs uses BT.601 below 720 lines, BT.709 through 1080, and BT.2020 above 1080.
    factors = (
        ((8414, 16519, 3208, 524288), (-4857, -9535, 14392, 4194304), (14392, -12052, -2341, 4194304)),
        ((5983, 20127, 2032, 524288), (-3298, -11094, 14392, 4194304), (14392, -13073, -1320, 4194304)),
        ((7393, 19080, 1669, 524288), (-4019, -10373, 14392, 4194304), (14392, -13235, -1158, 4194304)),
    )[0 if image_height < 720 else 2 if image_height > 1080 else 1]
    values = [(((red * row[0] + green * row[1] + blue * row[2] + row[3]) >> 14) + 1) >> 1 for row in factors]
    return values[0], values[2], values[1]

def encode_rle(idx: np.ndarray) -> bytes:
    h, w = idx.shape
    out = bytearray()
    for y in range(h):
        x = 0
        row = idx[y]
        while x < w:
            color = int(row[x])
            run = 1
            while x + run < w and int(row[x + run]) == color and run < 0x3FFF:
                run += 1
            if run <= 2 and color != 0:
                out.extend([color] * run)
            else:
                out.append(0x00)
                if color == 0 and run < 0x40:
                    out.append(run)
                elif color == 0:
                    out.append(0x40 | ((run >> 8) & 0x3F))
                    out.append(run & 0xFF)
                elif run < 0x40:
                    out.append(0x80 | run)
                    out.append(color)
                else:
                    out.append(0xC0 | ((run >> 8) & 0x3F))
                    out.append(run & 0xFF)
                    out.append(color)
            x += run
        out.extend([0x00, 0x00])
    return bytes(out)


def pgs_packet(seg_type: int, pts: int, dts: int, payload: bytes) -> bytes:
    return b"PG" + struct.pack(">IIBH", pts & 0xFFFFFFFF, dts & 0xFFFFFFFF, seg_type & 0xFF, len(payload)) + payload


def _build_graphics_payload(event: BdnEvent, video_width: int, video_height: int) -> dict:
    with Image.open(event.png_path) as image:
        width, height = image.size
        indexed, rgba_palette = image_to_indexed_and_palette(image)
    rle = encode_rle(indexed)
    palette_size = max(1, int(indexed.max()) + 1)
    palette_data = bytearray([0x00, 0x00])
    for palette_index in range(palette_size):
        red, green, blue, alpha = rgba_palette[palette_index]
        y, cr, cb = rgb_to_ycrcb(red, green, blue, video_height)
        palette_data += bytes([palette_index, y, cr, cb, alpha])

    first_fragment_size = min(len(rle), 0xFFE4)
    object_data_length = len(rle) + 4
    first_fragment = bytearray(struct.pack('>HBB', 0, 0, 0xC0 if len(rle) <= 0xFFE4 else 0x80))
    first_fragment += struct.pack('>I', object_data_length & 0x00FFFFFF)[1:]
    first_fragment += struct.pack('>HH', width, height) + rle[:first_fragment_size]
    object_fragments = [bytes(first_fragment)]
    consumed = first_fragment_size
    while consumed < len(rle):
        fragment_size = min(0xFFEB, len(rle) - consumed)
        sequence_flag = 0x40 if consumed + fragment_size == len(rle) else 0x00
        object_fragments.append(struct.pack('>HBB', 0, 0, sequence_flag) + rle[consumed:consumed + fragment_size])
        consumed += fragment_size

    return {
        'w': width,
        'h': height,
        'x': event.x,
        'y': event.y,
        'forced': event.forced,
        'pds': bytes(palette_data),
        'ods_payloads': object_fragments,
        # Decode durations are the integer forms used by Spp2Pgs for 256/128 Mpixel/s paths.
        'frame_init': (video_width * video_height * 9 + 3199) // 3200,
        'window_init': (width * height * 9 + 3199) // 3200,
        'image_decode': (width * height * 9 + 1599) // 1600,
    }


def _build_event_packets(
    event: BdnEvent,
    graphics: dict,
    composition_number: int,
    video_width: int,
    video_height: int,
    fps: float,
    fps_id: int,
    epoch_start: bool,
    buffer_version: int,
) -> Tuple[bytes, int, int, int]:
    start_pts = frame_to_pts(event.start_frame, fps)
    end_pts = frame_to_pts(event.end_frame, fps)
    decode_start = max(0, start_pts - graphics['frame_init'] - graphics['window_init'])
    object_decode_end = max(0, decode_start + graphics['image_decode'])
    presentation = bytearray(struct.pack('>HH', video_width, video_height))
    presentation += bytes([
        fps_id, (composition_number >> 8) & 0xFF, composition_number & 0xFF,
        0x80 if epoch_start else 0x40, 0, 0, 0x01,
    ])
    presentation += struct.pack('>HBBHH', 0, 0, 0x40 if graphics['forced'] else 0, graphics['x'], graphics['y'])
    window = bytes([0x01, 0x00]) + struct.pack(
        '>HHHH', graphics['x'], graphics['y'], graphics['w'], graphics['h']
    )
    packets = [
        pgs_packet(0x16, start_pts, decode_start, bytes(presentation)),
        pgs_packet(0x17, max(0, start_pts - graphics['window_init']), decode_start, window),
        pgs_packet(0x14, decode_start, 0, bytes([0, buffer_version]) + graphics['pds'][2:]),
    ]
    for object_payload in graphics['ods_payloads']:
        patched_payload = bytearray(object_payload)
        patched_payload[:3] = struct.pack('>HB', 0, buffer_version)
        packets.append(pgs_packet(0x15, object_decode_end, decode_start, bytes(patched_payload)))
    packets.append(pgs_packet(0x80, object_decode_end, 0, b''))

    clear_presentation = struct.pack('>HHBHB', video_width, video_height, fps_id, (composition_number + 1) & 0xFFFF, 0)
    clear_presentation += b'\x00\x00\x00'
    packets.extend([
        pgs_packet(0x16, end_pts, 0, clear_presentation),
        pgs_packet(0x17, max(0, end_pts - graphics['window_init']), 0, window),
        pgs_packet(0x80, max(0, end_pts - graphics['window_init']), 0, b''),
    ])
    return b''.join(packets), start_pts, end_pts, graphics['window_init']

def _build_eraser_packets(
    video_width: int, video_height: int, fps_id: int, composition_number: int, pts: int, window_init: int
) -> bytes:
    dts = max(0, pts - window_init - 1)
    presentation = struct.pack('>HHBHB', video_width, video_height, fps_id, composition_number & 0xFFFF, 0) + b'\x00\x00\x00'
    window = bytes([0x01, 0x00]) + struct.pack('>HHHH', 0, 0, 1, 1)
    return b''.join([
        pgs_packet(0x16, pts, dts, presentation),
        pgs_packet(0x17, dts + 1, dts, window),
        pgs_packet(0x80, dts, 0, b''),
    ])


def _build_anchor_packets(
    video_width: int, video_height: int, fps: float, fps_id: int, composition_number: int, pts: int
) -> bytes:
    # Spp2Pgs registers a 1x1 zero-alpha anchor so the decoder has a valid initial epoch at PTS zero.
    presentation = bytearray(struct.pack('>HH', video_width, video_height))
    presentation += bytes([fps_id, (composition_number >> 8) & 0xFF, composition_number & 0xFF, 0x80, 0, 0, 1])
    presentation += struct.pack('>HBBHH', 0, 0, 0, 0, 0)
    window = bytes([1, 0]) + struct.pack('>HHHH', 0, 0, 1, 1)
    palette = bytes([0, 0, 0, 16, 128, 128, 0])
    image_object = bytes([0, 0, 0xC0, 0, 0, 8, 0, 1, 0, 1, 0, 1, 0, 0])
    dts = max(0, pts - 3750)
    end_pts = pts + _min_pts_interval_for_fps(fps)
    clear = struct.pack('>HHBHB', video_width, video_height, fps_id, (composition_number + 1) & 0xFFFF, 0) + b'\x00\x00\x00'
    return b''.join([
        pgs_packet(0x16, pts, dts, bytes(presentation)), pgs_packet(0x17, max(0, pts - 1), dts, window),
        pgs_packet(0x14, dts, 0, palette), pgs_packet(0x15, pts, dts, image_object),
        pgs_packet(0x80, pts, 0, b''), pgs_packet(0x16, end_pts, 0, clear),
        pgs_packet(0x17, max(0, end_pts - 1), 0, window), pgs_packet(0x80, max(0, end_pts - 1), 0, b''),
    ])


def bdnxml_to_sup(xml_path: str, out_sup: str, jobs: int, bd_compat: str = 'off', debug: bool = False) -> int:
    document = parse_bdn_xml(xml_path)
    if not document.events:
        print(translate_text('No events found in BDN XML'), file=sys.stderr)
        return 1
    previous_end_frame = -1
    for event_index, event in enumerate(document.events):
        if event.end_frame <= event.start_frame:
            raise ValueError(translate_text('Invalid BDN event timing at event {event}').format(event=event_index + 1))
        if event.start_frame < previous_end_frame:
            raise ValueError(translate_text(
                'Overlapping BDN events are not supported (event {event})'
            ).format(event=event_index + 1))
        previous_end_frame = event.end_frame

    jobs = max(1, min(jobs, len(document.events)))
    frame_rate_id = fps_id_for(document.fps)
    if jobs > 1:
        if debug:
            print(translate_text('Precomputing graphics payloads with jobs={jobs}').format(jobs=jobs), file=sys.stderr)
        context = get_context('spawn')
        with ProcessPoolExecutor(max_workers=jobs, mp_context=context) as executor:
            graphics_payloads = list(executor.map(
                _build_graphics_payload, document.events, repeat(document.width), repeat(document.height), chunksize=2
            ))
    else:
        graphics_payloads = [
            _build_graphics_payload(event, document.width, document.height) for event in document.events
        ]

    composition_number = 0
    if bd_compat != 'on':
        with open(out_sup, 'wb') as output:
            for event_index, (event, graphics) in enumerate(zip(document.events, graphics_payloads)):
                packets, _, _, _ = _build_event_packets(
                    event, graphics, composition_number, document.width, document.height, document.fps,
                    frame_rate_id, True, (event_index + 1) & 0xFF,
                )
                output.write(packets)
                composition_number += 2
        return 0

    minimum_interval = _min_pts_interval_for_fps(document.fps)
    full_frame_area = document.width * document.height
    full_decode_duration = max(
        (full_frame_area * 9 + 3199) // 3200, (full_frame_area * 9 + 1599) // 1600
    ) + (full_frame_area * 9 + 3199) // 3200
    largest_window_area = 0
    epoch_active = False
    last_start_pts = last_end_pts = -10**18
    last_window_init = frame_to_pts(1, document.fps)
    epoch_resets = erasers = 0

    with open(out_sup, 'wb') as output:
        output.write(_build_anchor_packets(
            document.width, document.height, document.fps, frame_rate_id, composition_number, 0
        ))
        composition_number += 2
        for event_index, (event, graphics) in enumerate(zip(document.events, graphics_payloads)):
            start_pts = frame_to_pts(event.start_frame, document.fps)
            if epoch_active and start_pts < last_start_pts + minimum_interval:
                raise ValueError(translate_text(
                    'BDN events are too close for Blu-ray decoding (event {event})'
                ).format(event=event_index + 1))

            # Epoch separation follows Spp2Pgs: test the new event against the previous epoch's largest window
            # before adding its crop. Each event is one flattened, non-overlapping bitmap, so palette/object buffer
            # zero can be redefined after its clear composition; incremented versions prevent stale decoder reuse.
            erase_duration = (largest_window_area * 9 + 3199) // 3200
            possible_epoch_end = max(last_start_pts + max(minimum_interval, erase_duration), last_end_pts)
            separated_epoch = epoch_active and start_pts - possible_epoch_end > full_decode_duration
            if separated_epoch:
                output.write(_build_eraser_packets(
                    document.width, document.height, frame_rate_id, composition_number, last_end_pts, last_window_init
                ))
                composition_number += 1
                erasers += 1
                epoch_resets += 1
                largest_window_area = graphics['w'] * graphics['h']
                epoch_active = False
            else:
                largest_window_area = max(largest_window_area, graphics['w'] * graphics['h'])

            packets, last_start_pts, last_end_pts, last_window_init = _build_event_packets(
                event, graphics, composition_number, document.width, document.height, document.fps,
                frame_rate_id, not epoch_active, (event_index + 1) & 0xFF,
            )
            output.write(packets)
            composition_number += 2
            epoch_active = True
            if debug and (event_index + 1) % 200 == 0:
                print(translate_text('Packed {current}/{total} events').format(
                    current=event_index + 1, total=len(document.events)
                ), file=sys.stderr)
        if epoch_active:
            output.write(_build_eraser_packets(
                document.width, document.height, frame_rate_id, composition_number, last_end_pts, last_window_init
            ))
            erasers += 1

    if debug:
        print(translate_text(
            'Blu-ray compatibility: events={events} epoch_resets={epoch_resets} erasers={erasers} '
            'final_composition={composition}'
        ).format(
            events=len(document.events), epoch_resets=epoch_resets, erasers=erasers, composition=composition_number,
        ), file=sys.stderr)
    return 0

def _run_ass2sup_pipeline() -> int:
    parser = argparse.ArgumentParser(
        description=translate_text("ASS/SSA to SUP (embedded ass2bdnxml + bdnxml2sup)")
    )
    parser.add_argument("input_ass", help=translate_text("Input ASS/SSA file"))
    parser.add_argument("-o", "--output", required=True, help=translate_text("Output SUP file"))
    parser.add_argument("-v", "--video-format", default="1080p")
    parser.add_argument("-f", "--fps", default="23.976")
    parser.add_argument("-g", "--font-dir", default=None)
    parser.add_argument("-t", "--trackname", default="Undefined")
    parser.add_argument("-l", "--language", default="und")
    parser.add_argument("-j", "--jobs", type=int, default=max(1, (os.cpu_count() or 1)))
    parser.add_argument(
        "--bd-compat",
        choices=["off", "on"],
        default="off",
        help=translate_text("Blu-ray compatibility guard (off/on; on follows Spp2Pgs)"),
    )
    parser.add_argument(
        "--bd-compat-debug",
        action="store_true",
        help=translate_text("Print detailed Blu-ray compatibility statistics"),
    )
    parser.add_argument("--keep-temp", action="store_true")
    args = parser.parse_args()
    if args.bd_compat_debug:
        print(translate_text(
            'ASS to SUP: input={input} video_format={video_format} fps={fps} bd_compat={bd_compat} jobs={jobs}'
        ).format(
            input=args.input_ass, video_format=args.video_format, fps=args.fps,
            bd_compat=args.bd_compat, jobs=max(1, args.jobs),
        ), file=sys.stderr)

    temp_root = tempfile.mkdtemp(prefix="ass2sup_")
    xml_tmp = os.path.join(temp_root, "intermediate.xml")
    try:
        # Stage 1: ASS -> BDN XML + PNG (direct in-process call)
        cmd1 = [
            "ass2bdnxml-mode",
            "-o",
            xml_tmp,
            "-v",
            args.video_format,
            "-f",
            args.fps,
            "-t",
            args.trackname,
            "-l",
            args.language,
        ]
        if args.font_dir:
            cmd1.extend(["-g", args.font_dir])
        cmd1.append(args.input_ass)

        rc = main(cmd1[1:], jobs=max(1, args.jobs))

        if rc != 0:
            return rc

        # Stage 2: bdnxml -> sup (embedded implementation)
        rc = bdnxml_to_sup(xml_tmp, args.output, max(1, args.jobs), args.bd_compat, args.bd_compat_debug)
        if rc != 0:
            return rc
        print(translate_text("Done: {path}").format(path=args.output))
        return 0
    finally:
        if args.keep_temp:
            print(translate_text("Temporary files kept: {path}").format(path=temp_root), file=sys.stderr)
        else:
            shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(_run_ass2sup_pipeline())
