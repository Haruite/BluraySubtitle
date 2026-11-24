"""Locate and install the verified package for the running platform."""

from __future__ import annotations

import platform
import re
import sys
import sysconfig
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from src.core.i18n import translate_text


platform_update = None
SERVER_PACKAGE_LABEL = ""
PACKAGE_ARCHIVE = ""
SERVER_PACKAGE_URL = ""
DIRECT_UPDATE_REQUIREMENT = "Direct updates require a supported packaged edition."
if sys.platform.startswith("linux") and platform.machine().lower() in {"x86_64", "amd64", "aarch64", "arm64"}:
    from . import portable_update as platform_update

    SERVER_PACKAGE_LABEL = (
        "Server Linux ARM64 package" if platform_update.LINUX_ARCHITECTURE == "arm64"
        else "Server Linux x64 package"
    )
    DIRECT_UPDATE_REQUIREMENT = platform_update.DIRECT_UPDATE_REQUIREMENT
elif sys.platform == "darwin" and platform.machine() in ("arm64", "x86_64"):
    from . import macos_update as platform_update

    SERVER_PACKAGE_LABEL = ("Server macOS Apple silicon package" if platform_update.MACOS_ARCHITECTURE == "arm64"
                            else "Server macOS Intel package")
    DIRECT_UPDATE_REQUIREMENT = "Direct updates require the packaged macOS application."
elif sys.platform.startswith("freebsd") and platform.machine().lower() in {"amd64", "x86_64"}:
    from . import portable_update as platform_update

    SERVER_PACKAGE_LABEL = "Server FreeBSD x64 package"
    DIRECT_UPDATE_REQUIREMENT = platform_update.DIRECT_UPDATE_REQUIREMENT
elif (sys.platform == "win32" and sysconfig.get_platform() in {"win-amd64", "win-arm64"}
      and not (getattr(sys, "frozen", False)
               and (Path(sys._MEIPASS) / "compatibility-components.json").is_file())):
    from . import windows_update as platform_update

    SERVER_PACKAGE_LABEL = (
        "Server Windows ARM64 package" if platform_update.WINDOWS_ARCHITECTURE == "arm64"
        else "Server Windows x64 package"
    )
    DIRECT_UPDATE_REQUIREMENT = "Direct updates require the packaged Windows program and its bundled 7-Zip."


GITHUB_LATEST_RELEASE_API = "https://api.github.com/repos/Haruite/BluraySubtitle/releases/latest"
if platform_update:
    PACKAGE_ARCHIVE = platform_update.PACKAGE_ARCHIVE
    SERVER_PACKAGE_URL = platform_update.SERVER_PACKAGE_URL
SERVER_PACKAGE_METADATA_URL = f"{SERVER_PACKAGE_URL}.txt" if SERVER_PACKAGE_URL else ""


@dataclass(frozen=True)
class UpdatePackage:
    url: str
    sha256: str


def github_update_package(payload: dict[str, object]) -> UpdatePackage | None:
    if not PACKAGE_ARCHIVE:
        return None
    tag = payload.get("tag_name")
    assets = payload.get("assets")
    if not isinstance(tag, str) or not isinstance(assets, list):
        return None
    for asset in assets:
        if not isinstance(asset, dict) or asset.get("name") != PACKAGE_ARCHIVE:
            continue
        digest = asset.get("digest")
        if isinstance(digest, str) and re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest):
            url = f"https://github.com/Haruite/BluraySubtitle/releases/download/{quote(tag, safe='')}/{PACKAGE_ARCHIVE}"
            return UpdatePackage(url, digest.removeprefix("sha256:").lower())
    return None


def server_update_package(record: str) -> UpdatePackage | None:
    if not SERVER_PACKAGE_URL:
        return None
    fields = dict(line.split("=", 1) for line in record.splitlines() if "=" in line)
    digest = fields.get("sha256", "").lower()
    if re.fullmatch(r"[0-9a-f]{64}", digest):
        return UpdatePackage(f"{SERVER_PACKAGE_URL}?sha256={digest}", digest)
    return None


def update_executable() -> Path | None:
    return platform_update.update_executable() if platform_update else None


def start_program_update(package: UpdatePackage) -> None:
    if platform_update is None:
        raise RuntimeError(translate_text(DIRECT_UPDATE_REQUIREMENT))
    platform_update.start_update(package)
