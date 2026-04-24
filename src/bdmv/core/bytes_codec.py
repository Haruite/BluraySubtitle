from struct import unpack, pack

FORMAT_CHAR = {1: ">B", 2: ">H", 4: ">I", 8: ">Q"}


def unpack_bytes(data: bytes, offset: int, length: int) -> int:
    result, = unpack(FORMAT_CHAR[length], data[offset:offset + length])
    return result


def pack_bytes(data: int, length: int) -> bytes:
    return pack(FORMAT_CHAR[length], data)


__all__ = ["FORMAT_CHAR", "unpack_bytes", "pack_bytes"]
