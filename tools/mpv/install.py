"""Install the Linux mpv desktop configuration and an unpacked uosc release."""

from __future__ import annotations

from hashlib import sha256
import os
from pathlib import Path
import re
import shutil
from stat import S_IMODE
import subprocess
import sys
from tempfile import NamedTemporaryFile, TemporaryDirectory


ASSETS = Path(__file__).resolve().parent
UOSC_DIR = Path("scripts/uosc")
UOSC_BINARY = "bin/ziggy-linux"
UOSC_REQUIRED = (UOSC_BINARY, "intl/zh-hans.json")
UOSC_FONTS = ("uosc_icons.otf", "uosc_textures.ttf")
UOSC_FILE_LIST = ".bluray-files"
BUNDLED_SHADERS = ASSETS.parents[1] / "third_party/mpv_lazy_shaders"
SHADER_URL = (
    "https://raw.githubusercontent.com/hooke007/mpv_PlayKit/"
    "1ad89a52e8dab222b5628ab835bb0803995ead3a/portable_config/shaders"
)
LAZY_MENU = "mpv-lazy (&Z)"
LAZY_PROFILES = "mpv-lazy/profiles.conf"
SHADER_PATH = "mpv-lazy/shaders"
SHADERS = (
    ("Ani/Ani4Kv2_ArtCNN_C4F32_i2_dx.glsl", "Ani4Kv2 Upscaling"),
    ("Ani/AniSD_ArtCNN_C4F32_i4_dx.glsl", "AniSD Upscaling"),
    ("FSRCNNX/FSRCNNX_x2_16_0_4_1.glsl", "FSRCNNX Upscaling"),
    ("EDI/nnedi3_nns64_win8x4.glsl", "NNEDI3 Upscaling"),
    ("Anime4K/Anime4K_Restore_CNN_L.glsl", "Anime4K Restoration"),
    ("Anime4K/Anime4K_Upscale_GAN_x2_M.glsl", "Anime4K Upscaling"),
    ("ESRGAN/k7_modernAnime_FHD_x2.glsl", "k7 modernAnime Upscaling"),
    ("ESRGAN/k7_modernAnime_DT_FHD_x2.glsl", "k7 modernAnime DT Upscaling"),
    ("QCOM/QCOM_SGEDS_ms_RT.glsl", "QCOM Scaling and Sharpening"),
    ("Adaptive_sharpen/Adaptive_sharpen_lite_RT.glsl", "Adaptive Sharpen"),
)
DOWNLOADED_SHADERS = {
    "Ani/Ani4Kv2_ArtCNN_C4F32_i2_dx.glsl": "7571cba85f2054b1ba410c2cfec1710594ed086182b8c63adf996b08e4923f8c",
    "Ani/AniSD_ArtCNN_C4F32_i4_dx.glsl": "5cba020470947f6ddb7eddcec126bedc0a726150b3218d0eaed6cea3c1512647",
    "QCOM/QCOM_SGEDS_ms_RT.glsl": "ac2fe3458bd9524a9842c0983e292439ffa23f594f51b6eee0edeb4174adbf63",
}
BEGIN = "# BEGIN BluraySubtitle desktop settings"
END = "# END BluraySubtitle desktop settings"
SAVE_LABEL = "Save as Default Settings"
SAVE_COMMAND = "script-message-to bluray_defaults save"
FILTER_MENU = "VapourSynth Presets"
FILTER_OFF = "Turn Off VapourSynth Preset"
FILTER_STATE = 'p["user-data/bluray-vs/active"]'
MULTIPLIER_MENU = "Interpolation Multiplier"
MULTIPLIER_CUSTOM = "Custom Multiplier…"
MULTIPLIER_STATE = 'p["user-data/bluray-vs/multiplier"]'
MULTIPLIERS = (
    ("1.5×", "3/2"), ("2×", "2"), ("2.5×", "5/2"), ("3×", "3"),
    ("4×", "4"), ("5×", "5"), ("10×", "10"),
)
PRESETS = {
    "mvtools": ("MVTools Interpolation", ("mvtools.so",)),
    "rife": ("RIFE Vulkan Interpolation", (
        "librife_linux_x86-64.so",
        "models/rife-v4.6_ensembleFalse/flownet.bin",
        "models/rife-v4.6_ensembleFalse/flownet.param",
    )),
    "ccd": ("CCD Chroma Denoise", ("libccd.so",)),
    "bm3d": ("BM3D CPU Luma Denoise", ("bm3d.so",)),
}


def config_directory() -> Path:
    if mpv_home := os.environ.get("MPV_HOME"):
        return Path(mpv_home).expanduser().absolute()
    config_home = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return config_home / "mpv"


def write_if_changed(path: Path, content: bytes) -> None:
    path = path.resolve()
    mode = 0o644
    if path.is_file():
        if path.read_bytes() == content:
            return
        mode = S_IMODE(path.stat().st_mode)
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(content)
            stream.close()
            temporary.chmod(mode)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def default_menu() -> str:
    with NamedTemporaryFile(mode="w", suffix=".lua", encoding="utf-8") as script:
        script.write(
            'mp.add_timeout(0, function() '
            'io.write(mp.get_property("default-menu", "")); io.flush(); mp.commandv("quit") end)\n'
        )
        script.flush()
        result = subprocess.run(
            ["mpv", "--no-config", "--idle=yes", "--force-window=no", "--load-scripts=no",
             "--really-quiet", f"--script={script.name}"],
            check=True, stdout=subprocess.PIPE, encoding="utf-8", timeout=10,
        )
    if not result.stdout.strip():
        raise RuntimeError("The installed mpv has no built-in context menu")
    return result.stdout


def lazy_menu(labels: dict[str, str]) -> list[str]:
    entries = (
        ("Apply &Picture Preset", "apply-profile mpv-lazy-picture"),
        ("&Restore Previous Picture Settings", "apply-profile mpv-lazy-picture restore"),
        ("Apply &Subtitle Style", "apply-profile mpv-lazy-subtitles"),
        ("Restore Previous Sub&title Settings", "apply-profile mpv-lazy-subtitles restore"),
    )
    group = [LAZY_MENU]
    group.extend(f"\t{labels.get(title, title)}\t{command}" for title, command in entries)
    group.append("\t" + labels.get("Shaders (&G)", "Shaders (&G)"))
    for relative, title in SHADERS:
        filename = relative.rpartition("/")[2]
        group.append(
            f'\t\t{labels.get(title, title)}\tchange-list glsl-shaders toggle "~~/{SHADER_PATH}/{relative}"'
            f'\tchecked=table.concat(get("glsl-shaders", {{}}), "|"):find("{filename}", 1, true) ~= nil'
        )
    clear_label = "&Clear All Shaders"
    group.append(f'\t\t{labels.get(clear_label, clear_label)}\tchange-list glsl-shaders clr ""')
    return group


def localize_menu(original: str, language: str, presets: list[str]) -> str:
    pairs = [
        line.split("\t", 1)
        for line in (ASSETS / "menu.zh.tsv").read_text(encoding="utf-8").splitlines()
    ]
    to_chinese = dict(pairs)
    translations = to_chinese if language == "zh" else {zh: en for en, zh in pairs}
    label = to_chinese[SAVE_LABEL] if language == "zh" else SAVE_LABEL
    reload_en = "Reloading current file..."
    reload_zh = to_chinese[reload_en]
    lines = []
    save_position = None
    profile_position = None
    in_filter_menu = False
    has_lazy_menu = False
    for line in original.splitlines():
        item = line.lstrip()
        indent = line[:len(line) - len(item)]
        title, separator, fields = item.partition("\t")
        command = fields.lstrip("\t").partition("\t")[0].strip()
        if in_filter_menu and (indent or not item):
            continue
        in_filter_menu = not indent and title in (FILTER_MENU, to_chinese[FILTER_MENU])
        if in_filter_menu:
            continue
        if command == SAVE_COMMAND:
            if save_position is not None:
                continue
            title = label
            save_position = len(lines) + 1
        else:
            title = translations.get(title, title)
        if not indent and command == "$profiles":
            profile_position = len(lines) + 1
        if not indent and title == LAZY_MENU:
            has_lazy_menu = True
        fields = fields.replace(reload_en, reload_zh) if language == "zh" else fields.replace(reload_zh, reload_en)
        lines.append(indent + title + separator + fields)
    if save_position is None:
        position = profile_position if profile_position is not None else len(lines)
        lines.insert(position, f"{label}\t{SAVE_COMMAND}")
        save_position = position + 1
    labels = to_chinese if language == "zh" else {}
    group = []
    if presets:
        group.append(labels.get(FILTER_MENU, FILTER_MENU))
        for name in presets:
            title = PRESETS[name][0]
            group.append(
                f"\t{labels.get(title, title)}\tscript-message-to bluray_vs toggle {name}"
                f'\tchecked={FILTER_STATE} == "{name}"'
            )
        if "mvtools" in presets or "rife" in presets:
            group.append(f"\t{labels.get(MULTIPLIER_MENU, MULTIPLIER_MENU)}")
            for title, value in MULTIPLIERS:
                group.append(
                    f"\t\t{title}\tscript-message-to bluray_vs multiplier {value}"
                    f'\tchecked={MULTIPLIER_STATE} == "{value}"'
                )
            common = " or ".join(f'{MULTIPLIER_STATE} == "{value}"' for _, value in MULTIPLIERS)
            group.append(
                f"\t\t{labels.get(MULTIPLIER_CUSTOM, MULTIPLIER_CUSTOM)}\tscript-message-to bluray_vs custom-multiplier"
                f"\tchecked={MULTIPLIER_STATE} and not ({common})"
            )
        group.append(
            f"\t{labels.get(FILTER_OFF, FILTER_OFF)}\tscript-message-to bluray_vs off"
            f'\tdisabled=not {FILTER_STATE} or {FILTER_STATE} == ""'
        )
    if not has_lazy_menu:
        group.extend(lazy_menu(labels))
    position = next(
        (i for i in range(save_position, len(lines)) if lines[i] and not lines[i][0].isspace()),
        len(lines),
    )
    lines[position:position] = group
    return "\n".join(lines) + "\n"


def update_main_config(original: str, language: str) -> str:
    lines = original.splitlines()
    if BEGIN in lines:
        start = lines.index(BEGIN)
        if END not in lines[start + 1:]:
            raise ValueError("Unclosed BluraySubtitle desktop settings in mpv.conf")
        end = lines.index(END, start + 1)
        del lines[start:end + 1]
    original = "\n".join(lines).rstrip("\n")
    uosc_language = "zh-hans" if language == "zh" else "en"
    profile_paths = {f"~~/{LAZY_PROFILES}", f"~~home/{LAZY_PROFILES}"}
    has_profile_include = any(
        key.strip() == "include" and value.strip().strip('"') in profile_paths
        for key, _, value in (line.partition("=") for line in lines)
    )
    profile_include = "" if has_profile_include else f"include=~~home/{LAZY_PROFILES}\n"
    block = (
        f"{BEGIN}\n"
        "[default]\n"
        "script-opts-append=select-menu_conf_path=~~home/menu.conf\n"
        f"script-opts-append=uosc-languages={uosc_language}\n"
        f"script-opts-append=bluray_defaults-language={language}\n"
        f"script-opts-append=bluray_vs-language={language}\n"
        f"{profile_include}"
        "include=~~home/bluray-defaults.conf\n"
        f"{END}\n"
    )
    return original + "\n\n" + block if original.strip() else block


def update_context_options(original: str) -> str:
    lines = original.splitlines()
    settings = {line.partition("=")[0].strip() for line in lines}
    if "scale_with_window" in settings:
        lines = [
            "scale_with_window=no" if line.partition("=")[0].strip() == "scale_with_window" else line
            for line in lines
        ]
    else:
        lines.append("scale_with_window=no")
    if "font_size" not in settings:
        lines.append("font_size=22")
    return "\n".join(lines) + "\n"


def uosc_version(main: Path) -> tuple[int, ...]:
    if not main.is_file():
        return ()
    match = re.search(r"^local uosc_version = '([\d.]+)'", main.read_text(encoding="utf-8"), re.MULTILINE)
    return tuple(map(int, match[1].split("."))) if match else ()


def uosc_is_installed(destination: Path) -> bool:
    target = destination / UOSC_DIR
    if not uosc_version(target / "main.lua") or not os.access(target / UOSC_BINARY, os.X_OK):
        return False
    # Older installations did not record their file list.
    recorded = read_text(target / UOSC_FILE_LIST).splitlines() or ["lib/std.lua", "elements/Menu.lua"]
    files = [target / name for name in (*UOSC_REQUIRED, *recorded)]
    files.extend(destination / "fonts" / name for name in UOSC_FONTS)
    return all(path.is_file() for path in files)


def install_uosc(bundle: Path, destination: Path) -> None:
    source = bundle / UOSC_DIR
    version = uosc_version(source / "main.lua")
    contents = [(name, (bundle / "fonts" / name).read_bytes()) for name in UOSC_FONTS]
    if not version or not all((source / path).is_file() for path in UOSC_REQUIRED):
        raise ValueError("The uosc release is missing Linux desktop files")

    source_files = sorted(path.relative_to(source) for path in source.rglob("*") if path.is_file())
    target = destination / UOSC_DIR
    if (
        uosc_version(target / "main.lua") < version
        or not os.access(target / UOSC_BINARY, os.X_OK)
        or not all((target / path).is_file() for path in source_files)
    ):
        target.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=destination, prefix=".uosc-") as directory:
            new = Path(directory) / "new"
            previous = Path(directory) / "previous"
            shutil.copytree(source, new)
            if target.exists() or target.is_symlink():
                target.rename(previous)
            try:
                new.rename(target)
            except OSError:
                if previous.exists() or previous.is_symlink():
                    previous.rename(target)
                raise
    for name, content in contents:
        write_if_changed(destination / "fonts" / name, content)
    file_list = "".join(f"{path.as_posix()}\n" for path in source_files)
    write_if_changed(target / UOSC_FILE_LIST, file_list.encode("utf-8"))


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return ""


def install_lazy_assets(destination: Path) -> None:
    files = {}
    for relative, _ in SHADERS:
        target = destination / SHADER_PATH / relative
        if target.is_file():
            continue
        digest = DOWNLOADED_SHADERS.get(relative)
        if digest is None:
            content = (BUNDLED_SHADERS / relative).read_bytes()
        else:
            content = subprocess.run(
                ["wget", "-q", "--timeout=30", "--tries=3", "-O", "-", f"{SHADER_URL}/{relative}"],
                check=True, stdout=subprocess.PIPE, timeout=120,
            ).stdout
            if sha256(content).hexdigest() != digest:
                raise ValueError(f"mpv-lazy shader failed SHA-256 verification: {relative}")
        files[target] = content

    profile_path = destination / LAZY_PROFILES
    if not profile_path.is_file():
        files[profile_path] = (ASSETS / "profiles.conf").read_bytes()
    for target, content in files.items():
        write_if_changed(target, content)


def desktop_files(destination: Path, language: str, plugin_dir: Path, original_menu: str) -> dict[Path, bytes]:
    main_path = destination / "mpv.conf"
    context_path = destination / "script-opts/context_menu.conf"
    plugin_dir = plugin_dir.resolve()
    presets = [
        name for name, (_, required) in PRESETS.items()
        if all((plugin_dir / filename).is_file() for filename in required)
    ]
    files = {
        destination / "bluray-vs" / name: (ASSETS / "vapoursynth" / name).read_bytes()
        for name in ("filters.py", *(f"{preset}.vpy" for preset in presets))
    }
    files.update({
        destination / "bluray-vs/plugins-dir": os.fsencode(plugin_dir),
        destination / "bluray-modules/atomic_write.lua": (ASSETS / "atomic_write.lua").read_bytes(),
        destination / "scripts/bluray_vs.lua": (ASSETS / "bluray_vs.lua").read_bytes(),
        destination / "scripts/bluray_defaults.lua": (ASSETS / "bluray_defaults.lua").read_bytes(),
        destination / "menu.conf": localize_menu(original_menu, language, presets).encode("utf-8"),
        context_path: update_context_options(read_text(context_path)).encode("utf-8"),
        main_path: update_main_config(read_text(main_path), language).encode("utf-8"),
    })
    return files


def desktop_is_current(language: str, plugin_dir: Path) -> bool:
    destination = config_directory()
    if (
        not uosc_is_installed(destination)
        or not (destination / "bluray-defaults.conf").is_file()
        or not (destination / LAZY_PROFILES).is_file()
        or not all((destination / SHADER_PATH / relative).is_file() for relative, _ in SHADERS)
    ):
        return False
    menu = read_text(destination / "menu.conf")
    return bool(menu.strip()) and all(
        path.is_file() and path.read_bytes() == content
        for path, content in desktop_files(destination, language, plugin_dir, menu).items()
    )


def install(bundle: Path, language: str, plugin_dir: Path) -> None:
    destination = config_directory()
    menu = read_text(destination / "menu.conf")
    if not menu.strip() and not os.environ.get("MPV_HOME"):
        menu = read_text(Path.home() / ".mpv/menu.conf")
    files = desktop_files(destination, language, plugin_dir, menu if menu.strip() else default_menu())
    install_lazy_assets(destination)
    install_uosc(bundle, destination)
    try:
        with (destination / "bluray-defaults.conf").open("x", encoding="utf-8") as stream:
            stream.write("# Settings saved from the mpv context menu\n")
    except FileExistsError:
        pass
    for path, content in files.items():
        write_if_changed(path, content)


if __name__ == "__main__":
    language = "zh" if sys.argv[2] == "zh" else "en"
    plugin_dir = Path(sys.argv[3])
    if sys.argv[1] == "--status":
        print("ready" if desktop_is_current(language, plugin_dir) else "install")
    else:
        install(Path(sys.argv[1]), language, plugin_dir)
