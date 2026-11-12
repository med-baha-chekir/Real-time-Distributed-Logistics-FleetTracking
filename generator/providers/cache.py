import time


class TTLCache:

    def __init__(self):
        self._store = {}

    def get(self, key):
        """Return cached value if it exists and is not expired."""

        item = self._store.get(key)

        if item is None:
            return None

        value, expires_at = item

        if time.monotonic() >= expires_at:
            del self._store[key]
            return None

        return value

    def set(self, key, value, ttl_seconds):
        """Store a value with an expiration time."""

        expires_at = time.monotonic() + ttl_seconds

        self._store[key] = (value, expires_at)

    def delete(self, key):
        self._store.pop(key, None)

    def clear(self):
        self._store.clear()


# Shared cache instance
cache = TTLCache()
