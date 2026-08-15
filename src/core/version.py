"""Application version and release-version comparison helpers."""

from __future__ import annotations

import re
from typing import Mapping


APP_VERSION = "4.5"
APP_TITLE = f"BluraySubtitle v{APP_VERSION}"

_VERSION_TAG_PATTERN = re.compile(
    r"^[vV]?(\d+(?:\.\d+)*)(?:[-+][0-9A-Za-z.-]+)?$"
)


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
    "is_newer_release",
    "release_version",
    "version_number",
]
