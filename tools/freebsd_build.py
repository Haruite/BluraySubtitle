"""Build the native tools that need features beyond the default FreeBSD packages."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import gzip
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import sysconfig
import tarfile
import tempfile
from urllib.request import urlopen
from zipfile import ZipFile

from tools.lsmash_ffmpeg_compat import adapt_sources
from tools.macos_build_support import Build, copy, copy_licenses, digest, download, fingerprint, output, recipe_digest
from tools.macos_media import build_tsmuxer, github
from tools.macos_python_runtime import pypi
from tools.mpv.install import UOSC_DIR, UOSC_FONTS
from tools.mpv.vapoursynth.rife_assets import RIFE_LIBRARY, RIFE_MODEL_DIR
from tools.vapoursynth_plugin_releases import LEGACY_SOURCE_KEYS, R79_PLUGIN_NAMESPACES, SOURCES, PluginRelease, resolve_releases


ROOT = Path(__file__).resolve().parents[1]
LOCAL = Path("/usr/local")
PYTHON_VERSION = f"{sys.version_info.major}.{sys.version_info.minor}"
PYTHON_SITE = Path("lib") / f"python{PYTHON_VERSION}" / "site-packages"
VAPOURSYNTH_VERSION = "79"
PLUGIN_NAMESPACES = R79_PLUGIN_NAMESPACES | {"ccd": "ccd", "bm3d": "bm3d", "rife": "rife"}
SOURCE_TOOLS = {
    "tsmuxer": ("justdan96/tsMuxer", r"(v?\d+(?:\.\d+)+)"),
    "vsedit": ("YomikoR/VapourSynth-Editor", r"(R\d+-mod-[\d.]+)"),
    "hdr10plus_tool": ("quietvoid/hdr10plus_tool", r"(v?\d+(?:\.\d+)+)"),
    "fdkaac": ("nu774/fdkaac", r"(v?\d+(?:\.\d+)+)"),
    "mpv": ("mpv-player/mpv", r"(v\d+(?:\.\d+)+)"),
    "uosc": ("tomasklaen/uosc", r"(\d+(?:\.\d+)+)"),
}


class FreeBSDBuild(Build):
    def __init__(self, cache: Path):
        self.cache = cache
        self.arch = "amd64"
        self.flags = "-march=x86-64-v2"
        self.jobs = str(os.cpu_count() or 1)
        self.prefix = cache / "native"
        self.deps = LOCAL
        self.components = cache / "components"
        self.components.mkdir(exist_ok=True)
        self.downloads = cache / "downloads"
        self.expected = None
        self.restore = self.planning = False
        self.built = {}
        self.python_abi = sys.version
        self.system_packages = dict(line.split("\t")[:2] for line in output("pkg", "query", "%n\t%v").splitlines())
        self.version = output("uname", "-r").split("-", 1)[0]
        compiler = output("/usr/bin/cc", "--version").splitlines()[0]
        self.identities = {"native": (self.version, compiler, self.flags, str(self.prefix))}
        self.env = dict(
            os.environ,
            PATH=os.pathsep.join((str(self.prefix / "bin"), str(LOCAL / "bin"), os.environ["PATH"])),
            CFLAGS=self.flags,
            CXXFLAGS=self.flags,
            CPPFLAGS=f"-I{self.prefix}/include -I{LOCAL}/include",
            LDFLAGS=f"-L{self.prefix}/lib -L{LOCAL}/lib -Wl,-rpath,{self.prefix}/lib",
            PKG_CONFIG_PATH=f"{self.prefix}/lib/pkgconfig:{LOCAL}/libdata/pkgconfig:{LOCAL}/lib/pkgconfig",
            CMAKE_PREFIX_PATH=f"{self.prefix}:{LOCAL}",
            CMAKE_POLICY_VERSION_MINIMUM="3.10",
            CARGO_HOME=str(cache / "cargo"),
            GOMODCACHE=str(cache / "go-mod"),
            GOCACHE=str(cache / "go-build"),
            PIP_CACHE_DIR=str(cache / "pip"),
            CCACHE_DIR=str(cache / "ccache"),
            CCACHE_BASEDIR=str(cache),
            CCACHE_MAXSIZE=os.environ.get("CCACHE_MAXSIZE", "1G"),
            CCACHE_COMPILERCHECK="content",
        )

    def conda_inputs(self, packages):
        return {name: self.system_packages.get(name) for name in packages}

    def git_source(self, repo, tag, destination, *, revision="", submodules=(), sparse=()):
        identity = fingerprint([repo, tag, revision, submodules, sparse])
        cache = self.downloads / "git"
        archive = cache / f"{identity}.tar.gz"
        receipt = cache / f"{identity}.sha256"
        if archive.is_file() and receipt.is_file() and digest(archive) == receipt.read_text().strip():
            try:
                with tarfile.open(archive) as snapshot:
                    snapshot.extractall(destination, filter="data")
                return
            except (tarfile.TarError, gzip.BadGzipFile, EOFError):
                if destination.exists():
                    shutil.rmtree(destination)

        options = ("--filter=blob:none", "--sparse") if sparse else ()
        self.run("git", "clone", "--depth=1", *options, "--branch", tag, repo, destination)
        if revision and output("git", "rev-parse", f"refs/tags/{tag}", cwd=destination) != revision:
            raise ValueError(f"The tag {tag} changed while checking out {repo}")
        if sparse:
            self.run("git", "sparse-checkout", "set", *sparse, cwd=destination)
        if submodules:
            self.run("git", "submodule", "update", "--init", "--recursive", "--depth=1", *submodules, cwd=destination)
        # Preserve Git metadata because libplacebo uses it to identify its build version.
        cache.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=cache) as pending:
            staged = Path(pending) / "source.tar.gz"
            with tarfile.open(staged, "w:gz", compresslevel=2) as snapshot:
                snapshot.add(destination, arcname=".")
            checksum = staged.with_suffix(".sha256")
            checksum.write_text(digest(staged) + "\n")
            staged.replace(archive)
            checksum.replace(receipt)

    def cmake(self, source, build, *args, target=None):
        self.run("cmake", "-S", source, "-B", build, "-G", "Ninja", "-DCMAKE_BUILD_TYPE=Release",
                 "-DCMAKE_C_COMPILER_LAUNCHER=ccache", "-DCMAKE_CXX_COMPILER_LAUNCHER=ccache",
                 f"-DCMAKE_INSTALL_PREFIX={self.prefix}", *args)
        self.run("cmake", "--build", build, "--parallel", self.jobs, *(["--target", target] if target else []))

    def meson(self, source, build, *options, **environment):
        self.run("meson", "setup", build, source, "--buildtype=release", "-Db_lto=false",
                 f"--prefix={self.prefix}", *options, CC="ccache cc", CXX="ccache c++", **environment)
        self.run("meson", "compile", "-C", build, "-j", self.jobs)


def build_vapoursynth(ctx, work, stage, archive):
    source = ctx.source(archive["url"], work / "source", archive["digests"]["sha256"])
    memory = source / "src/core/memoryuse.cpp"
    memory.write_text(memory.read_text().replace("#elif defined(VS_TARGET_OS_DARWIN)", "#elif defined(__FreeBSD__)")
                      .replace('"hw.memsize"', '"hw.physmem"'))
    cpp = source / "src/vsscript/vsscript.cpp"
    text = cpp.read_text()
    marker = "readEnvConfig(const std::filesystem::path &vsscriptPath) {"
    if text.count(marker) != 1:
        raise ValueError("Unexpected VapourSynth interpreter discovery")
    # VSPipe and mpv must embed the interpreter from the relocated package.
    patch = f"""
    const auto privateLib = vsscriptPath.parent_path().parent_path().parent_path().parent_path();
    const auto privatePython = privateLib.parent_path() / "bin/python3";
    const auto privateLibrary = privateLib / "{sysconfig.get_config_var('INSTSONAME')}";
    if (std::filesystem::is_regular_file(privatePython) && std::filesystem::is_regular_file(privateLibrary))
        return {{privatePython, privateLibrary}};
"""
    cpp.write_text(text.replace(marker, marker + patch))
    build = work / "build"
    # The PyPI source archive includes the pinned subprojects used by its release wheels.
    ctx.run(sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation", "-v",
            "-Cbuild-dir=" + str(build), "-w", work / "wheel", source, CC="ccache cc", CXX="ccache c++")
    wheel, = (work / "wheel").glob("*.whl")
    ctx.run(sys.executable, "-m", "pip", "install", "--no-deps", "--no-compile", "--target", stage / PYTHON_SITE, wheel)
    installed = stage / PYTHON_SITE / "vapoursynth"
    if not (installed / "libvapoursynth.so").exists():
        library, = installed.glob("libvapoursynth.so.*")
        (installed / "libvapoursynth.so").symlink_to(library.name)
    for header in (source / "include").glob("*.h"):
        copy(header, stage / "include/vapoursynth" / header.name)
    copy_licenses(source, stage / "legal/vapoursynth")
    library = ctx.prefix / PYTHON_SITE / "vapoursynth"
    pc = stage / "lib/pkgconfig"
    pc.mkdir(parents=True)
    common = f"libdir={library}\nincludedir={ctx.prefix}/include/vapoursynth\n"
    for name, link in (("vapoursynth", "vapoursynth"), ("vapoursynth-script", "vsscript")):
        (pc / (name + ".pc")).write_text(common + f"Name: {name}\nDescription: VapourSynth SDK\n"
                                         f"Version: {VAPOURSYNTH_VERSION}\n"
                                         f"Cflags: -I${{includedir}}\nLibs: -L${{libdir}} -l{link}\n")


def build_vsedit(ctx, source, stage):
    project = source / "pro/vsedit"
    pro = project / "vsedit.pro"
    pro.write_text(pro.read_text().replace(', "x86_64")', ', "amd64|x86_64")'))
    console = source / "common-src/win32_console.cpp"
    console.write_text(re.sub(r"(?m)^#pragma comment \(lib, .*\)\n", "", console.read_text()))
    qmake = next(path for path in (LOCAL / "lib/qt6/bin/qmake", LOCAL / "bin/qmake6") if path.is_file())
    ctx.run(qmake, "vsedit.pro", "CONFIG+=release", "QMAKE_CXX=ccache c++", f"QMAKE_CXXFLAGS+={ctx.flags}",
            "-after", "TARGET=vsedit", cwd=project,
            VS_INCLUDE_PATH=str(ctx.prefix / "include/vapoursynth"))
    ctx.run("gmake", "-j" + ctx.jobs, cwd=project)
    executable, = (path for path in source.rglob("vsedit") if path.is_file() and os.access(path, os.X_OK))
    copy(executable, stage / "bin/vsedit")


def build_freebsd_tsmuxer(ctx, source, work, stage):
    renderer = source / "tsMuxer/osdep/textSubtitlesRenderFT.cpp"
    text = renderer.read_text()
    marker = "#elif defined(__NetBSD__)"
    if "defined(__FreeBSD__)" not in text:
        text = text.replace(marker, '#elif defined(__FreeBSD__)\nconst static char FONT_ROOT[] = "/usr/local/share/fonts/";\n' + marker)
        renderer.write_text(text)
    build_tsmuxer("tsmuxer", ctx, source, work, stage)


def build_mpv(ctx, source, work, stage, placebo):
    tag, url = placebo
    renderer = source / "subprojects/libplacebo"
    renderer.parent.mkdir(exist_ok=True)
    submodules = ("glad", "jinja", "markupsafe", "Vulkan-Headers", "fast_float")
    ctx.git_source("https://github.com/haasn/libplacebo.git", tag, renderer, revision=url.rsplit("/", 1)[1],
                   submodules=tuple(f"3rdparty/{name}" for name in submodules))
    build = work / "build"
    ctx.meson(source, build, "-Dlibbluray=enabled", "-Dvapoursynth=enabled", "-Dlua=luajit",
              "-Dlibmpv=false", "-Dmanpage-build=disabled", "-Dvulkan=enabled",
              "-Dx11=enabled", "-Dwayland=enabled", "-Doss-audio=enabled", "-Ddvbin=disabled",
              "-Ddvdnav=enabled", "-Dgl=enabled", "-Dshaderc=disabled", "--force-fallback-for=libplacebo",
              "-Dlibplacebo:vulkan=enabled", "-Dlibplacebo:opengl=enabled", "-Dlibplacebo:shaderc=enabled",
              LDFLAGS=ctx.env["LDFLAGS"] + " -Wl,--exclude-libs,libplacebo.a")
    copy(build / "mpv", stage / "bin/mpv")
    legal = stage / "legal/libplacebo-mpv"
    copy_licenses(renderer, legal)
    for name in submodules:
        copy_licenses(renderer / "3rdparty" / name, legal / name)


def build_uosc(ctx, source, stage, tag):
    assets = stage / "mpv"
    uosc = assets / UOSC_DIR
    shutil.copytree(source / "src/uosc", uosc, ignore=shutil.ignore_patterns("bin"))
    fonts = assets / "fonts"
    fonts.mkdir()
    url = f"https://github.com/tomasklaen/uosc/releases/download/{tag}/uosc.zip"
    with ZipFile(download(url, ctx.downloads)) as release:
        for name in UOSC_FONTS:
            (fonts / name).write_bytes(release.read(f"fonts/{name}"))
    binary = uosc / "bin/ziggy-freebsd"
    binary.parent.mkdir()
    environment = dict(ctx.env, CGO_ENABLED="0", GOAMD64="v2", GOTOOLCHAIN="local")
    subprocess.run(["go", "build", "-trimpath", "-ldflags=-s -w", "-o", binary, "./src/ziggy"],
                   cwd=source, env=environment, check=True)
    license_root = stage / "legal/uosc"
    copy_licenses(Path(output("go", "env", "GOROOT")), license_root / "go")
    modules = subprocess.check_output(
        ["go", "list", "-deps", "-f", '{{with .Module}}{{if not .Main}}{{.Path}}{{"\t"}}{{.Dir}}{{end}}{{end}}',
         "./src/ziggy"], cwd=source, env=environment, text=True,
    )
    for module in sorted(set(modules.splitlines()) - {""}):
        path, directory = module.split("\t")
        copy_licenses(Path(directory), license_root / "go-modules" / path)


def build_fdkaac(ctx, source, stage):
    if not (source / "configure").is_file():
        ctx.run("autoreconf", "-fiv", cwd=source)
    ctx.run("sh", "configure", f"--prefix={ctx.prefix}", cwd=source)
    ctx.run("gmake", "-j" + ctx.jobs, cwd=source)
    copy(source / "fdkaac", stage / "bin/fdkaac")


def build_hdr10plus(ctx, source, stage):
    ctx.run("cargo", "build", "--locked", "--release", "--bin", "hdr10plus_tool", cwd=source,
            RUSTFLAGS="-Ctarget-cpu=x86-64-v2", CARGO_BUILD_JOBS=ctx.jobs)
    copy(source / "target/release/hdr10plus_tool", stage / "bin/hdr10plus_tool")


def build_source_tools(ctx):
    with ThreadPoolExecutor(max_workers=8) as pool:
        renderer = pool.submit(github, "haasn/libplacebo", r"(v\d+(?:\.\d+)+)")
        tools = list(pool.map(lambda pair: github(*pair), SOURCE_TOOLS.values()))
        rife_source = SOURCES["rife"]
        rife = pool.submit(github, rife_source.repository, f"({rife_source.stable_tags})")
        filters = pool.submit(resolve_releases, (LEGACY_SOURCE_KEYS.get(name, name)
                                                 for name in PLUGIN_NAMESPACES if name != "rife"))
        metadata = pypi("VapourSynth")
        archive, = (asset for asset in metadata["releases"][VAPOURSYNTH_VERSION] if asset["packagetype"] == "sdist")
        releases = filters.result()
        releases["rife"] = PluginRelease(*rife.result())
        placebo = renderer.result()
    ctx.component("vapoursynth", [VAPOURSYNTH_VERSION, archive["digests"]["sha256"]],
                  lambda work, stage: build_vapoursynth(ctx, work, stage, archive),
                  recipe=recipe_digest(build_vapoursynth), packages=("meson", "ninja", "zimg"), python_abi=True)
    versions = {"vapoursynth": [f"R{VAPOURSYNTH_VERSION}", "https://github.com/vapoursynth/vapoursynth"],
                "libplacebo-mpv": placebo}
    builders = {"tsmuxer": build_freebsd_tsmuxer, "vsedit": build_vsedit, "mpv": build_mpv,
                "fdkaac": build_fdkaac, "hdr10plus_tool": build_hdr10plus, "uosc": build_uosc}
    for name, (tag, url) in zip(SOURCE_TOOLS, tools, strict=True):
        builder = builders[name]

        def install(work, stage):
            source = ctx.source(url, work / "source")
            if name == "mpv":
                builder(ctx, source, work, stage, placebo)
            elif name == "tsmuxer":
                builder(ctx, source, work, stage)
            elif name == "uosc":
                builder(ctx, source, stage, tag)
            else:
                builder(ctx, source, stage)
            copy_licenses(source, stage / "legal" / name)

        packages = {"mpv": ("ffmpeg", "libbluray", "libdvdnav", "libass", "libplacebo", "luajit", "vulkan-loader",
                            "wayland", "wayland-protocols", "libXpresent", "mesa-libs"),
                    "vsedit": ("qt6-base", "qt6-multimedia", "qt6-websockets"),
                    "tsmuxer": ("cmake-core", "ninja", "freetype2"),
                    "fdkaac": ("fdk-aac",),
                    "hdr10plus_tool": ("rust",),
                    "uosc": ("go",)}[name]
        dependencies = ("vapoursynth",) if name in {"mpv", "vsedit"} else ()
        inputs = [tag, url, *placebo] if name == "mpv" else [tag, url]
        ctx.component(name, inputs, install, dependencies=dependencies,
                      recipe=recipe_digest(install, builder, FreeBSDBuild.cmake, FreeBSDBuild.meson, copy_licenses),
                      packages=packages)
        versions[name] = [tag, url]
    build_filters(ctx, releases)
    versions.update({"vs-" + name: [release.ref, release.source_url] for name, release in releases.items()})
    return versions


def make_filter(ctx, source, files, target, *flags, cpp=True):
    ctx.run("ccache", "c++" if cpp else "cc", "-shared", "-fPIC", "-O3", ctx.flags,
            *(["-std=c++17"] if cpp else []), f"-I{ctx.prefix}/include/vapoursynth", f"-I{ctx.prefix}/include", "-I/usr/local/include",
            *flags, *files, "-o", target, cwd=source)


def build_zsmooth(ctx, source, stage):
    match = re.search(r'\.minimum_zig_version\s*=\s*"([\d.]+)"', (source / "build.zig.zon").read_text())
    if match is None:
        raise ValueError("zsmooth does not declare its Zig toolchain version")
    system_zig = shutil.which("zig" + match[1].rsplit(".", 1)[0].replace(".", "")) or shutil.which("zig")
    zig = ctx.cache / ("zig-" + match[1])
    if system_zig and output(system_zig, "version") == match[1]:
        compiler = system_zig
    else:
        compiler = zig / "zig"
    if not Path(compiler).is_file():
        with urlopen("https://ziglang.org/download/index.json", timeout=30) as response:
            release = json.load(response)[match[1]]["x86_64-freebsd"]
        with tempfile.TemporaryDirectory(dir=ctx.cache) as pending:
            sources = ctx.source(release["tarball"], Path(pending) / "zig", release["shasum"])
            sources.rename(zig)
    build = source / "build.zig"
    text, declarations = re.subn(r'(?ms)^    const fftw_dep = b\.dependency\("fftw", \.\{.*?^    \}\);\n',
                                  "", build.read_text(), count=1)
    link = 'root_module.linkLibrary(fftw_dep.artifact("fftw3f"));'
    if declarations != 1 or text.count(link) != 1:
        raise ValueError("Unexpected zsmooth FFTW build dependency")
    build.write_text(text.replace(link, '''root_module.addLibraryPath(.{ .cwd_relative = "/usr/local/lib" });
    root_module.linkSystemLibrary("fftw3f_threads", .{});
    root_module.linkSystemLibrary("fftw3f", .{});'''))
    ctx.run(compiler, "build", "-Doptimize=ReleaseFast", "-Dtarget=x86_64-freebsd", "-Dcpu=baseline",
            "-j" + ctx.jobs, cwd=source, ZIG_GLOBAL_CACHE_DIR=str(ctx.cache / "zig-cache"))
    library = stage / "libzsmooth.so"
    copy(source / "zig-out/lib/libzsmooth.so", library)
    ctx.run("brandelf", "-t", "FreeBSD", library)


def build_rife(ctx, work, stage, release):
    source = work / "source"
    # Use the ncnn and glslang submodules selected by the RIFE release.
    ctx.git_source(SOURCES["rife"].url + ".git", release.ref, source, revision=release.source_url.rsplit("/", 1)[1],
                   submodules=("subprojects/ncnn",), sparse=("RIFE", RIFE_MODEL_DIR, "subprojects"))
    build = work / "build"
    ctx.meson(source, build, "-Duse_system_ncnn=false", PYTHONPATH=str(ctx.prefix / PYTHON_SITE))
    copy(build / "librife.so", stage / RIFE_LIBRARY)
    shutil.copytree(source / RIFE_MODEL_DIR, stage / RIFE_MODEL_DIR)
    legal = stage.parent / "legal/vs-rife"
    ncnn = source / "subprojects/ncnn"
    copy_licenses(source, legal)
    copy_licenses(ncnn, legal / "ncnn")
    copy_licenses(ncnn / "glslang", legal / "glslang")


def build_filters(ctx, releases):
    direct_filters = {
        "bilateral": ("libbilateral.so", ("source", "*.cpp")),
        "sangnom": ("libsangnommod.so", ("src", "sangnom.cpp")),
        "removegrain": ("libremovegrain.so", ("src", "*.cpp")),
        "vivtc": ("libvivtc.so", ("src", "vivtc.c")),
    }
    sdk = str(ctx.prefix / PYTHON_SITE)
    for name, release in releases.items():
        def install(work, stage):
            plugins = stage / "plugins"
            plugins.mkdir()
            if name == "rife":
                build_rife(ctx, work, plugins, release)
                return
            source = ctx.source(release.source_url, work / "source", release.sha256)
            copy_licenses(source, stage / "legal" / ("vs-" + name))
            build = work / "build"
            if name in direct_filters:
                filename, (parent, glob) = direct_filters[name]
                make_filter(ctx, source, sorted((source / parent).glob(glob)), plugins / filename,
                            "-Iinclude", cpp=name != "vivtc")
            elif name == "legacy-filters":
                make_filter(ctx, source, ["src/filters/eedi3/eedi3.c"], plugins / "libeedi3.so", "-Iinclude", cpp=False)
                make_filter(ctx, source, ["src/filters/misc/miscfilters.cpp"], plugins / "libmiscfilters.so",
                            "-Iinclude", "-I.", "-DVS_TARGET_CPU_X86")
            elif name == "znedi3":
                ctx.run("gmake", "-j" + ctx.jobs, "X86=1", "X86_AVX512=1", cwd=source)
                copy(source / "vsznedi3.so", plugins / "znedi3.so")
                copy(source / "nnedi3_weights.bin", plugins / "nnedi3_weights.bin")
            elif name == "fmtconv":
                location = source / "build/unix" if (source / "build/unix/autogen.sh").is_file() else source
                ctx.run("sh", "autogen.sh", cwd=location)
                # FreeBSD's amd64 name does not select the x86 objects in this configure script.
                ctx.run("sh", "configure", f"--build=x86_64-unknown-freebsd{ctx.version}",
                        f"--prefix={ctx.prefix}", cwd=location, CC="ccache cc", CXX="ccache c++")
                ctx.run("gmake", "-j" + ctx.jobs, cwd=location)
                copy(next(path for path in location.rglob("libfmtconv.so*") if path.is_file()), plugins / "libfmtconv.so")
            elif name == "zsmooth":
                build_zsmooth(ctx, source, plugins)
            elif name in {"assrender", "nlm_ispc"}:
                options = ()
                if name == "nlm_ispc":
                    options = ("-DCMAKE_DISABLE_FIND_PACKAGE_Git=ON", f"-DVCS_TAG={release.ref}",
                               "-DCMAKE_ISPC_INSTRUCTION_SETS=sse2-i32x4;avx2-i32x8")
                ctx.cmake(source, build, *options)
                shared = "libvsnlm_ispc.so" if name == "nlm_ispc" else "libassrender.so"
                copy(next(build.rglob(shared)), plugins / shared)
            else:
                if name == "lsmas":
                    version = subprocess.check_output(["pkg-config", "--modversion", "libavcodec"], env=ctx.env, text=True)
                    adapt_sources(source, int(version.split(".")[0]))
                    source = source / "VapourSynth"
                if name == "eedi3m":
                    header = source / "EEDI3/EEDI3.h"
                    header.write_text("#include <cmath>\n" + header.read_text())
                flags = ctx.env["LDFLAGS"] + (" -lfftw3f_threads" if name == "dfttest" else "")
                ctx.meson(source, build, PYTHONPATH=sdk, LDFLAGS=flags)
                shared, = (path for path in build.glob("*.so") if path.is_file())
                copy(shared, plugins / shared.name)

        packages = {"lsmas": ("ffmpeg", "l-smash", "xxhash"), "assrender": ("libass",),
                    "nlm_ispc": ("ispc",), "dfttest": ("fftw3-float",), "mvtools": ("fftw3-float",),
                    "eedi3m": ("fftw3-float",), "placebo": ("libplacebo", "shaderc", "vulkan-headers"),
                    "zsmooth": ("fftw3-float", "zig015"),
                    "rife": ("vulkan-headers", "vulkan-loader")}.get(name, ())
        builders = {"rife": build_rife, "zsmooth": build_zsmooth, "lsmas": adapt_sources}
        builder = builders.get(name, make_filter)
        recipe = [recipe_digest(install, builder, FreeBSDBuild.cmake, FreeBSDBuild.meson), direct_filters.get(name)]
        if name == "rife":
            recipe.extend((RIFE_LIBRARY, RIFE_MODEL_DIR))
        ctx.component("vs-" + name, [release.ref, release.source_url, release.sha256], install, recipe=recipe,
                      dependencies=("vapoursynth",), packages=packages)
