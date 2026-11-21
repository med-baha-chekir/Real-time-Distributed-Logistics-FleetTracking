"""Mesure explain("executionStats") de toutes les requêtes de pipelines.py.

Chaque requête est exécutée --repeat fois (défaut 3) ; le temps retenu est la
médiane, pour limiter l'effet du cache (première exécution « à froid »).

  # sans index : les index secondaires de telemetry sont CACHÉS (hidden) pendant
  # la mesure puis réaffichés ; rien n'est supprimé
  python -m queries.explain_baseline --label before --hide-indexes
  # avec les index
  python -m queries.explain_baseline --label after

  (dans Docker : docker compose -f infra/docker-compose.rs.yml --profile tools run --rm tools ...)

Sorties :
  report/explain/<label>/<requete>.json   explain complet
  report/explain/<label>/summary.json     temps, docs examinés, clés examinées, étapes
"""

import argparse
import json
import os
import statistics
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
    parser.add_argument("--repeat", type=int, default=3, help="exécutions par requête (médiane)")
    parser.add_argument("--hide-indexes", action="store_true",
                        help="cache les index secondaires de telemetry pendant la mesure")
    args = parser.parse_args()

    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    ref = reference_time(db)

    hidden = []
    if args.hide_indexes:
        for name in db.telemetry.index_information():
            if name != "_id_":
                db.command("collMod", "telemetry", index={"name": name, "hidden": True})
                hidden.append(name)
        print(f"Index cachés pendant la mesure : {hidden}")
    try:
        run(db, ref, args, hidden)
    finally:
        for name in hidden:
            db.command("collMod", "telemetry", index={"name": name, "hidden": False})
        if hidden:
            print(f"Index réaffichés : {hidden}")
        client.close()


def run(db, ref, args, hidden):
    out_dir = os.path.join(args.out, args.label)
    os.makedirs(out_dir, exist_ok=True)

    counts = {c: db[c].estimated_document_count() for c in ("telemetry", "vehicle_state")}
    indexes = {"telemetry": sorted(n for n in db.telemetry.index_information() if n not in hidden),
               "vehicle_state": sorted(db.vehicle_state.index_information())}
    print(f"Référence temporelle : {ref.isoformat()}  |  documents : {counts}")
    print(f"Index : {indexes}\n")
    print(f"{'requête':<24} {'ms (méd.)':>9} {'docs exam.':>11} {'clés exam.':>11} "
          f"{'renvoyés':>9}  étapes   [{args.repeat} exécutions]")

    summary = {"label": args.label, "measured_at": datetime.now(timezone.utc).isoformat(),
               "reference_time": ref.isoformat(), "counts": counts, "indexes": indexes,
               "hidden_indexes": hidden, "repeat": args.repeat, "queries": {}}

    for name, build in ALL.items():
        coll, pipeline = build(ref)
        try:
            times = []
            for _ in range(max(1, args.repeat)):
                explain = db.command("explain",
                                     {"aggregate": coll, "pipeline": pipeline, "cursor": {}},
                                     verbosity="executionStats")
                times.append(summarize(explain)["executionTimeMillis"])
        except OperationFailure as exc:
            # ex. $geoNear sans index 2dsphere : l'échec est lui-même un résultat
            summary["queries"][name] = {"collection": coll, "error": exc.details.get("errmsg")}
            print(f"{name:<24} ÉCHEC : {exc.details.get('errmsg')}")
            continue

        with open(os.path.join(out_dir, f"{name}.json"), "w", encoding="utf-8") as f:
            f.write(json_util.dumps(explain, indent=2))

        s = summarize(explain)
        s["collection"] = coll
        s["times_ms"] = times
        s["executionTimeMillis"] = statistics.median(times)
        summary["queries"][name] = s
        print(f"{name:<24} {s['executionTimeMillis']!s:>9} {s['totalDocsExamined']!s:>11} "
              f"{s['totalKeysExamined']!s:>11} {s['nReturned']!s:>9}  {','.join(s['stages'])}  "
              f"{times}")

    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"\nRésultats : {out_dir}/")


if __name__ == "__main__":
    main()
