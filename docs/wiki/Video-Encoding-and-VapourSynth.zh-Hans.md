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
--preset fast --crf 20 --profile high --bframes 4 --ref 4

Balanced:
--preset medium --crf 18 --profile high --bframes 6 --ref 5 --deblock -1:-1

High Quality:
--preset slow --crf 16 --profile high --bframes 8 --ref 6 --deblock -1:-1 --aq-mode 2

Extreme:
--preset veryslow --crf 14 --profile high --bframes 10 --ref 8 --aq-mode 2 --trellis 2
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
--preset 4 --crf 20 --keyint 240 --tune 0

Extreme:
--preset 2 --crf 16 --keyint 240 --tune 0 --aq-mode 2
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

### 自动 getnative

BluraySubtitle 的自动 getnative 移植自 [Infiziert90/getnative](https://github.com/Infiziert90/getnative)，用于估算 1080p 片源在母版放大前的纵向制作分辨率，以及最可能使用的缩放核。启用自动 getnative 后，检测结果会成为生成 VPy 中的原生高度与逆缩放核，从而在后续滤镜或缩放前移除母版已有的放大；它不会修改源文件，也无法恢复原本不存在的细节。直接以 1080p 制作、混合分辨率、真人画面、重颗粒、合成文字和经过后期处理的素材都可能无法得到明确结果。

#### 抽帧与调度

程序通过 FFmpeg 逐轮增量抽取候选帧，不会一开始就准备 100 张图片。候选帧按边缘能量、亮度方差与信息熵排序，优先尝试细节清晰、对比较强的画面。每轮最多投放 20 个样本，并继续受逻辑 CPU 数与当前可用物理内存限制。内存计算会为系统预留 2 GiB，再为每个样本进程预算 800 MiB。800 MiB 只是并发调度估算，并非进程内存硬上限；复杂画面或短暂的最终扫描仍可能超过该数值。

所有已经投放的样本都会运行完毕，每个核和样本一有结果就立即输出。5 条有效曲线只用于判断是否需要下一轮；当前轮完成后得到的全部有效结果仍会参加最终选择。如果不足 5 条，程序才会继续增量抽帧，最多到 100 个样本的安全上限。最终至少需要两条可用曲线才会返回自动检测结果。

#### 单个样本分析什么

系统 Python 负责抽帧、进程调度与最终排名；便携版 Python 3.13 VapourSynth 环境运行 `getnative.vpy`，先把 PNG 样本从 RGB 按 BT.709 转成灰度，再检测全部 16 种逆缩放候选：bilinear、8 组不同参数的 bicubic、2/3/4/5 taps 的 Lanczos，以及 Spline16、Spline36、Spline64。每个候选会把画面逆缩放到待测高度，再放大回源尺寸并测量重建误差。纵向搜索范围通常是源高度的 40%～98%。

为了缩短耗时，每个核先对居中的半尺寸画面进行步长 4 粗扫，再在粗扫最佳高度附近执行全帧 1p 细扫。前三种优先核必定进入细扫；此后的核如果同条件粗扫得分不足当前最佳粗扫得分的 45%，可以跳过细扫，但仍会报告粗扫结果。全部核报告完毕后，获胜核还会执行一次全帧步长 4 复核，再在其 ±20p 范围内执行全帧 1p 精扫，避免保留第二套全范围 1p 图。每个 VSPipe 进程只使用一个 VapourSynth 帧线程，并把帧缓存上限设为 256 MiB，以控制并发时的内存增长。

#### 曲线判定与多帧汇总

对于每条重建误差曲线，getnative 会按照上游方法寻找相邻高度之间明显的误差突降。候选分辨率取突降处的当前高度，主要得分为“前一高度误差 ÷ 当前高度误差”。误差计算中的 5 像素边缘裁剪只用于排除不可靠的画面边缘，不会给检测高度增加或减少 5p；只有找不到可信的尖锐突降时，才使用宽缓谷底作为回退。

排名前会排除不稳定或剧烈振荡的曲线尾段。535p～545p 在实际素材中会产生非常普遍的误报，因此该区间会被有意排除；高于 1040p 的候选也会作为不合理的曲线尾段结果移除。所以，确实为原生 540p 的素材无法依靠自动检测，必须手动设置。

可用样本按四舍五入后的高度分组。每个样本的权重是 `min(得分, 2) * (高度 / 搜索范围上限)^4`；每组最强的 3 个权重之和决定获胜组，完全同分时选择更高的高度。这样既保留实测中有效的“尽量选择高分辨率且高分”倾向，也不会要求稠密共识，因为部分片源本来就只能产生很少的可用帧。最后用获胜组内的加权高度和缩放核票数生成 VPy 参数。

自动 getnative 始终是启发式检测，可能消耗大量时间与内存。具有清晰线条和可见细节的画面通常能给出最明确的曲线；暗场、片头片尾、柔焦摄影、噪点、混合动画制作流程和后续二次缩放都可能影响结果。结果不稳定时应查看逐核输出，并比较多集结果。若要脱离 GUI 单独测试文件，可修改 `src/scripts/getnative_file.py` 中的 `video_file` 后直接运行该脚本。

### 自动生成 VPy 的画面修复设置

Encode 页在 getnative、自动裁黑边和输出对比图选项的正下方提供五个数值强度。
任务启动时会捕获当前值，并替换自动生成脚本顶层的 `denoise_strength`、
`dehalo_strength`、`dering_strength`、`deband_strength` 和
`antialiasing_strength` 赋值。没有定义这些名称的自定义 VPy 不会被修改；
启动默认值也可在“高级”设置中保存。

| 设置 | 范围／默认值 | 推荐用法 | 自动生成脚本中的行为 |
| --- | --- | --- | --- |
| 降噪 | `0.0`～`3.0`／`0.6` | 保守起点保持 `0.6`；刻意颗粒或纸张纹理发生变化时调低，只在检查噪点层后再调高。 | `nlm_ispc.NLMeans` 仅对亮度执行小范围纯空间降噪（`d=0`），再用 Prewitt 遮罩恢复强边缘，并由 `mvsfunc.LimitFilter` 限制其余像素的最大变化。它取代旧的固定 `h=3` 参考，避免纹理和颗粒在后续滤镜前已经丢失。 |
| 去光晕 | `0.0`～`1.0`／`0.0` | 没有可见锐化光晕时保持 `0`。建议从 `0.15`～`0.25` 开始；确认存在明显光晕并检查代表帧后可用约 `0.25`～`0.35`。除非只处理并检查特定镜头，不建议整片超过 `0.4`。 | 采用 [xyx98/my-vapoursynth-script](https://github.com/xyx98/my-vapoursynth-script) 中 `abcxyz` 思路的保守亮度版本，通过缩小／放大建立宽光晕估计，经 `rgvs.Repair` 约束后只按设定比例混合。强度是混合比例，不是光晕半径。 |
| 去振铃 | `0.0`～`1.0`／`0.0` | 没有可见振铃时保持 `0`。建议从 `0.15`～`0.25` 开始；`0.25`～`0.35` 只用于明显的 DCT／缩放振铃。整片超过 `0.4` 容易让线稿和细纹理变软。 | 采用 `MinBlur`／`HQDering` 思路，在强边缘周围建立窄环带并排除边缘本身，只通过该遮罩应用经过 Repair 和严格限幅的平滑。强度只混合遮罩结果，不会扩大环带。 |
| 去色带 | `0.0`～`1.0`／`0.5` | 普通动画可从适中的 `0.5` 开始；没有色带或精细渐变／特效被损伤时使用 `0`，只有检查平坦渐变后才逐步接近 `1`。 | 限幅 `placebo.Deband` 候选处理 YUV，再用柔化的多平面 Prewitt 遮罩恢复边缘与纹理；`0` 跳过，`0.5` 混合一半自适应保护结果，`1` 完整应用。 |
| 抗锯齿 | `0.0`～`1.0`／`0.5` | 可能存在锯齿时可从适中的 `0.5` 开始。没有可见锯齿的高细节或刻意像素锐利素材使用 `0`，只有检查线条锐度后才逐步接近 `1`。 | Repair 后的 EEDI2 结果会向去色带后的源亮度限幅；`0` 跳过，中间值与源亮度混合，`1` 完整应用限幅结果。 |

所有阶段均可单独设为 `0` 关闭。降噪、去光晕、去振铃和抗锯齿只改变亮度，
去色带处理 YUV。去色带与抗锯齿默认使用字面上的混合中点 `0.5`，只针对特定瑕疵的
去光晕与去振铃仍保持关闭。颗粒、纸张纹理、雨丝、刻意柔光、细线稿和高原生精度作画都可能被
自动滤镜误认为缺陷；正式压制前应检查具有代表性的明亮、暗场、纹理丰富和特效较多画面。
不能只因为两个控件同时存在就盲目同时开启去光晕和去振铃，应先判断瑕疵属于宽锐化光晕、
窄振铃环带还是刻意画面元素。

通用界面只公开这些高层混合强度。光晕半径、振铃遮罩宽度、placebo 阈值／半径、
EEDI2 阈值和重建遮罩阈值会随来源尺度与瑕疵形态互相影响，因此仍属于脚本内部参数，
不继续增加到 GUI；需要逐镜头调整这些内部值时应使用自定义 VPy。

#### 从 xyx98/my-vapoursynth-script 采用的思路

自动生成脚本吸收了
[xyx98/my-vapoursynth-script](https://github.com/xyx98/my-vapoursynth-script)
中的部分思路，但运行时不导入该包：

| 上游组件 | 自动生成 VPy 已采用 | 有意没有照搬 |
| --- | --- | --- |
| [`xvs.scale.rescale`／`MRcore`](https://github.com/xyx98/my-vapoursynth-script/blob/master/xvs/scale.py) | 仅亮度参与原生逆缩放、使用相同的 2/255 起始阈值建立重建差异遮罩，并恢复最终分辨率合成元素；色度按明确的蓝光采样位置单独缩放。 | NNEDI3 放大、分数／选择性逆缩放和逐镜头后处理；自动 getnative 已提供检测高度与准确缩放核。 |
| [`xvs.dehalo.abcxyz`](https://github.com/xyx98/my-vapoursynth-script/blob/master/xvs/dehalo.py) | 8／24／32 级宽光晕估计和 `Repair` 约束，以显式强度只混合亮度。 | 超采样和用户可调半径；它们会增加耗时，也会让单一通用强度失去清晰含义。 |
| [`MinBlur`／`HQDering` 技法](https://github.com/xyx98/my-vapoursynth-script/blob/master/xvs/dehalo.py) | MinBlur 思路候选选择、`Repair`／`LimitFilter`，以及排除边缘本身的窄邻边振铃遮罩。 | 已弃用且无人维护的 warp 类 `LazyDering`／`SADering`；它们可能移动边缘几何，还需要更多遮罩／插件。 |
| [NLMeans 指南](https://github.com/xyx98/my-vapoursynth-script/blob/master/xvs/denoise.py) | 亮度纯空间（`d=0`）、`wmode=3` 降噪，改为保守可调 `h`，并增加边缘保护与变化限幅。 | 把时域或运动补偿降噪作为通用默认；运动估计错误、切镜、速度和硬件后端均需按来源决定。 |
| [`mwdbmask` 自适应去色带思路](https://github.com/xyx98/my-vapoursynth-script/blob/master/xvs/mask.py) | 对限幅 placebo 候选增加多平面边缘／细节保护；使用内置 Prewitt 和形态学运算实现，因此生成 VPy 不需要新增 TCanny 依赖。 | 按来源调整的 TCanny 阈值、额外亮度遮罩输入与色度位置控件。 |
| 既有 EEDI2／遮罩 AA 用法 | 原先已有的双方向 EEDI2 继续使用 Repair 和限幅，现在可调并可跳过。 | `XSAA`、`drAA`、压线、锐化和色度 AA；它们更激进，需要瑕疵专用遮罩与额外依赖。 |

该仓库中的其他候选不适合作为自动默认。BM3D 封装依赖另行安装的 CPU／CUDA／CUDA-RTC／HIP
namespace 以及按来源确定的 sigma；项目管理的便携插件集目前不含任何 BM3D namespace，
而在用户选定后静默回退到其他后端会违反 Encode 执行契约。因此在硬件专用预设能够安装并
预检一个确定后端之前，BM3D 仍只适合自定义 VPy。`STPresso`、`SPresso`、`STPressoMC`、
`FluxsmoothTMC`、`SAdeband` 和 `lbdeband` 已被该项目标为弃用或无人维护；NCOP／NCED
文字遮罩还需要额外输入或逐片调整。这些路径不应静默替换可移植的默认处理链。

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

## 隔行、胶转磁与混合 cadence 来源

自动生成的 VPy 无法为所有来源安全地选择同一种自动处理。`_FieldBased` 可以说明某帧
是逐行（`0`）、下场优先（`1`）或上场优先（`2`），却不能说明场结构为什么存在。真隔行
摄像或视频素材需要反交错；3:2 胶转磁的电影或动画通常需要场匹配后抽帧（IVTC）；逐行、
胶转磁和隔行片段混合时，还可能需要按范围分别处理。盲目使用 QTGMC 可能产生不必要的
双倍帧率或保留胶转磁顿挫，盲目 IVTC 则可能丢掉真实运动场。容器元数据也可能错误，
因此应逐帧检查有代表性的运动、摇镜和片尾，确认场序与 cadence，而不能只相信一个
元数据标签。

请为对应行建立自定义 VPy，并替换 `LWLibavSource` 后面的“只允许逐行”检查。对确实为
真隔行的素材，可以从以下 QTGMC 配置开始：

```python
import havsfunc as haf

# 上场优先使用 TFF=True；下场优先使用 False。
# FPSDivisor=1 把两个时间场都保留为双倍帧率逐行视频。
src8 = haf.QTGMC(src8, TFF=True, Preset="Slower", FPSDivisor=1)
src8 = src8.std.SetFrameProps(_FieldBased=0)
```

只有明确需要单倍帧率逐行结果并检查过运动后，才改用 `FPSDivisor=2`。对规则的 3:2
胶转磁，请安装 VIVTC 等场匹配插件，改用场匹配与抽帧路径，例如：

```python
matched = core.vivtc.VFM(src8, order=1)  # order=1 为 TFF，order=0 为 BFF
src8 = core.vivtc.VDecimate(matched)
src8 = src8.std.SetFrameProps(_FieldBased=0)
```

不能只清除 `_FieldBased`；那只会改元数据，不会重建逐行画面。反交错或 IVTC 应放在
位深转换、getnative／descale、降噪和其他修复之前。混合 cadence 应拆分或按条件替换
受影响范围，而不是把一种滤镜强制用于整段。完整压制前要预览梳齿、运动 cadence、
淡入淡出和滚动 Staff，并核对输出帧率、时长与音画同步。实际压制使用的 VapourSynth
运行时必须具备 QTGMC／VIVTC 及其依赖；自定义脚本自行负责这些额外依赖。

## 默认脚本使用的插件

默认脚本是可用起点，不是适合所有片源的通用修复方案。它只接受逐行视频，遇到隔行来源会明确报错，而不会按逐行素材错误处理。L-SMASH 索引保存在系统临时目录，不会尝试写入可能只读的原盘来源旁边。启用原生逆缩放时，只有亮度使用检测到的 descale 核；色度按蓝光左侧采样位置缩放，并用重建差异遮罩在片尾文字等最终分辨率合成区域恢复原始 YUV 平面。当前滤镜链包括：

片尾 Staff、画内文字和已经烧录在来源中的字幕并不是通过 OCR 或语义识别。启用原生
逆缩放后，脚本会比较原始 16 位亮度与“先逆缩放到检测出的原生高度、再重建到输出尺寸”
的亮度，二值化绝对差超过 2 个 8 位码值（换算到 16 位）的区域，再执行两次扩张和一次
Inflate。滤镜与缩放完成后，遮罩白区会恢复原始 YUV 平面。最终母版分辨率才合成的文字
通常无法通过原生高度路径准确重建，所以滚动 Staff 和内封硬字幕通常会被保护。细纹理、
锐化、线稿或噪点也可能触发同一遮罩；这是有意保留来源的误报，并不是文字分类。可选的
外挂 ASS／SSA 内嵌字幕属于另一条路径，会由 `assrender.TextSub` 直接读取所选字幕文件
渲染，不需要识别画面文字。

| namespace／包 | 默认脚本中的作用 |
| --- | --- |
| `lsmas.LWLibavSource` | 索引式源滤镜 |
| `fmtc` | 位深转换和重采样 |
| `descale` | 按检测到的原生分辨率执行可选逆向缩放 |
| `nlm_ispc` | 降噪 |
| `placebo` | 所有受支持平台上的去色带 |
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
