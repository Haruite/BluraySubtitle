# 在 Docker 中运行 Ubuntu 打包版

[English](Run-Ubuntu-Package-in-Docker.md) | 简体中文

在 Linux 桌面解压 `BluraySubtitle_ubuntu26.04_x64.tar.xz`，将可执行文件与 `_internal/` 放在解压所得的同一个 `BluraySubtitle/` 目录中。容器使用 Ubuntu 26.04 amd64 运行环境，程序和多媒体工具直接从挂载的包中启动。

## 准备运行环境

下面的镜像包含系统图形库和字体。已有这些依赖的 Ubuntu 26.04 镜像也可用作运行环境。

```bash
docker build --platform linux/amd64 -t bluraysubtitle-runtime:26.04 - <<'DOCKER'
FROM ubuntu:26.04
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    ca-certificates fontconfig fonts-noto-cjk x11-utils \
    libegl1 libegl-mesa0 libgl1 libglx-mesa0 libgl1-mesa-dri libopengl0 \
    libvulkan1 mesa-vulkan-drivers libva2 libva-drm2 libva-wayland2 libva-x11-2 libvdpau1 \
    && rm -rf /var/lib/apt/lists/*
DOCKER
```

## 启动程序

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

docker run --rm --init --platform linux/amd64 --network none \
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

在 `/data` 下选择片源，将输出路径设为 `/output`。宿主的配置目录会保存 `config.json`、可编辑的工具设置、脚本及已保存的日志。示例使用软件渲染和隔离网络。更新时在宿主机解压新版，再让 `pkg` 指向新目录。 [Docker 绑定挂载](https://docs.docker.com/engine/storage/bind-mounts/)

## 使用独立显示窗口

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
