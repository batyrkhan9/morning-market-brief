"""Retry a network call 3 times with exponential backoff."""
import time

ATTEMPTS = 3
BACKOFF_SECONDS = 2.0


def retry(fn, *args, **kwargs):
    last = None
    for attempt in range(ATTEMPTS):
        try:
            return fn(*args, **kwargs)
        except Exception as e:  # noqa: BLE001 - any network error counts
            last = e
            if attempt < ATTEMPTS - 1:
                time.sleep(BACKOFF_SECONDS * (2 ** attempt))
    raise last
