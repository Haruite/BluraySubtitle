"""Migration entrypoint.

Supports both:
- `python -m src.main`
- `python src/main.py`
"""

import os
import sys
import multiprocessing

_wayland_quiet_rule = "qt.qpa.wayland.textinput.warning=false"
_existing_rules = os.environ.get("QT_LOGGING_RULES", "").strip()
if _wayland_quiet_rule not in _existing_rules:
    os.environ["QT_LOGGING_RULES"] = (
        f"{_existing_rules};{_wayland_quiet_rule}" if _existing_rules else _wayland_quiet_rule
    )

# On Linux, default to X11 backend unless the user explicitly sets one.
if sys.platform.startswith("linux") and "QT_QPA_PLATFORM" not in os.environ:
    os.environ["QT_QPA_PLATFORM"] = "xcb"

try:
    from .runtime.bootstrap import main
except ImportError:
    _ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _ROOT not in sys.path:
        sys.path.insert(0, _ROOT)
    from src.runtime.bootstrap import main


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()

