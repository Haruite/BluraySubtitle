#!/bin/bash
set -u
work=$1
app=$2
failure=$3
restart_failed=$4
incoming="$work/incoming/BluraySubtitle.app"
launcher="$app/Contents/MacOS/BluraySubtitle"
exchanged=false

exchange() {
    /usr/bin/osascript -l JavaScript "$work/macos_files.js" exchange "$app" "$incoming"
}

launch() {
    local problem=$1 count
    /bin/rm -f "$work/ready"
    BLURAY_SUBTITLE_UPDATE_READY="$work/ready" BLURAY_SUBTITLE_GUI_READY="$work/ready" BLURAY_SUBTITLE_UPDATE_ERROR="$problem" \
        "$launcher" --detached-gui 9>&- </dev/null >/dev/null 2>&1 &
    local pid=$!
    for ((count=0; count<300; count++)); do
        [[ -f "$work/ready" ]] && return 0
        kill -0 "$pid" 2>/dev/null || return 1
        /bin/sleep 0.2
    done
    kill "$pid" 2>/dev/null || true
    for ((count=0; count<15; count++)); do
        kill -0 "$pid" 2>/dev/null || break
        /bin/sleep 0.2
    done
    kill -KILL "$pid" 2>/dev/null || true
    wait "$pid" 2>/dev/null || true
    return 1
}

if [[ ! -f "$work/failure.txt" ]]; then
    if exchange; then
        exchanged=true
        if launch ""; then
            cd / && /bin/rm -rf -- "$work"
            exit 0
        fi
        printf '%s\n%s\n' "$failure" "$restart_failed" > "$work/failure.txt"
    else
        printf '%s\n' "$failure" > "$work/failure.txt"
    fi
fi
if "$exchanged" && ! exchange; then exit 1; fi
if launch "$(/bin/cat "$work/failure.txt")"; then
    cd / && /bin/rm -rf -- "$work"
fi
exit 1
