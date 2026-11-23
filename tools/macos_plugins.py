"""Build the same R79 filter set as the regular Windows distribution."""

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from tools.macos_build_support import ROOT, Build, copy, copy_licenses, digest, message, recipe_digest

from tools.lsmash_ffmpeg_compat import adapt_sources
from tools.vapoursynth_plugin_releases import (
    LEGACY_SOURCE_KEYS,
    R79_PLUGIN_NAMESPACES,
    ispc_matches,
    resolve_releases,
)


def plugin_releases():
    return resolve_releases(LEGACY_SOURCE_KEYS.get(p, p) for p in R79_PLUGIN_NAMESPACES)


def compiler(ctx, source, files, dest, *flags, cpp=True):
    dest.parent.mkdir(parents=True, exist_ok=True)
    includes = (ctx.prefix / "include", ctx.prefix / "include/vapoursynth", ctx.deps / "include")
    ctx.run(
        "clang++" if cpp else "clang",
        "-dynamiclib",
        "-fPIC",
        "-O3",
        *(["-std=c++17"] if cpp else []),
        *shlex.split(ctx.flags),
        *("-I" + str(p) for p in includes),
        *flags,
        *files,
        "-o",
        dest,
        cwd=source,
    )


def build_eedi3(ctx, src, work, dest):
    compiler(ctx, src, ["src/filters/eedi3/eedi3.c"], dest, "-Iinclude", cpp=False)


def build_miscfilters(ctx, src, work, dest):
    compiler(
        ctx,
        src,
        ["src/filters/misc/miscfilters.cpp"],
        dest,
        "-Iinclude",
        "-I.",
        *(["-DVS_TARGET_CPU_X86"] if ctx.arch == "x86_64" else []),
    )


def build_vivtc(ctx, src, work, dest):
    compiler(ctx, src, ["src/vivtc.c"], dest, cpp=False)


def build_removegrain(ctx, src, work, dest):
    compiler(ctx, src, sorted((src / "src").glob("*.cpp")), dest)


def build_bilateral(ctx, src, work, dest):
    compiler(ctx, src, sorted((src / "source").glob("*.cpp")), dest, "-Iinclude")


def build_sangnom(ctx, src, work, dest):
    if ctx.arch == "arm64":
        file = src / "src/sangnom.cpp"
        file.write_text(file.read_text().replace("#include <emmintrin.h>", "#include <sse2neon.h>"))
    compiler(ctx, src, ["src/sangnom.cpp"], dest)


def build_znedi3(ctx, src, work, dest):
    ctx.run(
        "make", "-j" + ctx.jobs, *(["X86=1", "X86_AVX512=1"] if ctx.arch == "x86_64" else []), cwd=src
    )
    copy(src / "vsznedi3.so", dest)
    copy(src / "nnedi3_weights.bin", dest.parent / "nnedi3_weights.bin")


def build_fmtconv(ctx, src, work, dest):
    location = src / "build/unix"
    if not (location / "autogen.sh").exists():
        location = src
    ctx.run("sh", "autogen.sh", cwd=location)
    ctx.run("sh", "configure", f"--prefix={ctx.prefix}", cwd=location)
    ctx.run("make", "-j" + ctx.jobs, cwd=location)
    copy(
        next(p for p in location.rglob("*.so") if p.is_file())
        if not list(location.rglob("*.dylib"))
        else next(p for p in location.rglob("*.dylib") if p.is_file()),
        dest,
    )


def zsmooth_arm64_sdk(active_sdk: Path) -> Path | None:
    def targets(sdk):
        stub = sdk / "usr/lib/libSystem.tbd"
        # The top-level targets precede the install name and the reexported libraries.
        return stub.read_text().partition("install-name:")[0] if stub.is_file() else ""

    current = targets(active_sdk)
    if "arm64-macos" in current or "arm64e-macos" not in current:
        return active_sdk

    directories = {active_sdk.parent, Path("/Library/Developer/CommandLineTools/SDKs")}
    directories.update(Path("/Applications").glob(
        "Xcode*.app/Contents/Developer/Platforms/MacOSX.platform/Developer/SDKs"))
    sdks = {path.resolve() for directory in directories for path in directory.glob("MacOSX*.sdk")}
    candidates = []
    for sdk in sdks:
        if "arm64-macos" in targets(sdk):
            version = json.loads((sdk / "SDKSettings.json").read_bytes())["Version"]
            candidates.append((tuple(map(int, version.split("."))), sdk))
    return max(candidates)[1] if candidates else None


def build_zsmooth(ctx, src, work, dest):
    # The Zig build API is versioned with the compiler used by this release.
    version = re.search(r'\.minimum_zig_version\s*=\s*"([\d.]+)"', (src / "build.zig.zon").read_text())[1]
    environment = {}
    if version == "0.15.2" and ctx.arch == "arm64":
        # The Zig host build runner gets its SDK through xcrun and cannot resolve
        # ordinary arm64 symbols from the arm64e-only stubs in the 26.4+ SDKs.
        if ctx.zig_sdk is None:
            raise RuntimeError(message("Zig 0.15.2 needs a macOS SDK with arm64-macos libSystem stubs, "
                                       "such as the SDK in Xcode 26.3."))
        if ctx.zig_sdk != Path(ctx.env["SDKROOT"]).resolve():
            # Zig explicitly asks xcrun for "macosx", overriding SDKROOT. Pass the
            # absolute SDK to that lookup, including for a non-default CLT SDK.
            xcrun = work / "zig-tools/xcrun"
            xcrun.parent.mkdir()
            xcrun.write_text('#!/bin/sh\nif [ "$1" = --sdk ] && [ "$2" = macosx ]; then\n'
                             '    shift 2\n    exec /usr/bin/xcrun --sdk "$SDKROOT" "$@"\n'
                             'fi\nexec /usr/bin/xcrun "$@"\n')
            xcrun.chmod(0o755)
            environment = {"SDKROOT": str(ctx.zig_sdk), "PATH": os.pathsep.join((str(xcrun.parent), ctx.env["PATH"]))}
    zigroot = ctx.cache / f"zig-{version}"
    zig = zigroot / "ziglang/zig"
    if not zig.is_file():
        ctx.run(
            sys.executable,
            "-m",
            "pip",
            "install",
            "--only-binary=:all:",
            "--no-deps",
            "--target",
            zigroot,
            "ziglang==" + version,
        )
    # The pinned FFTW Zig port probes memalign as available on all Unix.
    # Darwin supplies posix_memalign. Patch a private source copy so other
    # builds can still verify and share Zig's original dependency cache.
    zon = src / "build.zig.zon"
    description = zon.read_text()
    section = re.search(r"\.fftw\s*=\s*\.\{(.*?)\n\s*\},", description, re.S)
    if section:
        remote = re.search(r'git\+https://github.com/([^?#"]+?)\.git[^"#]*#([0-9a-f]+)', section[1])
        if remote:
            fftw = ctx.source(
                f"https://codeload.github.com/{remote[1]}/tar.gz/{remote[2]}", work / "fftw"
            )
            recipe = fftw / "build.zig"
            old = recipe.read_text()
            new = re.sub(
                r"(\.HAVE_(?:DECL_)?MEMALIGN\s*=\s*)if \(!is_windows\) true else null", r"\g<1>null", old
            )
            if new != old:
                recipe.write_text(new)
                shutil.move(fftw, src / "fftw-macos")
                zon.write_text(
                    description[: section.start(1)]
                    + ' .path = "fftw-macos",'
                    + description[section.end(1) :]
                )
    target = "x86_64" if ctx.arch == "x86_64" else "aarch64"
    cpu = "ivybridge" if ctx.arch == "x86_64" else "apple_m1"
    ctx.run(
        zig,
        "build",
        "-Doptimize=ReleaseFast",
        f"-Dtarget={target}-macos.11.0",
        f"-Dcpu={cpu}",
        "-j" + ctx.jobs,
        cwd=src,
        ZIG_GLOBAL_CACHE_DIR=str(ctx.cache / "zig-cache"),
        **environment,
    )
    copy(next((src / "zig-out").rglob("libzsmooth.dylib")), dest)


def build_cmake_plugin(ctx, src, work, dest):
    build = work / "build"
    opts = []
    if dest.name == "libnlm_ispc.dylib":
        compiler = ctx.deps / "bin/ispc"
        if not ispc_matches(compiler, ctx.ispc_version):
            tag = "v" + ctx.ispc_version
            url = f"https://github.com/ispc/ispc/releases/download/{tag}/ispc-{tag}-macOS.{ctx.arch}.tar.gz"
            compiler = ctx.source(url, work / "ispc") / "bin/ispc"
        opts.append("-DCMAKE_ISPC_COMPILER=" + str(compiler))
        cpu = "sse2-i32x4;avx2-i32x8" if ctx.arch == "x86_64" else "neon-i32x4"
        opts.append("-DCMAKE_ISPC_INSTRUCTION_SETS=" + cpu)
    ctx.cmake(src, build, *opts)
    copy(next(build.rglob("libassrender.dylib" if dest.name == "libassrender.dylib" else "libvsnlm_ispc.dylib")), dest)


def build_meson(ctx, src, work, dest):
    from tools.macos_python_runtime import SITE

    build = work / "build"
    ctx.run("meson", "setup", build, src, "--buildtype=release", "-Db_lto=false",
            PYTHONPATH=str(ctx.prefix / SITE),
            LDFLAGS=ctx.env["LDFLAGS"] + (" -lfftw3f_threads" if dest.name == "libdfttest.dylib" else ""))
    ctx.run("meson", "compile", "-C", build, "-j", ctx.jobs)
    plugin, = (p for p in build.iterdir() if p.is_file() and p.suffix in (".so", ".dylib"))
    copy(plugin, dest)


def build_lsmas(ctx, src, work, dest):
    version = subprocess.check_output(["pkg-config", "--modversion", "libavcodec"], env=ctx.env, text=True)
    adapt_sources(src, int(version.split(".")[0]))
    build_meson(ctx, src / "VapourSynth", work, dest)


def build_eedi3m(ctx, src, work, dest):
    for path in src.rglob("EEDI3.cpp"):
        path.write_text(path.read_text().replace("std::max_align_t", "max_align_t"))
    header = src / "EEDI3/EEDI3.h"
    header.write_text("#include <cmath>\n" + header.read_text())
    build_meson(ctx, src, work, dest)


PLUGIN_BUILDERS = {
    "eedi3": build_eedi3, "miscfilters": build_miscfilters, "lsmas": build_lsmas, "eedi3m": build_eedi3m,
    "vivtc": build_vivtc, "removegrain": build_removegrain, "bilateral": build_bilateral,
    "sangnom": build_sangnom, "znedi3": build_znedi3, "fmtconv": build_fmtconv, "zsmooth": build_zsmooth,
    "assrender": build_cmake_plugin, "nlm_ispc": build_cmake_plugin,
}


def build_plugins(ctx, releases):
    for source, release in releases.items():
        for name in (("eedi3", "miscfilters") if source == "legacy-filters" else (source,)):
            builder = PLUGIN_BUILDERS.get(name, build_meson)

            def install(work, stage):
                src = ctx.source(release.source_url, work / "source", release.sha256)
                copy_licenses(src, stage / "legal" / source)
                folder = stage / "plugins"
                folder.mkdir()
                builder(ctx, src, work, folder / f"lib{name}.dylib")

            deps = ("vapoursynth", "lsmash", "ffmpeg") if name == "lsmas" else ("vapoursynth",)
            if name == "sangnom" and ctx.arch == "arm64":
                deps += ("sse2neon",)
            cmake = builder == build_cmake_plugin
            meson = builder in (build_meson, build_lsmas, build_eedi3m)
            build_tools = ("cmake", "ninja") if cmake else (("meson", "ninja") if meson else ())
            # Include the native SDKs even when upstream finds them automatically.
            packages = {"assrender": ("libass",), "nlm_ispc": ("ispc",), "dfttest": ("fftw",),
                        "placebo": ("shaderc", "libplacebo", "libvulkan-headers"),
                        "lsmas": ("xxhash",), "mvtools": ("fftw",), "eedi3m": ("fftw",),
                        "fmtconv": ("autoconf", "automake", "libtool")}.get(name, ())
            if meson or cmake:
                packages += ("pkg-config",)
            recipe = [recipe_digest(install, builder, *((Build.cmake,) if cmake else ())),
                      digest(ROOT / "tools/lsmash_ffmpeg_compat.py") if name == "lsmas" else ""]
            if name == "nlm_ispc":
                recipe.append(ctx.ispc_version)
            if name == "zsmooth" and ctx.arch == "arm64":
                active_sdk = Path(ctx.env["SDKROOT"]).resolve()
                ctx.zig_sdk = zsmooth_arm64_sdk(active_sdk)
                if ctx.zig_sdk is not None and ctx.zig_sdk != active_sdk:
                    recipe.append([str(ctx.zig_sdk), digest(ctx.zig_sdk / "SDKSettings.json")])
            ctx.component("vs-" + name, [release.ref, release.source_url, release.sha256], install,
                          dependencies=deps, recipe=recipe, packages=packages, build_tools=build_tools)
