"""Reuse native files from a successful Linux package setup."""

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


SYSTEM_ROOTS = tuple(Path("/usr/local") / name for name in ("bin", "include", "lib", "lib64", "share")) + (
    Path("/usr/share/mkvtoolnix"),
)
SYSTEM_FILES = tuple(Path(path) for path in ("/usr/bin/mpv", "/usr/include/libdovi/rpu_parser.h"))
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
    def __init__(self, plugins: Path, executables: list[Path]) -> None:
        self.plugins = plugins.resolve()
        self.home = Path.home().resolve()
        self.local_libs = tuple(
            (self.home / ".local" / directory).resolve()
            for directory in ("lib", "lib64", "lib/x86_64-linux-gnu")
        )
        self.roots = (
            *map(Path.resolve, SYSTEM_ROOTS), self.plugins, self.home / ".local/include/libdovi",
        )
        paths = (*SYSTEM_FILES, *executables, *(lib / "pkgconfig/dovi.pc" for lib in self.local_libs))
        self.files = {path.parent.resolve() / path.name for path in paths}

    def contains(self, path: Path) -> bool:
        # Reinstall Python distributions from cached wheels for the active interpreter.
        if path.is_relative_to("/usr/local/lib"):
            relative = path.relative_to("/usr/local/lib").parts
            if relative and relative[0].startswith("python"):
                return False
        return (
            path in self.files or any(path.is_relative_to(root) for root in self.roots)
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


def manifest(archive: tarfile.TarFile) -> dict:
    with archive.extractfile(MANIFEST) as record:
        return json.load(record)


def save_cache(cache: Path, baseline: dict, scope: InstallPaths) -> None:
    current = scope.entries()
    previous = {"files": {}, "apt": {}}
    if cache.is_file():
        try:
            with tarfile.open(cache) as archive:
                previous = manifest(archive)
        except (OSError, EOFError, ValueError, KeyError, tarfile.TarError):
            # A failed read must not prevent saving the rebuilt output.
            pass
    original = baseline["files"]
    paths = {
        name: previous["files"].get(name, original.get(name, [None] * 5)[-1])
        for name, stat_info in current.items()
        if name in previous["files"] or original.get(name) != stat_info
    }
    if not paths:
        return

    apt = {
        name: version for name, version in apt_packages().items()
        if name in previous["apt"] or baseline["apt"].get(name) != version
    }
    record = json.dumps({"files": paths, "apt": apt}, sort_keys=True).encode()
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


def restore_cache(cache: Path, scope: InstallPaths) -> None:
    with tarfile.open(cache) as archive, TemporaryDirectory(dir=cache.parent) as directory:
        record = manifest(archive)
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
                    if record["files"][str(path)] != digest(path):
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


def main() -> None:
    operation, cache, baseline, plugins, *executables = sys.argv[1:]
    cache, baseline = Path(cache), Path(baseline)
    scope = InstallPaths(Path(plugins), list(map(Path, executables)))
    if operation == "snapshot":
        baseline.write_text(json.dumps({"files": scope.entries(), "apt": apt_packages()}), encoding="utf-8")
    elif operation == "packages":
        with tarfile.open(cache) as archive:
            for name in manifest(archive)["apt"]:
                if not re.fullmatch(r"[a-z0-9][a-z0-9+.-]*(?::[a-z0-9]+)?", name):
                    raise ValueError(f"Invalid package name in build cache: {name}")
                print(name)
    elif operation == "restore":
        restore_cache(cache, scope)
    elif operation == "save":
        save_cache(cache, json.loads(baseline.read_text(encoding="utf-8")), scope)


if __name__ == "__main__":
    main()
