# BluraySubtitle 开发者指南

[English](BluraySubtitle-Developer-Guide.md) | 简体中文

本页把媒体模型与项目源码对应起来，描述的是当前行为而非重写提案。进行修改时仍以强制性的[代码修改规范](../development/code-standards.zh-Hans.md)为准。

## 领域定义

### 主 MPLS

在 BluraySubtitle 中，**主 MPLS** 是所选播放列表，其编排的播放内容属于正片电影或剧集主体。

这是语义选择，不能简化为：

- 编号最小或最大的播放列表；
- 最大的 M2TS；
- 最长的 MPLS；
- 某个库返回的第一个播放列表；
- 每卷原盘只能选择一个播放列表。

一卷原盘可以选择任意数量的主播放列表。每个所选主 MPLS 必须且只能对应一条非空主重混流命令，并按照当前 GUI 可见顺序处理。

### SP

**SP** 是项目对所选主播放列表内容之外的附加原盘内容的分类，包括：

- 其他 MPLS 播放列表；
- 所选主 MPLS 中未勾选的片段；
- 没有被任何 MPLS 覆盖但有用的 M2TS；
- 与主内容共用 M2TS、但使用不同时间区间的特典；
- 应用能够确定性处理的视频、纯音频、纯字幕、音频加字幕、IGS 菜单和单帧布局。

这里的 SP 不是蓝光规范缩写，也不是编解码格式或容器。UI 和代码注释必须保持这一定义。

### Segment／片段

在主播放列表 UI 中，**片段**是根据播放列表结构派生出的、用户可见的章节／文件区间。已勾选片段用于配置主剧集，未勾选片段排除在主输出之外并成为 SP 候选。

这里的 UI 片段与 Matroska `Segment`、PGS segment 或 MPEG-TS 数据包并不是同一概念。

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

`src/bdmv/clpi.py` 当前读取：

- SequenceInfo 中的 ATC/STC 条目；
- 呈现起止时间；
- ProgramInfo 中的节目；
- Program Map PID；
- 基本流 PID；
- 流编码元数据和语言。

它还会把 M2TS 路径映射到同编号 CLPI，并构建 PID → 语言映射。为保证选轨一致性，中文语言变体会规范化为 `zho`。

该解析器当前没有实现完整的 CLPI CPI 索引。除非以后增加并测试相关支持，否则代码和文档不能宣称项目实现了基于 CPI 的精确数据包跳转。

### M2TS

`src/bdmv/m2ts.py` 实现项目的原生传输流检查：

- 识别 192 字节 M2TS 和 188 字节 TS 布局；
- 按大块读取并迭代对齐后的 188 字节数据包；
- 从 TS 头提取 PID 和 PUSI；
- 组装 PES 头以获取第一个和最后一个 PTS；
- 优先使用 PCR 计算时长，并以 PTS 回退；
- 处理有限宽度时间戳回绕；
- 从 AVC/HEVC 参数集读取原生帧率，必要时定向回退到 ffprobe；
- 组装跨多个数据包的 PAT/PMT 区段；
- 报告流 PID、类型、编解码格式和语言 descriptor；
- 分类片段布局；
- 把受支持的 IGS 调色板／对象／按钮状态解码为 PNG；
- 在修复过程中根据 CLPI 构建 MPLS 流条目和属性。

重要常量：

```python
frame_size = 192
_TS_PACKET = 188
_SYNC = 0x47
```

PAT/PMT 组装必须跨数据包保持状态。UHD PMT 可能大于一个 TS payload，必须处理 PUSI pointer byte 和声明的 PSI section length。

时长优先采用 PCR，因为它表示传输流的节目时钟。找不到适用 PCR 时才使用 PTS。单帧流的第一个和最后一个 PTS 可能相同，帧数逻辑会单独处理这种情况。

### Matroska

`src/domain/media/mkv_container.py` 包含一个小型 EBML 读取器，直接从 `Segment/Info` 获取时长，避免仅为时长执行完整 `mkvinfo` 扫描。它还通过配置的 MKVToolNix 工具提供章节操作。

该读取器有意保持很窄的职责。一般 Matroska 识别、重混流、轨道提取、元数据编辑、追加和切割仍由 MKVToolNix 负责。

### 字幕

`src/domain/subtitles/pgs.py` 按以下结构解析裸 SUP 数据包：

- 两字节 `PG` magic；
- 32 位 PTS 和 DTS；
- 一字节 segment type；
- 两字节 segment length；
- segment payload。

它能够计算字幕结束时间、迭代时间戳、写出数据包、按 90 kHz 偏移追加另一条 PGS，以及选择并重置某个时间区间。

`src/domain/subtitles` 下的其他文件实现 SRT、ASS/SSA 模型、时间换算、样式／事件处理和 ASS → SUP 转换。

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
读取 STN/CLPI 及原生 PAT/PMT/PCR/PTS 信息
    ↓
填充选轨与输出规划
```

自动主播放列表选择只是便利功能，不是最终权威。对于分支、混淆、合集和多标题等异常原盘，仍需人工选择。

默认估算由 `src/runtime/services_split/lifecycle_and_configuration.py` 中的 `get_main_mpls()` 实现，评分含义参见[蓝光原盘结构](Blu-ray-Disc-Structure.zh-Hans.md)。该函数先对不同引用 M2TS 的体积求和，再将总量乘入评分；`checked=True` 时会把 M2TS 体积因子替换为 `1`。候选替换使用严格的 `>`，因此完全同分时会保留 `os.listdir()` 返回的第一条路径；不能把该顺序当成稳定的数字文件名排序。

SP 行按 BDMV 卷序号、MPLS 名称、未覆盖 M2TS 名称排序。扫描器仍会显示已被主内容完整覆盖的条目，但默认不勾选。短内容也保持可见，除非满足其他有效性规则，否则通常不勾选。

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

设 M2TS 的第一条相关 PTS 为 `first_m2ts_pts`：

```python
start = (in_time * 2 - first_m2ts_pts) / 90000
end = start + (out_time - in_time) / 45000
```

这是项目逐片段回退使用的有效文件相对窗口，能够考虑非零传输时间戳。

### 时间戳回绕

PTS/PCR base 是有限位宽计数器。计算经过时间时必须按时钟范围取模。直接使用有符号减法，会在源跨越回绕点时得到负数或异常巨大的时长。

### 边界行为

视频、音频、PG 和 IG 不一定具有相同的访问单元边界。请求时间具有毫秒精度，并不代表复制式裁切就能达到帧／采样级精确。

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

完整的 MPLS STN 布局是编排参考。逻辑轨道按跨 PlayItem 的 STN 类别和 Stream Number 序号标识，不要求 PID 固定不变。某个 STN 片段为对应 PlayItem 提供 PID 和格式属性；没有片段表示合法的时间线空档。PAT/PMT 中物理存在、但被该 PlayItem STN 隐藏的流，不能进入普通标题映射，除非独立 SP 工作流明确选择它。

有 MPLS 的“编辑轨道”行汇总每个 PlayItem 的 STN，并按第一次出现时的 PID 排列。加载期间不执行 `mkvmerge --identify`，也不检查 M2TS。每条逻辑轨道会显示来源 MPLS／槽位、全部不同 PID 和简明状态，提示中会合并 PID 与语言相同的连续 PlayItem。行语言取第一次出现的非 `und` 明确语言，后续语言变化只作信息提示；如果 MPLS 中的编码、视频格式／帧率／动态范围字段、音频格式／采样率字段或文本字幕字符集发生变化，因为这些片段不能安全地组成一条 Matroska 轨道，整行会被禁用。IGS 会显示但不可选择，因为 Matroska 没有交互图形字幕轨道。

主 Remux 命令保存 `{video_opts}`、`{audio_opts}` 和 `{sub_opts}`，而不是轨道 ID。执行时，内部 M2TS 解析器先把每个已声明片段与对应 PAT/PMT 核对；PID 缺失或传输编码冲突通常会使输出失败，因为“编辑轨道”具有最高权威。启用默认关闭的部分缺失选项后，只允许物理缺失的音频或字幕片段进入回退；如果 tsMuxer 也无法提供，该片段改为空档。整条已选逻辑轨道在输出中缺失、任何视频缺失和任何格式冲突仍会报错。完成内部检查后，才使用 MKVToolNix 分析结果选择直接 MPLS 混流或回退。这项检查有意不声称能够发现 MPLS 和 PAT/PMT 没有暴露的载荷级参数变化。

## 主 Remux 管线

简化后的成功路径：

```text
已捕获的不可变请求
    ↓
预检查所有播放列表、命令、轨道、工具和输出
    ↓
每个所选主 MPLS 执行一条非空主命令
    ↓
验证所有预期主输出
    ↓
处理所选 SP 任务
    ↓
应用章节、语言和元数据
    ↓
一次性提取所选音频用于清理／转换
    ↓
按策略移除静音／完全重复音频
    ↓
启用时转换所选无损音频
    ↓
把兼容 Dolby Vision 输入转换为受支持的 profile 8.1
    ↓
验证最终输出
```

蓝光 Remux 中，已存在的计划输出属于错误，不能覆盖或重命名。清理只能删除当前任务创建的不完整文件。

### 直接 MPLS 混流

MKVToolNix 是主重混流器，因为它能够理解 MPLS 播放项、片段相对时间、Matroska 轨道元数据、章节、切割和追加。

首先尝试直接混流。成功不仅要求命令完成，还要求计划输出存在，并在后续元数据检查中匹配。

### 轨道对齐回退

PlayItem 之间的 PID、本地 MKVToolNix 轨道 ID 或轨道存在性发生变化时，直接 MPLS 混流可能失败。回退流程：

1. 获取逻辑 STN 行和 `Chapter(mpls_path).in_out_time`；
2. 按准确区间处理每个 PlayItem，并且只纳入该 PlayItem 中实际存在的已选逻辑轨道片段；
3. 先让 MKVToolNix 重混流它能够暴露的已声明 PID，只有 MKVToolNix 遗漏已声明片段时才请求 tsMuxer 恢复；
4. 要求每个 PlayItem 结果准确包含本段预期存在的轨道，不为 STN 空档生成静音或空轨；
5. 为每条逻辑轨道第一次出现的片段设置绝对播放列表偏移，再通过显式轨道追加把后续片段逐段接到上一片段，并在需要时加入空档偏移；
6. 最终只用一次 `mkvmerge` 写入成品，再应用并验证章节与轨道语言；
7. 回退本身只复制码流；完整 Matroska 产物随后与直接 Remux 一样进入独立的音频后处理阶段。

tsMuxer 无法恢复某个片段时通常会使回退失败。部分缺失选项只允许 PAT/PMT 同样确认物理不存在的非视频片段改为空档：它会从该分段的预期布局中移除，并把对应区间记录为时间线空档。tsMuxer 已识别 PID 后再发生分离失败仍属于致命错误。最终写入前，每条已选逻辑轨道都必须至少实际出现一次。MKVToolNix 因载荷级变化拒绝追加时同样会失败；逐 PlayItem 临时文件不会被提升为最终输出。

### 为什么不能物理拼接 M2TS

物理拼接会忽略：

- 每个播放项的 `INTime` 和 `OUTTime`；
- STC/PTS 偏移；
- 重复片段；
- 分支顺序；
- 不同轨道布局；
- 编排后的流可见性；
- 章节时间。

任何合并播放项的优化都必须证明以上属性仍然等价。

## SP 管线

行的源类型决定处理路径：

- 有 MPLS 的行必须使用播放列表逻辑；
- 只有没有 MPLS 的行才使用裸 M2TS 逻辑。

所有已选择且输出名非空的行都必须完成。没有选择音频或字幕时，空输出名表示已记录的有意跳过。

输出类型由所选内容决定：

- 普通视频／容器输出 → `.mkv`；
- 单条裸音频或字幕 → 对应基本流扩展名；
- 多条音轨 → `.mka`；
- 多条字幕 → `.mks`；
- 单帧 → `.png`；
- 多个单帧片段 → 带编号的图片目录。

裸流和 PNG 无法保存 Matroska 轨道语言元数据。为不兼容输出配置这类元数据时，应在执行前拒绝。

剧集模式将两种精确 detail 机制分开处理。非主 MPLS 的完整有序 M2TS detail 与一条完整的已选主 MPLS 完全一致时，它提供的不重复音频和字幕轨道会加入该主 MPLS 的共享 GUI 轨道配置；对应 SP 行默认不勾选，避免重复重混流。合并后的行标明来源 MPLS／STN 槽位，按代表 PID 排列，并统一执行一次默认选轨算法。此机制绝不根据 table2 的单个分集行推导整条主 MPLS 匹配。

只有整条主 MPLS 规则不适用时，detail 与唯一一个 table2 分集完全一致的 SP 才能在分集完成后追加。主 MPLS 和 SP MPLS 各自独立执行同一默认选轨算法。实际附加时，每条逻辑轨道用绝对 `(M2TS 路径, PID)` 对应关系表示；只有这些关系都没有被剧集或更早的附加轨道占用时，候选轨道才算新增。PID 或 STN 槽位本身不作为跨文件身份。原剧集轨道保持顺序，接受的 SP 轨道按选择顺序随后排列。跨越多个分集行的 detail 不会关联多个输出，而是保持普通 SP。电影模式 SP 不进入以上任一附加路径。只有追加结果完成并验证后，才替换原剧集文件。

《Witch Craft Works Blu-ray BOX》的 DISC3 存在一种编排时间区间特例：`00002.mpls` 从 `00:00:00.000` 使用 `00006.m2ts`，但从 `00:00:02.002` 才开始使用 `00007.m2ts` 至 `00011.m2ts`；对应的独立 `00004.mpls` 至 `00008.mpls` 都从 `00:00:00.000` 开始使用同名片段。类似地，`00010.mpls` 从零开始使用 `00013.m2ts`，但从 `00:00:02.002` 才开始使用 `00014.m2ts` 至 `00024.m2ts`，而各独立播放列表仍从零开始。SP 覆盖按片段的精确时间区间判断，不按 M2TS 文件名集合判断，也不根据 table3 行之间的包含关系去重。因此，独立行多出的开头 `2.002` 秒会让它保持为普通且默认勾选的 SP，不能仅因为某条聚合 SP 引用了同一 M2TS 就取消勾选。

## 音频处理

最终 Matroska Remux 与 Encode 共用[媒体处理方案与工具选型](../development/media-pipeline-and-tool-selection.zh-Hans.md)所述的音频准备和编码流程。自动清理会：

1. 移除解码最大音量低于 `-60 dB` 的音轨；
2. 只在源编码系列和声道数相同的音轨之间比较连续区间的精确解码指纹及时间线位置；
3. 已知语言不同时绝不去重；
4. 重复时保留源顺序最早的音轨；
5. 报告每次移除。

独立的单轨音频输出保留唯一的已选轨道，不执行静音／重复音轨移除。

Remux 的无损转 FLAC 由可见复选框控制，启动时默认启用。DTS:X 和 TrueHD Atmos 需要单独启用默认关闭的高级选项，因为 FLAC 不能保留对象元数据。转换失败时保留源音轨。

共用的 FLAC／AAC／Opus 路径把一条逻辑轨道表示为“按顺序排列的连续 PCM 区间及其播放列表位置”。提取、清理、有效位深选择、编码和验证都复用这些区间，不用静音填充开头或中间空档。稀疏输出会重建为一条 Matroska 轨道；如果裸独立音频必须丢失空档，任务会直接失败。任一区间失败都会回退整条转换。

Remux 完成音轨间隙检测后会生成 `<输出>.audio-gaps.json`。伴随文件记录空档区间；音轨连续时轨道列表为空，并把检测结果与成品大小及相关轨道 UID 绑定。Remux 来源 Encode 会直接使用有效文件；文件缺失或过期时，FFmpeg 在同一次 Wave64 解码中采集数据包时间戳并推导区间，不会再次完整读取来源。

时长验证不计算编排空档，而是分别计算每个区间的正向缩短量，并用其中最大值执行提示或回退，绝不累加各区间损失，使阈值对应可能出现的最大听感延迟。重复检测同样包含区间顺序、位置和长度，因此 PCM 相同但所在时间不同的逻辑轨道不会被判为重复。

Encode 的蓝光暂存 Remux 必须保留源音频。只有视频压制成功后，才在最终混流中执行每轨 Encode 音频转换。

## 自动裁剪黑边

`src/runtime/video_crop.py` 负责按时长确定采样数、校验 FFmpeg 裁剪结果、保守合并矩形以及管理 VPy 裁剪块。它使用输入端时间定位而不是精确帧选择，并且不写出截图。采样数按每 150 秒一个计算并限制在 4～24 个，全部样本有效画面的并集会转换为一组偶数对齐的固定裁剪值。已有受管理裁剪块会被替换或移除，连续任务行不会叠加过期操作；脚本不存在已知安全的 `src8`／`res` 边界时，当前行会失败，不会在含义不明的位置插入裁剪。自动结果非零时也会拒绝 VPy 中非受管理的手工 `Crop`／`CropAbs` 调用，避免意外重复裁剪。

## Dolby Vision 处理

`src/runtime/dolby_vision.py` 拥有 `dovi_tool` 边界。

代码会：

- 解析并验证配置的可执行文件；
- 为 Encode 准备过程提取 MKV HEVC 轨；
- 分离／提取基础层和 RPU 中间文件；
- 存在物理裁剪时导出并调整全部 L5 有效画面 preset；
- 检查每个请求的中间文件均已创建；
- 向受支持的编码 HEVC 注入 RPU；
- 通过改写 RPU 并丢弃增强层视频，把双层 Remux 输入转换为单层 profile 8.1；
- 使用当前任务拥有的临时路径；
- 清理时只删除这些任务拥有的临时文件。

需要保留 Dolby Vision 时，不能静默回退到 SDR 或普通 HDR10。不支持的 x264/x265 位深组合必须在预检查失败。SVT-AV1 是已记录例外：允许编码，但省略 Dolby Vision 元数据并报告该决定。

## 字幕处理

字幕会同时影响内容和剧集映射：

- 字幕最大结束时间可用于估算剧集时长；
- 所选 SRT/ASS/SSA/SUP 必须按可见顺序映射到主输出行；
- 一个合并字幕输出中不能混用格式；
- PGS 追加／裁切使用 90 kHz 时间偏移；
- 软字幕保留可选择轨道；
- 硬字幕成为编码画面的一部分；
- 外挂字幕复制到对应输出旁，并使用相应名称。

字幕时长异常属于应修复的源数据问题，不能作为静默重排或截断行的理由。

## 错误与验证规则

项目优先执行确定性预检查：

- 源是否存在；
- 所选主 MPLS 与命令数量是否一一对应；
- 播放列表与任务行映射；
- 必需外部工具；
- 无效章节范围；
- 轨道／PID 可用性；
- 准确的计划输出路径；
- 重复路径；
- 已存在输出冲突。

执行后验证：

- 命令返回状态；
- 准确的计划输出是否存在；
- 预期轨道布局；
- 受支持输出中的语言和章节是否已应用；
- 必需 Dolby Vision 中间文件／最终流；
- 每个已选择且未有意跳过的行是否完成。

外部工具返回成功并不能证明所选流及其完整时长都被保留。[媒体管线设计与工具选择](../development/media-pipeline-and-tool-selection.zh-Hans.md)中记录的 TrueHD 限制就是具体例子。

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

修改解析器或工作流行为时，应在拥有该行为的边界补充可确定的针对性测试，并按代码规范运行集中测试。
