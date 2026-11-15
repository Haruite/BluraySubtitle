"""Update the VSScript R79 record after the bundle is unpacked or moved."""

import json
import os
from pathlib import Path
import sys
import tempfile


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
