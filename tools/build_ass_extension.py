"""Build the ASS extension with the interpreter that will load it."""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOURCES = tuple(ROOT / "src/domain/subtitles" / name for name in ("ass_native.c", "ass2sup_native.c"))
MODULE = "_bluraysubtitle_ass"
VERIFY_ASS_EXTENSION = r"""
from _bluraysubtitle_ass import encode_pgs_rle, index_pgs_alpha, parse_events, render_events, scan_duration
from datetime import timedelta

header = b"[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
row = "Dialogue: 0,0:00:00.01,0:00:01.23,Default,,0,0,0,,Text, with commas\n"
assert scan_duration(header + row.encode()) == 1.23
columns = ("Format", "Layer", "Start", "End", "Style", "Name", "MarginL", "MarginR", "MarginV", "Effect", "Text")

class Event:
    pass

events = []
pending, _, _ = parse_events(iter([row]), columns, 2, 3, events, Event, 8)
assert pending is None and events[0].End == timedelta(seconds=1.23)
assert render_events(events, columns, (False, False, True, True) + (False,) * 7, set(), 0, 1) == row
indexes, opacity = index_pgs_alpha(bytes([0, 1]), bytes([255, 255, 255, 0, 0, 0, 0, 255]))
assert opacity[2] == 255 and encode_pgs_rle(indexes, 2, 1) == bytes([0, 1, 2, 0, 0])
"""


def build_ass_extension(destination: Path) -> Path:
    from setuptools import Distribution, Extension

    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".ass-extension-", dir=destination) as directory:
        work = Path(directory)
        # Relative source and object paths avoid duplicating the checkout path under MSVC's build directory.
        for source in SOURCES:
            shutil.copyfile(source, work / source.name)
        previous_directory = Path.cwd()
        try:
            os.chdir(work)
            distribution = Distribution({
                "name": "BluraySubtitle",
                "ext_modules": [Extension(MODULE, [source.name for source in SOURCES])],
            })
            command = distribution.get_command_obj("build_ext")
            command.build_lib = "."
            command.build_temp = "obj"
            command.ensure_finalized()
            command.run()
            module = work / command.get_ext_fullpath(MODULE)
        finally:
            os.chdir(previous_directory)
        subprocess.run(
            [sys.executable, "-I", "-B", "-c",
             "import sys; sys.path.insert(0, sys.argv[1])\n" + VERIFY_ASS_EXTENSION, str(work)],
            check=True,
        )
        target = destination / module.name
        os.replace(module, target)
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT)
    print(build_ass_extension(parser.parse_args().output))
