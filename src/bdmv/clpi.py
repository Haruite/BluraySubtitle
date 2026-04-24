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


__all__ = ["CLPI"]
