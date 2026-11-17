"""RIFE files shared by Linux setup and mpv's VapourSynth presets."""

from platform import machine


RIFE_LIBRARY = "librife_linux_aarch64.so" if machine() in ("aarch64", "arm64") else "librife_linux_x86-64.so"
RIFE_MODEL_DIR = "models/rife-v4.6_ensembleFalse"
RIFE_FILES = (RIFE_LIBRARY, f"{RIFE_MODEL_DIR}/flownet.bin", f"{RIFE_MODEL_DIR}/flownet.param")


if __name__ == "__main__":
    print(RIFE_LIBRARY, RIFE_MODEL_DIR)
