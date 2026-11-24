"""Snapshot macOS build inputs and the components selected by the build plan."""

import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.actions_cache import fingerprint, write_snapshot_key


def main():
    root = Path(os.environ["BLURAY_SETUP_CACHE_DIR"])
    plan = json.loads(Path(os.environ["BLURAY_MACOS_CACHE_PLAN"]).read_bytes())
    completed = json.loads(os.environ.get("COMPLETED_COMPONENTS") or "{}")
    print(f"Completed native components: {len(completed)}/{len(plan['components'])}", flush=True)
    components = root / "components"
    selected = {f"{name}-{key}" for name, key in plan["components"].items()}
    for suffix in (".tar.gz", ".tar.sha256"):
        for path in components.glob(f"*{suffix}"):
            if path.name.removesuffix(suffix) not in selected:
                path.unlink()

    groups = {
        "setup": [(name, root / name, "**/*") for name in
                  ("downloads", "pip", "qt-sdk", "cargo/registry/cache", "cargo/git/db", "uv-cache",
                   "zig-cache/p", "interpreters", "ccache")],
        "conda": [("conda", root / "mamba/pkgs", pattern) for pattern in ("**/*.conda", "**/*.tar.bz2")],
        "components": [("components", components, pattern) for pattern in ("*.tar.gz", "*.tar.sha256")],
    }
    write_snapshot_key({family: digest for family, paths in groups.items() if (digest := fingerprint(tuple(paths)))})


if __name__ == "__main__":
    main()
