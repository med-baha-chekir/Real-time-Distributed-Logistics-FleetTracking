"""Tests météo : module Open-Meteo et contexte météo de la simulation."""

import os
from datetime import datetime

import pytest

from generator import weather_context
from generator.providers import weather
from generator.providers.cache import cache

FAKE_METEO = {
    "timezone": "Africa/Tunis",
    "hourly": {
        "time": ["2026-11-21T08:00", "2026-11-21T09:00"],
        "temperature_2m": [18.5, 19.2],
        "rain": [0.0, 2.4],
        "wind_speed_10m": [12.0, 14.0],
        "snowfall": [0.0, 0.0],
    },
}


class FakeResponse:
    def raise_for_status(self):
        pass

    def json(self):
        return FAKE_METEO


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()


def test_weather_provider(monkeypatch):
    monkeypatch.setattr(weather.requests, "get", lambda *a, **k: FakeResponse())
    result = weather.get_weather(latitude=36.8065, longitude=10.1815)
    for key in ("temperature", "rain", "wind_speed", "snowfall"):
        assert key in result
    assert len(result["temperature"]) == len(result["time"]) == 2


def test_weather_context_picks_current_hour(monkeypatch):
    monkeypatch.setattr(weather.requests, "get", lambda *a, **k: FakeResponse())
    ctx = weather_context.load_weather(now=datetime(2026, 11, 21, 9, 30))
    assert len(ctx) == 12
    assert ctx["Tunis"] == {"temperature": 19.2, "rain": 2.4}


def test_weather_context_offline_is_neutral(monkeypatch):
    def offline(*a, **k):
        raise weather.requests.ConnectionError("pas de réseau")

    monkeypatch.setattr(weather.requests, "get", offline)
    assert weather_context.load_weather() == {}
    assert weather_context.load_weather(enabled=False) == {}


@pytest.mark.skipif(os.getenv("RUN_NETWORK_TESTS") != "1", reason="appel réel à Open-Meteo")
def test_weather_live():
    result = weather.get_weather(36.8065, 10.1815)
    assert len(result["time"]) > 0
