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

## Lancer le générateur

```bash
docker compose -f infra/docker-compose.rs.yml --profile app build generator     # après chaque modification du code
docker compose -f infra/docker-compose.rs.yml --profile app run --rm generator
# Surcharger un paramètre ponctuellement :
docker compose -f infra/docker-compose.rs.yml --profile app run --rm -e TRUCK_COUNT=2000 -e DURATION_SECONDS=600 generator
```

Les paramètres viennent de `.env` (voir `.env.example`). `MONGO_URI` est forcée par le compose.

## Validation de schéma (`init-db.js`)

`telemetry`, `vehicle_state` et `vehicles` refusent les documents mal formés (`validationAction: "error"`) :

- `ts` / `last_ts` de type **Date** (une chaîne est refusée) ;
- `location` en GeoJSON `Point` avec **longitude ∈ [7, 12] et latitude ∈ [30, 38]** : une inversion lat/lng est refusée ;
- champs de mesure numériques, vitesse ∈ [0, 160], carburant ∈ [0, 100] % ;
- `vehicle_id` au format `VH-000123`.

`region` sera rendue obligatoire dans `telemetry` dès que le générateur v2 la produit (TODO dans le script).

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
| `../queries/explain_baseline.py` | `explain("executionStats")` de toutes les requêtes | `report/explain/<label>/` |

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

## Cluster shardé (sprint 3)

Environnement séparé : 3 config servers, 2 shards de 3 nœuds, 1 `mongos` (`127.0.0.1:27100`),
10 conteneurs, ~7,5 Go au maximum. Arrêter `rs0` pendant les tests libère de la RAM.

```bash
docker compose -f infra/docker-compose.shard.yml up -d
bash infra/scripts/init-shard.sh                       # idempotent
docker exec -it mongos mongosh                         # sh.status()
docker compose -f infra/docker-compose.shard.yml stop  # arrêt, données conservées
```

## Arrêt et remise à zéro

```bash
docker compose -f infra/docker-compose.rs.yml down       # arrête, garde les données
docker compose -f infra/docker-compose.rs.yml down -v    # supprime aussi les volumes (données perdues)
```
