#!/bin/bash
set -euo pipefail

root=$(cd -- "$(dirname -- "$0")/.." && pwd -P)
case "$(dpkg --print-architecture)" in
    amd64) architecture=x64; bcj=--x86 ;;
    arm64) architecture=arm64; bcj=--arm64 ;;
    *) printf '%s\n' 'Ubuntu packaging requires amd64 or arm64.' >&2; exit 1 ;;
esac
output="${1:-$root/dist}"
mkdir -p -- "$output"
output=$(cd -- "$output" && pwd -P)
archive="$output/BluraySubtitle_ubuntu26.04_$architecture.tar.xz"
record="$archive.txt"
if [[ -e "$archive" || -e "$record" ]]; then
    printf 'Output archive already exists: %s\n' "$archive" >&2
    exit 1
fi

stage=$(mktemp -d "$output/.ubuntu-package.XXXXXXXX")
trap 'rm -rf -- "$stage"' EXIT
mkdir "$stage/distro-qt"
qt_path=/usr/lib/python3/dist-packages/PyQt6
if [[ ! -d "$qt_path" ]]; then
    printf '%s\n' "Install Ubuntu's python3-pyqt6 package to build with the shared Qt runtime." >&2
    exit 1
fi
ln -s -- "$qt_path" "$stage/distro-qt/PyQt6"
export PYTHONPATH="$stage/distro-qt${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONPYCACHEPREFIX="$stage/pycache"
export PYINSTALLER_CONFIG_DIR="$stage/pyinstaller"

cd -- "$root"
/usr/bin/python3 -m PyInstaller --distpath "$stage/dist" --workpath "$stage/build" "BluraySubtitle_ubuntu2604_$architecture.spec"
/usr/bin/python3 -B tools/stage_ubuntu_runtime.py "$stage/dist/BluraySubtitle/_internal"
mkdir "$stage/dist/BluraySubtitle/_internal/mpv"
/usr/bin/python3 -B tools/mpv/install.py --bundle-menus "$stage/dist/BluraySubtitle/_internal/resource/mpv"
tar --sort=name -C "$stage/dist" -I "xz -T4 --block-size=128MiB $bcj --lzma2=preset=4,dict=64MiB" \
    -cf "$stage/package.tar.xz" BluraySubtitle
digest=$(sha256sum "$stage/package.tar.xz")
{
    printf 'sha256=%s\n' "${digest%% *}"
    cat "$stage/dist/BluraySubtitle/_internal/build-commit.txt"
} > "$stage/package.txt"
mv --update=none-fail -- "$stage/package.tar.xz" "$archive"
mv --update=none-fail -- "$stage/package.txt" "$record"
printf '%s\n' "$archive"
