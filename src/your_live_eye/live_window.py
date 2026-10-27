"""Use the source's recorded live interval; never infer live status from chat."""
import math


def live_interval(live):
    start, end = live.get('startDate'), live.get('stopDate')
    if (isinstance(start, bool) or isinstance(end, bool)
            or not isinstance(start, (int, float)) or not isinstance(end, (int, float))
            or not math.isfinite(start) or not math.isfinite(end)
            or start <= 0 or end <= start):
        return None
    return int(start), int(end)


def event_time_status(live, timestamp_ms):
    interval = live_interval(live)
    if interval is None:
        return 'unverified_window'
    start, end = interval
    return 'before_start' if timestamp_ms < start else 'after_stop' if timestamp_ms > end else 'inside'
