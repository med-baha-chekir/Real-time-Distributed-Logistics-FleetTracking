
import time
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from generator.providers.cache import TTLCache


def test_cache_hit():
    cache = TTLCache()

    cache.set("weather", {"temperature": 25}, 10)

    assert cache.get("weather") == {"temperature": 25}


def test_cache_expiration():
    cache = TTLCache()

    cache.set("weather", {"temperature": 25}, 0.1)

    time.sleep(0.2)

    assert cache.get("weather") is None


def test_cache_miss():
    cache = TTLCache()

    assert cache.get("unknown") is None
