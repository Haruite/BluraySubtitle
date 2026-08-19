#!/usr/bin/env bash
if [[ -z "${BLURAY_SETUP_SOURCE:-}" ]]; then
  BLURAY_SETUP_SOURCE="$(cd -- "$(dirname -- "$0")" && pwd)/$(basename -- "$0")"
fi
if [[ "${BLURAY_NO_CRLF_FIX:-}" != "1" ]]; then
  if LC_ALL=C grep -q $'\r' "$0"; then
    tmp="$(mktemp)"
    trap 'rm -f "$tmp"' EXIT
    tr -d '\r' < "$0" > "$tmp"
    chmod +x "$tmp" || true
    exec env BLURAY_NO_CRLF_FIX=1 BLURAY_SETUP_SOURCE="$BLURAY_SETUP_SOURCE" bash "$tmp" "$@"
  fi
fi
set -euo pipefail

X264_SOURCE_REPOSITORY="https://code.videolan.org/videolan/x264.git"
X264_SOURCE_MIRROR="https://github.com/mirror/x264.git"
X265_SOURCE_REPOSITORY="https://github.com/Multicorewareinc/x265.git"
FFMPEG_SOURCE_REPOSITORY="https://github.com/FFmpeg/FFmpeg.git"
SVT_AV1_SOURCE_REPOSITORY="https://gitlab.com/AOMediaCodec/SVT-AV1.git"
FDK_AAC_SOURCE_REPOSITORY="https://github.com/mstorsjo/fdk-aac.git"
FDKAAC_SOURCE_REPOSITORY="https://github.com/nu774/fdkaac.git"
SETTINGS_FILE="${BLURAY_SETTINGS_FILE:-$(dirname -- "$BLURAY_SETUP_SOURCE")/src/core/settings.py}"

# ---------------------------------------------------------------------------
# Language selection
# ---------------------------------------------------------------------------
# BLURAY_LANG can be preset to "en" or "zh" to skip the interactive prompt.
# When running non-interactively (no TTY), English is used as the default.
BLURAY_LANG="${BLURAY_LANG:-}"

select_language() {
  if [[ -n "$BLURAY_LANG" ]]; then
    return
  fi
  if [[ ! -t 0 ]]; then
    BLURAY_LANG="en"
    return
  fi
  echo ""
  echo "Please select a language / 请选择语言："
  echo "  1) English"
  echo "  2) 简体中文"
  echo ""
  local choice
  while true; do
    read -r -p "Enter 1 or 2 (default: 1): " choice
    choice="${choice:-1}"
    case "$choice" in
      1) BLURAY_LANG="en"; break ;;
      2) BLURAY_LANG="zh"; break ;;
      *) echo "Invalid input, please enter 1 or 2." ;;
    esac
  done
  echo ""
}

# msg <english_text> <chinese_text>
# Returns the string for the currently selected language.
msg() {
  if [[ "${BLURAY_LANG:-en}" == "zh" ]]; then
    printf '%s' "$2"
  else
    printf '%s' "$1"
  fi
}

log()      { echo -e "\n[BluraySubtitle][SETUP] $*\n"; }
die()      { echo -e "\n[BluraySubtitle][ERROR] $*\n" >&2; exit 1; }
log_blue() { printf "\n\033[34m[BluraySubtitle][SETUP] %s\033[0m\n\n" "$*"; }

bluray_build_tmp_base() {
  local base="${BLURAY_BUILD_TMP:-${TMPDIR:-}}"
  local candidate
  if [[ -z "$base" ]]; then
    for candidate in /var/tmp /tmp; do
      if [[ -d "$candidate" && -w "$candidate" ]]; then
        base="$candidate"
        break
      fi
    done
  fi
  [[ -n "$base" ]] || base="/tmp"
  mkdir -p "$base" 2>/dev/null || true
  printf '%s' "$base"
}

bluray_mktemp_dir() {
  local base tmp
  base="$(bluray_build_tmp_base)"
  tmp="$(mktemp -d -p "$base" 2>/dev/null || mktemp -d 2>/dev/null || true)"
  if [[ -z "${tmp:-}" ]]; then
    die "$(msg "Failed to create temp directory (disk quota exceeded?). Set BLURAY_BUILD_TMP to a directory with free space and retry." "创建临时目录失败（磁盘配额已满？）。请设置 BLURAY_BUILD_TMP 指向有足够空间的目录后重试。")"
  fi
  printf '%s' "$tmp"
}

bluray_mktemp_log_or_empty() {
  local base log
  base="$(bluray_build_tmp_base)"
  log="$(mktemp -p "$base" bluraysubtitle.XXXXXX.log 2>/dev/null || mktemp -t bluraysubtitle.XXXXXX.log 2>/dev/null || true)"
  if [[ -n "${log:-}" ]] && : >"$log" 2>/dev/null; then
    printf '%s' "$log"
  fi
}

# Resolve the newest stable numeric tag without depending on a forge API or jq.
# A caller may narrow the accepted tag syntax and remote tag glob per project.
latest_stable_tag() {
  local repository_url="$1"
  local stable_pattern="${2:-^[vV]?[0-9]+([.][0-9]+)+$}"
  local tag_glob="${3:-*}"
  local tag

  tag="$(
    git ls-remote --exit-code --refs --tags --sort=-version:refname \
      "$repository_url" "$tag_glob" \
      | awk -F 'refs/tags/' -v stable_pattern="$stable_pattern" \
        'NF == 2 && $2 ~ stable_pattern { print $2; exit }'
  )" || true
  if [[ -z "${tag:-}" ]]; then
    die "$(msg "Failed to resolve the latest stable tag for ${repository_url}" "无法获取 ${repository_url} 的最新稳定标签")"
  fi
  printf '%s' "$tag"
}

apt_clean() {
  sudo env DEBIAN_FRONTEND=noninteractive apt-get clean -y >/dev/null 2>&1 || true
  sudo env DEBIAN_FRONTEND=noninteractive apt-get autoremove -y >/dev/null 2>&1 || true
}

bluray_sudo() {
  if [[ "$(id -u)" -eq 0 ]]; then
    "$@"
  else
    sudo "$@"
  fi
}

load_configured_tool_paths() {
  [[ -f "$SETTINGS_FILE" ]] || die "$(msg "Settings file not found: ${SETTINGS_FILE}" "找不到设置文件：${SETTINGS_FILE}")"
  command -v python3 >/dev/null 2>&1 || die "$(msg 'python3 is required to read settings.py' '读取 settings.py 需要 python3')"

  local output name value count=0
  output="$(python3 - "$SETTINGS_FILE" <<'PY'
import os
import runpy
import sys

names = (
    "FLAC_PATH",
    "FFMPEG_PATH",
    "FFPROBE_PATH",
    "X265_PATH",
    "X264_PATH",
    "SVT_AV1_PATH",
    "FDK_AAC_PATH",
    "DOVI_TOOL_PATH",
    "HDR10PLUS_TOOL_PATH",
    "TRUEHDD_PATH",
    "VSEDIT_PATH",
    "VSPIPE_PATH",
    "PLUGIN_PATH",
    "TS_MUXER_PATH",
    "MKV_INFO_PATH",
    "MKV_MERGE_PATH",
    "MKV_PROP_EDIT_PATH",
    "MKV_EXTRACT_PATH",
)
settings = runpy.run_path(sys.argv[1])
for name in names:
    value = settings.get(name)
    if not isinstance(value, str) or not value:
        raise SystemExit(f"{name} must be a non-empty string")
    value = os.path.abspath(os.path.expanduser(value))
    if any(character in value for character in "\r\n\t"):
        raise SystemExit(f"{name} contains an unsupported control character")
    print(f"{name}\t{value}")
PY
)" || die "$(msg 'Failed to load configured Linux tool paths from settings.py' '无法从 settings.py 读取 Linux 工具路径')"

  while IFS=$'\t' read -r name value; do
    [[ -n "$name" && -n "$value" ]] || continue
    printf -v "$name" '%s' "$value"
    count=$((count + 1))
  done <<< "$output"
  [[ "$count" -eq 18 ]] || die "$(msg 'settings.py did not provide every required Linux tool path' 'settings.py 未提供全部必需的 Linux 工具路径')"

  X264_VERSION_FILE="$(dirname -- "$X264_PATH")/x264-version.txt"
  X265_FEATURE_FILE="$(dirname -- "$X265_PATH")/x265-build-features.txt"
  VSEDIT_BINARY_PATH="${VSEDIT_PATH}-bin"
}

install_configured_executable() {
  local source="$1"
  local destination="$2"
  [[ -f "$source" ]] || die "$(msg "Executable source not found: ${source}" "找不到可执行文件来源：${source}")"
  if [[ "$source" == "$destination" ]]; then
    bluray_sudo chmod 0755 "$destination"
    return 0
  fi
  bluray_sudo install -D -m 0755 "$source" "$destination"
}

install_command_at_configured_path() {
  local command_name="$1"
  local destination="$2"
  local source
  source="$(command -v "$command_name" 2>/dev/null || true)"
  [[ -n "$source" ]] || die "$(msg "Installed command not found: ${command_name}" "找不到已安装命令：${command_name}")"
  install_configured_executable "$source" "$destination"
}

ensure_configured_directory() {
  local directory="$1"
  if mkdir -p "$directory" 2>/dev/null; then
    return 0
  fi
  bluray_sudo install -d -m 0755 -o "$(id -u)" -g "$(id -g)" "$directory"
}

sync_mkvtoolnix_paths() {
  install_command_at_configured_path mkvinfo "$MKV_INFO_PATH"
  install_command_at_configured_path mkvmerge "$MKV_MERGE_PATH"
  install_command_at_configured_path mkvpropedit "$MKV_PROP_EDIT_PATH"
  install_command_at_configured_path mkvextract "$MKV_EXTRACT_PATH"
}

verify_configured_tool_paths() {
  local path
  for path in \
    "$FLAC_PATH" "$FFMPEG_PATH" "$FFPROBE_PATH" \
    "$X265_PATH" "$X264_PATH" "$SVT_AV1_PATH" "$FDK_AAC_PATH" \
    "$DOVI_TOOL_PATH" "$HDR10PLUS_TOOL_PATH" "$TRUEHDD_PATH" \
    "$VSEDIT_PATH" "$VSPIPE_PATH" "$TS_MUXER_PATH" \
    "$MKV_INFO_PATH" "$MKV_MERGE_PATH" "$MKV_PROP_EDIT_PATH" "$MKV_EXTRACT_PATH"; do
    [[ -x "$path" ]] || die "$(msg "Configured tool is missing or not executable: ${path}" "配置的工具不存在或不可执行：${path}")"
  done
  [[ -d "$PLUGIN_PATH" ]] || die "$(msg "Configured plugin directory is missing: ${PLUGIN_PATH}" "配置的插件目录不存在：${PLUGIN_PATH}")"
}

bluray_quarantine_local_boost() {
  BLURAY_BOOST_QUARANTINE_DIR="$(bluray_mktemp_dir)/boost-quarantine"
  mkdir -p "$BLURAY_BOOST_QUARANTINE_DIR"
  shopt -s nullglob
  local libs=(/usr/local/lib/libboost_*.so*)
  if (( ${#libs[@]} > 0 )); then
    log "$(msg 'Temporarily hiding /usr/local Boost libraries so mkvtoolnix links against system packages' '临时隐藏 /usr/local 下的 Boost 库，使 mkvtoolnix 链接系统包版本')"
    bluray_sudo mv "${libs[@]}" "$BLURAY_BOOST_QUARANTINE_DIR/"
    bluray_sudo ldconfig
  fi
  shopt -u nullglob
}

bluray_restore_local_boost() {
  if [[ -z "${BLURAY_BOOST_QUARANTINE_DIR:-}" || ! -d "$BLURAY_BOOST_QUARANTINE_DIR" ]]; then
    return 0
  fi
  shopt -s nullglob
  local libs=("$BLURAY_BOOST_QUARANTINE_DIR"/libboost_*.so*)
  if (( ${#libs[@]} > 0 )); then
    bluray_sudo mv "${libs[@]}" /usr/local/lib/
    bluray_sudo ldconfig
  fi
  shopt -u nullglob
  rm -rf "$BLURAY_BOOST_QUARANTINE_DIR" || true
  unset BLURAY_BOOST_QUARANTINE_DIR
}

# ---------------------------------------------------------------------------
# Terminal helpers
# ---------------------------------------------------------------------------

terminal_sane() {
  # Force-disable: mouse-click mode, mouse-move tracking, SGR coordinate mode, alternate screen
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

  printf "\n[BluraySubtitle][SETUP] $(msg 'Running' '执行')：%s" "$title"
  local logfile
  logfile="$(bluray_mktemp_log_or_empty)"
  if [[ -z "${logfile:-}" ]]; then
    "$@" || return $?
    return 0
  fi

  # 1. Open a split pane. The original printf that enabled mouse tracking has been
  #    removed to prevent garbled output.
  local pane_id
  pane_id="$(tmux split-window -v -p 35 -P -F "#{pane_id}" "bash -lc 'tail -n +1 -f \"${logfile}\"'")"
  tmux select-pane -t "$pane_id" -P "fg=white,bg=default" >/dev/null 2>&1 || true

  local task_pid=""

  # --- Ultimate cleanup function ---
  force_cleanup() {
    local sig_type=$1
    trap - INT TERM EXIT # Remove trap to prevent recursion

    # A. Force-kill residual processes: kill the task and all its child processes
    if [[ -n "$task_pid" ]]; then
      # Kill the entire process group to ensure tee and sub-commands all die
      pkill -P "$task_pid" 2>/dev/null || true
      kill -9 "$task_pid" 2>/dev/null || true
    fi

    # B. Capture output: grab the last 200 lines before killing the pane
    echo -e "\n\033[33m>>> [$(msg 'Task interrupted/error' '任务中断/异常')] $(msg 'Last 200 lines of output:' '保留最后 200 行输出内容：')\033[0m"
    tmux capture-pane -t "$pane_id" -p -S -200 2>/dev/null || true
    echo -e "\033[33m>>> [$(msg 'Done' '提取完成')] \033[0m\n"

    # C. Destroy the pane and reset terminal state
    tmux kill-pane -t "$pane_id" >/dev/null 2>&1 || true
    terminal_sane

    # If triggered by Ctrl+C, terminate the entire script
    [[ "$sig_type" == "INT" ]] && exit 130
  }

  # Bind signals
  trap 'force_cleanup INT' INT
  trap 'force_cleanup TERM' TERM

  # 2. Start the task in the background and capture its PID
  # Run inside a subshell ( ... ) so it can be killed as a unit
  (
    set +e
    "$@" 2>&1 | tee -a "$logfile" >/dev/null
    exit $?
  ) &
  task_pid=$!

  # Wait for the task to finish
  local ec=0
  wait "$task_pid" || ec=$?

  # 3. Normal / error handling
  if [[ "$ec" -ne 0 ]]; then
    # Non-zero exit: run cleanup and preserve output
    force_cleanup ERROR
  else
    # Success: kill the pane normally without reprinting
    tmux kill-pane -t "$pane_id" >/dev/null 2>&1 || true
    terminal_sane
    trap - INT TERM EXIT
  fi

  # Write to master log if configured
  if [[ -n "${BLURAY_MASTER_LOG:-}" ]]; then
    { echo "===== ${title} ====="; cat "$logfile"; echo; } >>"$BLURAY_MASTER_LOG" 2>/dev/null || true
  fi

  if [[ "$ec" == "0" ]]; then
    rm -f "$logfile" || true
    printf "\r\033[2K\033[34m[BluraySubtitle][SETUP] $(msg 'Running' '执行')：%s\033[0m\n\n" "$title"
    return 0
  fi

  return "$ec"
}

# ---------------------------------------------------------------------------
# APT helpers
# ---------------------------------------------------------------------------

apt_update() {
  tmux_run "apt-get update" sudo apt-get update
}

apt_install() {
  tmux_run "apt-get install ${*}" sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y "$@"
}

apt_fix_broken() {
  tmux_run "apt-get -f install" sudo env DEBIAN_FRONTEND=noninteractive apt-get -f install -y
}

# ---------------------------------------------------------------------------
# Bootstrap helpers
# ---------------------------------------------------------------------------

ensure_tmux_installed() {
  command -v tmux >/dev/null 2>&1 && return 0
  command -v apt-get >/dev/null 2>&1 || return 0
  command -v sudo >/dev/null 2>&1 || die "$(msg 'sudo is missing' '缺少 sudo')"
  sudo -v
  sudo apt-get update -qq >/dev/null 2>&1 || die "$(msg 'apt-get update failed (installing tmux)' 'apt-get update 失败（安装 tmux）')"
  sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq tmux >/dev/null 2>&1 || die "$(msg 'tmux installation failed' 'tmux 安装失败')"
}

ensure_sudo_once() {
  command -v sudo >/dev/null 2>&1 || die "$(msg 'sudo is missing' '缺少 sudo')"
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

is_remote_ssh() {
  [[ -n "${SSH_CONNECTION:-}" || -n "${SSH_CLIENT:-}" || -n "${SSH_TTY:-}" ]]
}

# ---------------------------------------------------------------------------
# Language selection must happen before tmux re-exec so the choice is
# inherited by the --in-tmux child via the BLURAY_LANG environment variable.
# ---------------------------------------------------------------------------
select_language

log "$(msg 'Recommended terminal: Xshell or PuTTY for remote execution' '推荐使用 Xshell 或 PuTTY 远程执行命令')"

if [[ "${1:-}" != "--in-tmux" && -z "${TMUX:-}" && -t 1 ]]; then
  if is_remote_ssh; then
    ensure_tmux_installed
    args_escaped="$(printf '%q ' "$@")"
    exec tmux new-session -A -s BluraySubtitle "bash -lc \"bash \\\"$0\\\" --in-tmux ${args_escaped}; echo; echo '[BluraySubtitle][SETUP] $(msg 'Script finished (scroll up to review output, press Ctrl+b d to detach from tmux)' '脚本已结束（可滚动查看上方输出，按 Ctrl+b d 退出 tmux）')'; exec bash\"" \; set -g mouse off \; set -g status off \; set -g remain-on-exit off
  fi
fi
if [[ "${1:-}" == "--in-tmux" ]]; then
  shift || true
fi

ensure_sudo_once

# ---------------------------------------------------------------------------
# OS / version checks
# ---------------------------------------------------------------------------

require_supported_os() {
  if [[ ! -f /etc/os-release ]]; then
    die "$(msg '/etc/os-release not found; cannot determine OS version' '未检测到 /etc/os-release，无法判断系统版本')"
  fi

  . /etc/os-release || true
  log "$(msg "Detected OS: ${PRETTY_NAME:-unknown}" "检测到系统：${PRETTY_NAME:-unknown}")"

  command -v dpkg >/dev/null 2>&1 || die "$(msg 'dpkg is missing; cannot compare OS versions' '缺少 dpkg，无法比较系统版本')"

  local id="${ID:-}"
  local version_id="${VERSION_ID:-}"

  if [[ "$id" == "ubuntu" ]]; then
    dpkg --compare-versions "$version_id" ge "22.04" || die "$(msg "Only Ubuntu >= 22.04 is supported (current: $version_id)" "仅支持 Ubuntu >= 22.04（当前：$version_id）")"
    return 0
  fi

  if [[ "$id" == "debian" ]]; then
    dpkg --compare-versions "$version_id" ge "12" || die "$(msg "Only Debian >= 12 is supported (current: $version_id)" "仅支持 Debian >= 12（当前：$version_id）")"
    return 0
  fi

  die "$(msg "Only Ubuntu >= 22.04 or Debian >= 12 is supported (current: ${PRETTY_NAME:-unknown})" "仅支持 Ubuntu >= 22.04 或 Debian >= 12（当前：${PRETTY_NAME:-unknown}）")"
}

repair_broken_apt_state() {
  log "$(msg 'Checking and repairing broken APT/dpkg state' '检查并修复 APT/Dpkg 破损状态')"
  sudo dpkg --configure -a || true
  apt_fix_broken || die "$(msg 'Failed to repair package dependencies; please run: sudo apt --fix-broken install' '修复系统包依赖失败，请手动执行 sudo apt --fix-broken install')"
}

# ---------------------------------------------------------------------------
# meson version management
# ---------------------------------------------------------------------------

ensure_meson_version() {
  local required_version="1.4.0"

  export PATH="$HOME/.local/bin:$PATH"

  if command -v meson >/dev/null 2>&1; then
    local current_version
    current_version="$(meson --version 2>/dev/null | head -n 1 || true)"
    if [[ -n "${current_version:-}" ]] && dpkg --compare-versions "$current_version" ge "$required_version"; then
      log "$(msg "meson version satisfied (${current_version} >= ${required_version}), skipping upgrade" "meson 版本满足要求（${current_version} >= ${required_version}），跳过升级")"
      return 0
    fi
    log "$(msg "meson version (${current_version:-unknown}) is below ${required_version}, upgrading" "检测到 meson 版本 (${current_version:-unknown}) 小于 ${required_version}，将升级")"
  else
    log "$(msg "meson not found, installing/upgrading to >= ${required_version}" "未检测到 meson，将安装/升级到 >= ${required_version}")"
  fi

  if ! python3 -m pip --version >/dev/null 2>&1; then
    apt_update
    apt_install python3-pip || die "$(msg 'Failed to install python3-pip' '安装 python3-pip 失败')"
  fi

  local pip_cmd=("python3" "-m" "pip")
  if command -v pip >/dev/null 2>&1; then
    pip_cmd=("pip")
  fi

  if ! env PIP_DISABLE_PIP_VERSION_CHECK=1 "${pip_cmd[@]}" install --user --upgrade -q --progress-bar off meson --break-system-packages >/dev/null 2>&1; then
    log "$(msg 'pip does not support --break-system-packages, retrying with compatible flags' '当前 pip 不支持 --break-system-packages，回退到兼容参数重试')"
    env PIP_DISABLE_PIP_VERSION_CHECK=1 "${pip_cmd[@]}" install --user --upgrade -q --progress-bar off meson >/dev/null 2>&1 || die "$(msg 'Failed to upgrade meson' '升级 meson 失败')"
  fi
  export PATH="$HOME/.local/bin:$PATH"

  local new_version
  new_version="$(meson --version 2>/dev/null | head -n 1 || true)"
  if [[ -z "${new_version:-}" ]] || ! dpkg --compare-versions "$new_version" ge "$required_version"; then
    die "$(msg "meson version still unsatisfied after upgrade (current: ${new_version:-unknown}, required: >= ${required_version})" "meson 升级后版本仍不满足要求（当前：${new_version:-unknown}，要求：>= ${required_version}）")"
  fi

  log "$(msg "meson upgrade complete (current: ${new_version})" "meson 升级完成（当前：${new_version}）")"
}

# ---------------------------------------------------------------------------
# mkvtoolnix
# ---------------------------------------------------------------------------

install_mkvtoolnix() {
  log "$(msg 'Installing mkvtoolnix / mkvtoolnix-gui' '安装 mkvtoolnix / mkvtoolnix-gui')"

  command -v apt-get >/dev/null 2>&1 || die "$(msg 'apt-get is missing' '缺少 apt-get')"
  command -v dpkg >/dev/null 2>&1 || die "$(msg 'dpkg is missing; cannot manage mkvtoolnix packages or compare versions' '缺少 dpkg，无法管理 mkvtoolnix 软件包或比较版本')"

  local mkvtoolnix_codename=""
  if [[ "${ID:-}" == "ubuntu" ]]; then
    case "${VERSION_ID:-}" in
      24.04) mkvtoolnix_codename="noble" ;;
      26.04) mkvtoolnix_codename="resolute" ;;
    esac
  fi

  if [[ -n "$mkvtoolnix_codename" ]]; then
    local architecture
    architecture="$(dpkg --print-architecture)"
    case "$architecture" in
      amd64 | arm64) ;;
      *) mkvtoolnix_codename="" ;;
    esac
  fi

  if [[ -n "$mkvtoolnix_codename" ]]; then
    local keyring_path="/etc/apt/keyrings/gpg-pub-moritzbunkus.gpg"
    local source_list_path="/etc/apt/sources.list.d/mkvtoolnix.download.list"
    log "$(msg "Installing MKVToolNix from its official Ubuntu repository (${mkvtoolnix_codename})" "从 MKVToolNix 官方 Ubuntu 软件源安装（${mkvtoolnix_codename}）")"
    bluray_sudo install -d -m 0755 /etc/apt/keyrings || die "$(msg 'Failed to create the APT keyring directory' '创建 APT 密钥目录失败')"
    tmux_run "$(msg 'Download the MKVToolNix repository signing key' '下载 MKVToolNix 软件源签名密钥')" \
      bluray_sudo wget -q -O "$keyring_path" https://mkvtoolnix.download/gpg-pub-moritzbunkus.gpg \
      || die "$(msg 'Failed to download the MKVToolNix repository signing key' '下载 MKVToolNix 软件源签名密钥失败')"
    printf 'deb [arch=%s signed-by=%s] https://mkvtoolnix.download/ubuntu/ %s main\n' \
      "$architecture" "$keyring_path" "$mkvtoolnix_codename" \
      | bluray_sudo tee "$source_list_path" >/dev/null \
      || die "$(msg 'Failed to configure the MKVToolNix repository' '配置 MKVToolNix 软件源失败')"
    apt_update || die "$(msg 'Failed to refresh the MKVToolNix repository' '刷新 MKVToolNix 软件源失败')"
    apt_install mkvtoolnix mkvtoolnix-gui || die "$(msg 'Failed to install MKVToolNix packages' 'MKVToolNix 软件包安装失败')"
    hash -r
    log "$(msg 'mkvtoolnix installation complete' 'mkvtoolnix 安装完成')"
    return 0
  fi

  if ! command -v curl >/dev/null 2>&1; then
    apt_update
    apt_install curl
  fi

  local latest_version version
  latest_version="$(
    curl -s "https://mkvtoolnix.download/latest-release.xml" \
      | grep -oP '(?<=<version>).*?(?=</version>)' \
      | head -n 1
  )"
  if [[ -z "${latest_version:-}" ]]; then
    die "$(msg 'Failed to fetch latest mkvtoolnix version' '获取 mkvtoolnix 最新版本失败')"
  fi
  version="${MKVTOOLNIX_VERSION:-$latest_version}"

  # Qt string literal operators used since MKVToolNix 99 require Qt >= 6.4.
  # Ubuntu 22.04 ships Qt 6.2, so keep the last compatible release by default.
  if [[ -z "${MKVTOOLNIX_VERSION:-}" && "${ID:-}" == "ubuntu" && "${VERSION_ID:-}" == "22.04" ]] \
      && dpkg --compare-versions "$version" gt "98.0"; then
    version="98.0"
    log "$(msg "Latest mkvtoolnix is ${latest_version}; using ${version} on Ubuntu 22.04 for Qt 6.2 compatibility" "mkvtoolnix 最新版本为 ${latest_version}；Ubuntu 22.04 使用 ${version} 以兼容 Qt 6.2")"
  else
    log "$(msg "Selected mkvtoolnix version: ${version} (latest upstream: ${latest_version})" "选择 mkvtoolnix 版本：${version}（上游最新：${latest_version}）")"
  fi

  local package_name
  local installed_deb_packages=()
  for package_name in mkvtoolnix-gui-dbg mkvtoolnix-dbg mkvtoolnix-gui mkvtoolnix; do
    if [[ "$(dpkg-query -W -f='${Status}' "$package_name" 2>/dev/null || true)" == "install ok installed" ]]; then
      installed_deb_packages+=("$package_name")
    fi
  done

  local current_version=""
  if command -v mkvmerge >/dev/null 2>&1; then
    current_version="$(mkvmerge --version 2>/dev/null | head -n 1 | grep -oE 'v[0-9]+(\.[0-9]+)+' | head -n 1 | tr -d 'v' || true)"
    if [[ -n "${current_version:-}" ]]; then
      log "$(msg "Installed mkvtoolnix version: ${current_version}" "检测到已安装 mkvtoolnix 版本：${current_version}")"
      if (( ${#installed_deb_packages[@]} == 0 )) && dpkg --compare-versions "$current_version" ge "$version"; then
        log "$(msg "mkvtoolnix version satisfied (${current_version} >= ${version}), skipping build" "mkvtoolnix 版本已满足要求（${current_version} >= ${version}），跳过编译安装")"
        return 0
      fi
      if (( ${#installed_deb_packages[@]} > 0 )); then
        log "$(msg 'The installed mkvtoolnix deb packages will be replaced by a direct source installation' '已安装的 mkvtoolnix deb 软件包将替换为源码直接安装')"
      else
        log "$(msg "mkvtoolnix version is outdated (${current_version} < ${version}), rebuilding from source" "检测到 mkvtoolnix 版本较旧（${current_version} < ${version}），将从源码编译升级")"
      fi
    else
      log "$(msg 'mkvmerge found but version could not be determined, rebuilding from source' '检测到 mkvmerge 但无法解析版本号，将从源码编译安装')"
    fi
  fi

  log "$(msg 'Installing build dependencies' '安装编译所需基础工具')"
  apt_update
  apt_install build-essential docbook-xsl libx11-xcb-dev libglu1-mesa-dev \
  libboost-date-time-dev libboost-dev libboost-filesystem-dev libboost-math-dev libboost-regex-dev libboost-system-dev \
  libbz2-dev libcmark-dev libdvdread-dev libflac-dev libfmt-dev libgmp-dev libgtest-dev liblzo2-dev libmagic-dev \
  libogg-dev libpcre2-8-0 libpcre2-dev libqt6svg6-dev libvorbis-dev \
  nlohmann-json3-dev pkg-config po4a qt6-base-dev qt6-base-dev-tools qt6-multimedia-dev \
  rake ruby xsltproc zlib1g-dev unzip libtool autoconf

  local build_dir
  build_dir="$(bluray_mktemp_dir)"

  (
    cd "$build_dir" || exit 1
    log "$(msg 'Downloading source tarball' '下载源码包')"
    curl -fsSL -o "mkvtoolnix_${version}.orig.tar.xz" "https://mkvtoolnix.download/sources/mkvtoolnix-${version}.tar.xz" || exit 1
    log "$(msg 'Extracting source tarball' '解压源码包')"
    tar xJf "mkvtoolnix_${version}.orig.tar.xz" || exit 1

    cd "mkvtoolnix-${version}" || exit 1
    bluray_quarantine_local_boost
    trap bluray_restore_local_boost EXIT

    log "$(msg 'Cleaning previous mkvtoolnix build artifacts' '清理 mkvtoolnix 旧的编译产物')"
    ./drake clean 2>/dev/null || true

    export LD_LIBRARY_PATH=""
    export LIBRARY_PATH="/usr/lib/x86_64-linux-gnu:/usr/lib"
    export PKG_CONFIG_PATH="/usr/lib/x86_64-linux-gnu/pkgconfig:/usr/share/pkgconfig"
    export LDFLAGS="-L/usr/lib/x86_64-linux-gnu -Wl,-rpath-link,/usr/lib/x86_64-linux-gnu"

    log "$(msg 'Configuring mkvtoolnix with GUI support' '配置启用 GUI 的 mkvtoolnix')"
    ./configure \
      --prefix=/usr \
      --docdir='${datarootdir}/doc/mkvtoolnix-gui' \
      --enable-gui \
      --enable-optimization || exit 1

    log "$(msg 'Building mkvtoolnix with Rake' '使用 Rake 编译 mkvtoolnix')"
    tmux_run "mkvtoolnix build" ./drake -j"$(nproc)" || exit 1
    ./drake apps:strip || exit 1

    if (( ${#installed_deb_packages[@]} > 0 )); then
      log "$(msg "Removing installed mkvtoolnix deb packages: ${installed_deb_packages[*]}" "正在卸载已安装的 mkvtoolnix deb 软件包：${installed_deb_packages[*]}")"
      tmux_run "apt-get remove ${installed_deb_packages[*]}" \
        sudo env DEBIAN_FRONTEND=noninteractive apt-get remove -y "${installed_deb_packages[@]}" || exit 1
      hash -r
    fi

    log "$(msg 'Installing mkvtoolnix with rake install' '使用 rake install 安装 mkvtoolnix')"
    tmux_run "rake install" bluray_sudo rake install || exit 1
    bluray_restore_local_boost
    trap - EXIT
    apt_clean
  ) || die "$(msg 'mkvtoolnix build/install failed (if missing deps, install them manually and retry)' 'mkvtoolnix 编译/安装失败（如提示缺依赖，可手动补齐后重试）')"

  rm -rf "$build_dir"

  log "$(msg 'mkvtoolnix installation complete' 'mkvtoolnix 安装完成')"
}

# ---------------------------------------------------------------------------
# libdovi
# ---------------------------------------------------------------------------

libdovi_header_is_complete() {
  local header
  for header in \
    /usr/local/include/libdovi/rpu_parser.h \
    "$HOME/.local/include/libdovi/rpu_parser.h" \
    /usr/include/libdovi/rpu_parser.h; do
    if [[ -f "$header" ]] \
        && grep -qF 'void dovi_rpu_free(' "$header" \
        && grep -qF 'void dovi_rpu_free_header(' "$header"; then
      return 0
    fi
  done
  return 1
}

repair_packaged_libdovi_header() {
  # Ubuntu 26.04 inherited the truncated generated header described in
  # https://bugs.debian.org/1124682. Use Debian's rebuilt header from the
  # same upstream 3.3.2 release without replacing Ubuntu's runtime library.
  [[ "${ID:-}" == "ubuntu" && "${VERSION_ID:-}" == "26.04" ]] || return 1

  local package_version
  package_version="$(dpkg-query -W -f='${Version}' libdovi-dev 2>/dev/null || true)"
  case "$package_version" in
    3.3.2-3*) ;;
    *) return 1 ;;
  esac

  local architecture checksum
  architecture="$(dpkg --print-architecture)"
  case "$architecture" in
    amd64) checksum="517d9a81e904d0b337e04b4f9fef0c4a1939fddc49237612547fd8ae033f3ad1" ;;
    arm64) checksum="27c6b2a66ab2de4ddd2f5b87ecb0826cb504f7218fc1cf73a649fdbc4b2c760b" ;;
    *) return 1 ;;
  esac

  local repair_version="3.3.2-3+b1"
  local repair_dir archive extracted_header
  repair_dir="$(bluray_mktemp_dir)"
  archive="$repair_dir/libdovi-dev.deb"
  extracted_header="$repair_dir/extracted/usr/include/libdovi/rpu_parser.h"

  log "$(msg "Repairing the truncated Ubuntu libdovi header with Debian's rebuilt 3.3.2 header" '使用 Debian 重新生成的 3.3.2 头文件修复 Ubuntu 中被截断的 libdovi 头文件')"
  if ! (
    tmux_run "$(msg 'Download the rebuilt libdovi development header' '下载重新生成的 libdovi 开发头文件')" \
      wget -q -O "$archive" \
        "https://deb.debian.org/debian/pool/main/r/rust-dolby-vision/libdovi-dev_${repair_version}_${architecture}.deb" \
      || exit 1
    printf '%s  %s\n' "$checksum" "$archive" | sha256sum -c - >/dev/null \
      || exit 1
    dpkg-deb -x "$archive" "$repair_dir/extracted" || exit 1
    [[ -f "$extracted_header" ]] || exit 1
    bluray_sudo install -m 0644 "$extracted_header" /usr/include/libdovi/rpu_parser.h \
      || exit 1
  ); then
    rm -rf "$repair_dir"
    return 1
  fi
  rm -rf "$repair_dir"
  libdovi_header_is_complete
}

has_libdovi_development() {
  local runtime_found="false"
  if sudo ldconfig -p 2>/dev/null | grep -qE '\blibdovi\.so(\.[0-9]+)*\b'; then
    runtime_found="true"
  else
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
    if [[ -n "${any_file:-}" ]]; then
      runtime_found="true"
    fi
  fi

  [[ "$runtime_found" == "true" ]] || return 1
  libdovi_header_is_complete || return 1

  local libdovi_pkg_config_path
  libdovi_pkg_config_path="/usr/local/lib/pkgconfig:/usr/local/lib/x86_64-linux-gnu/pkgconfig:/usr/local/lib/aarch64-linux-gnu/pkgconfig:${HOME}/.local/lib/pkgconfig:${HOME}/.local/lib/x86_64-linux-gnu/pkgconfig:${HOME}/.local/lib/aarch64-linux-gnu/pkgconfig:${PKG_CONFIG_PATH:-}"
  PKG_CONFIG_PATH="$libdovi_pkg_config_path" pkg-config --exists dovi 2>/dev/null
}

install_libdovi() {
  log "$(msg 'Installing libdovi (dovi_tool/dolby_vision)' '安装 libdovi（dovi_tool/dolby_vision）')"

  if has_libdovi_development; then
    log "$(msg 'libdovi development files already installed, skipping' '检测到 libdovi 开发文件已安装，跳过')"
    return 0
  fi

  apt_update || die "$(msg 'Failed to refresh package metadata for libdovi' '刷新 libdovi 软件包信息失败')"
  if apt-cache show libdovi-dev >/dev/null 2>&1; then
    log "$(msg 'Installing libdovi-dev from the system package repository' '从系统软件源安装 libdovi-dev')"
    apt_install pkg-config libdovi-dev || die "$(msg 'Failed to install libdovi-dev' 'libdovi-dev 安装失败')"
    if ! libdovi_header_is_complete; then
      repair_packaged_libdovi_header || true
    fi
    if has_libdovi_development; then
      log "$(msg 'libdovi installation complete' 'libdovi 安装完成')"
      return 0
    fi
    log "$(msg 'The packaged libdovi development files are incomplete; falling back to a cargo-c source build' '软件包中的 libdovi 开发文件不完整，回退到 cargo-c 源码编译')"
  else
    log "$(msg 'libdovi-dev is unavailable; falling back to a cargo-c source build' '软件源不提供 libdovi-dev，回退到 cargo-c 源码编译')"
  fi

  if [[ -z "$DOVI_TOOL_VERSION" ]]; then
    DOVI_TOOL_VERSION="$(latest_stable_tag https://github.com/quietvoid/dovi_tool.git)"
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
    apt_install "${missing_deps[@]}" || die "$(msg 'Failed to install libdovi dependencies' 'libdovi 依赖安装失败，请检查网络或包名')"
  fi

  local build_dir
  build_dir="$(mktemp -d)"

  (
    cd "$build_dir" || exit 1

    log "$(msg 'Setting up Rust environment' '配置 Rust 环境')"
    if ! command -v rustup >/dev/null 2>&1; then
      tmux_run "$(msg 'Download and install rustup' '下载并安装 rustup')" bash -lc "curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y" || exit 1
    fi
    source "$HOME/.cargo/env" || exit 1
    tmux_run "$(msg 'Update the stable Rust toolchain' '更新 Rust stable 工具链')" rustup update stable || exit 1

    log "$(msg 'Installing cargo-c' '安装 cargo-c')"
    tmux_run "$(msg 'Install cargo-c' '安装 cargo-c')" cargo install cargo-c || exit 1

    log "$(msg "Building and installing to $HOME/.local" "编译并安装到 $HOME/.local")"
    tmux_run "$(msg "Download dovi_tool ${DOVI_TOOL_VERSION}" "下载 dovi_tool ${DOVI_TOOL_VERSION}")" \
      git clone --depth 1 --branch "$DOVI_TOOL_VERSION" https://github.com/quietvoid/dovi_tool.git || exit 1
    cd dovi_tool/dolby_vision || exit 1
    tmux_run "$(msg 'Build and install dolby_vision' '编译安装 dolby_vision')" cargo cinstall --release --prefix="$HOME/.local" || exit 1

    local lib_dir
    lib_dir="$(
      find "$HOME/.local" -maxdepth 6 -name "libdovi.so*" -printf "%h\n" 2>/dev/null \
        | head -n 1
    )"
    if [[ -z "${lib_dir:-}" ]]; then
      exit 1
    fi

    log "$(msg 'Copying runtime library to /usr/local/lib and refreshing ldconfig' '安装运行库到 /usr/local/lib 并刷新 ldconfig')"
    sudo cp -a "$lib_dir"/libdovi.so* /usr/local/lib/ || exit 1
    sudo ldconfig || exit 1
  ) || die "$(msg 'libdovi build/install failed' 'libdovi 编译/安装失败')"

  rm -rf "$build_dir"

  if ! has_libdovi_development; then
    die "$(msg 'libdovi installed but its library or pkg-config metadata was not found' 'libdovi 安装完成，但未找到运行库或 pkg-config 元数据')"
  fi

  log "$(msg 'libdovi installation complete' 'libdovi 安装完成')"
}

# ---------------------------------------------------------------------------
# dovi_tool (prebuilt release binary for BluraySubtitle remux)
# ---------------------------------------------------------------------------

# Set DOVI_TOOL_VERSION to pin a release; source-built libdovi and the CLI otherwise use latest stable.
DOVI_TOOL_VERSION="${DOVI_TOOL_VERSION:-}"

install_dovi_tool() {
  if [[ -z "$DOVI_TOOL_VERSION" ]]; then
    DOVI_TOOL_VERSION="$(latest_stable_tag https://github.com/quietvoid/dovi_tool.git)"
  fi
  log "$(msg "Installing dovi_tool ${DOVI_TOOL_VERSION} (prebuilt)" "安装 dovi_tool ${DOVI_TOOL_VERSION}（预编译包）")"

  if [[ -x "$DOVI_TOOL_PATH" ]]; then
    log "$(msg "dovi_tool already installed (${DOVI_TOOL_PATH}), skipping" "检测到 dovi_tool 已安装（${DOVI_TOOL_PATH}），跳过")"
    return 0
  fi

  local arch tarball
  case "$(uname -m)" in
    x86_64 | amd64)
      arch=x86_64
      ;;
    aarch64 | arm64)
      arch=aarch64
      ;;
    *)
      die "$(msg "Unsupported CPU architecture for dovi_tool prebuilt: $(uname -m)" "当前 CPU 架构不支持预编译 dovi_tool：$(uname -m)")"
      ;;
  esac
  tarball="dovi_tool-${DOVI_TOOL_VERSION}-${arch}-unknown-linux-musl.tar.gz"

  local deps=(git wget tar)
  local missing_deps=()
  local dep
  for dep in "${deps[@]}"; do
    if ! dpkg-query -W -f='${Status}' "$dep" 2>/dev/null | grep -q "install ok installed"; then
      missing_deps+=("$dep")
    fi
  done
  if (( ${#missing_deps[@]} > 0 )); then
    apt_update
    apt_install "${missing_deps[@]}" || die "$(msg 'Failed to install dovi_tool dependencies' 'dovi_tool 依赖安装失败')"
  fi

  local build_dir
  build_dir="$(mktemp -d)"

  (
    cd "$build_dir" || exit 1
    tmux_run "$(msg "Download ${tarball}" "下载 ${tarball}")" \
      wget "https://github.com/quietvoid/dovi_tool/releases/download/${DOVI_TOOL_VERSION}/${tarball}" || exit 1
    tmux_run "$(msg 'Extract dovi_tool tarball' '解压 dovi_tool 压缩包')" tar zxvf "$tarball" || exit 1
    install_configured_executable dovi_tool "$DOVI_TOOL_PATH" || exit 1
  ) || die "$(msg 'dovi_tool install failed' 'dovi_tool 安装失败')"

  rm -rf "$build_dir"
  log "$(msg 'dovi_tool installation complete' 'dovi_tool 安装完成')"
}

# ---------------------------------------------------------------------------
# hdr10plus_tool (official prebuilt musl release)
# ---------------------------------------------------------------------------

install_hdr10plus_tool() {
  local version
  version="$(latest_stable_tag https://github.com/quietvoid/hdr10plus_tool.git)"
  log "$(msg "Installing hdr10plus_tool ${version} (prebuilt)" "安装 hdr10plus_tool ${version}（预编译包）")"

  local installed_output=""
  if [[ -x "$HDR10PLUS_TOOL_PATH" ]]; then
    installed_output="$("$HDR10PLUS_TOOL_PATH" --version 2>&1 || true)"
  fi
  if [[ "$installed_output" == *"hdr10plus_tool ${version#v}"* ]]; then
    log "$(msg "Latest official hdr10plus_tool ${version} is already installed; skipping." "已安装最新官方 hdr10plus_tool ${version}，跳过。")"
    return 0
  fi

  local arch tarball
  case "$(uname -m)" in
    x86_64 | amd64)
      arch=x86_64
      ;;
    aarch64 | arm64)
      arch=aarch64
      ;;
    *)
      die "$(msg "Unsupported CPU architecture for hdr10plus_tool prebuilt: $(uname -m)" "当前 CPU 架构不支持预编译 hdr10plus_tool：$(uname -m)")"
      ;;
  esac
  tarball="hdr10plus_tool-${version#v}-${arch}-unknown-linux-musl.tar.gz"

  local deps=(git wget tar)
  local missing_deps=()
  local dep
  for dep in "${deps[@]}"; do
    if ! dpkg-query -W -f='${Status}' "$dep" 2>/dev/null | grep -q "install ok installed"; then
      missing_deps+=("$dep")
    fi
  done
  if (( ${#missing_deps[@]} > 0 )); then
    apt_update
    apt_install "${missing_deps[@]}" || die "$(msg 'Failed to install hdr10plus_tool dependencies' 'hdr10plus_tool 依赖安装失败')"
  fi

  local install_dir
  install_dir="$(mktemp -d)"
  (
    cd "$install_dir" || exit 1
    tmux_run "$(msg "Download ${tarball}" "下载 ${tarball}")" \
      wget "https://github.com/quietvoid/hdr10plus_tool/releases/download/${version}/${tarball}" || exit 1
    tmux_run "$(msg 'Extract hdr10plus_tool tarball' '解压 hdr10plus_tool 压缩包')" tar zxf "$tarball" || exit 1
    install_configured_executable hdr10plus_tool "$HDR10PLUS_TOOL_PATH" || exit 1
  ) || die "$(msg 'hdr10plus_tool install failed' 'hdr10plus_tool 安装失败')"

  rm -rf "$install_dir"
  "$HDR10PLUS_TOOL_PATH" --version 2>&1 | grep -F "hdr10plus_tool ${version#v}" >/dev/null || \
    die "$(msg 'Installed hdr10plus_tool verification failed' '安装后的 hdr10plus_tool 验证失败')"
  log "$(msg 'hdr10plus_tool installation complete' 'hdr10plus_tool 安装完成')"
}

# ---------------------------------------------------------------------------
# truehdd (prebuilt release binary for TrueHD+Atmos decode)
# ---------------------------------------------------------------------------

# Set TRUEHDD_VERSION to pin a release; otherwise resolve the latest published release.
TRUEHDD_VERSION="${TRUEHDD_VERSION:-}"

install_truehdd() {
  if [[ -z "$TRUEHDD_VERSION" ]]; then
    if ! TRUEHDD_VERSION="$(
      curl -fsSL https://api.github.com/repos/truehdd/truehdd/releases/latest \
        | python3 -c 'import json, sys; print(json.load(sys.stdin)["tag_name"])'
    )"; then
      die "$(msg 'Failed to resolve the latest published truehdd release' '无法获取 truehdd 最新正式发布版本')"
    fi
  fi
  log "$(msg "Installing truehdd ${TRUEHDD_VERSION} (prebuilt)" "安装 truehdd ${TRUEHDD_VERSION}（预编译包）")"

  if [[ -x "$TRUEHDD_PATH" ]]; then
    log "$(msg "truehdd already installed (${TRUEHDD_PATH}), skipping" "检测到 truehdd 已安装（${TRUEHDD_PATH}），跳过")"
    return 0
  fi

  local arch tarball
  case "$(uname -m)" in
    x86_64 | amd64)
      arch=x86_64
      ;;
    aarch64 | arm64)
      arch=aarch64
      ;;
    *)
      die "$(msg "Unsupported CPU architecture for truehdd prebuilt: $(uname -m)" "当前 CPU 架构不支持预编译 truehdd：$(uname -m)")"
      ;;
  esac
  tarball="truehdd-${TRUEHDD_VERSION}-${arch}-unknown-linux-gnu.tar.gz"

  local deps=(git wget tar)
  local missing_deps=()
  local dep
  for dep in "${deps[@]}"; do
    if ! dpkg-query -W -f='${Status}' "$dep" 2>/dev/null | grep -q "install ok installed"; then
      missing_deps+=("$dep")
    fi
  done
  if (( ${#missing_deps[@]} > 0 )); then
    apt_update
    apt_install "${missing_deps[@]}" || die "$(msg 'Failed to install truehdd dependencies' 'truehdd 依赖安装失败')"
  fi

  local build_dir
  build_dir="$(mktemp -d)"

  (
    cd "$build_dir" || exit 1
    tmux_run "$(msg "Download ${tarball}" "下载 ${tarball}")" \
      wget "https://github.com/truehdd/truehdd/releases/download/${TRUEHDD_VERSION}/${tarball}" || exit 1
    tmux_run "$(msg 'Extract truehdd tarball' '解压 truehdd 压缩包')" tar zxvf "$tarball" || exit 1
    install_configured_executable truehdd "$TRUEHDD_PATH" || exit 1
  ) || die "$(msg 'truehdd install failed' 'truehdd 安装失败')"

  rm -rf "$build_dir"
  log "$(msg 'truehdd installation complete' 'truehdd 安装完成')"
}

# ---------------------------------------------------------------------------
# dav1d (for mpv-build / ffmpeg --enable-libdav1d)
# ---------------------------------------------------------------------------

# mpv-build's ffmpeg expects dav1d >= 1.0.0; Ubuntu 22.04 / Debian 12 often ship 0.9.x only.
ensure_dav1d_for_mpv() {
  log "$(msg 'Checking dav1d (mpv-build ffmpeg requires >= 1.0.0)' '检查 dav1d（mpv-build 内置 ffmpeg 需要 >= 1.0.0）')"

  local pc_extra="/usr/local/lib/x86_64-linux-gnu/pkgconfig:/usr/local/lib/aarch64-linux-gnu/pkgconfig:/usr/local/lib/pkgconfig"
  local mod=""
  if PKG_CONFIG_PATH="${pc_extra}:${PKG_CONFIG_PATH:-}" pkg-config --exists dav1d 2>/dev/null; then
    mod="$(PKG_CONFIG_PATH="${pc_extra}:${PKG_CONFIG_PATH:-}" pkg-config --modversion dav1d 2>/dev/null | head -n 1 || true)"
  fi
  if [[ -n "${mod:-}" ]] && dpkg --compare-versions "${mod}" ge "1.0.0" 2>/dev/null; then
    log "$(msg "dav1d satisfied (${mod} >= 1.0.0), skipping source build" "dav1d 已满足（${mod} >= 1.0.0），跳过源码编译")"
    return 0
  fi

  log "$(msg "dav1d missing or too old (${mod:-none} < 1.0.0), building from Videolan git" "dav1d 缺失或版本过低（${mod:-无} < 1.0.0），将从 Videolan 源码编译安装")"

  command -v meson >/dev/null 2>&1 || die "$(msg 'meson is required to build dav1d' '编译 dav1d 需要 meson')"
  command -v ninja >/dev/null 2>&1 || die "$(msg 'ninja is required to build dav1d' '编译 dav1d 需要 ninja')"

  local build_dir
  build_dir="$(mktemp -d)"

  (
    cd "$build_dir" || exit 1
    tmux_run "$(msg 'Clone dav1d' '克隆 dav1d')" git clone https://code.videolan.org/videolan/dav1d.git || exit 1
    cd dav1d || exit 1
    tmux_run "$(msg 'dav1d meson setup' 'dav1d meson 配置')" meson setup build --buildtype release -Ddefault_library=static || exit 1
    tmux_run "$(msg 'dav1d ninja build' 'dav1d ninja 构建')" ninja -C build || exit 1
    tmux_run "$(msg 'dav1d ninja install' 'dav1d 安装')" sudo ninja -C build install || exit 1
    tmux_run "ldconfig" sudo ldconfig || exit 1
  ) || die "$(msg 'dav1d build/install failed' 'dav1d 编译/安装失败')"

  rm -rf "$build_dir"

  mod=""
  if PKG_CONFIG_PATH="${pc_extra}:${PKG_CONFIG_PATH:-}" pkg-config --exists dav1d 2>/dev/null; then
    mod="$(PKG_CONFIG_PATH="${pc_extra}:${PKG_CONFIG_PATH:-}" pkg-config --modversion dav1d 2>/dev/null | head -n 1 || true)"
  fi
  if [[ -z "${mod:-}" ]] || ! dpkg --compare-versions "${mod}" ge "1.0.0" 2>/dev/null; then
    die "$(msg "dav1d install verification failed (pkg-config modversion: ${mod:-none})" "dav1d 安装后校验失败（pkg-config 模块版本：${mod:-无}）")"
  fi
  log "$(msg "dav1d from source ready (${mod})" "dav1d 源码安装完成（${mod}）")"
}

# ---------------------------------------------------------------------------
# mpv + FFmpeg / FFprobe
# ---------------------------------------------------------------------------

__installed_ffmpeg_version() {
  local executable="$1"
  [[ -x "$executable" ]] || return 0
  "$executable" -version 2>/dev/null \
    | head -n 1 \
    | sed -nE 's/^ff(mpeg|probe) version n?([0-9]+([.][0-9]+){1,3}).*/\2/p'
}

__ffmpeg_has_libopus() {
  local executable="$1"
  [[ -x "$executable" ]] || return 1
  "$executable" -hide_banner -h encoder=libopus 2>&1 | grep '^Encoder libopus' >/dev/null
}

install_mpv() {
  log "$(msg 'Installing mpv with stable FFmpeg / FFprobe (mpv-build with dovi_tool)' '安装 mpv 与稳定版 FFmpeg / FFprobe（使用包含 dovi_tool 的 mpv-build）')"

  local required_mpv_version="0.41.0"
  local ffmpeg_tag target_ffmpeg_version installed_ffmpeg_version installed_ffprobe_version ffmpeg_is_current="false"
  ffmpeg_tag="$(latest_stable_tag "$FFMPEG_SOURCE_REPOSITORY" '^n[0-9]+([.][0-9]+)+$' 'n*')"
  target_ffmpeg_version="${ffmpeg_tag#n}"
  installed_ffmpeg_version="$(__installed_ffmpeg_version "$FFMPEG_PATH" | head -n 1 || true)"
  installed_ffprobe_version="$(__installed_ffmpeg_version "$FFPROBE_PATH" | head -n 1 || true)"
  if [[ -n "$installed_ffmpeg_version" && -n "$installed_ffprobe_version" ]] \
    && dpkg --compare-versions "$installed_ffmpeg_version" ge "$target_ffmpeg_version" \
    && dpkg --compare-versions "$installed_ffprobe_version" ge "$target_ffmpeg_version" \
    && __ffmpeg_has_libopus "$FFMPEG_PATH"; then
    ffmpeg_is_current="true"
  fi

  local is_ubuntu_2204="false"
  local is_debian_12="false"
  local needs_meson_prebuild="false"
  local mpv_build_env=()
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
      if ! has_libdovi_development; then
        log "$(msg 'mpv installed but libdovi development files are missing, installing libdovi' '检测到 mpv 已安装但缺少 libdovi 开发文件，尝试安装 libdovi')"
        install_libdovi
      fi
      if [[ "$ffmpeg_is_current" == "true" ]]; then
        log "$(msg "mpv, FFmpeg, FFprobe, and libopus support already satisfy the requirements (${current_mpv_version}; ${installed_ffmpeg_version}/${installed_ffprobe_version}), skipping" "mpv、FFmpeg、FFprobe 与 libopus 支持均已满足要求（${current_mpv_version}；${installed_ffmpeg_version}/${installed_ffprobe_version}），跳过编译安装")"
        return 0
      fi
      log "$(msg "mpv is current, but FFmpeg / FFprobe ${target_ffmpeg_version} with libopus support is required; rebuilding them together with mpv" "mpv 已满足要求，但需要带 libopus 支持的 FFmpeg / FFprobe ${target_ffmpeg_version}；将与 mpv 一并重新编译")"
    else
      log "$(msg "System mpv version is too old (${current_mpv_version:-unknown} < ${required_mpv_version}), rebuilding from source" "检测到系统 mpv 版本较旧（${current_mpv_version:-unknown} < ${required_mpv_version}），将从源码编译升级")"
    fi
  fi

  install_libdovi

  log "$(msg 'Installing mpv build dependencies' '安装 mpv 编译所需系统依赖')"
  local mpv_deps=(
    build-essential cmake meson ninja-build git pkg-config yasm nasm
    libdav1d-dev libopus-dev
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
      # libshaderc-dev is not available on Ubuntu 22.04; remove it from the list
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
    apt_install "${missing_deps[@]}" || die "$(msg 'Failed to install mpv dependencies' 'mpv 依赖安装失败，请检查网络或包名')"
  fi

  if [[ "$needs_meson_prebuild" == "true" ]]; then
    ensure_meson_version
    if ! sudo python3 -m pip --version >/dev/null 2>&1; then
      apt_update
      apt_install python3-pip || die "$(msg 'Failed to install python3-pip (root environment)' '安装 python3-pip 失败（root 环境）')"
    fi
    if ! sudo env PIP_DISABLE_PIP_VERSION_CHECK=1 python3 -m pip install --upgrade -q --progress-bar off meson --break-system-packages >/dev/null 2>&1; then
      log "$(msg 'pip in root env does not support --break-system-packages, retrying with compatible flags' 'root 环境 pip 不支持 --break-system-packages，回退到兼容参数重试')"
      sudo env PIP_DISABLE_PIP_VERSION_CHECK=1 python3 -m pip install --upgrade -q --progress-bar off meson >/dev/null 2>&1 || die "$(msg 'Failed to upgrade meson in root environment' 'root 环境升级 meson 失败')"
    fi
    export PATH="/usr/local/bin:$HOME/.local/bin:$PATH"
    # Prevent stale user-site Meson packages from shadowing the root-installed version across the build and install.
    mpv_build_env=(env PYTHONNOUSERSITE=1)
  fi

  export PATH="/usr/local/bin:${HOME}/.local/bin:${PATH:-}"
  ensure_dav1d_for_mpv

  local build_dir
  build_dir="$(mktemp -d)"

(
    cd "$build_dir" || exit 1

    log "$(msg 'Building mpv-build' '编译 mpv-build')"
    tmux_run "$(msg 'Download mpv-build' '下载 mpv-build')" git clone https://github.com/mpv-player/mpv-build.git || exit 1
    cd mpv-build || exit 1

    rm -rf mpv/build ffmpeg/build libass/build 2>/dev/null || true
    tmux_run "$(msg 'Select the latest stable FFmpeg release' '选择最新稳定版 FFmpeg')" ./use-ffmpeg-release || exit 1

    echo "--enable-libbluray" > ffmpeg_options || exit 1
    echo "--enable-libdav1d" >> ffmpeg_options || exit 1
    echo "--enable-libopus" >> ffmpeg_options || exit 1
    echo "-Dlibbluray=enabled" > mpv_options || exit 1
    if [[ "$is_ubuntu_2204" == "true" ]]; then
      # Ubuntu 22.04's rst2man rejects the --output option used by current mpv.
      echo "-Dmanpage-build=disabled" >> mpv_options || exit 1
    fi
    if [[ "$is_ubuntu_2204" == "true" || "$is_debian_12" == "true" ]]; then
      log "$(msg 'Compatibility mode detected (Ubuntu 22.04/Debian 12): disabling Vulkan/Shaderc in mpv-build libplacebo to ensure mpv compiles' '检测到系统需要兼容模式（Ubuntu 22.04/Debian 12），禁用 mpv-build 内置 libplacebo 的 Vulkan/Shaderc 构建以保证 mpv 可编译')"
      cat > libplacebo_options <<'EOF'
-Dvulkan=disabled
-Dshaderc=disabled
EOF
    fi

    export PKG_CONFIG_PATH="/usr/local/lib/x86_64-linux-gnu/pkgconfig:/usr/local/lib/aarch64-linux-gnu/pkgconfig:/usr/local/lib/pkgconfig:${HOME}/.local/lib/pkgconfig:${HOME}/.local/lib/x86_64-linux-gnu/pkgconfig:${HOME}/.local/lib/aarch64-linux-gnu/pkgconfig:${PKG_CONFIG_PATH:-}"
    export PATH="/usr/local/bin:$HOME/.local/bin:$PATH"

    tmux_run "mpv-build rebuild" "${mpv_build_env[@]}" ./rebuild -j"$(nproc)" || exit 1
    tmux_run "mpv-build install" sudo env PYTHONNOUSERSITE=1 "PATH=$PATH" "PKG_CONFIG_PATH=${PKG_CONFIG_PATH:-}" ./install || exit 1
    install_configured_executable build_libs/bin/ffmpeg "$FFMPEG_PATH" || exit 1
    install_configured_executable build_libs/bin/ffprobe "$FFPROBE_PATH" || exit 1
  ) || die "$(msg 'mpv build/install failed' 'mpv 编译/安装失败')"

  rm -rf "$build_dir"
  installed_ffmpeg_version="$(__installed_ffmpeg_version "$FFMPEG_PATH" | head -n 1 || true)"
  installed_ffprobe_version="$(__installed_ffmpeg_version "$FFPROBE_PATH" | head -n 1 || true)"
  if [[ -z "$installed_ffmpeg_version" || -z "$installed_ffprobe_version" ]] \
    || ! dpkg --compare-versions "$installed_ffmpeg_version" ge "$target_ffmpeg_version" \
    || ! dpkg --compare-versions "$installed_ffprobe_version" ge "$target_ffmpeg_version" \
    || ! __ffmpeg_has_libopus "$FFMPEG_PATH"; then
    die "$(msg 'Installed FFmpeg / FFprobe version or libopus support verification failed' '安装后的 FFmpeg / FFprobe 版本或 libopus 支持校验失败')"
  fi
  log "$(msg "mpv, FFmpeg, FFprobe, and libopus support installation complete (${installed_ffmpeg_version}/${installed_ffprobe_version})" "mpv、FFmpeg、FFprobe 与 libopus 支持安装完成（${installed_ffmpeg_version}/${installed_ffprobe_version}）")"
  if [[ "$needs_meson_prebuild" != "true" ]]; then
    ensure_meson_version
  fi
}

# ---------------------------------------------------------------------------
# L-SMASH
# ---------------------------------------------------------------------------

__lsmash_is_installed() {
  command -v pkg-config >/dev/null 2>&1 && pkg-config --exists liblsmash 2>/dev/null
}

install_lsmash() {
  log "$(msg 'Installing L-SMASH (build from source)' '安装 lsmash（从源码编译并安装）')"

  export PKG_CONFIG_PATH="/usr/local/lib/pkgconfig:/usr/local/lib/x86_64-linux-gnu/pkgconfig:/usr/local/lib/aarch64-linux-gnu/pkgconfig:${PKG_CONFIG_PATH:-}"

  if __lsmash_is_installed; then
    log "$(msg 'L-SMASH already installed (liblsmash pkg-config metadata detected), skipping build' \
      '检测到 L-SMASH 已安装（pkg-config 可识别 liblsmash），跳过编译安装')"
    return 0
  fi

  local deps=(build-essential git pkg-config)
  local missing_deps=()
  for dep in "${deps[@]}"; do
    if ! dpkg-query -W -f='${Status}' "$dep" 2>/dev/null | grep -q "install ok installed"; then
      missing_deps+=("$dep")
    fi
  done
  if (( ${#missing_deps[@]} > 0 )); then
    apt_update
    apt_install "${missing_deps[@]}" || die "$(msg 'Failed to install L-SMASH dependencies' 'lsmash 依赖安装失败')"
  fi

  local build_dir
  build_dir="$(mktemp -d)"

  (
    cd "$build_dir" || exit 1

    local lsmash_tag
    lsmash_tag="${LSMASH_VERSION:-$(latest_stable_tag https://github.com/l-smash/l-smash.git)}"
    tmux_run "$(msg "Clone L-SMASH ${lsmash_tag}" "克隆 lsmash ${lsmash_tag}")" \
      git clone --depth 1 --branch "$lsmash_tag" https://github.com/l-smash/l-smash.git l-smash || exit 1
    cd l-smash || exit 1

    log "$(msg 'Configuring and building L-SMASH' '配置与编译 lsmash')"
    tmux_run "lsmash configure" ./configure --enable-shared || exit 1
    tmux_run "lsmash make" make -j"$(nproc)" || exit 1
    tmux_run "lsmash install" sudo make install || exit 1
    sudo ldconfig || exit 1
  ) || die "$(msg 'L-SMASH build/install failed' 'lsmash 编译/安装失败')"

  rm -rf "$build_dir"
  __lsmash_is_installed || die "$(msg 'L-SMASH installation is missing liblsmash pkg-config metadata' 'L-SMASH 安装后缺少 liblsmash 的 pkg-config 元数据')"
  log "$(msg 'L-SMASH installation complete' 'lsmash 安装完成')"
}

# ---------------------------------------------------------------------------
# x265 (latest official stable release)
# ---------------------------------------------------------------------------

__patch_x265_hdr10plus_json11() {
  local source_file="$1/source/dynamicHDR10/json11/json11.cpp"
  [[ -f "$source_file" ]] || \
    die "$(msg 'x265 HDR10+ json11 source file is missing' 'x265 HDR10+ json11 源文件不存在')"
  if grep -Fxq '#include <cstdint>' "$source_file"; then
    return 0
  fi
  grep -Fxq '#include <limits>' "$source_file" || \
    die "$(msg 'x265 HDR10+ json11 compatibility patch context is missing' 'x265 HDR10+ json11 兼容补丁上下文不存在')"
  sed -i '/^#include <limits>$/a #include <cstdint>' "$source_file"
  grep -Fxq '#include <cstdint>' "$source_file" || \
    die "$(msg 'x265 HDR10+ json11 compatibility patch failed' 'x265 HDR10+ json11 兼容补丁失败')"
}

# $1 = absolute path to the official x265 repository root.
__build_x265_official_multilib() {
  local x265_repo="$1"
  local MULTIBUILD="${x265_repo}/build/linux"
  local SRCROOT="${x265_repo}/source"

  [[ -f "${SRCROOT}/CMakeLists.txt" ]] || \
    die "$(msg 'x265 source tree has no CMakeLists.txt' 'x265 源码目录中找不到 CMakeLists.txt')"
  __patch_x265_hdr10plus_json11 "$x265_repo" || return $?

  case ${MAKEFLAGS-} in
  '')
    local _j
    _j="$(nproc 2>/dev/null || getconf _NPROCESSORS_ONLN 2>/dev/null || echo 4)"
    case "$_j" in ''|*[!0-9]*) _j=4 ;; esac
    export MAKEFLAGS="-j${_j}"
    ;;
  esac

  local -a _x265_cmake_args=(
    "-DCMAKE_POLICY_VERSION_MINIMUM=3.10"
    "-DENABLE_SHARED=OFF"
    "-DENABLE_LIBNUMA=OFF"
    "-DENABLE_LSMASH=OFF"
    "-DENABLE_LAVF=OFF"
    "-DENABLE_AVISYNTH=OFF"
    "-DENABLE_VPYSYNTH=OFF"
  )
  local CXXBIN="${CXX:-c++}"
  local LINK_MODE="${X265_LINK:-auto}"
  local _libstd="" _libc=""
  if command -v "$CXXBIN" >/dev/null 2>&1; then
    _libstd="$("$CXXBIN" -print-file-name=libstdc++.a 2>/dev/null || true)"
    _libc="$("$CXXBIN" -print-file-name=libc.a 2>/dev/null || true)"
  fi
  local _stdc_ok=0 _libc_ok=0
  [[ -n "$_libstd" && -f "$_libstd" ]] && _stdc_ok=1
  [[ -n "$_libc" && -f "$_libc" ]] && _libc_ok=1

  local X265_CMAKE_EXE_LINKER_FLAGS=""
  case "$LINK_MODE" in
  full)
    if [[ "$_stdc_ok" != 1 || "$_libc_ok" != 1 ]]; then
      die "$(msg 'X265_LINK=full needs static libstdc++.a and libc.a (see compiler -print-file-name).' \
        'X265_LINK=full 需要 libstdc++.a 与 libc.a（可用编译器 -print-file-name 检查）。')"
    fi
    X265_CMAKE_EXE_LINKER_FLAGS=-static
    ;;
  mostly)
    if [[ "$_stdc_ok" != 1 ]]; then
      die "$(msg 'X265_LINK=mostly needs libstdc++.a from your g++ dev package.' \
        'X265_LINK=mostly 需要 g++ 开发包提供的 libstdc++.a。')"
    fi
    X265_CMAKE_EXE_LINKER_FLAGS="-static-libgcc -static-libstdc++"
    ;;
  x265-only)
    X265_CMAKE_EXE_LINKER_FLAGS=""
    ;;
  auto)
    # Do not use full -static here: multilib x265 often still pulls libc/libm via .so even when
    # libc.a exists, which breaks the link. Use mostly-static C++ or fully dynamic unless
    # X265_LINK=full (explicit) after installing a complete static toolchain.
    if [[ "$_stdc_ok" == 1 ]]; then
      X265_CMAKE_EXE_LINKER_FLAGS="-static-libgcc -static-libstdc++"
      log "$(msg 'x265 link mode: auto → mostly static C++ (-static-libgcc -static-libstdc++).' \
        'x265 链接方式：auto → 以静态 C++ 运行时为主（-static-libgcc -static-libstdc++）。')"
    else
      X265_CMAKE_EXE_LINKER_FLAGS=""
      log "$(msg 'x265 link mode: auto → dynamic C++ runtime (install libstdc++-*-dev for mostly-static).' \
        'x265 链接方式：auto → 动态 C++ 运行时（安装 libstdc++-*-dev 可启用 mostly-static）。')"
    fi
    ;;
  *)
    die "$(msg "Unknown X265_LINK=${LINK_MODE} (use auto|full|mostly|x265-only)." \
      "未知的 X265_LINK=${LINK_MODE}（请使用 auto|full|mostly|x265-only）。")"
    ;;
  esac

  mkdir -p "${MULTIBUILD}/8bit" "${MULTIBUILD}/10bit" "${MULTIBUILD}/12bit"

  log "$(msg 'x265: configuring 12-bit core (static, no CLI)' 'x265：配置 12-bit 核心（静态库，无 CLI）')"
  cd "${MULTIBUILD}/12bit" || die "$(msg 'Cannot cd to x265 12-bit build dir' '无法进入 x265 12-bit 构建目录')"
  tmux_run "$(msg 'x265 12-bit: cmake' 'x265 12-bit：cmake')" \
    cmake "${_x265_cmake_args[@]}" "$SRCROOT" \
      -DHIGH_BIT_DEPTH=ON \
      -DEXPORT_C_API=OFF \
      -DENABLE_SHARED=OFF \
      -DENABLE_HDR10_PLUS=ON \
      -DENABLE_CLI=OFF \
      -DMAIN12=ON \
      -DENABLE_LIBNUMA=OFF || return $?
  tmux_run "$(msg 'x265 12-bit: make' 'x265 12-bit：make')" make || return $?

  log "$(msg 'x265: configuring 10-bit core (static, no CLI)' 'x265：配置 10-bit 核心（静态库，无 CLI）')"
  cd "${MULTIBUILD}/10bit" || die "$(msg 'Cannot cd to x265 10-bit build dir' '无法进入 x265 10-bit 构建目录')"
  tmux_run "$(msg 'x265 10-bit: cmake' 'x265 10-bit：cmake')" \
    cmake "${_x265_cmake_args[@]}" "$SRCROOT" \
      -DHIGH_BIT_DEPTH=ON \
      -DEXPORT_C_API=OFF \
      -DENABLE_SHARED=OFF \
      -DENABLE_HDR10_PLUS=ON \
      -DENABLE_CLI=OFF \
      -DENABLE_LIBNUMA=OFF || return $?
  tmux_run "$(msg 'x265 10-bit: make' 'x265 10-bit：make')" make || return $?

  log "$(msg 'x265: configuring 8-bit multilib CLI' 'x265：配置 8-bit multilib 可执行文件')"
  cd "${MULTIBUILD}/8bit" || die "$(msg 'Cannot cd to x265 8-bit build dir' '无法进入 x265 8-bit 构建目录')"
  ln -sf ../10bit/libx265.a libx265_main10.a || return $?
  ln -sf ../12bit/libx265.a libx265_main12.a || return $?
  if [[ -n "$X265_CMAKE_EXE_LINKER_FLAGS" ]]; then
    tmux_run "$(msg 'x265 8-bit: cmake (with linker flags)' 'x265 8-bit：cmake（含链接器参数）')" \
      cmake "${_x265_cmake_args[@]}" "$SRCROOT" \
        -DENABLE_SHARED=OFF \
        -DENABLE_LIBNUMA=OFF \
        -DENABLE_HDR10_PLUS=ON \
        -DCMAKE_EXE_LINKER_FLAGS="$X265_CMAKE_EXE_LINKER_FLAGS" \
        -DEXTRA_LIB="x265_main10.a;x265_main12.a" \
        -DEXTRA_LINK_FLAGS=-L. \
        -DLINKED_10BIT=ON \
        -DLINKED_12BIT=ON || return $?
  else
    tmux_run "$(msg 'x265 8-bit: cmake' 'x265 8-bit：cmake')" \
      cmake "${_x265_cmake_args[@]}" "$SRCROOT" \
        -DENABLE_SHARED=OFF \
        -DENABLE_LIBNUMA=OFF \
        -DENABLE_HDR10_PLUS=ON \
        -DEXTRA_LIB="x265_main10.a;x265_main12.a" \
        -DEXTRA_LINK_FLAGS=-L. \
        -DLINKED_10BIT=ON \
        -DLINKED_12BIT=ON || return $?
  fi
  tmux_run "$(msg 'x265 8-bit: make' 'x265 8-bit：make')" make || return $?

  log "$(msg 'x265: merging static libraries (ar)' 'x265：合并静态库（ar）')"
  mv libx265.a libx265_main.a || return $?
  if [[ "$(uname)" == "Linux" ]]; then
    ar -M <<EOF || return $?
CREATE libx265.a
ADDLIB libx265_main.a
ADDLIB libx265_main10.a
ADDLIB libx265_main12.a
SAVE
END
EOF
  else
    libtool -static -o libx265.a libx265_main.a libx265_main10.a libx265_main12.a 2>/dev/null || return $?
  fi

  if command -v strip >/dev/null 2>&1; then
    strip "${MULTIBUILD}/8bit/x265" 2>/dev/null || true
  fi

  local _x265_out="${MULTIBUILD}/8bit/x265"
  [[ -f "$_x265_out" ]] || die "$(msg 'x265 binary missing after build' '编译完成后未找到 x265 可执行文件')"
  log "$(msg "Installing x265 to ${X265_PATH}" "正在将 x265 安装到 ${X265_PATH}")"
  install_configured_executable "$_x265_out" "$X265_PATH" || return $?
  bluray_sudo mkdir -p "$(dirname -- "$X265_FEATURE_FILE")" || return $?
  printf '%s\n' 'hdr10plus-all-depths' | bluray_sudo tee "$X265_FEATURE_FILE" >/dev/null || return $?
}

install_x265() {
  local x265_version
  x265_version="$(latest_stable_tag "$X265_SOURCE_REPOSITORY" '^[0-9]+([.][0-9]+)+$' '[0-9]*')"
  log "$(msg "Installing official x265 ${x265_version}" "安装官方 x265 ${x265_version}")"

  local installed_output="" installed_help=""
  if [[ -x "$X265_PATH" ]]; then
    installed_output="$("$X265_PATH" --version 2>&1 || true)"
    installed_help="$("$X265_PATH" --help 2>&1 || true)"
  fi
  if [[ "$installed_output" == *"encoder version ${x265_version}"* &&
        "$installed_output" == *"8bit+10bit+12bit"* &&
        "$installed_help" == *"--dhdr10-info"* &&
        "$installed_help" == *"--dolby-vision-profile"* &&
        "$installed_help" == *"--dolby-vision-rpu"* &&
        -f "$X265_FEATURE_FILE" ]] &&
        grep -Fxq 'hdr10plus-all-depths' "$X265_FEATURE_FILE"; then
    log "$(msg "Latest official x265 ${x265_version} is already installed; skipping build." "已安装最新官方 x265 ${x265_version}，跳过编译。")"
    return 0
  fi

  local deps=(build-essential cmake git nasm python3)
  apt_update
  apt_install "${deps[@]}" || die "$(msg 'Failed to install x265 dependencies' 'x265 依赖安装失败')"

  local build_dir
  build_dir="$(mktemp -d)"

  (
    cd "$build_dir" || exit 1
    tmux_run "$(msg "Clone official x265 ${x265_version}" "克隆官方 x265 ${x265_version}")" \
      git clone --depth 1 --branch "$x265_version" "$X265_SOURCE_REPOSITORY" x265 || exit 1
    __build_x265_official_multilib "${build_dir}/x265" || exit 1
  ) || die "$(msg 'x265 build or install failed' 'x265 编译或安装过程中出错')"

  rm -rf "$build_dir"
  "$X265_PATH" --version 2>&1 | grep -F "encoder version ${x265_version}" >/dev/null || \
    die "$(msg 'Installed x265 version verification failed' '安装后的 x265 版本验证失败')"
  "$X265_PATH" --version 2>&1 | grep -F '8bit+10bit+12bit' >/dev/null || \
    die "$(msg 'Installed x265 multilib verification failed' '安装后的 x265 多位深验证失败')"
  installed_help="$("$X265_PATH" --help 2>&1 || true)"
  [[ "$installed_help" == *"--dhdr10-info"* ]] || \
    die "$(msg 'Installed x265 native HDR10+ verification failed' '安装后的 x265 原生 HDR10+ 验证失败')"
  [[ "$installed_help" == *"--dolby-vision-profile"* &&
     "$installed_help" == *"--dolby-vision-rpu"* ]] || \
    die "$(msg 'Installed x265 native Dolby Vision verification failed' '安装后的 x265 原生 Dolby Vision 验证失败')"
  grep -Fxq 'hdr10plus-all-depths' "$X265_FEATURE_FILE" || \
    die "$(msg 'Installed x265 HDR10+ core verification failed' '安装后的 x265 HDR10+ 核心验证失败')"
  log "$(msg 'x265 installation successful!' 'x265 安装成功！')"
}

# ---------------------------------------------------------------------------
# x264
# ---------------------------------------------------------------------------

install_x264() {
  local x264_repository=""
  local x264_commit=""
  local repository
  for repository in "$X264_SOURCE_REPOSITORY" "$X264_SOURCE_MIRROR"; do
    x264_commit="$(
      git ls-remote "$repository" refs/heads/master 2>/dev/null \
        | awk 'NR == 1 { print $1 }' || true
    )"
    if [[ -n "$x264_commit" ]]; then
      x264_repository="$repository"
      break
    fi
    if [[ "$repository" == "$X264_SOURCE_REPOSITORY" ]]; then
      log "$(msg 'The official x264 repository is unavailable; trying the GitHub mirror' 'x264 官方仓库不可用，尝试 GitHub 镜像')"
    fi
  done
  [[ -n "$x264_repository" && -n "$x264_commit" ]] || \
    die "$(msg 'Failed to resolve the latest x264 master revision from the official repository or mirror' '无法从 x264 官方仓库或镜像解析 master 的最新版本')"
  log "$(msg "Installing the latest x264 master from ${x264_repository}" "从 ${x264_repository} 安装最新 x264 master")"

  local version_file="$X264_VERSION_FILE"
  local installed_commit=""
  if [[ -x "$X264_PATH" && -f "$version_file" ]]; then
    installed_commit="$(tr -d '\r\n' < "$version_file")"
  fi
  if [[ "$installed_commit" == "$x264_commit" ]]; then
    log "$(msg 'The latest x264 master is already installed; skipping build.' '已安装最新 x264 master，跳过编译。')"
    return 0
  fi

  local deps=(build-essential git nasm)
  local missing_deps=()
  local dep
  for dep in "${deps[@]}"; do
    if ! dpkg-query -W -f='${Status}' "$dep" 2>/dev/null | grep -q "install ok installed"; then
      missing_deps+=("$dep")
    fi
  done
  if (( ${#missing_deps[@]} > 0 )); then
    apt_update
    apt_install "${missing_deps[@]}" || die "$(msg 'Failed to install x264 dependencies' 'x264 依赖安装失败')"
  fi

  local build_dir
  build_dir="$(mktemp -d)"

  (
    cd "$build_dir" || exit 1
    tmux_run "$(msg 'Clone the latest x264 master' '克隆最新 x264 master')" \
      git clone --depth 1 --branch master "$x264_repository" x264 || exit 1
    cd x264 || exit 1
    x264_commit="$(git rev-parse HEAD)"
    local x264_configure_args=(
      --enable-static
      --bit-depth=all
      --chroma-format=all
      --disable-opencl
      --enable-lto
    )
    local libavutil_major=""
    libavutil_major="$(pkg-config --modversion libavutil 2>/dev/null | cut -d. -f1 || true)"
    if [[ "$libavutil_major" =~ ^[0-9]+$ ]] \
        && (( libavutil_major >= 60 )) \
        && { ! grep -Fq AV_FRAME_FLAG_INTERLACED input/lavf.c \
             || ! grep -Fq AV_FRAME_FLAG_TOP_FIELD_FIRST input/lavf.c; }; then
      x264_configure_args+=(--disable-lavf)
    fi
    tmux_run "x264 configure" ./configure "${x264_configure_args[@]}" || exit 1
    tmux_run "x264 make" make -j"$(nproc)" || exit 1
    install_configured_executable x264 "$X264_PATH" || exit 1
    bluray_sudo mkdir -p "$(dirname -- "$version_file")" || exit 1
    printf '%s\n' "$x264_commit" | bluray_sudo tee "$version_file" >/dev/null || exit 1
  ) || die "$(msg 'x264 build/install failed' 'x264 编译/安装失败')"

  rm -rf "$build_dir"
  "$X264_PATH" --version >/dev/null 2>&1 || \
    die "$(msg 'Installed x264 verification failed' '安装后的 x264 验证失败')"
  log "$(msg 'x264 installation complete' 'x264 安装完成')"
}
# ---------------------------------------------------------------------------
# SVT-AV1 (AOMediaCodec + 12-bit patches)
# ---------------------------------------------------------------------------

__apply_svt_av1_source_patches() {
  local svt_root="$1"
  command -v python3 >/dev/null 2>&1 || \
    die "$(msg 'python3 is required for SVT-AV1 source patches.' '应用 SVT-AV1 源码补丁需要 python3。')"
  log "$(msg 'SVT-AV1: applying 12-bit source patches...' 'SVT-AV1：正在应用 12-bit 源码补丁…')"
  python3 - "$svt_root" <<'SVTAV1PY'
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
    # Upstream write_bitdepth() logs SVT_ERROR("Profile 2 Not supported") on the *valid* path for
    # Professional + 10/12-bit; the second bit is still written. Remove the bogus line (see entropy_coding.c).
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
SVTAV1PY
  local patch_status=$?
  if [[ "$patch_status" -ne 0 ]]; then
    return "$patch_status"
  fi
  log "$(msg 'SVT-AV1: source patch step finished.' 'SVT-AV1：源码补丁步骤已完成。')"
}

__installed_svt_av1_version() {
  [[ -x "$SVT_AV1_PATH" ]] || return 0
  { "$SVT_AV1_PATH" --version 2>&1 || true; } \
    | grep -oE '[vV]?[0-9]+([.][0-9]+){1,3}' \
    | head -n 1 \
    | sed -E 's/^[vV]//'
}

install_svt_av1() {
  local svt_tag target_version installed_version
  svt_tag="${SVT_AV1_VERSION:-$(latest_stable_tag "$SVT_AV1_SOURCE_REPOSITORY")}"
  target_version="${svt_tag#v}"
  installed_version="$(__installed_svt_av1_version | head -n 1 || true)"

  if [[ -n "$installed_version" ]] && dpkg --compare-versions "$installed_version" ge "$target_version"; then
    log "$(msg "SvtAv1EncApp is current (${installed_version} >= ${target_version}), skipping build" "SvtAv1EncApp 已是当前版本（${installed_version} >= ${target_version}），跳过编译")"
    return 0
  fi
  log "$(msg "Installing SVT-AV1 ${target_version} (attempting experimental 12-bit patches)" "正在安装 SVT-AV1 ${target_version}（尝试应用实验性 12-bit 补丁）")"

  local deps=(build-essential cmake git python3 nasm)
  apt_update
  apt_install "${deps[@]}" || die "$(msg 'Failed to install SVT-AV1 dependencies' 'SVT-AV1 依赖安装失败')"

  local build_dir
  build_dir="$(mktemp -d)"

  (
    cd "$build_dir" || exit 1
    tmux_run "$(msg 'Clone SVT-AV1' '克隆 SVT-AV1')" \
      git clone --depth 1 --branch "$svt_tag" "$SVT_AV1_SOURCE_REPOSITORY" SVT-AV1 || exit 1
    local patch_applied="false"
    if __apply_svt_av1_source_patches "${build_dir}/SVT-AV1"; then
      patch_applied="true"
    else
      log "$(msg 'The experimental SVT-AV1 12-bit patch does not match this release; building the unmodified upstream source with 8/10-bit support' 'SVT-AV1 实验性 12-bit 补丁不适用于此版本；将编译未修改的上游源码，支持 8/10-bit')"
    fi
    if ! tmux_run "$(msg 'SVT-AV1: build release static' 'SVT-AV1：release static 编译')" \
      bash -c "set -e; cd '${build_dir}/SVT-AV1/Build/linux' && ./build.sh release static"; then
      [[ "$patch_applied" == "true" ]] || exit 1
      log "$(msg 'The experimental SVT-AV1 build failed; retrying with the unmodified upstream source' 'SVT-AV1 实验性版本编译失败；正在使用未修改的上游源码重试')"
      rm -rf "${build_dir}/SVT-AV1"
      tmux_run "$(msg 'Clone unmodified SVT-AV1 fallback' '克隆未修改的 SVT-AV1 回退源码')" \
        git clone --depth 1 --branch "$svt_tag" "$SVT_AV1_SOURCE_REPOSITORY" SVT-AV1 || exit 1
      tmux_run "$(msg 'SVT-AV1: build upstream release static' 'SVT-AV1：编译上游 release static 版本')" \
        bash -c "set -e; cd '${build_dir}/SVT-AV1/Build/linux' && ./build.sh release static" || exit 1
    fi
    _svt_bin="${build_dir}/SVT-AV1/Bin/Release/SvtAv1EncApp"
    [[ -f "$_svt_bin" ]] || exit 1
    log "$(msg "Installing SvtAv1EncApp to ${SVT_AV1_PATH}" "正在安装 SvtAv1EncApp 到 ${SVT_AV1_PATH}")"
    install_configured_executable "$_svt_bin" "$SVT_AV1_PATH" || exit 1
  ) || die "$(msg 'SVT-AV1 build or install failed' 'SVT-AV1 编译或安装失败')"

  rm -rf "$build_dir"
  installed_version="$(__installed_svt_av1_version | head -n 1 || true)"
  if [[ -z "$installed_version" ]] || ! dpkg --compare-versions "$installed_version" ge "$target_version"; then
    die "$(msg 'Installed SVT-AV1 version verification failed' '安装后的 SVT-AV1 版本校验失败')"
  fi
  log "$(msg "SVT-AV1 installation complete (${installed_version})" "SVT-AV1 安装完成（${installed_version}）")"
}

# ---------------------------------------------------------------------------
# tsMuxer
# ---------------------------------------------------------------------------

TSMUXER_VERSION="${TSMUXER_VERSION:-}"

install_tsmuxer() {
  local tsmuxer_tag tsmuxer_version
  tsmuxer_tag="${TSMUXER_VERSION:-$(latest_stable_tag https://github.com/justdan96/tsMuxer.git)}"
  tsmuxer_version="${tsmuxer_tag#v}"
  log "$(msg "Installing tsMuxer ${tsmuxer_version}" "安装 tsMuxer ${tsmuxer_version}")"

  if [[ -x "$TS_MUXER_PATH" ]]; then
    log "$(msg 'tsMuxeR already installed, skipping' '检测到 tsMuxeR 已安装，跳过')"
    return 0
  fi

  local deps=(git wget unzip)
  local missing_deps=()
  local dep
  for dep in "${deps[@]}"; do
    if ! dpkg-query -W -f='${Status}' "$dep" 2>/dev/null | grep -q "install ok installed"; then
      missing_deps+=("$dep")
    fi
  done
  if (( ${#missing_deps[@]} > 0 )); then
    apt_update
    apt_install "${missing_deps[@]}" || die "$(msg 'Failed to install tsMuxer dependencies' 'tsMuxer 依赖安装失败')"
  fi

  local build_dir
  build_dir="$(mktemp -d)"

  (
    cd "$build_dir" || exit 1
    local archive="tsMuxer-${tsmuxer_version}-linux.zip"
    tmux_run "$(msg "Download ${archive}" "下载 ${archive}")" \
      wget "https://github.com/justdan96/tsMuxer/releases/download/${tsmuxer_tag}/${archive}" || exit 1
    tmux_run "$(msg 'Extract tsMuxer zip package' '解压 tsMuxer 压缩包')" unzip "$archive" || exit 1
    install_configured_executable tsMuxeR "$TS_MUXER_PATH" || exit 1
  ) || die "$(msg 'tsMuxer install failed' 'tsMuxer 安装失败')"

  rm -rf "$build_dir"
  log "$(msg 'tsMuxer installation complete' 'tsMuxer 安装完成')"
}

# ---------------------------------------------------------------------------
# FDK-AAC + fdkaac CLI (nu774)
# ---------------------------------------------------------------------------

__installed_fdkaac_version() {
  [[ -x "$FDK_AAC_PATH" ]] || return 0
  { "$FDK_AAC_PATH" -h 2>&1 || true; } \
    | sed -nE 's/^[[:space:]]*fdkaac[[:space:]]+[vV]?([0-9]+([.][0-9]+){1,3}).*/\1/p' \
    | head -n 1
}

install_fdk_aac() {
  local fdk_aac_tag fdkaac_tag target_version installed_version
  fdk_aac_tag="${FDK_AAC_VERSION:-$(latest_stable_tag "$FDK_AAC_SOURCE_REPOSITORY")}"
  fdkaac_tag="${FDKAAC_VERSION:-$(latest_stable_tag "$FDKAAC_SOURCE_REPOSITORY")}"
  target_version="${fdkaac_tag#v}"
  installed_version="$(__installed_fdkaac_version || true)"

  if [[ -n "$installed_version" ]] && dpkg --compare-versions "$installed_version" ge "$target_version"; then
    log "$(msg "fdkaac is current (${installed_version} >= ${target_version}), skipping build" "fdkaac 已是当前版本（${installed_version} >= ${target_version}），跳过编译")"
    return 0
  fi
  log "$(msg "Installing FDK-AAC ${fdk_aac_tag#v} and fdkaac ${target_version}" "正在安装 FDK-AAC ${fdk_aac_tag#v} 和 fdkaac ${target_version}")"

  local deps=(
    build-essential wget tar git autoconf automake libtool pkg-config
  )
  local missing_deps=()
  local dep
  for dep in "${deps[@]}"; do
    if ! dpkg-query -W -f='${Status}' "$dep" 2>/dev/null | grep -q "install ok installed"; then
      missing_deps+=("$dep")
    fi
  done
  if (( ${#missing_deps[@]} > 0 )); then
    apt_update
    apt_install "${missing_deps[@]}" || die "$(msg 'Failed to install FDK-AAC build dependencies' 'FDK-AAC 编译依赖安装失败')"
  fi

  local build_dir
  build_dir="$(mktemp -d)"

  (
    cd "$build_dir" || exit 1
    tmux_run "$(msg "Clone fdk-aac ${fdk_aac_tag}" "克隆 fdk-aac ${fdk_aac_tag}")" \
      git clone --depth 1 --branch "$fdk_aac_tag" "$FDK_AAC_SOURCE_REPOSITORY" fdk-aac || exit 1
    cd fdk-aac || exit 1
    tmux_run "$(msg 'fdk-aac: autogen.sh' 'fdk-aac：autogen.sh')" ./autogen.sh || exit 1
    tmux_run "$(msg 'fdk-aac: configure' 'fdk-aac：configure')" ./configure || exit 1
    tmux_run "$(msg 'fdk-aac: make' 'fdk-aac：make')" make -j"$(nproc)" || exit 1
    tmux_run "$(msg 'fdk-aac: make install' 'fdk-aac：make install')" sudo make install || exit 1
    sudo ldconfig || true
    cd "$build_dir" || exit 1
    tmux_run "$(msg "Clone fdkaac ${fdkaac_tag} (nu774)" "克隆 fdkaac ${fdkaac_tag}（nu774）")" \
      git clone --depth 1 --branch "$fdkaac_tag" "$FDKAAC_SOURCE_REPOSITORY" fdkaac || exit 1
    cd fdkaac || exit 1
    tmux_run "$(msg 'fdkaac: autoreconf -fi' 'fdkaac：autoreconf -fi')" autoreconf -fi || exit 1
    tmux_run "$(msg 'fdkaac: configure' 'fdkaac：configure')" ./configure || exit 1
    tmux_run "$(msg 'fdkaac: make' 'fdkaac：make')" make -j"$(nproc)" || exit 1
    tmux_run "$(msg 'fdkaac: make install' 'fdkaac：make install')" sudo make install || exit 1
    sudo ldconfig || true
    install_command_at_configured_path fdkaac "$FDK_AAC_PATH" || exit 1
  ) || die "$(msg 'FDK-AAC / fdkaac build or install failed' 'FDK-AAC / fdkaac 编译或安装失败')"

  rm -rf "$build_dir"
  installed_version="$(__installed_fdkaac_version || true)"
  if [[ -z "$installed_version" ]] || ! dpkg --compare-versions "$installed_version" ge "$target_version"; then
    die "$(msg 'Installed fdkaac version verification failed' '安装后的 fdkaac 版本校验失败')"
  fi
  log "$(msg "FDK-AAC and fdkaac installation complete (${installed_version})" "FDK-AAC 与 fdkaac 安装完成（${installed_version}）")"
}

# ---------------------------------------------------------------------------
# FLAC
# ---------------------------------------------------------------------------

install_flac() {
  local flac_tag latest_flac_version flac_bin=""
  local flac_source_path="/usr/local/bin/flac"
  flac_tag="${FLAC_VERSION:-$(latest_stable_tag https://github.com/xiph/flac.git)}"
  latest_flac_version="${flac_tag#v}"
  log "$(msg "Installing latest flac (${latest_flac_version}, build from source)" "安装最新 flac（${latest_flac_version}，从源码编译并安装）")"

  # A source build is owned by /usr/local; the configured runtime path may
  # still contain an older distribution package from an earlier setup run.
  if [[ -x "$flac_source_path" ]]; then
    flac_bin="$flac_source_path"
  elif [[ -x "$FLAC_PATH" ]]; then
    flac_bin="$FLAC_PATH"
  fi

  if [[ -n "$flac_bin" ]]; then
    local flac_version
    flac_version=$("$flac_bin" --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -n 1 || true)

    if [[ -n "$flac_version" ]]; then
      if dpkg --compare-versions "$flac_version" ge "$latest_flac_version"; then
        install_configured_executable "$flac_bin" "$FLAC_PATH"
        log "$(msg "flac already installed and current (${flac_version} >= ${latest_flac_version}), skipping" "检测到 flac 已安装且为当前版本（${flac_version} >= ${latest_flac_version}），跳过编译安装")"
        return 0
      fi
      log "$(msg "flac is outdated (${flac_version} < ${latest_flac_version}), removing it before rebuilding" "检测到 flac 版本过旧（${flac_version} < ${latest_flac_version}），卸载后重新编译")"
      sudo apt-get remove -y flac >/dev/null 2>&1 || true
      bluray_sudo rm -f "$flac_bin"
    else
      log "$(msg 'Cannot parse installed flac version, attempting to rebuild' '无法解析已安装的 flac 版本，尝试重新编译安装')"
      sudo apt-get remove -y flac >/dev/null 2>&1 || true
      bluray_sudo rm -f "$flac_bin"
    fi
  fi

  local deps=(libogg-dev libtool-bin gettext git)
  local missing_deps=()
  for dep in "${deps[@]}"; do
    if ! dpkg-query -W -f='${Status}' "$dep" 2>/dev/null | grep -q "install ok installed"; then
      missing_deps+=("$dep")
    fi
  done
  if (( ${#missing_deps[@]} > 0 )); then
    apt_update
    apt_install "${missing_deps[@]}" || die "$(msg 'Failed to install flac dependencies' 'flac 依赖安装失败，请检查网络或包名')"
  fi

  local build_dir
  build_dir="$(mktemp -d)"

  (
    cd "$build_dir" || exit 1
    tmux_run "$(msg "Clone flac ${flac_tag}" "克隆 flac ${flac_tag}")" \
      git clone --depth 1 --branch "$flac_tag" https://github.com/xiph/flac.git flac || exit 1
    cd flac || exit 1

    log "$(msg 'Configuring and building flac' '配置与编译 flac')"
    tmux_run "flac autogen" ./autogen.sh || exit 1
    tmux_run "flac configure" ./configure --enable-static --enable-shared --enable-64-bit-words || exit 1
    tmux_run "flac make" make -j"$(nproc)" || exit 1
    tmux_run "flac install" sudo make install || exit 1
    sudo ldconfig || exit 1
    install_configured_executable /usr/local/bin/flac "$FLAC_PATH" || exit 1
  ) || die "$(msg 'flac build/install failed' 'flac 编译/安装失败')"

  rm -rf "$build_dir"
  local installed_flac_version
  installed_flac_version=$("$FLAC_PATH" --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -n 1 || true)
  if [[ -z "$installed_flac_version" ]] || ! dpkg --compare-versions "$installed_flac_version" ge "$latest_flac_version"; then
    die "$(msg "Installed flac verification failed at ${FLAC_PATH}" "安装后的 flac 在 ${FLAC_PATH} 验证失败")"
  fi
  log "$(msg 'flac installation complete' 'flac 安装完成')"
}

# ---------------------------------------------------------------------------
# zimg
# ---------------------------------------------------------------------------

install_zimg_latest() {
  local header=""
  if [[ -f /usr/local/include/zimg.h ]]; then
    header="/usr/local/include/zimg.h"
  elif [[ -f /usr/include/zimg.h ]]; then
    header="/usr/include/zimg.h"
  fi

  if [[ -n "${header:-}" ]] && grep -q "ZIMG_TRANSFER_ST428" "$header"; then
    log "$(msg 'zimg already contains ZIMG_TRANSFER_ST428, skipping upgrade' '检测到 zimg 已包含 ZIMG_TRANSFER_ST428，跳过升级')"
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
    apt_install "${missing_deps[@]}" || die "$(msg 'Failed to install zimg build dependencies' 'zimg 编译依赖安装失败')"
  fi

  log "$(msg 'Current zimg version is too old (missing ZIMG_TRANSFER_ST428), building latest zimg from source...' '当前 zimg 版本过低（缺少 ZIMG_TRANSFER_ST428），开始编译安装最新版 zimg...')"

  local build_dir
  build_dir="$(mktemp -d)"
  (
    cd "$build_dir" || exit 1
    tmux_run "$(msg 'Download zimg' '下载 zimg')" git clone --depth 1 --recursive https://github.com/sekrit-twc/zimg.git . || exit 1
    tmux_run "zimg autogen" ./autogen.sh || exit 1
    tmux_run "zimg configure" ./configure --prefix=/usr/local || exit 1
    tmux_run "zimg make" make -j"$(nproc)" || exit 1
    tmux_run "zimg install" sudo make install || exit 1
  ) || die "$(msg 'zimg build/install failed' 'zimg 编译/安装失败')"
  rm -rf "$build_dir"
  sudo ldconfig
  log "$(msg 'Latest zimg installation complete' '最新版 zimg 安装完成')"
}

# ---------------------------------------------------------------------------
# VapourSynth
# ---------------------------------------------------------------------------

install_vapoursynth() {
  log "$(msg 'Installing VapourSynth (build from source)' '安装 VapourSynth（从源码编译并安装）')"

  log "$(msg 'Checking and upgrading Cython for VapourSynth compilation' '检查并升级 Cython 以支持 VapourSynth 编译')"
  if ! python3 -m pip --version >/dev/null 2>&1; then
    apt_update
    apt_install python3-pip || die "$(msg 'Failed to install python3-pip' '安装 python3-pip 失败')"
  fi
  if ! python3 -m pip install --user --upgrade cython --break-system-packages >/dev/null 2>&1; then
    log "$(msg 'pip does not support --break-system-packages, retrying with compatible flags' '当前 pip 不支持 --break-system-packages，回退到兼容参数重试')"
    python3 -m pip install --user --upgrade cython >/dev/null 2>&1 || die "$(msg 'Failed to upgrade Cython' 'Cython 升级失败')"
  fi
  export PATH="$HOME/.local/bin:$PATH"

  # VapourSynth-classic may not generate vspipe or may place it under /usr/local/bin.
  # Relax the check: just verify that the library or executable exists.
  if [[ -f "/usr/local/lib/libvapoursynth.so" ]] || sudo ldconfig -p 2>/dev/null | grep -qE '\blibvapoursynth\.so\b'; then
    log "$(msg 'VapourSynth already installed (libvapoursynth.so found), skipping' '检测到 VapourSynth 已安装（找到 libvapoursynth.so），跳过编译安装')"
    return 0
  fi

  install_zimg_latest

  # Verify Cython version >= 3.0
  local cython_cmd="cython"
  if ! command -v cython >/dev/null 2>&1; then
    if command -v cython3 >/dev/null 2>&1; then
      cython_cmd="cython3"
    else
      die "$(msg 'cython/cython3 not found' '未找到 cython/cython3')"
    fi
  fi
  CYTHON_V=$("$cython_cmd" --version 2>&1 | grep -oP '\d+\.\d+\.\d+' | head -n 1)
  if [[ "${CYTHON_V%%.*}" -lt 3 ]]; then
      die "$(msg "Cython version too low ($CYTHON_V); VapourSynth requires >= 3.0.0" "Cython 版本过低 ($CYTHON_V)，编译 VapourSynth 需要 3.0.0 以上版本")"
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
    apt_install "${missing_deps[@]}" || die "$(msg 'Failed to install VapourSynth dependencies' 'VapourSynth 依赖安装失败')"
  fi

  local build_dir
  build_dir="$(mktemp -d)"

  (
    cd "$build_dir" || exit 1

    # The originally provided URL returns 404; replaced with the GitHub archive link
    # which produces the same directory name after extraction.
    tmux_run "$(msg 'Download VapourSynth R57.A12' '下载 VapourSynth R57.A12')" wget -O R57.A12.tar.gz https://github.com/AmusementClub/vapoursynth-classic/archive/refs/tags/R57.A12.tar.gz || exit 1

    log "$(msg 'Extracting VapourSynth source tarball' '解压 VapourSynth 源码包')"
    tmux_run "$(msg 'Extract VapourSynth R57.A12' '解压 VapourSynth R57.A12')" tar zxvf R57.A12.tar.gz || exit 1
    cd vapoursynth-classic-R57.A12 || exit 1

    # VapourSynth-classic R57.A12 uses an API removed in FFmpeg 8; the replacement also supports older FFmpeg.
    if [[ -f "src/filters/subtext/image.cpp" ]] && grep -Fq 'avcodec_close(' src/filters/subtext/image.cpp; then
      log "$(msg 'Applying the FFmpeg 8.0+ API compatibility patch to VapourSynth...' '正在为 VapourSynth 应用 FFmpeg 8.0+ API 兼容性补丁...')"
      sed -i 's/avcodec_close(\(.*\));/avcodec_free_context(\&\(\1\));/g' src/filters/subtext/image.cpp
    fi

    log "$(msg 'Configuring and building VapourSynth' '配置与编译 VapourSynth')"
    tmux_run "VapourSynth autogen" ./autogen.sh || exit 1
    tmux_run "VapourSynth configure" ./configure CXXFLAGS="-O3 -fpermissive" || die "$(msg 'VapourSynth configure failed' 'VapourSynth 配置失败')"
    tmux_run "VapourSynth make" make -j"$(nproc)" || exit 1
    tmux_run "VapourSynth install" sudo make install || exit 1
    sudo ldconfig || exit 1

    local py_ver
    py_ver=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')

    log "$(msg "Creating vapoursynth.so symlink (for Python ${py_ver})" "创建 vapoursynth.so 软链接 (针对 Python ${py_ver})")"
    sudo mkdir -p /usr/lib/python3/dist-packages
    sudo ln -sf "/usr/local/lib/python${py_ver}/site-packages/vapoursynth.so" "/usr/lib/python3/dist-packages/vapoursynth.so" || exit 1
  ) || die "$(msg 'VapourSynth build/install failed' 'VapourSynth 编译/安装失败')"

  rm -rf "$build_dir"
  log "$(msg 'VapourSynth installation complete' 'VapourSynth 安装完成')"
}

# ---------------------------------------------------------------------------
# descale
# ---------------------------------------------------------------------------

install_descale() {
  log "$(msg 'Installing VapourSynth descale plugin' '安装 VapourSynth descale 插件')"

  local plugins_dir="$PLUGIN_PATH"
  ensure_configured_directory "$plugins_dir"
  if [[ -f "$plugins_dir/libdescale.so" ]]; then
    log "$(msg "descale plugin already exists in ${plugins_dir}, skipping" "检测到 ${plugins_dir} 已存在 descale 插件，跳过")"
    return 0
  fi

  local deps=(git meson ninja-build pkg-config build-essential)
  local missing_deps=()
  local dep
  for dep in "${deps[@]}"; do
    if ! dpkg-query -W -f='${Status}' "$dep" 2>/dev/null | grep -q "install ok installed"; then
      missing_deps+=("$dep")
    fi
  done
  if (( ${#missing_deps[@]} > 0 )); then
    apt_update
    apt_install "${missing_deps[@]}" || die "$(msg 'Failed to install descale dependencies' 'descale 依赖安装失败')"
  fi

  local build_dir
  build_dir="$(mktemp -d)"
  (
    cd "$build_dir" || exit 1
    tmux_run "$(msg 'Download vapoursynth-descale' '下载 vapoursynth-descale')" git clone https://github.com/Irrational-Encoding-Wizardry/vapoursynth-descale.git || exit 1
    cd vapoursynth-descale || exit 1
    tmux_run "descale meson setup" meson setup build --buildtype=release || exit 1
    tmux_run "descale ninja" ninja -C build || exit 1
    tmux_run "descale install" sudo ninja -C build install || exit 1
    sudo ldconfig || exit 1
  ) || die "$(msg 'descale build/install failed' 'descale 编译/安装失败')"

  local descale_src=""
  if [[ -f "/usr/local/lib/vapoursynth/libdescale.so" ]]; then
    descale_src="/usr/local/lib/vapoursynth/libdescale.so"
  elif [[ -f "/usr/lib/vapoursynth/libdescale.so" ]]; then
    descale_src="/usr/lib/vapoursynth/libdescale.so"
  fi
  [[ -n "$descale_src" ]] || die "$(msg 'descale installed but libdescale.so not found in system vapoursynth paths' 'descale 安装完成但未在系统 vapoursynth 路径找到 libdescale.so')"
  cp "$descale_src" "$plugins_dir/libdescale.so" || die "$(msg "Failed to copy libdescale.so to ${plugins_dir}" "复制 libdescale.so 到 ${plugins_dir} 失败")"

  rm -rf "$build_dir"
  log "$(msg "descale plugin installation complete (copied to ${plugins_dir})" "descale 插件安装完成（已复制到 ${plugins_dir}）")"
}

# ---------------------------------------------------------------------------
# 7-Zip CLI (VapourSynth portable .7z)
# ---------------------------------------------------------------------------

# Ubuntu/Debian p7zip-full is often 7-Zip 16.x and fails on newer methods (e.g. Delta + LZMA2 in recent archives).
ensure_modern_7zip_cli() {
  BLURAY_7ZZ_BIN=""

  if command -v 7zz >/dev/null 2>&1; then
    BLURAY_7ZZ_BIN="$(command -v 7zz)"
    return 0
  fi

  local p7_ver=""
  if command -v 7z >/dev/null 2>&1; then
    p7_ver="$(7z 2>&1 | head -n 1 | grep -oE '([0-9]+\.[0-9]+)' | head -n 1 || true)"
  fi
  if [[ -n "${p7_ver:-}" ]] && dpkg --compare-versions "$p7_ver" ge "22.00" 2>/dev/null; then
    BLURAY_7ZZ_BIN="$(command -v 7z)"
    return 0
  fi

  if ! command -v git >/dev/null 2>&1; then
    apt_update
    apt_install git || die "$(msg 'Failed to install git (needed to resolve the latest 7-Zip release)' '安装 git 失败（获取最新 7-Zip 版本需要）')"
  fi

  local seven_release_tag seven_version seven_tag
  seven_release_tag="${SEVENZIP_VERSION:-$(latest_stable_tag https://github.com/ip7z/7zip.git '^[0-9]+[.][0-9]+$')}"
  seven_version="${seven_release_tag#v}"
  seven_tag="${seven_version//./}"
  local arch_7=""
  case "$(uname -m)" in
    x86_64 | amd64) arch_7="x64" ;;
    aarch64 | arm64) arch_7="arm64" ;;
    armv7l | armv6l) arch_7="arm" ;;
    i686 | i386 | x86) arch_7="x86" ;;
    *)
      die "$(msg 'Unsupported CPU for 7-Zip bootstrap (install 7zz or p7zip >= 22)' '当前 CPU 无法自动下载 7-Zip CLI，请手动安装 7zz 或 p7zip >= 22')"
      ;;
  esac

  if ! dpkg-query -W -f='${Status}' xz-utils 2>/dev/null | grep -q "install ok installed"; then
    apt_update
    apt_install xz-utils || die "$(msg 'Failed to install xz-utils (needed to unpack 7-Zip CLI tarball)' '安装 xz-utils 失败（解压 7-Zip 官方包需要）')"
  fi

  local cache_root="${HOME}/.cache/BluraySubtitle"
  local dest="${cache_root}/7zip-${seven_tag}-linux-${arch_7}"
  mkdir -p "$dest"

  local zzpath=""
  zzpath="$(find "$dest" -maxdepth 2 -type f -name 7zz -print -quit 2>/dev/null || true)"
  if [[ -n "${zzpath:-}" && -f "$zzpath" ]]; then
    chmod +x "$zzpath" || true
    if [[ -x "$zzpath" ]]; then
      BLURAY_7ZZ_BIN="$zzpath"
      return 0
    fi
  fi

  local url="https://github.com/ip7z/7zip/releases/download/${seven_release_tag}/7z${seven_tag}-linux-${arch_7}.tar.xz"
  local tball="${dest}/7z${seven_tag}-linux-${arch_7}.tar.xz"

  log "$(msg "Installing official 7-Zip CLI (${seven_version}) under ~/.cache/BluraySubtitle (system p7zip is too old for some .7z files)" "正在安装官方 7-Zip 命令行（${seven_version}）到 ~/.cache/BluraySubtitle（系统 p7zip 过旧，无法解压部分 .7z）")"

  if command -v wget >/dev/null 2>&1; then
    wget -q -O "$tball" "$url" || die "$(msg 'Failed to download official 7-Zip CLI tarball' '下载官方 7-Zip 命令行包失败')"
  elif command -v curl >/dev/null 2>&1; then
    curl -fsSL -o "$tball" "$url" || die "$(msg 'Failed to download official 7-Zip CLI tarball (curl)' '下载官方 7-Zip 命令行包失败（curl）')"
  else
    apt_update
    apt_install wget curl || die "$(msg 'Failed to install wget/curl' '安装 wget/curl 失败')"
    wget -q -O "$tball" "$url" || die "$(msg 'Failed to download official 7-Zip CLI tarball' '下载官方 7-Zip 命令行包失败')"
  fi

  tmux_run "$(msg 'Extract official 7-Zip CLI tarball' '解压官方 7-Zip 命令行包')" tar -xJf "$tball" -C "$dest" || die "$(msg 'Failed to extract official 7-Zip CLI tarball' '解压官方 7-Zip 命令行包失败')"

  zzpath="$(find "$dest" -maxdepth 3 -type f -name 7zz -print -quit 2>/dev/null || true)"
  [[ -n "${zzpath:-}" && -f "$zzpath" ]] || die "$(msg '7zz not found after extracting official 7-Zip tarball' '解压官方 7-Zip 包后未找到 7zz')"
  chmod +x "$zzpath" || die "$(msg 'chmod 7zz failed' 'chmod 7zz 失败')"
  [[ -x "$zzpath" ]] || die "$(msg '7zz is not executable' '7zz 不可执行')"

  BLURAY_7ZZ_BIN="$zzpath"
}

# ---------------------------------------------------------------------------
# VapourSynthScripts
# ---------------------------------------------------------------------------

# Subset of the VCB-S portable bundle's VapourSynthScripts/ used here (same filenames as reference bundle).
install_vapoursynth_scripts() {
  local py_ver
  py_ver="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
  local dst_dir="/usr/local/lib/python${py_ver}/dist-packages"

  # Reference layout (e.g. .../VapourSynthScripts/*.py); keep in sync when updating the portable package.
  local -a vs_script_names=(
    MCDenoise.py
    adjust.py
    dfttest2.py
    havsfunc.py
    mirvsfunc.py
    muvsfunc.py
    muvsfunc_numpy.py
    mvsfunc.py
    nnedi3_resample.py
    vsTAAmbk.py
    vsmlrt.py
  )

  local name all_present=1
  for name in "${vs_script_names[@]}"; do
    if [[ ! -f "${dst_dir}/${name}" ]]; then
      all_present=0
      break
    fi
  done
  if (( all_present )); then
    log "$(msg "VapourSynthScripts (${#vs_script_names[@]} .py files) already installed at ${dst_dir}, skipping portable 7z" "VapourSynthScripts（${#vs_script_names[@]} 个 .py）已在 ${dst_dir}，跳过便携包下载/解压")"
    return 0
  fi

  log "$(msg 'Downloading VCB-S VapourSynth portable package and extracting VapourSynthScripts' '下载 VCB-S VapourSynth 可移植包并提取 VapourSynthScripts')"

  local vcbs_url="https://github.com/AmusementClub/tools/releases/download/2025H1p/vapoursynth_portable_25H1.1p_cpu.7z"

  ensure_modern_7zip_cli
  [[ -n "${BLURAY_7ZZ_BIN:-}" ]] || die "$(msg '7-Zip CLI path not set' '未设置 7-Zip 可执行路径')"

  if ! command -v wget >/dev/null 2>&1; then
    apt_update
    apt_install wget || die "$(msg 'Failed to install wget' '安装 wget 失败')"
  fi

  sudo mkdir -p "$dst_dir"

  local tmp_dir
  tmp_dir="$(mktemp -d)"
  trap 'rm -rf "$tmp_dir"' RETURN

  tmux_run "$(msg 'Download vapoursynth_portable_25H1.1p_cpu.7z' '下载 vapoursynth_portable_25H1.1p_cpu.7z')" wget -q -O "$tmp_dir/vapoursynth_portable.7z" "$vcbs_url" || die "$(msg 'Failed to download 7z package' '下载 7z 包失败')"
  tmux_run "$(msg 'Extract vapoursynth_portable.7z' '解压 vapoursynth_portable.7z')" "$BLURAY_7ZZ_BIN" x "$tmp_dir/vapoursynth_portable.7z" "-o$tmp_dir/extracted" || die "$(msg 'Failed to extract 7z package' '解压 7z 包失败')"

  local scripts_dir
  scripts_dir="$(find "$tmp_dir/extracted" -maxdepth 2 -type d -name VapourSynthScripts | head -n1)"
  if [[ -z "${scripts_dir:-}" ]]; then
    die "$(msg 'VapourSynthScripts subdirectory not found in extracted archive' '未在解压目录中找到 VapourSynthScripts 子目录')"
  fi

  local copied=0
  for name in "${vs_script_names[@]}"; do
    if [[ ! -f "${scripts_dir}/${name}" ]]; then
      die "$(msg "Expected script missing in archive: ${name}" "压缩包中缺少预期脚本：${name}")"
    fi
    sudo cp -f "${scripts_dir}/${name}" "$dst_dir/" || die "$(msg "Failed to copy script: ${name}" "复制脚本失败：${name}")"
    copied=$((copied + 1))
  done

  log "$(msg "Copied ${copied} script(s) from VapourSynthScripts to ${dst_dir}" "已从 VapourSynthScripts 复制脚本到 ${dst_dir}（数量：${copied}）")"
}

# ---------------------------------------------------------------------------
# VapourSynth Editor (vsedit)
# ---------------------------------------------------------------------------

# R19-mod-6.10 is the latest editor tested against the classic VapourSynth stack.
install_vapoursynth_editor() {
  log "$(msg 'Installing VapourSynth Editor (vsedit, build from source)' '安装 vapoursynth-editor (vsedit)（从源码编译并安装）')"

  if [[ -x "$VSEDIT_PATH" && -x "$VSEDIT_BINARY_PATH" ]]; then
    log "$(msg 'vsedit already installed (vsedit-bin found), skipping' '检测到 vsedit 已安装（存在 vsedit-bin），跳过编译安装')"
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
    apt_install "${missing_deps[@]}" || die "$(msg 'Failed to install vsedit dependencies' 'vsedit 依赖安装失败')"
  fi

  local build_dir
  build_dir="$(mktemp -d)"

  (
    cd "$build_dir" || exit 1
    mkdir -p vsedit_build
    cd vsedit_build || exit 1

    tmux_run "$(msg 'Download vsedit R19-mod-6.10' '下载 vsedit R19-mod-6.10')" wget -O R19-mod-6.10.tar.gz https://github.com/YomikoR/VapourSynth-Editor/archive/refs/tags/R19-mod-6.10.tar.gz || exit 1

    log "$(msg 'Extracting vsedit source tarball' '解压 vsedit 源码包')"
    tmux_run "$(msg 'Extract vsedit source' '解压 vsedit 源码包')" tar -zxvf R19-mod-6.10.tar.gz --strip-components=1 || exit 1
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

    log "$(msg 'Configuring and building vsedit (qmake6)' '配置并编译 vsedit (qmake6)')"
    qmake6 pro.pro CONFIG+=release 2>&1 | sed '/^Info: creating stash file /d' || exit 1
    tmux_run "vsedit make" bash -lc "make -j\"$(nproc)\" || make -j1" || exit 1

    log "$(msg 'Locating compiled vsedit binary and creating symlink' '查找编译生成的 vsedit 并建立软链接')"
    local bin_path
    bin_path=$(find "$build_dir/vsedit_build" -name "vsedit" -type f -executable | head -n 1)

    if [[ -z "$bin_path" ]]; then
      die "$(msg 'Compiled vsedit executable not found' '未找到编译生成的 vsedit 执行文件')"
    fi

    # Copy the real binary as vsedit-bin
    install_configured_executable "$bin_path" "$VSEDIT_BINARY_PATH" || exit 1

    local py_ver
    py_ver=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')

    # Create a vsedit wrapper script that injects the required environment variables
    # (fixes "Failed to get VSScript API" at startup)
    log "$(msg 'Creating vsedit wrapper launch script' '创建 vsedit 包装器启动脚本')"
    bluray_sudo mkdir -p "$(dirname -- "$VSEDIT_PATH")" || exit 1
    bluray_sudo tee "$VSEDIT_PATH" > /dev/null <<EOF
#!/bin/bash
export VAPOURSYNTH_PYTHON_PATH=/usr/lib/python${py_ver}
export LD_LIBRARY_PATH=/usr/local/lib:\$LD_LIBRARY_PATH
export LD_PRELOAD=/usr/local/lib/libvapoursynth-script.so
exec "${VSEDIT_BINARY_PATH}" "\$@"
EOF
    bluray_sudo chmod +x "$VSEDIT_PATH"

    log "$(msg 'vsedit wrapper created. You can now run vsedit directly.' 'vsedit 包装器创建成功。你现在可以直接运行 vsedit 了。')"
  ) || die "$(msg 'vsedit build/install failed' 'vsedit 编译/安装失败')"

  rm -rf "$build_dir"
  log "$(msg 'VapourSynth Editor (vsedit) installation complete' 'vapoursynth-editor (vsedit) 安装完成')"
}

# ---------------------------------------------------------------------------
# libplacebo
# ---------------------------------------------------------------------------

install_libplacebo_latest() {
    local required_version="6.338.0"
    if command -v pkg-config >/dev/null 2>&1 && pkg-config --exists libplacebo; then
        local current_version
        current_version="$(pkg-config --modversion libplacebo 2>/dev/null | head -n 1 || true)"
        if [[ -n "${current_version:-}" ]] && dpkg --compare-versions "$current_version" ge "$required_version"; then
            log "$(msg "libplacebo version satisfied (${current_version} >= ${required_version}), skipping build" "libplacebo 版本满足要求（${current_version} >= ${required_version}），跳过编译")"
            return 0
        fi
        log "$(msg "libplacebo version too low (${current_version:-unknown} < ${required_version}), upgrading" "检测到 libplacebo 版本过低（${current_version:-unknown} < ${required_version}），将升级")"
    elif sudo ldconfig -p 2>/dev/null | grep -qE '\blibplacebo\.so\b'; then
        log "$(msg 'libplacebo found but version cannot be determined (no pkg-config info), reinstalling to ensure vs-placebo compatibility' '检测到 libplacebo 已存在但无法获取版本（缺少 pkg-config 版本信息），将重装以确保兼容 vs-placebo')"
    fi

    log "$(msg 'Building libplacebo in isolated mode...' '正在以物理隔离模式编译 libplacebo...')"

    # Ensure environment variables are safe inside the function
    local py_ver
    py_ver=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    local safe_pythonpath="${HOME}/.local/lib/python${py_ver}/site-packages:${PYTHONPATH:-}"
    local shaderc_opt="-Dshaderc=enabled"
    if [[ -f /etc/os-release ]]; then
      . /etc/os-release || true
      if [[ "${ID:-}" == "debian" ]] && dpkg --compare-versions "${VERSION_ID:-0}" ge "12" && dpkg --compare-versions "${VERSION_ID:-0}" lt "13"; then
        shaderc_opt="-Dshaderc=disabled"
        log "$(msg 'Debian 12 detected, enabling libplacebo compatibility flag: disabling shaderc' '检测到 Debian 12，启用 libplacebo 兼容参数：禁用 shaderc')"
      fi
    fi

    local build_dir
    build_dir="$(mktemp -d)"
    (
        cd "$build_dir" || exit 1
        tmux_run "$(msg 'Download libplacebo v6.338.0' '下载 libplacebo v6.338.0')" git clone --recursive --depth 1 --branch v6.338.0 https://code.videolan.org/videolan/libplacebo.git .

        rm -rf build

        # Run configuration with safely scoped variables
        tmux_run "libplacebo meson setup" env PYTHONPATH="$safe_pythonpath" python3 -m mesonbuild.mesonmain setup build \
            --buildtype release \
            --prefix /usr/local \
            "$shaderc_opt" \
            -Dvulkan=enabled \
            -Dtests=false \
            -Dbench=false \
            -Ddemos=false || exit 1

        # Build and install
        tmux_run "libplacebo ninja" env PYTHONPATH="$safe_pythonpath" ninja -C build || exit 1
        tmux_run "libplacebo install" sudo env PYTHONPATH="$safe_pythonpath" ninja -C build install || exit 1
    ) || die "$(msg 'libplacebo build/install failed' 'libplacebo 编译/安装失败')"
    rm -rf "$build_dir"
    sudo ldconfig

    if ! command -v pkg-config >/dev/null 2>&1 || ! pkg-config --exists libplacebo; then
      die "$(msg 'libplacebo installed but not recognized by pkg-config' 'libplacebo 安装后未被 pkg-config 识别')"
    fi
}

# ---------------------------------------------------------------------------
# VapourSynth plugins
# ---------------------------------------------------------------------------

build_vs_plugins() {
  log "$(msg "Building/installing VapourSynth plugins to ${PLUGIN_PATH}" "编译/安装 VapourSynth 插件到 ${PLUGIN_PATH}")"

  local plugins_dir="$PLUGIN_PATH"
  ensure_configured_directory "$plugins_dir"

  ensure_meson_version
  export PATH="$HOME/.local/bin:$PATH"

  local deps=(
    build-essential git wget tar unzip sed
    meson ninja-build cmake libass-dev
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
    apt_install "${missing_deps[@]}" || die "$(msg 'Failed to install VS plugin dependencies' 'VS 插件依赖安装失败')"
  fi

  local build_dir
  build_dir="$(mktemp -d)"

  (
    cd "$build_dir" || exit 1

    local lsmash_plugin="$plugins_dir/libvslsmashsource.so"
    local lsmash_linker_report=""
    if [[ -f "$lsmash_plugin" ]] && command -v ldd >/dev/null 2>&1; then
      lsmash_linker_report="$(LC_ALL=C ldd -r "$lsmash_plugin" 2>&1 || true)"
    fi
    if [[ "$lsmash_linker_report" == *"undefined symbol:"* || "$lsmash_linker_report" == *"not found"* ]]; then
      log "$(msg 'Existing L-SMASH-Works plugin has unresolved symbols; rebuilding it' '现有 L-SMASH-Works 插件包含未解析符号，将重新编译')"
      rm -f "$lsmash_plugin" || exit 1
    fi

    if [[ ! -f "$lsmash_plugin" ]]; then
      log "$(msg 'Building L-SMASH-Works (VapourSynth)' '编译 L-SMASH-Works (VapourSynth)')"
      cd "$build_dir" || exit 1
      tmux_run "$(msg 'Download L-SMASH-Works' '下载 L-SMASH-Works')" git clone https://github.com/HomeOfAviSynthPlusEvolution/L-SMASH-Works.git || exit 1
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
        log "$(msg 'Old FFmpeg API detected (or compatibility mode required), rolling back L-SMASH-Works to compatible commit' '检测到旧版 FFmpeg API（或系统需兼容模式），回退 L-SMASH-Works 到兼容提交')"
        tmux_run "L-SMASH-Works git checkout" bash -lc "git checkout . && git -c advice.detachedHead=false checkout -q 70e19fb" || log "$(msg 'Warning: git rollback failed, trying to continue with current version' '警告：Git 回退失败，尝试继续使用当前版本')"
      else
        log "$(msg 'Pinning L-SMASH-Works to last VapourSynth API v3 compatible commit' '固定 L-SMASH-Works 到最后一个兼容 VapourSynth API v3 的提交')"
        tmux_run "L-SMASH-Works git checkout" bash -lc "git checkout . && git -c advice.detachedHead=false checkout -q ae51313" || log "$(msg 'Warning: git checkout ae51313 failed, trying to continue with current version' '警告：切换到 ae51313 失败，尝试继续使用当前版本')"
      fi

      # Apply FFmpeg compatibility patches (index accessors, D3D12 shim, removed codec IDs).
      local decode_file="../common/decode.c"
      if [[ -f "$decode_file" ]]; then
          python3 - "$need_compat" <<'PY' || exit 1
import re
import sys
from pathlib import Path

needs_old_ffmpeg_compat = sys.argv[1] == "true"

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

lwindex_path = Path("../common/lwindex.c")
if needs_old_ffmpeg_compat and lwindex_path.is_file():
    lwindex_data = lwindex_path.read_text(encoding="utf-8", errors="replace")
    compat_block = """/* FFmpeg 4.x exposes index entries directly on AVStream. */
#if LIBAVFORMAT_VERSION_MAJOR < 59
#define avformat_index_get_entries_count(stream) ((stream)->nb_index_entries)
#define avformat_index_get_entry(stream, index) (&(stream)->index_entries[(index)])
#endif

"""
    anchor = '#include "osdep.h"\n'
    if "LIBAVFORMAT_VERSION_MAJOR < 59" not in lwindex_data:
        if anchor not in lwindex_data:
            raise RuntimeError("L-SMASH-Works lwindex.c compatibility anchor not found")
        lwindex_data = lwindex_data.replace(anchor, compat_block + anchor, 1)
    lwindex_path.write_text(lwindex_data, encoding="utf-8")
PY
      fi
      rm -rf build
      tmux_run "L-SMASH-Works meson setup" meson setup build || exit 1
      tmux_run "L-SMASH-Works ninja" ninja -C build || exit 1
      local out
      out="$(find "$PWD" -maxdepth 3 -name "libvslsmashsource.so" -type f | head -n 1)"
      [[ -n "${out:-}" ]] || exit 1
      cp "$out" "$plugins_dir/" || exit 1
      lsmash_linker_report="$(LC_ALL=C ldd -r "$lsmash_plugin" 2>&1 || true)"
      if [[ "$lsmash_linker_report" == *"undefined symbol:"* || "$lsmash_linker_report" == *"not found"* ]]; then
        log "$(msg 'Rebuilt L-SMASH-Works plugin still has unresolved dependencies' '重编后的 L-SMASH-Works 插件仍包含未解析依赖')"
        exit 1
      fi
      cd "$build_dir" || exit 1
    else
      log "$(msg 'libvslsmashsource.so already exists, skipping' '已存在 libvslsmashsource.so，跳过')"
    fi

    # Keep r9: r10 declares VapourSynth >= R74, but this project uses R57.A12.
    if [[ ! -f "$plugins_dir/eedi3m.so" ]]; then
      log "$(msg 'Building VapourSynth-EEDI3 (r9)' '编译 VapourSynth-EEDI3 (r9)')"
      cd "$HOME" || exit 1
      tmux_run "$(msg 'Download EEDI3 r9' '下载 EEDI3 r9')" wget -O r9.tar.gz https://github.com/HomeOfVapourSynthEvolution/VapourSynth-EEDI3/archive/refs/tags/r9.tar.gz || exit 1
      tmux_run "$(msg 'Extract EEDI3 r9' '解压 EEDI3 r9')" tar zxvf r9.tar.gz || exit 1
      cd VapourSynth-EEDI3-r9/ || exit 1
      log "$(msg 'Fixing EEDI3 std::max_align_t compilation compatibility issue' '修复 EEDI3 的 std::max_align_t 编译兼容性问题')"
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
      log "$(msg 'eedi3m.so already exists, skipping' '已存在 eedi3m.so，跳过')"
    fi

    if [[ ! -f "$plugins_dir/libaddgrain.so" ]]; then
      log "$(msg 'Building VapourSynth-AddGrain (r10)' '编译 VapourSynth-AddGrain (r10)')"
      cd "$HOME" || exit 1
      tmux_run "$(msg 'Download AddGrain r10' '下载 AddGrain r10')" wget -O r10.tar.gz https://github.com/HomeOfVapourSynthEvolution/VapourSynth-AddGrain/archive/refs/tags/r10.tar.gz || exit 1
      tmux_run "$(msg 'Extract AddGrain r10' '解压 AddGrain r10')" tar zxvf r10.tar.gz || exit 1
      cd VapourSynth-AddGrain-r10/ || exit 1
      tmux_run "AddGrain meson setup" meson setup build || exit 1
      tmux_run "AddGrain ninja" ninja -C build || exit 1
      cp build/libaddgrain.so "$plugins_dir/" || exit 1
      cd "$build_dir" || exit 1
    else
      log "$(msg 'libaddgrain.so already exists, skipping' '已存在 libaddgrain.so，跳过')"
    fi

    # The upstream Linux binary requires GLIBC_2.38, so build from source on the
    # target system to remain loadable on Ubuntu 22.04 and Debian 12.
    if [[ ! -f "$plugins_dir/libassrender.so" ]]; then
      log "$(msg 'Building assrender (0.38.4)' '编译 assrender (0.38.4)')"
      cd "$HOME" || exit 1
      tmux_run "$(msg 'Clone assrender 0.38.4' '克隆 assrender 0.38.4')" git clone --depth 1 --branch 0.38.4 https://github.com/AmusementClub/assrender.git assrender-0.38.4 || exit 1
      cd assrender-0.38.4 || exit 1
      rm -rf build
      tmux_run "assrender cmake" cmake -S . -B build -DCMAKE_BUILD_TYPE=Release || exit 1
      tmux_run "assrender build" cmake --build build --parallel "$(nproc)" || exit 1
      local out
      out="$(find "$PWD/build" -name "libassrender.so" -type f | head -n 1)"
      [[ -n "${out:-}" ]] || exit 1
      cp "$out" "$plugins_dir/" || exit 1
      cd "$build_dir" || exit 1
    else
      log "$(msg 'libassrender.so already exists, skipping' '已存在 libassrender.so，跳过')"
    fi

    if [[ ! -f "$plugins_dir/libbilateral.so" ]]; then
      log "$(msg 'Building VapourSynth-Bilateral (r3)' '编译 VapourSynth-Bilateral (r3)')"
      cd "$HOME" || exit 1
      tmux_run "$(msg 'Download Bilateral r3' '下载 Bilateral r3')" wget -O r3.tar.gz https://github.com/HomeOfVapourSynthEvolution/VapourSynth-Bilateral/archive/refs/tags/r3.tar.gz || exit 1
      tmux_run "$(msg 'Extract Bilateral r3' '解压 Bilateral r3')" tar zxvf r3.tar.gz || exit 1
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
      log "$(msg 'libbilateral.so already exists, skipping' '已存在 libbilateral.so，跳过')"
    fi

    if [[ ! -f "$plugins_dir/libdfttest.so" ]]; then
      log "$(msg 'Building VapourSynth-DFTTest (r7)' '编译 VapourSynth-DFTTest (r7)')"
      cd "$HOME" || exit 1
      tmux_run "$(msg 'Download DFTTest r7' '下载 DFTTest r7')" wget -O r7.tar.gz https://github.com/HomeOfVapourSynthEvolution/VapourSynth-DFTTest/archive/refs/tags/r7.tar.gz || exit 1
      tmux_run "$(msg 'Extract DFTTest r7' '解压 DFTTest r7')" tar zxvf r7.tar.gz || exit 1
      cd VapourSynth-DFTTest-r7/ || exit 1
      log "$(msg 'Installing DFTTest build dependency: libfftw3-dev...' '正在安装 DFTTest 编译依赖: libfftw3-dev...')"
      apt_install libfftw3-dev
      tmux_run "DFTTest meson setup" meson setup build || exit 1
      tmux_run "DFTTest ninja" ninja -C build || exit 1
      cp build/libdfttest.so "$plugins_dir/" || exit 1
      cd "$build_dir" || exit 1
    else
      log "$(msg 'libdfttest.so already exists, skipping' '已存在 libdfttest.so，跳过')"
    fi

    if [[ ! -f "$plugins_dir/libeedi2.so" ]]; then
      log "$(msg 'Building VapourSynth-EEDI2 (r7.1)' '编译 VapourSynth-EEDI2 (r7.1)')"
      cd "$HOME" || exit 1
      tmux_run "$(msg 'Download EEDI2 r7.1' '下载 EEDI2 r7.1')" wget -O r7.1.tar.gz https://github.com/HomeOfVapourSynthEvolution/VapourSynth-EEDI2/archive/refs/tags/r7.1.tar.gz || exit 1
      tmux_run "$(msg 'Extract EEDI2 r7.1' '解压 EEDI2 r7.1')" tar zxvf r7.1.tar.gz || exit 1
      cd VapourSynth-EEDI2-r7.1/ || exit 1
      tmux_run "EEDI2 meson setup" meson setup build || exit 1
      tmux_run "EEDI2 ninja" ninja -C build || exit 1
      cp build/libeedi2.so "$plugins_dir/" || exit 1
      cd "$build_dir" || exit 1
    else
      log "$(msg 'libeedi2.so already exists, skipping' '已存在 libeedi2.so，跳过')"
    fi

    if [[ ! -f "$plugins_dir/libfmtconv.so" ]]; then
      log "$(msg 'Building fmtconv (r30)' '编译 fmtconv (r30)')"
      cd "$HOME" || exit 1
      tmux_run "$(msg 'Download fmtconv r30' '下载 fmtconv r30')" wget -O r30.tar.gz https://github.com/EleonoreMizo/fmtconv/archive/refs/tags/r30.tar.gz || exit 1
      tmux_run "$(msg 'Extract fmtconv r30' '解压 fmtconv r30')" tar zxvf r30.tar.gz || exit 1
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
      log "$(msg 'libfmtconv.so already exists, skipping' '已存在 libfmtconv.so，跳过')"
    fi

    if [[ ! -f "$plugins_dir/libremovegrain.so" ]]; then
      log "$(msg 'Building vs-removegrain (R1)' '编译 vs-removegrain (R1)')"
      cd "$HOME" || exit 1
      tmux_run "$(msg 'Download vs-removegrain R1' '下载 vs-removegrain R1')" wget https://github.com/vapoursynth/vs-removegrain/archive/refs/tags/R1.tar.gz || exit 1
      tmux_run "$(msg 'Extract vs-removegrain R1' '解压 vs-removegrain R1')" tar zxvf R1.tar.gz || exit 1
      cd vs-removegrain-R1/src || exit 1
      tmux_run "$(msg 'Build vs-removegrain R1' '编译 vs-removegrain R1')" g++ -shared -fPIC -O3 -Wall \
        $(pkg-config --cflags vapoursynth) \
        clense.cpp removegrainvs.cpp repairvs.cpp shared.cpp verticalcleaner.cpp \
        -o libremovegrain.so || exit 1
      cp libremovegrain.so "$plugins_dir/" || exit 1
      cd "$build_dir" || exit 1
    else
      log "$(msg 'libremovegrain.so already exists, skipping' '已存在 libremovegrain.so，跳过')"
    fi

    if [[ ! -f "$plugins_dir/libsangnommod.so" ]]; then
      log "$(msg 'Building VapourSynth-SangNomMod (v0.1-fix)' '编译 VapourSynth-SangNomMod (v0.1-fix)')"
      cd "$HOME" || exit 1
      tmux_run "$(msg 'Download SangNomMod v0.1-fix' '下载 SangNomMod v0.1-fix')" wget -O v0.1-fix.tar.gz https://github.com/HomeOfVapourSynthEvolution/VapourSynth-SangNomMod/archive/refs/tags/v0.1-fix.tar.gz || exit 1
      tmux_run "$(msg 'Extract SangNomMod v0.1-fix' '解压 SangNomMod v0.1-fix')" tar zxvf v0.1-fix.tar.gz || exit 1
      cd VapourSynth-SangNomMod-0.1-fix/ || exit 1
      tmux_run "SangNomMod configure" ./configure || exit 1
      tmux_run "SangNomMod make" make -j"$(nproc)" || exit 1
      local out
      out="$(find "$PWD" -maxdepth 3 -name "libsangnommod.so" -type f | head -n 1)"
      [[ -n "${out:-}" ]] || exit 1
      cp "$out" "$plugins_dir/" || exit 1
      cd "$build_dir" || exit 1
    else
      log "$(msg 'libsangnommod.so already exists, skipping' '已存在 libsangnommod.so，跳过')"
    fi

    # 2.0.4 supports the legacy install layout through -Dr73-compat=true.
    if [[ ! -f "$plugins_dir/libvs_placebo.so" ]]; then
      log "$(msg 'Building vs-placebo (2.0.4)' '编译 vs-placebo (2.0.4)')"
      cd "$HOME" || exit 1
      install_libplacebo_latest
      tmux_run "$(msg 'Download vs-placebo 2.0.4' '下载 vs-placebo 2.0.4')" wget -O 2.0.4.tar.gz https://github.com/Lypheo/vs-placebo/archive/refs/tags/2.0.4.tar.gz || exit 1
      tmux_run "$(msg 'Extract vs-placebo 2.0.4' '解压 vs-placebo 2.0.4')" tar zxvf 2.0.4.tar.gz || exit 1
      cd vs-placebo-2.0.4/ || exit 1
      export PKG_CONFIG_PATH="/usr/local/lib/pkgconfig:/usr/local/lib/x86_64-linux-gnu/pkgconfig:/usr/local/share/pkgconfig:$HOME/.local/lib/x86_64-linux-gnu/pkgconfig:${PKG_CONFIG_PATH:-}"
      export C_INCLUDE_PATH="$HOME/.local/include:${C_INCLUDE_PATH:-}"
      export LIBRARY_PATH="$HOME/.local/lib/x86_64-linux-gnu:${LIBRARY_PATH:-}"
      export LD_LIBRARY_PATH="$HOME/.local/lib/x86_64-linux-gnu:${LD_LIBRARY_PATH:-}"
      rm -rf build
      tmux_run "vs-placebo meson setup" meson setup build -Dr73-compat=true || exit 1
      tmux_run "vs-placebo ninja" ninja -C build || exit 1
      local out
      out="$(find "$PWD/build" -maxdepth 2 -name "libvs_placebo.so" -type f | head -n 1)"
      [[ -n "${out:-}" ]] || exit 1
      cp "$out" "$plugins_dir/" || exit 1
      cd "$build_dir" || exit 1
    else
      log "$(msg 'libvs_placebo.so already exists, skipping' '已存在 libvs_placebo.so，跳过')"
    fi

    # Upgrade ISPC when an older binary is present; command existence alone is insufficient.
    local required_ispc_version="1.31.0"
    local current_ispc_version=""
    if command -v ispc >/dev/null 2>&1; then
      current_ispc_version="$(ispc --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -n 1 || true)"
    fi
    if [[ -z "$current_ispc_version" ]] || dpkg --compare-versions "$current_ispc_version" lt "$required_ispc_version"; then
      log "$(msg 'Installing ispc (v1.31.0)' '安装 ispc (v1.31.0)')"
      tmux_run "$(msg 'Download ispc v1.31.0' '下载 ispc v1.31.0')" wget -O ispc-v1.31.0-linux.tar.gz https://github.com/ispc/ispc/releases/download/v1.31.0/ispc-v1.31.0-linux.tar.gz || exit 1
      tmux_run "$(msg 'Extract ispc v1.31.0' '解压 ispc v1.31.0')" tar -xvf ispc-v1.31.0-linux.tar.gz || exit 1
      sudo mv ispc-v1.31.0-linux/bin/ispc /usr/local/bin/ || exit 1
      sudo chmod +x /usr/local/bin/ispc || exit 1
    else
      log "$(msg "ispc version satisfied (${current_ispc_version} >= ${required_ispc_version}), skipping" "ispc 版本满足要求（${current_ispc_version} >= ${required_ispc_version}），跳过安装")"
    fi

    if [[ ! -f "$plugins_dir/libvsnlm_ispc.so" ]]; then
      log "$(msg 'Building vs-nlm-ispc (v4)' '编译 vs-nlm-ispc (v4)')"
      cd "$HOME" || exit 1
      tmux_run "$(msg 'Download vs-nlm-ispc v4' '下载 vs-nlm-ispc v4')" wget -O v4.tar.gz https://github.com/AmusementClub/vs-nlm-ispc/archive/refs/tags/v4.tar.gz || exit 1
      tmux_run "$(msg 'Extract vs-nlm-ispc v4' '解压 vs-nlm-ispc v4')" tar zxvf v4.tar.gz || exit 1
      cd vs-nlm-ispc-4/ || exit 1
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
      log "$(msg 'libvsnlm_ispc.so already exists, skipping' '已存在 libvsnlm_ispc.so，跳过')"
    fi

    # Keep zsmooth 0.7 because newer binaries are incompatible with R57.A12.
    if [[ ! -f "$plugins_dir/libzsmooth.x86_64-gnu.so" ]]; then
      log "$(msg 'Installing zsmooth (binary package)' '安装 zsmooth（二进制包）')"
      cd "$HOME" || exit 1
      tmux_run "$(msg 'Download zsmooth 0.7' '下载 zsmooth 0.7')" wget -O libzsmooth.x86_64-gnu.so.zip https://github.com/adworacz/zsmooth/releases/download/0.7/libzsmooth.x86_64-gnu.so.zip || exit 1
      tmux_run "$(msg 'Extract zsmooth 0.7' '解压 zsmooth 0.7')" unzip -o libzsmooth.x86_64-gnu.so.zip || exit 1
      mv libzsmooth.x86_64-gnu.so "$plugins_dir/" || exit 1
      cd "$build_dir" || exit 1
    else
      log "$(msg 'libzsmooth.x86_64-gnu.so already exists, skipping' '已存在 libzsmooth.x86_64-gnu.so，跳过')"
    fi

    # Keep mvtools v26: v29_2 declares VapourSynth >= R74.
    if [[ ! -f "$plugins_dir/mvtools.so" ]]; then
      log "$(msg 'Building vapoursynth-mvtools (v26)' '编译 vapoursynth-mvtools (v26)')"
      cd "$HOME" || exit 1
      tmux_run "$(msg 'Download mvtools v26' '下载 mvtools v26')" wget -O v26.tar.gz https://github.com/dubhatervapoursynth/vapoursynth-mvtools/archive/refs/tags/v26.tar.gz || exit 1
      tmux_run "$(msg 'Extract mvtools v26' '解压 mvtools v26')" tar zxvf v26.tar.gz || exit 1
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
      log "$(msg 'mvtools.so already exists, skipping' '已存在 mvtools.so，跳过')"
    fi

    log "$(msg 'Cleaning up downloaded archives and source directories' '清理下载压缩包与源码目录')"
    cd "$HOME" || exit 1
    rm -f \
      r9.tar.gz r10.tar.gz r3.tar.gz r7.tar.gz r7.1.tar.gz \
      r30.tar.gz R1.tar.gz v0.1-fix.tar.gz 2.0.4.tar.gz v4.tar.gz libzsmooth.x86_64-gnu.so.zip v26.tar.gz \
      ispc-v1.31.0-linux.tar.gz libassrender.so \
      || true
    rm -rf \
      assrender-0.38.4 VapourSynth-EEDI3-r9 VapourSynth-AddGrain-r10 VapourSynth-Bilateral-r3 \
      VapourSynth-DFTTest-r7 VapourSynth-EEDI2-r7.1 fmtconv-r30 vs-removegrain-R1 VapourSynth-SangNomMod-0.1-fix \
      vs-placebo-2.0.4 vs-nlm-ispc-4 vapoursynth-mvtools-26 ispc-v1.31.0-linux \
      || true

    log "$(msg "VS plugins build complete, output directory: $plugins_dir" "VS 插件编译完成，输出目录：$plugins_dir")"
  ) || die "$(msg 'VS plugin build failed' 'VS 插件编译失败')"

  rm -rf "$build_dir"
}

# ---------------------------------------------------------------------------
# Desktop shortcuts
# ---------------------------------------------------------------------------

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
        cp -f "$src" "$desktop_dir/$(basename "$src")" || die "$(msg "Failed to copy desktop file: $src" "复制 desktop 文件失败：$src")"
        chmod +x "$desktop_dir/$(basename "$src")" || true
      done < <(find "$app_dir" -maxdepth 1 -type f -name "*.desktop" \( -iname "*mpv*" -o -iname "*mkvtoolnix*" \) -print0)
    fi
  done
  if [[ "$found_any" != "true" ]]; then
    log "$(msg 'No mpv/mkvtoolnix desktop files found in /usr/local/share/applications or /usr/share/applications' '未在 /usr/local/share/applications 或 /usr/share/applications 中找到 mpv/mkvtoolnix 的 desktop 文件')"
  fi

  if [[ -x "$VSEDIT_PATH" ]]; then
    local vsedit_desktop="$desktop_dir/vsedit.desktop"
    cat > "$vsedit_desktop" <<EOF
[Desktop Entry]
Type=Application
Name=vsedit
Comment=VapourSynth Editor
Exec=${VSEDIT_PATH} %F
Terminal=false
Categories=AudioVideo;Video;
Icon=vsedit
StartupNotify=true
EOF
    chmod +x "$vsedit_desktop" || true
  fi

  log "$(msg "Desktop shortcuts ready: $desktop_dir" "桌面图标已准备完成：$desktop_dir")"
}

# ---------------------------------------------------------------------------
# Shaderc (Ubuntu 22.04 fix)
# ---------------------------------------------------------------------------

install_shaderc_fix() {
  # Only applies to Ubuntu 22.04
  if [[ -f /etc/os-release ]]; then
    . /etc/os-release
    if [[ "$ID" == "ubuntu" && "$VERSION_ID" == "22.04" ]]; then
      if sudo ldconfig -p 2>/dev/null | grep -qE '\blibshaderc(_shared)?\.so\b'; then
        log "$(msg 'Shaderc already installed (libshaderc found in ldconfig), skipping source build' '检测到 Shaderc 已安装（ldconfig 已包含 libshaderc），跳过源码编译')"
        return 0
      fi
      if command -v pkg-config >/dev/null 2>&1 && pkg-config --exists shaderc; then
        log "$(msg 'Shaderc already installed (pkg-config found shaderc), skipping source build' '检测到 Shaderc 已安装（pkg-config 可找到 shaderc），跳过源码编译')"
        return 0
      fi

      log "$(msg 'Official package version conflict detected, building Shaderc from source (this may take a few minutes)...' '检测到官方包版本冲突，正在从源码编译 Shaderc (这可能需要几分钟)...')"

      local build_dir
      build_dir="$(mktemp -d)"
      (
          cd "$build_dir" || exit 1

          # 1. Clone source
          tmux_run "$(msg 'Download shaderc' '下载 shaderc')" git clone https://github.com/google/shaderc . || exit 1

          # 2. Sync dependencies (glslang, spirv-tools, spirv-headers)
          #    This step is critical: it automatically fetches all missing low-level components.
          tmux_run "$(msg 'Sync shaderc dependencies' 'shaderc 同步依赖')" ./utils/git-sync-deps || exit 1

          # 3. Configure and build
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
      log "$(msg 'Shaderc built and installed from source.' 'Shaderc 源码编译并安装完成。')"
    fi
  fi
}

# ---------------------------------------------------------------------------
# BluraySubtitle Python deps (must match "python3" used to run src.main)
# ---------------------------------------------------------------------------

__bluray_python_imports_ok() {
  python3 -c "import numpy; import pycountry; import PyQt6.QtCore; import soundfile; from PIL import Image; import matplotlib" >/dev/null 2>&1
}

# --break-system-packages exists from pip ~23; Ubuntu 22.04's python3-pip is often older.
__pip_supports_break_system_packages() {
  python3 -m pip install --help 2>/dev/null | grep -qE '(^|[[:space:]])--break-system-packages([[:space:]]|$)'
}

install_bluray_python_deps() {
  log "$(msg 'Installing or upgrading Python dependencies (python3 -m pip: numpy pycountry PyQt6 soundfile pillow matplotlib)' '安装或升级 Python 依赖（python3 -m pip：numpy pycountry PyQt6 soundfile pillow matplotlib）')"

  if ! python3 -m pip --version >/dev/null 2>&1; then
    apt_update
    apt_install python3-pip || die "$(msg 'Failed to install python3-pip' '安装 python3-pip 失败')"
  fi

  local pip_extra=()
  local pip_mode_msg_en pip_mode_msg_zh
  if __pip_supports_break_system_packages; then
    pip_extra=(--break-system-packages)
    pip_mode_msg_en='Install or upgrade Python dependencies (python3 -m pip --break-system-packages)'
    pip_mode_msg_zh='安装或升级 Python 依赖（python3 -m pip --break-system-packages）'
  else
    pip_extra=(--user)
    pip_mode_msg_en='Install or upgrade Python dependencies (python3 -m pip --user; current pip does not support --break-system-packages)'
    pip_mode_msg_zh='安装或升级 Python 依赖（python3 -m pip --user；当前 pip 不支持 --break-system-packages）'
  fi

  tmux_run "$(msg "$pip_mode_msg_en" "$pip_mode_msg_zh")" \
    env PIP_DISABLE_PIP_VERSION_CHECK=1 python3 -m pip install --upgrade "${pip_extra[@]}" numpy pycountry PyQt6 soundfile pillow matplotlib \
    || tmux_run "$(msg 'Install or upgrade Python dependencies (retry)' '安装或升级 Python 依赖（重试）')" \
      env PIP_DISABLE_PIP_VERSION_CHECK=1 python3 -m pip install --upgrade "${pip_extra[@]}" numpy pycountry PyQt6 soundfile pillow matplotlib \
    || die "$(msg 'Failed to install Python dependencies with python3 -m pip' '使用 python3 -m pip 安装依赖失败')"

  __bluray_python_imports_ok || die "$(msg 'Python deps installed but import check failed. Note: Pillow is imported as PIL (e.g. from PIL import Image), not import pillow' '依赖已安装但仍无法通过导入检查。说明：Pillow 的安装包名为 pillow，代码中应使用 from PIL import Image，不要写 import pillow')"
}

# ---------------------------------------------------------------------------
# Main execution
# ---------------------------------------------------------------------------

command -v sudo >/dev/null 2>&1 || die "$(msg 'sudo is missing' '缺少 sudo')"
sudo -v

require_supported_os
repair_broken_apt_state

sys_deps=(
  python3 python3-pip python3-venv cmake ninja-build git
  wget fonts-wqy-microhei flac gedit
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
  log "$(msg "Installing system dependencies (missing: ${missing_deps[*]})" "安装系统依赖（缺少：${missing_deps[*]}）")"
  apt_update
  apt_install "${missing_deps[@]}"

  log "$(msg 'Refreshing font cache' '刷新字体缓存')"
  sudo fc-cache -f >/dev/null 2>&1 || true
else
  log "$(msg 'All system dependencies already installed, skipping' '系统依赖已全部安装，跳过')"
fi

load_configured_tool_paths
log "$(msg "Using tool paths from ${SETTINGS_FILE}" "使用 ${SETTINGS_FILE} 中配置的工具路径")"

install_shaderc_fix
install_mkvtoolnix
sync_mkvtoolnix_paths
install_mpv
install_x264
install_x265
install_svt_av1
install_tsmuxer
install_dovi_tool
install_hdr10plus_tool
install_truehdd
install_fdk_aac
install_flac
install_vapoursynth
install_command_at_configured_path vspipe "$VSPIPE_PATH"
install_descale
install_vapoursynth_scripts
install_vapoursynth_editor
install_lsmash
build_vs_plugins
install_desktop_shortcuts

install_bluray_python_deps
verify_configured_tool_paths


log "$(msg 'Done. Recommended way to run:' '完成。推荐的运行方式：')"
echo "python3 -m src.main"
