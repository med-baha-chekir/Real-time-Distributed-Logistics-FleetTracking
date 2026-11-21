"""Lancement du générateur de télémétrie (v2).

Exemples (depuis la racine du dépôt) :
  python -m generator.main                                   # realtime, paramètres du .env
  python -m generator.main --mode backfill --docs 1000000 --trucks 5000 --workers 4
  python -m generator.main --mode realtime --trucks 2000 --duration 600
  WRITE_CONCERN=1 python -m generator.main --mode backfill --docs 200000

Dans Docker :
  docker compose -f infra/docker-compose.rs.yml --profile app run --rm generator \
      python -m generator.main --mode backfill --docs 1000000 --trucks 5000 --workers 4
"""

import argparse
import math
import multiprocessing as mp
import time
from datetime import datetime, timedelta, timezone

from pymongo import MongoClient

from . import config as cfg
from .producer import run_worker
from .route_network import load_routes
from .weather_context import load_weather


def parse_args():
    p = argparse.ArgumentParser(description="Générateur de télémétrie de camions")
    p.add_argument("--mode", choices=["realtime", "backfill"], default=cfg.MODE)
    p.add_argument("--docs", type=int, default=cfg.DOCS, help="backfill : documents à produire")
    p.add_argument("--trucks", type=int, default=cfg.TRUCK_COUNT)
    p.add_argument("--workers", type=int, default=cfg.WORKERS)
    p.add_argument("--batch", type=int, default=cfg.BATCH_SIZE)
    p.add_argument("--interval", type=float, default=cfg.INTERVAL_SECONDS)
    p.add_argument("--duration", type=int, default=cfg.DURATION_SECONDS,
                   help="realtime : durée en s (0 = continu)")
    p.add_argument("--write-concern", default=cfg.WRITE_CONCERN)
    p.add_argument("--seed", type=int, default=cfg.SEED)
    p.add_argument("--no-weather", action="store_true", help="météo neutre, sans appel API")
    return p.parse_args()


def main():
    args = parse_args()
    settings = {
        "mongo_uri": cfg.MONGO_URI, "db_name": cfg.DB_NAME, "mode": args.mode,
        "trucks": args.trucks, "batch_size": args.batch, "interval": args.interval,
        "duration": args.duration, "write_concern": args.write_concern, "seed": args.seed,
    }
    workers = max(1, min(args.workers, args.trucks))

    # Vérifie la connexion avant de lancer les processus
    client = MongoClient(cfg.MONGO_URI, serverSelectionTimeoutMS=5000)
    client.admin.command("ping")
    client.close()
    print("Connexion MongoDB réussie.")

    routes = load_routes()
    src = routes[0].source
    print(f"Itinéraires : {len(routes)} ({'routes réelles OSRM' if src == 'osrm' else 'simplifiés'}), "
          f"{sum(len(r.fuel_stops_km) for r in routes)} stations-service")

    weather = load_weather(enabled=cfg.WEATHER and not args.no_weather)
    rainy = [r for r, w in weather.items() if w["rain"] > 0.5]
    print(f"Météo : {len(weather)} régions"
          + (f", pluie à {', '.join(rainy)}" if rainy else "") if weather else "Météo : neutre")

    start_iso, steps = None, None
    if args.mode == "backfill":
        steps = math.ceil(args.docs / args.trucks)
        end = datetime.now(timezone.utc)
        start = end - timedelta(seconds=(steps - 1) * args.interval)
        start_iso = start.isoformat()
        print(f"Backfill : {args.trucks} camions x {steps} cycles = {args.trucks * steps} docs, "
              f"de {start:%Y-%m-%d %H:%M:%S} à {end:%H:%M:%S} UTC")
    print(f"Démarrage : {args.trucks} camions, {workers} processus, lots de {args.batch}, "
          f"w={args.write_concern}, mode={args.mode}", flush=True)

    t0 = time.perf_counter()
    jobs = [(i, workers, settings, weather, start_iso, steps) for i in range(workers)]
    if workers == 1:
        results = [run_worker(*jobs[0])]
    else:
        with mp.get_context("spawn").Pool(workers) as pool:
            results = pool.starmap(run_worker, jobs)
    wall = time.perf_counter() - t0

    docs = sum(r["docs"] for r in results)
    errors = sum(r["errors"] for r in results)
    retries = sum(r["retries"] for r in results)
    lat = [r["latency_ms_mean"] for r in results if r["latency_ms_mean"] is not None]
    st = [r["state_latency_ms_mean"] for r in results if r["state_latency_ms_mean"] is not None]
    print("\n=== Résumé ===")
    print(f"Documents insérés : {docs} | Erreurs : {errors} | Reprises : {retries}")
    print(f"Durée : {wall:.1f} s | Débit global : {docs / wall:.0f} msg/s")
    if lat:
        print(f"Latence moyenne d'un insert_many : {sum(lat) / len(lat):.1f} ms"
              + (f" | mise à jour vehicle_state : {sum(st) / len(st):.1f} ms" if st else ""))
    print("Simulation terminée.", flush=True)


if __name__ == "__main__":
    main()
