#!/bin/sh
set -eu

bin_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
native=$(dirname -- "$bin_dir")
support=$(dirname -- "$native")
bundle=$(dirname -- "$support")
tool=${0##*/}
executable="$native/libexec/$tool"

unset QT_PLUGIN_PATH QT_QPA_PLATFORM_PLUGIN_PATH QML2_IMPORT_PATH QML_IMPORT_PATH LD_LIBRARY_PATH_ORIG
export LD_LIBRARY_PATH="$native/lib:$support"
case "$tool" in
    mpv|vsedit|vspipe)
        if [ "$tool" = mpv ]; then
            export MPV_HOME="${BLURAYSUB_MPV_CONFIG_PATH:-$support/mpv}"
            set -- "--config-dir=$MPV_HOME" "$@"
        fi
        export PYTHONHOME="$native/python"
        export PYTHONPATH="$support"
        export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
        export LD_LIBRARY_PATH="$support/vapoursynth:$LD_LIBRARY_PATH"
        export XDG_CONFIG_HOME="${BLURAY_SUBTITLE_CONFIG_DIR:-$bundle}/.vsscript"
        export VSSCRIPT_PATH="$support/vapoursynth/libvsscript.so"
        export BLURAYSUB_PLUGIN_PATH="${BLURAYSUB_PLUGIN_PATH-$native/plugins}"
        export VAPOURSYNTH_EXTRA_PLUGIN_PATH="$BLURAYSUB_PLUGIN_PATH"
        "$PYTHONHOME/bin/python3.14" "$native/write_ubuntu_vsscript_config.py" "$tool"
        if [ "$tool" = vspipe ]; then
            executable="$support/vapoursynth/vspipe"
        elif [ "$tool" = vsedit ]; then
            export QT_PLUGIN_PATH="$native/qt-plugins"
            export QT_QPA_PLATFORM_PLUGIN_PATH="$native/qt-plugins/platforms"
        fi
        ;;
esac

exec "$executable" "$@"
