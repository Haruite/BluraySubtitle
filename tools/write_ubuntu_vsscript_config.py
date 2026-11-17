"""Prepare the packaged player's defaults and VSScript R79 environment."""

from fcntl import LOCK_EX, flock
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

    # Relative links keep package defaults current after an update while allowing user overrides.
    patterns = ("fonts/*", "scripts/*.lua", "bluray-modules/*.lua", "bluray-vs/*", "mpv-lazy/**/*")
    links = {
        path.relative_to(assets): path for pattern in patterns for path in assets.glob(pattern) if path.is_file()
    }
    links[Path("menu.conf")] = assets / "menu.en.conf"
    if not (config / "scripts/uosc.lua").is_file():
        links[Path("scripts/uosc")] = assets / "scripts/uosc"
    for relative, source in links.items():
        target = config / relative
        if not target.parent.resolve().is_relative_to(config):
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            target.symlink_to(os.path.relpath(source, target.parent))
        except FileExistsError:
            pass

    # Preserve editable settings across updates, including concurrent first launches.
    for relative in ("script-opts/context_menu.conf", "bluray-defaults.conf"):
        target = config / relative
        if target.exists() or target.is_symlink() or not target.parent.resolve().is_relative_to(config):
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
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

    main = config / "mpv.conf"
    if main.is_symlink():
        return
    with main.open("a+b") as stream:
        flock(stream, LOCK_EX)
        stream.seek(0)
        original = stream.read()
        includes = {
            value.partition(b"#")[0].strip().strip(b"\"'").replace(b"~~/", b"~~home/", 1)
            for key, _, value in (line.partition(b"=") for line in original.splitlines())
            if key.strip() == b"include"
        }
        missing = [line for line in (assets / "mpv.conf").read_bytes().splitlines()
                   if line.partition(b"=")[2] not in includes]
        if missing:
            section = b"\n\n[default]\n" if original else b""
            stream.write(section + b"\n".join(missing) + b"\n")


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
