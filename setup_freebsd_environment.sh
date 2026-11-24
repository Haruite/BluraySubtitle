#!/bin/sh
set -eu

root=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
mode=Desktop
release=
output="$root/dist"
restore_only=false
while [ "$#" -gt 0 ]; do
    case "$1" in
        --mode) mode=${2:?}; shift ;;
        --release) release=${2:?}; shift ;;
        --output) output=${2:?}; shift ;;
        --restore-only) restore_only=true ;;
        -h|--help)
            printf 'Usage: %s [--mode Desktop|Build] [--release VERSION] [--output DIR] [--restore-only]\n' "$0"
            exit 0 ;;
        *) printf 'Unknown option: %s\n' "$1" >&2; exit 2 ;;
    esac
    shift
done
case "$mode" in Desktop|Build) ;; *) printf 'Unsupported mode: %s\n' "$mode" >&2; exit 2 ;; esac
case "$(uname -s)/$(uname -m)/$(uname -r)" in
    FreeBSD/amd64/14.*|FreeBSD/amd64/15.*) ;;
    *) printf '%s\n' 'FreeBSD 14.x or 15.x amd64 is required / 需要 FreeBSD 14.x 或 15.x amd64' >&2; exit 1 ;;
esac
installed_release=$(uname -r)
installed_release=${installed_release%%-*}
if [ -n "$release" ] && [ "$release" != "$installed_release" ]; then
    printf 'Expected FreeBSD %s, found %s / 构建系统版本不符\n' "$release" "$installed_release" >&2
    exit 1
fi

export BLURAY_SETUP_CACHE_DIR="${BLURAY_SETUP_CACHE_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/bluraysubtitle/freebsd-setup/$installed_release}"
mkdir -p -- "$BLURAY_SETUP_CACHE_DIR"
BLURAY_SETUP_CACHE_DIR=$(realpath -- "$BLURAY_SETUP_CACHE_DIR")
export PATH="/usr/local/bin:/usr/local/sbin:$PATH"

if "$restore_only"; then
    exec "$BLURAY_SETUP_CACHE_DIR/runtime/bin/python3" -B "$root/tools/freebsd_setup.py" "$mode" "$output" --restore-only
fi

mkdir -p -- "$BLURAY_SETUP_CACHE_DIR/packages"
pkg_command() {
    if [ "$(id -u)" -eq 0 ]; then
        env ASSUME_ALWAYS_YES=yes pkg -o "PKG_CACHEDIR=$BLURAY_SETUP_CACHE_DIR/packages" "$@"
    else
        sudo env ASSUME_ALWAYS_YES=yes pkg -o "PKG_CACHEDIR=$BLURAY_SETUP_CACHE_DIR/packages" "$@"
    fi
}

# The default Python flavor of the configured Ports repository supplies the
# interpreter and the native extensions, including PyQt6 and NumPy.
# Keep this list in one install transaction so the solver can update their ABI together.
pkg_command update -q
python_package=$(pkg rquery -U '%dn' python3)
case "$python_package" in python3[0-9]*) ;; *) exit 1 ;; esac
packages=$(tr -d '\r' < "$root/tools/freebsd_packages.txt" | sed "s/^py-/py${python_package#python}-/")
# shellcheck disable=SC2046
pkg_command install -y $packages
exec python3 -B "$root/tools/freebsd_setup.py" "$mode" "$output"
