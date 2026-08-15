# 媒体处理流程设计与工具选型

[English](media-pipeline-and-tool-selection.md) | 简体中文

本文说明 BluraySubtitle 当前的蓝光媒体处理方案，以及选择、限制或不使用特定外部工具的依据。文中记录的是项目有意依赖的行为，并非对所有工具和版本进行通用性能比较。

## 设计目标

媒体处理流程需要满足以下要求：

- 原生支持 Windows、Linux 和 Docker，不要求安装 Windows 兼容层；
- 将 MPLS PlayItem 的顺序、`in_time` 和 `out_time` 视为权威播放时间线；
- 保留 GUI 中选择的轨道、顺序、语言、章节范围和输出名称；
- 能从真实原盘的制作异常和流检测问题中恢复，同时不能静默改变用户要求的输出；
- 尽量减少外部进程启动次数和对大量媒体文件的重复扫描；
- 无法恢复已选择的非音频轨道时必须明确失败。

没有一种工具能够同时满足所有要求，因此项目使用一个主流程，并仅在必要位置使用范围明确、结果可验证的回退流程。

## 源码验证基线

本文中的实现细节于 2026-07-26 根据以下本地源码版本和命令行程序进行了检查：

- MKVToolNix 源码 `release-100.0-15-gbfc791cca` （`bfc791cca9763b494f66379953b9509b5187bc9a`）及 `mkvmerge` 100.0；
- tsMuxer 源码 `nightly-2024-06-06-02-00-53-1-gc6b1186` （`c6b1186209e42c877052e762c9185f3226ef8ea2`）及 tsMuxeR 2.7.0；
- 当前 BluraySubtitle 源码。

文中列出函数名，方便上游版本更新后重新核对。没有写死行号，因为行号比相关控制流程更容易变化。

## 当前处理流程

### 1. 程序内解析媒体信息

BluraySubtitle 自行解析 MPLS，并维护每个 PlayItem 的片段名称、`in_time` 和 `out_time`。[M2TS 解析器](../../src/bdmv/m2ts.py)直接读取传输流布局、PAT/PMT 流信息、PTS/PCR 时间以及需要的视频时间信息，并缓存未发生变化的文件的解析结果。

这与为每个 M2TS 分别启动一次 `ffprobe` 或 tsMuxer 不同。大型原盘可能包含数百个流文件，外部进程启动和重复探测会明显拖慢读取速度。外部探测仍用于特定操作和回退，但不作为批量发现 M2TS 信息的主要方式。

读取 MKV 时长采用相同原则。[Matroska 时长读取器](../../src/domain/media/mkv_container.py)直接读取 EBML Segment Info 中的 TimecodeScale 和 Duration，而不是等待 `mkvinfo` 遍历大型文件。这个实现显著加快了章节匹配流程中的时长收集。

### 2. 使用 MKVToolNix 作为主要 Remux 实现

`mkvmerge` 是主要 Remux 工具，因为它跨平台、直接生成目标 Matroska 容器、能够较好地保留轨道元数据，并且在 eac3to 和 tsMuxer 会错误包含完整 M2TS 的场景中，能够正确应用 MPLS PlayItem 的范围。

正常流程将 MPLS 直接交给 `mkvmerge`。混流后，BluraySubtitle 会应用并验证配置的语言和章节，而不是假定外部命令完整保留了所有指定元数据。

#### 为什么 MKVToolNix 会漏掉 tsMuxer 能识别的 M2TS 轨道

这并不是 MKVToolNix 简单读错了 PMT。在 `src/input/r_mpeg_ts.cpp` 中，`track_c::determine_codec_from_stream_type()` 确实会把 PMT 流类型 `0x24` 映射为 HEVC，但音视频轨道不能只根据这项声明就视为识别成功：

1. `reader_c::determine_track_parameters()` 调用对应编码的基本流解析器。
2. 对 HEVC，`track_c::new_stream_v_hevc()` 将 PES 负载交给 `mtx::hevc::es_parser_c`，在 `headers_parsed()` 成功前持续返回 `FILE_STATUS_MOREDATA`。
3. 只有编码专用探测成功后，`reader_c::probe_packet_complete()` 才会设置 `probed_ok`。
4. 最后的轨道创建循环会跳过 `probed_ok` 为 false 或未能确定编码的轨道。

这种设计可以避免仅凭 PMT 声明就创建一个无法验证基本流参数的输出轨道，因此比单纯信任传输流元数据更严格。

tsMuxer 使用另一套两阶段流程。`tsMuxer/tsDemuxer.cpp` 中的 `TSDemuxer::getTrackList()` 会把 PMT 中的每个 PID 放入候选集合；`METADemuxer::DetectStreamReader()` 随后为这些 PID 解复用一段有限长度的样本，并尝试对应的编码读取器。`HEVCStreamReader::checkStream()` 使用 tsMuxer 自己的 VPS/SPS/PPS 和 NAL 解析器验证 HEVC。因此，tsMuxer 并非完全不检查负载，只是它的解析器和接受边界与 MKVToolNix 不同。

对 Avatar UHD 中触发回退的两个 PlayItem 文件进行只读比较，结果如下：

| M2TS | PMT 视频 PID | mkvmerge | tsMuxeR 2.7.0 |
| --- | ---: |----------------| --- |
| `00073.m2ts` | 4113（`0x1011`） | 未列出视频轨道 | 识别为 HEVC Main10、3840x2160p、23.976 |
| `00096.m2ts` | 4113（`0x1011`） | 未列出视频轨道 | 识别为 HEVC Main10、3840x2160p、23.976 |

这验证了引入回退的实际原因，也确定了 MKVToolNix 拒绝轨道的处理阶段。但目前还没有定位这两个文件中具体异常的 NAL 单元或解析规则，因此本文不把原因武断归结为某个 VPS、SPS 或 Dolby Vision 缺陷。

#### MKVToolNix 如何对多个 M2TS 应用 MPLS 范围

MKVToolNix 不会把多片段 MPLS 当作一组不加限制的完整文件：

1. `src/common/mm_mpls_multi_file_io.cpp` 中的 `mm_mpls_multi_file_io_c::open_multi()` 按顺序遍历 MPLS PlayItem，并为每一项解析一个 M2TS 路径。同一片段被重复引用时仍保留为独立的有序项。
2. `src/merge/mkvmerge.cpp` 中的 `add_filelists_for_playlists()` 断言 M2TS 数量与 PlayItem 数量相同。它把第一个 PlayItem 的 `in_time` 和 `out_time` 分配给原始输入，并为后续每一项创建附加文件列表，分别保存该项自己的时间限制。
3. `create_append_mappings_for_playlists()` 把每个后续输入的轨道映射到前一 PlayItem 的对应轨道，以播放列表顺序连接分别裁切后的片段。
4. `read_file_headers()` 通过 `generic_reader_c::set_timestamp_restrictions()` 将每项时间限制传给基本流读取器。
5. 对 MPEG-TS，`src/input/r_mpeg_ts.cpp` 中的 `reader_c::determine_start_source_packet_number()` 使用对应 CLPI 的 Entry Point Map，定位到 PTS 不晚于 `in_time` 的最后一个源包附近。
6. CLPI 定位只是优化。真正的下限由 `track_c::send_to_packetizer()` 执行，它拒绝 `in_time` 之前的 PES 负载；上限由 `reader_c::parse_pes()` 执行，PES PTS 达到或超过 `out_time` 时将当前 M2TS 标记为读取结束。

因此，MKVToolNix 是在传输流/PES 时间戳边界执行裁切，而不是盲目拼接完整 M2TS。它并非任意采样级音频编辑，但交给 Matroska packetizer 的数据确实遵守原盘制作的 PlayItem 时间窗口。

### 3. 轨道对齐的 Remux 回退

MKVToolNix 对 M2TS 结构的验证通常比 tsMuxer 严格。这有利于发现异常输入，但部分原盘会出现 tsMuxer 能识别某条轨道而 `mkvmerge --identify` 不列出的情况。当不同 PlayItem 暴露不同轨道布局时，直接 Remux MPLS 也可能失败。

[轨道对齐回退](../../src/runtime/services_split/media_info_and_track_mapping.py)按以下方式处理：

1. “编辑轨道”中选择的轨道确定必需 PID 布局和输出顺序。
2. 分别处理 MPLS 中的每个 PlayItem。
3. 片段在对应 M2TS 中的相对范围按以下公式计算：

   ```text
   start = (in_time * 2 - first_m2ts_pts) / 90000
   end   = start + (out_time - in_time) / 45000
   ```

4. 非完整 PlayItem 使用 `mkvmerge --split parts:start-end` 裁切，明确保留非零的 MPLS 起止范围，而不是附加整个 M2TS。
5. `mkvmerge` 提供它能够识别的所有轨道。
6. 仅对仍然缺少的已选择 PID 调用 tsMuxer。需要恢复 Dolby Vision 增强层时也使用这一路径，随后由项目调用 `dovi_tool` 与基础层合并。
7. tsMuxer 无法恢复任何缺失的已选 PID（包括音频）时明确失败，不合成替代轨道。
8. 检查最终 PID 集合是否与要求的布局完全一致。
9. 多个修复片段使用 `--append-mode file` 拼接，使所有轨道采用同一个前序文件时间戳边界。使用 track append 时，较短或损坏的音轨可能早于视频开始下一片段。

当一个 MPLS 被拆分成多个分集 MKV 时，独立的多输出回退会把每集范围投影到相同的 PlayItem 窗口，并使用同样的恢复规则。

## 为什么不使用 eac3to 作为主要 demux 工具

### 平台支持

eac3to 是 Windows 程序。依赖它会破坏项目对 Linux 和 Docker 的原生支持。通过 Wine 运行会增加大型平台专用依赖，也无法提供相同的受支持执行契约。

### Avatar UHD 播放列表上的实测时间错误

2026-07-26 使用 eac3to 3.63 进行了只读本地检查，本次检查没有 demux 任何流。列出 `00800.mpls` 的标题 3 时报告：

```text
M2TS, 1 video track, 8 audio tracks, 8 subtitle tracks, 2:42:03
TrueHD/AC3 (Atmos), [eng], 7.1 channels, 48kHz, ... -1001ms
DTS-HD Master Audio, [eng], ... -1000ms
...
TrueHD/AC3 (Atmos), [zho], 7.1 channels, 48kHz, ... -1000ms
```

所有音轨都被赋予约一秒的负延迟，而播放列表实际约为 `2:42:02`。此前对同一来源进行完整 demux 时，提取的视频恰好少了 24 帧。以 24000/1001 fps 计算，24 帧约为 1.001 秒，与分析中多出的延迟一致。编写本文时没有再次执行这次大型 demux。

这是该来源与 eac3to 版本中已经确认的兼容性问题，并不表示所有 eac3to 操作都会产生一秒误差。

### MPLS 局部 PlayItem 的处理行为

实测发现，当 PlayItem 只使用某个 M2TS 内部的一段范围时，eac3to 和 tsMuxer 都可能错误处理。一个具有代表性的播放列表先长时间引用某个 M2TS，随后又引用同一 M2TS 中的两个短区间：

- eac3to 会把重复的完整 M2TS 加入一次；
- tsMuxer 会为每次 PlayItem 引用各加入一次完整 M2TS；
- 两者结果都不符合制作时指定的 `in_time`/`out_time` 窗口。

tsMuxer 源码解释了这个限制：它为每个 MPLS PlayItem 创建一个完整文件路径，并把 MPLS 时间信息交给读取器做时间线修正，但输入文件列表本身不会按照每项的 `IN_time` 和 `OUT_time` 裁切。

具体来说：

- `tsMuxer/metaDemuxer.cpp` 中的 `METADemuxer::addStream()` 为每个 MPLS PlayItem 向 `fileList` 添加一个完整 M2TS 路径。因为播放列表索引属于已处理轨道键的一部分，所以重复片段引用仍然保留为重复条目。
- `tsMuxer/bufferedFileReader.h` 中的 `FileListIterator` 只保存文件名。`BufferedReader::thread_main()` 在前一个文件到达 EOF 后打开下一个文件，没有接收 PlayItem 字节偏移或时间终点。
- `TSDemuxer::setMPLSInfo()` 只保存 PlayItem 向量。在文件边界，`TSDemuxer::simpleDemuxBlock()` 使用 `OUT_time - IN_time` 更新前一文件的预期时长并重置时间戳状态。
- `SimplePacketizerReader::setMPLSInfo()` 和 `doMplsCorrection()` 同样使用 `OUT_time - IN_time` 修正时间线，不会 seek 到 `IN_time`，也不会在 `OUT_time` 停止读取。

也就是说，MPLS 时间会影响重建的时间线，但不会决定实际读取哪些源包。同一 M2TS 出现在两个 PlayItem 中时，tsMuxer 会打开并完整读取它两次。这个控制流程与实测的“完整文件重复”结果相符，因此不是只根据输出时长作出的推测。

两种实现的差异可以概括为：

| 阶段 | MKVToolNix | tsMuxer |
| --- | --- | --- |
| 展开播放列表 | 每个 PlayItem 建立一个附加输入 | 每个 PlayItem 加入一个完整文件名 |
| 应用 `in_time` | CLPI 辅助定位，并按 PTS 拒绝过早的 PES | 不 seek 源文件，也不拒绝对应源包 |
| 应用 `out_time` | PES PTS 达到上限时停止当前 M2TS | 只用 `OUT_time - IN_time` 计算预期时间线长度 |
| 重复引用 M2TS | 重新打开，但只输出该项受限的 PTS 窗口 | 重新打开并再次读取完整文件 |

`mkvmerge` 直接处理 MPLS 时没有这个问题。BluraySubtitle 回退也不会触发它，因为每个 PlayItem 在拼接前都会显式转换为 M2TS 相对的 `--split parts:start-end` 范围。

### BluraySubtitle 已覆盖的相关功能

eac3to 提供了一些有价值的音频功能，包括检测有效位深和消除音频延迟，但这些功能不足以抵消它的平台和播放列表限制：

- 可以检查解码后的 PCM 有效位深是 16 位还是 24 位，而不是只相信容器声明；
- 替换音频使用从源轨道最小时间戳计算出的明确同步值重新混流；
- 已选择轨道会检查解码后的最大音量是否低于 `-60 dB`，以识别静音；
- 解码指纹用于检测源编码家族及声道数相同的完全重复轨道；已知语言不同的轨道仍然保留。

这些检查属于当前音频流程，而不是可选的 eac3to 预处理。

## 为什么 tsMuxer 只作为回退而不是主要 demux 工具

tsMuxer 的流检测在部分异常 M2TS 上比 MKVToolNix 更宽松，因此适合根据明确的缺失 PID 列表执行恢复。

它不适合作为主要 MPLS demux 工具有两个原因：

1. 前述局部 PlayItem 问题会包含完整 M2TS，而不是制作时指定的范围；
2. 损坏的 TrueHD 可能导致报错、严重丢帧，或者命令报告完成但提取流实际不可用。

### 为什么提取损坏的 TrueHD 不可靠

tsMuxer 对相关蓝光 TrueHD 布局使用两种不同的读取器。两条路径都没有损坏帧修复，并且失败处理方式值得注意：

- TrueHD-only PID 由 `MLPStreamReader` 处理。`MLPCodec::decodeFrame()` 将帧头或 major/minor-sync 验证失败报告为 Boolean `false`，`MLPStreamReader::decodeFrame()` 再把它转换为零，而不是独立的错误类型。`SimplePacketizerReader::readPacket()` 因此将其当作坏帧并进入重新同步；`MLPCodec::findFrame()` 只寻找下一个 TrueHD/MLP major sync。中间所有字节，包括原本可能可用的 minor-sync 帧，都会被跳过。普通输入块边界短于 `getHeaderLen()` 时，`SimplePacketizerReader` 会先缓存数据再调用解码，所以源码并不支持把问题简单归因于普通分块边界。
- 包含交错 AC-3 core 和 TrueHD 扩展数据的蓝光 PID 由 `AC3StreamReader` 处理。`AC3Codec::decodeFrame()` 在检测模式时验证首个 TrueHD major-sync 帧。`m_true_hd_mode` 变为 true 后，后续扩展帧主要按照声明长度前进；该状态下，嵌套的 `if (!m_true_hd_mode)` 验证分支不可能执行。失去帧边界后，`AC3Codec::findFrame()` 只搜索下一个 AC-3 `0x0b77` 同步字，因此该 core 帧之前的 TrueHD 字节可能被丢弃。
- 如果 `NOT_ENOUGH_BUFFER` 状态持续超过一个完整输入块，`SimplePacketizerReader` 可以抛出 `invalid stream`。其他异常帧会输出 `bad frame detected ... Resync stream` 后继续处理，因此返回码为零并不能证明提取出的基本流完整。
- 两条 TrueHD 路径都根据成功接受的帧样本数生成输出时间戳。`AC3StreamReader::readPacketTHD()` 使用 `m_totalTHDSamples` 重写 PTS，`AC3StreamReader::needMPLSCorrection()` 在 TrueHD 模式中明确返回 false。缺帧会缩短生成的时间线，原始 PTS 间隙或 MPLS 区间不会保留在裸流输出中。

两条路径都没有合成替换 access unit、把损坏区间保留为空隙或填充静音。因此，tsMuxer 适合恢复 MKVToolNix 未暴露的已选 PID，但不能代替专门修复损坏 TrueHD 的 demux 工具。

一次短素材测试可以说明实际影响。tsMuxeR 2.7.0 从时长 50.053 秒的 Avatar `00096.m2ts` 中 demux 两个 TrueHD PID，并返回 `Demux complete`。PID 4352 被识别为交错的 `A_AC3`，PID 4356 被识别为 TrueHD-only `A_MLP`。提取第二条轨道时反复出现 `bad frame detected ... Resync stream`。随后使用 `truehdd` 0.4.0 `info` 检查：

| PID | tsMuxer 输出 | 输出大小 | `truehdd` 时长 |
| ---: | --- | ---: | ---: |
| 4352 | AC-3 core + TrueHD | 34.27 MB | 00:00:06.587 |
| 4356 | TrueHD | 7.33 MB | 00:00:10.047 |

两个输出都明显短于 50.053 秒的 M2TS 区间，并且启用警告后，`truehdd` 报告了大量 parity 和 restart/seamless-branch 错误。单凭时长不能证明每个 PID 在制作时都应覆盖整个片段，但错误日志可以确认提取出的基本流并不干净。本次检查只使用了这个短 M2TS，没有 demux 完整播放列表。源码可以解释重新同步和丢帧行为，但无法仅凭这些结果确定每条坏帧报告分别来自原始负载损坏、不受支持的帧结构还是之前已经丢失同步。

把 tsMuxer 限制为按文件、按 PID 恢复，也使输出能够验证：BluraySubtitle 明确知道缺少哪些轨道，并会拒绝未能恢复要求布局的结果。

## TrueHD 与 Atmos 处理

### 当前限制：不修复损坏的 TrueHD

MKVToolNix 会解析并混流 TrueHD 帧，但不会执行解码器式错误隐藏，也不会合成替换 TrueHD 帧。传输流连续计数错误可能导致一个 PES 包被丢弃，而帧头仍然合理的帧也可能包含只有在解码时才会报告的负载损坏。

相关 MKVToolNix 代码明确体现了这一限制：

- `src/input/r_mpeg_ts.cpp` 中的 `reader_c::handle_transport_errors()` 把 TS transport-error 标志或意外的 continuity counter 都视为错误，清除已累计负载并记录丢弃当前 PES 包；它不会为丢弃区间生成替换音频。
- `src/common/truehd.cpp` 中的 `frame_t::parse_header()` 从首个 word 取得普通 TrueHD access unit 长度，并且普通 TrueHD 帧通过时不会检查负载校验和。相比之下，AC-3 分支会显式调用 `mtx::ac3::verify_checksums()`。因此，某个 TrueHD 帧可能在结构上能够分离，但仍包含随后被解码器报告的损坏。
- `parser_c::parse()` 复制每个接受帧的原始字节。失去帧边界后，`resync()` 向前搜索下一个 TrueHD/MLP major sync 或 AC-3 帧；跳过的字节不会转换成静音或替换 TrueHD 帧。
- `truehd_ac3_splitting_packet_converter_c::process_frames()` 把 PES 时间戳交给其中第一帧 TrueHD。后续帧由 `truehd_packetizer_c::process_framed()` 根据样本数确定时间。该 packetizer 把原始 `frame->m_data` 放入 Matroska 包；除可选的 dialog normalization 帧头修改外，不会重写或解码负载。
- `xtr_base_c::create_extractor()` 将 `MKV_A_TRUEHD` 映射到通用 `xtr_base_c` 提取器，后者的 `handle_frame()` 直接把每个 Matroska 帧写入输出文件。Matroska 时间戳及其中的间隙不会序列化到裸 `.thd` 基本流。

Matroska 时间戳能够表示丢帧后留下的时间间隙，但随后提取出的裸 `.thd` 无法表示：`mkvextract` 会连续写入基本流帧字节，裸 TrueHD 中没有 Matroska 时间戳间隙。因此，损坏来源可能具有看似合理的 MKV 时长，却在 `truehdd` 中产生大量错误，最终解码出的 PCM/FLAC 比视频短一到两秒。改变 MKV append mode 只能对齐文件边界，不会修复 TrueHD 负载，也不会增加裸流中的有效帧数。

因此，实测中的 `truehdd` 错误和解码时长不足，与两种有源码依据的机制相符：结构仍可接受但已经损坏的 TrueHD 帧会原样到达解码器；传输流或帧边界丢失也会在没有替换的情况下删除帧字节。在没有对受影响 PID 进行逐字节跟踪前，不能断言所有错误或完整的一到两秒差值只来自其中一种机制。

本地测试表明，eac3to 对这类损坏 TrueHD 的结果大体相似。

### 为什么暂不集成 DGDemux

对测试过的损坏 TrueHD 轨道，DGDemux 的结果明显更好。它的 file-gap 处理能够填充损坏或缺失区间，使 demux 后的 TrueHD 时长接近视频。

但是，DGDemux 附带许可证说明最终用户可以直接运行其可执行文件，而第三方软件使用或集成必须得到 Donald A. Graft 的明确书面许可，并且禁止重新分发。因此，BluraySubtitle 在未获得许可时不能调用、捆绑或集成 DGDemux。

即使取得许可，引入 DGDemux 也会增加一次完整原盘 demux 阶段、延长 Remux 时间、增加平台专用打包和命令处理，还需要维护第二套轨道顺序映射流程。目前这些维护成本并不合理。

### 为什么 Atmos 转换使用 `truehdd` 而不是 FFmpeg

在项目支持的解码器中，使用 `truehdd` 是因为它能完整解释当前流程所需的 TrueHD Atmos presentation。BluraySubtitle 在编码 FLAC 前解码 presentation 2，不把 FFmpeg 的 TrueHD 解码视为等价的 Atmos 转换路径。`truehdd` 不可用或失败时保留源 TrueHD Atmos 音轨。

使用 FLAC 是为了改善不同设备的播放兼容性。因此，对 TrueHD/MLP，只要成功解码，生成的 FLAC 即使大于原始 TrueHD 也会保留：转换目标是兼容性，而不是减小体积。DTS 的处理不同；DTS 系列来源在替换 FLAC 更大时保留原始 DTS。

处理已知 TrueHD 损坏的 DIY 原盘时，在丢弃源流前应比较解码音频和视频时长，并检查 `truehdd` 错误。

## 音频编码器选择

### 使用 FDK-AAC 而不是 qaac

qaac 不是原生跨平台方案，通常依赖 Apple 的 Windows 编码组件。FDK-AAC 可以在两个受支持的桌面平台使用，也能由项目 setup 脚本构建；在本程序使用的码率下，实际质量差距很小，不足以证明维护 Windows 专用 AAC 路径和第二套平台配置是合理的。

因此，BluraySubtitle 使用 `fdkaac` 命令行前端进行 AAC 编码。配置正数时表示明确码率；自动模式使用 FDK-AAC VBR 5。

### 优先独立 FLAC，失败时回退 FFmpeg

FLAC 是首选无损输出。首先尝试独立编码器，因为 FLAC 1.5.0 支持多线程编码；BluraySubtitle 使用 `-j` 传入检测到的逻辑 CPU 数量。

独立编码器对部分生成输入和运行环境的容错较低，可能执行失败。压缩来源也必须先解码为 PCM，独立编码器才能读取。因此，流程按以下顺序执行：

1. 已有解码后的 WAV/W64 时直接复用；
2. 否则先把压缩输入解码为 PCM；
3. 使用多线程运行独立 `flac` 编码器；
4. 删除失败产生的不完整输出，并回退到 FFmpeg FLAC 编码器。

这样既保留 FLAC 1.5.0 的性能优势，也不会让独立编码器成为单一失败点。

## 工具职责汇总

| 工具或组件 | 当前职责 | 限定在此范围的原因 |
| --- | --- | --- |
| 内部 MPLS/M2TS 解析器 | 播放列表窗口、PAT/PMT 轨道、PTS/PCR 时间、带缓存的批量发现 | 速度快，并遵守项目的 MPLS 规则 |
| 内部 Matroska 读取器 | 从 EBML Segment Info 读取时长 | 避免只查询时长时使用缓慢的 `mkvinfo` 扫描 |
| MKVToolNix | 主要 Remux、Matroska 提取、元数据编辑、逐片段裁切和拼接 | 跨平台，可靠处理 MPLS 范围和 Matroska |
| tsMuxer | 从单个 M2TS 恢复明确缺少的 PID | 检测较宽松，但不适合作为主要 MPLS demux 工具 |
| FFmpeg/ffprobe | 定向解码、分析、回退探测和编码 | 编码支持广泛；在批量发现之外可以接受进程开销 |
| truehdd | 解码 TrueHD Atmos presentation 2 | 当前 Atmos presentation 处理所需 |
| FLAC 1.5.0+ | 使用全部逻辑 CPU 线程进行首选 FLAC 编码 | 快速的多线程无损编码 |
| FFmpeg FLAC 编码器 | 独立 FLAC 不可用或失败时回退 | 容错更高的恢复路径 |
| fdkaac | AAC 编码 | qaac 的跨平台替代方案 |
| eac3to | 不使用 | 仅 Windows，并存在已确认的播放列表/时间兼容性问题 |
| DGDemux | 暂不集成 | 修复损坏 TrueHD 效果好，但第三方使用需要书面许可，并会增加流程复杂度 |
