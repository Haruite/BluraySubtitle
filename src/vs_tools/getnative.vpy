"""Portable VapourSynth execution half of the Infiziert90/getnative adaptation."""

import functools
import importlib
import math
import json
import os
import time

import numpy as np
import vapoursynth as vs

core = vs.core

try:
    core.num_threads = max(1, int(os.getenv("BLURAYSUB_GETNATIVE_VS_THREADS", "1")))
except (TypeError, ValueError):
    core.num_threads = 1
try:
    # A scan constructs many short-lived descale graphs. Bound the VS frame cache to
    # control concurrent growth; the 800 MiB per-process value is a scheduling estimate.
    core.max_cache_size = min(int(core.max_cache_size), 256)
except (AttributeError, TypeError, ValueError):
    pass

# Linux/macOS: VS does not auto-scan a plugin dir like some Windows installs. The app sets
# BLURAYSUB_PLUGIN_PATH from settings.PLUGIN_PATH when invoking vspipe (see getnative.py _vpy_call).
_bluraysub_plugin_path = str(os.getenv("BLURAYSUB_PLUGIN_PATH", "") or "").strip()
if _bluraysub_plugin_path and os.path.isdir(_bluraysub_plugin_path):
    vs.core.std.LoadAllPlugins(_bluraysub_plugin_path)

# muvsfunc probes optional plugin namespaces while importing. Import it only after
# Linux/macOS plugins are loaded so available implementations are not disabled.
_muvsfunc = importlib.import_module("muvsfunc")
measurediff = _muvsfunc.measurediff
rescale = _muvsfunc.rescale


def _write(payload):
    out_json = str(os.getenv("BLURAYSUB_GETNATIVE_OUTPUT_JSON", "") or "").strip()
    if not out_json:
        return
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _write_progress(payload):
    progress_jsonl = str(os.getenv("BLURAYSUB_GETNATIVE_PROGRESS_JSONL", "") or "").strip()
    if not progress_jsonl:
        return
    with open(progress_jsonl, "a", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")
        f.flush()


def _preset_format(name):
    fmt = getattr(vs, name, None)
    if fmt is None:
        preset = getattr(vs, "PresetFormat", None)
        fmt = getattr(preset, name, None) if preset is not None else None
    return fmt


def _blank():
    fmt = _preset_format("GRAY8")
    if fmt is None:
        # Last-resort fallback for API variants that only expose query_video_format.
        try:
            qvf = core.query_video_format
        except Exception:
            qvf = None
        if qvf is not None:
            gray_cf = getattr(getattr(vs, "ColorFamily", object), "GRAY", None)
            int_st = getattr(getattr(vs, "SampleType", object), "INTEGER", None)
            if gray_cf is not None and int_st is not None:
                try:
                    vf = qvf(
                        color_family=gray_cf,
                        sample_type=int_st,
                        bits_per_sample=8,
                        subsampling_w=0,
                        subsampling_h=0,
                    )
                    fmt = getattr(vf, "id", None)
                except Exception:
                    fmt = None
    if fmt is None:
        raise RuntimeError("Could not resolve GRAY8 format for BlankClip")
    core.std.BlankClip(width=8, height=8, format=fmt, length=1).set_output()


def _parse_params():
    raw = str(os.getenv("BLURAYSUB_GETNATIVE_PARAMS_JSON", "") or "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _default_rescalers():
    return [
        rescale.Bilinear(),
        rescale.Bicubic(1 / 3, 1 / 3),
        rescale.Bicubic(0.5, 0.0),
        rescale.Bicubic(0.0, 0.5),
        rescale.Bicubic(0.0, 0.75),
        rescale.Bicubic(1.0, 0.0),
        rescale.Bicubic(0.0, 1.0),
        rescale.Bicubic(0.2, 0.5),
        rescale.Bicubic(0.5, 0.5),
        rescale.Lanczos(2),
        rescale.Lanczos(3),
        rescale.Lanczos(4),
        rescale.Lanczos(5),
        rescale.Spline16(),
        rescale.Spline36(),
        rescale.Spline64(),
    ]


def _fast_rescalers():
    return [
        rescale.Bilinear(),
        rescale.Bicubic(1 / 3, 1 / 3),
        rescale.Bicubic(0.5, 0.0),
        rescale.Lanczos(3),
        rescale.Spline36(),
    ]


def _kernel_key(k):
    return str(getattr(k, "name", "") or "").strip().lower()


def _ordered_rescalers():
    fast = _fast_rescalers()
    all_k = _default_rescalers()
    out = []
    seen = set()
    for k in fast + all_k:
        key = _kernel_key(k) or str(k)
        if key in seen:
            continue
        seen.add(key)
        out.append(k)
    return out


def _find_kernel_by_name(kernels, name):
    target = str(name or "").strip().lower()
    for k in kernels:
        if _kernel_key(k) == target:
            return k
    raise ValueError(f"unknown getnative kernel: {name}")


def _measurediff_compat(clip1, clip2, ex_thr=0.015, crop_size=5):
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


def _target_dims(clip, target_h, base_height):
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


def _rescale_without_blur_arg(clip, kernel, target_h, base_height):
    w, h = _target_dims(clip, target_h, base_height)
    name = str(getattr(kernel, "name", "") or "").lower()
    taps = int(getattr(kernel, "taps", 3) or 3)
    b = float(getattr(kernel, "b", 0.0) or 0.0)
    c = float(getattr(kernel, "c", 0.5) or 0.5)

    if "lanczos" in name and hasattr(core.descale, "Delanczos"):
        low = core.descale.Delanczos(clip, w, h, taps=taps)
        return core.resize.Lanczos(low, clip.width, clip.height, filter_param_a=taps)
    if "bilinear" in name and hasattr(core.descale, "Debilinear"):
        low = core.descale.Debilinear(clip, w, h)
        return core.resize.Bilinear(low, clip.width, clip.height)
    if "spline16" in name and hasattr(core.descale, "Despline16"):
        low = core.descale.Despline16(clip, w, h)
        return core.resize.Spline16(low, clip.width, clip.height)
    if "spline36" in name and hasattr(core.descale, "Despline36"):
        low = core.descale.Despline36(clip, w, h)
        return core.resize.Spline36(low, clip.width, clip.height)
    if "spline64" in name and hasattr(core.descale, "Despline64"):
        low = core.descale.Despline64(clip, w, h)
        return core.resize.Spline64(low, clip.width, clip.height)
    if hasattr(core.descale, "Debicubic"):
        low = core.descale.Debicubic(clip, w, h, b=b, c=c)
        return core.resize.Bicubic(low, clip.width, clip.height, filter_param_a=b, filter_param_b=c)
    return core.resize.Bicubic(clip, clip.width, clip.height)


def _mad(vals):
    if not vals:
        return 0.0
    arr = np.asarray(list(vals), dtype=np.float64)
    if arr.size == 0:
        return 0.0
    med = float(np.median(arr))
    return float(np.median(np.abs(arr - med)))


def _is_banned_height(height):
    # Empirical false positives: the pervasive 540p notch and the unstable 1080p search tail.
    value = float(height)
    return abs(value - 540.0) <= 5.0 or value > 1040.0


def _best_height_from_curve(heights, vals):

    if len(vals) < 5:
        order = sorted(range(len(vals)), key=lambda n: float(vals[n]))
        i = next((j for j in order if not _is_banned_height(float(heights[j]))), order[0])
        return float(heights[i]), 0.0, 0, False

    n_raw = len(vals)
    step_vals = []
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

    def _local_bad_osc(idx):
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
    sharp_candidates = []
    full_range_tail = max_hv - float(min(float(x) for x in heights)) >= 160.0
    for i in range(1, len(heights)):
        hh = float(heights[i])
        if _is_banned_height(hh):
            continue
        if full_range_tail and tail_osc and hh >= tail_start:
            continue
        if hh >= 1000.0 and _local_bad_osc(i):
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

    def _half_width(idx):
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

    cand = []
    for i in valley_idx:
        hh = float(heights[i])
        if _is_banned_height(hh):
            continue
        if full_range_tail and tail_osc and hh >= tail_start:
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

    def _segment_bounds(idx):
        l = idx
        while l > 0 and float(dip[l]) >= noise_gate:
            l -= 1
        r = idx
        last = len(dip) - 1
        while r < last and float(dip[r]) >= noise_gate:
            r += 1
        return (l + 1, r - 1)

    segments = {}
    for i, s in filtered:
        b = _segment_bounds(int(i))
        segments.setdefault(b, []).append((int(i), float(s)))

    def _seg_rank(item):
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
    upstream_ratio = (
        max(1.0, float(vals[best_i - 1]) / max(float(vals[best_i]), 1e-12))
        if best_i > 0
        else 1.0
    )
    return float(best_h), float(upstream_ratio), len(segments), bool(best_s > 0.0)


def _collect_curve_for_kernel(
    clip,
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
):
    if two_stage:
        hs = [float(x) for x in src_heights]
        if len(hs) >= 200:
            step_vals = []
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

                # Kernel screening only needs a centered half-size crop. The winning
                # kernel is later verified with a full-frame coarse pass before its 1p scan.
                if coarse_half_size:
                    coarse_width = max(64, (int(clip.width) // 2) // 2 * 2)
                    coarse_height = max(64, (int(clip.height) // 2) // 2 * 2)
                    coarse_left = max(0, (int(clip.width) - coarse_width) // 2)
                    coarse_top = max(0, (int(clip.height) - coarse_height) // 2)
                    coarse_clip = core.std.CropAbs(
                        clip,
                        width=coarse_width,
                        height=coarse_height,
                        left=coarse_left,
                        top=coarse_top,
                    )
                else:
                    coarse_clip = clip
                    coarse_height = int(clip.height)
                coarse_scale = float(coarse_height) / float(max(1, int(clip.height)))
                coarse_base_height = (
                    float(base_height) * coarse_scale
                    if base_height is not None
                    else None
                )

                ch = []
                ce = []
                for h in coarse:
                    scaled_h = float(h) * coarse_scale
                    try:
                        if not vertical_only:
                            rescaled = kernel.rescale(
                                coarse_clip,
                                scaled_h,
                                coarse_base_height,
                            )
                        else:
                            rescaled = kernel.rescale_pro(
                                coarse_clip,
                                src_height=scaled_h,
                                base_height=coarse_base_height,
                            )
                    except Exception as e:
                        if "blur" in str(e).lower():
                            rescaled = _rescale_without_blur_arg(
                                coarse_clip,
                                kernel,
                                scaled_h,
                                coarse_base_height,
                            )
                        else:
                            raise
                    stats = stats_func(coarse_clip, rescaled)
                    fr = stats.get_frame(0)
                    val = float(fr.props[stats_prop]) + 1e-9
                    ch.append(float(h))
                    ce.append(val)

                coarse_best_h, coarse_best_s, _, coarse_valid = _best_height_from_curve(ch, ce)
                if (
                    global_best_score > 0.0
                    and coarse_valid
                    and coarse_best_s < global_best_score * 0.45
                ):
                    return {
                        "kernel": str(getattr(kernel, "name", "") or ""),
                        "heights": ch,
                        "errors": ce,
                        "evaluated_all": False,
                        "screen_score": float(coarse_best_s),
                        "screen_valid": bool(coarse_valid),
                        "skipped": True,
                    }
                center = int(round(float(coarse_best_h)))
                radius = 20
                rlo = max(lo, center - radius)
                rhi = min(hi, center + radius)
                fine = list(range(rlo, rhi + 1))

                fh = []
                fe = []
                for h in fine:
                    try:
                        if not vertical_only:
                            rescaled = kernel.rescale(clip, h, base_height)
                        else:
                            rescaled = kernel.rescale_pro(clip, src_height=h, base_height=base_height)
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
                return {
                    "kernel": str(getattr(kernel, "name", "") or ""),
                    "heights": fh,
                    "errors": fe,
                    "evaluated_all": True,
                    "screen_score": float(coarse_best_s),
                    "screen_valid": bool(coarse_valid),
                    "skipped": False,
                }

    heights = []
    errors = []
    best_local_score = -1.0
    stagnation = 0
    evaluated_all = True
    early_stop_enabled = int(early_stop_patience) < len(src_heights)

    for h in src_heights:
        try:
            if not vertical_only:
                rescaled = kernel.rescale(clip, h, base_height)
            else:
                rescaled = kernel.rescale_pro(clip, src_height=h, base_height=base_height)
        except Exception as e:
            if "blur" in str(e).lower():
                rescaled = _rescale_without_blur_arg(clip, kernel, h, base_height)
            else:
                raise
        stats = stats_func(clip, rescaled)
        fr = stats.get_frame(0)
        val = float(fr.props[stats_prop]) + 1e-9
        heights.append(float(h))
        errors.append(float(val))

        if early_stop_enabled and len(errors) >= 3:
            _, cand_s, _, _ = _best_height_from_curve(heights, errors)
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
    }


def _load_source_png(path):
    src = None
    imwri = getattr(core, "imwri", getattr(core, "imwrif", None))
    if imwri is not None and hasattr(imwri, "Read"):
        try:
            src = imwri.Read(path)
        except Exception:
            src = None
    if src is None and hasattr(core, "lsmas"):
        try:
            try:
                src = core.lsmas.LWLibavSource(path, cache=0)
            except TypeError:
                src = core.lsmas.LWLibavSource(path)
        except Exception:
            src = None
    if src is None:
        raise RuntimeError("failed to load image source: need imwri/imwrif Read or lsmas")

    if src.format is None:
        raise RuntimeError("image source has a variable format")
    rgb_cf = getattr(vs, "RGB", None)
    if rgb_cf is None:
        rgb_cf = getattr(getattr(vs, "ColorFamily", object), "RGB", 2)
    if src.format.color_family == rgb_cf:
        yuv444ps = _preset_format("YUV444PS")
        if yuv444ps is None:
            raise RuntimeError("Could not resolve YUV444PS format for RGB-to-luma conversion")
        src = core.resize.Point(src, format=yuv444ps, matrix_s="709")

    gray_cf = getattr(vs, "GRAY", None)
    if gray_cf is None:
        gray_cf = getattr(getattr(vs, "ColorFamily", object), "GRAY", 1)
    clip = core.std.ShufflePlanes(src, 0, gray_cf)
    gray_fmt = _preset_format("GRAYS")
    if gray_fmt is None:
        raise RuntimeError("Could not resolve GRAYS format for getnative")
    clip = clip.resize.Point(format=gray_fmt)
    return clip[0]


def _list_kernels_mode(params):
    fast_mode = bool(params.get("fast_mode", False))
    kernels = _default_rescalers() if not fast_mode else _ordered_rescalers()
    return {"kernels": [str(getattr(k, "name", "") or "") for k in kernels]}


def _collect_curve_mode(clip, params):
    fast_mode = bool(params.get("fast_mode", False))
    kernels = _default_rescalers() if not fast_mode else _ordered_rescalers()
    kernel_name = str(params.get("kernel_name", "") or "").strip()
    kernel = _find_kernel_by_name(kernels, kernel_name) if kernel_name else kernels[0]
    src_heights = params.get("src_heights") or list(range(500, 1001))
    if isinstance(src_heights, (int, float)):
        height_list = (float(src_heights),)
    else:
        height_list = tuple(float(h) for h in src_heights)
    stats_func = functools.partial(
        _measurediff_compat,
        ex_thr=float(params.get("ex_thr", 0.015)),
        crop_size=int(params.get("crop_size", 5)),
    )
    return _collect_curve_for_kernel(
        clip=clip,
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
    )


def _collect_curves_mode(clip, params):
    fast_mode = bool(params.get("fast_mode", False))
    kernels = _default_rescalers() if not fast_mode else _ordered_rescalers()
    limit = int(params.get("max_kernels", 0))
    if limit > 0:
        kernels = kernels[:limit]
    curves = []
    total = len(kernels)
    scan_started = time.perf_counter()
    best_screen_score = 0.0
    completed_screens = 0
    for index, kernel in enumerate(kernels, start=1):
        kernel_started = time.perf_counter()
        kernel_params = dict(params)
        kernel_params["kernel_name"] = str(getattr(kernel, "name", "") or "")
        # Compare only like-for-like coarse curves. The first three priority kernels
        # always receive their full fine scan before obvious later mismatches may skip it.
        kernel_params["global_best_score"] = (
            float(best_screen_score) if completed_screens >= 3 else 0.0
        )
        curve = _collect_curve_mode(clip, kernel_params)
        curves.append(curve)
        if bool(curve.get("screen_valid", False)):
            completed_screens += 1
            best_screen_score = max(
                best_screen_score,
                float(curve.get("screen_score", 0.0) or 0.0),
            )
        best_h, best_s, _, curve_valid = _best_height_from_curve(
            curve.get("heights", []),
            curve.get("errors", []),
        )
        elapsed_seconds = time.perf_counter() - scan_started
        _write_progress(
            {
                "phase": "kernel",
                "index": index,
                "total": total,
                "image": os.path.basename(
                    str(os.getenv("BLURAYSUB_GETNATIVE_INPUT_PNG", "") or "")
                ),
                "kernel": str(curve.get("kernel", "") or ""),
                "height": float(best_h),
                "score": float(best_s),
                "curve_valid": bool(curve_valid and curve.get("evaluated_all", True)),
                "skipped": bool(curve.get("skipped", False)),
                "kernel_seconds": float(time.perf_counter() - kernel_started),
                "elapsed_seconds": float(elapsed_seconds),
                "eta_seconds": float((elapsed_seconds / index) * (total - index)),
            }
        )
    return {"curves": curves}


try:
    input_png = str(os.getenv("BLURAYSUB_GETNATIVE_INPUT_PNG", "") or "").strip()
    if not input_png:
        _write({"ok": False, "stage": "args", "error": "missing BLURAYSUB_GETNATIVE_INPUT_PNG"})
        _blank()
        raise SystemExit(0)

    params = _parse_params()
    mode = str(params.get("mode", "collect_curve") or "collect_curve").strip().lower()
    if mode == "list_kernels":
        result = _list_kernels_mode(params)
    elif mode == "collect_curve":
        src = _load_source_png(input_png)
        final_started = time.perf_counter()
        result = _collect_curve_mode(src, params)
        if str(params.get("progress_phase", "") or "").strip().lower() == "final":
            best_h, best_s, _, curve_valid = _best_height_from_curve(
                result.get("heights", []),
                result.get("errors", []),
            )
            _write_progress(
                {
                    "phase": "final",
                    "image": os.path.basename(input_png),
                    "kernel": str(result.get("kernel", "") or ""),
                    "height": float(best_h),
                    "score": float(best_s),
                    "curve_valid": bool(curve_valid),
                    "elapsed_seconds": float(time.perf_counter() - final_started),
                }
            )
    elif mode == "collect_curves":
        src = _load_source_png(input_png)
        result = _collect_curves_mode(src, params)
    else:
        raise ValueError(f"unsupported mode: {mode}")
    _write({"ok": True, "result": result})
except Exception as e:
    _write({"ok": False, "stage": "run_getnative", "error": f"{type(e).__name__} - {e}"})

_blank()
