# Run the Ubuntu Package in Docker

English | [简体中文](Run-Ubuntu-Package-in-Docker.zh-Hans.md)

Extract `BluraySubtitle_ubuntu26.04_x64.tar.xz` on a Linux desktop. Keep the executable and `_internal/` together in the extracted `BluraySubtitle/` directory. Use an amd64 Ubuntu 26.04 container as the runtime. The application and its multimedia tools run from the mounted package.

## Prepare the runtime

This image contains the system graphics libraries and fonts. An existing Ubuntu 26.04 image with these libraries can serve as the runtime.

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

## Open the application

Run the following Bash block from the directory containing the extracted `BluraySubtitle/` folder. Set `media` to the source directory. The host display needs an X11 socket under `/tmp/.X11-unix` and a readable `xauth` entry.

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

Select media under `/data` and set output paths under `/output`. The host configuration directory retains `config.json`, editable tool settings, scripts and saved logs. The example uses software rendering and an isolated network. To update the mounted package, extract the new version on the host and point `pkg` to that directory. [Docker bind mounts](https://docs.docker.com/engine/storage/bind-mounts/)

## Use a separate display

If the host display has no file socket under `/tmp/.X11-unix`, or you want a separate window, use [Xephyr](https://manpages.ubuntu.com/manpages/resolute/man1/Xephyr.1.html). Install `xserver-xephyr` and `xauth` on the host. Save the preceding launch block as `run-bluraysubtitle.sh`, then use a free display number such as `:93`.

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
