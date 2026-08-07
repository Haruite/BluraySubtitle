# References and Further Reading

English | [简体中文](References.zh-Hans.md)

The wiki is an explanatory layer over the project’s source and verified behavior. When a public summary, a tool, and a real disc disagree, inspect the actual bytes and the code path used by the application.

## Project sources

- [BluraySubtitle README](../../README.md)
- [Media Pipeline Design and Tool Selection](../development/media-pipeline-and-tool-selection.md)
- [Code Modification Standards](../development/code-standards.md)
- [`src/bdmv`](../../src/bdmv)
- [`src/domain/media`](../../src/domain/media)
- [`src/domain/subtitles`](../../src/domain/subtitles)
- [`src/runtime`](../../src/runtime)
- [`tests`](../../tests)

## Blu-ray application format

- [lw/BluRay wiki](https://github.com/lw/BluRay/wiki), especially Application Format, MPLS, PlayItem, PlayList, PlayListMark, STNTable, CLPI, SequenceInfo, ProgramInfo, and M2TS.
- [Blu-ray Disc Association format specification overview](https://blu-raydisc.info/format-spec/rom3-spec.php).
- [VideoLAN libbluray](https://code.videolan.org/videolan/libbluray), an open-source Blu-ray playback and navigation implementation.

The lw/BluRay wiki states that its content is available under the [Creative Commons Attribution-ShareAlike license](https://creativecommons.org/licenses/by-sa/3.0/). The binary field names and structural relationships in this documentation were checked against that wiki, the project source, and cited open-source implementations. The explanations here are newly written and project-specific.

The complete Blu-ray specification books are licensed by the Blu-ray Disc Association and are not reproduced here. Public reverse-engineering documentation and open-source implementations can be incomplete; reserved fields and later-format extensions require particular care.

## MPEG transport streams

- [ISO/IEC 13818-1 overview](https://www.iso.org/standard/87619.html) for MPEG systems/transport streams.
- [FFmpeg MPEG-TS implementation](https://github.com/FFmpeg/FFmpeg/blob/master/libavformat/mpegts.c) for an additional open-source parser reference.
- [tsMuxer](https://github.com/justdan96/tsMuxer) for M2TS demux/mux, Blu-ray structures, stream readers, and PGS handling.
- [mpv manual: Blu-ray input](https://mpv.io/manual/stable/#blu-ray) for `bd://mpls/<number>` and `--bluray-device`.

## Matroska and MKVToolNix

- [Matroska data layout](https://www.matroska.org/technical/diagram.html)
- [Matroska element specification](https://www.matroska.org/technical/elements.html)
- [Matroska element ordering](https://www.matroska.org/technical/ordering.html)
- [Matroska subtitle storage](https://www.matroska.org/technical/subtitles.html)
- [Matroska attachments](https://www.matroska.org/technical/attachments.html)
- [MKVToolNix](https://gitlab.com/mbunkus/mkvtoolnix)
- [MKVToolNix documentation](https://mkvtoolnix.download/docs.html)

## Video and color

- [ITU-T H.264](https://www.itu.int/rec/T-REC-H.264)
- [ITU-T H.265](https://www.itu.int/rec/T-REC-H.265)
- [ITU-R BT.709](https://www.itu.int/rec/R-REC-BT.709)
- [ITU-R BT.2020](https://www.itu.int/rec/R-REC-BT.2020)
- [ITU-R BT.2100](https://www.itu.int/rec/R-REC-BT.2100)
- [VCB-Studio public guides](https://github.com/vcb-s/guides), particularly the introductory video, Blu-ray, workflow/tools, and encoder chapters.

## Encoding and frame processing

- [AV1 Bitstream and Decoding Process Specification](https://aomediacodec.github.io/av1-spec/av1-spec.pdf)
- [x265 preset documentation](https://x265.readthedocs.io/en/stable/presets.html)
- [x265 command-line options](https://x265.readthedocs.io/en/stable/cli.html)
- [SVT-AV1 documentation and source](https://gitlab.com/AOMediaCodec/SVT-AV1)
- [SVT-AV1 parameter reference](https://gitlab.com/AOMediaCodec/SVT-AV1/-/blob/master/Docs/Parameters.md)
- [VapourSynth documentation](https://www.vapoursynth.com/doc/)
- [VapourSynth getting started](https://www.vapoursynth.com/doc/gettingstarted.html)
- [VapourSynth plugin installation](https://www.vapoursynth.com/doc/installation.html#plugins-and-scripts)
- [L-SMASH-Works VapourSynth source filters](https://github.com/HomeOfAviSynthPlusEvolution/L-SMASH-Works/tree/master/VapourSynth)
- [FFMS2](https://github.com/FFMS/ffms2)
- [BestSource](https://github.com/vapoursynth/bestsource)

## Audio

- [FLAC format and tools](https://xiph.org/flac/documentation.html)
- [Opus specification, RFC 6716](https://www.rfc-editor.org/rfc/rfc6716)
- [FFmpeg codec documentation](https://ffmpeg.org/ffmpeg-codecs.html)
- [Dolby technologies](https://professional.dolby.com/technologies/)

Codec trademarks identify their respective technologies and owners. The tables in this wiki describe interoperability and project behavior; they are not licensing statements.

## Subtitles

- [Matroska codec specifications](https://www.matroska.org/technical/codec_specs.html) for Matroska subtitle codec identifiers and storage.
- [tsMuxer PGS reader](https://github.com/justdan96/tsMuxer/blob/master/tsMuxer/pgsStreamReader.cpp) as an open-source Presentation Graphics implementation reference.
- [Aegisub ASS tags](https://aegisub.org/docs/latest/ass_tags/) for ASS styling and override tags.

## Dolby Vision

- [An Introduction to Dolby Vision](https://professional.dolby.com/siteassets/pdfs/dolby-vision-whitepaper_an-introduction-to-dolby-vision_0916.pdf)
- [Dolby Vision streams within the ISO Base Media File Format](https://professionalsupport.dolby.com/s/article/Dolby-Vision-streams-within-the-ISO-Base-Media-File-Format)
- [dovi_tool](https://github.com/quietvoid/dovi_tool)

Profile and device support can evolve. The project behavior documented here is the behavior implemented and tested by the current repository, not a general promise that all Dolby Vision profiles can be converted without loss of profile features.
