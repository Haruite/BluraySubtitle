"""Replay the added APT package files for an Ubuntu Actions build."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys


STATUS = Path("/var/lib/dpkg/status")


def installed_packages():
    output = subprocess.check_output(
        ["dpkg-query", "-W", "-f=${Package}\t${Version}\t${Architecture}\t${db:Status-Status}\n"],
        text=True,
    )
    return {(name, architecture): version for name, version, architecture, state in
            (line.split("\t") for line in output.splitlines()) if state == "installed"}


def encode_packages(packages):
    return [[name, architecture, version] for (name, architecture), version in sorted(packages.items())]


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(initial, downloads, cache):
    before = {(name, architecture): version for name, architecture, version in
              json.loads(initial.read_text(encoding="utf-8"))}
    current = installed_packages()
    if any(current.get(package) != version for package, version in before.items()):
        raise ValueError("APT changed packages already present in the runner image")
    additions = current.keys() - before.keys()
    wanted = {name for name, _ in additions}
    archives = {}
    for archive in sorted(downloads.glob("*.deb")):
        if archive.name.split("_", 1)[0] not in wanted:
            continue
        information = subprocess.check_output(["dpkg-deb", "-f", archive, "Package", "Architecture", "Version"], text=True)
        fields = dict(line.split(": ", 1) for line in information.splitlines())
        package = fields["Package"], fields["Architecture"]
        if package in additions and fields["Version"] == current[package]:
            archives[package] = [archive.name, digest(archive)]
    if missing := sorted(additions - archives.keys()):
        raise ValueError("APT downloads are missing for " + ", ".join(name for name, _ in missing))
    cache.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(STATUS, cache / "status")
    record = {
        "base": encode_packages(before),
        "packages": [archives[package] for package in sorted(archives)],
        "status": digest(cache / "status"),
        "components": sorted(path.name for path in (downloads.parent / "builds/components").glob("*.tar.xz")),
    }
    staged = cache / "packages.json.part"
    staged.write_text(json.dumps(record, sort_keys=True) + "\n", encoding="utf-8")
    staged.replace(cache / "packages.json")


def restore(downloads, cache):
    manifest_file = cache / "packages.json"
    if not manifest_file.is_file():
        raise ValueError("No cached Ubuntu APT files for this runner")
    record = json.loads(manifest_file.read_text(encoding="utf-8"))
    components = downloads.parent / "builds/components"
    if any(Path(name).name != name or not (components / name).is_file() for name in record["components"]):
        raise ValueError("Some Ubuntu build artifacts are missing")
    if record["base"] != encode_packages(installed_packages()):
        raise ValueError("The Ubuntu runner's installed APT packages have changed")
    if digest(cache / "status") != record["status"]:
        raise ValueError("The cached APT package status is invalid")
    archives = []
    for name, checksum in record["packages"]:
        archive = downloads / name
        if Path(name).name != name or archive.suffix != ".deb" or digest(archive) != checksum:
            raise ValueError(f"Invalid cached APT download: {name}")
        archives.append(archive)
    # APT's database stays on the runner image. Setup uses the recorded status
    # only for dependency queries while testing the restored files.
    for archive in archives:
        subprocess.run(["sudo", "dpkg-deb", "--extract", archive, "/"], check=True)
    subprocess.run(["sudo", "ldconfig"], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("snapshot", "save", "restore"))
    parser.add_argument("cache", type=Path)
    args = parser.parse_args()
    downloads = args.cache / "apt"
    runtime = args.cache / "apt-runtime"
    initial = args.cache / "apt-initial.json"
    try:
        if args.operation == "snapshot":
            initial.parent.mkdir(parents=True, exist_ok=True)
            initial.write_text(json.dumps(encode_packages(installed_packages())), encoding="utf-8")
        elif args.operation == "save":
            save(initial, downloads, runtime)
        else:
            restore(downloads, runtime)
    except (KeyError, OSError, ValueError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))


if __name__ == "__main__":
    main()
