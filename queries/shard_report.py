"""Rapport d'une expérience de sharding (tâches S2 et S3), à lancer via mongos.

Pour chaque base fleet_<clé> chargée par infra/scripts/shard-experiment.sh :
  - répartition des documents et des données par shard ($collStats) ;
  - chunks par shard, chunks « jumbo » (config.chunks) ;
  - conformité du balancer (balancerCollectionStatus) ;
  - ciblage de 3 requêtes : combien de shards interrogés (explain) et temps (médiane de 3).

  docker run --rm --network fleet-shard-net -v <dépôt>:/work -w /work \
      -e MONGO_URI=mongodb://mongos:27017 fleet-generator \
      python -m queries.shard_report region hashed vehicle_ts

Résultats : report/data/shard_report.json (+ affichage)
"""

import argparse
import json
import os
import statistics
import time
from datetime import timedelta

from pymongo import MongoClient

from queries.ref_time import reference_time

MONGO_URI = os.getenv("MONGO_URI", "mongodb://mongos:27017")
MB = 1024 * 1024
KEYS = {
    "region": {"region": 1},
    "hashed": {"vehicle_id": "hashed"},
    "vehicle_ts": {"vehicle_id": 1, "ts": 1},
}


def distribution(db):
    per_shard = {}
    for s in db.telemetry.aggregate([{"$collStats": {"storageStats": {}}}]):
        st = s["storageStats"]
        per_shard[s["shard"]] = {"docs": st["count"], "data_mb": round(st["size"] / MB, 1)}
    total = sum(v["docs"] for v in per_shard.values()) or 1
    for v in per_shard.values():
        v["docs_pct"] = round(100 * v["docs"] / total, 1)
    return per_shard


def chunks(client, ns):
    cfg = client.config
    coll = cfg.collections.find_one({"_id": ns})
    flt = {"uuid": coll["uuid"]} if "uuid" in coll else {"ns": ns}
    per_shard, jumbo = {}, 0
    for c in cfg.chunks.find(flt, {"shard": 1, "jumbo": 1}):
        per_shard[c["shard"]] = per_shard.get(c["shard"], 0) + 1
        jumbo += 1 if c.get("jumbo") else 0
    return {"per_shard": per_shard, "total": sum(per_shard.values()), "jumbo": jumbo}


def query_set(ref):
    hour = {"ts": {"$gte": ref - timedelta(hours=1), "$lte": ref}}
    return {
        "region_tunis_1h": [  # statistiques d'UNE région
            {"$match": {"region": "Tunis", **hour}},
            {"$group": {"_id": None, "avg_speed": {"$avg": "$speed_kmh"}, "n": {"$sum": 1}}}],
        "vehicle_history": [  # historique d'UN camion
            {"$match": {"vehicle_id": "VH-000001"}},
            {"$sort": {"ts": -1}}, {"$limit": 100}],
        "all_regions_1h": [   # agrégation a, toutes les régions
            {"$match": hour},
            {"$group": {"_id": "$region", "avg_speed": {"$avg": "$speed_kmh"}}}],
    }


def targeting(db, pipeline, repeat):
    exp = db.command("explain", {"aggregate": "telemetry", "pipeline": pipeline, "cursor": {}},
                     verbosity="queryPlanner")
    shards = sorted(exp.get("shards", {}).keys())
    times = []
    for _ in range(repeat):
        t0 = time.perf_counter()
        rows = list(db.telemetry.aggregate(pipeline, allowDiskUse=True))
        times.append((time.perf_counter() - t0) * 1000)
    return {"shards": shards, "n_shards": len(shards), "ms": round(statistics.median(times), 1),
            "rows": len(rows)}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("keys", nargs="*", default=list(KEYS))
    p.add_argument("--repeat", type=int, default=3)
    p.add_argument("--out", default="report/data/shard_report.json")
    args = p.parse_args()

    client = MongoClient(MONGO_URI)
    n_shards = len(client.admin.command("listShards")["shards"])
    report = {}
    for key in args.keys:
        db = client[f"fleet_{key}"]
        ns = f"fleet_{key}.telemetry"
        ref = reference_time(db)
        status = client.admin.command("balancerCollectionStatus", ns)
        dist = distribution(db)
        true_docs = db.telemetry.count_documents({})   # via mongos : orphelins exclus
        r = {
            "shard_key": {k: v for k, v in KEYS[key].items()},
            "docs": true_docs,
            # Copies laissées sur l'ancien shard après une migration, effacées après
            # orphanCleanupDelaySecs (15 min) : $collStats les compte encore
            "orphans": sum(d["docs"] for d in dist.values()) - true_docs,
            "distribution": dist,
            "chunks": chunks(client, ns),
            "balancer_compliant": status.get("balancerCompliant"),
            "balancer_status": status.get("firstComplianceViolation"),
            "queries": {name: targeting(db, pipe, args.repeat)
                        for name, pipe in query_set(ref).items()},
        }
        if key == "region":
            # Régions présentes sur chaque shard (via les bornes des chunks)
            cfg = client.config
            uuid = cfg.collections.find_one({"_id": ns}).get("uuid")
            r["chunk_ranges"] = [
                {"shard": c["shard"], "min": str(c["min"].get("region")),
                 "max": str(c["max"].get("region")), "jumbo": bool(c.get("jumbo"))}
                for c in cfg.chunks.find({"uuid": uuid}).sort("min", 1)]
        report[key] = r

        print(f"\n=== Clé {key} : {r['shard_key']} — {r['docs']} documents"
              f" (orphelins en attente de nettoyage : {r['orphans']}) ===")
        for shard, d in sorted(r["distribution"].items()):
            print(f"  {shard}: {d['docs']:>8} docs ({d['docs_pct']:>5} %)  {d['data_mb']:>7} Mo  "
                  f"chunks={r['chunks']['per_shard'].get(shard, 0)}")
        print(f"  chunks={r['chunks']['total']}  jumbo={r['chunks']['jumbo']}  "
              f"balancer conforme={r['balancer_compliant']} {r['balancer_status'] or ''}")
        for name, q in r["queries"].items():
            print(f"  {name:<18} {q['n_shards']}/{n_shards} shard(s) {q['shards']}  "
                  f"{q['ms']:>8} ms  ({q['rows']} lignes)")
        if key == "region":
            for c in r["chunk_ranges"]:
                print(f"    chunk [{c['min']} ; {c['max']}[ -> {c['shard']}"
                      + ("  JUMBO" if c["jumbo"] else ""))

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nRésultats : {args.out}")
    client.close()


if __name__ == "__main__":
    main()
