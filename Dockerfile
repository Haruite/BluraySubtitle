# 使用 Ubuntu 25.10 作为基础镜像
FROM ubuntu:25.10

# 避免交互式安装时的时区确认
ENV DEBIAN_FRONTEND=noninteractive

# 设置工作目录
WORKDIR /app

# 更新并安装系统依赖
# 包括 ffmpeg, mkvtoolnix, flac (1.5.0+) 以及 PyQt6 运行所需的 X11 相关库
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    ffmpeg \
    wget \
    fonts-wqy-microhei \
    flac \
    gedit \
    libegl1 \
    libopengl0 \
    libglib2.0-0 \
    libxkbcommon0 \
    libdbus-1-3 \
    libxcb-cursor0 \
    libxcb-icccm4 \
    libxcb-keysyms1 \
    libxcb-shape0 \
    libxcb-xinerama0 \
    libxcb-xinput0 \
    libxcb-render-util0  --fix-missing \
    && rm -rf /var/lib/apt/lists/*

RUN fc-cache -f -v

# 安装 mkvtoolnix
RUN wget -O /etc/apt/keyrings/gpg-pub-moritzbunkus.gpg https://mkvtoolnix.download/gpg-pub-moritzbunkus.gpg
RUN printf "deb [arch=amd64 signed-by=/etc/apt/keyrings/gpg-pub-moritzbunkus.gpg] https://mkvtoolnix.download/ubuntu/ questing main\ndeb-src [arch=amd64 signed-by=/etc/apt/keyrings/gpg-pub-moritzbunkus.gpg] https://mkvtoolnix.download/ubuntu/ questing main\n" > /etc/apt/sources.list.d/mkvtoolnix.download.list
RUN apt-get update && apt-get install -y mkvtoolnix mkvtoolnix-gui && rm -rf /var/lib/apt/lists/*

# 复制 mpv
COPY ./mpv-bundle/lib/ /usr/local/lib/mpv-bundle/
COPY ./mpv-bundle/bin/mpv /usr/local/bin/mpv
ENV LD_LIBRARY_PATH=/usr/local/lib/mpv-bundle:/usr/local/lib:/usr/lib
RUN chmod +x /usr/local/bin/mpv
RUN ldconfig

# 编译 VapourSynth
RUN apt-get update && apt-get install -y build-essential autoconf automake libtool pkg-config python3-dev cython3 libzimg-dev libmagick++-dev libtesseract-dev python3-sphinx && rm -rf /var/lib/apt/lists/*
COPY ./Packages/R57.A12.tar.gz /app/
WORKDIR /app/vapoursynth-classic-R57.A12
RUN tar zxvf /app/R57.A12.tar.gz --strip-components=1 && \
    ./autogen.sh && \
    ./configure && \
    make -j$(nproc) && \
    make install && \
    ldconfig
RUN ln -s /usr/local/lib/python3.13/site-packages/vapoursynth.so /usr/lib/python3/dist-packages/vapoursynth.so

# 复制 vs scripts
COPY ./VapourSynthScripts/ /usr/local/lib/python3.13/dist-packages/

# 复制 plugins
COPY ./plugins/ /app/plugins/

# 编译 lsmash
COPY ./Packages/v2.14.5.tar.gz /app/
WORKDIR /app
RUN tar zxvf v2.14.5.tar.gz
WORKDIR /app/l-smash-2.14.5
RUN ./configure --enable-shared && make -j$(nproc) && make install && ldconfig

# 编译 vsedit
RUN apt-get update && apt-get install -y \
    qt6-base-dev \
    qt6-base-dev-tools \
    qt6-5compat-dev \
    qt6-websockets-dev \
    qt6-declarative-dev \
    libgl-dev \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app/vsedit_build
COPY ./Packages/R19-mod-6.9.tar.gz /app/
RUN tar -zxvf /app/R19-mod-6.9.tar.gz --strip-components=1 && ldconfig
WORKDIR /app/vsedit_build/pro
ENV CPLUS_INCLUDE_PATH=/usr/local/include/vapoursynth
ENV LIBRARY_PATH=/usr/local/lib
ENV LD_LIBRARY_PATH=/usr/local/lib:/usr/lib:/lib
RUN qmake6 pro.pro CONFIG+=release && \
    make -j$(nproc) || make -j1
RUN BIN_PATH=$(find /app/vsedit_build -name "vsedit" -type f -executable | head -n 1) && \
    ln -s "$BIN_PATH" /usr/local/bin/vsedit 
ENV VAPOURSYNTH_PYTHON_PATH=/usr/lib/python3.13
ENV LD_LIBRARY_PATH=/usr/local/lib:/usr/local/lib/mpv-bundle:$LD_LIBRARY_PATH
ENV LD_PRELOAD=/usr/local/lib/libvapoursynth-script.so
RUN ldconfig

# 复制 x265
COPY x265 /usr/bin/
RUN chmod +x /usr/bin/x265

# 复制项目文件
COPY BluraySubtitle.py /app/

# 在 Ubuntu 25.10 中，pip 默认受 PEP 668 限制，建议使用虚拟环境或 --break-system-packages
RUN pip3 install --no-cache-dir --break-system-packages pycountry PyQt6 librosa

# 设置环境变量，指向 Linux 系统路径
ENV FFMPEG_PATH=/usr/bin/ffmpeg
ENV FFPROBE_PATH=/usr/bin/ffprobe
ENV FLAC_PATH=/usr/bin/flac
ENV PLUGIN_PATH=/app/plugins/

WORKDIR /app

RUN apt-get update && apt-get install -y libunwind8 libunwind-dev xdg-utils libgl1-mesa-dri libglx-mesa0 mesa-vulkan-drivers && rm -rf /var/lib/apt/lists/*

# 启动程序
CMD ["sh", "-c", "python3 BluraySubtitle.py"]
