"""Print getnative results for one file, including sources taller than 1080p."""

from __future__ import annotations

import argparse
import os
import sys
import time


repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from src.core.i18n import translate_text


def main() -> None:
    language = 'zh' if os.environ.get('BLURAY_LANG') == 'zh' else 'en'
    parser = argparse.ArgumentParser(
        description=translate_text('Detect the native resolution of a video file.', language),
    )
    parser.add_argument('video_file', help=translate_text('Path to the input video file', language))
    args = parser.parse_args()
    source = os.path.abspath(os.path.expanduser(args.video_file))
    if not os.path.isfile(source):
        parser.error(translate_text('Video file not found: {path}', language).format(path=source))

    from src.runtime.services_split.encode_and_audio_tasks import EncodeAudioTasksMixin

    class _GetnativeService(EncodeAudioTasksMixin):
        def t(self, text: str) -> str:
            return translate_text(text, language)

    started = time.perf_counter()
    result = _GetnativeService()._infer_native_resolution(source)
    print(result, flush=True)
    print(round(time.perf_counter() - started, 3), flush=True)


if __name__ == '__main__':
    main()
