"""Start Windows PowerShell with the system DLL search path."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from src.exports.utils import run_command


def launch_system_powershell(
        arguments: list[str],
        *,
        cwd: Path | None = None,
        environment: dict[str, str] | None = None,
        stdout: int = subprocess.DEVNULL,
        stderr: int = subprocess.DEVNULL,
) -> subprocess.Popen[bytes]:
    powershell = Path(os.environ["SystemRoot"]) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    command = [str(powershell), "-NoProfile", "-NonInteractive", *arguments]
    env = dict(os.environ, **(environment or {}))

    runtime = getattr(sys, "_MEIPASS", None) if getattr(sys, "frozen", False) else None
    if runtime:
        runtime_path = os.path.normcase(runtime) + os.sep
        env["PATH"] = os.pathsep.join(
            entry for entry in env.get("PATH", "").split(os.pathsep)
            if entry and not (os.path.normcase(os.path.abspath(entry.strip('"'))) + os.sep).startswith(runtime_path)
        )
    return run_command(
        command, wait=False, system_dll_search=bool(runtime), cwd=cwd, env=env,
        stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
