"""Batch movie-mode BDMV remux (same pipeline as GUI movie mode + Start Remux)."""
from __future__ import annotations

import argparse
import os
import sys

# --- configure paths (only parameters you need to edit when not using CLI) ---
movie_folder = r'C:\tmp'  # parent folder containing BDMV disc directories
output_folder = r'C:\Remux'  # remux output root


def _repo_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))


def _ensure_import_path() -> None:
    root = _repo_root()
    if root not in sys.path:
        sys.path.insert(0, root)


def _folder_size_gib(folder: str) -> float:
    total = 0
    for root, _dirs, files in os.walk(folder):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return round(total / 1024 ** 3, 3)


def _dst_folder_for_bdmv(movie_root: str, output_root: str, bdmv_folder: str) -> str:
    movie_root = os.path.normpath(movie_root)
    output_root = os.path.normpath(output_root)
    bdmv_folder = os.path.normpath(bdmv_folder)
    rel = os.path.relpath(bdmv_folder, movie_root)
    if rel in ('.', ''):
        return output_root
    return os.path.normpath(os.path.join(output_root, rel))


def iter_bdmv_folders(movie_root: str) -> list[str]:
    """Find disc roots under movie_root (same scan as movie_remux.py main())."""
    movie_root = os.path.normpath(movie_root)
    found: list[str] = []
    seen: set[str] = set()

    def _add(candidate: str) -> None:
        path = os.path.normpath(candidate)
        if path in seen:
            return
        playlist = os.path.join(path, 'BDMV', 'PLAYLIST')
        if os.path.isdir(os.path.join(path, 'BDMV')) and os.path.isdir(playlist):
            seen.add(path)
            found.append(path)

    try:
        for name in os.listdir(movie_root):
            child = os.path.join(movie_root, name)
            if not os.path.isdir(child):
                continue
            for root, dirs, _files in os.walk(child):
                if 'BDMV' in dirs and os.path.isdir(os.path.join(root, 'BDMV', 'PLAYLIST')):
                    _add(root)
    except OSError:
        pass
    return sorted(found)


def _progress_cb(value: int | None = None, text: str | None = None) -> None:
    if text:
        prefix = f'[{value}] ' if value is not None else ''
        print(f'{prefix}{text}', flush=True)


def _mpls_rel_from_disc(mpls_no_ext: str) -> str:
    """Relative MPLS path from disc root (matches GUI cwd assumptions for ``00800.mpls``)."""
    stem = os.path.splitext(os.path.basename(str(mpls_no_ext or '').strip()))[0]
    return os.path.join('BDMV', 'PLAYLIST', stem)


def _patch_configuration_mpls_paths(
    configuration: dict[int, dict[str, int | str]],
    bdmv_folder: str,
    mpls_no_ext: str,
) -> None:
    """Store ``selected_mpls`` as ``BDMV/PLAYLIST/<stem>`` so service code can open ``<stem>.mpls`` from disc root."""
    rel = _mpls_rel_from_disc(mpls_no_ext)
    for conf in configuration.values():
        conf['folder'] = bdmv_folder
        conf['selected_mpls'] = rel


def remux_one_disc(bdmv_folder: str, movie_root: str, output_root: str) -> None:
    from src.core import find_mkvtoolnix, translate_text
    from src.runtime.remux import RemuxRequest
    from src.runtime.services import BluraySubtitle
    from src.runtime.sp import SpEntry

    bdmv_folder = os.path.normpath(bdmv_folder)
    playlist_cwd = os.path.join(bdmv_folder, 'BDMV', 'PLAYLIST')
    old_cwd = os.getcwd()
    try:
        os.chdir(bdmv_folder)
    except OSError as exc:
        print(f'Skip remux {bdmv_folder}: cannot chdir to disc root ({exc})', flush=True)
        return

    try:
        find_mkvtoolnix()
        bs = BluraySubtitle(bdmv_folder, [], False, _progress_cb, movie_mode=True, mux_dolby_vision=True)
        main_mpls_path = bs.get_main_mpls(bdmv_folder, checked=False)
        if not main_mpls_path or not os.path.isfile(main_mpls_path):
            print(f'Skip remux {bdmv_folder}: no main MPLS found', flush=True)
            return
        mpls_no_ext = os.path.splitext(os.path.basename(main_mpls_path))[0]
        # Service layer expects MPLS stem while cwd is PLAYLIST (or relative BDMV/PLAYLIST from disc root).
        try:
            os.chdir(playlist_cwd)
        except OSError as exc:
            print(f'Skip remux {bdmv_folder}: cannot chdir to PLAYLIST ({exc})', flush=True)
            return
        selected_mpls = [(bdmv_folder, os.path.splitext(main_mpls_path)[0])]
        configuration, episode_output_names = bs.build_movie_mode_configuration(selected_mpls)
        if not configuration:
            print(f'Skip remux {bdmv_folder}: empty movie configuration', flush=True)
            return
        _patch_configuration_mpls_paths(configuration, bdmv_folder, mpls_no_ext)
        sp_entries = bs.build_movie_mode_sp_entries(configuration)
        os.chdir(bdmv_folder)
        dst_folder = _dst_folder_for_bdmv(movie_root, output_root, bdmv_folder)
        remux_parent = os.path.dirname(dst_folder)
        request = RemuxRequest(
            bdmv_path=bdmv_folder,
            subtitle_files=(),
            complete_bluray_folder=False,
            output_folder=os.path.normpath(remux_parent),
            configuration=configuration,
            selected_mpls=tuple(selected_mpls),
            sp_entries=tuple(SpEntry.from_mapping(entry) for entry in sp_entries),
            episode_output_names=tuple(episode_output_names),
            episode_subtitle_languages=tuple('' for _ in configuration),
            movie_mode=True,
            mux_dolby_vision=True,
            ensure_tools=True,
        )
        bs.episodes_remux(
            request,
            cancel_event=None,
        )
        bd_size = _folder_size_gib(bdmv_folder)
        remux_size = _folder_size_gib(dst_folder)
        summary = translate_text(
            'Remux {path} completed: BDMV size {bd_size} GiB, remux size {remux_size} GiB, '
            'reduced size {reduced_size:.3f} GiB.'
        ).format(
            path=bdmv_folder,
            bd_size=bd_size,
            remux_size=remux_size,
            reduced_size=bd_size - remux_size,
        )
        print(summary, flush=True)
    except Exception as exc:
        print(f'Skip remux {bdmv_folder}: {exc}', flush=True)
    finally:
        try:
            os.chdir(old_cwd)
        except OSError:
            pass


def main() -> None:
    _ensure_import_path()
    parser = argparse.ArgumentParser(
        description='Batch remux every BDMV under movie_folder (GUI movie mode defaults).',
    )
    parser.add_argument(
        'movie_folder',
        nargs='?',
        default=movie_folder,
        help='Folder containing movie BDMV directories',
    )
    parser.add_argument(
        'output_folder',
        nargs='?',
        default=output_folder,
        help='Output root (each disc -> output_folder/<relative path>)',
    )
    args = parser.parse_args()
    movie_root = os.path.normpath(str(args.movie_folder or '').strip())
    output_root = os.path.normpath(str(args.output_folder or '').strip())
    if not movie_root or not os.path.isdir(movie_root):
        raise SystemExit(f'movie_folder not found: {movie_root!r}')
    if not output_root:
        raise SystemExit('output_folder is required')
    os.makedirs(output_root, exist_ok=True)
    discs = iter_bdmv_folders(movie_root)
    if not discs:
        print(f'No BDMV/PLAYLIST found under {movie_root}')
        return
    print(f'Found {len(discs)} disc(s) under {movie_root}')
    for disc in discs:
        print(f'--- remux {disc} ---')
        remux_one_disc(disc, movie_root, output_root)


if __name__ == '__main__':
    main()
