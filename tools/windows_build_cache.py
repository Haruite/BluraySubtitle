"""Publish and restore verified Windows build artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
from tempfile import NamedTemporaryFile, TemporaryDirectory
from zipfile import BadZipFile, ZipFile


MANIFEST = "build-cache.json"


def files_under(directory: Path) -> dict[str, Path]:
    return {path.relative_to(directory).as_posix(): path for path in directory.rglob("*") if path.is_file()}


def _valid_name(name: str) -> bool:
    return all(
        part and not part.endswith((".", " ")) and not re.search(r'[<>:"\\|?*\x00-\x1f]', part)
        and not re.fullmatch(r"(?:CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\..*)?", part, re.I)
        for part in name.split("/")
    )


def _copy_digest(source, destination) -> str:
    digest = hashlib.sha256()
    while block := source.read(1024 * 1024):
        digest.update(block)
        destination.write(block)
    return digest.hexdigest()


def restore(archive: Path, fingerprint: str, destination: Path) -> bool:
    if not archive.is_file():
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with TemporaryDirectory(prefix="build-cache-", dir=destination.parent) as temporary:
            payload = Path(temporary) / "payload"
            payload.mkdir()
            with ZipFile(archive) as bundle:
                manifest = json.loads(bundle.read(MANIFEST))
                if not isinstance(manifest, dict) or manifest.get("fingerprint") != fingerprint:
                    return False
                files = manifest.get("files")
                if not isinstance(files, dict) or not files:
                    return False
                names = bundle.namelist()
                if sorted(names) != sorted([MANIFEST, *files]) or len({name.casefold() for name in names}) != len(names):
                    return False
                for name, digest in files.items():
                    if not _valid_name(name) or not isinstance(digest, str):
                        return False
                    target = payload / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with bundle.open(name) as source, target.open("xb") as output:
                        if _copy_digest(source, output) != digest:
                            return False
            payload.rename(destination)
    except (BadZipFile, KeyError, OSError, ValueError):
        return False
    return True


def publish(archive: Path, fingerprint: str, files: dict[str, Path]) -> None:
    names = [MANIFEST, *files]
    if not files or not all(map(_valid_name, names)) or len({name.casefold() for name in names}) != len(names):
        raise ValueError("Invalid build cache files")
    archive.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=archive.parent, prefix=archive.stem + "-", suffix=".part", delete=False) as file:
        temporary = Path(file.name)
    try:
        hashes = {}
        with ZipFile(temporary, "w") as bundle:
            for name, path in sorted(files.items()):
                with path.open("rb") as source, bundle.open(name, "w", force_zip64=True) as output:
                    hashes[name] = _copy_digest(source, output)
            bundle.writestr(MANIFEST, json.dumps({"fingerprint": fingerprint, "files": hashes}))
        os.replace(temporary, archive)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("restore", "save"))
    parser.add_argument("archive", type=Path)
    parser.add_argument("fingerprint")
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    if args.operation == "restore":
        print("hit" if restore(args.archive, args.fingerprint, args.directory) else "miss")
    else:
        publish(args.archive, args.fingerprint, files_under(args.directory))


if __name__ == "__main__":
    main()
