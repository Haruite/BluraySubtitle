# Media Pipeline Design and Tool Selection

[简体中文](media-pipeline-and-tool-selection.zh-Hans.md)

This document describes the current Blu-ray media-processing design in BluraySubtitle and the reasons for selecting, limiting, or rejecting particular external tools. It records the behavior that the project intentionally relies on; it is not a general benchmark of every tool or version.

## Design goals

The pipeline is designed around the following requirements:

- support Windows, Linux, and Docker without requiring a Windows compatibility layer;
- treat MPLS play-item order and in/out times as the authoritative playback timeline;
- preserve the tracks, order, languages, chapter ranges, and output names selected in the GUI;
- recover from real-world Blu-ray authoring and stream-detection problems without silently changing the requested output;
- minimize repeated external-process startup and repeated scans of large media files; and
- fail explicitly when a selected non-audio track cannot be recovered.

No single tool satisfies all of these requirements. The implementation therefore uses a primary path plus narrow, validated fallbacks.

## Source-verification baseline

The implementation details in this document were checked against the following local source revisions and command-line binaries on 2026-07-26:

- MKVToolNix source `release-100.0-15-gbfc791cca` (`bfc791cca9763b494f66379953b9509b5187bc9a`) and `mkvmerge` 100.0;
- tsMuxer source `nightly-2024-06-06-02-00-53-1-gc6b1186` (`c6b1186209e42c877052e762c9185f3226ef8ea2`) and tsMuxeR 2.7.0; and
- the current BluraySubtitle source tree.

Function names are included so that the conclusions can be rechecked after an upstream update. Exact line numbers are intentionally omitted because they change more often than the relevant control flow.

## Current pipeline

### 1. In-process metadata parsing

BluraySubtitle parses MPLS structures itself and maintains each play item's clip name, `in_time`, and `out_time`. Its [M2TS parser](../../src/bdmv/m2ts.py) reads transport layout, PAT/PMT stream metadata, PTS/PCR timing, and selected video timing data directly. Parsed values are cached for unchanged files.

This is intentionally different from starting `ffprobe` or tsMuxer once for every M2TS. A large disc may contain hundreds of stream files, and process startup plus repeated probing is substantially slower than bounded in-process reads. External probing remains available for targeted operations and fallbacks; it is not the bulk M2TS discovery mechanism.

MKV duration follows the same principle. The [Matroska duration reader](../../src/domain/media/mkv_container.py) reads the EBML Segment Info, TimecodeScale, and Duration elements directly instead of waiting for `mkvinfo` to traverse a large file. This change made duration collection much faster in chapter-matching workflows.

### 2. MKVToolNix as the primary remux implementation

`mkvmerge` is the primary remuxer because it is cross-platform, produces the target Matroska container directly, preserves track metadata well, and correctly applies MPLS play-item ranges in cases where eac3to and tsMuxer have included whole M2TS files.

The normal path gives the MPLS directly to `mkvmerge`. After muxing, BluraySubtitle applies and verifies configured languages and chapters instead of assuming that an external command preserved every requested metadata value.

#### Why MKVToolNix can omit an M2TS track that tsMuxer identifies

The difference is not simply that MKVToolNix reads the PMT incorrectly. In MKVToolNix, `track_c::determine_codec_from_stream_type()` in `src/input/r_mpeg_ts.cpp` does map PMT stream type `0x24` to HEVC. Audio and video tracks are nevertheless not considered identified from that declaration alone:

1. `reader_c::determine_track_parameters()` invokes a codec-specific elementary-stream parser.
2. For HEVC, `track_c::new_stream_v_hevc()` feeds PES payload to `mtx::hevc::es_parser_c` and returns `FILE_STATUS_MOREDATA` until `headers_parsed()` becomes true.
3. `reader_c::probe_packet_complete()` sets `probed_ok` only after the codec-specific probe succeeds.
4. The final track-building loop skips any track for which `probed_ok` is false or no codec was established.

This design prevents a PMT declaration from creating an output track whose elementary-stream parameters MKVToolNix could not validate. It is stricter than merely trusting the transport metadata.

tsMuxer uses a different two-stage path. `TSDemuxer::getTrackList()` in `tsMuxer/tsDemuxer.cpp` inserts every PMT PID into its candidate map. `METADemuxer::DetectStreamReader()` then demuxes a bounded sample for those PIDs and tries its codec readers. `HEVCStreamReader::checkStream()` validates HEVC with tsMuxer's own VPS/SPS/PPS and NAL parsers. tsMuxer therefore does perform payload validation, but its parser and acceptance boundary are different from MKVToolNix's.

A read-only comparison on the two Avatar UHD play-item files that trigger the fallback produced the following result:

| M2TS | PMT video PID | mkvtoolnix | tsMuxeR 2.7.0 |
| --- | ---: |---------------------| --- |
| `00073.m2ts` | 4113 (`0x1011`) | video track omitted | HEVC Main10, 3840x2160p, 23.976 identified |
| `00096.m2ts` | 4113 (`0x1011`) | video track omitted | HEVC Main10, 3840x2160p, 23.976 identified |

This verifies the practical reason for the fallback and the stage at which MKVToolNix can reject a track. It does **not** yet identify the exact malformed NAL unit or parser rule responsible in these two files, so the document does not attribute the result to a specific VPS, SPS, or Dolby Vision defect.

#### How MKVToolNix enforces MPLS ranges across multiple M2TS files

MKVToolNix does not treat a multi-item MPLS as an unqualified list of complete files:

1. `mm_mpls_multi_file_io_c::open_multi()` in `src/common/mm_mpls_multi_file_io.cpp` iterates the ordered MPLS play items and resolves one M2TS path for each item. Repeated references remain separate ordered entries.
2. `add_filelists_for_playlists()` in `src/merge/mkvmerge.cpp` asserts that the M2TS and play-item counts match. It assigns the first play item's `in_time` and `out_time` to the original input and creates an appended file list for every subsequent item with that item's own timestamp restrictions.
3. `create_append_mappings_for_playlists()` maps each later input track back to the corresponding track in the preceding play item. This is the mechanism that joins the independently trimmed items in playlist order.
4. `read_file_headers()` passes each pair of timestamp restrictions to the elementary-stream reader through `generic_reader_c::set_timestamp_restrictions()`.
5. For MPEG-TS, `reader_c::determine_start_source_packet_number()` in `src/input/r_mpeg_ts.cpp` uses the matching CLPI entry-point map to seek near the last source packet whose PTS is no later than `in_time`.
6. Seeking near the entry point is only an optimization. The actual lower bound is enforced by `track_c::send_to_packetizer()`, which refuses PES payload before `in_time`. `reader_c::parse_pes()` enforces the upper bound by marking the current M2TS as exhausted when a PES PTS reaches or exceeds `out_time`.

The trim is therefore enforced at transport/PES timestamp boundaries rather than by blindly appending complete M2TS files. It is not an arbitrary sample-level audio edit, but it does honor the authored play-item windows for the packets delivered to the Matroska packetizers.

### 3. Track-aligned remux fallback

MKVToolNix validates M2TS structure more strictly than tsMuxer. This is useful for detecting malformed input, but some authored discs expose a track through tsMuxer while `mkvmerge --identify` omits it. Direct MPLS remuxing may also fail when different play items expose different track layouts.

The [track-aligned fallback](../../src/runtime/services_split/media_info_and_track_mapping.py) handles those cases:

1. The tracks selected in **Edit Tracks** define the required PID layout and output order.
2. Each MPLS play item is processed separately.
3. Its M2TS-relative range is calculated as:

   ```text
   start = (in_time * 2 - first_m2ts_pts) / 90000
   end   = start + (out_time - in_time) / 45000
   ```

4. A partial play item is trimmed with `mkvmerge --split parts:start-end`. This explicitly preserves non-zero MPLS in/out boundaries instead of appending the complete M2TS.
5. `mkvmerge` supplies every track it can identify.
6. tsMuxer is invoked only for selected PIDs that are still missing. This also supports recovery of a required Dolby Vision layer before the project combines it with `dovi_tool`.
7. A missing video or subtitle PID is fatal. Missing audio is first requested from tsMuxer; only audio that still cannot be recovered may be represented by duration-, sample-rate-, channel-, and bit-depth-matched PCM silence.
8. The resulting PID set is checked against the required layout.
9. Multiple repaired parts are concatenated with `--append-mode file`, so every track uses the same preceding-file timestamp boundary. Track-based appending could allow a short or damaged audio track to start the next part earlier than the video.

The multi-output fallback used to split one MPLS into several episode MKVs projects every episode range onto the same play-item windows and applies the same recovery rules.

### 4. SP tracks and MPLS-hidden tracks

An M2TS or CLPI can advertise more physical tracks than the MPLS Stream Number Table makes available for playback. PotPlayer, mpv, eac3to, and mkvmerge may therefore list two audio streams while BluraySubtitle displays only the one that the MPLS exposes. PowerDVD is a useful reference for the authored playback behavior: a track hidden by the MPLS is not offered during normal title playback.

BluraySubtitle does not blindly discard potentially useful material. In series mode it maintains an internal `m2ts_detail` value containing every M2TS name and its effective source window. When an SP entry has exactly the same `m2ts_detail` as a main episode, that SP entry is linked to the planned episode output. Selected SP audio or subtitle PIDs that are not already in the episode are appended to that MKV; a PID already present is not duplicated.

Other main episodes that do not contain the additional track remain unchanged. In typical authored discs such unexposed tracks are silent or duplicate audio. Even when their bytes are not silent, they are not addressable through normal MPLS playback and are not treated as valid title audio unless a matching SP timeline exposes them.

## Why eac3to is not the primary demuxer

### Platform support

eac3to is a Windows application. Depending on it would conflict with the project's native Linux and Docker support. Running it through Wine would add a large platform-specific dependency and would not provide the same supported execution contract.

### Observed timing error on the Avatar UHD playlist

A read-only local check was performed with eac3to 3.63 on 2026-07-26. No stream was demuxed during this check. Listing title 3 for `00800.mpls` reported:

```text
M2TS, 1 video track, 8 audio tracks, 8 subtitle tracks, 2:42:03
TrueHD/AC3 (Atmos), [eng], 7.1 channels, 48kHz, ... -1001ms
DTS-HD Master Audio, [eng], ... -1000ms
...
TrueHD/AC3 (Atmos), [zho], 7.1 channels, 48kHz, ... -1000ms
```

All audio tracks received an approximately one-second negative delay, while the playlist itself is approximately `2:42:02`. In an earlier full demux of this same source, the extracted video contained exactly 24 fewer frames. At 24000/1001 fps, 24 frames are approximately 1.001 seconds, consistent with the extra delay reported by the analysis. That large demux was not repeated while preparing this document.

This is a confirmed compatibility case for this source and eac3to version, not a claim that every eac3to operation has a one-second error.

### MPLS partial-play-item behavior

Both eac3to and tsMuxer have been observed mishandling playlists in which a play item uses only an interior interval of an M2TS. A representative playlist references one M2TS for a long interval and later references two short intervals from that same M2TS:

- eac3to includes the whole repeated M2TS once;
- tsMuxer includes the whole M2TS once for each play-item reference; and
- neither result matches the authored `in_time`/`out_time` windows.

The tsMuxer source explains the relevant limitation: it builds a complete-file path for each MPLS play item and passes MPLS timing information to readers for timeline correction, but the input file list itself is not clipped to each play item's `IN_time` and `OUT_time`.

More specifically:

- `METADemuxer::addStream()` in `tsMuxer/metaDemuxer.cpp` appends one complete M2TS path to `fileList` for every MPLS play item. Repeated clip references remain repeated entries because the list index is part of the processed-track key.
- `FileListIterator` in `tsMuxer/bufferedFileReader.h` stores only file names. `BufferedReader::thread_main()` opens each next name after the preceding file reaches EOF; no play-item byte offset or time limit is supplied.
- `TSDemuxer::setMPLSInfo()` only stores the play-item vector. At a file boundary, `TSDemuxer::simpleDemuxBlock()` uses `OUT_time - IN_time` to update the expected preceding-file duration and reset timestamp state.
- `SimplePacketizerReader::setMPLSInfo()` and `doMplsCorrection()` likewise use `OUT_time - IN_time` for timeline correction. They do not seek to `IN_time` or stop reading at `OUT_time`.

In other words, the MPLS times influence the reconstructed timeline but not which source packets are read. If the same M2TS appears in two play items, tsMuxer opens and reads that complete file twice. This control flow matches the observed duplicate-whole-file result and makes the limitation source-verifiable rather than an inference from output duration alone.

The implementation contrast can be summarized as follows:

| Stage | MKVToolNix | tsMuxer |
| --- | --- | --- |
| Expand playlist | One appended input per play item | One complete file name per play item |
| Apply `in_time` | CLPI-assisted seek plus PTS-based PES rejection | No source seek or packet rejection |
| Apply `out_time` | Stop the current M2TS when PES PTS reaches the limit | Use `OUT_time - IN_time` only for expected timeline length |
| Repeated M2TS reference | Reopen and emit only that item's restricted PTS window | Reopen and read the complete file again |

Direct MPLS processing by `mkvmerge` does not show this bug. The BluraySubtitle fallback also avoids it because every play item is explicitly converted to an M2TS-relative `--split parts:start-end` range before concatenation.

### Features covered by BluraySubtitle

eac3to has valuable audio functions, including effective bit-depth detection and audio-delay correction. Those functions alone are not a reason to accept its platform and playlist limitations:

- decoded PCM can be inspected for its effective 16- or 24-bit depth instead of trusting only the container declaration;
- replacement audio is remuxed with an explicit sync value derived from the source track's minimum timestamp;
- selected tracks are checked for decoded silence below `-60 dB`; and
- decoded fingerprints detect exact duplicates within the same source codec family and channel count, while tracks with different known languages are kept.

These checks are part of the current audio workflow rather than optional eac3to preprocessing.

## Why tsMuxer is a fallback instead of the primary demuxer

tsMuxer is useful because its stream detection is more permissive than MKVToolNix on some malformed M2TS files. It is therefore a good recovery tool for a known list of missing PIDs.

It is not used as the primary MPLS demuxer for two reasons:

1. the partial-play-item bug described above can include complete M2TS files instead of the authored ranges; and
2. damaged TrueHD streams can cause errors, severe frame loss, or an extracted stream that is reported as complete but is not usable.

### Why damaged TrueHD extraction is unreliable

tsMuxer uses two different readers for the relevant Blu-ray TrueHD layouts. Both lack damaged-frame repair, and their failure behavior is important:

- A TrueHD-only PID is handled by `MLPStreamReader`. `MLPCodec::decodeFrame()` reports header or major/minor-sync validation failure as a Boolean `false`, and `MLPStreamReader::decodeFrame()` converts that result to zero instead of a distinct error category. `SimplePacketizerReader::readPacket()` therefore treats it as a bad frame, enables resynchronization, and `MLPCodec::findFrame()` searches only for the next TrueHD/MLP major sync word. All intervening bytes, including otherwise usable minor-sync frames, are skipped.
  A normal input-block boundary shorter than `getHeaderLen()` is buffered by `SimplePacketizerReader` before this call, so the source does not support blaming ordinary block boundaries alone.
- A Blu-ray PID containing interleaved AC-3 core and TrueHD extension data is handled by `AC3StreamReader`. `AC3Codec::decodeFrame()` validates the first TrueHD major-sync frame while detecting the mode. Once `m_true_hd_mode` is true, subsequent extension frames are advanced primarily by their declared length; the nested `if (!m_true_hd_mode)` validation branch cannot execute in that state. If framing is lost, `AC3Codec::findFrame()` searches only for the next AC-3 `0x0b77` sync word, so TrueHD bytes before the next core frame can be discarded.
- `SimplePacketizerReader` can throw an `invalid stream` error when a `NOT_ENOUGH_BUFFER` condition persists beyond one full input block. Other malformed frames instead produce `bad frame detected ... Resync stream` and processing continues, so a zero exit status does not prove that the extracted elementary stream is complete.
- Both TrueHD paths generate output timestamps from accepted frame sample counts. `AC3StreamReader::readPacketTHD()` overwrites PTS from `m_totalTHDSamples`, and `AC3StreamReader::needMPLSCorrection()` explicitly returns false in TrueHD mode. Missing frames therefore shorten the generated timeline; no original PTS gap or MPLS interval is represented in the raw output.

There is no code in either path that synthesizes a replacement access unit, preserves a damaged interval as a gap, or fills it with silence. This makes tsMuxer useful for recovering a video or subtitle PID that MKVToolNix did not expose, but not a substitute for a dedicated damaged-TrueHD repair demuxer.

A short real-media check makes the impact concrete. tsMuxeR 2.7.0 demuxed both TrueHD PIDs from the 50.053-second Avatar `00096.m2ts` and returned `Demux complete`. It identified PID 4352 as interleaved `A_AC3` and PID 4356 as TrueHD-only `A_MLP`. The second track produced repeated `bad frame detected ... Resync stream` messages during demux. `truehdd` 0.4.0 `info` then reported:

| PID | tsMuxer output | Output size | `truehdd` duration |
| ---: | --- | ---: | ---: |
| 4352 | AC-3 core + TrueHD | 34.27 MB | 00:00:06.587 |
| 4356 | TrueHD | 7.33 MB | 00:00:10.047 |

Both are far shorter than the 50.053-second M2TS interval, and `truehdd` reported extensive parity and restart/seamless-branch errors when warnings were enabled. Duration alone does not prove that each PID was authored to cover the whole clip, but the error log confirms that the extracted elementary streams are not clean. The check used only this short M2TS, not the complete playlist.
The source explains the resynchronization and frame-loss behavior; it does not prove whether each individual bad-frame report was triggered by original payload damage, an unsupported framing pattern, or an earlier loss of framing.

Restricting tsMuxer to per-file, per-PID recovery also makes its output verifiable: BluraySubtitle knows exactly which tracks are missing and rejects a result that does not restore the required layout.

## TrueHD and Atmos handling

### Current limitation: damaged TrueHD is not repaired

MKVToolNix parses and muxes TrueHD frames but does not perform decoder-style error concealment or synthesize replacement TrueHD frames. A transport continuity error can drop a PES packet, while a frame whose header remains plausible may still contain payload that fails during decoding.

The relevant MKVToolNix paths make the limitation explicit:

- `reader_c::handle_transport_errors()` in `src/input/r_mpeg_ts.cpp` treats either the TS transport-error flag or an unexpected continuity counter as an error, clears the accumulated payload, and logs that it is dropping the current PES packet. It does not create replacement audio for the discarded interval.
- `frame_t::parse_header()` in `src/common/truehd.cpp` obtains a normal TrueHD access-unit length from the first word and accepts a normal frame without a payload checksum. The AC-3 branch, in contrast, explicitly calls `mtx::ac3::verify_checksums()`. A TrueHD frame can therefore be structurally separable while still containing damage that a decoder later reports.
- `parser_c::parse()` copies the bytes of every accepted frame. Its `resync()` routine searches forward for the next TrueHD/MLP major sync or AC-3 frame after framing is lost; skipped bytes are not converted into silence or a replacement TrueHD frame.
- `truehd_ac3_splitting_packet_converter_c::process_frames()` gives the PES timestamp to the first TrueHD frame in that PES. Subsequent frames are timed from their sample counts by `truehd_packetizer_c::process_framed()`. That packetizer places the original `frame->m_data` in the Matroska packet; apart from the optional dialog-normalization header edit, it does not rewrite or decode the payload.
- `xtr_base_c::create_extractor()` maps `MKV_A_TRUEHD` to the generic `xtr_base_c` extractor, whose `handle_frame()` writes each Matroska frame directly to the output file. Matroska timestamps and gaps are not serialized into a raw `.thd` elementary stream.

Matroska timestamps can represent a gap left by missing frames. A subsequently extracted raw `.thd` stream cannot: `mkvextract` writes the elementary frame bytes consecutively and raw TrueHD has no Matroska timestamp gap. Consequently a damaged source can have a plausible MKV duration but produce many `truehdd` errors and a decoded PCM/FLAC track that is one or two seconds shorter than the video. Changing MKV append mode aligns file boundaries but does not repair the TrueHD payload or increase the number of valid raw frames.

The observed `truehdd` errors and short decoded duration are therefore consistent with two source-backed mechanisms: damaged but structurally accepted TrueHD frames can reach the decoder unchanged, and transport/framing loss can remove frame bytes without replacement. Without a byte-level trace of the affected PIDs, it would be too strong to claim that every reported error or the entire one-to-two-second deficit comes from only one of those mechanisms.

Local tests show that eac3to has broadly similar results on this class of damaged TrueHD.

### Why DGDemux is not integrated

DGDemux has produced substantially better results on the tested damaged TrueHD tracks. Its file-gap processing can fill damaged or missing regions so that the demuxed TrueHD duration stays close to the video duration.

However, the license distributed with DGDemux states that end users may invoke the executables directly, while use by or incorporation into third-party software requires explicit written permission from Donald A. Graft. It also prohibits redistribution. BluraySubtitle therefore cannot call, bundle, or integrate DGDemux without that permission.

Even if permission were obtained, adding DGDemux would introduce another full-disc demux stage, lengthen remux processing, add platform-specific packaging and command handling, and create a second track-order mapping path. The maintenance cost is not currently justified.

### Why `truehdd` is used instead of FFmpeg for Atmos conversion

Within the supported decoder set, `truehdd` is used because it can fully interpret the TrueHD Atmos presentation required by this workflow. BluraySubtitle decodes presentation 2 before FLAC encoding and does not treat FFmpeg's TrueHD decoding as an equivalent Atmos conversion path. If `truehdd` is unavailable or fails, the source TrueHD Atmos track is retained.

FLAC is used to improve playback compatibility across devices. For TrueHD/MLP, a successfully decoded FLAC is therefore retained even when it is larger than the original TrueHD stream: compatibility, not size reduction, is the reason for this conversion. DTS is handled differently; a DTS-family source is kept when its replacement FLAC would be larger.

Known DIY discs with damaged TrueHD should be validated by comparing decoded audio duration with video duration and reviewing `truehdd` errors before the source stream is discarded.

## Audio encoder selection

### FDK-AAC instead of qaac

qaac is not a native cross-platform option and normally depends on Apple's Windows codec components. FDK-AAC is available on both supported desktop platforms, can be built by the project setup scripts, and provides sufficiently similar practical quality at the bitrates used by this application. The small quality difference does not justify a Windows-only AAC path and a second platform-specific configuration.

BluraySubtitle therefore uses the `fdkaac` command-line frontend for AAC. A configured positive value is an explicit bitrate; automatic mode uses FDK-AAC VBR mode 5.

### Standalone FLAC first, FFmpeg fallback

FLAC is the preferred lossless output. The standalone encoder is tried first because FLAC 1.5.0 supports multithreaded encoding; BluraySubtitle passes `-j` with the detected logical CPU count.

The standalone encoder is less tolerant of some generated inputs and runtime environments and may fail. Compressed sources also have to be decoded to PCM before the standalone encoder can read them. The pipeline therefore:

1. reuses an already decoded WAV/W64 when available;
2. otherwise decodes compressed input to PCM;
3. runs the standalone `flac` encoder with multithreading; and
4. removes a failed partial output and falls back to FFmpeg's FLAC encoder.

This preserves the performance advantage of FLAC 1.5.0 without making its successful execution a single point of failure.

## Tool responsibility summary

| Tool or component | Current responsibility | Reason for this scope |
| --- | --- | --- |
| Internal MPLS/M2TS parsers | Playlist windows, PAT/PMT tracks, PTS/PCR timing, cached bulk discovery | Fast and faithful to the project's MPLS rules |
| Internal Matroska reader | Read duration from EBML Segment Info | Avoid slow `mkvinfo` scans for duration-only queries |
| MKVToolNix | Primary remux, Matroska extraction, metadata edits, per-part trimming and append | Cross-platform and reliable with MPLS ranges and Matroska |
| tsMuxer | Recover explicitly missing PIDs from individual M2TS files | More permissive detection, but unsuitable as the primary MPLS demuxer |
| FFmpeg/ffprobe | Targeted decode, analysis, fallback probing and encoding | Broad codec support; process cost is acceptable outside bulk discovery |
| `truehdd` | Decode TrueHD Atmos presentation 2 | Required Atmos presentation handling |
| FLAC 1.5.0+ | Preferred FLAC encoding with all logical CPU threads | Fast multithreaded lossless encoding |
| FFmpeg FLAC encoder | Fallback when standalone FLAC is unavailable or fails | More tolerant recovery path |
| `fdkaac` | AAC encoding | Cross-platform replacement for qaac |
| eac3to | Not used | Windows-only and confirmed playlist/timing compatibility problems |
| DGDemux | Not integrated | Good damaged-TrueHD recovery, but third-party use requires written permission and adds workflow complexity |

