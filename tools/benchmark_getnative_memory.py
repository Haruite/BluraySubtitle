from __future__ import annotations

import argparse
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from PIL import Image

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from src.core.settings import PLUGIN_PATH
from src.vs_tools.getnative import _resolve_getnative_vpy_path, _resolve_vspipe


def _working_set_bytes(process_id: int) -> int:
    if sys.platform == "win32":
        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("size", ctypes.c_ulong),
                ("page_fault_count", ctypes.c_ulong),
                ("peak_working_set_size", ctypes.c_size_t),
                ("working_set_size", ctypes.c_size_t),
                ("quota_peak_paged_pool_usage", ctypes.c_size_t),
                ("quota_paged_pool_usage", ctypes.c_size_t),
                ("quota_peak_non_paged_pool_usage", ctypes.c_size_t),
                ("quota_non_paged_pool_usage", ctypes.c_size_t),
                ("pagefile_usage", ctypes.c_size_t),
                ("peak_pagefile_usage", ctypes.c_size_t),
            ]

        handle = ctypes.windll.kernel32.OpenProcess(0x0410, False, int(process_id))
        if not handle:
            return 0
        try:
            counters = ProcessMemoryCounters()
            counters.size = ctypes.sizeof(counters)
            if not ctypes.windll.psapi.GetProcessMemoryInfo(
                handle,
                ctypes.byref(counters),
                counters.size,
            ):
                return 0
            return int(counters.working_set_size)
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        status = Path(f"/proc/{int(process_id)}/status").read_text(encoding="utf-8")
    except OSError:
        return 0
    for line in status.splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) * 1024
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure one getnative VSPipe process peak working set.")
    parser.add_argument("image", help="Full-resolution PNG sample used by getnative.")
    parser.add_argument("--kernels", type=int, default=1, choices=range(1, 17), metavar="1-16")
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument(
        "--phase",
        choices=("kernels", "final"),
        default="kernels",
        help="measure the batched kernel scan or the winner-only final verification",
    )
    args = parser.parse_args()

    image_path = os.path.abspath(args.image)
    with Image.open(image_path) as image:
        source_height = int(image.height)
    min_height = max(240, int(source_height * 0.40))
    max_height = min(source_height - 2, int(source_height * 0.98))

    output_handle, output_json = tempfile.mkstemp(prefix="bluraysub_getnative_memory_", suffix=".json")
    os.close(output_handle)
    vspipe_executable, base_environment = _resolve_vspipe()
    environment = dict(base_environment or os.environ.copy())
    environment["BLURAYSUB_PLUGIN_PATH"] = str(PLUGIN_PATH or "")
    for thread_environment_name in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
    ):
        environment[thread_environment_name] = "1"
    environment["BLURAYSUB_GETNATIVE_INPUT_PNG"] = image_path
    environment["BLURAYSUB_GETNATIVE_OUTPUT_JSON"] = output_json
    environment["BLURAYSUB_GETNATIVE_VS_THREADS"] = str(max(1, int(args.threads)))
    if args.phase == "final":
        params = {
            "mode": "collect_curve",
            "fast_mode": True,
            "kernel_name": "bilinear",
            "src_heights": list(range(min_height, max_height + 1)),
            "early_stop_patience": 10**9,
            "global_best_score": 0.0,
            "two_stage": True,
            "coarse_half_size": False,
        }
    else:
        params = {
            "mode": "collect_curves",
            "fast_mode": True,
            "max_kernels": int(args.kernels),
            "src_heights": list(range(min_height, max_height + 1)),
            "early_stop_patience": 30,
            "two_stage": True,
        }
    environment["BLURAYSUB_GETNATIVE_PARAMS_JSON"] = json.dumps(params)
    creation_flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) if sys.platform == "win32" else 0
    started = time.perf_counter()
    peak_working_set = 0
    try:
        process = subprocess.Popen(
            [vspipe_executable, _resolve_getnative_vpy_path(), "-"],
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=creation_flags,
        )
        while process.poll() is None:
            peak_working_set = max(peak_working_set, _working_set_bytes(process.pid))
            time.sleep(0.2)
        _, stderr = process.communicate()
        peak_working_set = max(peak_working_set, _working_set_bytes(process.pid))
        if process.returncode != 0:
            raise RuntimeError(f"vspipe failed ({process.returncode}): {stderr.strip()}")
        payload = json.loads(Path(output_json).read_text(encoding="utf-8"))
        if not payload.get("ok"):
            raise RuntimeError(f"getnative.vpy failed: {payload}")
        measured_mib = peak_working_set / 1024**2
        print(
            json.dumps(
                {
                    "phase": str(args.phase),
                    "kernels": int(args.kernels),
                    "threads": max(1, int(args.threads)),
                    "elapsed_seconds": round(time.perf_counter() - started, 3),
                    "peak_working_set_mib": round(measured_mib, 1),
                    "configured_budget_mib_per_sample": 800,
                    "fits_configured_budget": bool(measured_mib <= 800.0),
                },
                indent=2,
            )
        )
        return 0
    finally:
        try:
            os.remove(output_json)
        except OSError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
