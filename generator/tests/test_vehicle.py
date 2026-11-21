"""Tests du modèle de camion v2 (sans MongoDB ni Internet)."""

import math
import re
from datetime import datetime, timedelta, timezone

import pytest

from generator import config as cfg
from generator.geo import nearest_city
from generator.route_network import load_routes
from generator.routes import CITIES
from generator.vehicle import Vehicle

T0 = datetime(2026, 11, 21, 8, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def routes():
    return load_routes()


def simulate(vehicle, steps, dt=5):
    return [vehicle.step(dt, T0 + timedelta(seconds=dt * k)) for k in range(steps)]


def test_geojson_order_and_tunisia_bounds(routes):
    """[longitude, latitude] et dans les bornes du validateur (init-db.js)."""
    for n in range(1, 21):
        for doc in simulate(Vehicle(n, routes), 50):
            loc = doc["location"]
            assert loc["type"] == "Point"
            lon, lat = loc["coordinates"]
            assert 7 <= lon <= 12, "longitude hors Tunisie (inversion lat/lng ?)"
            assert 30 <= lat <= 38


def test_timestamp_is_the_given_utc_datetime(routes):
    doc = Vehicle(1, routes).step(5, T0)
    assert isinstance(doc["ts"], datetime)
    assert doc["ts"] == T0
    assert doc["ts"].utcoffset() == timedelta(0)


def test_numeric_fields_and_ranges(routes):
    for doc in simulate(Vehicle(3, routes), 300):
        for field in ("speed_kmh", "fuel_level_pct", "fuel_rate_lph",
                      "engine_temp_c", "odometer_km"):
            value = doc[field]
            assert isinstance(value, float) and not isinstance(value, bool)
            assert math.isfinite(value)
        assert 0 <= doc["speed_kmh"] <= 160          # bornes du validateur
        assert 0 <= doc["fuel_level_pct"] <= 100
        assert doc["fuel_rate_lph"] >= 0


def test_region_is_one_of_the_12_cities(routes):
    docs = [d for n in range(1, 31) for d in simulate(Vehicle(n, routes), 20)]
    assert all(d["region"] in CITIES for d in docs)
    # La région suit la position : vrai pour l'immense majorité des points
    same = sum(d["region"] == nearest_city(tuple(d["location"]["coordinates"])) for d in docs)
    assert same / len(docs) > 0.95


def test_identifiers(routes):
    doc = Vehicle(42, routes).step(5, T0)
    assert doc["vehicle_id"] == "VH-000042"
    assert re.fullmatch(r"TR-\d{8}-000042-\d{3}", doc["trip_id"])
    assert re.fullmatch(r"R\d{2}", doc["route_id"])


def test_same_seed_same_data_different_seed_different_data(routes):
    a = simulate(Vehicle(7, routes, seed=1), 30)
    b = simulate(Vehicle(7, routes, seed=1), 30)
    c = simulate(Vehicle(7, routes, seed=2), 30)
    assert a == b
    assert a != c


def test_trucks_start_spread_over_the_country(routes):
    starts = [Vehicle(n, routes).step(5, T0) for n in range(1, 301)]
    assert len({d["route_id"] for d in starts}) >= 10
    assert len({d["region"] for d in starts}) >= 9
    # Plus de concentration dans la zone de Tunis (défaut du v1 : 42 %)
    in_tunis_box = sum(10.10 <= d["location"]["coordinates"][0] <= 10.25
                       and 36.78 <= d["location"]["coordinates"][1] <= 36.87
                       for d in starts)
    assert in_tunis_box / len(starts) < 0.10


def test_speeds_are_varied_with_stops(routes):
    docs = [d for n in range(1, 41) for d in simulate(Vehicle(n, routes), 360)]
    speeds = [d["speed_kmh"] for d in docs]
    assert any(s < 1 for s in speeds), "aucun arrêt"
    assert any(30 <= s < 60 for s in speeds), "pas de vitesse urbaine"
    assert any(s >= 80 for s in speeds), "pas de vitesse sur route"
    assert max(speeds) <= cfg.TRUCK_MAX_SPEED + 8 + 1e-9


def test_delivery_at_route_end_changes_trip(routes):
    v = Vehicle(5, routes)
    v.direction, v.km, v.stop_remaining_s, v.speed_kmh = 1, v.route.length_km - 0.05, 0, 80
    first_trip = v.trip_id
    simulate(v, 5)
    assert v.trip_id != first_trip
    assert v.direction == -1
    assert v.stop_remaining_s > 0                    # arrêt de livraison


def test_overheat_anomaly_produces_alerts(routes, monkeypatch):
    monkeypatch.setattr(cfg, "OVERHEAT_PRONE_RATIO", 1.0)
    v = Vehicle(9, routes)
    assert v.overheat_prone
    temps = [d["engine_temp_c"] for d in simulate(v, 2000)]
    assert max(temps) > cfg.OVERHEAT_THRESHOLD_C


def test_normal_trucks_stay_below_overheat(routes, monkeypatch):
    monkeypatch.setattr(cfg, "OVERHEAT_PRONE_RATIO", 0.0)
    temps = [d["engine_temp_c"] for n in range(1, 11) for d in simulate(Vehicle(n, routes), 500)]
    assert max(temps) < cfg.OVERHEAT_THRESHOLD_C


def test_anomaly_ratio_about_one_percent(routes):
    fleet = [Vehicle(n, routes) for n in range(1, 5001)]
    prone = sum(v.overheat_prone for v in fleet) / len(fleet)
    leak = sum(v.fuel_leak for v in fleet) / len(fleet)
    assert 0.005 < prone < 0.02
    assert 0.005 < leak < 0.02


def test_fuel_leak_consumes_more(routes, monkeypatch):
    monkeypatch.setattr(cfg, "FUEL_LEAK_RATIO", 0.0)
    normal = Vehicle(11, routes)
    monkeypatch.setattr(cfg, "FUEL_LEAK_RATIO", 1.0)
    leaking = Vehicle(11, routes)
    for v in (normal, leaking):
        v.stop_remaining_s, v.speed_kmh = 0, 80
    rate_n = sum(d["fuel_rate_lph"] for d in simulate(normal, 100)) / 100
    rate_l = sum(d["fuel_rate_lph"] for d in simulate(leaking, 100)) / 100
    assert rate_l > 1.3 * rate_n


def test_low_fuel_triggers_refuel(routes):
    v = Vehicle(13, routes)
    v.fuel_level_pct, v.stop_remaining_s, v.speed_kmh = 14.0, 0, 70
    docs = simulate(v, 2000)
    assert max(d["fuel_level_pct"] for d in docs[1:]) > 90, "pas de ravitaillement"


def test_rain_reduces_speed(routes):
    dry = Vehicle(15, routes, weather={c: {"temperature": 20, "rain": 0} for c in CITIES})
    wet = Vehicle(15, routes, weather={c: {"temperature": 20, "rain": 5} for c in CITIES})
    for v in (dry, wet):
        v.stop_remaining_s = 0
    mean = lambda v: sum(d["speed_kmh"] for d in simulate(v, 60)) / 60
    assert mean(wet) < mean(dry)


def test_reference_doc_matches_vehicles_schema(routes):
    doc = Vehicle(1, routes).reference_doc(T0)
    assert doc["_id"] == "VH-000001"
    assert doc["home_region"] in CITIES
    assert doc["status"] == "active"
    assert isinstance(doc["capacity_t"], int)
