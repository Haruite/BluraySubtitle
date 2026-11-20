# 程序包与系统要求

[English](Packages-and-System-Requirements.md) | 简体中文

## 选择下载文件

根据运行程序的操作系统和处理器架构选择一个压缩包。

| 文件 | 适用系统 | 处理器要求 |
| --- | --- | --- |
| `BluraySubtitle_windows_x64.7z` | Windows 10 x64（接口下限 1709）或 Windows 11 x64 | 主程序及随包的 NumPy 需要 x86-64-v2，例如 Intel Core Nehalem。随包的 zsmooth 滤镜还需要 AVX2。 |
| `BluraySubtitle_windows_arm64.7z` | Windows 10 ARM64（整包接口下限 1903）或 Windows 11 ARM64 | 支持 NEON 和 Armv8.1 LSE 原子指令（包括 `CASAL`）的 64 位 Arm 处理器。 |
| `BluraySubtitle_linux_x64.tar.xz` | 64 位 x86 Linux（x86-64），已验证的内核下限为 3.17 | 完整支持 x86-64-v3，例如 Intel Core Haswell 或 AMD Zen。在 x86-64-v2 基础上需要 AVX、AVX2、BMI1/2、F16C、FMA、LZCNT、MOVBE、OSXSAVE 及操作系统启用的 AVX 寄存器状态。 |
| `BluraySubtitle_linux_arm64.tar.xz` | 64 位 AArch64 Linux，已验证的内核下限为 3.17 | 支持浮点和 NEON 的 Armv8-A 处理器，实测基线为 Cortex-A53。 |

两个 ARM64 包的 NLM 滤镜都使用 128 位 NEON，可在没有 SVE 的处理器上运行。

下载目录中每个压缩包对应一份 `<压缩包名>.txt`，其中记录 SHA-256、Git 提交和提交时间，可用于核对下载文件和构建版本。

完整解压所选程序包。Windows 下运行 `BluraySubtitle_windows_x64.exe` 或 `BluraySubtitle_windows_arm64.exe`。Linux 下用 `tar -xJf <压缩包名>` 解压，进入 `BluraySubtitle/`，以普通用户身份运行 `./BluraySubtitle`。`_internal/` 须与启动程序放在一起。使用早期 Ubuntu 命名包的用户，首次切换时手动下载对应的 Linux 包。

## Windows 运行环境

构建 `13592ef` 使用 Qt 6.12.0 和 CPython 3.15.2。两个包的桌面插件 `qwindows.dll` 在加载时都要从 `UIAutomationCore.dll` 导入 `UiaRaiseNotificationEvent`。微软从 Windows 10 1709（内部版本 16299）起提供该入口。Qt 6.12 的官方支持表将 Windows 10 x64 的起点列为 1809，ARM64 条目只注明 Windows on ARM。[微软接口说明](https://learn.microsoft.com/zh-cn/windows/win32/api/uiautomationcoreapi/nf-uiautomationcoreapi-uiaraisenotificationevent) · [Qt 支持的平台](https://doc.qt.io/qt-6.12/windows.html)

ARM64 包中的 `ffmpeg.exe` 和 `ffprobe.exe` 启动时还要从原生 `avicap32.dll` 导入 `capCreateCaptureWindowA` 和 `capGetDriverDescriptionA`。Windows 10 ARM64 专业版 1709、1803、1809 的映像都只有 x86 副本。1903（内部版本 18362）的 `System32` 首次包含导出这两个入口的 ARM64 副本。即使只用 FFprobe 读取文件信息，也需要该 DLL。[微软视频采集接口说明](https://learn.microsoft.com/zh-cn/windows/win32/api/vfw/nf-vfw-capcreatecapturewindowa)

## Linux 运行环境

程序包自带 Python、glibc、Qt、图形客户端库和媒体工具，也可在 Alpine（musl）和 NixOS 上运行。桌面界面支持 X11、XWayland 或 WSLg。硬件加速需要宿主提供匹配的驱动，RIFE 插帧需要可用的 Vulkan 设备。无显示服务时，可用 `QT_QPA_PLATFORM=offscreen ./BluraySubtitle --foreground` 检查启动。

在 Linux 3.17.0 上，x64 和 ARM64 均以 Qt 6.6 启动主窗口和 VSEdit，并完成了 10 位 HEVC 编码和中文字幕封装。ARM64 已验证 Linux 3.17 的 64 KiB 页和 Ubuntu 26.04 的 4 KiB 页。内核满足新版 Qt 的要求时，主窗口会自动选用包内新版 Qt。

下表列出已测试的 x64 发行版。仅在系统缺少解压工具或中文字体时，以管理员权限运行相应命令。

| 实测 x64 系统 | 解压归档 | 显示中文 |
| --- | --- | --- |
| Ubuntu 22.04、24.04、26.04 | `apt install xz-utils` | `apt install fontconfig fonts-noto-cjk` |
| Debian 12、13 | `apt install xz-utils` | `apt install fontconfig fonts-noto-cjk` |
| Rocky Linux 9.9 | `dnf install xz` | `dnf install fontconfig google-noto-sans-cjk-ttc-fonts` |
| Fedora 45 | `dnf install xz` | `dnf install fontconfig google-noto-sans-cjk-fonts` |
| openSUSE Tumbleweed | 镜像已包含 | `zypper install fontconfig google-noto-sans-cjk-fonts` |
| Arch Linux | 镜像已包含 | `pacman -Syu --needed fontconfig noto-fonts-cjk` |
| Alpine 3.24 | BusyBox 已包含 | `apk add fontconfig font-noto-cjk` |
| NixOS 26.05 | 镜像已包含 | 在 NixOS 配置的 `fonts.packages` 中加入 `pkgs.noto-fonts-cjk-sans`。 |

## 源码安装脚本

**Windows**　`setup_windows_environment.ps1` 支持 x64 版 Windows 10 1909 及以上、带桌面体验的 x64 Windows Server 2019 及以上，以及 ARM64 版 Windows 11 及以上。请使用 64 位 PowerShell。默认安装 VapourSynth R79，可用 `-VapourSynthRuntime Classic` 选择 Classic。ARM64 的 Classic 使用独立的 x64 Python、插件和 VSEdit。

**Linux**　`setup_linux_environment.sh` 支持原生 x64 或 ARM64 的 Ubuntu、Debian 及其 APT 衍生版。脚本检查已安装的软件包和已配置的软件源，包括 backports。非 LTS 版与滚动发行版按相同条件判断。

| 依赖 | 源码安装要求 |
| --- | --- |
| FFmpeg 开发库 | FFmpeg 7 及以上，`libavcodec` 主版本至少为 61 |
| Vulkan 和 libplacebo | Vulkan 头文件 1.3.277 及以上，启用 Vulkan 的 libplacebo 6.338 及以上 |
| 其他构建工具和库 | dav1d 1.0、Meson 1.4、Docutils 0.20 及以上 |
| Qt 和 Python | Desktop 模式需要 Qt 6.4 及以上开发包。uv 安装最新稳定版 CPython 3。当前 PyQt6 wheel 要求 x64 glibc 2.34 及以上、ARM64 glibc 2.39 及以上。 |

x64 使用 zsmooth 和 RIFE 的上游预编译版，支持 x86-64-v3 处理器。无桌面的系统也可安装 RIFE 和模型。

### Linux 安装依赖验证

| 已核对的 x64 环境 | setup 依赖检查 |
| --- | --- |
| Ubuntu 26.04 LTS、26.10、Debian 13、LMDE 7、Devuan 6、antiX 26.1、Kali Rolling | 已安装的软件包或当前软件源满足要求。 |
| Ubuntu 24.10、25.04、25.10 | 官方签名发行索引中的版本满足要求。这三个非 LTS 版本均已结束维护。 |
| 标准源的 Ubuntu 22.04、24.04、Debian 12，以及 Mint 22.3、Pop!_OS 24.04、基于 24.04 的 KDE neon、antiX 23.2、Kali 2022.4 快照 | 所核对的软件源至少缺少一项所需版本，脚本会列出具体缺项。 |

Ubuntu 26.04 的 x64 和 ARM64 构建通过了归档验证。要生成本机架构的软件包，从仓库根目录运行以下命令。

```bash
bash setup_linux_environment.sh --mode Build
bash tools/build_linux_package.sh
```

## 在 Docker 中运行 Linux 包

在 Linux 桌面上解压与宿主机架构匹配的 Linux 包。将可执行文件与 `_internal/` 放在解压所得的同一个 `BluraySubtitle/` 目录中。程序和多媒体工具直接从挂载的包中启动。

### 准备运行环境

构建命令在 x64 宿主机上选择 `linux/amd64`，在 ARM64 宿主机上选择 `linux/arm64`。镜像包含系统图形库和字体。已有这些依赖的 Ubuntu 26.04 镜像也可用作运行环境。

```bash
(
cpu_arch=$(uname -m)
case "$cpu_arch" in
  x86_64|amd64) docker_platform=linux/amd64 ;;
  aarch64|arm64) docker_platform=linux/arm64 ;;
  *) printf '不支持的 CPU 架构 %s\n' "$cpu_arch" >&2; exit 1 ;;
esac

docker build --platform "$docker_platform" -t bluraysubtitle-runtime:26.04 - <<'DOCKER'
FROM ubuntu:26.04
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    ca-certificates fontconfig fonts-noto-cjk x11-utils \
    libegl1 libegl-mesa0 libgl1 libglx-mesa0 libgl1-mesa-dri libopengl0 \
    libvulkan1 mesa-vulkan-drivers libva2 libva-drm2 libva-wayland2 libva-x11-2 libvdpau1 \
    && rm -rf /var/lib/apt/lists/*
DOCKER
)
```

### 启动程序

从解压后的 `BluraySubtitle/` 目录的上一级执行下面的 Bash 命令，将 `media` 改为片源目录。宿主显示需要在 `/tmp/.X11-unix` 中有对应的 X11 套接字，并提供可读取的 `xauth` 认证记录。

```bash
(
set -euo pipefail
pkg=$(realpath ./BluraySubtitle)
media=/path/to/media
output="$HOME/Videos/BluraySubtitle"
config="$HOME/.local/share/bluraysubtitle-docker"

mkdir -p "$config" "$output"
display="$DISPLAY"
number="${display##*:}"
socket="/tmp/.X11-unix/X${number%%.*}"
auth=$(mktemp)
trap 'rm -f -- "$auth"' EXIT

test -S "$socket"
xauth nlist "$display" | sed 's/^..../ffff/' | xauth -f "$auth" nmerge -
test -s "$auth"

docker run --rm --init --network none \
  --user "$(id -u):$(id -g)" \
  --tmpfs "/run/bluraysubtitle:uid=$(id -u),gid=$(id -g),mode=0700" \
  -e DISPLAY="$display" -e XAUTHORITY=/tmp/bluray.Xauthority \
  -e QT_QPA_PLATFORM=xcb -e QT_X11_NO_MITSHM=1 \
  -e XDG_RUNTIME_DIR=/run/bluraysubtitle \
  -e BLURAY_SUBTITLE_CONFIG_DIR=/config -e XDG_CONFIG_HOME=/config \
  -e XDG_CACHE_HOME=/config/.cache -e LIBGL_ALWAYS_SOFTWARE=1 \
  --mount "type=bind,src=$socket,dst=$socket,readonly" \
  --mount "type=bind,src=$auth,dst=/tmp/bluray.Xauthority,readonly" \
  --mount "type=bind,src=$pkg,dst=/opt/BluraySubtitle,readonly" \
  --mount "type=bind,src=$config,dst=/config" \
  --mount "type=bind,src=$media,dst=/data,readonly" \
  --mount "type=bind,src=$output,dst=/output" \
  --workdir /config --entrypoint /opt/BluraySubtitle/BluraySubtitle \
  bluraysubtitle-runtime:26.04 --foreground
)
```

在 `/data` 下选择片源，将输出路径设为 `/output`。宿主的配置目录会保存含工具路径的 `config.json`、脚本及已保存的日志。示例使用软件渲染和隔离网络。更新时在宿主机解压新版，再让 `pkg` 指向新目录。 [Docker 绑定挂载](https://docs.docker.com/engine/storage/bind-mounts/)

### 使用独立显示窗口

如果宿主显示在 `/tmp/.X11-unix` 下没有文件套接字，或需要单独的显示窗口，可以使用 [Xephyr](https://manpages.ubuntu.com/manpages/resolute/man1/Xephyr.1.html)。在宿主机安装 `xserver-xephyr` 和 `xauth`，将上一段启动命令保存为 `run-bluraysubtitle.sh`，再使用 `:93` 等空闲显示编号。

```bash
(
set -e
display=:93
socket=/tmp/.X11-unix/X93
test ! -S "$socket"
auth=$(mktemp)
trap 'rm -f -- "$auth"' EXIT
xauth -f "$auth" add "$display" MIT-MAGIC-COOKIE-1 "$(mcookie)"
Xephyr "$display" -screen 1440x1000 -resizeable -nolisten tcp \
  -extension MIT-SHM -auth "$auth" &
display_pid=$!
trap 'kill "$display_pid" 2>/dev/null || true; rm -f -- "$auth"' EXIT
for _ in {1..30}; do
  [ -S "$socket" ] && break
  sleep 0.1
done
test -S "$socket"
DISPLAY="$display" XAUTHORITY="$auth" bash /path/to/run-bluraysubtitle.sh
)
```
