"""Prepare, fingerprint, and prune Windows build snapshots."""

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
from tools.actions_cache import (
    ARCHITECTURES, MAIN, delete_cache, fingerprint, main_cache_entries, superseded_snapshot_ids, write_snapshot_key,
)
from tools.windows_build_cache import read_manifest
from tools.windows_native_tools import WIN7_SHARED_PLUGINS


def split_x64_artifacts(tools: Path) -> None:
    standard = tools / "standard"
    for archive in tools.glob("*.zip"):
        name = archive.stem
        if name.startswith("vs-dll-"):
            # Dependency ZIPs have hashed names. The Vulkan loader belongs with the standard-only vs-placebo plugin.
            try:
                with ZipFile(archive) as bundle:
                    standard_only = any(member.casefold() == "vulkan-1.dll" for member in bundle.namelist())
            except (BadZipFile, OSError):
                continue  # Leave unreadable archives to the existing cache verification.
        else:
            standard_only = (
                name in {"mkvtoolnix", "mkvtoolnix-qtcore", "vsedit", "dovi-tool", "hdr10plus-tool"}
                or name.startswith(("vs-classic-", "vapoursynth"))
                or (name.startswith("vs-r79-") and name.removeprefix("vs-r79-") not in WIN7_SHARED_PLUGINS)
            )
        if standard_only:
            standard.mkdir(exist_ok=True)
            archive.replace(standard / archive.name)


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


def compatibility_fingerprint(work: Path) -> str:
    artifacts = tool_fingerprint(work / "cache")
    downloads = fingerprint((
        ("downloads", work / "downloads", "**/*"),
        ("crates", work / "rust-cargo/registry/cache", "**/*"),
        ("crate-index", work / "rust-cargo/registry/index", "**/*"),
    ))
    return hashlib.sha256(f"{artifacts}/{downloads}".encode("ascii")).hexdigest() if artifacts or downloads else ""


def snapshot_checksums(pip: Path, tools: Path, architecture: str, *, compatibility: Path | None = None) -> dict[str, str]:
    families = [("shared" if architecture == "X64" else "tools", lambda: tool_fingerprint(tools))]
    if compatibility is None:
        families.append(("pip", lambda: fingerprint((("pip", pip, "**/*"),))))
        if architecture == "X64":
            families.append(("standard", lambda: tool_fingerprint(tools / "standard")))
    else:
        families.append(("compat", lambda: compatibility_fingerprint(compatibility)))
    return {family: checksum for family, compute in families if (checksum := compute())}


def legacy_cache_prefixes(entries: list[dict], architecture: str, compatibility: bool) -> tuple[str, ...]:
    if compatibility:
        families = ["compat-v1"]
    else:
        families = ["pip-v1", "pip-v2", "tools-v3", "tools-v4"]
        if architecture == "X64":
            families.append("standard-v1")
    if architecture == "X64":
        other_variant = "standard" if compatibility else "compat"
        other_prefix = f"windows-build-v1-x64-{other_variant}-"
        if any(entry["ref"] == MAIN and entry["size_in_bytes"] > 0 and entry["key"].startswith(other_prefix)
               for entry in entries):
            # Both x64 builds must finish migrating before removing their common input.
            families.append("shared-v1")
    return tuple(f"windows-{family}-{architecture}-" for family in families)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("prepare", "snapshot", "prune"))
    parser.add_argument("architecture", choices=ARCHITECTURES)
    parser.add_argument("--compatibility", action="store_true")
    args = parser.parse_args()
    if args.operation != "prune":
        temp = Path(os.environ["RUNNER_TEMP"])
        tools = temp / "bluraysubtitle-builds/artifacts"
        if args.architecture == "ARM64":
            tools /= "arm64"
        (tools / "vapoursynth-components.zip").unlink(missing_ok=True)
        compatibility = temp / "bluraysubtitle-compat" if args.compatibility else None
        if args.architecture == "X64":
            split_x64_artifacts(tools)
        if args.operation == "prepare" and args.architecture == "X64" and not args.compatibility:
            # Build helpers read their per-component archives from the same directory on every platform.
            for archive in (tools / "standard").glob("*.zip"):
                archive.replace(tools / archive.name)
        if args.operation == "snapshot":
            write_snapshot_key(snapshot_checksums(
                temp / "bluraysubtitle-pip", tools, args.architecture, compatibility=compatibility,
            ))
        return

    endpoint, entries = main_cache_entries()
    legacy = legacy_cache_prefixes(entries, args.architecture, args.compatibility)
    for cache_id in superseded_snapshot_ids(
        entries, os.environ["PACKAGE_CACHE_PREFIX"], os.environ["SAVED_CACHE"], legacy,
    ):
        delete_cache(endpoint, cache_id)


if __name__ == "__main__":
    try:
        main()
    except (BadZipFile, KeyError, OSError, TypeError, ValueError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))
