"""Collection time series vs collection standard (tâche S4).

1. Copie telemetry dans une collection time series telemetry_ts
   (timeField "ts", metaField "meta" = {vehicle_id, region}, granularity "seconds")
   avec un $out (MongoDB 7) ; mesure la durée.
2. Compare la taille sur disque (données + index).
3. Compare le temps de 4 requêtes équivalentes (médiane de 3) :
   telemetry sans index secondaire (cachés), telemetry avec les index du sprint 3,
   et telemetry_ts (index automatique sur meta + ts).

  python -m queries.timeseries_compare            # copie si absente, puis mesures
  python -m queries.timeseries_compare --rebuild  # recopie

Résultats : report/data/timeseries_compare.json (+ affichage)
"""

import argparse
import json
import os
import statistics
import time
from datetime import timedelta

from pymongo import MongoClient

from queries.ref_time import reference_time

MONGO_URI = os.getenv(
    "MONGO_URI", "mongodb://mongo1:27017,mongo2:27017,mongo3:27017/?replicaSet=rs0"
)
DB_NAME = os.getenv("DB_NAME", "fleet")
MB = 1024 * 1024
TS_OPTIONS = {"timeField": "ts", "metaField": "meta", "granularity": "seconds"}


def build_timeseries(db):
    """telemetry -> telemetry_ts (même contenu, champs vehicle_id/region regroupés dans meta)."""
    db.drop_collection("telemetry_ts")
    pipeline = [
        {"$project": {
            "_id": 0, "ts": 1,
            "meta": {"vehicle_id": "$vehicle_id", "region": "$region"},
            "location": 1, "speed_kmh": 1, "fuel_level_pct": 1, "fuel_rate_lph": 1,
            "engine_temp_c": 1, "odometer_km": 1, "trip_id": 1, "route_id": 1,
        }},
        {"$out": {"db": db.name, "coll": "telemetry_ts", "timeseries": TS_OPTIONS}},
    ]
    t0 = time.perf_counter()
    db.telemetry.aggregate(pipeline, allowDiskUse=True)
    return time.perf_counter() - t0


def storage(db, name):
    s = next(db[name].aggregate([{"$collStats": {"storageStats": {}}}]))["storageStats"]
    out = {
        "count": s.get("count"),
        "data_mb": round(s.get("size", 0) / MB, 1),
        "storage_mb": round(s.get("storageSize", 0) / MB, 1),
        "index_mb": round(s.get("totalIndexSize", 0) / MB, 1),
        "indexes": sorted(s.get("indexSizes", {})),
    }
    ts = s.get("timeseries")
    if ts:
        out["buckets"] = ts.get("bucketCount")
        out["avg_docs_per_bucket"] = round(ts.get("avgNumMeasurementsPerCommit", 0) or 0, 1)
    return out


def queries(ref, ts_coll):
    """4 requêtes équivalentes ; pour la time series, vehicle_id / region sont dans meta."""
    m = "meta." if ts_coll else ""
    hour = {"ts": {"$gte": ref - timedelta(hours=1), "$lte": ref}}
    day = {"ts": {"$gte": ref - timedelta(hours=24), "$lte": ref}}
    return {
        "a_avg_speed_by_region": [
            {"$match": hour},
            {"$group": {"_id": f"${m}region", "avg_speed": {"$avg": "$speed_kmh"}, "n": {"$sum": 1}}},
            {"$sort": {"avg_speed": -1}}],
        "d_overheat_alerts": [
            {"$match": {**day, "engine_temp_c": {"$gt": 105}}},
            {"$group": {"_id": f"${m}vehicle_id", "max_temp": {"$max": "$engine_temp_c"},
                        "count": {"$sum": 1}}},
            {"$sort": {"count": -1}}],
        "e_speed_distribution": [
            {"$match": hour},
            {"$bucket": {"groupBy": "$speed_kmh", "boundaries": [0, 20, 40, 60, 80, 100, 130],
                         "default": "hors plage", "output": {"count": {"$sum": 1}}}}],
        "f_vehicle_history": [
            {"$match": {**day, f"{m}vehicle_id": "VH-000001"}},
            {"$sort": {"ts": -1}}, {"$limit": 100}],
    }


def timed(coll, pipeline, repeat):
    times, rows = [], None
    for _ in range(repeat):
        t0 = time.perf_counter()
        rows = list(coll.aggregate(pipeline, allowDiskUse=True))
        times.append((time.perf_counter() - t0) * 1000)
    return round(statistics.median(times), 1), [round(t) for t in times], len(rows)


def set_hidden(db, hidden):
    names = [n for n in db.telemetry.index_information() if n != "_id_"]
    for n in names:
        db.command("collMod", "telemetry", index={"name": n, "hidden": hidden})
    return names


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--rebuild", action="store_true")
    p.add_argument("--repeat", type=int, default=3)
    p.add_argument("--out", default="report/data/timeseries_compare.json")
    args = p.parse_args()

    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    ref = reference_time(db)
    result = {"reference_time": ref.isoformat()}

    if args.rebuild or "telemetry_ts" not in db.list_collection_names():
        print("Copie telemetry -> telemetry_ts (time series)...", flush=True)
        result["build_seconds"] = round(build_timeseries(db), 1)
        print(f"  fait en {result['build_seconds']} s")

    result["storage"] = {"telemetry": storage(db, "telemetry"),
                         "telemetry_ts": storage(db, "telemetry_ts")}
    for name, s in result["storage"].items():
        print(f"{name:<13} docs={s['count']}  données={s['data_mb']} Mo  "
              f"disque={s['storage_mb']} Mo  index={s['index_mb']} Mo  {s['indexes']}"
              + (f"  buckets={s['buckets']}" if "buckets" in s else ""))

    print(f"\n{'requête':<24} {'standard sans index':>20} {'standard + index':>17} "
          f"{'time series':>12}   (ms, médiane de {args.repeat})")
    result["queries"] = {}
    std_q, ts_q = queries(ref, False), queries(ref, True)
    for name in std_q:
        hidden = set_hidden(db, True)
        try:
            no_idx = timed(db.telemetry, std_q[name], args.repeat)
        finally:
            set_hidden(db, False)
        with_idx = timed(db.telemetry, std_q[name], args.repeat)
        tsr = timed(db.telemetry_ts, ts_q[name], args.repeat)
        assert no_idx[2] == with_idx[2] == tsr[2], f"{name} : résultats différents"
        result["queries"][name] = {"rows": tsr[2],
                                   "standard_no_index_ms": no_idx[0],
                                   "standard_indexed_ms": with_idx[0],
                                   "timeseries_ms": tsr[0],
                                   "runs": {"no_index": no_idx[1], "indexed": with_idx[1],
                                            "timeseries": tsr[1]}}
        print(f"{name:<24} {no_idx[0]:>20} {with_idx[0]:>17} {tsr[0]:>12}   ({tsr[2]} lignes)")
    result["hidden_during_no_index"] = hidden

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"\nRésultats : {args.out}")
    client.close()


if __name__ == "__main__":
    main()
