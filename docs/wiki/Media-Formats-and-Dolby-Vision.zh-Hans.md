# 媒体格式、字幕与 Dolby Vision

[English](Media-Formats-and-Dolby-Vision.md) | 简体中文

本页汇总蓝光原盘和 BluraySubtitle 中常见的格式。“格式”可能指容器、编解码器、基本流表示或字幕模型，因此每一节都会明确其所在层次。

## 视频格式

### MPEG-2 Video

MPEG-2 Video 可见于早期蓝光，在传统 BD-ROM 体系中仍是有效格式。它属于有损编码，在相近主观画质下的压缩效率明显低于 AVC 或 HEVC。

### VC-1

VC-1 是部分早期蓝光使用的有损视频编解码格式。播放和重混流工具对它的支持已经成熟，但现代压制工作流很少选择它作为目标格式。

### AVC / H.264

AVC 的标准名称为 H.264，是 1080p 蓝光最常见的视频编解码格式。典型原盘视频使用 8-bit 4:2:0 YCbCr。AVC 通常是有损的，尽管规范和部分编码器在普通蓝光发行用途之外也提供无损模式。

`x264` 是 AVC 编码器，不是容器，也不能单独创建 MKV；它输出的基本流需要在后续步骤中混流。

### MVC

Multiview Video Coding 是 AVC 的扩展，用于立体蓝光 3D。一个 AVC 基础视图可以搭配一个依赖 MVC 视图。原盘可能通过扩展和子路径表达依赖视图关系，而不是把它当作普通的第二视频轨独立选择。

### HEVC / H.265

HEVC 的标准名称为 H.265，是 Ultra HD Blu-ray 的主要视频编解码格式。UHD 内容通常使用 10-bit 4:2:0 YCbCr、Rec. 2020 信令和 HDR 传输特性。发行媒体中的 HEVC 通常是有损的。

`x265` 是 HEVC 编码器。BluraySubtitle 在受支持的 Dolby Vision 保留路径中使用 x265 10-bit 或 12-bit 输出。

### AV1

AV1 是现代有损视频编解码格式，BluraySubtitle 可通过 SVT-AV1 将其作为压制目标。项目处理的 BDMV/UHD-BD 源并不使用 AV1。当前工具链不会制作 AV1 Dolby Vision profile 10，因此 SVT-AV1 输出会省略 Dolby Vision 元数据并明确报告。

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

### PCM 与蓝光 LPCM

PCM 直接保存采样后的幅度值。蓝光 LPCM 则增加蓝光专用的帧结构和声道布局。PCM 未压缩且无损。

常见属性包括：

- 采样率，例如 48、96 或 192 kHz；
- 位深，例如 16 或 24 bit；
- 声道数和声道布局。

标称 24-bit 的轨道可能只有 16 位有效信号精度。有效位深必须根据解码样本判断，不能只看容器元数据。

### FLAC

FLAC 是用于 PCM 样本的无损编解码格式，通常可以在不改变解码样本的前提下减小 LPCM 体积。压缩等级只影响编码耗时和文件大小，不影响解码质量。

FLAC 无法保留 TrueHD Atmos 或 DTS:X 的沉浸式元数据模型。将这些格式转换为 FLAC，只能保留所选解码器产生的声道呈现结果。

BluraySubtitle 写入 FLAC 时会保留检测到的 PCM 有效位深；可配置的 FLAC 压缩等级默认为 8。

### Dolby Digital / AC-3

AC-3 是有损感知音频编解码格式，兼容性很广。蓝光中的 TrueHD 经常附带 AC-3 兼容 core。

### Dolby Digital Plus / E-AC-3

E-AC-3 是功能更强的有损 Dolby 编解码格式，可以支持比 AC-3 更多的声道和特性。它常见于流媒体，蓝光也定义了主 E-AC-3 和次 E-AC-3 stream type。

### Dolby TrueHD 与 MLP

TrueHD 是源自 Meridian Lossless Packing 的无损编解码格式。根据流布局，蓝光可以把 AC-3 兼容 core 与 TrueHD 扩展数据交织在一起，也可以携带仅 TrueHD 的呈现。

TrueHD 可以携带 Dolby Atmos 元数据。Atmos 描述超出固定声道流的对象、bed 和渲染信息。把所选呈现解码为 PCM 或 FLAC 后，无法继续以 Atmos 形式保留对象元数据。

损坏的 TrueHD 需要特别谨慎。即使传输丢失或无效帧使提取／解码后的音频变短，容器仍可能显示看似合理的总时长。MKVToolNix 和项目的普通抽流路径不会合成替代 TrueHD 帧。丢弃源轨前，应检查解码器错误，并比较解码后音频与视频时长。

### DTS core

DTS core 是有损编解码格式和兼容层。DTS-HD 流可以包含该 core，使旧解码器能够播放功能较少的版本。

### DTS-HD High Resolution Audio

DTS-HD HR 是有损扩展，能力和质量高于 core，但不是无损格式。

### DTS-HD Master Audio

DTS-HD MA 在兼容的 DTS core 上增加无损残差。完整解码器能够重建无损母版，只支持 core 的解码器仍可播放有损 DTS 表示。

### AAC

AAC 是有损感知音频编解码格式。BluraySubtitle 使用 `fdkaac` 前端编码 AAC。码率配置为 0 时代表自动模式，具体使用 FDK-AAC VBR 5。

### Opus

Opus 是面向语音和音乐的现代有损编解码格式。它可以作为 Encode 音频目标，但不能作为 Remux 工作流的无损音频转换目标。自动码率对不超过双声道使用 128 kbps，对更多声道使用 256 kbps。

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

无论转换目标为何，播放列表空档都会保留为 Matroska 轨道的时间戳空档，而不是静音 PCM。验证分别比较每个连续音频区间，并以单个区间的最大缩短量决定提示与回退，不累加各区间损失。

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

项目的 `SRT` 模型读取带编号字幕块，保存开始／结束时间和多行正文；追加时平移时间，裁切时为保留条目重新编号。当前裁切操作只保留开始与结束都完整落在所选区间内的字幕。

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

BluraySubtitle 的 `Ass` 模型会识别 SSA v4 或 ASS v4+ 样式 section，按已声明的 `Format:` 属性读取字段，把事件时间转换为可运算值，并保留正文中的逗号。模型支持平移、追加、裁切和重新写出事件。SRT → ASS 路径会创建 v4+ 头，并把基本粗体、下划线、斜体和字体颜色标记转换成 ASS override tag。

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

BluraySubtitle 的 `PGS` 类读取 SUP 数据包头、计算最大结束时间、在追加时平移时间戳，并在裁切时选择和重置数据包时间。项目还内置基于转换组件的 ASS → SUP 路径。

### IGS / Interactive Graphics

IGS 用于交互菜单和按钮状态。它同样基于位图和合成，但还包含页面、button-over group、状态、导航命令和交互时间。媒体工具有时会把仅含 IGS 的 M2TS 标记为字幕流，但它不是普通 PGS 字幕。

BluraySubtitle 可以识别 IGS stream type `0x91`，并为受支持的 SP 处理提取代表性的按钮状态图片。

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

BluraySubtitle 的受支持 Remux 路径接收兼容的基础层和增强层输入，并运行 `dovi_tool -m 2 mux --discard`。该命令把 RPU 改写为 profile 8.1，同时丢弃增强层视频，最终留下单层的基础层加 RPU 结果。

在 Encode 路径中：

- x265 10-bit 或 12-bit 输出可以接收提取出的 RPU，并以 profile 8.1 保留 Dolby Vision；
- 需要保留 Dolby Vision 时，x265 8-bit 和 x264 会被拒绝；
- SVT-AV1 可以继续编码，但当前工具链不会制作 AV1 Dolby Vision profile 10，因此会省略 Dolby Vision 元数据。

Profile 转换不代表 profile 7 FEL 的每个组成部分都能在 profile 8.1 结果中重现。保留 RPU 与保留增强层残差是两个不同问题。

### 项目工作流

对来自 MKV 的 Dolby Vision 压制，项目在概念上会：

1. 识别并提取 HEVC 视频轨；
2. 使用 `dovi_tool` 分离／提取基础表示和 RPU 元数据；
3. 存在自动物理裁剪时，导出全部 L5 有效画面 preset，减去实际裁剪边距，并生成任务自有的已编辑 RPU；
4. 用受支持位深的 x265 编码处理后的基础视频；
5. 实际 x265 声明支持原生参数，且当前行已经具备 VBV 和母版显示前提时，在同一次压制中写入准备好的 RPU，否则由 `dovi_tool` 后注入；
6. 原生产物验证失败时也回退到注入，验证编码 HEVC 中存在 RPU；来源带有 HDR10+ 时也验证 HDR10+；
7. 混流最终容器，并在验证该容器时要求 Profile 8 及与 VPy 输出一致的 RPU 帧数；当前启用的 HDR10+ 和由程序自动补充的静态字段也会再次检查。

x265 原生写入与备用后注入因此使用同一份裁剪后 RPU。支持时仍会保留来源 HDR10+ 元数据，但当前流程不会在裁剪后重新测量其亮度统计。

对于兼容的双层 Remux 输入，项目使用 `dovi_tool` mode 2 创建受支持的单层 profile 8.1 结果，不保留增强层画面残差。

每个生成的中间文件都会检查。如果缺少基础层、RPU、转换、注入或验证结果，任务会失败，不会在请求 Dolby Vision 的情况下静默生成普通 HDR 文件。

最终容器验证不匹配与中间产物损坏的处理不同：已经发布的 MKV 会保留，当前行记为带警告完成，并在不覆盖已有文件的 HDR 报告中记录不匹配信息供诊断。

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
