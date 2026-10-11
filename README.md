# Fleet Tracking — Phase 1 (Infrastructure)

Replica Set MongoDB à 3 nœuds avec Docker Compose + test de connexion Python.

## Structure

```
fleet-tracking/
├── docker-compose.yml
├── scripts/init-replica.sh      # rs.initiate() automatique
└── generator/
    ├── Dockerfile
    ├── requirements.txt
    └── test_connection.py
```

## Démarrage

```bash
docker compose up -d
docker compose logs mongo-init     # doit afficher "Primaire élu : ..."
```

## Test Python

```bash
docker compose run --rm app
```

Résultat attendu : nom du Replica Set, primaire, 3 membres, écriture `w=majority` OK.

## Vérifier le Replica Set

```bash
docker exec -it mongo1 mongosh --eval "rs.status()"
```

## Tests de panne (à noter dans le rapport)

```bash
docker stop mongo1       # arrêt du primaire : un autre nœud est élu
docker start mongo1      # retour : resynchronisation

docker stop mongo2 mongo3   # perte de 2 nœuds : plus d'écriture possible
docker start mongo2 mongo3
```

Pour chaque test, noter l'heure, la commande et le résultat.

## Arrêt

```bash
docker compose down        # garde les données
docker compose down -v     # supprime aussi les données
```

## Notes

- Cache WiredTiger limité à 0,5 Go par nœud (économie de RAM).
- Ports exposés : 27017, 27018, 27019 (mongo1, mongo2, mongo3).
- Les nœuds sont déclarés avec leurs noms Docker (`mongo1`...). Depuis ta machine hors Docker, le driver ne les résout pas : utilise le conteneur `app`, ou ajoute `127.0.0.1 mongo1 mongo2 mongo3` dans ton fichier hosts.

---

# Phase 2 — Modèle de données, générateur v1, ingestion

## Fichiers ajoutés (`generator/`)

| Fichier | Rôle |
|---|---|
| `config.py` | Paramètres (camions, lots, write concern), surchargeables par variables d'environnement |
| `routes.py` | 16 villes de Tunisie (lon, lat) et calcul de distance |
| `vehicle.py` | Classe `Vehicle` : trajets, vitesse, consommation, température |
| `producer.py` | `insert_many` par lots + mise à jour de `vehicle_state` (upsert), reprise pendant un failover |
| `metrics.py` | Débit (msg/s) et latence par lot |
| `main.py` | Lancement du générateur |
| `check.py` | Compte les documents et la taille des collections |
| `test_geojson.py` | Test unitaire : ordre `[lon, lat]`, types, plages de valeurs (sans MongoDB) |

## Lancer

```bash
# 1. Test sans base (vérifie les données)
docker compose run --rm app python test_geojson.py

# 2. Premier million de documents (mode backfill, rapide)
docker compose run --rm app python main.py --docs 1000000

# 3. Vérifier
docker compose run --rm app python check.py
```

Autres options :

```bash
python main.py --realtime --vehicles 2000      # un message / 5 s par camion
python main.py --docs 1000000 --batch 500      # autre taille de lot
WRITE_CONCERN=1 python main.py --docs 200000   # comparer w:1 et w:"majority"
```

## Modes

- **backfill** (défaut) : le temps simulé avance sans attendre et les données finissent à « maintenant ». C'est le plus rapide pour charger des millions de documents.
- **--realtime** : débit réel (2 000 camions = environ 400 msg/s). Utile pour la démo et le test de bascule.

## Choix volontaires

- Aucun index secondaire sur `telemetry` pour l'instant : la semaine 3 mesure `explain()` avant/après index.
- `vehicle_state` est mise à jour à chaque lot avec `bulk_write` + `upsert`.
- Pas encore d'anomalies ni de multiprocessing : ils arrivent avec le générateur v2 (semaine 3).

## À noter dans le rapport

Reporter le résumé affiché à la fin : débit (objectif ≥ 1 000 msg/s), latence moyenne par lot (objectif < 100 ms), et comparer `w:"majority"` avec `w:1`.

---

# Travail en équipe

Les règles (branches, commits, Pull Requests) sont dans [CONTRIBUTING.md](CONTRIBUTING.md).
Copier `.env.example` en `.env` avant de lancer le cluster à deux PC.
