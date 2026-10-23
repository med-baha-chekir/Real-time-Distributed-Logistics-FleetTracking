
import os
from dotenv import load_dotenv

# Charge les variables du fichier .env
load_dotenv()

# URI de connexion à MongoDB
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")

# Nom de la base de données
DB_NAME = os.getenv("DB_NAME", "fleet")

# Nombre de camions simulés pour la V1
TRUCK_COUNT = int(os.getenv("TRUCK_COUNT", "100"))

# Intervalle entre deux générations, en secondes
INTERVAL_SECONDS = float(os.getenv("INTERVAL_SECONDS", "5"))

# Taille maximale d'un lot d'insertion
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "500"))

# Durée totale en secondes ; 0 = exécution continue
DURATION_SECONDS = int(os.getenv("DURATION_SECONDS", "0"))

# Vitesse moyenne initiale en km/h
MIN_SPEED = 60.0
MAX_SPEED = 90.0

# Écart-type du bruit de vitesse en km/h
SPEED_NOISE = 3.0
