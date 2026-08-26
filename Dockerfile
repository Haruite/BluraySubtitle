# syntax=docker/dockerfile:1.6
FROM ubuntu:26.04

ENV DEBIAN_FRONTEND=noninteractive
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8
ENV PATH=/root/.local/bin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates wget \
    && install -d -m 0755 /etc/apt/keyrings \
    && wget -q -O /etc/apt/keyrings/gpg-pub-moritzbunkus.gpg https://mkvtoolnix.download/gpg-pub-moritzbunkus.gpg \
    && printf 'deb [arch=%s signed-by=/etc/apt/keyrings/gpg-pub-moritzbunkus.gpg] https://mkvtoolnix.download/ubuntu/ resolute main\n' "$(dpkg --print-architecture)" > /etc/apt/sources.list.d/mkvtoolnix.download.list \
    && rm -rf /var/lib/apt/lists/*

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl git wget unzip xz-utils tar sed pkg-config \
    build-essential cmake ninja-build autoconf automake libtool \
    python3 python3-pip python3-venv python3-dev python3-sphinx \
    fonts-wqy-microhei flac gedit nautilus mkvtoolnix mkvtoolnix-gui pipewire-bin \
    libegl1 libopengl0 libglib2.0-0 libxkbcommon0 libdbus-1-3 \
    libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 libxcb-shape0 \
    libxcb-xinerama0 libxcb-xinput0 libxcb-render-util0 \
    libunwind8 libunwind-dev xdg-utils libgl1-mesa-dri libglx-mesa0 mesa-vulkan-drivers \
    yasm nasm glslang-tools glslang-dev wayland-protocols yt-dlp \
    libass-dev libfribidi-dev libfreetype-dev libfontconfig1-dev libharfbuzz-dev libuchardet-dev \
    libgl1-mesa-dev libvdpau-dev libva-dev libx11-dev libxext-dev libxv-dev libxinerama-dev \
    libwayland-dev libxkbcommon-dev libegl1-mesa-dev libplacebo-dev libspirv-cross-c-shared-dev libshaderc-dev \
    libasound2-dev libpulse-dev libjack-dev libpipewire-0.3-dev libluajit-5.1-dev \
    libdav1d-dev libdovi-dev \
    libavcodec-dev libavformat-dev libavutil-dev libswscale-dev libswresample-dev libavfilter-dev \
    libmujs-dev libbluray-dev libxrandr-dev libxpresent-dev libxss-dev libdvdnav-dev libdvdread-dev \
    libzimg-dev libarchive-dev librubberband-dev libsdl2-dev libdrm-dev libgbm-dev \
    libssl-dev libjpeg-dev zlib1g-dev libogg-dev libopus-dev libtool-bin gettext \
    libmagick++-dev libtesseract-dev cython3 \
    qt6-base-dev qt6-base-dev-tools qt6-5compat-dev qt6-websockets-dev qt6-declarative-dev qt6-multimedia-dev libqt6svg6-dev libgl-dev \
    libxxhash-dev libfftw3-dev p7zip-full \
    && rm -rf /var/lib/apt/lists/*

ARG MKVTOOLNIX_VERSION
RUN set -eux; \
    TARGET_MKVTOOLNIX_VERSION="${MKVTOOLNIX_VERSION:-$(curl -fsSL https://mkvtoolnix.download/latest-release.xml | python3 -c 'import sys, xml.etree.ElementTree as ET; print(ET.parse(sys.stdin).findtext("./latest-source/version") or "")')}"; \
    INSTALLED_MKVTOOLNIX_VERSION="$(mkvmerge --version | grep -oE 'v[0-9]+([.][0-9]+)+' | head -n 1 | tr -d 'v')"; \
    test -n "$TARGET_MKVTOOLNIX_VERSION"; \
    test -n "$INSTALLED_MKVTOOLNIX_VERSION"; \
    if dpkg --compare-versions "$INSTALLED_MKVTOOLNIX_VERSION" lt "$TARGET_MKVTOOLNIX_VERSION"; then \
      apt-get update; \
      AVAILABLE_MKVTOOLNIX_VERSION="$(apt-cache policy mkvtoolnix | awk '$1 == "Candidate:" { print $2; exit }' | sed 's/-.*//')"; \
      test -n "$AVAILABLE_MKVTOOLNIX_VERSION"; \
      if dpkg --compare-versions "$AVAILABLE_MKVTOOLNIX_VERSION" ge "$TARGET_MKVTOOLNIX_VERSION"; then \
        apt-get install -y --no-install-recommends --only-upgrade mkvtoolnix mkvtoolnix-gui; \
      fi; \
    fi; \
    rm -rf /var/lib/apt/lists/*

RUN set -eux; \
    DOVI_HEADER=/usr/include/libdovi/rpu_parser.h; \
    if ! grep -qF 'void dovi_rpu_free(' "$DOVI_HEADER" \
        || ! grep -qF 'void dovi_rpu_free_header(' "$DOVI_HEADER"; then \
      DOVI_PACKAGE_VERSION="$(dpkg-query -W -f='${Version}' libdovi-dev)"; \
      case "$DOVI_PACKAGE_VERSION" in 3.3.2-3*) ;; *) exit 1 ;; esac; \
      DOVI_ARCH="$(dpkg --print-architecture)"; \
      case "$DOVI_ARCH" in \
        amd64) DOVI_HEADER_SHA256=517d9a81e904d0b337e04b4f9fef0c4a1939fddc49237612547fd8ae033f3ad1 ;; \
        arm64) DOVI_HEADER_SHA256=27c6b2a66ab2de4ddd2f5b87ecb0826cb504f7218fc1cf73a649fdbc4b2c760b ;; \
        *) exit 1 ;; \
      esac; \
      DOVI_REPAIR_VERSION=3.3.2-3+b1; \
      DOVI_REPAIR_PACKAGE=/tmp/libdovi-dev.deb; \
      wget -nv -O "$DOVI_REPAIR_PACKAGE" \
        "https://deb.debian.org/debian/pool/main/r/rust-dolby-vision/libdovi-dev_${DOVI_REPAIR_VERSION}_${DOVI_ARCH}.deb"; \
      printf '%s  %s\n' "$DOVI_HEADER_SHA256" "$DOVI_REPAIR_PACKAGE" | sha256sum -c -; \
      mkdir -p /tmp/libdovi-dev-fixed; \
      dpkg-deb -x "$DOVI_REPAIR_PACKAGE" /tmp/libdovi-dev-fixed; \
      install -m 0644 /tmp/libdovi-dev-fixed/usr/include/libdovi/rpu_parser.h "$DOVI_HEADER"; \
      rm -f "$DOVI_REPAIR_PACKAGE"; \
      rm -rf /tmp/libdovi-dev-fixed; \
    fi; \
    grep -qF 'void dovi_rpu_free(' "$DOVI_HEADER"; \
    grep -qF 'void dovi_rpu_free_header(' "$DOVI_HEADER"

RUN fc-cache -f >/dev/null 2>&1 || true

RUN set -eux; \
    ensure_meson_version() { \
      python3 -m pip install --break-system-packages --upgrade meson || python3 -m pip install --upgrade meson; \
      meson --version; \
    }; \
    ensure_meson_version; \
    python3 -m pip install --break-system-packages --upgrade cython || python3 -m pip install --upgrade cython

RUN set -eux; \
    DOVI_VER="$(git ls-remote --refs --tags --sort=-version:refname https://github.com/quietvoid/dovi_tool.git | awk -F 'refs/tags/' 'NF == 2 && $2 ~ /^[vV]?[0-9]+([.][0-9]+)+$/ { print $2; exit }')"; \
    test -n "$DOVI_VER"; \
    case "$(uname -m)" in \
      x86_64|amd64) DOVI_ARCH=x86_64 ;; \
      aarch64|arm64) DOVI_ARCH=aarch64 ;; \
      *) echo "unsupported arch for dovi_tool: $(uname -m)" >&2; exit 1 ;; \
    esac; \
    mkdir -p /tmp/dovi && cd /tmp/dovi; \
    wget -nv "https://github.com/quietvoid/dovi_tool/releases/download/${DOVI_VER}/dovi_tool-${DOVI_VER}-${DOVI_ARCH}-unknown-linux-musl.tar.gz"; \
    tar zxf "dovi_tool-${DOVI_VER}-${DOVI_ARCH}-unknown-linux-musl.tar.gz"; \
    install -m 0755 dovi_tool /usr/bin/dovi_tool; \
    rm -rf /tmp/dovi

RUN set -eux; \
    TRUEHDD_VER="$(curl -fsSL https://api.github.com/repos/truehdd/truehdd/releases/latest | python3 -c 'import json, sys; print(json.load(sys.stdin)["tag_name"])')"; \
    test -n "$TRUEHDD_VER"; \
    case "$(uname -m)" in \
      x86_64|amd64) TRUEHDD_ARCH=x86_64 ;; \
      aarch64|arm64) TRUEHDD_ARCH=aarch64 ;; \
      *) echo "unsupported arch for truehdd: $(uname -m)" >&2; exit 1 ;; \
    esac; \
    mkdir -p /tmp/truehdd_bin && cd /tmp/truehdd_bin; \
    wget -nv "https://github.com/truehdd/truehdd/releases/download/${TRUEHDD_VER}/truehdd-${TRUEHDD_VER}-${TRUEHDD_ARCH}-unknown-linux-gnu.tar.gz"; \
    tar zxf "truehdd-${TRUEHDD_VER}-${TRUEHDD_ARCH}-unknown-linux-gnu.tar.gz"; \
    install -m 0755 truehdd /usr/bin/truehdd; \
    rm -rf /tmp/truehdd_bin

ARG FFMPEG_TAG
RUN set -eux; \
    FFMPEG_TAG="${FFMPEG_TAG:-$(git ls-remote --refs --tags --sort=-version:refname https://github.com/FFmpeg/FFmpeg.git | awk -F 'refs/tags/' 'NF == 2 && $2 ~ /^[nN]?[0-9]+([.][0-9]+)+$/ { print $2; exit }')}"; \
    test -n "$FFMPEG_TAG"; \
    mkdir -p /tmp/mpv && cd /tmp/mpv; \
    git clone https://github.com/mpv-player/mpv-build.git; \
    cd mpv-build; \
    rm -rf mpv/build ffmpeg/build libass/build || true; \
    ./use-ffmpeg-release; \
    echo "--enable-libbluray" > ffmpeg_options; \
    echo "--enable-libdav1d" >> ffmpeg_options; \
    echo "--enable-libopus" >> ffmpeg_options; \
    echo "-Dlibbluray=enabled" > mpv_options; \
    echo "-Dlua=luajit" >> mpv_options; \
    ./rebuild -j"$(nproc)"; \
    ./install; \
    install -m 0755 build_libs/bin/ffmpeg /usr/bin/ffmpeg; \
    install -m 0755 build_libs/bin/ffprobe /usr/bin/ffprobe; \
    /usr/bin/ffmpeg -version >/dev/null; \
    /usr/bin/ffprobe -version >/dev/null; \
    /usr/bin/ffmpeg -hide_banner -h encoder=libopus 2>&1 | grep '^Encoder libopus' >/dev/null; \
    ldconfig; \
    rm -rf /tmp/mpv

RUN set -eux; \
    LSMASH_TAG="$(git ls-remote --refs --tags --sort=-version:refname https://github.com/l-smash/l-smash.git | awk -F 'refs/tags/' 'NF == 2 && $2 ~ /^[vV]?[0-9]+([.][0-9]+)+$/ { print $2; exit }')"; \
    test -n "$LSMASH_TAG"; \
    mkdir -p /tmp/lsmash && cd /tmp/lsmash; \
    git clone --depth 1 --branch "$LSMASH_TAG" https://github.com/l-smash/l-smash.git l-smash; \
    cd l-smash; \
    ./configure --enable-shared; \
    make -j"$(nproc)"; \
    make install; \
    ldconfig; \
    rm -rf /tmp/lsmash

ARG X265_TAG
RUN bash <<'X265EOS'
set -euo pipefail
repo=https://github.com/Multicorewareinc/x265.git
tag="${X265_TAG:-$(git ls-remote --refs --tags --sort=-version:refname "$repo" | awk -F 'refs/tags/' 'NF == 2 && $2 ~ /^[0-9]+([.][0-9]+)+$/ { print $2; exit }')}"
test -n "$tag"
mkdir -p /tmp/x265
cd /tmp/x265
git clone --depth 1 --branch "$tag" "$repo" x265
source_root=/tmp/x265/x265/source
json11_source="$source_root/dynamicHDR10/json11/json11.cpp"
if ! grep -Fxq '#include <cstdint>' "$json11_source"; then
    grep -Fxq '#include <limits>' "$json11_source"
    sed -i '/^#include <limits>$/a #include <cstdint>' "$json11_source"
fi
grep -Fxq '#include <cstdint>' "$json11_source"
build_root=/tmp/x265/build
jobs="$(nproc)"
common_args=(
    -DCMAKE_POLICY_VERSION_MINIMUM=3.10
    -DCMAKE_BUILD_TYPE=Release
    -DENABLE_SHARED=OFF
    -DENABLE_LIBNUMA=OFF
    -DENABLE_LSMASH=OFF
    -DENABLE_LAVF=OFF
    -DENABLE_AVISYNTH=OFF
    -DENABLE_VPYSYNTH=OFF
)
cmake -S "$source_root" -B "$build_root/12bit" "${common_args[@]}" \
    -DHIGH_BIT_DEPTH=ON \
    -DMAIN12=ON \
    -DEXPORT_C_API=OFF \
    -DENABLE_HDR10_PLUS=ON \
    -DENABLE_CLI=OFF
cmake --build "$build_root/12bit" --parallel "$jobs"
cmake -S "$source_root" -B "$build_root/10bit" "${common_args[@]}" \
    -DHIGH_BIT_DEPTH=ON \
    -DMAIN12=OFF \
    -DEXPORT_C_API=OFF \
    -DENABLE_HDR10_PLUS=ON \
    -DENABLE_CLI=OFF
cmake --build "$build_root/10bit" --parallel "$jobs"
mkdir -p "$build_root/8bit"
ln -s ../10bit/libx265.a "$build_root/8bit/libx265_main10.a"
ln -s ../12bit/libx265.a "$build_root/8bit/libx265_main12.a"
cmake -S "$source_root" -B "$build_root/8bit" "${common_args[@]}" \
    "-DCMAKE_EXE_LINKER_FLAGS=-static-libgcc -static-libstdc++" \
    '-DEXTRA_LIB=x265_main10.a;x265_main12.a' \
    -DEXTRA_LINK_FLAGS=-L. \
    -DLINKED_10BIT=ON \
    -DLINKED_12BIT=ON \
    -DENABLE_HDR10_PLUS=ON \
    -DENABLE_CLI=ON
cmake --build "$build_root/8bit" --parallel "$jobs"
install -m 0755 "$build_root/8bit/x265" /usr/bin/x265
/usr/bin/x265 --version 2>&1 | grep -F "encoder version $tag" >/dev/null
/usr/bin/x265 --version 2>&1 | grep -F '8bit+10bit+12bit' >/dev/null
x265_help="$(/usr/bin/x265 --help 2>&1 || true)"
[[ "$x265_help" == *"--dhdr10-info"* ]]
[[ "$x265_help" == *"--dolby-vision-profile"* ]]
[[ "$x265_help" == *"--dolby-vision-rpu"* ]]
rm -rf /tmp/x265
X265EOS

ARG SVT_AV1_TAG
RUN bash <<'SVTAV1EOS'
set -euo pipefail
mkdir -p /tmp/svtav1
cd /tmp/svtav1
SVT_TAG="${SVT_AV1_TAG:-$(git ls-remote --refs --tags --sort=-version:refname https://gitlab.com/AOMediaCodec/SVT-AV1.git | awk -F 'refs/tags/' 'NF == 2 && $2 ~ /^[vV]?[0-9]+([.][0-9]+)+$/ { print $2; exit }')}"
test -n "$SVT_TAG"
git clone --depth 1 --branch "$SVT_TAG" https://gitlab.com/AOMediaCodec/SVT-AV1.git
svt_root=/tmp/svtav1/SVT-AV1
test -f "$svt_root/Source/Lib/Globals/enc_settings.c"

case ${MAKEFLAGS-} in
'')
	_j="$(nproc 2>/dev/null || getconf _NPROCESSORS_ONLN 2>/dev/null || echo 4)"
	case "$_j" in ''|*[!0-9]*) _j=4 ;; esac
	export MAKEFLAGS="-j${_j}"
	;;
esac
command -v python3 >/dev/null 2>&1 || exit 1
svt_patched=0
if python3 - "$svt_root" <<'SVTAV1PATCH'
import sys
from pathlib import Path

root = Path(sys.argv[1])

APPLY = [
    (
        Path("Source/Lib/Globals/enc_settings.c"),
        """    if ((config->encoder_bit_depth != 8) && (config->encoder_bit_depth != 10)) {
        SVT_ERROR("Encoder Bit Depth shall be only 8 or 10 \\n");
        return_error = EB_ErrorBadParameter;
    }
    // Check if the EncoderBitDepth is conformant with the Profile constraint""",
        """#if CONFIG_ENABLE_HIGH_BIT_DEPTH
    if (config->encoder_bit_depth != 8 && config->encoder_bit_depth != 10 &&
        config->encoder_bit_depth != EB_TWELVE_BIT) {
        SVT_ERROR("Encoder Bit Depth shall be only 8, 10, or 12\\n");
        return_error = EB_ErrorBadParameter;
    }
    if (config->encoder_bit_depth == EB_TWELVE_BIT && config->profile != PROFESSIONAL_PROFILE) {
        SVT_ERROR("12-bit encoding requires Professional profile (seq_profile / --profile 2)\\n");
        return_error = EB_ErrorBadParameter;
    }
#else
    if ((config->encoder_bit_depth != 8) && (config->encoder_bit_depth != 10)) {
        SVT_ERROR("Encoder Bit Depth shall be only 8 or 10 \\n");
        return_error = EB_ErrorBadParameter;
    }
#endif
    // Check if the EncoderBitDepth is conformant with the Profile constraint""",
    ),
    (
        Path("Source/App/app_config.c"),
        """#define INPUT_DEPTH_TOKEN "--input-depth"
#define KEYINT_TOKEN "--keyint\"""",
        """#define INPUT_DEPTH_TOKEN "--input-depth"
#if CONFIG_ENABLE_HIGH_BIT_DEPTH
#define INPUT_DEPTH_HELP \\
    "Input video file and output bitstream bit-depth, default is 8 [8, 10, 12]. 12-bit requires " \\
    "`--profile 2` (Professional)"
#else
#define INPUT_DEPTH_HELP "Input video file and output bitstream bit-depth, default is 8 [8, 10]"
#endif
#define KEYINT_TOKEN "--keyint\"""",
    ),
    (
        Path("Source/App/app_config.c"),
        """    {INPUT_DEPTH_TOKEN, "Input video file and output bitstream bit-depth, default is 8 [8, 10]"},""",
        """    {INPUT_DEPTH_TOKEN, INPUT_DEPTH_HELP},""",
    ),
    (
        Path("Source/App/app_config.c"),
        """    frame_size = frame_size << ((app_cfg->config.encoder_bit_depth == 10) ? 1 : 0);""",
        """    frame_size = frame_size << ((app_cfg->config.encoder_bit_depth > 8) ? 1 : 0);""",
    ),
    (
        Path("Source/App/app_main.c"),
        """        double max_pix_value  = (cfg->encoder_bit_depth == 8) ? 255 : 1023;""",
        """        double max_pix_value = (double)((1u << cfg->encoder_bit_depth) - 1);""",
    ),
    (
        Path("Source/App/app_process_cmd.c"),
        """    double   max_pix_value = (app_cfg->config.encoder_bit_depth == 8) ? 255 : 1023;""",
        """    double max_pix_value = (double)((1u << app_cfg->config.encoder_bit_depth) - 1);""",
    ),
    (
        Path("Source/Lib/Codec/entropy_coding.c"),
        """    if (scs->static_config.profile == PROFESSIONAL_PROFILE && scs->static_config.encoder_bit_depth != EB_EIGHT_BIT) {
        SVT_ERROR("Profile 2 Not supported\\n");
        svt_aom_wb_write_bit(wb, scs->static_config.encoder_bit_depth == EB_TEN_BIT ? 0 : 1);
    }""",
        """    if (scs->static_config.profile == PROFESSIONAL_PROFILE && scs->static_config.encoder_bit_depth != EB_EIGHT_BIT) {
        svt_aom_wb_write_bit(wb, scs->static_config.encoder_bit_depth == EB_TEN_BIT ? 0 : 1);
    }""",
    ),
]


def run_apply():
    updated = {}
    for rel, old, new in APPLY:
        path = root / rel
        text = path.read_text(encoding="utf-8")
        if "12-bit encoding requires Professional profile" in text and rel.name == "enc_settings.c":
            continue
        if old not in text:
            if new in text:
                continue
            sys.exit(1)
        updated[path] = text.replace(old, new, 1)
    for path, text in updated.items():
        path.write_text(text, encoding="utf-8")



run_apply()
sys.exit(0)
SVTAV1PATCH
then
  svt_patched=1
fi

cd "$svt_root/Build/linux"
if ! ./build.sh release static; then
  test "$svt_patched" -eq 1
  rm -rf "$svt_root"
  cd /tmp/svtav1
  git clone --depth 1 --branch "$SVT_TAG" https://gitlab.com/AOMediaCodec/SVT-AV1.git
  cd "$svt_root/Build/linux"
  ./build.sh release static
fi

test -f "$svt_root/Bin/Release/SvtAv1EncApp"
cp "$svt_root/Bin/Release/SvtAv1EncApp" /usr/bin/SvtAv1EncApp
chmod +x /usr/bin/SvtAv1EncApp
rm -rf /tmp/svtav1
SVTAV1EOS

ARG FDK_AAC_TAG
ARG FDKAAC_TAG
RUN bash <<'FDKAAC'
set -euo pipefail
mkdir -p /tmp/fdk
cd /tmp/fdk
FDK_AAC_TAG="${FDK_AAC_TAG:-$(git ls-remote --refs --tags --sort=-version:refname https://github.com/mstorsjo/fdk-aac.git | awk -F 'refs/tags/' 'NF == 2 && $2 ~ /^[vV]?[0-9]+([.][0-9]+)+$/ { print $2; exit }')}"
FDKAAC_TAG="${FDKAAC_TAG:-$(git ls-remote --refs --tags --sort=-version:refname https://github.com/nu774/fdkaac.git | awk -F 'refs/tags/' 'NF == 2 && $2 ~ /^[vV]?[0-9]+([.][0-9]+)+$/ { print $2; exit }')}"
test -n "$FDK_AAC_TAG"
test -n "$FDKAAC_TAG"
git clone --depth 1 --branch "$FDK_AAC_TAG" https://github.com/mstorsjo/fdk-aac.git fdk-aac
cd fdk-aac
./autogen.sh
./configure --prefix=/usr/local
make -j"$(nproc)"
make install
ldconfig
cd /tmp/fdk
git clone --depth 1 --branch "$FDKAAC_TAG" https://github.com/nu774/fdkaac.git
cd fdkaac
autoreconf -fi
./configure --prefix=/usr/local
make -j"$(nproc)"
make install
ldconfig
rm -rf /tmp/fdk
FDKAAC

RUN bash <<'FLAC'
set -euo pipefail
FLAC_TAG="$(git ls-remote --refs --tags --sort=-version:refname https://github.com/xiph/flac.git | awk -F 'refs/tags/' 'NF == 2 && $2 ~ /^[vV]?[0-9]+([.][0-9]+)+$/ { print $2; exit }')"
test -n "$FLAC_TAG"
FLAC_VERSION="${FLAC_TAG#v}"
CURRENT_FLAC_VERSION="$(flac --version 2>/dev/null | grep -oE '[0-9]+[.][0-9]+[.][0-9]+' | head -n 1 || true)"
if [ -n "$CURRENT_FLAC_VERSION" ] && dpkg --compare-versions "$CURRENT_FLAC_VERSION" ge "$FLAC_VERSION"; then
  exit 0
fi
mkdir -p /tmp/flac
cd /tmp/flac
git clone --depth 1 --branch "$FLAC_TAG" https://github.com/xiph/flac.git flac
cd flac
./autogen.sh
./configure --enable-static --enable-shared --enable-64-bit-words
make -j"$(nproc)"
make install
install -m 0755 /usr/local/bin/flac /usr/bin/flac
ldconfig
rm -rf /tmp/flac
FLAC

RUN set -eux; \
    mkdir -p /tmp/vs && cd /tmp/vs; \
    wget -nv -O R57.A12.tar.gz https://github.com/AmusementClub/vapoursynth-classic/archive/refs/tags/R57.A12.tar.gz; \
    tar zxvf R57.A12.tar.gz; \
    cd vapoursynth-classic-R57.A12; \
    if [ -f src/filters/subtext/image.cpp ]; then sed -i 's/avcodec_close(\(.*\));/avcodec_free_context(\&\(\1\));/g' src/filters/subtext/image.cpp; fi; \
    ./autogen.sh; \
    ./configure --prefix=/usr/local CXXFLAGS="-O3 -fpermissive"; \
    make -j"$(nproc)"; \
    make install; \
    ldconfig; \
    PYV="$(python3 -c 'import sys; print("%d.%d" % (sys.version_info.major, sys.version_info.minor))')"; \
    mkdir -p /usr/lib/python3/dist-packages; \
    ln -sf "/usr/local/lib/python${PYV}/site-packages/vapoursynth.so" /usr/lib/python3/dist-packages/vapoursynth.so; \
    rm -rf /tmp/vs

RUN set -eux; \
    mkdir -p /tmp/descale && cd /tmp/descale; \
    git clone https://github.com/Irrational-Encoding-Wizardry/vapoursynth-descale.git; \
    cd vapoursynth-descale; \
    meson setup build --buildtype=release; \
    ninja -C build; \
    ninja -C build install; \
    ldconfig; \
    mkdir -p /app/plugins; \
    if [ -f /usr/local/lib/vapoursynth/libdescale.so ]; then cp /usr/local/lib/vapoursynth/libdescale.so /app/plugins/libdescale.so; \
    elif [ -f /usr/lib/vapoursynth/libdescale.so ]; then cp /usr/lib/vapoursynth/libdescale.so /app/plugins/libdescale.so; \
    else echo "libdescale.so not found after install" >&2; exit 1; fi; \
    rm -rf /tmp/descale

RUN set -eux; \
    mkdir -p /tmp/vsedit/vsedit_build && cd /tmp/vsedit/vsedit_build; \
    wget -nv -O R19-mod-6.10.tar.gz https://github.com/YomikoR/VapourSynth-Editor/archive/refs/tags/R19-mod-6.10.tar.gz; \
    tar -zxvf R19-mod-6.10.tar.gz --strip-components=1; \
    ldconfig; \
    cd pro; \
    export CPLUS_INCLUDE_PATH=/usr/local/include/vapoursynth; \
    export LIBRARY_PATH=/usr/local/lib; \
    export LD_LIBRARY_PATH=/usr/local/lib:/usr/lib:/lib; \
    qmake6 pro.pro CONFIG+=release; \
    make -j"$(nproc)" || make -j1; \
    BIN_PATH="$(find /tmp/vsedit/vsedit_build -name vsedit -type f -executable | head -n1)"; \
    test -n "${BIN_PATH}"; \
    cp "${BIN_PATH}" /usr/local/bin/vsedit-bin; \
    chmod +x /usr/local/bin/vsedit-bin; \
    PYV="$(python3 -c 'import sys; print("%d.%d" % (sys.version_info.major, sys.version_info.minor))')"; \
    printf '%s\n' '#!/bin/bash' "export VAPOURSYNTH_PYTHON_PATH=/usr/lib/python${PYV}" 'export LD_LIBRARY_PATH=/usr/local/lib:$LD_LIBRARY_PATH' 'export LD_PRELOAD=/usr/local/lib/libvapoursynth-script.so' 'exec /usr/local/bin/vsedit-bin "$@"' > /usr/local/bin/vsedit; \
    chmod +x /usr/local/bin/vsedit; \
    rm -rf /tmp/vsedit

RUN mkdir -p /app/plugins /tmp/vsplugins

RUN bash <<'LSMASH'
set -euo pipefail
export PATH=/root/.local/bin:$PATH
export PKG_CONFIG_PATH="/usr/local/lib/pkgconfig:/usr/local/lib/x86_64-linux-gnu/pkgconfig:/usr/local/share/pkgconfig:/root/.local/lib/x86_64-linux-gnu/pkgconfig:${PKG_CONFIG_PATH:-}"
cd /tmp/vsplugins
git clone https://github.com/HomeOfAviSynthPlusEvolution/L-SMASH-Works.git
cd L-SMASH-Works/VapourSynth
need_compat=false
if command -v pkg-config >/dev/null 2>&1 && pkg-config --exists libavcodec; then
  avcodec_ver="$(pkg-config --modversion libavcodec 2>/dev/null | head -n 1 || true)"
  avcodec_major="${avcodec_ver%%.*}"
  if [[ "$avcodec_major" =~ ^[0-9]+$ ]] && (( avcodec_major < 60 )); then
    need_compat=true
  fi
fi
if [[ "$need_compat" == "true" ]]; then
  git checkout . && git -c advice.detachedHead=false checkout -q 70e19fb
else
  git checkout . && git -c advice.detachedHead=false checkout -q ae51313
fi
python3 - <<'PY'
import re
from pathlib import Path

decode_path = Path("../common/decode.c")
data = decode_path.read_text(encoding="utf-8", errors="replace")
data = re.sub(r"^.*AV_PIX_FMT_D3D12\\n.*$", "", data, flags=re.MULTILINE)
data = re.sub(r"^#ifndef AV_PIX_FMT_D3D12\\n#define AV_PIX_FMT_D3D12 .*?\\n#endif\\n\\n?", "", data, flags=re.MULTILINE)

header_paths = [
    Path("/usr/include/x86_64-linux-gnu/libavutil/pixfmt.h"),
    Path("/usr/include/libavutil/pixfmt.h"),
    Path("/usr/local/include/libavutil/pixfmt.h"),
]
header_has_enum = False
for hp in header_paths:
    if hp.is_file():
        txt = hp.read_text(encoding="utf-8", errors="replace")
        if "AV_PIX_FMT_D3D12" in txt:
            header_has_enum = True
            break

if ("AV_PIX_FMT_D3D12" in data) and (not header_has_enum):
    shim = "\n".join([
        "#define AV_PIX_FMT_D3D12 AV_PIX_FMT_NONE",
        "",
    ])
    data = shim + data
decode_path.write_text(data, encoding="utf-8")

libav_path = Path("../common/libavsmash.c")
if libav_path.is_file():
    libav_data = libav_path.read_text(encoding="utf-8", errors="replace")
    v410_line = "        ELSE_IF_GET_CODEC_ID_FROM_CODEC_TYPE(AV_CODEC_ID_V410, QT_CODEC_TYPE_V410_VIDEO);\n"
    if v410_line in libav_data:
        libav_data = libav_data.replace(v410_line, "")
    libav_path.write_text(libav_data, encoding="utf-8")
PY
rm -rf build
meson setup build
ninja -C build
cp "$(find "$PWD" -maxdepth 3 -name libvslsmashsource.so -type f | head -n1)" /app/plugins/
LSMASH

RUN set -eux; \
    export PATH=/root/.local/bin:$PATH; \
    export PKG_CONFIG_PATH="/usr/local/lib/pkgconfig:/usr/local/lib/x86_64-linux-gnu/pkgconfig:/usr/local/share/pkgconfig:/root/.local/lib/x86_64-linux-gnu/pkgconfig:${PKG_CONFIG_PATH:-}"; \
    cd /tmp/vsplugins; \
    wget -nv -O r9.tar.gz https://github.com/HomeOfVapourSynthEvolution/VapourSynth-EEDI3/archive/refs/tags/r9.tar.gz; \
    tar zxvf r9.tar.gz; \
    cd VapourSynth-EEDI3-r9; \
    find . -type f -name EEDI3.cpp -exec sed -i 's/std::max_align_t/max_align_t/g' {} +; \
    python3 -c "import re; c=open('meson.build',encoding='utf-8',errors='replace').read(); c=re.sub(r'incdir = include_directories\\(.*?check: true,.*?\\.stdout\\(\\)\\.strip\\(\\),\\s*\\)','incdir = \\'/usr/local/include/vapoursynth\\'',c,flags=re.DOTALL); open('meson.build','w',encoding='utf-8').write(c)"; \
    meson setup build; ninja -C build; cp build/eedi3m.so /app/plugins/

RUN set -eux; \
    export PATH=/root/.local/bin:$PATH; \
    export PKG_CONFIG_PATH="/usr/local/lib/pkgconfig:/usr/local/lib/x86_64-linux-gnu/pkgconfig:/usr/local/share/pkgconfig:/root/.local/lib/x86_64-linux-gnu/pkgconfig:${PKG_CONFIG_PATH:-}"; \
    cd /tmp/vsplugins; \
    wget -nv -O r10.tar.gz https://github.com/HomeOfVapourSynthEvolution/VapourSynth-AddGrain/archive/refs/tags/r10.tar.gz; \
    tar zxvf r10.tar.gz; \
    cd VapourSynth-AddGrain-r10; \
    meson setup build; ninja -C build; \
    cp build/libaddgrain.so /app/plugins/

RUN set -eux; \
    export PATH=/root/.local/bin:$PATH; \
    export PKG_CONFIG_PATH="/usr/local/lib/pkgconfig:/usr/local/lib/x86_64-linux-gnu/pkgconfig:/usr/local/share/pkgconfig:/root/.local/lib/x86_64-linux-gnu/pkgconfig:${PKG_CONFIG_PATH:-}"; \
    cd /tmp/vsplugins; \
    git clone --depth 1 --branch 0.38.4 https://github.com/AmusementClub/assrender.git; \
    cd assrender; cmake -S . -B build -DCMAKE_BUILD_TYPE=Release; \
    cmake --build build --parallel "$(nproc)"; \
    cp "$(find "$PWD/build" -name libassrender.so -type f | head -n1)" /app/plugins/

RUN set -eux; \
    export PATH=/root/.local/bin:$PATH; \
    export PKG_CONFIG_PATH="/usr/local/lib/pkgconfig:/usr/local/lib/x86_64-linux-gnu/pkgconfig:/usr/local/share/pkgconfig:/root/.local/lib/x86_64-linux-gnu/pkgconfig:${PKG_CONFIG_PATH:-}"; \
    cd /tmp/vsplugins; \
    wget -nv -O r3.tar.gz https://github.com/HomeOfVapourSynthEvolution/VapourSynth-Bilateral/archive/refs/tags/r3.tar.gz; \
    tar zxvf r3.tar.gz; \
    cd VapourSynth-Bilateral-r3; \
    chmod +x configure; \
    ./configure; \
    make -j"$(nproc)"; \
    cp "$(find "$PWD" -maxdepth 3 -name libbilateral.so -type f | head -n1)" /app/plugins/

RUN set -eux; \
    export PATH=/root/.local/bin:$PATH; \
    export PKG_CONFIG_PATH="/usr/local/lib/pkgconfig:/usr/local/lib/x86_64-linux-gnu/pkgconfig:/usr/local/share/pkgconfig:/root/.local/lib/x86_64-linux-gnu/pkgconfig:${PKG_CONFIG_PATH:-}"; \
    cd /tmp/vsplugins; \
    wget -nv -O r7.tar.gz https://github.com/HomeOfVapourSynthEvolution/VapourSynth-DFTTest/archive/refs/tags/r7.tar.gz; \
    tar zxvf r7.tar.gz; \
    cd VapourSynth-DFTTest-r7; \
    meson setup build; ninja -C build; \
    cp build/libdfttest.so /app/plugins/

RUN set -eux; \
    export PATH=/root/.local/bin:$PATH; \
    export PKG_CONFIG_PATH="/usr/local/lib/pkgconfig:/usr/local/lib/x86_64-linux-gnu/pkgconfig:/usr/local/share/pkgconfig:/root/.local/lib/x86_64-linux-gnu/pkgconfig:${PKG_CONFIG_PATH:-}"; \
    cd /tmp/vsplugins; \
    wget -nv -O r7.1.tar.gz https://github.com/HomeOfVapourSynthEvolution/VapourSynth-EEDI2/archive/refs/tags/r7.1.tar.gz; \
    tar zxvf r7.1.tar.gz; \
    cd VapourSynth-EEDI2-r7.1; \
    meson setup build; ninja -C build; \
    cp build/libeedi2.so /app/plugins/

RUN set -eux; \
    export PATH=/root/.local/bin:$PATH; \
    export PKG_CONFIG_PATH="/usr/local/lib/pkgconfig:/usr/local/lib/x86_64-linux-gnu/pkgconfig:/usr/local/share/pkgconfig:/root/.local/lib/x86_64-linux-gnu/pkgconfig:${PKG_CONFIG_PATH:-}"; \
    cd /tmp/vsplugins; \
    wget -nv -O r30.tar.gz https://github.com/EleonoreMizo/fmtconv/archive/refs/tags/r30.tar.gz; \
    tar zxvf r30.tar.gz; \
    cd fmtconv-r30/build/unix; \
    ./autogen.sh; \
    ./configure; \
    make -j"$(nproc)"; \
    cp "$PWD/.libs/libfmtconv.so" /app/plugins/

RUN set -eux; \
    export PATH=/root/.local/bin:$PATH; \
    export PKG_CONFIG_PATH="/usr/local/lib/pkgconfig:/usr/local/lib/x86_64-linux-gnu/pkgconfig:/usr/local/share/pkgconfig:/root/.local/lib/x86_64-linux-gnu/pkgconfig:${PKG_CONFIG_PATH:-}"; \
    cd /tmp/vsplugins; \
    wget -nv -O R1.tar.gz https://github.com/vapoursynth/vs-removegrain/archive/refs/tags/R1.tar.gz; \
    tar zxvf R1.tar.gz; \
    cd vs-removegrain-R1/src; \
    g++ -shared -fPIC -O3 -Wall $(pkg-config --cflags vapoursynth) clense.cpp removegrainvs.cpp repairvs.cpp shared.cpp verticalcleaner.cpp -o libremovegrain.so; \
    cp libremovegrain.so /app/plugins/

RUN set -eux; \
    export PATH=/root/.local/bin:$PATH; \
    export PKG_CONFIG_PATH="/usr/local/lib/pkgconfig:/usr/local/lib/x86_64-linux-gnu/pkgconfig:/usr/local/share/pkgconfig:/root/.local/lib/x86_64-linux-gnu/pkgconfig:${PKG_CONFIG_PATH:-}"; \
    cd /tmp/vsplugins; \
    wget -nv -O v0.1-fix.tar.gz https://github.com/HomeOfVapourSynthEvolution/VapourSynth-SangNomMod/archive/refs/tags/v0.1-fix.tar.gz; \
    tar zxvf v0.1-fix.tar.gz; \
    cd VapourSynth-SangNomMod-0.1-fix; \
    ./configure; \
    make -j"$(nproc)"; \
    cp "$(find "$PWD" -maxdepth 3 -name libsangnommod.so -type f | head -n1)" /app/plugins/

RUN set -eux; \
    export PATH=/root/.local/bin:$PATH; \
    export PKG_CONFIG_PATH="/usr/local/lib/pkgconfig:/usr/local/lib/x86_64-linux-gnu/pkgconfig:/usr/local/share/pkgconfig:/root/.local/lib/x86_64-linux-gnu/pkgconfig:${PKG_CONFIG_PATH:-}"; \
    cd /tmp/vsplugins; \
    wget -nv -O 2.0.4.tar.gz https://github.com/Lypheo/vs-placebo/archive/refs/tags/2.0.4.tar.gz; \
    tar zxvf 2.0.4.tar.gz; \
    cd vs-placebo-2.0.4; \
    meson setup build -Dr73-compat=true; ninja -C build; \
    cp "$(find "$PWD/build" -maxdepth 2 -name libvs_placebo.so -type f | head -n1)" /app/plugins/

RUN set -eux; \
    export PATH=/root/.local/bin:$PATH; \
    export PKG_CONFIG_PATH="/usr/local/lib/pkgconfig:/usr/local/lib/x86_64-linux-gnu/pkgconfig:/usr/local/share/pkgconfig:/root/.local/lib/x86_64-linux-gnu/pkgconfig:${PKG_CONFIG_PATH:-}"; \
    cd /tmp/vsplugins; \
    wget -nv -O zsmooth.zip https://github.com/adworacz/zsmooth/releases/download/0.7/libzsmooth.x86_64-gnu.so.zip; \
    unzip -o zsmooth.zip; \
    mv libzsmooth.x86_64-gnu.so /app/plugins/

RUN set -eux; \
    export PATH=/root/.local/bin:$PATH; \
    export PKG_CONFIG_PATH="/usr/local/lib/pkgconfig:/usr/local/lib/x86_64-linux-gnu/pkgconfig:/usr/local/share/pkgconfig:/root/.local/lib/x86_64-linux-gnu/pkgconfig:${PKG_CONFIG_PATH:-}"; \
    cd /tmp/vsplugins; \
    wget -nv -O v26.tar.gz https://github.com/dubhatervapoursynth/vapoursynth-mvtools/archive/refs/tags/v26.tar.gz; \
    tar zxvf v26.tar.gz; \
    cd vapoursynth-mvtools-26; \
    python3 -c "import re; c=open('meson.build',encoding='utf-8',errors='replace').read(); c=re.sub(r\"incdir\\s*=\\s*include_directories\\s*\\(\\s*'vapoursynth/include'\\s*\\)\",\"incdir = '/usr/local/include/vapoursynth'\",c,flags=re.DOTALL); open('meson.build','w',encoding='utf-8').write(c)"; \
    meson setup build; ninja -C build; \
    cp build/mvtools.so /app/plugins/

RUN set -eux; \
    export PATH=/root/.local/bin:$PATH; \
    export PKG_CONFIG_PATH="/usr/local/lib/pkgconfig:/usr/local/lib/x86_64-linux-gnu/pkgconfig:/usr/local/share/pkgconfig:/root/.local/lib/x86_64-linux-gnu/pkgconfig:${PKG_CONFIG_PATH:-}"; \
    wget -nv -O /tmp/ispc.tar.gz https://github.com/ispc/ispc/releases/download/v1.31.0/ispc-v1.31.0-linux.tar.gz; \
    cd /tmp; tar -xvf ispc.tar.gz; \
    mv ispc-v1.31.0-linux/bin/ispc /usr/local/bin/; chmod +x /usr/local/bin/ispc

RUN set -eux; \
    export PATH=/root/.local/bin:$PATH; \
    export PKG_CONFIG_PATH="/usr/local/lib/pkgconfig:/usr/local/lib/x86_64-linux-gnu/pkgconfig:/usr/local/share/pkgconfig:/root/.local/lib/x86_64-linux-gnu/pkgconfig:${PKG_CONFIG_PATH:-}"; \
    cd /tmp/vsplugins; \
    wget -nv -O v4.tar.gz https://github.com/AmusementClub/vs-nlm-ispc/archive/refs/tags/v4.tar.gz; \
    tar zxvf v4.tar.gz; \
    cd vs-nlm-ispc-4; mkdir -p build && cd build; \
    cmake ..; make -j"$(nproc)"; \
    cp "$(find "$PWD" -maxdepth 2 -name libvsnlm_ispc.so -type f | head -n1)" /app/plugins/; \
    rm -rf /tmp/vsplugins /tmp/ispc.tar.gz /tmp/ispc-v1.31.0-linux

RUN python3 -m pip install --break-system-packages --upgrade numpy pycountry PyQt6 soundfile pillow matplotlib

RUN set -eux; \
    SEVENZIP_RELEASE="$(git ls-remote --refs --tags --sort=-version:refname https://github.com/ip7z/7zip.git | awk -F 'refs/tags/' 'NF == 2 && $2 ~ /^[0-9]+[.][0-9]+$/ { print $2; exit }')"; \
    test -n "$SEVENZIP_RELEASE"; \
    SEVENZIP_ASSET_VERSION="$(printf '%s' "$SEVENZIP_RELEASE" | tr -d '.')"; \
    case "$(uname -m)" in \
      x86_64|amd64) SEVENZIP_ARCH=x64 ;; \
      aarch64|arm64) SEVENZIP_ARCH=arm64 ;; \
      armv7l|armv6l) SEVENZIP_ARCH=arm ;; \
      i686|i386|x86) SEVENZIP_ARCH=x86 ;; \
      *) echo "unsupported arch for 7-Zip: $(uname -m)" >&2; exit 1 ;; \
    esac; \
    mkdir -p /tmp/7zip && cd /tmp/7zip; \
    wget -nv "https://github.com/ip7z/7zip/releases/download/${SEVENZIP_RELEASE}/7z${SEVENZIP_ASSET_VERSION}-linux-${SEVENZIP_ARCH}.tar.xz"; \
    tar -xJf "7z${SEVENZIP_ASSET_VERSION}-linux-${SEVENZIP_ARCH}.tar.xz"; \
    install -m 0755 7zz /usr/local/bin/7zz; \
    rm -rf /tmp/7zip

RUN set -eux; \
    mkdir -p /tmp/vcbs && cd /tmp/vcbs; \
    wget -nv -O vapoursynth_portable.7z "https://github.com/AmusementClub/tools/releases/download/2025H1p/vapoursynth_portable_25H1.1p_cpu.7z"; \
    7zz x vapoursynth_portable.7z -o./extracted; \
    PYV="$(python3 -c 'import sys; print("%d.%d" % (sys.version_info.major, sys.version_info.minor))')"; \
    DST="/usr/local/lib/python${PYV}/dist-packages"; \
    mkdir -p "${DST}"; \
    SCRIPTS_DIR="$(find ./extracted -maxdepth 2 -type d -name VapourSynthScripts | head -n1)"; \
    test -n "${SCRIPTS_DIR}"; \
    find "${SCRIPTS_DIR}" -maxdepth 1 -type f -name "*.py" -exec cp -f {} "${DST}/" \; ; \
    rm -rf /tmp/vcbs

ARG X264_COMMIT
RUN set -eux; \
    X264_OFFICIAL=https://code.videolan.org/videolan/x264.git; \
    X264_MIRROR=https://github.com/mirror/x264.git; \
    if [ -z "${X264_COMMIT:-}" ]; then \
      for repository in "$X264_OFFICIAL" "$X264_MIRROR"; do \
        X264_COMMIT="$(git ls-remote "$repository" refs/heads/master | awk 'NR == 1 { print $1 }')"; \
        if [ -n "$X264_COMMIT" ]; then break; fi; \
      done; \
    fi; \
    test -n "$X264_COMMIT"; \
    mkdir -p /tmp/x264 && cd /tmp/x264; \
    git init x264; \
    cd x264; \
    fetched=0; \
    for repository in "$X264_OFFICIAL" "$X264_MIRROR"; do \
      git remote remove origin 2>/dev/null || true; \
      git remote add origin "$repository"; \
      for attempt in 1 2 3 4 5; do \
        if git fetch --depth 1 origin "$X264_COMMIT"; then fetched=1; break; fi; \
        if [ "$attempt" -lt 5 ]; then sleep "$((attempt * 5))"; fi; \
      done; \
      if [ "$fetched" -eq 1 ]; then break; fi; \
    done; \
    test "$fetched" -eq 1; \
    git checkout --detach FETCH_HEAD; \
    X264_LAVF_OPTION=; \
    LIBAVUTIL_MAJOR="$(pkg-config --modversion libavutil 2>/dev/null | cut -d. -f1 || true)"; \
    case "$LIBAVUTIL_MAJOR" in \
      ''|*[!0-9]*) ;; \
      *) if [ "$LIBAVUTIL_MAJOR" -ge 60 ] && { ! grep -Fq AV_FRAME_FLAG_INTERLACED input/lavf.c || ! grep -Fq AV_FRAME_FLAG_TOP_FIELD_FIRST input/lavf.c; }; then X264_LAVF_OPTION=--disable-lavf; fi ;; \
    esac; \
    ./configure --enable-static --bit-depth=all --chroma-format=all --disable-opencl $X264_LAVF_OPTION --enable-lto; \
    make -j"$(nproc)"; \
    install -m 0755 x264 /usr/bin/x264; \
    /usr/bin/x264 --version >/dev/null; \
    rm -rf /tmp/x264

ARG TSMUXER_TAG
RUN set -eux; \
    TSMUXER_TAG="${TSMUXER_TAG:-$(git ls-remote --refs --tags --sort=-version:refname https://github.com/justdan96/tsMuxer.git | awk -F 'refs/tags/' 'NF == 2 && $2 ~ /^[vV]?[0-9]+([.][0-9]+)+$/ { print $2; exit }')}"; \
    test -n "$TSMUXER_TAG"; \
    TSMUXER_VER="${TSMUXER_TAG#v}"; \
    mkdir -p /tmp/tsmuxer && cd /tmp/tsmuxer; \
    wget -nv "https://github.com/justdan96/tsMuxer/releases/download/${TSMUXER_TAG}/tsMuxer-${TSMUXER_VER}-linux.zip"; \
    unzip "tsMuxer-${TSMUXER_VER}-linux.zip"; \
    cp tsMuxeR /usr/bin/tsMuxeR; \
    chmod +x /usr/bin/tsMuxeR; \
    rm -rf /tmp/tsmuxer

ARG HDR10PLUS_TAG
RUN set -eux; \
    HDR10PLUS_TAG="${HDR10PLUS_TAG:-$(git ls-remote --refs --tags --sort=-version:refname https://github.com/quietvoid/hdr10plus_tool.git | awk -F 'refs/tags/' 'NF == 2 && $2 ~ /^[vV]?[0-9]+([.][0-9]+)+$/ { print $2; exit }')}"; \
    test -n "$HDR10PLUS_TAG"; \
    HDR10PLUS_VER="${HDR10PLUS_TAG#v}"; \
    case "$(uname -m)" in \
      x86_64|amd64) HDR10PLUS_ARCH=x86_64 ;; \
      aarch64|arm64) HDR10PLUS_ARCH=aarch64 ;; \
      *) exit 1 ;; \
    esac; \
    HDR10PLUS_ARCHIVE="hdr10plus_tool-${HDR10PLUS_VER}-${HDR10PLUS_ARCH}-unknown-linux-musl.tar.gz"; \
    mkdir -p /tmp/hdr10plus-tool; \
    cd /tmp/hdr10plus-tool; \
    wget -nv "https://github.com/quietvoid/hdr10plus_tool/releases/download/${HDR10PLUS_TAG}/${HDR10PLUS_ARCHIVE}"; \
    tar zxf "${HDR10PLUS_ARCHIVE}"; \
    install -m 0755 hdr10plus_tool /usr/bin/hdr10plus_tool; \
    /usr/bin/hdr10plus_tool --version 2>&1 | grep -F "hdr10plus_tool ${HDR10PLUS_VER}" >/dev/null; \
    rm -rf /tmp/hdr10plus-tool

RUN pkg-config --exists dovi \
    && /usr/bin/ffmpeg -hide_banner -h encoder=libopus 2>&1 | grep '^Encoder libopus' >/dev/null \
    && test -x /usr/bin/dovi_tool \
    && test -x /usr/bin/hdr10plus_tool \
    && test -x /usr/bin/truehdd \
    && test -x /usr/bin/flac \
    && test -x /usr/bin/ffmpeg \
    && test -x /usr/bin/ffprobe \
    && test -x /usr/bin/x265 \
    && test -x /usr/bin/x264 \
    && test -x /usr/bin/SvtAv1EncApp \
    && test -x /usr/local/bin/fdkaac \
    && test -x /usr/local/bin/vsedit \
    && test -x /usr/local/bin/vspipe \
    && /usr/local/bin/mpv --list-options | grep -F ' --osc ' >/dev/null \
    && test -x /usr/bin/tsMuxeR \
    && test -x /usr/bin/mkvinfo \
    && test -x /usr/bin/mkvmerge \
    && test -x /usr/bin/mkvpropedit \
    && test -x /usr/bin/mkvextract \
    && test -d /app/plugins

ENV LD_PRELOAD=/usr/local/lib/libvapoursynth-script.so

WORKDIR /app
COPY src/ /app/src/
COPY config.default.json /app/config.default.json
RUN install -d -m 0755 -o ubuntu -g ubuntu /config \
    && install -d -m 0700 -o ubuntu -g ubuntu /tmp/runtime-ubuntu
ENV BLURAY_SUBTITLE_CONFIG_DIR=/config
ENV HOME=/home/ubuntu
ENV XDG_RUNTIME_DIR=/tmp/runtime-ubuntu
VOLUME ["/config"]
USER ubuntu
CMD ["dbus-run-session", "--", "python3", "-m", "src.main"]
