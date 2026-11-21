"""Paramètres du générateur, surchargeables par variables d'environnement (.env)."""

import os

from dotenv import load_dotenv

load_dotenv()

# --- MongoDB -----------------------------------------------------------------
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
DB_NAME = os.getenv("DB_NAME", "fleet")
# "majority" (aucune écriture confirmée perdue) ou "1" (plus rapide)
WRITE_CONCERN = os.getenv("WRITE_CONCERN", "majority")

# --- Simulation --------------------------------------------------------------
TRUCK_COUNT = int(os.getenv("TRUCK_COUNT", "100"))
# Intervalle entre deux messages d'un camion (secondes simulées)
INTERVAL_SECONDS = float(os.getenv("INTERVAL_SECONDS", "5"))
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "500"))
# "realtime" : un cycle toutes les INTERVAL_SECONDS, ts = maintenant
# "backfill" : horloge simulée sans attente, se termine à maintenant
MODE = os.getenv("MODE", "realtime")
# Backfill : nombre total de documents à produire
DOCS = int(os.getenv("DOCS", "1000000"))
# Realtime : durée totale en secondes ; 0 = exécution continue
DURATION_SECONDS = int(os.getenv("DURATION_SECONDS", "0"))
# Graine aléatoire : même graine = même jeu de données
SEED = int(os.getenv("SEED", "42"))
# Nombre de processus de génération (multiprocessing)
WORKERS = int(os.getenv("WORKERS", "1"))
# Météo réelle (Open-Meteo) au démarrage : "on" / "off"
WEATHER = os.getenv("WEATHER", "on").lower() == "on"

# --- Modèle physique -----------------------------------------------------------
# Vitesse maximale d'un camion (km/h)
TRUCK_MAX_SPEED = 100.0
# Accélération / freinage maximal (km/h par seconde)
ACCEL_KMH_PER_S = 2.0
BRAKE_KMH_PER_S = 4.0
# Écart-type du bruit de vitesse (km/h)
SPEED_NOISE = 2.0
# Réservoir (litres)
TANK_LITERS = 400.0
# Seuil de ravitaillement (%)
REFUEL_THRESHOLD_PCT = 15.0
# Seuil de surchauffe utilisé par le pipeline d (°C)
OVERHEAT_THRESHOLD_C = 105.0
# Part des camions sujets aux anomalies
OVERHEAT_PRONE_RATIO = 0.01
FUEL_LEAK_RATIO = 0.01

# Fichier des itinéraires pré-calculés (build_routes.py)
ROUTES_FILE = os.getenv(
    "ROUTES_FILE",
    os.path.join(os.path.dirname(__file__), "data", "routes_osrm.json"),
)
