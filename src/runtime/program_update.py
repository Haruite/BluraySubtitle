"""Locate and install the verified package for the running platform."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

if sys.platform.startswith("linux"):
    from . import ubuntu_update as platform_update

    SERVER_PACKAGE_LABEL = (
        "Server Ubuntu 26.04 ARM64 package" if platform_update.UBUNTU_ARCHITECTURE == "arm64"
        else "Server Ubuntu 26.04 x64 package"
    )
else:
    from . import windows_update as platform_update

    SERVER_PACKAGE_LABEL = (
        "Server Windows ARM64 package" if platform_update.WINDOWS_ARCHITECTURE == "arm64"
        else "Server Windows x64 package"
    )


GITHUB_LATEST_RELEASE_API = "https://api.github.com/repos/Haruite/BluraySubtitle/releases/latest"
SERVER_PACKAGE_METADATA_URL = f"{platform_update.SERVER_PACKAGE_URL}.txt"
DIRECT_UPDATE_REQUIREMENT = (
    "Direct updates require the packaged Ubuntu 26.04 program."
    if sys.platform.startswith("linux")
    else "Direct updates require the packaged Windows program and its bundled 7-Zip."
)


@dataclass(frozen=True)
class UpdatePackage:
    url: str
    sha256: str


def github_update_package(payload: dict[str, object]) -> UpdatePackage | None:
    tag = payload.get("tag_name")
    assets = payload.get("assets")
    if not isinstance(tag, str) or not isinstance(assets, list):
        return None
    archive = platform_update.PACKAGE_ARCHIVE
    for asset in assets:
        if not isinstance(asset, dict) or asset.get("name") != archive:
            continue
        digest = asset.get("digest")
        if isinstance(digest, str) and re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest):
            url = f"https://github.com/Haruite/BluraySubtitle/releases/download/{quote(tag, safe='')}/{archive}"
            return UpdatePackage(url, digest.removeprefix("sha256:").lower())
    return None


def server_update_package(record: str) -> UpdatePackage | None:
    fields = dict(line.split("=", 1) for line in record.splitlines() if "=" in line)
    digest = fields.get("sha256", "").lower()
    if re.fullmatch(r"[0-9a-f]{64}", digest):
        return UpdatePackage(f"{platform_update.SERVER_PACKAGE_URL}?sha256={digest}", digest)
    return None


def update_executable() -> Path | None:
    return platform_update.update_executable()


def start_program_update(package: UpdatePackage) -> None:
    platform_update.start_update(package)
