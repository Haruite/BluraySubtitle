# BluraySubtitle

[English](README.md) | 简体中文

项目文档：[Wiki／媒体概念与开发者指南](docs/wiki/Home.zh-Hans.md)

开发文档：[强制代码修改规范](docs/development/code-standards.zh-Hans.md) | [媒体处理方案与工具选型](docs/development/media-pipeline-and-tool-selection.zh-Hans.md) | [重构历史](docs/refactoring/refactoring-history.zh-Hans.md)

Windows x64 版本使用目录包发布。请完整解压发布压缩包，然后运行 `BluraySubtitle_windows_x64.exe`；不要将它与旁边的 `_internal` 目录分离。首次启动时，打包的 `config.default.json` 会在可执行文件旁创建可写的 `config.json`；源码运行时则使用仓库根目录。程序目录必须可写；配置无效时程序会明确报错并保留原文件，不会覆盖。

Windows x64 下载：

- [持续更新包](https://sbx.mysmy.top/tools/BluraySubtitle_windows_x64.7z)：独立于 GitHub Release 的发布周期及时更新。
- [GitHub Releases](https://github.com/Haruite/BluraySubtitle/releases)：随每个版本发布的归档包。

BluraySubtitle 是一个面向 Windows/Linux（含 Docker）的蓝光流程 GUI 工具。它将以下五类功能整合在一个应用中：

1. **原盘 Remux**
2. **原盘压制**
3. **原盘 DIY（待开发）**
4. **生成合并字幕**
5. **给 MKV 添加章节**

---

## 亮点

- 一个应用覆盖蓝光常见全流程（Remux、压制、DIY、合并字幕、章节）。
- 所有功能自动配置，不需要学习成本，懒人只需要点两下鼠标即可完成操作。
- 软件操作自由度高，也适合高级用户。
- 具备严谨的操作逻辑以及强大的纠错能力。
- 跨平台：Windows / Linux / Docker。

---

## 更多细节

### 界面与交互

- **中英文切换**（English / 简体中文）。
- **主题切换**：浅色 / 深色 / 彩色（支持透明度调节）。
- 右上角的**设置**窗口包含常规、路径、高级、外部工具和手动检查更新选项。
- 应用设置及窗口大小和位置会保存在 `config.json` 中。
- 以表格为核心的紧凑工作流。
- 点击底部按钮即开始操作，不阻塞 UI。
- 界面配置用于内部处理，所见即所得。
- 任务只使用界面当前显示的配置；如果这些配置无法生成有效任务，任务不会启动并会明确报错。

### 剧集 / 电影模式

- 支持 **剧集模式** 分集切割，也支持 **电影模式** 不切割。
- 内置算法自动按章节时间线拆分剧集，可选每集时长用于辅助计算。
- 支持设置**起始章节 / 结束章节**（适用于 remux/压制流程中的章节区间控制）。

#### 播放列表管理

- 自动选择主播放列表且正确率高。
- 支持手动选择主播放列表，每卷原盘支持任意数量主播放列表。
- 主播放列表支持章节片段选择，和起始/结束章节拆分联动。
- 主播放列表未选中片段和其他播放列表作为特典 SP 处理。

### 轨道管理

- 除视频轨道外，每条轨道都支持独立选择。
- 内置默认轨道选择算法，适应不同类型的原盘。不选择过多轨道，同时有需要的保留。
- 支持**一键选择所有轨道**。

### 特典 SP 管理

- 每条 SP 支持独立选择。
- 自动选择包含有效信息的 SP。
- 支持多种形式的 SP，全面覆盖原盘的有效信息。

### Remux / 压制控制

- 压制模式支持两类输入源：
  - 原盘
  - Remux
- 剧集模式下，“裁剪版权片段”仅在分集结束点位于对应 M2TS 文件结尾时检查该集最后 30 秒，并通过 `--split parts` 排除完整落在此窗口内的末尾 M2TS 播放项；MPLS 时间与章节保持不变。结构判断可能有误，特殊原盘需要人工检查，必要时应手动修改混流命令的 parts 区间。详见[蓝光原盘结构](docs/wiki/Blu-ray-Disc-Structure.zh-Hans.md#末尾的短版权片段)。
- 主播放列表支持编辑混流命令（`remux_cmd`）。每个已选主播放列表必须且只能对应一条非空命令，并按照界面当前显示的顺序执行；同一分卷选择多个主播放列表时也一样。
- 写入前，程序会推导全部命令输出和最终分集文件名。输出数量必须与可见分集行一致；路径重复或文件已经存在都会报错。
- 最终分集名称严格使用界面中显示的名称，无效文件名直接报错。
- 主命令及 README 记录的 fallback 无法生成全部计划输出时，Remux 会报错停止，不会使用输出目录中的无关文件代替。
- Remux 保持已选择的有损音轨不变。“将无损音轨转换为 FLAC”默认启用（可在“高级”中配置启动状态）。所有 FLAC 输出都会优先使用支持多线程的独立 `flac` 编码器，并自动使用检测到的逻辑 CPU 线程数；编码器不可用或失败时才回退到 `ffmpeg`。两种 FLAC 编码默认级别都是 8，可在“高级”设置中分别修改。DTS 系列音轨仅在 FLAC 不大于提取出的 DTS 时才替换源音轨；如果 FLAC 更大，则删除 FLAC 并保留原 DTS。PCM 和 TrueHD/MLP 成功转换出的 FLAC 即使更大也仍然保留。TrueHD Atmos 只有在 `truehdd` 成功解码 presentation 2 后才会转换。MKVToolNix 不会修复损坏的 TrueHD 帧，部分 DIY 原盘即使 MKV 时长看起来正常，仍可能在 `truehdd` 中产生大量错误，并使解码后的 FLAC 比视频短；删除源音轨前应比较解码音频和视频时长。详细原理见 [媒体处理方案与工具选型](docs/development/media-pipeline-and-tool-selection.zh-Hans.md)。
- 原盘 Remux 中选择的字幕始终作为软字幕轨内封到对应的正片 MKV，不会内嵌到画面，也不会输出为外挂字幕文件。
- 启用“混流 Dolby Vision”时，Remux 会将兼容的基础层和增强层合并为 Profile 8.1；关闭时不包含增强层。
- 混流完成后，程序会把“编辑轨道”保存的语言应用到实际包含的视频、音频和字幕轨道并验证结果；映射、工具或验证失败时会中止当前任务并删除该任务新建的主输出。

即使关闭“将无损音轨转换为 FLAC”，程序也会自动检查最终 Matroska 输出中已选择的音轨。解码后的最大音量低于 -60 dB 时，该音轨会作为静音轨移除。只有源编码家族和声道数相同的音轨才比较解码指纹；已知语言不同的音轨不会互相去重，完全重复时保留源顺序中最早的一条。独立的单轨音频输出会按选择生成，不执行这项移除处理。

- 压制参数支持：
  - `vspipe` 来源（程序自带 / 系统）
  - 压制工具（x264 / x265 / SvtAv1EncApp）
  - 压制工具来源（程序自带 / 系统）
  - 输出视频位深（x264 - 8 / 10 bit，x265 - 8 / 10 / 12 bit；SvtAv1 正常输出仅使用 8 / 10 bit，界面中的 12-bit 路径属于实验功能，setup 脚本产物无法生成有效视频）
  - 只读的内置压制预设、用户新增预设，以及当前任务参数的直接编辑
  - 无损音频转换（flac / aac / opus）
  - 启动时的编码器、位深和预设来自“高级”设置；其中可按当前选择的压制工具新增、重命名、修改和删除用户预设，内置预设保持只读；启动后每个任务仍以 Encode 页面当前可见的预设和参数为准
  - 启动时的无损音频目标、字幕封装方式、getnative、自动裁黑边、输出对比图和检测花屏/坏帧复选框同样来自“高级”设置，并可在启动任务前继续修改
  - 上述选项下一行可调整自动生成默认 VPy 的降噪、去光晕、去振铃、去色带和抗锯齿强度；单项设为 `0` 即可关闭。只针对特定瑕疵的去光晕与去振铃默认关闭，去色带与抗锯齿默认采用适中的 `0.5` 混合；所有值也可在“高级”设置中修改
  - 自动 getnative 会分析多个帧和多种核，可能消耗大量时间与内存。Encode 只会对源高度不超过 1080 的素材运行自动 getnative；更高的源即使勾选了选项也会跳过。如需分析，请手动运行 `src/scripts/getnative_file.py`，再把返回的 `height` 和 `kernel` 分别写入 VPy 的 `native_h` 与 `native_kernel`
  - 手动脚本使用的算法会按源高度缩放搜索与曲线尾段边界：始终排除较少见的 535p 至 545p 误报带，并排除高于“源高度 × 1040 / 1080”的候选值
  - 勾选“自动裁剪黑边”时，Encode 会分析多个时间点并应用一组保守的固定裁剪值。黑边随时间变化时会优先保留任一样本用到的像素
  - 勾选“输出对比图”时，每个压制视频都会把源和压制成品的同一帧保存为 PNG，路径为 **`<所选输出目录>/<来源文件夹名>/Compare`**
  - 勾选“检测花屏/坏帧”时，Encode 会在成品完成后重新运行本次压制实际使用的 VPy，并通过 PSNR 将全部参考帧与成品 MKV 逐帧比较；JSON 报告保存在 **`<所选输出目录>/<来源文件夹名>/FrameCheck`**。这相当于压制结束后额外执行一次完整 VPy 渲染，可能需要视频时长的几倍时间
- PCM、TrueHD/MLP、DTS 系列和 FLAC 等无损音轨使用“编辑轨道”中逐轨显示的 FLAC/AAC/Opus 选项；有损音轨保持不变。TrueHD Atmos 只有在 `truehdd` 成功解码 presentation 2 后才会转换；`truehdd` 不可用或解码失败时保留原 TrueHD 音轨。选择 FLAC 时同样应用上述 DTS/FLAC 体积规则。最终 Encode 混流同样执行上述静音/重复音轨清理；原盘暂存 Remux 不处理音频。
- 字幕封装：外挂 / 内挂 / 内嵌
- 每一行支持独立 VPy 路径（正片与 SP）。
- Remux 来源支持更多功能，比如编辑章节/附件等。

### 受管理的 x264 与 x265 版本

setup 脚本运行或 Docker 镜像构建时，会动态解析官方上游的当前版本：

- **[x264](https://code.videolan.org/videolan/x264)** 使用官方 `master` 的最新版本，编译为一个同时支持 8/10 位输出的 CLI；Windows setup 使用 MSYS2 UCRT64 工具链和 PGO（配置文件引导优化）。
- **[x265](https://github.com/Multicorewareinc/x265)** 使用官方最新的稳定数字版本标签，编译为一个静态链接的 8/10/12 位 multilib CLI，三个被链接的核心都启用原生 HDR10+ JSON 输入（`--dhdr10-info`）和 Dolby Vision RPU 输入（`--dolby-vision-profile`、`--dolby-vision-rpu`）。

受管理的路径保持不变，保存在 [settings.py](src/core/settings.py)。如需使用其他构建，直接替换相同路径下对应的可执行文件即可。

setup 脚本还会安装 [hdr10plus_tool](https://github.com/quietvoid/hdr10plus_tool) 的官方最新 release。

自行编译 x265 时，可参考 `setup_windows_environment.ps1`、`setup_linux_environment.sh` 中的官方 multilib 步骤。

压制会按照界面当前显示的行顺序，应用输出名称、逐行 VPy、字幕、语言、轨道选择和压制参数。原盘输入的暂存 Remux 会保留已选择的源音轨；只有视频压制成功后，才会在最终混流阶段执行无损音频转换。

压制会自动把兼容的来源色彩与 HDR 元数据写入输出；x265 10/12 位输出还会自动保留 HDR10+。选择原盘或 Remux 来源中的 Dolby Vision 时，x265 10/12 位输出会将其保留为 Profile 8.1；x264 和 x265 8 位不能保留 Dolby Vision，SVT-AV1 会明确提示并省略。自动裁剪改变画面尺寸时，程序会同时为 x265 原生写入和备用后注入调整 Dolby Vision 有效画面元数据。

### mkvtoolnix 兼容修复

针对常见 mkvtoolnix 边缘问题，内置了修复逻辑：

- 需要时重写章节（分段/切割场景）。
- 当 `mpls` 直接混流失败时自动走修复路径：
  - 多片段轨道对齐拼接回退，
  - 多集分片输出回退，
  - 提升复杂片单混流成功率。

### 实现细节（通俗版）

这部分用更好懂的方式说明程序内部怎么做。

#### A）SP 处理规则

1. **`select/选择`** 列控制该 SP 行是否参与混流。任务会等待 SP 扫描结束，然后一次性捕获界面中的行顺序、源文件、输出名称、所选轨道和编辑后的语言。
2. MPLS 行统一使用 MPLS 逻辑；只有没有 MPLS 的行才使用 M2TS 逻辑。
3. SP 行先按 **BDMV 分卷**、再按 **MPLS 名称**排序，最后排列未被播放列表覆盖的 **M2TS**。
4. MPLS 默认输出基础名称为 **`BD_Vol_{bdmv_vol}_SP{n}`**；序号按同一原盘中已选择的 MPLS 行计算，并统一补零位数。电影模式下 table2 只有一行时省略分卷前缀，基础名称直接使用 **`SP{n}`**。
5. 剧集模式有两条相互独立的精确匹配规则。非主 MPLS 的完整 M2TS detail 与唯一一个已选主 MPLS 完全一致时，它暴露的音频和字幕 PID 会成为该主 MPLS 的可选轨道，重复的 SP 行默认不勾选。否则，只有完整 detail 与唯一一集完全一致且提供新 PID 的 SP 才默认勾选并只关联到该集。跨越多个分集输出、但不与整条主 MPLS 完全一致的 SP 保持普通 SP，不会附加到多个输出。
6. 时长小于 **30 秒**的 MPLS 和 M2TS 仍会显示，但默认不勾选；MPLS 时长中的重复文件只计算一次。
7. 包含至少三个不同文件的 MPLS 默认勾选。
8. 解码帧数不超过 12 且每帧画面都完全相同的未覆盖 M2TS（包括由少量完全相同重复帧组成的短片），以及只包含一个这种 M2TS 的 MPLS，都会默认勾选并输出为 PNG；一旦发现第 13 帧就立即停止检测并排除该源。
9. 如果 MPLS 包含多个 M2TS，且每个文件的解码帧数都不超过 12、文件内每帧画面都完全相同，则默认勾选；输出为文件夹，内部文件名为 **`{n}-{m2ts_name}.png`**。
10. 没有选择任何音轨或字幕轨道时通常会将输出名称置空并主动跳过；如果源文件被识别为纯视频，则仍使用 `.mkv`，因为视频轨是隐式包含的。
11. 纯音频源只选择一条音轨时，使用该轨道对应的裸流后缀直接提取；PCM、DTS、TrueHD 和 MLP 使用 `.flac`。
12. 纯音频源选择多条音轨时使用 `.mka`；未被 MPLS 覆盖的“音频带字幕” M2TS 也使用 `.mka`，其余视频/容器布局使用 `.mkv`。
13. 纯字幕源只选择一条字幕时使用对应裸流后缀；选择多条字幕时使用 `.mks`。
14. 编辑轨道后会立即重新计算输出名称。上述整条主 MPLS 复用规则优先判定，之后才判断相互独立的单集追加规则。对于单集匹配，分集切割变化时关联行会立即同步名称。电影模式 SP 始终使用独立的 SP 输出路径，绝不附加到正片。实际执行严格使用界面当前显示的名称，不会静默改名，也不会扫描目录后改用其他文件。
15. MPLS 容器输出会先清除已有章节，再写入从播放列表生成并移除末尾标记的章节；只有一个零点章节时不写入。
16. 扫描阶段无法读取或不支持的行会被禁用。如果已选择的源文件或已捕获轨道配置随后不可用，任务会报错，而不是静默跳过。
17. “编辑轨道”中保存的语言会应用并验证到 `.mkv`、`.mka` 和 `.mks` SP 输出，也包括追加到分集正片的轨道。裸流和图像无法保存这类元数据，因此对应的语言配置会在执行前被拒绝。
18. 未被任何 MPLS 覆盖的 M2TS 也会列出，并分类为视频、纯音频、IGS 菜单、纯字幕、音频带字幕、私有/其他、混合非视频或未知类型。不支持的布局会被禁用；IGS 菜单保持可用但默认不勾选，零时长菜单也一样。提取 IGS 菜单时会跳过所有全黑状态图片。短条目默认不勾选，但单帧规则优先。常规基础名称为 **`BD_Vol_{bdmv_vol}_{m2ts_name}`**，单行电影则直接使用 **`{m2ts_name}`**；输出类型遵循上述单帧、音频、字幕、菜单和容器规则。

**SP 混流失败时**

- 空输出名称仍表示主动跳过；所有已选择且输出名称非空的行都必须成功完成。
- 只要能够事先确定，程序会在创建输出前检查源文件、已捕获轨道、准确输出路径、路径冲突、已有文件和语言修改工具。
- MPLS 行先尝试直接混流；失败后，无论一个还是多个片段，都进入同一条轨道对齐回退路径。
- 追加到分集正片的 SP 轨道必须提供有效的 `stream_id` 或 `original_transport_stream_id`；`properties.number` 不是 transport PID，所选轨道缺少这两个 PID 字段时会失败。
- 只有准确的计划输出真实存在才算成功。任何已选择行失败都会中止任务，并只清理该任务新建的不完整输出；追加 SP 的分集文件只有在新文件完成并验证后才会被替换。

#### B）轨道对齐与缺轨修复

当播放列表中的不同片段具有不同轨道布局时，直接混流可能失败。回退流程以“编辑轨道”中选择的轨道作为参考布局，并逐个处理播放列表片段：

1. 播放范围来自 `Chapter(mpls_path).in_out_time`；只使用片段的一部分时通过 `--split parts:start-end` 裁切。
2. `mkvmerge --identify` 只映射“编辑轨道”中可见且已选择的轨道；被 MPLS 隐藏的轨道不会加入，恢复后的轨道保持 GUI 选择顺序。
3. 缺少的已选轨道使用 tsMuxer 恢复。
4. tsMuxer 无法补齐任何缺失的已选轨道（包括音轨）时明确失败，不生成合成替代轨道。
5. 修复后的 PID 集合必须与参考布局完全一致。只有一个片段时直接移动到计划输出；多个片段使用 `--append-mode file` 顺序拼接，使所有轨道使用同一个前序文件时间戳边界。
6. 主输出和独立 SP 输出随后写入已配置的轨道语言与章节，并检查命令结果和最终元数据。

一个主 MPLS 拆分成多个分集文件时仍使用独立的多输出回退，但每个片段采用相同的轨道对齐和缺轨规则，并在收尾前确认所有计划输出都存在。

#### C）`view chapters` / `start_at_chapter` / `end_at_chapter` 联动与配置重算

以下 3 组输入中的任意一项变化时，分集配置都会重新计算：

1. `table1 -> view chapters` 中 MPLS 各段勾选状态
2. `table2` 各行 `start_at_chapter`
3. `table2` 各行 `end_at_chapter`

处理优先级（按变化源判断）：

**第一优先：view chapters 勾选变化（全量重算）**

1. 从第一个“被勾选区间”开始作为第一集 `start_at_chapter`。
2. 一旦遇到“未勾选区间起点”，当前集立即结束，`end_at_chapter` 设在该处；下一集从该区间末端重新开始。
3. 目标时长与分集行一一对应：该行有字幕时取其 `max_end_time`，否则取 `approx episode length`。
4. 为尽量避免产生短尾集，定义最短有效尾段为 `max(0, approx episode length - 300 秒)`。比较终点前，排除所有“到 MPLS 结尾的剩余时长小于该阈值”的非结尾候选；文件边界和章节点都执行此过滤，`ending` 始终可选。
5. 从仍被勾选且符合尾段条件的节点中选择两个候选终点：
   - 候选 A：最接近目标时长的“文件结束点”（从 view chapters 中判断该节点与上一个节点 m2ts 是否变化）；
   - 候选 B：最接近目标时长的“章节点”。
6. 终点选择规则：
   - 若候选 A 的偏差在 `[-1/4*目标时长, +1/2*目标时长]`，优先选候选 A；
   - 否则将负偏差乘以 `-2` 后再比较 A/B，取偏差更小者作为 `end_at_chapter`。
   - 若没有有效的非结尾候选，则使用 `ending`，将尾段并入当前集。

**第二优先：start_at_chapter 变化（从首个变化集向后重算）**

1. 与上一次配置比较，确定发生变化的 MPLS 及其中最先变化的分集。
2. 变化行之前的分集以及其他 MPLS 的分集保持不变。
3. 用户选择的新起点保持不变；从该集开始，在同一 MPLS 上按相同规则重新计算当前集终点以及后续所有起止点，不复用后续旧边界。
4. 同步取消勾选：将上一集结束点与新起点之间原本勾选的节点置为不勾选；若修改的是该 MPLS 第一集，则将新起点之前的节点置为不勾选。下一段从此后第一个仍被勾选的节点开始。
5. 删除无效或被完全覆盖的行，并按需补充分集，直到覆盖该 MPLS 被勾选的尾部。

**第三优先：end_at_chapter 变化（按扩大/缩小分支处理）**

1. 当前集的起点和用户选择的终点保持不变；变化集之前以及其他 MPLS 的分集保持不变。
2. 若 `end_at_chapter` 改小：重新计算同一 MPLS 的所有后续区间，并按需补充分集，直到覆盖被勾选的尾部。
3. 若 `end_at_chapter` 改大：删除被新终点完全覆盖的后续行；第一条剩余区间从新终点处或其后第一个仍被勾选的节点开始，然后按相同终点规则重算全部后续区间。
4. 自动生成的后续区间不复用旧边界，零长度行直接丢弃。

**无字幕时的 MPLS 隔离：**每条 MPLS 独立使用 `approx episode length` 切割。前面卷重算后，其分集行数变化可以导致后续全局集数编号顺延，但不得改变后面 MPLS 已保留的 `start_at_chapter/end_at_chapter` 边界。

下拉可选性约束：

- 对于 view chapters 里未勾选的节点，`start_at_chapter` 和 `end_at_chapter` 下拉中对应项必须置灰不可选。
- 仍需满足基本约束：`end_at_chapter > start_at_chapter`。
- 最终生成的每条剧集配置必须满足 `1 ≤ start_at_chapter < end_at_chapter ≤ ending`；在 GUI 重建前删除无效、反向、零长度以及以 `ending` 为起点的行。

#### D）补充说明

- 主混流命令支持占位符：`{output_file}`、`{audio_opts}`、`{sub_opts}`、`{parts_split}`。
- 主命令结果不符合预期时，fallback 会使用已解析参数并保留明确选择的轨道；只有没有明确选择时才使用默认轨道。
- 回退完成后，全部计划输出都必须存在；主播放列表输出不完整时任务失败。
- 章节重写和语言修正放在混流后执行，主要是为了规避 mkvmerge 的边缘元数据问题。

---

## 依赖要求

### Python 依赖

- `PyQt6`
- `numpy`
- `soundfile`
- `pycountry`
- `Pillow`（代码中以 `PIL` 导入）
- `matplotlib`

示例：

```bash
pip install PyQt6 numpy soundfile pycountry pillow matplotlib
```

### 外部工具

- mkvtoolnix：`mkvmerge`、`mkvinfo`、`mkvextract`、`mkvpropedit`
- `ffmpeg`、`ffprobe`
- `flac`（>= 1.5.0）

### 压制模式额外依赖

- VapourSynth 运行时与相关插件
- `vspipe`
- `vsedit`
- `x264`
- `x265`
- `hdr10plus_tool`
- `SvtAv1EncApp`
- `fdkaac`

> 具体使用程序自带还是系统路径，取决于当前模式与设置项。“外部工具”路径检查会探测已配置的 x265：只有 x265 声明 `--dhdr10-info` 时才要求 `hdr10plus_tool`，只有 x265 同时声明两项 Dolby Vision 输入参数时才要求 `dovi_tool`。

---

## 快速开始

```bash
python src/main.py
```

1. 在顶部选择语言与主题。
2. 切换到目标功能标签页。
3. 按当前模式加载源目录/文件。
4. 检查主播放列表与表格映射。
5. 需要时调整轨道、章节范围或参数。
6. 点击底部执行按钮开始任务。

---

## 各模式使用说明

## 1）生成合并字幕

典型流程：

1. 加载原盘目录；
2. 加载字幕目录；
3. 检查路径/时长/章节映射；
4. 必要时调整顺序或映射；
5. 执行合并。

建议：

- 对不上时先检查 main MPLS；
- 路径顺序错乱时先排序或拖动行；
- 个别字幕时长异常时先修字幕再执行。
- 只有任务启动时当前表格中已勾选的行会参与合并。
- 支持 SRT、ASS、SSA 和 SUP；同一个合并输出不能混用不同字幕格式。
- 后缀会完全按照界面显示应用；预设值包含开头的点，例如 `.en` 和 `.zh-Hans`。
- 每个结果会分别写到蓝光原盘目录旁和主播放列表旁；只要任一计划输出已存在，任务就会在写入前报错，且不会覆盖文件。
- 同一原盘选择多个主播放列表时分别合并；原盘目录旁的文件会附加 MPLS 文件名以避免重名。
- “补全蓝光目录”在剧集和电影模式下都会应用。

## 2）给 MKV 添加章节

典型流程：

1. 加载蓝光章节来源（playlist/chapter 信息）；
2. 加载目标 MKV 目录；
3. 校验 main MPLS；
4. 执行章节写入。

行为说明：

- MKV 默认按文件名列出；任务启动时按照表格当前可见顺序写入章节。
- 所选主播放列表按顺序使用，并根据 MKV 时长与播放列表章节点依次匹配；MKV 文件名不要求包含 `BD_Vol_NNN`。
- 勾选“直接编辑原文件”时使用 `mkvpropedit` 写入；未勾选时使用 `mkvmerge`，将每个结果写入源 MKV 所在目录下的 `output` 子目录。
- 写入前会检查所有主播放列表、MKV 输入、所需的 MKVToolNix 程序及可预知的输出冲突。已存在的输出会明确报错，绝不覆盖。
- 修改任何 MKV 前会先完成全部章节匹配计划；如果所选主播放列表无法覆盖表格中的全部 MKV，任务会停止且不写入章节。

## 3）原盘 Remux

典型流程：

1. 加载原盘目录；
2. （可选）加载字幕目录；
3. 校验主播放列表与章节区间；
4. （可选）编辑 remux 命令；
5. 选择输出目录并执行。

Remux 使用界面当前显示的播放列表顺序、命令、章节范围、输出名称、字幕语言、轨道设置、Dolby Vision 选项和“补全蓝光目录”设置。写入前会规划全部主输出；已有输出或重复输出会中止任务，不覆盖也不自动改名。

## 4）原盘压制

典型流程：

1. 选择输入源（原盘 / Remux）；
2. 配置 VPy、x265、字幕封装等选项；
3. （可选）编辑轨道或一键全选轨道；
4. （可选）设置起始/结束章节；
5. 执行压制。

压制使用界面当前显示的行顺序、输出名称、VPy、字幕、语言、轨道选择、逐轨音频转换选项和压制参数，且绝不覆盖已有文件。原盘输入遇到已有输出时会报错；Remux 输入会逐项提示并跳过已有且非空的正片/SP 文件、外挂字幕和附带文件，然后继续处理其余内容。空的正片/SP 文件或类型错误的路径不会被视为断点，因此耗时较长的压制可以安全地在中断后继续。

---

## VPy 编辑与预览

- **编辑脚本（edit_vpy）**：使用系统关联编辑器打开。
- **预览脚本（preview_script）**：使用 `vsedit` 打开，并按当前行上下文准备预览参数。
- 自动生成的默认 VPy 把处理后的 `res` 设为输出索引 `0`，把原始 `src8` 设为输出索引 `1`。在 VSEdit 预览窗口中按帧号同步，并通过 **Output index** 在 `0` 和 `1` 之间切换，即可查看同一帧处理前后的画面；这项实时预览不同于压制完成后由“输出对比图”生成的 PNG 文件。
- 默认脚本路径为 `vpy.vpy`。
- 自动生成的默认脚本不会自动处理隔行视频，因为真隔行、胶转磁和混合 cadence 需要不同方案；请按 [Encode／VapourSynth Wiki](docs/wiki/Video-Encoding-and-VapourSynth.zh-Hans.md#隔行胶转磁与混合-cadence-来源) 说明使用自定义 VPy。

---

## 仓库辅助脚本

- [`src/scripts/batch_remux_movie.py`](src/scripts/batch_remux_movie.py)：修改脚本内路径或通过命令行传入路径，可批量 Remux 一个电影目录下的全部 BDMV。
- [`src/scripts/getnative_file.py`](src/scripts/getnative_file.py)：修改 `video_file` 后直接运行，可输出单个视频的自动 getnative 结果与耗时秒数。

---

## setup_windows_environment.ps1（Windows 环境配置脚本）

`setup_windows_environment.ps1` 用于为 **Windows 客户端和 Windows Server x64 系统**配置完整的本地运行与编译环境。

首次运行前，先允许当前用户执行本地 PowerShell 脚本，再从仓库根目录启动：

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned -Force
.\setup_windows_environment.ps1
```

脚本会申请管理员权限、询问显示语言，并支持中断后重新运行。下载时会自动使用已配置的 **Windows 系统代理**；如果无法直连下载源，请先配置系统代理再启动脚本。

---

## setup_linux_environment.sh（Linux 运行环境脚本）

`setup_linux_environment.sh` 用于构建 Linux 程序运行环境，仅支持 **x64** 系统。当前支持的发行版：

- Ubuntu 22.04 或更高版本
- Debian 12 或更高版本

首次运行前先授予脚本执行权限，再从仓库根目录启动：

```bash
chmod +x setup_linux_environment.sh
./setup_linux_environment.sh
```

建议在远程终端中执行 `setup_linux_environment.sh`，因为远程终端会使用 tmux 输出，日志更简洁、更易读。

---

## Docker

构建镜像：

```bash
docker build -t bluray-subtitle-ubuntu .
```

拉取预构建镜像：

```bash
docker pull haruite/bluraysubtitle:latest
```

运行示例：

```bash
xhost +local:docker
sudo docker run -it --rm \
  --device /dev/snd \
  -e DISPLAY=$DISPLAY \
  -e LIBGL_ALWAYS_SOFTWARE=1 \
  -v /tmp/.X11-unix:/tmp/.X11-unix \
  -v /path/to/media:/data \
  --ipc=host \
  --shm-size=2gb \
  bluray-subtitle-ubuntu
```

Apple Silicon（amd64 容器）示例：

```bash
docker build --platform linux/amd64 -t bluray-subtitle-ubuntu .
docker pull --platform linux/amd64 haruite/bluraysubtitle:latest
```

---

## 常见问题排查

- 剧集映射不对：
  - 检查 main MPLS，播放MPLS，选择正确的MPLS；
  - 检查章节起止。
  - 检查字幕行顺序，可以点击文件名 header 栏排序。
  - 检查字幕时长，如果时长超长，很有可能是字幕文件有问题。可以右键 edit 编辑字幕，编辑字幕时会优先展示结束时间最晚的那些字幕，对有问题的字幕，修改其结束时间后保存，或者一并选择右键删除即可。
- 存在特典盘：
  - 取消特典盘分卷的 main MPLS 选择即可。
- 预览无法启动：
  - 检查 `vsedit` 路径；
  - 检查 VPy 文件与插件可用性。
- Docker/Linux 播放异常：
  - 检查 DISPLAY、音频转发、mpv 可用性。

---

## FAQ

### 压制会自动裁黑边吗？

可以，但需要主动勾选。程序不会落地截图，而是分析多个时间点，并使用能覆盖全部样本有效画面的保守固定裁剪值。这能处理许多固定黑边或黑边随时间变化的来源，但暗场、片头片尾、叠加元素和特殊母版仍可能让自动结果出错。请务必核对界面报告的裁剪值及压制后画面；需要精确控制时应关闭此选项，并在 VPy 中明确写入裁剪逻辑。

### 如何快速测试压制，不跑完整片？

如需快速测试视频侧流程，可在 VPy 最后两行输出语句前截取开头一段：

```python
res = res.std.Trim(first=0, length=720)
```

必须保持 `first=0`，这样“输出对比图”使用的来源与成品帧号才仍然对应。该写法只会缩短处理后的视频：getnative 和已选择的音轨转换仍会检查或处理完整来源，最终 MKV 中的来源音轨、软字幕和章节也不会同步截短；HDR10+ 会因完整来源时间轴与 VPy 输出不一致而被省略，这也不能作为可靠的完整 Dolby Vision 测试。若要测试全部压制流程，应使用视频、音频、字幕、章节和动态元数据已经同步截短的短 MKV。

### 为什么 remux 出来的体积比原盘大？

大概率存在重复的特典片段。解决方法: 检查各 mpls，点击查看章节，如果有 mpls 的片段与主 mpls 的片段重叠，选择该 mpls 为主 mpls，然后点击查看章节，取消重复段落的勾选，注意下方 SP 表会出现对应的项目，反选即可。

### 压制有给章节加 OP 和 ED 标识吗？

没有，如果需要，先 remux 原盘，然后在原盘压制界面选择源为 remux，这时候可以点击编辑章节自行编辑章节标题。

### 为什么 getnative 获取的每集的原始分辨率不一样？

正常现象，因为有些原盘不止一种原生分辨率，以及原盘制作流程的复杂性，导致源分辨率难以分辨。可以先跑一遍测试，如果每集输出的原始分辨率结果基本相同则可以用程序自动的 getnative，否则去掉勾选自动 getnative 选项并编辑 vpy 填入你认为的原始分辨率和缩放算法，或者根本不填。

### 程序可靠吗？ai 写的代码有保证吗？

请自行分辨，要有点自主判断能力。

---

## 鸣谢（Credits）

- [tsMuxer](https://github.com/justdan96/tsMuxer)
- [BluRay](https://github.com/lw/BluRay)
- [shinya](https://github.com/shimamura-hougetsu/shinya)
- [ass2bdnxml](https://github.com/Masaiki/ass2bdnxml)
- [BDSup2Sub](https://github.com/mjuhasz/BDSup2Sub)
- [Spp2Pgs](https://github.com/subelf/Spp2Pgs)
- [getnative](https://github.com/Infiziert90/getnative)
- [my-vapoursynth-script](https://github.com/xyx98/my-vapoursynth-script)
