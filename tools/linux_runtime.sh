#!/bin/sh
# Sourced while the process still uses the host environment.
# $support is the absolute _internal directory.
native="$support/linux"
loader="$native/glibc/ld.so"

if [ -f "$native/glibc/ld-linux-x86-64.so.2" ]; then
    "$loader" --library-path "$native/glibc" "$native/glibc/check-x86-64-v3" || {
        status=$?
        if [ "$status" -eq 64 ]; then
            case "${LC_ALL:-${LC_MESSAGES:-${LANG:-}}}" in
                zh*) printf '%s\n' 'BluraySubtitle 的 Linux x64 包需要 Haswell 级 CPU（x86-64-v3）。' >&2 ;;
                *) printf '%s\n' 'The BluraySubtitle Linux x64 package requires a Haswell-class CPU (x86-64-v3).' >&2 ;;
            esac
        fi
        exit "$status"
    }
fi

# NixOS exposes the active graphics driver outside the ELF loader's default paths.
driver_search=
if [ -d /run/opengl-driver/lib ]; then driver_search=:/run/opengl-driver/lib; fi

set_video_driver_paths() {
    # The bundled VA-API and VDPAU clients were built with Ubuntu's multiarch paths.
    if [ -f "$native/glibc/ld-linux-x86-64.so.2" ]; then
        multiarch=x86_64-linux-gnu
    else
        multiarch=aarch64-linux-gnu
    fi
    for dir in /run/opengl-driver/lib "/usr/lib/$multiarch" /usr/lib64 /usr/lib; do
        if [ -z "${LIBVA_DRIVERS_PATH+x}" ] && [ -d "$dir/dri" ]; then
            export LIBVA_DRIVERS_PATH="$dir/dri"
        fi
        if [ -z "${VDPAU_DRIVER_PATH+x}" ] && [ -d "$dir/vdpau" ]; then
            export VDPAU_DRIVER_PATH="$dir/vdpau"
        fi
    done
}

kernel_at_least() {
    [ "$1" -gt "$4" ] || { [ "$1" -eq "$4" ] && {
        [ "$2" -gt "$5" ] || { [ "$2" -eq "$5" ] && [ "$3" -ge "$6" ]; }
    }; }
}

select_linux_qt() {
    # VSEdit needs the Qt libraries and platform plugins from its 6.6.3 build SDK.
    qt_branch=6.6
    if [ "${1:-}" != vsedit ]; then
        IFS= read -r release < /proc/sys/kernel/osrelease
        release=${release%%[!0-9.]*}
        major=${release%%.*}
        tail=${release#*.}
        minor=${tail%%[!0-9]*}
        patch=0
        case "$tail" in *.*) tail=${tail#*.}; patch=${tail%%[!0-9]*} ;; esac
        read -r qt_major qt_minor qt_patch < "$native/qt/latest/minimum-kernel"
        if kernel_at_least "$major" "$minor" "${patch:-0}" "$qt_major" "$qt_minor" "$qt_patch"; then
            qt_branch=latest
        fi
    fi
    qt_package="$native/qt/$qt_branch"
    qt_prefix="$qt_package/PyQt6/Qt6"
}
