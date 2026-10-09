"""Helpers shared by every digital twin's views."""

from django.core.cache import cache
from django.shortcuts import render

SIMULATE_RATE_LIMIT = 20   # max requests per user per window
SIMULATE_RATE_WINDOW = 60  # seconds

# Read size when streaming a stored result file to the browser or a parser.
RESULT_STREAM_CHUNK = 64 * 1024


def dt_render(request, template, **extra):
    return render(request, template, {'show_sidebar': True, 'active_navbar_page': 'facilities', **extra})


def check_rate_limit(user_id, prefix, limit=SIMULATE_RATE_LIMIT, window=SIMULATE_RATE_WINDOW):
    key = f'{prefix}_simulate_rl_{user_id}'
    count = cache.get(key, 0)
    if count >= limit:
        return False
    cache.set(key, count + 1, timeout=window)
    return True


def format_duration(seconds):
    total_seconds = int(seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f'{hours}h {minutes:02d}m'
    return f'{minutes}m {secs:02d}s'


def iter_body_chunks(body, chunk_size=RESULT_STREAM_CHUNK):
    """Yield an object-storage body in chunks, closing it when done or abandoned."""
    try:
        while True:
            chunk = body.read(chunk_size)
            if not chunk:
                break
            yield chunk
    finally:
        body.close()
