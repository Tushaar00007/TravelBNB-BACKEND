import time

rate_limit_store = {}

def is_rate_limited(key: str, limit: int = 3, window: int = 60):
    """
    limit = max requests
    window = time in seconds
    """
    now = time.time()

    if key not in rate_limit_store:
        rate_limit_store[key] = []

    # remove old requests
    rate_limit_store[key] = [
        t for t in rate_limit_store[key] if now - t < window
    ]

    if len(rate_limit_store[key]) >= limit:
        return True

    rate_limit_store[key].append(now)
    return False