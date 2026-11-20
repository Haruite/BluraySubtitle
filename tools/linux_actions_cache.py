"""Fingerprint verified Ubuntu build snapshots and keep two per cache family."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.actions_cache import ARCHITECTURES, MAIN, delete_cache, fingerprint, main_cache_entries, superseded_cache_ids


NAMESPACES = {
    "setup": ("setup-v2", r"setup-v1-{arch}-[0-9]+-[0-9]+"),
    "tools": ("tools-v3", r"tools-v2-{arch}-[0-9a-f]{64}"),
    "apt": ("apt-runtime-v3", r"apt-runtime-v2-{arch}-[0-9a-f]{64}"),
}


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


def snapshot_keys(cache: Path, home: Path, architecture: str) -> dict[str, str]:
    checksums = {
        "setup": fingerprint((
            *((name, cache / name, "**/*") for name in ("downloads", "pip", "ccache", "cargo")),
            ("cargo-registry", home / ".cargo/registry/cache", "**/*"),
            ("cargo-git", home / ".cargo/git/db", "**/*"),
        )),
        "tools": fingerprint((("components", cache / "builds/components", "*.tar.xz"),)),
    }
    try:
        checksums["apt"] = apt_fingerprint(cache)
    except (ValueError, OSError) as error:
        print(f"::warning::Cannot save Ubuntu APT cache: {error}", file=sys.stderr)
    return {
        family: f"ubuntu2604-{NAMESPACES[family][0]}-{architecture}-{checksum}"
        for family, checksum in checksums.items() if checksum
    }


def outdated_cache_ids(entries: list[dict], architecture: str, restored: dict[str, str]) -> list[int]:
    main = [entry for entry in entries if entry["ref"] == MAIN]
    # The previous APT manifest needs the downloads from the old setup cache.
    # Keep that pair available until the new cache layout has been used.
    migrated_apt = any(
        entry["key"] == restored.get("apt") and entry["size_in_bytes"] > 0
        and re.fullmatch(rf"ubuntu2604-apt-runtime-v3-{architecture}-[0-9a-f]{{64}}", entry["key"])
        for entry in main
    )
    expired = []
    for family, (namespace, legacy_pattern) in NAMESPACES.items():
        pattern = rf"ubuntu2604-{namespace}-{architecture}-[0-9a-f]{{64}}"
        legacy_regex = "ubuntu2604-" + legacy_pattern.replace("{arch}", architecture)
        if family in ("setup", "apt") and not migrated_apt:
            legacy_regex = None
        expired.extend(superseded_cache_ids(main, pattern, legacy_regex, restored.get(family, "")))
    return expired


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("snapshot", "prune"))
    parser.add_argument("architecture", choices=ARCHITECTURES)
    args = parser.parse_args()
    if args.operation == "snapshot":
        keys = snapshot_keys(Path(os.environ["BLURAY_SETUP_CACHE_DIR"]), Path.home(), args.architecture)
        with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as stream:
            stream.writelines(f"{family}={key}\n" for family, key in keys.items())
        return

    restored = {family: os.environ[f"RESTORED_{family.upper()}_CACHE"] for family in NAMESPACES}
    endpoint, entries = main_cache_entries()
    for cache_id in outdated_cache_ids(entries, args.architecture, restored):
        delete_cache(endpoint, cache_id)
        print(f"Removed old Ubuntu {args.architecture} cache {cache_id}")


if __name__ == "__main__":
    try:
        main()
    except (KeyError, OSError, ValueError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))
