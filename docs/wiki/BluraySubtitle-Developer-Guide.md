# BluraySubtitle Developer Guide

English | [简体中文](BluraySubtitle-Developer-Guide.zh-Hans.md)

This page connects the media model to the source tree. It describes current behavior, not a proposed rewrite. The mandatory [Code Modification Standards](../development/code-standards.md) remain the authority for changes.

## Domain definitions

Use the [main MPLS and SP definitions](Blu-ray-Disc-Structure.md#main-content-and-sp-in-this-project) consistently in code and UI. A GUI **segment** is a chapter/file interval: checked intervals contribute to main output and unchecked intervals become SP candidates. It is distinct from a Matroska `Segment`, a PGS segment, or a TS packet.

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
| `src/bdmv/mpls.py` | Load/save MPLS, aggregate logical STN tracks, and patch STN tables from CLPI |

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

`src/bdmv/clpi.py` reads sequence/program metadata and presentation ranges, maps M2TS paths to same-numbered CLPI files, and builds PID-language mappings. Chinese language variants normalize to `zho`. The parser does not implement the complete CPI seek index; see [CLPI layout](Blu-ray-Disc-Structure.md#clpi-binary-layout).

### M2TS

`src/bdmv/m2ts.py` handles transport alignment, stateful PAT/PMT and PES assembly, PTS/PCR timing and wrap, AVC/HEVC frame-rate parsing with targeted ffprobe fallback, layout classification, IGS image decoding, and CLPI-based STN repair. Its constants are `frame_size = 192`, `_TS_PACKET = 188`, and `_SYNC = 0x47`; the [binary layout](Blu-ray-Disc-Structure.md#m2ts-binary-layout) explains the fields.

Duration prefers PCR and falls back to PTS. Single-frame input may have equal first/last PTS and requires separate frame-count handling. Reads remain bounded and PAT/PMT assembly spans packets.

### Matroska

`src/domain/media/mkv_container.py` includes a small EBML reader used to obtain duration directly from `Segment/Info`, avoiding a full `mkvinfo` scan for this common query. It also exposes chapter operations through configured MKVToolNix tools.

This reader is deliberately narrow. General Matroska identification, remuxing, track extraction, metadata editing, append, and split behavior remain MKVToolNix responsibilities.

### Subtitles

`src/domain/subtitles/pgs.py` reads/writes SUP packets, computes end time, shifts timestamps by 90 kHz units when appending, and selects/rebases packets when cutting. Header and display-set details are in [PGS](Media-Formats-and-Dolby-Vision.md#pgs--presentation-graphics).

The same directory contains SRT/ASS/SSA models, time/style/event handling, and ASS-to-SUP conversion. SRT cutting retains only cues wholly inside the interval and renumbers them. ASS parsing follows each declared `Format:` schema and preserves commas in the final text field; SRT-to-ASS maps basic bold, underline, italic, and font-color markup to override tags.

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
Build MPLS track choices from STN; inspect raw-M2TS SP metadata
    ↓
Populate track selection and output planning
```

Automatic main-playlist selection is a convenience, not an authority. Manual selection remains necessary for branching, obfuscated, compilation, and unusual multi-title discs.

`get_main_mpls()` in `src/runtime/services_split/lifecycle_and_configuration.py` implements the [main-playlist estimate](Blu-ray-Disc-Structure.md#how-the-automatic-main-playlist-estimate-works). With `checked=True`, the M2TS-size factor is replaced by `1`.

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

Use the [MPLS-to-M2TS window formulas](Blu-ray-Disc-Structure.md#intime-and-outtime), including the initial transport PTS. That page also describes clock wrap and access-unit boundary limitations; timestamp precision does not imply frame/sample-exact stream-copy cuts.

## Episode configuration

Episode configuration is recalculated when any of these **three** inputs changes:

1. MPLS segment check states in **`table1 → view chapters`**
2. Per-row **`start_at_chapter`** in **`table2`**
3. Per-row **`end_at_chapter`** in **`table2`**

**Priority 1: `view chapters` checkbox changes → full recompute**

1. First **checked** segment starts episode 1’s `start_at_chapter`.
2. On an **unchecked** segment start, the current episode **ends** there; `end_at_chapter` is set; the next episode starts after that segment.
3. Target length is row-aligned: if that episode row has a subtitle, use its **`max_end_time`**; otherwise use **`approx episode length`**.
4. To avoid creating a short tail episode, define minimum useful tail length as **`max(0, approx episode length − 300 seconds)`**. Before comparing endpoints, discard every non-ending candidate whose remaining time to the MPLS end is shorter than this threshold. This filter applies to both file-boundary and chapter candidates; **`ending`** is always eligible.
5. Two end candidates are selected from the eligible checked nodes:
   - **A**: nearest **file boundary** (from chapter view: this node vs previous node **changes m2ts**);
   - **B**: nearest **chapter** node.
6. Pick end:
   - if A’s error is in **`[-¼ × target, +½ × target]`**, prefer **A**;
   - else multiply **negative** error by **−2**, compare A vs B, take the smaller adjusted error as `end_at_chapter`.
   - If no useful non-ending candidate remains, use **`ending`** and absorb the tail into the current episode.

**Priority 2: `start_at_chapter` changes → recompute from first changed episode**

1. Compare with the previous configuration and locate the changed MPLS and its earliest changed episode.
2. Episodes before that row and episodes belonging to other MPLS playlists stay unchanged.
3. The edited start is authoritative. From that episode onward on the same MPLS, recompute every end and every later start/end with the same rules; do not reuse stale later bounds.
4. Sync uncheck: checked nodes between the previous episode end and the new start are unchecked; for the first episode on an MPLS, nodes before the new start are unchecked. The next generated range starts at the first still-checked node.
5. Remove invalid or fully consumed rows and add continuation rows as needed until the checked MPLS tail is covered.

**Priority 3: `end_at_chapter` changes → expand / shrink**

1. The edited episode’s start and explicit end are authoritative. Episodes before it and episodes belonging to other MPLS playlists stay unchanged.
2. If `end_at_chapter` is **moved earlier**, recompute all following ranges on the same MPLS and add continuation rows until its checked tail is covered.
3. If `end_at_chapter` is **moved later**, remove every following row fully covered by the new end. The first remaining range starts at the first still-checked node at or after the new end, then all following ranges are recomputed with the same endpoint rules.
4. Automatically generated continuation rows never reuse old later bounds, and zero-length rows are discarded.

**Playlist isolation without subtitles:** each MPLS uses `approx episode length` independently. Recomputing an earlier volume may change the global episode numbering because its row count changed, but it must not change any retained `start_at_chapter/end_at_chapter` bounds in later MPLS playlists.

**Dropdown constraints**

- Nodes **unchecked** in `view chapters` must be **disabled** in both `start_at_chapter` and `end_at_chapter` combos.
- Still require **`end_at_chapter > start_at_chapter`**.
- Every emitted series row must satisfy **`1 ≤ start_at_chapter < end_at_chapter ≤ ending`**. Invalid, reversed, zero-length, and `ending`-as-start rows are removed before rebuilding the GUI.

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

Logical-track identity and authored visibility follow the [STN model](Blu-ray-Disc-Structure.md#stn-table). GUI compatibility checks cover codec, video format/frame rate/dynamic range, audio format/sample rate, and TextST character code. Keep the captured source MPLS/STN slot separate from per-PlayItem PIDs and tool-local IDs.

The [remux fallback](../development/media-pipeline-and-tool-selection.md#3-track-aligned-remux-fallback) owns occurrence validation and direct/fallback selection. Main mux commands contain `{video_opts}`, `{audio_opts}`, and `{sub_opts}`; execution fills them from the captured choices.

## Main remux pipeline

`remux_and_episode_workflows.py` executes the captured request: preflight, one command per selected main MPLS, SP work, chapters/languages, final audio/Dolby Vision processing, and output verification. The [media-pipeline document](../development/media-pipeline-and-tool-selection.md#current-pipeline) defines direct MPLS muxing, per-PlayItem recovery, and multi-output splitting. Keep those paths under the same request and final verification contract.

## SP pipeline

`src/runtime/sp.py` supplies the entry/job types and exact M2TS-detail intervals. The [SP rules](Blu-ray-Disc-Structure.md#main-content-and-sp-in-this-project) define discovery, default selection, output naming, and whole-main versus single-episode matching.

MPLS rows try direct muxing, then the common track-aligned fallback. Episode-linked SP first uses the MPLS `stream_id`; missing/inconsistent mapping requires a PID-aligned intermediate and its canonical map. Preserve original episode track order and append accepted SP tracks in selected order.

Validate selected sources, captured tracks, exact output paths, collisions, and required language tools before writing when possible. In Remux, a selected-row failure stops the task and removes only task-created partial output; replace an episode only after its append result completes and passes verification. Encode batch failure behavior follows the [code standards](../development/code-standards.md#5-preflight-and-failure-handling).

## Audio processing

`src/runtime/audio_conversion.py` owns extraction, cleanup, effective-depth selection, conversion, interval rebuilding, and validation. See [audio conversion policy](../development/media-pipeline-and-tool-selection.md#audio-conversion-policy) and [FLAC/intermediate PCM](../development/media-pipeline-and-tool-selection.md#flac-and-intermediate-pcm) for the shared transaction. The [Encode pipeline](Video-Encoding-and-VapourSynth.md#the-bluraysubtitle-encode-pipeline) explains staging versus final audio processing.

## Automatic black-border cropping

`src/runtime/video_crop.py` owns sampling, rectangle aggregation, and replacement/removal of the managed VPy crop block. The [crop section](Video-Encoding-and-VapourSynth.md#automatic-black-border-cropping) specifies sampling and custom-script boundaries.

## Dolby Vision processing

`src/runtime/dolby_vision.py` owns tool validation and task-owned base/RPU intermediates, L5 crop edits, injection, and cleanup. See [profile 8.1](Media-Formats-and-Dolby-Vision.md#profile-81-in-this-project) for layer semantics and [HDR handling](Video-Encoding-and-VapourSynth.md#automatic-hdr-metadata-handling) for encoder eligibility and verification outcomes.

## Subtitle processing

Subtitle maximum end times inform episode-duration estimates, and selected SRT/ASS/SSA/SUP files map to main output rows in visible order. A merged subtitle output must use one format. Invalid subtitle duration is a source-data problem to fix, not a reason to silently reorder or truncate rows. Output packaging follows the [subtitle modes](Media-Formats-and-Dolby-Vision.md#softsub-hardsub-and-external-subtitles).

## Error and verification rules

Apply the [preflight and failure requirements](../development/code-standards.md#5-preflight-and-failure-handling). After execution, verify the planned files, selected track layout, chapters/languages, and requested HDR result. A successful exit code alone does not establish complete streams or duration; [damaged TrueHD](../development/media-pipeline-and-tool-selection.md#current-limitation-damaged-truehd-is-not-repaired) is a documented example.

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

Choose which tests to run or modify under the [testing policy](../development/code-standards.md#11-testing-and-change-reporting).
