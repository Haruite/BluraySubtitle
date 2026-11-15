# -*- mode: python ; coding: utf-8 -*-
"""Build the Windows x64 one-folder package with PyInstaller."""

from pathlib import Path
import runpy
import sys

if "SPECPATH" not in globals():
    from PyInstaller.__main__ import run

    raise SystemExit(run([str(Path(__file__).resolve()), *sys.argv[1:]]))

project = Path(SPECPATH).resolve()
runpy.run_path(
    str(project / "tools/windows_package_spec.py"),
    init_globals=dict(PROJECT_ROOT=project, WORK_PATH=Path(workpath), PACKAGE_ARCHITECTURE="x64"),
)
