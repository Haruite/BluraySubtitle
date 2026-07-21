# syntax=docker/dockerfile:1.6
FROM ubuntu:26.04

ENV DEBIAN_FRONTEND=noninteractive
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8
ENV PATH=/root/.local/bin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl git wget unzip xz-utils tar sed pkg-config \
    build-essential cmake ninja-build autoconf automake libtool \
    python3 python3-pip python3-venv python3-dev python3-sphinx \
    ffmpeg fonts-wqy-microhei flac gedit nautilus \
    libegl1 libopengl0 libglib2.0-0 libxkbcommon0 libdbus-1-3 \
    libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 libxcb-shape0 \
    libxcb-xinerama0 libxcb-xinput0 libxcb-render-util0 \
    libunwind8 libunwind-dev xdg-utils libgl1-mesa-dri libglx-mesa0 mesa-vulkan-drivers \
    yasm nasm glslang-tools glslang-dev wayland-protocols yt-dlp \
    libass-dev libfribidi-dev libfreetype-dev libfontconfig1-dev libharfbuzz-dev libuchardet-dev \
    libgl1-mesa-dev libvdpau-dev libva-dev libx11-dev libxext-dev libxv-dev libxinerama-dev \
    libwayland-dev libxkbcommon-dev libegl1-mesa-dev libplacebo-dev libspirv-cross-c-shared-dev libshaderc-dev \
    libasound2-dev libpulse-dev libjack-dev libpipewire-0.3-dev \
    libdav1d-dev \
    libavcodec-dev libavformat-dev libavutil-dev libswscale-dev libswresample-dev libavfilter-dev \
    libmujs-dev libbluray-dev libxrandr-dev libxpresent-dev libxss-dev libdvdnav-dev libdvdread-dev \
    libzimg-dev libarchive-dev librubberband-dev libsdl2-dev libdrm-dev libgbm-dev \
    libssl-dev libjpeg-dev zlib1g-dev libogg-dev libtool-bin gettext \
    libmagick++-dev libtesseract-dev cython3 \
    qt6-base-dev qt6-base-dev-tools qt6-5compat-dev qt6-websockets-dev qt6-declarative-dev qt6-multimedia-dev libqt6svg6-dev libgl-dev \
    libboost-date-time-dev libboost-dev libboost-filesystem-dev libboost-math-dev libboost-regex-dev libboost-system-dev libx11-xcb-dev libglu1-mesa-dev \
    libbz2-dev libcmark-dev libflac-dev libfmt-dev libgmp-dev libgtest-dev liblzo2-dev libmagic-dev \
    libvorbis-dev libpcre2-8-0 libpcre2-dev \
    nlohmann-json3-dev po4a rake ruby xsltproc debhelper fakeroot dpkg-dev docbook-xsl \
    libxxhash-dev libfftw3-dev p7zip-full \
    && rm -rf /var/lib/apt/lists/*

RUN fc-cache -f >/dev/null 2>&1 || true

RUN set -eux; \
    ensure_meson_version() { \
      python3 -m pip install --break-system-packages --upgrade meson || python3 -m pip install --upgrade meson; \
      meson --version; \
    }; \
    ensure_meson_version; \
    python3 -m pip install --break-system-packages --upgrade cython || python3 -m pip install --upgrade cython

RUN bash <<'MKVTOOLNIX'
set -euo pipefail
XML="$(curl -fsSL https://mkvtoolnix.download/latest-release.xml)"
VERSION="$(printf '%s' "$XML" | python3 -c "import re,sys; x=sys.stdin.read(); m=re.search(r'<latest-source>.*?<version>([^<]+)</version>', x, re.S); print((m.group(1) if m else '').strip())")"
test -n "$VERSION"
CURRENT=""
if command -v mkvmerge >/dev/null 2>&1; then
  CURRENT="$(dpkg-query -W -f='${Version}' mkvtoolnix 2>/dev/null | sed 's/-.*//' || true)"
  if [ -z "$CURRENT" ]; then
    CURRENT="$(mkvmerge --version 2>/dev/null | head -n 1 | grep -oE 'v[0-9]+(\.[0-9]+)+' | head -n 1 | tr -d v || true)"
  fi
fi
if [ -n "$CURRENT" ] && dpkg --compare-versions "$CURRENT" ge "$VERSION"; then
  exit 0
fi
mkdir -p /tmp/mkv && cd /tmp/mkv
curl -fsSL -o "mkvtoolnix_${VERSION}.orig.tar.xz" "https://mkvtoolnix.download/sources/mkvtoolnix-${VERSION}.tar.xz"
tar xJf "mkvtoolnix_${VERSION}.orig.tar.xz"
cd "mkvtoolnix-${VERSION}"
cp -R packaging/debian debian
./debian/create_files.rb
python3 - <<'PY'
from __future__ import annotations

import re
from pathlib import Path

rules_path = Path("debian/rules")
text = rules_path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)

start = None
for i, line in enumerate(text):
    if line.startswith("override_dh_auto_build:"):
        start = i
        break
if start is None:
    raise SystemExit("debian/rules: override_dh_auto_build not found")

end = start + 1
while end < len(text):
    line = text[end]
    if line.startswith("\t") or line.strip() == "":
        end += 1
        continue
    if re.match(r"^[^\t\s].+?:\s*(#.*)?$", line):
        break
    end += 1

replacement = [
    "override_dh_auto_build:\n",
    "\texport LD_LIBRARY_PATH=\n",
    "\texport LIBRARY_PATH=/usr/lib/x86_64-linux-gnu:/usr/lib\n",
    "\texport PKG_CONFIG_PATH=/usr/lib/x86_64-linux-gnu/pkgconfig:/usr/share/pkgconfig\n",
    "\texport LDFLAGS=\"-L/usr/lib/x86_64-linux-gnu -Wl,-rpath-link,/usr/lib/x86_64-linux-gnu\"\n",
    "ifeq (,$(filter nocheck,$(DEB_BUILD_OPTIONS)))\n",
    "\tLC_ALL=C ./drake -j$(shell nproc) tests:run_unit\n",
    "endif\n",
    "\n",
    "\t./drake -j$(shell nproc)\n",
]

text[start:end] = replacement
new_end = start + len(replacement)

if not any(line.startswith("override_dh_shlibdeps:") for line in text):
    text[new_end:new_end] = [
        "\n",
        "override_dh_shlibdeps:\n",
        "\tdh_shlibdeps --dpkg-shlibdeps-params=--ignore-missing-info\n",
    ]

rules_path.write_text("".join(text), encoding="utf-8")
PY
BOOST_QUARANTINE=""
if compgen -G "/usr/local/lib/libboost_*.so*" >/dev/null; then
  BOOST_QUARANTINE="$(mktemp -d)"
  mv /usr/local/lib/libboost_*.so* "$BOOST_QUARANTINE/"
  ldconfig
fi
restore_boost() {
  if [ -n "${BOOST_QUARANTINE:-}" ] && [ -d "$BOOST_QUARANTINE" ]; then
    mv "$BOOST_QUARANTINE"/libboost_*.so* /usr/local/lib/ 2>/dev/null || true
    ldconfig
    rm -rf "$BOOST_QUARANTINE"
  fi
}
trap restore_boost EXIT
rm -rf debian/mkvtoolnix debian/mkvtoolnix-gui 2>/dev/null || true
./drake clean 2>/dev/null || true
export LD_LIBRARY_PATH=""
export LIBRARY_PATH="/usr/lib/x86_64-linux-gnu:/usr/lib"
export PKG_CONFIG_PATH="/usr/lib/x86_64-linux-gnu/pkgconfig:/usr/share/pkgconfig"
export LDFLAGS="-L/usr/lib/x86_64-linux-gnu -Wl,-rpath-link,/usr/lib/x86_64-linux-gnu"
export DEB_BUILD_OPTIONS="${DEB_BUILD_OPTIONS:-nocheck}"
dpkg-buildpackage -b --no-sign
restore_boost
trap - EXIT
apt-get update
apt-get install -y ../mkvtoolnix*.deb || (dpkg -i ../mkvtoolnix*.deb || true; apt-get -f install -y)
rm -rf /tmp/mkv
MKVTOOLNIX

RUN set -eux; \
    DOVI_VER="$(git ls-remote --refs --tags --sort=-version:refname https://github.com/quietvoid/dovi_tool.git | awk -F 'refs/tags/' 'NF == 2 && $2 ~ /^[vV]?[0-9]+([.][0-9]+)+$/ { print $2; exit }')"; \
    test -n "$DOVI_VER"; \
    mkdir -p /tmp/dovi && cd /tmp/dovi; \
    if ! command -v rustup >/dev/null 2>&1; then curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y; fi; \
    . /root/.cargo/env; \
    rustup update stable; \
    cargo install cargo-c; \
    git clone --depth 1 --branch "$DOVI_VER" https://github.com/quietvoid/dovi_tool.git; \
    cd dovi_tool/dolby_vision; \
    cargo cinstall --release --prefix=/root/.local; \
    test "$(find /root/.local -name 'libdovi.so*' 2>/dev/null | wc -l)" -ge 1; \
    find /root/.local -name 'libdovi.so*' -exec cp -a {} /usr/local/lib/ \; ; \
    ldconfig; \
    case "$(uname -m)" in \
      x86_64|amd64) DOVI_ARCH=x86_64 ;; \
      aarch64|arm64) DOVI_ARCH=aarch64 ;; \
      *) echo "unsupported arch for dovi_tool: $(uname -m)" >&2; exit 1 ;; \
    esac; \
    cd /tmp/dovi; \
    wget -q "https://github.com/quietvoid/dovi_tool/releases/download/${DOVI_VER}/dovi_tool-${DOVI_VER}-${DOVI_ARCH}-unknown-linux-musl.tar.gz"; \
    tar zxf "dovi_tool-${DOVI_VER}-${DOVI_ARCH}-unknown-linux-musl.tar.gz"; \
    install -m 0755 dovi_tool /usr/bin/dovi_tool; \
    rm -rf /tmp/dovi

RUN set -eux; \
    TRUEHDD_VER="$(git ls-remote --refs --tags --sort=-version:refname https://github.com/truehdd/truehdd.git | awk -F 'refs/tags/' 'NF == 2 && $2 ~ /^[vV]?[0-9]+([.][0-9]+)+$/ { print $2; exit }')"; \
    test -n "$TRUEHDD_VER"; \
    case "$(uname -m)" in \
      x86_64|amd64) TRUEHDD_ARCH=x86_64 ;; \
      aarch64|arm64) TRUEHDD_ARCH=aarch64 ;; \
      *) echo "unsupported arch for truehdd: $(uname -m)" >&2; exit 1 ;; \
    esac; \
    mkdir -p /tmp/truehdd_bin && cd /tmp/truehdd_bin; \
    wget -q "https://github.com/truehdd/truehdd/releases/download/${TRUEHDD_VER}/truehdd-${TRUEHDD_VER}-${TRUEHDD_ARCH}-unknown-linux-gnu.tar.gz"; \
    tar zxf "truehdd-${TRUEHDD_VER}-${TRUEHDD_ARCH}-unknown-linux-gnu.tar.gz"; \
    install -m 0755 truehdd /usr/bin/truehdd; \
    rm -rf /tmp/truehdd_bin

RUN set -eux; \
    mkdir -p /tmp/mpv && cd /tmp/mpv; \
    git clone https://github.com/mpv-player/mpv-build.git; \
    cd mpv-build; \
    rm -rf mpv/build ffmpeg/build libass/build || true; \
    echo "--enable-libbluray" > ffmpeg_options; \
    echo "--enable-libdav1d" >> ffmpeg_options; \
    echo "-Dlibbluray=enabled" > mpv_options; \
    export PKG_CONFIG_PATH="/root/.local/lib/x86_64-linux-gnu/pkgconfig:${PKG_CONFIG_PATH:-}"; \
    ./rebuild -j"$(nproc)"; \
    ./install; \
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

RUN bash <<'EOS'
set -euo pipefail
mkdir -p /tmp/x265
cd /tmp/x265
git clone --depth 1 https://github.com/msg7086/x265-Yuuki-Asuna.git
x265_repo=/tmp/x265/x265-Yuuki-Asuna
MULTIBUILD=${x265_repo}/build/linux
SRCROOT=${x265_repo}/source
test -f "${SRCROOT}/CMakeLists.txt"

case ${MAKEFLAGS-} in
'')
	_j="$(nproc 2>/dev/null || getconf _NPROCESSORS_ONLN 2>/dev/null || echo 4)"
	case "$_j" in ''|*[!0-9]*) _j=4 ;; esac
	export MAKEFLAGS="-j${_j}"
	;;
esac

x265_cmake_extra_args="-DCMAKE_POLICY_VERSION_MINIMUM=3.10"

CXXBIN="${CXX:-c++}"
LINK_MODE="${X265_LINK:-auto}"
_libstd=""
_libc=""
if command -v "$CXXBIN" >/dev/null 2>&1; then
	_libstd="$("$CXXBIN" -print-file-name=libstdc++.a 2>/dev/null || true)"
	_libc="$("$CXXBIN" -print-file-name=libc.a 2>/dev/null || true)"
fi
_stdc_ok=0
_libc_ok=0
[ -n "$_libstd" ] && [ -f "$_libstd" ] && _stdc_ok=1
[ -n "$_libc" ] && [ -f "$_libc" ] && _libc_ok=1

X265_CMAKE_EXE_LINKER_FLAGS=""
case "$LINK_MODE" in
full)
	[ "$_stdc_ok" = 1 ] && [ "$_libc_ok" = 1 ] || exit 1
	X265_CMAKE_EXE_LINKER_FLAGS=-static
	;;
mostly)
	[ "$_stdc_ok" = 1 ] || exit 1
	X265_CMAKE_EXE_LINKER_FLAGS="-static-libgcc -static-libstdc++"
	;;
x265-only)
	X265_CMAKE_EXE_LINKER_FLAGS=""
	;;
auto)
	if [ "$_stdc_ok" = 1 ]; then
		X265_CMAKE_EXE_LINKER_FLAGS="-static-libgcc -static-libstdc++"
	else
		X265_CMAKE_EXE_LINKER_FLAGS=""
	fi
	;;
*) exit 1 ;;
esac

command -v python3 >/dev/null 2>&1 || exit 1
python3 - "$SRCROOT" <<'PY'
import pathlib, sys

root = pathlib.Path(sys.argv[1])
marker = "# x265-multilib-fullstatic: cmake4-patched\n"
main_cm = root / "CMakeLists.txt"
text = main_cm.read_text(encoding="utf-8", errors="surrogateescape")
if marker in text:
    sys.exit(0)

anchor = "option(FPROFILE_GENERATE"
idx = text.find(anchor)
if idx < 0:
    sys.exit("error: x265 CMakeLists.txt missing anchor %r" % (anchor,))

header = (
    "# vim: syntax=cmake\n"
    + marker
    + "cmake_minimum_required(VERSION 3.10)\n\n"
    + "if(NOT CMAKE_BUILD_TYPE)\n"
    + "    # default to Release build for GCC builds\n"
    + "    set(CMAKE_BUILD_TYPE Release CACHE STRING\n"
    + '        "Choose the type of build, options are: None(CMAKE_CXX_FLAGS or CMAKE_C_FLAGS used) Debug Release RelWithDebInfo MinSizeRel."\n'
    + "        FORCE)\n"
    + "endif()\n"
    + 'message(STATUS "cmake version ${CMAKE_VERSION}")\n'
    + "if(POLICY CMP0025)\n"
    + "    cmake_policy(SET CMP0025 NEW)\n"
    + "endif()\n"
    + "if(POLICY CMP0042)\n"
    + "    cmake_policy(SET CMP0042 NEW) # MACOSX_RPATH\n"
    + "endif()\n"
    + "if(POLICY CMP0054)\n"
    + "    cmake_policy(SET CMP0054 NEW)\n"
    + "endif()\n\n"
    + "project(x265 LANGUAGES C CXX)\n"
    + "include(CheckIncludeFiles)\n"
    + "include(CheckFunctionExists)\n"
    + "include(CheckSymbolExists)\n"
    + "include(CheckCXXCompilerFlag)\n\n"
)

rest = text[idx:]
rest = rest.replace(
    'if(${CMAKE_CXX_COMPILER_ID} STREQUAL "Clang")',
    'if(CMAKE_CXX_COMPILER_ID STREQUAL "Clang")',
)
rest = rest.replace(
    'if(${CMAKE_CXX_COMPILER_ID} STREQUAL "Intel")',
    'if(CMAKE_CXX_COMPILER_ID STREQUAL "Intel")',
)
rest = rest.replace(
    'if(${CMAKE_CXX_COMPILER_ID} STREQUAL "GNU")',
    'if(CMAKE_CXX_COMPILER_ID STREQUAL "GNU")',
)
rest = rest.replace(
    "if(IS_ABSOLUTE ${LIB} AND EXISTS ${LIB})",
    'if(IS_ABSOLUTE "${LIB}" AND EXISTS "${LIB}")',
)

main_cm.write_text(header + rest, encoding="utf-8", errors="surrogateescape")

hdr = root / "dynamicHDR10" / "CMakeLists.txt"
if hdr.is_file():
    ht = hdr.read_text(encoding="utf-8", errors="surrogateescape")
    old = "cmake_minimum_required (VERSION 2.8.11)"
    new = "cmake_minimum_required(VERSION 3.10)"
    if old in ht:
        hdr.write_text(ht.replace(old, new, 1), encoding="utf-8", errors="surrogateescape")
sys.exit(0)
PY

mkdir -p "$MULTIBUILD/8bit" "$MULTIBUILD/10bit" "$MULTIBUILD/12bit"

cd "$MULTIBUILD/12bit"
cmake "$x265_cmake_extra_args" "$SRCROOT" \
	-DHIGH_BIT_DEPTH=ON \
	-DEXPORT_C_API=OFF \
	-DENABLE_SHARED=OFF \
	-DENABLE_CLI=OFF \
	-DMAIN12=ON \
	-DENABLE_LIBNUMA=OFF
make

cd "$MULTIBUILD/10bit"
cmake "$x265_cmake_extra_args" "$SRCROOT" \
	-DHIGH_BIT_DEPTH=ON \
	-DEXPORT_C_API=OFF \
	-DENABLE_SHARED=OFF \
	-DENABLE_CLI=OFF \
	-DENABLE_LIBNUMA=OFF
make

cd "$MULTIBUILD/8bit"
ln -sf ../10bit/libx265.a libx265_main10.a
ln -sf ../12bit/libx265.a libx265_main12.a
if [ -n "$X265_CMAKE_EXE_LINKER_FLAGS" ]; then
	cmake "$x265_cmake_extra_args" "$SRCROOT" \
		-DENABLE_SHARED=OFF \
		-DENABLE_LIBNUMA=OFF \
		-DCMAKE_EXE_LINKER_FLAGS="$X265_CMAKE_EXE_LINKER_FLAGS" \
		-DEXTRA_LIB="x265_main10.a;x265_main12.a" \
		-DEXTRA_LINK_FLAGS=-L. \
		-DLINKED_10BIT=ON \
		-DLINKED_12BIT=ON
else
	cmake "$x265_cmake_extra_args" "$SRCROOT" \
		-DENABLE_SHARED=OFF \
		-DENABLE_LIBNUMA=OFF \
		-DEXTRA_LIB="x265_main10.a;x265_main12.a" \
		-DEXTRA_LINK_FLAGS=-L. \
		-DLINKED_10BIT=ON \
		-DLINKED_12BIT=ON
fi
make

mv libx265.a libx265_main.a
if [ "$(uname)" = "Linux" ]; then
	ar -M <<'ARSCRIPT'
CREATE libx265.a
ADDLIB libx265_main.a
ADDLIB libx265_main10.a
ADDLIB libx265_main12.a
SAVE
END
ARSCRIPT
else
	libtool -static -o libx265.a libx265_main.a libx265_main10.a libx265_main12.a 2>/dev/null
fi

if command -v strip >/dev/null 2>&1; then
	strip "$MULTIBUILD/8bit/x265" 2>/dev/null || true
fi

cp "$MULTIBUILD/8bit/x265" /usr/bin/x265
chmod +x /usr/bin/x265
rm -rf /tmp/x265
EOS

RUN bash <<'SVTAV1EOS'
set -euo pipefail
mkdir -p /tmp/svtav1
cd /tmp/svtav1
git clone --depth 1 --branch v4.2.0 https://gitlab.com/AOMediaCodec/SVT-AV1.git
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
python3 - "$svt_root" <<'SVTAV1PATCH'
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
    for rel, old, new in APPLY:
        path = root / rel
        text = path.read_text(encoding="utf-8")
        if "12-bit encoding requires Professional profile" in text and rel.name == "enc_settings.c":
            continue
        if old not in text:
            if new in text:
                continue
            sys.exit(1)
        path.write_text(text.replace(old, new, 1), encoding="utf-8")



run_apply()
sys.exit(0)
SVTAV1PATCH

cd "$svt_root/Build/linux"
./build.sh release static

test -f "$svt_root/Bin/Release/SvtAv1EncApp"
cp "$svt_root/Bin/Release/SvtAv1EncApp" /usr/bin/SvtAv1EncApp
chmod +x /usr/bin/SvtAv1EncApp
rm -rf /tmp/svtav1
SVTAV1EOS

RUN bash <<'FDKAAC'
set -euo pipefail
latest_stable_tag() {
  git ls-remote --refs --tags --sort=-version:refname "$1" |
    awk -F 'refs/tags/' 'NF == 2 && $2 ~ /^[vV]?[0-9]+([.][0-9]+)+$/ { print $2; exit }'
}
mkdir -p /tmp/fdk
cd /tmp/fdk
FDK_AAC_TAG="$(latest_stable_tag https://github.com/mstorsjo/fdk-aac.git)"
FDKAAC_TAG="$(latest_stable_tag https://github.com/nu774/fdkaac.git)"
test -n "$FDK_AAC_TAG"
test -n "$FDKAAC_TAG"
git clone --depth 1 --branch "$FDK_AAC_TAG" https://github.com/mstorsjo/fdk-aac.git fdk-aac
cd fdk-aac
./autogen.sh
./configure
make -j"$(nproc)"
make install
ldconfig
cd /tmp/fdk
git clone --depth 1 --branch "$FDKAAC_TAG" https://github.com/nu774/fdkaac.git
cd fdkaac
autoreconf -i
./configure
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
ldconfig
rm -rf /tmp/flac
FLAC

RUN set -eux; \
    mkdir -p /tmp/vs && cd /tmp/vs; \
    wget -O R57.A12.tar.gz https://github.com/AmusementClub/vapoursynth-classic/archive/refs/tags/R57.A12.tar.gz; \
    tar zxvf R57.A12.tar.gz; \
    cd vapoursynth-classic-R57.A12; \
    if [ -f src/filters/subtext/image.cpp ]; then sed -i 's/avcodec_close(\(.*\));/avcodec_free_context(\&\(\1\));/g' src/filters/subtext/image.cpp; fi; \
    ./autogen.sh; \
    ./configure CXXFLAGS="-O3 -fpermissive"; \
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
    wget -O R19-mod-6.10.tar.gz https://github.com/YomikoR/VapourSynth-Editor/archive/refs/tags/R19-mod-6.10.tar.gz; \
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
    wget -O r9.tar.gz https://github.com/HomeOfVapourSynthEvolution/VapourSynth-EEDI3/archive/refs/tags/r9.tar.gz; \
    tar zxvf r9.tar.gz; \
    cd VapourSynth-EEDI3-r9; \
    find . -type f -name EEDI3.cpp -exec sed -i 's/std::max_align_t/max_align_t/g' {} +; \
    python3 -c "import re; c=open('meson.build',encoding='utf-8',errors='replace').read(); c=re.sub(r'incdir = include_directories\\(.*?check: true,.*?\\.stdout\\(\\)\\.strip\\(\\),\\s*\\)','incdir = \\'/usr/local/include/vapoursynth\\'',c,flags=re.DOTALL); open('meson.build','w',encoding='utf-8').write(c)"; \
    meson setup build; ninja -C build; cp build/eedi3m.so /app/plugins/

RUN set -eux; \
    export PATH=/root/.local/bin:$PATH; \
    export PKG_CONFIG_PATH="/usr/local/lib/pkgconfig:/usr/local/lib/x86_64-linux-gnu/pkgconfig:/usr/local/share/pkgconfig:/root/.local/lib/x86_64-linux-gnu/pkgconfig:${PKG_CONFIG_PATH:-}"; \
    cd /tmp/vsplugins; \
    wget -O r10.tar.gz https://github.com/HomeOfVapourSynthEvolution/VapourSynth-AddGrain/archive/refs/tags/r10.tar.gz; \
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
    wget -O r3.tar.gz https://github.com/HomeOfVapourSynthEvolution/VapourSynth-Bilateral/archive/refs/tags/r3.tar.gz; \
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
    wget -O r7.tar.gz https://github.com/HomeOfVapourSynthEvolution/VapourSynth-DFTTest/archive/refs/tags/r7.tar.gz; \
    tar zxvf r7.tar.gz; \
    cd VapourSynth-DFTTest-r7; \
    meson setup build; ninja -C build; \
    cp build/libdfttest.so /app/plugins/

RUN set -eux; \
    export PATH=/root/.local/bin:$PATH; \
    export PKG_CONFIG_PATH="/usr/local/lib/pkgconfig:/usr/local/lib/x86_64-linux-gnu/pkgconfig:/usr/local/share/pkgconfig:/root/.local/lib/x86_64-linux-gnu/pkgconfig:${PKG_CONFIG_PATH:-}"; \
    cd /tmp/vsplugins; \
    wget -O r7.1.tar.gz https://github.com/HomeOfVapourSynthEvolution/VapourSynth-EEDI2/archive/refs/tags/r7.1.tar.gz; \
    tar zxvf r7.1.tar.gz; \
    cd VapourSynth-EEDI2-r7.1; \
    meson setup build; ninja -C build; \
    cp build/libeedi2.so /app/plugins/

RUN set -eux; \
    export PATH=/root/.local/bin:$PATH; \
    export PKG_CONFIG_PATH="/usr/local/lib/pkgconfig:/usr/local/lib/x86_64-linux-gnu/pkgconfig:/usr/local/share/pkgconfig:/root/.local/lib/x86_64-linux-gnu/pkgconfig:${PKG_CONFIG_PATH:-}"; \
    cd /tmp/vsplugins; \
    wget -O r30.tar.gz https://github.com/EleonoreMizo/fmtconv/archive/refs/tags/r30.tar.gz; \
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
    wget -O R1.tar.gz https://github.com/vapoursynth/vs-removegrain/archive/refs/tags/R1.tar.gz; \
    tar zxvf R1.tar.gz; \
    cd vs-removegrain-R1/src; \
    g++ -shared -fPIC -O3 -Wall $(pkg-config --cflags vapoursynth) clense.cpp removegrainvs.cpp repairvs.cpp shared.cpp verticalcleaner.cpp -o libremovegrain.so; \
    cp libremovegrain.so /app/plugins/

RUN set -eux; \
    export PATH=/root/.local/bin:$PATH; \
    export PKG_CONFIG_PATH="/usr/local/lib/pkgconfig:/usr/local/lib/x86_64-linux-gnu/pkgconfig:/usr/local/share/pkgconfig:/root/.local/lib/x86_64-linux-gnu/pkgconfig:${PKG_CONFIG_PATH:-}"; \
    cd /tmp/vsplugins; \
    wget -O v0.1-fix.tar.gz https://github.com/HomeOfVapourSynthEvolution/VapourSynth-SangNomMod/archive/refs/tags/v0.1-fix.tar.gz; \
    tar zxvf v0.1-fix.tar.gz; \
    cd VapourSynth-SangNomMod-0.1-fix; \
    ./configure; \
    make -j"$(nproc)"; \
    cp "$(find "$PWD" -maxdepth 3 -name libsangnommod.so -type f | head -n1)" /app/plugins/

RUN set -eux; \
    export PATH=/root/.local/bin:$PATH; \
    export PKG_CONFIG_PATH="/usr/local/lib/pkgconfig:/usr/local/lib/x86_64-linux-gnu/pkgconfig:/usr/local/share/pkgconfig:/root/.local/lib/x86_64-linux-gnu/pkgconfig:${PKG_CONFIG_PATH:-}"; \
    cd /tmp/vsplugins; \
    wget -O 2.0.4.tar.gz https://github.com/Lypheo/vs-placebo/archive/refs/tags/2.0.4.tar.gz; \
    tar zxvf 2.0.4.tar.gz; \
    cd vs-placebo-2.0.4; \
    meson setup build -Dr73-compat=true; ninja -C build; \
    cp "$(find "$PWD/build" -maxdepth 2 -name libvs_placebo.so -type f | head -n1)" /app/plugins/

RUN set -eux; \
    export PATH=/root/.local/bin:$PATH; \
    export PKG_CONFIG_PATH="/usr/local/lib/pkgconfig:/usr/local/lib/x86_64-linux-gnu/pkgconfig:/usr/local/share/pkgconfig:/root/.local/lib/x86_64-linux-gnu/pkgconfig:${PKG_CONFIG_PATH:-}"; \
    cd /tmp/vsplugins; \
    wget -O zsmooth.zip https://github.com/adworacz/zsmooth/releases/download/0.7/libzsmooth.x86_64-gnu.so.zip; \
    unzip -o zsmooth.zip; \
    mv libzsmooth.x86_64-gnu.so /app/plugins/

RUN set -eux; \
    export PATH=/root/.local/bin:$PATH; \
    export PKG_CONFIG_PATH="/usr/local/lib/pkgconfig:/usr/local/lib/x86_64-linux-gnu/pkgconfig:/usr/local/share/pkgconfig:/root/.local/lib/x86_64-linux-gnu/pkgconfig:${PKG_CONFIG_PATH:-}"; \
    cd /tmp/vsplugins; \
    wget -O v26.tar.gz https://github.com/dubhatervapoursynth/vapoursynth-mvtools/archive/refs/tags/v26.tar.gz; \
    tar zxvf v26.tar.gz; \
    cd vapoursynth-mvtools-26; \
    python3 -c "import re; c=open('meson.build',encoding='utf-8',errors='replace').read(); c=re.sub(r\"incdir\\s*=\\s*include_directories\\s*\\(\\s*'vapoursynth/include'\\s*\\)\",\"incdir = '/usr/local/include/vapoursynth'\",c,flags=re.DOTALL); open('meson.build','w',encoding='utf-8').write(c)"; \
    meson setup build; ninja -C build; \
    cp build/mvtools.so /app/plugins/

RUN set -eux; \
    export PATH=/root/.local/bin:$PATH; \
    export PKG_CONFIG_PATH="/usr/local/lib/pkgconfig:/usr/local/lib/x86_64-linux-gnu/pkgconfig:/usr/local/share/pkgconfig:/root/.local/lib/x86_64-linux-gnu/pkgconfig:${PKG_CONFIG_PATH:-}"; \
    wget -O /tmp/ispc.tar.gz https://github.com/ispc/ispc/releases/download/v1.31.0/ispc-v1.31.0-linux.tar.gz; \
    cd /tmp; tar -xvf ispc.tar.gz; \
    mv ispc-v1.31.0-linux/bin/ispc /usr/local/bin/; chmod +x /usr/local/bin/ispc

RUN set -eux; \
    export PATH=/root/.local/bin:$PATH; \
    export PKG_CONFIG_PATH="/usr/local/lib/pkgconfig:/usr/local/lib/x86_64-linux-gnu/pkgconfig:/usr/local/share/pkgconfig:/root/.local/lib/x86_64-linux-gnu/pkgconfig:${PKG_CONFIG_PATH:-}"; \
    cd /tmp/vsplugins; \
    wget -O v4.tar.gz https://github.com/AmusementClub/vs-nlm-ispc/archive/refs/tags/v4.tar.gz; \
    tar zxvf v4.tar.gz; \
    cd vs-nlm-ispc-4; mkdir -p build && cd build; \
    cmake ..; make -j"$(nproc)"; \
    cp "$(find "$PWD" -maxdepth 2 -name libvsnlm_ispc.so -type f | head -n1)" /app/plugins/; \
    rm -rf /tmp/vsplugins /tmp/ispc.tar.gz /tmp/ispc-v1.31.0-linux

RUN python3 -m pip install --break-system-packages --upgrade pycountry PyQt6 librosa pillow matplotlib

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
    wget -q "https://github.com/ip7z/7zip/releases/download/${SEVENZIP_RELEASE}/7z${SEVENZIP_ASSET_VERSION}-linux-${SEVENZIP_ARCH}.tar.xz"; \
    tar -xJf "7z${SEVENZIP_ASSET_VERSION}-linux-${SEVENZIP_ARCH}.tar.xz"; \
    install -m 0755 7zz /usr/local/bin/7zz; \
    rm -rf /tmp/7zip

RUN set -eux; \
    mkdir -p /tmp/vcbs && cd /tmp/vcbs; \
    wget -O vapoursynth_portable.7z "https://github.com/AmusementClub/tools/releases/download/2025H1p/vapoursynth_portable_25H1.1p_cpu.7z"; \
    7zz x vapoursynth_portable.7z -o./extracted; \
    PYV="$(python3 -c 'import sys; print("%d.%d" % (sys.version_info.major, sys.version_info.minor))')"; \
    DST="/usr/local/lib/python${PYV}/dist-packages"; \
    mkdir -p "${DST}"; \
    SCRIPTS_DIR="$(find ./extracted -maxdepth 2 -type d -name VapourSynthScripts | head -n1)"; \
    test -n "${SCRIPTS_DIR}"; \
    find "${SCRIPTS_DIR}" -maxdepth 1 -type f -name "*.py" -exec cp -f {} "${DST}/" \; ; \
    rm -rf /tmp/vcbs

RUN set -eux; \
    mkdir -p /tmp/x264 && cd /tmp/x264; \
    git clone https://code.videolan.org/videolan/x264.git; \
    cd x264; \
    ./configure --enable-static --bit-depth=all --extra-ldflags="-static"; \
    make -j"$(nproc)"; \
    cp x264 /usr/bin/; \
    chmod +x /usr/bin/x264; \
    rm -rf /tmp/x264

RUN set -eux; \
    TSMUXER_TAG="$(git ls-remote --refs --tags --sort=-version:refname https://github.com/justdan96/tsMuxer.git | awk -F 'refs/tags/' 'NF == 2 && $2 ~ /^[vV]?[0-9]+([.][0-9]+)+$/ { print $2; exit }')"; \
    test -n "$TSMUXER_TAG"; \
    TSMUXER_VER="${TSMUXER_TAG#v}"; \
    mkdir -p /tmp/tsmuxer && cd /tmp/tsmuxer; \
    wget "https://github.com/justdan96/tsMuxer/releases/download/${TSMUXER_TAG}/tsMuxer-${TSMUXER_VER}-linux.zip"; \
    unzip "tsMuxer-${TSMUXER_VER}-linux.zip"; \
    cp tsMuxeR /usr/bin/tsMuxeR; \
    chmod +x /usr/bin/tsMuxeR; \
    rm -rf /tmp/tsmuxer

RUN test -x /usr/bin/dovi_tool
RUN test -x /usr/bin/truehdd

ENV LD_PRELOAD=/usr/local/lib/libvapoursynth-script.so

WORKDIR /app
COPY src/ /app/src/
CMD ["python3", "-m", "src.main"]
