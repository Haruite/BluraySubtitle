# BluraySubtitle

[English](./README.md) | [简体中文](./README_zh.md)

BluraySubtitle 是一个面向 Windows/Linux（含 Docker）的蓝光流程 GUI 工具。  
它将以下四类功能整合在一个应用中：

1. **生成合并字幕**
2. **给 MKV 添加章节**
3. **原盘 Remux**
4. **原盘压制**

---

## 亮点

- 一个应用覆盖蓝光常见全流程（合并字幕、章节、Remux、压制）。
- 剧集/电影双模式，配合主播放列表与章节映射。
- Remux 具备失败自动修复能力，稳定性更高。
- 压制流程支持逐行 vpy 编辑与预览。
- 跨平台：Windows / Linux / Docker。

---

## 更多细节

### 界面与交互

- **中英文切换**（English / 简体中文）。
- **主题切换**：浅色 / 深色 / 彩色（支持透明度调节）。
- 每个盘可选择主播放列表（`main MPLS`）。
- 表格支持播放预览（`play`）。
- 以表格为核心的紧凑工作流，支持拖拽排序（相关模式中）。

### 轨道管理

- 支持按来源编辑轨道（音频/字幕）。
- 支持**一键选择所有轨道**（含 Remux 来源工作流）。
- 轨道选择会参与 Remux/压制命令生成。
- 主正片、SP、Remux 来源使用独立配置键，减少串配。

### Remux / 压制控制

- 压制模式支持两类输入源：
  - 原盘
  - Remux
- 主播放列表支持编辑混流命令（`remux_cmd`）。
- 压制参数支持：
  - `vspipe` 来源（程序自带 / 系统）
  - `x265` 来源（程序自带 / 系统）
  - x265 参数预设与自定义
  - 字幕封装：外挂 / 内挂 / 内嵌
- 每一行支持独立 VPy 路径（正片与 SP）。

### 剧集 / 电影模式

- 支持 **剧集模式** 与 **电影模式**。
- 支持按章节时间线拆分剧集。
- 支持每行设置**起始章节 / 结束章节**（适用于 remux/压制流程中的章节区间控制）。
- 剧集流程支持章节分段与 SP 处理。

### mkvtoolnix 兼容修复

针对常见 mkvtoolnix 边缘问题，内置了修复逻辑：

- 需要时重写章节（分段/切割场景）。
- 使用 `mkvpropedit` 修正输出轨道语言。
- 当 `mpls` 直接混流失败时自动走修复路径：
  - 多片段轨道对齐拼接回退，
  - 多集分片输出回退，
  - 提升复杂片单混流成功率。

### 实现细节（通俗版）

这部分用更好懂的方式说明程序内部怎么做。

#### A）SP 处理规则

1. 新增 `select/选择` 列，用来控制这一行 SP 是否参与混流。  
2. 不再按 MPLS 章节数分流逻辑；MPLS 行统一走 MPLS 处理，没有 MPLS 再按 M2TS 处理。  
3. `table3` 行顺序排列，先按 BDMV 分卷顺序，再按 MPLS 名，最后无 MPLS 的列按照 M2TS 名排序
4. 默认输出名统一为 `BD_Vol_{bdmv_vol}_SP{n}.mkv`；`n` 是同一卷内“已选择”MPLS 的序号，从 1 开始，位数统一，不足补 0。  
5. 如果某个 MPLS 包含的所有文件都在主 MPLS 内，该行默认不勾选。  
6. 时长小于 30 秒（注意，获取时长使用的是 `get_duration_no_repeat`，重复文件只计算一次时长）的 MPLS 和 M2TS 也会加入 `table3`，但默认不勾选。  
7. 特例 1：如果 MPLS 包括三个及以上不同文件，默认勾选。
8. 特例 1：如果 MPLS 只有一个 m2ts 且该 m2ts 只有 1 帧，默认勾选，输出为 `BD_Vol_{bdmv_vol}_SP{n}.png`。  
9. 特例 2：如果 MPLS 有多个 m2ts 且每个都只有 1 帧，默认勾选，输出为文件夹 `BD_Vol_{bdmv_vol}_SP{n}`，文件名格式 `{m}-{m2ts_name}.png`（`m` 从 1 开始补 0，`m2ts_name` 不带 `.m2ts`）。  
10. 如果该 MPLS 没有选中任何轨道，输出文件名置空，混流时直接跳过。  
11. 如果只选中 1 条音轨，输出名改为对应原始音频后缀，混流时直接提取。  
12. 如果选中多条音轨（且不走视频封装），输出为 `BD_Vol_{bdmv_vol}_SP{n}.mka`。  
13. 修改轨道后，立即触发输出文件名重算。  
14. MPLS 混流后先清章节：`mkvpropedit output.mkv --chapters ""`；再从 MPLS 生成 `chapter.txt`，去掉末尾章节点，且只有在内容不等于“仅一个 00:00:00 章节”时才写回。  
15. 若无法读取该 MPLS 的第一个 m2ts，该行置灰不可编辑，混流时跳过。  
16. 混流完成后，按主 MPLS 同样规则检查轨道语言，不一致时用 `mkvpropedit` 修正。  
17. 最后再扫描一遍“未被任何 MPLS 覆盖”的 m2ts 并追加到 `table3`：  
    - 用 `M2TS.get_duration` 取时长；  
    - 时长 `< 30s` 默认不勾选；  
    - 时长 `= 0` 的行置灰不可编辑并跳过；  
    - 选中后的基础输出名是 `BD_Vol_{bdmv_vol}_{m2ts_name}`；  
    - 后缀规则：一帧 -> png、单音轨 -> 直接提取原始后缀、多音轨 -> mka、其他 -> mkv。  

SP 混流失败时怎么处理：

- 如果该行源不可读（例如第一个 m2ts 读不到），界面会置灰并在执行时直接跳过。  
- 如果输出名为空或未选任何轨道，视为“主动跳过”，不计为错误。  
- MPLS 行先走主混流；若在多 clip 场景失败，再走轨道对齐拼接回退。  
- 回退后按“输出文件是否真实存在”做最终判定（包含 split 风格后缀兼容检查）。  
- 只有成功输出才会继续执行章节重写和语言修正；失败行保留失败状态，但不阻塞其他行继续。  

#### B）MPLS 混流失败时怎么修
`mkvmerge` 在 MPLS 混流（尤其多文件）时，可能因为不同 m2ts 的轨道布局不一致而失败。  
程序会先检查命令返回和输出文件是否有效；失败后进入回退修复。

单文件输出回退（常见于 SP、电影模式）：

1. 先分析第一个 m2ts 的轨道，作为“参考轨道布局”。  
2. 遍历 `Chapter(mpls_path).in_out_time`，对每个片段计算：  
   - `start_time = (in_time * 2 - first_pts) / 90000`  
   - `end_time = start_time + (out_time - in_time) / 45000`   
注意不是取文件开头时间作为 start_time，有些片段不是从文件开头开始播放，比如 a 文件播放中间穿插了一段 b 文件，那么 b 文件播放结束回到 a 文件那段就不是从 a 文件起始开始播放的。
3. 若 `start_time == 0` 且 `abs(end_time - 文件总时长秒) < 0.001`，则直接整段混流；否则使用 `--split parts:start-end`。  
4. 每个片段按参考轨道做对齐：  
   - 参考里没有的轨道（PID 不在首片段）丢弃；  
   - 参考里有的轨道保留；  
   - 缺失的参考音轨补静音轨。  
5. 生成每段命令时带 `--track-order FID:TID,...`，保证最终轨道顺序和第一个 m2ts 一致。  
6. 各段产物按顺序用 `+` 拼接，并加 `--append-mode track`。  
7. 混流后用 `mkvpropedit` 修正轨道语言。  
8. 写入章节（章节提取/重写走现有函数）；音频压缩等后续步骤在别处处理，这里只负责混流与修复。  

多文件输出回退（一个 MPLS 要拆成多个输出）：

1. 先从章节配置（以及自定义 `remux_cmd` 里的 split 提示）确定每个输出文件的切割时间窗口。  
2. 遍历 `in_out_time`，累加每段 `((out_time - in_time) / 45000)`，得到每个 m2ts 在播放时间线上的起止范围。  
3. 若某个 m2ts 时间段与当前切割窗口重叠，则该 m2ts 参与该输出。  
4. 计算重叠片段的切割起止：  
   - 窗口首文件：起点 = `窗口起点 - 文件时间线起点`，终点按单文件公式；  
   - 窗口中间文件：起止按单文件公式；  
   - 窗口尾文件：起点按单文件公式，终点 = `起点 + (窗口终点 - 文件时间线起点)`。  
5. 每段都按“参考轨道 + 缺轨补静音 + 固定 `--track-order`”混流。  
6. 将同一窗口内片段拼接为该窗口输出文件。  
7. 校验所有预期输出（`-001`、`-002`...）是否都存在，不完整则判定修复失败。  
8. 对成功输出执行现有的语言修正和章节写入流程。  

#### C）`view chapters` / `start_at_chapter` / `end_at_chapter` 联动与配置重算（重构规则）

配置生成函数至少以这 3 组输入为核心参数，并且三者任意变化都要触发重算：  

1. `table1 -> view chapters` 中 MPLS 各段勾选状态  
2. `table2` 各行 `start_at_chapter`  
3. `table2` 各行 `end_at_chapter`  

处理优先级（按变化源判断）：

**第一优先：view chapters 勾选变化（全量重算）**

1. 从第一个“被勾选区间”开始作为第一集 `start_at_chapter`。  
2. 一旦遇到“未勾选区间起点”，当前集立即结束，`end_at_chapter` 设在该处；下一集从该区间末端重新开始。  
3. 每集目标时长：有字幕时取该集字幕 `max_end_time`，无字幕时取 `approx episode length`。  
4. 对每一集取两个候选终点：  
   - 候选 A：最接近目标时长的“文件结束点”（从 view chapters 中判断该节点与上一个节点 m2ts 是否变化）；  
   - 候选 B：最接近目标时长的“章节点”。  
5. 终点选择规则：  
   - 若候选 A 的偏差在 `[-1/4*目标时长, +1/2*目标时长]`，优先选候选 A；  
   - 否则将负偏差乘以 `-2` 后再比较 A/B，取偏差更小者作为 `end_at_chapter`。  

**第二优先：start_at_chapter 变化（从首个变化集向后重算）**

1. 与上一次配置比较，从“最先发生变化”的那一集开始重算后续。  
2. 该集之前的 `start_at_chapter/end_at_chapter` 保持不变。  
3. 从变化集开始，后续按上面同一套规则重算（不依赖后面旧的 start 值）。  
4. 同步取消勾选：将“上一集 end”和“当前新 start”之间的节点置为不勾选。  

**第三优先：end_at_chapter 变化（按扩大/缩小分支处理）**

1. 变化集之前保持不变。  
2. 若 `end_at_chapter` 改小：后续集不重算，只清理空白区间节点勾选。  
3. 若 `end_at_chapter` 改大：下一集从其后“第一个仍被勾选节点”开始，重算后续各集 `start/end`。  

下拉可选性约束：

- 对于 view chapters 里未勾选的节点，`start_at_chapter` 和 `end_at_chapter` 下拉中对应项必须置灰不可选。  
- 仍需满足基本约束：`end_at_chapter > start_at_chapter`。  

#### D）补充说明

- 主混流命令支持占位符：`{output_file}`、`{audio_opts}`、`{sub_opts}`、`{parts_split}`。  
- 主命令结果不符合预期时，程序会尽量用已解析参数或默认轨道继续走回退。  
- 章节重写和语言修正放在混流后执行，主要是为了规避 mkvmerge 的边缘元数据问题。  

---

## 依赖要求

### Python 依赖

- `PyQt6`
- `librosa`
- `pycountry`

示例：

```bash
pip install PyQt6 librosa pycountry
```

### 外部工具

- mkvtoolnix：`mkvmerge`、`mkvinfo`、`mkvextract`、`mkvpropedit`
- `ffmpeg`、`ffprobe`
- `flac`（>= 1.5.0）

### 压制模式额外依赖

- VapourSynth 运行时与相关插件
- `vspipe`
- `x265`
- `vsedit`

> 具体使用程序自带还是系统路径，取决于当前模式与设置项。

---

## 快速开始

```bash
python BluraySubtitle.py
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

## 2）给 MKV 添加章节

典型流程：

1. 加载蓝光章节来源（playlist/chapter 信息）；
2. 加载目标 MKV 目录；
3. 校验 main MPLS；
4. 执行章节写入。

## 3）原盘 Remux

典型流程：

1. 加载原盘目录；
2.（可选）加载字幕目录；
3. 校验主播放列表与章节区间；
4.（可选）编辑 remux 命令；
5. 选择输出目录并执行。

## 4）原盘压制

典型流程：

1. 选择输入源（原盘 / Remux）；
2. 配置 VPy、x265、字幕封装等选项；
3.（可选）编辑轨道或一键全选轨道；
4.（可选）设置起始/结束章节；
5. 执行压制。

---

## VPy 编辑与预览

- **编辑脚本（edit_vpy）**：使用系统关联编辑器打开。
- **预览脚本（preview_script）**：使用 `vsedit` 打开，并按当前行上下文准备预览参数。
- 默认脚本路径为 `vpy.vpy`。

---

## build.sh（Linux 运行环境脚本）

`build.sh`是用于构建特定 Linux 系统程序运行环境的脚本，当前支持：
- Ubuntu 22.04 / 24.04 / 25.10 / 26.04（beta）
- Debian 12 / 13

建议在远程终端中执行 `build.sh`，因为远程终端会使用 tmux 输出，日志更简洁、更易读。

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
  - 检查章节起止，比如最后一集最后一个章节是版权提示，需要裁除，有三种方法：  
    a. 在主播放列表”查看章节"中中取消最后一段勾选并保存  
    b. 选择最后一集的结束章节，将 ending 改为最后一个章节  
    c. 混流命令编辑框中修改混流命令，请参阅 https://mkvtoolnix.download/doc/mkvmerge.html 中的--split parts 和 --split chapters 部分
  - 检查字幕行顺序，可以点击文件名 header 栏排序。
  - 检查字幕时长，如果时长超长，很有可能是字幕文件有问题。可以右键 edit 编辑字幕，编辑字幕时会优先展示结束时间最晚的那些字幕，对有问题的字幕，修改其结束时间后保存，或者一并选择右键删除即可。
- 存在特典盘：
  - 取消特点盘分卷的 main MPLS 选择即可
- 预览无法启动：
  - 检查 `vsedit` 路径；
  - 检查 VPy 文件与插件可用性。
- Docker/Linux 播放异常：
  - 检查 DISPLAY、音频转发、mpv 可用性。

---

## FAQ

### 压制会自动裁黑边吗？

不会。需要在 VPy 脚本中自行添加裁切逻辑。

### 如何快速测试压制，不跑完整片？

可在 VPy 输出前临时加一段裁剪，例如：

```python
res = res.std.Trim(first=0, length=720)
```

测试后删除即可。

---

## 鸣谢（Credits）

- [tsMuxer](https://github.com/justdan96/tsMuxer)
- [BluRay](https://github.com/lw/BluRay)
- [shinya](https://github.com/shimamura-hougetsu/shinya)
- [ass2bdnxml](https://github.com/Masaiki/ass2bdnxml)
- [BDSup2Sub](https://github.com/mjuhasz/BDSup2Sub)
- [Spp2Pgs](https://github.com/subelf/Spp2Pgs)
