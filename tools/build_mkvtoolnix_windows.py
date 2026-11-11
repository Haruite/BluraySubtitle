"""Build and cache the native Windows MKVToolNix command-line tools."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.windows_build_cache import files_under, publish, restore
from tools.windows_native_tools import (
    MKV_RECIPE, build_record, clean_tool_environment, fetch_verified, file_hash, fingerprint,
    imported_symbols, install_build, record_build, runtime_dependencies, tool_version, verify_mkv_runtime,
)
from tools.windows_tool_paths import MKV_SETTINGS


MSYS2_REQUIRED = 75
QT_FEATURES_OFF = ("gui", "widgets", "dbus", "sql", "xml", "testlib", "concurrent", "icu")
SECTION_FLAGS = "-ffunction-sections -fdata-sections"


def unpack_source(archive: Path, destination: Path) -> Path:
    with tarfile.open(archive) as source:
        # The command-line build does not need symbolic links on Windows.
        source.extractall(destination, members=(member for member in source if member.isfile() or member.isdir()),
                          filter="data")
    return destination / archive.name.removesuffix(".tar.xz")


def build_qtcore(work: Path, prefix: Path, compiler: Path, cache: Path, env: dict, jobs: int,
                 cxx_flags: str) -> tuple[Path, str]:
    version = subprocess.check_output([prefix / "bin/qmake6.exe", "-query", "QT_VERSION"], env=env, text=True).strip()
    match = re.fullmatch(r"(\d+\.\d+)\.\d+", version)
    if not match:
        raise ValueError(f"Unexpected MSYS2 Qt version: {version}")
    gcc_version = subprocess.check_output([compiler / "g++.exe", "-dumpfullversion"], env=env, text=True).strip()
    qt_key = fingerprint(MKV_RECIPE, version, gcc_version, file_hash(prefix / "bin/Qt6Core.dll"))
    archive = cache / "mkvtoolnix-qtcore.zip"
    payload = work / "qtcore"
    if restore(archive, qt_key, payload):
        return payload, version

    filename = f"qtbase-everywhere-src-{version}.tar.xz"
    url = f"https://download.qt.io/archive/qt/{match[1]}/{version}/submodules/{filename}"
    downloads = cache.parent / "downloads/mkvtoolnix"
    checksum = downloads / (filename + ".sha256")
    if not checksum.is_file():
        with urllib.request.urlopen(url + ".sha256", timeout=60) as response:
            digest = response.read().decode("ascii").split()[0].lower()
    else:
        digest = checksum.read_text(encoding="ascii").split()[0].lower()
    if not re.fullmatch("[0-9a-f]{64}", digest):
        raise ValueError(f"Invalid Qt source checksum: {url}")
    source = unpack_source(fetch_verified(url, downloads / filename, digest), work)
    checksum.write_text(digest + "\n", encoding="ascii", newline="\r\n")
    build = work / "qb"
    cmake = compiler / "cmake.exe"
    subprocess.run([
        cmake, "-S", source, "-B", build, "-G", "Ninja",
        f"-DCMAKE_C_COMPILER={compiler / 'gcc.exe'}", f"-DCMAKE_CXX_COMPILER={compiler / 'g++.exe'}",
        f"-DCMAKE_MAKE_PROGRAM={compiler / 'ninja.exe'}",
        f"-DCMAKE_PREFIX_PATH={prefix};{compiler.parent}", "-DCMAKE_BUILD_TYPE=Release", "-DBUILD_SHARED_LIBS=OFF",
        f"-DCMAKE_C_FLAGS={SECTION_FLAGS}", f"-DCMAKE_CXX_FLAGS={cxx_flags}",
        "-DQT_BUILD_TESTS=OFF", "-DQT_BUILD_EXAMPLES=OFF", "-DQT_BUILD_BENCHMARKS=OFF",
        "-DFEATURE_network=ON", "-DFEATURE_optimize_size=ON",
        *(f"-DFEATURE_{feature}=OFF" for feature in QT_FEATURES_OFF),
    ], env=env, check=True)
    subprocess.run([cmake, "--build", build, "--target", "Core", "--parallel", str(min(jobs, 8))], env=env, check=True)
    payload.mkdir()
    shutil.copyfile(build / "lib/libQt6Core.a", payload / "libQt6Core.a")
    prl = build / "src/corelib/preliminary_prl_for_Core_step1_Release.prl"
    libraries = next(line.partition("=")[2].strip().split(";") for line in prl.read_text(encoding="utf-8").splitlines()
                     if line.startswith("QMAKE_PRL_LIBS_FOR_CMAKE ="))
    # Preserve the exact library filenames while allowing the archive to move between machines.
    flags = ["-l:" + Path(name).name if Path(name).is_absolute() else "-l" + name for name in libraries if name]
    (payload / "libraries.txt").write_text("\n".join(flags) + "\n", encoding="utf-8", newline="\r\n")
    shutil.copytree(source / "LICENSES", payload / "licenses/Qt")
    publish(archive, qt_key, files_under(payload))
    return payload, version


def build_icons(source: Path) -> None:
    import gzip

    from PIL import Image
    from PyQt6.QtCore import QByteArray, Qt
    from PyQt6.QtGui import QGuiApplication, QImage, QPainter
    from PyQt6.QtSvg import QSvgRenderer

    _application = QGuiApplication.instance() or QGuiApplication(["mkvtoolnix-icons", "-platform", "offscreen"])
    icons = source / "share/icons/windows"
    icons.mkdir(parents=True, exist_ok=True)
    for executable in MKV_SETTINGS:
        name = Path(executable).stem
        svg = source / "share/icons/mkvtoolnix" / (("mkvtoolnix" if name == "mkvmerge" else name) + ".svgz")
        renderer = QSvgRenderer(QByteArray(gzip.decompress(svg.read_bytes())))
        if not renderer.isValid():
            raise ValueError(f"Invalid upstream icon: {svg}")
        pixels = QImage(256, 256, QImage.Format.Format_RGBA8888)
        pixels.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixels)
        renderer.render(painter)
        painter.end()
        data = pixels.constBits()
        data.setsize(pixels.sizeInBytes())
        Image.frombytes("RGBA", (256, 256), bytes(data)).save(icons / (name + ".ico"))


def patch_rake(source: Path) -> None:
    # Keep Ruby's temporary shell scripts in LF format.
    helpers = source / "rake.d/helpers.rb"
    text = helpers.read_text(encoding="utf-8").replace(
        'Tempfile.open("mkvtoolnix-rake-run") do |t|\n      t.puts',
        'Tempfile.open("mkvtoolnix-rake-run") do |t|\n      t.binmode\n      t.puts',
    )
    helpers.write_text(text, encoding="utf-8", newline="\n")
    # Let Rake compile the programs' prerequisites and capture the final link commands.
    application = source / "rake.d/application.rb"
    text, count = re.subn(
        r'(?m)^([ \t]*)runq "link", t\.name, (.+)$', r'\1File.write("#{t.name}.link", \2)',
        application.read_text(encoding="utf-8"),
    )
    if count != 1:
        raise RuntimeError("Unsupported MKVToolNix application linker rule")
    application.write_text(text, encoding="utf-8", newline="\n")
    shutil.copyfile(next(source.glob("rake.d/vendor/drake-*/bin/drake")), source / "drake")


def build_cli(source: Path, msys: Path, prefix: Path, jobs: int, cxx_flags: str) -> None:
    cygpath = msys / "usr/bin/cygpath.exe"
    posix_prefix = subprocess.check_output([cygpath, "-u", prefix], text=True).strip()
    posix_work = subprocess.check_output([cygpath, "-u", source.parent], text=True).strip()
    quote = shlex.quote
    build_icons(source)
    patch_rake(source)
    script = source.parent / "build-mkvtoolnix.sh"
    script.write_text("\n".join((
        "set -eu",
        f"deps={quote(posix_prefix)}",
        'export PATH="$deps/bin:/ucrt64/bin:/usr/bin"',
        f"mkdir -p {quote(posix_work + '/t')}",
        f"export TMPDIR={quote(posix_work + '/t')}",
        'export MINGW_PREFIX="$deps"',
        'export PKG_CONFIG_LIBDIR="$deps/lib/pkgconfig:/ucrt64/lib/pkgconfig"',
        'win_deps=$(cygpath -m "$deps")',
        "export CC=gcc CXX=g++ AR=ar RANLIB=ranlib WINDRES=windres STRIP=strip",
        'export CPPFLAGS="-I$win_deps/include -I$win_deps/include/qt6 -I$win_deps/include/qt6/QtCore"',
        'export LDFLAGS="-L$win_deps/lib"',
        f"export CFLAGS={quote('-Os -DNDEBUG ' + SECTION_FLAGS)} CXXFLAGS={quote('-Os -DNDEBUG ' + cxx_flags)}",
        "export INKSCAPE=/usr/bin/true MAGICK=/usr/bin/true",
        "/usr/bin/dash ./configure --build=x86_64-w64-mingw32 --host=x86_64-w64-mingw32 "
        "--disable-gui --disable-debug --disable-optimization --enable-precompiled-headers "
        '--with-qmake6="$deps/bin/qmake6.exe" --with-boost="$win_deps" --with-boost-filesystem=boost_filesystem-mt',
        # The icons are already rendered from the source SVGs.
        r"sed -i -E 's/^(INKSCAPE|MAGICK|CONVERT)[[:space:]]*=.*/\1 =/' build-config",
        r"sed -i -E 's/^(QT_CFLAGS = .*)$/\1 -DQT_STATIC/' build-config",
        "export RUBYSHELL=$(cygpath -m /usr/bin/dash.exe)",
        f"ruby ./drake -j{jobs} " + " ".join("apps:" + Path(name).stem for name in MKV_SETTINGS),
        "",
    )), encoding="utf-8", newline="\n")
    subprocess.run([msys / "usr/bin/dash.exe", posix_work + "/" + script.name], cwd=source, check=True)


def link_cli(source: Path, qtcore: Path, compiler: Path, env: dict) -> Path:
    commands = {name: shlex.split((source / "src" / (name + ".link")).read_text(encoding="utf-8"))[1:]
                for name in MKV_SETTINGS}
    linked = source.parent / "linked"
    linked.mkdir()
    core = qtcore / "libQt6Core.a"
    libraries = (qtcore / "libraries.txt").read_text(encoding="utf-8").splitlines()
    common_archives = [path for name in (
        "src/common/libmtxcommon.a", "lib/libmatroska/src/libmatroska.a", "lib/libebml/src/libebml.a",
        "lib/fmt/src/libfmt.a", "lib/pugixml/src/libpugixml.a",
    ) if (path := source / name).is_file()]
    bundled_libs = {"-l" + path.stem.removeprefix("lib") for path in common_archives}
    frontend_inputs = {argument for command in commands.values() for argument in command if argument.endswith(".o")}
    frontend_inputs.update(path.relative_to(source).as_posix() for path in (source / "src").rglob("*.a")
                           if path.name != "libmtxcommon.a")

    def symbols(option, inputs):
        output = subprocess.check_output([compiler / "nm.exe", "-g", "-P", option, *inputs], cwd=source,
                                         env=env, encoding="utf-8", errors="replace")
        return {fields[0]: fields[1] for line in output.splitlines()
                if len(fields := line.split()) >= 2 and len(fields[1]) == 1 and not fields[0].startswith(".")}

    defined = symbols("--defined-only", [core, *common_archives])
    exports = sorted(defined.keys() & symbols("--undefined-only", sorted(frontend_inputs)).keys())
    if not exports:
        raise RuntimeError("Could not resolve the MKVToolNix common-library exports")
    definitions = linked / "libmtxcommon.def"

    def is_qt_import(arg):
        return Path(arg).name == "libQt6Core.dll.a" or arg == "-lQt6Core"

    def link(name, args):
        response = linked / f"{name}.rsp"
        response.write_text("".join(f'"{arg}"\n' for arg in args), encoding="utf-8", newline="\n")
        subprocess.run([compiler / "g++.exe", "-s", "@" + str(response)], cwd=source, env=env, check=True)

    common_args = commands["mkvinfo.exe"]
    common_libs = common_args[common_args.index("-lmtxcommon"):]
    if not any(map(is_qt_import, common_libs)):
        raise RuntimeError("Could not find the QtCore link input")
    qt_index = next(index for index, arg in enumerate(common_libs) if is_qt_import(arg))
    common_libs[qt_index:qt_index + 1] = [core.as_posix(), *libraries]
    import_library = (linked / "libmtxcommon.dll.a").as_posix()
    common_link = [
        *common_args[:common_args.index("-o")], "-shared", "-Wl,--gc-sections,--exclude-all-symbols",
        f"-Wl,--out-implib={import_library}", "-o", (linked / "libmtxcommon.dll").as_posix(), definitions.as_posix(),
    ]
    common_libraries = [arg for arg in common_libs if Path(arg).name != "libQt6EntryPoint.a"]

    def link_common(names):
        definitions.write_text("LIBRARY libmtxcommon.dll\nEXPORTS\n" + "".join(
            f"  {name}{' DATA' if defined[name] in 'RDBGSV' else ''}\n" for name in names
        ), encoding="ascii", newline="\n")
        link("libmtxcommon", [
            *common_link, *("-Wl,--undefined=" + name for name in names),
            "-Wl,--start-group", *common_libraries, "-Wl,--end-group",
        ])

    link_common(exports)
    for name, args in commands.items():
        args[args.index("-o") + 1] = (linked / name).as_posix()
        args[args.index("-lmtxcommon")] = import_library
        link(name, [*(arg for arg in args if not is_qt_import(arg) and arg not in bundled_libs),
                    "-Wl,--gc-sections"])
    # Discard exports referenced only by object sections removed from the executables.
    imports = imported_symbols(linked / name for name in commands)["libmtxcommon.dll"]
    used = sorted(name.decode("ascii") for name in imports)
    if used != exports:
        link_common(used)
    return linked


def build_from_source(args, work: Path, payload: Path, key: str, prefix: Path) -> None:
    filename = f"mkvtoolnix-{args.version}.tar.xz"
    downloads = args.cache.parent / "downloads/mkvtoolnix"
    source = unpack_source(fetch_verified(args.source, downloads / filename, args.sha256), work)
    compiler = args.msys2_root / "ucrt64/bin"
    env = clean_tool_environment()
    env["PATH"] = os.pathsep.join(map(str, (compiler, prefix / "bin", args.msys2_root / "usr/bin", env["PATH"])))
    probe = subprocess.run(
        [compiler / "g++.exe", "-Os", "-fno-declone-ctor-dtor", "-x", "c++", "-c", "-o", work / "gcc-option.o", "-"],
        input="int main() {}\n", capture_output=True, text=True, env=env,
    )
    cxx_flags = SECTION_FLAGS + (" -fno-declone-ctor-dtor" if probe.returncode == 0 else "")
    qtcore, qt_version = build_qtcore(work, prefix, compiler, args.cache, env, args.jobs, cxx_flags)
    build_cli(source, args.msys2_root, prefix, args.jobs, cxx_flags)
    linked = link_cli(source, qtcore, compiler, env)
    stage_cli(source, linked, qtcore, prefix, compiler, payload, env)
    record_build(payload, "mkvtoolnix", MKV_RECIPE, args.version, key, MKV_SETTINGS,
                 source_url=args.source, source_sha256=args.sha256, qt_version=qt_version)


def stage_cli(source: Path, linked: Path, qtcore: Path, prefix: Path, compiler: Path, payload: Path, env: dict) -> None:
    programs = [linked / name for name in MKV_SETTINGS]
    dependencies = runtime_dependencies(programs, [linked, prefix / "bin", compiler])
    verify_mkv_runtime(programs, dependencies)
    payload.mkdir()
    for path in programs + list(dependencies.values()):
        name = "libFLAC.dll" if path.name.lower() == "libflac.dll" else path.name
        shutil.copyfile(path, payload / name)
    for translation in sorted((source / "po").glob("*.po")):
        destination = payload / "locale" / translation.stem / "LC_MESSAGES/mkvtoolnix.mo"
        destination.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([compiler / "msgfmt.exe", "--check", "-o", destination, translation], env=env, check=True)
    shutil.copytree(qtcore / "licenses", payload / "licenses")
    shutil.copytree(source / "doc/licenses", payload / "licenses/components")
    shutil.copyfile(source / "COPYING", payload / "licenses/COPYING")


def verify(directory: Path, record: dict, entrypoints: dict[str, str]) -> None:
    for name, executable in entrypoints.items():
        version = tool_version(directory / executable)
        if not re.match(rf"{re.escape(Path(name).stem)} v{re.escape(record['version'])}(?:\s|$)", version):
            raise RuntimeError(f"Unexpected version from {executable}: {version}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("version", "install"))
    parser.add_argument("directory", type=Path)
    parser.add_argument("executables", nargs=4, metavar="EXE")
    parser.add_argument("--version", default="")
    parser.add_argument("--source")
    parser.add_argument("--sha256")
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--work", type=Path)
    parser.add_argument("--msys2-root", type=Path)
    parser.add_argument("--jobs", type=int, default=os.cpu_count() or 1)
    parser.add_argument("--defer-msys2", action="store_true")
    args = parser.parse_args()
    entrypoints = dict(zip(MKV_SETTINGS, args.executables, strict=True))
    if args.operation == "version":
        record = build_record(args.directory, "mkvtoolnix", installed=True)
        if record and record["entrypoints"] == entrypoints:
            try:
                verify(args.directory, record, entrypoints)
            except (OSError, RuntimeError, subprocess.SubprocessError):
                return 0
            print(record["version"])
        return 0
    if (not args.source or not args.cache or not args.work or not re.fullmatch(r"\d+(?:\.\d+){1,3}", args.version)
            or not re.fullmatch(r"[0-9a-f]{64}", args.sha256 or "")):
        parser.error("install requires --version, --source, --sha256, --cache and --work")
    key = fingerprint(MKV_RECIPE, args.version, args.sha256)
    args.work.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mkv-", dir=args.work) as temporary:
        work = Path(temporary)
        archive = args.cache / "mkvtoolnix.zip"
        payload = work / "cached"
        record = build_record(payload, "mkvtoolnix") if restore(archive, key, payload) else None
        if record and record["fingerprint"] == key:
            try:
                verify(payload, record, record["entrypoints"])
            except (OSError, RuntimeError, subprocess.SubprocessError):
                record = None
        else:
            record = None
        if record is None:
            if args.defer_msys2:
                return MSYS2_REQUIRED
            if not args.msys2_root:
                parser.error("building MKVToolNix requires --msys2-root")
            payload = work / "payload"
            build_from_source(args, work, payload, key, args.msys2_root / "ucrt64")
            record = build_record(payload, "mkvtoolnix")
            if not record:
                raise RuntimeError("Invalid MKVToolNix build record")
            verify(payload, record, record["entrypoints"])
            publish(archive, key, files_under(payload))
        install_build(payload, args.directory, "mkvtoolnix", record, entrypoints)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
