"""Tests du module OSRM : réponse simulée par défaut, appel réel si RUN_NETWORK_TESTS=1."""

import os

import pytest

from generator.providers import routing
from generator.providers.cache import cache

TUNIS = (36.8065, 10.1815)    # get_route attend (latitude, longitude)
SOUSSE = (35.8256, 10.6369)

FAKE_OSRM = {
    "code": "Ok",
    "routes": [{
        "distance": 148226.1,
        "duration": 6706.2,
        "geometry": {"type": "LineString",
                     "coordinates": [[10.1815, 36.8065], [10.4, 36.4], [10.6369, 35.8256]]},
        "legs": [{"steps": []}],
    }],
}


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()


def test_routing_provider(monkeypatch):
    calls = []

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append(url)
        return FakeResponse(FAKE_OSRM)

    monkeypatch.setattr(routing.requests, "get", fake_get)
    result = routing.get_route(TUNIS, SOUSSE)

    # L'URL OSRM est en longitude,latitude
    assert calls[0].endswith("/driving/10.1815,36.8065;10.6369,35.8256")
    assert result["distance_m"] > 0 and result["duration_s"] > 0
    assert result["geometry"]["type"] == "LineString"
    assert len(result["coordinates"]) > 2

    # Deuxième appel : servi par le cache
    routing.get_route(TUNIS, SOUSSE)
    assert len(calls) == 1


def test_routing_rejects_invalid_coordinates():
    with pytest.raises(ValueError):
        routing.get_route((95, 10), SOUSSE)


def test_routing_error_code(monkeypatch):
    monkeypatch.setattr(routing.requests, "get",
                        lambda *a, **k: FakeResponse({"code": "NoRoute", "routes": []}))
    with pytest.raises(RuntimeError):
        routing.get_route(TUNIS, SOUSSE)


@pytest.mark.skipif(os.getenv("RUN_NETWORK_TESTS") != "1", reason="appel réel à OSRM")
def test_routing_live():
    result = routing.get_route(TUNIS, SOUSSE)
    assert 120_000 < result["distance_m"] < 200_000
    lon, lat = result["coordinates"][0]
    assert 7 <= lon <= 12 and 30 <= lat <= 38
