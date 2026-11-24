#!/bin/sh
set -eu

executable=$(realpath -- "$0")
runtime="$(dirname -- "$executable")/_internal"
exec "$runtime/bin/python3" -I -B "$runtime/app/entry.py" "$@"
