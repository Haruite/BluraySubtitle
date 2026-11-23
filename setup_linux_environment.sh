#!/usr/bin/env bash
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  set -euo pipefail
  setup_project_dir="$(cd -- "$(dirname -- "${BLURAY_SETUP_SOURCE:-$0}")" && pwd)"
  setup_snapshot_dir="$(mktemp -d -t bluraysubtitle-setup.XXXXXXXX)"
  trap 'rm -rf -- "$setup_snapshot_dir"' EXIT
  setup_snapshot_dir="$(realpath -- "$setup_snapshot_dir")"
  setup_temporary_dirs=("$setup_snapshot_dir")

  # Capture the helpers with their import paths and bundled resources before setup starts.
  BLURAY_SETUP_SOURCE="$setup_snapshot_dir/setup_linux_environment.sh"
  tr -d '\r' < "$0" > "$BLURAY_SETUP_SOURCE"
  tar --dereference --exclude=__pycache__ --exclude='*.py[co]' -C "$setup_project_dir" -cf - \
    --exclude="${setup_snapshot_dir##*/}" \
    config.default.json src tools resource/mpv third_party/vapoursynth_scripts third_party/mpv_lazy_shaders \
    | tar -xf - -C "$setup_snapshot_dir"

  setup_config_dir="${BLURAY_SUBTITLE_CONFIG_DIR:-$setup_project_dir}"
  setup_settings_source="${BLURAY_SETTINGS_FILE:-$setup_project_dir/src/core/settings.py}"
  if [[ "$setup_settings_source" != /* ]]; then
    setup_settings_source="$PWD/$setup_settings_source"
  fi
  SETTINGS_FILE="$setup_snapshot_dir/src/core/settings.py"
  if [[ -n "${BLURAY_SETTINGS_FILE:-}" ]]; then
    SETTINGS_FILE="$setup_snapshot_dir/settings-override.py"
    if [[ -f "$setup_settings_source" ]]; then
      cp -- "$setup_settings_source" "$SETTINGS_FILE"
    fi
  fi

  source "$BLURAY_SETUP_SOURCE"
  exit $?
fi
set -euo pipefail

cleanup_setup() {
  if [[ -n "$SUDO_KEEPALIVE_PID" ]]; then
    kill "$SUDO_KEEPALIVE_PID" 2>/dev/null || true
  fi
  rm -rf -- "${setup_temporary_dirs[@]}"
}

SUDO_KEEPALIVE_PID=""
trap cleanup_setup EXIT

X264_SOURCE_REPOSITORY="https://code.videolan.org/videolan/x264.git"
X264_SOURCE_MIRROR="https://github.com/mirror/x264.git"
X265_SOURCE_REPOSITORY="https://github.com/Multicorewareinc/x265.git"
FFMPEG_SOURCE_REPOSITORY="https://github.com/FFmpeg/FFmpeg.git"
SVT_AV1_SOURCE_REPOSITORY="https://gitlab.com/AOMediaCodec/SVT-AV1.git"
FDK_AAC_SOURCE_REPOSITORY="https://github.com/mstorsjo/fdk-aac.git"
FDKAAC_SOURCE_REPOSITORY="https://github.com/nu774/fdkaac.git"
VSEDIT_SOURCE_REPOSITORY="https://github.com/YomikoR/VapourSynth-Editor.git"
LSMASH_SOURCE_REPOSITORY="https://github.com/l-smash/l-smash.git"
# L-SMASH Works uses the liblsmash 2.x API.
LSMASH_COMPATIBLE_TAG_PATTERN='^[vV]?2([.][0-9]+)+$'
MESON_MIN_VERSION="1.4.0"
X264_CONFIGURE_OPTIONS=(--enable-static --bit-depth=all --chroma-format=all --enable-lto)
MPV_FFMPEG_OPTIONS=(--enable-libbluray --enable-libdav1d --enable-libopus --enable-gnutls --enable-vulkan)
MPV_FFMPEG_PACKAGE_OPTIONS=(--disable-static --enable-shared)
MPV_OPTIONS=(-Dlibbluray=enabled -Dlua=luajit -Dvapoursynth=enabled -Dmanpage-build=enabled)
MPV_VULKAN_OPTION=-Dvulkan=enabled
RIFE_MESON_OPTIONS=(-Db_lto=false -Dcpp_args=-march=armv8-a)
RIFE_NCNN_OPTIONS=(-DNCNN_INSTALL_SDK=ON -DNCNN_RUNTIME_CPU=ON -DCMAKE_POSITION_INDEPENDENT_CODE=ON -DCMAKE_INSTALL_LIBDIR=lib)
TSMUXER_CMAKE_OPTIONS=(-DCMAKE_POLICY_VERSION_MINIMUM=3.10 -DCMAKE_BUILD_TYPE=Release
  -DTSMUXER_GUI=OFF -DTSMUXER_STATIC_BUILD=OFF -DWITHOUT_PKGCONFIG=OFF)
TSMUXER_INCLUDE_PATCH='1i#include <algorithm>'
DFTTEST_MESON_OPTIONS=(-Dcpp_link_args=-lfftw3f_threads)
SANGNOM_SSE2NEON_PATCH='s/^#include <emmintrin.h>$/#include <sse2neon.h>/'
SETUP_ROOT="$(dirname -- "$BLURAY_SETUP_SOURCE")"
BLURAY_SETUP_CACHE_DIR="${BLURAY_SETUP_CACHE_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/bluraysubtitle/linux-setup}"
declare -A linux_build_tags=()

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
  local tag cached_tag
  cached_tag="${linux_build_tags["$repository_url $stable_pattern $tag_glob"]:-}"
  if [[ -n "$cached_tag" ]]; then
    printf '%s' "$cached_tag"
    return
  fi

  # Upstreams may mix tag case; keep the original spelling for downloads.
  tag="$(
    git ls-remote --exit-code --refs --tags \
      "$repository_url" "$tag_glob" \
      | awk -F 'refs/tags/' -v stable_pattern="$stable_pattern" \
        'NF == 2 && $2 ~ stable_pattern { print tolower($2) "\t" $2 }' \
      | LC_ALL=C sort -k1,1Vr | awk 'NR == 1 { print $2 }'
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
  command -v python3 >/dev/null 2>&1 || die "$(msg 'python3 is required to read tool paths' '读取工具路径需要 python3')"

  local output name value confirmation initial_paths reader="$SETUP_ROOT/tools/setup_tool_paths.py"
  if ! "$package_build"; then
    local -a read_paths=(env "BLURAY_SUBTITLE_CONFIG_DIR=$setup_config_dir" python3 -B "$reader")
    initial_paths="$("${read_paths[@]}" prepare "$SETTINGS_FILE" "$BLURAY_LANG")" || exit 1
    if [[ -n "$initial_paths" ]]; then
      printf '%s\n' "$initial_paths"
      printf '%s\n' "$(msg 'Edit config.json to change any paths. Press Enter when ready to continue.' '如需修改路径，请编辑 config.json。准备好后按回车继续。')"
      IFS= read -r confirmation || die "$(msg 'Tool paths were not confirmed.' '工具路径尚未确认。')"
    fi
    output="$("${read_paths[@]}" linux "$SETTINGS_FILE" "$BLURAY_LANG")" || exit 1
  else
    [[ -f "$SETTINGS_FILE" ]] || die "$(msg "Settings file not found: ${setup_settings_source}" "找不到设置文件：${setup_settings_source}")"
    # Use -c so shell IDEs can parse this command substitution reliably.
    output="$(python3 -c '
import os
from pathlib import Path
import sys

names = (
    "SEVEN_ZIP_PATH",
    "FLAC_PATH",
    "FFMPEG_PATH",
    "FFPROBE_PATH",
    "X265_PATH",
    "X264_PATH",
    "SVT_AV1_PATH",
    "FDK_AAC_PATH",
    "DOVI_TOOL_PATH",
    "HDR10PLUS_TOOL_PATH",
    "VSEDIT_PATH",
    "VSPIPE_PATH",
    "PLUGIN_PATH",
    "TS_MUXER_PATH",
    "MKVTOOLNIX_PATH",
)
snapshot, original, setup_root = sys.argv[1:]
sys.path.insert(0, setup_root)
# Preserve paths derived from __file__ in custom settings.
settings = {"__name__": "<run_path>", "__file__": original}
exec(compile(Path(snapshot).read_bytes(), original, "exec"), settings)
for name in names:
    value = settings.get(name)
    if not isinstance(value, str) or not value:
        raise SystemExit(f"{name} must be a non-empty string")
    value = os.path.abspath(os.path.expanduser(value))
    if any(character in value for character in "\r\n\t"):
        raise SystemExit(f"{name} contains an unsupported control character")
    print(f"{name}\t{value}")
' "$SETTINGS_FILE" "$setup_settings_source" "$SETUP_ROOT")" || die "$(msg 'Failed to load configured Linux tool paths from settings.py' '无法从 settings.py 读取 Linux 工具路径')"
  fi

  while IFS=$'\t' read -r name value; do
    [[ -n "$name" ]] || continue
    printf -v "$name" '%s' "$value"
  done <<< "$output"

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

artifact_stamp() {
  local checksum
  checksum="$(sha256sum < "$1")" || return 1
  printf '%s%s\n' "${2:+$2 }" "$checksum"
}

installed_artifact_matches() {
  local artifact="$1" record="$1.$2.sha256" checksum
  [[ -f "$artifact" && -f "$record" ]] || return 1
  checksum="$(artifact_stamp "$artifact" "${3:-}")" || return 1
  [[ "$checksum" == "$(cat -- "$record")" ]]
}

install_command_at_configured_path() {
  local command_name="$1"
  local destination="$2"
  local source
  source="$(command -v "$command_name" 2>/dev/null || true)"
  [[ -n "$source" ]] || die "$(msg "Installed command not found: ${command_name}" "找不到已安装命令：${command_name}")"
  install_configured_executable "$source" "$destination"
}

install_component() {
  local title="$1"
  shift
  if [[ -z "${component_stage:-}" ]]; then
    tmux_run "$title" bluray_sudo "$@"
    return
  fi
  mkdir -p -- "$component_stage" || return $?
  if [[ "$1" == make ]]; then
    # Makefile assignments can override environment variables such as DESTDIR.
    set -- "$@" "DESTDIR=$component_stage"
  else
    set -- env "DESTDIR=$component_stage" "$@"
  fi
  tmux_run "$title" "$@" || return $?
  apply_component_stage
}

apply_component_stage() {
  /usr/bin/python3 -B "$SETUP_ROOT/tools/linux_setup_cache.py" install "$component_stage" "$component_manifest" || return $?
  rm -rf -- "$component_stage"
}

ensure_configured_directory() {
  local directory="$1"
  if mkdir -p "$directory" 2>/dev/null; then
    return 0
  fi
  bluray_sudo install -d -m 0755 -o "$(id -u)" -g "$(id -g)" "$directory"
}

sync_mkvtoolnix_paths() {
  local tool
  for tool in mkvinfo mkvmerge mkvpropedit mkvextract; do
    install_configured_executable "/usr/bin/$tool" "$MKVTOOLNIX_PATH/$tool"
  done
}

verify_configured_tool_paths() {
  local path
  for path in \
    "$SEVEN_ZIP_PATH" "$FLAC_PATH" "$FFMPEG_PATH" "$FFPROBE_PATH" \
    "$X265_PATH" "$X264_PATH" "$SVT_AV1_PATH" "$FDK_AAC_PATH" \
    "$DOVI_TOOL_PATH" "$HDR10PLUS_TOOL_PATH" \
    "$VSEDIT_PATH" "$VSPIPE_PATH" "$TS_MUXER_PATH" \
    "$MKVTOOLNIX_PATH"/{mkvinfo,mkvmerge,mkvpropedit,mkvextract}; do
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
    trap - INT TERM

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

    case "$sig_type" in
      INT) exit 130 ;;
      TERM) exit 143 ;;
    esac
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
    trap - INT TERM
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

cached_download() (
  local identity="$1" output="$2" checksum cached partial
  shift 2
  checksum=$(printf '%s' "$identity" | sha256sum)
  cached="$BLURAY_SETUP_CACHE_DIR/downloads/${checksum%% *}"
  if [[ ! -s "$cached" ]]; then
    partial=$(mktemp "$BLURAY_SETUP_CACHE_DIR/downloads/.partial.XXXXXXXX") || return
    trap 'rm -f -- "$partial"' EXIT
    "$@" "$partial" || return
    [[ -s "$partial" ]] || return 1
    mv -fT -- "$partial" "$cached" || return
  fi
  cp --reflink=auto -- "$cached" "$output"
)

fetch_url() {
  wget -nv --timeout=30 --tries=5 -O "$2" "$1"
}

download_url() {
  cached_download "$1" "$2" fetch_url "$1"
}

fetch_git_tree() (
  local repository="$1" tag="$2" output="$3" directory
  directory=$(bluray_mktemp_dir) || return
  trap 'rm -rf -- "$directory"' EXIT
  git clone --depth 1 --branch "$tag" --recurse-submodules=3rdparty --shallow-submodules \
    "$repository" "$directory/source" || return
  tar -czf "$output" -C "$directory" source
)

download_git_tree() (
  local repository="$1" tag="$2" destination="$3" archive
  archive=$(mktemp) || return
  trap 'rm -f -- "$archive"' EXIT
  cached_download "git:$repository/$tag" "$archive" fetch_git_tree "$repository" "$tag" || return
  mkdir -p -- "$destination" || return
  tar -xf "$archive" --strip-components=1 -C "$destination"
)

fetch_source_archive() (
  local archive_url="$1" source_dir="$2" mirror_url="${3:-}" archive
  archive="$(mktemp)" || return 1
  trap 'rm -f -- "$archive"' EXIT
  mkdir -p -- "$source_dir" || return 1

  fetch_and_extract() {
    download_url "$1" "$archive" &&
      tar -xf "$archive" --strip-components=1 -C "$source_dir"
  }

  if ! fetch_and_extract "$archive_url"; then
    [[ -n "$mirror_url" ]] || return 1
    fetch_and_extract "$mirror_url"
  fi
)

github_archive_url() {
  local repository="${1#https://github.com/}"
  printf 'https://codeload.github.com/%s/tar.gz/%s\n' "${repository%.git}" "$2"
}

download_source_archive() {
  local name="$1"
  shift
  tmux_run "$(msg "Download ${name} source" "下载 ${name} 源码")" fetch_source_archive "$@"
}

download_github_release_asset() {
  local repository="${1#https://github.com/}" tag="$2" asset="$3" output="${4:-$3}"
  repository="${repository%.git}"
  if [[ -z "$tag" ]]; then
    tag="$(latest_stable_tag "https://github.com/$repository.git")" || return
  fi
  cached_download "github:$repository/$tag/$asset" "$output" fetch_github_release_asset "$repository" "$tag" "$asset"
}

fetch_github_release_asset() (
  local repository="${1#https://github.com/}" tag="$2" asset_name="$3" output="${4:-$3}"
  local releases_page="https://github.com/${repository%.git}/releases"
  local releases_url="https://api.github.com/repos/${repository%.git}/releases"
  local release_url="${releases_url}/latest" direct_url="${releases_page}/latest/download/${asset_name}"
  local partial content_type
  local -a curl_options=(-fsSL --retry-connrefused --connect-timeout 30 --speed-time 30 --speed-limit 1)
  local -a api_options=("${curl_options[@]}" --retry 1 --proto-redir '=https' -H 'X-GitHub-Api-Version: 2022-11-28')

  if [[ -n "$tag" ]]; then
    release_url="${releases_url}/tags/${tag}"
    direct_url="${releases_page}/download/${tag}/${asset_name}"
  fi
  partial="$(mktemp -- "${output}.XXXXXX")" || return $?
  trap 'rm -f -- "$partial"' EXIT

  fetch_release_api() {
    local url="$1" accept="$2" response
    local -a options=("${api_options[@]}" -H "Accept: $accept" -o "$partial")
    if [[ -n "$setup_github_api_token" ]]; then
      if response="$(curl -q "${options[@]}" -H @- -w '%{http_code} %{content_type}' "$url" \
        <<< "Authorization: Bearer $setup_github_api_token")"; then
        printf '%s' "${response#* }"
        return
      fi
      # The workflow token may lack access to another repository.
      case "${response%% *}" in
        401|403|404) ;;
        *) return 1 ;;
      esac
    fi
    curl -q "${options[@]}" -w '%{content_type}' "$url"
  }

  fetch_api_asset() {
    local asset_id content_type
    fetch_release_api "$release_url" 'application/vnd.github+json' >/dev/null || return $?
    asset_id="$(python3 -c '
import json
import sys

for asset in json.load(sys.stdin)["assets"]:
    if asset["name"] == sys.argv[1]:
        print(asset["id"])
        break
' "$asset_name" < "$partial")" || return $?
    [[ -n "$asset_id" ]] || return 1
    content_type="$(fetch_release_api "${releases_url}/assets/${asset_id}" application/octet-stream)" || return $?
    [[ "$content_type" != *json* && "$content_type" != text/html* ]]
  }

  if ! fetch_api_asset; then
    log "$(msg "GitHub API download failed for ${asset_name}. Trying the official release link." "GitHub API 下载 ${asset_name} 失败，改用官方发布链接。")"
    content_type="$(curl "${curl_options[@]}" --retry 4 -o "$partial" -w '%{content_type}' "$direct_url")" || return $?
    [[ "$content_type" != *json* && "$content_type" != text/html* ]] || return 1
  fi
  mv -f -- "$partial" "$output"
)

# ---------------------------------------------------------------------------
# APT helpers
# ---------------------------------------------------------------------------

apt_update() {
  require_native_build "APT dependencies"
  tmux_run "apt-get update" sudo apt-get update
}

apt_install() {
  require_native_build "APT dependencies"
  tmux_run "apt-get install $*" sudo env DEBIAN_FRONTEND=noninteractive apt-get \
    -o "Dir::Cache::archives=$BLURAY_SETUP_CACHE_DIR/apt" \
    -o APT::Keep-Downloaded-Packages=true install -y "$@"
}

apt_fix_broken() {
  apt_install -f
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
  sudo -v
  if [[ ! -t 0 ]]; then return 0; fi

  (
    while true; do
      sudo -n true || exit 0
      sleep 60
    done
  ) 2>/dev/null &
  SUDO_KEEPALIVE_PID="$!"
}

is_remote_ssh() {
  [[ -n "${SSH_CONNECTION:-}" || -n "${SSH_CLIENT:-}" || -n "${SSH_TTY:-}" ]]
}

start_setup_in_tmux() {
  local session=BluraySubtitle finished
  if ! tmux has-session -t "=$session" 2>/dev/null; then
    finished="$(msg 'Script finished (scroll up to review output, press Ctrl+b d to detach from tmux)' '脚本已结束（可滚动查看上方输出，按 Ctrl+b d 退出 tmux）')"
    if tmux new-session -d -s "$session" -c "$PWD" -e "BLURAY_LANG=$BLURAY_LANG" -- bash -lc '
      BLURAY_SETUP_SOURCE=$1
      setup_config_dir=$2
      SETTINGS_FILE=$3
      setup_settings_source=$4
      finished=$5
      shift 5
      (
        setup_temporary_dirs=("${BLURAY_SETUP_SOURCE%/*}")
        trap '\''rm -rf -- "${setup_temporary_dirs[@]}"'\'' EXIT
        source "$BLURAY_SETUP_SOURCE" --in-tmux "$@"
      )
      printf "\n[BluraySubtitle][SETUP] %s\n" "$finished"
      exec bash
    ' "$session" "$BLURAY_SETUP_SOURCE" "$setup_config_dir" "$SETTINGS_FILE" "$setup_settings_source" "$finished" "$@"; then
      # The pane keeps the snapshot until setup exits, including while detached.
      setup_temporary_dirs=()
    elif ! tmux has-session -t "=$session" 2>/dev/null; then
      return 1
    fi
  fi
  cleanup_setup
  setup_temporary_dirs=()
  tmux set -g mouse off \; set -g status off \; set -g remain-on-exit off
  exec tmux attach-session -t "=$session"
}

require_supported_os() {
  case "$(uname -m)" in
    x86_64|amd64) readonly APT_ARCH=amd64 LINUX_ARCH=x86_64 ;;
    aarch64|arm64) readonly APT_ARCH=arm64 LINUX_ARCH=aarch64 ;;
    *) die "$(msg 'Only x64 and ARM64 Linux are supported' '仅支持 x64 和 ARM64 Linux')" ;;
  esac
  readonly LINUX_MULTIARCH="$LINUX_ARCH-linux-gnu"
  command -v apt-get >/dev/null && command -v dpkg >/dev/null \
    || die "$(msg 'Linux setup requires APT and dpkg. Use the packaged build on other distributions.' 'Linux 安装脚本需要 APT 和 dpkg。其他发行版请使用打包版。')"
  [[ "$(dpkg --print-architecture)" == "$APT_ARCH" ]] \
    || die "$(msg "The APT userspace must match the native ${APT_ARCH} architecture" "APT 用户空间需要与本机 ${APT_ARCH} 架构一致")"

  local ID="" ID_LIKE="" PRETTY_NAME="" VERSION_CODENAME="" UBUNTU_CODENAME="" DEBIAN_CODENAME=""
  . /etc/os-release || die "$(msg 'Cannot read /etc/os-release' '无法读取 /etc/os-release')"
  local base_codename="$VERSION_CODENAME"
  if [[ "$ID" == ubuntu || " $ID_LIKE " == *" ubuntu "* || -n "$UBUNTU_CODENAME" ]]; then
    local DISTRIB_CODENAME=""
    if [[ -z "$UBUNTU_CODENAME" && -r /etc/upstream-release/lsb-release ]]; then
      . /etc/upstream-release/lsb-release
    fi
    base_codename="${UBUNTU_CODENAME:-${DISTRIB_CODENAME:-$VERSION_CODENAME}}"
  elif [[ "$ID" == debian || " $ID_LIKE " == *" debian "* || -r /etc/debian_version ]]; then
    local debian_version=""
    if [[ -r /etc/debian_version ]]; then IFS= read -r debian_version < /etc/debian_version || true; fi
    base_codename="${DEBIAN_CODENAME:-${VERSION_CODENAME:-${debian_version%%/*}}}"
    if [[ "$debian_version" == 13.* && "$ID" != kali ]]; then base_codename=trixie; fi
  else
    die "$(msg 'Setup supports Ubuntu, Debian and their APT derivatives. Use the packaged build on other distributions.' '安装脚本支持 Ubuntu、Debian 及其 APT 衍生版。其他发行版请使用打包版。')"
  fi
  # The upstream PyQt6 Linux wheels have different manylinux tags on the two architectures.
  local minimum_libc=2.34 libc_version
  if [[ "$APT_ARCH" == arm64 ]]; then minimum_libc=2.39; fi
  libc_version="$(getconf GNU_LIBC_VERSION)" && dpkg --compare-versions "${libc_version##* }" ge "$minimum_libc" \
    || die "$(msg "PyQt6 on $APT_ARCH needs glibc $minimum_libc or later. Use the packaged build on older systems." "$APT_ARCH 的 PyQt6 需要 glibc $minimum_libc 或更高版本。较旧系统请使用打包版。")"
  readonly APT_BASE_CODENAME="${base_codename:-$ID}" LINUX_DISTRO_ID="$ID"
  log "$(msg "Detected OS: ${PRETTY_NAME:-unknown} (APT base: $APT_BASE_CODENAME, $APT_ARCH)" "检测到系统：${PRETTY_NAME:-未知}（APT 底座：$APT_BASE_CODENAME，$APT_ARCH）")"
}

# ---------------------------------------------------------------------------
# Language selection must happen before tmux re-exec so the choice is
# inherited by the --in-tmux child via the BLURAY_LANG environment variable.
# ---------------------------------------------------------------------------
select_language
export BLURAY_LANG
require_supported_os

setup_in_tmux=false
if [[ "${1:-}" == "--in-tmux" ]]; then
  setup_in_tmux=true
  shift
fi
package_build=false
restore_only=false
case "${1:-}" in
  --build) package_build=true ;;
  --mode|--mod)
    case "${2:-}" in
      Build) package_build=true ;;
      Desktop) ;;
      *) die "$(msg 'Use --mode Build or --mode Desktop' '请使用 --mode Build 或 --mode Desktop')" ;;
    esac
    ;;
esac
if "$package_build" && [[ "${3:-}" == --restore-only ]]; then
  restore_only=true
fi

require_native_build() {
  if "$restore_only"; then
    if [[ -n "${BLURAY_BUILD_REQUIRED_FILE:-}" ]]; then touch -- "$BLURAY_BUILD_REQUIRED_FILE"; fi
    die "$(msg "The cached build environment needs setup for $1" "缓存的构建环境需要重新安装或构建 $1")"
  fi
}

# Keep the GitHub API token in this shell and out of external build commands.
setup_github_api_token="${BLURAYSUBTITLE_GITHUB_TOKEN:-}"
export -n setup_github_api_token
unset BLURAYSUBTITLE_GITHUB_TOKEN

# ---------------------------------------------------------------------------
# APT state
# ---------------------------------------------------------------------------

# Accept installed packages or APT candidates, including backports and pins.
check_setup_package_versions() {
  local -a requirements=(libvulkan-dev=1.3.277 libavcodec-dev=7.0 libplacebo-dev=6.338.0
                         libdav1d-dev=1.0.0 "meson=$MESON_MIN_VERSION" python3-docutils=0.20)
  if ! "$package_build"; then requirements+=(qt6-base-dev=6.4.0); fi
  local policy entry package minimum candidate installed
  local -a missing=()
  policy="$(LC_ALL=C apt-cache policy "${requirements[@]%%=*}")" || return 1
  for entry in "${requirements[@]}"; do
    package="${entry%=*}"
    minimum="${entry#*=}"
    installed="$(dpkg-query -W -f='${Status} ${Version}' "$package" 2>/dev/null || true)"
    if [[ "$installed" == 'install ok installed '* ]]; then
      installed="${installed##* }"
      if dpkg --compare-versions "${installed#*:}" ge "$minimum"; then continue; fi
    fi
    candidate="$(awk -v name="$package:" '/^[^ ]/ {selected = ($1 == name)} selected && $1 == "Candidate:" {print $2; exit}' <<< "$policy")"
    if [[ -n "$candidate" && "$candidate" != '(none)' ]] && dpkg --compare-versions "${candidate#*:}" ge "$minimum"; then
      setup_build_packages+=("$package")
    else
      missing+=("$package >= $minimum (${candidate:-none})")
    fi
  done
  if (( ${#missing[@]} )); then
    printf '  %s\n' "${missing[@]}" >&2
    return 1
  fi
}

repair_broken_apt_state() {
  log "$(msg 'Checking and repairing broken APT/dpkg state' '检查并修复 APT/Dpkg 破损状态')"
  sudo dpkg --configure -a || true
  apt_fix_broken || die "$(msg 'Failed to repair package dependencies; please run: sudo apt --fix-broken install' '修复系统包依赖失败，请手动执行 sudo apt --fix-broken install')"
}

# ---------------------------------------------------------------------------
# meson version management
# ---------------------------------------------------------------------------

require_meson_version() {
  local version
  version="$(PYTHONNOUSERSITE=1 meson --version)" && dpkg --compare-versions "$version" ge "$MESON_MIN_VERSION" \
    || die "$(msg "The build requires Meson $MESON_MIN_VERSION or later" "编译需要 Meson $MESON_MIN_VERSION 或更高版本")"
}

# ---------------------------------------------------------------------------
# mkvtoolnix
# ---------------------------------------------------------------------------

mkvtoolnix_apt_version() {
  local repository="$1" suite="$2" version="$3"
  LC_ALL=C apt-cache madison mkvtoolnix mkvtoolnix-gui | awk -v repository="$repository" -v suite="$suite/main" -v version="$version" '
    $NF == "Packages" && (repository == "" || (($5 == repository || $5 == repository "/") && $6 == suite)) {
      upstream = $3
      sub(/^[0-9]+:/, "", upstream)
      sub(/-[^-]+$/, "", upstream)
      if (upstream == version) {
        if ($1 == "mkvtoolnix") cli[++count] = $3
        if ($1 == "mkvtoolnix-gui") gui[$3] = 1
      }
    }
    END {
      for (i = 1; i <= count; i++) {
        if (cli[i] in gui) { print cli[i]; break }
      }
    }'
}

mkvtoolnix_installed_version() {
  local tool directory=/usr/bin version output
  local -a tools=(mkvinfo mkvmerge mkvpropedit mkvextract)
  if "$package_build"; then directory="${1:-$MKVTOOLNIX_PATH}"; else tools+=(mkvtoolnix-gui); fi
  for tool in "${tools[@]}"; do
    [[ -x "$directory/$tool" ]] || return 1
  done
  version="$(LC_ALL=C LD_LIBRARY_PATH="${QT66_PREFIX:+$QT66_PREFIX/lib64}" "$directory/mkvmerge" --version | sed -nE 's/^mkvmerge v([0-9]+(\.[0-9]+)+) .*/\1/p')" || return 1
  [[ -n "$version" ]] || return 1
  if "$package_build"; then
    for tool in mkvinfo mkvpropedit mkvextract; do
      output="$(LC_ALL=C LD_LIBRARY_PATH="$QT66_PREFIX/lib64" "$directory/$tool" --version)" || return 1
      [[ "$output " == "$tool v$version "* ]] || return 1
    done
  fi
  printf '%s\n' "$version"
}

mkvtoolnix_latest_version() {
  local tag
  tag="$(latest_stable_tag https://codeberg.org/mbunkus/mkvtoolnix.git '^release-[0-9]+([.][0-9]+)+$' 'release-*')" || return $?
  printf '%s\n' "${tag#release-}"
}

install_mkvtoolnix() {
  if "$package_build"; then
    local version="${MKVTOOLNIX_VERSION:-$(mkvtoolnix_latest_version)}" current_version
    [[ "$version" =~ ^[0-9]+([.][0-9]+)+$ ]] || return 1
    current_version="$(mkvtoolnix_installed_version || true)"
    if [[ -n "$current_version" ]] && dpkg --compare-versions "$current_version" gt "$version"; then
      version="$current_version"
    fi
    cached_linux_build mkvtoolnix build_mkvtoolnix files "$version $qt_cache_abi" \
      "$MKVTOOLNIX_PATH"/{mkvinfo,mkvmerge,mkvpropedit,mkvextract} -- "$version"
    return
  fi

  log "$(msg 'Installing mkvtoolnix / mkvtoolnix-gui' '安装 mkvtoolnix / mkvtoolnix-gui')"
  local entry
  local -a repositories=()
  case "$APT_BASE_CODENAME" in
    noble|resolute|stonking) repositories+=("https://mkvtoolnix.download/ubuntu $APT_BASE_CODENAME") ;;
    bookworm|trixie) repositories+=("https://mkvtoolnix.download/debian $APT_BASE_CODENAME") ;;
  esac
  if (( ${#repositories[@]} > 0 )); then
    local keyring_path="/etc/apt/keyrings/gpg-pub-moritzbunkus.gpg"
    local source_list_path="/etc/apt/sources.list.d/mkvtoolnix.download.list"
    local source_file
    source_file="$(mktemp)"
    if ! tmux_run "$(msg 'Download the MKVToolNix repository signing key' '下载 MKVToolNix 软件源签名密钥')" \
      download_url https://mkvtoolnix.download/gpg-pub-moritzbunkus.gpg "$source_file" \
      || ! bluray_sudo install -D -m 0644 "$source_file" "$keyring_path"; then
      rm -f -- "$source_file"
      die "$(msg 'Failed to install the MKVToolNix repository signing key' '安装 MKVToolNix 软件源签名密钥失败')"
    fi
    for entry in "${repositories[@]}"; do
      printf 'deb [arch=%s signed-by=%s] %s main\n' "$APT_ARCH" "$keyring_path" "$entry"
    done > "$source_file"
    if ! bluray_sudo install -D -m 0644 "$source_file" "$source_list_path"; then
      rm -f -- "$source_file"
      die "$(msg 'Failed to configure the MKVToolNix repository' '配置 MKVToolNix 软件源失败')"
    fi
    rm -f -- "$source_file"
    tmux_run 'apt-get update' sudo apt-get update --error-on=any \
      || die "$(msg 'Failed to refresh the MKVToolNix repository' '刷新 MKVToolNix 软件源失败')"
  else
    apt_update
  fi

  local version="${MKVTOOLNIX_VERSION:-$(mkvtoolnix_latest_version)}" current_version
  [[ "$version" =~ ^[0-9]+(\.[0-9]+)+$ ]] \
    || die "$(msg 'Failed to determine the MKVToolNix release version' '无法确定 MKVToolNix 发布版本')"

  current_version="$(mkvtoolnix_installed_version || true)"
  if [[ -n "$current_version" ]] && dpkg --compare-versions "$current_version" ge "$version"; then
    log "$(msg "Installed MKVToolNix ${current_version} satisfies the requested version ${version}" "已安装的 MKVToolNix ${current_version} 满足所需版本 ${version}")"
    return 0
  fi

  local repository suite deb_version
  # An empty entry checks the configured APT sources after the upstream repositories.
  for entry in "${repositories[@]}" ""; do
    read -r repository suite <<< "$entry"
    deb_version="$(mkvtoolnix_apt_version "$repository" "$suite" "$version")" \
      || die "$(msg 'Failed to query the MKVToolNix repository' '查询 MKVToolNix 软件源失败')"
    [[ -n "$deb_version" ]] || continue
    if [[ -n "$suite" ]]; then
      log "$(msg "Installing MKVToolNix ${version} from its official APT repository (${suite})" "从 MKVToolNix 官方 APT 软件源安装 ${version}（${suite}）")"
    else
      log "$(msg "Installing MKVToolNix ${version} from the configured APT sources" "从已配置的 APT 软件源安装 MKVToolNix ${version}")"
    fi
    apt_install --reinstall "mkvtoolnix=$deb_version" "mkvtoolnix-gui=$deb_version" \
      || die "$(msg 'Failed to install MKVToolNix packages' 'MKVToolNix 软件包安装失败')"
    hash -r
    [[ "$(mkvtoolnix_installed_version)" == "$version" ]] \
      || die "$(msg 'Installed MKVToolNix version verification failed' '安装后的 MKVToolNix 版本校验失败')"
    log "$(msg 'mkvtoolnix installation complete' 'mkvtoolnix 安装完成')"
    return 0
  done

  cached_linux_build mkvtoolnix build_mkvtoolnix system "$version ${QMAKE6:-qmake6} $qt_cache_abi" \
    /usr/bin/{mkvinfo,mkvmerge,mkvpropedit,mkvextract,mkvtoolnix-gui} -- "$version"
}

build_mkvtoolnix() {
  local version="$1"
  if [[ "$(mkvtoolnix_installed_version)" == "$version" ]]; then
    log "$(msg "MKVToolNix $version is already installed, skipping build" "MKVToolNix $version 已安装，跳过编译")"
    return
  fi
  if "$package_build"; then
    # Older Build runs installed these four QtCore clients under the SDK recipe hash.
    local previous previous_lib
    for previous in "${MKVTOOLNIX_PATH%/*/*}"/qt66-"$(uname -m)"-*; do
      previous_lib="$BLURAY_SETUP_CACHE_DIR/${previous##*/}/usr/lib64/libQt6Core.so.6"
      [[ -x "$previous/bin/mkvmerge" ]] && cmp -s "$previous_lib" "$QT66_PREFIX/lib64/libQt6Core.so.6" || continue
      [[ "$(mkvtoolnix_installed_version "$previous/bin")" == "$version" ]] || continue
      log "$(msg "Reusing MKVToolNix $version from the previous Qt SDK" "复用旧 Qt SDK 构建的 MKVToolNix $version")"
      install -m 0755 "$previous"/bin/{mkvinfo,mkvmerge,mkvpropedit,mkvextract} "$MKVTOOLNIX_PATH/" || return $?
      return 0
    done
  fi
  require_native_build MKVToolNix
  log "$(msg "Building MKVToolNix ${version} from source" "从源码编译 MKVToolNix ${version}")"
  local package_name
  local installed_deb_packages=()
  for package_name in mkvtoolnix-gui-dbg mkvtoolnix-dbg mkvtoolnix-gui mkvtoolnix; do
    if [[ "$(dpkg-query -W -f='${Status}' "$package_name" 2>/dev/null || true)" == "install ok installed" ]]; then
      installed_deb_packages+=("$package_name")
    fi
  done

  log "$(msg 'Installing build dependencies' '安装编译所需基础工具')"
  local -a qt_deps=()
  if ! "$package_build"; then qt_deps=(libqt6svg6-dev qt6-base-dev qt6-base-dev-tools qt6-multimedia-dev); fi
  # Boost.System headers are in libboost-dev; Boost >= 1.89 has no separate library.
  apt_install build-essential docbook-xsl libx11-xcb-dev libglu1-mesa-dev \
  libboost-date-time-dev libboost-dev libboost-filesystem-dev libboost-math-dev libboost-regex-dev \
  libbz2-dev libcmark-dev libdvdread-dev libflac-dev libfmt-dev libgmp-dev libgtest-dev liblzo2-dev libmagic-dev \
  libogg-dev libpcre2-8-0 libpcre2-dev libvorbis-dev \
  nlohmann-json3-dev pkg-config po4a "${qt_deps[@]}" \
  rake ruby xsltproc zlib1g-dev unzip libtool autoconf

  local qmake6_tool="${QMAKE6:-qmake6}" qt_version
  qt_version="$(LD_LIBRARY_PATH="${QT66_PREFIX:+$QT66_PREFIX/lib64}" "$qmake6_tool" -query QT_VERSION)" \
    && dpkg --compare-versions "$qt_version" ge 6.4.0 \
    || die "$(msg 'MKVToolNix needs qmake from Qt 6.4 or later' 'MKVToolNix 需要 Qt 6.4 或更高版本的 qmake')"
  local build_dir
  build_dir="$(bluray_mktemp_dir)"

  (
    cd "$build_dir" || exit 1
    log "$(msg 'Downloading source tarball' '下载源码包')"
    download_url "https://mkvtoolnix.download/sources/mkvtoolnix-${version}.tar.xz" "mkvtoolnix_${version}.orig.tar.xz" || exit 1
    log "$(msg 'Extracting source tarball' '解压源码包')"
    tar xJf "mkvtoolnix_${version}.orig.tar.xz" || exit 1

    cd "mkvtoolnix-${version}" || exit 1
    bluray_quarantine_local_boost
    trap bluray_restore_local_boost EXIT

    log "$(msg 'Cleaning previous mkvtoolnix build artifacts' '清理 mkvtoolnix 旧的编译产物')"
    ./drake clean 2>/dev/null || true

    export LD_LIBRARY_PATH=""
    export LIBRARY_PATH="/usr/lib/$LINUX_MULTIARCH:/usr/lib"
    export PKG_CONFIG_PATH="/usr/lib/$LINUX_MULTIARCH/pkgconfig:/usr/share/pkgconfig"
    export LDFLAGS="-L/usr/lib/$LINUX_MULTIARCH -Wl,-rpath-link,/usr/lib/$LINUX_MULTIARCH"

    local gui_option=--enable-gui
    if "$package_build"; then
      gui_option=--disable-gui
      export PKG_CONFIG_PATH="$QT66_PREFIX/lib64/pkgconfig:$PKG_CONFIG_PATH"
      export LD_LIBRARY_PATH="$QT66_PREFIX/lib64"
      export LDFLAGS="-L$QT66_PREFIX/lib64 -Wl,-rpath-link,$QT66_PREFIX/lib64 $LDFLAGS"
      # MKVToolNix discards the relative -I paths qmake emits with the Actions cache and build layout.
      local qt_headers
      qt_headers="$("$qmake6_tool" -query QT_INSTALL_HEADERS)" || exit 1
      export CPLUS_INCLUDE_PATH="$qt_headers:$qt_headers/QtCore${CPLUS_INCLUDE_PATH:+:$CPLUS_INCLUDE_PATH}"
    fi
    log "$(msg 'Configuring MKVToolNix' '正在配置 MKVToolNix')"
    ./configure \
      --prefix=/usr \
      --docdir='${datarootdir}/doc/mkvtoolnix-gui' \
      --with-qmake6="$qmake6_tool" \
      "$gui_option" \
      --enable-optimization || {
        # Show the failing compiler probe before Autoconf's cache and variable dumps.
        if [[ -f config.log ]]; then sed '/^## Cache variables/,$d' config.log | tail -n 100 >&2; fi
        exit 1
      }

    log "$(msg 'Building mkvtoolnix with Rake' '使用 Rake 编译 mkvtoolnix')"
    if "$package_build"; then
      # The default target includes GUI unit tests when GoogleTest is present.
      tmux_run "mkvtoolnix CLI build" ./drake -j"$(nproc)" apps:cli || exit 1
      install -s -m 0755 src/{mkvinfo,mkvmerge,mkvpropedit,mkvextract} "$MKVTOOLNIX_PATH/" || exit 1
      exit 0
    fi

    tmux_run "mkvtoolnix build" ./drake -j"$(nproc)" || exit 1
    ./drake apps:strip || exit 1
    if (( ${#installed_deb_packages[@]} > 0 )); then
      log "$(msg "Removing installed mkvtoolnix deb packages: ${installed_deb_packages[*]}" "正在卸载已安装的 mkvtoolnix deb 软件包：${installed_deb_packages[*]}")"
      tmux_run "apt-get remove ${installed_deb_packages[*]}" \
        sudo env DEBIAN_FRONTEND=noninteractive apt-get remove -y "${installed_deb_packages[@]}" || exit 1
      hash -r
    fi

    log "$(msg 'Installing mkvtoolnix with rake install' '使用 rake install 安装 mkvtoolnix')"
    install_component "rake install" rake install || exit 1
    bluray_restore_local_boost
    trap - EXIT
    apt_clean
  ) || die "$(msg 'mkvtoolnix build/install failed (if missing deps, install them manually and retry)' 'mkvtoolnix 编译/安装失败（如提示缺依赖，可手动补齐后重试）')"

  [[ "$(mkvtoolnix_installed_version)" == "$version" ]] \
    || die "$(msg 'Installed MKVToolNix version verification failed' '安装后的 MKVToolNix 版本校验失败')"
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
  # Use Debian's 3.3.2-3+b1 header for https://bugs.debian.org/1124682.
  # The snapshot retains the rebuild after it leaves the current Debian pool.
  local package_version
  package_version="$(dpkg-query -W -f='${Version}' libdovi-dev 2>/dev/null || true)"
  case "$package_version" in
    3.3.2-*) ;;
    *) return 1 ;;
  esac

  local snapshot_hash checksum
  case "$APT_ARCH" in
    amd64)
      snapshot_hash="5a43c70cf9cf92b95609732337723c60332f9edf"
      checksum="517d9a81e904d0b337e04b4f9fef0c4a1939fddc49237612547fd8ae033f3ad1"
      ;;
    arm64)
      snapshot_hash="e253e994ecfcd842db848e31f9d439495a30b62d"
      checksum="27c6b2a66ab2de4ddd2f5b87ecb0826cb504f7218fc1cf73a649fdbc4b2c760b"
      ;;
    *) return 1 ;;
  esac

  local repair_dir archive extracted_header
  repair_dir="$(bluray_mktemp_dir)"
  archive="$repair_dir/libdovi-dev.deb"
  extracted_header="$repair_dir/extracted/usr/include/libdovi/rpu_parser.h"

  log "$(msg "Repairing the truncated libdovi header with Debian's rebuilt 3.3.2 header" '使用 Debian 重新生成的 3.3.2 头文件修复被截断的 libdovi 头文件')"
  if ! (
    tmux_run "$(msg 'Download the rebuilt libdovi development header' '下载重新生成的 libdovi 开发头文件')" \
      download_url "https://snapshot.debian.org/file/$snapshot_hash" "$archive" \
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
  libdovi_pkg_config_path="/usr/local/lib/pkgconfig:/usr/local/lib/$LINUX_MULTIARCH/pkgconfig:$HOME/.local/lib/pkgconfig:$HOME/.local/lib/$LINUX_MULTIARCH/pkgconfig:${PKG_CONFIG_PATH:-}"
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
    download_source_archive "dovi_tool ${DOVI_TOOL_VERSION}" \
      "https://codeload.github.com/quietvoid/dovi_tool/tar.gz/refs/tags/${DOVI_TOOL_VERSION}" dovi_tool || exit 1
    cd dovi_tool/dolby_vision || exit 1
    local lib_dir destdir=""
    local -a install_args=(--release --prefix="$HOME/.local")
    if [[ -n "${component_stage:-}" ]]; then
      destdir="$component_stage"
      install_args+=(--destdir="$destdir")
    fi
    tmux_run "$(msg 'Build and install dolby_vision' '编译安装 dolby_vision')" cargo cinstall "${install_args[@]}" || exit 1

    lib_dir="$(
      find "$destdir$HOME/.local" -maxdepth 6 -name "libdovi.so*" -printf "%h\n" -quit 2>/dev/null
    )"
    if [[ -z "${lib_dir:-}" ]]; then
      exit 1
    fi

    log "$(msg 'Copying runtime library to /usr/local/lib and refreshing ldconfig' '安装运行库到 /usr/local/lib 并刷新 ldconfig')"
    if [[ -n "$destdir" ]]; then
      install -d "$destdir/usr/local/lib" || exit 1
      cp -a "$lib_dir"/libdovi.so* "$destdir/usr/local/lib/" || exit 1
      apply_component_stage || exit 1
    else
      sudo cp -a "$lib_dir"/libdovi.so* /usr/local/lib/ || exit 1
    fi
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
  local installed_version tag
  if [[ -x "$DOVI_TOOL_PATH" ]] && installed_version="$("$DOVI_TOOL_PATH" --version 2>/dev/null)" &&
      { [[ -z "$DOVI_TOOL_VERSION" ]] || [[ "$installed_version" == "dovi_tool ${DOVI_TOOL_VERSION#[vV]}" ]]; }; then
    log "$(msg "dovi_tool already installed (${DOVI_TOOL_PATH}), skipping" "检测到 dovi_tool 已安装（${DOVI_TOOL_PATH}），跳过")"
    return 0
  fi
  tag="${DOVI_TOOL_VERSION:-$(latest_stable_tag https://github.com/quietvoid/dovi_tool.git)}"
  log "$(msg "Installing dovi_tool ${tag} (prebuilt)" "安装 dovi_tool ${tag}（预编译包）")"

  local tarball="dovi_tool-${tag}-${LINUX_ARCH}-unknown-linux-musl.tar.gz"

  local deps=(git curl tar)
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
      download_github_release_asset quietvoid/dovi_tool "$tag" "$tarball" || exit 1
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

  local tarball="hdr10plus_tool-${version#v}-${LINUX_ARCH}-unknown-linux-musl.tar.gz"

  local deps=(git curl tar)
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
      download_github_release_asset quietvoid/hdr10plus_tool "$version" "$tarball" || exit 1
    tmux_run "$(msg 'Extract hdr10plus_tool tarball' '解压 hdr10plus_tool 压缩包')" tar zxf "$tarball" || exit 1
    install_configured_executable hdr10plus_tool "$HDR10PLUS_TOOL_PATH" || exit 1
  ) || die "$(msg 'hdr10plus_tool install failed' 'hdr10plus_tool 安装失败')"

  rm -rf "$install_dir"
  "$HDR10PLUS_TOOL_PATH" --version 2>&1 | grep -F "hdr10plus_tool ${version#v}" >/dev/null || \
    die "$(msg 'Installed hdr10plus_tool verification failed' '安装后的 hdr10plus_tool 验证失败')"
  log "$(msg 'hdr10plus_tool installation complete' 'hdr10plus_tool 安装完成')"
}

# ---------------------------------------------------------------------------
# mpv + FFmpeg / FFprobe
# ---------------------------------------------------------------------------

__installed_ffmpeg_version() {
  local executable="$1" suffix='[^[:space:]]*'
  [[ -x "$executable" ]] || return 0
  if "$package_build"; then suffix=''; fi
  "$executable" -version 2>/dev/null \
    | sed -nE "1s/^ff(mpeg|probe) version n?([0-9]+([.][0-9]+){1,3})${suffix}([[:space:]].*)?$/\2/p"
}

__ffmpeg_has_libopus() {
  local executable="$1"
  [[ -x "$executable" ]] || return 1
  "$executable" -hide_banner -h encoder=libopus 2>&1 | grep '^Encoder libopus' >/dev/null
}

test_mpv_vapoursynth() (
  local executable="$1" probe_dir probe_file output LC_ALL=C
  "$executable" --no-config --vf=help 2>/dev/null | grep -E '^[[:space:]]+vapoursynth[[:space:]]' >/dev/null || return 1
  probe_dir="$(mktemp -d)" || return 1
  trap 'rm -rf -- "$probe_dir"' EXIT
  probe_file="$probe_dir/probe.vpy"
  printf '%s\n' 'import vapoursynth as vs' 'assert vs.core.core_version.release_major == 79' \
    'assert user_data in ("bluray-probe", b"bluray-probe")' \
    'video_in.std.AddBorders(left=8, right=8).set_output()' > "$probe_file" || return 1

  # mpv can continue playback after a filter fails. Verify the filtered frame size.
  if ! output="$(timeout 20s "$executable" --no-config --load-scripts=no --load-select=no \
      --no-audio --ao=null --vo=null --frames=2 --msg-level=all=warn,cplayer=info \
      "--vf=vapoursynth=file=%${#probe_file}%$probe_file:user-data=bluray-probe" \
      'av://lavfi:testsrc2=size=64x48:rate=24' 2>&1)" \
    || [[ "$output" != *'VO: [null] 80x48 '* ]]; then
    printf '%s\n' "$output" >&2
    return 1
  fi
)

__mpv_tools_share_ffmpeg() {
  local library_dir="$1" program codec shared_codec=""
  for program in "$2" "$FFMPEG_PATH" "$FFPROBE_PATH"; do
    codec="$(LC_ALL=C ldd "$program" | awk '$1 ~ /^libavcodec[.]so[.]/ && $2 == "=>" { print $3 }')" || return 1
    if [[ "$codec" != "$library_dir"/libavcodec.so.* || "$codec" != "${shared_codec:-$codec}" ]]; then
      log "$(msg "$program uses libavcodec at ${codec:-unknown}, expected $library_dir" "$program 使用的 libavcodec 位于 ${codec:-未知}，预期目录为 $library_dir")" >&2
      return 1
    fi
    shared_codec="$codec"
  done
}

__mpv_tools_have_vulkan() {
  local drivers apis hwaccels
  drivers="$("$1" --no-config --vo=help)" &&
    grep -Eq '^[[:space:]]*gpu-next([[:space:]]|$)' <<< "$drivers" &&
    apis="$("$1" --no-config --gpu-api=help)" &&
    grep -Eq '^[[:space:]]*vulkan([[:space:]]|$)' <<< "$apis" &&
    hwaccels="$("$FFMPEG_PATH" -hide_banner -hwaccels)" &&
    grep -Fxq vulkan <<< "$hwaccels"
}

install_mpv() {
  log "$(msg 'Installing mpv with VapourSynth and stable FFmpeg / FFprobe' '安装支持 VapourSynth 的 mpv 与稳定版 FFmpeg / FFprobe')"

  local mpv_tag required_mpv_version shared_ffmpeg_dir=/usr/local/lib/bluraysubtitle-ffmpeg
  mpv_tag="$(latest_stable_tag https://github.com/mpv-player/mpv.git '^v[0-9]+([.][0-9]+)+$' 'v*')" || return $?
  required_mpv_version="${mpv_tag#v}"
  local mpv_executable=mpv
  if ! "$package_build"; then mpv_executable="${MPV_PATH:-mpv}"; fi
  local ffmpeg_tag target_ffmpeg_version installed_ffmpeg_version installed_ffprobe_version ffmpeg_is_current="false"
  ffmpeg_tag="$(latest_stable_tag "$FFMPEG_SOURCE_REPOSITORY" '^n[0-9]+([.][0-9]+)+$' 'n*')" || return $?
  target_ffmpeg_version="${ffmpeg_tag#n}"
  # A restored package must match its source tag. Desktop can reuse a newer system FFmpeg.
  local ffmpeg_version_relation=ge
  if "$package_build"; then ffmpeg_version_relation=eq; fi
  installed_ffmpeg_version="$(__installed_ffmpeg_version "$FFMPEG_PATH" || true)"
  installed_ffprobe_version="$(__installed_ffmpeg_version "$FFPROBE_PATH" || true)"
  if [[ -n "$installed_ffmpeg_version" && -n "$installed_ffprobe_version" ]] \
    && dpkg --compare-versions "$installed_ffmpeg_version" "$ffmpeg_version_relation" "$target_ffmpeg_version" \
    && dpkg --compare-versions "$installed_ffprobe_version" "$ffmpeg_version_relation" "$target_ffmpeg_version" \
    && __ffmpeg_has_libopus "$FFMPEG_PATH"; then
    ffmpeg_is_current="true"
  fi

  local installed_mpv current_mpv_version
  if installed_mpv="$(command -v "$mpv_executable")"; then
    installed_mpv="$(/usr/bin/python3 -B "$SETUP_ROOT/tools/mpv/install.py" --native-executable "$installed_mpv")" || return 1
    current_mpv_version="$("$installed_mpv" --version 2>/dev/null | head -n 1 | grep -oP 'mpv\s+v?\K[0-9]+(\.[0-9]+){1,2}' || true)"
    if [[ -n "${current_mpv_version:-}" ]] && dpkg --compare-versions "$current_mpv_version" ge "$required_mpv_version"; then
      if [[ "$ffmpeg_is_current" == "true" ]] \
        && __mpv_tools_have_vulkan "$installed_mpv" \
        && { ! "$package_build" || __mpv_tools_share_ffmpeg "$shared_ffmpeg_dir" "$installed_mpv"; } \
        && "$installed_mpv" --no-config --list-properties | grep -E '^[[:space:]]+default-menu$' >/dev/null \
        && test_mpv_vapoursynth "$installed_mpv"; then
        if ! "$package_build" && ! has_libdovi_development; then
          log "$(msg 'mpv installed but libdovi development files are missing, installing libdovi' '检测到 mpv 已安装但缺少 libdovi 开发文件，尝试安装 libdovi')"
          install_libdovi
        fi
        log "$(msg "mpv with working VapourSynth and FFmpeg / FFprobe with libopus satisfy the requirements, skipping" "mpv 的 VapourSynth 滤镜和 FFmpeg / FFprobe 的 libopus 支持均满足要求，跳过编译安装")"
        return 0
      fi
      log "$(msg "Rebuilding mpv with VapourSynth and FFmpeg / FFprobe ${target_ffmpeg_version} with libopus" "重新编译支持 VapourSynth 的 mpv，以及带 libopus 支持的 FFmpeg / FFprobe ${target_ffmpeg_version}")"
    else
      log "$(msg "System mpv version is too old (${current_mpv_version:-unknown} < ${required_mpv_version}), rebuilding from source" "检测到系统 mpv 版本较旧（${current_mpv_version:-unknown} < ${required_mpv_version}），将从源码编译升级")"
    fi
  fi

  require_native_build "mpv and FFmpeg"
  install_libdovi

  log "$(msg 'Installing mpv build dependencies' '安装 mpv 编译所需系统依赖')"
  local mpv_deps=(
    build-essential cmake meson ninja-build git pkg-config
    libdav1d-dev libopus-dev
    libssl-dev libjpeg-dev zlib1g-dev libavcodec-dev libavformat-dev
    libavutil-dev libswscale-dev libswresample-dev libavfilter-dev
    libass-dev libfribidi-dev libfreetype-dev libfontconfig1-dev
    libharfbuzz-dev libuchardet-dev libgl1-mesa-dev libvdpau-dev
    libva-dev libx11-dev libxext-dev libxv-dev libxinerama-dev
    libwayland-dev libxkbcommon-dev libegl1-mesa-dev libplacebo-dev
    libasound2-dev libpulse-dev libjack-dev libpipewire-0.3-dev
    libluajit-5.1-dev yt-dlp glslang-tools glslang-dev
    libspirv-cross-c-shared-dev autoconf
    automake libtool wayland-protocols libmujs-dev libbluray-dev
    libunwind-dev libxrandr-dev libxpresent-dev libxss-dev libdvdnav-dev
    libdvdread-dev libzimg-dev libarchive-dev librubberband-dev libsdl2-dev
    libdrm-dev libgbm-dev libgnutls28-dev libvulkan-dev spirv-headers python3-docutils curl xz-utils
  )
  if [[ "$APT_ARCH" == amd64 ]]; then
    mpv_deps+=(yasm nasm)
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
  local pkg_config_path="/usr/local/lib/$LINUX_MULTIARCH/pkgconfig:/usr/local/lib/pkgconfig:$HOME/.local/lib/pkgconfig:$HOME/.local/lib/$LINUX_MULTIARCH/pkgconfig:${PKG_CONFIG_PATH:-}"
  PKG_CONFIG_PATH="$pkg_config_path" install_shaderc

  require_meson_version
  local build_dir libass_tag libplacebo_tag
  libass_tag="$(latest_stable_tag https://github.com/libass/libass.git '^[0-9]+([.][0-9]+)+$')"
  libplacebo_tag="$(latest_stable_tag https://github.com/haasn/libplacebo.git '^v[0-9]+([.][0-9]+)+$' 'v*')"
  build_dir="$(bluray_mktemp_dir)"

  (
    cd "$build_dir" || exit 1

    # Supply the source directories directly because mpv-build's update step clones them.
    local mpv_build_revision
    mpv_build_revision="${linux_mpv_build_revision:-$(resolve_mpv_build_revision)}" || exit 1
    download_source_archive mpv-build \
      "https://codeload.github.com/mpv-player/mpv-build/tar.gz/$mpv_build_revision" . || exit 1
    download_source_archive "FFmpeg ${target_ffmpeg_version}" \
      "$(github_archive_url "$FFMPEG_SOURCE_REPOSITORY" "refs/tags/$ffmpeg_tag")" ffmpeg || exit 1
    # Use the release tag even when the build directory is inside another Git checkout.
    printf '%s\n' "$target_ffmpeg_version" > ffmpeg/FF_VERSION || exit 1
    download_source_archive "mpv ${mpv_tag}" \
      "https://codeload.github.com/mpv-player/mpv/tar.gz/refs/tags/${mpv_tag}" mpv || exit 1
    download_source_archive "libass ${libass_tag}" \
      "https://codeload.github.com/libass/libass/tar.gz/refs/tags/${libass_tag}" libass || exit 1
    # The libplacebo tag archive omits the bundled build dependencies.
    tmux_run "$(msg "Download libplacebo ${libplacebo_tag}" "下载 libplacebo ${libplacebo_tag}")" \
      download_git_tree https://github.com/haasn/libplacebo.git "$libplacebo_tag" libplacebo || exit 1

    printf '%s\n' "${MPV_FFMPEG_OPTIONS[@]}" > ffmpeg_options || exit 1
    if "$package_build"; then
      # Keep the three executables on one redistributable FFmpeg runtime.
      printf '%s\n' "${MPV_FFMPEG_PACKAGE_OPTIONS[@]}" >> ffmpeg_options || exit 1
      export LDFLAGS="${LDFLAGS:+$LDFLAGS }-Wl,-rpath,$shared_ffmpeg_dir"
      export LD_LIBRARY_PATH="$PWD/build_libs/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
    fi
    printf '%s\n' "${MPV_OPTIONS[@]}" > mpv_options || exit 1
    printf '%s\n' "$MPV_VULKAN_OPTION" > libplacebo_options || exit 1
    printf '%s\n' "$MPV_VULKAN_OPTION" >> mpv_options || exit 1

    export PKG_CONFIG_PATH="$pkg_config_path"
    export PATH="/usr/local/bin:$HOME/.local/bin:$PATH"
    pkg-config --atleast-version=56 vapoursynth \
      || die "$(msg 'mpv requires VapourSynth VSScript development files version 56 or later' 'mpv 需要 VapourSynth VSScript 56 或更高版本的开发文件')"

    # FFmpeg can write generated resources before make creates their directory.
    mkdir -p ffmpeg_build/fftools/resources || exit 1
    log "$(msg "Building mpv and FFmpeg in ${build_dir}. FFmpeg prints its configuration summary after checking the compiler and libraries." "在 ${build_dir} 编译 mpv 和 FFmpeg。FFmpeg 会在检查完编译器和依赖库后输出配置摘要。")"
    tmux_run "mpv-build build" env PYTHONNOUSERSITE=1 ./build -j"$(nproc)" || exit 1
    test_mpv_vapoursynth "$PWD/mpv/build/mpv" \
      || die "$(msg 'The rebuilt mpv failed the VapourSynth playback check' '重新编译的 mpv 未通过 VapourSynth 播放验证')"
    if "$package_build"; then
      local shared_stage="$component_stage$shared_ffmpeg_dir"
      install -d -m 0755 "$shared_stage" || exit 1
      local library
      for library in build_libs/lib/lib{av*,sw*}.so.*; do
        # Install each SONAME once. The linker does not need the other aliases.
        if [[ "${library##*.so.}" =~ ^[0-9]+$ ]]; then
          install -m 0644 "$library" "$shared_stage/" || exit 1
        fi
      done
    fi
    install_component "mpv-build install" env PYTHONNOUSERSITE=1 "PATH=$PATH" "PKG_CONFIG_PATH=${PKG_CONFIG_PATH:-}" ./install || exit 1
    install_configured_executable build_libs/bin/ffmpeg "$FFMPEG_PATH" || exit 1
    install_configured_executable build_libs/bin/ffprobe "$FFPROBE_PATH" || exit 1
    if ! "$package_build" && [[ -n "$MPV_PATH" ]]; then
      install_configured_executable "$PWD/mpv/build/mpv" "$MPV_PATH" || exit 1
    fi
  ) || die "$(msg "mpv build/install failed. Build files were kept in ${build_dir}" "mpv 编译/安装失败。构建文件保留在 ${build_dir}")"

  installed_ffmpeg_version="$(__installed_ffmpeg_version "$FFMPEG_PATH" || true)"
  installed_ffprobe_version="$(__installed_ffmpeg_version "$FFPROBE_PATH" || true)"
  if [[ "$installed_ffmpeg_version" != "$target_ffmpeg_version" || "$installed_ffprobe_version" != "$target_ffmpeg_version" ]] \
    || ! __ffmpeg_has_libopus "$FFMPEG_PATH"; then
    die "$(msg "Installed FFmpeg / FFprobe version or libopus support verification failed. Build files were kept in ${build_dir}" "安装后的 FFmpeg / FFprobe 版本或 libopus 支持校验失败。构建文件保留在 ${build_dir}")"
  fi
  if "$package_build" && ! __mpv_tools_share_ffmpeg "$shared_ffmpeg_dir" "$(command -v mpv)"; then
    die "$(msg 'mpv, FFmpeg and FFprobe did not link to the shared FFmpeg runtime' 'mpv、FFmpeg 或 FFprobe 未链接到同一套 FFmpeg 运行库')"
  fi
  if ! __mpv_tools_have_vulkan "$mpv_executable"; then
    die "$(msg 'The installed mpv and FFmpeg must both support Vulkan' '安装后的 mpv 和 FFmpeg 必须均支持 Vulkan')"
  fi
  rm -rf "$build_dir"
  log "$(msg "mpv with VapourSynth and FFmpeg / FFprobe with libopus installed (${installed_ffmpeg_version}/${installed_ffprobe_version})" "已安装支持 VapourSynth 的 mpv，以及带 libopus 支持的 FFmpeg / FFprobe（${installed_ffmpeg_version}/${installed_ffprobe_version}）")"
}

build_mpv_uosc_archive() (
  local repository="$1" tag="$2" output="$3" build_dir bundle
  build_dir="$(bluray_mktemp_dir)" || return
  trap 'rm -rf -- "$build_dir"' EXIT
  bundle="$build_dir/uosc"
  tmux_run "uosc download" download_github_release_asset "$repository" "$tag" uosc.zip "$build_dir/uosc.zip" \
    || die "$(msg 'Could not download the uosc release' '无法下载 uosc 发布包')"
  unzip -q "$build_dir/uosc.zip" -d "$bundle" -x 'scripts/uosc/bin/ziggy-darwin' 'scripts/uosc/bin/ziggy-windows.exe' || return
  download_url "https://raw.githubusercontent.com/tomasklaen/uosc/$tag/LICENSE.LGPL" "$bundle/LICENSE.LGPL" || return
  if [[ "$APT_ARCH" == arm64 ]]; then
    # Rebuild Ziggy from the same tag as the installed uosc release.
    require_native_build "uosc Ziggy"
    local go_release go_archive go_checksum
    go_release="$(curl -fsSL --retry 4 --connect-timeout 20 --max-time 45 'https://go.dev/dl/?mode=json' | python3 -c '
import json
import sys

release = next(release for release in json.load(sys.stdin) if release["stable"])
archive = next(file for file in release["files"] if file["os"] == "linux"
             and file["arch"] == "arm64" and file["kind"] == "archive")
print(archive["filename"], archive["sha256"])
')" || die "$(msg 'Could not resolve the Linux ARM64 Go archive' '无法获取 Go 的 Linux ARM64 发布包信息')"
    read -r go_archive go_checksum <<< "$go_release"
    tmux_run "$(msg 'Download Go for uosc' '下载 uosc 所需的 Go')" \
      download_url "https://go.dev/dl/$go_archive" "$build_dir/$go_archive" || return
    printf '%s  %s\n' "$go_checksum" "$build_dir/$go_archive" | sha256sum -c - || return
    tar -xzf "$build_dir/$go_archive" -C "$build_dir" || return
    download_source_archive "uosc ${tag}" "$(github_archive_url "$repository" "refs/tags/$tag")" "$build_dir/source" || return
    (
      cd "$build_dir/source" || exit
      tmux_run "$(msg 'Build uosc Ziggy for ARM64' '编译 ARM64 版 uosc Ziggy')" \
        env CGO_ENABLED=0 GOOS=linux GOARCH=arm64 GOTOOLCHAIN=local \
        GOPATH="$build_dir/gopath" GOCACHE="$build_dir/go-cache" "$build_dir/go/bin/go" \
        build -modcacherw -ldflags='-s -w' -o "$bundle/scripts/uosc/bin/ziggy-linux" ./src/ziggy/ziggy.go
    ) || return
  fi
  chmod +x "$bundle/scripts/uosc/bin/ziggy-linux" || return
  tar -czf "$output" -C "$bundle" .
)

stage_mpv_uosc_archive() (
  local output="$1" repository=https://github.com/tomasklaen/uosc tag pending
  tag="$(latest_stable_tag "$repository.git")" || return
  pending="$(mktemp -- "$(dirname -- "$output")/.uosc.XXXXXXXX")" || return
  trap 'rm -f -- "$pending"' EXIT
  cached_download "uosc-assets:v1:$repository:$tag:$APT_ARCH" "$pending" \
    build_mpv_uosc_archive "$repository" "$tag" || return
  mv -fT -- "$pending" "$output"
)

install_mpv_desktop() (
  local build_dir installer status bundle=--configure
  if [[ -n "$MPV_CONFIG_PATH" ]]; then
    export MPV_HOME="$MPV_CONFIG_PATH"
  fi
  installer="$(dirname -- "$BLURAY_SETUP_SOURCE")/tools/mpv/install.py"
  status="$(python3 "$installer" --status "$BLURAY_LANG" "$PLUGIN_PATH")" \
    || die "$(msg 'Could not check the mpv desktop configuration' '无法检查 mpv 桌面配置')"
  if [[ "$status" == "ready" ]]; then
    log "$(msg 'Both mpv menu languages and desktop settings are ready' 'mpv 双语菜单及桌面配置已就绪')"
    return 0
  fi
  if [[ "$status" == "install" ]]; then
    build_dir="$(bluray_mktemp_dir)"
    trap 'rm -rf -- "$build_dir"' EXIT
    stage_mpv_uosc_archive "$build_dir/uosc.tar.gz" || die "$(msg 'Could not prepare uosc' '无法准备 uosc')"
    bundle="$build_dir/uosc"
    mkdir -- "$bundle"
    tar -xzf "$build_dir/uosc.tar.gz" -C "$bundle"
  fi

  log "$(msg 'Configuring the English and Chinese mpv menus, shaders and playback presets' '正在配置 mpv 中英文菜单、着色器和播放预设')"
  python3 "$installer" "$bundle" "$BLURAY_LANG" "$PLUGIN_PATH" "${MPV_PATH:-mpv}" \
    || die "$(msg 'Could not configure the mpv desktop' '无法配置 mpv 桌面界面')"
)

# ---------------------------------------------------------------------------
# L-SMASH
# ---------------------------------------------------------------------------

__lsmash_is_installed() {
  local required_version="$1" version
  version="$(pkg-config --modversion liblsmash 2>/dev/null)" || return $?
  [[ "$version" == 2.* ]] && dpkg --compare-versions "$version" ge "$required_version"
}

install_lsmash() {
  log "$(msg 'Installing L-SMASH (build from source)' '安装 lsmash（从源码编译并安装）')"

  export PKG_CONFIG_PATH="/usr/local/lib/pkgconfig:/usr/local/lib/$LINUX_MULTIARCH/pkgconfig:${PKG_CONFIG_PATH:-}"

  local lsmash_tag required_version
  lsmash_tag="${LSMASH_VERSION:-$(latest_stable_tag "$LSMASH_SOURCE_REPOSITORY" "$LSMASH_COMPATIBLE_TAG_PATTERN")}" || return $?
  [[ "$lsmash_tag" =~ $LSMASH_COMPATIBLE_TAG_PATTERN ]] \
    || die "$(msg "L-SMASH Works requires a stable L-SMASH 2.x release (selected: $lsmash_tag)" \
      "L-SMASH Works 需要 L-SMASH 2.x 稳定版（当前选择：$lsmash_tag）")"
  required_version="${lsmash_tag#[vV]}"
  if __lsmash_is_installed "$required_version"; then
    log "$(msg 'Compatible L-SMASH release already installed, skipping build' \
      '已安装兼容的 L-SMASH 版本，跳过编译安装')"
    return 0
  fi
  require_native_build L-SMASH

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

    download_source_archive "L-SMASH ${lsmash_tag}" \
      "$(github_archive_url "$LSMASH_SOURCE_REPOSITORY" "refs/tags/$lsmash_tag")" l-smash || exit 1
    cd l-smash || exit 1

    log "$(msg 'Configuring and building L-SMASH' '配置与编译 lsmash')"
    tmux_run "lsmash configure" ./configure --enable-shared || exit 1
    tmux_run "lsmash make" make -j"$(nproc)" || exit 1
    install_component "lsmash install" make install || exit 1
    sudo ldconfig || exit 1
  ) || die "$(msg 'L-SMASH build/install failed' 'lsmash 编译/安装失败')"

  rm -rf "$build_dir"
  __lsmash_is_installed "$required_version" \
    || die "$(msg "Installed liblsmash does not satisfy the required 2.x version ($required_version or newer)" \
      "安装后的 liblsmash 版本不满足要求（2.x 且至少为 $required_version）")"
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

  local deps=(build-essential cmake git python3)
  if [[ "$APT_ARCH" == amd64 ]]; then
    deps+=(nasm)
  fi
  apt_update
  apt_install "${deps[@]}" || die "$(msg 'Failed to install x265 dependencies' 'x265 依赖安装失败')"

  local build_dir
  build_dir="$(mktemp -d)"

  (
    cd "$build_dir" || exit 1
    local archive="x265_${x265_version}.tar.gz"
    tmux_run "$(msg "Download x265 ${x265_version} source" "下载 x265 ${x265_version} 源码")" \
      download_github_release_asset "$X265_SOURCE_REPOSITORY" "$x265_version" "$archive" || exit 1
    mkdir -p x265 || exit 1
    tar -xf "$archive" --strip-components=1 -C x265 || exit 1
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

resolve_x264_source() {
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
      log "$(msg 'The official x264 repository is unavailable; trying the GitHub mirror' 'x264 官方仓库不可用，尝试 GitHub 镜像')" >&2
    fi
  done
  [[ -n "$x264_repository" && -n "$x264_commit" ]] || \
    die "$(msg 'Failed to resolve the latest x264 master revision from the official repository or mirror' '无法从 x264 官方仓库或镜像解析 master 的最新版本')"
  printf '%s %s\n' "$x264_repository" "$x264_commit"
}

install_x264() {
  local x264_source x264_repository x264_commit
  x264_source="${linux_x264_source:-$(resolve_x264_source)}" || return $?
  read -r x264_repository x264_commit <<< "$x264_source"
  log "$(msg "Installing x264 master at ${x264_commit}" "安装 x264 master 提交 ${x264_commit}")"

  local version_file="$X264_VERSION_FILE" installed_build="" expected_build
  expected_build="$x264_commit ${X264_CONFIGURE_OPTIONS[*]}"
  if [[ -x "$X264_PATH" && -f "$version_file" ]]; then IFS= read -r installed_build < "$version_file" || true; fi
  if [[ "$installed_build" == "$expected_build" ]] && "$X264_PATH" --version | grep -F '(libavformat ' >/dev/null; then
    log "$(msg 'The latest x264 master is already installed; skipping build.' '已安装最新 x264 master，跳过编译。')"
    return 0
  fi
  require_native_build x264

  local deps=(build-essential git pkg-config libavformat-dev libavcodec-dev libavutil-dev libswscale-dev)
  if [[ "$APT_ARCH" == amd64 ]]; then
    deps+=(nasm)
  fi
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
  local archive_url
  archive_url="$(github_archive_url "$X264_SOURCE_MIRROR" "$x264_commit")"
  local mirror_url=""
  if [[ "$x264_repository" == "$X264_SOURCE_REPOSITORY" ]]; then
    mirror_url="$archive_url"
    archive_url="${X264_SOURCE_REPOSITORY%.git}/-/archive/${x264_commit}/x264-${x264_commit}.tar.gz"
  fi

  (
    cd "$build_dir" || exit 1
    download_source_archive "x264 ${x264_commit:0:7}" "$archive_url" x264 "$mirror_url" || exit 1
    cd x264 || exit 1
    # FFmpeg 7+ exposes interlacing through AVFrame.flags.
    sed -i -e 's/h->frame->interlaced_frame/!!(h->frame->flags \& AV_FRAME_FLAG_INTERLACED)/g' \
           -e 's/h->frame->top_field_first/!!(h->frame->flags \& AV_FRAME_FLAG_TOP_FIELD_FIRST)/g' input/lavf.c || exit 1
    tmux_run "x264 configure" ./configure "${X264_CONFIGURE_OPTIONS[@]}" || exit 1
    if ! grep -Fxq '#define HAVE_LAVF 1' config.h || ! grep -Eq '^#define HAVE_OPENCL (1|\(BIT_DEPTH==8\))$' config.h; then
      die "$(msg 'x264 configuration requires libavformat input and 8-bit OpenCL support' 'x264 配置必须启用 libavformat 输入和 8-bit OpenCL 支持')"
    fi
    tmux_run "x264 make" make -j"$(nproc)" || exit 1
    install_configured_executable x264 "$X264_PATH" || exit 1
    bluray_sudo mkdir -p "$(dirname -- "$version_file")" || exit 1
    printf '%s\n' "$expected_build" | bluray_sudo tee "$version_file" >/dev/null || exit 1
  ) || die "$(msg 'x264 build/install failed' 'x264 编译/安装失败')"

  rm -rf "$build_dir"
  "$X264_PATH" --version >/dev/null 2>&1 || \
    die "$(msg 'Installed x264 verification failed' '安装后的 x264 验证失败')"
  log "$(msg 'x264 installation complete' 'x264 安装完成')"
}
# ---------------------------------------------------------------------------
# SVT-AV1 (AOMediaCodec)
# ---------------------------------------------------------------------------

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

  if [[ -n "$installed_version" ]] && dpkg --compare-versions "$installed_version" ge "$target_version" &&
      { ! "$package_build" || installed_artifact_matches "$SVT_AV1_PATH" portable; }; then
    log "$(msg "SvtAv1EncApp is current (${installed_version} >= ${target_version}), skipping build" "SvtAv1EncApp 已是当前版本（${installed_version} >= ${target_version}），跳过编译")"
    return 0
  fi
  log "$(msg "Installing SVT-AV1 ${target_version}" "正在安装 SVT-AV1 ${target_version}")"

  local deps=(build-essential cmake git python3)
  if [[ "$APT_ARCH" == amd64 ]]; then
    deps+=(nasm)
  fi
  apt_update
  apt_install "${deps[@]}" || die "$(msg 'Failed to install SVT-AV1 dependencies' 'SVT-AV1 依赖安装失败')"

  local build_options=(release static)
  if "$package_build"; then
    # Preserve runtime SIMD dispatch without targeting the package builder's CPU.
    build_options+=(--disable-native)
  else
    build_options+=(--native)
  fi
  local build_dir
  build_dir="$(mktemp -d)"

  (
    cd "$build_dir" || exit 1
    download_source_archive "SVT-AV1 ${svt_tag}" \
      "${SVT_AV1_SOURCE_REPOSITORY%.git}/-/archive/${svt_tag}/SVT-AV1-${svt_tag}.tar.gz" SVT-AV1 || exit 1
    cd SVT-AV1/Build/linux || exit 1
    tmux_run "$(msg 'SVT-AV1: build release static' 'SVT-AV1：release static 编译')" \
      bash ./build.sh "${build_options[@]}" || exit 1
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
  if "$package_build"; then
    sha256sum < "$SVT_AV1_PATH" | bluray_sudo tee "$SVT_AV1_PATH.portable.sha256" >/dev/null
  fi
  log "$(msg "SVT-AV1 installation complete (${installed_version})" "SVT-AV1 安装完成（${installed_version}）")"
}

# ---------------------------------------------------------------------------
# tsMuxer
# ---------------------------------------------------------------------------

TSMUXER_VERSION="${TSMUXER_VERSION:-}"

install_tsmuxer() {
  local repository=https://github.com/justdan96/tsMuxer
  local tsmuxer_tag tsmuxer_version installed_version
  if [[ -x "$TS_MUXER_PATH" ]] && installed_version="$("$TS_MUXER_PATH" --version 2>/dev/null)"; then
    installed_version="${installed_version#tsMuxeR version }"
    installed_version="${installed_version%% *}"
    if [[ -z "$TSMUXER_VERSION" || "${installed_version%.}" == "${TSMUXER_VERSION#[vV]}" ]]; then
      log "$(msg 'tsMuxeR already installed, skipping' '检测到 tsMuxeR 已安装，跳过')"
      return 0
    fi
  fi
  tsmuxer_tag="${TSMUXER_VERSION:-$(latest_stable_tag "$repository.git")}"
  tsmuxer_version="${tsmuxer_tag#[vV]}"
  log "$(msg "Installing tsMuxer ${tsmuxer_version}" "安装 tsMuxer ${tsmuxer_version}")"

  local deps=(git curl)
  if [[ "$APT_ARCH" == arm64 ]]; then
    require_native_build tsMuxeR
    deps+=(build-essential cmake ninja-build pkg-config zlib1g-dev libfreetype-dev)
  else
    deps+=(unzip)
  fi
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
    local executable=tsMuxeR
    if [[ "$APT_ARCH" == arm64 ]]; then
      download_source_archive "tsMuxeR ${tsmuxer_version}" \
        "$(github_archive_url "$repository" "refs/tags/$tsmuxer_tag")" source || exit 1
      # std::all_of requires its own header in this release.
      if ! grep -Fxq '#include <algorithm>' source/tsMuxer/srtStreamReader.cpp; then
        sed -i "$TSMUXER_INCLUDE_PATCH" source/tsMuxer/srtStreamReader.cpp || exit 1
      fi
      tmux_run "tsMuxeR cmake" cmake -S source -B build -G Ninja \
        "${TSMUXER_CMAKE_OPTIONS[@]}" || exit 1
      tmux_run "tsMuxeR ninja" cmake --build build --target tsmuxer --parallel "$(nproc)" || exit 1
      executable=build/tsMuxer/tsmuxer
    else
      local archive="tsMuxer-${tsmuxer_version}-linux.zip"
      tmux_run "$(msg "Download ${archive}" "下载 ${archive}")" \
        download_github_release_asset "$repository" "$tsmuxer_tag" "$archive" || exit 1
      tmux_run "$(msg 'Extract tsMuxer zip package' '解压 tsMuxer 压缩包')" unzip "$archive" || exit 1
    fi
    install_configured_executable "$executable" "$TS_MUXER_PATH" || exit 1
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
  local fdk_aac_tag fdkaac_tag target_version installed_version installed_library
  fdk_aac_tag="${FDK_AAC_VERSION:-$(latest_stable_tag "$FDK_AAC_SOURCE_REPOSITORY")}"
  fdkaac_tag="${FDKAAC_VERSION:-$(latest_stable_tag "$FDKAAC_SOURCE_REPOSITORY")}"
  target_version="${fdkaac_tag#v}"
  installed_version="$(__installed_fdkaac_version || true)"
  installed_library="$(pkg-config --modversion fdk-aac 2>/dev/null || true)"

  if [[ -n "$installed_version" && -n "$installed_library" ]] &&
      dpkg --compare-versions "$installed_version" ge "$target_version" &&
      dpkg --compare-versions "$installed_library" ge "${fdk_aac_tag#v}"; then
    log "$(msg "fdkaac is current (${installed_version} >= ${target_version}), skipping build" "fdkaac 已是当前版本（${installed_version} >= ${target_version}），跳过编译")"
    return 0
  fi
  require_native_build fdkaac
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
    download_source_archive "fdk-aac ${fdk_aac_tag}" \
      "$(github_archive_url "$FDK_AAC_SOURCE_REPOSITORY" "refs/tags/$fdk_aac_tag")" fdk-aac || exit 1
    cd fdk-aac || exit 1
    tmux_run "$(msg 'fdk-aac: autogen.sh' 'fdk-aac：autogen.sh')" ./autogen.sh || exit 1
    tmux_run "$(msg 'fdk-aac: configure' 'fdk-aac：configure')" ./configure || exit 1
    tmux_run "$(msg 'fdk-aac: make' 'fdk-aac：make')" make -j"$(nproc)" || exit 1
    install_component "$(msg 'fdk-aac: make install' 'fdk-aac：make install')" make install || exit 1
    sudo ldconfig || true
    cd "$build_dir" || exit 1
    download_source_archive "fdkaac ${fdkaac_tag}" \
      "$(github_archive_url "$FDKAAC_SOURCE_REPOSITORY" "refs/tags/$fdkaac_tag")" fdkaac || exit 1
    cd fdkaac || exit 1
    tmux_run "$(msg 'fdkaac: autoreconf -fi' 'fdkaac：autoreconf -fi')" autoreconf -fi || exit 1
    tmux_run "$(msg 'fdkaac: configure' 'fdkaac：configure')" ./configure || exit 1
    tmux_run "$(msg 'fdkaac: make' 'fdkaac：make')" make -j"$(nproc)" || exit 1
    install_component "$(msg 'fdkaac: make install' 'fdkaac：make install')" make install || exit 1
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
  latest_flac_version="${flac_tag#[vV]}"
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
      require_native_build FLAC
      log "$(msg "flac is outdated (${flac_version} < ${latest_flac_version}), removing it before rebuilding" "检测到 flac 版本过旧（${flac_version} < ${latest_flac_version}），卸载后重新编译")"
      sudo apt-get remove -y flac >/dev/null 2>&1 || true
      bluray_sudo rm -f "$flac_bin"
    else
      require_native_build FLAC
      log "$(msg 'Cannot parse installed flac version, attempting to rebuild' '无法解析已安装的 flac 版本，尝试重新编译安装')"
      sudo apt-get remove -y flac >/dev/null 2>&1 || true
      bluray_sudo rm -f "$flac_bin"
    fi
  fi
  require_native_build FLAC

  local deps=(libogg-dev libtool-bin gettext git xz-utils)
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
    download_source_archive "FLAC ${latest_flac_version}" \
      "https://downloads.xiph.org/releases/flac/flac-${latest_flac_version}.tar.xz" flac || exit 1
    cd flac || exit 1

    log "$(msg 'Configuring and building flac' '配置与编译 flac')"
    tmux_run "flac configure" ./configure --enable-static --enable-shared --enable-64-bit-words || exit 1
    tmux_run "flac make" make -j"$(nproc)" || exit 1
    install_component "flac install" make install || exit 1
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
# VapourSynth
# ---------------------------------------------------------------------------

VAPOURSYNTH_TAG="R79"
VAPOURSYNTH_PYTHON=""

select_vapoursynth_python() {
  local data_home="${XDG_DATA_HOME:-$HOME/.local/share}"
  [[ "$data_home" == /* ]] || data_home="$HOME/.local/share"
  local base="$data_home/bluraysubtitle" uv version runtime
  mkdir -p -- "$base"
  if ! "$base/uv/bin/python" -Im pip --version >/dev/null 2>&1; then
    /usr/bin/python3 -m venv "$base/uv"
  fi
  "$base/uv/bin/python" -m pip install --upgrade --only-binary=:all: uv
  uv="$base/uv/bin/uv"
  export UV_PYTHON_INSTALL_DIR="$base/interpreters" UV_PYTHON_BIN_DIR="$base/bin"
  local -a python_cache=()
  if "$package_build"; then
    export UV_CACHE_DIR="$PIP_CACHE_DIR/uv"
    python_cache=("$BLURAY_SETUP_CACHE_DIR/downloads/cpython")
  fi
  version="$(/usr/bin/python3 -B "$SETUP_ROOT/tools/install_linux_python.py" "$uv" "${python_cache[@]}")"
  runtime="$base/python-$version-$APT_ARCH"
  if [[ ! -x "$runtime/bin/python" ]]; then
    "$uv" venv --managed-python --python "$version" --seed "$runtime"
  elif ! "$runtime/bin/python" -Im pip --version >/dev/null 2>&1; then
    "$uv" pip install --python "$runtime/bin/python" --only-binary=:all: pip
  fi
  VAPOURSYNTH_PYTHON="$runtime/bin/python"
}

install_vapoursynth() {
  local package_dir sdk_dir=/usr/local/include/vapoursynth build_dir wrapper
  if ! "$VAPOURSYNTH_PYTHON" -I -c 'import vapoursynth as vs; assert vs.core.core_version.release_major == 79' >/dev/null 2>&1; then
    "$VAPOURSYNTH_PYTHON" -m pip install --disable-pip-version-check --only-binary=:all: "VapourSynth==${VAPOURSYNTH_TAG#R}"
  fi

  package_dir="$("$VAPOURSYNTH_PYTHON" -I -c 'import vapoursynth as vs; from pathlib import Path; print(Path(vs.__file__).parent)')"
  "$VAPOURSYNTH_PYTHON" -I -m vapoursynth config
  bluray_sudo install -d "$sdk_dir" /usr/local/lib/pkgconfig
  if ! cmp -s "$package_dir/include/VapourSynth4.h" "$sdk_dir/VapourSynth4.h" \
      || [[ ! -s "$sdk_dir/VapourSynth.h" || ! -s "$sdk_dir/VSHelper.h" ]]; then
    # The wheel ships API4 headers. The upstream R79 source also has the API3 headers used by legacy filters.
    build_dir="$(bluray_mktemp_dir)"
    download_source_archive "VapourSynth $VAPOURSYNTH_TAG" \
      "https://codeload.github.com/vapoursynth/vapoursynth/tar.gz/refs/tags/$VAPOURSYNTH_TAG" "$build_dir/source"
    bluray_sudo install -m 0644 "$build_dir/source/include/"*.h "$sdk_dir/"
    rm -rf -- "$build_dir"
  fi
  bluray_sudo tee /usr/local/lib/pkgconfig/vapoursynth.pc >/dev/null <<EOF
libdir=$package_dir
includedir=$sdk_dir
Name: VapourSynth
Description: VapourSynth filter SDK
Version: ${VAPOURSYNTH_TAG#R}
Cflags: -I\${includedir}
EOF
  # The system linker must not trust libraries managed by an unprivileged account.
  if [[ "$(stat -c '%u' "$package_dir")" == "0" && "$(stat -c '%u' "$(dirname "$package_dir")")" == "0" ]]; then
    case "$package_dir" in
      /usr/lib/* | /usr/local/lib/*) printf '%s\n' "$package_dir" | sudo tee /etc/ld.so.conf.d/bluraysubtitle-vapoursynth.conf >/dev/null ;;
    esac
    sudo ldconfig
  fi
  VAPOURSYNTH_VSSCRIPT="$package_dir/libvsscript.so"

  wrapper="$(mktemp)"
  {
    printf '%s\n' '#!/usr/bin/env bash' \
      'if [[ -z "${VAPOURSYNTH_EXTRA_PLUGIN_PATH+x}" && -z "${BLURAYSUB_PLUGIN_PATH:-}" ]]; then'
    printf '  export VAPOURSYNTH_EXTRA_PLUGIN_PATH=%q\n' "$PLUGIN_PATH"
    printf 'fi\nexec %q "$@"\n' "$package_dir/vspipe"
  } > "$wrapper"
  VAPOURSYNTH_EXTRA_PLUGIN_PATH="" "$package_dir/vspipe" --version | grep -Fx "Core $VAPOURSYNTH_TAG" \
    || die "$(msg 'VapourSynth R79 failed to load its configured Python' 'VapourSynth R79 未能加载配置的 Python')"
  install_configured_executable "$wrapper" "$VSPIPE_PATH"
  rm -f -- "$wrapper"
  export VSSCRIPT_PATH="$VAPOURSYNTH_VSSCRIPT"
}

# ---------------------------------------------------------------------------
# VapourSynth plugin versions
# ---------------------------------------------------------------------------

resolve_vs_plugin_releases() {
  local releases name tag source_url digest
  releases="$(cd "$SETUP_ROOT" && /usr/bin/python3 -B -m tools.vapoursynth_plugin_releases "$@")" || return $?
  while IFS=$'\t' read -r name tag source_url digest; do
    vs_plugin_tags[$name]="$tag"
    vs_plugin_sources[$name]="$source_url"
    vs_plugin_digests[$name]="$digest"
  done <<< "$releases"
}

vs_plugin_version() {
  "$VAPOURSYNTH_PYTHON" "$(dirname -- "$BLURAY_SETUP_SOURCE")/tools/vapoursynth_plugin_versions.py" \
    "$PLUGIN_PATH" "$1" "$2" "$3"
}

vs_plugin_needs_upgrade() {
  local filename="$1" target="$2" installed_version=""
  local target_version="${target#[rRvV]}"
  if [[ -f "$PLUGIN_PATH/$filename" ]]; then
    installed_version="$(vs_plugin_version read "$filename" "$target" 2>/dev/null || true)"
  fi
  if [[ -z "$installed_version" ]]; then
    log "$(msg "${filename}: version unavailable, installing ${target}" "${filename}：无法获取版本，将安装 ${target}")"
    return 0
  fi
  if [[ "$target" == commit:* ]]; then
    if [[ "$installed_version" == "$target" ]]; then
      log "$(msg "${filename}: installed revision matches ${target}" "${filename}：已安装提交与 ${target} 一致")"
      return 1
    fi
  elif [[ "$installed_version" != commit:* ]] && dpkg --compare-versions "$installed_version" ge "${target_version//_/.}"; then
    log "$(msg "${filename}: version satisfied (${installed_version} >= ${target})" "${filename}：版本满足要求（${installed_version} >= ${target}）")"
    return 1
  fi
  log "$(msg "${filename}: upgrading ${installed_version} to ${target}" "${filename}：将从 ${installed_version} 升级到 ${target}")"
  return 0
}

# ---------------------------------------------------------------------------
# descale
# ---------------------------------------------------------------------------

descale_supports_blur() {
  "$VAPOURSYNTH_PYTHON" - "$1" "$2" <<'PY'
import filecmp
from pathlib import Path
import sys

import vapoursynth as vs

plugin_path = Path(sys.argv[1])
if not plugin_path.is_file():
    raise SystemExit(1)
core = vs.core
if not hasattr(core, "descale"):
    core.std.LoadPlugin(path=str(plugin_path))
plugin = core.descale
if plugin.version.major < int(sys.argv[2]):
    raise SystemExit(1)
if not filecmp.cmp(plugin_path, plugin.plugin_path, shallow=False):
    raise SystemExit(1)
for name in ("Debilinear", "Debicubic", "Delanczos", "Despline16", "Despline36", "Despline64", "Descale"):
    if "blur:float:opt;" not in getattr(plugin, name).signature:
        raise SystemExit(1)
clip = core.std.BlankClip(width=64, height=48, format=vs.GRAYS, length=1)
plugin.Descale(clip, 48, 32, kernel="bilinear", blur=1.0).get_frame(0)
PY
}

install_descale() {
  log "$(msg 'Installing VapourSynth descale plugin' '安装 VapourSynth descale 插件')"

  local plugins_dir="$PLUGIN_PATH"
  ensure_configured_directory "$plugins_dir"
  local descale_tag="${vs_plugin_tags[descale]}" descale_version
  descale_version="${descale_tag#r}"
  descale_version="${descale_version%%.*}"
  if ! vs_plugin_needs_upgrade "libdescale.so" "$descale_tag" \
      && descale_supports_blur "$plugins_dir/libdescale.so" "$descale_version" >/dev/null 2>&1; then
    log "$(msg "descale ${descale_tag} with blur support is installed, skipping" "已安装支持 blur 的 descale ${descale_tag}，跳过")"
    return 0
  fi
  require_native_build descale

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
    download_source_archive "descale ${descale_tag}" \
      "${vs_plugin_sources[descale]}" vapoursynth-descale || exit 1
    cd vapoursynth-descale || exit 1
    # The pointee reference remains valid if GCC evaluates data.release() first.
    sed -i '/vsapi->createVideoFilter/s/data->/d./g' src/vsplugin.cc || exit 1
    tmux_run "descale meson setup" meson setup build --buildtype=release || exit 1
    tmux_run "descale ninja" ninja -C build || exit 1
    bluray_sudo install -D -m 0755 build/libdescale.so "$plugins_dir/libdescale.so" || exit 1
  ) || die "$(msg 'descale build/install failed' 'descale 编译/安装失败')"

  descale_supports_blur "$plugins_dir/libdescale.so" "$descale_version" \
    || die "$(msg 'Installed descale failed the blur runtime check' '安装后的 descale 未通过 blur 运行检查')"
  vs_plugin_version record "libdescale.so" "$descale_tag" \
    || die "$(msg 'Failed to record the installed descale version' '无法记录已安装 descale 的版本')"

  rm -rf "$build_dir"
  log "$(msg "descale ${descale_tag} installation complete with blur support (${plugins_dir})" "支持 blur 的 descale ${descale_tag} 安装完成（${plugins_dir}）")"
}

# ---------------------------------------------------------------------------
# 7-Zip CLI (ISO playlists and VapourSynth portable archives)
# ---------------------------------------------------------------------------

ensure_modern_7zip_cli() {
  local release version asset_version asset_arch=x64 installed_version=""
  release="${SEVENZIP_VERSION:-$(latest_stable_tag https://github.com/ip7z/7zip.git '^[0-9]+[.][0-9]+$')}"
  version="${release#v}"
  asset_version="${version//./}"
  if [[ "$APT_ARCH" == arm64 ]]; then
    asset_arch=arm64
  fi
  BLURAY_7ZZ_BIN="$SEVEN_ZIP_PATH"
  if [[ -x "$SEVEN_ZIP_PATH" ]]; then
    installed_version="$("$SEVEN_ZIP_PATH" i | sed -nE 's/^7-Zip[^0-9]*([0-9]+[.][0-9]+).*/\1/p' | head -n 1)" \
      || installed_version=""
  fi
  if [[ "$installed_version" == "$version" ]]; then
    return 0
  fi

  local build_dir
  build_dir="$(bluray_mktemp_dir)"
  if ! command -v xz >/dev/null 2>&1; then
    apt_install xz-utils
  fi
  log "$(msg "Installing 7-Zip ${version} at ${SEVEN_ZIP_PATH}" "正在将 7-Zip ${version} 安装到 ${SEVEN_ZIP_PATH}")"
  download_github_release_asset ip7z/7zip "$release" "7z${asset_version}-linux-${asset_arch}.tar.xz" "$build_dir/7zip.tar.xz" \
    || die "$(msg 'Failed to download official 7-Zip CLI' '下载官方 7-Zip 命令行程序失败')"
  tar -xJf "$build_dir/7zip.tar.xz" -C "$build_dir" \
    || die "$(msg 'Failed to extract official 7-Zip CLI' '解压官方 7-Zip 命令行程序失败')"
  install_configured_executable "$build_dir/7zz" "$SEVEN_ZIP_PATH"
  "$SEVEN_ZIP_PATH" i >/dev/null
  rm -rf "$build_dir"
}

# ---------------------------------------------------------------------------
# VapourSynthScripts
# ---------------------------------------------------------------------------

install_vapoursynth_scripts() {
  local scripts_dir
  scripts_dir="$("$VAPOURSYNTH_PYTHON" -c 'import sysconfig; print(sysconfig.get_path("purelib"))')"
  "$VAPOURSYNTH_PYTHON" "$SETUP_ROOT/tools/install_vapoursynth_scripts.py" --destination "$scripts_dir"
}

# ---------------------------------------------------------------------------
# VapourSynth Editor (vsedit)
# ---------------------------------------------------------------------------

write_vsedit_launcher() {
  if "$package_build"; then return; fi
  local wrapper
  wrapper="$(mktemp)"
  printf '#!/usr/bin/env bash\nexport VSSCRIPT_PATH=%q\nexport VAPOURSYNTH_EXTRA_PLUGIN_PATH=%q\nexec %q "$@"\n' \
    "$VAPOURSYNTH_VSSCRIPT" "$PLUGIN_PATH" "$VSEDIT_BINARY_PATH" > "$wrapper"
  install_configured_executable "$wrapper" "$VSEDIT_PATH"
  rm -f -- "$wrapper"
}

install_vapoursynth_editor() {
  local vsedit_tag target_version installed_tag=""
  vsedit_tag="${VSEDIT_TAG:-$(latest_stable_tag "$VSEDIT_SOURCE_REPOSITORY" '^[rR][0-9]+-mod-[0-9]+([.][0-9]+)*$')}"
  target_version="${vsedit_tag#[rR]}"
  if [[ -x "$VSEDIT_BINARY_PATH" ]]; then
    local installed_output
    installed_output="$(LD_LIBRARY_PATH="${QT66_PREFIX:+$QT66_PREFIX/lib64}" "$VSEDIT_BINARY_PATH" --version 2>&1 || true)"
    installed_tag="$(sed -nE 's/^VapourSynth Editor ([rR][0-9]+-mod-[0-9]+([.][0-9]+)*).*$/\1/p' <<<"$installed_output")"
    if [[ -n "$installed_tag" ]] && dpkg --compare-versions "${installed_tag#[rR]}" ge "$target_version"; then
      log "$(msg "vsedit is current (${installed_tag} >= ${vsedit_tag}), skipping build" "vsedit 已是当前版本（${installed_tag} >= ${vsedit_tag}），跳过编译")"
      write_vsedit_launcher
      return 0
    fi
  fi
  require_native_build VSEdit
  log "$(msg "Installing VapourSynth Editor ${vsedit_tag} (build from source)" "安装 VapourSynth Editor ${vsedit_tag}（从源码编译并安装）")"

  local -a deps=(build-essential libgl-dev wget tar)
  if "$package_build"; then
    deps+=(libglx-dev libopengl-dev)
  else
    deps+=(qt6-base-dev qt6-base-dev-tools qt6-5compat-dev qt6-websockets-dev qt6-declarative-dev)
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

    tmux_run "$(msg "Download vsedit ${vsedit_tag}" "下载 vsedit ${vsedit_tag}")" \
      download_url "$(github_archive_url "$VSEDIT_SOURCE_REPOSITORY" "refs/tags/$vsedit_tag")" vsedit.tar.gz || exit 1

    log "$(msg 'Extracting vsedit source tarball' '解压 vsedit 源码包')"
    tmux_run "$(msg 'Extract vsedit source' '解压 vsedit 源码包')" tar -zxvf vsedit.tar.gz --strip-components=1 || exit 1
    sudo ldconfig

    if ! "$package_build" && [[ -f "resources/vsedit.png" ]]; then
      sudo mkdir -p /usr/local/share/icons/hicolor/256x256/apps
      sudo cp -f "resources/vsedit.png" /usr/local/share/icons/hicolor/256x256/apps/vsedit.png || exit 1
    fi
    if ! "$package_build" && [[ -f "resources/vsedit.svg" ]]; then
      sudo mkdir -p /usr/local/share/icons/hicolor/scalable/apps
      sudo cp -f "resources/vsedit.svg" /usr/local/share/icons/hicolor/scalable/apps/vsedit.svg || exit 1
    fi

    cd pro || exit 1

    export CPLUS_INCLUDE_PATH=/usr/local/include/vapoursynth
    export LIBRARY_PATH=/usr/local/lib
    export LD_LIBRARY_PATH=/usr/local/lib:/usr/lib:/lib

    log "$(msg 'Configuring and building vsedit (qmake6)' '配置并编译 vsedit (qmake6)')"
    local project=pro.pro
    if "$package_build"; then
      cd vsedit || exit 1
      project=vsedit.pro
      export LD_LIBRARY_PATH="$QT66_PREFIX/lib64:$LD_LIBRARY_PATH"
      export LIBRARY_PATH="$QT66_PREFIX/lib64:$LIBRARY_PATH"
    fi
    "${QMAKE6:-qmake6}" "$project" CONFIG+=release 2>&1 | sed '/^Info: creating stash file /d' || exit 1
    tmux_run "vsedit make" bash -lc "make -j\"$(nproc)\" || make -j1" || exit 1

    log "$(msg 'Installing the compiled vsedit executable' '安装编译生成的 vsedit 可执行文件')"
    local bin_path
    # The upstream qmake project names its non-x86_64 release target vsedit-32bit.
    bin_path="$(find "$build_dir/vsedit_build/build" -type f -executable \
      \( -name vsedit -o -name vsedit-32bit \) -print -quit)" || exit 1

    if [[ -z "$bin_path" ]]; then
      die "$(msg 'Compiled vsedit executable not found' '未找到编译生成的 vsedit 执行文件')"
    fi

    # Copy the real binary as vsedit-bin
    if "$package_build"; then
      install -m 0755 "$bin_path" "$VSEDIT_BINARY_PATH" || exit 1
    else
      install_configured_executable "$bin_path" "$VSEDIT_BINARY_PATH" || exit 1
    fi

  ) || die "$(msg "vsedit build/install failed. Build files were kept in ${build_dir}" "vsedit 编译/安装失败。构建文件保留在 ${build_dir}")"

  write_vsedit_launcher
  rm -rf "$build_dir"
  log "$(msg 'VapourSynth Editor (vsedit) installation complete' 'vapoursynth-editor (vsedit) 安装完成')"
}

# ---------------------------------------------------------------------------
# VapourSynth plugins
# ---------------------------------------------------------------------------

install_vs_lsmash_works() (
  local build_dir="$1" plugins_dir="$2" lsmash_version="$3" source_url="$4" avcodec_major="$5"
  cd "$build_dir" || exit 1
  local lsmash_plugin="$plugins_dir/libvslsmashsource.so"
  local lsmash_linker_report=""
  local lsmash_dependencies_broken="false"
  if [[ -f "$lsmash_plugin" ]] && command -v ldd >/dev/null 2>&1; then
    lsmash_linker_report="$(LC_ALL=C ldd -r "$lsmash_plugin" 2>&1 || true)"
  fi
  if [[ "$lsmash_linker_report" == *"undefined symbol:"* || "$lsmash_linker_report" == *"not found"* ]]; then
    log "$(msg 'Existing L-SMASH-Works plugin has unresolved symbols; rebuilding it' '现有 L-SMASH-Works 插件包含未解析符号，将重新编译')"
    lsmash_dependencies_broken="true"
  fi

  if [[ "$lsmash_dependencies_broken" == "true" ]] \
      || vs_plugin_needs_upgrade "libvslsmashsource.so" "$lsmash_version"; then
    require_native_build "L-SMASH-Works"
    log "$(msg 'Building L-SMASH-Works (VapourSynth)' '编译 L-SMASH-Works (VapourSynth)')"
    download_source_archive "L-SMASH-Works $lsmash_version" "$source_url" L-SMASH-Works || exit 1
    cd L-SMASH-Works/VapourSynth || exit 1

    /usr/bin/python3 -B "$SETUP_ROOT/tools/lsmash_ffmpeg_compat.py" .. "$avcodec_major" || exit 1
    rm -rf build
    tmux_run "L-SMASH-Works meson setup" meson setup build || exit 1
    tmux_run "L-SMASH-Works ninja" ninja -C build || exit 1
    local out
    out="$(find "$PWD" -maxdepth 3 -name "libvslsmashsource.so" -type f | head -n 1)"
    [[ -n "${out:-}" ]] || exit 1
    lsmash_linker_report="$(LC_ALL=C ldd -r "$out" 2>&1 || true)"
    if [[ "$lsmash_linker_report" == *"undefined symbol:"* || "$lsmash_linker_report" == *"not found"* ]]; then
      log "$(msg 'Rebuilt L-SMASH-Works plugin still has unresolved dependencies' '重编后的 L-SMASH-Works 插件仍包含未解析依赖')"
      exit 1
    fi
    install -m 0755 "$out" "$lsmash_plugin" || exit 1
    vs_plugin_version record "libvslsmashsource.so" "$lsmash_version" || exit 1
  else
    log "$(msg 'L-SMASH-Works version is current, skipping' 'L-SMASH-Works 版本已满足要求，跳过')"
  fi
)

install_vs_eedi3m() (
  local build_dir="$1" plugins_dir="$2" tag="${vs_plugin_tags[eedi3m]}"
  cd "$build_dir" || exit 1
  if vs_plugin_needs_upgrade "eedi3m.so" "$tag"; then
    require_native_build "EEDI3m"
    log "$(msg "Building VapourSynth-EEDI3 ($tag)" "编译 VapourSynth-EEDI3 ($tag)")"
    download_source_archive "eedi3m $tag" "${vs_plugin_sources[eedi3m]}" eedi3m || exit 1
    cd eedi3m || exit 1
    log "$(msg 'Fixing EEDI3 std::max_align_t compilation compatibility issue' '修复 EEDI3 的 std::max_align_t 编译兼容性问题')"
    find . -type f -name "EEDI3.cpp" -exec sed -i 's/std::max_align_t/max_align_t/g' {} +
    if [[ "$APT_ARCH" == arm64 ]]; then
      sed -i '/^#include <algorithm>$/a #include <cmath>' EEDI3/EEDI3.h || exit 1
    fi
    tmux_run "EEDI3 meson setup" meson setup build --native-file "$vapoursynth_meson_file" || exit 1
    tmux_run "EEDI3 ninja" ninja -C build || exit 1
    install -m 0755 build/eedi3m.so "$plugins_dir/eedi3m.so" || exit 1
    vs_plugin_version record "eedi3m.so" "$tag" || exit 1
  else
    log "$(msg 'eedi3m.so version is current, skipping' 'eedi3m.so 版本已满足要求，跳过')"
  fi
)

install_vs_znedi3() (
  local build_dir="$1" plugins_dir="$2" tag="${vs_plugin_tags[znedi3]}"
  cd "$build_dir" || exit 1
  local znedi3_licenses="$plugins_dir/licenses/znedi3"
  local -a znedi3_make_args=()
  if [[ "$APT_ARCH" == amd64 ]]; then
    znedi3_make_args=(X86=1 X86_AVX512=1)
  fi
  if [[ ! -s "$plugins_dir/nnedi3_weights.bin" || ! -s "$znedi3_licenses/gpl2.txt" ]] ||
      vs_plugin_needs_upgrade "znedi3.so" "$tag"; then
    require_native_build "ZNEDI3"
    log "$(msg "Building ZNEDI3 $tag" "编译 ZNEDI3 $tag")"
    tmux_run "$(msg "Download ZNEDI3 $tag source" "下载 ZNEDI3 $tag 源码")" download_url \
      "${vs_plugin_sources[znedi3]}" znedi3.tar.gz || exit 1
    printf '%s  %s\n' "${vs_plugin_digests[znedi3]}" znedi3.tar.gz | sha256sum -c - || exit 1
    mkdir -p znedi3 || exit 1
    tar -xf znedi3.tar.gz --strip-components=1 -C znedi3 || exit 1
    tmux_run "ZNEDI3 make" make -C znedi3 -j"$(nproc)" "${znedi3_make_args[@]}" || exit 1
    install -m 0644 znedi3/nnedi3_weights.bin "$plugins_dir/nnedi3_weights.bin" || exit 1
    install -D -m 0644 znedi3/graphengine/COPYING "$znedi3_licenses/graphengine/COPYING" || exit 1
    install -D -m 0644 znedi3/vsxx/COPYING.LGPLv2.1 "$znedi3_licenses/vsxx/COPYING.LGPLv2.1" || exit 1
    install -D -m 0644 znedi3/gpl2.txt "$znedi3_licenses/gpl2.txt" || exit 1
    install -m 0755 znedi3/vsznedi3.so "$plugins_dir/znedi3.so" || exit 1
    vs_plugin_version record "znedi3.so" "$tag" || exit 1
  fi
)

install_vs_addgrain() (
  local build_dir="$1" plugins_dir="$2" tag="${vs_plugin_tags[addgrain]}"
  cd "$build_dir" || exit 1
  if vs_plugin_needs_upgrade "libaddgrain.so" "$tag"; then
    require_native_build "AddGrain"
    log "$(msg "Building VapourSynth-AddGrain ($tag)" "编译 VapourSynth-AddGrain ($tag)")"
    download_source_archive "addgrain $tag" "${vs_plugin_sources[addgrain]}" addgrain || exit 1
    cd addgrain || exit 1
    tmux_run "AddGrain meson setup" meson setup build || exit 1
    tmux_run "AddGrain ninja" ninja -C build || exit 1
    install -m 0755 build/libaddgrain.so "$plugins_dir/libaddgrain.so" || exit 1
    vs_plugin_version record "libaddgrain.so" "$tag" || exit 1
  else
    log "$(msg 'libaddgrain.so version is current, skipping' 'libaddgrain.so 版本已满足要求，跳过')"
  fi
)

install_vs_assrender() (
  local build_dir="$1" plugins_dir="$2" tag="${vs_plugin_tags[assrender]}"
  cd "$build_dir" || exit 1
  if vs_plugin_needs_upgrade "libassrender.so" "$tag"; then
    require_native_build "ASSRender"
    log "$(msg "Building assrender ($tag)" "编译 assrender ($tag)")"
    download_source_archive "assrender $tag" "${vs_plugin_sources[assrender]}" assrender || exit 1
    cd assrender || exit 1
    rm -rf build
    tmux_run "assrender cmake" cmake -S . -B build -DCMAKE_BUILD_TYPE=Release || exit 1
    tmux_run "assrender build" cmake --build build --parallel "$(nproc)" || exit 1
    local out
    out="$(find "$PWD/build" -name "libassrender.so" -type f | head -n 1)"
    [[ -n "${out:-}" ]] || exit 1
    install -m 0755 "$out" "$plugins_dir/libassrender.so" || exit 1
    vs_plugin_version record "libassrender.so" "$tag" || exit 1
  else
    log "$(msg 'libassrender.so version is current, skipping' 'libassrender.so 版本已满足要求，跳过')"
  fi
)

install_vs_bilateral() (
  local build_dir="$1" plugins_dir="$2" tag="${vs_plugin_tags[bilateral]}"
  cd "$build_dir" || exit 1
  if vs_plugin_needs_upgrade "libbilateral.so" "$tag"; then
    require_native_build "Bilateral"
    log "$(msg "Building VapourSynth-Bilateral ($tag)" "编译 VapourSynth-Bilateral ($tag)")"
    download_source_archive "bilateral $tag" "${vs_plugin_sources[bilateral]}" bilateral || exit 1
    cd bilateral || exit 1
    chmod +x configure || exit 1
    local -a bilateral_args=()
    if [[ "$APT_ARCH" == arm64 ]]; then
      bilateral_args+=(--target=arch=armv8-a)
    fi
    tmux_run "Bilateral configure" ./configure "${bilateral_args[@]}" || exit 1
    tmux_run "Bilateral make" make -j"$(nproc)" || exit 1
    local out
    out="$(find "$PWD" -maxdepth 3 -name "libbilateral.so" -type f | head -n 1)"
    [[ -n "${out:-}" ]] || exit 1
    install -m 0755 "$out" "$plugins_dir/libbilateral.so" || exit 1
    vs_plugin_version record "libbilateral.so" "$tag" || exit 1
  else
    log "$(msg 'libbilateral.so version is current, skipping' 'libbilateral.so 版本已满足要求，跳过')"
  fi
)

install_vs_dfttest() (
  local build_dir="$1" plugins_dir="$2" tag="${vs_plugin_tags[dfttest]}"
  cd "$build_dir" || exit 1
  local dfttest_plugin="$plugins_dir/libdfttest.so"
  local dfttest_linker_report=""
  local dfttest_dependencies_broken="false"
  if [[ -f "$dfttest_plugin" ]] && command -v ldd >/dev/null 2>&1; then
    dfttest_linker_report="$(LC_ALL=C ldd -r "$dfttest_plugin" 2>&1 || true)"
    if [[ "$dfttest_linker_report" == *"undefined symbol:"* || "$dfttest_linker_report" == *"not found"* ]]; then
      log "$(msg 'Existing DFTTest plugin has unresolved symbols; rebuilding it' '现有 DFTTest 插件包含未解析符号，将重新编译')"
      dfttest_dependencies_broken="true"
    fi
  fi
  if [[ "$dfttest_dependencies_broken" == "true" ]] \
      || vs_plugin_needs_upgrade "libdfttest.so" "$tag"; then
    require_native_build "DFTTest"
    log "$(msg "Building VapourSynth-DFTTest ($tag)" "编译 VapourSynth-DFTTest ($tag)")"
    download_source_archive "dfttest $tag" "${vs_plugin_sources[dfttest]}" dfttest || exit 1
    cd dfttest || exit 1
    # fftw >= 3.3.9 exports make_planner_thread_safe only from libfftw3f_threads, which fftw3f.pc does not link.
    tmux_run "DFTTest meson setup" meson setup build "${DFTTEST_MESON_OPTIONS[@]}" || exit 1
    tmux_run "DFTTest ninja" ninja -C build || exit 1
    dfttest_linker_report="$(LC_ALL=C ldd -r build/libdfttest.so 2>&1 || true)"
    if [[ "$dfttest_linker_report" == *"undefined symbol:"* || "$dfttest_linker_report" == *"not found"* ]]; then
      log "$(msg 'Rebuilt DFTTest plugin still has unresolved dependencies' '重编后的 DFTTest 插件仍包含未解析依赖')"
      exit 1
    fi
    install -m 0755 build/libdfttest.so "$plugins_dir/libdfttest.so" || exit 1
    vs_plugin_version record "libdfttest.so" "$tag" || exit 1
  else
    log "$(msg 'libdfttest.so version is current, skipping' 'libdfttest.so 版本已满足要求，跳过')"
  fi
)

install_vs_eedi2() (
  local build_dir="$1" plugins_dir="$2" tag="${vs_plugin_tags[eedi2]}"
  cd "$build_dir" || exit 1
  if vs_plugin_needs_upgrade "libeedi2.so" "$tag"; then
    require_native_build "EEDI2"
    log "$(msg "Building VapourSynth-EEDI2 ($tag)" "编译 VapourSynth-EEDI2 ($tag)")"
    download_source_archive "eedi2 $tag" "${vs_plugin_sources[eedi2]}" eedi2 || exit 1
    cd eedi2 || exit 1
    tmux_run "EEDI2 meson setup" meson setup build || exit 1
    tmux_run "EEDI2 ninja" ninja -C build || exit 1
    install -m 0755 build/libeedi2.so "$plugins_dir/libeedi2.so" || exit 1
    vs_plugin_version record "libeedi2.so" "$tag" || exit 1
  else
    log "$(msg 'libeedi2.so version is current, skipping' 'libeedi2.so 版本已满足要求，跳过')"
  fi
)

install_vs_fmtconv() (
  local build_dir="$1" plugins_dir="$2" fmtconv_tag="${vs_plugin_tags[fmtconv]}"
  cd "$build_dir" || exit 1
  if vs_plugin_needs_upgrade "libfmtconv.so" "$fmtconv_tag"; then
    require_native_build "fmtconv"
    log "$(msg "Building fmtconv ($fmtconv_tag)" "编译 fmtconv ($fmtconv_tag)")"
    download_source_archive "fmtconv $fmtconv_tag" "${vs_plugin_sources[fmtconv]}" fmtconv || exit 1
    cd fmtconv/build/unix || exit 1
    tmux_run "fmtconv autogen" ./autogen.sh || exit 1
    tmux_run "fmtconv configure" ./configure || exit 1
    tmux_run "fmtconv make" make -j"$(nproc)" || exit 1
    local out
    out="$(find "$PWD/.libs" -maxdepth 1 -name "libfmtconv.so" -type f | head -n 1)"
    [[ -n "${out:-}" ]] || exit 1
    install -m 0755 "$out" "$plugins_dir/libfmtconv.so" || exit 1
    vs_plugin_version record "libfmtconv.so" "$fmtconv_tag" || exit 1
  else
    log "$(msg 'libfmtconv.so version is current, skipping' 'libfmtconv.so 版本已满足要求，跳过')"
  fi
)

install_vs_legacy_filters() (
  local build_dir="$1" plugins_dir="$2" tag="${vs_plugin_tags[legacy-filters]}"
  cd "$build_dir" || exit 1
  local -a misc_flags=()
  if [[ "$APT_ARCH" == amd64 ]]; then
    misc_flags=(-DVS_TARGET_CPU_X86)
  fi
  if vs_plugin_needs_upgrade "libeedi3.so" "$tag" || vs_plugin_needs_upgrade "libmiscfilters.so" "$tag"; then
    require_native_build "VapourSynth Classic filters"
    download_source_archive "legacy VapourSynth filters $tag" \
      "${vs_plugin_sources[legacy-filters]}" "$build_dir/legacy-filters" || exit 1
    cd "$build_dir/legacy-filters" || exit 1
    cc -shared -fPIC -O3 -Iinclude src/filters/eedi3/eedi3.c -lm -o "$plugins_dir/libeedi3.so" || exit 1
    c++ -shared -fPIC -O3 "${misc_flags[@]}" -Iinclude -I. src/filters/misc/miscfilters.cpp -o "$plugins_dir/libmiscfilters.so" || exit 1
    vs_plugin_version record "libeedi3.so" "$tag" || exit 1
    vs_plugin_version record "libmiscfilters.so" "$tag" || exit 1
  fi
)

install_vs_vivtc() (
  local build_dir="$1" plugins_dir="$2" tag="${vs_plugin_tags[vivtc]}"
  cd "$build_dir" || exit 1
  if vs_plugin_needs_upgrade "libvivtc.so" "$tag"; then
    require_native_build "VIVTC"
    download_source_archive "VIVTC $tag" \
      "${vs_plugin_sources[vivtc]}" "$build_dir/vivtc" || exit 1
    cc -shared -fPIC -O3 -I/usr/local/include/vapoursynth "$build_dir/vivtc/src/vivtc.c" -lm -o "$plugins_dir/libvivtc.so" || exit 1
    vs_plugin_version record "libvivtc.so" "$tag" || exit 1
  fi
)

install_vs_removegrain() (
  local build_dir="$1" plugins_dir="$2" tag="${vs_plugin_tags[removegrain]}"
  cd "$build_dir" || exit 1
  if vs_plugin_needs_upgrade "libremovegrain.so" "$tag"; then
    require_native_build "RemoveGrain"
    log "$(msg "Building vs-removegrain ($tag)" "编译 vs-removegrain ($tag)")"
    download_source_archive "removegrain $tag" "${vs_plugin_sources[removegrain]}" removegrain || exit 1
    cd removegrain/src || exit 1
    tmux_run "$(msg "Build vs-removegrain $tag" "编译 vs-removegrain $tag")" g++ -shared -fPIC -O3 -Wall \
      $(pkg-config --cflags vapoursynth) \
      clense.cpp removegrainvs.cpp repairvs.cpp shared.cpp verticalcleaner.cpp \
      -o libremovegrain.so || exit 1
    install -m 0755 libremovegrain.so "$plugins_dir/libremovegrain.so" || exit 1
    vs_plugin_version record "libremovegrain.so" "$tag" || exit 1
  else
    log "$(msg 'libremovegrain.so version is current, skipping' 'libremovegrain.so 版本已满足要求，跳过')"
  fi
)

install_vs_sangnom() (
  local build_dir="$1" plugins_dir="$2" sse2neon_version="$3" tag="${vs_plugin_tags[sangnom]}"
  local plugin="$plugins_dir/libsangnommod.so"
  cd "$build_dir" || exit 1
  if { [[ "$APT_ARCH" == arm64 ]] && ! installed_artifact_matches "$plugin" sse2neon "$sse2neon_version"; } ||
      vs_plugin_needs_upgrade "libsangnommod.so" "$tag"; then
    require_native_build "SangNomMod"
    log "$(msg "Building VapourSynth-SangNomMod ($tag)" "编译 VapourSynth-SangNomMod ($tag)")"
    download_source_archive "sangnom $tag" "${vs_plugin_sources[sangnom]}" sangnom || exit 1
    cd sangnom || exit 1
    local -a sangnom_args=()
    if [[ "$APT_ARCH" == arm64 ]]; then
      download_source_archive sse2neon "https://codeload.github.com/DLTcollab/sse2neon/tar.gz/refs/tags/v$sse2neon_version" "$build_dir/sse2neon" || exit 1
      sed -i "$SANGNOM_SSE2NEON_PATCH" src/sangnom.cpp || exit 1
      sangnom_args+=(--target=arch=armv8-a "--extra-cxxflags=-I$build_dir/sse2neon")
    fi
    tmux_run "SangNomMod configure" ./configure "${sangnom_args[@]}" || exit 1
    tmux_run "SangNomMod make" make -j"$(nproc)" || exit 1
    local out
    out="$(find "$PWD" -maxdepth 3 -name "libsangnommod.so" -type f | head -n 1)"
    [[ -n "${out:-}" ]] || exit 1
    install -m 0755 "$out" "$plugin" || exit 1
    vs_plugin_version record "libsangnommod.so" "$tag" || exit 1
    if [[ "$APT_ARCH" == arm64 ]]; then
      artifact_stamp "$plugin" "$sse2neon_version" > "$plugin.sse2neon.sha256" || exit 1
    fi
  else
    log "$(msg 'libsangnommod.so version is current, skipping' 'libsangnommod.so 版本已满足要求，跳过')"
  fi
)

vs_placebo_links_full_runtime() {
  local plugin="$1" libplacebo="$2" loaded
  # A plugin from an older installation can load a different libplacebo SONAME.
  [[ -f "$plugin" ]] || return 1
  loaded="$(LC_ALL=C ldd "$plugin" | awk '$1 ~ /^libplacebo[.]so[.]/ && $2 == "=>" { print $3 }')" || return 1
  [[ -n "$loaded" && "$loaded" -ef "$libplacebo" ]] &&
    LC_ALL=C readelf -d "$plugin" | grep -F '[libdovi.so.' >/dev/null
}

install_vs_placebo() (
  local build_dir="$1" plugins_dir="$2" tag="${vs_plugin_tags[placebo]}"
  cd "$build_dir" || exit 1
  export PKG_CONFIG_PATH="/usr/local/lib/pkgconfig:/usr/local/lib/$LINUX_MULTIARCH/pkgconfig:/usr/local/share/pkgconfig:$HOME/.local/lib/$LINUX_MULTIARCH/pkgconfig:${PKG_CONFIG_PATH:-}"
  if ! pkg-config --atleast-version=6.338.0 libplacebo || [[ "$(pkg-config --variable=pl_has_vulkan libplacebo)" != 1 ]]; then
    die "$(msg 'vs-placebo requires libplacebo 6.338.0 or later with Vulkan enabled' 'vs-placebo 需要启用 Vulkan 的 libplacebo 6.338.0 或更高版本')"
  fi
  local libplacebo
  libplacebo="$(pkg-config --variable=libdir libplacebo)/libplacebo.so"
  if ! vs_placebo_links_full_runtime "$plugins_dir/libvs_placebo.so" "$libplacebo" || vs_plugin_needs_upgrade "libvs_placebo.so" "$tag"; then
    require_native_build "vs-placebo"
    if ! has_libdovi_development; then install_libdovi || exit 1; fi
    log "$(msg "Building vs-placebo ($tag)" "编译 vs-placebo ($tag)")"
    download_source_archive "placebo $tag" "${vs_plugin_sources[placebo]}" placebo || exit 1
    cd placebo || exit 1
    export C_INCLUDE_PATH="$HOME/.local/include:${C_INCLUDE_PATH:-}"
    export LIBRARY_PATH="$HOME/.local/lib/$LINUX_MULTIARCH:${LIBRARY_PATH:-}"
    export LD_LIBRARY_PATH="$HOME/.local/lib/$LINUX_MULTIARCH:${LD_LIBRARY_PATH:-}"
    rm -rf build
    tmux_run "vs-placebo meson setup" meson setup build --native-file "$vapoursynth_meson_file" || exit 1
    tmux_run "vs-placebo ninja" ninja -C build || exit 1
    local out
    out="$(find "$PWD/build" -maxdepth 2 -name "libvs_placebo.so" -type f | head -n 1)"
    [[ -n "${out:-}" ]] || exit 1
    vs_placebo_links_full_runtime "$out" "$libplacebo" \
      || die "$(msg 'vs-placebo must link to the selected Vulkan-enabled libplacebo and libdovi' 'vs-placebo 必须链接所选的 Vulkan 版 libplacebo 和 libdovi')"
    install -m 0755 "$out" "$plugins_dir/libvs_placebo.so" || exit 1
    vs_plugin_version record "libvs_placebo.so" "$tag" || exit 1
  else
    log "$(msg 'libvs_placebo.so version is current, skipping' 'libvs_placebo.so 版本已满足要求，跳过')"
  fi
)

ispc_binary() {
  if "$package_build" || [[ -x /usr/local/bin/ispc ]]; then
    printf '%s\n' /usr/local/bin/ispc
  else
    command -v ispc
  fi
}

install_vs_ispc() (
  local build_dir="$1" required_ispc_version="$2"
  cd "$build_dir" || exit 1
  local archive_dir="ispc-v${required_ispc_version}-linux"
  if [[ "$APT_ARCH" == arm64 ]]; then
    archive_dir+=".aarch64"
  fi
  local executable current_ispc_version="" comparison=ge
  if "$package_build"; then comparison=eq; fi
  if executable="$(ispc_binary)" && [[ -x "$executable" ]]; then
    current_ispc_version="$("$executable" --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -n 1 || true)"
  fi
  if [[ -z "$current_ispc_version" ]] || ! dpkg --compare-versions "$current_ispc_version" "$comparison" "$required_ispc_version"; then
    require_native_build ISPC
    tmux_run "$(msg "Download ISPC $required_ispc_version" "下载 ISPC $required_ispc_version")" \
      download_github_release_asset ispc/ispc "v$required_ispc_version" "$archive_dir.tar.gz" || exit 1
    tmux_run "$(msg "Extract ISPC $required_ispc_version" "解压 ISPC $required_ispc_version")" tar -xf "$archive_dir.tar.gz" || exit 1
    sudo install -m 0755 "$archive_dir/bin/ispc" /usr/local/bin/ispc || exit 1
  else
    log "$(msg "ispc version satisfied (${current_ispc_version} >= ${required_ispc_version}), skipping" "ispc 版本满足要求（${current_ispc_version} >= ${required_ispc_version}），跳过安装")"
  fi
)

install_vs_nlm_ispc() (
  local build_dir="$1" plugins_dir="$2" profile="$3" compiler="$4" compiler_id="$5" tag="${vs_plugin_tags[nlm_ispc]}"
  cd "$build_dir" || exit 1
  local nlm_plugin="$plugins_dir/libvsnlm_ispc.so"
  # The x64 build dispatches between the baseline and AVX2 kernels.
  local -a ispc_options=('-DCMAKE_ISPC_INSTRUCTION_SETS=sse2-i32x4;avx2-i32x8')
  if [[ "$APT_ARCH" == arm64 ]]; then
    # ISPC appends ISPC_ARGS after its command line. Keep the recorded CPU target authoritative.
    unset ISPC_ARGS
    ispc_options=(-DCMAKE_ISPC_INSTRUCTION_SETS=neon-i32x4 "-DCMAKE_ISPC_FLAGS=--cpu=$profile")
  fi
  if ! installed_artifact_matches "$nlm_plugin" "$profile" "$compiler_id" || vs_plugin_needs_upgrade "libvsnlm_ispc.so" "$tag"; then
    require_native_build "vs-nlm-ispc"
    log "$(msg "Building vs-nlm-ispc ($tag)" "编译 vs-nlm-ispc ($tag)")"
    download_source_archive "nlm_ispc $tag" "${vs_plugin_sources[nlm_ispc]}" nlm_ispc || exit 1
    cd nlm_ispc || exit 1
    mkdir -p build || exit 1
    cd build || exit 1
    tmux_run "vs-nlm-ispc cmake" cmake -DCMAKE_BUILD_TYPE=Release "-DCMAKE_ISPC_COMPILER=$compiler" "${ispc_options[@]}" .. || exit 1
    tmux_run "vs-nlm-ispc make" make -j"$(nproc)" || exit 1
    local out
    out="$(find "$PWD" -maxdepth 2 -name "libvsnlm_ispc.so" -type f | head -n 1)"
    [[ -n "${out:-}" ]] || exit 1
    install -m 0755 "$out" "$nlm_plugin" || exit 1
    vs_plugin_version record "libvsnlm_ispc.so" "$tag" || exit 1
    artifact_stamp "$nlm_plugin" "$compiler_id" > "$nlm_plugin.$profile.sha256" || exit 1
  else
    log "$(msg 'libvsnlm_ispc.so version is current, skipping' 'libvsnlm_ispc.so 版本已满足要求，跳过')"
  fi
)

install_vs_zsmooth() (
  local build_dir="$1" plugins_dir="$2" tag="${vs_plugin_tags[zsmooth]}"
  local library="libzsmooth.$LINUX_ARCH-gnu.so" asset="zsmooth-$LINUX_ARCH-linux-gnu.zip"
  local target="$plugins_dir/$library"
  if { [[ "$APT_ARCH" != amd64 ]] || installed_artifact_matches "$target" upstream; } && ! vs_plugin_needs_upgrade "$library" "$tag"; then
    return 0
  fi

  cd "$build_dir" || exit 1
  tmux_run "$(msg "Download zsmooth $tag" "下载 zsmooth $tag")" \
    download_github_release_asset adworacz/zsmooth "$tag" "$asset" || exit 1
  tmux_run "$(msg "Extract zsmooth $tag" "解压 zsmooth $tag")" unzip -o "$asset" -d zsmooth-release || exit 1
  install -m 0755 zsmooth-release/libzsmooth.so "$target" || exit 1
  vs_plugin_version record "$library" "$tag" || exit 1
  if [[ "$APT_ARCH" == amd64 ]]; then sha256sum < zsmooth-release/libzsmooth.so > "$target.upstream.sha256"; fi
)

install_vs_mvtools() (
  local build_dir="$1" plugins_dir="$2" tag="${vs_plugin_tags[mvtools]}"
  cd "$build_dir" || exit 1
  if vs_plugin_needs_upgrade "mvtools.so" "$tag"; then
    require_native_build "MVTools"
    log "$(msg "Building vapoursynth-mvtools ($tag)" "编译 vapoursynth-mvtools ($tag)")"
    download_source_archive "mvtools $tag" "${vs_plugin_sources[mvtools]}" mvtools || exit 1
    cd mvtools || exit 1
    tmux_run "mvtools meson setup" meson setup build --native-file "$vapoursynth_meson_file" || exit 1
    tmux_run "mvtools ninja" ninja -C build || exit 1
    install -m 0755 build/mvtools.so "$plugins_dir/mvtools.so" || exit 1
    vs_plugin_version record "mvtools.so" "$tag" || exit 1
  else
    log "$(msg 'mvtools.so version is current, skipping' 'mvtools.so 版本已满足要求，跳过')"
  fi
)

install_vs_build_dependencies() {
  local deps=(
    build-essential git wget tar unzip sed
    meson ninja-build cmake libass-dev
    autoconf automake libtool pkg-config
    libxxhash-dev libfftw3-dev
    python3 python3-pip
  )
  if [[ "$APT_ARCH" == amd64 ]]; then
    deps+=(nasm)
  fi
  local missing_deps=()
  for dep in "${deps[@]}"; do
    if ! dpkg-query -W -f='${Status}' "$dep" 2>/dev/null | grep -q "install ok installed"; then
      missing_deps+=("$dep")
    fi
  done
  local library
  for library in libavcodec libavformat libavutil libswscale libswresample; do
    if ! pkg-config --exists "$library" 2>/dev/null; then
      missing_deps+=("${library}-dev")
    fi
  done
  if (( ${#missing_deps[@]} > 0 )); then
    apt_update
    apt_install "${missing_deps[@]}" || die "$(msg 'Failed to install VS plugin dependencies' 'VS 插件依赖安装失败')"
  fi
  require_meson_version
}

build_vs_plugins() {
  log "$(msg "Building/installing VapourSynth plugins to ${PLUGIN_PATH}" "编译/安装 VapourSynth 插件到 ${PLUGIN_PATH}")"
  local plugins_dir="$PLUGIN_PATH"
  ensure_configured_directory "$plugins_dir"
  if ! "$restore_only"; then
    install_vs_build_dependencies
  fi
  export PATH="$HOME/.local/bin:$PATH"
  local build_dir
  build_dir="$(mktemp -d)"

  local lsmash_abi avcodec_major lsmash_tag="${vs_plugin_tags[lsmas]}" lsmash_source="${vs_plugin_sources[lsmas]}"
  lsmash_abi="$(pkg-config --modversion libavcodec libavformat libavutil libswscale libswresample liblsmash)" || {
    require_native_build "FFmpeg and L-SMASH development files"
    return 1
  }
  avcodec_major="${lsmash_abi%%.*}"
  [[ "$avcodec_major" =~ ^[0-9]+$ ]] \
    || die "$(msg 'Failed to determine the libavcodec development version for L-SMASH-Works' '无法确定 L-SMASH-Works 所需的 libavcodec 开发库版本')"
  if (( avcodec_major < 61 )); then
    die "$(msg "L-SMASH Works requires FFmpeg 7 or later (libavcodec >= 61, found $avcodec_major)" "L-SMASH Works 需要 FFmpeg 7 或更高版本（libavcodec 至少为 61，当前为 $avcodec_major）")"
  fi
  cached_linux_build lsmash-works install_vs_lsmash_works files "$vapoursynth_cache_abi $lsmash_source $lsmash_abi $(sha256sum < "$SETUP_ROOT/tools/lsmash_ffmpeg_compat.py")" \
    "$plugins_dir/libvslsmashsource.so" -- "$build_dir" "$plugins_dir" "$lsmash_tag" "$lsmash_source" "$avcodec_major"
  cached_linux_build eedi3m install_vs_eedi3m files "$vapoursynth_cache_abi ${vs_plugin_tags[eedi3m]}" \
    "$plugins_dir/eedi3m.so" -- "$build_dir" "$plugins_dir"
  cached_linux_build znedi3 install_vs_znedi3 files "$vapoursynth_cache_abi ${vs_plugin_tags[znedi3]} ${vs_plugin_digests[znedi3]}" \
    "$plugins_dir/znedi3.so" "$plugins_dir/nnedi3_weights.bin" "$plugins_dir/licenses/znedi3/graphengine/COPYING" \
    "$plugins_dir/licenses/znedi3/vsxx/COPYING.LGPLv2.1" "$plugins_dir/licenses/znedi3/gpl2.txt" \
    -- "$build_dir" "$plugins_dir"
  cached_linux_build addgrain install_vs_addgrain files "$vapoursynth_cache_abi ${vs_plugin_tags[addgrain]}" \
    "$plugins_dir/libaddgrain.so" -- "$build_dir" "$plugins_dir"
  cached_linux_build assrender install_vs_assrender files "$vapoursynth_cache_abi ${vs_plugin_tags[assrender]} $(pkg-config --modversion libass)" \
    "$plugins_dir/libassrender.so" -- "$build_dir" "$plugins_dir"
  cached_linux_build bilateral install_vs_bilateral files "$vapoursynth_cache_abi ${vs_plugin_tags[bilateral]}" \
    "$plugins_dir/libbilateral.so" -- "$build_dir" "$plugins_dir"
  cached_linux_build dfttest install_vs_dfttest files "$vapoursynth_cache_abi ${vs_plugin_tags[dfttest]}" \
    "$plugins_dir/libdfttest.so" -- "$build_dir" "$plugins_dir"
  cached_linux_build eedi2 install_vs_eedi2 files "$vapoursynth_cache_abi ${vs_plugin_tags[eedi2]}" \
    "$plugins_dir/libeedi2.so" -- "$build_dir" "$plugins_dir"
  cached_linux_build fmtconv install_vs_fmtconv files "$vapoursynth_cache_abi ${vs_plugin_tags[fmtconv]}" \
    "$plugins_dir/libfmtconv.so" -- "$build_dir" "$plugins_dir"
  cached_linux_build legacy-filters install_vs_legacy_filters files "$vapoursynth_cache_abi ${vs_plugin_tags[legacy-filters]}" \
    "$plugins_dir/libeedi3.so" "$plugins_dir/libmiscfilters.so" -- "$build_dir" "$plugins_dir"
  cached_linux_build vivtc install_vs_vivtc files "$vapoursynth_cache_abi ${vs_plugin_tags[vivtc]}" \
    "$plugins_dir/libvivtc.so" -- "$build_dir" "$plugins_dir"
  cached_linux_build removegrain install_vs_removegrain files "$vapoursynth_cache_abi ${vs_plugin_tags[removegrain]}" \
    "$plugins_dir/libremovegrain.so" -- "$build_dir" "$plugins_dir"
  local sse2neon_version=""
  local sangnom_inputs="$vapoursynth_cache_abi ${vs_plugin_tags[sangnom]}"
  local -a sangnom_outputs=("$plugins_dir/libsangnommod.so")
  if [[ "$APT_ARCH" == arm64 ]]; then
    sse2neon_version="$(latest_stable_tag https://github.com/DLTcollab/sse2neon.git '^v[0-9]+([.][0-9]+)+$' 'v*')" || return $?
    sse2neon_version="${sse2neon_version#v}"
    sangnom_inputs+=" $sse2neon_version $SANGNOM_SSE2NEON_PATCH"
    sangnom_outputs+=("$plugins_dir/libsangnommod.so.sse2neon.sha256")
  fi
  cached_linux_build sangnom install_vs_sangnom files "$sangnom_inputs" \
    "${sangnom_outputs[@]}" -- "$build_dir" "$plugins_dir" "$sse2neon_version"
  cached_linux_build vs-placebo install_vs_placebo system "$vapoursynth_cache_abi ${vs_plugin_tags[placebo]}" \
    "$plugins_dir/libvs_placebo.so" -- "$build_dir" "$plugins_dir"
  local ispc_version compiler compiler_id
  ispc_version="$(latest_stable_tag https://github.com/ispc/ispc.git '^v[0-9]+([.][0-9]+)+$' 'v*')" || return $?
  ispc_version="${ispc_version#v}"
  cached_linux_build ispc install_vs_ispc files "$ispc_version" /usr/local/bin/ispc -- "$build_dir" "$ispc_version"
  hash -r
  compiler="$(ispc_binary)" || return $?
  compiler_id="$("$compiler" --version)" || return $?
  local nlm_profile=portable
  if [[ "$APT_ARCH" == arm64 ]]; then nlm_profile=cortex-a53; fi
  cached_linux_build vs-nlm-ispc install_vs_nlm_ispc files "$vapoursynth_cache_abi ${vs_plugin_tags[nlm_ispc]} $compiler_id" \
    "$plugins_dir/libvsnlm_ispc.so" "$plugins_dir/libvsnlm_ispc.so.$nlm_profile.sha256" -- "$build_dir" "$plugins_dir" "$nlm_profile" "$compiler" "$compiler_id"
  local zsmooth_plugin="$plugins_dir/libzsmooth.$LINUX_ARCH-gnu.so"
  local -a zsmooth_outputs=("$zsmooth_plugin")
  if "$package_build" && [[ "$APT_ARCH" == amd64 ]]; then
    zsmooth_outputs+=("$zsmooth_plugin.upstream.sha256")
  fi
  cached_linux_build zsmooth install_vs_zsmooth files "$vapoursynth_cache_abi ${vs_plugin_tags[zsmooth]}" \
    "${zsmooth_outputs[@]}" -- "$build_dir" "$plugins_dir"
  cached_linux_build mvtools install_vs_mvtools files "$vapoursynth_cache_abi ${vs_plugin_tags[mvtools]}" \
    "$plugins_dir/mvtools.so" -- "$build_dir" "$plugins_dir"

  log "$(msg "VS plugins build complete, output directory: $plugins_dir" "VS 插件编译完成，输出目录：$plugins_dir")"
  rm -rf "$build_dir"
}

# ---------------------------------------------------------------------------
# Desktop VapourSynth plugins
# ---------------------------------------------------------------------------

test_desktop_vs_plugin() {
  VAPOURSYNTH_EXTRA_PLUGIN_PATH="" timeout 45s "$VAPOURSYNTH_PYTHON" -I - "$@" <<'PY'
import sys

import vapoursynth as vs

def check_plugin(name, path, mode="render"):
    core = vs.core
    core.std.LoadPlugin(path=path)
    if mode == "load":
        if not callable(core.rife.RIFE):
            raise RuntimeError("The RIFE filter is unavailable")
        return
    pixel_format = vs.GRAY8 if name == "bm3d" else vs.RGBS
    clip = core.std.BlankClip(width=96, height=64, format=pixel_format, length=3, fpsnum=24)
    if name == "ccd":
        result = core.ccd.CCD(clip, threshold=4.0)
    elif name == "bm3d":
        result = core.bm3d.Basic(clip, sigma=[3.0])
    else:
        result = core.rife.RIFE(clip, model=23, gpu_thread=1, skip=False)
        if result.fps != 48:
            raise RuntimeError("RIFE did not double the frame rate")
    frame = result.get_frame(1)
    if (frame.width, frame.height) != (96, 64):
        raise RuntimeError(f"{name} produced unexpected frame dimensions")


check_plugin(*sys.argv[1:])
PY
}

build_desktop_vs_plugin() (
  local name="$1" tag="$2" library="$3" build_dir
  if ! vs_plugin_needs_upgrade "$library" "$tag"; then
    return 0
  fi

  require_native_build "$name"

  build_dir="$(bluray_mktemp_dir)"
  trap 'rm -rf -- "$build_dir"' EXIT
  cd "$build_dir"
  log "$(msg "Building VapourSynth ${name} ${tag}" "编译 VapourSynth ${name} ${tag}")"
  tmux_run "${name} ${tag} download" download_url "${vs_plugin_sources[$name]}" source.tar.gz
  tar -xzf source.tar.gz --strip-components=1

  tmux_run "${name} meson setup" meson setup build --native-file "$vapoursynth_meson_file" -Db_lto=false
  tmux_run "${name} ninja" ninja -C build
  test_desktop_vs_plugin "$name" "$build_dir/build/$library" \
    || die "$(msg "${name} failed to render a test frame" "${name} 未通过测试帧渲染验证")"
  install -m 0755 "build/$library" "$PLUGIN_PATH/$library"
  vs_plugin_version record "$library" "$tag"
)

build_desktop_vs_rife_source() {
  local repository="$1" tag="$2" library="$3" model_dir="$4"
  local sdk="$PWD/ncnn-sdk" cmake_build="$PWD/ncnn-options/subprojects/ncnn/__CMake_build"
  local -x CMAKE_POLICY_VERSION_MINIMUM=3.10
  if ! pkg-config --exists vulkan; then
    apt_update || return $?
    apt_install libvulkan-dev || return $?
  fi

  # Fetch only the selected model and use the ncnn and glslang revisions pinned by the release.
  tmux_run "RIFE ${tag} source download" git -c advice.detachedHead=false clone \
    --filter=blob:none --sparse --depth 1 --branch "$tag" "${repository}.git" source || return $?
  tmux_run "RIFE ${tag} source checkout" git -C source sparse-checkout set RIFE subprojects "$model_dir" || return $?
  tmux_run "RIFE ncnn download" git -C source submodule update --init --depth 1 subprojects/ncnn || return $?
  tmux_run "RIFE glslang download" git -C source/subprojects/ncnn submodule update --init --depth 1 glslang || return $?
  # Meson's CMake import merges ncnn's per-source ISA flags, even for generic ARM code.
  # Configure the pinned RIFE layer selection, then let CMake compile the actual ncnn targets.
  tmux_run "RIFE ncnn configuration" meson setup ncnn-options source "${RIFE_MESON_OPTIONS[@]}" -Duse_system_ncnn=false || return $?
  tmux_run "RIFE ncnn SDK setup" cmake -S source/subprojects/ncnn -B "$cmake_build" "${RIFE_NCNN_OPTIONS[@]}" \
    "-DCMAKE_C_FLAGS=${CFLAGS:+$CFLAGS }-march=armv8-a" "-DCMAKE_CXX_FLAGS=${CXXFLAGS:+$CXXFLAGS }-march=armv8-a" \
    "-DCMAKE_INSTALL_PREFIX=$sdk" || return $?
  tmux_run "RIFE ncnn SDK build" cmake --build "$cmake_build" --parallel "$(nproc)" --target install || return $?
  # Meson omits CMake's LINK_ONLY entries from static dependencies. Keep the SDK's
  # link order and its pinned glslang/SPIRV targets when importing it into RIFE.
  sed -i -E '/INTERFACE_LINK_LIBRARIES/s/\\?[$]<LINK_ONLY:([^<>]+)>/\1/g' "$sdk/lib/cmake/ncnn/ncnn.cmake" || return $?
  tmux_run "RIFE Meson setup" meson setup source/build source "${RIFE_MESON_OPTIONS[@]}" \
    -Duse_system_ncnn=true "-Dcmake_prefix_path=$sdk" || return $?
  tmux_run "RIFE ninja" ninja -C source/build librife.so || return $?
  mv -- source/build/librife.so "source/$library"
}

install_desktop_vs_rife() (
  local repository="https://github.com/styler00dollar/VapourSynth-RIFE-ncnn-Vulkan"
  local library="$1" model_dir="$2" artifact="$3"
  local tag version build_dir model_file report
  local archive="" pending="" restored=false
  local -a model_files=("$model_dir/flownet.bin" "$model_dir/flownet.param")

  # Ship the same filter and model on headless hosts. A render test needs a GPU.
  local probe=load
  if ! "$package_build" && timeout -k 1s 10s "$VAPOURSYNTH_PYTHON" -IB "$SETUP_ROOT/tools/vulkan_device.py"; then
    probe=render
  fi

  tag="${vs_plugin_tags[rife]}"
  version="${tag#r}"
  version="${version/_mod_v/+mod.}"
  if installed_artifact_matches "$PLUGIN_PATH/$library" "$artifact" \
    && ! vs_plugin_needs_upgrade "$library" "$version" \
    && [[ -s "$PLUGIN_PATH/$model_dir/flownet.bin" && -s "$PLUGIN_PATH/$model_dir/flownet.param" ]]; then
    test_desktop_vs_plugin rife "$PLUGIN_PATH/$library" "$probe" \
      || die "$(msg "Installed RIFE failed its $probe check" "已安装的 RIFE 未通过 $probe 验证")"
    return 0
  fi

  build_dir="$(bluray_mktemp_dir)"
  trap 'rm -rf -- "$build_dir"; rm -f -- "$pending"' EXIT
  cd "$build_dir"
  if [[ "$APT_ARCH" == arm64 ]] && ! "$package_build"; then
    # The standalone desktop cache uses the original exact-version key.
    local key linux_cache_abi="${linux_cache_abis[1]}"
    local -a linux_build_inputs=()
    collect_linux_build_inputs rife
    key="$(linux_build_key rife files "$vapoursynth_cache_abi $tag" "$library" "${model_files[@]}")"
    archive="$BLURAY_SETUP_CACHE_DIR/builds/rife-${key%% *}.tar.gz"
  fi

  if [[ -s "$archive" ]] && tar -xzf "$archive" -- "$library" "${model_files[@]}" &&
      [[ -s "${model_files[0]}" && -s "${model_files[1]}" ]] &&
      test_desktop_vs_plugin rife "$PWD/$library" load; then
    restored=true
    log "$(msg "Reusing the ARM64 RIFE ${tag} build" "复用 RIFE ${tag} 的 ARM64 构建产物")"
  elif [[ "$APT_ARCH" == arm64 ]]; then
    log "$(msg "Building RIFE ${tag} for $APT_ARCH with the 4.6 model" "为 $APT_ARCH 编译 RIFE ${tag} 并准备 4.6 模型")"
    require_native_build RIFE
    build_desktop_vs_rife_source "$repository" "$tag" "$library" "$model_dir" \
      || die "$(msg 'The RIFE source build failed' 'RIFE 源码构建失败')"
    cd source
  else
    log "$(msg "Installing RIFE ${tag} with the 4.6 model" "安装 RIFE ${tag} 和 4.6 模型")"
    tmux_run "RIFE ${tag} download" download_github_release_asset "$repository" "$tag" "$library"
    mkdir -p "$model_dir"
    for model_file in "${model_files[@]}"; do
      tmux_run "RIFE model ${model_file##*/} download" download_url \
        "https://raw.githubusercontent.com/${repository#https://github.com/}/${tag}/${model_file}" "$model_file"
    done
  fi
  if ! report="$(LC_ALL=C ldd -r "./$library" 2>&1)" || [[ "$report" == *'not found'* || "$report" == *'undefined symbol'* ]]; then
    printf '%s\n' "$report" >&2
    die "$(msg 'The RIFE plugin has unresolved dependencies' 'RIFE 插件包含未解析的依赖')"
  fi
  [[ -s "${model_files[0]}" && -s "${model_files[1]}" ]] \
    || die "$(msg 'Missing or empty RIFE 4.6 model files' 'RIFE 4.6 模型文件缺失或为空')"
  test_desktop_vs_plugin rife "$PWD/$library" "$probe" \
    || die "$(msg "RIFE failed its $probe check" "RIFE 未通过 $probe 验证")"
  if [[ -n "$archive" ]] && ! "$restored"; then
    if ! { pending="$(mktemp "$BLURAY_SETUP_CACHE_DIR/builds/.rife.XXXXXXXX")" &&
        tar -czf "$pending" -- "$library" "${model_files[@]}" && mv -f -- "$pending" "$archive"; }; then
      log "$(msg 'Could not save the ARM64 RIFE build cache' '无法保存 RIFE 的 ARM64 构建缓存')"
    fi
  fi

  install -d "$PLUGIN_PATH/$model_dir"
  install -m 0644 "${model_files[@]}" "$PLUGIN_PATH/$model_dir/"
  install -m 0755 "$library" "$PLUGIN_PATH/$library"
  vs_plugin_version record "$library" "$version"
  sha256sum < "$library" > "$PLUGIN_PATH/$library.$artifact.sha256"
)

install_desktop_vs_plugins() {
  local rife_assets rife_library model_dir rife_cache_abi
  rife_assets="$(python3 -B "$SETUP_ROOT/tools/mpv/vapoursynth/rife_assets.py")" || return $?
  read -r rife_library model_dir <<< "$rife_assets"
  cached_linux_build ccd build_desktop_vs_plugin files "$vapoursynth_cache_abi ${vs_plugin_tags[ccd]}" \
    "$PLUGIN_PATH/libccd.so" -- ccd "${vs_plugin_tags[ccd]}" libccd.so
  cached_linux_build bm3d build_desktop_vs_plugin files "$vapoursynth_cache_abi ${vs_plugin_tags[bm3d]}" \
    "$PLUGIN_PATH/bm3d.so" -- bm3d "${vs_plugin_tags[bm3d]}" bm3d.so
  rife_cache_abi="$vapoursynth_cache_abi ${vs_plugin_tags[rife]} $model_dir"
  local artifact=upstream
  if [[ "$APT_ARCH" == arm64 ]]; then artifact=armv8-a; fi
  local -a rife_outputs=("$PLUGIN_PATH/$rife_library" "$PLUGIN_PATH/$model_dir/"{flownet.bin,flownet.param}
    "$PLUGIN_PATH/$rife_library.$artifact.sha256")
  # A fresh restore needs both model files even when an upgrade only replaces the plugin.
  cached_linux_build rife install_desktop_vs_rife complete-files "$rife_cache_abi" "${rife_outputs[@]}" -- "$rife_library" "$model_dir" "$artifact"
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

  local mpv_desktop="$desktop_dir/mpv.desktop"
  if [[ -f "$mpv_desktop" ]]; then
    sed -Ei 's@^Exec=(/[^[:space:]]*/)?mpv([[:space:]]|$)@Exec=/usr/local/bin/mpv\2@; s@^TryExec=(/[^[:space:]]*/)?mpv$@TryExec=/usr/local/bin/mpv@' "$mpv_desktop"
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
# Shaderc
# ---------------------------------------------------------------------------

shaderc_is_usable() (
  local shaderc_flags probe_dir
  shaderc_flags="$(pkg-config --cflags --libs 'shaderc >= 2019.1' 2>/dev/null)" || return 1
  probe_dir="$(bluray_mktemp_dir)" || return 1
  trap 'rm -rf -- "$probe_dir"' EXIT

  local flags=()
  # pkg-config escapes whitespace in paths with backslashes.
  read -a flags <<< "$shaderc_flags" || return 1
  cc -x c - -x none -o "$probe_dir/probe" "${flags[@]}" >/dev/null 2>&1 <<'C' || return 1
#include <shaderc/shaderc.h>

int main(void) {
    shaderc_compiler_t compiler = shaderc_compiler_initialize();
    if (!compiler)
        return 1;
    shaderc_compiler_release(compiler);
    return 0;
}
C
  "$probe_dir/probe" >/dev/null 2>&1
)

install_shaderc() {
  if shaderc_is_usable; then
    log "$(msg 'Existing Shaderc passed the link and initialization check, skipping source build' '现有 Shaderc 通过链接和初始化检查，跳过源码编译')"
    return 0
  fi

  if apt-get -s install --no-remove libshaderc-dev >/dev/null 2>&1; then
    apt_install --no-remove libshaderc-dev || die "$(msg 'Failed to install the Shaderc development package' '安装 Shaderc 开发包失败')"
    if shaderc_is_usable; then return 0; fi
  fi

  log "$(msg 'Shaderc is unavailable or failed its link and initialization check, building from source' 'Shaderc 不可用或未通过链接和初始化检查，将从源码编译')"

  local build_dir shaderc_tag
  shaderc_tag="$(latest_stable_tag https://github.com/google/shaderc.git '^v[0-9]+([.][0-9]+)+$' 'v*')"
  build_dir="$(mktemp -d)"
  (
      cd "$build_dir" || exit 1

      download_source_archive "Shaderc ${shaderc_tag}" \
          "https://codeload.github.com/google/shaderc/tar.gz/refs/tags/${shaderc_tag}" . || exit 1

      # Use Shaderc's DEPS parser and fetch only the dependencies needed with tests disabled.
      local dependencies path url
      dependencies="$(python3 -c '
from runpy import run_path

dependencies = run_path("utils/git-sync-deps")["parse_file_to_dict"]("DEPS")["deps"]
for path in ("third_party/glslang", "third_party/spirv-tools", "third_party/spirv-headers"):
    repository, commit = dependencies[path].rsplit("@", 1)
    repository = repository.removesuffix(".git")
    if repository.startswith("https://github.com/"):
        project = repository.removeprefix("https://github.com/")
        url = f"https://codeload.github.com/{project}/tar.gz/{commit}"
    else:
        url = f"{repository}/archive/{commit}.tar.gz"
    print(path, url)
')" || exit 1
      while read -r path url; do
          download_source_archive "${path##*/}" "$url" "$path" || exit 1
      done <<< "$dependencies"

      mkdir build && cd build || exit 1
      tmux_run "shaderc cmake" cmake -GNinja \
          -DCMAKE_BUILD_TYPE=Release \
          -DSHADERC_SKIP_TESTS=ON \
          -DCMAKE_INSTALL_PREFIX=/usr/local .. || exit 1

      tmux_run "shaderc ninja" ninja || exit 1
      install_component "shaderc install" ninja install || exit 1
  ) || die "$(msg 'Shaderc build/install failed' 'Shaderc 编译/安装失败')"
  rm -rf "$build_dir"
  sudo ldconfig || die "$(msg 'Failed to refresh the Shaderc library cache' '刷新 Shaderc 动态库缓存失败')"
  shaderc_is_usable || die "$(msg 'Installed Shaderc failed the link and initialization check' '安装后的 Shaderc 未通过链接和初始化检查')"
  log "$(msg 'Shaderc built and installed from source.' 'Shaderc 源码编译并安装完成。')"
}

# ---------------------------------------------------------------------------
# BluraySubtitle Python dependencies
# ---------------------------------------------------------------------------

__bluray_python_imports_ok() {
  local dependency failed=0
  local dependencies=(numpy:numpy pycountry:pycountry PyQt6:PyQt6.QtWidgets soundfile:soundfile pillow:PIL.Image)
  if "$package_build"; then
    dependencies+=(PyInstaller:PyInstaller)
  else
    dependencies+=(matplotlib:matplotlib)
  fi
  for dependency in "${dependencies[@]}"; do
    if ! "$VAPOURSYNTH_PYTHON" -c 'import importlib, sys; importlib.import_module(sys.argv[1])' "${dependency#*:}" >/dev/null; then
      printf '%s\n' "${dependency%%:*}"
      failed=1
    fi
  done
  return "$failed"
}

install_bluray_python_deps() {
  log "$(msg 'Installing application Python dependencies' '正在安装应用 Python 依赖')"
  local -a python_packages=(numpy pycountry soundfile pillow PyQt6)
  local -a pip_extra=(--only-binary=PyQt6,PyQt6-Qt6,PyQt6-sip)
  if "$package_build"; then
    python_packages+=(PyInstaller PyQt6-Qt6 PyQt6-sip)
  else
    python_packages+=(matplotlib)
  fi
  "$VAPOURSYNTH_PYTHON" -m pip install --upgrade "${pip_extra[@]}" "${python_packages[@]}"

  local failed_packages
  if ! failed_packages="$(__bluray_python_imports_ok)"; then
    local packages_to_reinstall=()
    mapfile -t packages_to_reinstall <<< "$failed_packages"
    log "$(msg "Reinstalling Python dependencies that failed to import: ${packages_to_reinstall[*]}" "正在重新安装导入失败的 Python 依赖：${packages_to_reinstall[*]}")"
    tmux_run "$(msg 'Reinstall Python dependencies without cached wheels' '不使用缓存 wheel 重新安装 Python 依赖')" \
      env PIP_DISABLE_PIP_VERSION_CHECK=1 "$VAPOURSYNTH_PYTHON" -m pip install --upgrade --force-reinstall --no-cache-dir "${pip_extra[@]}" "${packages_to_reinstall[@]}" \
      || die "$(msg 'Failed to reinstall Python dependencies; see the pip error above' '重新安装 Python 依赖失败，请查看上方 pip 错误')"
    if ! __bluray_python_imports_ok; then
      require_native_build "Python runtime libraries"
      die "$(msg 'Python dependencies still fail to import after reinstallation; see the traceback above' '重新安装后 Python 依赖仍无法导入，请查看上方 traceback')"
    fi
  fi
}

# ---------------------------------------------------------------------------
# Installed build artifact cache
# ---------------------------------------------------------------------------

resolve_mpv_build_revision() {
  git ls-remote --exit-code https://github.com/mpv-player/mpv-build.git refs/heads/master | cut -f1
}

cache_build_tag() {
  local repository="$1" override="${2:-}"
  local pattern="${3:-^[vV]?[0-9]+([.][0-9]+)+$}" glob="${4:-*}" tag
  tag="${override:-$(latest_stable_tag "$repository" "$pattern" "$glob")}" || return $?
  linux_build_tags["$repository $pattern $glob"]="$tag"
  linux_build_inputs+=("$repository" "$tag")
}

collect_linux_build_inputs() {
  local source="$1"
  case "$source" in
    vs-placebo) source=placebo ;;
    vs-nlm-ispc) source=nlm_ispc ;;
  esac
  if [[ -n "${vs_plugin_sources[$source]:-}" ]]; then
    linux_build_inputs+=("${vs_plugin_sources[$source]}" "${vs_plugin_digests[$source]:-}")
  fi
  case "$1" in
    mkvtoolnix-paths)
      linux_build_inputs+=("$(mkvtoolnix_installed_version)")
      ;;
    mpv-ffmpeg)
      cache_build_tag "$FFMPEG_SOURCE_REPOSITORY" "" '^n[0-9]+([.][0-9]+)+$' 'n*' || return $?
      cache_build_tag https://github.com/mpv-player/mpv.git "" '^v[0-9]+([.][0-9]+)+$' 'v*' || return $?
      cache_build_tag https://github.com/libass/libass.git "" '^[0-9]+([.][0-9]+)+$' || return $?
      cache_build_tag https://github.com/haasn/libplacebo.git "" '^v[0-9]+([.][0-9]+)+$' 'v*' || return $?
      linux_mpv_build_revision="$(resolve_mpv_build_revision)" || return $?
      linux_build_inputs+=("$linux_mpv_build_revision" "${MPV_FFMPEG_OPTIONS[@]}"
        "${MPV_FFMPEG_PACKAGE_OPTIONS[@]}" "${MPV_OPTIONS[@]}" "$MPV_VULKAN_OPTION")
      ;;
    x264)
      linux_x264_source="$(resolve_x264_source)" || return $?
      linux_build_inputs+=("${linux_x264_source##* }" "${X264_CONFIGURE_OPTIONS[@]}")
      ;;
    x265)
      cache_build_tag "$X265_SOURCE_REPOSITORY" "" '^[0-9]+([.][0-9]+)+$' '[0-9]*' || return $?
      ;;
    svt-av1)
      cache_build_tag "$SVT_AV1_SOURCE_REPOSITORY" "${SVT_AV1_VERSION:-}" || return $?
      ;;
    tsmuxer)
      cache_build_tag https://github.com/justdan96/tsMuxer.git "$TSMUXER_VERSION" || return $?
      TSMUXER_VERSION="${linux_build_inputs[-1]}"
      if [[ "$APT_ARCH" == arm64 ]]; then
        linux_build_inputs+=("${TSMUXER_CMAKE_OPTIONS[@]}" "$TSMUXER_INCLUDE_PATCH")
      fi
      ;;
    dovi-tool)
      cache_build_tag https://github.com/quietvoid/dovi_tool.git "$DOVI_TOOL_VERSION" || return $?
      DOVI_TOOL_VERSION="${linux_build_inputs[-1]}"
      ;;
    hdr10plus-tool)
      cache_build_tag https://github.com/quietvoid/hdr10plus_tool.git || return $?
      ;;
    fdkaac)
      cache_build_tag "$FDK_AAC_SOURCE_REPOSITORY" "${FDK_AAC_VERSION:-}" || return $?
      cache_build_tag "$FDKAAC_SOURCE_REPOSITORY" "${FDKAAC_VERSION:-}" || return $?
      ;;
    flac)
      cache_build_tag https://github.com/xiph/flac.git "${FLAC_VERSION:-}" || return $?
      ;;
    7zip)
      cache_build_tag https://github.com/ip7z/7zip.git "${SEVENZIP_VERSION:-}" '^[0-9]+[.][0-9]+$' || return $?
      ;;
    vsedit)
      cache_build_tag "$VSEDIT_SOURCE_REPOSITORY" "${VSEDIT_TAG:-}" '^[rR][0-9]+-mod-[0-9]+([.][0-9]+)*$' || return $?
      ;;
    lsmash)
      cache_build_tag "$LSMASH_SOURCE_REPOSITORY" "${LSMASH_VERSION:-}" "$LSMASH_COMPATIBLE_TAG_PATTERN" || return $?
      LSMASH_VERSION="${linux_build_inputs[-1]}"
      ;;
    dfttest)
      linux_build_inputs+=("${DFTTEST_MESON_OPTIONS[@]}")
      ;;
    vs-placebo)
      linux_build_inputs+=("$(pkg-config --modversion libplacebo)" "$(pkg-config --variable=pl_has_vulkan libplacebo)")
      ;;
    rife)
      if [[ "$APT_ARCH" == arm64 ]]; then
        linux_build_inputs+=("${RIFE_MESON_OPTIONS[@]}" "${RIFE_NCNN_OPTIONS[@]}")
      fi
      ;;
  esac
}

linux_build_key() {
  local component="$1" scope="$2" recipe_inputs="$3"
  shift 3
  {
    # Bump the component's revision when changing an inline build step or patch.
    # Options shared with the builders and upstream refs are already key inputs.
    printf '%s\0' 'linux-native-v3' "$component" "${linux_recipe_revisions[$component]:-1}" \
      "$linux_cache_abi" "$scope" "$recipe_inputs" "${linux_build_inputs[@]}" -- "$@"
  } | sha256sum
}

legacy_linux_build_key() {
  local component="$1" installer="$2" scope="$3" inputs="$4"
  shift 4
  [[ "$APT_ARCH" == amd64 && "${linux_recipe_revisions[$component]:-1}" == 1 &&
    -f "$cache_workspace/legacy/$installer" ]] || return 1
  case "$component" in
    # These recipes build differently from the old x64 workflow.
    mpv-ffmpeg|lsmash-works|vs-placebo|zsmooth|fmtconv|x264|rife) return 1 ;;
    dfttest)
      [[ "${DFTTEST_MESON_OPTIONS[*]}" == '-Dcpp_link_args=-lfftw3f_threads' ]] || return 1
      inputs="$vapoursynth_cache_abi"
      ;;
    x265)
      inputs="$(printf '%s\n' "$X265_SOURCE_REPOSITORY" "${X265_LINK:-auto}"
        cat "$cache_workspace/legacy/"{__build_x265_official_multilib,__patch_x265_hdr10plus_json11})"
      ;;
    vsedit) inputs+=" $(cat "$cache_workspace/legacy/write_vsedit_launcher")" ;;
    descale) inputs="https://github.com/AmusementClub/descale.git $vapoursynth_cache_abi" ;;
    ccd) inputs="$vapoursynth_cache_abi https://github.com/End-of-Eternity/vs-ccd.git ${vs_plugin_tags[ccd]}" ;;
    bm3d) inputs="$vapoursynth_cache_abi https://github.com/HomeOfVapourSynthEvolution/VapourSynth-BM3D.git r10.1" ;;
    assrender) inputs="$vapoursynth_cache_abi $(pkg-config --modversion libass)" ;;
    vs-nlm-ispc) inputs="$vapoursynth_cache_abi $(ispc --version)" ;;
    eedi3m|znedi3|addgrain|bilateral|eedi2|legacy-filters|vivtc|removegrain|sangnom|mvtools)
      inputs="$vapoursynth_cache_abi"
      ;;
    mkvtoolnix|mkvtoolnix-paths|vapoursynth-sdk|svt-av1|tsmuxer|dovi-tool|hdr10plus-tool|fdkaac|flac|7zip|lsmash|ispc) ;;
    *) return 1 ;;
  esac
  {
    printf '%s\0' "$linux_cache_abi" "$scope" "$inputs" "$@"
    cat "$cache_workspace/legacy/$installer"
  } | sha256sum
}

cached_linux_build() {
  local component="$1" installer="$2" scope="$3" recipe_inputs="$4"
  shift 4
  local -a outputs=()
  while (( $# )) && [[ "$1" != -- ]]; do
    outputs+=("$1")
    shift
  done
  if (( $# )); then shift; fi
  if ! "$package_build"; then
    "$installer" "$@"
    return
  fi

  local key archive restored_key="" previous_key abi
  local -a previous_keys=()
  local component_manifest="$cache_workspace/$component.json" component_stage="$cache_workspace/$component-install"
  local -A linux_build_tags=()
  local -a linux_build_inputs=()
  local linux_mpv_build_revision="" linux_x264_source=""
  local TSMUXER_VERSION="$TSMUXER_VERSION" DOVI_TOOL_VERSION="$DOVI_TOOL_VERSION"
  local LSMASH_VERSION="${LSMASH_VERSION:-}"
  collect_linux_build_inputs "$component" || return $?
  key="$(linux_build_key "$component" "$scope" "$recipe_inputs" "${outputs[@]}")" || return $?
  key="${key%% *}"
  archive="$BLURAY_SETUP_CACHE_DIR/builds/components/$component.tar.xz"
  local -a helper=(/usr/bin/python3 -B "$SETUP_ROOT/tools/linux_setup_cache.py")
  local -a args=("$archive" "$component_manifest" "$key" "$scope" "$PLUGIN_PATH")

  if ! "$restore_only"; then
    "${helper[@]}" snapshot "${args[@]}" "" "${outputs[@]}" || return $?
  fi
  if [[ -s "$archive" ]]; then
    for abi in "${linux_cache_abis[@]:1}"; do
      if [[ "$abi" != "$linux_cache_abi" ]]; then
        previous_key="$(linux_cache_abi="$abi" linux_build_key "$component" "$scope" "$recipe_inputs" "${outputs[@]}")" || return $?
        previous_keys+=("${previous_key%% *}")
      fi
      if previous_key="$(linux_cache_abi="$abi" legacy_linux_build_key "$component" "$installer" "$scope" "$recipe_inputs" "${outputs[@]}")"; then
        previous_keys+=("${previous_key%% *}")
      fi
    done
    if restored_key="$("${helper[@]}" restore "${args[@]}" "${previous_keys[*]}" "${outputs[@]}")"; then
      if [[ "$scope" == system ]]; then sudo ldconfig || return $?; fi
      log "$(msg "Restored the build cache for $component" "已恢复 $component 的构建缓存")"
    fi
  fi
  if "$restore_only" && [[ -z "$restored_key" ]]; then
    # Prebuilt tools can fill a missing artifact cache without APT or a native build.
    "${helper[@]}" snapshot "${args[@]}" "" "${outputs[@]}" || return $?
  fi
  "$installer" "$@"
  local status=$?
  (( status == 0 )) || return "$status"
  "${helper[@]}" save "${args[@]}" "$restored_key" "${outputs[@]}"
}

# ---------------------------------------------------------------------------
# Main execution
# ---------------------------------------------------------------------------

# Build cache replay uses its verified binaries and does not require APT indexes.
setup_build_packages=()
# Use one source snapshot. A fresh bash preserves errexit in the replay's installers
# and keeps the temporary dpkg database out of any subsequent native build.
if "$package_build" && ! "$restore_only" && ! "$setup_in_tmux" && [[ "${BLURAY_BUILD_CACHE_PROBED:-}" != true ]]; then
  build_required="$SETUP_ROOT/build-required"
  if BLURAY_BUILD_REQUIRED_FILE="$build_required" BLURAYSUBTITLE_GITHUB_TOKEN="$setup_github_api_token" \
      BLURAY_SETUP_SOURCE="$BLURAY_SETUP_SOURCE" SETTINGS_FILE="$SETTINGS_FILE" \
      setup_settings_source="$setup_settings_source" setup_config_dir="$setup_config_dir" \
      bash -c 'setup_temporary_dirs=(); source "$BLURAY_SETUP_SOURCE" --mode Build --restore-only'; then
    exit 0
  elif [[ ! -f "$build_required" ]]; then
    exit 1
  fi
  log "$(msg 'The cache needs additional build dependencies or a native component. Continuing setup.' '缓存需要补充构建依赖或编译组件，继续安装。')"
fi
if ! "$restore_only"; then
  # New minimal images can have only dpkg's status file and no repository indexes yet.
  if ! LC_ALL=C apt-cache policy | grep -E '^[[:space:]]*-?[0-9]+ .+ Packages$' >/dev/null; then apt_update; fi
  check_setup_package_versions \
    || die "$(msg 'Full setup needs the package versions listed above. Refresh the APT indexes or use the packaged build.' '完整安装需要上面列出的软件包版本。请刷新 APT 索引或使用打包版。')"
  if ! "$setup_in_tmux" && [[ -z "${TMUX:-}" && -t 1 ]] && is_remote_ssh; then
    ensure_tmux_installed
    start_setup_in_tmux "$@"
  fi
fi
ensure_sudo_once
mkdir -p -- "$BLURAY_SETUP_CACHE_DIR"/{downloads,apt,pip,ccache,builds/components}
BLURAY_SETUP_CACHE_DIR="$(realpath "$BLURAY_SETUP_CACHE_DIR")"
export BLURAY_SETUP_CACHE_DIR
export PIP_CACHE_DIR="$BLURAY_SETUP_CACHE_DIR/pip"
export CCACHE_DIR="$BLURAY_SETUP_CACHE_DIR/ccache"
export CARGO_TARGET_DIR="$BLURAY_SETUP_CACHE_DIR/cargo"
export CCACHE_BASEDIR="$(bluray_build_tmp_base)"
export CCACHE_NOHASHDIR=true
if [[ -n "${BLURAY_BUILD_TMP:-}" ]]; then
  export TMPDIR="$CCACHE_BASEDIR"
fi
if "$restore_only" && [[ -f "$BLURAY_SETUP_CACHE_DIR/apt-runtime/packages.json" ]]; then
  apt_state="$(bluray_mktemp_dir)"
  setup_temporary_dirs+=("$apt_state")
  /usr/bin/python3 -B "$SETUP_ROOT/tools/linux_apt_cache.py" restore "$BLURAY_SETUP_CACHE_DIR" "$apt_state" \
    || require_native_build "the APT runtime snapshot"
  export DPKG_ADMINDIR="$apt_state"
elif "$restore_only"; then
  # A local warm build can use its real installed packages without a CI .deb manifest.
  for tool in cc strip readelf patchelf pkg-config tar xz git curl unzip; do
    command -v "$tool" >/dev/null || require_native_build "$tool"
  done
  if [[ ! -x "${XDG_DATA_HOME:-$HOME/.local/share}/bluraysubtitle/uv/bin/python" ]]; then
    /usr/bin/python3 -c 'import ensurepip' 2>/dev/null || require_native_build "python3-venv"
  fi
elif ! "$package_build" || [[ -n "$(dpkg --audit)" ]] || ! apt-get check -s >/dev/null 2>&1; then
  repair_broken_apt_state
fi

sys_deps=(
  python3 python3-pip python3-venv cmake ninja-build git ccache
  curl wget unzip fonts-wqy-microhei flac
  libegl1 libopengl0 libglib2.0-0 libglib2.0-bin libxkbcommon0 libxkbcommon-x11-0 libdbus-1-3 libx11-6
  libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 libxcb-shape0
  libxcb-xinerama0 libxcb-xinput0 libxcb-render-util0
  libunwind8 libunwind-dev xdg-utils libgl1-mesa-dri libglx-mesa0 libvulkan1 mesa-vulkan-drivers
)

if "$package_build"; then
  sys_deps+=(libarchive-tools patchelf libdouble-conversion3 libegl-dev libgles-dev libass-dev libplacebo-dev xz-utils
    pipewire-bin libpipewire-0.3-modules)
else
  sys_deps+=(gedit)
fi

missing_deps=("${setup_build_packages[@]}")
if ! "$restore_only"; then
  for dep in "${sys_deps[@]}"; do
    installed_names=("$dep")
    if [[ "$dep" == libglib2.0-0 ]]; then installed_names=("$dep:$APT_ARCH" "libglib2.0-0t64:$APT_ARCH"); fi
    if ! { dpkg-query -W -f='${Status}\n' "${installed_names[@]}" 2>/dev/null || true; } | grep -qx 'install ok installed'; then
      missing_deps+=("$dep")
    fi
  done
fi

if (( ${#missing_deps[@]} > 0 )); then
  log "$(msg "Installing system dependencies (missing: ${missing_deps[*]})" "安装系统依赖（缺少：${missing_deps[*]}）")"
  apt_update
  apt_install "${missing_deps[@]}"

  log "$(msg 'Refreshing font cache' '刷新字体缓存')"
  sudo fc-cache -f >/dev/null 2>&1 || true
else
  log "$(msg 'All system dependencies already installed, skipping' '系统依赖已全部安装，跳过')"
fi

export PATH="/usr/lib/ccache:$PATH"
load_configured_tool_paths
if "$package_build"; then
  log "$(msg "Using tool paths from ${setup_settings_source}" "使用 ${setup_settings_source} 中配置的工具路径")"
else
  log "$(msg 'Using tool paths from config.json' '使用 config.json 中配置的工具路径')"
fi

select_vapoursynth_python
install_bluray_python_deps
linux_cache_abi="" qt_cache_abi="" vapoursynth_cache_abi=""
declare -A linux_recipe_revisions=([vsedit]=2 [mkvtoolnix]=2 [vapoursynth-sdk]=2 [lsmash-works]=2 [eedi3m]=2 [mvtools]=2 [bm3d]=2 [ispc]=2 [vs-nlm-ispc]=2)
if [[ "$APT_ARCH" == arm64 ]]; then linux_recipe_revisions[sangnom]=2; fi
declare -A vs_plugin_tags=() vs_plugin_sources=() vs_plugin_digests=()
if "$package_build"; then
  cache_workspace="$(bluray_mktemp_dir)"
  setup_temporary_dirs+=("$cache_workspace")
  if [[ "$APT_ARCH" == amd64 && -n "${BLURAY_LEGACY_CACHE_SETUP:-}" ]]; then
    /usr/bin/python3 -B "$SETUP_ROOT/tools/linux_setup_cache.py" legacy-declarations \
      "$BLURAY_LEGACY_CACHE_SETUP" "$cache_workspace/legacy" \
      || log "$(msg 'Could not read the previous cache recipes' '无法读取旧版缓存配方')"
  fi
  QT66_PREFIX="$("$VAPOURSYNTH_PYTHON" -B "$SETUP_ROOT/tools/install_linux_qt66.py" "$BLURAY_SETUP_CACHE_DIR")" || {
    status=$?
    if (( status == 127 )); then
      require_native_build libarchive-tools
      die "$(msg 'Qt SDK extraction needs bsdtar (libarchive-tools).' '解包 Qt SDK 需要 bsdtar（libarchive-tools）。')"
    fi
    exit "$status"
  }
  QMAKE6="$QT66_PREFIX/lib64/qt6/bin/qmake"
  # The packaged tools link these Qt libraries. qmake-only SDK repairs can reuse them.
  qt_cache_abi="$(cd -- "$QT66_PREFIX/lib64" && sha256sum libQt6{Core,Gui,Network,Widgets}.so.6 | sha256sum)"
  qt_cache_abi="qt6-$APT_ARCH-${qt_cache_abi:0:16}"
  MKVTOOLNIX_PATH="$HOME/.local/share/bluraysubtitle/build/$qt_cache_abi/bin"
  mkdir -p -- "$MKVTOOLNIX_PATH"
  VSEDIT_BINARY_PATH="$MKVTOOLNIX_PATH/vsedit"
  VSEDIT_PATH="$VSEDIT_BINARY_PATH"
fi
if "$package_build" || [[ "$APT_ARCH" == arm64 ]]; then
  mapfile -d '' -t linux_cache_abis < <(
    /usr/bin/python3 -B "$SETUP_ROOT/tools/linux_apt_cache.py" native-abis "$BLURAY_SETUP_CACHE_DIR" "$APT_ARCH"
  )
  (( ${#linux_cache_abis[@]} >= 2 )) || die "$(msg 'Could not read native runtime versions' '无法读取原生运行库版本')"
  for abi_index in "${!linux_cache_abis[@]}"; do
    linux_cache_abis[abi_index]="$(printf '%s\n' "$LINUX_DISTRO_ID/$APT_BASE_CODENAME/$(uname -m)" \
      "${CC:-}" "${CXX:-}" "${CFLAGS:-}" "${CXXFLAGS:-}" "${CPPFLAGS:-}" "${LDFLAGS:-}" "${linux_cache_abis[abi_index]}")"
  done
  linux_cache_abi="${linux_cache_abis[0]}"
fi

install_mkvtoolnix
if ! "$package_build"; then sync_mkvtoolnix_paths; fi
# Meson otherwise uses its own interpreter for plugins that call vs.get_include().
vapoursynth_meson_file="$SETUP_ROOT/vapoursynth-python.ini"
printf "[binaries]\npython = '''%s'''\n" "$VAPOURSYNTH_PYTHON" > "$vapoursynth_meson_file"
cached_linux_build vapoursynth-sdk install_vapoursynth system \
  "$VAPOURSYNTH_TAG $("$VAPOURSYNTH_PYTHON" --version)" "$VSPIPE_PATH" /usr/local/lib/pkgconfig/vapoursynth.pc \
  /usr/local/include/vapoursynth/{VSConstants4,VSFrameMemory,VSHelper,VSHelper4,VSScript,VSScript4,VapourSynth,VapourSynth4}.h
if "$package_build" || [[ "$APT_ARCH" == arm64 ]]; then
  vapoursynth_cache_abi="$(sha256sum "$VAPOURSYNTH_VSSCRIPT" /usr/local/include/vapoursynth/*.h | sha256sum)"
fi
cached_linux_build mpv-ffmpeg install_mpv system "$MESON_MIN_VERSION $DOVI_TOOL_VERSION $vapoursynth_cache_abi" \
  "$FFMPEG_PATH" "$FFPROBE_PATH" /usr/bin/mpv /usr/include/libdovi/rpu_parser.h
# Build caches contain the native executable. Restore an existing Desktop launcher after updating it.
if ! "$package_build" || [[ -f /usr/local/libexec/bluraysubtitle/mpv_runtime.py ]]; then
  bluray_sudo /usr/bin/python3 -B "$SETUP_ROOT/tools/mpv/install.py" --install-launcher
fi
if ! "$package_build"; then
  /usr/bin/python3 -B "$SETUP_ROOT/tools/mpv/install.py" --configure-runtime "$VAPOURSYNTH_VSSCRIPT" "$PLUGIN_PATH" "$MPV_PATH"
fi
cached_linux_build x264 install_x264 files \
  "$X264_SOURCE_REPOSITORY $X264_SOURCE_MIRROR $(pkg-config --modversion libavutil libavformat 2>/dev/null || true)" \
  "$X264_PATH" "$X264_VERSION_FILE"
cached_linux_build x265 install_x265 files "${X265_LINK:-auto}" "$X265_PATH" "$X265_FEATURE_FILE"
cached_linux_build svt-av1 install_svt_av1 files "$SVT_AV1_SOURCE_REPOSITORY ${SVT_AV1_VERSION:-}" \
  "$SVT_AV1_PATH" "$SVT_AV1_PATH.portable.sha256"
cached_linux_build tsmuxer install_tsmuxer files "$TSMUXER_VERSION" "$TS_MUXER_PATH"
cached_linux_build dovi-tool install_dovi_tool files "$DOVI_TOOL_VERSION" "$DOVI_TOOL_PATH"
cached_linux_build hdr10plus-tool install_hdr10plus_tool files "" "$HDR10PLUS_TOOL_PATH"
cached_linux_build fdkaac install_fdk_aac system \
  "$FDK_AAC_SOURCE_REPOSITORY $FDKAAC_SOURCE_REPOSITORY ${FDK_AAC_VERSION:-} ${FDKAAC_VERSION:-}" "$FDK_AAC_PATH"
cached_linux_build flac install_flac system "${FLAC_VERSION:-}" "$FLAC_PATH"
ensure_configured_directory "$PLUGIN_PATH"
resolve_vs_plugin_releases descale lsmas eedi3m znedi3 addgrain assrender bilateral dfttest eedi2 \
  fmtconv legacy-filters vivtc removegrain sangnom placebo nlm_ispc zsmooth mvtools ccd bm3d rife \
  || die "$(msg 'Failed to resolve stable VapourSynth plugin releases' '查询 VapourSynth 插件稳定版失败')"
cached_linux_build descale install_descale files "$vapoursynth_cache_abi ${vs_plugin_sources[descale]}" "$PLUGIN_PATH/libdescale.so"
cached_linux_build 7zip ensure_modern_7zip_cli files "${SEVENZIP_VERSION:-}" "$SEVEN_ZIP_PATH"
install_vapoursynth_scripts
cached_linux_build vsedit install_vapoursynth_editor files \
  "$VSEDIT_SOURCE_REPOSITORY ${VSEDIT_TAG:-} $vapoursynth_cache_abi $qt_cache_abi" \
  "$VSEDIT_BINARY_PATH"
cached_linux_build lsmash install_lsmash system "${LSMASH_VERSION:-}"
build_vs_plugins
install_desktop_vs_plugins
if "$package_build"; then
  stage_mpv_uosc_archive "$BLURAY_SETUP_CACHE_DIR/mpv-uosc-$APT_ARCH.tar.gz" \
    || die "$(msg 'Could not prepare uosc for the Linux package' '无法为 Linux 包准备 uosc')"
  python3 -B "$SETUP_ROOT/tools/mpv/install.py" --cache-lazy-shaders \
    || die "$(msg 'Could not prepare mpv-lazy shaders for the Linux package' '无法为 Linux 包准备 mpv-lazy 着色器')"
else
  if [[ -n "$LIBASS_PATH" && ! -f "$LIBASS_PATH" ]]; then
    installed_libass="$(/sbin/ldconfig -p | awk '/^[[:space:]]*libass\.so\.9 / && !found {print $NF; found=1}')"
    [[ -f "$installed_libass" ]] || die "$(msg 'Could not find the installed libass library' '找不到已安装的 libass 库')"
    bluray_sudo install -D -m 0644 "$installed_libass" "$LIBASS_PATH"
  fi
  install_mpv_desktop
  install_desktop_shortcuts
fi

verify_configured_tool_paths
if "$package_build"; then
  build_environment="$(mktemp "$BLURAY_SETUP_CACHE_DIR/build-environment.XXXXXXXX")"
  printf '%s\n' "$VAPOURSYNTH_PYTHON" "$QT66_PREFIX" "$MKVTOOLNIX_PATH" > "$build_environment"
  mv -f -- "$build_environment" "$BLURAY_SETUP_CACHE_DIR/build-environment-$APT_ARCH"
  sudo chown -R -- "$(id -u):$(id -g)" "$PIP_CACHE_DIR" "$BLURAY_SETUP_CACHE_DIR/apt"
fi
if "$restore_only"; then
  log "$(msg 'Verified the restored build environment without APT installation.' '已验证恢复的构建环境，跳过 APT 安装。')"
fi

log "$(msg 'Done. Recommended way to run:' '完成。推荐的运行方式：')"
printf '%q -m src.main\n' "$VAPOURSYNTH_PYTHON"
