def parse_hhmmss_ms_to_seconds(ts: str) -> float:
    try:
        ts = ts.strip()
        if len(ts) < 12:
            return 0.0
        h = int(ts[0:2])
        m = int(ts[3:5])
        s = int(ts[6:8])
        ms = int(ts[9:12])
        return h * 3600 + m * 60 + s + ms / 1000
    except (ValueError, IndexError):
        return 0.0


def format_srt_timestamp(seconds: float) -> str:
    total_milliseconds = int(round(float(seconds) * 1000))
    hours, remainder = divmod(total_milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return f'{hours:02d}:{minutes:02d}:{whole_seconds:02d},{milliseconds:03d}'


__all__ = ["format_srt_timestamp", "parse_hhmmss_ms_to_seconds"]
