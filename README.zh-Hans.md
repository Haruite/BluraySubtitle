# BluraySubtitle

[English](README.md) | 简体中文

项目文档：[Wiki／媒体概念与开发者指南](docs/wiki/Home.zh-Hans.md) | [界面展示及说明](docs/wiki/Interface-Guide.zh-Hans.md)

开发文档：[强制代码修改规范](docs/development/code-standards.zh-Hans.md) | [媒体处理方案与工具选型](docs/development/media-pipeline-and-tool-selection.zh-Hans.md) | [重构历史](docs/refactoring/refactoring-history.zh-Hans.md)

- `main` 分支最新构建，每次推送更新。[Windows x64](https://sbx.mysmy.top/tools/BluraySubtitle/BluraySubtitle_windows_x64.7z) · [Windows ARM64](https://sbx.mysmy.top/tools/BluraySubtitle/BluraySubtitle_windows_arm64.7z) · [Ubuntu 26.04 x64](https://sbx.mysmy.top/tools/BluraySubtitle/BluraySubtitle_ubuntu26.04_x64.tar.xz) · [Ubuntu 26.04 ARM64](https://sbx.mysmy.top/tools/BluraySubtitle/BluraySubtitle_ubuntu26.04_arm64.tar.xz)
- 版本 4.7 以后，对应版本的安装包会附在 Release 中。[GitHub Releases](https://github.com/Haruite/BluraySubtitle/releases)

Windows x64 程序包支持 **Windows 10 1809 及以上版本 和 Windows 11**。Windows ARM64 程序包面向 **Windows 10 和 Windows 11 ARM64 版本**，具体最低 Windows 10 版本待验证。Windows 10 建议使用 **22H2**。

BluraySubtitle 是一个跨平台的蓝光流程 GUI 工具。它将以下五类功能整合在一个应用中：

1. **原盘 Remux**
2. **原盘压制**
3. **原盘 DIY（待开发）**
4. **生成合并字幕**
5. **给 MKV 添加章节**

---

## 功能与控制

### 界面与设置

- 语言支持英文／简体中文，有浅色、深色、彩色三种主题，支持透调节明度。
- 页面可纵向滚动，拖动表格底部调节条可调整高度。
- **设置**管理常规选项、字体、路径、启动默认值和外部工具。在**工具**页可检查更新或创建启动快捷方式。
- 所有可以互动的控件、可以编辑的单元格外围有一圈加强线，可编辑单元格悬浮有气泡提示，不可编辑单元格双击提示只可复制。
- 主窗口默认脱离终端运行，日志可在独立窗口查看。
- 主窗口和日志窗口都可以设置背景图片和背景图片透明度、模糊度。

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
- 带空档的音轨转换后须保存在 Matroska 容器中。
- **设置 → 高级 → 音频编码**中的 **Remux 时保存 .audio-gaps.json** 默认关闭。如果 Remux 成品要用于后续压制，建议开启，并将 `.audio-gaps.json` 保留在成品旁，供压制时复用音轨间隙检测结果。
- 转换失败或时长缩短超过阈值（默认 1 秒）时保留原轨，阈值可在设置中调整。

格式选择见[音频格式与转换目标](docs/wiki/Media-Formats-and-Dolby-Vision.zh-Hans.md#无损音频转换决策)，清理和验证规则见[媒体处理流程](docs/development/media-pipeline-and-tool-selection.zh-Hans.md#音频处理)。

### 压制控制

- x264 支持 8/10-bit，x265 支持 8/10/12-bit。SVT-AV1 标准构建支持 8/10-bit；仅当所选编码器支持时才显示 12-bit 选项。
- 保留来源 CFR／VFR 时间轴和音画同步。VPy 处理须保持帧对应关系，也支持[开头截取测试](#如何快速测试压制不跑完整片)。
- 内置预设只读；可在**高级**中管理用户预设，也可直接修改压制参数。
- 每个正片／SP 行可指定 VPy 和逐轨 FLAC/AAC/Opus 转换。字幕支持外挂、内挂和内嵌；Remux 来源还支持编辑章节／附件。
- 字幕文件夹按当前正片行顺序填入字幕，压制前请检查对应关系。
- 默认 VPy 提供降噪、去光晕、去振铃、去色带和抗锯齿强度设置。
- 自动 getnative 可能消耗较多时间和内存，并跳过高度超过 1080 像素的源；更高分辨率可用 [getnative 脚本](src/scripts/getnative_file.py)手动分析。
- 自动裁剪需检查画面；对比图和坏帧报告分别保存在输出目录的 `Compare` 和 `FrameCheck` 中。完整坏帧检测耗时可能为视频时长的数倍。
- 保留 Dolby Vision 须使用 x265 10-bit；x265 10/12-bit 支持 HDR10+。FEL 图像残差无法用于压制，完成后会提示；SVT-AV1 会提示不能保留 Dolby Vision。

参数、滤镜、预览和元数据限制见[视频压制与 VapourSynth](docs/wiki/Video-Encoding-and-VapourSynth.zh-Hans.md)。

### SP 管理

**设置 → 常规 → Remux 时保留 SP（特典）**默认勾选。关闭后，在原盘 Remux 和原盘压制中载入原盘时，SP 表的条目默认全部不勾选。
完成主播放列表及分集选择后再检查 SP 表，调整勾选内容。仅 Remux SP 时，取消所有主播放列表，只在 SP 表中保留所需行。编辑轨道会更新输出名称和格式；匹配的评论音轨可以加入正片。详见 [SP 选择、命名与附加规则](docs/wiki/Blu-ray-Disc-Structure.zh-Hans.md#本项目中的正片与-sp)。

## 依赖要求

从源码运行时，按使用的功能安装相应的工具。

### Python 依赖

需要使用 Python 3.10 及以上版本，启动程序界面还需要安装以下 pip 包。

```bash
python -m pip install PyQt6 numpy soundfile pycountry
```

如果有其他功能要求：
- `Pillow` 用于自动 getnative 等图像处理。
- 系统无法直接报告可用内存时，可以安装 `psutil`，让自动 getnative 按可用内存设置并发数。
- 自定义 VPy 调用 `muvsfunc.getnative()` 绘图时需要 `matplotlib`。
- 自行打包时需要 `PyInstaller`。

### 外部工具

使用 BDMV 目录合并字幕只需上述界面依赖。读取 ISO 镜像中的播放列表时，还需 7-Zip（`7zz` 或 `7z`）。

| 功能 | 工具 |
| --- | --- |
| Remux、压制封装和添加 MKV 章节 | MKVToolNix（`mkvmerge`、`mkvinfo`、`mkvextract`、`mkvpropedit`） |
| 媒体检测、解码和音频转换 | `ffmpeg`、`ffprobe` |
| FLAC 或 AAC 音轨转换 | FLAC 用 `flac` 1.5.0 及以上版本，AAC 用 `fdkaac` |
| Remux 回退抽流 | `tsMuxeR` |
| 动态 HDR 元数据 | Dolby Vision 用 `dovi_tool`，HDR10+ 用 `hdr10plus_tool` |
| ASS 字幕渲染 | `libass` 供 ASSRender 使用 |

### 压制模式额外依赖

- VapourSynth 运行时和 .vpy 脚本涉及的插件。
- `x264`、`x265` 或 `SvtAv1EncApp`，按所选编码器安装。
- VPy 预览使用 `vsedit`。

> 在**设置 → 外部工具**中修改和检查路径。路径留空时会自动查找已安装的工具。配置保存在 `config.json` 中。

---

## 快速开始

```bash
python src/main.py
```

桌面版启动后在独立进程中运行，可以关闭启动它的终端。在终端里给启动命令加上 `--foreground`，即可同时在终端中查看输出。

桌面支持系统托盘时，关闭主窗口默认会将它收起到托盘，任务会继续运行。单击托盘图标或从同一目录再次启动程序可恢复主窗口。要退出程序，点击主窗口或托盘图标右键菜单中的 **退出**。可在 **设置 → 常规 → 关闭主窗口时最小化到托盘** 关闭此行为。

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

1. 加载蓝光章节来源；
2. 加载目标 MKV 目录；
3. 校验 main MPLS；
4. 执行章节写入。

行为说明：

- 蓝光来源可以是完整 BDMV 目录，也可以是只包含播放列表的文件夹，但任需保持原始目录结构。可以在 qBittorrent 下载原盘时只勾选 PLAYLIST 文件夹。
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

- **编辑脚本**使用系统关联编辑器，**预览脚本**使用 `vsedit`。默认脚本生成在 `config.json` 旁的 `vpy/vpy_<标识>.vpy`。预览默认脚本时，VSEdit 打开已填入当前行片源和字幕路径的临时副本。关闭 VSEdit 后，已保存的滤镜修改会同步回默认脚本。
- 默认 VPy 可对比处理后画面与原画，操作见 [VSEdit 预览与截图](docs/wiki/Video-Encoding-and-VapourSynth.zh-Hans.md#在-vsedit-中对比处理后画面与原画)。
- 隔行、胶转磁和混合 cadence 来源需按[预处理说明](docs/wiki/Video-Encoding-and-VapourSynth.zh-Hans.md#隔行胶转磁与混合-cadence-来源)准备。

---

## 仓库辅助脚本

- [`src/scripts/batch_remux_movie.py`](src/scripts/batch_remux_movie.py)：修改脚本内路径或通过命令行传入路径，可批量 Remux 一个电影目录下的全部 BDMV。
- [`src/scripts/batch_getnative_file.py`](src/scripts/getnative_file.py)：运行时传入视频路径，可输出单个视频的 getnative 结果与耗时秒数。

---

## 跨平台支持

只要系统和架构能够提供[所需的 Python 版本及依赖](#python-依赖)和所用功能的外部工具，即可从源码运行。\
有些功能（主要是压制）依赖较多外部工具，编译和配置步骤也较多。以下环境配置脚本可为所列系统准备运行全部功能的环境。其他系统可以手动配置。\
项目也提供 Windows 和 Ubuntu 打包版。

### setup_windows_environment.ps1（Windows 环境配置脚本）

脚本为 **x64 Windows 10 1909 及以上版本**、**带桌面体验的 x64 Windows Server 2019 及以上版本**和 **ARM64 Windows 11 及以上版本**配置源码运行环境。两种架构默认使用 VapourSynth R79。需要 Classic 时可传入 `-VapourSynthRuntime Classic`。在 ARM64 上，该选项使用独立的 x64 Python，并为 Classic 插件和 VSEdit 使用 x64 构建。

首次运行时，先设置当前用户的 PowerShell 执行策略，再从仓库根目录启动脚本。

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned -Force
.\setup_windows_environment.ps1
```

脚本会申请管理员权限、询问显示语言，并支持中断后重新运行。下载时会自动使用已配置的 **Windows 系统代理**。如果无法直连下载源，请先配置系统代理再启动脚本。

完成环境配置后，如果要打包运行环境，在仓库根目录按架构选择一条打包命令运行。

```powershell
pyinstaller BluraySubtitle_windows_x64.spec
```

```powershell
pyinstaller BluraySubtitle_windows_arm64.spec
```

### setup_linux_environment.sh（Linux 运行环境脚本）

脚本可为以下基于 APT 的原生 **x64 或 ARM64 Linux** 系统配置源码运行环境。

- Ubuntu 22.04 及以上版本，包括基于这些 Ubuntu 版本的衍生发行版。
- Debian 12 及以上版本，包括基于这些 Debian 版本的衍生发行版。

脚本安装 VapourSynth R79。如果系统 Python 版本较旧，脚本会安装独立的 Python 3.12，并在结束时给出启动命令。

脚本的早期版本在以下 x64 WSL 2 环境中完成过验证。

- Ubuntu 22.04、24.04、26.04、26.10
- Debian 12、13
- Kali Linux 2022.4、Kali Rolling
- Linux Mint 22.3
- LMDE 7
- antiX 23.2、26.1
- Devuan 6
- KDE neon
- Pop!_OS 24.04

使用具备 `sudo` 权限的普通账户。直接以 `root` 用户运行脚本不保证成功。首次运行前先授予脚本执行权限，再从仓库根目录启动。

```bash
chmod +x setup_linux_environment.sh
./setup_linux_environment.sh
```

播放预设和字幕字体见 [Linux 桌面 mpv](docs/wiki/Media-Formats-and-Dolby-Vision.zh-Hans.md#linux-桌面-mpv-播放)。

通过 SSH 运行 `setup_linux_environment.sh` 时，脚本会使用 **tmux** 显示构建日志。

---

## 常见问题排查

- 剧集映射不对：
  - 检查 main MPLS，播放MPLS，选择正确的MPLS；
  - 检查章节起止。
  - 检查字幕行顺序，可以点击文件名 header 栏排序。
  - 检查字幕时长。对于时间超长的字幕，可以右键编辑字幕，编辑字幕时会优先展示结束时间最晚的那些行，如果有问题，修改其结束时间后保存，或者一并选择右键删除即可。
- 存在特典盘：
  - 取消特典盘分卷的 main MPLS 选择即可。
- 预览无法启动：
  - 检查 `vsedit` 路径；
  - 检查 VPy 文件与插件可用性。
- Linux 播放异常时，检查显示连接和选定的 mpv 路径。

---

## FAQ

### 哪些 Linux 系统可以使用打包版？

PyInstaller 打包版面向 Ubuntu 26.04，提供 x64 和 ARM64 两个版本，理论上更高版本的系统也可以使用。选择与你的系统架构匹配的包。两种包均包含多媒体工具和 VapourSynth 运行时。其他不支持的系统上可以使用 Docker 运行解压后的程序，参见 [Docker 运行 Ubuntu 打包版](docs/wiki/Run-Ubuntu-Package-in-Docker.zh-Hans.md)。

### 如何快速测试压制，不跑完整片？

如需快速测试视频侧流程，可在 VPy 最后两行输出语句前截取开头一段：

```python
res = res.std.Trim(first=0, length=720)
```

`720` 可改成所需帧数。此方法仅截短视频，getnative 和音轨转换仍处理完整来源，音轨、软字幕及章节也不会同步截短。HDR10+ 会被省略，也不适合验证完整 Dolby Vision 流程。测试全部压制流程时，请使用视频、音频、字幕、章节和动态元数据已同步截短的短 MKV。

### 为什么 remux 出来的体积比原盘大？

大概率存在重复的特典片段。解决方法：检查各 MPLS，点击“查看章节”；如果某个 MPLS 的片段与主 MPLS 重叠，选择该 MPLS 为主 MPLS，再取消重复段落的勾选，并检查下方 SP 表，取消相同内容的输出。参见带截图的[《花样少年少女》示例](docs/wiki/Interface-Guide.zh-Hans.md#示例避免重复片段让-remux-体积膨胀)。

### 压制有给章节加 OP 和 ED 标识吗？

没有。如果需要，先 remux 原盘，然后在原盘压制界面选择源为 remux，这时候可以点击编辑章节自行编辑章节标题。

### 为什么 getnative 获取的每集的原始分辨率不一样？

因为有些原盘不止一种原生分辨率，而原盘制作流程中有时候也会加入不同分辨率的素材，导致源分辨率难以分辨。可以先跑一遍测试，如果每集输出的原始分辨率结果基本相同则可以用程序自动的 getnative，否则去掉勾选自动 getnative 选项并编辑 vpy 填入你认为的原始分辨率和缩放算法，或者根本不填。

## 鸣谢（Credits）

- [tsMuxer](https://github.com/justdan96/tsMuxer)
- [BluRay](https://github.com/lw/BluRay)
- [shinya](https://github.com/shimamura-hougetsu/shinya)
- [ass2bdnxml](https://github.com/Masaiki/ass2bdnxml)
- [BDSup2Sub](https://github.com/mjuhasz/BDSup2Sub)
- [Spp2Pgs](https://github.com/subelf/Spp2Pgs)
- [getnative](https://github.com/Infiziert90/getnative)
- [my-vapoursynth-script](https://github.com/xyx98/my-vapoursynth-script)
- [mpv_PlayKit (mpv-lazy)](https://github.com/hooke007/mpv_PlayKit)
