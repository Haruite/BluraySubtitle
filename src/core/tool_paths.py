"""User tool paths and the resolved paths captured by each workflow."""

from __future__ import annotations

import ast
import ctypes
import ctypes.util
import os
import shutil
import sys
from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from functools import cache
from pathlib import Path
from types import MappingProxyType

from . import settings
from .i18n import translate_text


ENCODER_PATH_NAMES = {"x264": "X264_PATH", "x265": "X265_PATH", "svtav1": "SVT_AV1_PATH"}
MKVTOOLNIX_TOOLS = {
    "MKV_MERGE_PATH": "mkvmerge",
    "MKV_INFO_PATH": "mkvinfo",
    "MKV_PROP_EDIT_PATH": "mkvpropedit",
    "MKV_EXTRACT_PATH": "mkvextract",
}
TOOL_DIRECTORY_NAMES = frozenset({"PLUGIN_PATH", "MKVTOOLNIX_PATH", "MPV_CONFIG_PATH"})
TOOL_PATH_NAMES = (
    "SEVEN_ZIP_PATH", "FLAC_PATH", "FFMPEG_PATH", "FFPROBE_PATH",
    *ENCODER_PATH_NAMES.values(), "FDK_AAC_PATH", "DOVI_TOOL_PATH", "HDR10PLUS_TOOL_PATH",
    "VSEDIT_PATH", "VSPIPE_PATH", "PLUGIN_PATH", "LIBASS_PATH", "TS_MUXER_PATH",
    "MKVTOOLNIX_PATH", "MPV_PATH", "MPV_CONFIG_PATH",
)
TOOL_EXECUTABLE_NAMES = tuple(
    name for name in (*TOOL_PATH_NAMES, *MKVTOOLNIX_TOOLS) if name not in TOOL_DIRECTORY_NAMES and name != "LIBASS_PATH"
)

_EXECUTABLE_CANDIDATES = {
    "SEVEN_ZIP_PATH": ("7zz", "7z"),
    "FLAC_PATH": ("flac",),
    "FFMPEG_PATH": ("ffmpeg",),
    "FFPROBE_PATH": ("ffprobe",),
    "X264_PATH": ("x264",),
    "X265_PATH": ("x265",),
    "SVT_AV1_PATH": ("SvtAv1EncApp",),
    "FDK_AAC_PATH": ("fdkaac",),
    "DOVI_TOOL_PATH": ("dovi_tool",),
    "HDR10PLUS_TOOL_PATH": ("hdr10plus_tool",),
    "VSEDIT_PATH": ("vsedit",),
    "VSPIPE_PATH": ("vspipe",),
    "TS_MUXER_PATH": ("tsMuxeR", "tsmuxer"),
}


active_tool_paths: ContextVar[Mapping[str, str] | None] = ContextVar("active_tool_paths", default=None)


@contextmanager
def using_tool_paths(paths: Mapping[str, str]):
    reset = active_tool_paths.set(paths)
    try:
        yield
    finally:
        active_tool_paths.reset(reset)


def bundle_directory() -> Path | None:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS).resolve()
    return None


def is_bundled_tool(path: str) -> bool:
    bundle = bundle_directory()
    return bool(path and bundle and Path(path).resolve().is_relative_to(bundle))


def mkvtoolnix_executables(directory: str) -> dict[str, str]:
    suffix = ".exe" if sys.platform == "win32" else ""
    return {
        name: os.path.join(directory, program + suffix) if directory else ""
        for name, program in MKVTOOLNIX_TOOLS.items()
    }


def migrate_tool_paths(paths: Mapping[str, str]) -> dict[str, str]:
    result = dict(paths)
    if "MKVTOOLNIX_PATH" not in paths:
        # Use the muxer's directory when the old fields point to different installations.
        for name in MKVTOOLNIX_TOOLS:
            if path := paths.get(name):
                if not isinstance(path, str):
                    raise ValueError(translate_text("Invalid path for {tool}.").format(tool=name))
                result["MKVTOOLNIX_PATH"] = os.path.dirname(path) or os.path.dirname(os.path.expandvars(path)) or "."
                break
    for name in MKVTOOLNIX_TOOLS:
        result.pop(name, None)
    return result


def _bundled_encode_paths(bundle: Path) -> dict[str, str]:
    if sys.platform == "win32":
        vspipe = bundle / "Lib/site-packages/vapoursynth/vspipe.exe"
        if not vspipe.is_file():
            vspipe = bundle / "vspipe.exe"
        filenames = ("x264.exe", "x265.exe", "SvtAv1EncApp.exe")
        bin_directory = bundle
    else:
        bin_directory = bundle / "linux/bin"
        vspipe = bin_directory / "vspipe"
        filenames = ("x264", "x265", "SvtAv1EncApp")
    return {
        "VSPIPE_PATH": str(vspipe),
        **{name: str(bin_directory / filename) for name, filename in zip(ENCODER_PATH_NAMES.values(), filenames)},
    }


def default_tool_paths() -> dict[str, str]:
    bundle = bundle_directory()
    if bundle is None or not (sys.platform == "win32" or sys.platform.startswith("linux")):
        return dict.fromkeys(TOOL_PATH_NAMES, "")
    paths = {name: getattr(settings, name) for name in TOOL_PATH_NAMES}
    paths.update(_bundled_encode_paths(bundle))
    return paths


def _read_legacy_paths(path: Path, bundle: Path | None) -> dict[str, str]:
    """Read known assignments from the old settings editor without running Python code."""
    paths: dict[str, str] = {}

    def read_value(node: ast.expr) -> str:
        if isinstance(node, ast.Call):
            function = ast.unparse(node.func)
            if function == "_bundled_path" and len(node.args) == 2:
                return str(bundle / read_value(node.args[0])) if bundle else read_value(node.args[1])
            if function == "os.path.expanduser" and len(node.args) == 1:
                return os.path.expanduser(read_value(node.args[0]))
        value = ast.literal_eval(node)
        if not isinstance(value, str):
            raise ValueError("Tool path must be a string")
        return value

    def collect(statements: list[ast.stmt]) -> None:
        for node in statements:
            if isinstance(node, ast.If):
                condition = node.test
                if isinstance(condition, ast.Compare) and ast.unparse(condition.left) == "sys.platform":
                    if (
                            len(condition.ops) == 1 and isinstance(condition.ops[0], (ast.Eq, ast.NotEq))
                            and isinstance(condition.comparators[0], ast.Constant)
                    ):
                        matches = sys.platform == condition.comparators[0].value
                        collect(node.body if matches == isinstance(condition.ops[0], ast.Eq) else node.orelse)
                continue
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                targets = [node.target]
            else:
                continue
            names = [
                target.id for target in targets if isinstance(target, ast.Name)
                and (target.id in TOOL_PATH_NAMES or target.id in MKVTOOLNIX_TOOLS)
            ]
            if not names:
                continue
            try:
                entry = read_value(node.value)
            except ValueError as error:
                raise ValueError(f"Could not read {names[0]} in {path}") from error
            paths.update(dict.fromkeys(names, entry))

    collect(ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path)).body)
    return migrate_tool_paths(paths)


def initial_tool_paths(config_directory: Path, settings_path: Path | None = None) -> dict[str, str]:
    paths = default_tool_paths()
    bundle = bundle_directory()
    if settings_path is None and bundle:
        legacy_directory = Path(sys.executable).resolve().parent if sys.platform == "win32" else config_directory
        legacy = legacy_directory / "src/core/settings.py"
        if legacy.is_file():
            settings_path = legacy
    if settings_path is not None:
        imported = _read_legacy_paths(settings_path, bundle)
        if bundle:
            # The old frozen Encode page defaulted to the bundled tools.
            for name in ("VSPIPE_PATH", *ENCODER_PATH_NAMES.values()):
                if imported.get(name) == getattr(settings, name):
                    imported.pop(name)
        paths.update(imported)
    if bundle and config_directory == Path(sys.executable).resolve().parent:
        for name, path in paths.items():
            if path and Path(path).is_relative_to(bundle):
                paths[name] = os.path.relpath(path, config_directory)
    return paths


def default_mpv_config_directory() -> Path:
    if bundle_directory() is not None and settings.MPV_CONFIG_PATH:
        return Path(settings.MPV_CONFIG_PATH)
    if mpv_home := os.environ.get("MPV_HOME"):
        return Path(mpv_home).expanduser().absolute()
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData/Roaming") / "mpv"
    return (Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "mpv").absolute()


def _find_libass_path() -> str:
    if sys.platform == "win32":
        for name in ("libass-9.dll", "libass.dll", "ass.dll"):
            if path := ctypes.util.find_library(name):
                return os.path.abspath(path)
        return ""

    class DlInfo(ctypes.Structure):
        _fields_ = [
            ("filename", ctypes.c_char_p), ("base", ctypes.c_void_p),
            ("symbol", ctypes.c_char_p), ("address", ctypes.c_void_p),
        ]

    try:
        dladdr = getattr(ctypes.CDLL(None), "dladdr", None)
    except OSError:
        return ""
    if dladdr is None:
        return ""
    dladdr.argtypes = (ctypes.c_void_p, ctypes.POINTER(DlInfo))
    dladdr.restype = ctypes.c_int
    defaults = (
        ("libass.dylib", "/opt/homebrew/lib/libass.dylib", "/usr/local/lib/libass.dylib")
        if sys.platform == "darwin" else ("libass.so.9", "libass.so")
    )
    candidates = dict.fromkeys((ctypes.util.find_library("ass"), *defaults))
    for name in filter(None, candidates):
        try:
            library = ctypes.CDLL(name)
            symbol = library.ass_library_init
        except (OSError, AttributeError):
            continue
        info = DlInfo()
        if dladdr(symbol, ctypes.byref(info)) and info.filename:
            return os.path.abspath(os.fsdecode(info.filename))
    return ""


def _find_associated_windows_mpv() -> str:
    import winreg

    choice = r"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.mp4\UserChoice"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, choice) as key:
            program_id, _ = winreg.QueryValueEx(key, "ProgId")
    except OSError:
        return ""
    name = program_id.rsplit("\\", 1)[-1]
    names = [name]
    if not name.lower().endswith(".exe"):
        names.append(f"{name}.exe")
    if "mpv" in name.lower() and "mpv.exe" not in names:
        names.append("mpv.exe")
    for name in names:
        for root, command_key in (
                (winreg.HKEY_CLASSES_ROOT, rf"{name}\shell\open\command"),
                (winreg.HKEY_CLASSES_ROOT, rf"Applications\{name}\shell\open\command"),
                (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{name}"),
        ):
            try:
                with winreg.OpenKey(root, command_key) as key:
                    command, _ = winreg.QueryValueEx(key, "")
            except OSError:
                continue
            command = os.path.expandvars(command).strip()
            executable = command[1:].partition('"')[0] if command.startswith('"') else command.partition(" ")[0]
            if os.path.basename(executable).lower() == "mpv.exe":
                path = executable if os.path.isabs(executable) else shutil.which(executable)
                if path and os.path.isfile(path):
                    return path
    return ""


def _discover_tool_paths(paths: dict[str, str]) -> None:
    for name, programs in _EXECUTABLE_CANDIDATES.items():
        if paths.get(name):
            continue
        for program in programs:
            if executable := shutil.which(program):
                paths[name] = os.path.abspath(executable)
                break
    if not paths.get("MKVTOOLNIX_PATH"):
        for directory in os.get_exec_path():
            directory = os.path.abspath(directory)
            if all(tool_path_exists(name, entry) for name, entry in mkvtoolnix_executables(directory).items()):
                paths["MKVTOOLNIX_PATH"] = directory
                break

    if sys.platform == "win32" or sys.platform.startswith("linux"):
        # Installations prepared by setup may also put tools outside PATH.
        for name in TOOL_PATH_NAMES:
            if paths.get(name):
                continue
            candidate = getattr(settings, name)
            if name == "MKVTOOLNIX_PATH":
                found = all(
                    tool_path_exists(tool, entry) for tool, entry in mkvtoolnix_executables(candidate).items()
                )
            else:
                found = tool_path_exists(name, candidate)
            if found:
                paths[name] = candidate
    if not paths.get("LIBASS_PATH"):
        paths["LIBASS_PATH"] = _find_libass_path()
    if not paths.get("MPV_PATH"):
        if sys.platform == "win32":
            paths["MPV_PATH"] = _find_associated_windows_mpv()
        elif executable := shutil.which("mpv"):
            paths["MPV_PATH"] = os.path.abspath(executable)
    if not paths.get("MPV_CONFIG_PATH"):
        paths["MPV_CONFIG_PATH"] = str(default_mpv_config_directory())


def resolve_tool_paths(
        configured: Mapping[str, str], config_directory: Path, *, discover: bool = True,
) -> Mapping[str, str]:
    paths = dict.fromkeys(TOOL_PATH_NAMES, "")
    for name, path in configured.items():
        if not isinstance(path, str) or any(character in path for character in '\0\r\n\t'):
            raise ValueError(translate_text("Invalid path for {tool}.").format(tool=name))
        # Keep symlink paths so launchers can use their selected installation directory.
        paths[name] = os.path.abspath(config_directory / os.path.expanduser(os.path.expandvars(path))) if path else ""
    if discover:
        _discover_tool_paths(paths)
    paths.update(mkvtoolnix_executables(paths["MKVTOOLNIX_PATH"]))
    return MappingProxyType(paths)


@cache
def _resolved_defaults() -> Mapping[str, str]:
    return resolve_tool_paths(default_tool_paths(), Path(__file__).resolve().parents[2])


def tool_path(name: str) -> str:
    paths = active_tool_paths.get()
    return (_resolved_defaults() if paths is None else paths)[name]


def tool_path_exists(name: str, path: str) -> bool:
    if not path:
        return False
    if name in TOOL_DIRECTORY_NAMES:
        return os.path.isdir(path)
    return os.path.isfile(path) and (name == "LIBASS_PATH" or os.access(path, os.X_OK))


def require_tool_path(name: str) -> str:
    path = tool_path(name)
    if not tool_path_exists(name, path):
        raise FileNotFoundError(translate_text("The path {path} for {tool} is missing or unusable.").format(
            tool=name, path=path or translate_text("not configured"),
        ))
    return path
