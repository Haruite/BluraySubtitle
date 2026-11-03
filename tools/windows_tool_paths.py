"""Load Windows setup paths and keep VSEdit in its own directory."""

import ast
import json
import os
from pathlib import Path
import runpy
import sys
import tempfile


def normalize_vsedit_path(path: Path) -> Path:
    path = path.expanduser().resolve()
    if path.parent.name.casefold() != "vsedit":
        path = path.parent / "vsedit" / path.name
    return path


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

    editor = normalize_vsedit_path(Path(paths["VSEDIT_PATH"]))
    editor.parent.mkdir(parents=True, exist_ok=True)
    if str(editor) != paths["VSEDIT_PATH"]:
        source = settings_path.read_text(encoding="utf-8")
        assignment = next((
            node for node in ast.parse(source).body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "VSEDIT_PATH" for target in node.targets)
        ), None)
        if assignment is None:
            raise ValueError("Missing top-level VSEDIT_PATH assignment in settings.py")
        value = assignment.value
        # Preserve the frozen path and the separate Linux assignment.
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id == "_bundled_path":
            value = value.args[1]
        encoded = source.encode("utf-8")
        lines = encoded.splitlines(keepends=True)
        start = sum(map(len, lines[:value.lineno - 1])) + value.col_offset
        end = sum(map(len, lines[:value.end_lineno - 1])) + value.end_col_offset
        source = (encoded[:start] + repr(str(editor)).encode("utf-8") + encoded[end:]).decode("utf-8")
        compile(source, str(settings_path), "exec")
        source = source.replace("\r\n", "\n").replace("\n", "\r\n")
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
        paths["VSEDIT_PATH"] = str(editor)
    return paths


if __name__ == "__main__":
    print(json.dumps(load_tool_paths(Path(sys.argv[1]), sys.argv[2:])))
