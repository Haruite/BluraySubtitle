#!/bin/sh
set -eu
# Keep the invocation name when resolving the symlink to the common launcher.
tool=${0##*/}
launcher=$(readlink -f -- "$0")
native=${launcher%/bin/launch-tool}
support=${native%/linux}
bundle=${support%/_internal}
. "$native/runtime.sh"
unset LD_LIBRARY_PATH_ORIG QT_PLUGIN_PATH QT_QPA_PLATFORM_PLUGIN_PATH QML2_IMPORT_PATH QML_IMPORT_PATH
if [ -x "$native/static/$tool" ]; then exec "$native/static/$tool" "$@"; fi
if [ -d "$native/glibc/gconv" ]; then export GCONV_PATH="$native/glibc/gconv"; fi
search="$native/glibc:$native/lib:$support${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}$driver_search"
executable="$native/libexec/$tool"
case "$tool" in
    vsedit|mkvinfo|mkvmerge|mkvpropedit|mkvextract)
        select_linux_qt "$tool"
        search="$native/glibc:$qt_prefix/lib:$native/lib:$support${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}$driver_search"
        export QT_PLUGIN_PATH="$qt_prefix/plugins" QT_QPA_PLATFORM_PLUGIN_PATH="$qt_prefix/plugins/platforms"
        ;;
esac
case "$tool" in
    ffmpeg|ffprobe|mpv|vsedit|vspipe|python3) set_video_driver_paths ;;
esac
case "$tool" in
    mpv|ffmpeg|ffprobe)
        # The private PipeWire client must use its matching SPA plugins and protocol modules.
        export PIPEWIRE_CONFIG_DIR="$native/pipewire"
        export PIPEWIRE_MODULE_DIR="$native/pipewire/pipewire-0.3" SPA_PLUGIN_DIR="$native/pipewire/spa-0.2"
        ;;
esac
case "$tool" in
    mkvinfo|mkvmerge|mkvpropedit|mkvextract)
        # A musl or Nix host may have UTF-8 locales that the private glibc cannot read.
        if ! "$loader" --library-path "$search" "$native/glibc/check-locale"; then
            export LC_ALL=C.UTF-8 LOCPATH="$native/glibc/locale"
        fi
        ;;
esac
case "$tool" in
    python3|mpv|vsedit|vspipe)
        export PYTHONHOME="$native/python" PYTHONPATH="$support" PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
        if [ "$tool" = python3 ]; then
            export VAPOURSYNTH_EXTRA_PLUGIN_PATH="${BLURAYSUB_PLUGIN_PATH-${VAPOURSYNTH_EXTRA_PLUGIN_PATH-$native/plugins}}"
            exec "$loader" --library-path "$search" "$PYTHONHOME/libexec/python3" "$@"
        fi
        if [ "$tool" = mpv ]; then
            export MPV_HOME="${BLURAYSUB_MPV_CONFIG_PATH:-$support/mpv}"
            set -- "--config-dir=$MPV_HOME" "$@"
        fi
        export XDG_CONFIG_HOME="${BLURAY_SUBTITLE_CONFIG_DIR:-$bundle}/.vsscript"
        export VSSCRIPT_PATH="$support/vapoursynth/libvsscript.so"
        export BLURAYSUB_PLUGIN_PATH="${BLURAYSUB_PLUGIN_PATH-$native/plugins}"
        export VAPOURSYNTH_EXTRA_PLUGIN_PATH="$BLURAYSUB_PLUGIN_PATH"
        search="$support/vapoursynth:$search"
        "$loader" --library-path "$search" "$PYTHONHOME/libexec/python3" "$native/write_linux_vsscript_config.py" "$tool"
        if [ "$tool" = vspipe ]; then executable="$support/vapoursynth/vspipe"; fi
        ;;
esac
exec "$loader" --library-path "$search" "$executable" "$@"
