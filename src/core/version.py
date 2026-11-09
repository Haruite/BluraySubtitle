"""Application version, build commit, and release-version comparison."""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from functools import cache
from pathlib import Path
from typing import Mapping


APP_VERSION = "4.7"
APP_TITLE = f"BluraySubtitle v{APP_VERSION}"
BUILD_COMMIT_FILENAME = "build-commit.txt"

_VERSION_TAG_PATTERN = re.compile(
    r"^[vV]?(\d+(?:\.\d+)*)(?:[-+][0-9A-Za-z.-]+)?$"
)


@dataclass(frozen=True)
class CommitInfo:
    commit_hash: str
    committed_at: datetime


def parse_commit_record(record: str) -> CommitInfo:
    """Read the commit fields shared by the Windows bundle and website."""
    fields = dict(line.split("=", 1) for line in record.splitlines() if "=" in line)
    commit_hash = fields.get("commit", "")
    if re.fullmatch(r"[0-9a-fA-F]{40}", commit_hash) is None:
        raise ValueError("Missing or invalid commit hash")
    timestamp = fields.get("commit_time", "")
    if timestamp.endswith("Z"):
        timestamp = timestamp[:-1] + "+00:00"
    committed_at = datetime.fromisoformat(timestamp)
    if committed_at.utcoffset() is None:
        raise ValueError("Commit time must include a time zone")
    return CommitInfo(commit_hash.lower(), committed_at)


def git_commit_record(project_root: Path) -> str:
    """Read the checked-out commit hash and committer time from Git."""
    return subprocess.run(
        [
            "git", "-C", str(project_root), "show", "--no-patch", "--no-notes",
            "--no-show-signature", "--format=commit=%H%ncommit_time=%cI", "HEAD", "--",
        ],
        capture_output=True,
        check=True,
        encoding="utf-8",
        timeout=5,
    ).stdout


@cache
def current_commit() -> CommitInfo | None:
    """Capture the current build identity when its metadata is available."""
    try:
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            path = Path(sys._MEIPASS) / BUILD_COMMIT_FILENAME
            record = path.read_text(encoding="utf-8")
        else:
            project_root = Path(__file__).resolve().parents[2]
            if not (project_root / ".git").exists():
                return None
            record = git_commit_record(project_root)
        return parse_commit_record(record)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def version_number(value: str) -> tuple[int, ...]:
    """Return the numeric components from a release version or tag."""
    match = _VERSION_TAG_PATTERN.fullmatch(str(value).strip())
    if match is None:
        raise ValueError(f"Invalid release version: {value!r}")
    return tuple(int(part) for part in match.group(1).split("."))


def release_version(payload: Mapping[str, object]) -> str:
    """Return only the numeric version from a GitHub release payload."""
    tag_name = payload.get("tag_name")
    if not isinstance(tag_name, str):
        raise ValueError("GitHub release payload has no tag_name")
    version_number(tag_name)
    match = _VERSION_TAG_PATTERN.fullmatch(tag_name.strip())
    assert match is not None
    return match.group(1)


def is_newer_release(candidate: str, current: str = APP_VERSION) -> bool:
    """Return whether a numeric release version is newer than the application."""
    candidate_parts = version_number(candidate)
    current_parts = version_number(current)
    width = max(len(candidate_parts), len(current_parts))
    candidate_parts += (0,) * (width - len(candidate_parts))
    current_parts += (0,) * (width - len(current_parts))
    return candidate_parts > current_parts


__all__ = [
    "APP_TITLE",
    "APP_VERSION",
    "BUILD_COMMIT_FILENAME",
    "CommitInfo",
    "current_commit",
    "git_commit_record",
    "is_newer_release",
    "parse_commit_record",
    "release_version",
    "version_number",
]
