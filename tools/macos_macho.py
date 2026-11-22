"""Read the Mach-O load commands that control architecture, deployment and relocation."""

import struct
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MachO:
    minimum: tuple[int, int, int]
    loads: tuple[str, ...]
    rpaths: tuple[str, ...]
    install_id: str
    universal: bool


def inspect_macho(file: Path, arch: str) -> MachO | None:
    cpu = {"x86_64": 0x01000007, "arm64": 0x0100000C}[arch]
    subtype = {"x86_64": 3, "arm64": 0}[arch]
    with file.open("rb") as stream:
        magic = stream.read(4)
        fat = magic in (b"\xca\xfe\xba\xbe", b"\xca\xfe\xba\xbf")
        if fat:
            wide = magic[-1] == 0xBF
            (count,) = struct.unpack(">I", stream.read(4))
            # Java bytecode has the same four magic bytes as a fat executable.
            if count > 128:
                return None
            offset = None
            for _ in range(count):
                kind, sub, position, *_ = struct.unpack(
                    ">IIQQII" if wide else ">IIIII", stream.read(32 if wide else 20)
                )
                if kind == cpu and sub & 0xFFFFFF == subtype:
                    offset = position
            if offset is None:
                raise ValueError(f"{file} has no baseline {arch} slice")
            stream.seek(offset)
            magic = stream.read(4)
        if magic != b"\xcf\xfa\xed\xfe":
            return None
        kind, sub, _, count, length, _, _ = struct.unpack("<7I", stream.read(28))
        if (kind, sub & 0xFFFFFF) != (cpu, subtype):
            raise ValueError(f"Incorrect CPU type {kind:#x}/{sub:#x} in {file}")
        commands = stream.read(length)
    minimum = (0, 0, 0)
    loads, rpaths, install_id = [], [], ""
    position = 0
    for _ in range(count):
        cmd, size = struct.unpack_from("<II", commands, position)
        if size < 8 or position + size > length:
            raise ValueError(f"Invalid load command in {file}")
        if cmd in (0x24, 0x32):
            (number,) = struct.unpack_from("<I", commands, position + (12 if cmd == 0x32 else 8))
            minimum = (number >> 16, (number >> 8) & 255, number & 255)
        elif cmd in (0xC, 0xD, 0x80000018, 0x8000001F, 0x80000023, 0x8000001C):
            (start,) = struct.unpack_from("<I", commands, position + 8)
            name = commands[position + start : position + size].split(b"\0", 1)[0].decode()
            if cmd == 0xD:
                install_id = name
            elif cmd == 0x8000001C:
                rpaths.append(name)
            else:
                loads.append(name)
        position += size
    return MachO(minimum, tuple(loads), tuple(rpaths), install_id, fat)
