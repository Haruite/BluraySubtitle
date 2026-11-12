"""Migration entrypoint.

Supports both:
- `python -m src.main`
- `python src/main.py`
"""

from contextlib import suppress
import multiprocessing
import os
import subprocess
import sys

_wayland_quiet_rule = "qt.qpa.wayland.textinput.warning=false"
_existing_rules = os.environ.get("QT_LOGGING_RULES", "").strip()
if _wayland_quiet_rule not in _existing_rules:
    os.environ["QT_LOGGING_RULES"] = (
        f"{_existing_rules};{_wayland_quiet_rule}" if _existing_rules else _wayland_quiet_rule
    )

# On Linux, default to X11 backend unless the user explicitly sets one.
if sys.platform.startswith("linux") and "QT_QPA_PLATFORM" not in os.environ:
    os.environ["QT_QPA_PLATFORM"] = "xcb"

if not __package__:
    _ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _ROOT not in sys.path:
        sys.path.insert(0, _ROOT)


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
    command.extend(argument for argument in arguments if argument != "--detach")
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


def main() -> None:
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
    if not foreground and "--detached-gui" not in arguments:
        raise SystemExit(_launch_detached(arguments))
    sys.argv[1:] = [
        argument for argument in arguments if argument not in ("--detach", "--detached-gui", "--foreground")
    ]

    application_log = ApplicationLog()
    os.environ.setdefault("QT_FORCE_STDERR_LOGGING", "1")
    with application_log.capture(foreground=foreground):
        # Capture startup output before importing Qt or constructing the window.
        from src.runtime.bootstrap import run_src_entry

        run_src_entry(application_log)


if __name__ == "__main__":
    main()
