"""Select the packaged Qt binding and expose the relocatable public entry point."""

import os
from pathlib import Path
import sys

from _pyi_rth_utils.qt import create_embedded_qt_conf

qt_package = Path(os.environ.pop("BLURAY_QT_PACKAGE"))
sys.path.insert(0, str(qt_package))
plugins = qt_package / "PyQt6/Qt6/plugins"
os.environ["QT_PLUGIN_PATH"] = str(plugins)
os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(plugins / "platforms")
create_embedded_qt_conf("PyQt6", str(plugins.parent))

# glibc has already consumed its search path. Host executables must start with their own libc.
host_path = os.environ.pop("BLURAY_HOST_LIBRARY_PATH", None)
for name in ("LD_LIBRARY_PATH", "LD_LIBRARY_PATH_ORIG"):
    if host_path is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = host_path

# Detach, multiprocessing, desktop entries and the updater all relaunch through this path.
sys.executable = os.environ.pop("BLURAY_LINUX_ENTRY")
if sys.argv[0] == str(Path(sys._MEIPASS) / "BluraySubtitle"):
    sys.argv[0] = sys.executable
