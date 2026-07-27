# Media Fundamentals

This page introduces the concepts used throughout BluraySubtitle. The most
important distinction is this:

> A container organizes tracks. A codec defines how the samples in a track are
> represented.

An `.mkv` file is therefore not a video format in the same sense as H.264 or
HEVC. Matroska is the container; H.264, HEVC, FLAC, TrueHD, PGS, and other
formats can be the contents of its tracks.

## Media as layers

A useful mental model is a stack of layers:

| Layer | Question it answers | Examples |
| --- | --- | --- |
| Disc/application structure | What should the player play, and in what order? | BDMV, MPLS, CLPI |
| Transport or container | How are streams stored and synchronized? | M2TS, MKV, MP4 |
| Track | What independent media stream is this? | main video, commentary audio, PGS subtitles |
| Codec or elementary format | How are the samples represented? | H.264, HEVC, LPCM, FLAC, AC-3, PGS |
| Decoded samples | What does the decoder produce? | video frames, PCM audio samples, subtitle bitmaps |

Confusing these layers leads to common mistakes. “Convert MKV to HEVC” mixes a
container with a codec. The precise request is usually “decode the video track
from an MKV, encode it as HEVC, and mux the resulting track into an MKV.”

## Container and track

A **container** stores one or more synchronized media tracks plus metadata.
Typical tracks are:

- one or more video tracks;
- one or more audio tracks;
- subtitle tracks;
- chapters;
- attachments such as fonts or cover art; and
- tags and language, name, default, and forced-display metadata.

A **track** is one independently addressable stream inside the container. Two
Japanese audio tracks in the same MKV are still separate tracks even when they
use the same codec. Track order, language, name, and default/forced flags are
metadata about those streams; they are not part of the decoded sound or image.

Track numbering is tool-specific. A transport-stream PID, an MKVToolNix track
ID, a Matroska `TrackNumber`, and a GUI row number are different identifiers.
BluraySubtitle must map between them explicitly rather than assuming that the
same integer means the same track at every layer.

## MKV and Matroska

**Matroska** is an extensible multimedia container based on EBML. `.mkv` is the
usual extension for a Matroska file containing video. Related conventions are:

- `.mka` for audio-focused Matroska files;
- `.mks` for subtitle-focused Matroska files; and
- `.mk3d` for stereoscopic video.

These extensions describe the intended container use, not a different codec.
Matroska can hold many video, audio, and subtitle formats and can represent
chapters, attachments, tags, track language, track names, and timestamp gaps.

At a high level, a Matroska file contains an EBML header and a `Segment`.
Important `Segment` children include:

- `Info`: time scale, duration, title, and writing application;
- `Tracks`: codec and metadata for each track;
- `Cluster`: timestamped media blocks;
- `Cues`: seeking indexes;
- `Chapters`;
- `Attachments`; and
- `Tags`.

Matroska timestamps belong to the container timeline. Extracting a raw
elementary stream can discard container-only information. For example, a
timestamp gap can exist in an MKV, while an extracted raw TrueHD stream is just
consecutive frame bytes and cannot preserve that Matroska gap by itself.

### Why BluraySubtitle uses MKV instead of MP4

MP4 is an excellent delivery container and is widely supported by browsers,
phones, televisions, and editing software. It is not inherently lower quality:
container choice does not change decoded video quality. BluraySubtitle uses MKV
because the project is primarily preserving and reorganizing disc content rather
than targeting one restricted distribution platform.

In this workflow, Matroska provides a practical home for:

- multiple video, audio, and subtitle tracks with independent languages, names,
  and default/forced flags;
- the codecs commonly found on Blu-ray and in archival remuxes, including
  lossless audio, PGS, and ASS;
- chapters, tags, timestamp behavior, and font attachments needed by ASS;
- `.mka` audio-only and `.mks` subtitle-only companion outputs; and
- MKVToolNix operations for extraction, append, trim, chapter writing, attachment
  handling, and metadata verification.

The ISO Base Media File Format underlying MP4 is extensible, and specialized
MP4 variants can carry more than the subset accepted by everyday players.
Practical MP4 interoperability is nevertheless narrower: ASS and PGS are not
ordinary MP4 subtitle choices, fonts are not handled like Matroska attachments,
and some Blu-ray audio formats require conversion or player-specific mappings.
Choosing MP4 could therefore force track conversion, loss of presentation
metadata, or external sidecar files.

Use MP4 when a target device or service requires it and its supported codec
subset is known. Use MKV here when preserving the selected source tracks and
their metadata is the priority. Changing MKV to MP4 is a remux only when every
selected stream has a compatible MP4 mapping; otherwise conversion is required.

## Elementary stream

An **elementary stream** contains one coded stream without the surrounding
multi-track container. Common examples include:

- `.h264` or `.avc` for an AVC elementary stream;
- `.hevc` or `.h265` for an HEVC elementary stream;
- `.ac3`, `.dts`, `.thd`, or `.flac` for audio; and
- `.sup` for Blu-ray Presentation Graphics subtitles.

File extensions are conventions rather than proof. Reliable software inspects
the bitstream or container metadata instead of trusting the suffix alone.

## Demux

**Demultiplexing**, usually shortened to **demuxing**, separates selected tracks
from a container or transport stream.

Examples:

- M2TS → HEVC + TrueHD + PGS;
- MKV → FLAC + ASS; or
- MPLS-backed Blu-ray playback → the selected streams from several time-bounded
  M2TS clips.

Demuxing does not inherently decode or re-encode the stream. A correct
stream-copy demux normally preserves the encoded access units. It can still
change surrounding framing, timestamps, delay representation, or codec-private
headers because the source and destination representations differ.

Demuxing an MPLS is more than concatenating files. Each playlist `PlayItem`
selects a clip and an `INTime`/`OUTTime` window. The same M2TS can be reused with
different windows, and different play items can have different track layouts.

## Mux and remux

**Multiplexing**, or **muxing**, combines tracks and metadata into a container.
**Remuxing** reads tracks from an existing container or disc structure and
muxes them into a new container without re-encoding the streams being copied.

A pure remux:

1. reads encoded packets;
2. adjusts their container timestamps and metadata as needed; and
3. writes those packets to a new container.

The decoded picture or sound is not regenerated, so there is no codec
generation loss for copied streams. The output file is nevertheless not
byte-identical to the input: container headers, interleaving, timestamps,
track order, names, language tags, chapters, and attachments can change.

In BluraySubtitle, “Blu-ray Remux” names a product workflow. Video is not
re-encoded, but the workflow may:

- keep or exclude selected tracks;
- trim to MPLS play-item windows and selected chapters;
- join clips;
- apply track languages and chapters;
- convert selected lossless audio to FLAC when that option is enabled;
- remove documented silent or exact duplicate audio; and
- combine compatible Dolby Vision layers.

For that reason, “Remux” should not be read as “copy every byte from the disc.”

## Decode, encode, and transcode

**Decoding** turns a compressed or coded track into usable samples:

- H.264/HEVC → video frames;
- FLAC/TrueHD/AAC → PCM audio; or
- PGS → subtitle bitmaps and composition instructions.

**Encoding** turns samples into a coded stream. Video encoding usually involves
prediction, transform, quantization, entropy coding, and rate control. Audio
encoding may be lossless or lossy.

**Transcoding** is the end-to-end act of decoding one representation and
encoding another. It may also include preprocessing such as resizing,
denoising, debanding, color conversion, or subtitle rendering.

BluraySubtitle’s Encode workflow normally has these conceptual stages:

1. remux the selected Blu-ray content to a stable staging source;
2. decode video through the processing pipeline;
3. optionally process frames with VapourSynth;
4. encode with x264, x265, or SVT-AV1;
5. process selected audio according to its per-track policy;
6. package subtitles as external, softsub, or hardsub content; and
7. mux and verify the final output.

**Soft subtitles** remain a selectable subtitle track. **Hard subtitles** are
rendered into video frames before encoding and can no longer be disabled
during playback.

## Lossless and lossy

The words **lossless** and **lossy** describe whether an encoding step can
reconstruct its input samples exactly.

### Lossless

A lossless codec reconstructs the original decoded samples bit-for-bit.
Examples include:

- FLAC for PCM audio;
- lossless TrueHD/MLP audio;
- the lossless extension of DTS-HD Master Audio; and
- encoder-specific lossless video modes.

Lossless does not mean uncompressed. FLAC is compressed, but it reconstructs
the input PCM exactly.

### Lossy

A lossy codec intentionally discards information to reduce bitrate. Examples
include:

- AVC/H.264 and HEVC/H.265 in their normal Blu-ray usage;
- MPEG-2 Video and VC-1 in normal disc usage;
- AC-3, E-AC-3, AAC, DTS core, and Opus.

Loss can be perceptually small, but the decoded output is not identical to the
encoder input.

### Important qualifications

- **A lossless container operation is not a codec.** Remuxing can preserve
  encoded tracks exactly even when those tracks were originally encoded with a
  lossy codec.
- **Lossless-to-lossless conversion preserves decoded samples, not necessarily
  ancillary metadata.** TrueHD to FLAC can preserve decoded PCM but cannot
  preserve Atmos object metadata as Atmos metadata in FLAC.
- **A lossless source does not make a lossy encode lossless.** LPCM → AAC is
  lossy.
- **Repeated lossy encoding causes generation loss.** AVC → raw frames → HEVC
  introduces another lossy generation even if the new bitrate is high.
- **Bit depth is not the same as losslessness.** A 24-bit container can carry
  only 16 effective bits, and reducing bit depth can be lossy unless the
  discarded bits contain no information.

## Original disc, BDMV, and BDRip

In this project, an **original disc source** generally means a readable backup,
mounted image, or directory that retains the Blu-ray application structure.
The key directory is `BDMV`; its sibling is commonly `CERTIFICATE`.

**BDMV** is not a single media file. It is the application and media tree that
tells a Blu-ray player:

- which titles exist;
- which navigation object starts;
- which playlists define playback;
- which M2TS clips and time windows form each playlist;
- which streams belong to each play item; and
- where chapter and entry marks occur.

**BDRip** is a community term rather than one precise format. It usually means
a derived release made from Blu-ray, often with video processing and
re-encoding. **BDRemux** generally means a release that preserves the source
video stream and remuxes selected disc content into a consumer container such
as MKV.

## A practical example

Assume an MPLS defines:

| Play item | M2TS clip | Window | Contents |
| ---: | --- | --- | --- |
| 0 | `00010.m2ts` | 00:00–00:12 | studio card |
| 1 | `00020.m2ts` | 00:05–24:10 | episode |
| 2 | `00030.m2ts` | 00:00–00:08 | copyright bumper |

The playlist is not equivalent to any one M2TS. It is a virtual timeline made
from three windows. A main-content selection may retain only the episode
window. The unselected studio card and bumper can then become SP content under
the project’s rules.

If the selected video track is AVC and it is copied into MKV unchanged, that is
a video remux. If it is decoded, filtered, and encoded as HEVC, that is a video
transcode. If the LPCM audio is encoded to FLAC, that audio conversion is
lossless. If it is encoded to AAC, that audio conversion is lossy.

## Common misconceptions

### “The largest M2TS is the movie”

Often, but not reliably. Seamless branching, reused clips, multi-angle content,
episode concatenation, and playlist obfuscation can make file size misleading.
The authored playback path is expressed by MPLS play items and their windows.

### “The longest MPLS is always the main MPLS”

No. A decoy playlist can be longer, and one disc may contain several legitimate
main playlists. BluraySubtitle allows manual selection because semantic intent
cannot always be inferred from duration.

### “MKV means the video was encoded”

No. MKV is a container. The video inside may be a direct copy from the disc or
a new encode.

### “Remux means every track is retained”

No. A remux normally selects tracks. BluraySubtitle also applies its documented
audio conversion and cleanup policies.

### “Lossless audio always gives a smaller file”

No. FLAC compresses PCM efficiently, but already compressed lossless formats
can be smaller than their FLAC decode/re-encode result. File size and
losslessness answer different questions.

### “A raw extracted stream preserves the whole source timeline”

Not necessarily. Container timestamps, edits, delays, and gaps may not have an
equivalent representation in the raw elementary stream.
