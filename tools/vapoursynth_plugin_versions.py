"""Read VapourSynth plugin versions and maintain hash-bound fallback records."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import sys
import tempfile


def normalize_version(value: str) -> str:
    return re.sub(r"^[rRvV](?=[0-9])", "", value.strip())


def usable_version(value, target: str) -> str | None:
    if isinstance(value, dict):
        value = value.get("version")
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if not isinstance(value, str):
        return None
    value = value.strip()
    if target.startswith("commit:"):
        match = re.search(r"-g([0-9a-f]{7,40})$", value)
        if match:
            revision = match.group(1)
            return target if revision.startswith(target[7:]) else "commit:" + revision
        return None
    value = normalize_version(re.sub(r"-0-g[0-9a-f]+$", "", value))
    if not re.fullmatch(r"[0-9][0-9A-Za-z.+~-]*", value):
        return None
    expected = normalize_version(target)
    if re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", value):
        actual_parts = [int(part) for part in value.split(".")]
        numeric_prefix = re.match(r"[0-9]+(?:\.[0-9]+)*", expected)
        if numeric_prefix is None:
            return None
        expected_parts = [int(part) for part in numeric_prefix.group().split(".")]
        common = min(len(actual_parts), len(expected_parts))
        # Registered fields cannot identify a matching patch/fork suffix, but
        # a different numeric prefix still identifies an older/newer release.
        incomplete = numeric_prefix.group() != expected or len(actual_parts) < len(expected_parts)
        if incomplete and actual_parts[:common] == expected_parts[:common]:
            return None
    return value


def reported_version(plugin, target: str) -> str | None:
    import vapoursynth as vs

    for function in plugin.functions():
        if function.name.lower() == "version" and not function.signature:
            try:
                value = usable_version(getattr(plugin, function.name)(), target)
            except (vs.Error, UnicodeError, TypeError, ValueError):
                value = None
            # The upstream vs-nlm-ispc v4 Windows release still reports v3.
            if plugin.name == "Non-local means denoise filter implemented in ISPC" and normalize_version(target) == "4" and value == "3":
                value = None
            if value is not None:
                return value
    if plugin.version.major >= 0:
        return usable_version(f"{plugin.version.major}.{plugin.version.minor}", target)
    return None


def _records(plugin_path: Path) -> tuple[Path, dict[str, tuple[str, str]]]:
    version_file = plugin_path.parent / "version/version.txt"
    records = {}
    if version_file.is_file():
        for line in version_file.read_text(encoding="utf-8").splitlines():
            if line:
                name, release, digest = line.split("\t")
                records[name] = (release, digest)
    return version_file, records


def fallback_version(plugin_path: Path) -> str | None:
    _, records = _records(plugin_path)
    record = records.get(plugin_path.name)
    if record and record[1] == hashlib.sha256(plugin_path.read_bytes()).hexdigest():
        return normalize_version(record[0])
    return None


def record_version(plugin_path: Path, target: str, native_version: str | None) -> None:
    version_file, records = _records(plugin_path)
    if native_version is None:
        records[plugin_path.name] = (target, hashlib.sha256(plugin_path.read_bytes()).hexdigest())
    else:
        records.pop(plugin_path.name, None)
    if not records and not version_file.is_file():
        return
    version_file.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=version_file.parent, delete=False) as stream:
        for name, (release, digest) in sorted(records.items()):
            stream.write(f"{name}\t{release}\t{digest}\n")
        temporary = stream.name
    os.replace(temporary, version_file)


def _compare_part(left: str, right: str) -> int:
    # Debian version ordering: tilde, end/digits, letters, other punctuation.
    def order(value: str) -> int:
        if value == "~":
            return -1
        if not value or value.isdigit():
            return 0
        return ord(value) if value.isalpha() else ord(value) + 256

    i = j = 0
    while i < len(left) or j < len(right):
        while (i < len(left) and not left[i].isdigit()) or (j < len(right) and not right[j].isdigit()):
            difference = order(left[i:i + 1]) - order(right[j:j + 1])
            if difference:
                return difference
            i += i < len(left)
            j += j < len(right)
        while i < len(left) and left[i] == "0":
            i += 1
        while j < len(right) and right[j] == "0":
            j += 1
        end_i, end_j = i, j
        while end_i < len(left) and left[end_i].isdigit():
            end_i += 1
        while end_j < len(right) and right[end_j].isdigit():
            end_j += 1
        if end_i - i != end_j - j:
            return (end_i - i) - (end_j - j)
        if left[i:end_i] != right[j:end_j]:
            return 1 if left[i:end_i] > right[j:end_j] else -1
        i, j = end_i, end_j
    return 0


def version_satisfies(installed: str, target: str) -> bool:
    if target.startswith("commit:"):
        return installed == target
    if installed.startswith("commit:"):
        return False
    installed, target = normalize_version(installed), normalize_version(target)
    left, _, left_revision = installed.rpartition("-")
    right, _, right_revision = target.rpartition("-")
    comparison = _compare_part(left or installed, right or target)
    return comparison > 0 or (comparison == 0 and _compare_part(left_revision if left else "0", right_revision if right else "0") >= 0)


def main() -> None:
    import vapoursynth as vs

    plugins_dir = Path(sys.argv[1])
    mode, filename, target = sys.argv[2:]
    plugin_path = plugins_dir / filename
    if not plugin_path.is_file():
        raise SystemExit(1)
    core = vs.core
    core.std.LoadPlugin(path=str(plugin_path), forcens="setup_version_probe", forceid="bluraysubtitle.setup.version")
    native = reported_version(core.setup_version_probe, target)
    if mode == "read":
        value = native or fallback_version(plugin_path)
        if value is not None:
            print(value)
    elif mode == "record":
        record_version(plugin_path, target, native)
    else:
        raise ValueError(f"Unknown plugin version operation: {mode}")


if __name__ == "__main__":
    main()
