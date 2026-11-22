#!/bin/bash
set -euo pipefail

export BLURAY_LANG=${BLURAY_LANG:-${LANG:-en}}
msg() {
    case "$BLURAY_LANG" in zh*) echo "$2";; *) echo "$1";; esac
}

mode=Desktop
restore=false
plan_args=()
reuse_tools=false
while (($#)); do
    case "$1" in
        --mode) mode=${2:?Expected Desktop or Build}; shift 2 ;;
        --restore-only) restore=true; shift ;;
        --plan|--from-plan)
            [[ "$1" != --from-plan ]] || reuse_tools=true
            plan_args+=("$1" "${2:?Expected a cache plan path}"); shift 2 ;;
        -h|--help) msg 'Usage: ./setup_macos_environment.sh [--mode Desktop|Build] [--restore-only] [--plan FILE|--from-plan FILE]' '用法：./setup_macos_environment.sh [--mode Desktop|Build] [--restore-only] [--plan FILE|--from-plan FILE]'; exit 0 ;;
        *) msg "Unknown argument: $1" "未知参数：$1" >&2; exit 2 ;;
    esac
done
case "$mode" in Desktop|Build) ;; *) msg "Unknown setup mode: $mode" "未知的安装模式：$mode" >&2; exit 2 ;; esac
if [[ $(uname -s) != Darwin || $(sysctl -in sysctl.proc_translated) == 1 ]]; then
    msg 'Run setup on a native Intel or Apple silicon Mac.' '请在原生 Intel Mac 或 Apple 芯片 Mac 上运行安装脚本。' >&2
    exit 1
fi
case "$(uname -m)" in
    x86_64) subdir=osx-64; cpu=x86_64 ;;
    arm64) subdir=osx-arm64; cpu=aarch64 ;;
    *) exit 1 ;;
esac
if ! xcode-select -p >/dev/null 2>&1; then
    msg 'Install the Apple Command Line Tools with xcode-select --install, then run setup again.' '请先用 xcode-select --install 安装 Apple 命令行工具，再运行安装脚本。' >&2
    exit 1
fi

root=$(cd "$(dirname "$0")" && pwd)
cache=${BLURAY_SETUP_CACHE_DIR:-"$HOME/Library/Caches/BluraySubtitle/macos-$(uname -m)"}
mkdir -p "$cache"/{bootstrap,downloads}
export BLURAY_SETUP_CACHE_DIR="$cache"
export PIP_CACHE_DIR="$cache/pip"
export UV_CACHE_DIR="$cache/uv-cache" UV_PYTHON_INSTALL_DIR="$cache/interpreters"
export MAMBA_ROOT_PREFIX="$cache/mamba" CONDA_OVERRIDE_OSX=11.0
uv="$cache/bootstrap/uv"
mamba="$cache/bootstrap/micromamba"
if "$restore"; then plan_args+=(--restore-only); reuse_tools=true; fi
if "$reuse_tools"; then
    exec "$cache/build-tools/bin/python" -B "$root/tools/macos_setup.py" "$mode" ${plan_args[@]+"${plan_args[@]}"}
fi
pending=$(mktemp -d "$cache/bootstrap/.install.XXXXXXXX")
trap 'rm -rf -- "$pending"' EXIT
if [[ ! -x "$uv" ]]; then
    curl -fLsS --retry 4 "https://github.com/astral-sh/uv/releases/latest/download/uv-$cpu-apple-darwin.tar.gz" -o "$pending/uv.tgz"
    tar -xf "$pending/uv.tgz" -C "$pending" --strip-components 1 "uv-$cpu-apple-darwin/uv"
    mv "$pending/uv" "$uv"
fi
if [[ ! -x "$mamba" ]]; then
    curl -fLsS --retry 4 "https://micro.mamba.pm/api/micromamba/$subdir/latest" -o "$pending/mamba.tbz"
    tar -xf "$pending/mamba.tbz" -C "$pending" --strip-components 1 bin/micromamba
    mv "$pending/micromamba" "$mamba"
fi
"$uv" python install 3 --no-bin
python=$("$uv" python find --managed-python 3)
"$uv" venv --allow-existing --python "$python" --seed "$cache/build-tools"
"$uv" pip install --python "$cache/build-tools/bin/python" --upgrade \
    aqtinstall cmake ninja Cython meson-python packaging pip setuptools wheel
deps=(zimg zlib libass freetype libpng expat harfbuzz fribidi fontconfig fftw xxhash gmp libboost-devel fmt pugixml libflac libogg libvorbis dav1d-devel libopus
      libplacebo shaderc libvulkan-headers docbook-xsl gettext-tools ruby autoconf automake libtool nasm pkg-config ispc)
operation=create
if [[ -f "$cache/deps/conda-meta/history" ]]; then operation=install; fi
"$mamba" "$operation" --yes --platform "$subdir" --override-channels -c conda-forge \
    -p "$cache/deps" "${deps[@]}"
# Keep the compiler cache tool outside the dependency prefix used for linking.
if ! command -v ccache >/dev/null; then
    operation=create
    if [[ -f "$cache/ccache-tools/conda-meta/history" ]]; then operation=install; fi
    "$mamba" "$operation" --yes --platform "$subdir" --override-channels -c conda-forge -p "$cache/ccache-tools" ccache
fi
"$cache/build-tools/bin/python" -B "$root/tools/macos_setup.py" "$mode" ${plan_args[@]+"${plan_args[@]}"}
