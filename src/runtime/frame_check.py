"""Full-frame PSNR verification for completed Encode video outputs."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from threading import Event, Thread
from typing import Callable

from src.exports.utils import run_command
from src.runtime import TaskCancelled


DEFAULT_LUMA_PSNR_THRESHOLD_DB = 30.0
DEFAULT_CHROMA_PSNR_THRESHOLD_DB = 40.0
_PSNR_FIELD_RE = re.compile(r"([a-z_]+):([^\s]+)")
_DECODE_ERROR_MARKERS = (
    "corrupt decoded frame",
    "error while decoding",
    "invalid data found",
    "concealing",
    "missing reference picture",
    "decode_slice_header error",
)


@dataclass(frozen=True)
class FrameCheckResult:
    """Summary returned to the Encode workflow after a report is written."""

    report_path: str
    status: str
    compared_frames: int
    suspicious_frames: int


@dataclass(frozen=True)
class _ProcessOutcome:
    vspipe_exit_code: int
    ffmpeg_exit_code: int
    vspipe_log: str
    ffmpeg_log: str


def frame_check_report_path(encoded_path: str) -> str:
    """Return the deterministic report path owned by one encoded video."""
    normalized = os.path.abspath(os.path.normpath(encoded_path))
    stem = os.path.splitext(os.path.basename(normalized))[0]
    return os.path.join(os.path.dirname(normalized), "FrameCheck", f"{stem}.frame-check.json")


def _probe_encoded_video(ffprobe_executable: str, encoded_path: str) -> dict[str, object]:
    result = run_command(
        [
            str(ffprobe_executable),
            "-v", "error",
            "-select_streams", "v:0",
            "-count_packets",
            "-show_entries",
            "stream=nb_read_packets,avg_frame_rate,r_frame_rate,width,height,pix_fmt",
            "-of", "json",
            encoded_path,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(
            str(result.stderr or "").strip()
            or f"ffprobe exited with code {result.returncode}"
        )
    document = json.loads(result.stdout or "{}")
    streams = document.get("streams") if isinstance(document, dict) else None
    if not isinstance(streams, list) or not streams or not isinstance(streams[0], dict):
        raise RuntimeError(f"No encoded video stream was found: {encoded_path}")
    stream = streams[0]
    packet_text = str(stream.get("nb_read_packets") or "").strip()
    packet_count = int(packet_text) if packet_text.isdigit() else None
    frame_rate = str(
        stream.get("avg_frame_rate")
        or stream.get("r_frame_rate")
        or ""
    ).strip()
    try:
        parsed_rate = Fraction(frame_rate)
        fps = float(parsed_rate) if parsed_rate > 0 else None
    except (ValueError, ZeroDivisionError):
        fps = None
    return {
        "packet_count": packet_count,
        "frame_rate": frame_rate or None,
        "fps": fps,
        "width": stream.get("width"),
        "height": stream.get("height"),
        "pixel_format": stream.get("pix_fmt"),
    }


def _read_process_log(stream, limit: int = 65536) -> str:
    stream.flush()
    size = stream.tell()
    stream.seek(max(0, size - limit))
    return stream.read().decode("utf-8", errors="replace").strip()


def _stop_process(process) -> None:
    if process is None or process.poll() is not None:
        return
    try:
        process.kill()
    except OSError:
        pass


def _run_full_frame_check_process(
        vspipe_executable: str,
        vpy_path: str,
        vspipe_environment: dict[str, str],
        ffmpeg_executable: str,
        encoded_path: str,
        stats_path: str,
        cancel_event: Event | None,
        progress_callback: Callable[
            [int, float, float | None, float | None], None
        ] | None = None,
        total_frames: int | None = None,
) -> _ProcessOutcome:
    process_options: dict[str, object] = {
        "env": dict(vspipe_environment),
        "bufsize": 0,
    }
    if os.name == "nt":
        process_options["creationflags"] = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    vspipe_command = [str(vspipe_executable), "--y4m", str(vpy_path), "-"]
    psnr_filter = (
        "[0:v:0]settb=AVTB,setpts=N[reference];"
        "[1:v:0]settb=AVTB,setpts=N[encoded];"
        "[reference][encoded]psnr="
        "stats_file=-:eof_action=pass:repeatlast=0[checked]"
    )
    ffmpeg_command = [
        str(ffmpeg_executable),
        "-hide_banner",
        "-nostdin",
        "-nostats",
        "-loglevel", "warning",
        "-i", "pipe:0",
        "-i", encoded_path,
        "-filter_complex", psnr_filter,
        "-map", "[checked]",
        "-an",
        "-sn",
        "-dn",
        "-f", "null",
        "-",
    ]
    vspipe_process = None
    ffmpeg_process = None
    stats_reader = None
    compared_frames = 0
    with (
            open(stats_path, "wb") as stats_stream,
            tempfile.TemporaryFile(mode="w+b") as vspipe_log_stream,
            tempfile.TemporaryFile(mode="w+b") as ffmpeg_log_stream,
    ):
        try:
            vspipe_process = run_command(
                vspipe_command,
                wait=False,
                stdout=subprocess.PIPE,
                stderr=vspipe_log_stream,
                **process_options,
            )
            ffmpeg_process = run_command(
                ffmpeg_command,
                wait=False,
                stdin=vspipe_process.stdout,
                stdout=subprocess.PIPE,
                stderr=ffmpeg_log_stream,
                **process_options,
            )
            if vspipe_process.stdout is not None:
                vspipe_process.stdout.close()
            if ffmpeg_process.stdout is None:
                raise RuntimeError("FFmpeg frame-check output pipe is unavailable")

            def copy_stats() -> None:
                nonlocal compared_frames
                try:
                    for stats_line in iter(ffmpeg_process.stdout.readline, b""):
                        stats_stream.write(stats_line)
                        if b"n:" in stats_line and b"psnr_avg:" in stats_line:
                            compared_frames += 1
                except (OSError, ValueError):
                    pass
                finally:
                    try:
                        ffmpeg_process.stdout.close()
                    except OSError:
                        pass

            stats_reader = Thread(target=copy_stats, daemon=True)
            stats_reader.start()
            started_at = time.monotonic()
            last_progress_at = started_at
            if progress_callback is not None:
                progress_callback(0, 0.0, None, None)
            while vspipe_process.poll() is None or ffmpeg_process.poll() is None:
                if cancel_event is not None and cancel_event.is_set():
                    _stop_process(ffmpeg_process)
                    _stop_process(vspipe_process)
                    ffmpeg_process.wait()
                    vspipe_process.wait()
                    raise TaskCancelled()
                if ffmpeg_process.poll() not in (None, 0):
                    _stop_process(vspipe_process)
                current_time = time.monotonic()
                if (
                        progress_callback is not None
                        and current_time - last_progress_at >= 15.0
                ):
                    elapsed_seconds = max(current_time - started_at, 0.001)
                    frames_per_second = compared_frames / elapsed_seconds
                    progress_fraction = (
                        min(compared_frames / total_frames, 1.0)
                        if total_frames is not None and total_frames > 0
                        else None
                    )
                    remaining_seconds = (
                        max(total_frames - compared_frames, 0) / frames_per_second
                        if total_frames is not None
                        and total_frames > 0
                        and frames_per_second > 0
                        else None
                    )
                    progress_callback(
                        compared_frames,
                        frames_per_second,
                        progress_fraction,
                        remaining_seconds,
                    )
                    last_progress_at = current_time
                time.sleep(0.1)
            stats_reader.join()
            stats_stream.flush()
            if progress_callback is not None:
                elapsed_seconds = max(time.monotonic() - started_at, 0.001)
                frames_per_second = compared_frames / elapsed_seconds
                progress_fraction = (
                    min(compared_frames / total_frames, 1.0)
                    if total_frames is not None and total_frames > 0
                    else None
                )
                progress_callback(
                    compared_frames,
                    frames_per_second,
                    progress_fraction,
                    (
                        0.0
                        if progress_fraction is not None
                        and progress_fraction >= 1.0
                        else None
                    ),
                )
            return _ProcessOutcome(
                int(vspipe_process.returncode),
                int(ffmpeg_process.returncode),
                _read_process_log(vspipe_log_stream),
                _read_process_log(ffmpeg_log_stream),
            )
        except BaseException:
            _stop_process(ffmpeg_process)
            _stop_process(vspipe_process)
            if ffmpeg_process is not None:
                ffmpeg_process.wait()
            if vspipe_process is not None:
                vspipe_process.wait()
            if stats_reader is not None:
                stats_reader.join(timeout=1.0)
            raise


def _parse_psnr_value(value: str | None) -> float | None:
    if value is None:
        return None
    if value.lower() == "inf":
        return math.inf
    try:
        parsed = float(value)
        return None if math.isnan(parsed) else parsed
    except ValueError:
        return None


def _json_psnr_value(value: float | None) -> float | str | None:
    if value is None:
        return None
    return "inf" if math.isinf(value) else round(value, 6)


def _summarize_psnr(
        stats_path: str,
        fps: float | None,
        luma_psnr_threshold_db: float,
        chroma_psnr_threshold_db: float,
) -> dict[str, object]:
    totals = {name: 0.0 for name in ("average", "y", "u", "v")}
    finite_counts = {name: 0 for name in totals}
    infinite_counts = {name: 0 for name in totals}
    minima: dict[str, float | None] = {name: None for name in totals}
    suspicious_ranges: list[dict[str, object]] = []
    worst_frames: list[dict[str, object]] = []
    current_range: dict[str, object] | None = None
    compared_frames = 0
    suspicious_frames = 0

    with open(stats_path, "r", encoding="utf-8", errors="replace") as stats:
        for line in stats:
            fields = dict(_PSNR_FIELD_RE.findall(line))
            if "n" not in fields or "psnr_avg" not in fields:
                continue
            try:
                frame_number = max(0, int(fields["n"]) - 1)
            except ValueError:
                continue
            values = {
                "average": _parse_psnr_value(fields.get("psnr_avg")),
                "y": _parse_psnr_value(fields.get("psnr_y")),
                "u": _parse_psnr_value(fields.get("psnr_u")),
                "v": _parse_psnr_value(fields.get("psnr_v")),
            }
            compared_frames += 1
            for name, value in values.items():
                if value is None:
                    continue
                if math.isinf(value):
                    infinite_counts[name] += 1
                    continue
                totals[name] += value
                finite_counts[name] += 1
                minima[name] = value if minima[name] is None else min(minima[name], value)
            luma_value = values["y"] if values["y"] is not None else values["average"]
            is_suspicious = bool(
                (luma_value is not None and luma_value < luma_psnr_threshold_db)
                or (
                    values["u"] is not None
                    and values["u"] < chroma_psnr_threshold_db
                )
                or (
                    values["v"] is not None
                    and values["v"] < chroma_psnr_threshold_db
                )
            )
            if not is_suspicious:
                if current_range is not None:
                    suspicious_ranges.append(current_range)
                    current_range = None
                continue
            suspicious_frames += 1
            frame_data = {
                "frame": frame_number,
                "timestamp_seconds": round(frame_number / fps, 6) if fps else None,
                "psnr_average_db": _json_psnr_value(values["average"]),
                "psnr_y_db": _json_psnr_value(values["y"]),
                "psnr_u_db": _json_psnr_value(values["u"]),
                "psnr_v_db": _json_psnr_value(values["v"]),
            }
            severity = min(
                value
                for value in values.values()
                if value is not None
            )
            worst_frames.append({"severity": severity, **frame_data})
            worst_frames.sort(key=lambda item: item["severity"])
            del worst_frames[20:]
            if current_range is None or frame_number != int(current_range["end_frame"]) + 1:
                if current_range is not None:
                    suspicious_ranges.append(current_range)
                current_range = {
                    "start_frame": frame_number,
                    "end_frame": frame_number,
                    "start_seconds": frame_data["timestamp_seconds"],
                    "end_seconds": frame_data["timestamp_seconds"],
                    "frame_count": 1,
                    "_minimums": dict(values),
                }
            else:
                current_range["end_frame"] = frame_number
                current_range["end_seconds"] = frame_data["timestamp_seconds"]
                current_range["frame_count"] = int(current_range["frame_count"]) + 1
                range_minima = current_range["_minimums"]
                for name, value in values.items():
                    minimum = range_minima[name]
                    if value is not None and (
                            minimum is None
                            or value < minimum
                    ):
                        range_minima[name] = value
    if current_range is not None:
        suspicious_ranges.append(current_range)
    for suspicious_range in suspicious_ranges:
        range_minima = suspicious_range.pop("_minimums")
        for name, value in range_minima.items():
            suspicious_range[f"minimum_psnr_{name}_db"] = _json_psnr_value(value)
    metric_summary = {}
    for name in totals:
        finite_count = finite_counts[name]
        if finite_count:
            mean: float | str | None = round(totals[name] / finite_count, 6)
        elif infinite_counts[name]:
            mean = "inf"
        else:
            mean = None
        metric_summary[name] = {
            "mean_db": mean,
            "minimum_db": _json_psnr_value(minima[name]),
            "infinite_frames": infinite_counts[name],
        }
    return {
        "compared_frames": compared_frames,
        "suspicious_frames": suspicious_frames,
        "suspicious_ranges": suspicious_ranges,
        "worst_frames": [
            {key: value for key, value in frame.items() if key != "severity"}
            for frame in worst_frames
        ],
        "metrics": metric_summary,
    }


def _write_report(report_path: str, document: dict[str, object]) -> None:
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "x", encoding="utf-8", newline="\n") as report:
        json.dump(document, report, ensure_ascii=False, indent=2, allow_nan=False)
        report.write("\n")


def run_full_frame_check(
        *,
        vspipe_executable: str,
        vpy_path: str,
        vspipe_environment: dict[str, str],
        ffmpeg_executable: str,
        ffprobe_executable: str,
        encoded_path: str,
        expected_reference_frames: int | None = None,
        luma_psnr_threshold_db: float = DEFAULT_LUMA_PSNR_THRESHOLD_DB,
        chroma_psnr_threshold_db: float = DEFAULT_CHROMA_PSNR_THRESHOLD_DB,
        cancel_event: Event | None = None,
        progress_callback: Callable[
            [int, float, float | None, float | None], None
        ] | None = None,
) -> FrameCheckResult:
    """Compare the exact Encode VPy output with the completed encoded video."""
    normalized_vpy = os.path.abspath(os.path.normpath(vpy_path))
    normalized_encoded = os.path.abspath(os.path.normpath(encoded_path))
    report_path = frame_check_report_path(normalized_encoded)
    if os.path.exists(report_path):
        raise FileExistsError(report_path)
    vpy_digest = hashlib.sha256(Path(normalized_vpy).read_bytes()).hexdigest()
    created_at = datetime.now(timezone.utc).isoformat()
    try:
        encoded_video = _probe_encoded_video(ffprobe_executable, normalized_encoded)
        packet_count = encoded_video.get("packet_count")
        progress_total_frames = next((
            count
            for count in (packet_count, expected_reference_frames)
            if isinstance(count, int) and count > 0
        ), None)
        with tempfile.TemporaryDirectory(prefix="bluraysub_frame_check_") as temporary_directory:
            stats_path = os.path.join(temporary_directory, "psnr.log")
            outcome = _run_full_frame_check_process(
                vspipe_executable,
                normalized_vpy,
                vspipe_environment,
                ffmpeg_executable,
                normalized_encoded,
                stats_path,
                cancel_event,
                progress_callback=progress_callback,
                total_frames=progress_total_frames,
            )
            summary = _summarize_psnr(
                stats_path,
                encoded_video.get("fps"),
                luma_psnr_threshold_db,
                chroma_psnr_threshold_db,
            )
        compared_frames = int(summary["compared_frames"])
        frame_counts = [
            count
            for count in (expected_reference_frames, packet_count, compared_frames)
            if isinstance(count, int)
        ]
        frame_count_matches = len(frame_counts) >= 2 and len(set(frame_counts)) == 1
        decode_errors = [
            line.strip()
            for line in outcome.ffmpeg_log.splitlines()
            if any(marker in line.lower() for marker in _DECODE_ERROR_MARKERS)
        ]
        if outcome.vspipe_exit_code != 0 or outcome.ffmpeg_exit_code != 0 or compared_frames == 0:
            status = "error"
        elif not frame_count_matches or decode_errors:
            status = "fail"
        elif int(summary["suspicious_frames"]) > 0:
            status = "suspect"
        else:
            status = "pass"
        document = {
            "schema_version": 1,
            "created_at": created_at,
            "status": status,
            "mode": "vpy_ffmpeg_psnr",
            "reference": {
                "vpy_path": normalized_vpy,
                "vpy_sha256": vpy_digest,
                "expected_frames": expected_reference_frames,
            },
            "encoded": {
                "path": normalized_encoded,
                **encoded_video,
            },
            "thresholds_db": {
                "y": luma_psnr_threshold_db,
                "u": chroma_psnr_threshold_db,
                "v": chroma_psnr_threshold_db,
            },
            "summary": {
                "compared_frames": compared_frames,
                "frame_count_matches": frame_count_matches,
                "suspicious_frames": summary["suspicious_frames"],
                "suspicious_range_count": len(summary["suspicious_ranges"]),
                "metrics": summary["metrics"],
            },
            "suspicious_ranges": summary["suspicious_ranges"],
            "worst_frames": summary["worst_frames"],
            "decode_errors": decode_errors,
            "tools": {
                "vspipe_exit_code": outcome.vspipe_exit_code,
                "ffmpeg_exit_code": outcome.ffmpeg_exit_code,
                "vspipe_log_tail": outcome.vspipe_log,
                "ffmpeg_log_tail": outcome.ffmpeg_log,
            },
        }
    except TaskCancelled:
        raise
    except Exception as error:
        status = "error"
        compared_frames = 0
        summary = {"suspicious_frames": 0}
        document = {
            "schema_version": 1,
            "created_at": created_at,
            "status": status,
            "mode": "vpy_ffmpeg_psnr",
            "reference": {
                "vpy_path": normalized_vpy,
                "vpy_sha256": vpy_digest,
                "expected_frames": expected_reference_frames,
            },
            "encoded": {"path": normalized_encoded},
            "error": f"{type(error).__name__}: {error}",
        }
    _write_report(report_path, document)
    return FrameCheckResult(
        report_path,
        status,
        compared_frames,
        int(summary["suspicious_frames"]),
    )


__all__ = [
    "FrameCheckResult",
    "frame_check_report_path",
    "run_full_frame_check",
]
