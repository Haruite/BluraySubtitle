"""Replay the APT packages used to assemble the Linux package."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

STATUS = Path("/var/lib/dpkg/status")
# The mpv build provides FFmpeg and FFprobe at the distro package's paths.
# Their shared library dependencies are recorded separately from the CLI package.
REPLACED_APT_PACKAGES = {"ffmpeg"}
# Packaging commands and the pkg-config probes used for the artifact keys.
PACKAGING_PACKAGES = {
    "binutils", "gcc", "libc6-dev", "libass-dev", "libavcodec-dev", "libavformat-dev",
    "libavutil-dev", "libplacebo-dev", "libswresample-dev", "libswscale-dev", "libvulkan1", "python3-pip",
    "libarchive-tools", "libdouble-conversion3", "libxkbcommon-x11-0", "patchelf",
    "python3-venv", "python3-pip-whl", "xz-utils",
    f"python{sys.version_info.major}.{sys.version_info.minor}-venv",
}


def abi_version(version):
    # Ignore the update serial, keeping the base revision and any release qualifier.
    return re.sub(r"(ubuntu\d+(?:[.~]\d{2}\.\d{2})?)\.\d+$|(\+deb\d+u)\d+$", lambda m: m[1] or m[2], version)


def can_reuse_revision(cached, installed):
    return cached == installed or (
        abi_version(cached) == abi_version(installed)
        and subprocess.run(["dpkg", "--compare-versions", installed, "gt", cached]).returncode == 0
    )


def native_version_sets(cache, architecture):
    names = ("libc6", "libgcc-s1", "libstdc++6")
    current = subprocess.check_output(
        ["dpkg-query", "-W", *(f"{name}:{architecture}" for name in names)], text=True,
    ).splitlines()
    packages = dict(row.split("\t") for row in current)
    stable = [f"{name}\t{abi_version(version)}" for name, version in packages.items()]
    # v3 archives used the full dpkg-query output. Try that exact key for both
    # this runner and the runner that published the matching APT snapshot.
    versions = [stable, current]
    manifest = cache / "packages.json"
    if manifest.is_file():
        try:
            previous = {f"{name}:{arch}": version for name, arch, version, _ in json.loads(manifest.read_bytes())}
            if all(can_reuse_revision(previous.get(name, version), version) for name, version in packages.items()):
                saved = [f"{name}\t{previous.get(name, version)}" for name, version in packages.items()]
                if saved != current:
                    versions.append(saved)
        except (OSError, ValueError, TypeError):
            pass  # The optional migration input is not required for a clean build.
    return versions


def check_mixed_revisions(updated, extracted, state, architecture):
    # Do not unpack an old split package alongside an updated dependency with an
    # incompatible version constraint (for example libc6-dev and libc6).
    relation = re.compile(r"(?:^|\|)\s*([\w.+-]+)(?::[\w-]+)?\s*\(\s*(<<|<=|=|>=|>>)\s*([^\s)]+)\s*\)")
    dependencies, conflicts = set(), set()
    for controls, peers in ((extracted, updated), (updated, extracted)):
        for control in controls.values():
            for field in ("Pre-Depends", "Depends", "Breaks", "Conflicts"):
                conflict = field in ("Breaks", "Conflicts")
                for group in control.get(field, "").split(","):
                    for name, op, bound in relation.findall(group):
                        if name in peers:
                            version = peers[name]["Version"]
                            matches = subprocess.run(["dpkg", "--compare-versions", version, op, bound]).returncode == 0
                            if matches == conflict:
                                (conflicts if conflict else dependencies).add(group.strip())
    if dependencies or conflicts:
        # dpkg evaluates alternatives and virtual providers against the proposed status.
        check = subprocess.run([
            "dpkg-checkbuilddeps", "-I", "-a", architecture, f"--admindir={state}",
            "-d", ", ".join(sorted(dependencies)), "-c", ", ".join(sorted(conflicts)), "/dev/null",
        ], capture_output=True, text=True)
        if check.returncode:
            raise ValueError(f"Incompatible cached APT dependencies: {check.stderr.strip()}")


def package_fields(paragraph):
    return {
        name: value.lstrip()
        for line in re.sub(r"\n[ \t]+", " ", paragraph).splitlines() if line
        for name, _, value in (line.partition(":"),)
    }


def status_records():
    records = {}
    for paragraph in STATUS.read_text(encoding="utf-8").strip().split("\n\n"):
        fields = package_fields(paragraph)
        records[fields["Package"], fields["Architecture"]] = (fields, paragraph)
    return records


def package_paths(paths: list[str]) -> set[str]:
    candidates = set()
    for name in paths:
        if not name:
            continue
        for path in (name, str(Path(name).resolve())):
            if path.startswith(("/usr/bin/", "/usr/lib/", "/bin/", "/lib/", "/usr/share/pipewire/")):
                candidates.add(path)
                if path.startswith(("/usr/lib/", "/usr/bin/")):
                    candidates.add(path[4:])
    return candidates


def package_owners(candidates: set[str]) -> set[str]:
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


def save(downloads, cache, used_paths, restored_packages=None):
    candidates = package_paths(used_paths.read_text(encoding="utf-8").splitlines())
    owners = package_owners(candidates)
    native = subprocess.check_output(["dpkg", "--print-architecture"], text=True).strip()
    installed = {
        (name, architecture): fields["Version"]
        for (name, architecture), (fields, _) in status_records().items()
        if fields.get("Status", "").endswith(" ok installed")
    }
    required = {
        (name, architecture): version for (name, architecture), version in installed.items()
        if architecture in (native, "all") and name not in REPLACED_APT_PACKAGES
        and (name in owners or f"{name}:{architecture}" in owners or name in PACKAGING_PACKAGES)
    }
    if restored_packages is not None and restored_packages.is_file():
        for name, architecture, version, files in json.loads(restored_packages.read_text(encoding="utf-8")):
            package = name, architecture
            if (
                architecture in (native, "all") and name not in REPLACED_APT_PACKAGES
                and package not in installed and (candidates.intersection(files) or name in PACKAGING_PACKAGES)
            ):
                required[package] = version
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


def restore(downloads, cache, state, restored_packages=None):
    if restored_packages is not None:
        restored_packages.unlink(missing_ok=True)
    records = status_records()
    package_list = [
        record for record in json.loads((cache / "packages.json").read_text(encoding="utf-8"))
        if record[0] not in REPLACED_APT_PACKAGES
    ]
    if not package_list:
        raise ValueError("No cached APT dependencies for packaging")
    native = subprocess.check_output(["dpkg", "--print-architecture"], text=True).strip()
    archives = []
    updated, extracted_controls = {}, {}
    for name, architecture, version, source in package_list:
        if architecture not in (native, "all"):
            raise ValueError(f"Cannot restore {name}:{architecture} on {native}")
        package = name, architecture
        fields, _ = records.get(package, ({}, ""))
        if fields.get("Status", "").endswith(" ok installed"):
            if not can_reuse_revision(version, fields["Version"]):
                raise ValueError(f"Cached packaging requires {name}:{architecture} {version}, found {fields['Version']}")
            if fields["Version"] != version:
                updated[name] = fields
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
        archives.append((archive, name, architecture, version))
        extracted_controls[name] = control
        records[package] = (control, paragraph + "\nStatus: install ok installed")

    (state / "status").write_text("\n\n".join(record for _, record in records.values()) + "\n", encoding="utf-8")
    if updated and extracted_controls:
        check_mixed_revisions(updated, extracted_controls, state, native)

    # Preserve the runner's real package state and add only the extracted packages to the query database.
    # A later fallback build still uses these files even though the real dpkg database has no record of them.
    restored = []
    try:
        for archive, name, architecture, version in archives:
            extracted = subprocess.check_output(["sudo", "dpkg-deb", "--vextract", archive, "/"], text=True)
            files = ["/" + path.removeprefix("./") for path in extracted.splitlines()]
            restored.append([name, architecture, version, files])
    finally:
        if restored_packages is not None:
            restored_packages.write_text(json.dumps(restored) + "\n", encoding="utf-8")
    if archives:
        subprocess.run(["sudo", "ldconfig"], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("save", "restore", "native-abis"))
    parser.add_argument("cache", type=Path)
    parser.add_argument("argument", help="paths file, temporary dpkg directory, or native architecture")
    args = parser.parse_args()
    try:
        if args.operation == "native-abis":
            for rows in native_version_sets(args.cache / "apt-runtime", args.argument):
                sys.stdout.write("\n".join(rows) + "\0")
            return
        operation = save if args.operation == "save" else restore
        restored_packages = os.environ.get("BLURAY_APT_RESTORED_PACKAGES")
        operation(
            args.cache / "apt", args.cache / "apt-runtime", Path(args.argument),
            Path(restored_packages) if restored_packages else None,
        )
    except (KeyError, OSError, TypeError, ValueError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))


if __name__ == "__main__":
    main()
