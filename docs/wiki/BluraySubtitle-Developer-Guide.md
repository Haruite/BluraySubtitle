# BluraySubtitle Developer Guide

English | [简体中文](BluraySubtitle-Developer-Guide.zh-Hans.md)

This page connects the media model to the source tree. It describes current behavior, not a proposed rewrite. The mandatory [Code Modification Standards](../development/code-standards.md) remain the authority for changes.

## Domain definitions

### Main MPLS

In BluraySubtitle, a **main MPLS** is a selected playlist whose authored playback content represents the principal movie or episode material.

This is a semantic selection. It must not be reduced to:

- the lowest or highest playlist number;
- the largest M2TS;
- the longest MPLS;
- the first playlist returned by a library; or
- one playlist per disc.

One disc can have any number of selected main playlists. A selected main MPLS must have exactly one non-empty main remux command, and selected playlists are processed in current GUI order.

### SP

**SP** is the project’s category for additional disc content outside the selected main-playlist content. It includes:

- other MPLS playlists;
- unchecked segments of a selected main MPLS;
- useful M2TS files not covered by any MPLS;
- extras that share an M2TS with main content but use a different interval;
- video, audio-only, subtitle-only, audio-plus-subtitle, IGS-menu, and single-frame layouts that the application can process deterministically.

SP is not a Blu-ray standard acronym in this context and is not a codec or container. UI and code comments should preserve this project definition.

### Segment

In the main-playlist UI, a **segment** is a user-visible chapter/file interval derived from playlist structure. Checked segments contribute to main episode configuration. Unchecked segments are excluded from main output and become SP candidates.

This UI segment is not the same as a Matroska `Segment`, a PGS segment, or an MPEG-TS packet.

## Source-code map

### Blu-ray structures

| Source | Responsibility |
| --- | --- |
| `src/bdmv/structures/mpls_header.py` | Top-level MPLS header and section addresses |
| `src/bdmv/structures/playlist.py` | Play item and subpath collections |
| `src/bdmv/structures/play_item.py` | Clip reference, flags, 45 kHz `INTime`/`OUTTime`, angles, STN |
| `src/bdmv/structures/playlist_mark.py` | Playlist mark collection |
| `src/bdmv/structures/playlist_mark_item.py` | Mark type, play-item reference, timestamp, PID, duration |
| `src/bdmv/structures/stn_table.py` | Stream-category counts and entries |
| `src/bdmv/structures/stream_entry.py` | PID/subpath stream addressing |
| `src/bdmv/structures/stream_attributes.py` | Codec, format, rate, and language attributes |
| `src/bdmv/structures/sub_path.py` | Secondary synchronized paths |
| `src/bdmv/mpls.py` | Load/save MPLS and patch STN tables from CLPI |

The structured parser uses `InfoDict` records and explicit big-endian byte packing/unpacking. Variable-sized structures use their declared length fields. `update_counts()`, `update_constants()`, and `update_addresses()` must run before serialization when structure sizes change.

### Playlist timing and chapters

`src/bdmv/chapter.py` is the lightweight workflow parser. `Chapter` reads:

- `PlayListStartAddress`;
- each play item’s clip name, `INTime`, and `OUTTime`; and
- playlist marks grouped by referenced play item.

It exposes:

```python
in_out_time: list[tuple[str, int, int]]
mark_info: dict[int, list[int]]
```

`get_total_time()` sums `(out_time - in_time) / 45000`.

`chapter_play_item_file_ranges()` combines these immutable play-item rows with the corresponding CLPI presentation range. `episode_tail_trim_plan()` uses that structure to derive a per-episode parts end and affected M2TS names; it never replaces `in_out_time` or `mark_info`. The GUI captures the derived end in the row configuration, removes affected names only from the visible M2TS column, and generates the executable `--split parts` range before worker launch.

### CLPI

`src/bdmv/clpi.py` currently reads:

- SequenceInfo ATC/STC entries;
- presentation start/end times;
- ProgramInfo programs;
- program-map PID;
- elementary PIDs; and
- stream coding metadata and language.

It also maps an M2TS path to the same-numbered CLPI and builds PID-to-language mappings. Chinese language variants are normalized to `zho` for selection parity.

The parser does not currently implement the complete CLPI CPI index. Do not claim packet-accurate CPI seeking in code or documentation unless that support is added and tested.

### M2TS

`src/bdmv/m2ts.py` implements the project’s native transport inspection:

- detects 192-byte M2TS and 188-byte TS layouts;
- iterates aligned 188-byte packets in large blocks;
- extracts PID and PUSI from TS headers;
- assembles PES headers to find first and last PTS;
- reads PCR for duration, with PTS fallback;
- handles finite timestamp wrap;
- reads AVC/HEVC parameter sets for native frame rate, with targeted ffprobe fallback;
- assembles multi-packet PAT/PMT sections;
- reports stream PID, type, codec, and language descriptors;
- classifies clip layouts;
- decodes supported IGS palette/object/button state data to PNG; and
- builds MPLS stream entries/attributes from CLPI during repair.

Important constants are:

```python
frame_size = 192
_TS_PACKET = 188
_SYNC = 0x47
```

PAT/PMT assembly must remain stateful across packets. UHD PMTs can exceed one TS payload. PUSI pointer bytes and declared PSI section length must be honored.

Duration prefers PCR because it represents the transport program clock. PTS is a fallback when suitable PCR cannot be found. A single-frame stream can have the same first and last PTS and is handled separately by frame-count logic.

### Matroska

`src/domain/media/mkv_container.py` includes a small EBML reader used to obtain duration directly from `Segment/Info`, avoiding a full `mkvinfo` scan for this common query. It also exposes chapter operations through configured MKVToolNix tools.

This reader is deliberately narrow. General Matroska identification, remuxing, track extraction, metadata editing, append, and split behavior remain MKVToolNix responsibilities.

### Subtitles

`src/domain/subtitles/pgs.py` parses raw SUP packets with:

- two-byte `PG` magic;
- 32-bit PTS and DTS;
- one-byte segment type;
- two-byte segment length; and
- segment payload.

It computes subtitle end time, iterates timestamps, writes packets, appends a second PGS with a 90 kHz shift, and cuts/rebases a time interval.

Other files under `src/domain/subtitles` implement SRT, ASS/SSA models, time conversion, style/event handling, and ASS-to-SUP conversion.

### Workflow and tool integration

| Source | Responsibility |
| --- | --- |
| `src/runtime/remux.py` | Remux request/domain types and shared remux behavior |
| `src/runtime/sp.py` | SP entry/job types and M2TS-detail interval parsing |
| `src/runtime/encode.py` | Encode request/domain types |
| `src/runtime/audio_conversion.py` | Audio extraction, analysis, conversion, and cleanup helpers |
| `src/runtime/dolby_vision.py` | `dovi_tool` preparation, profile 8.1 conversion, RPU injection |
| `src/runtime/services_split/remux_and_episode_workflows.py` | Main remux and episode execution |
| `src/runtime/services_split/subtitle_and_chapter_pipeline.py` | Subtitle, chapter, and SP planning/execution |
| `src/runtime/services_split/media_info_and_track_mapping.py` | Media probing and identifier mapping |
| `src/runtime/services_split/encode_and_audio_tasks.py` | Encode and final audio processing |
| `src/runtime/gui_runtime_split/sp_chapter_segment_logic.py` | Main segment/SP GUI relationship |
| `src/runtime/gui_runtime_split/scan_and_worker_hooks.py` | Scan launch and worker integration |

The GUI is the execution contract. The workflow captures visible selection, order, output names, chapter ranges, commands, track choices, languages, audio policies, subtitle mode, and Dolby Vision setting into plain request data before launching a worker.

## Discovery model

A simplified discovery pipeline is:

```text
Locate BDMV roots
    ↓
Enumerate and parse MPLS
    ↓
Estimate/select main playlists
    ↓
Expand main play items and chapter/file boundaries
    ↓
Apply checked main segments and episode chapter ranges
    ↓
Inventory other MPLS, excluded intervals, and uncovered M2TS as SP
    ↓
Read STN/CLPI plus native PAT/PMT/PCR/PTS information
    ↓
Populate track selection and output planning
```

Automatic main-playlist selection is a convenience, not an authority. Manual selection remains necessary for branching, obfuscated, compilation, and unusual multi-title discs.

`get_main_mpls()` in `src/runtime/services_split/lifecycle_and_configuration.py` implements the default estimate described in [Blu-ray Disc Structure](Blu-ray-Disc-Structure.md). It sums distinct referenced M2TS sizes before multiplying that total into the score. With `checked=True`, the M2TS-size factor is replaced by `1`. Candidate replacement uses strict `>`, so an exact tie retains the first path returned by `os.listdir()`; do not treat that order as a stable numeric sort.

SP rows are ordered by BDMV volume, then MPLS name, then uncovered M2TS name. The scanner shows content that is completely covered by main content but leaves it unchecked by default. Short content remains visible but is normally unchecked unless other usefulness rules apply.

## Timing model

### Clock domains

Developers must keep these domains explicit:

| Value | Clock |
| --- | ---: |
| MPLS `INTime`, `OUTTime`, and marks | 45,000 ticks/s |
| MPEG PTS and DTS | 90,000 ticks/s |
| PCR base | 90,000 ticks/s |
| PCR extension | 27,000,000 ticks/s |
| Matroska timestamps | `TimestampScale` nanoseconds per tick |
| PGS SUP PTS/DTS | 90,000 ticks/s |

Name variables with their domain or convert at a clear boundary. Avoid passing an unqualified integer named `time` through multiple layers.

### Play-item window conversion

For an M2TS whose first relevant PTS is `first_m2ts_pts`:

```python
start = (in_time * 2 - first_m2ts_pts) / 90000
end = start + (out_time - in_time) / 45000
```

This is the project’s effective file-relative window for per-clip fallback. It accounts for non-zero transport timestamps.

### Timestamp wrap

PTS/PCR bases are finite-width counters. Compute elapsed time modulo the clock range. A simple signed subtraction can produce a negative or enormous duration when the source crosses the wrap point.

### Boundary behavior

Video, audio, PG, and IG do not necessarily share identical access-unit boundaries. Do not infer that a stream-copy cut is frame/sample exact merely because its requested timestamp has millisecond precision.

## Track identity model

At minimum, the workflow deals with:

| Identifier | Owner |
| --- | --- |
| PID | MPEG transport stream |
| stream type | PMT/BD stream coding |
| MPLS stream entry | authored play-item visibility |
| CLPI stream PID/language | clip metadata |
| MKVToolNix input track ID | one identified input |
| Matroska track number/UID | final container |
| GUI row and selection order | user contract |

`properties.number` from MKVToolNix is not a transport PID. SP append/recovery requires a real `stream_id` or `original_transport_stream_id`. If no valid PID can be mapped, the selected job fails instead of guessing.

The selected MPLS STN layout is the reference. A PAT/PMT stream that physically exists but is hidden by MPLS is excluded from normal main title mapping unless an SP or recovery workflow explicitly selects it.

## Main remux pipeline

A simplified successful path is:

```text
Captured immutable request
    ↓
Preflight all selected playlists, commands, tracks, tools, and outputs
    ↓
Run one non-empty main command per selected main MPLS
    ↓
Verify every expected main output
    ↓
Process selected SP jobs
    ↓
Apply chapters, languages, and metadata
    ↓
Extract selected audio once for cleanup/conversion
    ↓
Remove silent/exact duplicate audio according to policy
    ↓
Convert selected lossless audio when enabled
    ↓
Convert compatible Dolby Vision input to the supported profile 8.1 result
    ↓
Verify final outputs
```

Existing planned outputs are errors for Blu-ray Remux. They are not overwritten or renamed. Cleanup may remove only task-created partial artifacts.

### Direct MPLS mux

MKVToolNix is the primary remuxer because it understands MPLS play items, clip-relative timing, Matroska track metadata, chapters, splitting, and append.

Direct mux is attempted first. Success requires the planned output to exist and later metadata checks to match.

### Track-aligned fallback

Direct MPLS mux can fail when adjacent clips have different track layouts. The fallback:

1. obtains `Chapter(mpls_path).in_out_time`;
2. processes every play item with its exact interval;
3. identifies only GUI-selected/MPLS-visible tracks;
4. maps every clip to the selected reference layout;
5. asks tsMuxer to recover missing selected video/subtitle PIDs and, when possible, audio PIDs;
6. synthesizes matching-duration PCM silence only for audio still unavailable;
7. requires the repaired PID set to exactly match the reference layout;
8. appends aligned per-clip MKVs in playlist order with MKVToolNix; and
9. applies/verifies chapters and track languages.

A missing selected video or subtitle stream is fatal. Silence is an explicit missing-audio alignment mechanism, not general error concealment.

### Why physical M2TS concatenation is insufficient

Concatenating source files ignores:

- per-play-item `INTime` and `OUTTime`;
- STC/PTS offsets;
- repeated clips;
- branch order;
- different track layouts;
- authored stream visibility; and
- chapter timing.

Any optimization that collapses play items must prove that all of those properties remain equivalent.

## SP pipeline

The row source determines the path:

- an MPLS-backed row always uses playlist logic;
- raw M2TS logic is used only when no MPLS belongs to the row.

Selected rows with non-empty outputs are required to complete. An empty output name with no selected audio or subtitle track is the documented intentional skip.

Output type follows selected content:

- normal video/container output → `.mkv`;
- one raw audio or subtitle stream → its elementary extension;
- multiple audio tracks → `.mka`;
- multiple subtitle tracks → `.mks`;
- one frame → `.png`;
- multiple one-frame clips → a numbered image directory.

Raw streams and PNG files cannot store Matroska track-language metadata. Configuring such metadata for an incompatible output is rejected before execution.

When an SP interval exactly and uniquely matches one main episode’s M2TS detail in series mode, selected SP audio or subtitle PIDs can be appended to the planned episode output. Multiple selected SP rows are consumed in visible order: the first row owns a repeated PID, already present PIDs are skipped, and appended SP PIDs are kept in ascending order after the original main tracks. Movie-mode SP rows never use this attachment path. The episode is replaced only after the append result has completed and passed verification.

## Audio processing

Final Remux and Encode audio processing:

1. extracts all selected audio tracks in one `mkvextract` invocation;
2. reuses those files for analysis and conversion;
3. decodes tracks for maximum-volume and fingerprint checks;
4. removes decoded maximum volume below `-60 dB`;
5. compares exact decoded fingerprints only within the same source codec family and channel count;
6. never deduplicates tracks with different known languages;
7. keeps the earliest source-order duplicate; and
8. reports every removal.

The one-extraction invariant avoids reopening a very large MKV once per track. It also means the output volume must have enough temporary space for all selected audio streams.

Remux lossless-to-FLAC conversion is controlled by its visible checkbox and is enabled by default at startup. Disabling it preserves selected source audio, apart from the documented cleanup. Remux does not use AAC or Opus for this conversion.

Encode’s Blu-ray staging remux preserves source audio. Per-track Encode audio conversion occurs only in final muxing after video encode succeeds.

## Automatic black-border cropping

`src/runtime/video_crop.py` owns duration-adaptive sampling, FFmpeg crop-result validation, conservative rectangle aggregation, and the managed VPy crop block. It uses input-side time seeking rather than exact frame selection and writes no screenshots. The one-per-150-second sample count is clamped to 4–24, and the union of sampled active areas becomes one even-aligned crop. Existing managed blocks are replaced or removed so sequential rows cannot accumulate stale crop operations.
A script without a known safe `src8`/`res` boundary fails the row instead of inserting a crop at an ambiguous point. A non-managed manual `Crop`/`CropAbs` call is also rejected when automatic cropping would be nonzero, preventing accidental double cropping.

## Dolby Vision processing

`src/runtime/dolby_vision.py` owns the `dovi_tool` boundary.

The code:

- resolves and validates the configured executable;
- extracts the MKV HEVC track when preparing an encode;
- demuxes/extracts base-layer and RPU intermediates;
- exports and adjusts every L5 active-area preset when physical cropping is active;
- checks that every requested intermediate was created;
- injects RPU metadata into supported encoded HEVC;
- converts dual-layer remux input to single-layer profile 8.1 by rewriting RPU metadata and discarding enhancement-layer video;
- uses temporary paths owned by the current job; and
- removes only those owned temporary artifacts during cleanup.

Do not silently fall back to SDR or HDR10 under a request that requires Dolby Vision preservation. Unsupported x264/x265 bit-depth combinations fail preflight. SVT-AV1 is the documented exception: encoding is allowed, Dolby Vision metadata is omitted, and the task reports that decision.

## Subtitle processing

Subtitles can affect both content and episode mapping:

- subtitle maximum end time can estimate episode length;
- selected SRT/ASS/SSA/SUP inputs must map to main output rows in visible order;
- formats cannot be mixed within one merged subtitle output;
- PGS append/cut operations use 90 kHz timestamp shifts;
- softsub outputs retain a selectable track;
- hardsub inputs become part of the encoded picture; and
- external subtitles are copied/named alongside the corresponding output.

An impossible subtitle duration is treated as source data to fix, not as a reason to silently reorder or truncate rows.

## Error and verification rules

The project prefers deterministic preflight:

- source existence;
- selected main/MPLS-to-command cardinality;
- playlist and row mapping;
- required external tools;
- invalid chapter ranges;
- track/PID availability;
- exact planned output paths;
- duplicate paths; and
- existing-output collisions.

After execution, it verifies:

- command return status;
- exact planned output existence;
- expected track layout;
- applied languages and chapters where supported;
- required Dolby Vision intermediates/final stream; and
- completion of every selected non-skipped row.

A successful external-tool exit code alone is not proof that all selected streams or their full duration survived. The TrueHD limitations documented in [Media Pipeline Design and Tool Selection](../development/media-pipeline-and-tool-selection.md) are a concrete example.

## Tests to consult

| Test file | Main coverage |
| --- | --- |
| `tests/test_m2ts_parser.py` | TS/M2TS alignment, PAT/PMT, timing, track classification |
| `tests/test_sp_workflow.py` | SP planning, exact outputs, append/recovery, PID mapping |
| `tests/test_remux_workflow.py` | Main remux contracts and fallbacks |
| `tests/test_encode_workflow.py` | Encode requests, staging, resumability, final mux |
| `tests/test_video_crop.py` | Adaptive time sampling, crop aggregation, managed VPy insertion |
| `tests/test_audio_dolby_vision_workflow.py` | Audio conversion/cleanup and Dolby Vision |
| `tests/test_add_chapters_workflow.py` | Main playlist order and chapter-to-MKV mapping |
| `tests/test_ass2sup.py` | ASS-to-SUP generation |
| `tests/test_worker_configuration_boundaries.py` | Immutable captured GUI configuration |

When changing parser or workflow behavior, add a focused deterministic test at the owning boundary and run the concentrated suite required by the code standards.
