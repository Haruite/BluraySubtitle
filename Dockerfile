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
    libxxhash-dev libfftw3-dev \
    && rm -rf /var/lib/apt/lists/*

RUN fc-cache -f >/dev/null 2>&1 || true

RUN set -eux; \
    ensure_meson_version() { \
      python3 -m pip install --break-system-packages --upgrade meson || python3 -m pip install --upgrade meson; \
      meson --version; \
    }; \
    ensure_meson_version; \
    python3 -m pip install --break-system-packages --upgrade cython || python3 -m pip install --upgrade cython

RUN set -eux; \
    XML="$(curl -fsSL https://mkvtoolnix.download/latest-release.xml)"; \
    VERSION="$(printf '%s' "$XML" | python3 -c "import re,sys; x=sys.stdin.read(); m=re.search(r'<latest-source>.*?<version>([^<]+)</version>', x, re.S); print((m.group(1) if m else '').strip())")"; \
    test -n "$VERSION"; \
    mkdir -p /tmp/mkv && cd /tmp/mkv; \
    curl -fsSL -o "mkvtoolnix_${VERSION}.orig.tar.xz" "https://mkvtoolnix.download/sources/mkvtoolnix-${VERSION}.tar.xz"; \
    tar xJf "mkvtoolnix_${VERSION}.orig.tar.xz"; \
    cd "mkvtoolnix-${VERSION}"; \
    cp -R packaging/debian debian; \
    ./debian/create_files.rb; \
    python3 -c "import base64; exec(base64.b64decode('aW1wb3J0IHJlCmZyb20gcGF0aGxpYiBpbXBvcnQgUGF0aAoKcnVsZXNfcGF0aCA9IFBhdGgoImRlYmlhbi9ydWxlcyIpCnRleHQgPSBydWxlc19wYXRoLnJlYWRfdGV4dChlbmNvZGluZz0idXRmLTgiLCBlcnJvcnM9InJlcGxhY2UiKS5zcGxpdGxpbmVzKGtlZXBlbmRzPVRydWUpCnN0YXJ0ID0gbmV4dCgoaSBmb3IgaSwgbGluZSBpbiBlbnVtZXJhdGUodGV4dCkgaWYgbGluZS5zdGFydHN3aXRoKCJvdmVycmlkZV9kaF9hdXRvX2J1aWxkOiIpKSwgTm9uZSkKaWYgc3RhcnQgaXMgTm9uZToKICAgIHJhaXNlIFN5c3RlbUV4aXQoImRlYmlhbi9ydWxlczogbWlzc2luZyBvdmVycmlkZV9kaF9hdXRvX2J1aWxkIikKZW5kID0gc3RhcnQgKyAxCndoaWxlIGVuZCA8IGxlbih0ZXh0KToKICAgIGxpbmUgPSB0ZXh0W2VuZF0KICAgIGlmIGxpbmUuc3RhcnRzd2l0aCgiXHQiKSBvciBsaW5lLnN0cmlwKCkgPT0gIiI6CiAgICAgICAgZW5kICs9IDEKICAgICAgICBjb250aW51ZQogICAgaWYgcmUubWF0Y2gociJeW15cdFxzXS4rPzpccyooIy4qKT8kIiwgbGluZSk6CiAgICAgICAgYnJlYWsKICAgIGVuZCArPSAxCnJlcGxhY2VtZW50ID0gWwogICAgIm92ZXJyaWRlX2RoX2F1dG9fYnVpbGQ6XG4iLAogICAgImlmZXEgKCwkKGZpbHRlciBub2NoZWNrLCQoREVCX0JVSUxEX09QVElPTlMpKSlcbiIsCiAgICAiXHRMQ19BTEw9QyAuL2RyYWtlIC1qJChzaGVsbCBucHJvYykgdGVzdHM6cnVuX3VuaXRcbiIsCiAgICAiZW5kaWZcbiIsCiAgICAiXG4iLAogICAgIlx0Li9kcmFrZSAtaiQoc2hlbGwgbnByb2MpXG4iLApdCnRleHRbc3RhcnQ6ZW5kXSA9IHJlcGxhY2VtZW50CnJ1bGVzX3BhdGgud3JpdGVfdGV4dCgiIi5qb2luKHRleHQpLCBlbmNvZGluZz0idXRmLTgiKQo=').decode())"; \
    dpkg-buildpackage -b --no-sign; \
    apt-get update; \
    apt-get install -y ../mkvtoolnix*.deb || (dpkg -i ../mkvtoolnix*.deb || true; apt-get -f install -y); \
    rm -rf /tmp/mkv

RUN set -eux; \
    mkdir -p /tmp/dovi && cd /tmp/dovi; \
    if ! command -v cargo >/dev/null 2>&1; then curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y; fi; \
    . /root/.cargo/env; \
    cargo install cargo-c; \
    git clone https://github.com/quietvoid/dovi_tool.git; \
    cd dovi_tool/dolby_vision; \
    cargo cinstall --release --prefix=/root/.local; \
    test "$(find /root/.local -name 'libdovi.so*' 2>/dev/null | wc -l)" -ge 1; \
    find /root/.local -name 'libdovi.so*' -exec cp -a {} /usr/local/lib/ \; ; \
    ldconfig; \
    rm -rf /tmp/dovi

RUN set -eux; \
    mkdir -p /tmp/mpv && cd /tmp/mpv; \
    git clone https://github.com/mpv-player/mpv-build.git; \
    cd mpv-build; \
    rm -rf mpv/build ffmpeg/build libass/build || true; \
    echo "--enable-libbluray" > ffmpeg_options; \
    echo "-Dlibbluray=enabled" > mpv_options; \
    export PKG_CONFIG_PATH="/root/.local/lib/x86_64-linux-gnu/pkgconfig:${PKG_CONFIG_PATH:-}"; \
    ./rebuild -j"$(nproc)"; \
    ./install; \
    ldconfig; \
    rm -rf /tmp/mpv

RUN set -eux; \
    mkdir -p /tmp/lsmash && cd /tmp/lsmash; \
    wget -O v2.14.5.tar.gz https://github.com/l-smash/l-smash/archive/refs/tags/v2.14.5.tar.gz; \
    tar zxvf v2.14.5.tar.gz; \
    cd l-smash-2.14.5; \
    ./configure --enable-shared; \
    make -j"$(nproc)"; \
    make install; \
    ldconfig; \
    rm -rf /tmp/lsmash

RUN set -eux; \
    mkdir -p /tmp/x265 && cd /tmp/x265; \
    wget https://github.com/msg7086/x265-Yuuki-Asuna/archive/refs/tags/Asuna-2.8.tar.gz; \
    tar zxvf Asuna-2.8.tar.gz; \
    cd x265-Yuuki-Asuna-Asuna-2.8/source; \
    sed -i 's/cmake_minimum_required(VERSION .*)/cmake_minimum_required(VERSION 3.5)/g' CMakeLists.txt; \
    sed -i '/cmake_policy(SET CMP0025 OLD)/d' CMakeLists.txt; \
    sed -i '/cmake_policy(SET CMP0054 OLD)/d' CMakeLists.txt; \
    sed -i '/cmake_minimum_required/d' CMakeLists.txt; \
    sed -i '1i cmake_minimum_required(VERSION 3.5)' CMakeLists.txt; \
    mkdir -p build && cd build; \
    cmake -G "Unix Makefiles" -DENABLE_SHARED=OFF -DHIGH_BIT_DEPTH=ON -DSTATIC_LINK_CRT=ON -DCMAKE_EXE_LINKER_FLAGS="-static" ..; \
    make -j"$(nproc)"; \
    cp x265 /usr/bin/x265; \
    chmod +x /usr/bin/x265; \
    rm -rf /tmp/x265

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
    mkdir -p /tmp/vsedit/vsedit_build && cd /tmp/vsedit/vsedit_build; \
    wget -O R19-mod-6.9.tar.gz https://github.com/YomikoR/VapourSynth-Editor/archive/refs/tags/R19-mod-6.9.tar.gz; \
    tar -zxvf R19-mod-6.9.tar.gz --strip-components=1; \
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

RUN mkdir -p /root/plugins /tmp/vsplugins

RUN set -eux; \
    export PATH=/root/.local/bin:$PATH; \
    export PKG_CONFIG_PATH="/usr/local/lib/pkgconfig:/usr/local/lib/x86_64-linux-gnu/pkgconfig:/usr/local/share/pkgconfig:/root/.local/lib/x86_64-linux-gnu/pkgconfig:${PKG_CONFIG_PATH:-}"; \
    cd /tmp/vsplugins; \
    git clone https://github.com/HomeOfAviSynthPlusEvolution/L-SMASH-Works.git; \
    cd L-SMASH-Works/VapourSynth; \
    AVCODEC_MAJOR="$(pkg-config --modversion libavcodec 2>/dev/null | cut -d. -f1 || true)"; \
    if [ -n "${AVCODEC_MAJOR}" ] && [ "${AVCODEC_MAJOR}" -lt 60 ]; then git -c advice.detachedHead=false checkout -q 70e19fb || true; fi; \
    python3 -c "import re;from pathlib import Path;p=Path('../common/decode.c'); d=p.read_text(encoding='utf-8',errors='replace') if p.exists() else ''; d=re.sub(r'^.*AV_PIX_FMT_D3D12\\\\\\\\n.*$','',d,flags=re.MULTILINE); d=re.sub(r'^#ifndef AV_PIX_FMT_D3D12\\\\n#define AV_PIX_FMT_D3D12 .*?\\\\n#endif\\\\n\\\\n?','',d,flags=re.MULTILINE); p.write_text(d,encoding='utf-8') if p.exists() else None"; \
    meson setup build; ninja -C build; \
    cp "$(find "$PWD" -maxdepth 3 -name libvslsmashsource.so -type f | head -n1)" /root/plugins/

RUN set -eux; \
    export PATH=/root/.local/bin:$PATH; \
    export PKG_CONFIG_PATH="/usr/local/lib/pkgconfig:/usr/local/lib/x86_64-linux-gnu/pkgconfig:/usr/local/share/pkgconfig:/root/.local/lib/x86_64-linux-gnu/pkgconfig:${PKG_CONFIG_PATH:-}"; \
    cd /tmp/vsplugins; \
    wget -O r9.tar.gz https://github.com/HomeOfVapourSynthEvolution/VapourSynth-EEDI3/archive/refs/tags/r9.tar.gz; \
    tar zxvf r9.tar.gz; \
    cd VapourSynth-EEDI3-r9; \
    find . -type f -name EEDI3.cpp -exec sed -i 's/std::max_align_t/max_align_t/g' {} +; \
    python3 -c "import re; c=open('meson.build',encoding='utf-8',errors='replace').read(); c=re.sub(r'incdir = include_directories\\(.*?check: true,.*?\\.stdout\\(\\)\\.strip\\(\\),\\s*\\)','incdir = \\'/usr/local/include/vapoursynth\\'',c,flags=re.DOTALL); open('meson.build','w',encoding='utf-8').write(c)"; \
    meson setup build; ninja -C build; cp build/eedi3m.so /root/plugins/

RUN set -eux; \
    export PATH=/root/.local/bin:$PATH; \
    export PKG_CONFIG_PATH="/usr/local/lib/pkgconfig:/usr/local/lib/x86_64-linux-gnu/pkgconfig:/usr/local/share/pkgconfig:/root/.local/lib/x86_64-linux-gnu/pkgconfig:${PKG_CONFIG_PATH:-}"; \
    cd /tmp/vsplugins; \
    wget -O r10.tar.gz https://github.com/HomeOfVapourSynthEvolution/VapourSynth-AddGrain/archive/refs/tags/r10.tar.gz; \
    tar zxvf r10.tar.gz; \
    cd VapourSynth-AddGrain-r10; \
    meson setup build; ninja -C build; \
    cp build/libaddgrain.so /root/plugins/

RUN set -eux; \
    export PATH=/root/.local/bin:$PATH; \
    export PKG_CONFIG_PATH="/usr/local/lib/pkgconfig:/usr/local/lib/x86_64-linux-gnu/pkgconfig:/usr/local/share/pkgconfig:/root/.local/lib/x86_64-linux-gnu/pkgconfig:${PKG_CONFIG_PATH:-}"; \
    cd /tmp/vsplugins; \
    wget -O assrender.zip https://github.com/AmusementClub/assrender/releases/download/0.38.3/assrender_linux-x64_v0.38.3.zip; \
    unzip -o assrender.zip; \
    cp libassrender.so /root/plugins/

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
    cp "$(find "$PWD" -maxdepth 3 -name libbilateral.so -type f | head -n1)" /root/plugins/

RUN set -eux; \
    export PATH=/root/.local/bin:$PATH; \
    export PKG_CONFIG_PATH="/usr/local/lib/pkgconfig:/usr/local/lib/x86_64-linux-gnu/pkgconfig:/usr/local/share/pkgconfig:/root/.local/lib/x86_64-linux-gnu/pkgconfig:${PKG_CONFIG_PATH:-}"; \
    cd /tmp/vsplugins; \
    wget -O r7.tar.gz https://github.com/HomeOfVapourSynthEvolution/VapourSynth-DFTTest/archive/refs/tags/r7.tar.gz; \
    tar zxvf r7.tar.gz; \
    cd VapourSynth-DFTTest-r7; \
    meson setup build; ninja -C build; \
    cp build/libdfttest.so /root/plugins/

RUN set -eux; \
    export PATH=/root/.local/bin:$PATH; \
    export PKG_CONFIG_PATH="/usr/local/lib/pkgconfig:/usr/local/lib/x86_64-linux-gnu/pkgconfig:/usr/local/share/pkgconfig:/root/.local/lib/x86_64-linux-gnu/pkgconfig:${PKG_CONFIG_PATH:-}"; \
    cd /tmp/vsplugins; \
    wget -O r7.1.tar.gz https://github.com/HomeOfVapourSynthEvolution/VapourSynth-EEDI2/archive/refs/tags/r7.1.tar.gz; \
    tar zxvf r7.1.tar.gz; \
    cd VapourSynth-EEDI2-r7.1; \
    meson setup build; ninja -C build; \
    cp build/libeedi2.so /root/plugins/

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
    cp "$PWD/.libs/libfmtconv.so" /root/plugins/

RUN set -eux; \
    export PATH=/root/.local/bin:$PATH; \
    export PKG_CONFIG_PATH="/usr/local/lib/pkgconfig:/usr/local/lib/x86_64-linux-gnu/pkgconfig:/usr/local/share/pkgconfig:/root/.local/lib/x86_64-linux-gnu/pkgconfig:${PKG_CONFIG_PATH:-}"; \
    cd /tmp/vsplugins; \
    wget -O R1.tar.gz https://github.com/vapoursynth/vs-removegrain/archive/refs/tags/R1.tar.gz; \
    tar zxvf R1.tar.gz; \
    cd vs-removegrain-R1/src; \
    g++ -shared -fPIC -O3 -Wall $(pkg-config --cflags vapoursynth) clense.cpp removegrainvs.cpp repairvs.cpp shared.cpp verticalcleaner.cpp -o libremovegrain.so; \
    cp libremovegrain.so /root/plugins/

RUN set -eux; \
    export PATH=/root/.local/bin:$PATH; \
    export PKG_CONFIG_PATH="/usr/local/lib/pkgconfig:/usr/local/lib/x86_64-linux-gnu/pkgconfig:/usr/local/share/pkgconfig:/root/.local/lib/x86_64-linux-gnu/pkgconfig:${PKG_CONFIG_PATH:-}"; \
    cd /tmp/vsplugins; \
    wget -O v0.1-fix.tar.gz https://github.com/HomeOfVapourSynthEvolution/VapourSynth-SangNomMod/archive/refs/tags/v0.1-fix.tar.gz; \
    tar zxvf v0.1-fix.tar.gz; \
    cd VapourSynth-SangNomMod-0.1-fix; \
    ./configure; \
    make -j"$(nproc)"; \
    cp "$(find "$PWD" -maxdepth 3 -name libsangnommod.so -type f | head -n1)" /root/plugins/

RUN set -eux; \
    export PATH=/root/.local/bin:$PATH; \
    export PKG_CONFIG_PATH="/usr/local/lib/pkgconfig:/usr/local/lib/x86_64-linux-gnu/pkgconfig:/usr/local/share/pkgconfig:/root/.local/lib/x86_64-linux-gnu/pkgconfig:${PKG_CONFIG_PATH:-}"; \
    cd /tmp/vsplugins; \
    wget -O 2.0.0.tar.gz https://github.com/Lypheo/vs-placebo/archive/refs/tags/2.0.0.tar.gz; \
    tar zxvf 2.0.0.tar.gz; \
    cd vs-placebo-2.0.0; \
    git clone https://github.com/sekrit-twc/libp2p.git; \
    meson setup build; ninja -C build; \
    cp "$(find "$PWD/build" -maxdepth 2 -name libvs_placebo.so -type f | head -n1)" /root/plugins/

RUN set -eux; \
    export PATH=/root/.local/bin:$PATH; \
    export PKG_CONFIG_PATH="/usr/local/lib/pkgconfig:/usr/local/lib/x86_64-linux-gnu/pkgconfig:/usr/local/share/pkgconfig:/root/.local/lib/x86_64-linux-gnu/pkgconfig:${PKG_CONFIG_PATH:-}"; \
    cd /tmp/vsplugins; \
    wget -O zsmooth.zip https://github.com/adworacz/zsmooth/releases/download/0.7/libzsmooth.x86_64-gnu.so.zip; \
    unzip -o zsmooth.zip; \
    mv libzsmooth.x86_64-gnu.so /root/plugins/

RUN set -eux; \
    export PATH=/root/.local/bin:$PATH; \
    export PKG_CONFIG_PATH="/usr/local/lib/pkgconfig:/usr/local/lib/x86_64-linux-gnu/pkgconfig:/usr/local/share/pkgconfig:/root/.local/lib/x86_64-linux-gnu/pkgconfig:${PKG_CONFIG_PATH:-}"; \
    cd /tmp/vsplugins; \
    wget -O v26.tar.gz https://github.com/dubhatervapoursynth/vapoursynth-mvtools/archive/refs/tags/v26.tar.gz; \
    tar zxvf v26.tar.gz; \
    cd vapoursynth-mvtools-26; \
    python3 -c "import re; c=open('meson.build',encoding='utf-8',errors='replace').read(); c=re.sub(r\"incdir\\s*=\\s*include_directories\\s*\\(\\s*'vapoursynth/include'\\s*\\)\",\"incdir = '/usr/local/include/vapoursynth'\",c,flags=re.DOTALL); open('meson.build','w',encoding='utf-8').write(c)"; \
    meson setup build; ninja -C build; \
    cp build/mvtools.so /root/plugins/

RUN set -eux; \
    export PATH=/root/.local/bin:$PATH; \
    export PKG_CONFIG_PATH="/usr/local/lib/pkgconfig:/usr/local/lib/x86_64-linux-gnu/pkgconfig:/usr/local/share/pkgconfig:/root/.local/lib/x86_64-linux-gnu/pkgconfig:${PKG_CONFIG_PATH:-}"; \
    wget -O /tmp/ispc.tar.gz https://github.com/ispc/ispc/releases/download/v1.23.0/ispc-v1.23.0-linux.tar.gz; \
    cd /tmp; tar -xvf ispc.tar.gz; \
    mv ispc-v1.23.0-linux/bin/ispc /usr/local/bin/; chmod +x /usr/local/bin/ispc

RUN set -eux; \
    export PATH=/root/.local/bin:$PATH; \
    export PKG_CONFIG_PATH="/usr/local/lib/pkgconfig:/usr/local/lib/x86_64-linux-gnu/pkgconfig:/usr/local/share/pkgconfig:/root/.local/lib/x86_64-linux-gnu/pkgconfig:${PKG_CONFIG_PATH:-}"; \
    cd /tmp/vsplugins; \
    wget -O v2.tar.gz https://github.com/AmusementClub/vs-nlm-ispc/archive/refs/tags/v2.tar.gz; \
    tar zxvf v2.tar.gz; \
    cd vs-nlm-ispc-2; mkdir -p build && cd build; \
    cmake ..; make -j"$(nproc)"; \
    cp "$(find "$PWD" -maxdepth 2 -name libvsnlm_ispc.so -type f | head -n1)" /root/plugins/; \
    rm -rf /tmp/vsplugins /tmp/ispc.tar.gz /tmp/ispc-v1.23.0-linux

RUN python3 -m pip install --break-system-packages --upgrade pycountry PyQt6 librosa || \
    python3 -m pip install --upgrade pycountry PyQt6 librosa

COPY VapourSynthScripts/ /app/VapourSynthScripts/

RUN set -eux; \
    SRC_ZIP="/app/VapourSynthScripts/VapourSynthScripts.zip"; \
    if [ ! -f "${SRC_ZIP}" ] && [ -f /app/VapourSynthScripts.zip ]; then SRC_ZIP="/app/VapourSynthScripts.zip"; fi; \
    if [ -f "${SRC_ZIP}" ]; then \
      PYV="$(python3 -c 'import sys; print("%d.%d" % (sys.version_info.major, sys.version_info.minor))')"; \
      DST="/usr/local/lib/python${PYV}/dist-packages"; \
      mkdir -p "${DST}"; \
      TMP="$(mktemp -d)"; \
      unzip -q -o "${SRC_ZIP}" -d "${TMP}"; \
      find "${TMP}" -maxdepth 1 -type f -name "*.py" -exec cp -f {} "${DST}/" \; ; \
      rm -rf "${TMP}"; \
    fi

ENV LD_PRELOAD=/usr/local/lib/libvapoursynth-script.so

WORKDIR /app
COPY src/ /app/src/
CMD ["python3", "-m", "src.main"]
