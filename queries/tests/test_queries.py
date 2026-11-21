"""Tests des requêtes (structure des pipelines) et de l'outil de comparaison, sans MongoDB."""

from datetime import datetime, timedelta, timezone

from queries.compare_explain import gain
from queries.pipelines import ALL, TUNIS, TUNIS_ZONE

REF = datetime(2026, 11, 21, 19, 23, 43, tzinfo=timezone.utc)


def first_match(pipeline):
    return next(st["$match"] for st in pipeline if "$match" in st)


def test_every_query_targets_a_known_collection():
    for name, build in ALL.items():
        coll, pipeline = build(REF)
        assert coll in ("telemetry", "vehicle_state"), name
        assert isinstance(pipeline, list) and pipeline, name


def test_telemetry_aggregations_have_a_time_window():
    """Correction du plan : a, b, d, e, f et la zone filtrent sur ts (sinon COLLSCAN complet)."""
    for name, build in ALL.items():
        coll, pipeline = build(REF)
        if coll != "telemetry":
            continue
        ts = first_match(pipeline)["ts"]
        assert ts["$lte"] == REF, name
        assert ts["$gte"] < REF, name


def test_windows_are_relative_to_the_reference_time():
    _, a = ALL["a_avg_speed_by_region"](REF)
    _, d = ALL["d_overheat_alerts"](REF)
    assert first_match(a)["ts"]["$gte"] == REF - timedelta(hours=1)
    assert first_match(d)["ts"]["$gte"] == REF - timedelta(hours=24)
    assert first_match(d)["engine_temp_c"] == {"$gt": 105}


def test_geonear_is_first_stage_with_lon_lat():
    coll, pipeline = ALL["geo_near_point"](REF)
    assert coll == "vehicle_state"
    near = pipeline[0]["$geoNear"]                  # doit être le premier étage
    lon, lat = near["near"]["coordinates"]
    assert (lon, lat) == tuple(TUNIS) and 7 <= lon <= 12 and 30 <= lat <= 38
    assert near["maxDistance"] == 10_000


def test_zone_polygon_is_closed_geojson():
    ring = TUNIS_ZONE["coordinates"][0]
    assert ring[0] == ring[-1]                     # anneau fermé (GeoJSON)
    assert all(7 <= lon <= 12 and 30 <= lat <= 38 for lon, lat in ring)


def test_speed_buckets_match_the_plan():
    _, e = ALL["e_speed_distribution"](REF)
    bucket = next(st["$bucket"] for st in e if "$bucket" in st)
    assert bucket["boundaries"] == [0, 20, 40, 60, 80, 100, 130]


def test_gain_formatting():
    assert gain(4680, 1604) == "×2.9"
    assert gain(3574, 8766) == "**÷2.5**"
    assert gain(5, 6) == "≈"                       # quelques ms : bruit
    assert gain(2968, 0).startswith("×2")
    assert gain(None, 10) == ""
