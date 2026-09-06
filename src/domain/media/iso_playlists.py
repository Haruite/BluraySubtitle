"""Read only the playlist metadata needed to merge subtitles beside an ISO."""

import os
import subprocess
import threading

from src.core import settings
from src.core.i18n import translate_text
from src.runtime import TaskCancelled


def extract_iso_playlists(iso_path: str, destination: str, cancel_event: threading.Event) -> None:
    """Extract into a caller-owned temporary disc root without mounting the image."""
    if cancel_event.is_set():
        raise TaskCancelled()
    playlist_folder = os.path.join(destination, 'BDMV', 'PLAYLIST')
    os.makedirs(playlist_folder, exist_ok=False)
    # Flatten just this directory into a canonical BDMV layout. No stream data,
    # loop devices, drive letters, desktop services, or mount privileges are needed.
    command = [
        settings.SEVEN_ZIP_PATH, 'e', '-y', '-bd', '-bso0', '-bsp0', '-ssc-',
        f'-o{playlist_folder}', '--', os.path.abspath(iso_path), 'BDMV/PLAYLIST/*.mpls',
    ]
    try:
        with subprocess.Popen(
                command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        ) as process:
            try:
                while True:
                    if cancel_event.is_set():
                        raise TaskCancelled()
                    try:
                        output, _ = process.communicate(timeout=0.1)
                        break
                    except subprocess.TimeoutExpired:
                        continue
                if cancel_event.is_set():
                    raise TaskCancelled()
                if process.returncode != 0:
                    raise OSError(output.decode('utf-8', errors='replace').strip())
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
        playlist_files = os.listdir(playlist_folder)
        if not playlist_files:
            raise ValueError(translate_text('The ISO contains no BDMV playlists'))
        for name in playlist_files:
            # Blu-ray names are numeric; normalize the extension for existing readers.
            if name.lower().endswith('.mpls') and not name.endswith('.mpls'):
                os.rename(os.path.join(playlist_folder, name), os.path.join(playlist_folder, name[:-5] + '.mpls'))
    except (OSError, ValueError) as error:
        raise OSError(translate_text('Failed to read ISO playlists: {path}\n{error}').format(
            path=iso_path, error=error,
        )) from error
