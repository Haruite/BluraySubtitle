# Media Pipeline Design and Tool Selection

English | [简体中文](media-pipeline-and-tool-selection.zh-Hans.md)

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

Disc loading and **Edit Tracks** aggregate every PlayItem STN directly and sort logical-track rows by their first PID. They do not identify the MPLS or inspect any M2TS. A logical track is the same ordinal stream number in the same STN category; its PID may change or its occurrence may be absent in one PlayItem. The dialog shows all distinct PIDs and a state summary, with the per-PlayItem PID/language timeline in a tooltip. The first explicit non-`und` language is the default; later language changes are displayed but do not redefine the track. MPLS-declared codec and presentation fields must remain append-compatible or the GUI disables the whole row. IGS rows are also disabled because interactive graphics have no Matroska subtitle-track representation.

At execution, the internal M2TS parser checks every declared occurrence against the corresponding M2TS PAT/PMT. An absent STN occurrence is a valid gap. By default, a missing declared PID or a conflicting transport stream type means a GUI-selected logical track cannot be retained, so the output fails instead of continuing with a reduced track set. The disabled-by-default partial-missing option lets only a physically absent audio or subtitle occurrence continue to fallback so tsMuxer can attempt recovery. MKVToolNix then identifies the MPLS and every M2TS only to decide whether the direct path can preserve the logical mapping. A gap, MKVToolNix-omitted track, or changed local track ID selects fallback before the long direct mux starts.

The [track-aligned fallback](../../src/runtime/services_split/media_info_and_track_mapping.py) handles those cases:

1. The compatible logical tracks selected in **Edit Tracks** define the output order. Each PlayItem occurrence supplies its own PID.
2. Each MPLS PlayItem is processed separately. Only logical-track occurrences declared for that PlayItem enter its part; an absent occurrence remains a gap.
3. Its M2TS-relative range is calculated as:

   ```text
   start = (in_time * 2 - first_m2ts_pts) / 90000
   end   = start + (out_time - in_time) / 45000
   ```

4. A partial play item is trimmed with `mkvmerge --split parts:start-end`. This explicitly preserves non-zero MPLS in/out boundaries instead of appending the complete M2TS.
5. `mkvmerge` supplies every declared occurrence it can identify.
6. tsMuxer is invoked only for declared PIDs that MKVToolNix omits. This also supports recovery of a required Dolby Vision layer before the project combines it with `dovi_tool`.
7. If tsMuxer cannot recover a missing declared occurrence, fallback normally fails. With the partial-missing option enabled, an audio or subtitle PID also confirmed absent by PAT/PMT is removed from that PlayItem's expected occurrences and becomes a timeline gap. Missing video, format conflicts, or a PID that tsMuxer exposes but cannot successfully demux remain hard failures.
8. Each repaired part's PID set must exactly match its remaining expected occurrences.
9. Before writing, every selected logical track must occur at least once in the output window. The final output is then written once. Every logical track's first occurrence is a normal input with its absolute playlist offset; later occurrences are chained to the preceding occurrence with `--append-to`, and `--sync` retains any leading or intermediate gap. Matroska timestamps represent the gap without dummy packets.
10. The fallback itself remains a stream-copy Remux. After it succeeds, the resulting Matroska file enters the same separate audio post-processing stage as a direct Remux, including FLAC conversion when selected.

The multi-output fallback used to split one MPLS into several episode MKVs projects every episode range onto the same PlayItem windows and applies the same occurrence, gap, recovery, and single-final-write rules.

After final Remux naming and audio cleanup/conversion, every analyzed output receives one adjacent `<output>.audio-gaps.json`. It records only gap-bearing tracks and contains an empty track list when all audio is continuous. Remux-source Encode validates the sidecar against the source file size and Matroska track UID before using it; a valid empty sidecar confirms continuity without another detection pass. If the file is absent or invalid, FFmpeg records packet timestamps during the same multi-output Wave64 decode already required for audio processing and derives the continuous intervals from those timestamps. Millisecond-scale Matroska timestamp quantization is merged within a small tolerance so it is not mistaken for authored silence between intervals.

The precheck boundary is intentionally limited to fields available from MPLS and PAT/PMT. Those structures cannot expose every payload-derived append constraint, such as PCM bit depth or channel layout found only in payload headers, or codec-private changes discovered by an elementary-stream parser. The project does not perform a speculative full-payload scan for this unconfirmed edge case. If MKVToolNix rejects such an append during fallback, the operation fails explicitly and no partial part becomes the final output.

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

There is no code in either path that synthesizes a replacement access unit, preserves a damaged interval as a gap, or fills it with silence. This makes tsMuxer useful for recovering a selected PID that MKVToolNix did not expose, but not a substitute for a dedicated damaged-TrueHD repair demuxer.

A short real-media check makes the impact concrete. tsMuxeR 2.7.0 demuxed both TrueHD PIDs from the 50.053-second Avatar `00096.m2ts` and returned `Demux complete`. It identified PID 4352 as interleaved `A_AC3` and PID 4356 as TrueHD-only `A_MLP`. The second track produced repeated `bad frame detected ... Resync stream` messages during demux. A decoder check then reported:

| PID | tsMuxer output | Output size | Decoded duration |
| ---: | --- | ---: | ---: |
| 4352 | AC-3 core + TrueHD | 34.27 MB | 00:00:06.587 |
| 4356 | TrueHD | 7.33 MB | 00:00:10.047 |

Both are far shorter than the 50.053-second M2TS interval, and the decoder reported extensive parity and restart/seamless-branch errors when warnings were enabled. Duration alone does not prove that each PID was authored to cover the whole clip, but the error log confirms that the extracted elementary streams are not clean. The check used only this short M2TS, not the complete playlist.
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

Matroska timestamps can represent a gap left by missing frames. A subsequently extracted raw `.thd` stream cannot: `mkvextract` writes the elementary frame bytes consecutively and raw TrueHD has no Matroska timestamp gap. Consequently a damaged source can have a plausible MKV duration but produce decoder errors and a decoded PCM/FLAC track that is one or two seconds shorter than the video. Changing MKV append mode aligns file boundaries but does not repair the TrueHD payload or increase the number of valid raw frames.

The observed decoder errors and short decoded duration are therefore consistent with two source-backed mechanisms: damaged but structurally accepted TrueHD frames can reach the decoder unchanged, and transport/framing loss can remove frame bytes without replacement. Without a byte-level trace of the affected PIDs, it would be too strong to claim that every reported error or the entire one-to-two-second deficit comes from only one of those mechanisms.

Local tests show that eac3to has broadly similar results on this class of damaged TrueHD.

### Why DGDemux is not integrated

DGDemux has produced substantially better results on the tested damaged TrueHD tracks. Its file-gap processing can fill damaged or missing regions so that the demuxed TrueHD duration stays close to the video duration.

However, the license distributed with DGDemux states that end users may invoke the executables directly, while use by or incorporation into third-party software requires explicit written permission from Donald A. Graft. It also prohibits redistribution. BluraySubtitle therefore cannot call, bundle, or integrate DGDemux without that permission.

Even if permission were obtained, adding DGDemux would introduce another full-disc demux stage, lengthen remux processing, add platform-specific packaging and command handling, and create a second track-order mapping path. The maintenance cost is not currently justified.

### Audio conversion policy

FFmpeg decodes TrueHD and DTS. Because FLAC cannot represent DTS:X or TrueHD Atmos object metadata, Remux converts those streams only when its separate Advanced option is enabled. The shared conversion transaction applies to FLAC, AAC, and Opus targets: a decode, analysis, encode, timeline-rebuild, or duration-validation failure in any continuous interval keeps the complete original track.

An authored leading or intermediate gap is container timing, not PCM. Conversion processes only the intervals that actually contain audio and recreates their Matroska timestamps without generating silence. Duration validation compares those intervals individually, reports a greatest positive shortening over 0.1 seconds, and discards the converted logical track when that greatest single-interval loss exceeds the configured threshold. Losses are not summed because the check protects against audible delay rather than measuring cumulative program length. The default threshold is 1 second.

Known DIY discs with damaged TrueHD still require care because neither MKVToolNix nor this conversion path repairs missing frames. The automatic duration fallback prevents a materially shortened conversion from replacing its source.

## Audio encoder selection

### FDK-AAC instead of qaac

qaac is not a native cross-platform option and normally depends on Apple's Windows codec components. FDK-AAC is available on both supported desktop platforms, can be built by the project setup scripts, and provides sufficiently similar practical quality at the bitrates used by this application. The small quality difference does not justify a Windows-only AAC path and a second platform-specific configuration.

BluraySubtitle therefore uses the `fdkaac` command-line frontend for AAC. A configured positive value is an explicit bitrate; automatic mode uses FDK-AAC VBR mode 5.

### FLAC and intermediate PCM

Final Matroska audio processing probes the source once, then uses one multi-output FFmpeg process to decode the tracks required by cleanup or conversion. A sparse logical track produces one Wave64 file per continuous interval; ordinary tracks produce one. Wave64 avoids RIFF WAV's 4 GiB limit. BDMV-derived workflows use 24-bit PCM; workflows accepting arbitrary Matroska inputs use 32-bit PCM. If batch extraction fails, partial files are removed and each logical track, including all of its intervals, is retried once; a track that still fails remains unchanged.

For a BDMV-derived Remux, the fallback's known interval map is used directly and written to the output sidecar. For a Remux-source Encode, a matching sidecar avoids rediscovery; without one, packet timestamps are collected while the same source decode writes Wave64, so detecting gaps does not add another full read of the MKV.

Analysis and encoding reuse the decoded files. FLAC output follows the greatest detected 16-, 24-, or 32-bit effective depth across the complete logical track rather than the intermediate container width. The standalone multithreaded encoder handles matching-width continuous input; FFmpeg removes zero padding and provides 16/24-bit fallback. True 32-bit output requires the standalone encoder because FFmpeg's FLAC encoder is limited to 24 bits, so a sparse true-32-bit track remains unchanged rather than being down-packed.

For sparse AAC and Opus, each interval is encoded independently and one track-append command rebuilds the Matroska timeline. Sparse FLAC uses one FFmpeg encoder stream with retained timestamp discontinuities because MKVToolNix cannot safely append independently encoded FLAC streams. The rebuilt result is decoded over all authored windows in one pass and the duration rule above is applied per interval. Standalone audio formats cannot represent a playlist gap without inserted samples, so a sparse standalone audio job fails instead of hiding the gap or adding silence.

## Tool responsibility summary

| Tool or component | Current responsibility | Reason for this scope |
| --- | --- | --- |
| Internal MPLS/M2TS parsers | Playlist windows, PAT/PMT tracks, PTS/PCR timing, cached bulk discovery | Fast and faithful to the project's MPLS rules |
| Internal Matroska reader | Read duration from EBML Segment Info | Avoid slow `mkvinfo` scans for duration-only queries |
| MKVToolNix | Primary remux, Matroska extraction, metadata edits, per-part trimming and append | Cross-platform and reliable with MPLS ranges and Matroska |
| tsMuxer | Recover explicitly missing PIDs from individual M2TS files | More permissive detection, but unsuitable as the primary MPLS demuxer |
| FFmpeg/ffprobe | Audio probing, batch Wave64 decoding, per-track extraction fallback, analysis, conversion, and piped PCM | Broad codec support while avoiding repeated source reads in the normal path |
| FLAC 1.5.0+ | Preferred FLAC encoding with all logical CPU threads | Fast multithreaded lossless encoding |
| FFmpeg FLAC encoder | 16/24-bit output and fallback | More tolerant recovery path; not used for true 32-bit output |
| fdkaac | AAC encoding | Cross-platform replacement for qaac |
| eac3to | Not used | Windows-only and confirmed playlist/timing compatibility problems |
| DGDemux | Not integrated | Good damaged-TrueHD recovery, but third-party use requires written permission and adds workflow complexity |
