"""Prepare and read the desktop setup tool paths."""

import argparse
import json
import os
from dataclasses import replace
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core.app_config import app_config_path, load_app_config, save_app_config
from src.core.i18n import translate_text
from src.core.tool_paths import initial_tool_paths, resolve_tool_paths
from tools.windows_tool_paths import normalize_mkvtoolnix_path, normalize_vsedit_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("prepare", "linux", "windows"))
    parser.add_argument("settings", type=Path)
    parser.add_argument("language", choices=("en", "zh"))
    args = parser.parse_args()
    path = app_config_path()

    def show_initialized_tools(config) -> None:
        print(path)
        for name, value in config.tools.items():
            print(f"{name} = {value}")

    optional = {"MPV_PATH", "MPV_CONFIG_PATH", "PLUGIN_PATH" if sys.platform == "win32" else "LIBASS_PATH"}
    try:
        if args.operation == "prepare":
            initialized = []
            config = load_app_config(path, settings_path=args.settings, on_tools_initialized=initialized.append)
            automatic = [name for name, value in config.tools.items() if not value and name not in optional]
            if automatic and not initialized:
                defaults = initial_tool_paths(path.parent, args.settings)
                tools = config.tools | {name: defaults[name] for name in automatic}
                if tools != config.tools:
                    config = replace(config, tools=tools)
                    save_app_config(config, path)
                    show_initialized_tools(config)
            elif initialized:
                show_initialized_tools(config)
            return

        config = load_app_config(path, require_tools=True)
        resolved = resolve_tool_paths(config.tools, path.parent, discover=False)
        paths = {name: resolved[name] for name in config.tools}
        for name, value in paths.items():
            if (name not in optional and not value) or (args.operation == "windows" and '"' in value):
                raise ValueError(translate_text("Invalid setup tool path for {tool} in {path}", args.language).format(
                    tool=name, path=path,
                ))
        if args.operation == "linux":
            for name, value in paths.items():
                print(f"{name}\t{value}")
            return

        mkv = normalize_mkvtoolnix_path(Path(paths["MKVTOOLNIX_PATH"]))
        editor = normalize_vsedit_path(Path(paths["VSEDIT_PATH"]))
        mkv.mkdir(parents=True, exist_ok=True)
        editor.parent.mkdir(parents=True, exist_ok=True)
        normalized = {"MKVTOOLNIX_PATH": mkv, "VSEDIT_PATH": editor}
        saved_tools = config.tools.copy()
        for name, value in normalized.items():
            if str(value) != paths[name]:
                original = os.path.expanduser(os.path.expandvars(saved_tools[name]))
                saved_tools[name] = str(value) if os.path.isabs(original) else os.path.relpath(value, path.parent)
                paths[name] = str(value)
        if saved_tools != config.tools:
            save_app_config(replace(config, tools=saved_tools), path)
        print(json.dumps(paths))
    except (OSError, SyntaxError, ValueError) as error:
        message = translate_text("Could not read setup tool paths from {path}. {error}", args.language)
        parser.exit(1, message.format(path=path, error=error) + "\n")


if __name__ == "__main__":
    main()
