"""RIFE files used by desktop setup and mpv's VapourSynth presets."""

from platform import machine
import sys


_PLATFORM = "freebsd" if sys.platform.startswith("freebsd") else "linux"
_ARCHITECTURE = "aarch64" if machine() in ("aarch64", "arm64") else "x86-64"
RIFE_LIBRARY = f"librife_{_PLATFORM}_{_ARCHITECTURE}.so"
RIFE_MODEL_DIR = "models/rife-v4.6_ensembleFalse"
RIFE_FILES = (RIFE_LIBRARY, f"{RIFE_MODEL_DIR}/flownet.bin", f"{RIFE_MODEL_DIR}/flownet.param")


if __name__ == "__main__":
    print(RIFE_LIBRARY, RIFE_MODEL_DIR)
