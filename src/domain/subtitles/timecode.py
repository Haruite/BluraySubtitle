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


__all__ = ["parse_hhmmss_ms_to_seconds"]
