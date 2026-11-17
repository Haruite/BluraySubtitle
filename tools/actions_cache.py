"""Shared GitHub Actions snapshot fingerprints and retention."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess


ARCHITECTURES = ("X64", "ARM64")
MAIN = "refs/heads/main"


def fingerprint(groups: tuple[tuple[str, Path, str], ...], required: dict[str, str] | None = None) -> str:
    digest = hashlib.sha256()
    seen = False
    remaining = dict(required or {})
    for name, directory, pattern in groups:
        for path in sorted(directory.glob(pattern)):
            relative = path.relative_to(directory)
            if name == "ccache" and (
                relative.parts[0] == "tmp" or path.name in {"stats", "stats.lock", "cleanup.timestamp"}
            ):
                continue
            if name == "pip" and "http-v2" in relative.parts and path.suffix != ".body":
                # CacheControl refreshes HTTP headers when the response body is unchanged.
                continue
            if path.name.startswith(".partial."):
                continue
            if path.is_symlink():
                content = os.fsencode(os.readlink(path))
                kind = b"link"
            elif path.is_file():
                with path.open("rb") as stream:
                    content = hashlib.file_digest(stream, "sha256").digest()
                kind = f"file-{path.stat().st_mode & 0o111:o}".encode()
            else:
                continue
            entry = f"{name}/{relative.as_posix()}"
            if entry in remaining and (path.is_symlink() or remaining.pop(entry) != content.hex()):
                raise ValueError(f"Invalid cached APT file {path.name}")
            digest.update(kind + b"\0" + os.fsencode(entry) + b"\0" + len(content).to_bytes(8, "big") + content)
            seen = True
    if remaining:
        raise ValueError("Cached APT manifest references missing packages")
    return digest.hexdigest() if seen else ""


def superseded_cache_ids(entries: list[dict], pattern: str, legacy_pattern: str | None, restored: str) -> list[int]:
    current = sorted(
        (entry for entry in entries if entry["ref"] == MAIN and re.fullmatch(pattern, entry["key"])),
        key=lambda entry: (entry["created_at"], entry["id"]), reverse=True,
    )
    restored_index = next((
        index for index, entry in enumerate(current)
        if entry["key"] == restored and entry["size_in_bytes"] > 0
    ), None)
    if restored_index is None:
        return []

    # Protect the restored archive and any newer upload pending verification.
    # When the newest archive was restored, keep one older archive as a fallback.
    older = current[restored_index + 1:]
    legacy = sorted(
        (entry for entry in entries if entry["ref"] == MAIN and legacy_pattern and re.fullmatch(legacy_pattern, entry["key"])),
        key=lambda entry: (entry["created_at"], entry["id"]), reverse=True,
    )
    return [entry["id"] for entry in (older + legacy)[int(restored_index == 0):]]


def main_cache_entries() -> tuple[str, list[dict]]:
    if os.environ["GITHUB_REF"] != MAIN:
        raise ValueError("Cache pruning requires the main branch")
    endpoint = f"repos/{os.environ['GITHUB_REPOSITORY']}/actions/caches"
    pages = json.loads(subprocess.check_output(
        ["gh", "api", "--paginate", "--slurp", f"{endpoint}?ref=refs%2Fheads%2Fmain&per_page=100"], text=True,
    ))
    return endpoint, [entry for page in pages for entry in page["actions_caches"]]


def delete_cache(endpoint: str, cache_id: int) -> None:
    subprocess.run(["gh", "api", "--method", "DELETE", f"{endpoint}/{cache_id}"], check=True)
