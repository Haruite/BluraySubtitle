"""Migration entrypoint.

Supports both:
- `python -m src.main`
- `python src/main.py`
"""

from __future__ import annotations

from contextlib import suppress
import multiprocessing
import os
from pathlib import Path
import subprocess
import sys

_wayland_quiet_rule = "qt.qpa.wayland.textinput.warning=false"
_existing_rules = os.environ.get("QT_LOGGING_RULES", "").strip()
if _wayland_quiet_rule not in _existing_rules:
    os.environ["QT_LOGGING_RULES"] = (
        f"{_existing_rules};{_wayland_quiet_rule}" if _existing_rules else _wayland_quiet_rule
    )

# Prefer X11/XWayland desktop integration and let Qt fall back to native Wayland.
if sys.platform.startswith(("linux", "freebsd")) and os.environ.get("DISPLAY"):
    os.environ.setdefault("QT_QPA_PLATFORM", "xcb;wayland")

if not __package__:
    _ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _ROOT not in sys.path:
        sys.path.insert(0, _ROOT)


if getattr(sys, "frozen", False):
    site_packages = Path(sys._MEIPASS) / "Lib/site-packages"
    if site_packages.is_dir():
        sys.path.insert(0, str(site_packages))


def _launch_detached(arguments: list[str]) -> int:
    command = [sys.executable]
    environment = dict(os.environ, PYTHONUNBUFFERED="1")
    if getattr(sys, "frozen", False):
        environment["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    else:
        # Keep the original interpreter options and module or script entry point.
        entrypoint_end = len(sys.orig_argv) - len(arguments)
        command.extend(sys.orig_argv[1:entrypoint_end])
    command.append("--detached-gui")
    command.extend(argument for argument in arguments if argument not in ("--detach", "--detached-gui"))
    process_options = (
        {"creationflags": subprocess.CREATE_NO_WINDOW}
        if sys.platform == "win32" else {"start_new_session": True}
    )

    try:
        subprocess.Popen(
            command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
            env=environment, **process_options,
        )
    except OSError as error:
        from src.core.app_config import app_config_path, load_app_config
        from src.core.i18n import translate_text

        language = None
        with suppress(OSError, ValueError):
            config_path = app_config_path()
            if config_path.is_file():
                language = load_app_config(config_path).ui.language
        message = translate_text("Could not start the GUI in a separate process. {error}", language)
        print(message.format(error=error), file=sys.stderr)
        return 1
    return 0


def main(*, detached_gui: bool = False) -> None:
    if sys.platform == "darwin" and sys.version_info < (3, 10):
        runtime = Path.home() / "Library/Application Support/BluraySubtitle/Runtime"
        python = runtime / "python/bin/python3"
        if (getattr(sys, "_bluray_macos_runtime", None) or not (runtime / "runtime.json").is_file()
                or not os.access(python, os.X_OK)):
            raise SystemExit(f"BluraySubtitle: Python {sys.version.split()[0]} < 3.10\n./setup_macos_environment.sh")
        # Use this checkout with the Python and Qt installed by the macOS setup script.
        entry = Path(__file__).resolve().parents[1] / "tools/macos_entry.py"
        os.execv(python, [str(python), "-I", "-B", str(entry), "--detach", *sys.argv[1:]])

    from src.runtime.application_log import ApplicationLog, prepare_windows_stdio

    arguments = sys.argv[1:]
    foreground = "--foreground" in arguments
    # Keep redirected Windows logs UTF-8, including frozen multiprocessing workers.
    if sys.platform == "win32":
        prepare_windows_stdio(foreground=foreground)
        for stream in (sys.stdout, sys.stderr):
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    multiprocessing.freeze_support()
    if not (foreground or detached_gui or "--detached-gui" in arguments):
        raise SystemExit(_launch_detached(arguments))
    sys.argv[1:] = [
        argument for argument in arguments if argument not in ("--detach", "--detached-gui", "--foreground")
    ]

    application_log = ApplicationLog()
    os.environ.setdefault("QT_FORCE_STDERR_LOGGING", "1")
    with application_log.capture(foreground=foreground):
        # Capture startup output before importing Qt or constructing the window.
        from src.runtime.bootstrap import RESTART_FOR_UI_SCALE, run_src_entry

        exit_code = run_src_entry(application_log)
        if exit_code == RESTART_FOR_UI_SCALE:
            # The Qt event loop has shut down and released the single-instance lock.
            exit_code = _launch_detached(arguments)
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
