"""Auto-generated split target: encode_and_audio_tasks."""
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import traceback
import multiprocessing
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Optional

import pycountry

from core.settings import VSPIPE_PATH
from ...core import FFMPEG_PATH
from ...core.settings import PLUGIN_PATH
from .service_base import BluraySubtitleServiceBase
from ...core import X265_PATH, MKV_INFO_PATH, MKV_EXTRACT_PATH, mkvtoolnix_ui_language_arg
from ...core.i18n import translate_text
from ...exports.utils import print_exc_terminal, get_vspipe_context, force_remove_file, print_terminal_line
from ...vs_tools.getnative import getnative as auto_getnative

MIGRATE_METHODS = ['flac_task', 'encode_task', 'extract_lossless']
KEEP_GETNATIVE_ARTIFACTS = bool(str(os.getenv("BLURAYSUB_KEEP_GETNATIVE_ARTIFACTS", "") or "").strip() == "1")
_GETNATIVE_DEBUG_DIR_ENV = str(os.getenv("BLURAYSUB_GETNATIVE_DEBUG_DIR", "") or "").strip()
GETNATIVE_DEBUG_DIR = os.path.abspath(_GETNATIVE_DEBUG_DIR_ENV) if _GETNATIVE_DEBUG_DIR_ENV else None


def _windows_no_window_flags() -> int:
    if sys.platform == "win32":
        return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return 0


def _split_x265_extra_args(params: str) -> list[str]:
    s = (params or "").strip()
    if not s:
        return []
    try:
        return shlex.split(s, posix=sys.platform != "win32")
    except ValueError:
        return s.split()


def _emit_encode_log_line(message: str) -> None:
    try:
        print_terminal_line(message)
    except Exception:
        print(message, flush=True)


def _encode_inherit_subprocess_stderr() -> bool:
    """True when not frozen: inherit vspipe/x265 stderr so the terminal shows native x265 output (\\r, no app parsing)."""
    return not (bool(getattr(sys, "frozen", False)) and hasattr(sys, "_MEIPASS"))


def _pump_subprocess_stderr_raw(stream) -> None:
    """Forward child stderr bytes unchanged (PyInstaller / no TTY)."""
    if stream is None:
        return
    out = getattr(sys.stderr, "buffer", None)
    try:
        while True:
            chunk = stream.read(65536)
            if not chunk:
                break
            if out is not None:
                try:
                    out.write(chunk)
                    out.flush()
                except Exception:
                    pass
            else:
                try:
                    sys.stderr.write(chunk.decode("utf-8", errors="replace"))
                    sys.stderr.flush()
                except Exception:
                    pass
    finally:
        try:
            stream.close()
        except Exception:
            pass


_X265_STATUS_PERCENT_RE = re.compile(r"\[\s*(\d+(?:\.\d+)?)\s*%\s*\]")


def _pump_x265_stderr_percent_steps(stream) -> None:
    """
    PyInstaller: x265 overwrites one status line with \\r. Each full snapshot ends at the next \\r;
    only those complete segments are parsed (avoids emitting half-lines when read() splits mid-line).
    Status lines like ``[1.0%] 326/32896 frames, ...`` are printed once per int(percent) step; other
    lines (warnings, etc.) print every time.
    """
    if stream is None:
        return
    out = getattr(sys.stderr, "buffer", None)
    last_int_pct = -1

    def write_line(text: str) -> None:
        t = text.rstrip("\r\n")
        if not t:
            return
        b = (t + "\n").encode("utf-8", errors="replace")
        if out is not None:
            try:
                out.write(b)
                out.flush()
            except Exception:
                pass
        else:
            try:
                sys.stderr.write(t + "\n")
                sys.stderr.flush()
            except Exception:
                pass

    def handle_segment(seg: str) -> None:
        nonlocal last_int_pct
        st = seg.strip()
        if not st:
            return
        m = _X265_STATUS_PERCENT_RE.search(st)
        if m:
            pct = float(m.group(1))
            ip = int(min(100, max(0, pct)))
            if ip > last_int_pct:
                last_int_pct = ip
                write_line(st)
        else:
            write_line(st)

    buf = bytearray()
    chunk_size = 8192
    try:
        while True:
            chunk = stream.read(chunk_size)
            if not chunk:
                break
            buf.extend(chunk)
            while b"\n" in buf:
                line, rest = buf.split(b"\n", 1)
                buf[:] = rest
                seg = line.split(b"\r")[-1].decode("utf-8", errors="replace")
                handle_segment(seg)
            if b"\r" in buf:
                parts = bytes(buf).split(b"\r")
                for part in parts[:-1]:
                    if not part.strip():
                        continue
                    seg = part.decode("utf-8", errors="replace")
                    handle_segment(seg)
                buf[:] = parts[-1]
            if len(buf) > 262144:
                del buf[:-131072]
        if buf.strip():
            seg = bytes(buf).decode("utf-8", errors="replace").strip()
            if seg:
                handle_segment(seg)
    finally:
        try:
            stream.close()
        except Exception:
            pass


def _run_vspipe_x265_with_progress(
    vspipe_exe: str,
    vpy_path: str,
    x265_exe: str,
    x265_params: str,
    hevc_file: str,
    env: Optional[dict],
) -> int:
    """
    vspipe --y4m | x265 without cmd.exe.
    Direct Python: stderr inherited and no CREATE_NO_WINDOW so cmd shows x265. Frozen: vspipe stderr raw; x265 stderr
    parsed for ``[n.n%]`` status lines and printed once per integer percent.
    """
    env_use = dict(env) if env else os.environ.copy()
    inherit_err = _encode_inherit_subprocess_stderr()
    popen_kw: dict = {"env": env_use}
    # CREATE_NO_WINDOW detaches from the parent console; stderr=None then often produces no visible x265 output in cmd.
    if sys.platform == "win32" and not inherit_err:
        popen_kw["creationflags"] = _windows_no_window_flags()
    # Default pipe buffering can hold stderr until the buffer fills or the process exits, so progress
    # appears only at the end; bufsize=0 uses unbuffered binary readers on the pipe fds.
    if not inherit_err:
        popen_kw["bufsize"] = 0
    stderr_v = None if inherit_err else subprocess.PIPE
    stderr_x = None if inherit_err else subprocess.PIPE

    vspipe_cmd = [str(vspipe_exe), "--y4m", str(vpy_path), "-"]
    x265_parts = _split_x265_extra_args(x265_params)
    x265_cmd = [str(x265_exe)] + x265_parts + ["--y4m", "-D", "10", "-o", str(hevc_file), "-"]

    p_v = subprocess.Popen(
        vspipe_cmd,
        stdout=subprocess.PIPE,
        stderr=stderr_v,
        **popen_kw,
    )
    p_x = subprocess.Popen(
        x265_cmd,
        stdin=p_v.stdout,
        stdout=subprocess.DEVNULL,
        stderr=stderr_x,
        **popen_kw,
    )
    if p_v.stdout is not None:
        p_v.stdout.close()

    pump_threads: list[threading.Thread] = []
    if not inherit_err:
        t_v = threading.Thread(target=_pump_subprocess_stderr_raw, args=(p_v.stderr,), daemon=True)
        t_x = threading.Thread(target=_pump_x265_stderr_percent_steps, args=(p_x.stderr,), daemon=True)
        t_v.start()
        t_x.start()
        pump_threads = [t_v, t_x]

    rc_x = int(p_x.wait())
    rc_v = int(p_v.wait())
    for t in pump_threads:
        t.join(timeout=5.0)
    if rc_x != 0:
        return rc_x
    return rc_v


def _ensure_runtime_vpy_file(vpy_path: str) -> bool:
    path = os.path.abspath(vpy_path or "").strip()
    if not path:
        return False
    if os.path.isfile(path):
        return True
    try:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        content = (
            "import os\n"
            "import hashlib\n"
            "import vapoursynth as vs\n"
            "from vapoursynth import core\n"
            "a = r\"\"  # optional, auto-generated by app\n"
            "native_h = 0  # optional, auto-generated by app\n"
            "native_kernel = \"\"  # optional, auto-generated by app\n"
            "try:\n"
            "    src8 = core.lsmas.LWLibavSource(a)\n"
            "except BaseException as _e:\n"
            "    if _e.__class__ in (KeyboardInterrupt, SystemExit):\n"
            "        raise\n"
            "    if type(_e).__name__ in (\"KeyboardInterrupt\", \"SystemExit\"):\n"
            "        raise\n"
            "    if hasattr(core, \"ffms2\"):\n"
            "        _t = os.environ.get(\"TEMP\") or os.environ.get(\"TMP\") or os.path.expandvars(\"%TEMP%\") or \".\"\n"
            "        _k = hashlib.sha1(os.path.normcase(os.path.normpath(a)).encode(\"utf-8\")).hexdigest()\n"
            "        _ffidx = os.path.join(_t, \"bluraysub_ffms2_\" + _k + \".ffindex\")\n"
            "        try:\n"
            "            src8 = core.ffms2.Source(a, cachefile=_ffidx)\n"
            "        except TypeError:\n"
            "            src8 = core.ffms2.Source(a)\n"
            "    else:\n"
            "        raise\n"
            "res = core.fmtc.bitdepth(src8, bits=10)\n"
            "# sub_file = \"\"  # optional, auto-generated by app\n"
            "# res = core.assrender.TextSub(res, file=sub_file)\n"
            "res.set_output()\n"
            "src8.set_output(1)\n"
        )
        with open(path, "w", encoding="utf-8") as fp:
            fp.write(content)
        return True
    except Exception:
        print_exc_terminal()
        return False


def _estimate_native_from_image_worker(image_path: str, plugin_path: str, debug_dir: Optional[str]) -> dict:
    try:
        # Keep worker independent from vapoursynth; VS work happens inside getnative.vpy via vspipe.
        from PIL import Image

        with Image.open(image_path) as img:
            h = int(img.height)
        loader = "pil"
        min_h = max(240, int(h * 0.40))
        max_h = min(h - 2, int(h * 0.98))
        if min_h >= max_h:
            return {
                "ok": False,
                "image": os.path.basename(image_path),
                "stage": "range",
                "error": f"invalid height search range - min_h={min_h}, max_h={max_h}, src_h={h}",
            }

        debug_out_dir = None
        try:
            if debug_dir:
                os.makedirs(debug_dir, exist_ok=True)
                base = os.path.splitext(os.path.basename(image_path))[0]
                cand = os.path.join(debug_dir, base)
                if os.path.exists(cand):
                    k = 1
                    while True:
                        cand2 = os.path.join(debug_dir, f"{base}_{k}")
                        if not os.path.exists(cand2):
                            cand = cand2
                            break
                        k += 1
                os.makedirs(cand, exist_ok=True)
                meta = {
                    "image": os.path.basename(image_path),
                    "range": [int(min_h), int(max_h)],
                    "loader": loader,
                    "src_h": int(h),
                }
                with open(os.path.join(cand, "meta.json"), "w", encoding="utf-8") as f:
                    json.dump(meta, f, ensure_ascii=False, indent=2)
                debug_out_dir = cand
        except Exception:
            debug_out_dir = None

        def _run_getnative_in_range(lo: int, hi: int) -> tuple[float, str, float, dict]:
            out0 = auto_getnative(
                image_path,
                src_heights=tuple(range(lo, hi + 1)),
                debug_dir=debug_out_dir,
                fast_mode=True,
                score_quit=0.0,
                score_margin=1.50,
                min_kernels=8,
                max_kernels=16,
                consensus_quit=True,
            )
            if isinstance(out0, dict):
                props0 = dict(out0)
            elif hasattr(out0, "get_frame"):
                props0 = dict(out0.get_frame(0).props)
            else:
                raise TypeError(f"unsupported getnative return type: {type(out0).__name__}")
            kernel0 = props0.get("getnative_kernel", "")
            if isinstance(kernel0, bytes):
                kernel0 = kernel0.decode("utf-8", errors="ignore")
            return (
                float(props0.get("getnative_height", 0.0)),
                str(kernel0),
                float(props0.get("getnative_score", 0.0)),
                dict(props0),
            )

        native_h, kernel, score, props = _run_getnative_in_range(min_h, max_h)
        curve_valid = int(props.get("getnative_curve_valid", 1))
        edge_hit = int(props.get("getnative_edge_hit", 0))
        dec_ratio = float(props.get("getnative_decreasing_ratio", 0.0))

        return {
            "ok": True,
            "height": native_h,
            "kernel": kernel,
            "score": score,
            "image": os.path.basename(image_path),
            "stage": "done",
            "range": [min_h, max_h],
            "loader": loader,
            "curve_valid": curve_valid,
            "edge_hit": edge_hit,
            "decreasing_ratio": dec_ratio,
        }
    except Exception as e:
        return {
            "ok": False,
            "image": os.path.basename(image_path),
            "stage": "run_getnative",
            "error": f"{type(e).__name__} - {e}",
            "traceback": traceback.format_exc(limit=8),
        }


class EncodeAudioTasksMixin(BluraySubtitleServiceBase):
    @staticmethod
    def _log_getnative(message: str):
        try:
            print_terminal_line(message)
        except Exception:
            print(message, flush=True)

    @staticmethod
    def _frame_discriminability_score(image_path: str) -> float:
        """Higher score means frame is more suitable for native-res estimation."""
        try:
            from PIL import Image
            import numpy as np
        except Exception:
            return 0.0
        try:
            img = Image.open(image_path).convert("L")
            w, h = img.size
            # Speed guard: downscale large frames before scoring.
            max_w = 960
            if w > max_w:
                nh = max(2, int(round(h * max_w / w)))
                img = img.resize((max_w, nh), Image.Resampling.BILINEAR)
            arr = np.asarray(img, dtype=np.float32) / 255.0
            if arr.ndim != 2 or arr.size == 0:
                return 0.0
            # Edge energy (simple gradient), luminance variance, and entropy.
            gx = np.abs(arr[:, 1:] - arr[:, :-1]).mean() if arr.shape[1] > 1 else 0.0
            gy = np.abs(arr[1:, :] - arr[:-1, :]).mean() if arr.shape[0] > 1 else 0.0
            edge = float((gx + gy) * 0.5)
            std = float(arr.std())
            hist, _ = np.histogram(arr, bins=64, range=(0.0, 1.0))
            p = hist.astype(np.float64)
            s = float(p.sum())
            if s > 0:
                p /= s
                p = p[p > 0]
                entropy = float(-(p * np.log2(p)).sum() / 6.0)  # normalize roughly to [0,1]
            else:
                entropy = 0.0
            return edge * 0.55 + std * 0.30 + entropy * 0.15
        except Exception:
            return 0.0

    def _extract_sample_images(self, video_path: str, temp_dir: str, max_total: int = 100) -> list[str]:
        score_map: dict[str, float] = {}
        target = max(1, int(max_total))
        rounds = [
            ('select_not_mod_240', 'select=\'not(mod(n,240))\',scale=iw:ih'),
            ('select_not_mod_120', 'select=\'not(mod(n,120))\',scale=iw:ih'),
            ('select_not_mod_60', 'select=\'not(mod(n,60))\',scale=iw:ih'),
            ('fps_1_2', 'fps=1/2,scale=iw:ih'),
            ('fps_1', 'fps=1,scale=iw:ih'),
        ]
        try:
            for ridx, (rname, vfexpr) in enumerate(rounds, start=1):
                pattern = os.path.join(temp_dir, "frame_%012d.png")
                cmd = (
                    f'"{FFMPEG_PATH}" -hide_banner -loglevel error -y -i "{video_path}" '
                    f'-vf "{vfexpr}" -vsync 0 -frames:v {target} -frame_pts 1 "{pattern}"'
                )
                subprocess.Popen(cmd, shell=True, creationflags=_windows_no_window_flags()).wait()

                imgs = sorted(
                    os.path.join(temp_dir, n)
                    for n in os.listdir(temp_dir)
                    if n.lower().endswith(".png")
                )
                for p in imgs:
                    if p not in score_map:
                        score_map[p] = self._frame_discriminability_score(p)

                ranked = sorted(score_map.items(), key=lambda kv: kv[1], reverse=True)
                selected = [p for p, _ in ranked][:target]
                self._log_getnative(
                    f'{self.t("[BluraySubtitle] getnative frame-screen round ")}{ridx}/{len(rounds)} - '
                    f'{self.t("candidates=")}{len(score_map)}{self.t(", selected=")}{len(selected)}'
                )
                if len(selected) >= target:
                    return selected[:target]
                if len(score_map) >= target:
                    return selected[:target]

            ranked = sorted(score_map.items(), key=lambda kv: kv[1], reverse=True)
            return [p for p, _ in ranked][:target]
        except Exception:
            print_exc_terminal()
            return []

    def _estimate_native_from_image(self, image_path: str) -> Optional[dict]:
        return _estimate_native_from_image_worker(image_path, str(PLUGIN_PATH or '').strip(), GETNATIVE_DEBUG_DIR)

    def _infer_native_resolution(self, video_path: str) -> Optional[dict]:
        desired_valid = 5
        max_total = 100
        valid_results: list[dict] = []
        all_sample_images: list[str] = []
        plugin_dir = str(PLUGIN_PATH or '').strip()

        try:
            temp_dir = tempfile.mkdtemp(prefix="bluraysub_native_")
            sample_images = self._extract_sample_images(video_path, temp_dir=temp_dir, max_total=max_total)
            all_sample_images.extend(sample_images)
            if not sample_images:
                return None

            batch_size = max(1, int(os.cpu_count() or 1))
            cursor = 0
            evaluated = 0
            while len(valid_results) < desired_valid and evaluated < max_total and cursor < len(sample_images):
                batch = sample_images[cursor:cursor + batch_size]
                cursor += len(batch)
                evaluated += len(batch)

                self._log_getnative(
                    f'{self.t("[BluraySubtitle] getnative round ")}{(evaluated + batch_size - 1) // batch_size} - '
                    f'{self.t("evaluating ")}{len(batch)}{self.t(" new samples ")}'
                    f'{self.t("(valid_so_far=")}{len(valid_results)})'
                )
                for idx, image in enumerate(batch, start=1):
                    self._log_getnative(
                        f'{self.t("[BluraySubtitle] getnative sample begin ")}{idx}/{len(batch)} - {os.path.basename(image)}'
                    )

                max_workers = max(1, min(len(batch), (os.cpu_count() or 1)))
                future_to_image: dict = {}
                try:
                    mp_method = "fork" if sys.platform != "win32" else "spawn"
                    mp_ctx = multiprocessing.get_context(mp_method)
                    with ProcessPoolExecutor(max_workers=max_workers, mp_context=mp_ctx) as executor:
                        for image in batch:
                            future = executor.submit(_estimate_native_from_image_worker, image, plugin_dir, GETNATIVE_DEBUG_DIR)
                            future_to_image[future] = image
                        ordered_results: dict[str, dict] = {}
                        for future in as_completed(future_to_image):
                            image = future_to_image[future]
                            try:
                                ordered_results[image] = future.result() or {}
                            except Exception as e:
                                ordered_results[image] = {
                                    "ok": False,
                                    "image": os.path.basename(image),
                                    "stage": "worker_process",
                                    "error": f"{type(e).__name__} - {e}",
                                }
                    eval_sequence = [(img, ordered_results.get(img, {})) for img in batch]
                except Exception as e:
                    self._log_getnative(
                        f'{self.t("[BluraySubtitle] getnative - multiprocessing unavailable, fallback to single process ")}'
                        f'({type(e).__name__} - {e})'
                    )
                    eval_sequence = [(img, self._estimate_native_from_image(img) or {}) for img in batch]

                for image, r in eval_sequence:
                    if not bool(r.get("ok", False)):
                        self._log_getnative(
                            f'{self.t("[BluraySubtitle] getnative sample failed: ")}{os.path.basename(image)} '
                            f'{self.t("(stage=")}{r.get("stage", "unknown")}{self.t(", error=")}{r.get("error", "unknown")})'
                        )
                        tb = str(r.get("traceback", "") or "").strip()
                        if tb:
                            self._log_getnative(
                                f'{self.t("[BluraySubtitle] getnative traceback for ")}{os.path.basename(image)}\n{tb}'
                            )
                        continue
                    if int(r.get("curve_valid", 1)) == 1:
                        self._log_getnative(
                            f'{self.t("[BluraySubtitle] getnative sample: ")}{r.get("image","")} -> '
                            f'{r.get("height",0):.2f}p {r.get("kernel","")} {self.t("score=")}{r.get("score",0):.6f} '
                            f'{self.t("range=")}{tuple(r.get("range", []))} {self.t("loader=")}{r.get("loader","unknown")} '
                            f'{self.t("curve_valid=")}{int(r.get("curve_valid", 1))} '
                            f'{self.t("edge_hit=")}{int(r.get("edge_hit", 0))} '
                            f'{self.t("dec_ratio=")}{float(r.get("decreasing_ratio", 0.0)):.3f}'
                        )
                        valid_results.append(r)
                    else:
                        self._log_getnative(
                            f'{self.t("[BluraySubtitle] getnative sample rejected by curve-shape: ")}'
                            f'{r.get("image","")} {self.t("edge_hit=")}{r.get("edge_hit",0)} '
                            f'{self.t("decreasing_ratio=")}{float(r.get("decreasing_ratio",0.0)):.3f} '
                            f'{self.t(" -> ")}{r.get("height",0):.2f}p {r.get("kernel","")} {self.t("score=")}{r.get("score",0):.6f}'
                        )
        finally:
            if not KEEP_GETNATIVE_ARTIFACTS:
                for image in all_sample_images:
                    try:
                        os.remove(image)
                    except Exception:
                        pass
                try:
                    if all_sample_images:
                        parent = os.path.dirname(all_sample_images[0])
                        if parent and os.path.isdir(parent):
                            os.rmdir(parent)
                except Exception:
                    pass

        if len(valid_results) < 2:
            total_seen = max(1, int(evaluated))
            self._log_getnative(
                f'[BluraySubtitle] getnative: insufficient valid curves ({len(valid_results)}/{total_seen})'
            )
            return None

        # Robust aggregation (minimal): keep dominant rounded-height cluster, then median.
        buckets: dict[int, list[dict]] = {}
        for r in valid_results:
            key = int(round(float(r.get("height", 0.0))))
            buckets.setdefault(key, []).append(r)

        def _row_weight(x: dict) -> float:
            s = max(0.0, float(x.get("score", 0.0)))
            h = max(1.0, float(x.get("height", 0.0)))
            rg = x.get("range", []) or []
            hi = float(rg[1]) if isinstance(rg, (list, tuple)) and len(rg) >= 2 else 1.0
            hi = max(1.0, hi)
            hr = max(0.0, min(1.0, h / hi))
            return s * (hr**4.0)

        def _bucket_weight(rows: list[dict]) -> float:
            ws = sorted((_row_weight(x) for x in rows), reverse=True)
            return float(sum(ws[:3]))

        best_key, best_rows = max(buckets.items(), key=lambda kv: (_bucket_weight(kv[1]), kv[0]))
        kept = best_rows

        heights = sorted(float(x["height"]) for x in kept)
        spread = heights[-1] - heights[0]
        if spread > 24:
            self._log_getnative(
                f'{self.t("[BluraySubtitle] getnative - sample spread too large ")}'
                f'({spread:.2f} > 24){self.t(", no consensus")}'
            )
            return None

        ws = [max(0.0, float(x.get("score", 0.0))) for x in kept]
        w2 = [_row_weight(x) for x in kept]
        wsum = float(sum(w2))
        if wsum <= 0:
            final_h = int(round(heights[len(heights) // 2]))
        else:
            final_h = int(round(sum(float(x["height"]) * w for x, w in zip(kept, w2)) / wsum))

        kernels: dict[str, float] = {}
        for r in kept:
            k = str(r.get("kernel", "") or "")
            kernels[k] = kernels.get(k, 0.0) + _row_weight(r)
        final_kernel = max(kernels.items(), key=lambda kv: kv[1])[0] if kernels else ""
        return {"height": final_h, "kernel": final_kernel, "confidence": max(x.get("score", 0.0) for x in kept)}

    def _cleanup_getnative_artifacts(self):
        if KEEP_GETNATIVE_ARTIFACTS:
            return
        try:
            debug_roots = []
            if GETNATIVE_DEBUG_DIR:
                debug_roots.append(str(GETNATIVE_DEBUG_DIR))
            debug_roots.append(os.path.abspath("getnative_debug"))
            debug_roots.append(os.path.abspath("get_native_debug"))
            for p0 in debug_roots:
                try:
                    if p0 and os.path.isdir(p0):
                        shutil.rmtree(p0, ignore_errors=True)
                except Exception:
                    pass
            for n in os.listdir("."):
                ln = n.lower()
                if (ln.startswith("auto_getnative_") and (ln.endswith(".png") or ln.endswith(".txt"))) or (
                    ln.startswith("getnative_") and (ln.endswith(".png") or ln.endswith(".txt"))
                ):
                    try:
                        p = os.path.abspath(n)
                        if os.path.isfile(p):
                            os.remove(p)
                    except Exception:
                        pass
        except Exception:
            pass

    def flac_task(self, output_file, dst_folder, i, source_file: Optional[str] = None):
        track_count, track_info, flac_files = self.process_audio_to_flac(output_file, dst_folder, i,
                                                                         source_file=source_file)
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
            subprocess.Popen(remux_cmd, shell=True, creationflags=_windows_no_window_flags()).wait()
            if same_mkv:
                if os.path.getsize(output_file1) > os.path.getsize(output_file):
                    os.remove(output_file1)
                else:
                    os.remove(output_file)
                    os.rename(output_file1, output_file)
            for flac_file in flac_files:
                os.remove(flac_file)
        self._extract_single_audio_from_mka(output_file)

    def encode_task(self, output_file, dst_folder, i, vpy_path: str, vspipe_mode: str, x265_mode: str, x265_params: str,
                    sub_pack_mode: str, source_file: Optional[str] = None):
        if not os.path.isfile(vpy_path):
            if _ensure_runtime_vpy_file(vpy_path):
                self._log_getnative(f'{self.t("[BluraySubtitle] recreate missing vpy: ")}{vpy_path}')
            else:
                self._log_getnative(f'{self.t("[BluraySubtitle] vpy not found and recreate failed: ")}{vpy_path}')
        if not os.path.isfile(vpy_path):
            return

        src_mkv = os.path.normpath(source_file) if source_file else os.path.normpath(output_file)
        self._cleanup_getnative_artifacts()
        use_getnative = bool(getattr(self, "use_getnative", True))
        native_info = None
        if use_getnative:
            self._log_getnative(f'{self.t("[BluraySubtitle] getnative - start analyzing ")}{os.path.basename(src_mkv)}')
            try:
                self._progress(text=f'{self.t("Getnative analyzing: ")}{os.path.basename(src_mkv)}')
            except Exception:
                pass
            native_info = self._infer_native_resolution(src_mkv)
            self._cleanup_getnative_artifacts()
            if native_info:
                self._log_getnative(
                    f'{self.t("[BluraySubtitle] getnative - ")}{os.path.basename(src_mkv)} -> '
                    f'{native_info["height"]}p ({native_info["kernel"]}, {self.t("score>=")}{native_info["confidence"]:.4f})'
                )
            else:
                self._log_getnative(
                    f'{self.t("[BluraySubtitle] getnative - ")}{os.path.basename(src_mkv)} -> '
                    f'{self.t("no confident native resolution")}'
                )

        def update_vpy_script():
            if not os.path.exists(vpy_path):
                return
            try:
                with open(vpy_path, 'r', encoding='utf-8') as fp:
                    lines = fp.readlines()
            except Exception:
                print_exc_terminal()
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

                if stripped.startswith('native_h ='):
                    if not native_info:
                        new_lines.append(line)
                        continue
                    indent = line[:len(line) - len(stripped)]
                    comment = ''
                    if '#' in stripped:
                        comment = ' #' + stripped.split('#', 1)[1].rstrip('\n')
                    native_h = int(native_info["height"]) if native_info else 0
                    if native_h > 0 and native_h % 2:
                        native_h -= 1
                    new_lines.append(f'{indent}native_h = {native_h}{comment}\n')
                    updated = True
                    continue

                if stripped.startswith('native_kernel ='):
                    if not native_info:
                        new_lines.append(line)
                        continue
                    indent = line[:len(line) - len(stripped)]
                    comment = ''
                    if '#' in stripped:
                        comment = ' #' + stripped.split('#', 1)[1].rstrip('\n')
                    native_kernel = str(native_info["kernel"]) if native_info else ""
                    native_kernel = native_kernel.replace('"', '\\"')
                    new_lines.append(f'{indent}native_kernel = "{native_kernel}"{comment}\n')
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
            script_text = ''.join(new_lines)
            try:
                with open(vpy_path, 'w', encoding='utf-8') as fp:
                    fp.write(script_text)
            except Exception:
                print_exc_terminal()

        update_vpy_script()

        def cleanup_lwi_for_source(source_path: str):
            for suffix in ('.lwi', '.lwi.lock'):
                try:
                    p = source_path + suffix
                    if os.path.exists(p) and os.path.isfile(p):
                        os.remove(p)
                except Exception:
                    print_exc_terminal()

        if vspipe_mode == 'bundle':
            vspipe_exe, vspipe_env = get_vspipe_context()
        else:
            vspipe_exe, vspipe_env = VSPIPE_PATH, None
        x265_exe = X265_PATH
        hevc_file = os.path.join(dst_folder, os.path.splitext(os.path.basename(output_file))[0] + '.hevc')
        cmd = f'"{vspipe_exe}" --y4m "{vpy_path}" - | "{x265_exe}" {x265_params or ""} --y4m -D 10 -o "{hevc_file}" -'
        print(f'{translate_text("Encode command:")}{cmd}')
        enc_rc = _run_vspipe_x265_with_progress(
            vspipe_exe, vpy_path, x265_exe, x265_params or "", hevc_file, vspipe_env
        )
        if enc_rc != 0:
            _emit_encode_log_line(f"[BluraySubtitle] encode pipeline exited with code {enc_rc}")
        cleanup_lwi_for_source(src_mkv)
        track_count, track_info, flac_files = self.process_audio_to_flac(output_file, dst_folder, i,
                                                                         source_file=src_mkv)

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
            subprocess.Popen(remux_cmd, shell=True, creationflags=_windows_no_window_flags()).wait()
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

    def extract_lossless(self, mkv_file: str, dolby_truehd_tracks: list[int], output_base: Optional[str] = None) -> \
    tuple[int, dict[int, str]]:
        if sys.platform == 'win32':
            process = subprocess.Popen(f'"{MKV_INFO_PATH}" "{mkv_file}" --ui-language en',
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                       encoding='utf-8', errors='ignore', shell=True,
                                       creationflags=_windows_no_window_flags())
        else:
            process = subprocess.Popen(f'"{MKV_INFO_PATH}" "{mkv_file}" --ui-language en_US',
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                       encoding='utf-8', errors='ignore', shell=True,
                                       creationflags=_windows_no_window_flags())
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
            subprocess.Popen(extract_cmd, shell=True, creationflags=_windows_no_window_flags()).wait()

        return track_count, track_info
