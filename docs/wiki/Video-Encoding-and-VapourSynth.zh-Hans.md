# 视频压制与 VapourSynth

[English](Video-Encoding-and-VapourSynth.md) | 简体中文

压制是把解码后的视频帧重新生成一条压缩视频流的过程。它与 Remux 不同：
Remux 复制已有编码流，而压制会解码帧、按需处理帧，再重新作出编码决策。本页介绍
BluraySubtitle 使用的编码格式、编码器、参数预设和 VapourSynth 管线。

## 编码格式、编码器与容器不是一回事

以下名称属于不同层次：

| 层次 | 示例 | 含义 |
| --- | --- | --- |
| 视频编码标准 | H.264/AVC、H.265/HEVC、AV1 | 定义合规位流和解码器行为 |
| 编码器实现 | x264、x265、SVT-AV1 | 生成符合相应标准的位流 |
| 容器 | MKV、MP4 | 将编码视频与音频、字幕、章节和元数据放在一起 |

因此，x264 生成 H.264 视频，x265 生成 H.265 视频，SVT-AV1 生成 AV1 视频。
使用 x265 压制不表示结果必须放入 MP4；BluraySubtitle 会将编码流封装进 MKV。

## 选择 H.264、H.265 还是 AV1

### x264 与 H.264 / AVC

H.264 是三种选择中最早出现的一种，软硬件播放兼容性最广。x264 成熟、行为可预期，
在实用参数下通常也比新编码格式的实现更快。需要兼容旧播放器、低性能客户端，或兼容性
比最小体积更重要时，可以选择它。

BluraySubtitle 支持 x264 的 8-bit 和 10-bit 输出，不提供 12-bit x264。相同观感下，
H.264 通常比精心配置的新格式需要更多数据，但编码格式的代际本身并不能决定画质。

### x265 与 H.265 / HEVC

H.265 是 H.264 的后继标准，引入了更灵活的分块、预测和编码工具。x265 通常能比
x264 达到更好的压缩效率，尤其适合高分辨率内容，代价是需要更多编码计算，并且兼容性
略窄。

x265 是项目的默认编码器，默认输出 10-bit。10-bit 对 SDR 源也有意义，因为更细的
内部和输出精度有助于减少量化与色带问题；它不会把 SDR 变成 HDR。BluraySubtitle
支持 x265 的 8-bit、10-bit 和 12-bit 输出。

项目的 Dolby Vision 压制保留路径要求 x265 10-bit 或 12-bit。这是当前项目实现的
约束，并不表示任意 x265 压制都能保留所有 Dolby Vision Profile。

### SVT-AV1 与 AV1

AV1 是由 Alliance for Open Media 制定的开放视频编码标准，目标之一是提高压缩效率，
并包含胶片颗粒合成等工具。SVT-AV1 是本项目集成的独立 AV1 编码器。

关注文件体积且播放环境较新时，AV1 很有吸引力，但仍需根据目标用户检查编码成本和
设备支持。BluraySubtitle 支持 SVT-AV1 的 8-bit、10-bit 和 12-bit 输出，并在最终
混流成 MKV 之前生成 IVF 中间流。

当前项目使用 SVT-AV1 压制时不会保留 Dolby Vision 元数据。需要项目所述 Dolby
Vision 压制路径时，应选择 x265 10/12-bit。

### 不存在脱离参数的固定画质排名

“AV1 优于 H.265，H.265 又优于 H.264”对于实际压制过于简单。结果取决于：

- 源分辨率、颗粒、动画风格、运动和已有瑕疵；
- 编码器实现及版本；
- 码率控制目标；
- preset 和各项分析参数；
- 编码前滤镜；
- 播放设备和解码器。

应使用具有代表性的短片段，并按实际观看距离比较。不要先把同一视频压成一种格式，再
把这个有损结果转成另一种格式来比较，因为后一次压制还会继承前一次的损失。

## BluraySubtitle 压制管线

原盘输入的高层流程如下：

```text
所选 MPLS 与轨道
        │
        ▼
按播放列表／章节区间生成暂存 MKV
        │
        ▼
VapourSynth .vpy 脚本
        │
        ▼
vspipe --y4m
        │
        ├── x264  → .h264
        ├── x265  → .hevc
        └── SVT-AV1 → .ivf
        │
        ▼
与所选音频、字幕、章节、附件和元数据混流成最终 MKV
```

暂存 Remux 会保留源音频。只有视频成功压制后，最终混流阶段才进行音频转换和清理，
避免在视频结果尚未生成时提前执行有损或耗时的音频操作。

`vspipe` 通过管道向编码器提供 Y4M 帧，所以普通压制不需要落盘一份完整的未压缩视频。
编码器产生的基本流是中间文件，最终交付给用户的是 MKV。

## 码率控制与 preset 的含义

### CRF

内置预设使用 **CRF**（Constant Rate Factor）码率控制。CRF 要求编码器追求某个
质量水平，而不是固定最终体积：

- CRF 越低，通常画质越高、文件越大；
- CRF 越高，通常损失越多、文件越小；
- 最终体积仍会随源复杂度变化。

x264、x265 和 SVT-AV1 的 CRF 数字不能横向等同。某编码器的 18 不能视为与另一
编码器的 18 具有相同画质。

必须满足严格交付体积时，按码率的一遍或多遍压制可能更合适，但 BluraySubtitle 内置
预设以 CRF 为主。用户新增预设和直接编辑的参数也可以使用编码器支持的其他模式。

### 编码器 preset

编码器自己的 `--preset` 控制速度与压缩效率的取舍。更慢的 preset 会花更多 CPU 时间
搜索编码方案，通常能更高效地保存所选质量。它不是简单的画质开关：相同 CRF 下换成
更慢 preset，并不保证体积不变，也不保证每个场景都有肉眼可见的提升。

BluraySubtitle 又在编码器参数之上提供了一层项目预设：

| 项目预设 | 设计用途 |
| --- | --- |
| Fast／快速 | 快速输出或测试压制 |
| Balanced／均衡 | 默认起点 |
| High Quality／高质 | 提高质量预算和分析量 |
| Extreme／极限 | 极慢且质量预算很大的起点 |

四组内置预设保持只读。“高级”设置可以为其中当前选择的压制工具新增、重命名、修改和
删除用户预设；`config.json` 只保存这些用户新增条目。Encode 页面只显示当前压制工具
对应的内置预设和用户预设。选择预设会填充参数框，直接修改参数框则保持所选预设名称
不变。任务启动时界面可见的参数字符串具有最高权威。

## 内置参数预设

当前值定义在
[`src/core/encode_presets.py`](../../src/core/encode_presets.py) 中。它们是起点，
不承诺固定体积或固定主观画质。

### x264

```text
Fast:
--preset fast --crf 20 --profile high --level 4.1 --bframes 4 --ref 4

Balanced:
--preset medium --crf 18 --profile high --level 4.1 --bframes 6 --ref 5 --deblock -1:-1

High Quality:
--preset slow --crf 16 --profile high --level 4.1 --bframes 8 --ref 6 --deblock -1:-1 --aq-mode 2

Extreme:
--preset veryslow --crf 14 --profile high --level 4.1 --bframes 10 --ref 8 --aq-mode 2 --trellis 2
```

必要时，应用会根据所选 8-bit 或 10-bit 输出调整 x264 profile。

### x265

```text
Fast:
--preset fast --crf 20 --aq-mode 2 --bframes 8 --ref 4 --me 2 --subme 2

Balanced:
--preset slower --crf 18 --aq-mode 3 --bframes 8 --ref 5 --me 3 --subme 4

High Quality:
--preset slower --crf 16 --aq-mode 3 --bframes 8 --psy-rd 2.0 --psy-rdoq 1.0
--deblock -1:-1 --rc-lookahead 60 --ref 6 --subme 5

Extreme:
--preset placebo --crf 14 --aq-mode 3 --aq-strength 1.0
--cbqpoffs -2 --crqpoffs -2 --bframes 12 --b-adapt 2 --ref 6
--rc-lookahead 120 --lookahead-threads 0 --psy-rd 2.5 --psy-rdoq 2.0
--rdoq-level 2 --deblock -2:-2 --qcomp 0.65 --merange 57
--no-sao --no-strong-intra-smoothing
```

`placebo` 本来就是极端选项，其额外耗时通常具有非常明显的边际收益递减。不能仅因为
它位于列表最后就默认选择它。

### SVT-AV1

```text
Fast:
--preset 10 --crf 32 --keyint 240 --tune 0

Balanced:
--preset 6 --crf 24 --keyint 240 --tune 0

High Quality:
--preset 4 --crf 20 --keyint 240 --tune 0 --film-grain 4

Extreme:
--preset 2 --crf 16 --keyint 240 --tune 0 --film-grain 0 --aq-mode 2
```

与 x264/x265 的命名 preset 不同，SVT-AV1 的 preset 数字越大，压制越快，但压缩
效率也会有所取舍。选择 12-bit 且参数中没有显式 profile 时，项目会自动补充所需
profile。在 Windows 上，当前项目会强制 SVT-AV1 使用可移植 C 路径，以规避集成
工作流中已知的输出损坏问题。

## 常用参数的直观含义

| 参数 | 实际含义 |
| --- | --- |
| `--crf` | CRF 模式的质量／体积目标 |
| `--preset` | 编码器投入的分析量与速度 |
| `--aq-mode`、`--aq-strength` | 根据空间／视觉复杂度重新分配量化 |
| `--bframes` | 双向预测帧的最大使用量 |
| `--ref` | 参考帧预算 |
| `--me`、`--subme`、`--merange` | 运动搜索方式、精细度和范围 |
| `--keyint` | 关键帧／GOP 最大间隔 |
| `--rc-lookahead` | 为码率控制和帧类型决策预读的帧数 |
| `--psy-rd`、`--psy-rdoq` | 模式决策和量化中的心理视觉权重 |
| `--deblock` | 环路去块行为 |
| SVT-AV1 `--film-grain` | 胶片颗粒合成强度，不是普通降噪滤镜 |

参数之间会互相影响。复制针对另一种片源的超长命令，可能让画面更差，也可能只是让
压制变慢。最终色彩范围、原色、传递特性、矩阵、位深和色度格式必须与处理后的帧一致。

## VapourSynth 做什么

VapourSynth 是由 Python 驱动的帧服务器。一个 `.vpy` 脚本会：

1. 打开并索引视频源；
2. 构建视频帧处理滤镜图；
3. 通过 `set_output()` 暴露一个或多个 `VideoNode`；
4. 在 `vspipe` 或预览程序请求时按需计算帧。

VapourSynth 本身不编码视频。本项目由 `vspipe` 计算所选输出，并把 Y4M 帧送给
x264、x265 或 SVT-AV1。

GUI 可以生成、编辑和预览 `.vpy`。压制前会把真实源路径以及可选的原生分辨率信息
写入脚本；所选输出位深会同步到最终的 `fmtc.bitdepth(..., bits=N)`。选择内嵌字幕
时，程序会启用 `assrender.TextSub` 行并传入字幕路径。

自动裁黑边默认关闭。启用后，BluraySubtitle 会先探测时长与尺寸，再用 FFmpeg 输入端
快速定位，在每个时间分桶中分析一个伪随机时间点。采样数按每 150 秒一个计算，并限制
在 4～24 个；每个时间点只解码附近三帧，不写出图片文件。固定裁剪值来自全部检测结果
中有效画面矩形的并集，因此任一样本使用到的像素都会保留。程序会在其余滤镜图之前插入
受管理的 `src8.std.Crop(...)`。自动分析必然是启发式的：暗场、片头片尾、叠加元素和
特殊黑边都可能造成错误，请核对报告的边距与压制后画面。

启动编码器前，BluraySubtitle 会抽查输出 0 的首帧、中间帧和末帧。稳定的
`_ColorRange`、`_Primaries`、`_Transfer`、`_Matrix` 和 `_ChromaLocation`
属性优先于来源元数据，缺失属性则回退到来源；抽查值不一致时当前行会停止。

实际来源带有 HDR10+ 时，x265 10/12 位压制会提取经过校验的 JSON，并对照 VPy
时间轴检查元数据帧数和来源帧率。程序按二进制文件身份探测一次实际 x265：声明
支持 `--dhdr10-info` 时在压制中写入；缺少该参数或原生验证失败时，改由
`hdr10plus_tool` 执行经过验证的后注入。失败时会省略动态元数据继续压制，并保留
非空 JSON 供诊断；使用该流程的自定义脚本必须保持帧顺序。

同时输出 HDR10+ 与 Dolby Vision 时，只有实际 x265 声明支持两条原生路径，且
当前行已经具备 VBV 和母版显示参数时，才会在同一次压制中写入两者。缺少原生
支持或原生产物验证失败时，沿用现有注入工具且不改变码率控制；最后一次注入后、
最终混流前会分别检查 HEVC 中的两种动态元数据。

自动裁剪改变编码尺寸时，程序会按实际裁剪值调整每个 Dolby Vision L5 有效画面
preset，再把所得 Profile 8.1 RPU 交给 x265 原生写入或后注入。因此，手工提供 RPU
不能与自动裁剪同时使用。HDR10+ 在此流程中没有对应的裁剪偏移编辑：程序会保留来源
元数据，不再显示额外的裁剪专项提示。

最终 MKV 发布后，BluraySubtitle 会反向探测由程序自动补充的静态字段，并再次检查
当前启用的动态元数据。Dolby Vision 必须报告 Profile 8，且 RPU 帧数必须与 VPy 输出
一致。不匹配时保留 MKV，记录一份不覆盖已有文件的警告报告，并继续处理后续行。

## 默认脚本使用的插件

默认脚本是可用起点，不是适合所有片源的通用修复方案。当前滤镜链包括：

| namespace／包 | 默认脚本中的作用 |
| --- | --- |
| `lsmas.LWLibavSource` | 首选索引式源滤镜 |
| `ffms2.Source` | 源滤镜回退 |
| `fmtc` | 位深转换和重采样 |
| `descale` | 按检测到的原生分辨率执行可选逆向缩放 |
| `nlm_ispc` | 降噪 |
| Windows 上的 `neo_f3kdb`／其他平台的 `placebo` | 去色带 |
| `mvsfunc.LimitFilter` | 参照原始 clip 限制滤镜改动 |
| `eedi2` | 边缘导向抗锯齿 |
| `rgvs.Repair` | 约束修复后的平面 |
| 内置 `std` 与 `resize` | 平面操作、格式安全缩放和输出构建 |
| `assrender.TextSub` | 可选 ASS/SSA 内嵌渲染 |

插件可用性取决于运行环境。所需插件或 Python 模块缺失时，脚本会在求值阶段失败；
环境配置脚本和“外部工具”设置决定实际使用哪个运行时。

## 常见的其他 VapourSynth 插件

自订脚本经常使用不同的滤镜链。常见类别包括：

| 任务 | 常见示例 | 主要注意事项 |
| --- | --- | --- |
| 源读取 | BestSource、L-SMASH-Works、FFMS2 | 索引和时间戳行为并不相同 |
| 去隔行／IVTC | QTGMC、VIVTC、TIVTC | 必须先确认场序和 cadence |
| 缩放／逆向缩放 | `resize`、fmtconv、descale、基于 zimg 的 helper | 保持 range、matrix、chroma location 和宽高比 |
| 降噪 | BM3D 系列、DFTTest、KNLMeansCL/NLMeans、基于 MVTools 的滤镜 | 过度降噪会破坏纹理和颗粒 |
| 去色带 | neo_f3kdb、libplacebo | 需要适量颗粒／dither 避免再次量化出色带 |
| 抗锯齿 | EEDI2/EEDI3、NNEDI3/ZNEDI3、基于 sangnom 的 helper | 只有线条需要修复时应配合 mask |
| 字幕渲染 | assrender／基于 libass 的滤镜 | 字体和脚本分辨率会影响排版 |

这些名称是生态中的常见选项，不代表 BluraySubtitle 保证提供全部依赖。自订脚本应自行
负责插件依赖和输出正确性。

## 脚本设计检查清单

- 检查源帧数、帧率、扫描方式和场序。
- 保留或明确设置 `_Matrix`、`_Transfer`、`_Primaries`、`_ColorRange` 和
  chroma location 属性。
- 对具有代表性的帧做对比后再使用破坏性滤镜。
- 中间处理使用足够精度，降低位深时执行 dither。
- 裁切和缩放尺寸必须满足输出色度抽样要求。
- 预览暗部渐变、颗粒、线条、运动和滚动字幕，不能只看干净静态画面。
- 确保主 `set_output()` 输出的正是要压制的 clip。
- 开始完整标题前，使用最终编码参数做短片段测试。

## 延伸阅读

H.264、H.265、AV1、x265、SVT-AV1 和 VapourSynth 的规范与手册链接见
[参考资料](References.zh-Hans.md)。
