"""Load and normalize the configured Windows installation paths."""

import ast
import json
import os
from pathlib import Path
import runpy
import sys
import tempfile


MKV_SETTINGS = {
    "mkvmerge.exe": "MKV_MERGE_PATH",
    "mkvinfo.exe": "MKV_INFO_PATH",
    "mkvpropedit.exe": "MKV_PROP_EDIT_PATH",
    "mkvextract.exe": "MKV_EXTRACT_PATH",
}


def normalize_tool_path(path: Path, folder: str) -> Path:
    path = path.expanduser().resolve()
    if path.parent.name.casefold() != folder:
        path = path.parent / folder / path.name
    return path


def normalize_vsedit_path(path: Path) -> Path:
    return normalize_tool_path(path, "vsedit")


def write_tool_paths(settings_path: Path, changes: dict[str, str]) -> None:
    source = settings_path.read_text(encoding="utf-8")
    encoded = source.encode("utf-8")
    lines = encoded.splitlines(keepends=True)
    replacements = []
    assignments = {
        node.targets[0].id: node.value for node in ast.parse(source).body
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
    }
    for name, path in changes.items():
        value = assignments[name]
        # Preserve the frozen path and the separate Linux assignment.
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id == "_bundled_path":
            value = value.args[1]
        start = sum(map(len, lines[:value.lineno - 1])) + value.col_offset
        end = sum(map(len, lines[:value.end_lineno - 1])) + value.end_col_offset
        replacements.append((start, end, repr(path).encode("utf-8")))
    for start, end, replacement in sorted(replacements, reverse=True):
        encoded = encoded[:start] + replacement + encoded[end:]
    source = encoded.decode("utf-8").replace("\n", "\r\n")
    compile(source, str(settings_path), "exec")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="", delete=False,
            dir=settings_path.parent, prefix=f".{settings_path.name}.", suffix=".tmp",
        ) as stream:
            temporary = Path(stream.name)
            stream.write(source)
        temporary.replace(settings_path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def load_tool_paths(settings_path: Path, names: list[str]) -> dict[str, str]:
    settings = runpy.run_path(str(settings_path))
    paths = {}
    for name in names:
        value = settings[name]
        if name == "PLUGIN_PATH" and value == "":
            paths[name] = ""
            continue
        if not isinstance(value, str) or not value:
            raise ValueError(f"{name} must be a non-empty string")
        if any(character in value for character in '\r\n\t"'):
            raise ValueError(f"{name} contains an unsupported path character")
        paths[name] = os.path.abspath(os.path.expanduser(value))

    normalized = {}
    if "VSEDIT_PATH" in paths:
        normalized["VSEDIT_PATH"] = normalize_vsedit_path(Path(paths["VSEDIT_PATH"]))
    if "MKV_MERGE_PATH" in paths:
        directory = normalize_tool_path(Path(paths["MKV_MERGE_PATH"]), "mkvtoolnix").parent
        for name in MKV_SETTINGS.values():
            if name in paths:
                normalized[name] = directory / Path(paths[name]).name
    for directory in {path.parent for path in normalized.values()}:
        directory.mkdir(parents=True, exist_ok=True)
    changes = {name: str(path) for name, path in normalized.items() if str(path) != paths[name]}
    if changes:
        write_tool_paths(settings_path, changes)
        paths.update(changes)
    return paths


if __name__ == "__main__":
    print(json.dumps(load_tool_paths(Path(sys.argv[1]), sys.argv[2:])))
