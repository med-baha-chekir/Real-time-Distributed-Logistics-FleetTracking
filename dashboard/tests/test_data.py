"""Tests de la couche données du dashboard (sans MongoDB ni Streamlit)."""

from datetime import datetime, timedelta, timezone

from pymongo import ReadPreference

from dashboard import data

REF = datetime(2026, 11, 21, 19, 23, 43, tzinfo=timezone.utc)


def state_doc(vid, lon=10.18, lat=36.80, speed=60.0, temp=90.0, age_min=0):
    return {"_id": vid, "location": {"type": "Point", "coordinates": [lon, lat]},
            "region": "Tunis", "route_id": "R01", "speed_kmh": speed, "engine_temp_c": temp,
            "fuel_level_pct": 50.0, "last_ts": REF - timedelta(minutes=age_min)}


def test_classify():
    assert data.classify(80, 90) == "en route"
    assert data.classify(0, 90) == "arrêt"
    assert data.classify(0.5, 90) == "arrêt"
    assert data.classify(80, 110) == "alerte"          # la surchauffe prime sur la vitesse
    assert data.classify(None, None) == "arrêt"


def test_state_frame_keeps_lon_lat_order_and_colors():
    df = data.state_frame([state_doc("VH-000001", lon=10.5, lat=36.1),
                           state_doc("VH-000002", speed=0),
                           state_doc("VH-000003", temp=112)])
    assert list(df["lon"]) [0] == 10.5 and list(df["lat"])[0] == 36.1   # GeoJSON [lon, lat]
    assert list(df["status"]) == ["en route", "arrêt", "alerte"]
    assert df.loc[2, "color"] == data.STATUS_COLORS["alerte"]


def test_state_frame_empty_has_columns():
    df = data.state_frame([])
    assert df.empty and {"lon", "lat", "status", "color"} <= set(df.columns)


def test_kpis():
    df = data.state_frame([
        state_doc("VH-000001", speed=80),
        state_doc("VH-000002", speed=60),
        state_doc("VH-000003", speed=0),                 # actif mais à l'arrêt
        state_doc("VH-000004", speed=70, temp=110),      # en surchauffe
        state_doc("VH-000005", speed=90, age_min=30),    # plus de message depuis 30 min
    ])
    k = data.kpis(df, REF, avg_fuel_lph=31.2, alerts_24h=3)
    assert k["trucks"] == 5
    assert k["active"] == 4                              # le 5e est trop ancien
    assert k["moving"] == 3
    assert k["avg_speed"] == 70.0                        # (80 + 60 + 70) / 3
    assert k["overheating_now"] == 1
    assert k["avg_fuel_lph"] == 31.2 and k["alerts_24h"] == 3


def test_kpis_empty():
    k = data.kpis(data.state_frame([]), REF, None, None)
    assert k["trucks"] == 0 and k["avg_speed"] is None


def test_histogram_frame_orders_buckets():
    rows = [{"_id": 60, "count": 5}, {"_id": 0, "count": 2}, {"_id": 100, "count": 1},
            {"_id": 20, "count": 3}]
    df = data.histogram_frame(rows)
    assert list(df["tranche"]) == ["0–20", "20–40", "60–80", "100–130"]
    assert list(df["messages"]) == [2, 3, 5, 1]


def test_format_age():
    assert data.format_age(45) == "45 s"
    assert data.format_age(720) == "12 min"
    assert data.format_age(7500) == "2 h 05"
    assert data.format_age(3 * 86400 + 5) == "3 j"


def test_route_paths_from_repository_file():
    paths = data.load_route_paths()
    assert len(paths) == 13                              # 13 itinéraires OSRM
    lon, lat = paths[0]["path"][0]
    assert 7 <= lon <= 12 and 30 <= lat <= 38
    assert data.load_route_paths("absent.json") == []


def test_client_reads_from_secondary_during_failover():
    client = data.make_client("mongodb://localhost:1/?serverSelectionTimeoutMS=10")
    try:
        assert client.read_preference == ReadPreference.PRIMARY_PREFERRED
    finally:
        client.close()
