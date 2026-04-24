from .subtitle import Subtitle


def parse_subtitle_worker(file_path: str):
    try:
        return file_path, Subtitle(file_path)
    except Exception:
        return file_path, None


__all__ = ["parse_subtitle_worker"]

