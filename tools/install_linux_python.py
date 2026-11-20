"""Install uv's latest stable CPython, optionally retaining its distribution for Build replay."""

import json
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
from urllib.parse import unquote, urlsplit


def install(uv: str, mirror: Path | None = None) -> str:
    releases = json.loads(subprocess.check_output([
        uv, "python", "list", "--only-downloads", "--all-versions", "--output-format", "json", "3",
    ]))
    release = max(
        (r for r in releases if r["implementation"] == "cpython" and r["variant"] == "default"
         and re.fullmatch(r"3\.\d+\.\d+", r["version"])),
        key=lambda r: tuple(map(int, r["version"].split("."))),
    )
    version = release["version"]
    command = [uv, "python", "install", version]
    if mirror is None:
        subprocess.run(command, check=True, stdout=sys.stderr)
        return version

    # uv substitutes the mirror root and retains the upstream release tag and filename.
    url = release["url"]
    tag, filename = (unquote(part) for part in urlsplit(url).path.rsplit("/", 2)[-2:])
    if any(Path(part).name != part or part in ("", ".", "..") for part in (tag, filename)):
        raise ValueError(f"Invalid CPython archive URL: {url}")
    archive = mirror / tag / filename
    command.extend(["--mirror", mirror.resolve().as_uri()])
    if archive.is_file() and subprocess.run(command, stdout=sys.stderr).returncode == 0:
        return version

    archive.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=archive.parent) as temporary:
        # Publish the archive only after uv accepts the staging mirror.
        staging = Path(temporary)
        pending = staging / tag / filename
        pending.parent.mkdir()
        subprocess.run(["curl", "-fLsS", "--retry", "4", "-o", pending, url], check=True)
        subprocess.run([*command[:-1], staging.resolve().as_uri()], check=True, stdout=sys.stderr)
        pending.replace(archive)
    return version


if __name__ == "__main__":
    print(install(sys.argv[1], Path(sys.argv[2]) if len(sys.argv) > 2 else None))
