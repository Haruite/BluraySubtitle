"""Fingerprint Windows build snapshots and keep two per architecture and family."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from zipfile import BadZipFile, ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.actions_cache import ARCHITECTURES, delete_cache, fingerprint, main_cache_entries, superseded_cache_ids
from tools.windows_build_cache import read_manifest


NAMESPACES = {"pip": (2, 1), "tools": (4, 3)}


def tool_fingerprint(directory: Path) -> str:
    entries = []
    for archive in sorted(directory.glob("*.zip")):
        with ZipFile(archive) as bundle:
            manifest = read_manifest(bundle)
            for name, checksum in manifest["files"].items():
                with bundle.open(name) as stream:
                    if hashlib.file_digest(stream, "sha256").hexdigest() != checksum:
                        raise ValueError(f"Invalid cached file {archive.name}/{name}")
            entries.append((archive.name, manifest["fingerprint"], manifest["files"]))
    return hashlib.sha256(json.dumps(entries, sort_keys=True).encode("utf-8")).hexdigest() if entries else ""


def snapshot_keys(pip: Path, tools: Path, architecture: str) -> dict[str, str]:
    checksums = {}
    for family, compute in (
        ("pip", lambda: fingerprint((("pip", pip, "**/*"),))),
        ("tools", lambda: tool_fingerprint(tools)),
    ):
        try:
            checksums[family] = compute()
        except (BadZipFile, KeyError, OSError, TypeError, ValueError) as error:
            print(f"::warning::Cannot fingerprint Windows {family} cache: {error}", file=sys.stderr)
    return {
        family: f"windows-{family}-v{NAMESPACES[family][0]}-{architecture}-{checksum}"
        for family, checksum in checksums.items() if checksum
    }


def outdated_cache_ids(entries: list[dict], architecture: str, restored: dict[str, str]) -> list[int]:
    expired = []
    for family, (current, legacy) in NAMESPACES.items():
        pattern = rf"windows-{family}-v{current}-{architecture}-[0-9a-f]{{64}}"
        legacy_pattern = rf"windows-{family}-v{legacy}-{architecture}-[0-9a-f]{{64}}"
        expired.extend(superseded_cache_ids(entries, pattern, legacy_pattern, restored.get(family, "")))
    return expired


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("snapshot", "prune"))
    parser.add_argument("architecture", choices=ARCHITECTURES)
    args = parser.parse_args()
    if args.operation == "snapshot":
        temp = Path(os.environ["RUNNER_TEMP"])
        tools = temp / "bluraysubtitle-builds/artifacts"
        if args.architecture == "ARM64":
            tools /= "arm64"
        (tools / "vapoursynth-components.zip").unlink(missing_ok=True)
        keys = snapshot_keys(temp / "bluraysubtitle-pip", tools, args.architecture)
        with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as stream:
            stream.writelines(f"{family}={key}\n" for family, key in keys.items())
        return

    restored = {family: os.environ[f"RESTORED_{family.upper()}_CACHE"] for family in NAMESPACES}
    endpoint, entries = main_cache_entries()
    for cache_id in outdated_cache_ids(entries, args.architecture, restored):
        delete_cache(endpoint, cache_id)
        print(f"Removed old Windows {args.architecture} cache {cache_id}")


if __name__ == "__main__":
    try:
        main()
    except (KeyError, OSError, ValueError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))
