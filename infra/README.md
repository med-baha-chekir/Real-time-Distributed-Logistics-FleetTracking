# Infrastructure — Replica Set MongoDB `rs0`

Replica Set à 3 nœuds (`mongo1`, `mongo2`, `mongo3`, image `mongo:7`) sous Docker Compose,
plus le générateur de télémétrie lancé dans le même réseau Docker.

## Décision réseau (sprint 2)

**Tout tourne sur le PC de A** (32 Go) : cluster, générateur, mesures et démo.

- Les ports MongoDB sont publiés **uniquement sur `127.0.0.1`** : le cluster n'est pas accessible depuis le réseau.
- Le générateur (et plus tard le dashboard) tourne dans un conteneur du réseau `fleet-net`, où les noms `mongo1..3` sont résolus.
- Le PC de B développe sur son propre Replica Set local, pousse sur Git, et A lance le code sur le cluster de référence.
- Le cluster réparti sur les deux PC (Tailscale) reste un **bonus** de fin de projet.

## Prérequis

| Élément | Valeur |
|---|---|
| Docker Desktop | backend WSL2 |
| Mémoire WSL2 | `%UserProfile%\.wslconfig` → `[wsl2]` `memory=22GB` `processors=6` `swap=4GB`, puis `wsl --shutdown` |
| Disque libre | ≥ 15 Go (10 M de documents × 3 réplicas + index) |
| Shell | Git Bash pour les scripts `.sh` |

## Démarrage (depuis la racine du dépôt)

```bash
cp .env.example .env                                   # une seule fois
docker compose -f infra/docker-compose.rs.yml up -d    # 3 nœuds mongod
bash infra/scripts/init-rs.sh                          # rs.initiate + attente du primaire
bash infra/scripts/init-db.sh                          # collections, validateurs, index vehicle_state
bash infra/scripts/check-status.sh                     # état du cluster
```

Tous les scripts sont **idempotents** : on peut les relancer sans risque.

## Fichiers

| Fichier | Rôle |
|---|---|
| `docker-compose.rs.yml` | 3 nœuds (`--wiredTigerCacheSizeGB 0.5`, `mem_limit: 1g`, healthcheck) + service `generator` (profil `app`) |
| `scripts/init-rs.js` / `init-rs.sh` | `rs.initiate()` puis attente d'un PRIMARY |
| `scripts/init-db.js` / `init-db.sh` | Collections `vehicles`, `telemetry`, `vehicle_state` avec validation `$jsonSchema` |
| `scripts/check-status.sh` | Nœuds, état, retard de réplication, taille des collections |
| `rs-status.txt` | Dernière sortie de `check-status.sh` (pour le rapport) |

## Connexion

| Depuis | URI |
|---|---|
| Un conteneur du réseau `fleet-net` | `mongodb://mongo1:27017,mongo2:27017,mongo3:27017/?replicaSet=rs0` |
| mongosh / Compass sur le PC hôte (un seul nœud, sans failover) | `mongodb://127.0.0.1:27017/?directConnection=true` (27018, 27019 pour mongo2, mongo3) |
| Shell dans le cluster | `docker exec -it mongo1 mongosh "mongodb://mongo1:27017,mongo2:27017,mongo3:27017/fleet?replicaSet=rs0"` |

Depuis l'hôte, l'URI `replicaSet=rs0` ne fonctionne pas : les membres s'annoncent sous les noms
Docker `mongoX:27017`, que Windows ne résout pas. D'où le choix de lancer les clients dans Docker.

## Lancer le générateur (v2)

```bash
docker compose -f infra/docker-compose.rs.yml --profile app build generator     # après chaque modification du code

# Temps réel (démo, tests de panne) : 2 000 camions, 1 message / 5 s chacun (~400 msg/s)
docker compose -f infra/docker-compose.rs.yml --profile app run --rm generator     python -m generator.main --mode realtime --trucks 2000 --duration 600

# Backfill (chargement rapide) : 1 M de documents se terminant à « maintenant »
docker compose -f infra/docker-compose.rs.yml --profile app run --rm generator     python -m generator.main --mode backfill --docs 1000000 --trucks 5000 --workers 4

# Comparer les write concerns
docker compose -f infra/docker-compose.rs.yml --profile app run --rm generator     python -m generator.main --mode backfill --docs 200000 --trucks 5000 --write-concern 1
```

Options : `--mode`, `--docs`, `--trucks`, `--workers`, `--batch`, `--interval`, `--duration`,
`--write-concern`, `--seed`, `--no-weather` (valeurs par défaut lues dans `.env`, voir `.env.example`).
`MONGO_URI` est forcée par le compose. Autre base : `-e DB_NAME=fleet_test` (et
`DB_NAME=fleet_test bash infra/scripts/init-db.sh` pour y créer les validateurs).

## Dashboard

```bash
docker compose -f infra/docker-compose.rs.yml --profile app up -d --build dashboard   # http://localhost:8501
DB_NAME=fleet_demo docker compose -f infra/docker-compose.rs.yml --profile app up -d dashboard  # autre base
```

Détails, sections et scénario de démonstration : [`dashboard/README.md`](../dashboard/README.md).

## Validation de schéma (`init-db.js`)

`telemetry`, `vehicle_state` et `vehicles` refusent les documents mal formés (`validationAction: "error"`) :

- `ts` / `last_ts` de type **Date** (une chaîne est refusée) ;
- `location` en GeoJSON `Point` avec **longitude ∈ [7, 12] et latitude ∈ [30, 38]** : une inversion lat/lng est refusée ;
- champs de mesure numériques, vitesse ∈ [0, 160], carburant ∈ [0, 100] % ;
- `vehicle_id` au format `VH-000123`.

`region` est obligatoire dans `telemetry` et doit être l'une des 12 régions (depuis le générateur v2).

**Index** : seul `vehicle_state.location` (2dsphere) est créé. Aucun index secondaire sur `telemetry`
avant le sprint 3, pour mesurer `explain("executionStats")` avant / après.

## Outils de mesure (service `tools`)

Le service `tools` réutilise l'image du générateur et monte le dépôt dans `/work` :

```bash
docker compose -f infra/docker-compose.rs.yml --profile tools build tools
docker compose -f infra/docker-compose.rs.yml --profile tools run --rm tools python infra/scripts/bench_write.py --docs 100000
docker compose -f infra/docker-compose.rs.yml --profile tools run --rm tools python -m queries.explain_baseline --label before
```

| Script | Mesure | Résultats |
|---|---|---|
| `scripts/failover_probe.py` | interruption des écritures, écritures perdues | `report/data/failover/` |
| `scripts/failover-scenarios.sh` | les 4 scénarios de panne, automatisés | `report/data/failover/`, synthèse `report/failover.md` |
| `scripts/bench_write.py` | débit et latence, w:1 vs w:majority, lots 500 / 1000 | `report/data/bench_write.json` |
| `scripts/bench_generator.sh` | débit du **vrai générateur** : 2 000 / 5 000 camions × w:1 / majority (base `fleet_bench`) | `report/data/bench_generator.txt` |
| `scripts/failover-under-load.sh` | scénario de panne pendant que le générateur tourne | `report/data/failover/<scenario>-runload.*` |
| `../queries/explain_baseline.py` | `explain("executionStats")` de toutes les requêtes, médiane de 3 (`--hide-indexes` : sans index) | `report/explain/<label>/` |
| `../queries/compare_explain.py` | tableau comparatif de plusieurs mesures explain | `report/data/explain_comparison.md` |
| `../queries/run_queries.py` | exécute les agrégations et requêtes géo, affiche les résultats | `report/data/query_results.json` |
| `scripts/init-indexes.sh` | crée les index de `telemetry` (plan ; `INDEX_SET=extra` : + index ajoutés), durée et taille | `report/data/indexes_*.txt` |
| `scripts/bench_index_cost.sh` | coût des index sur le débit d'ingestion (aucun / plan / extra) | `report/data/bench_index_cost.txt` |
| `../queries/timeseries_compare.py` | copie `telemetry` en time series, compare taille et temps | `report/data/timeseries_compare.*` |

## Tests de panne

Automatisés (sonde d'écriture en parallèle, ~1 min par scénario) :

```bash
bash infra/scripts/failover-scenarios.sh s1-stop 1   # arrêt propre du primaire
bash infra/scripts/failover-scenarios.sh s1-kill 1   # crash du primaire
bash infra/scripts/failover-scenarios.sh s2 1        # arrêt d'un secondaire
bash infra/scripts/failover-scenarios.sh s3 1        # perte de 2 nœuds
bash infra/scripts/failover-scenarios.sh s4 1        # retour d'un nœud, resynchronisation
```

À la main (pour la démo) :

```bash
bash infra/scripts/check-status.sh          # repérer le PRIMARY
docker stop <primaire>                      # élection d'un nouveau primaire
docker start <primaire>                     # retour et resynchronisation
```

Résultats et analyse : `report/failover.md`.

## Cluster shardé (sprint 4)

Environnement séparé : 3 config servers, 2 shards de 3 nœuds, 1 `mongos` (`127.0.0.1:27100`),
10 conteneurs, ~7,5 Go au maximum. Arrêter `rs0` pendant les tests libère de la RAM.

```bash
docker compose -f infra/docker-compose.shard.yml up -d
bash infra/scripts/init-shard.sh                       # idempotent
docker exec -it mongos mongosh                         # sh.status()
docker compose -f infra/docker-compose.shard.yml stop  # arrêt, données conservées
```

Expérience des shard keys (rs0 arrêté pour libérer la RAM) :

```bash
docker compose -f infra/docker-compose.rs.yml stop
docker compose -f infra/docker-compose.shard.yml up -d && bash infra/scripts/init-shard.sh
CHUNK_MB=4 bash infra/scripts/shard-experiment.sh 1000000 region hashed vehicle_ts   # ~10 min
# attendre ~15 min le nettoyage des orphelins, puis le rapport final :
docker run --rm --network fleet-shard-net -v "$(pwd -W):/work" -w /work \
    -e MONGO_URI=mongodb://mongos:27017 fleet-generator python -m queries.shard_report
```

Bases créées : `fleet_region`, `fleet_hashed`, `fleet_vehicle_ts` (1 M de documents chacune).
Résultats et analyse : `report/sharding.md`.

## Arrêt et remise à zéro

```bash
docker compose -f infra/docker-compose.rs.yml down       # arrête, garde les données
docker compose -f infra/docker-compose.rs.yml down -v    # supprime aussi les volumes (données perdues)
```
