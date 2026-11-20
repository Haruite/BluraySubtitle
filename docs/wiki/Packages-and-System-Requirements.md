# Packages and system requirements

English | [简体中文](Packages-and-System-Requirements.zh-Hans.md)

## Choose a download

Choose one archive for the operating system and processor that will run the application. [Latest build directory](https://sbx.mysmy.top/tools/BluraySubtitle/) · [Tagged releases](https://github.com/Haruite/BluraySubtitle/releases)

| File | Operating system | Processor requirements |
| --- | --- | --- |
| `BluraySubtitle_windows_x64.7z` | Windows 10 x64 (required APIs available from 1709) or Windows 11 x64 | Intel or AMD x64. The AVX2 build of the zsmooth filter requires AVX2. |
| `BluraySubtitle_windows_arm64.7z` | Windows 10 ARM64 (1903 or later for the bundled tools) or Windows 11 ARM64 | 64-bit Arm processor. Native VapourSynth R79 filters use NEON. |
| `BluraySubtitle_linux_x64.tar.xz` | 64-bit x86 Linux (x86-64), tested down to kernel 3.17 | Full x86-64-v3 support, as on Intel Core Haswell or AMD Zen. Above x86-64-v2 this requires AVX, AVX2, BMI1/2, F16C, FMA, LZCNT, MOVBE and OSXSAVE with AVX state enabled by the OS. |
| `BluraySubtitle_linux_arm64.tar.xz` | 64-bit AArch64 Linux, tested down to kernel 3.17 | Armv8-A with floating point and NEON. Cortex-A53 is the tested baseline. |

Each archive in the download directory has a matching `<archive-name>.txt` containing the SHA-256, Git commit and commit time. Use it to verify the download and identify the build.

Extract the entire archive. On Windows, run `BluraySubtitle_windows_x64.exe` or `BluraySubtitle_windows_arm64.exe`. On Linux, extract with `tar -xJf <archive-name>`, enter `BluraySubtitle/` and run `./BluraySubtitle` as your normal user. Keep `_internal/` beside the launcher. To switch from an earlier Ubuntu-named package, download the matching Linux archive manually once.

## Windows runtime

Build `13592ef` uses Qt 6.12.0 and CPython 3.15.2. On both architectures, the desktop plugin `qwindows.dll` imports `UiaRaiseNotificationEvent` from `UIAutomationCore.dll` at load time. Microsoft added this entry point in Windows 10 version 1709 (build 16299). Qt 6.12 officially supports Windows 10 x64 from 1809 and lists Windows on ARM without specifying a Windows 10 release. [Microsoft API reference](https://learn.microsoft.com/en-us/windows/win32/api/uiautomationcoreapi/nf-uiautomationcoreapi-uiaraisenotificationevent) · [Qt supported platforms](https://doc.qt.io/qt-6.12/windows.html)

The ARM64 `ffmpeg.exe` and `ffprobe.exe` also import `capCreateCaptureWindowA` and `capGetDriverDescriptionA` from native `avicap32.dll` at startup. Windows 10 Pro ARM64 images for 1709, 1803 and 1809 contain only the x86 copy. Version 1903 (build 18362) is the first with an ARM64 copy in `System32` that exports both functions. FFprobe needs this DLL even to read information from a file. [Microsoft video capture API reference](https://learn.microsoft.com/en-us/windows/win32/api/vfw/nf-vfw-capcreatecapturewindowa)

## Linux runtime

The package includes Python, glibc, Qt, graphics client libraries and media tools. It also runs on Alpine with musl and on NixOS. The GUI supports X11, XWayland and WSLg. Hardware acceleration uses the host graphics driver. RIFE interpolation needs a working Vulkan device. For a headless startup check, run `QT_QPA_PLATFORM=offscreen ./BluraySubtitle --foreground`.

On Linux 3.17.0, both architectures launched the main window and VSEdit with Qt 6.6, encoded 10-bit HEVC and muxed Chinese subtitles. ARM64 tests covered 64 KiB pages on Linux 3.17 and 4 KiB pages on Ubuntu 26.04. The main window selects the current bundled Qt when the kernel meets its requirements.

The following x64 distributions have been tested. Run the corresponding package-manager commands with administrator privileges only when extraction tools or Chinese fonts are missing.

| Tested x64 system | To extract the archive | For Chinese text |
| --- | --- | --- |
| Ubuntu 22.04, 24.04, 26.04 | `apt install xz-utils` | `apt install fontconfig fonts-noto-cjk` |
| Debian 12, 13 | `apt install xz-utils` | `apt install fontconfig fonts-noto-cjk` |
| Rocky Linux 9.9 | `dnf install xz` | `dnf install fontconfig google-noto-sans-cjk-ttc-fonts` |
| Fedora 45 | `dnf install xz` | `dnf install fontconfig google-noto-sans-cjk-fonts` |
| openSUSE Tumbleweed | Included | `zypper install fontconfig google-noto-sans-cjk-fonts` |
| Arch Linux | Included | `pacman -Syu --needed fontconfig noto-fonts-cjk` |
| Alpine 3.24 | Included in BusyBox | `apk add fontconfig font-noto-cjk` |
| NixOS 26.05 | Included | Add `pkgs.noto-fonts-cjk-sans` to `fonts.packages` in the NixOS configuration. |

## Source setup scripts

**Windows.** `setup_windows_environment.ps1` supports x64 Windows 10 version 1909 or later, x64 Windows Server 2019 or later with Desktop Experience, and ARM64 Windows 11 or later. Use 64-bit PowerShell. The default is VapourSynth R79. Select Classic with `-VapourSynthRuntime Classic`. On ARM64, Classic uses a separate x64 Python, x64 plugins and x64 VSEdit.

**Linux.** `setup_linux_environment.sh` supports native x64 or ARM64 Ubuntu, Debian and their APT derivatives. It checks installed packages and the candidates in the configured repositories, including backports. Interim and rolling releases use the same checks.

| Dependency | Source setup requirement |
| --- | --- |
| FFmpeg development libraries | FFmpeg 7 or later, with `libavcodec` major version 61 or later |
| Vulkan and libplacebo | Vulkan headers 1.3.277 or later and Vulkan-enabled libplacebo 6.338 or later |
| Other build tools and libraries | dav1d 1.0 or later, Meson 1.4 or later and Docutils 0.20 or later |
| Qt and Python | Desktop setup requires Qt development files 6.4 or later. uv installs the latest stable CPython 3. The current PyQt6 wheels require glibc 2.34 or later on x64 and 2.39 or later on ARM64. |

On x64, setup installs the upstream zsmooth and RIFE binaries for x86-64-v3 processors. Headless installations also include RIFE and its model.

### Linux setup dependency checks

| x64 environments checked | Setup prerequisites |
| --- | --- |
| Ubuntu 26.04 LTS and 26.10, Debian 13, LMDE 7, Devuan 6, antiX 26.1, Kali Rolling | Passed with the installed packages or configured repositories. |
| Ubuntu 24.10, 25.04 and 25.10 | The signed release indexes contain the required versions. These interim releases have reached end of support. |
| Stock Ubuntu 22.04 and 24.04, Debian 12, Mint 22.3, Pop!_OS 24.04, KDE neon on the 24.04 base, antiX 23.2 and the Kali 2022.4 snapshot | The repositories checked lack one or more required versions. Setup lists the missing packages. |

The Ubuntu 26.04 x64 and ARM64 builds passed archive verification. To build the package for the native architecture, run the following from the repository root.

```bash
bash setup_linux_environment.sh --mode Build
bash tools/build_linux_package.sh
```

## Run the Linux package in Docker

On a Linux desktop, extract the Linux archive for the host architecture. Keep the executable and `_internal/` together in the extracted `BluraySubtitle/` directory. The application and its multimedia tools run from the mounted package.

### Prepare the runtime

The build command selects `linux/amd64` on x64 hosts and `linux/arm64` on ARM64 hosts. The image contains the system graphics libraries and fonts. An existing Ubuntu 26.04 image with these libraries can serve as the runtime.

```bash
(
cpu_arch=$(uname -m)
case "$cpu_arch" in
  x86_64|amd64) docker_platform=linux/amd64 ;;
  aarch64|arm64) docker_platform=linux/arm64 ;;
  *) printf 'Unsupported CPU architecture %s\n' "$cpu_arch" >&2; exit 1 ;;
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

### Open the application

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

Select media under `/data` and set output paths under `/output`. The host configuration directory retains scripts, saved logs, and `config.json` with the tool paths. The example uses software rendering and an isolated network. To update the mounted package, extract the new version on the host and point `pkg` to that directory. [Docker bind mounts](https://docs.docker.com/engine/storage/bind-mounts/)

### Use a separate display

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
