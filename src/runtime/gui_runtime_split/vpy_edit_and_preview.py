"""Target module for VPy edit/preview methods of `BluraySubtitleGUI`."""

import os
import re
import shutil
import sys
import tempfile
from typing import Optional

from PyQt6.QtCore import QProcess, QProcessEnvironment
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLineEdit, QPushButton, QFileDialog, QMessageBox

from src.core.settings import ENCODE_REMUX_LABELS, ENCODE_LABELS, PLUGIN_PATH, VSEDIT_PATH, ENCODE_SP_LABELS, \
    ENCODE_REMUX_SP_LABELS
from src.exports.utils import print_exc_terminal, run_command
from .gui_base import BluraySubtitleGuiBase


_PREVIOUS_GETNATIVE_KERNEL_HELPER = (
    '_NATIVE_BICUBIC = {\n'
    '    "bicubic_0.333_0.333": (1/3, 1/3),\n'
    '    "bicubic_0.5_0.0": (0.5, 0.0),\n'
    '    "bicubic_0.0_0.5": (0.0, 0.5),\n'
    '    "bicubic_0.0_0.75": (0.0, 0.75),\n'
    '    "bicubic_1.0_0.0": (1.0, 0.0),\n'
    '    "bicubic_0.0_1.0": (0.0, 1.0),\n'
    '    "bicubic_0.2_0.5": (0.2, 0.5),\n'
    '    "bicubic_0.5_0.5": (0.5, 0.5),\n'
    '}\n'
    '\n'
    'def _descale_native(clip, width, height, kernel_name):\n'
    '    name = str(kernel_name or "").strip().lower()\n'
    '    if name == "bilinear":\n'
    '        if hasattr(core.descale, "Debilinear"):\n'
    '            return core.descale.Debilinear(clip, width, height)\n'
    '        return core.descale.Descale(clip, width, height, kernel="bilinear")\n'
    '    if name in _NATIVE_BICUBIC or name == "bicubic":\n'
    '        b, c = _NATIVE_BICUBIC.get(name, (1/3, 1/3))\n'
    '        if hasattr(core.descale, "Debicubic"):\n'
    '            return core.descale.Debicubic(clip, width, height, b=b, c=c)\n'
    '        return core.descale.Descale(clip, width, height, kernel="bicubic", b=b, c=c)\n'
    '    if name.startswith("lanczos"):\n'
    '        taps_text = name[len("lanczos"):]\n'
    '        if not taps_text.isdigit():\n'
    '            raise ValueError(f"Invalid getnative Lanczos kernel: {kernel_name}")\n'
    '        taps = int(taps_text)\n'
    '        if hasattr(core.descale, "Delanczos"):\n'
    '            return core.descale.Delanczos(clip, width, height, taps=taps)\n'
    '        return core.descale.Descale(clip, width, height, kernel="lanczos", taps=taps)\n'
    '    spline_filters = {\n'
    '        "spline16": "Despline16",\n'
    '        "spline36": "Despline36",\n'
    '        "spline64": "Despline64",\n'
    '    }\n'
    '    if name in spline_filters:\n'
    '        descaler = getattr(core.descale, spline_filters[name], None)\n'
    '        if descaler is not None:\n'
    '            return descaler(clip, width, height)\n'
    '        return core.descale.Descale(clip, width, height, kernel=name)\n'
    '    raise ValueError(f"Unsupported getnative kernel: {kernel_name}")\n'
    '\n'
)

_GETNATIVE_KERNEL_HELPER = (
    _PREVIOUS_GETNATIVE_KERNEL_HELPER
    + 'def _resize_native(clip, width, height, kernel_name):\n'
    '    name = str(kernel_name or "").strip().lower()\n'
    '    if name == "bilinear":\n'
    '        return core.resize.Bilinear(clip, width, height)\n'
    '    if name in _NATIVE_BICUBIC or name == "bicubic":\n'
    '        b, c = _NATIVE_BICUBIC.get(name, (1/3, 1/3))\n'
    '        return core.resize.Bicubic(\n'
    '            clip, width, height, filter_param_a=b, filter_param_b=c\n'
    '        )\n'
    '    if name.startswith("lanczos"):\n'
    '        taps = int(name[len("lanczos"):])\n'
    '        return core.resize.Lanczos(clip, width, height, filter_param_a=taps)\n'
    '    spline_filters = {\n'
    '        "spline16": core.resize.Spline16,\n'
    '        "spline36": core.resize.Spline36,\n'
    '        "spline64": core.resize.Spline64,\n'
    '    }\n'
    '    if name in spline_filters:\n'
    '        return spline_filters[name](clip, width, height)\n'
    '    raise ValueError(f"Unsupported getnative kernel: {kernel_name}")\n'
    '\n'
    'def _rescale_protection_mask(original, reconstructed):\n'
    '    mask = core.std.Expr([original, reconstructed], "x y - abs")\n'
    '    mask = core.std.Binarize(mask, threshold=2 * 256)\n'
    '    return mask.std.Maximum().std.Maximum().std.Inflate()\n'
    '\n'
)
_LEGACY_GETNATIVE_DESCALE_BLOCK = (
    '        kl = (native_kernel or "").lower()\n'
    '        if "lanczos" in kl and hasattr(core.descale, "Delanczos"):\n'
    '            low = core.descale.Delanczos(src16, native_w, nh, taps=3)\n'
    '        elif "bilinear" in kl and hasattr(core.descale, "Debilinear"):\n'
    '            low = core.descale.Debilinear(src16, native_w, nh)\n'
    '        elif hasattr(core.descale, "Debicubic"):\n'
    '            low = core.descale.Debicubic(src16, native_w, nh, b=1/3, c=1/3)\n'
    '        else:\n'
    '            low = core.resize.Bicubic(src16, native_w, nh)\n'
    '        proc16 = low\n'
)
_PREVIOUS_GETNATIVE_DESCALE_BLOCK = (
    '        low = _descale_native(src16, native_w, nh, native_kernel)\n'
    '        proc16 = low\n'
)
_GETNATIVE_DESCALE_BLOCK = (
    '        src16Y = core.std.ShufflePlanes(src16, 0, GRAY_CF)\n'
    '        lowY = _descale_native(src16Y, native_w, nh, native_kernel)\n'
    '        reconstructedY = _resize_native(lowY, target_w, target_h, native_kernel)\n'
    '        rescale_mask = _rescale_protection_mask(src16Y, reconstructedY)\n'
    '        native_chroma = core.resize.Spline64(\n'
    '            src16, native_w, nh, chromaloc_in_s="left", chromaloc_s="left"\n'
    '        )\n'
    '        proc16 = core.std.ShufflePlanes([lowY, native_chroma], [0, 1, 2], YUV_CF)\n'
)

_PREVIOUS_VPY_PROCESSING_SETTINGS = (
    'denoise_strength = 0.6  # 0.0-3.0; 0 disables denoise\n'
    'dehalo_strength = 0.25  # 0.0-1.0; 0 disables dehalo\n'
    'dering_strength = 0.25  # 0.0-1.0; 0 disables dering\n'
    '\n'
)

_PREVIOUS_VPY_PROCESSING_SETTINGS_V2 = (
    'denoise_strength = 0.6  # 0.0-3.0; 0 disables denoise\n'
    'dehalo_strength = 0.0  # 0.0-1.0; enable only for visible sharpening halos\n'
    'dering_strength = 0.0  # 0.0-1.0; enable only for visible ringing\n'
    'deband_strength = 1.0  # 0.0-1.0; 0 disables deband\n'
    'antialiasing_strength = 1.0  # 0.0-1.0; 0 disables anti-aliasing\n'
    '\n'
)

_VPY_PROCESSING_SETTINGS = (
    'denoise_strength = 0.6  # 0.0-3.0; 0 disables denoise\n'
    'dehalo_strength = 0.0  # 0.0-1.0; enable only for visible sharpening halos\n'
    'dering_strength = 0.0  # 0.0-1.0; enable only for visible ringing\n'
    'deband_strength = 0.5  # 0.0-1.0; 0 disables deband\n'
    'antialiasing_strength = 0.5  # 0.0-1.0; 0 disables anti-aliasing\n'
    '\n'
)

_VPY_PROCESSING_HELPERS = (
    'def _merge_luma(clip, luma):\n'
    '    return core.std.ShufflePlanes([luma, clip], [0, 1, 2], YUV_CF)\n'
    '\n'
    'def _m4(value):\n'
    '    return max(16, int(round(value / 4.0)) * 4)\n'
    '\n'
    'def _scale_8bit(value, clip):\n'
    '    return value * (1 << (clip.format.bits_per_sample - 8))\n'
    '\n'
    'def _denoise_luma_protected(clip, strength):\n'
    '    strength = max(0.0, min(float(strength), 3.0))\n'
    '    if strength == 0.0:\n'
    '        return clip\n'
    '    filtered = core.nlm_ispc.NLMeans(\n'
    '        clip, d=0, a=2, s=2, h=strength, channels="Y", wmode=3\n'
    '    )\n'
    '    source_y = core.std.ShufflePlanes(clip, 0, GRAY_CF)\n'
    '    filtered_y = core.std.ShufflePlanes(filtered, 0, GRAY_CF)\n'
    '    # Preserve line art and other strong spatial detail before limiting pixel changes.\n'
    '    edge_mask = source_y.std.Prewitt().std.Binarize(_scale_8bit(5, source_y))\n'
    '    edge_mask = edge_mask.std.Maximum().std.Inflate()\n'
    '    protected_y = core.std.MaskedMerge(filtered_y, source_y, edge_mask)\n'
    '    limited_y = mvf.LimitFilter(\n'
    '        protected_y, source_y, thr=max(0.45, strength * 0.65), elast=2.0\n'
    '    )\n'
    '    return _merge_luma(clip, limited_y)\n'
    '\n'
    'def _dehalo_luma(clip, strength):\n'
    '    strength = max(0.0, min(float(strength), 1.0))\n'
    '    if strength == 0.0:\n'
    '        return clip\n'
    '    source_y = core.std.ShufflePlanes(clip, 0, GRAY_CF)\n'
    '    halo = core.resize.Bicubic(\n'
    '        source_y, _m4(source_y.width / 2.4), _m4(source_y.height / 2.4),\n'
    '        filter_param_a=1/3, filter_param_b=1/3\n'
    '    )\n'
    '    halo = core.resize.Bicubic(\n'
    '        halo, source_y.width, source_y.height, filter_param_a=1, filter_param_b=0\n'
    '    )\n'
    '    halo_low = _scale_8bit(8, source_y)\n'
    '    halo_high = _scale_8bit(24, source_y)\n'
    '    halo_blend = _scale_8bit(32, source_y)\n'
    '    # Conservative abcxyz-style halo estimate, repaired and blended on luma only.\n'
    '    candidate = core.std.Expr(\n'
    '        [source_y, halo],\n'
    '        f"x {halo_low} + y < x {halo_low} + "\n'
    '        f"x {halo_high} - y > x {halo_high} - y ? ? "\n'
    '        f"x y - abs * x {halo_blend} x y - abs - * + {halo_blend} /"\n'
    '    )\n'
    '    repaired = core.rgvs.Repair(source_y, candidate, 1)\n'
    '    return _merge_luma(\n'
    '        clip, core.std.Merge(source_y, repaired, weight=strength)\n'
    '    )\n'
    '\n'
    'def _min_blur_luma(clip):\n'
    '    rg11 = core.rgvs.RemoveGrain(clip, 11)\n'
    '    rg4 = core.rgvs.RemoveGrain(clip, 4)\n'
    '    return core.std.Expr(\n'
    '        [clip, rg11, rg4],\n'
    '        "x y - x z - * 0 < x x y - abs x z - abs < y z ? ?"\n'
    '    )\n'
    '\n'
    'def _dering_luma(clip, strength):\n'
    '    strength = max(0.0, min(float(strength), 1.0))\n'
    '    if strength == 0.0:\n'
    '        return clip\n'
    '    source_y = core.std.ShufflePlanes(clip, 0, GRAY_CF)\n'
    '    smoothed_y = _min_blur_luma(source_y)\n'
    '    smoothed_y = core.rgvs.Repair(smoothed_y, source_y, 1)\n'
    '    smoothed_y = mvf.LimitFilter(\n'
    '        smoothed_y, source_y, thr=1.2, brighten_thr=0.6, elast=2.0\n'
    '    )\n'
    '    # HQDering-style ring mask: process the narrow band around strong edges, not the edge.\n'
    '    edge = source_y.std.Prewitt().std.Binarize(_scale_8bit(10, source_y))\n'
    '    outer = edge.std.Maximum().std.Maximum()\n'
    '    ring_mask = core.std.Expr([outer, edge], "x y -")\n'
    '    ring_mask = ring_mask.std.Inflate().std.Convolution(\n'
    '        matrix=[1, 1, 1, 1, 1, 1, 1, 1, 1], divisor=9\n'
    '    )\n'
    '    ringed_y = core.std.MaskedMerge(source_y, smoothed_y, ring_mask)\n'
    '    return _merge_luma(\n'
    '        clip, core.std.Merge(source_y, ringed_y, weight=strength)\n'
    '    )\n'
    '\n'
)

_LEGACY_VPY_FILTER_BLOCK = (
    'nr16 = core.nlm_ispc.NLMeans(proc16, d=0, wmode=3, h=3)\n'
)

_VPY_FILTER_BLOCK = (
    'nr16 = _denoise_luma_protected(proc16, denoise_strength)\n'
    'nr16 = _dehalo_luma(nr16, dehalo_strength)\n'
    'nr16 = _dering_luma(nr16, dering_strength)\n'
)

_PREVIOUS_VPY_POST_FILTER_BLOCK = (
    '_nr_pl = core.fmtc.bitdepth(nr16, bits=16)\n'
    'dbed = core.placebo.Deband(_nr_pl, planes=7, iterations=2, threshold=4.5, radius=16.0, grain=0.0)\n'
    'dbed = mvf.LimitFilter(dbed, _nr_pl, thr=0.55, elast=1.5, planes=[0, 1, 2])\n'
    'nr16Y = core.std.ShufflePlanes(_nr_pl, 0, GRAY_CF)\n'
    'aa_nr16Y = core.eedi2.EEDI2(nr16Y, field=1, mthresh=10, lthresh=20, vthresh=20, maxd=24, nt=50)\n'
    'aa_nr16Y = core.fmtc.resample(aa_nr16Y, proc_w, proc_h, 0, -0.5).std.Transpose()\n'
    'aa_nr16Y = core.eedi2.EEDI2(aa_nr16Y, field=1, mthresh=10, lthresh=20, vthresh=20, maxd=24, nt=50)\n'
    'aa_nr16Y = core.fmtc.resample(aa_nr16Y, proc_h, proc_w, 0, -0.5).std.Transpose()\n'
    'if (\n'
    '    aa_nr16Y.width != nr16Y.width\n'
    '    or aa_nr16Y.height != nr16Y.height\n'
    '    or aa_nr16Y.format.id != nr16Y.format.id\n'
    '):\n'
    '    aa_nr16Y = core.resize.Bicubic(\n'
    '        aa_nr16Y, nr16Y.width, nr16Y.height, format=nr16Y.format\n'
    '    )\n'
    'aaedY = core.rgvs.Repair(aa_nr16Y, nr16Y, 2)\n'
    'dbedY = core.std.ShufflePlanes(dbed, 0, GRAY_CF)\n'
    'mergedY = mvf.LimitFilter(dbedY, aaedY, thr=1.0, elast=1.5)\n'
    'merged = core.std.ShufflePlanes([mergedY, dbed], [0,1,2], YUV_CF)\n'
)

_LEGACY_WINDOWS_VPY_POST_FILTER_BLOCK = _PREVIOUS_VPY_POST_FILTER_BLOCK.replace(
    'dbed = core.placebo.Deband(_nr_pl, planes=7, iterations=2, threshold=4.5, radius=16.0, grain=0.0)\n',
    'dbed = core.neo_f3kdb.Deband(_nr_pl, 12, 72, 48, 48, 0, 0, output_depth=16)'
    '.neo_f3kdb.Deband(24, 56, 32, 32, 0, 0, output_depth=16)\n',
)

_PREVIOUS_VPY_POST_FILTER_BLOCK_V2 = (
    '# placebo.Deband accepts only 8/16-bit integer or 32-bit float.\n'
    '_nr_pl = core.fmtc.bitdepth(nr16, bits=16)\n'
    'deband_strength = max(0.0, min(float(deband_strength), 1.0))\n'
    'if deband_strength == 0.0:\n'
    '    dbed = _nr_pl\n'
    'else:\n'
    '    dbed_candidate = core.placebo.Deband(\n'
    '        _nr_pl, planes=7, iterations=2, threshold=4.5, radius=16.0, grain=0.0\n'
    '    )\n'
    '    dbed_candidate = mvf.LimitFilter(\n'
    '        dbed_candidate, _nr_pl, thr=0.55, elast=1.5, planes=[0, 1, 2]\n'
    '    )\n'
    '    dbed = dbed_candidate if deband_strength == 1.0 else core.std.Merge(\n'
    '        _nr_pl, dbed_candidate, weight=deband_strength\n'
    '    )\n'
    'dbedY = core.std.ShufflePlanes(dbed, 0, GRAY_CF)\n'
    'antialiasing_strength = max(\n'
    '    0.0, min(float(antialiasing_strength), 1.0)\n'
    ')\n'
    'if antialiasing_strength == 0.0:\n'
    '    mergedY = dbedY\n'
    'else:\n'
    '    nr16Y = core.std.ShufflePlanes(_nr_pl, 0, GRAY_CF)\n'
    '    aa_nr16Y = core.eedi2.EEDI2(\n'
    '        nr16Y, field=1, mthresh=10, lthresh=20, vthresh=20, maxd=24, nt=50\n'
    '    )\n'
    '    aa_nr16Y = core.fmtc.resample(\n'
    '        aa_nr16Y, proc_w, proc_h, 0, -0.5\n'
    '    ).std.Transpose()\n'
    '    aa_nr16Y = core.eedi2.EEDI2(\n'
    '        aa_nr16Y, field=1, mthresh=10, lthresh=20, vthresh=20, maxd=24, nt=50\n'
    '    )\n'
    '    aa_nr16Y = core.fmtc.resample(\n'
    '        aa_nr16Y, proc_h, proc_w, 0, -0.5\n'
    '    ).std.Transpose()\n'
    '    if (\n'
    '        aa_nr16Y.width != nr16Y.width\n'
    '        or aa_nr16Y.height != nr16Y.height\n'
    '        or aa_nr16Y.format.id != nr16Y.format.id\n'
    '    ):\n'
    '        aa_nr16Y = core.resize.Bicubic(\n'
    '            aa_nr16Y, nr16Y.width, nr16Y.height, format=nr16Y.format\n'
    '        )\n'
    '    aaedY = core.rgvs.Repair(aa_nr16Y, nr16Y, 2)\n'
    '    antialiasedY = mvf.LimitFilter(dbedY, aaedY, thr=1.0, elast=1.5)\n'
    '    mergedY = (\n'
    '        antialiasedY\n'
    '        if antialiasing_strength == 1.0\n'
    '        else core.std.Merge(dbedY, antialiasedY, weight=antialiasing_strength)\n'
    '    )\n'
    'merged = core.std.ShufflePlanes([mergedY, dbed], [0,1,2], YUV_CF)\n'
)

_VPY_POST_FILTER_BLOCK = _PREVIOUS_VPY_POST_FILTER_BLOCK_V2.replace(
    '    dbed_candidate = mvf.LimitFilter(\n'
    '        dbed_candidate, _nr_pl, thr=0.55, elast=1.5, planes=[0, 1, 2]\n'
    '    )\n',
    '    dbed_candidate = mvf.LimitFilter(\n'
    '        dbed_candidate, _nr_pl, thr=0.55, elast=1.5, planes=[0, 1, 2]\n'
    '    )\n'
    '    # Protect edge and texture planes while debanding flatter regions.\n'
    '    detail_mask = _nr_pl.std.Prewitt().std.Binarize(\n'
    '        threshold=_scale_8bit(3, _nr_pl)\n'
    '    )\n'
    '    detail_mask = (\n'
    '        detail_mask.std.Maximum().std.Maximum().std.Inflate().std.Convolution(\n'
    '            matrix=[1, 1, 1, 1, 1, 1, 1, 1, 1], divisor=9\n'
    '        )\n'
    '    )\n'
    '    dbed_candidate = core.std.MaskedMerge(\n'
    '        dbed_candidate, _nr_pl, detail_mask\n'
    '    )\n',
).replace(
    '    antialiasedY = mvf.LimitFilter(dbedY, aaedY, thr=1.0, elast=1.5)\n',
    '    antialiasedY = mvf.LimitFilter(aaedY, dbedY, thr=1.0, elast=1.5)\n',
)


class VpyEditPreviewMixin(BluraySubtitleGuiBase):
    def _current_vpy_processing_values(self) -> dict[str, float]:
        controls = (
            ('denoise_strength', 'vpy_denoise_strength_spin', 0.6),
            ('dehalo_strength', 'vpy_dehalo_strength_spin', 0.0),
            ('dering_strength', 'vpy_dering_strength_spin', 0.0),
            ('deband_strength', 'vpy_deband_strength_spin', 0.5),
            (
                'antialiasing_strength',
                'vpy_antialiasing_strength_spin',
                0.5,
            ),
        )
        values: dict[str, float] = {}
        for script_name, attribute_name, default in controls:
            control = getattr(self, attribute_name, None)
            values[script_name] = float(control.value()) if control is not None else default
        return values

    @staticmethod
    def _patch_vpy_processing_value_in_text(
            text: str,
            values: dict[str, float],
    ) -> str:
        for name, value in values.items():
            match = re.match(
                rf'^({re.escape(name)}\s*=\s*)'
                rf'[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?'
                rf'(\s*(#.*)?)$',
                text,
            )
            if match:
                return f'{match.group(1)}{format(value, ".6g")}{match.group(2)}'
        return text

    def _selected_output_bits_for_vpy(self) -> int:
        """Bits for ``fmtc.bitdepth(..., bits=N)``: follows Encode UI / BD encode constraints."""
        try:
            fn = getattr(self, '_current_encode_tool_and_depth', None)
            if callable(fn):
                _t, depth = fn()
                if str(depth).isdigit():
                    return int(depth)
        except Exception:
            pass
        try:
            bdc = getattr(self, 'encode_bit_depth_combo', None)
            if bdc is not None:
                d = bdc.currentData()
                if d is not None and str(d).isdigit():
                    return int(d)
        except Exception:
            pass
        return 10

    @staticmethod
    def _patch_fmtc_output_bits_in_text(raw_line: str, bits: int) -> str:
        """Rewrite only final-output fmtc lines (LHS ``res``), not intermediates like ``src16 = fmtc(src8,…)``."""
        s = raw_line.lstrip()
        if re.match(r"res\s*=\s*core\.fmtc\.bitdepth\s*\(\s*src8\s*,", s):
            return re.sub(
                r"(core\.fmtc\.bitdepth\(\s*src8\s*,\s*bits\s*=\s*)\d+",
                lambda m: m.group(1) + str(int(bits)),
                raw_line,
                count=1,
            )
        if re.match(r"res\s*=\s*core\.fmtc\.bitdepth\s*\(\s*res\s*,", s):
            return re.sub(
                r"(core\.fmtc\.bitdepth\(\s*res\s*,\s*bits\s*=\s*)\d+",
                lambda m: m.group(1) + str(int(bits)),
                raw_line,
                count=1,
            )
        return raw_line

    def sync_default_vpy_fmtc_with_encode_ui(self) -> None:
        """Write ``fmtc.bitdepth(..., bits=N)`` into default ``vpy.vpy`` from Encode tool + output depth."""
        try:
            box = getattr(self, 'encode_box', None)
            if box is not None and not box.isVisible():
                return
        except Exception:
            pass
        path = self.get_default_vpy_path()
        if not os.path.isfile(path):
            return
        bits = self._selected_output_bits_for_vpy()
        try:
            with open(path, 'r', encoding='utf-8') as fp:
                lines = fp.readlines()
        except Exception:
            return
        new_lines: list[str] = []
        changed = False
        for line in lines:
            raw = line.rstrip('\r\n')
            patched = self._patch_fmtc_output_bits_in_text(raw, bits)
            if patched != raw:
                changed = True
            new_lines.append(patched + '\n')
        if not changed:
            return
        try:
            with open(path, 'w', encoding='utf-8') as fp:
                fp.writelines(new_lines)
        except Exception:
            print_exc_terminal()

    def get_default_vpy_path(self) -> str:
        config_directory = os.environ.get('BLURAY_SUBTITLE_CONFIG_DIR')
        if config_directory:
            return os.path.normpath(
                os.path.abspath(os.path.join(config_directory, 'vpy.vpy'))
            )
        return os.path.normpath(os.path.abspath('vpy.vpy'))

    def ensure_default_vpy_file(self):
        path = self.get_default_vpy_path()
        if os.path.exists(path) and os.path.isfile(path):
            try:
                with open(path, 'r', encoding='utf-8') as fp:
                    existing = fp.read()
                marker = 'native_kernel = ""  # optional, auto-generated by app\n\n'
                upgraded = existing
                if (
                        _PREVIOUS_GETNATIVE_KERNEL_HELPER in upgraded
                        and _PREVIOUS_GETNATIVE_DESCALE_BLOCK in upgraded
                ):
                    upgraded = upgraded.replace(
                        _PREVIOUS_GETNATIVE_KERNEL_HELPER,
                        _GETNATIVE_KERNEL_HELPER,
                        1,
                    ).replace(
                        _PREVIOUS_GETNATIVE_DESCALE_BLOCK,
                        _GETNATIVE_DESCALE_BLOCK,
                        1,
                    )
                if _LEGACY_GETNATIVE_DESCALE_BLOCK in existing and marker in existing:
                    upgraded = upgraded.replace(
                        marker,
                        marker + _GETNATIVE_KERNEL_HELPER,
                        1,
                    ).replace(
                        _LEGACY_GETNATIVE_DESCALE_BLOCK,
                        _GETNATIVE_DESCALE_BLOCK,
                        1,
                    )
                can_upgrade_filter = (
                    marker in upgraded
                    and _GETNATIVE_KERNEL_HELPER in upgraded
                    and _GETNATIVE_DESCALE_BLOCK in upgraded
                )
                if _LEGACY_VPY_FILTER_BLOCK in upgraded and can_upgrade_filter:
                    filter_upgrade_base = upgraded
                    missing_settings = []
                    for setting_line in _VPY_PROCESSING_SETTINGS.splitlines(keepends=True):
                        setting_name = setting_line.split('=', 1)[0].strip()
                        if not setting_name:
                            continue
                        if not re.search(
                                rf'^{re.escape(setting_name)}\s*=',
                                upgraded,
                                re.MULTILINE,
                        ):
                            missing_settings.append(setting_line)
                    if missing_settings:
                        upgraded = upgraded.replace(
                            marker,
                            marker + ''.join(missing_settings) + '\n',
                            1,
                        )
                    if 'def _denoise_luma_protected(' not in upgraded:
                        upgraded = upgraded.replace(
                            _GETNATIVE_KERNEL_HELPER,
                            _GETNATIVE_KERNEL_HELPER + _VPY_PROCESSING_HELPERS,
                            1,
                        )
                    required_helpers = (
                        'def _denoise_luma_protected(',
                        'def _dehalo_luma(',
                        'def _dering_luma(',
                    )
                    required_settings = (
                        'denoise_strength',
                        'dehalo_strength',
                        'dering_strength',
                        'deband_strength',
                        'antialiasing_strength',
                    )
                    if (
                            all(helper in upgraded for helper in required_helpers)
                            and all(
                                re.search(
                                    rf'^{re.escape(name)}\s*=',
                                    upgraded,
                                    re.MULTILINE,
                                )
                                for name in required_settings
                            )
                    ):
                        upgraded = upgraded.replace(
                            _LEGACY_VPY_FILTER_BLOCK,
                            _VPY_FILTER_BLOCK,
                            1,
                        )
                    else:
                        upgraded = filter_upgrade_base
                if (
                        _PREVIOUS_VPY_PROCESSING_SETTINGS_V2 in upgraded
                        and _PREVIOUS_VPY_POST_FILTER_BLOCK_V2 in upgraded
                ):
                    upgraded = upgraded.replace(
                        _PREVIOUS_VPY_PROCESSING_SETTINGS_V2,
                        _VPY_PROCESSING_SETTINGS,
                        1,
                    ).replace(
                        _PREVIOUS_VPY_POST_FILTER_BLOCK_V2,
                        _VPY_POST_FILTER_BLOCK,
                        1,
                    )
                previous_post_filter = next((
                    block
                    for block in (
                        _PREVIOUS_VPY_POST_FILTER_BLOCK,
                        _LEGACY_WINDOWS_VPY_POST_FILTER_BLOCK,
                    )
                    if block in upgraded
                ), None)
                if (
                        previous_post_filter is not None
                        and _PREVIOUS_VPY_PROCESSING_SETTINGS in upgraded
                ):
                    upgraded = upgraded.replace(
                        _PREVIOUS_VPY_PROCESSING_SETTINGS,
                        _VPY_PROCESSING_SETTINGS,
                        1,
                    ).replace(
                        previous_post_filter,
                        _VPY_POST_FILTER_BLOCK,
                        1,
                    )
                elif (
                        previous_post_filter is not None
                        and _VPY_PROCESSING_SETTINGS in upgraded
                ):
                    upgraded = upgraded.replace(
                        previous_post_filter,
                        _VPY_POST_FILTER_BLOCK,
                        1,
                    )
                if upgraded != existing:
                    with open(path, 'w', encoding='utf-8') as fp:
                        fp.write(upgraded)
            except Exception:
                print_exc_terminal()
            return
        plugin_line = (
            '' if sys.platform == 'win32' else
            'DEFAULT_PLUGIN_PATH = "/app/plugins" if os.path.exists("/.dockerenv") else os.path.expanduser("~/plugins")\n'
            'PLUGIN_PATH = os.environ.get("BLURAYSUB_PLUGIN_PATH") or DEFAULT_PLUGIN_PATH\n'
            'if os.path.isdir(PLUGIN_PATH):\n'
            '    core.std.LoadAllPlugins(PLUGIN_PATH)\n'
        )
        content = (
                'import os\n'
                'import hashlib\n'
                'import tempfile\n'
                'import vapoursynth as vs\n'
                'from vapoursynth import core\n'
                + plugin_line +
                'import mvsfunc as mvf\n'
                '\n'
                '\n'
                'GRAY_CF = getattr(vs, "GRAY", None)\n'
                'if GRAY_CF is None:\n'
                '    GRAY_CF = getattr(vs.ColorFamily, "GRAY", 1)\n'
                '    setattr(vs, "GRAY", GRAY_CF)\n'
                'YUV_CF = getattr(vs, "YUV", None)\n'
                'if YUV_CF is None:\n'
                '    YUV_CF = getattr(vs.ColorFamily, "YUV", 2)\n'
                '    setattr(vs, "YUV", YUV_CF)\n'
                'if not hasattr(vs, "INTEGER"):\n'
                '    setattr(vs, "INTEGER", getattr(vs.SampleType, "INTEGER", 0))\n'
                'if not hasattr(vs, "FLOAT"):\n'
                '    setattr(vs, "FLOAT", getattr(vs.SampleType, "FLOAT", 1))\n'
                'a = r""  # optional, auto-generated by app\n'
                'native_h = 0  # optional, auto-generated by app\n'
                'native_kernel = ""  # optional, auto-generated by app\n'
                '\n'
                + _VPY_PROCESSING_SETTINGS
                + _GETNATIVE_KERNEL_HELPER
                + _VPY_PROCESSING_HELPERS
                + '_source_key = hashlib.sha1(\n'
                '    os.path.normcase(os.path.abspath(a)).encode("utf-8")\n'
                ').hexdigest()\n'
                '_lwi = os.path.join(tempfile.gettempdir(), "bluraysub_lwlibav_" + _source_key + ".lwi")\n'
                'src8 = core.lsmas.LWLibavSource(a, cache=1, cachefile=_lwi)\n'
                'if int(src8.get_frame(0).props.get("_FieldBased", 0)) != 0:\n'
                '    raise ValueError("The default VPy supports progressive video only; deinterlace the source first.")\n'
                'src16 = core.fmtc.bitdepth(src8, bits=16)\n'
                'target_w = src16.width\n'
                'target_h = src16.height\n'
                'proc16 = src16\n'
                'proc_w = target_w\n'
                'proc_h = target_h\n'
                'if native_h and native_h > 0 and native_h < target_h:\n'
                '    nh = int(native_h)\n'
                '    if nh % 2:\n'
                '        nh -= 1\n'
                '    native_w = int(round(nh * target_w / target_h))\n'
                '    if native_w % 2:\n'
                '        native_w -= 1\n'
                '    if native_w > 0:\n'
                '        proc_w = native_w\n'
                '        proc_h = nh\n'
                + _GETNATIVE_DESCALE_BLOCK
                + _VPY_FILTER_BLOCK
                + _VPY_POST_FILTER_BLOCK
                + 'if proc_w != target_w or proc_h != target_h:\n'
                '    merged = core.resize.Spline64(\n'
                '        merged, target_w, target_h, chromaloc_in_s="left", chromaloc_s="left"\n'
                '    )\n'
                '    merged = core.std.MaskedMerge(\n'
                '        merged, src16, rescale_mask, planes=[0, 1, 2], first_plane=True\n'
                '    )\n'
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
            print_exc_terminal()

    def delete_default_vpy_file(self):
        path = self.get_default_vpy_path()
        try:
            if os.path.exists(path) and os.path.isfile(path):
                os.remove(path)
        except Exception:
            print_exc_terminal()

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
            print_exc_terminal()
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
            print_exc_terminal()

    def create_vpy_path_widget(self, initial_path: Optional[str] = None, parent: Optional[QWidget] = None) -> QWidget:
        widget = QWidget(parent or self.table2)
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        widget.setLayout(layout)

        line_edit = QLineEdit(widget)
        line_edit.setText(initial_path or self.get_default_vpy_path())

        button = QPushButton(self.t('Select'), widget)

        def select_file():
            start_dir = os.path.dirname(line_edit.text()) if line_edit.text() else os.getcwd()
            path, _ = QFileDialog.getOpenFileName(
                self,
                self.t("Select VPy File"),
                start_dir,
                "Python/VapourSynth (*.py *.vpy)"
            )
            if path:
                line_edit.setText(os.path.normpath(path))

        button.clicked.connect(select_file)
        layout.addWidget(line_edit)
        layout.addWidget(button)
        return widget

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
            QMessageBox.information(self, "Prompt", "VPy path is empty")
            return
        if not os.path.exists(path):
            QMessageBox.information(self, "Prompt", f"File does not exist: {path}")
            return
        if sys.platform == 'win32':
            os.startfile(path)
        else:
            run_command(['xdg-open', path], wait=False)

    def open_vpy_in_vsedit(self, path: str) -> Optional[QProcess]:
        path = str(path or '').strip()
        if not path:
            QMessageBox.information(self, "Prompt", "VPy path is empty")
            return None
        if not os.path.exists(path):
            QMessageBox.information(self, "Prompt", f"File does not exist: {path}")
            return None

        vsedit_exe = VSEDIT_PATH
        if not vsedit_exe or not os.path.exists(vsedit_exe):
            vsedit_exe = shutil.which('vsedit') or ''
        if not vsedit_exe:
            QMessageBox.information(self, "Prompt", "vsedit not found, check VSEDIT_PATH or system PATH")
            return None

        try:
            proc = QProcess(self)
            environment = QProcessEnvironment.systemEnvironment()
            if str(PLUGIN_PATH or '').strip():
                environment.insert('BLURAYSUB_PLUGIN_PATH', str(PLUGIN_PATH))
            proc.setProcessEnvironment(environment)
            proc.setProgram(vsedit_exe)
            proc.setArguments([os.path.normpath(path)])
            proc.start()
            if not proc.waitForStarted(2000):
                QMessageBox.warning(self, "Prompt", "Failed to launch vsedit")
                try:
                    proc.kill()
                except Exception:
                    pass
                proc.deleteLater()
                return None
            return proc
        except Exception as e:
            QMessageBox.warning(self, "Prompt", f"Failed to open vsedit: {e}")
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

            restore_by_modified = {norm(mod): orig for orig, mod in mapping.values() if
                                   orig is not None and mod is not None}

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

        bits = self._selected_output_bits_for_vpy()
        processing_values = self._current_vpy_processing_values()
        changed = False
        for idx, line in enumerate(lines):
            raw = norm(line)
            pb = self._patch_fmtc_output_bits_in_text(raw, bits)
            if pb != raw:
                raw = pb
                lines[idx] = raw + '\n'
                changed = True
            pp = self._patch_vpy_processing_value_in_text(raw, processing_values)
            if pp != raw:
                raw = pp
                lines[idx] = raw + '\n'
                changed = True
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

            m_t = re.match(
                r'^(\s*)(#\s*)?(res\s*=\s*core\.assrender\.TextSub\(\s*res\s*,\s*file\s*=\s*sub_file\s*\))(\s*(#.*)?)$',
                raw)
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

            m_t = re.match(
                r'^(\s*)(#\s*)?(res\s*=\s*core\.assrender\.TextSub\(\s*res\s*,\s*file\s*=\s*sub_file\s*\))(\s*(#.*)?)$',
                raw)
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
            bits = self._selected_output_bits_for_vpy()
            processing_values = self._current_vpy_processing_values()
            with open(default_vpy, 'r', encoding='utf-8') as fp:
                lines = fp.readlines()

            out: list[str] = []
            for line in lines:
                raw = line.rstrip('\r\n')
                raw = self._patch_fmtc_output_bits_in_text(raw, bits)
                raw = self._patch_vpy_processing_value_in_text(raw, processing_values)

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

                m_t = re.match(
                    r'^(\s*)(#\s*)?(res\s*=\s*core\.assrender\.TextSub\(\s*res\s*,\s*file\s*=\s*sub_file\s*\))(\s*(#.*)?)$',
                    raw)
                if m_t:
                    indent = m_t.group(1)
                    expr = m_t.group(3)
                    suffix = m_t.group(4) or ''
                    comment = '' if subtitle_path else '# '
                    out.append(f'{indent}{comment}{expr}{suffix}\n')
                    continue

                out.append(raw + '\n')

            fd, temp_vpy = tempfile.mkstemp(prefix='bluraysubtitle_preview_', suffix='.vpy')
            os.close(fd)
            with open(temp_vpy, 'w', encoding='utf-8') as fp:
                fp.writelines(out)
            return temp_vpy
        except Exception:
            print_exc_terminal()
            return ''

    def _create_temp_edit_vpy_from_default(self, video_path: str, subtitle_path: str) -> str:
        """Create a temporary editable copy of default vpy with row-specific a/sub_file values."""
        self.ensure_default_vpy_file()
        default_vpy = self.get_default_vpy_path()
        if not os.path.exists(default_vpy):
            return ''
        try:
            bits = self._selected_output_bits_for_vpy()
            processing_values = self._current_vpy_processing_values()
            with open(default_vpy, 'r', encoding='utf-8') as fp:
                lines = fp.readlines()

            out: list[str] = []
            for line in lines:
                raw = line.rstrip('\r\n')
                raw = self._patch_fmtc_output_bits_in_text(raw, bits)
                raw = self._patch_vpy_processing_value_in_text(raw, processing_values)

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

                out.append(raw + '\n')

            fd, temp_vpy = tempfile.mkstemp(prefix='bluraysubtitle_edit_', suffix='.vpy')
            os.close(fd)
            with open(temp_vpy, 'w', encoding='utf-8') as fp:
                fp.writelines(out)
            return temp_vpy
        except Exception:
            print_exc_terminal()
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
            print_exc_terminal()

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
            print_exc_terminal()

    def _edit_vpy_with_default_sync(self, video_path: str, subtitle_path: str):
        """Open editable temp script and sync edits back to default vpy (except a=/sub_file=)."""
        temp_vpy = self._create_temp_edit_vpy_from_default(video_path=video_path or '',
                                                           subtitle_path=subtitle_path or '')
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
                should_load_subtitle = bool(
                    getattr(self, 'sub_pack_hard_radio', None) and self.sub_pack_hard_radio.isChecked())
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
            should_load_subtitle = bool(
                getattr(self, 'sub_pack_hard_radio', None) and self.sub_pack_hard_radio.isChecked())
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
            QMessageBox.information(self, "Prompt", "Cannot determine video file path")
            return

        vpy_path = (vpy_path or '').strip()
        default_vpy = self.get_default_vpy_path()
        if not vpy_path:
            vpy_path = default_vpy

        try:
            try:
                is_default = os.path.normcase(os.path.abspath(os.path.normpath(vpy_path))) == os.path.normcase(
                    os.path.abspath(os.path.normpath(default_vpy)))
            except Exception:
                is_default = False
            if is_default:
                self.ensure_default_vpy_file()
                temp_vpy = self._create_temp_preview_vpy_from_default(video_path=video_path,
                                                                      subtitle_path=subtitle_path or '')
                if not temp_vpy:
                    QMessageBox.warning(self, "Prompt", "Failed to generate preview script")
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
                self._update_vpy_paths_in_file(vpy_path=vpy_path, video_path=video_path,
                                               subtitle_path=subtitle_path or '')
                self.open_vpy_in_vsedit(vpy_path)
        except Exception as e:
            QMessageBox.warning(self, "Prompt", f"Preview script failed: {e}")

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
                should_load_subtitle = bool(
                    getattr(self, 'sub_pack_hard_radio', None) and self.sub_pack_hard_radio.isChecked())
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
            should_load_subtitle = bool(
                getattr(self, 'sub_pack_hard_radio', None) and self.sub_pack_hard_radio.isChecked())
        except Exception:
            should_load_subtitle = False
        subtitle_path = sub_item.text().strip() if should_load_subtitle and sub_item and sub_item.text().strip() else ''

        vpy_path = self.get_vpy_path_from_row(row_index)
        self._preview_script_for_row(vpy_path=vpy_path, video_path=video_path, subtitle_path=subtitle_path)

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
