# BluraySubtitle 开发者指南

[English](BluraySubtitle-Developer-Guide.md) | 简体中文

本页把媒体模型与项目源码对应起来，描述的是当前行为而非重写提案。进行修改时仍以强制性的[代码修改规范](../development/code-standards.zh-Hans.md)为准。

## 领域定义

代码与界面统一使用[主 MPLS 和 SP 定义](Blu-ray-Disc-Structure.zh-Hans.md#本项目中的正片与-sp)。GUI **片段**是章节／文件区间：勾选区间进入正片，未勾选区间成为 SP 候选。它不同于 Matroska `Segment`、PGS segment 或 TS 数据包。

## 源码导航

### 蓝光结构

| 源码 | 职责 |
| --- | --- |
| `src/bdmv/structures/mpls_header.py` | 顶层 MPLS 头和区域地址 |
| `src/bdmv/structures/playlist.py` | 播放项与子路径集合 |
| `src/bdmv/structures/play_item.py` | 片段引用、标记、45 kHz `INTime`/`OUTTime`、多角度和 STN |
| `src/bdmv/structures/playlist_mark.py` | 播放列表标记集合 |
| `src/bdmv/structures/playlist_mark_item.py` | 标记类型、播放项引用、时间戳、PID 和时长 |
| `src/bdmv/structures/stn_table.py` | 流分类数量和条目 |
| `src/bdmv/structures/stream_entry.py` | PID／子路径流寻址 |
| `src/bdmv/structures/stream_attributes.py` | 编解码、格式、采样率／帧率和语言属性 |
| `src/bdmv/structures/sub_path.py` | 次要同步路径 |
| `src/bdmv/mpls.py` | 读取／保存 MPLS、汇总逻辑 STN 轨道，并根据 CLPI 修补 STN 表 |

结构化解析器使用 `InfoDict` 记录和显式大端字节打包／解包。可变长度结构以其声明长度为准。结构大小变化后，序列化前必须执行相应的 `update_counts()`、`update_constants()` 和 `update_addresses()`。

### 播放列表时间与章节

`src/bdmv/chapter.py` 是工作流使用的轻量解析器。`Chapter` 会读取：

- `PlayListStartAddress`；
- 每个播放项的片段名称、`INTime` 和 `OUTTime`；
- 按所引用播放项分组的播放列表标记。

它公开：

```python
in_out_time: list[tuple[str, int, int]]
mark_info: dict[int, list[int]]
```

`get_total_time()` 对 `(out_time - in_time) / 45000` 求和。

`chapter_play_item_file_ranges()` 会把这些不可变的播放项行与对应 CLPI 呈现范围组合起来；`episode_tail_trim_plan()` 根据该结构推导每集的 parts 结束时间和受影响的 M2TS 名称，但不会替换 `in_out_time` 或 `mark_info`。GUI 会把推导出的结束时间捕获到行配置中，只从可见 M2TS 列移除受影响的名称，并在启动 Worker 前生成可执行的 `--split parts` 区间。

### CLPI

`src/bdmv/clpi.py` 读取序列／节目元数据和呈现区间，将 M2TS 映射到同编号 CLPI，并建立 PID 语言映射；中文语言变体统一为 `zho`。解析器未实现完整 CPI 跳转索引，字段说明见 [CLPI 结构](Blu-ray-Disc-Structure.zh-Hans.md#clpi-二进制结构)。

### M2TS

`src/bdmv/m2ts.py` 负责传输包对齐、有状态 PAT/PMT 与 PES 拼装、PTS/PCR 时间及回绕、AVC/HEVC 帧率解析和针对性 ffprobe 回退、布局分类、IGS 图像解码，以及基于 CLPI 的 STN 修复。常量为 `frame_size = 192`、`_TS_PACKET = 188`、`_SYNC = 0x47`，字段见[二进制结构](Blu-ray-Disc-Structure.zh-Hans.md#m2ts-二进制结构)。

时长优先使用 PCR，缺失时回退 PTS；单帧输入的首尾 PTS 可能相同，需单独处理帧数。读取范围有界，PAT/PMT 拼装跨包保持状态。

### Matroska

`src/domain/media/mkv_container.py` 包含一个小型 EBML 读取器，直接从 `Segment/Info` 获取时长，避免仅为时长执行完整 `mkvinfo` 扫描。它还通过配置的 MKVToolNix 工具提供章节操作。

该读取器有意保持很窄的职责。一般 Matroska 识别、重混流、轨道提取、元数据编辑、追加和切割仍由 MKVToolNix 负责。

### 字幕

`src/domain/subtitles/pgs.py` 读写 SUP 包、计算结束时间，追加时以 90 kHz 单位平移时间戳，裁切时选择数据包并重定位。包头与显示集见 [PGS](Media-Formats-and-Dolby-Vision.zh-Hans.md#pgs--presentation-graphics)。

同目录还包含 SRT/ASS/SSA 模型、时间／样式／事件处理和 ASS-to-SUP 转换。SRT 裁切只保留完整位于区间内的字幕并重新编号。ASS 按声明的 `Format:` 解析，保留末尾文本字段中的逗号；SRT-to-ASS 将基本粗体、下划线、斜体和字体颜色标记转成覆盖标签。

### 工作流与工具集成

| 源码 | 职责 |
| --- | --- |
| `src/runtime/remux.py` | Remux 请求／领域类型和共享行为 |
| `src/runtime/sp.py` | SP 条目／任务类型和 M2TS detail 区间解析 |
| `src/runtime/encode.py` | Encode 请求／领域类型 |
| `src/runtime/audio_conversion.py` | 音频提取、分析、转换和清理辅助逻辑 |
| `src/runtime/dolby_vision.py` | `dovi_tool` 准备、profile 8.1 转换和 RPU 注入 |
| `src/runtime/services_split/remux_and_episode_workflows.py` | 主重混流和剧集执行 |
| `src/runtime/services_split/subtitle_and_chapter_pipeline.py` | 字幕、章节和 SP 规划／执行 |
| `src/runtime/services_split/media_info_and_track_mapping.py` | 媒体探测和标识符映射 |
| `src/runtime/services_split/encode_and_audio_tasks.py` | Encode 和最终音频处理 |
| `src/runtime/gui_runtime_split/sp_chapter_segment_logic.py` | 主片段与 SP 的 GUI 关系 |
| `src/runtime/gui_runtime_split/scan_and_worker_hooks.py` | 扫描启动和 Worker 集成 |

GUI 是执行契约。工作流会在启动 Worker 前，把当前可见选择、顺序、输出名、章节范围、命令、轨道、语言、音频策略、字幕模式和 Dolby Vision 设置捕获为普通请求数据。

## 内容发现模型

简化后的扫描管线：

```text
定位 BDMV 根目录
    ↓
枚举并解析 MPLS
    ↓
估算／选择主播放列表
    ↓
展开主播放项和章节／文件边界
    ↓
应用主片段勾选状态和剧集章节范围
    ↓
把其他 MPLS、排除区间和未覆盖 M2TS 统计为 SP
    ↓
根据 STN 构建 MPLS 选轨；检查原始 M2TS SP 元数据
    ↓
填充选轨与输出规划
```

自动主播放列表选择只是便利功能，不是最终权威。对于分支、混淆、合集和多标题等异常原盘，仍需人工选择。

默认估算由 `src/runtime/services_split/lifecycle_and_configuration.py` 中的 `get_main_mpls()` 实现，评分规则见[主播放列表估算](Blu-ray-Disc-Structure.zh-Hans.md#自动估算主播放列表的方式)；`checked=True` 时将 M2TS 体积因子替换为 `1`。

## 时间模型

### 时钟域

开发者必须明确区分：

| 数值 | 时钟 |
| --- | ---: |
| MPLS `INTime`、`OUTTime` 和标记 | 45,000 tick/s |
| MPEG PTS 和 DTS | 90,000 tick/s |
| PCR base | 90,000 tick/s |
| PCR extension | 27,000,000 tick/s |
| Matroska 时间戳 | 每 tick 为 `TimestampScale` 纳秒 |
| PGS SUP PTS/DTS | 90,000 tick/s |

变量名应体现所在时钟域，或在明确边界处换算。不要让一个没有单位限定的 `time` 整数跨越多个层次传递。

### 播放项窗口换算

使用[MPLS 到 M2TS 的窗口公式](Blu-ray-Disc-Structure.zh-Hans.md#intime-与-outtime)，计入初始传输 PTS。该页也说明时钟回绕和访问单元边界限制；时间戳精度不代表流复制能逐帧／逐样本精确切割。

## 分集配置

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

## 轨道标识模型

工作流至少涉及：

| 标识 | 所属层 |
| --- | --- |
| PID | MPEG 传输流 |
| stream type | PMT／蓝光流编码 |
| MPLS stream entry | 编排的播放项可见性 |
| CLPI 流 PID／语言 | 片段元数据 |
| MKVToolNix 输入轨道 ID | 某个被识别的输入 |
| Matroska track number／UID | 最终容器 |
| GUI 行和选择顺序 | 用户执行契约 |

MKVToolNix 的 `properties.number` 不是传输 PID。SP 追加／恢复需要真正的 `stream_id` 或 `original_transport_stream_id`。无法映射有效 PID 时，所选任务必须失败，不能猜测。

逻辑轨道身份及编排可见性遵循 [STN 模型](Blu-ray-Disc-Structure.zh-Hans.md#stn-表)。GUI 兼容检查涵盖编码、视频格式／帧率／动态范围、音频格式／采样率及 TextST 字符编码；已捕获的来源 MPLS／STN 槽位须与逐 PlayItem PID 和工具内部 ID 分开。

[Remux 回退](../development/media-pipeline-and-tool-selection.zh-Hans.md#3-轨道对齐的-remux-回退)负责片段校验及直接／回退路径选择。主混流命令使用 `{video_opts}`、`{audio_opts}`、`{sub_opts}`，执行时根据已捕获选择填入。

## 主 Remux 管线

`remux_and_episode_workflows.py` 执行已捕获请求：预检查、每条主 MPLS 的单条命令、SP、章节／语言、最终音频／Dolby Vision 处理及输出验证。[媒体处理流程](../development/media-pipeline-and-tool-selection.zh-Hans.md#当前处理流程)定义直接 MPLS 混流、逐 PlayItem 恢复及多输出分集；这些路径共用同一请求和最终验证契约。

## SP 管线

`src/runtime/sp.py` 提供条目／任务类型和精确 M2TS detail 区间。[SP 规则](Blu-ray-Disc-Structure.zh-Hans.md#本项目中的正片与-sp)定义发现、默认选择、输出命名及整条正片／单集匹配。

MPLS 行先直接混流，再使用共用轨道对齐回退。分集关联 SP 优先使用 MPLS `stream_id`；映射缺失或不一致时，先生成 PID 对齐中间输出，再使用其规范映射。原分集轨道顺序保持不变，接受的 SP 轨道按选择顺序追加。

可提前确定时，写入前检查所选来源、已捕获轨道、准确输出路径、冲突及所需语言工具。Remux 中已选行失败会停止任务，只清理任务创建的不完整输出；分集须在追加结果完成并验证后才替换。Encode 批处理的失败规则见[代码规范](../development/code-standards.zh-Hans.md#5-预检查与失败处理)。

## 音频处理

`src/runtime/audio_conversion.py` 负责提取、清理、有效位深、转换、区间重建及验证。共用事务见[音频转换规则](../development/media-pipeline-and-tool-selection.zh-Hans.md#音频转换规则)和 [FLAC／中间 PCM](../development/media-pipeline-and-tool-selection.zh-Hans.md#flac-与中间-pcm)；暂存与最终音频处理的区别见[压制管线](Video-Encoding-and-VapourSynth.zh-Hans.md#bluraysubtitle-压制管线)。

## 自动裁剪黑边

`src/runtime/video_crop.py` 负责采样、矩形汇总，以及受管理 VPy 裁剪块的替换／移除。采样规则和自定义脚本边界见[裁剪说明](Video-Encoding-and-VapourSynth.zh-Hans.md#自动裁剪黑边)。

## Dolby Vision 处理

`src/runtime/dolby_vision.py` 负责工具校验、任务自有基础层／RPU 中间文件、L5 裁剪修改、注入与清理。分层语义见 [profile 8.1](Media-Formats-and-Dolby-Vision.zh-Hans.md#本项目中的-profile-81)，编码器适用条件和验证结果见 [HDR 处理](Video-Encoding-and-VapourSynth.zh-Hans.md#自动-hdr-元数据处理)。

## 字幕处理

字幕最大结束时间参与分集时长估算，所选 SRT/ASS/SSA/SUP 按可见顺序映射到正片输出行；同一合并输出不能混用字幕格式。时长异常属于应修复的源数据问题，不能据此静默重排行或截断区间。输出封装遵循[字幕模式](Media-Formats-and-Dolby-Vision.zh-Hans.md#软字幕硬字幕与外挂字幕)。

## 错误与验证规则

遵守[预检查与失败处理要求](../development/code-standards.zh-Hans.md#5-预检查与失败处理)。执行后验证计划文件、所选轨道布局、章节／语言和请求的 HDR 结果。退出成功不能单独证明流和时长完整，[损坏 TrueHD](../development/media-pipeline-and-tool-selection.zh-Hans.md#当前限制不修复损坏的-truehd)就是已记录的例子。

## 相关测试

| 测试文件 | 主要覆盖 |
| --- | --- |
| `tests/test_m2ts_parser.py` | TS/M2TS 对齐、PAT/PMT、时钟和轨道分类 |
| `tests/test_sp_workflow.py` | SP 规划、准确输出、追加／恢复和 PID 映射 |
| `tests/test_remux_workflow.py` | 主 Remux 契约和回退 |
| `tests/test_encode_workflow.py` | Encode 请求、暂存、恢复执行和最终混流 |
| `tests/test_video_crop.py` | 时长自适应采样、裁剪合并和受管理 VPy 插入 |
| `tests/test_audio_dolby_vision_workflow.py` | 音频转换／清理和 Dolby Vision |
| `tests/test_add_chapters_workflow.py` | 主播放列表顺序和章节到 MKV 的映射 |
| `tests/test_ass2sup.py` | ASS → SUP 生成 |
| `tests/test_worker_configuration_boundaries.py` | 已捕获 GUI 配置的不可变性 |

按[测试规范](../development/code-standards.zh-Hans.md#11-测试与修改报告)选择运行或修改哪些测试。
