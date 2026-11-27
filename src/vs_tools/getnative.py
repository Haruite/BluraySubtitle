"""Native-resolution analysis adapted from Infiziert90/getnative."""

from __future__ import annotations

import functools
import json
import math
import os
import time
from concurrent.futures import wait
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np

from src.core.i18n import translate_text
from src.exports.utils import print_terminal_line


class _KernelResult:
    def __init__(
        self,
        name: str,
        heights: List[float],
        errors: List[float],
        best_height: float,
        best_score: float,
        evaluated_all: bool,
        valley_count: int = 0,
        curve_valid: bool = True,
    ) -> None:
        self.name = name
        self.heights = heights
        self.errors = errors
        self.best_height = best_height
        self.best_score = best_score
        self.evaluated_all = evaluated_all
        self.valley_count = valley_count
        self.curve_valid = curve_valid


def format_getnative_progress(event: Dict) -> Optional[str]:
    phase = str(event.get("phase", "") or "").strip().lower()
    image = str(event.get("image", "") or "")
    kernel = str(event.get("kernel", "") or "")
    height = float(event.get("height", 0.0) or 0.0)
    score = float(event.get("score", 0.0) or 0.0)
    valid = int(bool(event.get("curve_valid", False)))
    skipped = int(bool(event.get("skipped", False)))
    if phase == "kernel":
        template = translate_text(
            "[BluraySubtitle] getnative kernel {index}/{total}: {image} - "
            "{kernel} -> {height:.2f}p score={score:.6f} valid={valid} skipped={skipped} "
            "kernel_time={kernel_seconds:.1f}s elapsed={elapsed_seconds:.1f}s "
            "eta={eta_seconds:.1f}s"
        )
        message = template.format(
            index=int(event.get("index", 0) or 0),
            total=int(event.get("total", 0) or 0),
            image=image,
            kernel=kernel,
            height=height,
            score=score,
            valid=valid,
            skipped=skipped,
            kernel_seconds=float(event.get("kernel_seconds", 0.0) or 0.0),
            elapsed_seconds=float(event.get("elapsed_seconds", 0.0) or 0.0),
            eta_seconds=float(event.get("eta_seconds", 0.0) or 0.0),
        )
    elif phase == "final":
        template = translate_text(
            "[BluraySubtitle] getnative final curve: {image} - "
            "{kernel} -> {height:.2f}p score={score:.6f} valid={valid} "
            "elapsed={elapsed_seconds:.1f}s"
        )
        message = template.format(
            image=image,
            kernel=kernel,
            height=height,
            score=score,
            valid=valid,
            elapsed_seconds=float(event.get("elapsed_seconds", 0.0) or 0.0),
        )
    else:
        return None
    return message


def _emit_getnative_progress(event: Dict, progress_jsonl: Optional[str] = None) -> None:
    if progress_jsonl is None:
        progress_jsonl = os.getenv("BLURAYSUB_GETNATIVE_PROGRESS_JSONL", "")
    if progress_jsonl:
        with open(progress_jsonl, "a", encoding="utf-8") as progress_file:
            progress_file.write(json.dumps(event, separators=(",", ":")) + "\n")
        return
    message = format_getnative_progress(event)
    if message:
        print_terminal_line(message)


def _mad(vals: Sequence[float]) -> float:
    if not vals:
        return 0.0
    arr = np.asarray(list(vals), dtype=np.float64)
    if arr.size == 0:
        return 0.0
    med = float(np.median(arr))
    return float(np.median(np.abs(arr - med)))


_REFERENCE_SOURCE_HEIGHT = 1080.0


def _height_scale(source_height: float) -> float:
    """Return a positive scale relative to the original 1080p heuristics."""
    return max(1.0, float(source_height)) / _REFERENCE_SOURCE_HEIGHT


def _is_banned_height(height: float, source_height: float = 1080.0) -> bool:
    """Reject the fixed 540p interference band and scaled unstable tail."""
    scale = _height_scale(source_height)
    value = float(height)
    # Keep this band fixed: 1080p is a common valid result for 2160p sources.
    false_positive_center = 540.0
    false_positive_radius = 5.0
    stable_curve_limit = 1040.0 * scale
    return (
        abs(value - false_positive_center) <= false_positive_radius
        or value > stable_curve_limit
    )


def _best_height_from_curve(
        heights: Sequence[float],
        vals: Sequence[float],
        source_height: float = 1080.0,
) -> Tuple[float, float, int, bool]:

    if len(vals) < 5:
        order = sorted(range(len(vals)), key=lambda n: float(vals[n]))
        i = next((
            j
            for j in order
            if not _is_banned_height(float(heights[j]), source_height)
        ), order[0])
        return float(heights[i]), 0.0, 0, False

    n_raw = len(vals)
    step_vals: List[float] = []
    for a, b in zip(heights[:-1], heights[1:]):
        try:
            dv = abs(float(b) - float(a))
        except Exception:
            dv = 0.0
        if dv > 1e-9:
            step_vals.append(dv)
    step = float(np.median(np.asarray(step_vals, dtype=np.float64))) if step_vals else 1.0
    step = max(1e-9, step)

    max_w = 11
    w_n = max(5, min(max_w, (n_raw // 120) * 2 + 5))
    if w_n % 2 == 0:
        w_n += 1
    w_span = int(round(12.0 / step))
    w_span = max(5, min(max_w, w_span))
    if w_span % 2 == 0:
        w_span += 1
    smooth_w = int(min(w_n, w_span))

    arr = np.asarray(vals, dtype=np.float64)
    kernel = np.ones(smooth_w, dtype=np.float64) / float(smooth_w)
    padded = np.pad(arr, (smooth_w // 2, smooth_w // 2), mode="edge")
    smoothed = np.convolve(padded, kernel, mode="valid").astype(np.float64).tolist()
    interior = list(range(1, len(smoothed) - 1))
    valley_idx = [
        i
        for i in interior
        if (smoothed[i] <= smoothed[i - 1] and smoothed[i] <= smoothed[i + 1])
        and (smoothed[i] < smoothed[i - 1] or smoothed[i] < smoothed[i + 1])
    ]
    if not valley_idx:
        order = sorted(range(len(vals)), key=lambda n: float(vals[n]))
        i = next((
            j
            for j in order
            if not _is_banned_height(float(heights[j]), source_height)
        ), order[0])
        return float(heights[i]), 0.0, 0, False

    n = len(smoothed)
    log_smoothed = [math.log10(max(v, 1e-12)) for v in smoothed]
    log_arr = np.asarray(log_smoothed, dtype=np.float64)

    trend_w = int(max(9, min(51, smooth_w * 5)))
    if trend_w % 2 == 0:
        trend_w += 1
    trend_kernel = np.ones(trend_w, dtype=np.float64) / float(trend_w)
    trend_padded = np.pad(log_arr, (trend_w // 2, trend_w // 2), mode="edge")
    log_trend = np.convolve(trend_padded, trend_kernel, mode="valid")
    resid = log_arr - log_trend
    dip = log_trend - log_arr
    noise = max(1e-9, _mad(resid.tolist()))
    noise_gate = 3.0 * noise
    jitter = max(1e-9, _mad(np.diff(log_arr).tolist()))
    smooth_factor = 1.0 / (1.0 + float(jitter / noise))

    height_scale = _height_scale(source_height)
    max_hv = float(max(float(x) for x in heights) or 1.0)
    tail_start = max_hv - 80.0 * height_scale
    tail_idx = [j for j, hh in enumerate(heights) if float(hh) >= tail_start]
    tail_osc = False

    body_d1_mad = max(1e-9, _mad(np.diff(resid).tolist()))
    if len(tail_idx) >= 20:
        a = int(tail_idx[0])
        b = int(tail_idx[-1]) + 1
        seg = np.asarray(resid[a:b], dtype=np.float64)

        if a >= 30:
            body_d1_mad = max(1e-9, _mad(np.diff(np.asarray(resid[:a], dtype=np.float64)).tolist()))
        dif = np.diff(seg)
        tail_d1_mad = max(1e-9, _mad(dif.tolist()))
        sgn = np.sign(dif)
        sgn = sgn[sgn != 0]
        rate = 0.0
        if sgn.size >= 8:
            changes = int(np.count_nonzero(sgn[1:] != sgn[:-1]))
            rate = float(changes) / float(max(sgn.size - 1, 1))
        if (rate >= 0.25 and tail_d1_mad >= body_d1_mad * 2.0) or (tail_d1_mad >= body_d1_mad * 3.0):
            tail_osc = True

    def _local_bad_osc(idx: int) -> bool:
        wloc = 18
        lo = max(0, idx - wloc)
        hi = min(len(resid), idx + wloc + 1)
        if hi - lo < 8:
            return False
        seg = np.asarray(resid[lo:hi], dtype=np.float64)
        dif = np.diff(seg)
        d1_mad = max(1e-9, _mad(dif.tolist()))
        sgn = np.sign(dif)
        sgn = sgn[sgn != 0]
        if sgn.size < 8:
            return False
        changes = int(np.count_nonzero(sgn[1:] != sgn[:-1]))
        rate = float(changes) / float(max(sgn.size - 1, 1))
        return bool(rate >= 0.35 and d1_mad >= body_d1_mad * 2.0)

    # Upstream getnative identifies the native-height notch from the error drop between
    # adjacent heights. Preserve that sharp signal before the broad-valley fallback below.
    raw_log = np.log10(np.maximum(arr, 1e-12))
    raw_delta = np.diff(raw_log)
    drop_noise = max(1e-9, _mad(raw_delta.tolist()))
    sharp_candidates: List[Tuple[int, float, float]] = []
    full_range_tail = (
        max_hv - float(min(float(x) for x in heights))
        >= 160.0 * height_scale
    )
    oscillation_floor = 1000.0 * height_scale
    for i in range(1, len(heights)):
        hh = float(heights[i])
        if _is_banned_height(hh, source_height):
            continue
        if full_range_tail and tail_osc and hh >= tail_start:
            continue
        if hh >= oscillation_floor and _local_bad_osc(i):
            continue
        drop = -float(raw_delta[i - 1])
        if drop < 3.0 * drop_noise:
            continue
        sharp_candidates.append((i, drop / drop_noise, drop))
    if sharp_candidates:
        sharp_max_drop = max(drop for _, _, drop in sharp_candidates)
        sharp_filtered = [
            (i, normalized_score, drop)
            for i, normalized_score, drop in sharp_candidates
            if drop >= sharp_max_drop * 0.33
        ]
        alpha = 1.2
        best_i, _, best_drop = max(
            sharp_filtered,
            key=lambda item: (
                float(item[2])
                * (max(0.0, min(1.0, float(heights[item[0]]) / max_hv)) ** alpha),
                float(item[2]),
                float(heights[item[0]]),
            ),
        )
        upstream_ratio = math.pow(10.0, float(best_drop))
        # The adjacent drop belongs to heights[i]. crop_size=5 only trims metric
        # borders and must never be applied as a fixed five-pixel height offset.
        return float(heights[best_i]), float(upstream_ratio), len(sharp_candidates), True

    def _half_width(idx: int) -> int:
        d = float(dip[idx])
        if d <= 0:
            return 1
        thr = d * 0.5
        l = idx
        while l > 0 and float(dip[l]) >= thr:
            l -= 1
        r = idx
        last = len(dip) - 1
        while r < last and float(dip[r]) >= thr:
            r += 1
        return int(max(1, r - l - 1))

    cand: List[Tuple[int, float]] = []
    for i in valley_idx:
        hh = float(heights[i])
        if _is_banned_height(hh, source_height):
            continue
        if full_range_tail and tail_osc and hh >= tail_start:
            continue
        if hh >= oscillation_floor and _local_bad_osc(i):
            continue
        d = float(dip[i])
        if d < noise_gate:
            continue
        w0 = _half_width(i)
        wloc = 14
        lo = max(0, i - wloc)
        hi = min(len(log_arr), i + wloc + 1)
        local_jitter = max(1e-9, _mad(np.diff(log_arr[lo:hi]).tolist()))
        local_factor = 1.0 / (1.0 + float(local_jitter / jitter))
        s = (d / noise) * math.sqrt(float(w0)) * smooth_factor * local_factor
        if s > 0:
            cand.append((i, s))
    if not cand:
        order = sorted(range(len(vals)), key=lambda n: float(vals[n]))
        i = next((
            j
            for j in order
            if not _is_banned_height(float(heights[j]), source_height)
        ), order[0])
        return float(heights[i]), 0.0, 0, False
    max_s = max(s for _, s in cand)
    rel_min = 0.25
    filtered = [(i, s) for i, s in cand if s >= max_s * rel_min]
    if not filtered:
        order = sorted(range(len(vals)), key=lambda n: float(vals[n]))
        i = next((
            j
            for j in order
            if not _is_banned_height(float(heights[j]), source_height)
        ), order[0])
        return float(heights[i]), 0.0, 0, False

    alpha = 1.2

    def _segment_bounds(idx: int) -> tuple[int, int]:
        l = idx
        while l > 0 and float(dip[l]) >= noise_gate:
            l -= 1
        r = idx
        last = len(dip) - 1
        while r < last and float(dip[r]) >= noise_gate:
            r += 1
        return (l + 1, r - 1)

    segments: Dict[tuple[int, int], List[Tuple[int, float]]] = {}
    for i, s in filtered:
        b = _segment_bounds(int(i))
        segments.setdefault(b, []).append((int(i), float(s)))

    def _seg_rank(item: tuple[tuple[int, int], List[Tuple[int, float]]]) -> tuple[float, float, float]:
        (l, r), xs = item
        i0, s0 = max(xs, key=lambda it: float(it[1]))
        h0 = float(heights[i0])
        hr = max(0.0, min(1.0, h0 / max_hv))
        return (float(s0) * (hr**alpha), float(s0), h0)

    (seg_l, seg_r), _ = max(segments.items(), key=_seg_rank)
    in_seg = list(range(seg_l, seg_r + 1))
    best_i = max(in_seg, key=lambda j: float(dip[j]))
    peak = float(dip[best_i])
    if peak > 0.0:
        thr = peak * 0.5
        l = best_i
        while l > seg_l and float(dip[l]) >= thr:
            l -= 1
        r = best_i
        while r < seg_r and float(dip[r]) >= thr:
            r += 1
        l = min(seg_r, max(seg_l, l + 1))
        r = min(seg_r, max(seg_l, r - 1))
        if r >= l:
            allowed = [
                j
                for j in range(l, r + 1)
                if not _is_banned_height(float(heights[j]), source_height)
            ]
            if allowed:
                best_i = min(allowed, key=lambda j: float(vals[j]))
            else:
                allowed2 = [
                    j
                    for j in range(seg_l, seg_r + 1)
                    if not _is_banned_height(float(heights[j]), source_height)
                ]
                if allowed2:
                    best_i = min(allowed2, key=lambda j: float(vals[j]))
                else:
                    return float(heights[best_i]), 0.0, len(segments), False

    best_h = float(heights[best_i])
    w0 = _half_width(best_i)
    wloc = 14
    lo = max(0, best_i - wloc)
    hi = min(len(log_arr), best_i + wloc + 1)
    local_jitter = max(1e-9, _mad(np.diff(log_arr[lo:hi]).tolist()))
    local_factor = 1.0 / (1.0 + float(local_jitter / jitter))
    best_s = (float(dip[best_i]) / float(noise)) * math.sqrt(float(max(1, w0))) * float(smooth_factor) * float(local_factor)
    upstream_ratio = (
        max(1.0, float(vals[best_i - 1]) / max(float(vals[best_i]), 1e-12))
        if best_i > 0
        else 1.0
    )
    return float(best_h), float(upstream_ratio), len(segments), bool(best_s > 0.0)


def _kernel_consensus(
    results: Sequence[_KernelResult],
    tol: float = 2.0,
    min_count: int = 2,
) -> Optional[float]:
    eligible = sorted(
        (r for r in results if r.curve_valid and r.evaluated_all),
        key=lambda r: r.best_height,
    )
    required = max(2, int(min_count))
    if len(eligible) < required:
        return None

    left = 0
    clusters: List[List[_KernelResult]] = []
    for right, result in enumerate(eligible):
        while result.best_height - eligible[left].best_height > float(tol):
            left += 1
        cluster = eligible[left : right + 1]
        if len(cluster) >= required:
            clusters.append(cluster)
    if not clusters:
        return None

    winner = max(
        clusters,
        key=lambda cluster: (
            len(cluster),
            sum(max(0.0, result.best_score) for result in cluster),
            max(result.best_height for result in cluster),
        ),
    )
    return float(sum(result.best_height for result in winner) / len(winner))


def _curve_decreasing_ratio(vals: Sequence[float]) -> float:
    if len(vals) < 2:
        return 1.0
    n = len(vals)
    w = 9 if n >= 9 else (5 if n >= 5 else 3)
    half = w // 2
    smooth: List[float] = []
    for i in range(n):
        lo = max(0, i - half)
        hi = min(n, i + half + 1)
        smooth.append(float(sum(vals[lo:hi])) / float(max(1, hi - lo)))
    arr = np.asarray(smooth, dtype=np.float64)
    if arr.size < 2:
        return 1.0
    dif = np.diff(arr)
    dec = int(np.count_nonzero(dif <= 0))
    return float(dec) / float(max(arr.size - 1, 1))


def _coarse_heights(src_heights):
    if len(src_heights) < 200:
        return []
    steps = [abs(b - a) for a, b in zip(src_heights, src_heights[1:])]
    positive_steps = [step for step in steps if step > 1e-9]
    step = float(np.median(positive_steps)) if positive_steps else 1.0
    if abs(step - 1.0) > 1e-6:
        return []
    lo = int(round(min(src_heights)))
    hi = int(round(max(src_heights)))
    coarse = list(range(lo, hi + 1, 4 if hi - lo >= 400 else 3))
    if coarse[-1] != hi:
        coarse.append(hi)
    return coarse


@dataclass
class _SampleScan:
    image: str
    clip: Any
    progress_jsonl: Optional[str] = None
    curves: list[dict] = field(default_factory=list)
    best_screen_score: float = 0.0
    completed_screens: int = 0


class _VapourSynthAnalysis:
    """Own the native graph and filter helpers for a group of compatible samples."""

    def __init__(self, input_png: str, plugin_path: str, threads: int = 1):
        import vapoursynth as vs

        self.vs = vs
        self.core = vs.core
        self.input_png = input_png
        self.core.num_threads = max(
            1, int(os.getenv("BLURAYSUB_GETNATIVE_VS_THREADS", str(threads)))
        )
        self.request_limit = max(1, min(threads, self.core.num_threads))
        self.core.max_cache_size = min(int(self.core.max_cache_size), 256)
        if plugin_path:
            self.core.std.LoadAllPlugins(plugin_path)

        # Optional filter availability is detected while muvsfunc is imported.
        from muvsfunc import measurediff, rescale

        self.measurediff = measurediff
        self.rescale = rescale
        self.clip = self._load_source_png(input_png)

    def _preset_format(self, name):
        fmt = getattr(self.vs, name, None)
        if fmt is None:
            preset = getattr(self.vs, "PresetFormat", None)
            fmt = getattr(preset, name, None) if preset is not None else None
        return fmt

    def _default_rescalers(self):
        return [
            self.rescale.Bilinear(),
            self.rescale.Bicubic(1 / 3, 1 / 3),
            self.rescale.Bicubic(0.5, 0.0),
            self.rescale.Bicubic(0.0, 0.5),
            self.rescale.Bicubic(0.0, 0.75),
            self.rescale.Bicubic(1.0, 0.0),
            self.rescale.Bicubic(0.0, 1.0),
            self.rescale.Bicubic(0.2, 0.5),
            self.rescale.Bicubic(0.5, 0.5),
            self.rescale.Lanczos(2),
            self.rescale.Lanczos(3),
            self.rescale.Lanczos(4),
            self.rescale.Lanczos(5),
            self.rescale.Spline16(),
            self.rescale.Spline36(),
            self.rescale.Spline64(),
        ]

    def _fast_rescalers(self):
        return [
            self.rescale.Bilinear(),
            self.rescale.Bicubic(1 / 3, 1 / 3),
            self.rescale.Bicubic(0.5, 0.0),
            self.rescale.Lanczos(3),
            self.rescale.Spline36(),
        ]

    def _kernel_key(self, k):
        return str(getattr(k, "name", "") or "").strip().lower()

    def _ordered_rescalers(self):
        fast = self._fast_rescalers()
        all_k = self._default_rescalers()
        out = []
        seen = set()
        for k in fast + all_k:
            key = self._kernel_key(k) or str(k)
            if key in seen:
                continue
            seen.add(key)
            out.append(k)
        return out

    def _find_kernel_by_name(self, kernels, name):
        target = str(name or "").strip().lower()
        for k in kernels:
            if self._kernel_key(k) == target:
                return k
        raise ValueError(f"unknown getnative kernel: {name}")

    def _measurediff_compat(self, clip1, clip2, ex_thr=0.015, crop_size=5):
        if not hasattr(self.vs, "GRAYS"):
            try:
                if clip1.format is not None:
                    setattr(self.vs, "GRAYS", int(clip1.format.id))
            except Exception:
                pass
        if not hasattr(self.vs, "GRAY"):
            try:
                gray_cf = getattr(getattr(self.vs, "ColorFamily", object), "GRAY", None)
                if gray_cf is not None:
                    setattr(self.vs, "GRAY", gray_cf)
            except Exception:
                pass
        return self.measurediff(clip1, clip2, ex_thr=ex_thr, crop_size=crop_size)

    def _target_dims(self, clip, target_h, base_height):
        ref_h = int(base_height or clip.height or 1)
        th = int(round(target_h))
        tw = int(round(th * clip.width / ref_h))
        th = max(2, th)
        tw = max(2, tw)
        if tw % 2:
            tw -= 1
        if th % 2:
            th -= 1
        return max(2, tw), max(2, th)

    def _rescale_without_blur_arg(self, clip, kernel, target_h, base_height):
        w, h = self._target_dims(clip, target_h, base_height)
        name = str(getattr(kernel, "name", "") or "").lower()
        taps = int(getattr(kernel, "taps", 3) or 3)
        b = float(getattr(kernel, "b", 0.0) or 0.0)
        c = float(getattr(kernel, "c", 0.5) or 0.5)

        if "lanczos" in name and hasattr(self.core.descale, "Delanczos"):
            low = self.core.descale.Delanczos(clip, w, h, taps=taps)
            return self.core.resize.Lanczos(low, clip.width, clip.height, filter_param_a=taps)
        if "bilinear" in name and hasattr(self.core.descale, "Debilinear"):
            low = self.core.descale.Debilinear(clip, w, h)
            return self.core.resize.Bilinear(low, clip.width, clip.height)
        if "spline16" in name and hasattr(self.core.descale, "Despline16"):
            low = self.core.descale.Despline16(clip, w, h)
            return self.core.resize.Spline16(low, clip.width, clip.height)
        if "spline36" in name and hasattr(self.core.descale, "Despline36"):
            low = self.core.descale.Despline36(clip, w, h)
            return self.core.resize.Spline36(low, clip.width, clip.height)
        if "spline64" in name and hasattr(self.core.descale, "Despline64"):
            low = self.core.descale.Despline64(clip, w, h)
            return self.core.resize.Spline64(low, clip.width, clip.height)
        if hasattr(self.core.descale, "Debicubic"):
            low = self.core.descale.Debicubic(clip, w, h, b=b, c=c)
            return self.core.resize.Bicubic(low, clip.width, clip.height, filter_param_a=b, filter_param_b=c)
        return self.core.resize.Bicubic(clip, clip.width, clip.height)

    def _stats_clip(self, clip, kernel, height, base_height, vertical_only, stats_func):
        try:
            if vertical_only:
                rescaled = kernel.rescale_pro(clip, src_height=height, base_height=base_height)
            else:
                rescaled = kernel.rescale(clip, height, base_height)
        except Exception as error:
            if "blur" not in str(error).lower():
                raise
            rescaled = self._rescale_without_blur_arg(clip, kernel, height, base_height)
        return stats_func(clip, rescaled)

    def _measure_error_grid(self, clip, kernel, heights, base_height, vertical_only, stats_func, stats_prop):
        errors = [[] for _ in range(clip.num_frames)]
        for start in range(0, len(heights), self.request_limit):
            nodes = [
                self._stats_clip(clip, kernel, height, base_height, vertical_only, stats_func)
                for height in heights[start:start + self.request_limit]
            ]
            if len(nodes) == 1:
                first_errors = [float(nodes[0].get_frame(0).props[stats_prop]) + 1e-9]
            else:
                # Initialize independent filters in parallel before requesting other
                # frames at each height. Keep at most one window of graphs alive.
                pending = [node.get_frame_async(0) for node in nodes]
                wait(pending)
                first_errors = [float(future.result().props[stats_prop]) + 1e-9 for future in pending]
                del pending
            for node, first_error in zip(nodes, first_errors):
                errors[0].append(first_error)
                for frame_index in range(1, clip.num_frames):
                    error = float(node.get_frame(frame_index).props[stats_prop]) + 1e-9
                    errors[frame_index].append(error)
        return errors

    def _coarse_clip(self, clip):
        width = max(64, (int(clip.width) // 2) // 2 * 2)
        height = max(64, (int(clip.height) // 2) // 2 * 2)
        return self.core.std.CropAbs(
            clip,
            width=width,
            height=height,
            left=max(0, (int(clip.width) - width) // 2),
            top=max(0, (int(clip.height) - height) // 2),
        )

    def _collect_curve_for_kernel(
        self,
        clip,
        source_height,
        kernel,
        src_heights,
        base_height,
        vertical_only,
        stats_func,
        stats_prop,
        early_stop_patience,
        global_best_score,
        two_stage=False,
        coarse_half_size=True,
        coarse_errors=None,
    ):
        coarse = _coarse_heights(src_heights) if two_stage else []
        if coarse:
            if coarse_errors is None:
                coarse_clip = self._coarse_clip(clip) if coarse_half_size else clip
                scale = float(coarse_clip.height) / float(max(1, int(clip.height)))
                scaled_base = float(base_height) * scale if base_height is not None else None
                coarse_errors = self._measure_error_grid(
                    coarse_clip, kernel, [h * scale for h in coarse], scaled_base,
                    vertical_only, stats_func, stats_prop,
                )[0]
            coarse_heights = [float(h) for h in coarse]
            coarse_best_h, coarse_best_s, _, coarse_valid = _best_height_from_curve(
                coarse_heights, coarse_errors, source_height,
            )
            if global_best_score > 0.0 and coarse_valid and coarse_best_s < global_best_score * 0.45:
                return {
                    "kernel": str(getattr(kernel, "name", "") or ""),
                    "heights": coarse_heights,
                    "errors": coarse_errors,
                    "evaluated_all": False,
                    "screen_score": float(coarse_best_s),
                    "screen_valid": bool(coarse_valid),
                    "skipped": True,
                    "source_height": int(source_height),
                }

            center = int(round(float(coarse_best_h)))
            fine = list(range(max(coarse[0], center - 20), min(coarse[-1], center + 20) + 1))
            errors = self._measure_error_grid(
                clip, kernel, fine, base_height, vertical_only, stats_func, stats_prop,
            )[0]
            return {
                "kernel": str(getattr(kernel, "name", "") or ""),
                "heights": [float(h) for h in fine],
                "errors": errors,
                "evaluated_all": True,
                "screen_score": float(coarse_best_s),
                "screen_valid": bool(coarse_valid),
                "skipped": False,
                "source_height": int(source_height),
            }

        heights = []
        errors = []
        best_local_score = -1.0
        stagnation = 0
        evaluated_all = True
        early_stop_enabled = int(early_stop_patience) < len(src_heights)

        for h in src_heights:
            stats = self._stats_clip(clip, kernel, h, base_height, vertical_only, stats_func)
            val = float(stats.get_frame(0).props[stats_prop]) + 1e-9
            heights.append(float(h))
            errors.append(val)

            if early_stop_enabled and len(errors) >= 3:
                _, cand_s, _, _ = _best_height_from_curve(
                    heights,
                    errors,
                    source_height,
                )
                if cand_s > best_local_score:
                    best_local_score = cand_s
                    stagnation = 0
                else:
                    stagnation += 1
            if early_stop_enabled and len(errors) >= 20 and stagnation >= int(early_stop_patience):
                if global_best_score > 0 and best_local_score < global_best_score * 0.60:
                    evaluated_all = False
                    break

        return {
            "kernel": str(getattr(kernel, "name", "") or ""),
            "heights": heights,
            "errors": errors,
            "evaluated_all": bool(evaluated_all),
            "source_height": int(source_height),
        }

    def _load_source_png(self, path):
        src = None
        imwri = getattr(self.core, "imwri", getattr(self.core, "imwrif", None))
        if imwri is not None and hasattr(imwri, "Read"):
            try:
                src = imwri.Read(path)
            except Exception:
                src = None
        if src is None and hasattr(self.core, "lsmas"):
            try:
                try:
                    src = self.core.lsmas.LWLibavSource(path, cache=0)
                except TypeError:
                    src = self.core.lsmas.LWLibavSource(path)
            except Exception:
                src = None
        if src is None:
            raise RuntimeError("failed to load image source: need imwri/imwrif Read or lsmas")

        if src.format is None:
            raise RuntimeError("image source has a variable format")
        rgb_cf = getattr(self.vs, "RGB", None)
        if rgb_cf is None:
            rgb_cf = getattr(getattr(self.vs, "ColorFamily", object), "RGB", 2)
        if src.format.color_family == rgb_cf:
            yuv444ps = self._preset_format("YUV444PS")
            if yuv444ps is None:
                raise RuntimeError("Could not resolve YUV444PS format for RGB-to-luma conversion")
            src = self.core.resize.Point(src, format=yuv444ps, matrix_s="709")

        gray_cf = getattr(self.vs, "GRAY", None)
        if gray_cf is None:
            gray_cf = getattr(getattr(self.vs, "ColorFamily", object), "GRAY", 1)
        clip = self.core.std.ShufflePlanes(src, 0, gray_cf)
        gray_fmt = self._preset_format("GRAYS")
        if gray_fmt is None:
            raise RuntimeError("Could not resolve GRAYS format for getnative")
        clip = clip.resize.Point(format=gray_fmt)
        return clip[0]

    def _list_kernels_mode(self, params):
        fast_mode = bool(params.get("fast_mode", False))
        kernels = self._default_rescalers() if not fast_mode else self._ordered_rescalers()
        return {"kernels": [str(getattr(k, "name", "") or "") for k in kernels]}

    def _collect_curve_mode(self, clip, params, coarse_errors=None):
        fast_mode = bool(params.get("fast_mode", False))
        kernels = self._default_rescalers() if not fast_mode else self._ordered_rescalers()
        kernel_name = str(params.get("kernel_name", "") or "").strip()
        kernel = self._find_kernel_by_name(kernels, kernel_name) if kernel_name else kernels[0]
        source_height = int(clip.height)
        src_heights = params.get("src_heights")
        if not src_heights:
            minimum = max(240, int(source_height * 0.40))
            maximum = min(source_height - 2, int(source_height * 0.98))
            if minimum >= maximum:
                raise ValueError(
                    f"invalid source height search range: {minimum}..{maximum} "
                    f"for {source_height}p"
                )
            src_heights = list(range(minimum, maximum + 1))
        if isinstance(src_heights, (int, float)):
            height_list = (float(src_heights),)
        else:
            height_list = tuple(float(h) for h in src_heights)
        stats_func = functools.partial(
            self._measurediff_compat,
            ex_thr=float(params.get("ex_thr", 0.015)),
            crop_size=int(params.get("crop_size", 5)),
        )
        return self._collect_curve_for_kernel(
            clip=clip,
            source_height=source_height,
            kernel=kernel,
            src_heights=height_list,
            base_height=params.get("base_height", None),
            vertical_only=bool(params.get("vertical_only", False)),
            stats_func=stats_func,
            stats_prop=str(params.get("stats_prop", "PlaneDiffMeasure")),
            early_stop_patience=int(params.get("early_stop_patience", 30)),
            global_best_score=float(params.get("global_best_score", 0.0)),
            two_stage=bool(params.get("two_stage", False)),
            coarse_half_size=bool(params.get("coarse_half_size", True)),
            coarse_errors=coarse_errors,
        )

    def _collect_curves_mode(self, clip, params):
        sample = _SampleScan(self.input_png, clip)
        self._collect_sample_curves([sample], params)
        return {"curves": sample.curves}

    def _collect_sample_curves(self, samples, params):
        fast_mode = bool(params.get("fast_mode", False))
        kernels = self._default_rescalers() if not fast_mode else self._ordered_rescalers()
        limit = int(params.get("max_kernels", 0))
        if limit > 0:
            kernels = kernels[:limit]
        coarse = []
        if len(samples) > 1 and params.get("two_stage") and params.get("coarse_half_size", True):
            coarse = _coarse_heights(params["src_heights"])
        if coarse:
            # Splicing keeps the source frame identity while sharing the filters
            # and their initialized geometry for each candidate height.
            coarse_clip = self._coarse_clip(self.core.std.Splice([sample.clip for sample in samples]))
            scale = coarse_clip.height / samples[0].clip.height
            heights = [h * scale for h in coarse]
            base = params.get("base_height")
            scaled_base = float(base) * scale if base is not None else None
            stats_func = functools.partial(
                self._measurediff_compat,
                ex_thr=float(params.get("ex_thr", 0.015)),
                crop_size=int(params.get("crop_size", 5)),
            )
            stats_prop = str(params.get("stats_prop", "PlaneDiffMeasure"))

        total = len(kernels)
        scan_started = time.perf_counter()
        for index, kernel in enumerate(kernels, start=1):
            kernel_started = time.perf_counter()
            kernel_params = dict(params)
            kernel_params["kernel_name"] = str(getattr(kernel, "name", "") or "")
            shared_errors = self._measure_error_grid(
                coarse_clip, kernel, heights, scaled_base, bool(params.get("vertical_only", False)),
                stats_func, stats_prop,
            ) if coarse else [None] * len(samples)
            for sample, errors in zip(samples, shared_errors, strict=True):
                # Each frame screens its kernels against its own earlier coarse curves.
                kernel_params["global_best_score"] = (
                    sample.best_screen_score if sample.completed_screens >= 3 else 0.0
                )
                curve = self._collect_curve_mode(sample.clip, kernel_params, coarse_errors=errors)
                sample.curves.append(curve)
                if bool(curve.get("screen_valid", False)):
                    sample.completed_screens += 1
                    sample.best_screen_score = max(
                        sample.best_screen_score,
                        float(curve.get("screen_score", 0.0) or 0.0),
                    )
                best_h, best_s, _, curve_valid = _best_height_from_curve(
                    curve.get("heights", []),
                    curve.get("errors", []),
                    float(curve.get("source_height") or sample.clip.height),
                )
                elapsed_seconds = time.perf_counter() - scan_started
                _emit_getnative_progress(
                    {
                        "phase": "kernel",
                        "index": index,
                        "total": total,
                        "image": os.path.basename(sample.image),
                        "kernel": str(curve.get("kernel", "") or ""),
                        "height": float(best_h),
                        "score": float(best_s),
                        "curve_valid": bool(curve_valid and curve.get("evaluated_all", True)),
                        "skipped": bool(curve.get("skipped", False)),
                        "kernel_seconds": float(time.perf_counter() - kernel_started),
                        "elapsed_seconds": float(elapsed_seconds),
                        "eta_seconds": float((elapsed_seconds / index) * (total - index)),
                    },
                    sample.progress_jsonl,
                )


def _default_src_heights(input_png: str) -> tuple[float, ...]:
    """Build the default proportional search range from the actual source image."""
    from PIL import Image

    with Image.open(input_png) as image:
        source_height = int(image.height)
    minimum = max(240, int(source_height * 0.40))
    maximum = min(source_height - 2, int(source_height * 0.98))
    if minimum >= maximum:
        raise ValueError(
            f"invalid source height search range: {minimum}..{maximum} "
            f"for {source_height}p"
        )
    return tuple(float(height) for height in range(minimum, maximum + 1))


def getnative(
    clip,
    rescalers=None,
    src_heights: Optional[
        Union[int, float, Sequence[int], Sequence[float]]
    ] = None,
    base_height: Optional[int] = None,
    crop_size: int = 5,
    dark: bool = True,
    ex_thr: float = 0.015,
    filename: Optional[str] = None,
    debug_dir: Optional[str] = None,
    vertical_only: bool = False,
    stats_func=None,
    stats_prop: str = "PlaneDiffMeasure",
    *,
    early_stop_patience: int = 30,
    consensus_quit: bool = True,
    consensus_min_kernels: int = 3,
    fast_mode: bool = False,
    score_quit: float = 0.0,
    score_margin: float = 1.25,
    min_kernels: int = 4,
    max_kernels: int = 0,
    debug_full_scan: bool = False,
    plugin_path: Optional[str] = None,
):
    if stats_func is not None:
        raise ValueError("stats_func override is not supported")
    if rescalers is not None:
        raise ValueError("custom rescalers are not supported")
    if not isinstance(clip, (str, Path)):
        raise TypeError("getnative expects a PNG path as the clip argument")

    input_png = str(clip)
    if not os.path.isfile(input_png):
        raise FileNotFoundError(input_png)
    if plugin_path is None:
        from src.core.tool_paths import tool_path

        plugin_path = tool_path("PLUGIN_PATH")
    native = _VapourSynthAnalysis(input_png, plugin_path)
    if src_heights is None:
        height_list = _default_src_heights(input_png)
    elif isinstance(src_heights, (int, float)):
        height_list = (float(src_heights),)
    else:
        height_list = tuple(float(h) for h in src_heights)
    if not height_list:
        raise ValueError("src_heights cannot be empty.")

    full_scan = bool(debug_dir) and bool(debug_full_scan)
    consensus_min = int(consensus_min_kernels)
    if fast_mode and consensus_min_kernels == 3:
        consensus_min = 2

    batch_all_kernels = bool(
        fast_mode
        and not full_scan
        and not score_quit
        and not consensus_quit
        and int(max_kernels) > 0
        and int(min_kernels) >= int(max_kernels)
    )
    batched_curves = None
    if batch_all_kernels:
        curve_response = native._collect_curves_mode(
            native.clip,
            {
                "fast_mode": True,
                "max_kernels": int(max_kernels),
                "src_heights": list(height_list),
                "base_height": base_height,
                "vertical_only": bool(vertical_only),
                "ex_thr": float(ex_thr),
                "crop_size": int(crop_size),
                "stats_prop": str(stats_prop),
                "early_stop_patience": int(early_stop_patience),
                "global_best_score": 0.0,
                "two_stage": True,
            },
        )
        batched_curves = list(curve_response.get("curves") or [])
        kernel_names = [str(curve.get("kernel", "") or "") for curve in batched_curves]
    else:
        kernel_resp = native._list_kernels_mode({"fast_mode": bool(fast_mode)})
        kernel_names = list(kernel_resp.get("kernels") or [])
    if not kernel_names:
        raise RuntimeError("no rescaling kernels are available")

    results: List[_KernelResult] = []
    global_best = -1.0
    for kernel_index, kernel_name in enumerate(kernel_names):
        if batched_curves is not None:
            curve = batched_curves[kernel_index]
        else:
            curve = native._collect_curve_mode(
                native.clip,
                {
                    "kernel_name": kernel_name,
                    "src_heights": list(height_list),
                    "base_height": base_height,
                    "vertical_only": bool(vertical_only),
                    "ex_thr": float(ex_thr),
                    "crop_size": int(crop_size),
                    "stats_prop": str(stats_prop),
                    "early_stop_patience": int(10**9 if full_scan else early_stop_patience),
                    "global_best_score": float(0.0 if full_scan else global_best),
                    "two_stage": bool(not full_scan),
                },
            )
        kr = _kernel_result(kernel_name, curve)
        if kr is None:
            continue
        results.append(kr)
        if kr.curve_valid and kr.evaluated_all:
            global_best = max(global_best, kr.best_score)
        if max_kernels and len(results) >= int(max_kernels):
            break
        if not full_scan and len(results) >= max(1, int(min_kernels)):
            eligible = [r for r in results if r.curve_valid and r.evaluated_all]
            best = max((float(r.best_score) for r in eligible), default=0.0)
            second = max([float(r.best_score) for r in eligible if float(r.best_score) < best] or [0.0])
            if score_quit and best >= float(score_quit) and (second <= 0.0 or best >= second * float(score_margin)):
                break
        if (
            (not full_scan)
            and consensus_quit
            and len(results) >= max(max(1, int(min_kernels)), consensus_min)
        ):
            if _kernel_consensus(results, min_count=consensus_min) is not None:
                break

    result = _verify_getnative(
        native,
        _SampleScan(input_png, native.clip),
        results,
        {
            "src_heights": list(height_list),
            "base_height": base_height,
            "vertical_only": bool(vertical_only),
            "ex_thr": float(ex_thr),
            "crop_size": int(crop_size),
            "stats_prop": str(stats_prop),
        },
    )
    result.update(debug_dir=debug_dir, filename=filename, dark=dark)
    return result


def _kernel_result(kernel_name, curve):
    heights = [float(x) for x in curve.get("heights", [])]
    errors = [float(x) for x in curve.get("errors", [])]
    if not heights or not errors:
        return None
    best_h, best_s, valley_count, curve_valid = _best_height_from_curve(
        heights, errors, float(curve.get("source_height") or _REFERENCE_SOURCE_HEIGHT),
    )
    return _KernelResult(
        name=str(kernel_name),
        heights=heights,
        errors=errors,
        best_height=best_h,
        best_score=best_s,
        evaluated_all=bool(curve.get("evaluated_all", True)),
        valley_count=int(valley_count),
        curve_valid=bool(curve_valid),
    )


def _verify_getnative(native, sample, results, params):
    if not results:
        raise RuntimeError("no getnative curve data collected")
    valid_results = [r for r in results if r.curve_valid and r.evaluated_all]
    winner0 = max(valid_results, key=lambda r: (r.best_score, r.best_height)) if valid_results else min(
        results, key=lambda r: (min(r.errors), r.best_height)
    )

    final_started = time.perf_counter()
    final_curve = native._collect_curve_mode(
        sample.clip,
        {
            **params,
            "kernel_name": winner0.name,
            "early_stop_patience": int(10**9),
            "global_best_score": 0.0,
            # Recheck the winning kernel on a full-frame step-4 curve, then retain
            # its full-frame 1p ±20 neighborhood. This preserves exact heights while
            # avoiding a second 627-point full-resolution pass and its cache peak.
            "two_stage": True,
            "coarse_half_size": False,
        },
    )
    wh = [float(x) for x in final_curve.get("heights", [])]
    we = [float(x) for x in final_curve.get("errors", [])]
    if not wh or not we or len(wh) != len(we):
        raise RuntimeError("winner getnative curve is empty or malformed")
    final_source_height = float(
        final_curve.get("source_height") or _REFERENCE_SOURCE_HEIGHT
    )
    w_best_h, w_best_s, w_valley_count, w_curve_valid = _best_height_from_curve(
        wh,
        we,
        final_source_height,
    )
    best_idx = min(range(len(wh)), key=lambda i: abs(float(wh[i]) - float(w_best_h)))
    edge_hit = int(best_idx <= 1 or best_idx >= len(wh) - 2)
    dec_ratio = _curve_decreasing_ratio(we)
    curve_valid = int(bool(w_curve_valid) and (edge_hit == 0))
    curve_valid_strict = int(bool(curve_valid) and (dec_ratio < 0.80))

    _emit_getnative_progress({
        "phase": "final",
        "image": os.path.basename(sample.image),
        "kernel": str(winner0.name),
        "height": float(w_best_h),
        "score": float(w_best_s),
        "curve_valid": bool(w_curve_valid),
        "elapsed_seconds": time.perf_counter() - final_started,
    }, sample.progress_jsonl)
    return {
        "getnative_kernel": str(winner0.name),
        "getnative_height": float(w_best_h),
        "getnative_score": float(w_best_s),
        "getnative_curve_valid": int(curve_valid),
        "getnative_curve_valid_strict": int(curve_valid_strict),
        "getnative_edge_hit": int(edge_hit),
        "getnative_decreasing_ratio": float(dec_ratio),
        "getnative_valley_count": int(w_valley_count),
        "getnative_source_height": int(round(final_source_height)),
    }


def getnative_batch(
    image_progress: dict[str, Optional[str]],
    *,
    src_heights: Sequence[float],
    plugin_path: str,
    threads: int = 1,
) -> dict[str, dict]:
    """Scan the same heights for samples from one source geometry."""
    if not image_progress:
        return {}
    first_image = next(iter(image_progress))
    native = _VapourSynthAnalysis(first_image, plugin_path, threads)
    samples = [
        _SampleScan(image, native.clip if image == first_image else native._load_source_png(image), progress)
        for image, progress in image_progress.items()
    ]
    params = {
        "src_heights": tuple(float(height) for height in src_heights),
        "fast_mode": True,
        "max_kernels": 16,
        "two_stage": True,
    }
    native._collect_sample_curves(samples, params)
    results = {}
    for sample in samples:
        scored = [
            value for curve in sample.curves
            if (value := _kernel_result(curve["kernel"], curve)) is not None
        ]
        results[sample.image] = _verify_getnative(native, sample, scored, params)
    return results
