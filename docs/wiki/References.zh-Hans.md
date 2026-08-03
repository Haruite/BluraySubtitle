# 参考资料与延伸阅读

[English](References.md) | 简体中文

本文档是建立在项目源码和经验证行为之上的解释层。如果公开资料、工具行为与实际光盘相互矛盾，应当检查真实字节，以及应用程序实际执行的代码路径。

## 项目资料

- [BluraySubtitle README](../../README.zh-Hans.md)
- [媒体管线设计与工具选择](../development/media-pipeline-and-tool-selection.zh-Hans.md)
- [代码修改规范](../development/code-standards.zh-Hans.md)
- [`src/bdmv`](../../src/bdmv)
- [`src/domain/media`](../../src/domain/media)
- [`src/domain/subtitles`](../../src/domain/subtitles)
- [`src/runtime`](../../src/runtime)
- [`tests`](../../tests)

## Blu-ray 应用格式

- [lw/BluRay wiki](https://github.com/lw/BluRay/wiki)，尤其是 Application Format、MPLS、PlayItem、PlayList、PlayListMark、STNTable、CLPI、SequenceInfo、ProgramInfo 和 M2TS 等页面。
- [Blu-ray Disc Association 格式规范概览](https://blu-raydisc.info/format-spec/rom3-spec.php)。
- [VideoLAN libbluray](https://code.videolan.org/videolan/libbluray)，一个开源的 Blu-ray 播放与导航实现。

lw/BluRay wiki 声明其内容采用 [知识共享署名—相同方式共享许可协议](https://creativecommons.org/licenses/by-sa/3.0/)。本文档中的二进制字段名和结构关系参考了该 wiki，并与项目源码及所引用的开源实现进行了核对；正文解释为针对本项目重新编写的内容，并包含项目特有的行为。

完整的 Blu-ray 规范由 Blu-ray Disc Association 授权，本文档不予转载。公开的逆向工程资料和开源实现可能并不完整；处理保留字段及后期格式扩展时尤其需要谨慎。

## MPEG 传输流

- [ISO/IEC 13818-1 概览](https://www.iso.org/standard/87619.html)，用于了解 MPEG 系统及传输流。
- [FFmpeg MPEG-TS 实现](https://github.com/FFmpeg/FFmpeg/blob/master/libavformat/mpegts.c)，可作为另一份开源解析器参考。
- [tsMuxer](https://github.com/justdan96/tsMuxer)，可参考其中的 M2TS 解复用/复用、Blu-ray 结构、流读取器和 PGS 处理实现。
- [mpv 手册：Blu-ray 输入](https://mpv.io/manual/stable/#blu-ray)，用于核对 `bd://mpls/<编号>` 和 `--bluray-device`。

## Matroska 与 MKVToolNix

- [Matroska 数据布局](https://www.matroska.org/technical/diagram.html)
- [Matroska 元素规范](https://www.matroska.org/technical/elements.html)
- [Matroska 元素顺序](https://www.matroska.org/technical/ordering.html)
- [Matroska 字幕存储](https://www.matroska.org/technical/subtitles.html)
- [Matroska 附件](https://www.matroska.org/technical/attachments.html)
- [MKVToolNix](https://gitlab.com/mbunkus/mkvtoolnix)
- [MKVToolNix 文档](https://mkvtoolnix.download/docs.html)

## 视频与色彩

- [ITU-T H.264](https://www.itu.int/rec/T-REC-H.264)
- [ITU-T H.265](https://www.itu.int/rec/T-REC-H.265)
- [ITU-R BT.709](https://www.itu.int/rec/R-REC-BT.709)
- [ITU-R BT.2020](https://www.itu.int/rec/R-REC-BT.2020)
- [ITU-R BT.2100](https://www.itu.int/rec/R-REC-BT.2100)
- [VCB-Studio 公开教程](https://github.com/vcb-s/guides)，尤其是视频基础、Blu-ray、工作流与工具以及编码器等前几章。

## 压制与帧处理

- [AV1 位流与解码过程规范](https://aomediacodec.github.io/av1-spec/av1-spec.pdf)
- [x265 preset 文档](https://x265.readthedocs.io/en/stable/presets.html)
- [x265 命令行参数](https://x265.readthedocs.io/en/stable/cli.html)
- [SVT-AV1 文档与源码](https://gitlab.com/AOMediaCodec/SVT-AV1)
- [SVT-AV1 参数参考](https://gitlab.com/AOMediaCodec/SVT-AV1/-/blob/master/Docs/Parameters.md)
- [VapourSynth 文档](https://www.vapoursynth.com/doc/)
- [VapourSynth 入门](https://www.vapoursynth.com/doc/gettingstarted.html)
- [VapourSynth 插件安装](https://www.vapoursynth.com/doc/installation.html#plugins-and-scripts)
- [L-SMASH-Works VapourSynth 源滤镜](https://github.com/HomeOfAviSynthPlusEvolution/L-SMASH-Works/tree/master/VapourSynth)
- [FFMS2](https://github.com/FFMS/ffms2)
- [BestSource](https://github.com/vapoursynth/bestsource)

## 音频

- [FLAC 格式与工具](https://xiph.org/flac/documentation.html)
- [Opus 规范 RFC 6716](https://www.rfc-editor.org/rfc/rfc6716)
- [FFmpeg 编解码器文档](https://ffmpeg.org/ffmpeg-codecs.html)
- [Dolby 技术](https://professional.dolby.com/technologies/)

各编解码器商标用于标识相应技术及其所有者。本文档中的表格描述互操作性和项目行为，不构成任何许可声明。

## 字幕

- [Matroska 编解码器规范](https://www.matroska.org/technical/codec_specs.html)，可参考 Matroska 字幕编解码器标识及存储方式。
- [tsMuxer PGS 读取器](https://github.com/justdan96/tsMuxer/blob/master/tsMuxer/pgsStreamReader.cpp)，可作为开源的 Presentation Graphics 实现参考。
- [Aegisub ASS 标签](https://aegisub.org/docs/latest/ass_tags/)，用于了解 ASS 样式和覆盖标签。

## Dolby Vision

- [Dolby Vision 简介](https://professional.dolby.com/siteassets/pdfs/dolby-vision-whitepaper_an-introduction-to-dolby-vision_0916.pdf)
- [ISO 基础媒体文件格式中的 Dolby Vision 码流](https://professionalsupport.dolby.com/s/article/Dolby-Vision-streams-within-the-ISO-Base-Media-File-Format)
- [dovi_tool](https://github.com/quietvoid/dovi_tool)

Profile 和设备支持可能随时间演进。本文档描述的是当前仓库已经实现并测试的项目行为，并不承诺所有 Dolby Vision Profile 都能在不损失 Profile 特性的情况下完成转换。
