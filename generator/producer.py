"""Boucle de génération et d'écriture dans MongoDB (un processus = un worker).

À chaque cycle :
  1. chaque camion du worker produit un document telemetry ;
  2. les documents sont insérés par lots : insert_many(ordered=False) ;
  3. vehicle_state reçoit la dernière position de chaque camion du lot
     (bulk_write d'UpdateOne(..., upsert=True)).

Modes :
  - realtime : un cycle toutes les INTERVAL_SECONDS, ts = maintenant ;
  - backfill : l'horloge simulée avance sans attendre et se termine à
    « maintenant » (fenêtres « dernière heure » non vides).

Pendant une bascule du primaire, les lots sont rejoués (5 tentatives) : les
documents gardent leur _id, donc un document déjà inséré n'est pas dupliqué
(erreur 11000 ignorée).
"""

import time
from datetime import timedelta

from pymongo import MongoClient, ReplaceOne, UpdateOne
from pymongo.errors import AutoReconnect, BulkWriteError, PyMongoError
from pymongo.write_concern import WriteConcern

from .metrics import Metrics
from .route_network import load_routes
from .vehicle import Vehicle

MAX_RETRIES = 5
DUPLICATE_KEY = 11000


def parse_write_concern(value):
    return WriteConcern(w=int(value) if str(value).isdigit() else value)


class Producer:
    def __init__(self, db, vehicle_numbers, settings, weather=None, label=""):
        self.settings = s = settings
        wc = parse_write_concern(s["write_concern"])
        self.telemetry = db.get_collection("telemetry", write_concern=wc)
        self.state = db.get_collection("vehicle_state", write_concern=wc)
        self.vehicles_coll = db.get_collection("vehicles", write_concern=wc)

        routes = load_routes()
        self.vehicles = [Vehicle(n, routes, seed=s["seed"], weather=weather)
                         for n in vehicle_numbers]
        self.metrics = Metrics(label)

    # --------------------------------------------------------------- écriture
    def _with_retry(self, fn):
        """Exécute fn ; rejoue pendant une bascule du primaire."""
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                return fn()
            except AutoReconnect as exc:      # inclut NotPrimaryError, timeouts réseau
                if attempt == MAX_RETRIES:
                    raise
                self.metrics.record_retry()
                print(f"{self.metrics.label}Bascule en cours ({type(exc).__name__}), "
                      f"nouvelle tentative {attempt}/{MAX_RETRIES - 1}", flush=True)
                time.sleep(attempt)

    def _insert_batch(self, batch):
        t0 = time.perf_counter()
        inserted = 0
        try:
            res = self._with_retry(lambda: self.telemetry.insert_many(batch, ordered=False))
            inserted = len(res.inserted_ids)
        except BulkWriteError as exc:
            # Documents insérés lors d'une tentative précédente : clé _id en double
            dups = sum(1 for e in exc.details.get("writeErrors", [])
                       if e.get("code") == DUPLICATE_KEY)
            inserted = exc.details.get("nInserted", 0) + dups
            if dups != len(exc.details.get("writeErrors", [])):
                self.metrics.record_error()
                first = exc.details["writeErrors"][0]
                print(f"{self.metrics.label}Documents refusés : {first.get('errmsg', '')[:160]}",
                      flush=True)
        except PyMongoError as exc:
            self.metrics.record_error()
            print(f"{self.metrics.label}Erreur MongoDB : {type(exc).__name__}: {exc}", flush=True)
            return

        insert_ms = (time.perf_counter() - t0) * 1000

        # Dernière position de chaque camion du lot
        last = {d["vehicle_id"]: d for d in batch}
        ops = [UpdateOne({"_id": vid}, {"$set": {
                   "last_ts": d["ts"], "location": d["location"], "region": d["region"],
                   "speed_kmh": d["speed_kmh"], "engine_temp_c": d["engine_temp_c"],
                   "fuel_level_pct": d["fuel_level_pct"], "route_id": d["route_id"]}},
                   upsert=True)
               for vid, d in last.items()]
        t1 = time.perf_counter()
        try:
            self._with_retry(lambda: self.state.bulk_write(ops, ordered=False))
        except PyMongoError as exc:
            self.metrics.record_error()
            print(f"{self.metrics.label}Erreur vehicle_state : {type(exc).__name__}: {exc}",
                  flush=True)

        self.metrics.record_batch(inserted, insert_ms, (time.perf_counter() - t1) * 1000)

    def _write_cycle(self, documents):
        size = self.settings["batch_size"]
        for start in range(0, len(documents), size):
            self._insert_batch(documents[start:start + size])

    def seed_vehicles(self, ts):
        """Remplit la collection vehicles (relançable sans doublon)."""
        ops = [ReplaceOne({"_id": v.vehicle_id}, v.reference_doc(ts), upsert=True)
               for v in self.vehicles]
        if ops:
            self._with_retry(lambda: self.vehicles_coll.bulk_write(ops, ordered=False))

    # ------------------------------------------------------------------ modes
    def run_backfill(self, start_ts, steps):
        interval = self.settings["interval"]
        report_every = max(1, steps // 10)
        for k in range(steps):
            ts = start_ts + timedelta(seconds=k * interval)
            self._write_cycle([v.step(interval, ts) for v in self.vehicles])
            if (k + 1) % report_every == 0 or k + 1 == steps:
                print(f"{self.metrics.label}cycle {k + 1}/{steps} (ts={ts:%H:%M:%S}) ", end="")
                self.metrics.report()
        return self.metrics.summary()

    def run_realtime(self, now_fn):
        interval = self.settings["interval"]
        duration = self.settings["duration"]
        last_report = time.perf_counter()
        while True:
            cycle_start = time.perf_counter()
            ts = now_fn()
            self._write_cycle([v.step(interval, ts) for v in self.vehicles])

            if time.perf_counter() - last_report >= 5:
                self.metrics.report()
                last_report = time.perf_counter()
            if duration > 0 and self.metrics.elapsed() >= duration:
                break
            time.sleep(max(0.0, interval - (time.perf_counter() - cycle_start)))
        self.metrics.report()
        return self.metrics.summary()


def run_worker(worker_id, workers, settings, weather, start_iso=None, steps=None):
    """Point d'entrée d'un processus : camions n tels que (n - 1) % workers == worker_id."""
    from datetime import datetime, timezone

    numbers = [n for n in range(1, settings["trucks"] + 1) if (n - 1) % workers == worker_id]
    label = f"[w{worker_id}] " if workers > 1 else ""
    client = MongoClient(settings["mongo_uri"], serverSelectionTimeoutMS=10000)
    try:
        db = client[settings["db_name"]]
        producer = Producer(db, numbers, settings, weather=weather, label=label)
        now_fn = lambda: datetime.now(timezone.utc)
        if settings["mode"] == "backfill":
            start_ts = datetime.fromisoformat(start_iso)
            producer.seed_vehicles(start_ts)
            return producer.run_backfill(start_ts, steps)
        producer.seed_vehicles(now_fn())
        return producer.run_realtime(now_fn)
    finally:
        client.close()
