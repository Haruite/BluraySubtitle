"""Getnative split-mode orchestrator (py: algorithm, vpy: VS execution)."""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, Union

import numpy as np

from core.settings import VSPIPE_PATH


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


def _resolve_vspipe():
    if hasattr(sys, "_MEIPASS"):
        from src.exports.utils import get_vspipe_context

        return get_vspipe_context()
    env = os.environ.copy()
    preferred = str(
        env.get("BLURAYSUB_VSPIPE")
        or env.get("VSPIPE_EXE")
        or ""
    ).strip()
    if preferred:
        if os.path.isfile(preferred):
            return (preferred, env)
        found_pref = shutil.which(preferred)
        if found_pref:
            return (found_pref, env)

    local_names = ["vspipe.exe", "vspipe"] if os.name == "nt" else ["vspipe", "vspipe.exe"]
    search_dirs = [
        os.path.abspath("."),
        os.path.dirname(os.path.abspath(__file__)),
        os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")),
        os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "vs_pkg")),
        os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "vs_pkg")),
    ]
    for d in search_dirs:
        for n in local_names:
            p = os.path.join(d, n)
            if os.path.isfile(p):
                return (p, env)

    return (VSPIPE_PATH, env)

    raise FileNotFoundError(
        "vspipe executable not found. Set BLURAYSUB_VSPIPE to full path "
        "(example: C:/Software/release-x64/vspipe.exe) or add vspipe to PATH."
    )


def _normalize_src_heights(src_heights: Union[int, float, Sequence[int], Sequence[float]]) -> Tuple[float, ...]:
    if isinstance(src_heights, (int, float)):
        return (float(src_heights),)
    return tuple(float(h) for h in src_heights)


def _resolve_getnative_vpy_path() -> str:
    """Locate getnative.vpy next to this module; PyInstaller must list it in datas (see .spec)."""
    env = str(os.getenv("BLURAYSUB_GETNATIVE_VPY", "") or "").strip()
    if env and os.path.isfile(env):
        return env

    here = Path(__file__).resolve()
    candidates = [
        here.with_suffix(".vpy"),
        here.parent / "getnative.vpy",
    ]
    mei = getattr(sys, "_MEIPASS", None)
    if mei:
        mei_root = Path(mei)
        candidates.extend(
            [
                mei_root / "src" / "vs_tools" / "getnative.vpy",
                mei_root / "vs_tools" / "getnative.vpy",
            ]
        )
    exe_dir = Path(getattr(sys, "executable", "") or "").resolve().parent
    if exe_dir.parts:
        candidates.extend(
            [
                exe_dir / "getnative.vpy",
                exe_dir / "src" / "vs_tools" / "getnative.vpy",
            ]
        )

    for p in candidates:
        s = str(p)
        if os.path.isfile(s):
            return s
    tried = ", ".join(str(p) for p in candidates[:6])
    raise FileNotFoundError(
        "getnative.vpy not found. Add src/vs_tools/getnative.vpy to PyInstaller datas, "
        "or set BLURAYSUB_GETNATIVE_VPY to its full path. Tried: "
        + tried
    )


def _vpy_call(input_png: str, params: Dict) -> Dict:
    vpy_path = _resolve_getnative_vpy_path()
    if not os.path.exists(input_png):
        raise FileNotFoundError(f"input PNG not found: {input_png}")

    fd_out, output_json = tempfile.mkstemp(prefix="bluraysub_getnative_", suffix=".json")
    os.close(fd_out)
    try:
        vspipe_exe, vspipe_env = _resolve_vspipe()
        env = dict(vspipe_env or os.environ.copy())
        try:
            from src.core.settings import PLUGIN_PATH as _plugin_path
        except Exception:
            _plugin_path = os.environ.get("BLURAYSUB_PLUGIN_PATH", "")
        _pp = str(_plugin_path or "").strip()
        if _pp:
            env["BLURAYSUB_PLUGIN_PATH"] = _pp
        env["BLURAYSUB_GETNATIVE_INPUT_PNG"] = input_png
        env["BLURAYSUB_GETNATIVE_OUTPUT_JSON"] = output_json
        env["BLURAYSUB_GETNATIVE_PARAMS_JSON"] = json.dumps(params, ensure_ascii=False)
        run_kwargs = {
            "env": env,
            "capture_output": True,
            "text": True,
            "check": False,
        }
        if os.name == "nt":
            run_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        proc = subprocess.run([vspipe_exe, vpy_path, "-"], **run_kwargs)
        if proc.returncode != 0:
            raise RuntimeError(f"vspipe failed ({proc.returncode}): {(proc.stderr or proc.stdout or '').strip()}")
        with open(output_json, "r", encoding="utf-8") as f:
            payload = json.load(f)
        if not isinstance(payload, dict) or not payload.get("ok"):
            raise RuntimeError(f"getnative.vpy failed: {payload}")
        result = payload.get("result")
        if not isinstance(result, dict):
            raise RuntimeError("invalid getnative.vpy result payload")
        return result
    finally:
        try:
            if os.path.exists(output_json):
                os.remove(output_json)
        except Exception:
            pass


def _mad(vals: Sequence[float]) -> float:
    if not vals:
        return 0.0
    arr = np.asarray(list(vals), dtype=np.float64)
    if arr.size == 0:
        return 0.0
    med = float(np.median(arr))
    return float(np.median(np.abs(arr - med)))


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


def _smooth_curve(vals: Sequence[float]) -> List[float]:
    n = len(vals)
    if n < 5:
        return [float(v) for v in vals]
    w = max(5, min(21, (n // 60) * 2 + 5))
    if w % 2 == 0:
        w += 1
    half = w // 2
    arr = np.asarray(vals, dtype=np.float64)
    kernel = np.ones(w, dtype=np.float64) / float(w)
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
            cand.append((i, s))
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


def getnative(
    clip,
    rescalers=None,
    src_heights: Union[int, float, Sequence[int], Sequence[float]] = tuple(range(500, 1001)),
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
):
    if stats_func is not None:
        raise ValueError("stats_func override is not supported in split mode")
    if rescalers is not None:
        raise ValueError("custom rescalers are not supported in split mode")
    if not isinstance(clip, (str, Path)):
        raise TypeError("split mode expects PNG path as `clip` argument")

    input_png = str(clip)
    height_list = _normalize_src_heights(src_heights)
    if not height_list:
        raise ValueError("src_heights cannot be empty.")

    kernel_resp = _vpy_call(input_png, {"mode": "list_kernels", "fast_mode": bool(fast_mode)})
    kernel_names = list(kernel_resp.get("kernels") or [])
    if not kernel_names:
        raise RuntimeError("no kernels returned by vpy")

    full_scan = bool(debug_dir) and bool(debug_full_scan)
    consensus_min = int(consensus_min_kernels)
    if fast_mode and consensus_min_kernels == 3:
        consensus_min = 2

    results: List[_KernelResult] = []
    global_best = -1.0
    for kernel_name in kernel_names:
        curve = _vpy_call(
            input_png,
            {
                "mode": "collect_curve",
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
        heights = [float(x) for x in curve.get("heights", [])]
        errors = [float(x) for x in curve.get("errors", [])]
        if not heights or not errors:
            continue
        best_h, best_s, valley_count, curve_valid = _best_height_from_curve(heights, errors)
        kr = _KernelResult(
            name=str(kernel_name),
            heights=heights,
            errors=errors,
            best_height=best_h,
            best_score=best_s,
            evaluated_all=bool(curve.get("evaluated_all", True)),
            valley_count=int(valley_count),
            curve_valid=bool(curve_valid),
        )
        results.append(kr)
        global_best = max(global_best, kr.best_score)
        if max_kernels and len(results) >= int(max_kernels):
            break
        if not full_scan and len(results) >= max(1, int(min_kernels)):
            best = max(results, key=lambda r: float(r.best_score)).best_score
            second = max([float(r.best_score) for r in results if float(r.best_score) < best] or [0.0])
            if score_quit and best >= float(score_quit) and (second <= 0.0 or best >= second * float(score_margin)):
                break
        if (not full_scan) and consensus_quit and len(results) >= consensus_min:
            if _kernel_consensus(results) is not None:
                break

    if not results:
        raise RuntimeError("no getnative curve data collected")
    valid_results = [r for r in results if r.curve_valid]
    winner0 = max(valid_results, key=lambda r: (r.best_score, r.best_height)) if valid_results else min(
        results, key=lambda r: (min(r.errors), r.best_height)
    )

    final_curve = _vpy_call(
        input_png,
        {
            "mode": "collect_curve",
            "kernel_name": winner0.name,
            "src_heights": list(height_list),
            "base_height": base_height,
            "vertical_only": bool(vertical_only),
            "ex_thr": float(ex_thr),
            "crop_size": int(crop_size),
            "stats_prop": str(stats_prop),
            "early_stop_patience": int(10**9),
            "global_best_score": 0.0,
            "two_stage": False,
        },
    )
    wh = [float(x) for x in final_curve.get("heights", [])]
    we = [float(x) for x in final_curve.get("errors", [])]
    w_best_h, w_best_s, w_valley_count, w_curve_valid = _best_height_from_curve(wh, we)
    best_idx = min(range(len(wh)), key=lambda i: abs(float(wh[i]) - float(w_best_h)))
    edge_hit = int(best_idx <= 1 or best_idx >= len(wh) - 2)
    dec_ratio = _curve_decreasing_ratio(we)
    curve_valid = int(bool(w_curve_valid) and (edge_hit == 0))
    curve_valid_strict = int(bool(curve_valid) and (dec_ratio < 0.80))

    return {
        "getnative_kernel": str(winner0.name),
        "getnative_height": float(w_best_h),
        "getnative_score": float(w_best_s),
        "getnative_curve_valid": int(curve_valid),
        "getnative_curve_valid_strict": int(curve_valid_strict),
        "getnative_edge_hit": int(edge_hit),
        "getnative_decreasing_ratio": float(dec_ratio),
        "getnative_valley_count": int(w_valley_count),
        "debug_dir": debug_dir,
        "filename": filename,
        "dark": dark,
    }

