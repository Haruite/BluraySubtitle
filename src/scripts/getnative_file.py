"""Print the project's automatic getnative result for one configured video file."""

from __future__ import annotations

import os
import sys
import time

# Edit this path, then run the script directly from the repository checkout.
video_file = r'C:\path\to\video.m2ts'


repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from src.runtime.services_split.encode_and_audio_tasks import EncodeAudioTasksMixin


class _GetnativeService(EncodeAudioTasksMixin):
    def t(self, text: str) -> str:
        return text


def main() -> None:
    source = os.path.normpath(video_file)
    if not os.path.isfile(source):
        raise SystemExit(f'video_file not found: {source!r}')
    started = time.perf_counter()
    result = _GetnativeService()._infer_native_resolution(source)
    print(result, flush=True)
    print(round(time.perf_counter() - started, 3), flush=True)


if __name__ == '__main__':
    main()
