#!/bin/bash
set -euo pipefail

root=$(cd -- "$(dirname -- "$0")/.." && pwd -P)
apt_arch=$(dpkg --print-architecture)
case "$apt_arch" in
    amd64) architecture=x64 ;;
    arm64) architecture=arm64 ;;
    *) printf '%s\n' 'Linux packaging requires amd64 or arm64.' >&2; exit 1 ;;
esac
output="${1:-$root/dist}"
mkdir -p -- "$output"
output=$(cd -- "$output" && pwd -P)
archive="$output/BluraySubtitle_linux_$architecture.tar.xz"
record="$archive.txt"
if [[ -e "$archive" || -L "$archive" || -e "$record" || -L "$record" ]]; then
    printf 'Output archive already exists: %s\n' "$archive" >&2
    exit 1
fi

# PyInstaller and the private runtime create relative symlinks inside the bundle.
build_tmp=${BLURAY_BUILD_TMP:-${TMPDIR:-/var/tmp}}
mkdir -p -- "$build_tmp"
pending=$(mktemp -d -- "$output/.linux-publish.XXXXXXXX")
trap 'rm -rf -- "$pending"' EXIT
stage=$(cd -- "$build_tmp" && mktemp -d -- "$PWD/.linux-package.XXXXXXXX")
trap 'rm -rf -- "$stage" "$pending"' EXIT
if ! ln -s . "$stage/symlink-check"; then
    printf '%s\n' 'Set BLURAY_BUILD_TMP to a Linux directory that supports symbolic links.' \
        '请将 BLURAY_BUILD_TMP 设为支持符号链接的 Linux 目录。' >&2
    exit 1
fi
export TMPDIR="$stage"
export BLURAY_SETUP_CACHE_DIR="${BLURAY_SETUP_CACHE_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/bluraysubtitle/linux-setup}"
uosc_archive="$BLURAY_SETUP_CACHE_DIR/mpv-uosc-$apt_arch.tar.gz"
if [[ ! -s "$uosc_archive" ]]; then
    printf '%s\n' 'Run setup_linux_environment.sh --mode Build to prepare the packaged uosc release.' >&2
    exit 1
fi
mapfile -t build_environment < "$BLURAY_SETUP_CACHE_DIR/build-environment-$apt_arch"
python="${build_environment[0]}"
export BLURAY_QT66_PREFIX="${build_environment[1]}" BLURAY_QT_TOOLS="${build_environment[2]}"
export BLURAY_SUBTITLE_CONFIG_DIR="$stage/config"
mkdir "$stage/uosc" "$stage/package" "$stage/package/BluraySubtitle"
tar -xzf "$uosc_archive" -C "$stage/uosc"
unset PYTHONPATH PYTHONHOME LD_LIBRARY_PATH
export PYTHONPYCACHEPREFIX="$stage/pycache"
export PYINSTALLER_CONFIG_DIR="$stage/pyinstaller"

cd -- "$root"
"$python" -m PyInstaller --distpath "$stage/dist" --workpath "$stage/build" "BluraySubtitle_linux_$architecture.spec"
bundle="$stage/package/BluraySubtitle"
mv -- "$stage/dist/BluraySubtitle" "$bundle/_internal"
"$python" -B tools/stage_linux_runtime.py "$bundle/_internal" "$stage/uosc"
install -m 0755 tools/launch_linux_app.sh "$bundle/BluraySubtitle"
# Plain LZMA2 with a 4 MiB dictionary and CRC32 works with early XZ decoders.
XZ_DEFAULTS= XZ_OPT= tar --sort=name -C "$stage/package" -I 'xz -T4 --check=crc32 -4' \
    -cf "$pending/package.tar.xz" BluraySubtitle
digest=$(sha256sum "$pending/package.tar.xz")
{
    printf 'sha256=%s\n' "${digest%% *}"
    cat "$bundle/_internal/build-commit.txt"
} > "$pending/package.txt"
# Publish on the output filesystem so the final archive becomes visible in one rename.
mv -T --update=none-fail -- "$pending/package.txt" "$record"
if ! mv -T --update=none-fail -- "$pending/package.tar.xz" "$archive"; then
    rm -f -- "$record"
    exit 1
fi
printf '%s\n' "$archive"
