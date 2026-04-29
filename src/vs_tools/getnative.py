"""Optimized getnative helper for BluraySubtitle.

Usage:
    from src.getnative import getnative
"""

from __future__ import annotations

import functools
import json
import math
import os
import re
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np
import vapoursynth as vs
from muvsfunc import core, measurediff, rescale

GRAY_FORMAT_ID = getattr(vs, "GRAYS", None)


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


def _default_rescalers() -> List[rescale.Rescaler]:
    return [
        rescale.Bilinear(),
        # Bicubic family (8)
        rescale.Bicubic(1 / 3, 1 / 3),
        rescale.Bicubic(0.5, 0.0),
        rescale.Bicubic(0.0, 0.5),
        rescale.Bicubic(0.0, 0.75),
        rescale.Bicubic(1.0, 0.0),
        rescale.Bicubic(0.0, 1.0),
        rescale.Bicubic(0.2, 0.5),
        rescale.Bicubic(0.5, 0.5),
        # Lanczos family (4)
        rescale.Lanczos(2),
        rescale.Lanczos(3),
        rescale.Lanczos(4),
        rescale.Lanczos(5),
        # Spline family (3)
        rescale.Spline16(),
        rescale.Spline36(),
        rescale.Spline64(),
    ]


def _fast_rescalers() -> List[rescale.Rescaler]:
    return [
        rescale.Bilinear(),
        rescale.Bicubic(1 / 3, 1 / 3),
        rescale.Bicubic(0.5, 0.0),
        rescale.Lanczos(3),
        rescale.Spline36(),
    ]


def _kernel_key(k: rescale.Rescaler) -> str:
    return str(getattr(k, "name", "") or "").strip().lower()


def _ordered_rescalers() -> List[rescale.Rescaler]:
    fast = _fast_rescalers()
    all_k = _default_rescalers()
    out: List[rescale.Rescaler] = []
    seen: set[str] = set()
    for k in fast + all_k:
        key = _kernel_key(k) or str(k)
        if key in seen:
            continue
        seen.add(key)
        out.append(k)
    return out


def _find_kernel_by_name(kernels: Sequence[rescale.Rescaler], name: str) -> rescale.Rescaler:
    target = str(name or "").strip().lower()
    for k in kernels:
        if _kernel_key(k) == target:
            return k
    return kernels[0]


def _measurediff_compat(
    clip1: vs.VideoNode,
    clip2: vs.VideoNode,
    *,
    ex_thr: float = 0.015,
    crop_size: int = 5,
) -> vs.VideoNode:
    # Prefer original muvsfunc.measurediff for result parity.
    # In some VS builds, constants like vs.GRAYS are missing; patch minimal aliases.
    if not hasattr(vs, "GRAYS"):
        try:
            if clip1.format is not None:
                setattr(vs, "GRAYS", int(clip1.format.id))
        except Exception:
            pass
    if not hasattr(vs, "GRAY"):
        try:
            gray_cf = getattr(getattr(vs, "ColorFamily", object), "GRAY", None)
            if gray_cf is not None:
                setattr(vs, "GRAY", gray_cf)
        except Exception:
            pass
    return measurediff(clip1, clip2, ex_thr=ex_thr, crop_size=crop_size)


def _valley_score(vals: Sequence[float], idx: int) -> float:
    if idx <= 0 or idx >= len(vals) - 1:
        return 0.0
    a = max(vals[idx - 1], 1e-12)
    b = max(vals[idx], 1e-12)
    c = max(vals[idx + 1], 1e-12)
    return math.log10(a) + math.log10(c) - 2.0 * math.log10(b)


def _valley_prominence(log_vals: Sequence[float], idx: int, window: int) -> float:
    if idx <= 0 or idx >= len(log_vals) - 1:
        return 0.0
    n = len(log_vals)
    w = max(2, int(window))
    left = log_vals[max(0, idx - w) : idx]
    right = log_vals[idx + 1 : min(n, idx + w + 1)]
    if not left or not right:
        return 0.0
    ref = min(max(left), max(right))
    return max(0.0, float(ref - log_vals[idx]))


def _mad(vals: Sequence[float]) -> float:
    if not vals:
        return 0.0
    arr = np.asarray(list(vals), dtype=np.float64)
    if arr.size == 0:
        return 0.0
    med = float(np.median(arr))
    return float(np.median(np.abs(arr - med)))


def _smooth_curve(vals: Sequence[float]) -> List[float]:
    n = len(vals)
    if n < 5:
        return [float(v) for v in vals]
    # Adaptive odd window: mild smoothing for noisy monotonic curves.
    w = max(5, min(21, (n // 60) * 2 + 5))
    if w % 2 == 0:
        w += 1
    half = w // 2
    arr = np.asarray(vals, dtype=np.float64)
    kernel = np.ones(w, dtype=np.float64) / float(w)
    # Edge padding keeps boundary behavior stable.
    padded = np.pad(arr, (half, half), mode="edge")
    smoothed = np.convolve(padded, kernel, mode="valid")
    return smoothed.astype(np.float64).tolist()


def _best_height_from_curve(heights: Sequence[float], vals: Sequence[float]) -> Tuple[float, float, int, bool]:
    def _is_banned_height(h: float) -> bool:
        hh = float(h)
        if abs(hh - 540.0) <= 5.0:
            return True
        return False

    if len(vals) < 5:
        order = sorted(range(len(vals)), key=lambda n: float(vals[n]))
        i = next((j for j in order if not _is_banned_height(float(heights[j]))), order[0])
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
        i = next((j for j in order if not _is_banned_height(float(heights[j]))), order[0])
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

    max_hv = float(max(float(x) for x in heights) or 1.0)
    tail_start = max_hv - 80.0
    tail_idx = [j for j, hh in enumerate(heights) if float(hh) >= tail_start]
    tail_osc = False
    body_noise = noise
    body_d1_mad = max(1e-9, _mad(np.diff(resid).tolist()))
    if len(tail_idx) >= 20:
        a = int(tail_idx[0])
        b = int(tail_idx[-1]) + 1
        seg = np.asarray(resid[a:b], dtype=np.float64)
        if a >= 30:
            body_noise = max(1e-9, _mad(np.asarray(resid[:a], dtype=np.float64).tolist()))
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
        if _is_banned_height(hh):
            continue
        if tail_osc and hh >= tail_start:
            continue
        if hh >= 1000.0 and _local_bad_osc(i):
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
            cand.append((i, float(s)))

    if not cand:
        order = sorted(range(len(vals)), key=lambda n: float(vals[n]))
        i = next((j for j in order if not _is_banned_height(float(heights[j]))), order[0])
        return float(heights[i]), 0.0, 0, False

    max_s = max(s for _, s in cand)
    rel_min = 0.25
    filtered = [(i, s) for i, s in cand if s >= max_s * rel_min]
    if not filtered:
        order = sorted(range(len(vals)), key=lambda n: float(vals[n]))
        i = next((j for j in order if not _is_banned_height(float(heights[j]))), order[0])
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

    (seg_l, seg_r), seg_items = max(segments.items(), key=_seg_rank)
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
            allowed = [j for j in range(l, r + 1) if not _is_banned_height(float(heights[j]))]
            if allowed:
                best_i = min(allowed, key=lambda j: float(vals[j]))
            else:
                allowed2 = [j for j in range(seg_l, seg_r + 1) if not _is_banned_height(float(heights[j]))]
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
    return float(best_h), float(best_s), len(segments), True


def _kernel_consensus(results: Sequence[_KernelResult], tol: float = 2.0) -> Optional[float]:
    if len(results) < 2:
        return None
    buckets: Dict[int, List[float]] = {}
    for r in results:
        key = int(round(r.best_height))
        buckets.setdefault(key, []).append(r.best_height)
    best_key, best_vals = max(buckets.items(), key=lambda kv: len(kv[1]))
    if len(best_vals) >= 2 and max(abs(v - best_key) for v in best_vals) <= tol:
        return float(sum(best_vals) / len(best_vals))
    return None


def _curve_decreasing_ratio(vals: Sequence[float]) -> float:
    if len(vals) < 2:
        return 1.0
    # Smooth first to suppress tiny jitter causing false non-monotonic detections.
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


def _save_auto_plot(results: Sequence[_KernelResult], filename: Optional[str], dark: bool = True) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    if dark:
        plt.style.use("dark_background")
    fig, ax = plt.subplots(figsize=(12, 8))
    fig.set_tight_layout(True)
    for r in results:
        ax.plot(r.heights, r.errors, label=f"{r.name} -> {r.best_height:.2f}p")
    ax.set(xlabel="Height", ylabel="Relative error", yscale="log", title="auto_getnative")
    ax.legend(fontsize=8)
    out = filename or f"auto_getnative_{os.getpid()}.png"
    fig.savefig(out)
    plt.close(fig)

    txt_path = Path(out).with_suffix(".txt")
    with txt_path.open("w", encoding="utf-8") as f:
        for r in results:
            f.write(
                f"[{r.name}] best={r.best_height:.3f} score={r.best_score:.6f} "
                f"evaluated_all={r.evaluated_all}\n"
            )


def _safe_stem(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", str(name or "").strip())
    s = s.strip("._-")
    return s or "kernel"


_PLOT_BACKEND_READY = False


def _get_plt():
    global _PLOT_BACKEND_READY
    import matplotlib

    if not _PLOT_BACKEND_READY:
        matplotlib.use("Agg")
        _PLOT_BACKEND_READY = True
    import matplotlib.pyplot as plt

    return plt


def _save_kernel_plot(out_png: str, r: _KernelResult, dark: bool = True) -> None:
    plt = _get_plt()

    if dark:
        plt.style.use("dark_background")
    fig, ax = plt.subplots(figsize=(12, 8))
    fig.set_tight_layout(True)
    ax.plot(r.heights, r.errors, label=r.name)
    ax.axvline(float(r.best_height), color="cyan", linewidth=1.0, linestyle="--")
    ax.set(xlabel="Height", ylabel="Relative error", yscale="log", title="getnative_curve")
    ax.legend(fontsize=8)
    fig.savefig(out_png)
    plt.close(fig)


def _save_kernel_debug(out_dir: str, r: _KernelResult, dark: bool = True) -> None:
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    stem = _safe_stem(r.name)
    out_json = str(Path(out_dir) / f"{stem}.json")
    out_png = str(Path(out_dir) / f"{stem}.png")
    payload = {
        "kernel": r.name,
        "heights": [float(x) for x in r.heights],
        "errors": [float(x) for x in r.errors],
        "best_height": float(r.best_height),
        "best_score": float(r.best_score),
        "valley_count": int(r.valley_count),
        "curve_valid": bool(r.curve_valid),
        "evaluated_all": bool(r.evaluated_all),
    }
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    _save_kernel_plot(out_png, r, dark=dark)


def _dump_debug_dir(results: Sequence[_KernelResult], out_dir: str, dark: bool = True) -> None:
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    for r in results:
        _save_kernel_debug(out_dir, r, dark=dark)


def _target_dims(clip: vs.VideoNode, target_h: float, base_height: Optional[int]) -> Tuple[int, int]:
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


def _rescale_without_blur_arg(
    clip: vs.VideoNode,
    kernel: rescale.Rescaler,
    target_h: float,
    base_height: Optional[int],
) -> vs.VideoNode:
    # Descale plugin API (README) has no `blur` parameter; call plugin directly.
    w, h = _target_dims(clip, target_h, base_height)
    name = str(getattr(kernel, "name", "") or "").lower()
    taps = int(getattr(kernel, "taps", 3) or 3)
    b = float(getattr(kernel, "b", 0.0) or 0.0)
    c = float(getattr(kernel, "c", 0.5) or 0.5)

    if "lanczos" in name and hasattr(core.descale, "Delanczos"):
        low = core.descale.Delanczos(clip, w, h, taps=taps)
        up = core.resize.Lanczos(low, clip.width, clip.height, filter_param_a=taps)
    elif "bilinear" in name and hasattr(core.descale, "Debilinear"):
        low = core.descale.Debilinear(clip, w, h)
        up = core.resize.Bilinear(low, clip.width, clip.height)
    elif "spline16" in name and hasattr(core.descale, "Despline16"):
        low = core.descale.Despline16(clip, w, h)
        up = core.resize.Spline16(low, clip.width, clip.height)
    elif "spline36" in name and hasattr(core.descale, "Despline36"):
        low = core.descale.Despline36(clip, w, h)
        up = core.resize.Spline36(low, clip.width, clip.height)
    elif "spline64" in name and hasattr(core.descale, "Despline64"):
        low = core.descale.Despline64(clip, w, h)
        up = core.resize.Spline64(low, clip.width, clip.height)
    elif hasattr(core.descale, "Debicubic"):
        low = core.descale.Debicubic(clip, w, h, b=b, c=c)
        up = core.resize.Bicubic(low, clip.width, clip.height, filter_param_a=b, filter_param_b=c)
    else:
        # Last fallback: no descale plugin path available for this kernel.
        up = core.resize.Bicubic(clip, clip.width, clip.height)

    return up


def _collect_curve_for_kernel(
    clip: vs.VideoNode,
    kernel: rescale.Rescaler,
    src_heights: Sequence[float],
    base_height: Optional[int],
    vertical_only: bool,
    stats_func: Callable[[vs.VideoNode, vs.VideoNode], vs.VideoNode],
    stats_prop: str,
    early_stop_patience: int,
    global_best_score: float,
    *,
    two_stage: bool = False,
) -> _KernelResult:
    if two_stage:
        hs = [float(x) for x in src_heights]
        if len(hs) >= 200:
            step_vals: List[float] = []
            for a, b in zip(hs[:-1], hs[1:]):
                dv = abs(float(b) - float(a))
                if dv > 1e-9:
                    step_vals.append(dv)
            step = float(np.median(np.asarray(step_vals, dtype=np.float64))) if step_vals else 1.0
            if abs(step - 1.0) <= 1e-6:
                lo = int(round(min(hs)))
                hi = int(round(max(hs)))
                coarse_step = 4 if (hi - lo) >= 400 else 3
                coarse = list(range(lo, hi + 1, coarse_step))
                if coarse[-1] != hi:
                    coarse.append(hi)

                ch: List[float] = []
                ce: List[float] = []
                for h in coarse:
                    try:
                        if not vertical_only:
                            rescaled = kernel.rescale(clip, h, base_height)  # type: ignore[arg-type]
                        else:
                            rescaled = kernel.rescale_pro(clip, src_height=h, base_height=base_height)  # type: ignore[arg-type]
                    except Exception as e:
                        if "blur" in str(e).lower():
                            rescaled = _rescale_without_blur_arg(clip, kernel, h, base_height)
                        else:
                            raise
                    stats = stats_func(clip, rescaled)
                    fr = stats.get_frame(0)
                    val = float(fr.props[stats_prop]) + 1e-9
                    ch.append(float(h))
                    ce.append(val)

                coarse_best_h, coarse_best_s, coarse_vc, coarse_ok = _best_height_from_curve(ch, ce)
                if global_best_score > 0 and coarse_best_s < global_best_score * 0.60:
                    return _KernelResult(kernel.name, ch, ce, coarse_best_h, coarse_best_s, False, coarse_vc, False)
                center = int(round(float(coarse_best_h)))
                radius = 20
                rlo = max(lo, center - radius)
                rhi = min(hi, center + radius)
                fine = list(range(rlo, rhi + 1))

                fh: List[float] = []
                fe: List[float] = []
                for h in fine:
                    try:
                        if not vertical_only:
                            rescaled = kernel.rescale(clip, h, base_height)  # type: ignore[arg-type]
                        else:
                            rescaled = kernel.rescale_pro(clip, src_height=h, base_height=base_height)  # type: ignore[arg-type]
                    except Exception as e:
                        if "blur" in str(e).lower():
                            rescaled = _rescale_without_blur_arg(clip, kernel, h, base_height)
                        else:
                            raise
                    stats = stats_func(clip, rescaled)
                    fr = stats.get_frame(0)
                    val = float(fr.props[stats_prop]) + 1e-9
                    fh.append(float(h))
                    fe.append(val)

                best_h, best_s, valley_count, curve_valid = _best_height_from_curve(fh, fe)
                return _KernelResult(kernel.name, fh, fe, best_h, best_s, True, valley_count, curve_valid)

    heights: List[float] = []
    errs: List[float] = []
    best_local_score = -1.0
    stagnation = 0
    evaluated_all = True

    for h in src_heights:
        try:
            if not vertical_only:
                rescaled = kernel.rescale(clip, h, base_height)  # type: ignore[arg-type]
            else:
                rescaled = kernel.rescale_pro(clip, src_height=h, base_height=base_height)  # type: ignore[arg-type]
        except Exception as e:
            # Keep descale compatibility only; do not alter original getnative scoring logic.
            if "blur" in str(e).lower():
                rescaled = _rescale_without_blur_arg(clip, kernel, h, base_height)
            else:
                raise
        stats = stats_func(clip, rescaled)
        fr = stats.get_frame(0)
        val = float(fr.props[stats_prop]) + 1e-9
        heights.append(float(h))
        errs.append(val)

        if len(errs) >= 3:
            _, cand_s, _, _ = _best_height_from_curve(heights, errs)
            if cand_s > best_local_score:
                best_local_score = cand_s
                stagnation = 0
            else:
                stagnation += 1

        if len(errs) >= 20 and stagnation >= early_stop_patience:
            if global_best_score > 0 and best_local_score < global_best_score * 0.60:
                evaluated_all = False
                break

    if not errs:
        raise RuntimeError(f"No getnative data for kernel: {kernel.name}")
    best_h, best_s, valley_count, curve_valid = _best_height_from_curve(heights, errs)
    return _KernelResult(kernel.name, heights, errs, best_h, best_s, evaluated_all, valley_count, curve_valid)


def getnative(
    clip: vs.VideoNode,
    rescalers: Optional[Union[rescale.Rescaler, List[rescale.Rescaler]]] = None,
    src_heights: Union[int, float, Sequence[int], Sequence[float]] = tuple(range(500, 1001)),
    base_height: Optional[int] = None,
    crop_size: int = 5,
    dark: bool = True,
    ex_thr: float = 0.015,
    filename: Optional[str] = None,
    debug_dir: Optional[str] = None,
    vertical_only: bool = False,
    stats_func: Optional[Callable[[vs.VideoNode, vs.VideoNode], vs.VideoNode]] = None,
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
) -> vs.VideoNode:
    """Auto-kernel getnative with multi-core and early-stop."""
    assert isinstance(clip, vs.VideoNode)
    if GRAY_FORMAT_ID is not None and clip.format.id != GRAY_FORMAT_ID:
        raise ValueError("getnative expects GRAYS input clip")

    if clip.num_frames != 1:
        raise ValueError("src.getnative.getnative currently expects a single-frame GRAYS clip.")

    if stats_func is None:
        stats_func = functools.partial(_measurediff_compat, ex_thr=ex_thr, crop_size=crop_size)

    if isinstance(src_heights, (int, float)):
        height_list: Tuple[float, ...] = (float(src_heights),)
    else:
        height_list = tuple(float(h) for h in src_heights)
    if not height_list:
        raise ValueError("src_heights cannot be empty.")

    if rescalers is None:
        kernel_list = _default_rescalers() if not fast_mode else _ordered_rescalers()
    elif isinstance(rescalers, list):
        kernel_list = rescalers
    else:
        kernel_list = [rescalers]

    try:
        target_threads = max(4, (os.cpu_count() or 4))
        if core.num_threads < target_threads:
            core.num_threads = target_threads
    except Exception:
        pass

    full_scan = bool(debug_dir) and bool(debug_full_scan)
    consensus_min = int(consensus_min_kernels)
    if fast_mode and consensus_min_kernels == 3:
        consensus_min = 2
    results: List[_KernelResult] = []
    global_best = -1.0
    for kernel in kernel_list:
        kr = _collect_curve_for_kernel(
            clip=clip,
            kernel=kernel,
            src_heights=height_list,
            base_height=base_height,
            vertical_only=vertical_only,
            stats_func=stats_func,
            stats_prop=stats_prop,
            early_stop_patience=(10**9 if full_scan else early_stop_patience),
            global_best_score=(0.0 if full_scan else global_best),
            two_stage=(not full_scan),
        )
        results.append(kr)
        if debug_dir:
            _save_kernel_debug(debug_dir, kr, dark=dark)
        global_best = max(global_best, kr.best_score)

        if max_kernels and len(results) >= int(max_kernels):
            break
        if not full_scan:
            tried = len(results)
            if tried >= max(1, int(min_kernels)):
                best = max(results, key=lambda r: float(r.best_score)).best_score if results else 0.0
                second = 0.0
                for r in results:
                    s = float(r.best_score)
                    if s >= best:
                        continue
                    second = max(second, s)
                if score_quit and best >= float(score_quit) and (second <= 0.0 or best >= second * float(score_margin)):
                    break
        if (not full_scan) and consensus_quit and len(results) >= consensus_min:
            if _kernel_consensus(results) is not None:
                break

    valid_results = [r for r in results if r.curve_valid]
    if valid_results:
        winner0 = max(valid_results, key=lambda r: (r.best_score, r.best_height))
    else:
        winner0 = min(results, key=lambda r: (min(r.errors), r.best_height))

    # Winner-only full-range scan for precise curve/score.
    winner = _collect_curve_for_kernel(
        clip=clip,
        kernel=_find_kernel_by_name(kernel_list, winner0.name),
        src_heights=height_list,
        base_height=base_height,
        vertical_only=vertical_only,
        stats_func=stats_func,
        stats_prop=stats_prop,
        early_stop_patience=10**9,
        global_best_score=0.0,
        two_stage=False,
    )
    if debug_dir:
        _save_kernel_debug(debug_dir, winner, dark=dark)
    n_curve = len(winner.heights)
    best_idx = min(range(n_curve), key=lambda i: abs(float(winner.heights[i]) - float(winner.best_height)))
    edge_hit = int(best_idx <= 1 or best_idx >= n_curve - 2)
    dec_ratio = _curve_decreasing_ratio(winner.errors)
    curve_valid = int(bool(winner.curve_valid) and (edge_hit == 0))
    curve_valid_strict = int(bool(curve_valid) and (dec_ratio < 0.80))
    if filename:
        _save_auto_plot(results, filename=filename, dark=dark)

    return clip.std.SetFrameProps(
        getnative_kernel=winner.name,
        getnative_height=float(winner.best_height),
        getnative_score=float(winner.best_score),
        getnative_curve_valid=int(curve_valid),
        getnative_curve_valid_strict=int(curve_valid_strict),
        getnative_edge_hit=int(edge_hit),
        getnative_decreasing_ratio=float(dec_ratio),
        getnative_valley_count=int(winner.valley_count),
    )
