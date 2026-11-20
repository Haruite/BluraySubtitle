# -*- mode: python ; coding: utf-8 -*-
"""Build the Linux ARM64 application with PyInstaller."""

from pathlib import Path
import runpy

project = Path(SPECPATH).resolve()
runpy.run_path(
    str(project / "tools/linux_package_spec.py"),
    init_globals=dict(PROJECT_ROOT=project, PACKAGE_ARCHITECTURE="arm64"),
)
