"""Mesure explain("executionStats") de toutes les requêtes de pipelines.py.

À lancer deux fois :
  1. --label before : AVANT de créer les index sur telemetry (sprint 2, sur 1 M de docs v2) ;
  2. --label after  : APRÈS création des index (sprint 3).

  docker compose -f infra/docker-compose.rs.yml --profile tools run --rm tools \
      python -m queries.explain_baseline --label before

Sorties :
  report/explain/<label>/<requete>.json   explain complet
  report/explain/<label>/summary.json     temps, docs examinés, clés examinées, étapes
"""

import argparse
import json
import os
from datetime import datetime, timezone

from bson import json_util
from pymongo import MongoClient
from pymongo.errors import OperationFailure

from queries.pipelines import ALL
from queries.ref_time import reference_time

MONGO_URI = os.getenv(
    "MONGO_URI", "mongodb://mongo1:27017,mongo2:27017,mongo3:27017/?replicaSet=rs0"
)
DB_NAME = os.getenv("DB_NAME", "fleet")


def find_key(obj, key):
    """Toutes les valeurs de `key` trouvées récursivement dans obj."""
    found = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key:
                found.append(v)
            found.extend(find_key(v, key))
    elif isinstance(obj, list):
        for item in obj:
            found.extend(find_key(item, key))
    return found


def summarize(explain):
    """Indicateurs principaux d'un explain d'agrégation (classique ou SBE)."""
    stats = find_key(explain, "executionStats")
    s = stats[0] if stats else {}
    winning = find_key(explain, "winningPlan")
    stages = sorted(set(find_key(winning, "stage"))) if winning else []
    return {
        "executionTimeMillis": s.get("executionTimeMillis"),
        "totalDocsExamined": s.get("totalDocsExamined"),
        "totalKeysExamined": s.get("totalKeysExamined"),
        "nReturned": s.get("nReturned"),
        "stages": stages,
        "uses_index": any(st in ("IXSCAN", "GEO_NEAR_2DSPHERE", "EXPRESS_IXSCAN")
                          for st in stages),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True, help="before | after | autre")
    parser.add_argument("--out", default="report/explain")
    args = parser.parse_args()

    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    ref = reference_time(db)
    out_dir = os.path.join(args.out, args.label)
    os.makedirs(out_dir, exist_ok=True)

    counts = {c: db[c].estimated_document_count() for c in ("telemetry", "vehicle_state")}
    indexes = {c: sorted(db[c].index_information()) for c in ("telemetry", "vehicle_state")}
    print(f"Référence temporelle : {ref.isoformat()}  |  documents : {counts}")
    print(f"Index : {indexes}\n")
    print(f"{'requête':<24} {'ms':>7} {'docs exam.':>11} {'clés exam.':>11} {'renvoyés':>9}  étapes")

    summary = {"label": args.label, "measured_at": datetime.now(timezone.utc).isoformat(),
               "reference_time": ref.isoformat(), "counts": counts, "indexes": indexes,
               "queries": {}}

    for name, build in ALL.items():
        coll, pipeline = build(ref)
        try:
            explain = db.command("explain",
                                 {"aggregate": coll, "pipeline": pipeline, "cursor": {}},
                                 verbosity="executionStats")
        except OperationFailure as exc:
            # ex. $geoNear sans index 2dsphere : l'échec est lui-même un résultat
            summary["queries"][name] = {"collection": coll, "error": exc.details.get("errmsg")}
            print(f"{name:<24} ÉCHEC : {exc.details.get('errmsg')}")
            continue

        with open(os.path.join(out_dir, f"{name}.json"), "w", encoding="utf-8") as f:
            f.write(json_util.dumps(explain, indent=2))

        s = summarize(explain)
        s["collection"] = coll
        summary["queries"][name] = s
        print(f"{name:<24} {s['executionTimeMillis']!s:>7} {s['totalDocsExamined']!s:>11} "
              f"{s['totalKeysExamined']!s:>11} {s['nReturned']!s:>9}  {','.join(s['stages'])}")

    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"\nRésultats : {out_dir}/")
    client.close()


if __name__ == "__main__":
    main()
