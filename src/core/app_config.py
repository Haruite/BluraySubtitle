"""Persistent application preferences stored beside the program."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from base64 import b64decode
from binascii import Error as BinasciiError
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from src.core.encode_presets import ENCODE_PRESET_NAMES, encode_preset_parameters


APP_CONFIG_FILENAME = "config.json"
DEFAULT_CONFIG_FILENAME = "config.default.json"
CONFIG_SCHEMA_VERSION = 1
FUNCTION_PAGE_IDS = {
    "bluray_remux": 3,
    "bluray_encode": 4,
    "bluray_diy": 5,
    "merge_subtitles": 1,
    "add_chapters": 2,
}


@dataclass(frozen=True)
class WindowPreferences:
    geometry: str = ""


@dataclass(frozen=True)
class UiPreferences:
    language: str = "en"
    theme: str = "light"
    font_size: int = 10
    opacity: int = 94


@dataclass(frozen=True)
class StartupPreferences:
    function_page: str = "bluray_remux"
    episode_mode: str = "series"


@dataclass(frozen=True)
class PathPreferences:
    remux_output: str = ""
    encode_output: str = ""


@dataclass(frozen=True)
class AudioPreferences:
    flac_compression_level: int = 8
    ffmpeg_flac_compression_level: int = 8
    fdkaac_bitrate_kbps: int = 0
    opus_bitrate_kbps: int = 0


@dataclass(frozen=True)
class RemuxPreferences:
    convert_lossless_audio_to_flac: bool = True


@dataclass(frozen=True)
class EncodePreferences:
    encoder: str = "x265"
    bit_depth: str = "10"
    preset: str = "Balanced"
    preset_parameters: str = encode_preset_parameters("x265", "Balanced")
    lossless_audio_codec: str = "flac"
    subtitle_mode: str = "external"
    use_getnative: bool = True
    auto_crop_black_borders: bool = False
    output_comparison_images: bool = True


@dataclass(frozen=True)
class AppConfig:
    schema_version: int = CONFIG_SCHEMA_VERSION
    window: WindowPreferences = WindowPreferences()
    ui: UiPreferences = UiPreferences()
    startup: StartupPreferences = StartupPreferences()
    paths: PathPreferences = PathPreferences()
    audio: AudioPreferences = AudioPreferences()
    remux: RemuxPreferences = RemuxPreferences()
    encode: EncodePreferences = EncodePreferences()


def default_app_config() -> AppConfig:
    return AppConfig()


def application_directory() -> Path:
    if bool(getattr(sys, "frozen", False)):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def app_config_path() -> Path:
    return application_directory() / APP_CONFIG_FILENAME


def default_config_path() -> Path:
    if bool(getattr(sys, "frozen", False)) and hasattr(sys, "_MEIPASS"):
        return Path(str(sys._MEIPASS)).resolve() / DEFAULT_CONFIG_FILENAME
    return application_directory() / DEFAULT_CONFIG_FILENAME


def _object_section(raw: dict[str, Any], name: str) -> dict[str, Any]:
    value = raw.get(name, {})
    if not isinstance(value, dict):
        raise ValueError(f"Configuration section must be an object: {name}")
    return value


def _string_value(section: dict[str, Any], name: str, default: str) -> str:
    value = section.get(name, default)
    if not isinstance(value, str):
        raise ValueError(f"Configuration value must be a string: {name}")
    return value


def _integer_value(
        section: dict[str, Any],
        name: str,
        default: int,
        minimum: int,
        maximum: int,
) -> int:
    value = section.get(name, default)
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(
            f"Configuration value must be an integer from {minimum} to {maximum}: {name}"
        )
    return value


def _boolean_value(section: dict[str, Any], name: str, default: bool) -> bool:
    value = section.get(name, default)
    if type(value) is not bool:
        raise ValueError(f"Configuration value must be a boolean: {name}")
    return value


def app_config_from_mapping(raw: dict[str, Any]) -> AppConfig:
    if not isinstance(raw, dict):
        raise ValueError("Configuration root must be a JSON object")
    schema_version = raw.get("schema_version", CONFIG_SCHEMA_VERSION)
    if type(schema_version) is not int or schema_version != CONFIG_SCHEMA_VERSION:
        raise ValueError(f"Unsupported configuration schema version: {schema_version}")

    window = _object_section(raw, "window")
    ui = _object_section(raw, "ui")
    startup = _object_section(raw, "startup")
    paths = _object_section(raw, "paths")
    audio = _object_section(raw, "audio")
    remux = _object_section(raw, "remux")
    encode = _object_section(raw, "encode")

    language = _string_value(ui, "language", "en")
    if language not in ("en", "zh"):
        raise ValueError(f"Unsupported UI language: {language}")
    theme = _string_value(ui, "theme", "light")
    if theme not in ("light", "dark", "colorful"):
        raise ValueError(f"Unsupported UI theme: {theme}")
    function_page = _string_value(startup, "function_page", "bluray_remux")
    if function_page not in FUNCTION_PAGE_IDS:
        raise ValueError(f"Unsupported startup function page: {function_page}")
    episode_mode = _string_value(startup, "episode_mode", "series")
    if episode_mode not in ("series", "movie"):
        raise ValueError(f"Unsupported startup episode mode: {episode_mode}")
    encoder = _string_value(encode, "encoder", "x265")
    if encoder not in ("x264", "x265", "svtav1"):
        raise ValueError(f"Unsupported default encoder: {encoder}")
    bit_depth = _string_value(encode, "bit_depth", "10")
    if bit_depth not in ("8", "10", "12") or (
            encoder == "x264" and bit_depth == "12"
    ):
        raise ValueError(
            f"Unsupported default bit depth for {encoder}: {bit_depth}"
        )
    preset = _string_value(encode, "preset", "Balanced")
    if preset not in ENCODE_PRESET_NAMES:
        raise ValueError(f"Unsupported default encode preset: {preset}")
    lossless_audio_codec = _string_value(
        encode,
        "lossless_audio_codec",
        "flac",
    )
    if lossless_audio_codec not in ("flac", "aac", "opus"):
        raise ValueError(
            f"Unsupported default lossless audio target: {lossless_audio_codec}"
        )
    subtitle_mode = _string_value(encode, "subtitle_mode", "external")
    if subtitle_mode not in ("external", "softsub", "hardsub"):
        raise ValueError(f"Unsupported default subtitle packaging: {subtitle_mode}")

    geometry = _string_value(window, "geometry", "")
    if geometry:
        try:
            b64decode(geometry, validate=True)
        except (BinasciiError, ValueError) as error:
            raise ValueError("Stored window geometry is not valid Base64") from error

    return AppConfig(
        schema_version=schema_version,
        window=WindowPreferences(
            geometry=geometry,
        ),
        ui=UiPreferences(
            language=language,
            theme=theme,
            font_size=_integer_value(ui, "font_size", 10, 6, 14),
            opacity=_integer_value(ui, "opacity", 94, 60, 100),
        ),
        startup=StartupPreferences(
            function_page=function_page,
            episode_mode=episode_mode,
        ),
        paths=PathPreferences(
            remux_output=_string_value(paths, "remux_output", ""),
            encode_output=_string_value(paths, "encode_output", ""),
        ),
        audio=AudioPreferences(
            flac_compression_level=_integer_value(
                audio,
                "flac_compression_level",
                8,
                0,
                8,
            ),
            ffmpeg_flac_compression_level=_integer_value(
                audio,
                "ffmpeg_flac_compression_level",
                8,
                0,
                12,
            ),
            fdkaac_bitrate_kbps=_integer_value(
                audio,
                "fdkaac_bitrate_kbps",
                0,
                0,
                1024,
            ),
            opus_bitrate_kbps=_integer_value(
                audio,
                "opus_bitrate_kbps",
                0,
                0,
                1024,
            ),
        ),
        remux=RemuxPreferences(
            convert_lossless_audio_to_flac=_boolean_value(
                remux,
                "convert_lossless_audio_to_flac",
                True,
            ),
        ),
        encode=EncodePreferences(
            encoder=encoder,
            bit_depth=bit_depth,
            preset=preset,
            preset_parameters=_string_value(
                encode,
                "preset_parameters",
                encode_preset_parameters(encoder, preset),
            ),
            lossless_audio_codec=lossless_audio_codec,
            subtitle_mode=subtitle_mode,
            use_getnative=_boolean_value(
                encode,
                "use_getnative",
                True,
            ),
            auto_crop_black_borders=_boolean_value(
                encode,
                "auto_crop_black_borders",
                False,
            ),
            output_comparison_images=_boolean_value(
                encode,
                "output_comparison_images",
                True,
            ),
        ),
    )


def _read_app_config(path: Path) -> AppConfig:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"Invalid JSON in {path}: {error}") from error
    return app_config_from_mapping(raw)


def save_app_config(config: AppConfig, path: Path | None = None) -> None:
    target = Path(path) if path is not None else app_config_path()
    if not target.parent.is_dir():
        raise FileNotFoundError(f"Configuration directory does not exist: {target.parent}")
    text = json.dumps(asdict(config), ensure_ascii=False, indent=2).replace(
        "\n", "\r\n"
    ) + "\r\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, target)
    except Exception:
        try:
            os.remove(temporary_name)
        except OSError:
            pass
        raise


def load_app_config(
        path: Path | None = None,
        template_path: Path | None = None,
) -> AppConfig:
    target = Path(path) if path is not None else app_config_path()
    if target.is_file():
        return _read_app_config(target)
    template = Path(template_path) if template_path is not None else default_config_path()
    if not template.is_file():
        raise FileNotFoundError(f"Default configuration does not exist: {template}")
    config = _read_app_config(template)
    save_app_config(config, target)
    return config


__all__ = [
    "APP_CONFIG_FILENAME",
    "CONFIG_SCHEMA_VERSION",
    "DEFAULT_CONFIG_FILENAME",
    "FUNCTION_PAGE_IDS",
    "AppConfig",
    "AudioPreferences",
    "EncodePreferences",
    "PathPreferences",
    "RemuxPreferences",
    "StartupPreferences",
    "UiPreferences",
    "WindowPreferences",
    "app_config_from_mapping",
    "app_config_path",
    "application_directory",
    "default_app_config",
    "default_config_path",
    "load_app_config",
    "save_app_config",
]
