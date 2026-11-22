"""Source downloads, native build tools and per-component installation archives."""

from __future__ import annotations

import ast
import gzip
import hashlib
import inspect
from importlib.metadata import version
import json
import os
import platform
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import textwrap
import zlib
from pathlib import Path

from src.core.i18n import translate_text

ROOT = Path(__file__).resolve().parents[1]


def message(template, **values):
    language = os.environ.get("BLURAY_LANG") or os.environ.get("LANG", "en")
    return translate_text(template, "zh" if language.lower().startswith("zh") else "en").format(**values)


def run(*arguments, cwd=None, env=None):
    subprocess.run(list(map(str, arguments)), cwd=cwd, env=env, check=True)


def output(*arguments, cwd=None):
    return subprocess.check_output(list(map(str, arguments)), cwd=cwd, text=True).strip()


def digest(path: Path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def recipe_digest(*functions):
    # Follow the local helpers actually called by this recipe. A change to one
    # filter or encoder must not invalidate its siblings.
    sources = {}
    pending = list(functions)
    while pending:
        fn = pending.pop()
        module = fn.__module__.rsplit(".", 1)[-1].removeprefix("macos_")
        name = f"{module}.{fn.__qualname__}"
        if name in sources:
            continue
        tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
        # Module placement does not change the compiled product.
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("tools.macos_"):
                node.module = node.module.removeprefix("tools.macos_")
        sources[name] = ast.dump(tree)
        for value in inspect.getclosurevars(fn).globals.values():
            if inspect.isfunction(value) and value.__module__.startswith("tools.macos_"):
                pending.append(value)
    return fingerprint(sources)


def copy_licenses(source, target):
    for pattern in (
        "LICENSE*",
        "COPYING*",
        "License*",
        "Licence*",
        "license*.txt",
        "gpl2.txt",
        "doc/License.txt",
        "DOC/License.txt",
        "graphengine/COPYING",
        "vsxx/COPYING*",
    ):
        for path in source.glob(pattern):
            if path.is_file():
                copy(path, target / path.relative_to(source))


def download(url: str, cache: Path, expected: str = "") -> Path:
    target = cache / hashlib.sha256(url.encode()).hexdigest()
    record = target.with_suffix(".sha256")
    if target.is_file() and (expected or record.exists()):
        if digest(target) == (expected or record.read_text().strip()):
            return target
    cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=cache) as temp:
        pending = Path(temp) / "download"
        run("curl", "-fLsS", "--retry", "4", "--connect-timeout", "20", "-o", pending, url)
        checksum = digest(pending)
        if expected and expected != checksum:
            raise ValueError(f"Checksum mismatch for {url}")
        pending.replace(target)
        receipt = Path(temp) / "digest"
        receipt.write_text(checksum)
        receipt.replace(record)
    return target


def copy(source: Path, destination: Path):
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


class Build:
    def __init__(self, cache: Path, restore: bool, *, planning=False, expected=None):
        self.cache = cache
        self.restore = restore
        self.planning = planning
        self.expected = expected
        self.prefix = cache / "native"
        self.deps = cache / "deps"
        self.downloads = cache / "downloads"
        self.arch = platform.machine()
        self.jobs = str(min(12, os.cpu_count() or 2))
        self.prefix.mkdir(parents=True, exist_ok=True)
        self.components = cache / "components"
        self.components.mkdir(exist_ok=True)
        self.compiler = output("xcrun", "clang", "--version").splitlines()[0]
        self.sdk = output("xcrun", "--sdk", "macosx", "--show-sdk-version")
        self.flags = "-mmacosx-version-min=11.0 " + (
            "-march=ivybridge" if self.arch == "x86_64" else "-mcpu=apple-m1"
        )
        self.built = {}
        self.env = dict(
            os.environ,
            MACOSX_DEPLOYMENT_TARGET="11.0",
            CC="/usr/bin/clang",
            CXX="/usr/bin/clang++",
            SDKROOT=output("xcrun", "--sdk", "macosx", "--show-sdk-path"),
            CFLAGS=self.flags,
            CXXFLAGS=self.flags,
            CMAKE_BUILD_PARALLEL_LEVEL=self.jobs,
            CMAKE_POLICY_VERSION_MINIMUM="3.10",
            CARGO_HOME=str(cache / "cargo"),
            RUSTUP_HOME=str(cache / "rustup"),
            PATH=os.pathsep.join(
                map(
                    str,
                    (
                        Path(sys.executable).parent,
                        self.prefix / "bin",
                        self.deps / "bin",
                        cache / "cargo/bin",
                        os.environ["PATH"],
                    ),
                )
            ),
            CPPFLAGS=shlex.join(["-I" + str(p / "include") for p in (self.prefix, self.deps)]),
            LDFLAGS=shlex.join(
                [
                    "-mmacosx-version-min=11.0",
                    "-Wl,-headerpad_max_install_names",
                    *("-L" + str(p / "lib") for p in (self.prefix, self.deps)),
                    *("-Wl,-rpath," + str(p / "lib") for p in (self.prefix, self.deps)),
                ]
            ),
            PKG_CONFIG_PATH=os.pathsep.join(
                map(
                    str,
                    (
                        self.prefix / "lib/pkgconfig",
                        self.deps / "lib/pkgconfig",
                        self.deps / "share/pkgconfig",
                    ),
                )
            ),
            CMAKE_PREFIX_PATH=os.pathsep.join(map(str, (self.prefix, self.deps))),
        )
        ccache = shutil.which("ccache", path=self.env["PATH"]) or self.cache / "ccache-tools/bin/ccache"
        if Path(ccache).is_file():
            wrappers = cache / "compiler-wrappers"
            wrappers.mkdir(exist_ok=True)
            for name in ("clang", "clang++"):
                link = wrappers / name
                if not link.is_symlink() or link.readlink() != Path(ccache):
                    pending = wrappers / (name + ".tmp")
                    pending.unlink(missing_ok=True)
                    pending.symlink_to(ccache)
                    pending.replace(link)
            self.env.update(CC=str(wrappers / "clang"), CXX=str(wrappers / "clang++"),
                            PATH=str(wrappers) + os.pathsep + self.env["PATH"],
                            CCACHE_PATH=str(Path(output("xcrun", "--find", "clang")).parent),
                            CCACHE_DIR=str(cache / "ccache"), CCACHE_BASEDIR=str(cache),
                            CCACHE_COMPILERCHECK="content", CCACHE_MAXSIZE=os.environ.get("CCACHE_MAXSIZE", "2G"))
        self.conda = {}
        for path in (self.deps / "conda-meta").glob("*.json"):
            record = json.loads(path.read_bytes())
            self.conda[record["name"]] = (path.stem, [d.split()[0] for d in record.get("depends", ())])
        toolchain = (self.sdk, self.compiler, self.flags)
        self.python_abi = (sys.implementation.cache_tag, sys.version, digest(Path(sys.executable).resolve()))
        self.identities = {
            "native": [toolchain, str(self.prefix), self.env["CPPFLAGS"], self.env["LDFLAGS"],
                       recipe_digest(Build.run, Build.source)],
            "python": self.python_abi,
            "compiler": toolchain,
            "icon": output("sw_vers", "-buildVersion"),
            "download": (),
        }

    def conda_inputs(self, packages):
        # Configure scripts with unrestricted library detection use the full sysroot.
        pending = list(self.conda if packages is None else packages)
        selected = {}
        while pending:
            name = pending.pop()
            if name not in selected:
                build, requires = self.conda.get(name, (None, ()))
                selected[name] = build
                pending.extend(requires)
        return selected

    def start_install(self):
        # Each run restores the exact selected components into a fresh prefix.
        marker = self.prefix / ".bluraysubtitle-install"
        if marker.exists():
            shutil.rmtree(self.prefix)
        elif self.prefix.exists() and any(self.prefix.iterdir()):
            raise FileExistsError(f"Existing unmanaged build prefix: {self.prefix}")
        self.prefix.mkdir(exist_ok=True)
        marker.touch()

    def run(self, *args, cwd=None, **overrides):
        run(*args, cwd=cwd, env={**self.env, **overrides})

    def source(self, url, directory, sha=""):
        path = download(url, self.downloads, sha)
        directory.mkdir(parents=True)
        with tarfile.open(path) as archive:
            archive.extractall(directory, filter="data")
        items = list(directory.iterdir())
        if len(items) == 1 and items[0].is_dir():
            return items[0]
        return directory

    def cmake(self, source, build, *args, target=None):
        self.run(
            "cmake",
            "-S",
            source,
            "-B",
            build,
            "-G",
            "Ninja",
            "-DCMAKE_BUILD_TYPE=Release",
            "-DCMAKE_OSX_DEPLOYMENT_TARGET=11.0",
            f"-DCMAKE_OSX_ARCHITECTURES={self.arch}",
            f"-DCMAKE_INSTALL_PREFIX={self.prefix}",
            *args,
        )
        self.run(
            "cmake", "--build", build, "--parallel", self.jobs, *(["--target", target] if target else [])
        )

    def component(self, name, revision, build, *, dependencies=(), recipe="", scope="native",
                  packages=(), build_tools=(), python_abi=False):
        key = fingerprint([self.arch, self.identities[scope], name, revision, recipe,
                           self.conda_inputs(packages), {p: version(p) for p in build_tools},
                           self.python_abi if python_abi else None, [self.built[n] for n in dependencies]])
        if self.expected is not None and self.expected.get(name) != key:
            raise ValueError(f"The build inputs for {name} changed after resolving its cache key")
        if self.planning:
            self.built[name] = key
            return
        artifact = self.components / f"{name}-{key}.tar.gz"
        receipt = artifact.with_suffix(".sha256")
        with tempfile.TemporaryDirectory(dir=self.cache, prefix=f".{name}-") as temp:
            work = Path(temp)
            stage = work / "stage"
            restored = False
            if artifact.is_file():
                try:
                    if not receipt.is_file() or receipt.read_text().strip() != digest(artifact):
                        raise ValueError(f"Invalid checksum for {artifact}")
                    with tarfile.open(artifact) as tar:
                        tar.extractall(stage, filter="data")
                    restored = True
                except (ValueError, tarfile.TarError, gzip.BadGzipFile, EOFError, zlib.error):
                    if self.restore:
                        raise ValueError(message("Invalid component cache {path}.", path=artifact))
                    if stage.exists():
                        shutil.rmtree(stage)
            if not restored:
                if self.restore:
                    raise FileNotFoundError(message("Missing cached component {name}.", name=name))
                stage.mkdir()
                print(message("Building {name} {revision}", name=name, revision=revision), flush=True)
                try:
                    build(work, stage)
                except (OSError, ValueError, subprocess.SubprocessError):
                    for logname in ("config.log", "meson-log.txt", "CMakeConfigureLog.yaml"):
                        for number, log in enumerate(work.rglob(logname)):
                            copy(log, self.cache / "logs" / name / f"{number}-{logname}")
                    raise
                if not any(p.is_file() for p in stage.rglob("*")):
                    raise RuntimeError(f"{name} did not install any files")
                pending = work / "component.tgz"
                with tarfile.open(pending, "w:gz", compresslevel=2) as tar:
                    tar.add(stage, arcname=".")
                checksum = work / "checksum"
                checksum.write_text(digest(pending) + "\n")
                pending.replace(artifact)
                checksum.replace(receipt)
            else:
                print(message("Restoring {name} {revision}", name=name, revision=revision), flush=True)
            shutil.copytree(stage, self.prefix, dirs_exist_ok=True, symlinks=True)
        self.built[name] = key
        # A later component can fail after this archive was checksummed and installed.
        if self.expected is not None and (output_file := os.environ.get("GITHUB_OUTPUT")):
            with open(output_file, "a", encoding="utf-8") as stream:
                print(f"{name}={key}", file=stream)
