# 媒体基础概念

[English](Media-Fundamentals.md) | 简体中文

## 媒体的分层模型

| 层次 | 职责 | 示例 |
| --- | --- | --- |
| 原盘／应用结构 | 选择内容及播放顺序 | BDMV、MPLS、CLPI |
| 容器或传输流 | 存储并同步各条流 | MKV、MP4、M2TS |
| 轨道 | 标识一条媒体流 | 主视频、评论音轨、字幕 |
| 编码或基本流格式 | 表示编码样本 | H.264、HEVC、FLAC、PGS |
| 解码后样本 | 提供画面、声音或图形 | 视频帧、PCM、字幕位图 |

容器组织轨道，编解码格式描述样本。因此，MKV 既可以包含直接复制的 AVC，也可以包含重新编码的 HEVC。“把 MKV 转成 HEVC”通常指重新编码其中的视频轨，再封装进容器。

## 容器与轨道

**轨道（track）**是可独立寻址的视频、音频或字幕流。两条日语音轨即使用相同编码，也仍是不同轨道。顺序、语言、名称、默认／强制标记描述轨道，不改变解码样本。

**容器（container）**保存这些轨道，以及章节、字体或封面等附件和标签。章节与附件不是视听轨道。

轨道标识属于具体来源或工具：transport PID、MKVToolNix 输入轨道 ID、Matroska `TrackNumber` 和 GUI 行号不能互换，详见[开发者指南的标识符对照](BluraySubtitle-Developer-Guide.zh-Hans.md#轨道标识模型)。

## MKV 与 Matroska

Matroska 是基于 EBML 的容器。扩展名通常表示用途：`.mkv` 用于视频、`.mka` 用于音频、`.mks` 用于字幕、`.mk3d` 用于立体视频；它们不指定编码格式。

EBML 头之后的 Matroska `Segment` 包含：

| 元素 | 内容 |
| --- | --- |
| `Info` | 时间刻度、时长、标题、写入程序 |
| `Tracks` | 各轨道编码及元数据 |
| `Cluster` | 带时间戳的媒体块 |
| `Cues` | 跳转索引 |
| `Chapters`、`Attachments`、`Tags` | 导航及辅助元数据 |

### 为什么项目使用 MKV，而不是更常见的 MP4

MKV 能容纳项目所需的原盘音频、PGS／ASS 字幕、字体、章节和时间戳空档，MKVToolNix 则提供提取、裁切、追加和元数据编辑。MP4 广泛用于分发，但普通播放器实际支持的组合较窄：部分原盘轨道需要转换或外挂文件，ASS／PGS／字体也不是常规 MP4 内容。

容器本身不改变画质。只有每条所选流都有目标播放器支持的 MP4 映射时，转为 MP4 才只是 Remux；否则还需转换相应轨道。

## 基本流

**基本流（elementary stream）**只包含一条编码流，没有多轨容器。常见扩展名有 `.h264`／`.avc`、`.hevc`／`.h265`、`.ac3`、`.dts`、`.thd`、`.flac` 和 `.sup`。应检查实际内容，而不只相信后缀。

提取裸流可能丢失容器层的时间和元数据。例如，Matroska 能用时间戳表示音轨空档，裸 TrueHD 的连续帧字节本身却无法表达该空档。

## Demux、Mux 与 Remux

| 操作 | 含义 | 示例 |
| --- | --- | --- |
| Demux／抽流 | 分离所选编码流 | M2TS → HEVC + TrueHD + PGS |
| Mux／混流 | 组合流与元数据 | HEVC + FLAC + ASS → MKV |
| Remux／重混流 | 将编码流复制进新容器 | 所选原盘视频／音频 → MKV |

流复制不重新生成解码样本，因此不会给被复制的轨道增加编码世代损失。容器头、帧结构、时间戳、轨道顺序及元数据仍可改变，输出文件不必与来源逐字节相同。

BluraySubtitle 的 **原盘 Remux** 是工作流名称：视频直接复制，但仍可能执行所选音频转换和已记录的清理，详见 [README 音频控制](../../README.zh-Hans.md#音频控制)。MPLS 输入复制的是[播放列表时间窗口](Blu-ray-Disc-Structure.zh-Hans.md#intime-与-outtime)，不是完整 M2TS 文件。

## Decode、Encode 与 Transcode

**Decode／解码**产生可用样本，例如 HEVC 解码为视频帧、FLAC 解码为 PCM、PGS 解码为位图。**Encode／编码**把样本转为编码流。**Transcode／转码**组合解码与编码，中间可加入缩放、降噪或字幕渲染。

[压制管线](Video-Encoding-and-VapourSynth.zh-Hans.md#bluraysubtitle-压制管线)介绍 VapourSynth 与视频编码器的连接；字幕封装方式见[软字幕、硬字幕与外挂字幕](Media-Formats-and-Dolby-Vision.zh-Hans.md#软字幕硬字幕与外挂字幕)。

## 无损与有损

**无损编码**能精确重建输入样本，但仍可压缩数据，例如 PCM 转 FLAC。**有损编码**通过丢弃信息降低码率，例如蓝光常规 AVC／HEVC 和 AAC。

- 复制已有的有损轨道不会增加新的编码损失。
- 重新编码为有损格式会增加一代损失，即使码率很高或来源无损。
- 保留 PCM 样本不等于保留沉浸式音频元数据，详见[音频格式](Media-Formats-and-Dolby-Vision.zh-Hans.md#音频格式)。
- 位深和体积不能证明无损。标称 24-bit 的轨道可能只有 16 位有效精度；已有压缩无损音频转 FLAC 后也可能更大。

| 示例 | 结果 |
| --- | --- |
| 原盘 AVC 复制进 MKV | 视频重混流 |
| AVC 解码、滤镜处理后编码为 HEVC | 视频转码 |
| LPCM 编码为 FLAC | 无损音频转换 |
| LPCM 编码为 AAC | 有损音频转换 |

## 原盘、BDMV 与 BDRip

**原盘源**是保留蓝光应用结构的可读取备份、挂载镜像或目录。**BDMV** 是目录树而非单个媒体文件，其播放列表定义片段顺序与区间。目录结构及本项目的正片／SP 分类见[蓝光原盘结构](Blu-ray-Disc-Structure.zh-Hans.md)。

**BDRip** 和 **BDRemux** 是社区术语，并非精确文件格式。BDRip 通常指从蓝光制作的压制成品；BDRemux 通常保留源视频，将所选原盘内容重新封装进 MKV 等容器。
