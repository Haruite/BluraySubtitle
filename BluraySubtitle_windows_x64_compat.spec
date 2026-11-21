# -*- mode: python ; coding: utf-8 -*-
"""Build the Windows 7 SP1 x64 one-folder package from the compatibility staging area."""

import os
from pathlib import Path
import runpy


project = Path(SPECPATH).resolve()
runpy.run_path(
    str(project / "tools/windows_package_spec.py"),
    init_globals=dict(PROJECT_ROOT=project, WORK_PATH=Path(workpath), PACKAGE_ARCHITECTURE="x64",
                      COMPAT_ROOT=Path(os.environ["BLURAYSUBTITLE_WINDOWS_COMPAT_ROOT"])),
)
