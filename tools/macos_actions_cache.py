"""Snapshot macOS setup downloads and retain verified per-component cache generations."""

import argparse
import json
import os
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.actions_cache import ARCHITECTURES, delete_cache, fingerprint, main_cache_entries, superseded_cache_ids


def snapshot(arch):
    root = Path(os.environ["BLURAY_SETUP_CACHE_DIR"])
    groups = {
        "setup": [(name, root / name, "**/*") for name in
                  ("downloads", "pip", "qt-sdk", "cargo/registry/cache", "cargo/git/db", "uv-cache",
                   "zig-cache/p", "interpreters", "ccache")],
        "conda": [("conda", root / "mamba/pkgs", pattern) for pattern in ("**/*.conda", "**/*.tar.bz2")],
    }
    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as out:
        for family, paths in groups.items():
            digest = fingerprint(tuple(paths))
            if digest:
                print(f"{family}=macos-{family}-v2-{arch}-{digest}", file=out)


def prune(arch):
    endpoint, entries = main_cache_entries()
    for family in ("setup", "conda"):
        restored = os.environ.get("RESTORED_" + family.upper(), "")
        pattern = rf"macos-{family}-v2-{arch}-[0-9a-f]{{64}}"
        for cache_id in superseded_cache_ids(entries, pattern, None, restored):
            delete_cache(endpoint, cache_id)
    for name, restored in json.loads(os.environ.get("RESTORED_COMPONENTS") or "{}").items():
        if not re.fullmatch(r"[a-z0-9._-]+", name):
            raise ValueError(f"Invalid component name: {name}")
        pattern = rf"bluraysubtitle-macos-v2-{arch}-{re.escape(name)}-[0-9a-f]{{64}}-[0-9a-f]{{64}}"
        for cache_id in superseded_cache_ids(entries, pattern, None, restored):
            delete_cache(endpoint, cache_id)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("snapshot", "prune"))
    parser.add_argument("architecture", choices=ARCHITECTURES)
    args = parser.parse_args()
    (snapshot if args.action == "snapshot" else prune)(args.architecture)
