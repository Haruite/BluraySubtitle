"""Synchronize repository-managed VapourSynth scripts and their notices."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


SCRIPT_SOURCE = Path(__file__).resolve().parents[1] / "third_party" / "vapoursynth_scripts"


def install_scripts(destination: Path, *, check: bool = False) -> dict[str, int | str]:
    """Copy changed managed files, or report differences without writing in check mode."""
    scripts = sorted(SCRIPT_SOURCE.glob("*.py"), key=lambda path: path.name)
    if not scripts:
        raise FileNotFoundError(f"No VapourSynth scripts found in {SCRIPT_SOURCE}")
    notices = [SCRIPT_SOURCE / "COPYRIGHT.md", SCRIPT_SOURCE / "COPYRIGHT.zh-Hans.md"]
    notices.extend(sorted(
        (path for path in (SCRIPT_SOURCE / "licenses").rglob("*") if path.is_file()),
        key=lambda path: path.relative_to(SCRIPT_SOURCE).as_posix(),
    ))
    sources = scripts + notices
    # Read the complete snapshot before changing an installation.
    contents = [(source, source.read_bytes()) for source in sources]
    fingerprint = hashlib.sha256()
    updated = 0
    for source, content in contents:
        relative = source.relative_to(SCRIPT_SOURCE)
        fingerprint.update(relative.as_posix().encode("utf-8") + b"\0")
        fingerprint.update(hashlib.sha256(content).digest())
        target = destination / relative if source in scripts else (
            destination / "licenses" / "vapoursynth_scripts" / relative
        )
        if target.is_file() and target.read_bytes() == content:
            continue
        updated += 1
        if not check:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
    return {
        "scripts": len(scripts),
        "files": len(sources),
        "updated": updated,
        "sha256": fingerprint.hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    result = install_scripts(arguments.destination, check=arguments.check)
    print(json.dumps(result))
    return int(arguments.check and bool(result["updated"]))


if __name__ == "__main__":
    raise SystemExit(main())
