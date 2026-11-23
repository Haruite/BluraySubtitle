"""Resolve stable releases for VapourSynth plugins and their build dependencies."""

from __future__ import annotations

from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import json
from pathlib import Path
import re
import subprocess
import sys
import urllib.parse
import urllib.request

from .vapoursynth_plugin_versions import version_satisfies


R79_PLUGIN_NAMESPACES = {
    "descale": "descale",
    "addgrain": "grain",
    "assrender": "assrender",
    "bilateral": "bilateral",
    "dfttest": "dfttest",
    "eedi2": "eedi2",
    "eedi3m": "eedi3m",
    "znedi3": "znedi3",
    "fmtconv": "fmtc",
    "lsmas": "lsmas",
    "sangnom": "sangnom",
    "placebo": "placebo",
    "nlm_ispc": "nlm_ispc",
    "zsmooth": "zsmooth",
    "mvtools": "mv",
    "removegrain": "rgvs",
    "eedi3": "eedi3",
    "misc": "misc",
    "vivtc": "vivtc",
}
LEGACY_SOURCE_KEYS = {"eedi3": "legacy-filters", "misc": "legacy-filters"}


@dataclass(frozen=True)
class PluginSource:
    repository: str
    stable_tags: str = r"[rRvV]?[0-9]+(?:\.[0-9]+)*"
    classic_before: str = ""

    @property
    def url(self) -> str:
        return urllib.parse.urljoin("https://github.com/", self.repository)

    def archive(self, ref: str) -> str:
        if self.url.startswith("https://gitlab.com/"):
            return f"{self.url}/-/archive/{ref}/{self.url.rsplit('/', 1)[-1]}-{ref}.tar.gz"
        return f"https://codeload.github.com/{self.repository}/tar.gz/{ref}"


SOURCES = {
    "descale": PluginSource("AmusementClub/descale", r"[rR][0-9]+\.A[0-9]*"),
    "addgrain": PluginSource("HomeOfVapourSynthEvolution/VapourSynth-AddGrain"),
    "assrender": PluginSource("AmusementClub/assrender"),
    "bilateral": PluginSource("HomeOfVapourSynthEvolution/VapourSynth-Bilateral"),
    "dfttest": PluginSource("HomeOfVapourSynthEvolution/VapourSynth-DFTTest"),
    "eedi2": PluginSource("HomeOfVapourSynthEvolution/VapourSynth-EEDI2"),
    "eedi3m": PluginSource("HomeOfVapourSynthEvolution/VapourSynth-EEDI3"),
    "znedi3": PluginSource("vapoursynth/znedi3-pypi"),
    "fmtconv": PluginSource("https://gitlab.com/EleonoreMizo/fmtconv"),
    # Numeric release tags of this series exclude old date-based tags.
    "lsmas": PluginSource("HomeOfAviSynthPlusEvolution/L-SMASH-Works", r"[1-9][0-9]{3}(?:\.[0-9]+)*"),
    "sangnom": PluginSource("HomeOfVapourSynthEvolution/VapourSynth-SangNomMod", r"v[0-9]+(?:\.[0-9]+)*(?:-fix)?"),
    "placebo": PluginSource("Lypheo/vs-placebo"),
    "nlm_ispc": PluginSource("AmusementClub/vs-nlm-ispc"),
    # zsmooth 0.9 switched from the Classic-compatible API 4.0 to API 4.1.
    "zsmooth": PluginSource("adworacz/zsmooth", classic_before="0.9"),
    # MVTools v27 and later declare a build requirement of VapourSynth R74.
    "mvtools": PluginSource("dubhatervapoursynth/vapoursynth-mvtools", r"v[0-9]+(?:[._][0-9]+)*", classic_before="v27"),
    "removegrain": PluginSource("vapoursynth/vs-removegrain"),
    "legacy-filters": PluginSource("AmusementClub/vapoursynth-classic", r"[rR][0-9]+\.A[0-9]+(?:\.post[0-9]+)?"),
    "vivtc": PluginSource("vapoursynth/vivtc"),
    "ccd": PluginSource("End-of-Eternity/vs-ccd"),
    "bm3d": PluginSource("HomeOfVapourSynthEvolution/VapourSynth-BM3D"),
    "rife": PluginSource("styler00dollar/VapourSynth-RIFE-ncnn-Vulkan", r"r[0-9]+_mod_v[0-9]+"),
    "sse2neon": PluginSource("DLTcollab/sse2neon", r"v[0-9]+(?:\.[0-9]+)+"),
    "ispc": PluginSource("ispc/ispc", r"v[0-9]+(?:\.[0-9]+)+"),
}


@dataclass(frozen=True)
class PluginRelease:
    ref: str
    source_url: str
    sha256: str = ""


def latest_tag(source: PluginSource, git: str = "git", *, classic: bool = False) -> str:
    output = subprocess.check_output(
        [git, "ls-remote", "--exit-code", "--refs", "--tags", source.url + ".git"],
        text=True, encoding="utf-8", timeout=60,
    )
    tags = (line.partition("\trefs/tags/")[2] for line in output.splitlines())
    latest = ""
    for tag in tags:
        if not re.fullmatch(source.stable_tags, tag):
            continue
        if classic and source.classic_before and version_satisfies(tag, source.classic_before):
            continue
        if not latest or version_satisfies(tag, latest):
            latest = tag
    if not latest:
        raise RuntimeError(f"No compatible stable release found for {source.url}")
    return latest


def ispc_matches(executable: Path, version: str) -> bool:
    try:
        banner = subprocess.check_output([executable, "--version"], text=True, stderr=subprocess.STDOUT)
    except (OSError, subprocess.CalledProcessError):
        return False
    return f"ISPC), {version} " in banner


def znedi3_release() -> PluginRelease:
    # The PyPI sdist contains the VSXX and GraphEngine submodules and model weights.
    with urllib.request.urlopen("https://pypi.org/pypi/vapoursynth-znedi3/json", timeout=60) as response:
        metadata = json.load(response)
    releases = {}
    for ref, assets in metadata.get("releases", {}).items():
        if re.fullmatch(r"[0-9]+(?:\.[0-9]+)*(?:\.post[0-9]+)?", ref):
            for asset in assets:
                if asset["packagetype"] == "sdist" and not asset["yanked"] and asset["filename"].endswith(".tar.gz"):
                    releases[ref] = PluginRelease(ref, asset["url"], asset["digests"]["sha256"])
    latest = ""
    for ref in releases:
        if not latest or version_satisfies(ref, latest):
            latest = ref
    if not latest:
        raise RuntimeError("No stable ZNEDI3 source archive found on PyPI")
    return releases[latest]


def resolve_releases(keys: Iterable[str], git: str = "git", *, classic: bool = False) -> dict[str, PluginRelease]:
    def resolve(key: str) -> PluginRelease:
        if key == "znedi3":
            return znedi3_release()
        source = SOURCES[key]
        ref = latest_tag(source, git, classic=classic)
        return PluginRelease(ref, source.archive(ref))

    unique_keys = tuple(dict.fromkeys(keys))
    with ThreadPoolExecutor(max_workers=6) as pool:
        return dict(zip(unique_keys, pool.map(resolve, unique_keys)))


if __name__ == "__main__":
    for key, release in resolve_releases(sys.argv[1:]).items():
        print(key, release.ref, release.source_url, release.sha256, sep="\t")
