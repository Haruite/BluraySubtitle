# BluraySubtitle

[English](README.md) | 简体中文

项目文档：[Wiki／媒体概念与开发者指南](docs/wiki/Home.zh-Hans.md) | [界面展示及说明](docs/wiki/Interface-Guide.zh-Hans.md)

开发文档：[强制代码修改规范](docs/development/code-standards.zh-Hans.md) | [媒体处理方案与工具选型](docs/development/media-pipeline-and-tool-selection.zh-Hans.md) | [重构历史](docs/refactoring/refactoring-history.zh-Hans.md)

Windows x64 版本使用目录包发布。请完整解压后运行 `BluraySubtitle_windows_x64.exe`，不要将它与 `_internal` 目录分离。配置保存在程序目录的 `config.json` 中，源码运行时位于仓库根目录；请确保该目录可写。

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
- 页面可纵向滚动，拖动表格底部调节条可调整高度；布局和表格操作见[界面指南](docs/wiki/Interface-Guide.zh-Hans.md#主窗口的内容分区)。
- **设置**管理常规选项、路径、启动默认值、外部工具和手动更新。
- 勾选要处理的原盘，拖动路径调整顺序。剧集模式按章节分集，电影模式保持连续输出；每卷可选择多个主 MPLS。执行前请检查自动选片、分集范围和轨道。

### Remux 控制

在**编辑轨道**中选择视频、音频和字幕；如需调整混流命令，可直接编辑主 MPLS 对应的命令。命令中手写的选轨参数会被界面选择替换。

- **允许非视频轨道部分缺失**默认关闭。开启后可保留音频／字幕片段缺失形成的空档，缺失视频或整条已选轨道仍会失败。详见[缺轨处理](docs/development/media-pipeline-and-tool-selection.zh-Hans.md#3-轨道对齐的-remux-回退)。
- **裁剪版权片段**尝试移除分集末尾的短版权片段，须检查结果，详见[适用条件](docs/wiki/Blu-ray-Disc-Structure.zh-Hans.md#末尾的短版权片段)。
- 所选外挂字幕内封为正片 MKV 的软字幕轨道。
- **混流 Dolby Vision**将 MEL 转换为 profile 8.1，FEL 或无法识别的增强层保留 profile 7；关闭时排除增强层。详见 [Dolby Vision 分层处理](docs/wiki/Media-Formats-and-Dolby-Vision.zh-Hans.md#本项目中的-profile-81)。

### 音频控制

- Remux 保留有损音轨，默认将无损音轨转换为 FLAC；转换开关和压缩等级可在**高级**中配置。
- **Remux 时将 DTS:X 和 TrueHD Atmos 转换为 FLAC**默认关闭，因为 FLAC 无法保留对象元数据。
- Remux 和压制会移除静音及完全重复的音轨，并报告移除结果；独立单轨音频除外。
- 带空档的音轨转换后须保存在 Matroska 容器中。请保留 Remux 输出旁的 `.audio-gaps.json`，供后续压制使用。
- 转换失败或时长缩短超过阈值（默认 1 秒）时保留原轨，阈值可在设置中调整。

格式选择见[音频格式与转换目标](docs/wiki/Media-Formats-and-Dolby-Vision.zh-Hans.md#无损音频转换决策)，清理和验证规则见[媒体处理流程](docs/development/media-pipeline-and-tool-selection.zh-Hans.md#音频处理)。

### 压制控制

- 可选择自带／系统 `vspipe` 和编码器：x264 支持 8/10-bit，x265 支持 8/10/12-bit，SVT-AV1 支持 8/10-bit；SVT-AV1 的 12-bit 实验选项不可用。
- 保留来源 CFR／VFR 时间轴和音画同步。VPy 处理须保持帧对应关系，也支持[开头截取测试](#如何快速测试压制不跑完整片)。
- 内置预设只读；可在**高级**中管理用户预设，也可直接修改压制参数。
- 每个正片／SP 行可指定 VPy 和逐轨 FLAC/AAC/Opus 转换。字幕支持外挂、内挂和内嵌；Remux 来源还支持编辑章节／附件。
- 默认 VPy 提供降噪、去光晕、去振铃、去色带和抗锯齿强度设置。
- 自动 getnative 可能消耗较多时间和内存，并跳过高度超过 1080 像素的源；更高分辨率可用 [getnative 脚本](src/scripts/getnative_file.py)手动分析。
- 自动裁剪需检查画面；对比图和坏帧报告分别保存在输出目录的 `Compare` 和 `FrameCheck` 中。完整坏帧检测耗时可能为视频时长的数倍。
- 保留 Dolby Vision 须使用 x265 10/12-bit，同时支持 HDR10+。FEL 图像残差无法用于压制，完成后会提示；SVT-AV1 会提示不能保留 Dolby Vision。

参数、滤镜、预览和元数据限制见[视频压制与 VapourSynth](docs/wiki/Video-Encoding-and-VapourSynth.zh-Hans.md)。

### SP 管理

完成主播放列表及分集选择后再检查 SP 表，取消不需要的内容。编辑轨道会更新输出名称和格式；匹配的评论音轨可以加入正片。详见 [SP 选择、命名与附加规则](docs/wiki/Blu-ray-Disc-Structure.zh-Hans.md#本项目中的正片与-sp)。

## 依赖要求

### Python 依赖

- `PyQt6`
- `numpy`
- `soundfile`
- `pycountry`
- `Pillow`
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
- `hdr10plus_tool`（HDR10+）
- `dovi_tool`（Dolby Vision）
- `SvtAv1EncApp`
- `fdkaac`

> 在**设置 > 外部工具**中配置路径并检查工具可用性；压制可选择自带或系统工具。

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

- 加载目录时支持大于 5 GiB 的 ISO，合并字幕以同名文件保存在镜像旁。ISO 输入仅用于合并字幕。
- 对不上时先检查 main MPLS；
- 路径顺序错乱时先排序或拖动行；
- 个别字幕时长异常时先修字幕再执行。
- 支持 SRT、ASS、SSA 和 SUP；同一个合并输出不能混用不同字幕格式。
- 结果保存在原盘目录旁和主播放列表旁；输出已存在时会报错，不覆盖文件。
- 同一原盘选择多个主播放列表时分别合并；原盘目录旁的文件会附加 MPLS 文件名以避免重名。

## 2）给 MKV 添加章节

典型流程：

1. 加载蓝光章节来源（playlist/chapter 信息）；
2. 加载目标 MKV 目录；
3. 校验 main MPLS；
4. 执行章节写入。

行为说明：

- MKV 按表格顺序与主播放列表的章节匹配，请先检查排列顺序。
- 勾选“直接编辑原文件”时写入源 MKV；否则保存在源目录的 `output` 子目录。
- 章节无法完整匹配或输出已存在时停止写入。

## 3）原盘 Remux

典型流程：

1. 加载原盘目录；
2. （可选）加载字幕目录；
3. 校验主播放列表与章节区间；
4. （可选）编辑 remux 命令；
5. 选择输出目录并执行。

请在执行前检查[Remux 设置](#remux-控制)和输出名称。已有或重复输出会中止任务，不覆盖文件。

## 4）原盘压制

典型流程：

1. 选择输入源（原盘 / Remux）；
2. 配置 VPy、x265、字幕封装等选项；
3. （可选）编辑轨道或一键全选轨道；
4. （可选）设置起始/结束章节；
5. 执行压制。

原盘输入遇到已有输出时会报错；Remux 输入会跳过已完成的正片／SP、外挂字幕和附带文件，继续剩余任务，可用于中断后恢复压制。空的正片／SP 文件会报错，需先处理。

---

## VPy 编辑与预览

- **编辑脚本**使用系统关联编辑器，**预览脚本**使用 `vsedit`；默认脚本为 `vpy.vpy`。
- 默认 VPy 可对比处理后画面与原画，操作见 [VSEdit 预览与截图](docs/wiki/Video-Encoding-and-VapourSynth.zh-Hans.md#在-vsedit-中对比处理后画面与原画)。
- 隔行、胶转磁和混合 cadence 来源需按[预处理说明](docs/wiki/Video-Encoding-and-VapourSynth.zh-Hans.md#隔行胶转磁与混合-cadence-来源)准备。

---

## 仓库辅助脚本

- [`src/scripts/batch_remux_movie.py`](src/scripts/batch_remux_movie.py)：修改脚本内路径或通过命令行传入路径，可批量 Remux 一个电影目录下的全部 BDMV。
- [`src/scripts/getnative_file.py`](src/scripts/getnative_file.py)：修改 `video_file` 后直接运行，可输出单个视频的自动 getnative 结果与耗时秒数。

---

## setup_windows_environment.ps1（Windows 环境配置脚本）

`setup_windows_environment.ps1` 用于为 **Windows 客户端和 Windows Server x64 系统**配置运行与编译环境。

首次运行前，先设置当前用户的 PowerShell 执行策略，再从仓库根目录启动：

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

可在宿主机运行 `pactl info`、`wpctl status` 和 `aplay -l` 判断可用接口。桌面的 PipeWire 或 PulseAudio 已经管理声卡时，不要再把 `/dev/snd` 作为回退暴露给容器。

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

可以，需要主动勾选并核对裁剪值及成品画面。暗场、片头片尾和特殊黑边可能使自动结果出错；需要精确控制时关闭该选项，在 VPy 中指定裁剪。原理见[自动裁剪黑边](docs/wiki/Video-Encoding-and-VapourSynth.zh-Hans.md#自动裁剪黑边)。

### 如何快速测试压制，不跑完整片？

如需快速测试视频侧流程，可在 VPy 最后两行输出语句前截取开头一段：

```python
res = res.std.Trim(first=0, length=720)
```

`720` 可改成所需帧数。此方法仅截短视频，getnative 和音轨转换仍处理完整来源，音轨、软字幕及章节也不会同步截短。HDR10+ 会被省略，也不适合验证完整 Dolby Vision 流程。测试全部压制流程时，请使用视频、音频、字幕、章节和动态元数据已同步截短的短 MKV。

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
