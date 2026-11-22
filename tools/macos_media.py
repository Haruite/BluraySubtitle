"""Build the media toolchain with the deployment target of the compatibility Qt."""

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
import urllib.request
from pathlib import Path
from xml.etree import ElementTree

from tools.macos_build_support import Build, copy, copy_licenses, digest, download, output, recipe_digest
from tools.macos_macho import inspect_macho


def tags(repo, pattern):
    lines = output("git", "ls-remote", "--refs", "--tags", repo)
    entries = [
        (m.group(1), line.split()[0])
        for line in lines.splitlines()
        if (m := re.fullmatch(pattern, line.partition("refs/tags/")[2]))
    ]
    return max(entries, key=lambda x: tuple(map(int, re.findall(r"\d+", x[0]))))


def github(repo, pattern=r"([vV]?\d+(?:\.\d+)+)"):
    tag, commit = tags(f"https://github.com/{repo}.git", pattern)
    return tag, f"https://codeload.github.com/{repo}/tar.gz/{commit}"


def release_index(url, pattern):
    with urllib.request.urlopen(url, timeout=45) as response:
        versions = re.findall(pattern, response.read().decode())
    return max(versions, key=lambda s: tuple(map(int, s.split("."))))


def releases():
    from concurrent.futures import ThreadPoolExecutor

    jobs = {
        "lsmash": lambda: github("l-smash/l-smash", r"(v?2(?:\.\d+)+)"),
        "x265": lambda: github("Multicorewareinc/x265"),
        "fdk-aac": lambda: github("mstorsjo/fdk-aac"),
        "fdkaac": lambda: github("nu774/fdkaac"),
        "flac": lambda: github("xiph/flac"),
        "tsmuxer": lambda: github("justdan96/tsMuxer"),
        "dovi": lambda: github("quietvoid/dovi_tool"),
        "hdr10plus": lambda: github("quietvoid/hdr10plus_tool"),
        "7zip": lambda: github("ip7z/7zip"),
        "vsedit": lambda: github("YomikoR/VapourSynth-Editor", r"(R\d+-mod-[\d.]+)"),
    }
    with ThreadPoolExecutor(6) as pool:
        versions = dict(zip(jobs, pool.map(lambda name: jobs[name](), jobs)))
    # The Windows and Linux packages also track VideoLAN's master commit.
    upstream = "https://code.videolan.org/videolan/x264"
    try:
        commit = output("git", "ls-remote", "--exit-code", upstream + ".git", "refs/heads/master").split()[0]
        versions["x264"] = commit, f"{upstream}/-/archive/{commit}/x264-{commit}.tar.gz"
    except subprocess.CalledProcessError:
        commit = output(
            "git", "ls-remote", "--exit-code", "https://github.com/mirror/x264.git", "refs/heads/master"
        ).split()[0]
        versions["x264"] = commit, f"https://codeload.github.com/mirror/x264/tar.gz/{commit}"
    repo = "https://gitlab.com/AOMediaCodec/SVT-AV1"
    tag, commit = tags(repo + ".git", r"(v\d+(?:\.\d+)+)")
    versions["svt-av1"] = tag, f"{repo}/-/archive/{commit}/SVT-AV1-{commit}.tar.gz"
    version = release_index("https://ffmpeg.org/releases/", r'href="ffmpeg-(\d+(?:\.\d+)+)\.tar\.xz"')
    versions["ffmpeg"] = version, f"https://ffmpeg.org/releases/ffmpeg-{version}.tar.xz"
    for name in ("libudfread", "libbluray"):
        server = f"https://download.videolan.org/pub/videolan/{name}/"
        if name == "libudfread":
            version = release_index(server, r'href="libudfread-(\d+(?:\.\d+)+)\.tar\.xz"')
        else:
            version = release_index(server, r'href="(\d+(?:\.\d+)+)/"')
            server += version + "/"
        versions[name] = version, f"{server}{name}-{version}.tar.xz"
    with urllib.request.urlopen("https://mkvtoolnix.download/latest-release.xml", timeout=45) as response:
        version = ElementTree.parse(response).findtext("./latest-source/version")
    if not version or not re.fullmatch(r"\d+(?:\.\d+)+", version):
        raise ValueError("Invalid MKVToolNix source version")
    versions["mkvtoolnix"] = version, f"https://mkvtoolnix.download/sources/mkvtoolnix-{version}.tar.xz"
    # 1.4.2 raised the Metal backend's deployment target to macOS 12.
    versions["moltenvk"] = (
        "v1.4.1",
        "https://github.com/KhronosGroup/MoltenVK/releases/download/v1.4.1/MoltenVK-macos.tar",
    )
    return versions


def stage_install(ctx, src, work, stage, argv):
    dest = work / "install"
    ctx.run(*argv, cwd=src, DESTDIR=str(dest))
    shutil.copytree(dest / ctx.prefix.relative_to("/"), stage, dirs_exist_ok=True, symlinks=True)


def autotools(ctx, src, work, stage, *opts):
    if not (src / "configure").exists():
        ctx.run("autoreconf", "-fiv", cwd=src)
    ctx.run("bash", "configure", f"--prefix={ctx.prefix}", *opts, cwd=src)
    ctx.run("make", "-j" + ctx.jobs, cwd=src)
    stage_install(ctx, src, work, stage, ["make", f"DESTDIR={work / 'install'}", "install"])


def build_x265(name, ctx, src, work, stage):
    root = src / "source"
    json11 = root / "dynamicHDR10/json11/json11.cpp"
    code = json11.read_text()
    if "#include <cstdint>" not in code:
        json11.write_text("#include <cstdint>\n" + code)
    options = [
        "-DENABLE_SHARED=OFF",
        "-DENABLE_LIBNUMA=OFF",
        "-DENABLE_LAVF=OFF",
        "-DENABLE_HDR10_PLUS=ON",
        "-DENABLE_LSMASH=OFF",
    ]
    for bits in (12, 10):
        directory = work / f"b{bits}"
        ctx.cmake(
            root,
            directory,
            *options,
            "-DHIGH_BIT_DEPTH=ON",
            "-DEXPORT_C_API=OFF",
            "-DENABLE_CLI=OFF",
            f"-DMAIN12={'ON' if bits == 12 else 'OFF'}",
        )
    main = work / "b8"
    main.mkdir()
    for bits in (10, 12):
        (main / f"libx265_main{bits}.a").symlink_to(work / f"b{bits}/libx265.a")
    ctx.cmake(
        root,
        main,
        *options,
        "-DLINKED_10BIT=ON",
        "-DLINKED_12BIT=ON",
        "-DEXTRA_LIB=x265_main10.a;x265_main12.a",
        f"-DEXTRA_LINK_FLAGS=-L{main}",
        target="cli",
    )
    copy(main / "x265", stage / "bin/x265")


def rust_toolchain(ctx, *, provision):
    settings = {"RUSTUP_HOME": os.environ.get("RUSTUP_HOME", str(Path.home() / ".rustup")),
                "RUSTFLAGS": "-Ctarget-cpu=" + ("ivybridge" if ctx.arch == "x86_64" else "apple-m1"),
                "CARGO_BUILD_JOBS": ctx.jobs}
    private = ctx.cache / "rust-tools"
    cargo = shutil.which("cargo", path=ctx.env["PATH"])
    rustc = shutil.which("rustc", path=ctx.env["PATH"])
    if not cargo or not rustc or subprocess.run(
        [cargo, "--version"], env={**ctx.env, **settings}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ).returncode:
        cargo = private / "bin/cargo"
        rustc = private / "bin/rustc"
        if not cargo.is_file() and provision:
            ctx.run(ctx.cache / "bootstrap/micromamba", "create", "-y", "--override-channels",
                    "-c", "conda-forge", "-p", private, "rust")
    settings["RUSTC"] = str(rustc)
    versions = [subprocess.check_output(command, env={**ctx.env, **settings}, text=True).strip()
                for command in ([cargo, "--version"], [rustc, "--version", "--verbose"])]
    return cargo, settings, versions


def hdr_providers(ctx, media, *, offline=False):
    # Choose a compatible upstream executable before resolving the cache key.
    # Only a source build needs an installed Rust compiler or its version in that key.
    providers = {}
    for name, binary in (("dovi", "dovi_tool"), ("hdr10plus", "hdr10plus_tool")):
        tag = media[name][0]
        url = f"https://github.com/quietvoid/{binary}/releases/download/{tag}/{binary}-{tag}-universal-macOS.zip"
        if offline:
            cached = ctx.downloads / hashlib.sha256(url.encode()).hexdigest()
            receipt = cached.with_suffix(".sha256")
            asset = cached if receipt.is_file() and cached.is_file() and digest(cached) == receipt.read_text().strip() else None
        else:
            try:
                asset = download(url, ctx.downloads)
            except subprocess.CalledProcessError as error:
                if error.returncode != 22:
                    raise
                asset = None
        if asset is not None:
            with tempfile.TemporaryDirectory(dir=ctx.cache) as tmp, zipfile.ZipFile(asset) as archive:
                for member in archive.namelist():
                    if Path(member).name != binary:
                        continue
                    file = Path(tmp) / binary
                    with archive.open(member) as src, file.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
                    try:
                        info = inspect_macho(file, ctx.arch)
                    except ValueError:
                        continue
                    if info and info.minimum <= (11, 0, 0):
                        providers[name] = {"url": url, "sha256": digest(asset), "member": member}
                        break
        if name not in providers:
            providers[name] = {"rust": rust_toolchain(ctx, provision=not offline)[2]}
    return providers


def build_hdr_cli(name, ctx, work, stage, release):
    binary = "dovi_tool" if name == "dovi" else "hdr10plus_tool"
    source = ctx.source(release[1], work / "source")
    copy_licenses(source, stage / "legal" / name)
    destination = stage / "bin" / binary
    provider = ctx.hdr[name]
    if "url" in provider:
        asset = download(provider["url"], ctx.downloads, provider["sha256"])
        ctx.run("ditto", "-x", "-k", asset, work / "upstream")
        copy_licenses(work / "upstream", stage / "legal" / name)
        copy(work / "upstream" / provider["member"], destination)
    else:
        cargo, settings, versions = rust_toolchain(ctx, provision=False)
        if versions != provider["rust"]:
            raise ValueError(f"The Rust compiler for {name} changed after resolving its cache key")
        ctx.run(cargo, "build", "--locked", "--release", "--bin", binary, cwd=source, **settings)
        copy(source / "target/release" / binary, destination)


def install_moltenvk(name, ctx, work, stage, release):
    _, url = release
    package = ctx.source(url, work / "moltenvk")
    copy_licenses(package, stage / "legal" / name)
    files = [p for p in package.rglob("libMoltenVK.dylib") if "macos" in str(p.parent).lower()]
    copy(min(files, key=lambda p: len(p.parts)), stage / "lib/libMoltenVK.dylib")
    icd = stage / "share/vulkan/icd.d/MoltenVK_icd.json"
    icd.parent.mkdir(parents=True)
    manifests = list(package.rglob("MoltenVK_icd.json"))
    import json

    data = json.loads(manifests[0].read_text())
    data["ICD"]["library_path"] = "../../../lib/libMoltenVK.dylib"
    icd.write_text(json.dumps(data))


def install_7zip(name, ctx, work, stage, release):
    tag, _ = release
    suffix = "mac-x64" if ctx.arch == "x86_64" else "mac"
    archive = download(
        f"https://github.com/ip7z/7zip/releases/download/{tag}/7z{tag.replace('.', '')}-{suffix}.tar.xz",
        ctx.downloads,
    )
    ctx.run("tar", "-xf", archive, "-C", work)
    copy_licenses(work, stage / "legal" / name)
    copy(next(work.rglob("7zz")), stage / "bin/7zz")


def build_qmake(ctx):
    qt = ctx.cache / "qt-sdk"
    qmake = qt / "6.6.3/macos/bin/qmake"
    if not qmake.is_file():
        sdk = qmake.parent.parent
        new_sdk = not sdk.exists()
        try:
            ctx.run("aqt", "install-qt", "mac", "desktop", "6.6.3", "clang_64",
                    "--archives", "qtbase", "--outputdir", qt, cwd=ctx.cache)
        except (OSError, subprocess.SubprocessError):
            # An interrupted extraction can leave qmake in an incomplete cached SDK.
            if new_sdk and sdk.is_dir():
                shutil.rmtree(sdk)
            else:
                qmake.unlink(missing_ok=True)
            raise
    return qmake


def build_autotools(name, ctx, src, work, stage):
    options = ("--enable-static", "--bit-depth=all", "--chroma-format=all") if name == "x264" else ()
    autotools(ctx, src, work, stage, *options)


def build_bluray(name, ctx, src, work, stage):
    if (src / "meson.build").exists():
        build = work / "build"
        opts = ["-Dbdj_jar=disabled"] if name == "libbluray" else []
        ctx.run(
            "meson",
            "setup",
            build,
            src,
            "--prefix",
            ctx.prefix,
            "--libdir",
            "lib",
            "--buildtype=release",
            *opts,
        )
        ctx.run("meson", "compile", "-C", build, "-j", ctx.jobs)
        stage_install(ctx, src, work, stage, ["meson", "install", "-C", build])
    else:
        autotools(ctx, src, work, stage, *(["--disable-bdjava-jar"] if name == "libbluray" else []))


def build_ffmpeg(name, ctx, src, work, stage):
    autotools(
        ctx,
        src,
        work,
        stage,
        "--enable-shared",
        "--disable-static",
        "--disable-doc",
        "--disable-ffplay",
        "--disable-debug",
        "--enable-libopus",
        "--enable-libdav1d",
        "--enable-libbluray",
        "--enable-libass",
        "--enable-videotoolbox",
        "--enable-audiotoolbox",
        "--disable-autodetect",
        "--enable-zlib",
    )


def build_cmake_media(name, ctx, src, work, stage):
    build = work / "build"
    opts = ["-DINSTALL_MANPAGES=OFF"] if name == "flac" else []
    ctx.cmake(src, build, "-DBUILD_TESTING=OFF", "-DBUILD_EXAMPLES=OFF", "-DBUILD_DOCS=OFF", *opts)
    stage_install(ctx, src, work, stage, ["cmake", "--install", build])


def build_tsmuxer(name, ctx, src, work, stage):
    file = src / "tsMuxer/srtStreamReader.cpp"
    file.write_text("#include <algorithm>\n" + file.read_text())
    ctx.cmake(
        src,
        work / "build",
        "-DTSMUXER_GUI=OFF",
        "-DTSMUXER_STATIC_BUILD=OFF",
        "-DWITHOUT_PKGCONFIG=OFF",
        target="tsmuxer",
    )
    copy(next(p for p in (work / "build").rglob("tsmuxer") if p.is_file()), stage / "bin/tsMuxeR")


def build_mkvtoolnix(name, ctx, src, work, stage):
    ctx.run(
        "bash",
        "configure",
        f"--prefix={ctx.prefix}",
        "--disable-gui",
        "--disable-update-check",
        f"--with-boost={ctx.deps}",
        f"--with-boost-libdir={ctx.deps}/lib",
        f"--with-docbook-xsl-root={ctx.deps}/share/docbook-xsl",
        f"--with-qmake6={build_qmake(ctx)}",
        cwd=src,
    )
    names = ("mkvmerge", "mkvinfo", "mkvextract", "mkvpropedit")
    ctx.run("ruby", "drake", "-j" + ctx.jobs, *(f"src/{s}" for s in names), cwd=src)
    for binary in names:
        copy(src / "src" / binary, stage / "bin" / binary)
    catalog = stage / "bin/locale/zh_CN/LC_MESSAGES/mkvtoolnix.mo"
    catalog.parent.mkdir(parents=True)
    ctx.run("msgfmt", "-o", catalog, src / "po/zh_CN.po")


def build_vsedit(name, ctx, src, work, stage):
    project = src / "pro/vsedit"
    ctx.run(
        build_qmake(ctx),
        "vsedit.pro",
        "CONFIG+=release",
        "CONFIG-=app_bundle",
        "QMAKE_MACOSX_DEPLOYMENT_TARGET=11.0",
        f"QMAKE_APPLE_DEVICE_ARCHS={ctx.arch}",
        "TARGET=vsedit",
        cwd=project,
        VS_INCLUDE_PATH=str(ctx.prefix / "include/vapoursynth"),
    )
    # Qt 6.6 qmake adds AGL for Intel even though VSEdit has no AGL imports.
    # The macOS 26 SDK no longer provides its link stub.
    makefile = project / "Makefile"
    makefile.write_text(makefile.read_text().replace("-framework AGL", ""))
    ctx.run("make", "-j" + ctx.jobs, cwd=project)
    candidates = [
        p
        for p in src.rglob("vsedit*")
        if p.is_file() and p.name in ("vsedit", "vsedit-32bit") and os.access(p, os.X_OK)
    ]
    (executable,) = candidates
    copy(executable, stage / "libexec/vsedit")

# The registry is also used to resolve the exact cache plan before Actions downloads artifacts.
MEDIA_RECIPES = {
    "libudfread": (build_bluray, ()),
    "libbluray": (build_bluray, ("libudfread",)),
    "ffmpeg": (build_ffmpeg, ("libbluray",)),
    "lsmash": (build_autotools, ()),
    "x264": (build_autotools, ("ffmpeg", "lsmash")),
    "x265": (build_x265, ()),
    "svt-av1": (build_cmake_media, ()),
    "tsmuxer": (build_tsmuxer, ()),
    "fdk-aac": (build_autotools, ()),
    "fdkaac": (build_autotools, ("fdk-aac",)),
    "flac": (build_cmake_media, ()),
    "7zip": (install_7zip, ()),
    "dovi": (build_hdr_cli, ()),
    "hdr10plus": (build_hdr_cli, ()),
    "mkvtoolnix": (build_mkvtoolnix, ("qt-6.6",)),
    "vsedit": (build_vsedit, ("vapoursynth", "qt-6.6")),
    "moltenvk": (install_moltenvk, ()),
}


def build_media(ctx, versions):
    for name, (builder, dependencies) in MEDIA_RECIPES.items():
        release = versions[name]
        prebuilt = builder in (install_7zip, install_moltenvk, build_hdr_cli)

        def install(work, stage):
            if prebuilt:
                builder(name, ctx, work, stage, release)
            else:
                src = ctx.source(release[1], work / "source")
                copy_licenses(src, stage / "legal" / name)
                builder(name, ctx, src, work, stage)

        cmake = builder in (build_cmake_media, build_x265, build_tsmuxer)
        build_tools = ("cmake", "ninja") if cmake else (("meson", "ninja") if builder == build_bluray else ())
        # Limit known dependency sets. Unrestricted upstream configure checks also
        # see optional libraries in the sysroot, especially MKVToolNix and x264.
        packages = {
            "libudfread": ("pkg-config", "autoconf", "automake", "libtool"),
            "ffmpeg": ("pkg-config", "nasm", "libopus", "dav1d-devel", "libass", "zlib"),
            "x265": ("nasm",), "svt-av1": ("nasm",), "vsedit": (), "7zip": (), "moltenvk": (),
            "dovi": (), "hdr10plus": (),
        }.get(name)
        helpers = (Build.cmake,) if cmake else ()
        provider = ctx.hdr.get(name)
        revision = [release, provider] if provider else release
        downloaded = builder in (install_7zip, install_moltenvk) or (provider and "url" in provider)
        ctx.component(name, revision, install, dependencies=dependencies, recipe=recipe_digest(install, builder, *helpers),
                      scope="download" if downloaded else "native",
                      packages=packages, build_tools=build_tools)
