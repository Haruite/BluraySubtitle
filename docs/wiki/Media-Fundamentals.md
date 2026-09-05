# Media Fundamentals

English | [简体中文](Media-Fundamentals.zh-Hans.md)

## Media as layers

| Layer | Responsibility | Examples |
| --- | --- | --- |
| Disc/application structure | Select content and playback order | BDMV, MPLS, CLPI |
| Container or transport | Store and synchronize streams | MKV, MP4, M2TS |
| Track | Identify one media stream | main video, commentary audio, subtitles |
| Codec or elementary format | Represent coded samples | H.264, HEVC, FLAC, PGS |
| Decoded samples | Supply pictures, sound, or graphics | video frames, PCM, subtitle bitmaps |

A container organizes tracks; a codec describes their samples. An MKV may therefore contain either copied AVC video or newly encoded HEVC. “Convert MKV to HEVC” usually means re-encoding its video track, then muxing that track into a container.

## Container and track

A **track** is an independently addressable video, audio, or subtitle stream. Two Japanese audio tracks remain distinct even when they use the same codec. Track order, language, name, and default/forced flags describe the stream without changing its decoded samples.

A **container** holds those tracks alongside chapters, attachments such as fonts or cover art, and tags. Chapters and attachments are not audiovisual tracks.

Track identifiers belong to their source or tool: a transport PID, MKVToolNix input track ID, Matroska `TrackNumber`, and GUI row number are not interchangeable. See the [developer guide's identifier map](BluraySubtitle-Developer-Guide.md#track-identity-model).

## MKV and Matroska

Matroska is an EBML-based container. Its extensions conventionally indicate the intended content: `.mkv` for video, `.mka` for audio, `.mks` for subtitles, and `.mk3d` for stereoscopic video. They do not specify a codec.

After the EBML header, a Matroska `Segment` contains:

| Element | Contents |
| --- | --- |
| `Info` | Time scale, duration, title, writing application |
| `Tracks` | Codec and metadata for each track |
| `Cluster` | Timestamped media blocks |
| `Cues` | Seeking indexes |
| `Chapters`, `Attachments`, `Tags` | Navigation and supporting metadata |

### Why BluraySubtitle uses MKV instead of MP4

MKV accommodates the project's disc audio, PGS/ASS subtitles, fonts, chapters, and timestamp gaps, with MKVToolNix providing extraction, trimming, append, and metadata editing. MP4 is widely supported for delivery, but its practical player-compatible subset is narrower: some disc tracks need conversion or external files, and ASS/PGS/fonts are not ordinary MP4 choices.

Container choice alone does not change picture quality. Moving to MP4 is a remux only if every selected stream has a compatible mapping supported by the target player; otherwise, conversion is required.

## Elementary stream

An **elementary stream** contains one coded stream without a multi-track container. Common extensions include `.h264`/`.avc`, `.hevc`/`.h265`, `.ac3`, `.dts`, `.thd`, `.flac`, and `.sup`. Inspect the contents rather than trusting the filename suffix.

Raw extraction can lose container-only timing and metadata. For example, Matroska can represent an audio gap with timestamps, while raw TrueHD frame bytes cannot represent that gap by themselves.

## Demux, mux, and remux

| Operation | Meaning | Example |
| --- | --- | --- |
| Demux | Separate selected encoded streams | M2TS → HEVC + TrueHD + PGS |
| Mux | Combine streams and metadata | HEVC + FLAC + ASS → MKV |
| Remux | Copy encoded streams into a new container | Selected disc video/audio → MKV |

Stream copy does not regenerate decoded samples, so copied tracks have no new codec generation loss. Container headers, framing, timestamps, track order, and metadata can still change; the output file need not be byte-identical to its source.

BluraySubtitle's **Blu-ray Remux** is a workflow name: it copies video but may apply the selected audio conversion and documented cleanup. See the [README's audio controls](../../README.md#audio-controls). For MPLS inputs, the copied content follows [playlist windows](Blu-ray-Disc-Structure.md#intime-and-outtime), rather than complete M2TS files.

## Decode, encode, and transcode

**Decode** produces usable samples, such as video frames from HEVC, PCM from FLAC, or bitmaps from PGS. **Encode** turns samples into a coded stream. **Transcode** combines decoding and encoding, optionally with resizing, denoising, or subtitle rendering between them.

The [Encode pipeline](Video-Encoding-and-VapourSynth.md#the-bluraysubtitle-encode-pipeline) shows how VapourSynth and the video encoder connect. Subtitle packaging is explained in [softsub, hardsub, and external subtitles](Media-Formats-and-Dolby-Vision.md#softsub-hardsub-and-external-subtitles).

## Lossless and lossy

**Lossless** encoding reconstructs its input samples exactly; it can still compress them, as FLAC does with PCM. **Lossy** encoding discards information to reduce bitrate, as normal Blu-ray AVC/HEVC and AAC do.

- Copying an already lossy track introduces no new encoding loss.
- Re-encoding to a lossy format adds a generation of loss, even at a high bitrate or from a lossless source.
- Preserving PCM samples does not guarantee preservation of immersive audio metadata; see [audio formats](Media-Formats-and-Dolby-Vision.md#audio-formats).
- Bit depth and file size do not establish losslessness. A nominal 24-bit track may have only 16 effective bits; converting already compressed lossless audio to FLAC can increase its size.

| Example | Result |
| --- | --- |
| AVC copied from disc into MKV | Video remux |
| AVC decoded, filtered, and encoded as HEVC | Video transcode |
| LPCM encoded as FLAC | Lossless audio conversion |
| LPCM encoded as AAC | Lossy audio conversion |

## Original disc, BDMV, and BDRip

An **original disc source** is a readable backup, mounted image, or directory retaining the Blu-ray application structure. **BDMV** is a directory tree, not one media file; its playlists define the clip order and intervals. See [Blu-ray Disc Structure](Blu-ray-Disc-Structure.md) for its layout and the project's main-content/SP categories.

**BDRip** and **BDRemux** are community terms, not precise file formats. BDRip usually describes a Blu-ray-derived encode; BDRemux usually preserves source video while reorganizing selected disc content into a container such as MKV.
