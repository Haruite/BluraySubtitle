"""Build the common interpreter and R79, and install isolated PyQt runtime branches."""

import json
import shutil
import sys
import subprocess
import tempfile
import urllib.request
from pathlib import Path

from tools.build_ass_extension import SOURCES as ASS_EXTENSION_SOURCES
from tools.macos_build_support import ROOT, copy, digest

PYLIB = Path(f"python/lib/python{sys.version_info.major}.{sys.version_info.minor}")
SITE = PYLIB / "site-packages"


def pypi(project):
    with urllib.request.urlopen(f"https://pypi.org/pypi/{project}/json", timeout=45) as response:
        return json.load(response)


def install_python(ctx, stage):
    source = Path(sys.base_prefix)
    shutil.copytree(
        source,
        stage / "python",
        symlinks=True,
        ignore=shutil.ignore_patterns(
            "__pycache__", "*.pyc", "*.a", "test", "tests", "idlelib", "tkinter", "_tkinter*", "tcl8*", "tk8*"
        ),
    )
    ctx.run(
        sys.executable,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--only-binary=:all:",
        "--no-compile",
        "--platform",
        f"macosx_11_0_{ctx.arch}",
        "--target",
        stage / SITE,
        *ctx.python_requirements,
    )


def install_vs(ctx, work, stage, archive):
    source = ctx.source(archive["url"], work / "source", archive["digests"]["sha256"])
    # Locate the interpreter adjacent to this R79 installation after moving the app.
    cpp = source / "src/vsscript/vsscript.cpp"
    needle = "readEnvConfig(const std::filesystem::path &vsscriptPath) {"
    code = """
#ifdef __APPLE__
    const auto privateLib = vsscriptPath.parent_path().parent_path().parent_path().parent_path();
    const auto privatePython = privateLib.parent_path() / "bin/python3";
    const auto privateDylib = privateLib / "LIBPYTHON";
    if (std::filesystem::is_regular_file(privatePython) && std::filesystem::is_regular_file(privateDylib))
        return {privatePython, privateDylib};
#endif
""".replace("LIBPYTHON", f"libpython{sys.version_info.major}.{sys.version_info.minor}.dylib")
    original = cpp.read_text()
    if needle not in original:
        raise ValueError("Unexpected R79 Python discovery implementation")
    cpp.write_text(original.replace(needle, needle + code, 1))
    # Apple's floating-point std::to_chars entry points first shipped in 13.3.
    # Boost.Charconv implements the same fixed-format and precision overloads.
    for filename in ("vspipe.cpp", "vsjson.cpp"):
        path = source / "src/vspipe" / filename
        text = path.read_text().replace(
            "#include <charconv>", "#include <charconv>\n#include <boost/charconv.hpp>"
        )
        path.write_text(
            text.replace("std::to_chars(", "boost::charconv::to_chars(").replace(
                "std::chars_format::fixed", "boost::charconv::chars_format::fixed"
            )
        )
    wheels = work / "wheels"
    build_dir = work / "meson"
    try:
        ctx.run(
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-build-isolation",
            "--no-deps",
            "-v",
            f"--config-settings=build-dir={build_dir}",
            "-w",
            wheels,
            source,
            LDFLAGS=ctx.env["LDFLAGS"] + " -lboost_charconv",
        )
    except subprocess.CalledProcessError:
        log = build_dir / "meson-logs/meson-log.txt"
        if log.exists():
            print(log.read_text()[-5000:], file=sys.stderr)
        raise
    (wheel,) = wheels.glob("*.whl")
    ctx.run(
        sys.executable, "-m", "pip", "install", "--no-deps", "--no-compile", "--target", stage / SITE, wheel
    )
    for header in (source / "include").glob("*.h"):
        copy(header, stage / "include/vapoursynth" / header.name)
    pc = stage / "lib/pkgconfig/vapoursynth.pc"
    pc.parent.mkdir(parents=True, exist_ok=True)
    pc.write_text(
        f"prefix={ctx.prefix}\n"
        "libdir=${prefix}/lib\nincludedir=${prefix}/include/vapoursynth\n"
        "Name: VapourSynth\nDescription: VapourSynth filter SDK\nVersion: 79\nCflags: -I${includedir}\n"
    )
    executable = stage / "bin/vspipe"
    executable.parent.mkdir(exist_ok=True)
    executable.symlink_to(Path("..") / SITE / "vapoursynth/vspipe")


def install_qt(ctx, stage, branch, requirements):
    target = stage / "qt" / branch
    platform = f"macosx_{'11' if branch == '6.6' else '26'}_0_{ctx.arch}"
    ctx.run(
        sys.executable,
        "-m",
        "pip",
        "install",
        "--only-binary=:all:",
        "--disable-pip-version-check",
        "--no-compile",
        "--platform",
        platform,
        "--target",
        target,
        *requirements,
    )
    # Keep the GUI, network and SVG frameworks used by the main window and VSEdit.
    package = target / "PyQt6"
    qt = package / "Qt6"
    modules = {"QtCore", "QtGui", "QtWidgets", "QtNetwork", "QtDBus", "QtSvg", "QtOpenGL", "QtOpenGLWidgets"}
    for path in package.glob("Qt*.abi3.so"):
        if path.name.split(".")[0] not in modules:
            path.unlink()
    for framework in (qt / "lib").glob("*.framework"):
        if framework.stem not in modules:
            shutil.rmtree(framework)
    for path in (qt / "plugins").iterdir():
        if path.is_dir() and path.name not in ("platforms", "imageformats", "iconengines", "styles", "tls"):
            shutil.rmtree(path)
    for name in ("qml", "qsci", "bindings", "uic"):
        directory = (qt if name == "qml" else package) / name
        if directory.is_dir():
            shutil.rmtree(directory)
    for file in (qt / "translations").glob("*.qm"):
        if file.stem not in ("qt_zh_CN", "qtbase_zh_CN", "qt_en", "qtbase_en"):
            file.unlink()
    if not (qt / "plugins/platforms/libqcocoa.dylib").is_file():
        raise ValueError(f"Qt {branch} has no Cocoa platform plugin")


def resolved_wheels(requirements, platform_tag):
    # Pin transitive wheels too. A newer CFFI or SIP build must change the key.
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "wheels.json"
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "--dry-run", "--ignore-installed",
                        "--only-binary=:all:", "--disable-pip-version-check", "--platform", platform_tag,
                        "--report", str(report), *requirements], check=True)
        wheels = []
        for item in json.loads(report.read_bytes())["install"]:
            source = item["download_info"]
            sha = source["archive_info"]["hashes"]["sha256"]
            wheels.append(f"{item['metadata']['name']} @ {source['url']}#sha256={sha}")
        return sorted(wheels)


def python_releases(arch):
    projects = ("numpy", "soundfile", "pycountry", "pillow", "psutil")
    archive = next(a for a in pypi("VapourSynth/79")["urls"] if a["packagetype"] == "sdist")
    sip = "PyQt6-sip==" + pypi("PyQt6-sip")["info"]["version"]
    branches = {
        "6.6": ("6.6.1", "6.6.3"),
        "latest": (pypi("PyQt6")["info"]["version"], pypi("PyQt6-Qt6")["info"]["version"]),
    }
    return {
        "requirements": resolved_wheels([f"{p}=={pypi(p)['info']['version']}" for p in projects],
                                       f"macosx_11_0_{arch}"),
        "vapoursynth": {"url": archive["url"], "digests": {"sha256": archive["digests"]["sha256"]}},
        "qt": {
            branch: resolved_wheels([f"PyQt6=={binding}", f"PyQt6-Qt6=={qt}", sip],
                                   f"macosx_{'11' if branch == '6.6' else '26'}_0_{arch}")
            for branch, (binding, qt) in branches.items()
        },
    }


def build_python(ctx, versions):
    from tools.macos_build_support import recipe_digest

    ctx.python_requirements = versions["requirements"]
    ctx.component(
        "python",
        [sys.version, ctx.python_requirements],
        lambda w, s: install_python(ctx, s),
        scope="python",
        recipe=recipe_digest(install_python),
    )
    ass_builder = ROOT / "tools/build_ass_extension.py"
    ctx.component(
        "ass-extension",
        [digest(path) for path in (ass_builder, *ASS_EXTENSION_SOURCES)],
        lambda _, stage: ctx.run(sys.executable, "-B", ass_builder, "--output", stage / SITE),
        scope="python",
        build_tools=("setuptools",),
        python_abi=True,
    )
    archive = versions["vapoursynth"]
    ctx.component(
        "vapoursynth",
        archive["digests"]["sha256"],
        lambda w, s: install_vs(ctx, w, s, archive),
        recipe=recipe_digest(install_vs),
        packages=("zimg", "libboost-devel", "pkg-config"),
        build_tools=("Cython", "meson", "meson-python", "ninja"), python_abi=True,
    )
    for branch, packages in versions["qt"].items():
        ctx.component(
            f"qt-{branch}",
            packages,
            lambda w, s: install_qt(ctx, s, branch, packages),
            recipe=recipe_digest(install_qt),
            scope="python",
        )
