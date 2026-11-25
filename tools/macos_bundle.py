"""Assemble and relocate a native Big Sur runtime and its Finder application."""

import json
import os
import plistlib
import shutil
import sys
import tempfile
from collections import deque
from pathlib import Path

from tools.macos_build_support import ROOT, copy, digest, output, recipe_digest, run
from tools.macos_macho import inspect_macho
from tools.macos_python_runtime import PYLIB, SITE

SYSTEM = ("/usr/lib/", "/System/Library/")
PROGRAMS = (
    "7zz",
    "ffmpeg",
    "ffprobe",
    "bluraysub-gpu-capabilities",
    "x264",
    "x265",
    "SvtAv1EncApp",
    "flac",
    "fdkaac",
    "dovi_tool",
    "hdr10plus_tool",
    "tsMuxeR",
    "mkvmerge",
    "mkvinfo",
    "mkvpropedit",
    "mkvextract",
)


def relocation(ctx, root):
    root = root.resolve(strict=True)
    sources = {}
    aliases = {}
    for prefix in (ctx.prefix / "lib", ctx.deps / "lib"):
        for item in prefix.glob("*.dylib"):
            aliases.setdefault(item.name, item)

    def vendor(src):
        src = src.resolve(strict=True)
        target = root / "lib" / src.name
        if target in sources and sources[target] != src:
            if digest(sources[target]) != digest(src):
                raise ValueError(f"Conflicting native libraries: {src} and {sources[target]}")
        if not target.exists():
            copy(src, target)
        sources[target] = src
        return target

    for lib in ("libass.dylib", "libvulkan.1.dylib", "libMoltenVK.dylib"):
        target = vendor(aliases[lib])
        if target.name != lib:
            (root / "lib" / lib).symlink_to(target.name)
    queue = deque(p for p in root.rglob("*") if not p.is_symlink() and p.is_file())
    finished = set()
    latest = (11, 0, 0)
    while queue:
        file = queue.popleft()
        if file in finished:
            continue
        finished.add(file)
        info = inspect_macho(file, ctx.arch)
        if info is None:
            continue
        rel = file.relative_to(root)
        branch = rel.parts[1] if rel.parts[0] == "qt" else "6.6"
        qtlib = root / "qt" / branch / "PyQt6/Qt6/lib"
        if branch == "latest":
            latest = max(latest, info.minimum)
        elif info.minimum > (11, 0, 0):
            raise ValueError(f"{rel} requires macOS {info.minimum}, expected 11.0")
        file.chmod(file.stat().st_mode | 0o200)
        if info.universal:
            temp = file.with_name(file.name + ".thin")
            run("lipo", file, "-thin", ctx.arch, "-output", temp)
            temp.chmod(file.stat().st_mode)
            temp.replace(file)
        changes = []
        original = sources.get(file, ctx.prefix / rel)
        for name in info.loads:
            if name.startswith(SYSTEM):
                continue
            tail = name.removeprefix("@rpath/")
            if ".framework/" in name:
                parts = Path(name).parts
                index = next(i for i, s in enumerate(parts) if s.endswith(".framework"))
                dest = qtlib.joinpath(*parts[index:])
                if not dest.exists():
                    raise ValueError(f"Missing framework for {rel}: {name}")
            else:
                candidates = []
                if name.startswith("@loader_path/"):
                    local = name.removeprefix("@loader_path/")
                    candidates.extend((file.parent / local, original.parent / local))
                elif name.startswith("/"):
                    candidates.append(Path(name))
                elif name.startswith("@rpath/"):
                    for rpath in info.rpaths:
                        for parent in (file.parent, original.parent):
                            expanded = rpath.replace("@loader_path", str(parent))
                            if expanded.startswith("/"):
                                candidates.append(Path(expanded) / tail)
                    candidates.extend((file.parent / tail, root / "python/lib" / tail, qtlib / tail))
                candidates.extend((root / "lib" / Path(name).name, aliases.get(Path(name).name)))
                found = next((x.resolve() for x in candidates if x is not None and x.is_file()), None)
                if found is None:
                    raise ValueError(f"Unresolved {name} in {rel}")
                dest = found if found.is_relative_to(root) else vendor(found)
            queue.append(dest.resolve())
            wanted = "@loader_path/" + os.path.relpath(dest, file.parent)
            if name != wanted:
                changes.extend(["-change", name, wanted])
        if info.install_id.startswith("/") and not info.install_id.startswith(SYSTEM):
            changes.extend(["-id", file.name])
        for rpath in set(info.rpaths):
            if rpath.startswith("/") and not rpath.startswith(SYSTEM):
                changes.extend(["-delete_rpath", rpath])
        if changes:
            run("install_name_tool", *changes, file)
        run("codesign", "--force", "--sign", "-", file)
    # Conda stores the upstream notices next to its extracted packages. Collect
    # them for the libraries that actually entered this architecture's runtime.
    vendored = {str(p.relative_to(ctx.deps)) for p in sources.values() if p.is_relative_to(ctx.deps)}
    conda = []
    for metadata in sorted((ctx.deps / "conda-meta").glob("*.json")):
        record = json.loads(metadata.read_text())
        if vendored.isdisjoint(record.get("files", [])):
            continue
        conda.append({k: record[k] for k in ("name", "version", "url", "license") if k in record})
        licenses = Path(record["link"]["source"]) / "info/licenses"
        if licenses.is_dir():
            shutil.copytree(licenses, root / "legal" / "conda" / record["name"], dirs_exist_ok=True)
    (root / "legal/conda-packages.json").write_text(json.dumps(conda, indent=2) + "\n")
    return latest


def macos_notices(ctx, root):
    from importlib.metadata import distributions
    from urllib.parse import quote

    from src.core.i18n import translate_text
    from tools.update_third_party_notices import render_notices

    legal = root / "legal"
    # Content copies leave SMB's SF_ARCHIVED flags on the source volume.
    shutil.copyfile(ROOT / "LICENSE", legal / "BluraySubtitle-LICENSE.txt")
    shutil.copyfile(root / PYLIB / "LICENSE.txt", legal / "CPython-LICENSE.txt")
    (legal / "vapoursynth").mkdir(exist_ok=True)
    vs_license, = (root / SITE).glob("vapoursynth-*.dist-info/licenses/COPYING.LESSER")
    shutil.copyfile(vs_license, legal / "vapoursynth/COPYING.LESSER")
    shutil.copytree(ROOT / "third_party/vapoursynth_scripts", legal / "vapoursynth_scripts",
                    ignore=shutil.ignore_patterns("*.py", "__pycache__"), copy_function=shutil.copyfile)
    python = {d.metadata["Name"].lower(): d.version for d in distributions(path=[str(root / SITE)])}
    qt = {d.metadata["Name"].lower(): d.version for d in distributions(path=[str(root / "qt/latest")])}
    media = ctx.versions["media"]
    conda = json.loads((legal / "conda-packages.json").read_text())
    versions = {
        "SITE_PACKAGES": SITE.as_posix(), "PYTHON_VERSION": sys.version.split()[0],
        "PYTHON_ARCHITECTURE": ctx.arch, "VAPOURSYNTH_VERSION": "R" + python["vapoursynth"],
        "QT_VERSION": qt["pyqt6-qt6"], "PYQT_VERSION": qt["pyqt6"],
        "NUMPY_VERSION": python["numpy"], "PILLOW_VERSION": python["pillow"],
        "PYCOUNTRY_VERSION": python["pycountry"], "SOUNDFILE_VERSION": python["soundfile"],
        "LIBSNDFILE_VERSION": output(root / "python/bin/python3", "-I", "-B", "-c",
                                     "import soundfile; print(soundfile.__libsndfile_version__)"),
        "LIBASS_VERSION": next(row["version"] for row in conda if row["name"] == "libass"),
    }
    media_fields = {"7zip": "SEVEN_ZIP", "ffmpeg": "FFMPEG", "flac": "FLAC", "fdkaac": "FDKAAC",
                    "fdk-aac": "FDK_AAC", "x264": "X264", "x265": "X265", "svt-av1": "SVT_AV1",
                    "tsmuxer": "TSMUXER", "dovi": "DOVI_TOOL", "hdr10plus": "HDR10PLUS_TOOL",
                    "mkvtoolnix": "MKVTOOLNIX", "vsedit": "VSEDIT"}
    for key, field in media_fields.items():
        versions[field + "_VERSION"] = media[key][0].removeprefix("v")

    for language, filename in (("en", "THIRD_PARTY_NOTICES.md"), ("zh", "THIRD_PARTY_NOTICES.zh-Hans.md")):
        source = translate_text("Source", language)
        license_label = translate_text("License", language)

        def links(url, folder, title=license_label):
            result = f"[{source}]({url})"
            files = sorted(p for p in folder.rglob("*") if p.is_file())
            if files:
                result += f" · [{title}]({quote(files[0].relative_to(legal).as_posix())})"
            return result

        plugins = []
        for name, release in sorted(ctx.versions["plugins"].items()):
            binaries = ("libeedi3.dylib", "libmiscfilters.dylib") if name == "legacy-filters" else (f"lib{name}.dylib",)
            files = ", ".join(f"`plugins/{n}`" for n in binaries)
            plugins.append(f"| {name} | {release['ref']} | {files} | {links(release['source_url'], legal / name)} |")
        extra = [(name, ref, links(url, legal / name)) for name, (ref, url) in media.items() if name not in media_fields]
        extra.extend((row["name"], row["version"], links(row["url"], legal / "conda" / row["name"], row.get("license") or license_label))
                     for row in conda)
        for name, ref in {**python, **qt}.items():
            if name not in {"numpy", "pillow", "pycountry", "soundfile", "vapoursynth", "pyqt6", "pyqt6-qt6"}:
                extra.append((name, ref, f"[{source}](https://pypi.org/project/{quote(name)}/{quote(ref)}/)"))
        versions["VAPOURSYNTH_COMPONENTS"] = "\n".join(plugins)
        versions["ADDITIONAL_COMPONENTS"] = "\n".join(f"| {name} | {ref} | {details} |" for name, ref, details in sorted(extra))
        render_notices({ROOT / "legal/macos" / filename: legal / filename}, versions)


def macos_icon(work, stage):
    icon = stage / "share/BluraySubtitle.icns"
    icon.parent.mkdir()
    iconset = work / "BluraySubtitle.iconset"
    iconset.mkdir()
    master = work / "master.png"
    run("sips", "-s", "format", "png", "-z", "1024", "1024", ROOT / "resource/bluraysubtitle.svg", "--out", master)
    for size in (16, 32, 128, 256, 512):
        for scale, suffix in ((1, ""), (2, "@2x")):
            side = str(size * scale)
            run("sips", "-z", side, side, master, "--out", iconset / f"icon_{size}x{size}{suffix}.png")
    run("iconutil", "-c", "icns", "-o", icon, iconset)


def build_assets(ctx, mode):
    ctx.component("app-icon", digest(ROOT / "resource/bluraysubtitle.svg"), macos_icon,
                  recipe=recipe_digest(macos_icon), scope="icon")
    if mode == "Build":
        source = Path(__file__).with_name("macos_launcher.c")

        def compile_launcher(work, stage):
            target = stage / "packaging/BluraySubtitle"
            target.parent.mkdir()
            ctx.run("clang", *ctx.flags.split(), source, "-o", target)

        ctx.component("app-launcher", digest(source), compile_launcher,
                      recipe=recipe_digest(compile_launcher, ctx.run), scope="compiler")


def assemble(ctx, root):
    root.mkdir(parents=True)
    for name in ("python", "qt", "plugins", "legal", "libexec", "share/vulkan"):
        shutil.copytree(
            ctx.prefix / name,
            root / name,
            symlinks=True,
            ignore=shutil.ignore_patterns("libqpdf.dylib") if name == "qt" else None,
        )
    from tools.install_vapoursynth_scripts import install_scripts

    install_scripts(root / SITE)
    python_library = root / "python/lib/libpython.dylib"
    python_library.symlink_to(f"libpython{sys.version_info.major}.{sys.version_info.minor}.dylib")
    for name in PROGRAMS:
        copy(ctx.prefix / "bin" / name, root / "bin" / name)
    if (ctx.prefix / "bin/locale").is_dir():
        shutil.copytree(ctx.prefix / "bin/locale", root / "bin/locale")
    pipe = root / "bin/vspipe"
    pipe.write_text(f"""#!/bin/sh
set -eu
base=$(cd "$(dirname "$0")/.." && pwd)
export PYTHONDONTWRITEBYTECODE=1
export VAPOURSYNTH_EXTRA_PLUGIN_PATH="${{VAPOURSYNTH_EXTRA_PLUGIN_PATH:-$base/plugins}}"
export VK_DRIVER_FILES="${{VK_DRIVER_FILES:-$base/share/vulkan/icd.d/MoltenVK_icd.json}}"
exec "$base/{SITE.as_posix()}/vapoursynth/vspipe" "$@"
""")
    pipe.chmod(0o755)
    editor = root / "bin/vsedit"
    editor.write_text(f"""#!/bin/sh
set -eu
base=$(cd "$(dirname "$0")/.." && pwd)
export PYTHONDONTWRITEBYTECODE=1
export QT_PLUGIN_PATH="$base/qt/6.6/PyQt6/Qt6/plugins"
export VSSCRIPT_PATH="$base/{SITE.as_posix()}/vapoursynth/libvsscript.dylib"
export VAPOURSYNTH_EXTRA_PLUGIN_PATH="${{VAPOURSYNTH_EXTRA_PLUGIN_PATH:-$base/plugins}}"
exec "$base/libexec/vsedit" "$@"
""")
    editor.chmod(0o755)
    copy(ctx.prefix / "share/BluraySubtitle.icns", root / "share/BluraySubtitle.icns")
    latest = relocation(ctx, root)
    macos_notices(ctx, root)
    (root / "legal/sources.json").write_text(json.dumps(ctx.versions, sort_keys=True, indent=2) + "\n")
    manifest = {
        "architecture": ctx.arch,
        "latest_qt_minimum": latest,
        "vsscript": str(SITE / "vapoursynth/libvsscript.dylib"),
        "components": ctx.built,
    }
    (root / "runtime.json").write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")


def application(ctx, app):
    from src.core.version import APP_VERSION, BUILD_COMMIT_FILENAME, git_commit_record

    contents = app / "Contents"
    runtime = contents / "Resources/Runtime"
    assemble(ctx, runtime)
    project = runtime / "app"
    for name in ("src", "resource"):
        shutil.copytree(
            ROOT / name, project / name, copy_function=shutil.copyfile,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "mpv"),
        )
    for name in ("config.default.json", "LICENSE"):
        shutil.copyfile(ROOT / name, project / name)
    tools = project / "tools"
    tools.mkdir(parents=True)
    for name in ("macos_entry.py", "macos_update.py", "macos_finish_update.sh"):
        shutil.copyfile(Path(__file__).with_name(name), tools / name)
    copy(runtime / "share/BluraySubtitle.icns", contents / "Resources/BluraySubtitle.icns")
    (project / BUILD_COMMIT_FILENAME).write_text(git_commit_record(ROOT))
    (contents / "MacOS").mkdir()
    copy(ctx.prefix / "packaging/BluraySubtitle", contents / "MacOS/BluraySubtitle")
    with (contents / "Info.plist").open("wb") as f:
        plistlib.dump(
            {
                "CFBundleName": "BluraySubtitle",
                "CFBundleDisplayName": "BluraySubtitle",
                "CFBundleExecutable": "BluraySubtitle",
                "CFBundleIconFile": "BluraySubtitle.icns",
                "CFBundleIdentifier": "io.github.haruite.BluraySubtitle",
                "CFBundlePackageType": "APPL",
                "CFBundleVersion": APP_VERSION,
                "CFBundleShortVersionString": APP_VERSION,
                "LSMinimumSystemVersion": "11.0",
                "NSHighResolutionCapable": True,
            },
            f,
        )
    run("codesign", "--force", "--sign", "-", app)
    # A published app in /Applications must also be readable by other Mac accounts.
    run("/bin/chmod", "-RP", "a+rX,go-w", app)


def archive_name(arch):
    return "BluraySubtitle_macos_" + {"x86_64": "x64", "arm64": "arm64"}[arch] + ".zip"


def archive(ctx, work):
    from src.core.version import BUILD_COMMIT_FILENAME

    app = work / "BluraySubtitle.app"
    application(ctx, app)
    zipped = work / archive_name(ctx.arch)
    run("ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", app, zipped)
    commit = (app / "Contents/Resources/Runtime/app" / BUILD_COMMIT_FILENAME).read_text()
    record = zipped.with_suffix(".zip.txt")
    record.write_text(f"sha256={digest(zipped)}\n{commit}")
    zipped.chmod(0o644)
    record.chmod(0o644)
    return zipped
