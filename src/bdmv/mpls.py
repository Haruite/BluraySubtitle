import os
import shutil
from typing import Optional

from .clpi import CLPI
from .core import InfoDict
from .m2ts import M2TS
from .structures.mpls_header import MPLSHeader
from .structures.stn_table import STNTable


class MPLS:
    def __init__(self, filename=None, strict=True):
        self.filename: Optional[str] = None
        self.strict = strict
        self.data = MPLSHeader() if not filename else None
        if filename:
            self.load(filename, strict)

    def load(self, filename, strict):
        self.filename = os.path.abspath(filename)
        with open(filename, "rb") as f:
            data = f.read()
        self.data = MPLSHeader.from_bytes(data, strict=strict)

    def save(self, destination, overwrite=False):
        self.data.update_constants()
        self.data.update_addresses()
        if os.path.exists(destination) and not overwrite:
            raise FileExistsError()
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        with open(destination, "wb") as f:
            f.write(self.data.to_bytes())

    def patch_playlist_stream_tables_from_clpi(
        self,
        *,
        output_path: Optional[str] = None,
        write_backup_copy: bool = True,
        strict: bool = False,
        retime_mode: str = "clip_range",
        clamp_playlist_marks: bool = False,
        remap_playlist_marks: bool = False,
        prefer_video_program: bool = True,
        include_interactive_graphics: bool = True,
        preserve_original_timebase: bool = True,
    ) -> dict[str, object]:
        if not self.filename:
            raise ValueError("MPLS.filename is empty. Load an MPLS file first.")
        mpls_path = os.path.abspath(self.filename)
        if not os.path.isfile(mpls_path):
            raise FileNotFoundError(mpls_path)

        if strict != self.strict:
            self.load(mpls_path, strict)
            self.strict = strict
        playlist_file = self
        playlist = playlist_file.data["PlayList"]
        play_items = playlist["PlayItems"]

        bdmv_root = os.path.dirname(os.path.dirname(mpls_path))
        clipinf_dir = os.path.join(bdmv_root, "CLIPINF")
        backup_clipinf_dir = os.path.join(bdmv_root, "BACKUP", "CLIPINF")

        patched_items = 0
        details: list[dict[str, object]] = []
        timing_warnings: list[str] = []
        playitem_time_pairs: list[tuple[int, int, int, int]] = []
        timebase_shift = 0

        if retime_mode not in {"keep", "clip_range", "preserve_duration"}:
            raise ValueError("retime_mode must be one of: keep, clip_range, preserve_duration")

        def _is_video_stream_type(stream_type: int) -> bool:
            return stream_type in {0x01, 0x02, 0x1B, 0xEA, 0x24, 0x20}

        def _choose_program(program_list: list[InfoDict]) -> InfoDict:
            if not program_list:
                raise ValueError("No programs in CLPI ProgramInfo")
            if not prefer_video_program:
                return program_list[0]
            for program in program_list:
                streams = program.get("StreamsInPS") or []
                for stream in streams:
                    sc = stream.get("StreamCodingInfo")
                    if sc and _is_video_stream_type(int(sc.get("StreamCodingType", -1))):
                        return program
            return max(program_list, key=lambda p: len(p.get("StreamsInPS") or []))

        def _get_clpi_time_range(clpi_data: InfoDict) -> tuple[Optional[int], Optional[int]]:
            seq = clpi_data.get("SequenceInfo")
            if not seq:
                return None, None
            atc_list = seq.get("ATCSequences") or []
            if not atc_list:
                return None, None
            stc_list = atc_list[0].get("STCSequences") or []
            if not stc_list:
                return None, None
            stc = stc_list[0]
            return int(stc.get("PresentationStartTime", 0)), int(stc.get("PresentationEndTime", 0))

        old_base_in: Optional[int] = None
        new_base_in: Optional[int] = None

        for idx, play_item in enumerate(play_items):
            clip_name = str(play_item["ClipInformationFileName"])
            clpi_path = os.path.join(clipinf_dir, f"{clip_name}.clpi")
            if not os.path.isfile(clpi_path):
                clpi_path = os.path.join(backup_clipinf_dir, f"{clip_name}.clpi")
            if not os.path.isfile(clpi_path):
                raise FileNotFoundError(f"CLPI not found for clip {clip_name}: {clpi_path}")

            clpi_file = CLPI(clpi_path, strict=strict)
            programs = clpi_file.data["ProgramInfo"]["Programs"]
            if not programs:
                raise ValueError(f"No ProgramInfo found in CLPI: {clpi_path}")
            chosen_program = _choose_program(programs)
            streams_in_ps = chosen_program["StreamsInPS"]
            clpi_start, clpi_end = _get_clpi_time_range(clpi_file.data)

            stn = STNTable()
            stn["Length"] = 1
            stn["reserved1"] = 0
            stn["reserved2"] = 0
            for name in STNTable.stream_names:
                stn[f"NumberOf{name}"] = 0
                stn[name] = []

            per_type_counts: dict[str, int] = {}
            for stream in streams_in_ps:
                stream_pid = int(stream["StreamPID"])
                sc_info = stream["StreamCodingInfo"]
                stream_type = int(sc_info["StreamCodingType"])
                if stream_type == 0x91 and not include_interactive_graphics:
                    continue
                bucket_name = M2TS._stn_bucket_name_for_stream_type(stream_type)
                if not bucket_name:
                    continue
                pair = InfoDict()
                pair["StreamEntry"] = M2TS._mpls_stream_entry_from_pid(stream_pid)
                pair["StreamAttributes"] = M2TS._mpls_stream_attributes_from_clpi_info(sc_info)
                stn[bucket_name].append(pair)
                per_type_counts[bucket_name] = per_type_counts.get(bucket_name, 0) + 1

            play_item["STNTable"] = stn

            old_in = int(play_item["INTime"])
            old_out = int(play_item["OUTTime"])
            new_in = old_in
            new_out = old_out
            if clpi_start is not None and clpi_end is not None and clpi_end > clpi_start:
                if retime_mode == "clip_range":
                    new_in = clpi_start
                    new_out = clpi_end
                elif retime_mode == "preserve_duration":
                    old_dur = max(old_out - old_in, 0)
                    new_in = max(old_in, clpi_start)
                    new_out = min(new_in + old_dur, clpi_end)
                    if new_out <= new_in:
                        new_in, new_out = clpi_start, clpi_end
                if retime_mode == "keep":
                    if not (clpi_start <= old_in < clpi_end and clpi_start < old_out <= clpi_end and old_out > old_in):
                        timing_warnings.append(
                            f"PlayItem {idx} ({clip_name}) IN/OUT out of CLPI range: "
                            f"[{old_in}, {old_out}] vs [{clpi_start}, {clpi_end}]"
                        )
                else:
                    play_item["INTime"] = int(new_in)
                    play_item["OUTTime"] = int(new_out)

            if old_base_in is None:
                old_base_in = old_in
            if new_base_in is None:
                new_base_in = int(play_item["INTime"])

            patched_items += 1
            playitem_time_pairs.append((old_in, old_out, int(play_item["INTime"]), int(play_item["OUTTime"])))
            details.append(
                {
                    "play_item_index": idx,
                    "clip": clip_name,
                    "clpi_path": clpi_path,
                    "stream_counts": per_type_counts,
                    "program_map_pid": int(chosen_program.get("ProgramMapPID", 0)),
                    "program_stream_count": len(streams_in_ps),
                    "in_time_old": old_in,
                    "out_time_old": old_out,
                    "in_time_new": int(play_item["INTime"]),
                    "out_time_new": int(play_item["OUTTime"]),
                    "clpi_start": clpi_start,
                    "clpi_end": clpi_end,
                }
            )

        if preserve_original_timebase and retime_mode != "keep" and old_base_in is not None and new_base_in is not None:
            timebase_shift = int(old_base_in - new_base_in)

        playlist.update_counts()

        if remap_playlist_marks and play_items:
            marks = playlist_file.data["PlayListMark"]["PlayListMarks"]
            for mark in marks:
                pi = int(mark["RefToPlayItemID"])
                if pi < 0 or pi >= len(play_items):
                    continue
                old_in, old_out, new_in, new_out = playitem_time_pairs[pi]
                old_ts = int(mark["MarkTimeStamp"])
                old_dur = max(old_out - old_in, 0)
                new_dur = max(new_out - new_in, 0)
                if old_dur <= 0 or new_dur <= 0:
                    mapped = new_in
                else:
                    rel = (old_ts - old_in) / float(old_dur)
                    mapped = int(round(new_in + rel * new_dur))
                if mapped < new_in:
                    mapped = new_in
                elif mapped > new_out:
                    mapped = new_out
                mark["MarkTimeStamp"] = mapped

            if preserve_original_timebase and timebase_shift != 0:
                for mark in marks:
                    mark["MarkTimeStamp"] = int(mark["MarkTimeStamp"]) + timebase_shift
        elif clamp_playlist_marks and play_items:
            marks = playlist_file.data["PlayListMark"]["PlayListMarks"]
            for mark in marks:
                pi = int(mark["RefToPlayItemID"])
                if pi < 0 or pi >= len(play_items):
                    continue
                pi_in = int(play_items[pi]["INTime"])
                pi_out = int(play_items[pi]["OUTTime"])
                ts = int(mark["MarkTimeStamp"])
                if ts < pi_in:
                    mark["MarkTimeStamp"] = pi_in
                elif ts > pi_out:
                    mark["MarkTimeStamp"] = pi_out
        elif preserve_original_timebase and timebase_shift != 0:
            marks = playlist_file.data["PlayListMark"]["PlayListMarks"]
            for mark in marks:
                mark["MarkTimeStamp"] = int(mark["MarkTimeStamp"]) + timebase_shift

        dst = os.path.abspath(output_path or mpls_path)
        playlist_file.save(dst, overwrite=True)

        backup_written = None
        if write_backup_copy:
            backup_playlist_path = os.path.join(bdmv_root, "BACKUP", "PLAYLIST", os.path.basename(dst))
            backup_playlist_dir = os.path.dirname(backup_playlist_path)
            os.makedirs(backup_playlist_dir, exist_ok=True)
            shutil.copy2(dst, backup_playlist_path)
            backup_written = backup_playlist_path

        return {
            "mpls_path": mpls_path,
            "written_path": dst,
            "backup_written_path": backup_written,
            "play_item_count": len(play_items),
            "patched_item_count": patched_items,
            "retime_mode": retime_mode,
            "remap_playlist_marks": bool(remap_playlist_marks),
            "preserve_original_timebase": bool(preserve_original_timebase),
            "timebase_shift": int(timebase_shift),
            "timing_warnings": timing_warnings,
            "details": details,
        }


__all__ = ["MPLS"]
