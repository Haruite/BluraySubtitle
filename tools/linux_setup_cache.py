"""Reuse installed Linux package build artifacts by component."""

from __future__ import annotations

from contextlib import nullcontext
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tarfile
from tempfile import TemporaryDirectory

from vapoursynth_plugin_versions import _records, record_version

SYSTEM_ROOTS = tuple(Path("/usr/local") / name for name in ("bin", "include", "lib", "lib64", "share")) + (
    Path("/usr/share/mkvtoolnix"),
)
MANIFEST = "build.json"


def apt_packages() -> dict[str, str]:
    output = subprocess.check_output(
        ["dpkg-query", "-W", "-f=${binary:Package}\t${Version}\t${db:Status-Status}\n"],
        text=True,
    )
    return {
        name: version
        for name, version, state in (line.split("\t") for line in output.splitlines())
        if state == "installed" and not name.startswith("mkvtoolnix")
    }


def digest(path: Path) -> str:
    if path.is_symlink():
        return "link:" + os.readlink(path)
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class InstallPaths:
    def __init__(self, plugins: Path, paths: list[Path], system: bool) -> None:
        self.plugins = plugins.resolve()
        self.home = Path.home().resolve()
        self.local_libs = tuple(
            (self.home / ".local" / directory).resolve()
            for directory in ("lib", "lib64", "lib/x86_64-linux-gnu")
        ) if system else ()
        self.roots = (
            *map(Path.resolve, SYSTEM_ROOTS), (self.home / ".local/include/libdovi").resolve(),
        ) if system else ()
        paths = (*paths, *(lib / "pkgconfig/dovi.pc" for lib in self.local_libs))
        self.files = {path.parent.resolve() / path.name for path in paths}

    def contains(self, path: Path) -> bool:
        if path in self.files:
            return True
        # Each filter owns only its declared outputs. Version records are merged separately.
        if path.is_relative_to(self.plugins):
            return False
        # Reinstall Python distributions from cached wheels for the active interpreter.
        if path.is_relative_to("/usr/local/lib"):
            relative = path.relative_to("/usr/local/lib").parts
            if relative and relative[0].startswith("python"):
                return False
        return (
            any(path.is_relative_to(root) for root in self.roots)
            or (path.parent in self.local_libs and path.name.startswith("libdovi."))
        )

    def entries(self) -> dict[str, list]:
        candidates = set(self.files)
        for library_directory in self.local_libs:
            candidates.update(library_directory.glob("libdovi.*"))
        for root in self.roots:
            for name, folders, files in os.walk(root):
                parent = Path(name)
                links = [folder for folder in folders if (parent / folder).is_symlink()]
                folders[:] = [folder for folder in folders if folder not in links and self.contains(parent / folder)]
                candidates.update(parent / file for file in (*files, *links))
        entries = {}
        for path in candidates:
            if not self.contains(path):
                continue
            try:
                info = path.lstat()
                if stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
                    entries[str(path)] = [
                        info.st_mode, info.st_size, info.st_mtime_ns, info.st_ino,
                        digest(path) if path in self.files else None,
                    ]
            except FileNotFoundError:
                continue
        return entries


def manifest(archive: tarfile.TarFile, key: str) -> dict:
    with archive.extractfile(MANIFEST) as record:
        data = json.load(record)
    if data["recipe"] != key:
        raise ValueError("Build recipe has changed")
    return data


def save_cache(cache: Path, key: str, baseline: dict, scope: InstallPaths, restored: bool) -> None:
    current = scope.entries()
    previous = {"files": {}, "apt": {}, "plugins": {}}
    if restored:
        try:
            with tarfile.open(cache) as archive:
                previous = manifest(archive, key)
        except (OSError, EOFError, ValueError, KeyError, tarfile.TarError):
            # A failed read must not prevent saving the rebuilt output.
            pass
    original = baseline["files"]
    paths = {}
    for name, info in current.items():
        before = original.get(name)
        cached = previous["files"].get(name)
        if before == info and not cached:
            continue
        checksum = info[-1] or digest(Path(name))
        mode = stat.S_IMODE(info[0])
        if cached and cached[1:] == [checksum, mode]:
            paths[name] = cached
        elif before != info and (not before or (before[-1], stat.S_IMODE(before[0])) != (checksum, mode)):
            paths[name] = [before[-1] if before else None, checksum, mode]
    if not paths:
        return

    apt = {
        name: version for name, version in apt_packages().items()
        if name in previous["apt"] or baseline["apt"].get(name) != version
    }
    plugins = {}
    for path in scope.files:
        if path.parent == scope.plugins and path.suffix == ".so" and str(path) in paths:
            _, records = _records(path)
            version = records.get(path.name)
            if version and version[1] == paths[str(path)][1]:
                plugins[str(path)] = version[0]
    current_manifest = {"recipe": key, "files": paths, "apt": apt, "plugins": plugins}
    if current_manifest == previous:
        return

    record = json.dumps(current_manifest, sort_keys=True).encode()
    cache.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=cache.parent) as directory:
        replacement = Path(directory) / "native.tar.xz"
        with replacement.open("wb") as stream, subprocess.Popen(
            ["xz", "-2", "-T2"], stdin=subprocess.PIPE, stdout=stream
        ) as compressor:
            with tarfile.open(fileobj=compressor.stdin, mode="w|") as archive:
                info = tarfile.TarInfo(MANIFEST)
                info.size = len(record)
                archive.addfile(info, io.BytesIO(record))
                for name in sorted(paths):
                    archive.add(name, arcname=name.lstrip("/"), recursive=False)
                    archive.inodes.clear()
            compressor.stdin.close()
            if compressor.wait():
                raise RuntimeError("Could not compress the installed tool cache")
        replacement.replace(cache)


def restore_cache(cache: Path, key: str, scope: InstallPaths) -> None:
    with tarfile.open(cache) as archive, TemporaryDirectory(dir=cache.parent) as directory:
        record = manifest(archive, key)
        installed = apt_packages()
        if any(installed.get(name) != version for name, version in record["apt"].items()):
            raise ValueError("The build cache was created with different APT dependencies")
        with tarfile.open(Path(directory) / "system.tar", "w") as system, \
             tarfile.open(Path(directory) / "user.tar", "w") as user:
            for member in archive:
                if member.name == MANIFEST:
                    continue
                relative = Path(member.name)
                path = Path("/") / relative
                if (
                    relative.is_absolute() or ".." in relative.parts or str(path) not in record["files"]
                    or not scope.contains(path) or path.parent.resolve() != path.parent
                    or not (member.isfile() or member.issym())
                ):
                    raise ValueError(f"Unexpected path in build cache: {member.name}")
                if path.is_symlink() or path.is_file():
                    before, checksum, _ = record["files"][str(path)]
                    existing = digest(path)
                    if existing != before or existing == checksum:
                        continue
                elif path.exists():
                    continue
                if member.issym():
                    target = (path.parent / member.linkname).resolve()
                    if not scope.contains(target) and not target.is_relative_to("/usr/lib"):
                        raise ValueError(f"Unexpected link in build cache: {member.name}")
                target_tar = user if path.is_relative_to(scope.plugins) or path.is_relative_to(scope.home) else system
                with archive.extractfile(member) if member.isfile() else nullcontext() as payload:
                    target_tar.addfile(member.replace(mode=member.mode & 0o777), payload)
        for name, command in (("system", ["sudo", "tar"]), ("user", ["tar"])):
            subdivision = Path(directory) / f"{name}.tar"
            with tarfile.open(subdivision) as subset:
                present = subset.next() is not None
            if present:
                subprocess.run(
                    [*command, "-xf", str(subdivision), "-C", "/", "--no-overwrite-dir", "--no-same-owner"],
                    check=True,
                )
        # Restore just the matching digest-bound fallback records into the shared file.
        for name, version in record["plugins"].items():
            path = Path(name)
            if path in scope.files and path.parent == scope.plugins and path.is_file():
                if digest(path) == record["files"][name][1]:
                    record_version(path, version, None)


def missing_packages(cache: Path, key: str) -> None:
    with tarfile.open(cache) as archive:
        dependencies = manifest(archive, key)["apt"]
    installed = apt_packages()
    for name, version in dependencies.items():
        if not re.fullmatch(r"[a-z0-9][a-z0-9+.-]*(?::[a-z0-9]+)?", name):
            raise ValueError(f"Invalid package name in build cache: {name}")
        if name not in installed:
            print(name)
        elif installed[name] != version:
            raise ValueError(f"Build cache requires {name} {version}, found {installed[name]}")


def main() -> None:
    operation, cache, baseline, key, mode, plugins, restored, *paths = sys.argv[1:]
    cache, baseline = Path(cache), Path(baseline)
    scope = InstallPaths(Path(plugins), list(map(Path, paths)), system=mode == "system")
    try:
        if operation == "snapshot":
            baseline.write_text(json.dumps({"files": scope.entries(), "apt": apt_packages()}), encoding="utf-8")
        elif operation == "packages":
            missing_packages(cache, key)
        elif operation == "restore":
            restore_cache(cache, key, scope)
        elif operation == "save":
            save_cache(cache, key, json.loads(baseline.read_text(encoding="utf-8")), scope, restored == "true")
    except (OSError, EOFError, ValueError, KeyError, tarfile.TarError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))


if __name__ == "__main__":
    main()
