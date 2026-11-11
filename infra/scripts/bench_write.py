"""Benchmark d'ingestion : write concern (w:1 / w:majority) x taille de lot.

Insère des documents de télémétrie factices, conformes au validateur, dans une
collection dédiée (bench_telemetry, supprimée au début de chaque combinaison)
pour ne pas polluer telemetry. Mesure :
  - débit (documents / s) ;
  - latence d'un insert_many : moyenne, médiane, 95e centile.

Lancement :
  docker compose -f infra/docker-compose.rs.yml --profile tools run --rm tools \
      python infra/scripts/bench_write.py --docs 200000

À refaire avec le vrai générateur v2 (variable WRITE_CONCERN) pour le rapport final.
"""

import argparse
import json
import os
import random
import statistics
import time
from datetime import datetime, timedelta, timezone

from pymongo import MongoClient
from pymongo.write_concern import WriteConcern

MONGO_URI = os.getenv(
    "MONGO_URI", "mongodb://mongo1:27017,mongo2:27017,mongo3:27017/?replicaSet=rs0"
)
DB_NAME = os.getenv("DB_NAME", "fleet")
REGIONS = ["Tunis", "Bizerte", "Nabeul", "Sousse", "Monastir", "Kairouan",
           "Sfax", "Gabes", "Gafsa", "Kasserine", "Beja", "Kef"]


def fake_docs(n, start_ts, rng):
    """n documents au format telemetry (voir docs/data-model.md)."""
    docs = []
    for i in range(n):
        vid = rng.randint(1, 5000)
        docs.append({
            "vehicle_id": f"VH-{vid:06d}",
            "ts": start_ts + timedelta(milliseconds=i),
            "location": {"type": "Point",
                         "coordinates": [round(rng.uniform(8.0, 11.0), 6),
                                         round(rng.uniform(33.5, 37.3), 6)]},
            "region": rng.choice(REGIONS),
            "speed_kmh": round(rng.uniform(0, 110), 1),
            "fuel_level_pct": round(rng.uniform(5, 100), 1),
            "fuel_rate_lph": round(rng.uniform(5, 45), 1),
            "engine_temp_c": round(rng.gauss(90, 4), 1),
            "odometer_km": round(rng.uniform(1e4, 3e5), 1),
            "trip_id": f"TR-{rng.randint(0, 999999):06d}",
        })
    return docs


def run_case(db, w, batch_size, total_docs, rng):
    coll_name = "bench_telemetry"
    db.drop_collection(coll_name)
    coll = db.get_collection(coll_name, write_concern=WriteConcern(w=w))

    n_batches = total_docs // batch_size
    start_ts = datetime.now(timezone.utc)
    # Documents générés avant la mesure : on ne mesure que MongoDB
    batches = [fake_docs(batch_size, start_ts + timedelta(seconds=b), rng)
               for b in range(n_batches)]

    latencies_ms = []
    t_start = time.perf_counter()
    for batch in batches:
        t0 = time.perf_counter()
        coll.insert_many(batch, ordered=False)
        latencies_ms.append((time.perf_counter() - t0) * 1000)
    elapsed = time.perf_counter() - t_start

    inserted = n_batches * batch_size
    lat_sorted = sorted(latencies_ms)
    result = {
        "write_concern": str(w),
        "batch_size": batch_size,
        "docs": inserted,
        "elapsed_s": round(elapsed, 2),
        "throughput_docs_s": round(inserted / elapsed),
        "latency_ms_mean": round(statistics.mean(latencies_ms), 1),
        "latency_ms_median": round(statistics.median(latencies_ms), 1),
        "latency_ms_p95": round(lat_sorted[int(0.95 * (len(lat_sorted) - 1))], 1),
    }
    db.drop_collection(coll_name)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--docs", type=int, default=200_000, help="documents par combinaison")
    parser.add_argument("--batches", default="500,1000", help="tailles de lot, séparées par des virgules")
    parser.add_argument("--repeat", type=int, default=2, help="répétitions par combinaison")
    parser.add_argument("--out", default="report/data/bench_write.json")
    args = parser.parse_args()

    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    rng = random.Random(42)
    batch_sizes = [int(b) for b in args.batches.split(",")]

    results = []
    print(f"{'w':>9} {'lot':>5} {'docs':>8} {'débit/s':>9} {'moy ms':>8} {'méd ms':>8} {'p95 ms':>8}")
    for rep in range(1, args.repeat + 1):
        for batch_size in batch_sizes:
            for w in (1, "majority"):
                r = run_case(db, w, batch_size, args.docs, rng)
                r["repeat"] = rep
                results.append(r)
                print(f"{r['write_concern']:>9} {batch_size:>5} {r['docs']:>8} "
                      f"{r['throughput_docs_s']:>9} {r['latency_ms_mean']:>8} "
                      f"{r['latency_ms_median']:>8} {r['latency_ms_p95']:>8}", flush=True)

    # Moyenne des répétitions par combinaison
    summary = []
    for batch_size in batch_sizes:
        for w in ("1", "majority"):
            rs = [r for r in results if r["batch_size"] == batch_size and r["write_concern"] == w]
            summary.append({
                "write_concern": w,
                "batch_size": batch_size,
                "throughput_docs_s": round(statistics.mean(r["throughput_docs_s"] for r in rs)),
                "latency_ms_mean": round(statistics.mean(r["latency_ms_mean"] for r in rs), 1),
                "latency_ms_p95": round(statistics.mean(r["latency_ms_p95"] for r in rs), 1),
            })

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({
            "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "docs_per_case": args.docs,
            "note": "documents factices, générés avant la mesure ; replica set 3 noeuds sur une machine",
            "runs": results,
            "summary": summary,
        }, f, indent=2, ensure_ascii=False)

    print("\n=== Moyenne des répétitions ===")
    for s in summary:
        print(f"w={s['write_concern']:<9} lot={s['batch_size']:<5} "
              f"{s['throughput_docs_s']:>7} docs/s   moy {s['latency_ms_mean']} ms   p95 {s['latency_ms_p95']} ms")
    print(f"Résultats : {args.out}")
    client.close()


if __name__ == "__main__":
    main()
