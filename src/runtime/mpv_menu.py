"""Select mpv's context-menu language for application-launched playback."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from src.core.app_config import application_support_directory


def menu_labels() -> dict[str, str]:
    path = application_support_directory() / "resource/mpv/menu.zh.tsv"
    return dict(line.split("\t", 1) for line in path.read_text(encoding="utf-8").splitlines())


def translate_mpv_menu(original: str, language: str) -> str:
    labels = menu_labels()
    translations = labels if language == "zh" else {value: key for key, value in labels.items()}
    reload = "Reloading current file..."
    old, new = (reload, labels[reload]) if language == "zh" else (labels[reload], reload)
    lines = []
    for line in original.splitlines():
        item = line.lstrip()
        title, separator, commands = item.partition("\t")
        indent = line[:len(line) - len(item)]
        lines.append(indent + translations.get(title, title) + separator + commands.replace(old, new))
    return "\n".join(lines) + "\n"


def mpv_language_options(language: str, config: Path) -> tuple[list[str], TemporaryDirectory[str] | None]:
    language = "zh" if language == "zh" else "en"
    filename = f"menu.{language}.conf"
    generated = None
    if (config / filename).is_file():
        menu = str(config / filename)
    else:
        fallback = application_support_directory() / "resource/mpv" / filename
        menu = str(fallback) if fallback.is_file() else ""
        try:
            legacy = (config / "menu.conf").read_text(encoding="utf-8-sig")
            if legacy.strip():
                generated = TemporaryDirectory(prefix="bluraysubtitle-mpv-")
                localized = Path(generated.name) / filename
                localized.write_text(translate_mpv_menu(legacy, language), encoding="utf-8")
                menu = str(localized)
        except (OSError, UnicodeError):
            if generated is not None:
                generated.cleanup()
                generated = None

    options = [
        "--script-opts-append=uosc-languages=" + ("zh-hans" if language == "zh" else "en"),
        f"--script-opts-append=bluray_defaults-language={language}",
        f"--script-opts-append=bluray_vs-language={language}",
    ]
    if menu:
        # The append operation takes one key/value pair, including commas in a path.
        options.append(f"--script-opts-append=select-menu_conf_path={menu}")
    return options, generated
