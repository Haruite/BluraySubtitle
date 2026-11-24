"""Install the FreeBSD desktop runtime or make the FreeBSD amd64 archive."""

import argparse
import fcntl
import json
import os
from pathlib import Path
import shlex
import shutil
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core.app_config import app_config_path, load_app_config
from src.core.tool_paths import (
    MKVTOOLNIX_TOOLS, TOOL_DIRECTORY_NAMES, default_mpv_config_directory, portable_runtime_paths, resolve_tool_paths,
)
from src.core.version import git_commit_record
from tools.freebsd_build import FreeBSDBuild, ROOT, build_source_tools
from tools.freebsd_bundle import ARCHIVE, archive, stage_application, stage_runtime
from tools.macos_build_support import digest, fingerprint, message, output
from tools.mpv import install as mpv_config
from tools.verify_freebsd_package import verify_package, verify_runtime


def runtime_recipe():
    files = [ROOT / "setup_freebsd_environment.sh", ROOT / "LICENSE", ROOT / "tools/macos_build_support.py",
             ROOT / "tools/macos_media.py", ROOT / "tools/lsmash_ffmpeg_compat.py",
             ROOT / "tools/macos_python_runtime.py", ROOT / "tools/update_third_party_notices.py",
             ROOT / "tools/vapoursynth_plugin_releases.py", ROOT / "tools/vapoursynth_plugin_versions.py"]
    for pattern in ("tools/freebsd_*", "tools/launch_freebsd_*", "tools/mpv/**/*", "legal/freebsd/*",
                    "third_party/vapoursynth_scripts/**/*", "third_party/mpv_lazy_shaders/**/*", "resource/mpv/*"):
        files.extend(path for path in ROOT.glob(pattern) if path.is_file() and "__pycache__" not in path.parts)
    release = output("freebsd-version", "-u")
    return fingerprint([release, sorted((str(path.relative_to(ROOT)), digest(path)) for path in files)])


def replace_runtime(staged: Path, destination: Path):
    previous = staged.parent / "previous"
    if os.path.lexists(destination):
        if destination.is_symlink() or not (destination / "runtime.json").is_file():
            raise FileExistsError(f"Existing unmanaged runtime: {destination}")
        destination.rename(previous)
    try:
        staged.rename(destination)
    except OSError:
        if previous.exists():
            previous.rename(destination)
        raise


def install_desktop(runtime: Path):
    config_path = app_config_path()
    config = load_app_config(config_path)
    configured = resolve_tool_paths(config.tools, config_path.parent, discover=False)
    data = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
    directory = data / "bluraysubtitle"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "freebsd"
    with tempfile.TemporaryDirectory(dir=directory, prefix=".freebsd-install-") as tmp:
        work = Path(tmp)
        staged = work / "install"
        staged.mkdir()
        installed = staged / "_internal"
        shutil.copytree(runtime, installed, symlinks=True)
        stage_application(installed, git_commit_record(ROOT))
        launcher = staged / "BluraySubtitle"
        launcher.write_text("#!/bin/sh\n" + f"export BLURAY_FREEBSD_SOURCE={shlex.quote(str(ROOT))}\n"
                            + (ROOT / "tools/launch_freebsd_app.sh").read_text().split("\n", 1)[1])
        launcher.chmod(0o755)
        # Mark the top-level installation before an atomic replacement.
        shutil.copyfile(installed / "runtime.json", staged / "runtime.json")
        replace_runtime(staged, target)
    defaults = portable_runtime_paths(target / "_internal")
    links = {Path(configured[name]): path for name, path in defaults.items()
             if name not in TOOL_DIRECTORY_NAMES and configured.get(name)}
    if root := configured.get("MKVTOOLNIX_PATH"):
        links.update({Path(root) / file: defaults["MKVTOOLNIX_PATH"] / file for file in MKVTOOLNIX_TOOLS.values()})
    if root := configured.get("PLUGIN_PATH"):
        links.update({Path(root) / path.name: path for path in defaults["PLUGIN_PATH"].iterdir()})
    for destination, origin in links.items():
        if not os.path.lexists(destination):
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.symlink_to(origin)
    assets = defaults["MPV_CONFIG_PATH"]
    mpv_directory = Path(configured["MPV_CONFIG_PATH"]) if configured.get("MPV_CONFIG_PATH") else default_mpv_config_directory()
    mpv_directory.mkdir(parents=True, exist_ok=True)
    mpv_config.install_uosc(assets, mpv_directory, binary="bin/ziggy-freebsd")
    menu = mpv_config.read_text(mpv_directory / "menu.conf")
    player = str(defaults["MPV_PATH"])
    plugins = Path(configured.get("PLUGIN_PATH") or defaults["PLUGIN_PATH"])
    language = "zh" if config.ui.language == "zh" else "en"
    for path, content in mpv_config.desktop_files(mpv_directory, language, plugins, menu or mpv_config.default_menu(player)).items():
        mpv_config.write_if_changed(path, content)
    for path in (mpv_config.LAZY_PROFILES, "bluray-defaults.conf",
                 *(f"{mpv_config.SHADER_PATH}/{name}" for name, _ in mpv_config.SHADERS)):
        if not (mpv_directory / path).exists():
            mpv_config.write_if_changed(mpv_directory / path, (assets / path).read_bytes())
    from src.runtime.desktop_integration import desktop_entry_id, write_desktop_entry

    entry_id = desktop_entry_id(target)
    write_desktop_entry(data / "applications" / f"{entry_id}.desktop", [str(target / "BluraySubtitle")],
                        target, "BluraySubtitle", ROOT / "resource/bluraysubtitle.svg", entry_id)
    print(message("Start the source application with {launcher}", launcher=target / "BluraySubtitle"), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("Desktop", "Build"))
    parser.add_argument("destination", type=Path)
    parser.add_argument("--restore-only", action="store_true")
    args = parser.parse_args()
    cache = Path(os.environ["BLURAY_SETUP_CACHE_DIR"])
    runtime = cache / "runtime"
    recipe = runtime_recipe()
    if args.mode == "Build":
        for path in (args.destination / ARCHIVE, args.destination / (ARCHIVE + ".txt")):
            if os.path.lexists(path):
                raise FileExistsError(path)
    with (cache / "setup.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        record_file = runtime / "runtime.json"
        record = json.loads(record_file.read_text()) if record_file.is_file() else {}
        if args.restore_only:
            if record.get("recipe") != recipe:
                raise ValueError("The restored FreeBSD runtime was built with different recipes")
        else:
            ctx = FreeBSDBuild(cache)
            ctx.start_install()
            sources = build_source_tools(ctx)
            version_key = fingerprint(ctx.system_packages)
            if (record.get("recipe"), record.get("components"), record.get("ports")) != (recipe, ctx.built, version_key):
                with tempfile.TemporaryDirectory(dir=cache, prefix=".runtime-") as tmp:
                    work = Path(tmp)
                    staged = work / "runtime"
                    staged.mkdir()
                    stage_runtime(ctx, staged, sources, recipe)
                    manifest = staged / "runtime.json"
                    current = json.loads(manifest.read_text())
                    manifest.write_text(json.dumps({**current, "ports": version_key}, sort_keys=True) + "\n")
                    verify_runtime(staged, work)
                    replace_runtime(staged, runtime)
        if args.mode == "Build":
            path = archive(runtime, args.destination.resolve(), verify_package)
            print(message("Verified archive {path}", path=path), flush=True)
        else:
            install_desktop(runtime)


if __name__ == "__main__":
    main()
