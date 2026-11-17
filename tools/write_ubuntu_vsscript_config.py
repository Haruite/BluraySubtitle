"""Prepare the packaged player's defaults and VSScript R79 environment."""

import json
import os
from pathlib import Path
import sys
import tempfile


def install_mpv_defaults(support: Path) -> None:
    config = support / "mpv"
    assets = support / "resource/mpv"
    if Path(os.environ["MPV_HOME"]).resolve() != config or not (assets / "scripts/uosc/main.lua").is_file():
        return

    # Users can override scripts and fonts. Relative links keep package assets current after an update.
    paths = [path.relative_to(assets) for path in (assets / "fonts").iterdir() if path.is_file()]
    if not (config / "scripts/uosc.lua").is_file():
        paths.append(Path("scripts/uosc"))
    for relative in paths:
        target = config / relative
        if not target.parent.resolve().is_relative_to(config):
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            target.symlink_to(os.path.relpath(assets / relative, target.parent))
        except FileExistsError:
            pass

    relative = Path("script-opts/context_menu.conf")
    target = config / relative
    if target.exists() or target.is_symlink() or not target.parent.resolve().is_relative_to(config):
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    # Preserve editable menu options across updates, including concurrent first launches.
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as output:
        temporary = Path(output.name)
        try:
            output.write((assets / relative).read_bytes())
            output.close()
            os.link(temporary, target)
        except FileExistsError:
            pass
        finally:
            temporary.unlink(missing_ok=True)


executable = Path(sys.executable).resolve()
vsscript = Path(os.environ["VSSCRIPT_PATH"])
library = vsscript.parent.parent / "libpython3.14.so.1.0"
target = Path(os.environ["XDG_CONFIG_HOME"]) / "vapoursynth/vapoursynth.toml"
fields = [str(executable), str(library), str(int(executable.stat().st_mtime))]
record = f"{json.dumps(str(vsscript), ensure_ascii=False)} = {json.dumps(fields, ensure_ascii=False)}\n"
target.parent.mkdir(parents=True, exist_ok=True)
try:
    current = target.read_text(encoding="utf-8")
except FileNotFoundError:
    current = ""
if current != record:
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=target.parent, delete=False
    ) as output:
        output.write(record)
    source = Path(output.name)
    try:
        source.replace(target)
    finally:
        source.unlink(missing_ok=True)

if sys.argv[1:] == ["mpv"]:
    install_mpv_defaults(vsscript.parent.parent.resolve())
