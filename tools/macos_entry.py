"""Start the source application using the runtime selected for this version of macOS."""

import json
import os
import platform
import sys
from pathlib import Path


def main():
    runtime = Path(sys.executable).resolve().parents[2]
    project = Path(__file__).resolve().parents[1]
    manifest = json.loads((runtime / "runtime.json").read_text())
    version = tuple(int(n) for n in platform.mac_ver()[0].split("."))
    branch = "latest" if (*version, 0, 0)[:3] >= tuple(manifest["latest_qt_minimum"]) else "6.6"
    if os.environ.get("BLURAY_MACOS_QT") == "6.6":
        branch = "6.6"
    qt = runtime / "qt" / branch
    sys.path[:0] = [str(project), str(qt)]
    sys._bluray_macos_runtime = runtime
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    os.environ["QT_PLUGIN_PATH"] = str(qt / "PyQt6/Qt6/plugins")
    os.environ["VSSCRIPT_PATH"] = str(runtime / manifest["vsscript"])
    os.environ.setdefault("VK_DRIVER_FILES", str(runtime / "share/vulkan/icd.d/MoltenVK_icd.json"))
    os.environ["VAPOURSYNTH_EXTRA_PLUGIN_PATH"] = str(runtime / "plugins")
    if project == runtime / "app":
        sys._bluray_macos_app = runtime.parents[2]
        config = Path.home() / "Library/Application Support/BluraySubtitle"
        os.environ.setdefault("BLURAY_SUBTITLE_CONFIG_DIR", str(config))
    from src.main import main as start

    if not any(arg in ("--detach", "--foreground", "--detached-gui") for arg in sys.argv[1:]):
        sys.argv.append("--detached-gui")
    start()


if __name__ == "__main__":
    main()
