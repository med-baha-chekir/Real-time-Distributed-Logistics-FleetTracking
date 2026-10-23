
from pymongo import MongoClient

from config import MONGO_URI, DB_NAME
from producer import Producer


def main():
    # Création du client MongoDB
    client = MongoClient(
        MONGO_URI,
        serverSelectionTimeoutMS=5000,
    )

    try:
        # Vérifie que MongoDB est accessible
        client.admin.command("ping")
        print("Connexion MongoDB réussie.")

        # Sélection de la base de données
        db = client[DB_NAME]

        # Création et lancement du producteur
        producer = Producer(db)
        producer.run()

    except Exception as exc:
        print(f"Erreur : {exc}")
        raise

    finally:
        # Ferme proprement la connexion à la fin
        client.close()


if __name__ == "__main__":
    main()
