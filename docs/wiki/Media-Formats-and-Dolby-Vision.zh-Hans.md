# 媒体格式、字幕与 Dolby Vision

[English](Media-Formats-and-Dolby-Vision.md) | 简体中文

本页汇总蓝光原盘和 BluraySubtitle 中常见的格式。“格式”可能指容器、编解码器、基本流表示或字幕模型，因此每一节都会明确其所在层次。

## 视频格式

| 编码 | 常见用途与特征 |
| --- | --- |
| MPEG-2 Video | 早期蓝光有损视频，压缩效率低于 AVC／HEVC |
| VC-1 | 早期蓝光有损视频，通常用于重混流或解码而非新压制目标 |
| AVC / H.264 | 常见 1080p 蓝光视频，通常为 8-bit 4:2:0；常规原盘发行使用有损编码 |
| MVC | AVC 立体扩展：基础视图加依赖视图，可通过扩展／子路径寻址 |
| HEVC / H.265 | UHD 蓝光主要编码，常见 10-bit 4:2:0 及 Rec. 2020／HDR 信令 |
| AV1 | 项目通过 SVT-AV1 提供的压制目标，不是这里的 BDMV／UHD-BD 来源编码 |

编码名称标识位流，x264、x265、SVT-AV1 则是编码器实现。输出位深、兼容性及 Dolby Vision 限制见[编码器选择](Video-Encoding-and-VapourSynth.zh-Hans.md#选择-h264h265-还是-av1)。

### 像素格式不等于编解码格式

`yuv420p`、`yuv420p10le`、8-bit、10-bit、4:2:0、limited range、Rec. 709、Rec. 2020 等描述的是解码样本表示和色彩信令，不能与编解码器名称混为一谈。

相关概念包括：

- **位深（bit depth）**：每个分量的编码位数；
- **色度抽样（chroma subsampling）**：降低色度分辨率，例如 4:2:0；
- **色彩原色（primaries）**：RGB 原色的色度坐标；
- **传输特性（transfer characteristics）**：信号码值与光之间的映射；
- **矩阵系数（matrix coefficients）**：RGB 与亮度／色度分量之间的转换；
- **色彩范围（range）**：limited/video range 或 full range。

这些标签必须与信号含义匹配。重混流应保留正确的信令；重新编码则必须显式生成或复制正确的输出元数据。

## 音频格式

| 格式 | 压缩方式与特征 |
| --- | --- |
| PCM / Blu-ray LPCM | 未压缩样本；蓝光增加帧结构／声道布局。常见 48/96/192 kHz、16/24 位，有效精度可能低于标称位深。 |
| FLAC | 无损压缩 PCM；压缩等级影响耗时／体积，不影响解码质量。 |
| AC-3 / Dolby Digital | 有损兼容音频，蓝光上常与 TrueHD 交织存储。 |
| E-AC-3 / Dolby Digital Plus | 比 AC-3 提供更多能力的有损 Dolby 格式，用于流媒体及蓝光主／次音频。 |
| TrueHD / MLP | 基于 Meridian Lossless Packing 的无损声道音频，可独立存在或与 AC-3 交织；可携带 Atmos 对象、声床及渲染元数据。 |
| DTS core | 面向旧解码器的有损兼容层。 |
| DTS-HD High Resolution | DTS core 的有损扩展。 |
| DTS-HD Master Audio | 无损残差加兼容有损核心，完整解码器可重建母版。 |
| AAC | 通过 `fdkaac` 输出的有损压制目标；码率 `0` 使用 FDK-AAC VBR 模式 5。 |
| Opus | 有损压制目标；自动码率在不超过两声道时为 128 kbps，更多声道为 256 kbps。 |

FLAC 保留解码 PCM，不保留 DTS:X 或 TrueHD Atmos 对象元数据。项目的 FLAC 输出遵循有效样本位深，转换控制见 [README](../../README.zh-Hans.md#音频控制)。

损坏的 TrueHD 可能具有看似正常的容器时长，但解码音频缩短；常规工具不会合成替代 TrueHD 帧。处理异常来源前，应查阅[已知限制与验证](../development/media-pipeline-and-tool-selection.zh-Hans.md#当前限制不修复损坏的-truehd)。

## 音频 core 与 extension

“Core” 不一定表示原盘中一条独立可选的轨道。它可以是复合编码呈现内部的兼容子流。不同工具可能显示为：

- 一条逻辑 TrueHD/DTS-HD 轨道；
- 无损呈现与兼容 core 分开显示；
- 工具不支持扩展解析时只显示 core。

因此，不能仅凭某个工具显示的轨道数量判断物理流布局。

## 无损音频转换决策

项目的转换策略可以概括为：

| 源系列 | 可能目标 | 损失模型 | 项目说明 |
| --- | --- | --- | --- |
| LPCM | FLAC | PCM 表示间无损转换 | 由无损音频选项控制 |
| FLAC | FLAC | 无损 | 通常直接复制，除非处理过程要求重编码 |
| TrueHD/MLP 或 DTS-HD MA | FLAC | 对正确解码后的声道呈现无损 | 沉浸式变体需要明确启用 |
| DTS core / DTS-HD HR | 不变 | 源本来有损 | 排除在自动无损转换之外 |
| 无损源 | AAC/Opus | 有损 | 仅用于 Encode，并按所选策略执行 |
| AC-3/E-AC-3/AAC/Opus | 不变 | 不产生新的编解码世代 | 所选有损音频通常原样保留 |

空档保留、时长检查和整轨回退遵循[音频转换规则](../development/media-pipeline-and-tool-selection.zh-Hans.md#音频转换规则)。

## 字幕模型

字幕大体分为两类：

- **文本字幕**：容器保存文本、时间以及可选的样式指令；
- **位图字幕**：流提供图片、调色板、位置和显示合成信息。

### SRT

SubRip（`.srt`）由多个字幕块组成，块之间用空行分隔。一个普通字幕块包含：

1. 十进制序号；
2. 以 `-->` 分隔的开始和结束时间；
3. 一行或多行正文；
4. 表示该字幕块结束的空行。

```srt
1
00:00:01,000 --> 00:00:03,500
第一行字幕
第二行字幕

2
00:00:05,250 --> 00:00:07,000
下一条字幕
```

惯用时间格式为 `HH:MM:SS,mmm`，其中 `mmm` 是毫秒。序号表示文件顺序，不是呈现时间；裁切或拼接后，工具通常会重新编号。SRT 没有统一的复杂样式系统。部分渲染器接受少量类似 HTML 的标签，但支持并不一致，不能用它保证精确排版。

SRT 文件内部通常也不能可靠声明字符编码，交换时最安全的选择是 UTF-8。BluraySubtitle 的转换路径会尝试多种 Unicode 与旧式编码来读取已有文件，但新建文本应尽量使用 UTF-8。

SRT 作为 `S_TEXT/UTF8` 存入 Matroska 后，时间由容器 block 的时间戳和时长表示，block payload 只保存 UTF-8 字幕正文，而不是把完整 `.srt` 文件原样塞进轨道。

### ASS 与 SSA

Advanced SubStation Alpha（`.ass`）和 SubStation Alpha（`.ssa`）是支持复杂样式、定位、变换、绘图、卡拉 OK 和字体依赖的文本格式。正确渲染可能需要附件字体或已安装字体。

ASS 文件由多个具名 section 组成，最重要的是：

| Section | 内容 |
| --- | --- |
| `[Script Info]` | 脚本类型、标题、脚本分辨率、换行方式等全局设置 |
| `[Aegisub Project Garbage]` | 可选编辑器状态，不属于呈现内容 |
| `[V4+ Styles]` | 一个 `Format:` 字段表，以及多条具名 `Style:` |
| `[Events]` | 一个 `Format:` 字段表，以及 `Dialogue:` 和可选 `Comment:` |

最小示例如下：

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
Dialogue: 0,0:00:01.00,0:00:04.50,Default,,0,0,0,,第一行\N第二行
```

`Format:` 声明字段顺序，所以解析器应按它读取，不能假设所有文件使用同一固定布局。最后一个 `Text` 字段本身可以包含逗号。ASS 时间通常使用 `h:mm:ss.cc`，精度是百分之一秒，而不是 SRT 的毫秒。`\N` 表示强制换行。花括号中的 override tag，例如 `{\i1}`、`{\pos(960,900)}` 或 `{\fad(200,200)}`，可以只对某段事件改变样式、位置、动画、绘图和卡拉 OK 效果。

`PlayResX` 与 `PlayResY` 定义脚本坐标系；只修改它们而不同比例调整样式和位置，会改变最终排版。样式的 `Fontname` 引用字体内部家族名称，它可能与字体文件名不同，因此分发所引用字体也是保留 ASS 呈现的一部分。

ASS/SSA 可以：

- 作为 Matroska 软字幕轨保存；
- 作为外挂字幕发布；
- 渲染到视频，或转换为位图字幕格式。

在 Matroska 中，`S_TEXT/ASS`／`S_TEXT/SSA` 的全局脚本和样式 section 保存在 codec private data 中，每个事件则存入带时间的 block。字体应作为普通 Matroska 附件保存，而不是使用旧式 uuencode `[Fonts]` 数据。

### PGS / Presentation Graphics

PGS 是蓝光的位图呈现字幕系统。裸 PGS 流通常存储在 `.sup` 文件中。它不是文本，若没有 OCR 或手工重建就无法像文本一样编辑。

SUP 数据包通常以以下结构开始：

```text
"PG" magic
PTS（32-bit，90 kHz）
DTS（32-bit，90 kHz）
segment type
segment length
segment payload
```

重要 segment type 包括：

| 类型 | 名称 | 用途 |
| ---: | --- | --- |
| `0x14` | PDS | Palette Definition Segment，调色板定义 |
| `0x15` | ODS | Object Definition Segment，包含 RLE 位图 |
| `0x16` | PCS | Presentation Composition Segment，呈现合成 |
| `0x17` | WDS | Window Definition Segment，窗口定义 |
| `0x80` | END | 一个 display set 结束 |

一个渲染后的字幕事件由完整 display set 组合而成，不是单个独立图片数据包。合成状态可以获取、更新、复用或清除对象。因此，裁切或拼接 PGS 时必须调整时间戳，并保留渲染各 display set 所需的定义。

### IGS / Interactive Graphics

IGS 是交互菜单图形，不是普通 PGS 字幕；合成方式及图像提取限制见 [HDMV／BD-J 菜单](Blu-ray-Disc-Structure.zh-Hans.md#hdmvbd-j-菜单与-igs)。

### TextST

TextST 是 stream type `0x92` 对应的蓝光文本字幕格式。尽管 SRT、ASS 和 TextST 都与文本有关，它们仍是不同格式。

## 软字幕、硬字幕与外挂字幕

| 封装方式 | 结果 | 能否关闭？ | 播放时是否需要渲染器／字体？ |
| --- | --- | ---: | ---: |
| 外挂 | 独立字幕文件 | 是 | 通常需要 |
| 软字幕 | MKV 内的字幕轨 | 是 | 文本字幕通常需要 |
| 硬字幕 | 已编码进视频像素 | 否 | 编码完成后不需要 |

ASS 转 PGS 会保留字幕可选择性，但会按指定分辨率和帧率／时间模型栅格化外观。硬字幕则直接栅格化进视频，再参与视频编码。

## Dolby Vision 基础

Dolby Vision 是把编码画面与动态呈现元数据结合起来的 HDR 系统，元数据用于让内容适配目标显示设备。与只提供静态 HDR 元数据的方式不同，Dolby Vision 元数据可以随时间变化。

常见术语：

- **BL — Base Layer**：可独立解码的基础画面；在 UHD Blu-ray 上通常与 HDR10 兼容；
- **EL — Enhancement Layer**：部分 Dolby Vision profile 使用的附加编码数据；
- **RPU — Reference Processing Unit metadata**：携带在 HEVC 流中的动态 Dolby Vision 元数据；
- **MEL — Minimum Enhancement Layer**：残差贡献最小的增强层；
- **FEL — Full Enhancement Layer**：能够携带额外残差画面信息的增强层；
- **profile**：对编码、分层、兼容性和元数据约束的规定组合。

### UHD Blu-ray 上的 Dolby Vision

UHD Blu-ray Dolby Vision 通常使用 profile 7。原盘可以保存 HEVC 基础层和依赖增强表示，并携带 RPU 元数据。工具可能显示两个 HEVC 视频轨／PID，而 Matroska 表示也可能把 Dolby Vision 数据组合在一条 HEVC 轨内。

不要把“存在两条视频轨”当作唯一 Dolby Vision 判断条件。流 descriptor、HEVC NAL 单元内容和 Dolby Vision 元数据检查更可靠。

### 本项目中的 profile 8.1

对兼容的双层 Remux 输入，`dovi_tool -m 2 mux --discard` 将 RPU 改写为 profile 8.1 并丢弃增强层视频，生成单条基础层加 RPU 的 HEVC 轨道。因此，保留 RPU 不代表保留了 profile 7 FEL 的画面残差。

压制还有独立的位深、裁剪、原生写入／注入及验证要求，统一见[自动 HDR 元数据处理](Video-Encoding-and-VapourSynth.zh-Hans.md#自动-hdr-元数据处理)。

## 格式识别清单

诊断一条轨道时，应记录：

1. 源所在层：MPLS、M2TS、MKV 或基本流；
2. 容器轨道 ID 和传输 PID（如适用）；
3. codec ID 和 transport stream type；
4. 语言、名称、默认和强制标记；
5. 时长和起始时间戳；
6. 视频像素格式／色彩元数据，或音频采样格式／声道布局；
7. core/extension 或 base/enhancement 关系；
8. 时间戳、延迟或空隙是否只存在于源容器；
9. 所选操作属于流复制、无损转换还是有损转码。
