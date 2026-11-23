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
    MKV_RECIPE, MKV_WIN7_RECIPE, PE_ARM64, build_record, clean_tool_environment, fetch_verified, file_hash, fingerprint,
    imported_symbols, install_build, msys_pkg_config_environment, pe_imports, record_build, runtime_dependencies, tool_version,
    verify_mkv_runtime, windows_machine,
)
from tools.windows_tool_paths import MKV_PROGRAMS


MSYS2_REQUIRED = 75
QT_FEATURES_OFF = ("gui", "widgets", "dbus", "sql", "xml", "testlib", "concurrent", "icu")
SECTION_FLAGS = "-ffunction-sections -fdata-sections"
WIN7_FLAGS = "-D_WIN32_WINNT=0x0601 -DWINVER=0x0601"


def latest_mkvtoolnix_version(git: str = "git") -> str:
    refs = subprocess.check_output([
        git, "ls-remote", "--exit-code", "--refs", "--tags", "--sort=-v:refname",
        "https://codeberg.org/mbunkus/mkvtoolnix.git", "refs/tags/release-*",
    ], encoding="utf-8", timeout=60)
    match = re.search(r"\trefs/tags/release-([0-9]+(?:\.[0-9]+)+)$", refs, re.MULTILINE)
    if not match:
        raise ValueError("No stable MKVToolNix release tag found on Codeberg")
    return match[1]


def unpack_source(archive: Path, destination: Path) -> Path:
    with tarfile.open(archive) as source:
        # The command-line build does not need symbolic links on Windows.
        source.extractall(destination, members=(member for member in source if member.isfile() or member.isdir()),
                          filter="data")
    return destination / archive.name.removesuffix(".tar.xz")


def build_qtcore(work: Path, prefix: Path, compiler: Path, cache: Path, env: dict, jobs: int,
                 cxx_flags: str, *, qmake: Path, compat_source: Path | None = None) -> tuple[Path, str]:
    version = subprocess.check_output([qmake, "-query", "QT_VERSION"], env=env, text=True).strip()
    match = re.fullmatch(r"(\d+\.\d+)\.\d+", version)
    if not match:
        raise ValueError(f"Unexpected MSYS2 Qt version: {version}")
    arm64 = windows_machine() == PE_ARM64
    c_compiler = compiler / ("clang.exe" if arm64 else "gcc.exe")
    cxx_compiler = compiler / ("clang++.exe" if arm64 else "g++.exe")
    compiler_version = subprocess.check_output(
        [cxx_compiler, "--version" if arm64 else "-dumpfullversion"], env=env, text=True,
    ).strip()
    recipe = "mingw-ucrt-qtcore-win7-1" if compat_source else MKV_RECIPE
    qt_key = fingerprint(recipe, version, compiler_version, file_hash(qmake.parent / "Qt6Core.dll"))
    archive = cache / "mkvtoolnix-qtcore.zip"
    payload = work / "qtcore"
    if restore(archive, qt_key, payload):
        return payload, version

    if compat_source:
        source = compat_source
    else:
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
    arm_options = [
        "-DQT_QMAKE_TARGET_MKSPEC=win32-clang-g++",
        f"-DCMAKE_RC_COMPILER:FILEPATH={(compiler / 'llvm-windres.exe').as_posix()}",
    ] if arm64 else []
    subprocess.run([
        cmake, "-S", source, "-B", build, "-G", "Ninja", "-Wno-deprecated",
        f"-DCMAKE_C_COMPILER={c_compiler}", f"-DCMAKE_CXX_COMPILER={cxx_compiler}",
        f"-DCMAKE_MAKE_PROGRAM={compiler / 'ninja.exe'}", *arm_options,
        f"-DCMAKE_PREFIX_PATH={prefix};{compiler.parent}", "-DCMAKE_BUILD_TYPE=Release", "-DBUILD_SHARED_LIBS=OFF",
        f"-DCMAKE_C_FLAGS={SECTION_FLAGS}{' ' + WIN7_FLAGS if compat_source else ''}", f"-DCMAKE_CXX_FLAGS={cxx_flags}",
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
    for executable in MKV_PROGRAMS:
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


def build_cli(source: Path, msys: Path, prefix: Path, jobs: int, cxx_flags: str, env: dict, *,
              qmake: Path, compat: bool = False) -> None:
    cygpath = msys / "usr/bin/cygpath.exe"
    posix_prefix = subprocess.check_output([cygpath, "-u", prefix], text=True).strip()
    posix_work = subprocess.check_output([cygpath, "-u", source.parent], text=True).strip()
    posix_qmake = subprocess.check_output([cygpath, "-u", qmake], text=True).strip()
    qt_include = qmake.parent.parent / "include" if compat else prefix / "include/qt6"
    # MSYS2's libdvdread dependency pulls in libdvdcss with a static CreateFile2 import.
    dvdread = " --without-dvdread" if compat else ""
    quote = shlex.quote
    sysroot = "/" + prefix.name
    arm64 = windows_machine() == PE_ARM64
    host = "aarch64-w64-mingw32" if arm64 else "x86_64-w64-mingw32"
    tools = ("CC=clang CXX=clang++ AR=llvm-ar RANLIB=llvm-ranlib WINDRES=llvm-windres STRIP=llvm-strip"
             if arm64 else "CC=gcc CXX=g++ AR=ar RANLIB=ranlib WINDRES=windres STRIP=strip")
    build_icons(source)
    patch_rake(source)
    script = source.parent / "build-mkvtoolnix.sh"
    script.write_text("\n".join((
        "set -eu",
        f"deps={quote(posix_prefix)}",
        f'export PATH="$deps/bin:{sysroot}/bin:/usr/bin"',
        f"mkdir -p {quote(posix_work + '/t')}",
        f"export TMPDIR={quote(posix_work + '/t')}",
        'export MINGW_PREFIX="$deps"',
        'win_deps=$(cygpath -m "$deps")',
        "export " + tools,
        f'export CPPFLAGS="-I$win_deps/include -I{qt_include.as_posix()} -I{(qt_include / "QtCore").as_posix()}"',
        'export LDFLAGS="-L$win_deps/lib"',
        f"export CFLAGS={quote('-Os -DNDEBUG ' + SECTION_FLAGS)} CXXFLAGS={quote('-Os -DNDEBUG ' + cxx_flags)}",
        "export INKSCAPE=/usr/bin/true MAGICK=/usr/bin/true",
        f"/usr/bin/dash ./configure --build={host} --host={host} "
        "--disable-gui --disable-debug --disable-optimization --enable-precompiled-headers "
        f'--with-qmake6={quote(posix_qmake)}{dvdread} --with-boost="$win_deps" '
        '--with-boost-system=boost_filesystem-mt --with-boost-filesystem=boost_filesystem-mt',
        # The icons are already rendered from the source SVGs.
        r"sed -i -E 's/^(INKSCAPE|MAGICK|CONVERT)[[:space:]]*=.*/\1 =/' build-config",
        r"sed -i -E 's/^(QT_CFLAGS = .*)$/\1 -DQT_STATIC/' build-config",
        "export RUBYSHELL=$(cygpath -m /usr/bin/dash.exe)",
        f"ruby ./drake -j{jobs} " + " ".join("apps:" + Path(name).stem for name in MKV_PROGRAMS),
        "",
    )), encoding="utf-8", newline="\n")
    try:
        subprocess.run([msys / "usr/bin/dash.exe", posix_work + "/" + script.name], cwd=source, env=env, check=True)
    except subprocess.CalledProcessError:
        if compat and (log := source / "config.log").is_file():
            shutil.copyfile(log, source.parent.parent / "mkvtoolnix-config.log")
        raise


def link_cli(source: Path, qtcore: Path, compiler: Path, env: dict) -> Path:
    commands = {name: shlex.split((source / "src" / (name + ".link")).read_text(encoding="utf-8"))[1:]
                for name in MKV_PROGRAMS}
    linked = source.parent / "linked"
    linked.mkdir()
    core = qtcore / "libQt6Core.a"
    libraries = (qtcore / "libraries.txt").read_text(encoding="utf-8").splitlines()
    arm64 = windows_machine() == PE_ARM64
    nm = compiler / ("llvm-nm.exe" if arm64 else "nm.exe")
    cxx = compiler / ("clang++.exe" if arm64 else "g++.exe")
    common_archives = [path for name in (
        "src/common/libmtxcommon.a", "lib/libmatroska/src/libmatroska.a", "lib/libebml/src/libebml.a",
        "lib/fmt/src/libfmt.a", "lib/pugixml/src/libpugixml.a",
    ) if (path := source / name).is_file()]
    bundled_libs = {"-l" + path.stem.removeprefix("lib") for path in common_archives}
    frontend_inputs = {argument for command in commands.values() for argument in command if argument.endswith(".o")}
    frontend_inputs.update(path.relative_to(source).as_posix() for path in (source / "src").rglob("*.a")
                           if path.name != "libmtxcommon.a")

    def symbols(option, inputs):
        output = subprocess.check_output([nm, "-g", "-P", option, *inputs], cwd=source,
                                         env=env, encoding="utf-8", errors="replace")
        return {fields[0]: fields[1] for line in output.splitlines()
                if len(fields := line.split()) >= 2 and len(fields[1]) == 1 and not fields[0].startswith(".")}

    defined = symbols("--defined-only", [core, *common_archives])
    exports = sorted(defined.keys() & symbols("--undefined-only", sorted(frontend_inputs)).keys())
    if not exports:
        raise RuntimeError("Could not resolve the MKVToolNix common-library exports")
    definitions = linked / "libmtxcommon.def"

    def is_qt_import(arg):
        return Path(arg).name in {"libQt6Core.a", "libQt6Core.dll.a"} or arg == "-lQt6Core"

    def link(name, args):
        response = linked / f"{name}.rsp"
        response.write_text("".join(f'"{arg}"\n' for arg in args), encoding="utf-8", newline="\n")
        subprocess.run([cxx, "-s", "@" + str(response)], cwd=source, env=env, check=True)

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
    compiler = prefix / "bin"
    env = clean_tool_environment()
    env["PATH"] = os.pathsep.join(map(str, (compiler, args.msys2_root / "usr/bin", env["PATH"])))
    env.update(msys_pkg_config_environment(prefix))
    cxx_flags = SECTION_FLAGS
    if windows_machine() != PE_ARM64:
        probe = subprocess.run(
            [compiler / "g++.exe", "-Os", "-fno-declone-ctor-dtor", "-x", "c++", "-c", "-o", work / "gcc-option.o", "-"],
            input="int main() {}\n", capture_output=True, text=True, env=env,
        )
        if probe.returncode == 0:
            cxx_flags += " -fno-declone-ctor-dtor"
    if args.qt_win7_source:
        cxx_flags += " " + WIN7_FLAGS
    qmake = args.qt_win7_sdk / "bin/qmake.exe" if args.qt_win7_sdk else prefix / "bin/qmake6.exe"
    qtcore, qt_version = build_qtcore(work, prefix, compiler, args.cache, env, args.jobs, cxx_flags,
                                     qmake=qmake, compat_source=args.qt_win7_source)
    build_cli(source, args.msys2_root, prefix, args.jobs, cxx_flags, env, qmake=qmake, compat=bool(args.qt_win7_source))
    linked = link_cli(source, qtcore, compiler, env)
    stage_cli(source, linked, qtcore, prefix, compiler, payload, env)
    recipe = MKV_WIN7_RECIPE if args.qt_win7_source else MKV_RECIPE
    record_build(payload, "mkvtoolnix", recipe, args.version, key, MKV_PROGRAMS,
                 source_url=args.source, source_sha256=args.sha256, qt_version=qt_version)


def stage_cli(source: Path, linked: Path, qtcore: Path, prefix: Path, compiler: Path, payload: Path, env: dict) -> None:
    programs = [linked / name for name in MKV_PROGRAMS]
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
        pe_imports(directory / executable)
        version = tool_version(directory / executable)
        if not re.match(rf"{re.escape(Path(name).stem)} v{re.escape(record['version'])}(?:\s|$)", version):
            raise RuntimeError(f"Unexpected version from {executable}: {version}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("latest-version", "version", "install"))
    parser.add_argument("directory", type=Path, nargs="?")
    parser.add_argument("--git", default="git")
    parser.add_argument("--version", default="")
    parser.add_argument("--source")
    parser.add_argument("--sha256")
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--work", type=Path)
    parser.add_argument("--msys2-root", type=Path)
    parser.add_argument("--jobs", type=int, default=os.cpu_count() or 1)
    parser.add_argument("--defer-msys2", action="store_true")
    parser.add_argument("--qt-win7-source", type=Path)
    parser.add_argument("--qt-win7-sdk", type=Path)
    args = parser.parse_args()
    if args.operation == "latest-version":
        print(latest_mkvtoolnix_version(args.git))
        return 0
    if args.directory is None:
        parser.error(f"{args.operation} requires an installation directory")
    entrypoints = {name: name for name in MKV_PROGRAMS}
    if args.operation == "version":
        record = build_record(args.directory, "mkvtoolnix", installed=True)
        if record and record["entrypoints"] == entrypoints:
            try:
                verify(args.directory, record, entrypoints)
            except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
                return 0
            print(record["version"])
        return 0
    if (not args.source or not args.cache or not args.work or not re.fullmatch(r"\d+(?:\.\d+){1,3}", args.version)
            or not re.fullmatch(r"[0-9a-f]{64}", args.sha256 or "")):
        parser.error("install requires --version, --source, --sha256, --cache and --work")
    arm64 = windows_machine() == PE_ARM64
    if bool(args.qt_win7_source) != bool(args.qt_win7_sdk) or (arm64 and args.qt_win7_source):
        parser.error("the x64 Win7 build requires both patched Qt sources and the matching MinGW Qt SDK")
    compatibility = bool(args.qt_win7_source)
    recipe = MKV_WIN7_RECIPE if compatibility else MKV_RECIPE
    key = fingerprint(recipe, args.version, args.sha256, "arm64") if arm64 else fingerprint(recipe, args.version, args.sha256)
    args.work.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mkv-", dir=args.work) as temporary:
        work = Path(temporary)
        archive = args.cache / "mkvtoolnix.zip"
        payload = work / "cached"
        record = build_record(payload, "mkvtoolnix", compatibility=compatibility) if restore(archive, key, payload) else None
        if record and record["fingerprint"] == key:
            try:
                verify(payload, record, record["entrypoints"])
            except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
                record = None
        else:
            record = None
        if record is None:
            if args.defer_msys2:
                return MSYS2_REQUIRED
            if not args.msys2_root:
                parser.error("building MKVToolNix requires --msys2-root")
            payload = work / "payload"
            build_from_source(args, work, payload, key, args.msys2_root / ("clangarm64" if arm64 else "ucrt64"))
            record = build_record(payload, "mkvtoolnix", compatibility=compatibility)
            if not record:
                raise RuntimeError("Invalid MKVToolNix build record")
            verify(payload, record, record["entrypoints"])
            publish(archive, key, files_under(payload))
        install_build(payload, args.directory, "mkvtoolnix", record, entrypoints)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
