"""Persistent application preferences stored beside the program."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from base64 import b64decode
from binascii import Error as BinasciiError
from dataclasses import asdict, dataclass, field, replace
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable

from src.core.encode_presets import (
    ENCODE_PRESET_NAMES,
    UserEncodePreset,
    encode_preset_parameters,
    encode_presets_for_encoder,
)
from src.core.tool_paths import MKVTOOLNIX_TOOLS, default_tool_paths, initial_tool_paths, migrate_tool_paths


APP_CONFIG_FILENAME = "config.json"
DEFAULT_CONFIG_FILENAME = "config.default.json"
CONFIG_SCHEMA_VERSION = 1
MAX_BACKGROUND_BLUR = 40
MAX_LOG_LINE_LIMIT = 100_000
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
    log_geometry: str = ""


@dataclass(frozen=True)
class FontPreferences:
    interface: str = ""
    table: str = ""
    log: str = ""
    editor: str = ""


@dataclass(frozen=True)
class UiPreferences:
    language: str = "en"
    theme: str = "light"
    font_size: int = 10
    opacity: int = 100
    save_log_to_file: bool = False
    log_line_limit: int = 4000
    log_theme: str = "follow"
    close_to_tray: bool = True
    check_updates_on_startup: bool = True
    main_background_path: str = ""
    main_background_opacity: int = 20
    main_background_blur: int = 0
    log_background_path: str = ""
    log_background_opacity: int = 20
    log_background_blur: int = 0
    fonts: FontPreferences = FontPreferences()


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
    duration_loss_fallback_threshold_seconds: float = 1.0


@dataclass(frozen=True)
class RemuxPreferences:
    convert_lossless_audio_to_flac: bool = True
    convert_immersive_audio_to_flac: bool = False
    allow_partial_missing_non_video_tracks: bool = False
    save_audio_gaps: bool = False
    keep_sp_by_default: bool = True


@dataclass(frozen=True)
class EncodePreferences:
    encoder: str = "x265"
    bit_depth: str = "10"
    preset: str = "Balanced"
    custom_presets: tuple[UserEncodePreset, ...] = ()
    lossless_audio_codec: str = "flac"
    subtitle_mode: str = "external"
    use_getnative: bool = True
    auto_crop_black_borders: bool = False
    output_comparison_images: bool = True
    check_corrupted_frames: bool = False
    frame_check_luma_psnr_threshold_db: float = 30.0
    frame_check_chroma_psnr_threshold_db: float = 30.0
    vpy_denoise_strength: float = 0.6
    vpy_dehalo_strength: float = 0.0
    vpy_dering_strength: float = 0.0
    vpy_deband_strength: float = 0.5
    vpy_antialiasing_strength: float = 0.5


@dataclass(frozen=True)
class AppConfig:
    schema_version: int = CONFIG_SCHEMA_VERSION
    window: WindowPreferences = WindowPreferences()
    ui: UiPreferences = UiPreferences()
    startup: StartupPreferences = StartupPreferences()
    paths: PathPreferences = PathPreferences()
    tools: dict[str, str] = field(default_factory=default_tool_paths)
    audio: AudioPreferences = AudioPreferences()
    remux: RemuxPreferences = RemuxPreferences()
    encode: EncodePreferences = EncodePreferences()


def default_app_config() -> AppConfig:
    return AppConfig()


def application_directory() -> Path:
    if bool(getattr(sys, "frozen", False)):
        return Path(sys.executable).resolve().parent
    if runtime := getattr(sys, "_bluray_freebsd_runtime", None):
        return Path(runtime).parent
    return Path(__file__).resolve().parents[2]


def application_support_directory() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS).resolve()
    if runtime := getattr(sys, "_bluray_freebsd_runtime", None):
        return Path(runtime) / "app"
    return application_directory()


def macos_application_bundle() -> Path | None:
    """Finder bundle of the running packaged edition, including renamed installations."""
    bundle = getattr(sys, "_bluray_macos_app", None)
    return Path(bundle) if sys.platform == "darwin" and bundle else None


def application_location_id(directory: Path | None = None) -> str:
    return sha256(os.fsencode(os.path.normcase(str(directory or application_directory())))).hexdigest()[:24]


def app_config_path() -> Path:
    configured_directory = os.environ.get("BLURAY_SUBTITLE_CONFIG_DIR")
    if configured_directory:
        return Path(configured_directory).expanduser().resolve() / APP_CONFIG_FILENAME
    return application_directory() / APP_CONFIG_FILENAME


def default_config_path() -> Path:
    return application_support_directory() / DEFAULT_CONFIG_FILENAME


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


def _number_value(
        section: dict[str, Any],
        name: str,
        default: float,
        minimum: float,
        maximum: float,
) -> float:
    value = section.get(name, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(
            f"Configuration value must be a number from {minimum} to {maximum}: {name}"
        )
    result = float(value)
    if not minimum <= result <= maximum:
        raise ValueError(
            f"Configuration value must be a number from {minimum} to {maximum}: {name}"
        )
    return result


def _boolean_value(section: dict[str, Any], name: str, default: bool) -> bool:
    value = section.get(name, default)
    if type(value) is not bool:
        raise ValueError(f"Configuration value must be a boolean: {name}")
    return value


def _available_encode_preset_name(base_name: str, used_names: set[str]) -> str:
    name = base_name
    suffix = 2
    while name.casefold() in used_names:
        name = f"{base_name} {suffix}"
        suffix += 1
    return name


def _custom_encode_presets(
        section: dict[str, Any],
        default_encoder: str,
        default_preset: str,
) -> tuple[str, tuple[UserEncodePreset, ...]]:
    value = section.get("custom_presets", [])
    if not isinstance(value, list):
        raise ValueError("Configuration value must be a list: custom_presets")
    presets: list[UserEncodePreset] = []
    names_by_encoder: dict[str, set[str]] = {
        "x264": set(),
        "x265": set(),
        "svtav1": set(),
    }
    built_in_names = {name.casefold() for name in ENCODE_PRESET_NAMES}
    newly_reserved_names = {"very fast", "very high quality"}
    previously_reserved_names = built_in_names - newly_reserved_names
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            raise ValueError(
                f"Custom encode preset {index} must be an object"
            )
        encoder = _string_value(item, "encoder", "").strip().lower()
        if encoder not in names_by_encoder:
            raise ValueError(
                f"Unsupported custom encode preset encoder: {encoder}"
            )
        name = _string_value(item, "name", "").strip()
        if not name:
            raise ValueError("Custom encode preset name must not be empty")
        normalized_name = name.casefold()
        if normalized_name in previously_reserved_names:
            raise ValueError(
                f"Custom encode preset name conflicts with a built-in preset: {name}"
            )
        if normalized_name in names_by_encoder[encoder]:
            raise ValueError(
                f"Duplicate custom encode preset for {encoder}: {name}"
            )
        names_by_encoder[encoder].add(normalized_name)
        presets.append(UserEncodePreset(
            encoder=encoder,
            name=name,
            parameters=_string_value(item, "parameters", "").strip(),
        ))

    # Older configurations could use the new built-in names for custom presets.
    for index, preset in enumerate(presets):
        if preset.name.casefold() not in newly_reserved_names:
            continue
        used_names = names_by_encoder[preset.encoder]
        name = _available_encode_preset_name(f"{preset.name} Custom", used_names | built_in_names)
        used_names.add(name.casefold())
        presets[index] = replace(preset, name=name)
        if preset.encoder == default_encoder and preset.name == default_preset:
            default_preset = name
    return default_preset, tuple(presets)


def _migrate_legacy_encode_parameters(
        section: dict[str, Any],
        encoder: str,
        preset: str,
        custom_presets: tuple[UserEncodePreset, ...],
) -> tuple[str, tuple[UserEncodePreset, ...]]:
    if "preset_parameters" not in section:
        return preset, custom_presets
    legacy_parameters = _string_value(
        section,
        "preset_parameters",
        "",
    ).strip()
    if preset in ENCODE_PRESET_NAMES:
        if legacy_parameters == encode_preset_parameters(encoder, preset):
            return preset, custom_presets
        base_name = f"{preset} Custom"
    elif preset == "Custom":
        base_name = "Custom"
    else:
        return preset, custom_presets
    used_names = {
        item.name.casefold()
        for item in custom_presets
        if item.encoder == encoder
    } | {name.casefold() for name in ENCODE_PRESET_NAMES}
    migrated_name = _available_encode_preset_name(base_name, used_names)
    return migrated_name, custom_presets + (UserEncodePreset(
        encoder=encoder,
        name=migrated_name,
        parameters=legacy_parameters,
    ),)


def app_config_from_mapping(raw: dict[str, Any]) -> AppConfig:
    if not isinstance(raw, dict):
        raise ValueError("Configuration root must be a JSON object")
    schema_version = raw.get("schema_version", CONFIG_SCHEMA_VERSION)
    if type(schema_version) is not int or schema_version != CONFIG_SCHEMA_VERSION:
        raise ValueError(f"Unsupported configuration schema version: {schema_version}")

    window = _object_section(raw, "window")
    ui = _object_section(raw, "ui")
    fonts = _object_section(ui, "fonts")
    startup = _object_section(raw, "startup")
    paths = _object_section(raw, "paths")
    tools = migrate_tool_paths(_object_section(raw, "tools"))
    audio = _object_section(raw, "audio")
    remux = _object_section(raw, "remux")
    encode = _object_section(raw, "encode")

    language = _string_value(ui, "language", "en")
    if language not in ("en", "zh"):
        raise ValueError(f"Unsupported UI language: {language}")
    theme = _string_value(ui, "theme", "light")
    if theme not in ("light", "dark", "colorful"):
        raise ValueError(f"Unsupported UI theme: {theme}")
    log_theme = _string_value(ui, "log_theme", UiPreferences.log_theme)
    if log_theme not in ("follow", "light", "dark", "colorful"):
        raise ValueError(f"Unsupported log window theme {log_theme!r}")
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
    preset = _string_value(encode, "preset", "Balanced").strip()
    preset, custom_presets = _custom_encode_presets(encode, encoder, preset)
    preset, custom_presets = _migrate_legacy_encode_parameters(
        encode,
        encoder,
        preset,
        custom_presets,
    )
    if preset not in encode_presets_for_encoder(encoder, custom_presets):
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

    window_geometries = {
        name: _string_value(window, name, "") for name in ("geometry", "log_geometry")
    }
    for geometry in window_geometries.values():
        try:
            b64decode(geometry, validate=True)
        except (BinasciiError, ValueError) as error:
            raise ValueError("Stored window geometry is not valid Base64") from error

    return AppConfig(
        schema_version=schema_version,
        window=WindowPreferences(**window_geometries),
        ui=UiPreferences(
            language=language,
            theme=theme,
            font_size=_integer_value(ui, "font_size", 10, 6, 14),
            opacity=_integer_value(ui, "opacity", UiPreferences.opacity, 60, 100),
            save_log_to_file=_boolean_value(ui, "save_log_to_file", UiPreferences.save_log_to_file),
            log_line_limit=_integer_value(ui, "log_line_limit", UiPreferences.log_line_limit, 1, MAX_LOG_LINE_LIMIT),
            log_theme=log_theme,
            close_to_tray=_boolean_value(ui, "close_to_tray", UiPreferences.close_to_tray),
            check_updates_on_startup=_boolean_value(ui, "check_updates_on_startup", UiPreferences.check_updates_on_startup),
            main_background_path=_string_value(ui, "main_background_path", UiPreferences.main_background_path),
            main_background_opacity=_integer_value(
                ui, "main_background_opacity", UiPreferences.main_background_opacity, 0, 100,
            ),
            main_background_blur=_integer_value(
                ui, "main_background_blur", UiPreferences.main_background_blur, 0, MAX_BACKGROUND_BLUR,
            ),
            log_background_path=_string_value(ui, "log_background_path", UiPreferences.log_background_path),
            log_background_opacity=_integer_value(
                ui, "log_background_opacity", UiPreferences.log_background_opacity, 0, 100,
            ),
            log_background_blur=_integer_value(
                ui, "log_background_blur", UiPreferences.log_background_blur, 0, MAX_BACKGROUND_BLUR,
            ),
            fonts=FontPreferences(
                interface=_string_value(fonts, "interface", ""),
                table=_string_value(fonts, "table", ""),
                log=_string_value(fonts, "log", ""),
                editor=_string_value(fonts, "editor", ""),
            ),
        ),
        startup=StartupPreferences(
            function_page=function_page,
            episode_mode=episode_mode,
        ),
        paths=PathPreferences(
            remux_output=_string_value(paths, "remux_output", ""),
            encode_output=_string_value(paths, "encode_output", ""),
        ),
        tools={name: _string_value(tools, name, value) for name, value in default_tool_paths().items()},
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
            duration_loss_fallback_threshold_seconds=_number_value(
                audio,
                "duration_loss_fallback_threshold_seconds",
                1.0,
                0.1,
                60.0,
            ),
        ),
        remux=RemuxPreferences(
            convert_lossless_audio_to_flac=_boolean_value(
                remux,
                "convert_lossless_audio_to_flac",
                True,
            ),
            convert_immersive_audio_to_flac=_boolean_value(
                remux,
                "convert_immersive_audio_to_flac",
                False,
            ),
            allow_partial_missing_non_video_tracks=_boolean_value(
                remux,
                "allow_partial_missing_non_video_tracks",
                False,
            ),
            save_audio_gaps=_boolean_value(remux, "save_audio_gaps", False),
            keep_sp_by_default=_boolean_value(remux, "keep_sp_by_default", RemuxPreferences.keep_sp_by_default),
        ),
        encode=EncodePreferences(
            encoder=encoder,
            bit_depth=bit_depth,
            preset=preset,
            custom_presets=custom_presets,
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
            check_corrupted_frames=_boolean_value(
                encode,
                "check_corrupted_frames",
                False,
            ),
            frame_check_luma_psnr_threshold_db=_number_value(
                encode,
                "frame_check_luma_psnr_threshold_db",
                30.0,
                0.0,
                100.0,
            ),
            frame_check_chroma_psnr_threshold_db=_number_value(
                encode,
                "frame_check_chroma_psnr_threshold_db",
                30.0,
                0.0,
                100.0,
            ),
            vpy_denoise_strength=_number_value(
                encode,
                "vpy_denoise_strength",
                0.6,
                0.0,
                3.0,
            ),
            vpy_dehalo_strength=_number_value(
                encode,
                "vpy_dehalo_strength",
                0.0,
                0.0,
                1.0,
            ),
            vpy_dering_strength=_number_value(
                encode,
                "vpy_dering_strength",
                0.0,
                0.0,
                1.0,
            ),
            vpy_deband_strength=_number_value(
                encode,
                "vpy_deband_strength",
                0.5,
                0.0,
                1.0,
            ),
            vpy_antialiasing_strength=_number_value(
                encode,
                "vpy_antialiasing_strength",
                0.5,
                0.0,
                1.0,
            ),
        ),
    )


def _read_config_mapping(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"Invalid JSON in {path}: {error}") from error
    if not isinstance(raw, dict):
        raise ValueError("Configuration root must be a JSON object")
    return raw


def save_app_config(config: AppConfig, path: Path | None = None, *, preserve_tools: bool = False) -> None:
    target = Path(path) if path is not None else app_config_path()
    if not target.parent.is_dir():
        raise FileNotFoundError(f"Configuration directory does not exist: {target.parent}")
    values = asdict(config)
    if preserve_tools and target.is_file():
        current = _read_config_mapping(target)
        if "tools" in current:
            values["tools"] = current["tools"]
        else:
            values.pop("tools")
    text = json.dumps(values, ensure_ascii=False, indent=2).replace(
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
        *,
        settings_path: Path | None = None,
        on_tools_initialized: Callable[[AppConfig], None] | None = None,
        require_tools: bool = False,
) -> AppConfig:
    target = Path(path) if path is not None else app_config_path()
    existing = target.is_file()
    if existing or require_tools:
        raw = _read_config_mapping(target)
    else:
        template = Path(template_path) if template_path is not None else default_config_path()
        if not template.is_file():
            raise FileNotFoundError(f"Default configuration does not exist: {template}")
        raw = _read_config_mapping(template)
    initialize_tools = "tools" not in raw
    if initialize_tools:
        if require_tools:
            raise ValueError(f"Configuration is missing the tools section: {target}")
        raw["tools"] = initial_tool_paths(target.parent, settings_path)
    config = app_config_from_mapping(raw)
    if not existing or initialize_tools or MKVTOOLNIX_TOOLS.keys() & raw["tools"].keys():
        save_app_config(config, target)
    if initialize_tools and on_tools_initialized is not None:
        on_tools_initialized(config)
    return config


__all__ = [
    "APP_CONFIG_FILENAME",
    "CONFIG_SCHEMA_VERSION",
    "DEFAULT_CONFIG_FILENAME",
    "FUNCTION_PAGE_IDS",
    "AppConfig",
    "AudioPreferences",
    "EncodePreferences",
    "FontPreferences",
    "PathPreferences",
    "RemuxPreferences",
    "StartupPreferences",
    "UiPreferences",
    "UserEncodePreset",
    "WindowPreferences",
    "app_config_from_mapping",
    "app_config_path",
    "application_directory",
    "application_location_id",
    "application_support_directory",
    "default_app_config",
    "default_config_path",
    "load_app_config",
    "save_app_config",
]
