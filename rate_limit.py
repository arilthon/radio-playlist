"""Espera para respostas HTTP 429."""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import math


def retry_delay(value, failures=1):
    fallback = min(900, 60 * 2 ** min(max(failures - 1, 0), 4))
    try:
        seconds = float(value)
        if not math.isfinite(seconds) or seconds < 0:
            return fallback
    except (TypeError, ValueError):
        try:
            date = parsedate_to_datetime(value)
            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
            seconds = (date - datetime.now(timezone.utc)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            return fallback
    return max(fallback, math.ceil(seconds))
