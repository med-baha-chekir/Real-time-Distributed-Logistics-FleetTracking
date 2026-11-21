"""Sonde de disponibilité en écriture pendant un test de panne.

Écrit un petit document toutes les --interval secondes avec w:"majority",
note l'heure de chaque écriture confirmée ou échouée, puis calcule :
  - la plus longue interruption entre deux écritures confirmées
    (= indisponibilité vue par le client, proche du temps d'élection) ;
  - le nombre d'écritures échouées ;
  - les écritures confirmées mais absentes de la base (doit être 0 avec w:majority).

Lancement (dans le réseau Docker) :
  docker compose -f infra/docker-compose.rs.yml --profile tools run --rm tools \
      python infra/scripts/failover_probe.py --duration 60 --label s1-run1
"""

import argparse
import json
import os
import time
from datetime import datetime, timezone

from pymongo import MongoClient
from pymongo.errors import PyMongoError
from pymongo.write_concern import WriteConcern

MONGO_URI = os.getenv(
    "MONGO_URI", "mongodb://mongo1:27017,mongo2:27017,mongo3:27017/?replicaSet=rs0"
)
DB_NAME = os.getenv("DB_NAME", "fleet")


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def primary_of(client):
    """Nom du primaire courant, ou None."""
    try:
        status = client.admin.command("replSetGetStatus")
        for m in status["members"]:
            if m["stateStr"] == "PRIMARY":
                return m["name"]
    except PyMongoError:
        pass
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, default=60, help="durée en secondes")
    parser.add_argument("--interval", type=float, default=0.1, help="pause entre écritures (s)")
    parser.add_argument("--label", default="probe", help="identifiant du test")
    parser.add_argument("--out", default="report/data/failover", help="dossier des résultats JSON")
    parser.add_argument("--verify-timeout", type=float, default=90,
                        help="attente max d'un primaire pour la vérification finale (s)")
    args = parser.parse_args()

    client = MongoClient(
        MONGO_URI,
        serverSelectionTimeoutMS=2000,
        socketTimeoutMS=5000,
        connectTimeoutMS=2000,
    )
    coll = client[DB_NAME].get_collection(
        "failover_probe", write_concern=WriteConcern(w="majority", wtimeout=5000)
    )

    run_id = f"{args.label}-{int(time.time())}"
    acked = []        # (seq, t) écritures confirmées
    failures = []     # (seq, t, erreur)
    transitions = []  # changements d'état OK <-> ÉCHEC
    state_ok = None
    seq = 0

    print(f"[{now_iso()}] Sonde {run_id} : {args.duration:.0f} s, une écriture / {args.interval} s")
    print(f"[{now_iso()}] Primaire initial : {primary_of(client)}")

    start = time.perf_counter()
    while time.perf_counter() - start < args.duration:
        seq += 1
        t0 = time.perf_counter()
        try:
            coll.insert_one({"run": run_id, "seq": seq, "sent_at": datetime.now(timezone.utc)})
            t = time.perf_counter() - start
            acked.append((seq, t))
            ok = True
        except PyMongoError as exc:
            t = time.perf_counter() - start
            failures.append((seq, t, type(exc).__name__))
            ok = False

        if ok != state_ok:
            label = "écritures OK" if ok else f"ÉCHEC ({failures[-1][2]})"
            transitions.append({"t": round(t, 3), "at": now_iso(), "state": label})
            print(f"[{now_iso()}] t={t:7.2f} s  -> {label}", flush=True)
            state_ok = ok

        time.sleep(max(0.0, args.interval - (time.perf_counter() - t0)))

    # Plus longue interruption entre deux écritures confirmées
    times = [t for _, t in acked]
    gaps = [(b - a, a, b) for a, b in zip(times, times[1:])]
    max_gap, gap_from, gap_to = max(gaps, default=(0.0, 0.0, 0.0))

    # Vérification : chaque écriture confirmée doit être en base (lecture sur le primaire)
    deadline = time.time() + args.verify_timeout
    found = None
    while time.time() < deadline:
        try:
            found = set(coll.distinct("seq", {"run": run_id}))
            break
        except PyMongoError:
            time.sleep(1)
    lost = None if found is None else sorted(s for s, _ in acked if s not in found)

    summary = {
        "run": run_id,
        "finished_at": now_iso(),
        "duration_s": args.duration,
        "interval_s": args.interval,
        "writes_attempted": seq,
        "writes_acked": len(acked),
        "writes_failed": len(failures),
        "max_gap_s": round(max_gap, 3),
        "max_gap_window_s": [round(gap_from, 3), round(gap_to, 3)],
        "acked_but_lost": None if lost is None else len(lost),
        "final_primary": primary_of(client),
        "transitions": transitions,
    }

    os.makedirs(args.out, exist_ok=True)
    path = os.path.join(args.out, f"{args.label}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print("\n=== Résultat ===")
    print(f"Écritures tentées / confirmées / échouées : {seq} / {len(acked)} / {len(failures)}")
    print(f"Plus longue interruption : {max_gap:.2f} s (entre t={gap_from:.2f} s et t={gap_to:.2f} s)")
    print(f"Écritures confirmées perdues : {summary['acked_but_lost']}")
    print(f"Primaire final : {summary['final_primary']}")
    print(f"Résultats : {path}")
    client.close()


if __name__ == "__main__":
    main()
