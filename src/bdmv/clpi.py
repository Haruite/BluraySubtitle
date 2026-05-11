import os
from pathlib import Path

from .core import InfoDict, unpack_bytes


class CLPI:
    def __init__(self, filename=None, strict=True):
        self.strict = strict
        self.data = {}
        if filename:
            self.load(filename, strict)

    @staticmethod
    def _parse_stream_coding_info(data: bytes, offset: int) -> tuple[InfoDict, int]:
        ln = unpack_bytes(data, offset, 1)
        block = data[offset: offset + ln + 1]
        info = InfoDict()
        info["Length"] = ln
        info["StreamCodingType"] = unpack_bytes(block, 1, 1)
        t = info["StreamCodingType"]
        if t in [0x01, 0x02, 0x1B, 0xEA]:
            info["VideoFormat"], info["FrameRate"] = divmod(unpack_bytes(block, 2, 1), 16)
        elif t == 0x24:
            info["VideoFormat"], info["FrameRate"] = divmod(unpack_bytes(block, 2, 1), 16)
            info["DynamicRangeType"], info["ColorSpace"] = divmod(unpack_bytes(block, 3, 1), 16)
            info["CRFlag"] = unpack_bytes(block, 4, 1) >> 7 & 1
            info["HDRPlusFlag"] = unpack_bytes(block, 4, 1) >> 6 & 1
        elif t in [0x03, 0x04, 0x80, 0x81, 0x82, 0x83, 0x84, 0x85, 0x86, 0xA1, 0xA2]:
            info["AudioFormat"], info["SampleRate"] = divmod(unpack_bytes(block, 2, 1), 16)
            info["Language"] = block[3:6].decode("utf-8", errors="ignore")
        elif t in [0x90, 0x91]:
            info["Language"] = block[2:5].decode("utf-8", errors="ignore")
        elif t == 0x92:
            info["CharCode"] = unpack_bytes(block, 2, 1)
            info["Language"] = block[3:6].decode("utf-8", errors="ignore")
        return info, offset + ln + 1

    def load(self, filename, strict):
        with open(filename, "rb") as f:
            data = f.read()
        seq_start = unpack_bytes(data, 8, 4)
        prog_start = unpack_bytes(data, 12, 4)
        seq_len = unpack_bytes(data, seq_start, 4)
        prog_len = unpack_bytes(data, prog_start, 4)
        seq_data = data[seq_start: seq_start + seq_len + 4]
        prog_data = data[prog_start: prog_start + prog_len + 4]

        sequence_info = InfoDict()
        atc_cnt = unpack_bytes(seq_data, 5, 1)
        sequence_info["ATCSequences"] = []
        pos = 6
        for _ in range(atc_cnt):
            atc = InfoDict()
            _spn = unpack_bytes(seq_data, pos, 4)
            stc_cnt = unpack_bytes(seq_data, pos + 4, 1)
            stc_pos = pos + 6
            atc["STCSequences"] = []
            for _j in range(stc_cnt):
                stc = InfoDict()
                stc["PresentationStartTime"] = unpack_bytes(seq_data, stc_pos + 6, 4)
                stc["PresentationEndTime"] = unpack_bytes(seq_data, stc_pos + 10, 4)
                atc["STCSequences"].append(stc)
                stc_pos += 14
            sequence_info["ATCSequences"].append(atc)
            pos = stc_pos

        program_info = InfoDict()
        prog_cnt = unpack_bytes(prog_data, 5, 1)
        programs = []
        pos = 6
        for _ in range(prog_cnt):
            p = InfoDict()
            p["SPNProgramSequenceStart"] = unpack_bytes(prog_data, pos, 4)
            p["ProgramMapPID"] = unpack_bytes(prog_data, pos + 4, 2)
            stream_cnt = unpack_bytes(prog_data, pos + 6, 1)
            p["NumberOfStreamsInPS"] = stream_cnt
            p["NumberOfGroups"] = unpack_bytes(prog_data, pos + 7, 1)
            pos += 8
            p["StreamsInPS"] = []
            for _j in range(stream_cnt):
                s = InfoDict()
                s["StreamPID"] = unpack_bytes(prog_data, pos, 2)
                pos += 2
                sc, pos = self._parse_stream_coding_info(prog_data, pos)
                s["StreamCodingInfo"] = sc
                p["StreamsInPS"].append(s)
            programs.append(p)
        program_info["Programs"] = programs

        self.data = {
            "SequenceInfo": sequence_info,
            "ProgramInfo": program_info,
        }


def clpi_path_from_m2ts_path(m2ts_path: str) -> str:
    """
    Map ``.../BDMV/STREAM/xxxxx.m2ts`` to ``.../BDMV/CLIPINF/xxxxx.clpi`` (Blu-ray layout).
    """
    p = Path(os.path.normpath(str(m2ts_path or "").strip()))
    if p.suffix.lower() != ".m2ts":
        return ""
    if p.parent.name.lower() == "stream":
        return str(p.parent.parent / "CLIPINF" / f"{p.stem}.clpi")
    parts = list(p.parts)
    for i, part in enumerate(parts):
        if part.lower() == "stream":
            parts[i] = "CLIPINF"
            return str(Path(*parts).with_name(f"{p.stem}.clpi"))
    return ""


def _normalize_clip_language_code(raw: object) -> str:
    """Trim BD padding; lowercase ISO 639-2/T codes; map Chinese variants to ``zho`` for track-selection parity."""
    t = str(raw or "").replace("\x00", "").strip().lower()
    if not t:
        return "und"
    t = t[:3]
    if t in ("chi", "cmn", "yue", "nan"):
        return "zho"
    return t


def pid_to_lang_from_clpi_path(clpi_path: str) -> dict[int, str]:
    """Build transport-stream PID -> ISO-639-2 language (or ``und``) from a clip info file (first program)."""
    out: dict[int, str] = {}
    path = os.path.normpath(str(clpi_path or "").strip())
    if not path or not os.path.isfile(path):
        return out
    try:
        clip = CLPI(path, strict=False)
        programs = (clip.data.get("ProgramInfo") or {}).get("Programs") or []
    except Exception:
        return out
    if not programs:
        return out
    for stream in programs[0].get("StreamsInPS") or []:
        try:
            pid = int(stream.get("StreamPID", -1))
        except Exception:
            continue
        sci = stream.get("StreamCodingInfo")
        if not isinstance(sci, dict):
            sci = {}
        raw = sci.get("Language", "und")
        if raw is None:
            raw = "und"
        out[pid] = _normalize_clip_language_code(raw)
    return out


def pid_to_lang_from_m2ts_path(m2ts_path: str) -> dict[int, str]:
    """Same as ``src/tmp.py`` (shinya ``ClipInformationFile``): CLPI next to the M2TS under ``CLIPINF``."""
    return pid_to_lang_from_clpi_path(clpi_path_from_m2ts_path(m2ts_path))


__all__ = ["CLPI", "clpi_path_from_m2ts_path", "pid_to_lang_from_clpi_path", "pid_to_lang_from_m2ts_path"]
