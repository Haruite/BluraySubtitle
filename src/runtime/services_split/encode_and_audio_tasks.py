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

from ...core.settings import VSPIPE_PATH, TRUEHDD_PATH
from ...core import FFMPEG_PATH, FFPROBE_PATH
from ...core.settings import PLUGIN_PATH
from .service_base import BluraySubtitleServiceBase
from ...core import MKV_INFO_PATH, MKV_EXTRACT_PATH, DOVI_TOOL_PATH, mkvtoolnix_ui_language_arg
from .media_info_and_track_mapping import MediaInfoTrackMappingMixin
from ...core.i18n import translate_text
from ...exports.utils import (
    print_exc_terminal,
    get_vspipe_context,
    force_remove_file,
    print_terminal_line,
    run_shell_command_with_output,
    resolve_encoder_executable_path,
    mkv_codec_id_is_dts_family,
)
from ...vs_tools.getnative import getnative as auto_getnative

MIGRATE_METHODS = ['flac_task', 'encode_task', 'extract_lossless']
KEEP_GETNATIVE_ARTIFACTS = bool(str(os.getenv("BLURAYSUB_KEEP_GETNATIVE_ARTIFACTS", "") or "").strip() == "1")

_EXTERNAL_AUDIO_SUFFIXES = (
    '.flac', '.m4a', '.opus', '.ac3', '.eac3', '.aac', '.mp3', '.mp2', '.ogg', '.dts', '.thd', '.wav', '.w64',
)


def _truehdd_exe() -> str:
    from ...core import settings as _core_settings
    raw = str(getattr(_core_settings, 'TRUEHDD_PATH', '') or TRUEHDD_PATH or '').strip()
    if raw and os.path.isfile(raw):
        return raw
    return shutil.which('truehdd') or shutil.which('truehdd.exe') or ''


def _ffprobe_audio_params(path: str) -> dict[str, int]:
    """Best-effort channel count / sample rate for elementary or PCM audio."""
    out = {'channels': 8, 'sample_rate': 48000, 'bits': 24}
    if not path or not os.path.isfile(path):
        return out
    try:
        proc = subprocess.run(
            [FFPROBE_PATH or 'ffprobe', '-v', 'error', '-select_streams', 'a:0',
             '-show_entries', 'stream=channels,sample_rate,bits_per_raw_sample,sample_fmt',
             '-of', 'json', path],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='ignore',
            shell=False,
        )
        data = json.loads(proc.stdout or '{}')
        streams = data.get('streams') or []
        if not streams:
            return out
        st = streams[0] if isinstance(streams[0], dict) else {}
        try:
            out['channels'] = max(1, int(st.get('channels') or out['channels']))
        except Exception:
            pass
        try:
            out['sample_rate'] = max(1, int(st.get('sample_rate') or out['sample_rate']))
        except Exception:
            pass
        try:
            bits = int(st.get('bits_per_raw_sample') or 0)
            if bits > 0:
                out['bits'] = bits
        except Exception:
            pass
        fmt = str(st.get('sample_fmt') or '').lower()
        if 's32' in fmt:
            out['bits'] = 32
        elif 's16' in fmt:
            out['bits'] = 16
    except Exception:
        pass
    return out


def _pcm_raw_to_wav(pcm_path: str, wav_path: str, channels: int, sample_rate: int, bits: int = 24) -> bool:
    """
    Wrap truehdd raw PCM (24-bit little-endian per ``truehdd decode --format pcm``) as RIFF WAV.

    *channels* and *sample_rate* must match the decoded presentation; wrong values produce noise.
    """
    if not os.path.isfile(pcm_path):
        return False
    bits = 24 if int(bits or 0) not in (16, 24, 32) else int(bits)
    fmt = {16: 's16le', 24: 's24le', 32: 's32le'}[bits]
    try:
        ch = max(1, int(channels or 8))
        sr = max(1, int(sample_rate or 48000))
    except Exception:
        ch, sr = 8, 48000
    pcm_codec = {16: 'pcm_s16le', 24: 'pcm_s24le', 32: 'pcm_s32le'}[bits]
    cmd = (
        f'"{FFMPEG_PATH}" -hide_banner -loglevel error -y '
        f'-f {fmt} -ar {sr} -ac {ch} -i "{pcm_path}" -c:a {pcm_codec} "{wav_path}"'
    )
    try:
        subprocess.run(cmd, shell=True, check=False, creationflags=_windows_no_window_flags())
        return os.path.isfile(wav_path) and os.path.getsize(wav_path) > 0
    except Exception:
        return False


def _ffmpeg_container_to_riff_wav(src_path: str, wav_path: str) -> bool:
    """Demux truehdd W64/CAF (or any ffmpeg-readable audio) into standard RIFF WAV."""
    if not os.path.isfile(src_path):
        return False
    cmd = (
        f'"{FFMPEG_PATH}" -hide_banner -loglevel error -y '
        f'-i "{src_path}" -c:a pcm_s24le "{wav_path}"'
    )
    try:
        subprocess.run(cmd, shell=True, check=False, creationflags=_windows_no_window_flags())
        return os.path.isfile(wav_path) and os.path.getsize(wav_path) > 0
    except Exception:
        return False


def _truehdd_info_pcm_params(exe: str, thd_path: str, presentation: int) -> dict[str, int]:
    """Parse ``truehdd info`` text for a presentation's channel count and sample rate."""
    out = {'channels': 8, 'sample_rate': 48000, 'bits': 24}
    if not exe or not os.path.isfile(thd_path):
        return out
    try:
        proc = subprocess.run(
            [exe, 'info', thd_path],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='ignore',
            shell=False,
            creationflags=_windows_no_window_flags(),
        )
    except Exception:
        return out
    text = f'{proc.stdout or ""}\n{proc.stderr or ""}'
    pres = int(presentation)
    block = text
    for marker in (
            f'presentation {pres}',
            f'Presentation {pres}',
            f'presentation index {pres}',
            f'Presentation index {pres}',
    ):
        idx = text.lower().find(marker.lower())
        if idx >= 0:
            block = text[idx:idx + 4000]
            break
    ch_m = re.search(r'(?i)(?:channels?|ch)\s*[:=]\s*(\d+)', block)
    if ch_m:
        try:
            out['channels'] = max(1, int(ch_m.group(1)))
        except Exception:
            pass
    sr_m = re.search(r'(?i)sample\s*rate\s*[:=]?\s*(\d+)', block)
    if not sr_m:
        sr_m = re.search(r'(?i)(\d{5,6})\s*Hz', block)
    if sr_m:
        try:
            out['sample_rate'] = max(1, int(sr_m.group(1)))
        except Exception:
            pass
    return out


def _lossy_extract_suffix_for_codec_id(codec_id: str) -> Optional[str]:
    """Elementary-file suffix for lossy audio Codec IDs (excludes LPCM/DTS/TRUEHD/FLAC handled elsewhere)."""
    cid = str(codec_id or '').strip().upper()
    if not cid or cid in ('A_PCM/INT/LIT', 'A_PCM/INT/BIG', 'A_TRUEHD', 'A_MLP', 'A_FLAC'):
        return None
    if mkv_codec_id_is_dts_family(cid):
        return None
    if cid == 'A_AC3':
        return 'ac3'
    if cid == 'A_EAC3':
        return 'eac3'
    if cid.startswith('A_AAC'):
        return 'aac'
    if cid == 'A_MPEG/L3':
        return 'mp3'
    if cid == 'A_MPEG/L2':
        return 'mp2'
    if cid == 'A_OPUS':
        return 'opus'
    if cid == 'A_VORBIS':
        return 'ogg'
    return None
_GETNATIVE_DEBUG_DIR_ENV = str(os.getenv("BLURAYSUB_GETNATIVE_DEBUG_DIR", "") or "").strip()
GETNATIVE_DEBUG_DIR = os.path.abspath(_GETNATIVE_DEBUG_DIR_ENV) if _GETNATIVE_DEBUG_DIR_ENV else None


def _windows_no_window_flags() -> int:
    if sys.platform == "win32":
        return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return 0


def _run_mkvmerge_shell(cmd: str) -> int:
    return run_shell_command_with_output(cmd)


def _commit_inplace_mkv_remux(output_file: str, temp_mkv: str, mux_rc: int) -> bool:
    """
    Replace *output_file* with *temp_mkv* after a same-path audio remux.

    Do not discard the remux solely because the container grew (e.g. TrueHD→FLAC
    swap can still increase size when other tracks/subtitles differ).
    """
    if mux_rc != 0:
        print(
            f'{translate_text("mkvmerge 混流失败 (exit ")}{mux_rc}'
            f'{translate_text(")，保留原 MKV：")}{output_file}',
            flush=True,
        )
        if os.path.isfile(temp_mkv):
            force_remove_file(temp_mkv)
        return False
    if not os.path.isfile(temp_mkv) or os.path.getsize(temp_mkv) < 1024:
        print(
            f'{translate_text("mkvmerge 混流未生成有效 tmp，保留原 MKV：")}{output_file}',
            flush=True,
        )
        if os.path.isfile(temp_mkv):
            force_remove_file(temp_mkv)
        return False
    try:
        orig_sz = os.path.getsize(output_file)
        new_sz = os.path.getsize(temp_mkv)
    except OSError:
        orig_sz = 0
        new_sz = 0
    if new_sz > orig_sz:
        print(
            f'{translate_text("混流后文件变大 (")}{new_sz / 1024 ** 2:.1f} MiB > '
            f'{orig_sz / 1024 ** 2:.1f} MiB{translate_text(")，仍应用音轨替换结果")}',
            flush=True,
        )
    force_remove_file(output_file)
    os.rename(temp_mkv, output_file)
    return True


def _split_x265_extra_args(params: str) -> list[str]:
    s = (params or "").strip()
    if not s:
        return []
    try:
        return shlex.split(s, posix=sys.platform != "win32")
    except ValueError:
        return s.split()


def _normalize_x264_extra_for_bit_depth(extra: list[str], bd: str) -> list[str]:
    """Map x264 --profile to output depth: 8-bit → high, 10-bit → high10 (see x264 --output-depth)."""
    out = list(extra)
    b = str(bd or "").strip()
    if b not in ("8", "10"):
        return out
    want = "high10" if b == "10" else "high"

    i = 0
    found_profile = False
    while i < len(out):
        tok = out[i]
        if tok == "--profile" and i + 1 < len(out):
            found_profile = True
            pv = out[i + 1]
            if pv == "high" and want == "high10":
                out[i + 1] = "high10"
            elif pv == "high10" and want == "high":
                out[i + 1] = "high"
            i += 2
            continue
        if isinstance(tok, str) and tok.startswith("--profile="):
            found_profile = True
            key, _, val = tok.partition("=")
            if val == "high" and want == "high10":
                out[i] = f"{key}=high10"
            elif val == "high10" and want == "high":
                out[i] = f"{key}=high"
            i += 1
            continue
        i += 1

    if not found_profile and b == "10":
        out = ["--profile", "high10"] + out
    return out


def _emit_encode_log_line(message: str) -> None:
    try:
        print_terminal_line(message)
    except Exception:
        print(message, flush=True)


def _format_encoder_cmd_for_echo(enc_cmd: list) -> str:
    """Shell-style echo string; always quote paths after ``-o`` / ``-b``."""
    parts: list[str] = []
    i = 0
    if enc_cmd:
        exe = str(enc_cmd[0])
        parts.append(f'"{exe}"' if (' ' in exe or ';' in exe) else exe)
        i = 1
    while i < len(enc_cmd):
        tok = str(enc_cmd[i])
        if tok in ('-o', '-b') and i + 1 < len(enc_cmd):
            parts.append(tok)
            parts.append(f'"{enc_cmd[i + 1]}"')
            i += 2
            continue
        if ' ' in tok or ';' in tok:
            parts.append(f'"{tok}"')
        else:
            parts.append(tok)
        i += 1
    return ' '.join(parts)


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


def _run_vspipe_piped_encode(
    vspipe_exe: str,
    vpy_path: str,
    encoder_cmd: list[str],
    env: Optional[dict],
) -> int:
    """
    vspipe --y4m | encoder (x264 / x265 / SvtAv1EncApp) without cmd.exe.
    In a real TTY, inherit the encoder stderr so x265 can use \\r line progress; otherwise pipe and
    forward stderr bytes unchanged (same as x264/SVT) so logs match the encoder's native output.
    """
    env_use = dict(env) if env else os.environ.copy()
    inherit_err = _encode_inherit_subprocess_stderr()
    try:
        stderr_is_tty = sys.stderr.isatty()
    except Exception:
        stderr_is_tty = False
    use_encoder_stderr_inherit = bool(inherit_err and stderr_is_tty)
    popen_kw: dict = {"env": env_use, "bufsize": 0}
    if sys.platform == "win32" and not inherit_err:
        popen_kw["creationflags"] = _windows_no_window_flags()
    stderr_v = None if inherit_err else subprocess.PIPE
    stderr_e = None if use_encoder_stderr_inherit else subprocess.PIPE

    vspipe_cmd = [str(vspipe_exe), "--y4m", str(vpy_path), "-"]
    enc_cmd = [str(x) for x in encoder_cmd]

    p_v = subprocess.Popen(
        vspipe_cmd,
        stdout=subprocess.PIPE,
        stderr=stderr_v,
        **popen_kw,
    )
    p_e = subprocess.Popen(
        enc_cmd,
        stdin=p_v.stdout,
        stdout=subprocess.DEVNULL,
        stderr=stderr_e,
        **popen_kw,
    )
    if p_v.stdout is not None:
        p_v.stdout.close()

    pump_threads: list[threading.Thread] = []
    if stderr_v is not None:
        t_v = threading.Thread(target=_pump_subprocess_stderr_raw, args=(p_v.stderr,), daemon=True)
        t_v.start()
        pump_threads.append(t_v)
    if stderr_e is not None:
        t_e = threading.Thread(target=_pump_subprocess_stderr_raw, args=(p_e.stderr,), daemon=True)
        t_e.start()
        pump_threads.append(t_e)

    rc_e = int(p_e.wait())
    rc_v = int(p_v.wait())
    for t in pump_threads:
        t.join(timeout=5.0)
    if rc_e != 0:
        return rc_e
    return rc_v


def _run_vspipe_svt_win_tempfile_encode(
    vspipe_exe: str,
    vpy_path: str,
    encoder_cmd: list[str],
    env: Optional[dict],
    *,
    temp_dir: Optional[str] = None,
) -> int:
    """
    Windows-only escape hatch: vspipe → full .y4m on disk → SvtAv1EncApp -i <file>.
    Avoids pipe short-read / CRLF / CRT quirks; needs free disk space for the entire y4m stream.
    """
    env_use = dict(env) if env else os.environ.copy()
    popen_kw: dict = {"env": env_use}
    if sys.platform == "win32":
        popen_kw["creationflags"] = _windows_no_window_flags()
    td = temp_dir
    if td:
        try:
            os.makedirs(td, exist_ok=True)
        except Exception:
            td = None
    fd, y4m_path = tempfile.mkstemp(
        prefix="bluraysub_svt_", suffix=".y4m", dir=td if td else None
    )
    os.close(fd)
    vspipe_cmd = [str(vspipe_exe), "--y4m", str(vpy_path), "-"]
    enc_cmd = [str(x) for x in encoder_cmd]
    try:
        with open(y4m_path, "wb") as y4m_f:
            p_v = subprocess.run(vspipe_cmd, stdout=y4m_f, stderr=subprocess.PIPE, **popen_kw)
        if p_v.returncode != 0:
            try:
                tail = (p_v.stderr or b"").decode("utf-8", errors="replace")[-600:]
                _emit_encode_log_line(f"[BluraySubtitle] vspipe temp-y4m failed rc={p_v.returncode}\n{tail}")
            except Exception:
                pass
            return int(p_v.returncode)
        enc_fs = [y4m_path if a.lower() == "stdin" else a for a in enc_cmd]
        p_e = subprocess.run(enc_fs, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, **popen_kw)
        if p_e.returncode != 0:
            try:
                tail = (p_e.stderr or b"").decode("utf-8", errors="replace")[-800:]
                if tail.strip():
                    _emit_encode_log_line(f"[BluraySubtitle] SvtAv1EncApp stderr (tail):\n{tail}")
            except Exception:
                pass
        return int(p_e.returncode)
    finally:
        try:
            os.remove(y4m_path)
        except OSError:
            pass


def _normalize_encode_tool_label(raw: str) -> str:
    s = (raw or "").strip().lower()
    if s in ("x264", "x265", "svtav1"):
        return s
    if s == "sav1" or s == "av1":
        return "svtav1"
    return "x265"


def _svtav1_extra_has_explicit_profile(extra: list[str]) -> bool:
    """True if SvtAv1EncApp args already set --profile / -profile (12-bit needs profile 2 when unset)."""
    for a in extra or []:
        al = str(a).strip().lower()
        if al in ("--profile", "-profile"):
            return True
        if al.startswith("--profile=") or al.startswith("-profile="):
            return True
    return False


def _video_intermediate_extension(tool: str) -> str:
    t = _normalize_encode_tool_label(tool)
    return { "x264": ".h264", "x265": ".hevc", "svtav1": ".ivf" }[t]


def encode_dovi_supported(tool: str, encode_bit_depth: str) -> bool:
    """Dolby Vision encode path requires x265 or SVT-AV1 at 10-bit or deeper."""
    tool_key = _normalize_encode_tool_label(tool)
    if tool_key not in ('x265', 'svtav1'):
        return False
    try:
        bd = int(str(encode_bit_depth or '10').strip())
    except Exception:
        bd = 10
    return bd >= 10


def encode_dovi_preflight_mkv_paths(
        mkv_paths: list[str],
        encode_tool: str,
        encode_bit_depth: str,
) -> Optional[str]:
    """Return an error message if any *mkv_paths* is Dolby Vision but encode settings are unsupported."""
    if encode_dovi_supported(encode_tool, encode_bit_depth):
        return None
    for p in mkv_paths or []:
        path = os.path.normpath(str(p or ''))
        if not path or not os.path.isfile(path):
            continue
        if MediaInfoTrackMappingMixin.mkvinfo_dolby_vision_track_id(path) is not None:
            return translate_text('Dolby Vision 不支持 h264 或输出位深 8bit')
    return None


def _dovi_tool_exe_encode() -> str:
    raw = str(DOVI_TOOL_PATH or '').strip()
    if raw and os.path.isfile(raw):
        return raw
    return shutil.which('dovi_tool') or shutil.which('dovi_tool.exe') or ''


def prepare_encode_dolby_vision(
        mkv_path: str,
        dst_folder: str,
        track_id: int,
) -> Optional[dict[str, str]]:
    """
  Extract DoVi HEVC from MKV, demux BL for VapourSynth, ``extract-rpu`` from source HEVC.

  Returns dict with keys ``bl_hevc``, ``rpu_bin``, ``work_dir`` or None on failure.
    """
    mkv_path = os.path.normpath(str(mkv_path or ''))
    if not mkv_path or not os.path.isfile(mkv_path):
        return None
    work_dir = os.path.normpath(os.path.join(str(dst_folder or '.'), '_dovi_encode'))
    try:
        os.makedirs(work_dir, exist_ok=True)
    except Exception:
        return None
    stem = os.path.splitext(os.path.basename(mkv_path))[0]
    extract_path = os.path.normpath(os.path.join(work_dir, f'{stem}.dovi_src.hevc'))
    target_el = os.path.normpath(os.path.join(work_dir, f'{stem}.EL.hevc'))
    target_bl = os.path.normpath(os.path.join(work_dir, f'{stem}.BL.hevc'))
    rpu_path = os.path.normpath(os.path.join(work_dir, 'RPU.bin'))
    for stale in (extract_path, target_el, target_bl, rpu_path):
        try:
            if os.path.isfile(stale):
                os.remove(stale)
        except OSError:
            pass
    extract_exe = str(MKV_EXTRACT_PATH or '').strip() or 'mkvextract'
    extract_cmd = (
        f'"{extract_exe}" {mkvtoolnix_ui_language_arg()} tracks "{mkv_path}" '
        f'{int(track_id)}:"{extract_path}"'
    )
    print(f'[encode-dovi] {extract_cmd}')
    rc = run_shell_command_with_output(extract_cmd)
    if rc != 0:
        print(f'[encode-dovi] mkvextract failed: exit {rc}')
    if rc != 0 or not os.path.isfile(extract_path) or os.path.getsize(extract_path) < 1024:
        print(f'[encode-dovi] mkvextract failed rc={rc}')
        return None
    dovi_exe = _dovi_tool_exe_encode()
    if not dovi_exe:
        print('[encode-dovi] dovi_tool executable not found (DOVI_TOOL_PATH)')
        return None
    demux_cmd = (
        f'"{dovi_exe}" -m 2 demux -e "{target_el}" -b "{target_bl}" "{extract_path}"'
    )
    print(f'[encode-dovi] output dir: {work_dir}')
    print(f'[encode-dovi] {demux_cmd}')
    rc_d = run_shell_command_with_output(demux_cmd, cwd=work_dir)
    if rc_d != 0:
        print(f'[encode-dovi] dovi_tool demux exit {rc_d}')
        return None
    el_path, bl_path = target_el, target_bl
    min_hevc = 1024
    if (
            not os.path.isfile(bl_path)
            or os.path.getsize(bl_path) < min_hevc
    ):
        print(
            f'[encode-dovi] demux did not produce BL under {work_dir}: '
            f'{os.path.basename(target_bl)}',
        )
        return None
    extract_rpu_cmd = f'"{dovi_exe}" extract-rpu "{extract_path}" -o "{rpu_path}"'
    print(f'[encode-dovi] {extract_rpu_cmd}')
    rc_rpu = run_shell_command_with_output(extract_rpu_cmd, timeout=7200)
    if rc_rpu != 0 or not os.path.isfile(rpu_path) or os.path.getsize(rpu_path) < 64:
        print(f'[encode-dovi] extract-rpu failed rc={rc_rpu}')
        return None
    for discard in (el_path, extract_path):
        try:
            if os.path.isfile(discard):
                os.remove(discard)
        except OSError:
            pass
    print(f'[encode-dovi] RPU.bin ok, BL={bl_path}')
    return {'bl_hevc': bl_path, 'rpu_bin': rpu_path, 'work_dir': work_dir}


def dovi_tool_inject_rpu_hevc(hevc_path: str, rpu_bin: str) -> bool:
    """Inject RPU into encoded HEVC; replace *hevc_path* in place."""
    hevc = os.path.normpath(str(hevc_path or ''))
    rpu = os.path.normpath(str(rpu_bin or ''))
    if not hevc or not rpu or not os.path.isfile(hevc) or not os.path.isfile(rpu):
        return False
    exe = _dovi_tool_exe_encode()
    if not exe:
        print('[encode-dovi] dovi_tool executable not found for inject-rpu')
        return False
    out_tmp = hevc + '.tmp.hevc'
    try:
        if os.path.isfile(out_tmp):
            os.remove(out_tmp)
    except OSError:
        pass
    cmd = f'"{exe}" inject-rpu -i "{hevc}" --rpu-in "{rpu}" -o "{out_tmp}"'
    print(f'[encode-dovi] {cmd}')
    rc = run_shell_command_with_output(cmd, timeout=7200)
    if rc != 0 or not os.path.isfile(out_tmp):
        print(f'[encode-dovi] inject-rpu failed rc={rc}')
        return False
    try:
        os.remove(hevc)
    except OSError:
        pass
    try:
        os.replace(out_tmp, hevc)
    except OSError:
        try:
            shutil.copy2(out_tmp, hevc)
            os.remove(out_tmp)
        except Exception:
            return False
    try:
        if os.path.isfile(out_tmp):
            os.remove(out_tmp)
    except OSError:
        pass
    out_sz = os.path.getsize(hevc) if os.path.isfile(hevc) else 0
    print(f'[encode-dovi] inject-rpu ok -> {hevc} ({out_sz} bytes)', flush=True)
    return out_sz > 1024


def cleanup_encode_dolby_vision_workdir(plan: Optional[dict[str, str]]) -> None:
    if not plan:
        return
    for key in ('el_hevc', 'bl_hevc', 'rpu_bin', 'dovi_src_hevc'):
        p = str((plan or {}).get(key) or '')
        if p and os.path.isfile(p):
            try:
                os.remove(p)
            except OSError:
                pass
    wd = str((plan or {}).get('work_dir') or '')
    if wd and os.path.isdir(wd):
        try:
            shutil.rmtree(wd, ignore_errors=True)
        except Exception:
            pass


_VPY_A_LINE_RE = re.compile(
    r'^(\s*)(#\s*)?(\ba\s*=\s*)(.+?)(\s*(#.*)?)\s*$',
)


def _to_vpy_raw_string(value: str) -> str:
    return 'r"' + str(value or '').replace('"', '\\"') + '"'


def _write_vpy_video_source_a(vpy_path: str, video_path: str) -> bool:
    """Set ``a = r"..."`` in *vpy_path* (skip commented assignments)."""
    vpy_path = os.path.normpath(os.path.abspath(str(vpy_path or '').strip()))
    video_path = os.path.normpath(str(video_path or '').strip())
    if not vpy_path or not os.path.isfile(vpy_path) or not video_path:
        return False
    try:
        with open(vpy_path, 'r', encoding='utf-8') as fp:
            lines = fp.readlines()
    except Exception:
        print_exc_terminal()
        return False
    rhs = _to_vpy_raw_string(video_path)
    patched = False
    new_lines: list[str] = []
    for line in lines:
        raw = line.rstrip('\r\n')
        m = _VPY_A_LINE_RE.match(raw)
        if not m or m.group(2):
            new_lines.append(line)
            continue
        indent, expr, suffix = m.group(1), m.group(3), m.group(5) or ''
        new_raw = f'{indent}{expr}{rhs}{suffix}'
        new_lines.append(new_raw + '\n')
        patched = True
    if not patched:
        insert_at = len(new_lines)
        for idx, line in enumerate(new_lines):
            if 'LWLibavSource' in line or 'ffms2.Source' in line:
                insert_at = idx
                break
        new_lines.insert(insert_at, f'a = {rhs}  # auto-generated by app\n')
    try:
        with open(vpy_path, 'w', encoding='utf-8') as fp:
            fp.writelines(new_lines)
    except Exception:
        print_exc_terminal()
        return False
    print(f'[encode] vpy a = {video_path}', flush=True)
    return True


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
        external_audio = list(dict.fromkeys(
            (getattr(self, '_track_flac_map', {}) or {}).values()))
        if not external_audio:
            external_audio = list(flac_files or [])
        if external_audio:
            src_mkv = os.path.normpath(source_file) if source_file else os.path.normpath(output_file)
            same_mkv = os.path.normpath(output_file) == src_mkv
            output_file1 = (os.path.splitext(output_file)[0] + '.tmp.mkv') if same_mkv else output_file
            remux_cmd = self.generate_remux_cmd(track_count, track_info, external_audio, output_file1, src_mkv)
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
            mux_rc = _run_mkvmerge_shell(remux_cmd)
            committed = (not same_mkv) or _commit_inplace_mkv_remux(output_file, output_file1, mux_rc)
            if committed and mux_rc == 0:
                for audio_file in external_audio:
                    try:
                        os.remove(audio_file)
                    except OSError:
                        pass
            elif mux_rc != 0 and not same_mkv:
                print(
                    f'{translate_text("mkvmerge 混流失败 (exit ")}{mux_rc}'
                    f'{translate_text(")：")}{output_file1}',
                    flush=True,
                )
        self._extract_single_audio_from_mka(output_file)

    def encode_task(self, output_file, dst_folder, i, vpy_path: str, vspipe_mode: str, x265_mode: str, x265_params: str,
                    sub_pack_mode: str, source_file: Optional[str] = None,
                    encode_tool: str = 'x265', encode_bit_depth: str = '10'):
        vpy_path = os.path.normpath(os.path.abspath(str(vpy_path or '').strip()))
        if not os.path.isfile(vpy_path):
            if _ensure_runtime_vpy_file(vpy_path):
                self._log_getnative(f'{self.t("[BluraySubtitle] recreate missing vpy: ")}{vpy_path}')
            else:
                self._log_getnative(f'{self.t("[BluraySubtitle] vpy not found and recreate failed: ")}{vpy_path}')
        if not os.path.isfile(vpy_path):
            return

        src_mkv = os.path.normpath(source_file) if source_file else os.path.normpath(output_file)
        tool_key = _normalize_encode_tool_label(encode_tool)
        bd = str(encode_bit_depth or '10').strip()
        if bd not in ('8', '10', '12'):
            bd = '10'
        bits_int = int(bd)
        vpy_video_source = src_mkv
        encode_dovi_plan: Optional[dict[str, str]] = None
        if str(src_mkv).lower().endswith('.mkv') and os.path.isfile(src_mkv):
            dv_tid = MediaInfoTrackMappingMixin.mkvinfo_dolby_vision_track_id(src_mkv)
            if dv_tid is not None:
                if not encode_dovi_supported(encode_tool, bd):
                    print(
                        f'[encode-dovi] {translate_text("Dolby Vision 不支持 h264 或输出位深 8bit")} '
                        f'({os.path.basename(src_mkv)})',
                        flush=True,
                    )
                    return
                try:
                    self._progress(text=f'Dolby Vision: preparing {os.path.basename(src_mkv)}')
                except Exception:
                    pass
                encode_dovi_plan = prepare_encode_dolby_vision(src_mkv, dst_folder, int(dv_tid))
                if not encode_dovi_plan:
                    print(
                        f'[encode-dovi] failed to prepare Dolby Vision encode for {src_mkv}',
                        flush=True,
                    )
                    return
                vpy_video_source = str(encode_dovi_plan.get('bl_hevc') or src_mkv)
        self._cleanup_getnative_artifacts()
        use_getnative = bool(getattr(self, "use_getnative", True))
        native_info = None
        if use_getnative:
            self._log_getnative(
                f'{self.t("[BluraySubtitle] getnative - start analyzing ")}{os.path.basename(vpy_video_source)}')
            try:
                self._progress(text=f'{self.t("Getnative analyzing: ")}{os.path.basename(vpy_video_source)}')
            except Exception:
                pass
            native_info = self._infer_native_resolution(vpy_video_source)
            self._cleanup_getnative_artifacts()
            if native_info:
                self._log_getnative(
                    f'{self.t("[BluraySubtitle] getnative - ")}{os.path.basename(src_mkv)} -> '
                    f'{native_info["height"]}p ({native_info["kernel"]}, {self.t("score>=")}{native_info["confidence"]:.4f})'
                )
            else:
                self._log_getnative(
                    f'{self.t("[BluraySubtitle] getnative - ")}{os.path.basename(vpy_video_source)} -> '
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

            subtitle_real_path = None
            if self.sub_files and len(self.sub_files) >= i and i > -1:
                subtitle_real_path = os.path.normpath(self.sub_files[i - 1])

            def _patch_output_fmtc_bitdepth_line(line: str) -> tuple[str, bool]:
                """
                Only touch the *final* encode output depth:
                - res = core.fmtc.bitdepth(res, bits=N)   (typical custom script)
                - res = core.fmtc.bitdepth(src8, bits=N)  (default template)
                Do NOT rewrite e.g. src16 = core.fmtc.bitdepth(src8, bits=8) — that desyncs the
                filter chain and the y4m C tag vs --input-depth (garbage on any OS, easy to miss).
                """
                t = line.rstrip("\r\n")
                s = t.lstrip()
                if re.match(r"res\s*=\s*core\.fmtc\.bitdepth\s*\(\s*src8\s*,", s):
                    nl = re.sub(
                        r"(core\.fmtc\.bitdepth\(\s*src8\s*,\s*bits\s*=\s*)\d+",
                        lambda m: m.group(1) + str(bits_int),
                        line,
                        count=1,
                    )
                    return (nl, nl != line)
                if re.match(r"res\s*=\s*core\.fmtc\.bitdepth\s*\(\s*res\s*,", s):
                    nl = re.sub(
                        r"(core\.fmtc\.bitdepth\(\s*res\s*,\s*bits\s*=\s*)\d+",
                        lambda m: m.group(1) + str(bits_int),
                        line,
                        count=1,
                    )
                    return (nl, nl != line)
                return (line, False)

            updated = False
            new_lines = []
            for line in lines:
                stripped = line.lstrip()

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
                    new_lines.append(f'{indent}sub_file = {_to_vpy_raw_string(subtitle_real_path)}{comment}\n')
                    updated = True
                    continue

                nl, ch = _patch_output_fmtc_bitdepth_line(line)
                if ch:
                    new_lines.append(nl)
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
        if not _write_vpy_video_source_a(vpy_path, vpy_video_source):
            print(
                f'[encode] failed to set vpy source (a) in {vpy_path}',
                flush=True,
            )
            if encode_dovi_plan:
                cleanup_encode_dolby_vision_workdir(encode_dovi_plan)
            return

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
        vspipe_env = dict(vspipe_env) if vspipe_env else dict(os.environ)
        vspipe_env['BLURAYSUB_VPY_SOURCE'] = os.path.normpath(vpy_video_source)

        enc_bundle = (x265_mode or '') == 'bundle'
        enc_mode = 'bundle' if enc_bundle else 'system'
        enc_exe = resolve_encoder_executable_path(tool_key, enc_mode)
        ext = _video_intermediate_extension(tool_key)
        encoded_path = os.path.join(dst_folder, os.path.splitext(os.path.basename(output_file))[0] + ext)
        extra = _split_x265_extra_args(x265_params or '')
        if tool_key == 'x264':
            extra = _normalize_x264_extra_for_bit_depth(extra, bd)
        elif tool_key == 'svtav1' and bd == '12' and not _svtav1_extra_has_explicit_profile(extra):
            extra = ['--profile', '2'] + list(extra)

        if tool_key == 'x264':
            enc_cmd = [enc_exe, '--demuxer', 'y4m', '-'] + extra + ['--output-depth', bd, '-o', encoded_path]
        elif tool_key == 'x265':
            # Stdin is already '--y4m' '-' ; a trailing '-' is parsed as a second input (unused) and can abort x265.
            enc_cmd = (
                [enc_exe]
                + extra
                + ['--y4m', '-', '--input-depth', bd, '--output-depth', bd, '-o', encoded_path]
            )
        else:
            # Windows: SVT-AV1 hand-tuned asm can corrupt output (upstream unfixed); force portable C paths.
            if sys.platform == "win32":
                enc_cmd = [enc_exe, "--asm", "c", "-i", "stdin", "--input-depth", bd] + extra + ["-b", encoded_path]
            else:
                enc_cmd = [enc_exe, "-i", "stdin", "--input-depth", bd] + extra + ["-b", encoded_path]

        use_svt_win_temp_y4m = (
            tool_key == "svtav1"
            and sys.platform == "win32"
            and str(os.environ.get("BLURAYSUB_SVT_WIN_TEMP_Y4M", "") or "").strip() == "1"
        )
        if use_svt_win_temp_y4m:
            cmd_echo = (
                f'[temp y4m] "{vspipe_exe}" --y4m "{vpy_path}" -  -->  "{enc_cmd[0]}" -i <temp.y4m> ... -b "{encoded_path}"'
            )
            try:
                _emit_encode_log_line(
                    "[BluraySubtitle] SVT-AV1: temp y4m file mode (BLURAYSUB_SVT_WIN_TEMP_Y4M=1); high disk use."
                )
            except Exception:
                pass
        else:
            cmd_echo = f'"{vspipe_exe}" --y4m "{vpy_path}" - | {_format_encoder_cmd_for_echo(enc_cmd)}'
        print(f'{translate_text("Encode command:")}{cmd_echo}')
        if use_svt_win_temp_y4m:
            enc_rc = _run_vspipe_svt_win_tempfile_encode(
                str(vspipe_exe),
                vpy_path,
                enc_cmd,
                vspipe_env,
                temp_dir=os.path.dirname(encoded_path) or None,
            )
        else:
            enc_rc = _run_vspipe_piped_encode(str(vspipe_exe), vpy_path, enc_cmd, vspipe_env)
        if enc_rc != 0:
            _emit_encode_log_line(f"[BluraySubtitle] encode pipeline exited with code {enc_rc}")
        cleanup_lwi_for_source(vpy_video_source)
        if encode_dovi_plan and enc_rc != 0:
            cleanup_encode_dolby_vision_workdir(encode_dovi_plan)
            encode_dovi_plan = None
        if encode_dovi_plan and enc_rc == 0 and os.path.isfile(encoded_path):
            try:
                self._progress(text=f'Dolby Vision: inject RPU {os.path.basename(encoded_path)}')
            except Exception:
                pass
            rpu_path = str(encode_dovi_plan.get('rpu_bin') or '')
            if not dovi_tool_inject_rpu_hevc(encoded_path, rpu_path):
                print('[encode-dovi] post-encode inject-rpu failed', flush=True)
                cleanup_encode_dolby_vision_workdir(encode_dovi_plan)
                return
            cleanup_encode_dolby_vision_workdir(encode_dovi_plan)
            encode_dovi_plan = None
        cleanup_lwi_for_source(src_mkv)
        track_count, track_info, flac_files = self.process_audio_to_flac(output_file, dst_folder, i,
                                                                         source_file=src_mkv)

        external_audio = list(dict.fromkeys(
            (getattr(self, '_track_flac_map', {}) or {}).values()))
        if not external_audio:
            external_audio = list(flac_files or [])
        if external_audio or os.path.exists(encoded_path):
            same_mkv = os.path.normpath(output_file) == src_mkv
            output_file1 = (os.path.splitext(output_file)[0] + '.tmp.mkv') if same_mkv else output_file
            if not same_mkv and os.path.exists(output_file1):
                force_remove_file(output_file1)
            remux_cmd = self.generate_remux_cmd(track_count, track_info, external_audio, output_file1, src_mkv,
                                                encoded_video_file=encoded_path if os.path.exists(encoded_path) else None)
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
            mux_rc = _run_mkvmerge_shell(remux_cmd)
            committed = (not same_mkv) or _commit_inplace_mkv_remux(output_file, output_file1, mux_rc)
            if committed and mux_rc == 0:
                for audio_file in external_audio:
                    try:
                        os.remove(audio_file)
                    except OSError:
                        pass
            elif mux_rc != 0 and not same_mkv:
                print(
                    f'{translate_text("mkvmerge 混流失败 (exit ")}{mux_rc}'
                    f'{translate_text(")：")}{output_file1}',
                    flush=True,
                )
            if os.path.exists(encoded_path):
                os.remove(encoded_path)
        cleanup_lwi_for_source(src_mkv)

    def _decode_truehd_atmos_thd_files(self, output_base: str, track_info: dict[int, str]) -> None:
        """Decode TrueHD+Atmos ``.thd`` with truehdd, then RIFF WAV for the FLAC pass."""
        truehdd_ids = set(getattr(self, '_truehdd_decode_track_ids', None) or ())
        if not truehdd_ids:
            return
        exe = _truehdd_exe()
        if not exe:
            print('[truehdd] executable not found (set TRUEHDD_PATH or install truehdd)')
            return
        base = str(output_base or '').strip()
        if not base:
            return
        presentation = 2
        for track_id in sorted(truehdd_ids):
            if track_id not in track_info:
                continue
            thd_path = f'{base}.track{int(track_id)}.thd'
            if not os.path.isfile(thd_path):
                print(f'[truehdd] skip track {track_id}: missing {thd_path}')
                continue
            out_base = os.path.splitext(thd_path)[0]
            wav_path = out_base + '.wav'
            riff_tmp = out_base + '.__riff.wav'
            w64_path = out_base + '.wav'
            decoded_pcm_prefix = os.path.join(os.path.dirname(thd_path), f'decoded_track{int(track_id)}')
            for stale in (
                    wav_path,
                    riff_tmp,
                    f'{decoded_pcm_prefix}.pcm',
                    f'{decoded_pcm_prefix}.wav',
                    f'{decoded_pcm_prefix}.w64',
            ):
                if os.path.isfile(stale):
                    try:
                        os.remove(stale)
                    except Exception:
                        pass
            cmd = (
                f'"{exe}" --progress decode --format w64 --presentation {presentation} '
                f'--output-path "{out_base}" "{thd_path}"'
            )
            print(f'{translate_text("TrueHD Atmos 解码命令：")}{cmd}')
            wav_ok = False
            rc_decode = run_shell_command_with_output(cmd)
            if rc_decode == 0 and os.path.isfile(w64_path):
                print(
                    f'{translate_text("truehdd W64 转 RIFF WAV：")}'
                    f'"{FFMPEG_PATH}" -i "{w64_path}" -c:a pcm_s24le "{riff_tmp}"')
                if _ffmpeg_container_to_riff_wav(w64_path, riff_tmp):
                    try:
                        os.remove(w64_path)
                    except Exception:
                        pass
                    try:
                        os.replace(riff_tmp, wav_path)
                    except Exception:
                        if os.path.isfile(riff_tmp):
                            shutil.move(riff_tmp, wav_path)
                    wav_ok = os.path.isfile(wav_path) and os.path.getsize(wav_path) > 0
            if not wav_ok:
                if rc_decode != 0:
                    print(f'[truehdd] w64 decode exit {rc_decode} track {track_id}, trying raw PCM fallback')
                for stale in (w64_path, riff_tmp):
                    if os.path.isfile(stale):
                        try:
                            os.remove(stale)
                        except Exception:
                            pass
                pcm_cmd = (
                    f'"{exe}" --progress decode --format pcm --presentation {presentation} '
                    f'--output-path "{decoded_pcm_prefix}" "{thd_path}"'
                )
                print(f'{translate_text("TrueHD Atmos PCM 回退解码：")}{pcm_cmd}')
                pcm_rc = run_shell_command_with_output(pcm_cmd)
                if pcm_rc != 0:
                    print(f'[truehdd] pcm fallback exit {pcm_rc} track {track_id}')
                    continue
                pcm_candidates = sorted(
                    f for f in os.listdir(os.path.dirname(thd_path) or '.')
                    if f.lower().startswith(os.path.basename(decoded_pcm_prefix).lower())
                    and f.lower().endswith('.pcm')
                )
                pcm_path = ''
                if pcm_candidates:
                    pcm_path = os.path.normpath(os.path.join(os.path.dirname(thd_path), pcm_candidates[0]))
                if not pcm_path or not os.path.isfile(pcm_path):
                    print(f'[truehdd] no PCM output for track {track_id} (expected {decoded_pcm_prefix}.pcm)')
                    continue
                params = _truehdd_info_pcm_params(exe, thd_path, presentation)
                print(
                    f'{translate_text("truehdd 原始 PCM→WAV (")}{params["channels"]} ch, '
                    f'{params["sample_rate"]} Hz, {params["bits"]} bit{translate_text(")：")}'
                    f'-f s24le -ar {params["sample_rate"]} -ac {params["channels"]}')
                if not _pcm_raw_to_wav(
                        pcm_path,
                        wav_path,
                        params['channels'],
                        params['sample_rate'],
                        params.get('bits', 24),
                ):
                    print(f'[truehdd] PCM→WAV failed track {track_id}: {pcm_path}')
                    continue
                try:
                    os.remove(pcm_path)
                except Exception:
                    pass
                for extra in pcm_candidates[1:]:
                    try:
                        os.remove(os.path.join(os.path.dirname(thd_path), extra))
                    except Exception:
                        pass
                wav_ok = True
            if not wav_ok:
                continue
            try:
                os.remove(thd_path)
            except Exception:
                pass
            print(
                f'{translate_text("TrueHD Atmos 音轨 ｢")}{thd_path}{translate_text("｣ 已解码为 ｢")}{wav_path}{translate_text("｣")}')

    def extract_lossless(self, mkv_file: str, output_base: Optional[str] = None) -> tuple[int, dict[int, str]]:
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
        lossy_track_ids: set[int] = set()
        track_id = -1
        code_id_to_stream_type = {'A_DTS': 'DTS', 'A_PCM/INT/LIT': 'LPCM', 'A_PCM/INT/BIG': 'LPCM',
                                  'A_TRUEHD': 'TRUEHD', 'A_MLP': 'TRUEHD', 'A_FLAC': 'FLAC'}
        for line in stdout.splitlines():
            if (line.startswith('|  + Track number: ') or line.startswith('| + Track number: ')
                    or line.startswith('|+ Track number: ')):
                tail = line.split(':', 1)[1] if ':' in line else ''
                nums = re.findall(r'\d+', tail)
                if len(nums) >= 2:
                    track_id = int(nums[1])
                elif len(nums) == 1:
                    track_id = int(nums[0]) - 1
                else:
                    track_id = -1
                    continue
                track_count = max(track_count, track_id)
                continue
            if track_id < 0:
                continue
            if (line.startswith('|  + Codec ID: ') or line.startswith('| + Codec ID: ')
                    or line.startswith('|+ Codec ID: ')):
                codec_id = line.split(':', 1)[1].strip() if ':' in line else ''
                stream_type = code_id_to_stream_type.get(codec_id)
                if stream_type is None and mkv_codec_id_is_dts_family(codec_id):
                    stream_type = 'DTS'
                if stream_type in ('LPCM', 'DTS', 'TRUEHD', 'FLAC'):
                    if stream_type == 'LPCM':
                        track_suffix_info[track_id] = 'wav'
                    elif stream_type == 'DTS':
                        track_suffix_info[track_id] = 'dts'
                    elif stream_type == 'FLAC':
                        track_suffix_info[track_id] = 'flac'
                    else:
                        track_suffix_info[track_id] = 'thd'
                    track_info.setdefault(track_id, 'und')
                else:
                    lossy_suffix = _lossy_extract_suffix_for_codec_id(codec_id)
                    if lossy_suffix and track_id not in track_suffix_info:
                        track_suffix_info[track_id] = lossy_suffix
                        track_info.setdefault(track_id, 'und')
                        lossy_track_ids.add(track_id)
                continue
            if (line.startswith('|  + Language (IETF BCP 47): ') or line.startswith(
                    '| + Language (IETF BCP 47): ') or line.startswith('|+ Language (IETF BCP 47): ')):
                bcp_47_code = line.split(':', 1)[1].strip() if ':' in line else ''
                language = pycountry.languages.get(alpha_2=bcp_47_code.split('-')[0])
                if language is None:
                    language = pycountry.languages.get(alpha_3=bcp_47_code.split('-')[0])
                if language:
                    lang = getattr(language, "bibliographic", getattr(language, "alpha_3", None))
                else:
                    lang = 'und'
                if track_id in track_suffix_info:
                    track_info[track_id] = lang
                continue

        if track_info:
            extract_info = []
            base = output_base if output_base else mkv_file[:-4]
            for track_id, lang in track_info.items():
                extract_info.append(
                    f'{track_id}:"{base}.track{track_id}.{track_suffix_info[track_id]}"')
            extract_cmd = f'"{MKV_EXTRACT_PATH}" {mkvtoolnix_ui_language_arg()} "{mkv_file}" tracks {" ".join(extract_info)}'
            print(f'{translate_text("正在提取音轨，命令: ")}{extract_cmd}')
            subprocess.Popen(extract_cmd, shell=True, creationflags=_windows_no_window_flags()).wait()

        self._extracted_lossy_track_ids = lossy_track_ids
        return track_count, track_info
