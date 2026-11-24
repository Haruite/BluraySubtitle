"""Start BluraySubtitle with the relocatable FreeBSD interpreter and tools."""

import os
from pathlib import Path
import sys


def main():
    project = Path(__file__).resolve().parent
    runtime = project.parent
    sys._bluray_freebsd_runtime = runtime
    if source := os.environ.get("BLURAY_FREEBSD_SOURCE"):
        project = Path(source)
        os.environ.setdefault("BLURAY_SUBTITLE_CONFIG_DIR", str(project))
    sys.path.insert(0, str(project))
    from src.main import main as start

    start()


if __name__ == "__main__":
    main()
