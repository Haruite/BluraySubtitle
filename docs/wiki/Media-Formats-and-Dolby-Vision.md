# Media Formats, Subtitles, and Dolby Vision

English | [简体中文](Media-Formats-and-Dolby-Vision.zh-Hans.md)

This page summarizes the formats encountered in Blu-ray and BluraySubtitle. “Format” can mean a container, codec, elementary-stream representation, or subtitle model, so each section states which layer it describes.

## Video formats

| Codec | Typical use and properties |
| --- | --- |
| MPEG-2 Video | Lossy video on early Blu-ray; less compression-efficient than AVC/HEVC |
| VC-1 | Lossy early-Blu-ray video; usually remuxed or decoded rather than chosen for new encodes |
| AVC / H.264 | Common 1080p Blu-ray video, normally 8-bit 4:2:0; normal disc delivery is lossy |
| MVC | AVC's stereoscopic extension: a base view plus a dependent view, sometimes addressed through extensions/subpaths |
| HEVC / H.265 | Primary UHD-Blu-ray codec, commonly 10-bit 4:2:0 with Rec. 2020/HDR signaling |
| AV1 | An Encode target through SVT-AV1, rather than a BDMV/UHD-BD source codec in this project |

Codec names identify the bitstream; x264, x265, and SVT-AV1 are encoder implementations. See [encoder selection](Video-Encoding-and-VapourSynth.md#choosing-h264-h265-or-av1) for output depth, compatibility, and Dolby Vision constraints.

### Pixel format is separate from codec

Descriptions such as `yuv420p`, `yuv420p10le`, 8-bit, 10-bit, 4:2:0, limited range, Rec. 709, and Rec. 2020 describe decoded sample representation and color signaling. They are not interchangeable with codec names.

Relevant concepts include:

- **bit depth**: number of code-value bits per component;
- **chroma subsampling**: reduced chroma resolution, such as 4:2:0;
- **primaries**: the chromaticity coordinates of the RGB primaries;
- **transfer characteristics**: mapping between signal code values and light;
- **matrix coefficients**: conversion between RGB and luma/chroma components; and
- **range**: limited/video range or full range.

These tags must match the intended signal. Remuxing should preserve correct signaling; encoding must explicitly generate or copy correct output metadata.

## Audio formats

| Format | Compression and characteristics |
| --- | --- |
| PCM / Blu-ray LPCM | Uncompressed samples; Blu-ray adds framing/channel layout. Common rates are 48/96/192 kHz and depths 16/24 bits. Effective precision can be lower than the declared depth. |
| FLAC | Losslessly compresses PCM; compression level affects effort/size, not decoded quality. |
| AC-3 / Dolby Digital | Lossy compatibility audio, often interleaved with TrueHD on Blu-ray. |
| E-AC-3 / Dolby Digital Plus | Lossy Dolby format with greater capability than AC-3; used by streaming and Blu-ray primary/secondary audio. |
| TrueHD / MLP | Lossless channel audio based on Meridian Lossless Packing; may be TrueHD-only or interleaved with AC-3. Can carry Atmos objects/beds/rendering metadata. |
| DTS core | Lossy compatibility layer for older decoders. |
| DTS-HD High Resolution | Lossy extension to DTS core. |
| DTS-HD Master Audio | Lossless residual plus a compatible lossy core; a capable decoder reconstructs the master. |
| AAC | Lossy Encode target via `fdkaac`; bitrate `0` selects FDK-AAC VBR mode 5. |
| Opus | Lossy Encode target; Auto uses 128 kbps for up to two channels and 256 kbps for more channels. |

FLAC preserves decoded PCM, not DTS:X or TrueHD Atmos object metadata. The project's FLAC output follows effective sample depth; conversion controls are in the [README](../../README.md#audio-controls).

Damaged TrueHD can retain a plausible container duration while decoded audio becomes shorter. The normal tools do not synthesize replacement TrueHD frames; consult the [documented limitation and validation](../development/media-pipeline-and-tool-selection.md#current-limitation-damaged-truehd-is-not-repaired) before discarding a problematic source.

## Audio core and extension terminology

“Core” does not necessarily mean a separate selectable disc track. It can be a compatible substream within a compound coded presentation. Different tools may display:

- one logical TrueHD/DTS-HD track;
- the lossless presentation and compatibility core separately; or
- only the core when extension parsing is unsupported.

Track count shown by one tool is therefore not sufficient evidence of the physical stream layout.

## Lossless-audio conversion decisions

The project’s conversion policy can be summarized as:

| Source family | Possible target | Loss model | Project note |
| --- | --- | --- | --- |
| LPCM | FLAC | Lossless PCM-to-PCM representation | Controlled by the lossless-audio option |
| FLAC | FLAC | Lossless | Usually copy unless processing requires re-encode |
| TrueHD/MLP or DTS-HD MA | FLAC | Lossless for a correctly decoded channel presentation | Immersive variants require explicit opt-in |
| DTS core / DTS-HD HR | unchanged | Source is lossy | Excluded from automatic lossless conversion |
| Lossless source | AAC/Opus | Lossy | Encode workflow only, per selected policy |
| AC-3/E-AC-3/AAC/Opus | unchanged | No new codec generation | Selected lossy audio is normally preserved |

Gap preservation, duration checks, and whole-track fallback follow the [audio conversion policy](../development/media-pipeline-and-tool-selection.md#audio-conversion-policy).

## Subtitle models

Subtitles fall into two broad models:

- **text subtitles**, where the container stores text, timing, and possibly styling instructions; and
- **bitmap subtitles**, where the stream supplies images, palettes, placement, and display composition.

### SRT

SubRip (`.srt`) is a sequence of cue blocks separated by a blank line. A normal block contains:

1. a decimal cue number;
2. a start and end timestamp separated by `-->`;
3. one or more text lines; and
4. a blank line terminating the block.

```srt
1
00:00:01,000 --> 00:00:03,500
First subtitle line
Second subtitle line

2
00:00:05,250 --> 00:00:07,000
Another subtitle
```

The conventional timestamp form is `HH:MM:SS,mmm`, where `mmm` is milliseconds. Cue numbers identify file order but are not presentation timestamps; tools commonly renumber them after cutting or joining. SRT does not have a single rich style system. Some renderers accept a small HTML-like subset, but support is inconsistent and should not be relied upon for precise layout.

Character encoding is also not declared reliably inside an SRT file. UTF-8 is the safest exchange choice. BluraySubtitle's conversion path tries several Unicode and legacy encodings for existing files, but newly created text should be UTF-8 whenever possible.

When SRT is stored in Matroska as `S_TEXT/UTF8`, the container block timestamp and duration replace the numbered-file timing lines. The block payload contains the UTF-8 cue text, not a complete embedded `.srt` file.

### ASS and SSA

Advanced SubStation Alpha (`.ass`) and SubStation Alpha (`.ssa`) are text-based formats with rich styles, positioning, transforms, drawing, karaoke, and font dependencies. Correct rendering can require attached or installed fonts.

An ASS file is divided into named sections. The important sections are:

| Section | Contents |
| --- | --- |
| `[Script Info]` | Script type, title, script resolution, wrapping and other global settings |
| `[Aegisub Project Garbage]` | Optional editor state; not presentation content |
| `[V4+ Styles]` | A `Format:` schema followed by named `Style:` rows |
| `[Events]` | A `Format:` schema followed by `Dialogue:` and optional `Comment:` rows |

A minimal example is:

```ass
[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Italic, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,60,&H00FFFFFF,&H00000000,&H80000000,0,0,1,3,1,2,60,60,40,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:04.50,Default,,0,0,0,,First line\NSecond line
```

`Format:` declares the column order, so a parser should use it instead of assuming one fixed layout. The final `Text` field may contain commas. ASS time normally uses `h:mm:ss.cc`, with centiseconds rather than SRT's milliseconds. `\N` is a forced line break. Override tags inside braces, for example `{\i1}`, `{\pos(960,900)}`, or `{\fad(200,200)}`, can change style, position, animation, drawing, and karaoke for part of an event.

`PlayResX` and `PlayResY` define the script coordinate system; changing them without scaling styles and positions changes the rendered layout. A style's `Fontname` refers to the font's internal family name, which may differ from its filename. Distributing the referenced fonts is therefore part of preserving an ASS presentation.

ASS/SSA can be:

- stored as a soft subtitle track in Matroska;
- distributed externally; or
- rendered to video or converted to a bitmap subtitle format.

Inside Matroska, the global script and style sections are stored as codec private data for `S_TEXT/ASS`/`S_TEXT/SSA`, while each event is stored in a timed block. Fonts should be normal Matroska attachments rather than legacy uuencoded `[Fonts]` data.

### PGS / Presentation Graphics

PGS is Blu-ray’s bitmap presentation subtitle system. A raw PGS stream is commonly stored in a `.sup` file. It is not text and cannot be edited as text without OCR or manual reconstruction.

A SUP packet commonly begins with:

```text
"PG" magic
PTS (32-bit, 90 kHz)
DTS (32-bit, 90 kHz)
segment type
segment length
segment payload
```

Important segment types include:

| Type | Name | Purpose |
| ---: | --- | --- |
| `0x14` | PDS | Palette Definition Segment |
| `0x15` | ODS | Object Definition Segment containing RLE bitmap data |
| `0x16` | PCS | Presentation Composition Segment |
| `0x17` | WDS | Window Definition Segment |
| `0x80` | END | End of a display set |

A rendered subtitle event is assembled from a display set rather than one standalone image packet. Composition state can acquire, update, reuse, or clear objects. Cutting or concatenating PGS therefore requires timestamp adjustment and preservation of the definitions needed to render each display set.

### IGS / Interactive Graphics

IGS is interactive menu graphics, not ordinary PGS subtitles. See [HDMV/BD-J menus](Blu-ray-Disc-Structure.md#hdmvbd-j-menus-and-igs) for composition and the image-extraction limits.

### TextST

TextST is the Blu-ray text-subtitle format associated with stream type `0x92`. It is distinct from SRT and ASS even though all are text-oriented.

## Softsub, hardsub, and external subtitles

| Packaging | Result | Can be disabled? | Requires renderer/fonts at playback? |
| --- | --- | ---: | ---: |
| External | Separate subtitle file | Yes | Usually |
| Softsub | Subtitle track inside MKV | Yes | Text subtitles usually do |
| Hardsub | Pixels encoded into video | No | No, after encoding |

Converting ASS to PGS keeps subtitles selectable but rasterizes their appearance at a chosen resolution and frame/timing model. Hardsubbing rasterizes directly into the video and then subjects the result to video encoding.

## Dolby Vision fundamentals

Dolby Vision is an HDR system that combines a coded picture representation with dynamic metadata used to adapt the presentation to a target display. Unlike static HDR metadata alone, the Dolby Vision metadata can change over time.

Useful terms are:

- **BL — Base Layer**: the independently decodable base picture, often compatible with HDR10 on UHD Blu-ray;
- **EL — Enhancement Layer**: additional coded data used by some Dolby Vision profiles;
- **RPU — Reference Processing Unit metadata**: dynamic Dolby Vision metadata carried in the HEVC stream;
- **MEL — Minimum Enhancement Layer**: an enhancement layer with minimal residual contribution;
- **FEL — Full Enhancement Layer**: an enhancement layer that can carry additional residual picture information; and
- **profile**: a defined combination of coding, layer, compatibility, and metadata constraints.

### Dolby Vision on UHD Blu-ray

UHD Blu-ray Dolby Vision is commonly associated with profile 7. A disc can store a base HEVC layer and a dependent enhancement representation, with RPU metadata. Tool output may show two HEVC video tracks/PIDs, while a Matroska representation may combine the Dolby Vision data into one HEVC track.

Do not use “two video tracks” as the sole Dolby Vision test. Stream descriptors, HEVC NAL-unit content, and Dolby Vision metadata inspection provide stronger evidence.

### Profile 8.1 in this project

For compatible dual-layer Remux input, `dovi_tool -m 2 mux --discard` rewrites RPU metadata for profile 8.1 and discards enhancement-layer video, producing one base-plus-RPU HEVC track. A profile 7 FEL's picture residual is therefore not preserved merely because the RPU is retained.

Encode has separate bit-depth, crop, native-writing/injection, and verification requirements. These are documented together under [automatic HDR metadata handling](Video-Encoding-and-VapourSynth.md#automatic-hdr-metadata-handling).

## Format identification checklist

When diagnosing a track, record all of the following:

1. source layer: MPLS, M2TS, MKV, or elementary stream;
2. container track ID and transport PID, if applicable;
3. codec ID and transport stream type;
4. language, name, default, and forced flags;
5. duration and start timestamp;
6. video pixel format/color metadata or audio sample format/channel layout;
7. core/extension or base/enhancement relationships;
8. whether timestamps, delays, or gaps exist only in the source container; and
9. whether the selected operation is stream copy, lossless conversion, or lossy transcode.
