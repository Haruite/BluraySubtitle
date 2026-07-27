# BluraySubtitle Wiki

This wiki explains the media concepts behind BluraySubtitle and connects them
to the project's implementation. It is intended for two audiences:

- users who need a reliable mental model of Blu-ray, Matroska, tracks, remuxing,
  encoding, subtitles, audio, video, and Dolby Vision; and
- developers who need the binary structures, timing rules, source-code map,
  and workflow invariants used by the application.

Start with [Media Fundamentals](Media-Fundamentals.md) if terms such as
*container*, *track*, *demux*, or *lossless* are new. Continue with
[Blu-ray Disc Structure](Blu-ray-Disc-Structure.md) for BDMV, MPLS, CLPI, M2TS,
playlist timing, and chapters. Codec and subtitle details are collected in
[Media Formats and Dolby Vision](Media-Formats-and-Dolby-Vision.md).
[Video Encoding and VapourSynth](Video-Encoding-and-VapourSynth.md) explains
codec selection, encoder presets, frame processing, and the project's encode path.

Developers should then read
[BluraySubtitle Developer Guide](BluraySubtitle-Developer-Guide.md), which
defines the project's meaning of **main MPLS** and **SP**, describes the
discovery and remux pipeline, and points to the relevant source files.

## Project terminology at a glance

The following definitions are project-specific and must not be confused with
terms from the Blu-ray specification:

- **Main MPLS**: a selected disc playlist whose authored playback content is
  the main feature, movie, or episode content. It is not necessarily the
  numerically first, largest, or longest playlist.
- **SP**: all additional disc content outside the selected main-playlist
  content. This includes other playlists, unchecked segments of a main MPLS,
  and useful M2TS files that are not covered by a playlist. `SP` is a
  BluraySubtitle content category, not a Blu-ray file format or standard term.
- **Original disc / Blu-ray source**: in normal project usage, a readable
  Blu-ray directory or mounted image that exposes the BDMV structure. The
  application does not make encrypted sectors readable by itself.
- **Remux**: copying selected encoded streams into a new container without
  re-encoding the video. A BluraySubtitle Remux job may still perform explicitly
  selected or documented audio conversion and cleanup, so the final file is not
  necessarily a byte-for-byte copy of every source stream.
- **Encode**: decoding and re-encoding video, with optional preprocessing, then
  muxing the result with the selected audio, subtitle, chapter, and metadata
  content.

## Suggested reading paths

### I only want to use the application

1. [Media Fundamentals](Media-Fundamentals.md)
2. [Blu-ray Disc Structure](Blu-ray-Disc-Structure.md), through “MPLS, M2TS,
   and CLPI: how they work together”
3. [Media Formats and Dolby Vision](Media-Formats-and-Dolby-Vision.md)
4. [Video Encoding and VapourSynth](Video-Encoding-and-VapourSynth.md), for Encode users
5. The main project [README](../../README.md)

### I want to understand or modify the implementation

1. All user-oriented pages above
2. [BluraySubtitle Developer Guide](BluraySubtitle-Developer-Guide.md)
3. [Media Pipeline Design and Tool Selection](../development/media-pipeline-and-tool-selection.md)
4. [Code Modification Standards](../development/code-standards.md)

## Scope

The wiki focuses on the parts of Blu-ray that affect identifying, extracting,
remuxing, encoding, and preserving audiovisual content. It explains navigation
files enough to locate authored playback paths, but it is not a complete
implementation guide for an HDMV virtual machine, BD-J, AACS, BD+, region
control, or disc authoring.

The binary details are based on the project's parsers, the public
[lw/BluRay wiki](https://github.com/lw/BluRay/wiki), and the specifications
and open-source implementations listed in [References](References.md).
