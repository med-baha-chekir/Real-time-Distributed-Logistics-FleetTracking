import time

from pymongo.errors import PyMongoError

from config import (
    TRUCK_COUNT,
    INTERVAL_SECONDS,
    BATCH_SIZE,
    DURATION_SECONDS,
)
from vehicle import Vehicle
from metrics import Metrics


class Producer:
    def __init__(self, db):
        self.db = db
        self.telemetry = db["telemetry"]

        # Création des camions en mémoire
        self.vehicles = [
            Vehicle(i) for i in range(1, TRUCK_COUNT + 1)
        ]

        self.metrics = Metrics()

    def run(self):
        print(
            f"Démarrage : {len(self.vehicles)} camions",
            flush=True,
        )

        last_cycle = time.perf_counter()
        last_report = last_cycle

        while True:
            cycle_start = time.perf_counter()

            # Mesure le temps écoulé depuis le cycle précédent.
            # Au premier cycle, utilise l'intervalle configuré.
            dt_seconds = (
                INTERVAL_SECONDS
                if last_cycle is None
                else max(cycle_start - last_cycle, 0.001)
            )
            last_cycle = cycle_start

            # Génère une mesure par camion
            documents = [
                vehicle.step(dt_seconds)
                for vehicle in self.vehicles
            ]

            # Découpe les documents en lots
            for start in range(0, len(documents), BATCH_SIZE):
                batch = documents[start:start + BATCH_SIZE]

                try:
                    result = self.telemetry.insert_many(
                        batch,
                        ordered=False,
                    )

                    # inserted_ids contient les identifiants
                    # des documents insérés avec succès.
                    self.metrics.record_success(len(result.inserted_ids))

                except PyMongoError as exc:
                    # Certaines écritures peuvent avoir réussi
                    # même si l'opération globale a échoué.
                    # Ne pas compter tout le lot comme inséré.
                    self.metrics.record_error()
                    print(
                        f"Erreur MongoDB : {type(exc).__name__}: {exc}",
                        flush=True,
                    )

            # Affiche les métriques toutes les 5 secondes
            now = time.perf_counter()
            if now - last_report >= 5:
                self.metrics.report()
                last_report = now

            # Arrêt facultatif après la durée configurée
            elapsed = time.perf_counter() - self.metrics.start_time

            if DURATION_SECONDS > 0 and elapsed >= DURATION_SECONDS:
                break

            # Respecte l'intervalle sans attendre inutilement
            cycle_elapsed = time.perf_counter() - cycle_start
            time.sleep(max(0, INTERVAL_SECONDS - cycle_elapsed))

        self.metrics.report()
        print("Simulation terminée.", flush=True)
