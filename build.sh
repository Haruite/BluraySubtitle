#!/usr/bin/env bash
if [[ "${BLURAY_NO_CRLF_FIX:-}" != "1" ]]; then
  if LC_ALL=C grep -q $'\r' "$0"; then
    tmp="$(mktemp)"
    trap 'rm -f "$tmp"' EXIT
    tr -d '\r' < "$0" > "$tmp"
    chmod +x "$tmp" || true
    exec env BLURAY_NO_CRLF_FIX=1 bash "$tmp" "$@"
  fi
fi
set -euo pipefail

log() { echo -e "\n[BluraySubtitle][SETUP] $*\n"; }
die() { echo -e "\n[BluraySubtitle][ERROR] $*\n" >&2; exit 1; }

log_blue() { printf "\n\033[34m[BluraySubtitle][SETUP] %s\033[0m\n\n" "$*"; }

log "推荐使用 Xshell 或 PuTTY 远程执行命令"

terminal_sane() {
  # 强制关闭：鼠标点击模式、鼠标移动跟踪、SGR坐标模式、备用屏幕
  printf '\e[?1000l\e[?1002l\e[?1003l\e[?1006l\e[?1049l' 2>/dev/null || true
  stty sane 2>/dev/null || true
}

tmux_run() {
  local title="$1"
  shift

  if [[ -z "${TMUX:-}" ]] || ! command -v tmux >/dev/null 2>&1; then
    "$@" || return $?
    return 0
  fi

  printf "\n[BluraySubtitle][SETUP] 执行：%s" "$title"
  local logfile
  logfile="$(mktemp -t bluraysubtitle.XXXXXX.log)"

  # 1. 开启面板。删除了原脚本中开启鼠标追踪的 printf 行，防止乱码。
  local pane_id
  pane_id="$(tmux split-window -v -p 35 -P -F "#{pane_id}" "bash -lc 'tail -n +1 -f \"${logfile}\"'")"
  tmux select-pane -t "$pane_id" -P "fg=white,bg=default" >/dev/null 2>&1 || true

  local task_pid=""

  # --- 终极清理函数 ---
  force_cleanup() {
    local sig_type=$1
    trap - INT TERM EXIT # 移除 trap 防止递归

    # A. 暴力清理残留进程：杀死该任务及其产生的所有子进程
    if [[ -n "$task_pid" ]]; then
      # 获取整个进程组并杀掉，确保 tee 和子命令一起死
      pkill -P "$task_pid" 2>/dev/null || true
      kill -9 "$task_pid" 2>/dev/null || true
    fi

    # B. 提取内容：在杀掉面板前，把最后 200 行抓出来
    echo -e "\n\033[33m>>> [任务中断/异常] 保留最后 200 行输出内容：\033[0m"
    tmux capture-pane -t "$pane_id" -p -S -200 2>/dev/null || true
    echo -e "\033[33m>>> [提取完成] \033[0m\n"

    # C. 销毁面板并重置终端状态
    tmux kill-pane -t "$pane_id" >/dev/null 2>&1 || true
    terminal_sane

    # 如果是 Ctrl+C，强制终止整个脚本运行
    [[ "$sig_type" == "INT" ]] && exit 130
  }

  # 绑定信号
  trap 'force_cleanup INT' INT
  trap 'force_cleanup TERM' TERM

  # 2. 启动任务：放入后台并获取 PID
  # 使用 ( ... ) 开启子 Shell 运行，确保能被整体杀掉
  (
    set +e
    "$@" 2>&1 | tee -a "$logfile" >/dev/null
    exit $?
  ) &
  task_pid=$!

  # 等待任务结束
  local ec=0
  wait "$task_pid" || ec=$?

  # 3. 正常/错误处理
  if [[ "$ec" -ne 0 ]]; then
    # 如果是非正常退出（报错），执行清理并保留输出
    force_cleanup ERROR
  else
    # 正常完成：正常杀掉面板，不重复打印
    tmux kill-pane -t "$pane_id" >/dev/null 2>&1 || true
    terminal_sane
    trap - INT TERM EXIT
  fi

  # 记录主日志
  if [[ -n "${BLURAY_MASTER_LOG:-}" ]]; then
    { echo "===== ${title} ====="; cat "$logfile"; echo; } >>"$BLURAY_MASTER_LOG" 2>/dev/null || true
  fi

  if [[ "$ec" == "0" ]]; then
    rm -f "$logfile" || true
    printf "\r\033[2K\033[34m[BluraySubtitle][SETUP] 执行：%s\033[0m\n\n" "$title"
    return 0
  fi

  return "$ec"
}

apt_update() {
  tmux_run "apt-get update" sudo apt-get update
}

apt_install() {
  tmux_run "apt-get install ${*}" sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y "$@"
}

apt_fix_broken() {
  tmux_run "apt-get -f install" sudo env DEBIAN_FRONTEND=noninteractive apt-get -f install -y
}

ensure_tmux_installed() {
  command -v tmux >/dev/null 2>&1 && return 0
  command -v apt-get >/dev/null 2>&1 || return 0
  command -v sudo >/dev/null 2>&1 || die "缺少 sudo"
  sudo -v
  sudo apt-get update -qq >/dev/null 2>&1 || die "apt-get update 失败（安装 tmux）"
  sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq tmux >/dev/null 2>&1 || die "tmux 安装失败"
}

ensure_sudo_once() {
  command -v sudo >/dev/null 2>&1 || die "缺少 sudo"
  if [[ ! -t 0 ]]; then
    return 0
  fi

  sudo -v

  (
    while true; do
      sudo -n true || exit 0
      sleep 60
    done
  ) 2>/dev/null &
  SUDO_KEEPALIVE_PID="$!"
  trap 'kill "${SUDO_KEEPALIVE_PID:-0}" >/dev/null 2>&1 || true' EXIT
}

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_DIR"

if [[ ! -f "$REPO_DIR/BluraySubtitle.py" ]]; then
  die "请在项目根目录运行（需要存在 BluraySubtitle.py）"
fi

is_remote_ssh() {
  [[ -n "${SSH_CONNECTION:-}" || -n "${SSH_CLIENT:-}" || -n "${SSH_TTY:-}" ]]
}

if [[ "${1:-}" != "--in-tmux" && -z "${TMUX:-}" && -t 1 ]]; then
  if is_remote_ssh; then
    ensure_tmux_installed
    args_escaped="$(printf '%q ' "$@")"
    exec tmux new-session -A -s BluraySubtitle "bash -lc \"bash \\\"$0\\\" --in-tmux ${args_escaped}; echo; echo '[BluraySubtitle][SETUP] 脚本已结束（可滚动查看上方输出，按 Ctrl+b d 退出 tmux）'; exec bash\"" \; set -g mouse off \; set -g status off \; set -g remain-on-exit off
  fi
fi
if [[ "${1:-}" == "--in-tmux" ]]; then
  shift || true
fi

ensure_sudo_once

require_supported_os() {
  if [[ ! -f /etc/os-release ]]; then
    die "未检测到 /etc/os-release，无法判断系统版本"
  fi

  . /etc/os-release || true
  log "检测到系统：${PRETTY_NAME:-unknown}"

  command -v dpkg >/dev/null 2>&1 || die "缺少 dpkg，无法比较系统版本"

  local id="${ID:-}"
  local version_id="${VERSION_ID:-}"

  if [[ "$id" == "ubuntu" ]]; then
    dpkg --compare-versions "$version_id" ge "22.04" || die "仅支持 Ubuntu >= 22.04（当前：$version_id）"
    return 0
  fi

  if [[ "$id" == "debian" ]]; then
    dpkg --compare-versions "$version_id" ge "12" || die "仅支持 Debian >= 12（当前：$version_id）"
    return 0
  fi

  die "仅支持 Ubuntu >= 22.04 或 Debian >= 12（当前：${PRETTY_NAME:-unknown}）"
}

repair_broken_apt_state() {
  log "检查并修复 APT/Dpkg 破损状态"
  sudo dpkg --configure -a || true
  apt_fix_broken || die "修复系统包依赖失败，请手动执行 sudo apt --fix-broken install"
}

ensure_meson_version() {
  local required_version="1.4.0"

  export PATH="$HOME/.local/bin:$PATH"

  if command -v meson >/dev/null 2>&1; then
    local current_version
    current_version="$(meson --version 2>/dev/null | head -n 1 || true)"
    if [[ -n "${current_version:-}" ]] && dpkg --compare-versions "$current_version" ge "$required_version"; then
      log "meson 版本满足要求（${current_version} >= ${required_version}），跳过升级"
      return 0
    fi
    log "检测到 meson 版本 (${current_version:-unknown}) 小于 ${required_version}，将升级"
  else
    log "未检测到 meson，将安装/升级到 >= ${required_version}"
  fi

  if ! python3 -m pip --version >/dev/null 2>&1; then
    apt_update
    apt_install python3-pip || die "安装 python3-pip 失败"
  fi

  local pip_cmd=("python3" "-m" "pip")
  if command -v pip >/dev/null 2>&1; then
    pip_cmd=("pip")
  fi

  if ! env PIP_DISABLE_PIP_VERSION_CHECK=1 "${pip_cmd[@]}" install --user --upgrade -q --progress-bar off meson --break-system-packages >/dev/null 2>&1; then
    log "当前 pip 不支持 --break-system-packages，回退到兼容参数重试"
    env PIP_DISABLE_PIP_VERSION_CHECK=1 "${pip_cmd[@]}" install --user --upgrade -q --progress-bar off meson >/dev/null 2>&1 || die "升级 meson 失败"
  fi
  export PATH="$HOME/.local/bin:$PATH"

  local new_version
  new_version="$(meson --version 2>/dev/null | head -n 1 || true)"
  if [[ -z "${new_version:-}" ]] || ! dpkg --compare-versions "$new_version" ge "$required_version"; then
    die "meson 升级后版本仍不满足要求（当前：${new_version:-unknown}，要求：>= ${required_version}）"
  fi

  log "meson 升级完成（当前：${new_version}）"
}

install_mkvtoolnix() {
  log "安装 mkvtoolnix / mkvtoolnix-gui（从源码编译 deb 并安装）"

  if [[ -x "/usr/bin/mkvmerge" ]]; then
    log "检测到 mkvtoolnix 已安装（/usr/bin/mkvmerge 存在），跳过编译安装"
    return 0
  fi

  command -v apt-get >/dev/null 2>&1 || die "缺少 apt-get"
  if ! command -v curl >/dev/null 2>&1; then
    apt_update
    apt_install curl
  fi
  if ! command -v dpkg-buildpackage >/dev/null 2>&1; then
    apt_update
    apt_install dpkg-dev
  fi

  log "安装编译所需基础工具"
  apt_update
  apt_install build-essential debhelper docbook-xsl fakeroot libx11-xcb-dev libglu1-mesa-dev \
  libboost-date-time-dev libboost-dev libboost-filesystem-dev libboost-math-dev libboost-regex-dev libboost-system-dev \
  libbz2-dev libcmark-dev libdvdread-dev libflac-dev libfmt-dev libgmp-dev libgtest-dev liblzo2-dev libmagic-dev \
  libogg-dev libpcre2-8-0 libpcre2-dev libqt6svg6-dev libvorbis-dev \
  nlohmann-json3-dev pkg-config po4a qt6-base-dev qt6-base-dev-tools qt6-multimedia-dev \
  rake ruby xsltproc zlib1g-dev unzip pkg-config libtool autoconf
  local version
  version="$(
    curl -s "https://mkvtoolnix.download/latest-release.xml" \
      | grep -oP '(?<=<version>).*?(?=</version>)' \
      | head -n 1
  )"
  if [[ -z "${version:-}" ]]; then
    die "获取 mkvtoolnix 最新版本失败"
  fi
  log "检测到 mkvtoolnix 最新版本：${version}"

  local build_dir
  build_dir="$(mktemp -d)"

  (
    cd "$build_dir" || exit 1
    log "下载源码包"
    curl -fsSL -o "mkvtoolnix_${version}.orig.tar.xz" "https://mkvtoolnix.download/sources/mkvtoolnix-${version}.tar.xz" || exit 1
    log "解压源码包"
    tar xJf "mkvtoolnix_${version}.orig.tar.xz" || exit 1

    cd "mkvtoolnix-${version}" || exit 1
    log "准备 debian 打包文件"
    cp -R packaging/debian debian || exit 1
    ./debian/create_files.rb 2>&1 | sed -E '/^Creating files for ubuntu /d;/ handling .*debian\/(control|rules)\.erb$/d' || exit 1

    log "修改 debian/rules（override_dh_auto_build 加入并行编译参数）"
    python3 - <<'PY' || exit 1
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
    raise SystemExit("debian/rules 中未找到 override_dh_auto_build:")

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
    "ifeq (,$(filter nocheck,$(DEB_BUILD_OPTIONS)))\n",
    "\tLC_ALL=C ./drake -j$(shell nproc) tests:run_unit\n",
    "endif\n",
    "\n",
    "\t./drake -j$(shell nproc)\n",
]

text[start:end] = replacement
rules_path.write_text("".join(text), encoding="utf-8")
PY

    log "开始编译 deb（dpkg-buildpackage）"
    tmux_run "dpkg-buildpackage" dpkg-buildpackage -b --no-sign || exit 1

    log "安装编译产物（源码上级目录的 mkvtoolnix*.deb）"
    mapfile -t debs < <(find .. -maxdepth 1 -type f -name "mkvtoolnix*.deb" -print | sort)
    if (( ${#debs[@]} == 0 )); then
      die "未找到 mkvtoolnix*.deb（编译可能失败）"
    fi

    log "一次性安装全部 mkvtoolnix deb（自动处理依赖顺序）"
    if ! apt_install "${debs[@]}"; then
      log "apt 本地 deb 安装失败，回退到 dpkg + 修复依赖"
      sudo dpkg -i "${debs[@]}" || true
      apt_fix_broken || exit 1
    fi
  ) || die "mkvtoolnix 编译/安装失败（如提示缺依赖，可手动补齐后重试）"

  rm -rf "$build_dir"

  log "mkvtoolnix 安装完成"
}

has_libdovi_runtime() {
  if sudo ldconfig -p 2>/dev/null | grep -qE '\blibdovi\.so(\.[0-9]+)*\b'; then
    return 0
  fi
  local any_file
  any_file="$(
    ls -1 \
      /usr/local/lib/libdovi.so* \
      /usr/local/lib64/libdovi.so* \
      /usr/local/lib/*/libdovi.so* \
      /usr/lib/libdovi.so* \
      /usr/lib64/libdovi.so* \
      /usr/lib/*/libdovi.so* \
      2>/dev/null | head -n 1 || true
  )"
  [[ -n "${any_file:-}" ]]
}

install_libdovi() {
  log "安装 libdovi（dovi_tool/dolby_vision）"

  if has_libdovi_runtime; then
    log "检测到 libdovi 已安装（ldconfig 已包含 libdovi.so），跳过"
    return 0
  fi

  local deps=(
    build-essential curl pkg-config git
    libssl-dev
  )

  local missing_deps=()
  for dep in "${deps[@]}"; do
    if ! dpkg-query -W -f='${Status}' "$dep" 2>/dev/null | grep -q "install ok installed"; then
      missing_deps+=("$dep")
    fi
  done
  if (( ${#missing_deps[@]} > 0 )); then
    apt_update
    apt_install "${missing_deps[@]}" || die "libdovi 依赖安装失败，请检查网络或包名"
  fi

  local build_dir
  build_dir="$(mktemp -d)"

  (
    cd "$build_dir" || exit 1

    log "配置 Rust 环境"
    if ! command -v cargo >/dev/null 2>&1; then
      tmux_run "下载并安装 rustup" bash -lc "curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y" || exit 1
    fi
    source "$HOME/.cargo/env" || exit 1

    log "安装 cargo-c"
    tmux_run "安装 cargo-c" cargo install cargo-c || exit 1

    log "编译并安装到 $HOME/.local"
    tmux_run "下载 dovi_tool" git clone https://github.com/quietvoid/dovi_tool.git || exit 1
    cd dovi_tool/dolby_vision || exit 1
    tmux_run "编译安装 dolby_vision" cargo cinstall --release --prefix="$HOME/.local" || exit 1

    local lib_dir
    lib_dir="$(
      find "$HOME/.local" -maxdepth 6 -name "libdovi.so*" -printf "%h\n" 2>/dev/null \
        | head -n 1
    )"
    if [[ -z "${lib_dir:-}" ]]; then
      exit 1
    fi

    log "安装运行库到 /usr/local/lib 并刷新 ldconfig"
    sudo cp -a "$lib_dir"/libdovi.so* /usr/local/lib/ || exit 1
    sudo ldconfig || exit 1
  ) || die "libdovi 编译/安装失败"

  rm -rf "$build_dir"

  if ! has_libdovi_runtime; then
    die "libdovi 安装完成但仍未被系统识别（未找到 libdovi.so*）"
  fi

  log "libdovi 安装完成"
}

install_mpv() {
  log "安装 mpv（编译并安装 mpv-build 及 dovi_tool）"

  local required_mpv_version="0.41.0"
  local is_ubuntu_2204="false"
  local is_debian_12="false"
  local needs_meson_prebuild="false"
  if [[ -f /etc/os-release ]]; then
    . /etc/os-release || true
    if [[ "${ID:-}" == "ubuntu" && "${VERSION_ID:-}" == "22.04" ]]; then
      is_ubuntu_2204="true"
      needs_meson_prebuild="true"
    fi
    if [[ "${ID:-}" == "debian" ]]; then
      if dpkg --compare-versions "${VERSION_ID:-0}" ge "12" && dpkg --compare-versions "${VERSION_ID:-0}" lt "13"; then
        is_debian_12="true"
        needs_meson_prebuild="true"
      fi
    fi
  fi

  if command -v mpv >/dev/null 2>&1; then
    local current_mpv_version
    current_mpv_version="$(mpv --version 2>/dev/null | head -n 1 | grep -oP 'mpv\s+v?\K[0-9]+(\.[0-9]+){1,2}' || true)"
    if [[ -n "${current_mpv_version:-}" ]] && dpkg --compare-versions "$current_mpv_version" ge "$required_mpv_version"; then
      if has_libdovi_runtime; then
        log "检测到 mpv 已安装且版本满足要求（${current_mpv_version} >= ${required_mpv_version}），跳过编译安装"
        return 0
      fi
      log "检测到 mpv 已安装但缺少 libdovi.so，尝试安装 libdovi"
      install_libdovi
      return 0
    fi
    log "检测到系统 mpv 版本较旧（${current_mpv_version:-unknown} < ${required_mpv_version}），将从源码编译升级"
  fi

  install_libdovi

  log "安装 mpv 编译所需系统依赖"
  local mpv_deps=(
    build-essential cmake meson ninja-build git pkg-config yasm nasm
    libssl-dev libjpeg-dev zlib1g-dev libavcodec-dev libavformat-dev
    libavutil-dev libswscale-dev libswresample-dev libavfilter-dev
    libass-dev libfribidi-dev libfreetype-dev libfontconfig1-dev
    libharfbuzz-dev libuchardet-dev libgl1-mesa-dev libvdpau-dev
    libva-dev libx11-dev libxext-dev libxv-dev libxinerama-dev
    libwayland-dev libxkbcommon-dev libegl1-mesa-dev libplacebo-dev
    libasound2-dev libpulse-dev libjack-dev libpipewire-0.3-dev
    libluajit-5.1-dev yt-dlp glslang-tools glslang-dev
    libspirv-cross-c-shared-dev libshaderc-dev autoconf
    automake libtool wayland-protocols libmujs-dev libbluray-dev
    libunwind-dev libxrandr-dev libxpresent-dev libxss-dev libdvdnav-dev
    libdvdread-dev libzimg-dev libarchive-dev librubberband-dev libsdl2-dev
    libdrm-dev libgbm-dev curl
  )

  if [[ -f /etc/os-release ]]; then
    . /etc/os-release || true
    if [[ "${ID:-}" == "ubuntu" && "${VERSION_ID:-}" == "22.04" ]]; then
      local filtered_deps=()
      local dep
      for dep in "${mpv_deps[@]}"; do
        if [[ "$dep" != "libshaderc-dev" ]]; then
          filtered_deps+=("$dep")
        fi
      done
      mpv_deps=("${filtered_deps[@]}")
    fi
  fi

  local missing_deps=()
  for dep in "${mpv_deps[@]}"; do
    if ! dpkg-query -W -f='${Status}' "$dep" 2>/dev/null | grep -q "install ok installed"; then
      missing_deps+=("$dep")
    fi
  done

  if (( ${#missing_deps[@]} > 0 )); then
    apt_update
    apt_install "${missing_deps[@]}" || die "mpv 依赖安装失败，请检查网络或包名"
  fi

  if [[ "$needs_meson_prebuild" == "true" ]]; then
    ensure_meson_version
    if ! sudo python3 -m pip --version >/dev/null 2>&1; then
      apt_update
      apt_install python3-pip || die "安装 python3-pip 失败（root 环境）"
    fi
    if ! sudo env PIP_DISABLE_PIP_VERSION_CHECK=1 python3 -m pip install --upgrade -q --progress-bar off meson --break-system-packages >/dev/null 2>&1; then
      log "root 环境 pip 不支持 --break-system-packages，回退到兼容参数重试"
      sudo env PIP_DISABLE_PIP_VERSION_CHECK=1 python3 -m pip install --upgrade -q --progress-bar off meson >/dev/null 2>&1 || die "root 环境升级 meson 失败"
    fi
    export PATH="/usr/local/bin:$HOME/.local/bin:$PATH"
  fi

  local build_dir
  build_dir="$(mktemp -d)"

(
    cd "$build_dir" || exit 1

    log "编译 mpv-build"
    tmux_run "下载 mpv-build" git clone https://github.com/mpv-player/mpv-build.git || exit 1
    cd mpv-build || exit 1

    rm -rf mpv/build ffmpeg/build libass/build 2>/dev/null || true

    echo "--enable-libbluray" > ffmpeg_options || exit 1
    echo "-Dlibbluray=enabled" > mpv_options || exit 1
    if [[ "$is_ubuntu_2204" == "true" || "$is_debian_12" == "true" ]]; then
      log "检测到系统需要兼容模式（Ubuntu 22.04/Debian 12），禁用 mpv-build 内置 libplacebo 的 Vulkan/Shaderc 构建以保证 mpv 可编译"
      cat > libplacebo_options <<'EOF'
-Dvulkan=disabled
-Dshaderc=disabled
EOF
    fi

    export PKG_CONFIG_PATH="$HOME/.local/lib/x86_64-linux-gnu/pkgconfig:${PKG_CONFIG_PATH:-}"
    export PATH="/usr/local/bin:$HOME/.local/bin:$PATH"

    tmux_run "mpv-build rebuild" ./rebuild -j"$(nproc)" || exit 1
    tmux_run "mpv-build install" sudo env "PATH=$PATH" "PKG_CONFIG_PATH=${PKG_CONFIG_PATH:-}" ./install || exit 1
  ) || die "mpv 编译/安装失败"

  rm -rf "$build_dir"
  log "mpv 安装完成"
  if [[ "$needs_meson_prebuild" != "true" ]]; then
    ensure_meson_version
  fi
}

install_lsmash() {
  log "安装 lsmash（从源码编译并安装）"

  if sudo ldconfig -p 2>/dev/null | grep -qE '\bliblsmash\.so\b'; then
    log "检测到 lsmash 已安装（ldconfig 中存在 liblsmash.so），跳过编译安装"
    return 0
  fi

  local deps=(build-essential wget tar)
  local missing_deps=()
  for dep in "${deps[@]}"; do
    if ! dpkg-query -W -f='${Status}' "$dep" 2>/dev/null | grep -q "install ok installed"; then
      missing_deps+=("$dep")
    fi
  done
  if (( ${#missing_deps[@]} > 0 )); then
    apt_update
    apt_install "${missing_deps[@]}" || die "lsmash 依赖安装失败"
  fi

  local build_dir
  build_dir="$(mktemp -d)"

  (
    cd "$build_dir" || exit 1
    
    if [[ -f "$REPO_DIR/Packages/v2.14.5.tar.gz" ]]; then
      log "使用本地源码包：Packages/v2.14.5.tar.gz"
      cp "$REPO_DIR/Packages/v2.14.5.tar.gz" . || exit 1
    else
      log "本地源码包不存在，尝试在线下载"
      tmux_run "下载 lsmash v2.14.5" wget -O v2.14.5.tar.gz https://github.com/l-smash/l-smash/archive/refs/tags/v2.14.5.tar.gz || exit 1
    fi

    tmux_run "解压 lsmash v2.14.5" tar zxvf v2.14.5.tar.gz || exit 1
    cd l-smash-2.14.5 || exit 1
    
    log "配置与编译 lsmash"
    tmux_run "lsmash configure" ./configure --enable-shared || exit 1
    tmux_run "lsmash make" make -j"$(nproc)" || exit 1
    tmux_run "lsmash install" sudo make install || exit 1
    sudo ldconfig || exit 1
  ) || die "lsmash 编译/安装失败"

  rm -rf "$build_dir"
  log "lsmash 安装完成"
}

install_x265() {
  log "开始安装 x265 (Yuuki-Asuna 版)"

  # 如果已经存在则跳过
  if [[ -x "/usr/bin/x265" ]] || command -v x265 >/dev/null 2>&1; then
    log "检测到 x265 已存在，跳过编译。"
    return 0
  fi

  install_lsmash

  # 依赖安装
  local deps=(build-essential cmake git yasm nasm wget)
  apt_update
  apt_install "${deps[@]}" || die "x265 依赖安装失败"

  local build_dir
  build_dir="$(mktemp -d)"

  (
    cd "$build_dir" || exit 1
    log "下载 x265-Yuuki-Asuna 源码..."
    tmux_run "下载 x265 Asuna-2.8" wget https://github.com/msg7086/x265-Yuuki-Asuna/archive/refs/tags/Asuna-2.8.tar.gz || exit 1
    tmux_run "解压 x265 Asuna-2.8" tar zxvf Asuna-2.8.tar.gz || exit 1

    cd x265-Yuuki-Asuna-Asuna-2.8/source || exit 1

    # --- 针对 Ubuntu 26.04 (CMake 4.x) 的特殊处理 ---
    if grep -q "26.04" /etc/os-release; then
      log "检测到 Ubuntu 26.04，正在应用 CMake 4.x 兼容性补丁..."

      # 1. 强制提升最低版本要求到 3.5
      sed -i 's/cmake_minimum_required(VERSION .*)/cmake_minimum_required(VERSION 3.5)/g' CMakeLists.txt

      # 2. 移除 CMake 4.x 不再支持的 OLD 策略设置
      sed -i '/cmake_policy(SET CMP0025 OLD)/d' CMakeLists.txt
      sed -i '/cmake_policy(SET CMP0054 OLD)/d' CMakeLists.txt

      # 3. 修正 project() 声明顺序
      # 先删掉原有的 cmake_minimum_required 行（通常在第20行左右）防止重复
      sed -i '/cmake_minimum_required/d' CMakeLists.txt
      # 在文件最开头插入新的声明
      sed -i '1i cmake_minimum_required(VERSION 3.5)' CMakeLists.txt
    fi

    mkdir -p build && cd build || exit 1

    log "配置 CMake 项目..."
    tmux_run "x265 cmake" cmake -G "Unix Makefiles" \
          -DENABLE_SHARED=OFF \
          -DHIGH_BIT_DEPTH=ON \
          -DSTATIC_LINK_CRT=ON \
          -DCMAKE_EXE_LINKER_FLAGS="-static" \
          .. || exit 1

    log "正在编译 x265 (使用 $(nproc) 核心)..."
    tmux_run "x265 make" make -j"$(nproc)" || exit 1

    log "安装编译产物..."
    sudo cp x265 /usr/bin/x265 || exit 1
  ) || die "x265 编译或安装过程中出错"

  rm -rf "$build_dir"
  log "x265 安装成功！"
}

install_flac() {
  log "安装 flac（要求 >= 1.5.0，从源码编译并安装）"

  if [[ -x "/usr/bin/flac" ]] || command -v flac >/dev/null 2>&1; then
    local flac_bin
    flac_bin=$(command -v flac || echo "/usr/bin/flac")
    local flac_version
    flac_version=$("$flac_bin" --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -n 1)

    if [[ -n "$flac_version" ]]; then
      local lowest
      lowest=$(printf '%s\n' "1.5.0" "$flac_version" | sort -V | head -n1)
      if [[ "$lowest" == "$flac_version" && "$flac_version" != "1.5.0" ]]; then
        log "检测到 flac 版本 ($flac_version) 小于 1.5.0，将卸载旧版本并重新编译安装"
        sudo apt-get remove -y flac >/dev/null 2>&1 || true
        sudo rm -f "$flac_bin"
      else
        log "检测到 flac 已安装且版本 ($flac_version) >= 1.5.0，跳过编译安装"
        return 0
      fi
    else
      log "无法解析已安装的 flac 版本，尝试重新编译安装"
      sudo apt-get remove -y flac >/dev/null 2>&1 || true
      sudo rm -f "$flac_bin"
    fi
  fi

  local deps=(libogg-dev libtool-bin gettext wget tar xz-utils)
  local missing_deps=()
  for dep in "${deps[@]}"; do
    if ! dpkg-query -W -f='${Status}' "$dep" 2>/dev/null | grep -q "install ok installed"; then
      missing_deps+=("$dep")
    fi
  done
  if (( ${#missing_deps[@]} > 0 )); then
    apt_update
    apt_install "${missing_deps[@]}" || die "flac 依赖安装失败，请检查网络或包名"
  fi

  local build_dir
  build_dir="$(mktemp -d)"

  (
    cd "$build_dir" || exit 1
    log "下载 flac 源码包"
    tmux_run "下载 flac 1.5.0" wget https://github.com/xiph/flac/releases/download/1.5.0/flac-1.5.0.tar.xz || exit 1
    log "解压 flac 源码包"
    tmux_run "解压 flac 1.5.0" tar -xvf flac-1.5.0.tar.xz || exit 1
    
    cd flac-1.5.0 || exit 1
    
    log "配置与编译 flac"
    tmux_run "flac autogen" ./autogen.sh || exit 1
    tmux_run "flac configure" ./configure --enable-static --enable-shared --enable-64-bit-words || exit 1
    tmux_run "flac make" make -j"$(nproc)" || exit 1
    tmux_run "flac install" sudo make install || exit 1
    sudo ldconfig || exit 1
    sudo ln -sf /usr/local/bin/flac /usr/bin/flac || exit 1
  ) || die "flac 编译/安装失败"

  rm -rf "$build_dir"
  log "flac 安装完成"
}

install_zimg_latest() {
  local header=""
  if [[ -f /usr/local/include/zimg.h ]]; then
    header="/usr/local/include/zimg.h"
  elif [[ -f /usr/include/zimg.h ]]; then
    header="/usr/include/zimg.h"
  fi

  if [[ -n "${header:-}" ]] && grep -q "ZIMG_TRANSFER_ST428" "$header"; then
    log "检测到 zimg 已包含 ZIMG_TRANSFER_ST428，跳过升级"
    return 0
  fi

  local deps=(build-essential autoconf automake libtool pkg-config git)
  local missing_deps=()
  local dep
  for dep in "${deps[@]}"; do
    if ! dpkg-query -W -f='${Status}' "$dep" 2>/dev/null | grep -q "install ok installed"; then
      missing_deps+=("$dep")
    fi
  done
  if (( ${#missing_deps[@]} > 0 )); then
    apt_update
    apt_install "${missing_deps[@]}" || die "zimg 编译依赖安装失败"
  fi

  log "当前 zimg 版本过低（缺少 ZIMG_TRANSFER_ST428），开始编译安装最新版 zimg..."

  local build_dir
  build_dir="$(mktemp -d)"
  (
    cd "$build_dir" || exit 1
    tmux_run "下载 zimg" git clone --depth 1 --recursive https://github.com/sekrit-twc/zimg.git . || exit 1
    tmux_run "zimg autogen" ./autogen.sh || exit 1
    tmux_run "zimg configure" ./configure --prefix=/usr/local || exit 1
    tmux_run "zimg make" make -j"$(nproc)" || exit 1
    tmux_run "zimg install" sudo make install || exit 1
  ) || die "zimg 编译/安装失败"
  rm -rf "$build_dir"
  sudo ldconfig
  log "最新版 zimg 安装完成"
}

install_vapoursynth() {
  log "安装 VapourSynth（从源码编译并安装）"

  log "检查并升级 Cython 以支持 VapourSynth 编译"
  if ! python3 -m pip --version >/dev/null 2>&1; then
    apt_update
    apt_install python3-pip || die "安装 python3-pip 失败"
  fi
  if ! python3 -m pip install --user --upgrade cython --break-system-packages >/dev/null 2>&1; then
    log "当前 pip 不支持 --break-system-packages，回退到兼容参数重试"
    python3 -m pip install --user --upgrade cython >/dev/null 2>&1 || die "Cython 升级失败"
  fi
  export PATH="$HOME/.local/bin:$PATH"

  # VapourSynth-classic 可能没有生成 vspipe 或者生成在 /usr/local/bin 下
  # 放宽检测条件：检查库文件或执行文件是否存在即可
  if [[ -f "/usr/local/lib/libvapoursynth.so" ]] || sudo ldconfig -p 2>/dev/null | grep -qE '\blibvapoursynth\.so\b'; then
    log "检测到 VapourSynth 已安装（找到 libvapoursynth.so），跳过编译安装"
    return 0
  fi

  install_zimg_latest

  # 验证 Cython 版本是否 >= 3.0
  local cython_cmd="cython"
  if ! command -v cython >/dev/null 2>&1; then
    if command -v cython3 >/dev/null 2>&1; then
      cython_cmd="cython3"
    else
      die "未找到 cython/cython3"
    fi
  fi
  CYTHON_V=$("$cython_cmd" --version 2>&1 | grep -oP '\d+\.\d+\.\d+' | head -n 1)
  if [[ "${CYTHON_V%%.*}" -lt 3 ]]; then
      die "Cython 版本过低 ($CYTHON_V)，编译 VapourSynth 需要 3.0.0 以上版本"
  fi

  local deps=(build-essential autoconf automake libtool pkg-config python3-dev cython3 libzimg-dev libmagick++-dev libtesseract-dev python3-sphinx wget tar)
  local missing_deps=()
  for dep in "${deps[@]}"; do
    if ! dpkg-query -W -f='${Status}' "$dep" 2>/dev/null | grep -q "install ok installed"; then
      missing_deps+=("$dep")
    fi
  done
  if (( ${#missing_deps[@]} > 0 )); then
    apt_update
    apt_install "${missing_deps[@]}" || die "VapourSynth 依赖安装失败"
  fi

  local build_dir
  build_dir="$(mktemp -d)"

  (
    cd "$build_dir" || exit 1
    
    if [[ -f "$REPO_DIR/Packages/R57.A12.tar.gz" ]]; then
      log "使用本地源码包：Packages/R57.A12.tar.gz"
      cp "$REPO_DIR/Packages/R57.A12.tar.gz" . || exit 1
    else
      log "本地源码包不存在，尝试在线下载"
      # 原提供的链接会报 404，这里替换为 Github 归档源码链接，解压后目录名一致
      tmux_run "下载 VapourSynth R57.A12" wget -O R57.A12.tar.gz https://github.com/AmusementClub/vapoursynth-classic/archive/refs/tags/R57.A12.tar.gz || exit 1
    fi

    log "解压 VapourSynth 源码包"
    tmux_run "解压 VapourSynth R57.A12" tar zxvf R57.A12.tar.gz || exit 1
    cd vapoursynth-classic-R57.A12 || exit 1

    # --- 针对 Ubuntu 26.04 (新版 FFmpeg) 的补丁判断 ---
    if grep -q "26.04" /etc/os-release; then
      log "检测到 Ubuntu 26.04，正在应用 FFmpeg 7.0+ API 兼容性补丁..."

      # 1. 修复 avcodec_close 被移除的问题
      # 将 avcodec_close(d->avctx); 替换为 avcodec_free_context(&(d->avctx));
      if [ -f "src/filters/subtext/image.cpp" ]; then
        sed -i 's/avcodec_close(\(.*\));/avcodec_free_context(\&\(\1\));/g' src/filters/subtext/image.cpp
      fi

      # 2. 针对 GCC 15 可能存在的严格 C++ 警告，增强 CXXFLAGS
      export CXXFLAGS="${CXXFLAGS:-} -fpermissive -Wno-error=narrowing"
    fi
    
    log "配置与编译 VapourSynth"
    tmux_run "VapourSynth autogen" ./autogen.sh || exit 1
    tmux_run "VapourSynth configure" ./configure CXXFLAGS="-O3 -fpermissive" || die "VapourSynth 配置失败"
    tmux_run "VapourSynth make" make -j"$(nproc)" || exit 1
    tmux_run "VapourSynth install" sudo make install || exit 1
    sudo ldconfig || exit 1
    
    local py_ver
    py_ver=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    
    log "创建 vapoursynth.so 软链接 (针对 Python ${py_ver})"
    sudo mkdir -p /usr/lib/python3/dist-packages
    sudo ln -sf "/usr/local/lib/python${py_ver}/site-packages/vapoursynth.so" "/usr/lib/python3/dist-packages/vapoursynth.so" || exit 1
  ) || die "VapourSynth 编译/安装失败"

  rm -rf "$build_dir"
  log "VapourSynth 安装完成"
}

install_vapoursynth_scripts() {
  local src_dir="$REPO_DIR/VapourSynthScripts"
  if [[ ! -d "$src_dir" ]]; then
    log "未找到 VapourSynthScripts 目录，跳过安装脚本"
    return 0
  fi

  local py_ver
  py_ver="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
  local dst_dir="/usr/local/lib/python${py_ver}/dist-packages"
  sudo mkdir -p "$dst_dir"

  local copied=0
  while IFS= read -r -d '' file; do
    sudo cp -f "$file" "$dst_dir/" || die "复制脚本失败：$file"
    copied=$((copied + 1))
  done < <(find "$src_dir" -maxdepth 1 -type f -name "*.py" -print0)

  log "已复制 VapourSynthScripts 脚本到 ${dst_dir}（数量：${copied}）"
}

install_vapoursynth_editor() {
  log "安装 vapoursynth-editor (vsedit)（从源码编译并安装）"

  if [[ -x "/usr/local/bin/vsedit-bin" ]] || command -v vsedit-bin >/dev/null 2>&1; then
    log "检测到 vsedit 已安装（存在 vsedit-bin），跳过编译安装"
    return 0
  fi

  local deps=(qt6-base-dev qt6-base-dev-tools qt6-5compat-dev qt6-websockets-dev qt6-declarative-dev libgl-dev wget tar)
  if [[ -f /etc/os-release ]]; then
    . /etc/os-release || true
    if [[ "${ID:-}" == "ubuntu" && "${VERSION_ID:-}" == "22.04" ]]; then
      deps=(qt6-base-dev qt6-base-dev-tools libqt6core5compat6-dev libqt6websockets6-dev qt6-declarative-dev libgl-dev wget tar)
    fi
  fi

  local missing_deps=()
  for dep in "${deps[@]}"; do
    if ! dpkg-query -W -f='${Status}' "$dep" 2>/dev/null | grep -q "install ok installed"; then
      missing_deps+=("$dep")
    fi
  done
  if (( ${#missing_deps[@]} > 0 )); then
    apt_update
    apt_install "${missing_deps[@]}" || die "vsedit 依赖安装失败"
  fi

  local build_dir
  build_dir="$(mktemp -d)"

  (
    cd "$build_dir" || exit 1
    mkdir -p vsedit_build
    cd vsedit_build || exit 1

    if [[ -f "$REPO_DIR/Packages/R19-mod-6.9.tar.gz" ]]; then
      log "使用本地源码包：Packages/R19-mod-6.9.tar.gz"
      cp "$REPO_DIR/Packages/R19-mod-6.9.tar.gz" . || exit 1
    else
      log "本地源码包不存在，尝试在线下载"
      tmux_run "下载 vsedit R19-mod-6.9" wget -O R19-mod-6.9.tar.gz https://github.com/Yurihaia/vapoursynth-editor/archive/refs/tags/R19-mod-6.9.tar.gz || exit 1
    fi

    log "解压 vsedit 源码包"
    tmux_run "解压 vsedit 源码包" tar -zxvf R19-mod-6.9.tar.gz --strip-components=1 || exit 1
    sudo ldconfig

    if [[ -f "resources/vsedit.png" ]]; then
      sudo mkdir -p /usr/local/share/icons/hicolor/256x256/apps
      sudo cp -f "resources/vsedit.png" /usr/local/share/icons/hicolor/256x256/apps/vsedit.png || exit 1
    fi
    if [[ -f "resources/vsedit.svg" ]]; then
      sudo mkdir -p /usr/local/share/icons/hicolor/scalable/apps
      sudo cp -f "resources/vsedit.svg" /usr/local/share/icons/hicolor/scalable/apps/vsedit.svg || exit 1
    fi

    cd pro || exit 1
    
    export CPLUS_INCLUDE_PATH=/usr/local/include/vapoursynth
    export LIBRARY_PATH=/usr/local/lib
    export LD_LIBRARY_PATH=/usr/local/lib:/usr/lib:/lib

    log "配置并编译 vsedit (qmake6)"
    qmake6 pro.pro CONFIG+=release 2>&1 | sed '/^Info: creating stash file /d' || exit 1
    tmux_run "vsedit make" bash -lc "make -j\"$(nproc)\" || make -j1" || exit 1

    log "查找编译生成的 vsedit 并建立软链接"
    local bin_path
    bin_path=$(find "$build_dir/vsedit_build" -name "vsedit" -type f -executable | head -n 1)
    
    if [[ -z "$bin_path" ]]; then
      die "未找到编译生成的 vsedit 执行文件"
    fi

    # 将真实二进制文件复制为 vsedit-bin
    sudo cp "$bin_path" /usr/local/bin/vsedit-bin || exit 1
    sudo chmod +x /usr/local/bin/vsedit-bin
    
    local py_ver
    py_ver=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    
    # 创建 vsedit 包装器脚本，自动注入运行所需的环境变量（解决 Failed to get VSScript API 的问题）
    log "创建 vsedit 包装器启动脚本"
    sudo tee /usr/local/bin/vsedit > /dev/null <<EOF
#!/bin/bash
export VAPOURSYNTH_PYTHON_PATH=/usr/lib/python${py_ver}
export LD_LIBRARY_PATH=/usr/local/lib:\$LD_LIBRARY_PATH
export LD_PRELOAD=/usr/local/lib/libvapoursynth-script.so
exec /usr/local/bin/vsedit-bin "\$@"
EOF
    sudo chmod +x /usr/local/bin/vsedit
    
    log "vsedit 包装器创建成功。你现在可以直接运行 vsedit 了。"
  ) || die "vsedit 编译/安装失败"

  rm -rf "$build_dir"
  log "vapoursynth-editor (vsedit) 安装完成"
}

install_libplacebo_latest() {
    local required_version="6.338.0"
    if command -v pkg-config >/dev/null 2>&1 && pkg-config --exists libplacebo; then
        local current_version
        current_version="$(pkg-config --modversion libplacebo 2>/dev/null | head -n 1 || true)"
        if [[ -n "${current_version:-}" ]] && dpkg --compare-versions "$current_version" ge "$required_version"; then
            log "libplacebo 版本满足要求（${current_version} >= ${required_version}），跳过编译"
            return 0
        fi
        log "检测到 libplacebo 版本过低（${current_version:-unknown} < ${required_version}），将升级"
    elif sudo ldconfig -p 2>/dev/null | grep -qE '\blibplacebo\.so\b'; then
        log "检测到 libplacebo 已存在但无法获取版本（缺少 pkg-config 版本信息），将重装以确保兼容 vs-placebo"
    fi

    log "正在以物理隔离模式编译 libplacebo..."

    # 再次确保环境变量在函数内部也是安全的
    local py_ver
    py_ver=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    local safe_pythonpath="${HOME}/.local/lib/python${py_ver}/site-packages:${PYTHONPATH:-}"
    local shaderc_opt="-Dshaderc=enabled"
    if [[ -f /etc/os-release ]]; then
      . /etc/os-release || true
      if [[ "${ID:-}" == "debian" ]] && dpkg --compare-versions "${VERSION_ID:-0}" ge "12" && dpkg --compare-versions "${VERSION_ID:-0}" lt "13"; then
        shaderc_opt="-Dshaderc=disabled"
        log "检测到 Debian 12，启用 libplacebo 兼容参数：禁用 shaderc"
      fi
    fi

    local build_dir
    build_dir="$(mktemp -d)"
    (
        cd "$build_dir" || exit 1
        tmux_run "下载 libplacebo v6.338.0" git clone --recursive --depth 1 --branch v6.338.0 https://code.videolan.org/videolan/libplacebo.git .

        rm -rf build

        # 使用安全定义的变量运行配置
        tmux_run "libplacebo meson setup" env PYTHONPATH="$safe_pythonpath" python3 -m mesonbuild.mesonmain setup build \
            --buildtype release \
            --prefix /usr/local \
            "$shaderc_opt" \
            -Dvulkan=enabled \
            -Dtests=false \
            -Dbench=false \
            -Ddemos=false || exit 1

        # 编译与安装
        tmux_run "libplacebo ninja" env PYTHONPATH="$safe_pythonpath" ninja -C build || exit 1
        tmux_run "libplacebo install" sudo env PYTHONPATH="$safe_pythonpath" ninja -C build install || exit 1
    ) || die "libplacebo 编译/安装失败"
    rm -rf "$build_dir"
    sudo ldconfig

    if ! command -v pkg-config >/dev/null 2>&1 || ! pkg-config --exists libplacebo; then
      die "libplacebo 安装后未被 pkg-config 识别"
    fi
}

build_vs_plugins() {
  log "编译/安装 VapourSynth 插件到 ~/plugins"

  local plugins_dir="$HOME/plugins"
  mkdir -p "$plugins_dir"

  ensure_meson_version
  export PATH="$HOME/.local/bin:$PATH"

  local deps=(
    build-essential git wget tar unzip sed
    meson ninja-build cmake
    autoconf automake libtool pkg-config
    libxxhash-dev
    python3 python3-pip
  )
  local missing_deps=()
  for dep in "${deps[@]}"; do
    if ! dpkg-query -W -f='${Status}' "$dep" 2>/dev/null | grep -q "install ok installed"; then
      missing_deps+=("$dep")
    fi
  done
  if (( ${#missing_deps[@]} > 0 )); then
    apt_update
    apt_install "${missing_deps[@]}" || die "VS 插件依赖安装失败"
  fi

  local build_dir
  build_dir="$(mktemp -d)"

  (
    cd "$build_dir" || exit 1

    if [[ ! -f "$plugins_dir/libvslsmashsource.so" ]]; then
      log "编译 L-SMASH-Works (VapourSynth)"
      cd "$HOME" || exit 1
      tmux_run "下载 L-SMASH-Works" git clone https://github.com/HomeOfAviSynthPlusEvolution/L-SMASH-Works.git || exit 1
      cd L-SMASH-Works/VapourSynth || exit 1
      local need_compat="false"
      if [[ -f /etc/os-release ]]; then
        . /etc/os-release || true
        if [[ "${ID:-}" == "ubuntu" && "${VERSION_ID:-}" == "22.04" ]]; then
          need_compat="true"
        fi
        if [[ "${ID:-}" == "debian" && "${VERSION_ID:-}" == "12" ]]; then
          need_compat="true"
        fi
      fi
      if command -v pkg-config >/dev/null 2>&1 && pkg-config --exists libavcodec; then
        local avcodec_ver avcodec_major
        avcodec_ver="$(pkg-config --modversion libavcodec 2>/dev/null | head -n 1 || true)"
        avcodec_major="${avcodec_ver%%.*}"
        if [[ "$avcodec_major" =~ ^[0-9]+$ ]] && (( avcodec_major < 60 )); then
          need_compat="true"
        fi
      fi
      if [[ "$need_compat" == "true" ]]; then
        log "检测到旧版 FFmpeg API（或系统需兼容模式），回退 L-SMASH-Works 到兼容提交"
        tmux_run "L-SMASH-Works git checkout" bash -lc "git checkout . && git -c advice.detachedHead=false checkout -q 70e19fb" || log "警告：Git 回退失败，尝试继续使用当前版本"
      fi

      # 2. 保留并执行你原有的 D3D12 宏补丁逻辑 (无论哪个版本都加上，防止万一)
      local decode_file="../common/decode.c"
      if [[ -f "$decode_file" ]]; then
          python3 - <<'PY' || exit 1
import re
from pathlib import Path
path = Path("../common/decode.c")
data = path.read_text(encoding="utf-8", errors="replace")
data = re.sub(r"^.*AV_PIX_FMT_D3D12\\\\n.*$", "", data, flags=re.MULTILINE)
data = re.sub(r"^#ifndef AV_PIX_FMT_D3D12\\n#define AV_PIX_FMT_D3D12 .*?\\n#endif\\n\\n?", "", data, flags=re.MULTILINE)

header_paths = [
    Path("/usr/include/x86_64-linux-gnu/libavutil/pixfmt.h"),
    Path("/usr/include/libavutil/pixfmt.h"),
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
path.write_text(data, encoding="utf-8")
PY
      fi
      rm -rf build
      tmux_run "L-SMASH-Works meson setup" meson setup build || exit 1
      tmux_run "L-SMASH-Works ninja" ninja -C build || exit 1
      local out
      out="$(find "$PWD" -maxdepth 3 -name "libvslsmashsource.so" -type f | head -n 1)"
      [[ -n "${out:-}" ]] || exit 1
      cp "$out" "$plugins_dir/" || exit 1
      cd "$build_dir" || exit 1
    else
      log "已存在 libvslsmashsource.so，跳过"
    fi

    if [[ ! -f "$plugins_dir/eedi3m.so" ]]; then
      log "编译 VapourSynth-EEDI3 (r9)"
      cd "$HOME" || exit 1
      tmux_run "下载 EEDI3 r9" wget -O r9.tar.gz https://github.com/HomeOfVapourSynthEvolution/VapourSynth-EEDI3/archive/refs/tags/r9.tar.gz || exit 1
      tmux_run "解压 EEDI3 r9" tar zxvf r9.tar.gz || exit 1
      cd VapourSynth-EEDI3-r9/ || exit 1
      log "修复 EEDI3 的 std::max_align_t 编译兼容性问题"
      find . -type f -name "EEDI3.cpp" -exec sed -i 's/std::max_align_t/max_align_t/g' {} +
      python3 - <<'PY' || exit 1
import re
content = open('meson.build', encoding='utf-8', errors='replace').read()
pattern = r"incdir = include_directories\(.*?check: true,.*?\.stdout\(\)\.strip\(\),\s*\)"
new_content = re.sub(pattern, "incdir = '/usr/local/include/vapoursynth'", content, flags=re.DOTALL)
open('meson.build', 'w', encoding='utf-8').write(new_content)
PY
      rm -rf build
      tmux_run "EEDI3 meson setup" meson setup build || exit 1
      tmux_run "EEDI3 ninja" ninja -C build || exit 1
      cp build/eedi3m.so "$plugins_dir/" || exit 1
      cd "$build_dir" || exit 1
    else
      log "已存在 eedi3m.so，跳过"
    fi

    if [[ ! -f "$plugins_dir/libaddgrain.so" ]]; then
      log "编译 VapourSynth-AddGrain (r10)"
      cd "$HOME" || exit 1
      tmux_run "下载 AddGrain r10" wget -O r10.tar.gz https://github.com/HomeOfVapourSynthEvolution/VapourSynth-AddGrain/archive/refs/tags/r10.tar.gz || exit 1
      tmux_run "解压 AddGrain r10" tar zxvf r10.tar.gz || exit 1
      cd VapourSynth-AddGrain-r10/ || exit 1
      tmux_run "AddGrain meson setup" meson setup build || exit 1
      tmux_run "AddGrain ninja" ninja -C build || exit 1
      cp build/libaddgrain.so "$plugins_dir/" || exit 1
      cd "$build_dir" || exit 1
    else
      log "已存在 libaddgrain.so，跳过"
    fi

    if [[ ! -f "$plugins_dir/libassrender.so" ]]; then
      log "安装 assrender (0.38.3)"
      cd "$HOME" || exit 1
      tmux_run "下载 assrender 0.38.3" wget -O assrender_linux-x64_v0.38.3.zip https://github.com/AmusementClub/assrender/releases/download/0.38.3/assrender_linux-x64_v0.38.3.zip || exit 1
      tmux_run "解压 assrender 0.38.3" unzip -o assrender_linux-x64_v0.38.3.zip || exit 1
      cp libassrender.so "$plugins_dir/" || exit 1
      cd "$build_dir" || exit 1
    else
      log "已存在 libassrender.so，跳过"
    fi

    if [[ ! -f "$plugins_dir/libbilateral.so" ]]; then
      log "编译 VapourSynth-Bilateral (r3)"
      cd "$HOME" || exit 1
      tmux_run "下载 Bilateral r3" wget -O r3.tar.gz https://github.com/HomeOfVapourSynthEvolution/VapourSynth-Bilateral/archive/refs/tags/r3.tar.gz || exit 1
      tmux_run "解压 Bilateral r3" tar zxvf r3.tar.gz || exit 1
      cd VapourSynth-Bilateral-r3/ || exit 1
      chmod +x configure || exit 1
      tmux_run "Bilateral configure" ./configure || exit 1
      tmux_run "Bilateral make" make -j"$(nproc)" || exit 1
      local out
      out="$(find "$PWD" -maxdepth 3 -name "libbilateral.so" -type f | head -n 1)"
      [[ -n "${out:-}" ]] || exit 1
      cp "$out" "$plugins_dir/" || exit 1
      cd "$build_dir" || exit 1
    else
      log "已存在 libbilateral.so，跳过"
    fi

    if [[ ! -f "$plugins_dir/libdfttest.so" ]]; then
      log "编译 VapourSynth-DFTTest (r7)"
      cd "$HOME" || exit 1
      tmux_run "下载 DFTTest r7" wget -O r7.tar.gz https://github.com/HomeOfVapourSynthEvolution/VapourSynth-DFTTest/archive/refs/tags/r7.tar.gz || exit 1
      tmux_run "解压 DFTTest r7" tar zxvf r7.tar.gz || exit 1
      cd VapourSynth-DFTTest-r7/ || exit 1
      log "正在安装 DFTTest 编译依赖: libfftw3-dev..."
      apt_install libfftw3-dev
      tmux_run "DFTTest meson setup" meson setup build || exit 1
      tmux_run "DFTTest ninja" ninja -C build || exit 1
      cp build/libdfttest.so "$plugins_dir/" || exit 1
      cd "$build_dir" || exit 1
    else
      log "已存在 libdfttest.so，跳过"
    fi

    if [[ ! -f "$plugins_dir/libeedi2.so" ]]; then
      log "编译 VapourSynth-EEDI2 (r7.1)"
      cd "$HOME" || exit 1
      tmux_run "下载 EEDI2 r7.1" wget -O r7.1.tar.gz https://github.com/HomeOfVapourSynthEvolution/VapourSynth-EEDI2/archive/refs/tags/r7.1.tar.gz || exit 1
      tmux_run "解压 EEDI2 r7.1" tar zxvf r7.1.tar.gz || exit 1
      cd VapourSynth-EEDI2-r7.1/ || exit 1
      tmux_run "EEDI2 meson setup" meson setup build || exit 1
      tmux_run "EEDI2 ninja" ninja -C build || exit 1
      cp build/libeedi2.so "$plugins_dir/" || exit 1
      cd "$build_dir" || exit 1
    else
      log "已存在 libeedi2.so，跳过"
    fi

    if [[ ! -f "$plugins_dir/libfmtconv.so" ]]; then
      log "编译 fmtconv (r30)"
      cd "$HOME" || exit 1
      tmux_run "下载 fmtconv r30" wget -O r30.tar.gz https://github.com/EleonoreMizo/fmtconv/archive/refs/tags/r30.tar.gz || exit 1
      tmux_run "解压 fmtconv r30" tar zxvf r30.tar.gz || exit 1
      cd fmtconv-r30/build/unix || exit 1
      tmux_run "fmtconv autogen" ./autogen.sh || exit 1
      tmux_run "fmtconv configure" ./configure || exit 1
      tmux_run "fmtconv make" make -j"$(nproc)" || exit 1
      local out
      out="$(find "$PWD/.libs" -maxdepth 1 -name "libfmtconv.so" -type f | head -n 1)"
      [[ -n "${out:-}" ]] || exit 1
      cp "$out" "$plugins_dir/" || exit 1
      cd "$build_dir" || exit 1
    else
      log "已存在 libfmtconv.so，跳过"
    fi

    if [[ ! -f "$plugins_dir/libremovegrain.so" ]]; then
      log "编译 vs-removegrain (R1)"
      cd "$HOME" || exit 1
      tmux_run "下载 vs-removegrain R1" wget https://github.com/vapoursynth/vs-removegrain/archive/refs/tags/R1.tar.gz || exit 1
      tmux_run "解压 vs-removegrain R1" tar zxvf R1.tar.gz || exit 1
      cd vs-removegrain-R1/src || exit 1
      tmux_run "编译 vs-removegrain R1" g++ -shared -fPIC -O3 -Wall \
        $(pkg-config --cflags vapoursynth) \
        clense.cpp removegrainvs.cpp repairvs.cpp shared.cpp verticalcleaner.cpp \
        -o libremovegrain.so || exit 1
      cp libremovegrain.so "$plugins_dir/" || exit 1
      cd "$build_dir" || exit 1
    else
      log "已存在 libremovegrain.so，跳过"
    fi

    if [[ ! -f "$plugins_dir/libsangnommod.so" ]]; then
      log "编译 VapourSynth-SangNomMod (v0.1-fix)"
      cd "$HOME" || exit 1
      tmux_run "下载 SangNomMod v0.1-fix" wget -O v0.1-fix.tar.gz https://github.com/HomeOfVapourSynthEvolution/VapourSynth-SangNomMod/archive/refs/tags/v0.1-fix.tar.gz || exit 1
      tmux_run "解压 SangNomMod v0.1-fix" tar zxvf v0.1-fix.tar.gz || exit 1
      cd VapourSynth-SangNomMod-0.1-fix/ || exit 1
      tmux_run "SangNomMod configure" ./configure || exit 1
      tmux_run "SangNomMod make" make -j"$(nproc)" || exit 1
      local out
      out="$(find "$PWD" -maxdepth 3 -name "libsangnommod.so" -type f | head -n 1)"
      [[ -n "${out:-}" ]] || exit 1
      cp "$out" "$plugins_dir/" || exit 1
      cd "$build_dir" || exit 1
    else
      log "已存在 libsangnommod.so，跳过"
    fi

    if [[ ! -f "$plugins_dir/libvs_placebo.so" ]]; then
      log "编译 vs-placebo (2.0.0)"
      cd "$HOME" || exit 1
      install_libplacebo_latest
      tmux_run "下载 vs-placebo 2.0.0" wget -O 2.0.0.tar.gz https://github.com/Lypheo/vs-placebo/archive/refs/tags/2.0.0.tar.gz || exit 1
      tmux_run "解压 vs-placebo 2.0.0" tar zxvf 2.0.0.tar.gz || exit 1
      cd vs-placebo-2.0.0/ || exit 1
      export PKG_CONFIG_PATH="/usr/local/lib/pkgconfig:/usr/local/lib/x86_64-linux-gnu/pkgconfig:/usr/local/share/pkgconfig:$HOME/.local/lib/x86_64-linux-gnu/pkgconfig:${PKG_CONFIG_PATH:-}"
      export C_INCLUDE_PATH="$HOME/.local/include:${C_INCLUDE_PATH:-}"
      export LIBRARY_PATH="$HOME/.local/lib/x86_64-linux-gnu:${LIBRARY_PATH:-}"
      export LD_LIBRARY_PATH="$HOME/.local/lib/x86_64-linux-gnu:${LD_LIBRARY_PATH:-}"
      rm -rf libp2p
      tmux_run "下载 libp2p" git clone https://github.com/sekrit-twc/libp2p.git || exit 1
      rm -rf build
      tmux_run "vs-placebo meson setup" meson setup build || exit 1
      tmux_run "vs-placebo ninja" ninja -C build || exit 1
      local out
      out="$(find "$PWD/build" -maxdepth 2 -name "libvs_placebo.so" -type f | head -n 1)"
      [[ -n "${out:-}" ]] || exit 1
      cp "$out" "$plugins_dir/" || exit 1
      cd "$build_dir" || exit 1
    else
      log "已存在 libvs_placebo.so，跳过"
    fi

    if ! command -v ispc >/dev/null 2>&1; then
      log "安装 ispc (v1.23.0)"
      tmux_run "下载 ispc v1.23.0" wget -O ispc-v1.23.0-linux.tar.gz https://github.com/ispc/ispc/releases/download/v1.23.0/ispc-v1.23.0-linux.tar.gz || exit 1
      tmux_run "解压 ispc v1.23.0" tar -xvf ispc-v1.23.0-linux.tar.gz || exit 1
      sudo mv ispc-v1.23.0-linux/bin/ispc /usr/local/bin/ || exit 1
      sudo chmod +x /usr/local/bin/ispc || exit 1
    else
      log "已检测到 ispc，跳过安装"
    fi

    if [[ ! -f "$plugins_dir/libvsnlm_ispc.so" ]]; then
      log "编译 vs-nlm-ispc (v2)"
      cd "$HOME" || exit 1
      tmux_run "下载 vs-nlm-ispc v2" wget -O v2.tar.gz https://github.com/AmusementClub/vs-nlm-ispc/archive/refs/tags/v2.tar.gz || exit 1
      tmux_run "解压 vs-nlm-ispc v2" tar zxvf v2.tar.gz || exit 1
      cd vs-nlm-ispc-2/ || exit 1
      mkdir -p build || exit 1
      cd build || exit 1
      tmux_run "vs-nlm-ispc cmake" cmake .. || exit 1
      tmux_run "vs-nlm-ispc make" make -j"$(nproc)" || exit 1
      local out
      out="$(find "$PWD" -maxdepth 2 -name "libvsnlm_ispc.so" -type f | head -n 1)"
      [[ -n "${out:-}" ]] || exit 1
      cp "$out" "$plugins_dir/" || exit 1
      cd "$build_dir" || exit 1
    else
      log "已存在 libvsnlm_ispc.so，跳过"
    fi

    if [[ ! -f "$plugins_dir/libzsmooth.x86_64-gnu.so" ]]; then
      log "安装 zsmooth（二进制包）"
      cd "$HOME" || exit 1
      tmux_run "下载 zsmooth 0.7" wget -O libzsmooth.x86_64-gnu.so.zip https://github.com/adworacz/zsmooth/releases/download/0.7/libzsmooth.x86_64-gnu.so.zip || exit 1
      tmux_run "解压 zsmooth 0.7" unzip -o libzsmooth.x86_64-gnu.so.zip || exit 1
      mv libzsmooth.x86_64-gnu.so "$plugins_dir/" || exit 1
      cd "$build_dir" || exit 1
    else
      log "已存在 libzsmooth.x86_64-gnu.so，跳过"
    fi

    if [[ ! -f "$plugins_dir/mvtools.so" ]]; then
      log "编译 vapoursynth-mvtools (v26)"
      cd "$HOME" || exit 1
      tmux_run "下载 mvtools v26" wget -O v26.tar.gz https://github.com/dubhatervapoursynth/vapoursynth-mvtools/archive/refs/tags/v26.tar.gz || exit 1
      tmux_run "解压 mvtools v26" tar zxvf v26.tar.gz || exit 1
      cd vapoursynth-mvtools-26/ || exit 1
      python3 - <<'PY' || exit 1
import re
with open('meson.build', 'r', encoding='utf-8', errors='replace') as f:
    content = f.read()
pattern = r"incdir\s*=\s*include_directories\s*\(\s*'vapoursynth/include'\s*\)"
new_content = re.sub(pattern, "incdir = '/usr/local/include/vapoursynth'", content, flags=re.DOTALL)
with open('meson.build', 'w', encoding='utf-8') as f:
    f.write(new_content)
PY
      tmux_run "mvtools meson setup" meson setup build || exit 1
      tmux_run "mvtools ninja" ninja -C build || exit 1
      cp build/mvtools.so "$plugins_dir/" || exit 1
      cd "$build_dir" || exit 1
    else
      log "已存在 mvtools.so，跳过"
    fi

    log "清理下载压缩包与源码目录"
    cd "$HOME" || exit 1
    rm -f \
      r9.tar.gz r10.tar.gz assrender_linux-x64_v0.38.3.zip r3.tar.gz r7.tar.gz r7.1.tar.gz \
      r30.tar.gz R1.tar.gz v0.1-fix.tar.gz 2.0.0.tar.gz v2.tar.gz libzsmooth.x86_64-gnu.so.zip v26.tar.gz \
      ispc-v1.23.0-linux.tar.gz libassrender.so \
      || true
    rm -rf \
      L-SMASH-Works VapourSynth-EEDI3-r9 VapourSynth-AddGrain-r10 VapourSynth-Bilateral-r3 \
      VapourSynth-DFTTest-r7 VapourSynth-EEDI2-r7.1 fmtconv-r30 vs-removegrain-R1 VapourSynth-SangNomMod-0.1-fix \
      vs-placebo-2.0.0 vs-nlm-ispc-2 vapoursynth-mvtools-26 ispc-v1.23.0-linux \
      || true

    log "VS 插件编译完成，输出目录：$plugins_dir"
  ) || die "VS 插件编译失败"

  rm -rf "$build_dir"
}

install_desktop_shortcuts() {
  local desktop_dir=""
  if command -v xdg-user-dir >/dev/null 2>&1; then
    desktop_dir="$(xdg-user-dir DESKTOP 2>/dev/null || true)"
  fi
  if [[ -z "${desktop_dir:-}" || "$desktop_dir" == "$HOME" ]]; then
    if [[ -d "$HOME/Desktop" ]]; then
      desktop_dir="$HOME/Desktop"
    elif [[ -d "$HOME/桌面" ]]; then
      desktop_dir="$HOME/桌面"
    else
      desktop_dir="$HOME/Desktop"
    fi
  fi

  mkdir -p "$desktop_dir" || true

  local found_any="false"
  local app_dir
  for app_dir in /usr/local/share/applications /usr/share/applications; do
    if [[ -d "$app_dir" ]]; then
      while IFS= read -r -d '' src; do
        found_any="true"
        cp -f "$src" "$desktop_dir/$(basename "$src")" || die "复制 desktop 文件失败：$src"
        chmod +x "$desktop_dir/$(basename "$src")" || true
      done < <(find "$app_dir" -maxdepth 1 -type f -name "*.desktop" \( -iname "*mpv*" -o -iname "*mkvtoolnix*" \) -print0)
    fi
  done
  if [[ "$found_any" != "true" ]]; then
    log "未在 /usr/local/share/applications 或 /usr/share/applications 中找到 mpv/mkvtoolnix 的 desktop 文件"
  fi

  if [[ -x "/usr/local/bin/vsedit" ]]; then
    local vsedit_desktop="$desktop_dir/vsedit.desktop"
    cat > "$vsedit_desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=vsedit
Comment=VapourSynth Editor
Exec=/usr/local/bin/vsedit %F
Terminal=false
Categories=AudioVideo;Video;
Icon=vsedit
StartupNotify=true
EOF
    chmod +x "$vsedit_desktop" || true
  fi

  log "桌面图标已准备完成：$desktop_dir"
}

install_shaderc_fix() {
  # 检测是否为 Ubuntu 22.04
  if [[ -f /etc/os-release ]]; then
    . /etc/os-release
    if [[ "$ID" == "ubuntu" && "$VERSION_ID" == "22.04" ]]; then
      if sudo ldconfig -p 2>/dev/null | grep -qE '\blibshaderc(_shared)?\.so\b'; then
        log "检测到 Shaderc 已安装（ldconfig 已包含 libshaderc），跳过源码编译"
        return 0
      fi
      if command -v pkg-config >/dev/null 2>&1 && pkg-config --exists shaderc; then
        log "检测到 Shaderc 已安装（pkg-config 可找到 shaderc），跳过源码编译"
        return 0
      fi

      log "检测到官方包版本冲突，正在从源码编译 Shaderc (这可能需要几分钟)..."

      local build_dir
      build_dir="$(mktemp -d)"
      (
          cd "$build_dir" || exit 1

          # 1. 克隆源码
          tmux_run "下载 shaderc" git clone https://github.com/google/shaderc . || exit 1

          # 2. 下载依赖 (glslang, spirv-tools, spirv-headers)
          # 这一步非常关键，它会自动配齐所有缺失的底层组件
          tmux_run "shaderc 同步依赖" ./utils/git-sync-deps || exit 1

          # 3. 配置与编译
          mkdir build && cd build
          tmux_run "shaderc cmake" cmake -GNinja \
              -DCMAKE_BUILD_TYPE=Release \
              -DSHADERC_SKIP_TESTS=ON \
              -DCMAKE_INSTALL_PREFIX=/usr/local .. || exit 1

          tmux_run "shaderc ninja" ninja || exit 1
          tmux_run "shaderc install" sudo ninja install || exit 1
      )
      rm -rf "$build_dir"
      sudo ldconfig
      log "Shaderc 源码编译并安装完成。"
    fi
  fi
}

command -v sudo >/dev/null 2>&1 || die "缺少 sudo"
sudo -v

require_supported_os
repair_broken_apt_state

sys_deps=(
  python3 python3-pip python3-venv cmake ninja-build
  ffmpeg wget fonts-wqy-microhei flac gedit
  libegl1 libopengl0 libglib2.0-0 libxkbcommon0 libdbus-1-3
  libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 libxcb-shape0
  libxcb-xinerama0 libxcb-xinput0 libxcb-render-util0
  libunwind8 libunwind-dev xdg-utils libgl1-mesa-dri libglx-mesa0 mesa-vulkan-drivers
)

missing_deps=()
for dep in "${sys_deps[@]}"; do
  if ! dpkg-query -W -f='${Status}' "$dep" 2>/dev/null | grep -q "install ok installed"; then
    missing_deps+=("$dep")
  fi
done

if (( ${#missing_deps[@]} > 0 )); then
  log "安装系统依赖（缺少：${missing_deps[*]}）"
  apt_update
  apt_install "${missing_deps[@]}"

  log "刷新字体缓存"
  sudo fc-cache -f >/dev/null 2>&1 || true
else
  log "系统依赖已全部安装，跳过"
fi

install_shaderc_fix
install_mkvtoolnix
install_mpv
install_x265
install_flac
install_vapoursynth
install_vapoursynth_scripts
install_vapoursynth_editor
build_vs_plugins
install_desktop_shortcuts

log "安装 Python 依赖（使用系统 python3：pycountry PyQt6 librosa）"
if ! pip3 show pycountry PyQt6 librosa >/dev/null 2>&1; then
  py_minor="$(python3 -c 'import sys; print(sys.version_info.minor)' 2>/dev/null || echo 0)"
  if (( py_minor >= 12 )); then
    tmux_run "安装 Python 依赖" env PIP_DISABLE_PIP_VERSION_CHECK=1 pip3 install --upgrade -q --progress-bar off pycountry PyQt6 librosa --break-system-packages >/dev/null 2>&1 \
      || tmux_run "安装 Python 依赖(重试)" env PIP_DISABLE_PIP_VERSION_CHECK=1 pip3 install --upgrade pycountry PyQt6 librosa --break-system-packages
  else
    tmux_run "安装 Python 依赖" env PIP_DISABLE_PIP_VERSION_CHECK=1 pip3 install --upgrade -q --progress-bar off pycountry PyQt6 librosa >/dev/null 2>&1 \
      || tmux_run "安装 Python 依赖(重试)" env PIP_DISABLE_PIP_VERSION_CHECK=1 pip3 install --upgrade pycountry PyQt6 librosa
  fi
else
  log "Python 依赖已安装，跳过"
fi


log "完成。推荐的运行方式："
echo "cd \"$REPO_DIR\""
#echo "export FFMPEG_PATH=/usr/bin/ffmpeg"
#echo "export FFPROBE_PATH=/usr/bin/ffprobe"
#echo "export FLAC_PATH=/usr/bin/flac"
#echo "export PLUGIN_PATH=\"\$HOME/plugins/\""
#echo "export LD_PRELOAD=/usr/local/lib/libvapoursynth-script.so"
echo "python3 -m src.main"
