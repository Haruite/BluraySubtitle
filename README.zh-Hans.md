# BluraySubtitle

[English](README.md) | 简体中文

项目文档：[Wiki／媒体概念与开发者指南](docs/wiki/Home.zh-Hans.md) | [界面展示及说明](docs/wiki/Interface-Guide.zh-Hans.md)

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

## 功能与控制

### 界面与任务设置

- 支持英文／简体中文，以及浅色、深色、彩色主题和透明度调整。
- **设置**包含常规、路径、高级、外部工具和手动更新；应用设置与窗口位置、大小保存在 `config.json`。
- 剧集模式按章节时间线分集，电影模式保持连续输出；每卷可选择多个主 MPLS。自动选片和分集估算仍需检查。片段勾选与章节编辑的联动见[分集重算规则](docs/wiki/BluraySubtitle-Developer-Guide.zh-Hans.md#分集配置)。
- 任务采用启动时界面显示的行顺序、名称、区间、命令、轨道及语言，无效配置会在执行前报错。选择和检查方法见[界面示例](docs/wiki/Interface-Guide.zh-Hans.md)。

### Remux 控制

每个已选主 MPLS 对应一条非空的可编辑混流命令。计划输出数量必须与可见分集行数一致，无效文件名会被拒绝。视频、音频、字幕选择以**编辑轨道**为准，命令中手写的选轨参数会被替换。逻辑轨道行显示 PID 和状态，悬停可查看逐 PlayItem 明细；不兼容的轨道会被禁用。

- **允许非视频轨道部分缺失**默认关闭。只有 tsMuxer 无法恢复物理缺失的音频／字幕片段、且该轨道在输出其他位置存在时，才允许保留空档；缺失视频或整条已选轨道仍会失败。
- **裁剪版权片段**可在分集结束于 M2TS 文件结尾时，移除最后 30 秒内的完整末尾片段。须检查结果，详见[具体规则与例外](docs/wiki/Blu-ray-Disc-Structure.zh-Hans.md#末尾的短版权片段)。
- 所选外挂字幕作为软字幕轨内封进正片 MKV；Remux 不将其烧录进画面，也不另存为外挂输出。
- **混流 Dolby Vision**将已确认的 MEL 转换为 profile 8.1，FEL 或无法识别的增强层保留 profile 7；关闭时排除增强层。详见 [Dolby Vision 分层处理](docs/wiki/Media-Formats-and-Dolby-Vision.zh-Hans.md#本项目中的-profile-81)。

混流后会应用并验证已保存的轨道语言。映射、工具或语言验证失败会停止任务并删除其新建的主输出；轨道数量和 MKVToolNix 数据包统计检查则在结束时汇总警告，后续 Remux 继续。

### 音频控制

- Remux 不重新编码有损音轨。**将无损音轨转换为 FLAC**默认启用；启动状态和独立／FFmpeg FLAC 压缩等级（均默认为 8）可在**高级**中配置。
- **Remux 时将 DTS:X 和 TrueHD Atmos 转换为 FLAC**是独立选项，默认关闭，因为 FLAC 无法保留对象元数据。
- 即使关闭 FLAC 转换，最终 Matroska 输出仍会清理音轨：移除解码最大音量低于 `-60 dB` 的轨道，以及同编码家族、同声道数内解码后完全重复的轨道。已知语言不同则保留，重复时保留源顺序最早的一条，每次移除均报告。独立单轨音频不执行此清理。
- 转换在 Matroska 中保留编排空档，不补静音；带空档的独立音频输出会被拒绝。请保留旁边的 `.audio-gaps.json` 供以后从 Remux 来源压制使用，包括表示连续音轨的有效空记录。
- 转换失败保留原轨。单个连续区间的最大缩短量超过 0.1 秒会提示；超过可配置阈值（默认 1 秒）则放弃转换结果。

格式选择见[音频格式与转换目标](docs/wiki/Media-Formats-and-Dolby-Vision.zh-Hans.md#无损音频转换决策)，验证和恢复细节见[媒体处理流程](docs/development/media-pipeline-and-tool-selection.zh-Hans.md)。

### 压制控制

- 可选择自带／系统 `vspipe` 和编码器：x264 支持 8/10-bit，x265 支持 8/10/12-bit，SVT-AV1 正常输出使用 8/10-bit。界面中的 SVT-AV1 12-bit 路径属于实验功能，setup 脚本产物不能生成有效视频。
- 内置预设只读；**高级**管理用户预设及启动默认值，每次任务采用界面当前的参数文本。
- 每个正片／SP 行有独立 VPy 路径和逐轨 FLAC/AAC/Opus 选择。字幕支持外挂、内挂和内嵌；Remux 来源还支持编辑章节／附件。
- 默认 VPy 提供降噪、去光晕、去振铃、去色带和抗锯齿强度；这些控制及 getnative／裁剪／对比图／坏帧检测的启动默认值均保存在**高级**设置。
- 自动 getnative 可能消耗较多时间和内存，并跳过高度超过 1080 像素的源；更高分辨率须手动运行 `src/scripts/getnative_file.py`。
- 自动裁剪默认关闭，需检查画面。对比图写入 `<所选输出目录>/<来源文件夹名>/Compare`，完整逐帧 PSNR 报告写入 `FrameCheck`；完整检查会重新渲染 VPy，耗时可能为视频时长的数倍。
- 兼容的色彩／HDR 元数据会写入输出。保留 Dolby Vision 须使用 x265 10/12-bit；x264 和 x265 8-bit 不支持。SVT-AV1 在完成弹窗中提示不会保留 Dolby Vision。x265 10/12-bit 同时支持 HDR10+；自动裁剪会调整 Dolby Vision 有效画面元数据。x265 保留 Dolby Vision 时，在同一完成弹窗中提示 FEL 图像残差未被利用，不因此使任务失败。

默认值、参数、预览快捷键和元数据限制见[视频压制与 VapourSynth](docs/wiki/Video-Encoding-and-VapourSynth.zh-Hans.md)。

### SP 管理

完成主播放列表及分集选择后再检查 SP 表。SP 行可来自其他播放列表、主播放列表的排除区间或未覆盖的 M2TS。编辑轨道会更新输出名称和格式；匹配的评论内容可能复用主输出或追加到唯一一集。[SP 选择、命名与附加规则](docs/wiki/Blu-ray-Disc-Structure.zh-Hans.md#本项目中的正片与-sp)记录默认行为和特殊原盘案例。

### 受管理的 x264 与 x265 版本

setup 脚本运行或 Docker 镜像构建时，会动态解析官方上游的当前版本：

- **[x264](https://code.videolan.org/videolan/x264)** 使用官方 `master` 的最新版本，编译为一个同时支持 8/10 位输出的 CLI；Windows setup 使用 MSYS2 UCRT64 工具链和 PGO（配置文件引导优化）。
- **[x265](https://github.com/Multicorewareinc/x265)** 使用官方最新的稳定数字版本标签，编译为一个静态链接的 8/10/12 位 multilib CLI，三个被链接的核心都启用原生 HDR10+ JSON 输入（`--dhdr10-info`）和 Dolby Vision RPU 输入（`--dolby-vision-profile`、`--dolby-vision-rpu`）。

受管理的路径保持不变，保存在 [settings.py](src/core/settings.py)。如需使用其他构建，直接替换相同路径下对应的可执行文件即可。

setup 脚本还会安装 [hdr10plus_tool](https://github.com/quietvoid/hdr10plus_tool) 的官方最新 release。

自行编译 x265 时，可参考 `setup_windows_environment.ps1`、`setup_linux_environment.sh` 中的官方 multilib 步骤。

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
- 7-Zip，用于读取 ISO 镜像中的播放列表

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

注意事项：

- 在“生成合并字幕”中加载目录时，也会读取大于 5 GiB 的 `.iso` 文件内的 BDMV 播放列表，扩展名不区分大小写。受支持的 Windows、Linux 和 Docker 均可使用，无需挂载镜像。播放列表保存在程序私有临时目录中，关闭窗口后清理；合并字幕以 ISO 文件主名保存在镜像旁。ISO 输入不支持预览、Remux、Encode 或补全原盘目录。
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
- 自动生成的默认 VPy 把处理后的 `res` 设为输出索引 `0`，把原始 `src8` 设为输出索引 `1`。VSEdit 的预览与截图快捷键见 [Encode／VapourSynth Wiki](docs/wiki/Video-Encoding-and-VapourSynth.zh-Hans.md#在-vsedit-中对比处理后画面与原画)；这项实时预览不同于压制完成后由“输出对比图”生成的 PNG 文件。
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

PulseAudio 或 PipeWire-Pulse 运行示例（推荐用于大多数 Linux 桌面和远程桌面会话）：

```bash
xhost +local:docker
sudo docker run -it --rm \
  -e DISPLAY=$DISPLAY \
  -e LIBGL_ALWAYS_SOFTWARE=1 \
  -e BLURAY_SUBTITLE_MPV_AUDIO_OUTPUT=pulse \
  -e PULSE_SERVER=unix:/tmp/pulse/native \
  -v /tmp/.X11-unix:/tmp/.X11-unix \
  -v /run/user/$(id -u)/pulse/native:/tmp/pulse/native \
  -v bluray-subtitle-config:/config \
  -v /path/to/media:/data \
  --ipc=host \
  --shm-size=2gb \
  bluray-subtitle-ubuntu
```

命名卷 `bluray-subtitle-config` 用于保存 `config.json` 和生成的 `vpy.vpy`。后续运行时复用同一个卷名，即使容器使用 `--rm`，程序内修改的设置也会被重新加载。

容器以非 root 用户 `ubuntu`（UID/GID `1000`）运行桌面程序；挂载的媒体必须允许该用户访问。

Docker 音频方式只能选择以下一种：

- **PulseAudio 或 PipeWire-Pulse（推荐）：**使用上方完整示例中的 `BLURAY_SUBTITLE_MPV_AUDIO_OUTPUT=pulse`、`PULSE_SERVER` 和 `/pulse/native` 三个选项。
- **不使用 PipeWire-Pulse 的原生 PipeWire：**将上述三个 Pulse 选项替换为：

  ```bash
  -e BLURAY_SUBTITLE_MPV_AUDIO_OUTPUT=pipewire \
  -v /run/user/$(id -u)/pipewire-0:/tmp/runtime-ubuntu/pipewire-0
  ```

- **仅使用 ALSA 的宿主机：**将三个 Pulse 选项替换为以下内容。宿主机必须存在 `controlC0`；当宿主音频组 GID 与镜像不同时，group 选项会授予非 root 容器用户设备访问权：

  ```bash
  --device /dev/snd \
  --group-add "$(stat -c '%g' /dev/snd/controlC0)" \
  -e BLURAY_SUBTITLE_MPV_AUDIO_OUTPUT=alsa
  ```

可在宿主机运行 `pactl info`、`wpctl status` 和 `aplay -l` 判断可用接口。桌面的 PipeWire 或 PulseAudio 已经管理声卡时，不要再把 `/dev/snd` 作为回退暴露给容器。非 Docker 的 Linux 源码运行不需要这些转发选项，宿主机 mpv 会照常自动选择音频输出。

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
  - 检查 DISPLAY 和 mpv 可用性。Docker 无声时，确认所选的 PulseAudio、PipeWire 或 ALSA 宿主端点存在，并使用 Docker 章节中对应的一组选项。

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

大概率存在重复的特典片段。解决方法：检查各 MPLS，点击“查看章节”；如果某个 MPLS 的片段与主 MPLS 重叠，选择该 MPLS 为主 MPLS，再取消重复段落的勾选，并检查下方 SP 表，取消相同内容的输出。参见带截图的[《花样少年少女》示例](docs/wiki/Interface-Guide.zh-Hans.md#示例避免重复片段让-remux-体积膨胀)。

### 压制有给章节加 OP 和 ED 标识吗？

没有，如果需要，先 remux 原盘，然后在原盘压制界面选择源为 remux，这时候可以点击编辑章节自行编辑章节标题。

### 为什么 getnative 获取的每集的原始分辨率不一样？

正常现象，因为有些原盘不止一种原生分辨率，以及原盘制作流程的复杂性，导致源分辨率难以分辨。可以先跑一遍测试，如果每集输出的原始分辨率结果基本相同则可以用程序自动的 getnative，否则去掉勾选自动 getnative 选项并编辑 vpy 填入你认为的原始分辨率和缩放算法，或者根本不填。



## 鸣谢（Credits）

- [tsMuxer](https://github.com/justdan96/tsMuxer)
- [BluRay](https://github.com/lw/BluRay)
- [shinya](https://github.com/shimamura-hougetsu/shinya)
- [ass2bdnxml](https://github.com/Masaiki/ass2bdnxml)
- [BDSup2Sub](https://github.com/mjuhasz/BDSup2Sub)
- [Spp2Pgs](https://github.com/subelf/Spp2Pgs)
- [getnative](https://github.com/Infiziert90/getnative)
- [my-vapoursynth-script](https://github.com/xyx98/my-vapoursynth-script)
