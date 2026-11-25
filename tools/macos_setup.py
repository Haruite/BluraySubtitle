"""Install the macOS source environment or produce a verified architecture-specific archive."""

import argparse
import fcntl
import json
import os
import shlex
import shutil
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core.app_config import app_config_path
from src.core.tool_paths import MKVTOOLNIX_TOOLS, TOOL_DIRECTORY_NAMES, portable_runtime_paths
from tools.macos_build_support import ROOT, Build, message, run
from tools.macos_bundle import archive, archive_name, assemble, build_assets
from tools.macos_media import build_media, hdr_providers, releases
from tools.macos_plugins import build_plugins, plugin_releases
from tools.macos_python_runtime import build_python, python_releases
from tools.setup_tool_paths import prepare_tool_paths, read_tool_paths
from tools.vapoursynth_plugin_releases import SOURCES, PluginRelease, latest_tag


def desktop(ctx, target: Path, config_path: Path, configured: dict[str, str]) -> None:
    from src.runtime.macos_shortcuts import refresh_source_launchers

    directory = target.parent
    directory.mkdir(parents=True, exist_ok=True)
    if target.exists() and not (target / "runtime.json").is_file():
        raise FileExistsError(f"Existing unmanaged directory: {target}")
    with tempfile.TemporaryDirectory(dir=directory) as tmp:
        work = Path(tmp)
        staged = work / "Runtime"
        assemble(ctx, staged)
        launcher = staged / "bin/BluraySubtitle"
        launcher.write_text(
            '#!/bin/sh\nset -eu\nruntime=$(cd "$(dirname "$0")/.." && pwd)\n'
            f"default_config={shlex.quote(str(config_path.parent))}\n"
            'export BLURAY_SUBTITLE_CONFIG_DIR="${BLURAY_SUBTITLE_CONFIG_DIR:-$default_config}"\n'
            f'exec "$runtime/python/bin/python3" -I -B {shlex.quote(str(ROOT / "tools/macos_entry.py"))} "$@"\n'
        )
        launcher.chmod(0o755)
        from tools.verify_macos_package import verify_runtime

        verify_runtime(staged)
        old = work / "previous"
        if target.exists():
            target.rename(old)
        try:
            staged.rename(target)
        except OSError:
            if old.exists():
                old.rename(target)
            raise
    refresh_source_launchers(target)
    # Explicit user paths can point to independently maintained programs. Populate
    # missing destinations with links into the verified installation.
    defaults = portable_runtime_paths(target)
    links = [(Path(configured[name]), src) for name, src in defaults.items() if name not in TOOL_DIRECTORY_NAMES]
    mkv_directory = Path(configured["MKVTOOLNIX_PATH"])
    links.extend((mkv_directory / program, defaults["MKVTOOLNIX_PATH"] / program) for program in MKVTOOLNIX_TOOLS.values())
    plugin_directory = Path(configured["PLUGIN_PATH"])
    links.extend((plugin_directory / src.name, src) for src in defaults["PLUGIN_PATH"].iterdir())
    for dest, src in links:
        if dest == src or dest.exists():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.symlink_to(src)
    print(
        message("Start the source application with {launcher}", launcher=target / "bin/BluraySubtitle"),
        flush=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("Desktop", "Build"))
    parser.add_argument("--restore-only", action="store_true")
    plans = parser.add_mutually_exclusive_group()
    plans.add_argument("--plan", type=Path, help="Write the resolved source versions and exact component keys")
    plans.add_argument("--from-plan", type=Path, help="Build the versions selected before restoring Actions caches")
    args = parser.parse_args()
    cache = Path(os.environ["BLURAY_SETUP_CACHE_DIR"]).expanduser().resolve()
    with (cache / "setup.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if args.mode == "Desktop" and args.plan is None:
            runtime = Path.home() / "Library/Application Support/BluraySubtitle/Runtime"
            config_path = app_config_path()
            defaults = {name: str(path) for name, path in portable_runtime_paths(runtime).items()}
            try:
                config_path.parent.mkdir(parents=True, exist_ok=True)
                if prepare_tool_paths(config_path, defaults=defaults):
                    input(message("Edit config.json to change any paths. Press Enter when ready to continue.") + "\n")
                locale = os.environ.get("BLURAY_LANG") or os.environ.get("LANG", "en")
                _, configured = read_tool_paths(config_path, "zh" if locale.lower().startswith("zh") else "en")
            except EOFError:
                parser.exit(1, message("Tool paths were not confirmed.") + "\n")
            except (OSError, ValueError) as error:
                parser.exit(1, message("Could not read setup tool paths from {path}. {error}",
                                       path=config_path, error=error) + "\n")
        plan = json.loads(args.from_plan.read_text()) if args.from_plan else None
        ctx = Build(cache, args.restore_only, planning=bool(args.plan), expected=plan["components"] if plan else None)
        dest = Path(os.environ.get("BLURAY_MACOS_OUTPUT_DIR", ROOT / "dist")).resolve()
        if args.mode == "Build" and not ctx.planning:
            name = archive_name(ctx.arch)
            for target in (dest / name, dest / (name + ".txt")):
                if target.exists() or target.is_symlink():
                    raise FileExistsError(target)
        versions_file = cache / "source-versions.json"
        if plan or args.restore_only:
            recorded = plan["sources"] if plan else json.loads(versions_file.read_text())
            python = recorded["python"]
            media = recorded["media"]
            if "ispc" not in recorded or (ctx.arch == "arm64" and "sse2neon" not in media):
                raise ValueError("The saved sources predate build dependency tracking. Run setup again to resolve a new build plan.")
            ctx.ispc_version = recorded["ispc"]
            ctx.hdr = recorded.get("hdr") or hdr_providers(ctx, media, offline=True)
            filters = {k: PluginRelease(**v) for k, v in recorded["plugins"].items()}
        else:
            ctx.ispc_version = latest_tag(SOURCES["ispc"]).removeprefix("v")
            python = python_releases(ctx.arch)
            media = releases(ctx.arch)
            ctx.hdr = hdr_providers(ctx, media)
            filters = plugin_releases()
        if not ctx.planning:
            ctx.start_install()
        build_python(ctx, python)
        build_media(ctx, media)
        build_plugins(ctx, filters)
        sources = {"python": python, "media": media, "hdr": ctx.hdr, "ispc": ctx.ispc_version,
                   "plugins": {k: asdict(v) for k, v in filters.items()}}
        build_assets(ctx, args.mode)
        if args.plan:
            args.plan.write_text(json.dumps({"sources": sources, "components": ctx.built}, sort_keys=True) + "\n")
            return
        if plan and ctx.built != plan["components"]:
            raise ValueError("The build components changed after resolving the cache plan")
        ctx.versions = sources
        if args.mode == "Desktop":
            desktop(ctx, runtime, config_path, configured)
        else:
            from tools.verify_macos_package import verify_archive

            dest.mkdir(parents=True, exist_ok=True)
            # Build and sign locally. SMB output volumes need only store the verified files.
            with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory(dir=dest) as incoming:
                package = archive(ctx, Path(temporary))
                verify_archive(package)
                record = package.with_suffix(".zip.txt")
                for path in (package, record):
                    shutil.copy(path, Path(incoming) / path.name)
                place = ("/usr/bin/osascript", "-l", "JavaScript", ROOT / "src/runtime/macos_files.js", "place")
                final = dest / package.name
                run(*place, Path(incoming) / package.name, final)
                try:
                    run(*place, Path(incoming) / record.name, dest / record.name)
                except BaseException:
                    final.unlink()
                    raise
            print(message("Verified archive {path}", path=final), flush=True)
        for record, data in ((versions_file, sources), (cache / "verified-components.json", ctx.built)):
            pending = record.with_suffix(".tmp")
            pending.write_text(json.dumps(data, sort_keys=True, indent=2) + "\n")
            pending.replace(record)


if __name__ == "__main__":
    main()
