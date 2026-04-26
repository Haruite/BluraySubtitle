#!/usr/bin/env python3
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
from typing import List, Optional, Tuple
import numpy as np
from PIL import Image


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
    image_number: int
    start_frame: int
    end_frame: int
    crop: Crop


@dataclass
class Segment:
    image_number: int
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
    "720p": (1280, 720),
    "1080p": (1920, 1080),
    "1440p": (2560, 1440),
    "2k": (2560, 1440),
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


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="ASS/SSA to BDN XML + PNG (Python + libass)")
    p.add_argument("input", help="Input .ass/.ssa file")
    p.add_argument("-o", "--output", required=True, help="Output BDN XML file")
    p.add_argument("-v", "--video-format", default="1080p", help="720p,1080p,1440p,2k or WxH")
    p.add_argument("-f", "--fps", default="23.976", help="e.g. 23.976,24,25,30000/1001")
    p.add_argument("-g", "--font-dir", default=None, help="Additional font dir for libass")
    p.add_argument("-t", "--trackname", default="Undefined", help="BDN Name Title")
    p.add_argument("-l", "--language", default="und", help="BDN language code")
    return p.parse_args()


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
        raise ValueError(f"invalid video format: {v}")
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
            raise ValueError(f"invalid fps: {fps_text}")
        tc_fps = int(round(num / den))
        return num, den, tc_fps, fps_text
    val = float(fps_text)
    if val <= 0:
        raise ValueError(f"invalid fps: {fps_text}")
    num = int(round(val * 1000))
    den = 1000
    tc_fps = int(round(val))
    return num, den, tc_fps, fps_text


def parse_ass_time_to_ms(s: str) -> int:
    # ASS timestamp: H:MM:SS.cs
    hms, cs = s.strip().split(".")
    h, m, sec = hms.split(":")
    return (int(h) * 3600 + int(m) * 60 + int(sec)) * 1000 + int(cs) * 10


def estimate_total_frames(ass_path: str, fps_num: int, fps_den: int) -> int:
    max_end_ms = 0
    with open(ass_path, "r", encoding="utf-8", errors="ignore") as f:
        for raw in f:
            line = raw.strip()
            if not line.startswith("Dialogue:"):
                continue
            parts = line[len("Dialogue:"):].split(",", 3)
            if len(parts) < 3:
                continue
            try:
                start_ms = parse_ass_time_to_ms(parts[1])
                end_ms = parse_ass_time_to_ms(parts[2])
            except Exception:
                continue
            if end_ms < start_ms:
                continue
            if end_ms > max_end_ms:
                max_end_ms = end_ms
    if max_end_ms <= 0:
        return 0
    return int(max_end_ms * fps_num / fps_den / 1000.0) + 1


def mk_timecode(frame: int, fps: int) -> str:
    frames = frame % fps
    t = frame // fps
    s = t % 60
    t //= 60
    m = t % 60
    h = t // 60
    return f"{h:02d}:{m:02d}:{s:02d}:{frames:02d}"


def write_png_rgba(path: str, rgba: np.ndarray) -> None:
    # Pillow's PNG codec is typically backed by libpng on Linux distributions.
    Image.fromarray(rgba, mode="RGBA").save(path, format="PNG", compress_level=3)


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
        graphic_name = f"{ev.image_number:08d}_0.png"
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
    libname = ctypes.util.find_library("ass") or "libass.so.9"
    lib = ctypes.CDLL(libname)
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


def silence_libass_logs(lib, ass_lib):
    global G_ASS_LOG_CB
    cb_t = ctypes.CFUNCTYPE(None, ctypes.c_int, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_void_p)
    if G_ASS_LOG_CB is None:
        def _cb(level, fmt, va, data):
            return
        G_ASS_LOG_CB = cb_t(_cb)
    lib.ass_set_message_cb(ass_lib, G_ASS_LOG_CB, None)


def hash_rgba(data: np.ndarray) -> str:
    return hashlib.blake2b(data.tobytes(), digest_size=16).hexdigest()


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
    global G_LIB, G_ASS_LIB, G_RENDERER, G_TRACK, G_WIDTH, G_HEIGHT, G_FPS_NUM, G_FPS_DEN, G_OUT_DIR
    G_LIB = load_libass()
    G_ASS_LIB = G_LIB.ass_library_init()
    silence_libass_logs(G_LIB, G_ASS_LIB)
    G_RENDERER = G_LIB.ass_renderer_init(G_ASS_LIB)
    G_LIB.ass_set_storage_size(G_RENDERER, width, height)
    G_LIB.ass_set_frame_size(G_RENDERER, width, height)
    if font_dir:
        G_LIB.ass_set_fonts_dir(G_ASS_LIB, font_dir.encode("utf-8"))
    G_LIB.ass_set_fonts(G_RENDERER, None, None, 1, None, 1)
    G_TRACK = G_LIB.ass_read_file(G_ASS_LIB, os.path.abspath(in_path).encode("utf-8"), b"UTF-8")
    if not G_TRACK:
        raise RuntimeError("worker failed to load subtitle track")
    G_WIDTH = width
    G_HEIGHT = height
    G_FPS_NUM = fps_num
    G_FPS_DEN = fps_den
    G_OUT_DIR = out_dir
    atexit.register(worker_cleanup)


def render_range(frame_range):
    start, end = frame_range

    segments: List[Segment] = []
    have_line = False
    start_frame = 0
    prev_hash = ""
    prev_crop: Optional[Crop] = None
    prev_png_rgba: Optional[np.ndarray] = None
    prev_changed = True
    changed_flag = ctypes.c_int(1)

    for i in range(start, end):
        ts_ms = int(i * G_FPS_DEN * 1000 / G_FPS_NUM)
        img = G_LIB.ass_render_frame(G_RENDERER, G_TRACK, ts_ms, ctypes.byref(changed_flag))
        changed = changed_flag.value != 0
        if (not changed) and have_line and prev_crop is not None and prev_changed:
            # libass reports frame unchanged: extend current segment directly.
            prev_changed = changed
            continue

        rgba = blend_ass_image_chain(img, G_WIDTH, G_HEIGHT)
        cropped = crop_rgba(rgba)
        prev_changed = changed

        if cropped is None:
            if have_line and prev_crop is not None:
                if prev_png_rgba is not None:
                    write_png_rgba(os.path.join(G_OUT_DIR, f"{start_frame:08d}_0.png"), prev_png_rgba)
                segments.append(Segment(start_frame, start_frame, i, prev_crop, prev_hash))
            have_line = False
            prev_crop = None
            prev_png_rgba = None
            prev_hash = ""
            continue

        crop, png_rgba = cropped
        h = hash_rgba(png_rgba)

        if not have_line:
            have_line = True
            start_frame = i
            prev_crop = crop
            prev_png_rgba = png_rgba
            prev_hash = h
            continue

        if (not changed) and h == prev_hash:
            continue

        if prev_crop is not None:
            if prev_png_rgba is not None:
                write_png_rgba(os.path.join(G_OUT_DIR, f"{start_frame:08d}_0.png"), prev_png_rgba)
            segments.append(Segment(start_frame, start_frame, i, prev_crop, prev_hash))
        start_frame = i
        prev_crop = crop
        prev_png_rgba = png_rgba
        prev_hash = h

    if have_line and prev_crop is not None:
        if prev_png_rgba is not None:
            write_png_rgba(os.path.join(G_OUT_DIR, f"{start_frame:08d}_0.png"), prev_png_rgba)
        segments.append(Segment(start_frame, start_frame, end - 1, prev_crop, prev_hash))

    return segments


def merge_segments(chunks: List[List[Segment]], out_dir: str) -> List[Event]:
    merged: List[Segment] = []
    for chunk in chunks:
        for seg in chunk:
            if merged and seg.start_frame <= merged[-1].end_frame + 1 and seg.frame_hash == merged[-1].frame_hash:
                merged[-1].end_frame = seg.end_frame
            else:
                merged.append(seg)
    return [Event(s.image_number, s.start_frame, s.end_frame, s.crop) for s in merged]


def main() -> int:
    args = parse_args()
    in_path = args.input
    out_xml = args.output
    xml_abs = os.path.abspath(out_xml)
    xml_dir = os.path.dirname(xml_abs) or "."
    xml_stem = os.path.splitext(os.path.basename(xml_abs))[0]
    png_dir_name = f"{xml_stem}_png"
    out_dir = os.path.join(xml_dir, png_dir_name)
    if not os.path.isfile(in_path):
        print(f"input file not found: {in_path}", file=sys.stderr)
        return 1
    os.makedirs(out_dir, exist_ok=True)

    width, height, vf_text = parse_video_format(args.video_format)
    fps_num, fps_den, tc_fps, fps_text = parse_fps(args.fps)
    total_frames = estimate_total_frames(in_path, fps_num, fps_den)
    if total_frames <= 0:
        print("no dialogue events found", file=sys.stderr)
        return 1

    jobs = max(1, min((os.cpu_count() or 1), total_frames))
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
        print("interrupted; workers terminated", file=sys.stderr)
        return 130

    events = merge_segments(chunks, out_dir)

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

    print(f"done: {len(events)} events -> {out_xml} (jobs={jobs}, chunks={len(tasks)})")
    return 0


@dataclass
class BdnEvent:
    in_tc: str
    out_tc: str
    forced: bool
    x: int
    y: int
    width: int
    height: int
    png_path: str


@dataclass
class BdnDoc:
    width: int
    height: int
    fps: float
    events: List[BdnEvent]


def _video_format_to_wh(s: str) -> Tuple[int, int]:
    m = {
        "480i": (720, 480),
        "480p": (720, 480),
        "576i": (720, 576),
        "576p": (720, 576),
        "720p": (1280, 720),
        "1080i": (1920, 1080),
        "1080p": (1920, 1080),
    }
    s = s.strip().lower()
    if s in m:
        return m[s]
    if "x" in s:
        a, b = s.split("x", 1)
        return int(a), int(b)
    raise ValueError(f"unsupported VideoFormat: {s}")


def parse_bdn_xml(xml_path: str) -> BdnDoc:
    root = ET.parse(xml_path).getroot()
    fmt = root.find("./Description/Format")
    if fmt is None:
        raise ValueError("invalid BDN XML: missing Description/Format")
    vf = fmt.attrib.get("VideoFormat", "1080p")
    fr = fmt.attrib.get("FrameRate", "23.976")
    width, height = _video_format_to_wh(vf)
    fps = float(fr)

    base = os.path.dirname(os.path.abspath(xml_path))
    events: List[BdnEvent] = []
    for ev in root.findall("./Events/Event"):
        in_tc = ev.attrib.get("InTC", "00:00:00:00")
        out_tc = ev.attrib.get("OutTC", "00:00:00:00")
        forced = ev.attrib.get("Forced", "False").lower() == "true"
        g = ev.find("./Graphic")
        if g is None:
            continue
        png_name = (g.text or "").strip()
        events.append(
            BdnEvent(
                in_tc=in_tc,
                out_tc=out_tc,
                forced=forced,
                x=int(g.attrib.get("X", "0")),
                y=int(g.attrib.get("Y", "0")),
                width=int(g.attrib.get("Width", "0")),
                height=int(g.attrib.get("Height", "0")),
                png_path=os.path.join(base, png_name),
            )
        )
    return BdnDoc(width=width, height=height, fps=fps, events=events)


def fps_id_for(fps: float) -> int:
    table = [
        (24000.0 / 1001.0, 0x10),
        (23.975, 0x10),
        (24.0, 0x20),
        (25.0, 0x30),
        (30000.0 / 1001.0, 0x40),
        (50.0, 0x60),
        (60000.0 / 1001.0, 0x70),
    ]
    best = min(table, key=lambda t: abs(t[0] - fps))
    return best[1]


def tc_to_pts(tc: str, fps: float) -> int:
    fps_tc = int(round(fps))
    hh, mm, ss, ff = [int(x) for x in tc.split(":")]
    frame_no = (((hh * 60 + mm) * 60 + ss) * fps_tc) + ff
    return int(round(frame_no * 90000.0 / fps))


def _alpha_table_for_p_image(img: Image.Image) -> List[int]:
    alpha = [255] * 256
    tr = img.info.get("transparency", None)
    if tr is None:
        return alpha
    if isinstance(tr, int):
        alpha[tr] = 0
        return alpha
    if isinstance(tr, (bytes, bytearray, list, tuple)):
        n = min(256, len(tr))
        for i in range(n):
            alpha[i] = int(tr[i])
    return alpha


def _from_indexed_png(img: Image.Image) -> Tuple[np.ndarray, List[Tuple[int, int, int, int]]]:
    arr = np.array(img, dtype=np.uint8)
    pal_raw = img.getpalette() or []
    atab = _alpha_table_for_p_image(img)
    trans_old = min(range(256), key=lambda i: atab[i])
    remap = np.arange(256, dtype=np.uint8)
    remap[trans_old] = 0
    nxt = 1
    for i in range(256):
        if i == trans_old:
            continue
        remap[i] = nxt
        nxt += 1
    idx = remap[arr]
    pal = [(0, 0, 0, 0)] * 256
    pal[0] = (0, 0, 0, 0)
    for old_i in range(256):
        new_i = int(remap[old_i])
        if new_i == 0:
            continue
        r = pal_raw[old_i * 3 + 0] if old_i * 3 + 0 < len(pal_raw) else 0
        g = pal_raw[old_i * 3 + 1] if old_i * 3 + 1 < len(pal_raw) else 0
        b = pal_raw[old_i * 3 + 2] if old_i * 3 + 2 < len(pal_raw) else 0
        pal[new_i] = (r, g, b, atab[old_i])
    return idx, pal


def _from_rgba_quantized(rgba: np.ndarray) -> Tuple[np.ndarray, List[Tuple[int, int, int, int]]]:
    alpha = rgba[:, :, 3]
    # Reserve palette index 0 for fully transparent pixels to avoid gray background boxes.
    qimg = Image.fromarray(rgba, mode="RGBA").quantize(colors=254, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE)
    idx = np.array(qimg, dtype=np.uint8).astype(np.uint16) + 1
    idx[alpha == 0] = 0
    idx = idx.astype(np.uint8)
    pal_raw = qimg.getpalette() or []
    pal = [(0, 0, 0, 0)] * 256
    pal[0] = (0, 0, 0, 0)
    for i in range(254):
        r = pal_raw[i * 3 + 0] if i * 3 + 0 < len(pal_raw) else 0
        g = pal_raw[i * 3 + 1] if i * 3 + 1 < len(pal_raw) else 0
        b = pal_raw[i * 3 + 2] if i * 3 + 2 < len(pal_raw) else 0
        pi = i + 1
        mask = idx == pi
        amax = int(alpha[mask].max()) if np.any(mask) else 0
        pal[pi] = (r, g, b, amax)
    return idx, pal


def image_to_indexed_and_palette(img: Image.Image) -> Tuple[np.ndarray, List[Tuple[int, int, int, int]]]:
    if img.mode == "P":
        return _from_indexed_png(img)
    return _from_rgba_quantized(np.array(img.convert("RGBA"), dtype=np.uint8))


def rgb_to_ycrcb(r: int, g: int, b: int) -> Tuple[int, int, int]:
    y = r * 0.2126 * 219.0 / 255.0 + g * 0.7152 * 219.0 / 255.0 + b * 0.0722 * 219.0 / 255.0
    cb = -r * 0.2126 / 1.8556 * 224.0 / 255.0 - g * 0.7152 / 1.8556 * 224.0 / 255.0 + b * 0.5 * 224.0 / 255.0
    cr = r * 0.5 * 224.0 / 255.0 - g * 0.7152 / 1.5748 * 224.0 / 255.0 - b * 0.0722 / 1.5748 * 224.0 / 255.0
    y = max(16, min(235, 16 + int(round(y))))
    cb = max(16, min(240, 128 + int(round(cb))))
    cr = max(16, min(240, 128 + int(round(cr))))
    return y, cr, cb


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


def make_sup_frame(ev: BdnEvent, comp_num: int, v_w: int, v_h: int, fps: float, fps_id: int) -> bytes:
    img = Image.open(ev.png_path)
    width, height = img.size
    idx, pal_rgba = image_to_indexed_and_palette(img)
    rle = encode_rle(idx)
    pal_size = max(1, int(idx.max()) + 1)
    pts_start = tc_to_pts(ev.in_tc, fps)
    pts_end = tc_to_pts(ev.out_tc, fps)
    frame_init = (v_w * v_h * 9 + 3199) // 3200
    window_init = (width * height * 9 + 3199) // 3200
    image_decode = (width * height * 9 + 1599) // 1600

    pcs_start = bytearray()
    pcs_start += struct.pack(">HH", v_w, v_h)
    pcs_start += bytes([fps_id, (comp_num >> 8) & 0xFF, comp_num & 0xFF, 0x80, 0x00, 0x00, 0x01])
    pcs_start += struct.pack(">H", 0x0000)
    pcs_start += bytes([0x00, 0x40 if ev.forced else 0x00])
    pcs_start += struct.pack(">HH", ev.x, ev.y)

    wds = bytearray([0x01, 0x00]) + struct.pack(">HHHH", ev.x, ev.y, width, height)
    pds = bytearray([0x00, 0x00])
    for i in range(pal_size):
        r, g, b, a = pal_rgba[i]
        y, cr, cb = rgb_to_ycrcb(r, g, b)
        pds += bytes([i & 0xFF, y & 0xFF, cr & 0xFF, cb & 0xFF, a & 0xFF])

    ods_packets: List[bytes] = []
    first_sz = min(len(rle), 0xFFE4)
    add_packets = 0 if len(rle) <= 0xFFE4 else 1 + (len(rle) - 0xFFE4) // 0xFFEB
    marker = 0xC0000000 if add_packets == 0 else 0x80000000
    obj_data_len = len(rle) + 4
    ods_first = bytearray(struct.pack(">HBB", 0x0000, 0x00, 0x00))
    ods_first[3] = 0xC0 if add_packets == 0 else 0x80
    ods_first += struct.pack(">I", marker | (obj_data_len & 0x00FFFFFF))[1:]
    ods_first += struct.pack(">HH", width, height)
    ods_first += rle[:first_sz]
    t = pts_start - (frame_init + window_init) + image_decode
    ods_packets.append(pgs_packet(0x15, t, 0, bytes(ods_first)))
    consumed = first_sz
    while consumed < len(rle):
        sz = min(0xFFEB, len(rle) - consumed)
        ods_next = bytearray(struct.pack(">HBB", 0x0000, 0x00, 0x40))
        ods_next += rle[consumed:consumed + sz]
        ods_packets.append(pgs_packet(0x15, t, 0, bytes(ods_next)))
        consumed += sz

    packets = [
        pgs_packet(0x16, pts_start, 0, bytes(pcs_start)),
        pgs_packet(0x17, pts_start - window_init, 0, bytes(wds)),
        pgs_packet(0x14, pts_start - (frame_init + window_init), 0, bytes(pds)),
        *ods_packets,
        pgs_packet(0x80, t, 0, b""),
    ]
    pcs_end = bytearray()
    pcs_end += struct.pack(">HH", v_w, v_h)
    pcs_end += bytes([fps_id, ((comp_num + 1) >> 8) & 0xFF, (comp_num + 1) & 0xFF, 0x00, 0x00, 0x00, 0x00])
    packets += [
        pgs_packet(0x16, pts_end, 0, bytes(pcs_end)),
        pgs_packet(0x17, pts_end - window_init, 0, bytes(wds)),
        pgs_packet(0x80, pts_end - window_init, 0, b""),
    ]
    return b"".join(packets)


def _build_frame_task(task):
    idx, ev, v_w, v_h, fps, fps_id = task
    return make_sup_frame(ev, idx * 2, v_w, v_h, fps, fps_id)


def bdnxml_to_sup(xml_path: str, out_sup: str, jobs: int) -> int:
    doc = parse_bdn_xml(xml_path)
    if not doc.events:
        print("no events found in BDN XML", file=sys.stderr)
        return 1
    jobs = max(1, min(jobs, len(doc.events)))
    fps_id = fps_id_for(doc.fps)
    tasks = [(i, ev, doc.width, doc.height, doc.fps, fps_id) for i, ev in enumerate(doc.events)]
    with open(out_sup, "wb") as f:
        if jobs == 1:
            for task in tasks:
                f.write(_build_frame_task(task))
        else:
            ctx = get_context("spawn")
            with ProcessPoolExecutor(max_workers=jobs, mp_context=ctx) as ex:
                for frame in ex.map(_build_frame_task, tasks, chunksize=4):
                    f.write(frame)
    return 0


def _run_ass2sup_pipeline() -> int:
    p = argparse.ArgumentParser(
        description="ASS/SSA to SUP (embedded ass2bdnxml + bdnxml2sup)"
    )
    p.add_argument("input_ass", help="Input ASS/SSA file")
    p.add_argument("-o", "--output", required=True, help="Output SUP file")
    p.add_argument("-v", "--video-format", default="1080p")
    p.add_argument("-f", "--fps", default="23.976")
    p.add_argument("-g", "--font-dir", default=None)
    p.add_argument("-t", "--trackname", default="Undefined")
    p.add_argument("-l", "--language", default="und")
    p.add_argument("-j", "--jobs", type=int, default=max(1, (os.cpu_count() or 1)))
    p.add_argument("--keep-temp", action="store_true")
    args = p.parse_args()

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

        old_argv = sys.argv
        try:
            sys.argv = cmd1
            rc = main()
        finally:
            sys.argv = old_argv
        if rc != 0:
            return rc

        # Stage 2: bdnxml -> sup (embedded implementation)
        rc = bdnxml_to_sup(xml_tmp, args.output, max(1, args.jobs))
        if rc != 0:
            return rc
        print(f"done: {args.output}")
        return 0
    finally:
        if args.keep_temp:
            print(f"temp kept: {temp_root}", file=sys.stderr)
        else:
            shutil.rmtree(temp_root, ignore_errors=True)


def _entrypoint() -> int:
    # Renamed file ass2sup.py enters pipeline mode by default.
    # Old name ass2bdnxml.py keeps original behavior.
    name = os.path.basename(sys.argv[0]).lower()
    if name == "ass2sup.py":
        return _run_ass2sup_pipeline()
    return main()


if __name__ == "__main__":
    raise SystemExit(_entrypoint())
