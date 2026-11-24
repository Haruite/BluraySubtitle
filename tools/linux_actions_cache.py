"""Fingerprint the combined Ubuntu build cache."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.actions_cache import fingerprint, write_snapshot_key


def apt_fingerprint(cache: Path) -> str:
    manifest = cache / "apt-runtime/packages.json"
    if not manifest.is_file():
        return ""
    packages = json.loads(manifest.read_bytes())
    required = {}
    for _, _, _, source in packages:
        if source is None:
            continue
        filename, checksum = source
        if Path(filename).name != filename or not filename.endswith(".deb"):
            raise ValueError(f"Invalid package in the cached APT manifest: {filename}")
        required[f"archives/{filename}"] = checksum
    if not packages:
        return ""
    return fingerprint((
        ("manifest", manifest.parent, manifest.name),
        ("archives", cache / "apt", "*.deb"),
    ), required)


def snapshot_checksums(cache: Path, home: Path) -> dict[str, str]:
    checksums = {
        "setup": fingerprint((
            *((name, cache / name, "**/*") for name in ("downloads", "pip", "ccache", "cargo")),
            ("cargo-registry", home / ".cargo/registry/cache", "**/*"),
            ("cargo-git", home / ".cargo/git/db", "**/*"),
        )),
        "tools": fingerprint((("components", cache / "builds/components", "*.tar.xz"),)),
    }
    checksums["apt"] = apt_fingerprint(cache)
    return {name: digest for name, digest in checksums.items() if digest}


def main() -> None:
    checksums = snapshot_checksums(Path(os.environ["BLURAY_SETUP_CACHE_DIR"]), Path.home())
    if "tools" not in checksums or "apt" not in checksums:
        raise ValueError("The Ubuntu cache needs verified tool archives and an APT manifest")
    write_snapshot_key(checksums)


if __name__ == "__main__":
    try:
        main()
    except (KeyError, OSError, ValueError) as error:
        sys.exit(str(error))
