"""Cache the installed files declared or staged by each Linux build."""

from __future__ import annotations

from contextlib import nullcontext
import hashlib
import io
import json
import os
from pathlib import Path
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


def digest(path: Path) -> str:
    if path.is_symlink():
        return "link:" + os.readlink(path)
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def installed_digest(path: Path) -> str | None:
    return digest(path) if path.is_symlink() or path.is_file() else None


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
        self.files = {path.parent.resolve() / path.name for path in paths}

    def contains(self, path: Path) -> bool:
        if path in self.files:
            return True
        if path.is_relative_to(self.plugins):
            return False
        if path.is_relative_to("/usr/local/lib"):
            relative = path.relative_to("/usr/local/lib").parts
            if relative and relative[0].startswith("python"):
                return False
        return (
            any(path.is_relative_to(root) for root in self.roots)
            or any(path == lib / "pkgconfig/dovi.pc" or (path.parent == lib and path.name.startswith("libdovi."))
                   for lib in self.local_libs)
        )


def install_archive(file: Path, *, privileged: bool) -> None:
    if file.stat().st_size <= tarfile.RECORDSIZE:
        with tarfile.open(file) as archive:
            if archive.next() is None:
                return
    subprocess.run(
        [*(["sudo"] if privileged else []), "tar", "-xf", file, "-C", "/", "--no-overwrite-dir", "--no-same-owner"],
        check=True,
    )


def install_stage(stage: Path, baseline: Path) -> None:
    before = json.loads(baseline.read_text(encoding="utf-8"))
    entries = [file for file in stage.rglob("*") if file.is_symlink() or file.is_file()]
    if not entries:
        raise ValueError("The component did not install any files into DESTDIR")
    home = Path.home().resolve()
    with TemporaryDirectory(dir=stage.parent) as directory:
        system, user = Path(directory) / "system.tar", Path(directory) / "user.tar"
        with tarfile.open(system, "w") as system_archive, tarfile.open(user, "w") as user_archive:
            for source in entries:
                destination = Path("/") / source.relative_to(stage)
                destination = destination.parent.resolve() / destination.name
                name = str(destination)
                if name not in before:
                    before[name] = installed_digest(destination)
                archive = user_archive if destination.is_relative_to(home) else system_archive
                archive.add(source, arcname=name.lstrip("/"), recursive=False)
                archive.inodes.clear()
        install_archive(system, privileged=True)
        install_archive(user, privileged=False)
    baseline.write_text(json.dumps(before), encoding="utf-8")


def manifest(archive: tarfile.TarFile, key: str) -> dict:
    member = archive.next()
    if member is None or member.name != MANIFEST or not member.isfile():
        raise ValueError("The archive has no installation manifest")
    with archive.extractfile(member) as record:
        data = json.load(record)
    if data["recipe"] != key:
        raise ValueError("Build recipe has changed")
    return data


def save_cache(cache: Path, key: str, baseline: dict, scope: InstallPaths, restored: bool) -> None:
    previous = {"files": {}, "plugins": {}}
    if restored:
        with tarfile.open(cache, "r|xz") as archive:
            previous = manifest(archive, key)

    candidates = {**{name: entry[0] for name, entry in previous["files"].items()}, **baseline}
    paths = {}
    for name, before in candidates.items():
        path = Path(name)
        if not scope.contains(path) or (checksum := installed_digest(path)) is None:
            continue
        mode = stat.S_IMODE(path.lstat().st_mode) & 0o777
        cached = previous["files"].get(name)
        if cached and cached[1:] == [checksum, mode]:
            paths[name] = cached
        else:
            paths[name] = [before, checksum, mode]
    if not paths:
        return

    plugins = {}
    for path in scope.files:
        if path.parent == scope.plugins and path.suffix == ".so" and str(path) in paths:
            _, records = _records(path)
            version = records.get(path.name)
            if version and version[1] == paths[str(path)][1]:
                plugins[str(path)] = version[0]
    if paths == previous["files"] and plugins == previous["plugins"]:
        return

    record = json.dumps({"recipe": key, "files": paths, "plugins": plugins}, sort_keys=True).encode()
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


class HashingReader:
    def __init__(self, source):
        self.source = source
        self.sha256 = hashlib.sha256()

    def read(self, size):
        block = self.source.read(size)
        self.sha256.update(block)
        return block


def restore_cache(cache: Path, key: str, scope: InstallPaths) -> None:
    with tarfile.open(cache, "r|xz") as archive, TemporaryDirectory(dir=cache.parent) as directory:
        record = manifest(archive, key)
        files = record["files"]
        seen = set()
        system, user = Path(directory) / "system.tar", Path(directory) / "user.tar"
        with tarfile.open(system, "w") as system_archive, tarfile.open(user, "w") as user_archive:
            for member in archive:
                if member.name == MANIFEST:
                    continue
                relative = Path(member.name)
                path = Path("/") / relative
                if (
                    relative.is_absolute() or ".." in relative.parts or str(path) not in files or path in seen
                    or not scope.contains(path) or path.parent.resolve() != path.parent
                    or not (member.isfile() or member.issym())
                ):
                    raise ValueError(f"Unexpected path in build cache: {member.name}")
                seen.add(path)
                before, checksum, mode = files[str(path)]
                existing = installed_digest(path)
                if existing is not None:
                    if existing == checksum and stat.S_IMODE(path.lstat().st_mode) == mode:
                        continue
                    if existing not in (before, checksum):
                        raise ValueError(f"Existing file differs from the build cache: {path}")
                elif path.exists():
                    raise ValueError(f"Existing path conflicts with the build cache: {path}")
                if member.issym():
                    target = (path.parent / member.linkname).resolve()
                    if not scope.contains(target) and not target.is_relative_to("/usr/lib"):
                        raise ValueError(f"Unexpected link in build cache: {member.name}")
                is_user = path.is_relative_to(scope.plugins) or path.is_relative_to(scope.home)
                target_tar = user_archive if is_user else system_archive
                with archive.extractfile(member) if member.isfile() else nullcontext() as payload:
                    reader = HashingReader(payload) if payload else None
                    target_tar.addfile(member.replace(mode=mode & 0o777), reader)
                    actual = reader.sha256.hexdigest() if reader else "link:" + member.linkname
                    if actual != checksum:
                        raise ValueError(f"Invalid checksum for cached file: {path}")
        if {str(path) for path in seen} != files.keys():
            raise ValueError("The archive does not contain its complete installation manifest")
        install_archive(system, privileged=True)
        install_archive(user, privileged=False)
        for name, version in record["plugins"].items():
            path = Path(name)
            if path in scope.files and path.parent == scope.plugins and path.is_file():
                if digest(path) == files[name][1]:
                    record_version(path, version, None)


def main() -> None:
    try:
        operation = sys.argv[1]
        if operation == "install":
            install_stage(*map(Path, sys.argv[2:]))
            return
        cache, baseline, key, mode, plugins, restored, *paths = sys.argv[2:]
        cache, baseline = Path(cache), Path(baseline)
        scope = InstallPaths(Path(plugins), list(map(Path, paths)), system=mode == "system")
        if operation == "snapshot":
            baseline.write_text(json.dumps({str(path): installed_digest(path) for path in scope.files}), encoding="utf-8")
        elif operation == "restore":
            restore_cache(cache, key, scope)
        elif operation == "save":
            save_cache(cache, key, json.loads(baseline.read_text(encoding="utf-8")), scope, restored == "true")
        else:
            raise ValueError(f"Unknown cache operation: {operation}")
    except (OSError, EOFError, ValueError, KeyError, TypeError, tarfile.TarError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))


if __name__ == "__main__":
    main()
