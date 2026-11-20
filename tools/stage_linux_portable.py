"""Assemble the two Qt runtimes and Ubuntu's matching private ELF interpreter and libc."""

import filecmp
from importlib.metadata import distribution
import os
from pathlib import Path
import shutil
import subprocess

from PyQt6 import QtCore, sip
from PyQt6.QtCore import QLibraryInfo

from linux_runtime_libs import GLIBC, HOST_DRIVER, QT_MODULES, kernel_requirement, linked_libraries, selected_plugins


def dependency_paths(files: list[Path], used_paths: set[Path], search: tuple[Path, ...] = ()) -> dict[str, Path]:
    libraries = {}
    for file in files:
        for name, path in linked_libraries(file, search).items():
            if path is None:
                raise RuntimeError(f"Missing dependency for {file}: {name}")
            used_paths.add(path)
            if GLIBC.fullmatch(name) or HOST_DRIVER.fullmatch(name):
                continue
            source = path.resolve(strict=True)
            previous = libraries.setdefault(name, source)
            if previous != source:
                raise RuntimeError(f"Conflicting versions of {name}: {previous}, {source}")
    return libraries


def stage_glibc(support: Path, system: Path, used: set[Path]) -> None:
    destination = support / "linux/glibc"
    destination.mkdir()
    for source in sorted(system.iterdir()):
        if GLIBC.fullmatch(source.name) and source.is_file():
            shutil.copy2(source, destination / source.name)
            used.add(source)
    if (system / "gconv").is_dir():
        shutil.copytree(system / "gconv", destination / "gconv", ignore=shutil.ignore_patterns("gconv-modules.cache"))
        used.update((system / "gconv").glob("*.so"))
    locale = Path("/usr/lib/locale/C.utf8")
    shutil.copytree(locale, destination / "locale/C.utf8")
    used.add(locale / "LC_CTYPE")
    subprocess.run(
        ["cc", "-Os", "-s", "-x", "c", "-", "-o", str(destination / "check-locale")],
        input='#include <locale.h>\nint main(void) { return setlocale(LC_ALL, "") == 0; }\n',
        text=True, check=True,
    )
    shutil.copy2("/usr/share/doc/libc6/copyright", support / "legal/glibc-copyright")
    loader, = destination.glob("ld-linux-*.so.*")
    if not os.access(loader, os.X_OK) or kernel_requirement(destination / "libc.so.6") > (3, 17, 0):
        raise RuntimeError("The private glibc must support Linux 3.17")
    (destination / "ld.so").symlink_to(loader.name)
    if loader.name == "ld-linux-x86-64.so.2":
        # The probe itself must run on older CPUs. GCC checks CPUID and OS support for the AVX register state.
        subprocess.run(
            ["cc", "-march=x86-64", "-Os", "-s", "-x", "c", "-", "-o", str(destination / "check-x86-64-v3")],
            input='int main(void) { return __builtin_cpu_supports("x86-64-v3") ? 0 : 64; }\n',
            text=True, check=True,
        )


def stage_qt(support: Path, qt_tools: list[Path], used: set[Path]) -> None:
    sdk = Path(os.environ["BLURAY_QT66_PREFIX"])
    paths = QLibraryInfo.LibraryPath
    current = Path(QtCore.__file__).parent
    variants = (
        ("latest", current, Path(QLibraryInfo.path(paths.LibrariesPath)), Path(QLibraryInfo.path(paths.PluginsPath)),
         Path(QLibraryInfo.path(paths.TranslationsPath))),
        ("6.6", next((sdk / "lib64").glob("python*/site-packages/PyQt6")), sdk / "lib64",
         sdk / "lib64/qt6/plugins", sdk / "share/qt6/translations"),
    )
    for name in ("PyQt6", "PyQt6-Qt6", "PyQt6-sip"):
        dist = distribution(name)
        for entry in dist.files or ():
            if ".dist-info" in entry.parts[0] and ("licenses" in entry.parts or entry.name.startswith("LICENSE")):
                target = support / "legal" / name / Path(*entry.parts[1:])
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dist.locate_file(entry), target)

    for label, bindings, libs, plugins, translations in variants:
        root = support / "linux/qt" / label
        package = root / "PyQt6"
        qt = package / "Qt6"
        (qt / "lib").mkdir(parents=True)
        init = bindings / "__init__.py"
        if init.is_file():
            shutil.copy2(init, package)
        modules = [next(bindings.glob(f"{name}.*.so")) for name in QT_MODULES]
        for source in (*modules, Path(sip.__file__)):
            shutil.copy2(source, package / source.name)
        selected = selected_plugins(plugins)
        platforms = {x.name for x in selected if x.parent.name == "platforms"}
        if not {"libqxcb.so", "libqoffscreen.so"} <= platforms or not any("wayland" in n for n in platforms):
            raise RuntimeError(f"Incomplete Qt {label} platform plugins in {plugins}")
        for source in selected:
            target = qt / "plugins" / source.relative_to(plugins)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        for language in ("en", "zh_CN"):
            for prefix in ("qt", "qtbase"):
                source = translations / f"{prefix}_{language}.qm"
                if source.is_file():
                    (qt / "translations").mkdir(exist_ok=True)
                    shutil.copy2(source, qt / "translations")
        executables = [tool for tool in qt_tools if label == "6.6" or tool.name != "vsedit"]
        binaries = modules + selected + executables
        deps = dependency_paths(binaries, used, (libs,))
        for name, source in deps.items():
            if name.startswith("libQt6") and not source.is_relative_to(libs.resolve()):
                raise RuntimeError(f"Qt {label} would load a different Qt library: {source}")
            target = qt / "lib" / name
            shared = support / name
            if shared.is_file() and filecmp.cmp(source, shared, shallow=False):
                target.symlink_to(os.path.relpath(shared, target.parent))
            else:
                shutil.copy2(source, target)
        minimum = kernel_requirement(qt / "lib/libQt6Core.so.6")
        for binary in set(binaries).union(deps.values()):
            minimum = max(minimum, kernel_requirement(binary, note_required=False))
        if label == "6.6" and minimum > (3, 17, 0):
            raise RuntimeError(f"The compatibility Qt requires Linux {minimum}")
        (root / "minimum-kernel").write_text("%d %d %d\n" % minimum, encoding="ascii")
        if label == "6.6":
            for directory in (sdk / "share/licenses").glob("*"):
                if directory.is_dir():
                    shutil.copytree(directory, support / "legal/qt66" / directory.name, dirs_exist_ok=True)


def remove_build_rpaths(file: Path) -> None:
    # An absolute DT_RPATH can take precedence even over the private loader's --library-path.
    path = subprocess.check_output(["patchelf", "--print-rpath", file], text=True).strip()
    if path and any(not entry.startswith(("$ORIGIN", "${ORIGIN}")) for entry in path.split(":")):
        relative = ":".join(entry for entry in path.split(":") if entry.startswith(("$ORIGIN", "${ORIGIN}")))
        subprocess.run(["patchelf", "--set-rpath", relative, file], check=True)
