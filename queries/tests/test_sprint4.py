"""Tests sans MongoDB des outils du sprint 4 (time series, sharding)."""

from datetime import datetime, timezone

from queries import shard_report, timeseries_compare

REF = datetime(2026, 11, 21, 19, 23, 43, tzinfo=timezone.utc)


def test_timeseries_options():
    assert timeseries_compare.TS_OPTIONS == {
        "timeField": "ts", "metaField": "meta", "granularity": "seconds"}


def test_timeseries_queries_use_meta_fields():
    std = timeseries_compare.queries(REF, ts_coll=False)
    ts = timeseries_compare.queries(REF, ts_coll=True)
    assert set(std) == set(ts)
    assert std["a_avg_speed_by_region"][1]["$group"]["_id"] == "$region"
    assert ts["a_avg_speed_by_region"][1]["$group"]["_id"] == "$meta.region"
    assert "meta.vehicle_id" in ts["f_vehicle_history"][0]["$match"]
    assert "vehicle_id" in std["f_vehicle_history"][0]["$match"]
    # Mêmes fenêtres temporelles dans les deux versions
    for name in std:
        assert std[name][0]["$match"]["ts"] == ts[name][0]["$match"]["ts"]


def test_shard_keys_compared():
    assert shard_report.KEYS == {
        "region": {"region": 1},
        "hashed": {"vehicle_id": "hashed"},
        "vehicle_ts": {"vehicle_id": 1, "ts": 1},
    }


def test_targeting_queries_filter_on_each_key_field():
    q = shard_report.query_set(REF)
    assert q["region_tunis_1h"][0]["$match"]["region"] == "Tunis"      # ciblée avec la clé region
    assert q["vehicle_history"][0]["$match"]["vehicle_id"] == "VH-000001"  # ciblée avec vehicle_id
    assert "region" not in q["all_regions_1h"][0]["$match"]           # diffusée avec toutes les clés
