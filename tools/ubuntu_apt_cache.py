"""Replay the APT packages used to assemble the Ubuntu package."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

STATUS = Path("/var/lib/dpkg/status")
# Packaging commands and the pkg-config probes used for the artifact keys.
PACKAGING_PACKAGES = {
    "binutils", "gcc", "libc6-dev", "libass-dev", "libavcodec-dev", "libavformat-dev",
    "libavutil-dev", "libswscale-dev", "python3-pip", "python3-pyqt6", "qt6-base-dev-tools",
    "xz-utils",
}


def package_fields(paragraph):
    return {
        name: value.lstrip()
        for line in paragraph.splitlines() if line and not line[0].isspace()
        for name, _, value in (line.partition(":"),)
    }


def status_records():
    records = {}
    for paragraph in STATUS.read_text(encoding="utf-8").strip().split("\n\n"):
        fields = package_fields(paragraph)
        records[fields["Package"], fields["Architecture"]] = (fields, paragraph)
    return records


def package_owners(paths: list[str]) -> set[str]:
    candidates = set()
    for name in paths:
        if not name:
            continue
        for path in (name, str(Path(name).resolve())):
            if path.startswith(("/usr/bin/", "/usr/lib/", "/bin/", "/lib/")):
                candidates.add(path)
                if path.startswith(("/usr/lib/", "/usr/bin/")):
                    candidates.add(path[4:])
    if not candidates:
        return set()
    result = subprocess.run(
        ["dpkg-query", "-S", "--", *sorted(candidates)], capture_output=True, text=True,
        env={**os.environ, "LC_ALL": "C"},
    )
    if result.returncode not in (0, 1):
        result.check_returncode()
    return {
        name for line in result.stdout.splitlines()
        for owner, _, path in (line.rpartition(": "),) if path in candidates
        for name in owner.split(", ")
    }


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def deb_record(path):
    paragraph = subprocess.check_output(["dpkg-deb", "-f", path], text=True).rstrip()
    return package_fields(paragraph), paragraph


def save(downloads, cache, used_paths):
    owners = package_owners(used_paths.read_text(encoding="utf-8").splitlines())
    native = subprocess.check_output(["dpkg", "--print-architecture"], text=True).strip()
    required = {
        (name, architecture): fields["Version"]
        for (name, architecture), (fields, _) in status_records().items()
        if fields.get("Status", "").endswith(" ok installed")
        and (name in owners or f"{name}:{architecture}" in owners
             or (name in PACKAGING_PACKAGES and architecture in (native, "all")))
    }
    if not required:
        raise ValueError("No APT dependencies were recorded for packaging")
    names = {name for name, _ in required}
    archives = {}
    for archive in sorted(downloads.glob("*.deb")):
        if archive.name.split("_", 1)[0] not in names:
            continue
        fields, _ = deb_record(archive)
        package = fields["Package"], fields["Architecture"]
        if required.get(package) == fields["Version"]:
            archives[package] = [archive.name, digest(archive)]
    cache.mkdir(parents=True, exist_ok=True)
    record = [
        [name, architecture, version, archives.get((name, architecture))]
        for (name, architecture), version in sorted(required.items())
    ]
    staged = cache / "packages.json.part"
    staged.write_text(json.dumps(record) + "\n", encoding="utf-8")
    staged.replace(cache / "packages.json")


def restore(downloads, cache, state):
    records = status_records()
    package_list = json.loads((cache / "packages.json").read_text(encoding="utf-8"))
    if not package_list:
        raise ValueError("No cached APT dependencies for packaging")
    archives = []
    for name, architecture, version, source in package_list:
        package = name, architecture
        fields, _ = records.get(package, ({}, ""))
        if fields.get("Status", "").endswith(" ok installed"):
            if fields["Version"] != version:
                raise ValueError(f"Cached packaging requires {name}:{architecture} {version}, found {fields['Version']}")
            continue
        if source is None:
            raise ValueError(f"No cached APT archive for {name}:{architecture} {version}")
        filename, checksum = source
        archive = downloads / filename
        if Path(filename).name != filename or archive.suffix != ".deb" or digest(archive) != checksum:
            raise ValueError(f"Invalid cached APT download: {filename}")
        control, paragraph = deb_record(archive)
        if (control["Package"], control["Architecture"], control["Version"]) != (name, architecture, version):
            raise ValueError(f"Cached APT archive has unexpected package metadata: {filename}")
        archives.append(archive)
        records[package] = (control, paragraph + "\nStatus: install ok installed")

    # Preserve the runner's real package state and add only the extracted packages to the query database.
    for archive in archives:
        subprocess.run(["sudo", "dpkg-deb", "--extract", archive, "/"], check=True)
    if archives:
        subprocess.run(["sudo", "ldconfig"], check=True)
    (state / "status").write_text("\n\n".join(record for _, record in records.values()) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("save", "restore"))
    parser.add_argument("cache", type=Path)
    parser.add_argument("paths_or_state", type=Path)
    args = parser.parse_args()
    try:
        operation = save if args.operation == "save" else restore
        operation(args.cache / "apt", args.cache / "apt-runtime", args.paths_or_state)
    except (KeyError, OSError, TypeError, ValueError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))


if __name__ == "__main__":
    main()
