"""Exécute les agrégations et requêtes géo de pipelines.py et affiche leurs résultats.

  python -m queries.run_queries                      # toutes les requêtes
  python -m queries.run_queries a_avg_speed_by_region geo_near_point
  python -m queries.run_queries --out report/data/query_results.json

Sert à documenter les requêtes (rapport) et de modèle pour le dashboard.
"""

import argparse
import json
import os
import time

from bson import json_util
from pymongo import MongoClient

from queries.pipelines import ALL
from queries.ref_time import reference_time

MONGO_URI = os.getenv(
    "MONGO_URI", "mongodb://mongo1:27017,mongo2:27017,mongo3:27017/?replicaSet=rs0"
)
DB_NAME = os.getenv("DB_NAME", "fleet")


def short(doc):
    """Version lisible d'un résultat (arrondis, sans GeoJSON complet)."""
    out = {}
    for k, v in doc.items():
        if k == "location":
            out[k] = v.get("coordinates")
        elif isinstance(v, float):
            out[k] = round(v, 1)
        elif hasattr(v, "isoformat"):
            out[k] = v.isoformat(timespec="seconds")
        else:
            out[k] = v
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("names", nargs="*", help="requêtes à exécuter (défaut : toutes)")
    p.add_argument("--limit", type=int, default=12, help="lignes affichées par requête")
    p.add_argument("--out", help="fichier JSON des résultats complets")
    args = p.parse_args()

    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    ref = reference_time(db)
    print(f"Base {DB_NAME} — heure de référence {ref.isoformat(timespec='seconds')}\n")

    results = {"reference_time": ref.isoformat(), "queries": {}}
    for name in args.names or ALL:
        coll, pipeline = ALL[name](ref)
        t0 = time.perf_counter()
        rows = list(db[coll].aggregate(pipeline, allowDiskUse=True))
        ms = (time.perf_counter() - t0) * 1000
        results["queries"][name] = {"collection": coll, "ms": round(ms, 1),
                                    "rows": len(rows), "result": rows}
        print(f"== {name} ({coll}) : {len(rows)} lignes en {ms:.0f} ms")
        for r in rows[:args.limit]:
            print("   ", short(r))
        if len(rows) > args.limit:
            print(f"    … {len(rows) - args.limit} autres lignes")
        print()

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(json_util.dumps(results, indent=1, ensure_ascii=False))
        print(f"Résultats complets : {args.out}")
    client.close()


if __name__ == "__main__":
    main()
