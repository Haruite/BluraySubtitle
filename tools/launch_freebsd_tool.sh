#!/bin/sh
set -eu

executable=$(realpath -- "$0")
runtime=$(dirname -- "$(dirname -- "$executable")")
program=${executable##*/}
if [ -z "${BLURAYSUB_FREEBSD_LIBRARY_PATH+x}" ]; then
    export BLURAYSUB_FREEBSD_LIBRARY_PATH="${LD_LIBRARY_PATH:-}"
fi
export LD_LIBRARY_PATH="$runtime/lib${BLURAYSUB_FREEBSD_LIBRARY_PATH:+:$BLURAYSUB_FREEBSD_LIBRARY_PATH}"

case "$program" in
    python3|vspipe|mpv|vsedit)
        unset PYTHONPATH PYTHONHOME
        export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
        export VAPOURSYNTH_EXTRA_PLUGIN_PATH="${VAPOURSYNTH_EXTRA_PLUGIN_PATH-${BLURAYSUB_PLUGIN_PATH:-$runtime/plugins}}"
        ;;
esac
case "$program" in
    python3|vsedit)
        export QT_PLUGIN_PATH="$runtime/qt"
        unset QT_QPA_PLATFORM_PLUGIN_PATH
        ;;
esac
case "$program" in
    python3) exec "$runtime/python/bin/python3" "$@" ;;
    vspipe)
        set -- "$runtime"/python/lib/python*/site-packages/vapoursynth/vspipe "$@"
        exec "$@" ;;
    vsedit)
        for library in "$runtime"/python/lib/python*/site-packages/vapoursynth/libvsscript.so; do
            export VSSCRIPT_PATH="$library"
        done
        ;;
    mpv)
        export MPV_HOME="${MPV_HOME:-$runtime/mpv}"
        export BLURAYSUB_MPV_CONFIG_PATH="${BLURAYSUB_MPV_CONFIG_PATH:-$MPV_HOME}"
        export MPV_UOSC_ZIGGY="${MPV_UOSC_ZIGGY:-$runtime/mpv/scripts/uosc/bin/ziggy-freebsd}"
        export PATH="$runtime/bin:$PATH"
        ;;
esac
exec "$runtime/libexec/$program" "$@"
