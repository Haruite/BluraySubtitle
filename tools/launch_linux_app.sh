#!/bin/sh
set -eu
self=$(readlink -f -- "$0")
support=${self%/*}/_internal
. "$support/linux/runtime.sh"
select_linux_qt
# The PyInstaller bootloader re-execs the private loader once, without its arguments.
# Preserve the host setting separately for host shells, browsers and other child processes.
if [ "${LD_LIBRARY_PATH+x}" = x ]; then
    export BLURAY_HOST_LIBRARY_PATH="$LD_LIBRARY_PATH"
else
    unset BLURAY_HOST_LIBRARY_PATH
fi
export LD_LIBRARY_PATH="$native/glibc:$qt_prefix/lib:$support${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}$driver_search"
export BLURAY_QT_PACKAGE="$qt_package" BLURAY_LINUX_ENTRY="$self"
exec "$loader" "$support/BluraySubtitle" "$@"
