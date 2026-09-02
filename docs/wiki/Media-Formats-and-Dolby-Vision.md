# Media Formats, Subtitles, and Dolby Vision

English | [简体中文](Media-Formats-and-Dolby-Vision.zh-Hans.md)

This page summarizes the formats encountered in Blu-ray and BluraySubtitle. “Format” can mean a container, codec, elementary-stream representation, or subtitle model, so each section states which layer it describes.

## Video formats

### MPEG-2 Video

MPEG-2 Video appears on early Blu-ray titles and remains valid in the classic BD-ROM ecosystem. It is lossy and substantially less compression-efficient than AVC or HEVC for comparable visual quality.

### VC-1

VC-1 is a lossy video codec found on some early Blu-ray releases. Tool support is mature for playback and remuxing, but modern encode workflows rarely choose it as a target.

### AVC / H.264

AVC, standardized as H.264, is the most common video codec on 1080p Blu-ray. Typical disc video uses 8-bit 4:2:0 YCbCr. AVC is normally lossy, although the standard and some encoders provide lossless modes outside ordinary Blu-ray delivery practice.

`x264` is an AVC encoder. It is not a container and it does not create an MKV by itself; its elementary output is later muxed.

### MVC

Multiview Video Coding extends AVC for stereoscopic Blu-ray 3D. A base AVC view can be paired with a dependent MVC view. The disc may expose dependent-view relationships through extensions and subpaths rather than as an ordinary second video selected independently.

### HEVC / H.265

HEVC, standardized as H.265, is the primary video codec for Ultra HD Blu-ray. UHD material commonly uses 10-bit 4:2:0 YCbCr, Rec. 2020 signaling, and HDR transfer characteristics. HEVC is normally lossy in delivered media.

`x265` is an HEVC encoder. BluraySubtitle uses x265 10-bit or 12-bit output when preserving Dolby Vision metadata in its supported encode path.

### AV1

AV1 is a modern lossy video codec supported as an encode target by BluraySubtitle through SVT-AV1. AV1 is not the video codec used by the BDMV/UHD-BD sources handled here. The current project toolchain does not author AV1 Dolby Vision profile 10, so SVT-AV1 output omits Dolby Vision metadata with an explicit task message.

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

### PCM and Blu-ray LPCM

PCM stores sampled amplitude values directly. Blu-ray LPCM adds Blu-ray-specific framing and channel layout. PCM is uncompressed and lossless.

Common properties are:

- sample rate, such as 48, 96, or 192 kHz;
- bit depth, such as 16 or 24 bits;
- channel count and channel layout.

A nominal 24-bit track may contain only 16 bits of effective signal precision. Effective depth must be determined from decoded samples rather than container metadata alone.

### FLAC

FLAC is a lossless codec for PCM samples. It normally reduces the size of LPCM without changing decoded samples. Compression level changes encoding effort and file size, not decoded quality.

FLAC does not preserve immersive metadata models from TrueHD Atmos or DTS:X. Converting those formats to FLAC preserves only the decoded channel presentation produced by the chosen decoder.

BluraySubtitle preserves the detected effective PCM depth when writing FLAC. Its configurable FLAC compression levels default to 8.

### Dolby Digital / AC-3

AC-3 is a lossy perceptual audio codec. It is widely supported and is often embedded as a compatibility core alongside TrueHD on Blu-ray.

### Dolby Digital Plus / E-AC-3

E-AC-3 is a more capable lossy Dolby codec. It can carry more channels and features than AC-3 and is common in streaming; Blu-ray also defines primary and secondary E-AC-3 stream types.

### Dolby TrueHD and MLP

TrueHD is a lossless codec derived from Meridian Lossless Packing. Blu-ray can interleave an AC-3 compatibility core with TrueHD extension data, or carry a TrueHD-only presentation depending on the stream layout.

Dolby Atmos metadata can be carried with TrueHD. Atmos describes objects, beds, and rendering information beyond a fixed decoded channel stream. Decoding a selected presentation to PCM or FLAC does not retain the Atmos object metadata as Atmos.

Damaged TrueHD requires special caution. A container may retain a plausible overall duration even when transport loss or invalid frames cause an extracted or decoded stream to be shorter. MKVToolNix and the project’s normal demux path do not synthesize replacement TrueHD frames. Review decoder errors and compare decoded audio duration against video before discarding the source.

### DTS core

DTS core is a lossy codec and compatibility layer. A DTS-HD stream can include this core so older decoders can play a reduced representation.

### DTS-HD High Resolution Audio

DTS-HD HR is a lossy extension that improves capability and quality over the core but is not lossless.

### DTS-HD Master Audio

DTS-HD MA adds a lossless residual to a compatible DTS core. A capable decoder reconstructs the lossless master; a core-only decoder can play the lossy DTS representation.

### AAC

AAC is a lossy perceptual codec. BluraySubtitle uses the `fdkaac` frontend for AAC encoding. A configured bitrate of zero means automatic mode, implemented as FDK-AAC VBR mode 5.

### Opus

Opus is a modern lossy codec optimized across speech and music use cases. It is supported as an audio target in Encode, not as the Remux workflow’s lossless-audio conversion target. Automatic bitrate uses 128 kbps for up to two channels and 256 kbps for more channels.

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

The project's `SRT` model reads numbered blocks, stores start/end time and multiline text, shifts timestamps when appending, and renumbers retained cues when cutting. A cue is retained by the current cut operation only when its whole interval lies inside the selected range.

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

BluraySubtitle's `Ass` model detects SSA v4 or ASS v4+ style sections, reads the declared `Format:` attributes, converts event times to timed values, and preserves commas in the final text field. It can shift, append, cut, and write the structured events. The SRT-to-ASS path creates a v4+ header and translates basic bold, underline, italic, and font-color markup into ASS override tags.

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

BluraySubtitle’s `PGS` class reads SUP packet headers, computes the maximum end time, shifts timestamps when appending, and selects/rebases packets when cutting. The project also contains an ASS-to-SUP path using its bundled conversion components.

### IGS / Interactive Graphics

IGS is used for interactive menus and button states. It is also bitmap and composition based, but adds pages, button-over groups, states, navigation commands, and interaction timing. Media tools sometimes label an IGS-only M2TS as a subtitle stream, but it is not an ordinary PGS subtitle.

BluraySubtitle can identify IGS stream type `0x91` and extract representative button-state images for supported SP handling.

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

BluraySubtitle’s supported remux path takes compatible base and enhancement inputs and runs `dovi_tool -m 2 mux --discard`. This rewrites the RPU for profile 8.1 and discards the enhancement-layer video, leaving a single-layer base-plus-RPU result. In the encode path:

- x265 10-bit or 12-bit output can receive extracted RPU metadata and retain Dolby Vision as profile 8.1;
- x265 8-bit and x264 are rejected when Dolby Vision preservation is required; and
- SVT-AV1 encoding proceeds without Dolby Vision metadata because the current toolchain does not author AV1 Dolby Vision profile 10.

Profile conversion is not a promise that every component of a profile 7 FEL is reproduced by a profile 8.1 result. RPU preservation and enhancement-layer residual preservation are different questions.

### Project workflow

For a Dolby Vision encode sourced from MKV, the project conceptually:

1. identifies and extracts the HEVC video track;
2. uses `dovi_tool` to demux/extract the base representation and RPU metadata;
3. when an automatic physical crop is active, exports every L5 active-area preset, subtracts the crop margins, and creates a task-owned edited RPU;
4. encodes the processed base video with a supported x265 output depth;
5. writes the prepared RPU in that x265 run when the actual executable advertises the native options and the VBV/mastering-display prerequisites are already present, otherwise injects it afterward with `dovi_tool`;
6. falls back to injection if native output verification fails, verifies the encoded HEVC contains RPU metadata, and also verifies HDR10+ when the source carried it; and
7. muxes the final container, then requires profile 8 and an RPU frame count matching the VPy output when it verifies that container. Active HDR10+ and automatically supplied static fields are also checked again.

Both native x265 writing and fallback injection therefore consume the same crop-adjusted RPU. Source HDR10+ metadata is retained when supported, but the current workflow does not remeasure its brightness statistics after cropping.

For compatible dual-layer remux input, it uses `dovi_tool` mode 2 to create the supported single-layer profile 8.1 result; enhancement-layer picture residuals are not retained.

Every generated intermediate is checked. Missing base-layer, RPU, combined, injected, or verified output is treated as a failure rather than silently producing a non-Dolby-Vision file under a Dolby Vision request.

A final-container verification mismatch is handled differently from a broken intermediate: the published MKV is retained, the row completes with a warning, and a non-overwriting HDR report records the mismatch for diagnosis.

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
