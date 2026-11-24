"""Shared GitHub Actions snapshot fingerprints and retention."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


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


def write_snapshot_key(checksums: dict[str, str]) -> None:
    if not checksums:
        return
    digest = hashlib.sha256(json.dumps(checksums, sort_keys=True).encode("utf-8")).hexdigest()
    content_prefix = f"{os.environ['PACKAGE_CACHE_PREFIX']}{digest}-"
    restored = os.environ.get("RESTORED_CACHE_KEY", "")
    # Cache keys are immutable. Allocate a new generation when the payload changes.
    key = (restored if restored.startswith(content_prefix)
           else f"{content_prefix}{os.environ['GITHUB_RUN_ID']}-{os.environ['GITHUB_RUN_ATTEMPT']}")
    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as stream:
        print(f"key={key}", file=stream)


def superseded_snapshot_ids(entries: list[dict], prefix: str, retained: str, legacy: tuple[str, ...] = ()) -> list[int]:
    if not prefix or not retained.startswith(prefix) or retained == prefix:
        return []
    main = [entry for entry in entries if entry["ref"] == MAIN]
    keeper = max(
        (entry for entry in main if entry["key"] == retained and entry["size_in_bytes"] > 0),
        key=lambda entry: (entry["created_at"], entry["id"]), default=None,
    )
    if keeper is None:
        return []
    # Keep newer snapshots if this run restored a superseded key.
    cutoff = keeper["created_at"], keeper["id"]
    return [
        entry["id"] for entry in main
        if entry["id"] != keeper["id"] and (
            entry["key"].startswith(legacy)
            or (entry["key"].startswith(prefix) and (entry["created_at"], entry["id"]) < cutoff)
        )
    ]


def main_cache_entries() -> tuple[str, list[dict]]:
    if os.environ["GITHUB_REF"] != MAIN:
        raise ValueError("Cache pruning requires the main branch")
    endpoint = f"repos/{os.environ['GITHUB_REPOSITORY']}/actions/caches"
    pages = json.loads(subprocess.check_output(
        ["gh", "api", "--paginate", "--slurp", f"{endpoint}?ref=refs%2Fheads%2Fmain&per_page=100"], text=True,
    ))
    return endpoint, [entry for page in pages for entry in page["actions_caches"]]


def delete_cache(endpoint: str, cache_id: int) -> None:
    result = subprocess.run(
        ["gh", "api", "--method", "DELETE", f"{endpoint}/{cache_id}"],
        stderr=subprocess.PIPE, encoding="utf-8", errors="replace",
    )
    if result.returncode and result.stderr.rstrip().endswith("(HTTP 404)"):
        return  # A parallel build may already have removed the shared legacy cache.
    sys.stderr.write(result.stderr)
    result.check_returncode()
    print(f"Removed superseded cache {cache_id}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prefix")
    parser.add_argument("retained")
    parser.add_argument("legacy", nargs="*")
    args = parser.parse_args()
    if args.retained:
        endpoint, entries = main_cache_entries()
        for cache_id in superseded_snapshot_ids(entries, args.prefix, args.retained, tuple(args.legacy)):
            delete_cache(endpoint, cache_id)
