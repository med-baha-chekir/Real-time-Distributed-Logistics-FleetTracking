# Avancement du projet — Real-time Distributed Logistics & Fleet Tracking

> État au **21/11/2026** — sprints 2 et 3 fusionnés (PR #10, #11, #12) ; **sprint 4 (sharding,
> time series)** fait sur la branche `feature/sprint4-sharding` (à fusionner dans `develop`).
> Binôme : **Baha (A)** — infrastructure et mesures · **Abdelkader (B)** — générateur, dashboard.
> Référence : plan d'exécution détaillé (PDF, 6 semaines à partir du 11/10/2026).

## Vue d'ensemble

| Brique | État | Responsable |
|---|---|---|
| ① Générateur de télémétrie | ✅ v2 terminé : routes réelles OSRM, régions, anomalies, météo, testé | B (+ A) |
| ② Ingestion par lots | ✅ v2 : `vehicle_state`, `vehicles`, backfill, write concern, multiprocessing, reprise après bascule | B (+ A) |
| ③ Replica Set + tolérance aux pannes | ✅ terminé et mesuré, y compris sous charge | A |
| ④ Agrégations + requêtes géo | ✅ écrites, mesurées et documentées sur 5 M docs (`report/requetes.md`) | A (+ B pour l'oral) |
| ⑤ Index (explain avant / après) | ✅ 7 index mesurés : f > ×1 000, d ×155, a/b/e ×2,9, zone ×4,6 ; coût −31 % à l'écriture (`report/index.md`) | A |
| ⑥ Sharding (bonus) | ✅ 3 shard keys comparées sur 1 M docs : répartition, ciblage, chunk jumbo démontré (`report/sharding.md`) | A |
| ⑥ bis Time series (bonus) | ✅ 8,3 fois moins de place, agrégations 2–3 fois plus rapides (`report/timeseries.md`) | A |
| ⑦ Dashboard | ❌ pas commencé | B |
| ⑧ Rapport | 🟡 brouillons Markdown : partie technique, pannes, mesures, index, requêtes, sharding, time series ; LaTeX à faire | A + B |

**Retard** : la partie A a rattrapé le plan (semaines 1 à 4 faites, y compris les bonus sharding
et time series). Le **chemin critique est le dashboard (B)**, obligatoire et pas commencé :
toutes les requêtes dont il a besoin sont prêtes et mesurées (`queries/pipelines.py`). Reste
ensuite le rapport final (sprint 5) et la démo (sprint 6).

---

# Partie 1 — Ce qui est fait

## 1.1 Organisation et dépôt Git

| Élément | Détail |
|---|---|
| Dépôt GitHub | `main` (stable), `develop` (intégration), une branche par fonctionnalité, PR avant fusion |
| PR fusionnées | #1 à #9 (dernière : #9 `feature/sprint2-infra`, le 21/11) |
| Conventions | `.gitignore` (secrets, données générées, essais), `.gitattributes` (`.sh` / `.js` en LF, sinon bash plante sous Windows) |
| Configuration | `.env.example` : URI, base, paramètres du générateur (`.env` jamais versionné) |
| Contrat de données | [`docs/data-model.md`](data-model.md) : format exact des 3 collections, 12 régions, règles |

## 1.2 Infrastructure — Replica Set `rs0` (A)

**Fichiers** : [`infra/docker-compose.rs.yml`](../infra/docker-compose.rs.yml), [`infra/scripts/`](../infra/scripts/), [`infra/README.md`](../infra/README.md)

| Élément | Détail |
|---|---|
| Cluster | 3 nœuds `mongo:7` (`mongo1..3`), cache WiredTiger 0,5 Go, 1 Go max par conteneur, healthcheck, volumes persistants |
| Réseau | **Décision : tout tourne sur le PC de A.** Ports publiés sur `127.0.0.1` seulement ; clients dans le réseau Docker `fleet-net` |
| Service `generator` | Lance le générateur dans le réseau Docker (profil `app`) |
| Service `tools` | Lance les scripts de mesure avec le dépôt monté dans `/work` (profil `tools`) |
| `init-rs.sh` | `rs.initiate()` + attente de l'élection d'un primaire (idempotent) |
| `init-db.sh` / `init-db.js` | Crée `vehicles`, `telemetry`, `vehicle_state` avec **validation `$jsonSchema`** + index 2dsphere sur `vehicle_state` (idempotent) |
| `check-status.sh` | Nœuds, état, retard de réplication, taille des collections |

**Validation de schéma** (testée) — refuse : `ts` en chaîne, lat/lng inversées (bornes de la
Tunisie), mesures en texte, `vehicle_id` mal formé. Accepte les documents du générateur.

**Volontairement absent** : aucun index secondaire sur `telemetry` (mesure avant / après au sprint 3).

## 1.3 Tolérance aux pannes — mesurée (A)

**Fichiers** : [`failover_probe.py`](../infra/scripts/failover_probe.py), [`failover-scenarios.sh`](../infra/scripts/failover-scenarios.sh), résultats [`report/failover.md`](../report/failover.md), données brutes `report/data/failover/`

Sonde : 1 écriture `w:"majority"` toutes les 100 ms pendant chaque scénario.

| Scénario | Interruption des écritures | Écritures confirmées perdues |
|---|---|---|
| Arrêt propre du primaire (`docker stop`, ×3) | **0,58 s** | 0 |
| Crash du primaire (`docker kill`, ×3) | **11,5 s** (délai de détection de 10 s) | 0 |
| Arrêt d'un secondaire | aucune | 0 |
| Perte de 2 nœuds sur 3 | écritures bloquées toute la panne (≈ 31 s) | 0 |
| Retour d'un nœud | resynchronisation en **2 à 3 s** | 0 |

## 1.4 Benchmark d'ingestion (A)

**Fichiers** : [`bench_write.py`](../infra/scripts/bench_write.py), résultats [`report/mesures.md`](../report/mesures.md)

| Write concern | Lot | Débit | Latence moyenne / p95 |
|---|---|---|---|
| `w:1` | 500 | ≈ 51 800 docs/s | 9,7 / 11,2 ms |
| `w:"majority"` | 500 | ≈ 31 900 docs/s | 15,7 / 24,2 ms |
| `w:1` | 1 000 | ≈ 54 900 docs/s | 18,3 / 22,9 ms |
| `w:"majority"` | 1 000 | ≈ 38 600 docs/s | 25,9 / 45,2 ms |

`w:"majority"` coûte 30 à 38 % de débit. Documents factices : c'est un **plafond**, à refaire avec
le vrai générateur.

## 1.5 Requêtes et outil de mesure explain (A)

**Fichiers** : [`queries/`](../queries/)

| Fichier | Contenu |
|---|---|
| `pipelines.py` | Agrégations **a** (vitesse / région), **b** (consommation / camion), **c** (camions / région), **d** (surchauffe), **e** (histogramme des vitesses), **f** (historique d'un camion), **géo** : rayon 10 km, polygone, vitesse dans une zone. Fenêtres temporelles ajoutées à b, e et 12.3 |
| `ref_time.py` | Heure de référence = dernier `ts` en base (sinon « dernière heure » est vide sur des données d'hier) |
| `explain_baseline.py` | `explain("executionStats")` de toutes les requêtes → `report/explain/<label>/` (temps, docs examinés, clés examinées, COLLSCAN / IXSCAN) |

Testé sur 8 000 documents v1 : tout en COLLSCAN (normal sans index). Le test a révélé **0 alerte de
surchauffe** et **42 % des messages dans la zone de Tunis** → défauts du générateur v1.

## 1.6 Cluster shardé (A, bonus)

**Fichiers** : [`docker-compose.shard.yml`](../infra/docker-compose.shard.yml), [`init-shard.sh`](../infra/scripts/init-shard.sh)

3 config servers + 2 shards (3 nœuds chacun) + 1 `mongos` (`127.0.0.1:27100`), 10 conteneurs,
~7,5 Go max. Initialisation idempotente testée ; test de fumée avec `{vehicle_id: "hashed"}` sur
20 000 documents : **49 % / 51 %**.

## 1.7 Générateur v2 (B, terminé avec A)

**Fichiers** : [`generator/`](../generator/) — package Python lancé par `python -m generator.main`.

| Fichier | Rôle |
|---|---|
| `routes.py` | 12 villes (lon, lat) + **13 itinéraires** (R13 Kairouan → Kasserine ajouté : sans lui la région Kasserine était vide) |
| `build_routes.py` | Pré-calcul **une fois** (avec Internet) : tracés OSRM + stations-service Overpass → `data/routes_osrm.json` |
| `data/routes_osrm.json` | 13 tracés réels (600 à 3 600 points chacun, vitesse OSRM par tronçon), 31 stations (615 Ko, versionné) |
| `route_network.py` | Classe `Route` : position, vitesse, région selon la distance parcourue ; repli sur les lignes droites si le fichier manque |
| `geo.py` | Haversine, région = ville la plus proche |
| `weather_context.py` | Météo réelle Open-Meteo par région au démarrage (pluie → −15 % de vitesse) ; météo neutre si hors ligne |
| `vehicle.py` | Camion : départ réparti, accélération/freinage, feux en ville, livraison 5–20 min aux extrémités (point réparti sur les 3 derniers km), ravitaillement, consommation selon vitesse et charge, température moteur, anomalies |
| `producer.py` | Lots `insert_many(ordered=False)`, upsert `vehicle_state`, remplissage `vehicles`, modes realtime / backfill, **reprise automatique pendant une bascule** (5 tentatives, sans doublon) |
| `metrics.py` | Débit, erreurs, reprises, latence `insert_many` et latence `vehicle_state` séparées |
| `main.py` | Options `--mode --docs --trucks --workers --batch --interval --duration --write-concern --seed --no-weather`, multiprocessing |
| `providers/` | Modules API d'Abdelkader (OSRM, Open-Meteo, Overpass) : imports corrigés, `User-Agent` ajouté (Overpass renvoyait 406), miroirs Overpass |
| `requirements.txt` / `requirements-dev.txt` | Exécution (pymongo, dotenv, requests) / développement (pytest, folium, pandas, matplotlib) |
| `../pytest.ini` | `pytest` depuis la racine du dépôt |
| `../validate_trajectories.py` | 200 camions × 2 h simulées : carte, figure, statistiques |

**Tâches G1 à G13 : faites** (détail en 2.1).

### Vérifications effectuées (21/11)

| Vérification | Résultat |
|---|---|
| Tests unitaires | **42 réussis**, 2 ignorés (appels API réels, activables avec `RUN_NETWORK_TESTS=1`) ; passent sans Internet |
| Trajectoires (`validate_trajectories.py`) | Camions sur les vraies routes ; **12 régions / 12** ; vitesses : 17 % arrêt, 7 % 20–40, 16 % 40–60, 30 % 60–80, 30 % 80–100 km/h ; max 99 km/h ; consommation 30 L/h ; 2 camions sur 200 en surchauffe (≈ 1 %) |
| Temps réel, 2 000 camions (Docker, Replica Set) | **≈ 400–500 msg/s, 0 erreur** ; `insert_many` 18 ms/lot (objectif < 100 ms) ; `vehicle_state` 82 ms/lot |
| Backfill 200 000 docs, 5 000 camions, w:majority | **1 processus : 44 s (4 500 msg/s) ; 4 processus : 23 s (8 700 msg/s)**, 0 erreur |
| Crash du primaire pendant la génération (`docker kill`) | **0 erreur, 0 document perdu**, 1 reprise automatique |
| Contenu de la base de test | `vehicle_state` = `vehicles` = 5 000 ; 0 document sans `region` ; 0 `ts` non Date ; 12 régions |
| Requêtes du plan sur les données v2 | a : 12 régions (48 à 66 km/h) ; c : 12 régions ; **d : 4 camions en surchauffe** (v1 : 0) ; e : 5 tranches de vitesse ; rayon 10 km : 228 camions ; polygone : 121 ; vitesse dans la zone : 43 km/h |

### Limites connues

- **Overpass injoignable** depuis notre réseau (délai dépassé sur les 3 serveurs, même hors Docker) :
  les 31 stations sont **estimées** (une tous les 45 km, `"fuel_source": "estimated"` dans le JSON).
  Quand Overpass répondra : `python -m generator.build_routes --fuel-only`.
- Le serveur OSRM public est un serveur de démonstration : relancer `build_routes.py` seulement si
  les itinéraires changent ; la simulation n'appelle jamais OSRM.
- Open-Meteo répond parfois partiellement (5 régions sur 12 lors d'un essai) : les régions sans
  réponse ont une météo neutre.
- En backfill, 1 M de documents avec 5 000 camions = 200 cycles = **17 min simulées** seulement.
  Pour que la fenêtre « 24 h » du pipeline d ait du sens, utiliser moins de camions ou plus de
  documents (2 000 camions → 42 min ; 5 M docs / 5 000 camions → 83 min).
- La base de test `fleet_test` utilisée pendant le développement a été supprimée le 21/11.

## 1.8 Rapport

| Fichier | Contenu |
|---|---|
| [`report/partie-technique.md`](../report/partie-technique.md) | Architecture, Replica Set, deux types de panne, validation, plan d'index, choix des shard keys |
| [`report/failover.md`](../report/failover.md) | Tests de panne détaillés et analysés, dont la panne sous charge et la bascule spontanée |
| [`report/mesures.md`](../report/mesures.md) | Toutes les mesures de la section 15 du plan (débit, latence, disque, explain before, bascule) |
| [`report/index.md`](../report/index.md) | Index : avant / après, index partiels et couvrants, coût sur l'ingestion (sprint 3) |
| [`report/requetes.md`](../report/requetes.md) | Les 6 agrégations et 3 requêtes géo : question, pipeline, résultat, temps, index (sprint 3) |
| [`report/sharding.md`](../report/sharding.md) | Comparaison des 3 shard keys : chargement, répartition, ciblage, chunk jumbo (sprint 4) |
| [`report/timeseries.md`](../report/timeseries.md) | Time series vs collection standard : taille, temps, analyse (sprint 4) |

## 1.9 Ingestion et mesures sur vraies données (A, 21/11)

**Fichiers** : [`report/mesures.md`](../report/mesures.md), [`report/failover.md`](../report/failover.md),
`report/data/` (`ingestion_5M.log`, `bench_generator.txt`, `status_5M.txt`, `explain_before.txt`),
`report/explain/before/`, scripts [`bench_generator.sh`](../infra/scripts/bench_generator.sh) et
[`failover-under-load.sh`](../infra/scripts/failover-under-load.sh).

**Jeu de données de référence (base `fleet`)** : **5 000 000 documents**, 2 000 camions, 12 régions,
**3 h 28** de données (15:55 → 19:23 UTC le 21/11), `SEED=42`. Seul index sur `telemetry` : `_id`.
Choix de 5 M (et non 1 M) : avec 1 M de docs et 5 000 camions, les données ne couvraient que
17 min et la fenêtre « dernière heure » aurait retenu 100 % des documents, ce qui rend la
comparaison avant / après index sans intérêt. Avec 3 h 28, la dernière heure = 29 % des documents.

| Mesure | Résultat |
|---|---|
| Ingestion de 5 M docs (w:majority, 4 processus) | **17,8 min, 4 676 msg/s, 0 erreur** ; `insert_many` 111 ms/lot en fin d'ingestion |
| Vrai générateur, base vide (200 000 docs) | **w:1 ≈ 13 200 msg/s ; w:majority ≈ 10 600 msg/s** (−20 %) |
| Taille sur disque `telemetry` | 1 496 Mo de données → **449 Mo sur disque** (compression ×3,3) ; 313 octets/doc ; index `_id` 140 Mo |
| Explain « before » (5 M docs, sans index) | requêtes a, b, d, e, f, géo-zone : **3,1 à 5,3 s**, **5 000 000 docs examinés** (COLLSCAN) ; requêtes sur `vehicle_state` : 2 à 66 ms |
| Panne sous charge (`docker kill` du primaire, générateur à 2 000 camions) | interruption **20,2 s** (11,5 s à vide), **0 écriture confirmée perdue**, générateur : 0 erreur, 1 reprise |
| Bascule spontanée pendant l'ingestion | élection déclenchée par la surcharge (heartbeats en retard > 10 s) ; **0 erreur** grâce à `retryWrites` |

**Constats pour le rapport** :
- Le débit baisse quand la collection dépasse le cache WiredTiger (0,5 Go/nœud) : 8 700 msg/s sur
  200 000 docs → 4 676 msg/s sur 5 M.
- L'index 2dsphere de `vehicle_state` pèse **125 Mo pour 2 000 documents** (5 M de déplacements
  successifs) : à analyser, piste `compact`.
- Une surcharge peut provoquer une bascule non voulue : argument pour bien dimensionner les nœuds.

---|---|
| [`report/partie-technique.md`](../report/partie-technique.md) | Architecture, Replica Set, deux types de panne, validation, plan d'index, choix des shard keys |
| [`report/failover.md`](../report/failover.md) | Tests de panne détaillés et analysés |
| [`report/mesures.md`](../report/mesures.md) | Tableau des mesures de la section 15 du plan |

---

## 1.10 Index et documentation des requêtes (A, sprint 3, 21/11)

**Fichiers** : [`report/index.md`](../report/index.md), [`report/requetes.md`](../report/requetes.md),
[`init-indexes.js`/`.sh`](../infra/scripts/init-indexes.js), [`bench_index_cost.sh`](../infra/scripts/bench_index_cost.sh),
[`queries/compare_explain.py`](../queries/compare_explain.py), [`queries/run_queries.py`](../queries/run_queries.py),
`queries/tests/` (7 tests), `report/explain/{before,after,after-extra}/`, `report/data/` (`indexes_*.txt`,
`explain_*.txt`, `explain_comparison.md`, `bench_index_cost.txt`, `query_results.json`).

**Méthode** : médiane de 3 exécutions par requête ; mesure « sans index » refaite en **cachant**
les index (`hidden`) au lieu de les supprimer.

| Requête (5 M docs) | Sans index | Index du plan (4) | + index ajoutés (3) | Gain final |
|---|---|---|---|---|
| f — historique d'un camion | 2 968 ms | **0 ms** | 1 ms | **> ×1 000** |
| d — alertes de surchauffe | 3 574 ms | 8 766 ms (**÷2,5**) | **23 ms** (index partiel) | **×155** |
| géo — vitesse dans une zone | 4 525 ms | 20 386 ms (**÷4,5**) | **987 ms** (`{ts, location}`) | **×4,6** |
| a / b / e — dernière heure | 4 400–4 700 ms | ≈ 2 400 ms | **1 600–1 730 ms** (index couvrant) | **×2,6–2,9** |
| c, géo rayon, géo polygone (`vehicle_state`) | 1–5 ms | ≈ | ≈ | déjà rapides |

| Coût | Valeur |
|---|---|
| Création des 4 index du plan sur 5 M docs | 72 s, 220 Mo |
| Total des index de `telemetry` (8 avec `_id`) | 604 Mo (données : 450 Mo) |
| Débit d'ingestion (500 000 docs, w:majority) | 7 945 msg/s → 5 941 (**−25 %**, plan) → 5 457 (**−31 %**, 7 index) |

**Enseignements** : un index très sélectif est spectaculaire (f) ; au-delà de ~30 % de la
collection il apporte peu (a, b, e) ; un index mal adapté peut **ralentir** une requête (d, zone).
Les index **partiels** et **couvrants**, choisis après `explain`, sont les plus rentables.

**Requêtes documentées** (`report/requetes.md`) : pour chacune, question métier, pipeline,
résultat réel, temps et index utilisé. Les résultats retrouvent les anomalies du générateur
(22 camions en surchauffe = 1,1 % ; camions « fuite » en tête de la consommation).

---

## 1.11 Sharding et time series (A, sprint 4, 21/11)

**Fichiers** : [`report/sharding.md`](../report/sharding.md), [`report/timeseries.md`](../report/timeseries.md),
[`shard-experiment.sh`](../infra/scripts/shard-experiment.sh), [`queries/shard_report.py`](../queries/shard_report.py),
[`queries/timeseries_compare.py`](../queries/timeseries_compare.py), `queries/tests/test_sprint4.py` (4 tests),
`report/data/` (`shard_experiment.txt`, `shard_report.{txt,json}`, `shard_jumbo_demo.txt`,
`timeseries_compare.{txt,json}`).

### Sharding (S1 à S3)

2 shards (Replica Sets de 3 nœuds), 3 config servers, 1 mongos ; **1 M de documents par clé**
(générateur v2, même graine) ; chunk size réduite à 4 Mo pour que le balancer agisse.

| | `region` | `vehicle_id` haché | `{vehicle_id, ts}` |
|---|---|---|---|
| Débit de chargement | 6 698 msg/s | 6 189 msg/s | 4 929 msg/s |
| Répartition finale (shard1 / shard2) | 50,1 / 49,9 % | 50,5 / 49,5 % | 50,8 / 49,2 % |
| « Une région » (Tunis, 1 h) | **1 shard**, 239 ms | 2 shards, 337 ms | 2 shards, 367 ms |
| « Un camion » (100 derniers) | 2 shards, 194 ms | **1 shard, 11 ms** | **1 shard, 2 ms** |
| Capacité à grandir | ❌ chunk de Tunis indivisible et intransportable (jumbo, démontré) | ✅ | ✅ |

Recommandation : `{ vehicle_id: "hashed" }`. Constat de méthode : juste après le chargement,
6 à 7 % de documents **orphelins** (copies laissées par les migrations, effacées après 15 min)
faussaient la répartition ; mesure finale faite après nettoyage.

### Time series (S4)

| | Standard (`telemetry`) | Time series (`telemetry_ts`) |
|---|---|---|
| Disque (données + index) | 450 + 604 Mo | **105 + 23 Mo (÷8,3)** |
| a — vitesse par région (1 h) | 1 816 ms (index couvrant) ; 5 718 ms sans index | **681 ms** |
| e — distribution des vitesses | 1 824 ms ; 4 921 ms sans index | **887 ms** |
| d — alertes de surchauffe | **26 ms** (index partiel) | 234 ms |
| f — historique d'un camion | **3 ms** | 109 ms |

5 M de mesures copiées en 256 s (`$out` vers time series), 18 284 buckets.

### État du cluster après le sprint 4

- `rs0` redémarré ; base `fleet` : `telemetry` (5 M, 8 index), **`telemetry_ts`** (5 M, time
  series), `vehicle_state`, `vehicles`. `check-status.sh` affiche les buckets des time series.
- Cluster shardé **arrêté**, données conservées (`fleet_region`, `fleet_hashed`,
  `fleet_vehicle_ts`, 1 M de documents chacune) pour la démo.

---

# Partie 2 — Ce qui reste à faire

Légende priorité : 🔴 bloquant · 🟠 obligatoire · 🟢 bonus.

## 2.1 Générateur v2 — ✅ TERMINÉ (21/11)

| # | Tâche | Réalisation |
|---|---|---|
| G1 ✅ | Brancher OSRM | `build_routes.py` → `data/routes_osrm.json` (13 tracés réels) ; simulation hors ligne |
| G2 ✅ | `region` | Ville la plus proche, pré-calculée par segment ; 12 régions couvertes |
| G3 ✅ | `vehicle_state` | Upsert de la dernière position de chaque camion à chaque lot |
| G4 ✅ | `vehicles` | 1 fiche par camion (modèle, capacité, région d'attache), relançable |
| G5 ✅ | Backfill | `--mode backfill --docs N` : horloge simulée qui finit à maintenant |
| G6 ✅ | Vitesses réalistes | Vitesse OSRM du tronçon, plafond camion 100 km/h, charge, accélération, feux, livraisons |
| G7 ✅ | Anomalies | 1 % surchauffe (épisodes > 105 °C), 1 % fuite de carburant (×1,6) |
| G8 ✅ | Départs répartis | Itinéraire, sens et position aléatoires ; nouveau `trip_id` à chaque livraison |
| G9 ✅ | Write concern / graine | `--write-concern`, `--seed` ; insertions partielles comptées ; doublons de reprise ignorés |
| G10 ✅ | Nettoyage | Package Python, imports relatifs, `requests` ajouté, tests API simulés (mock), `pytest.ini` |
| G11 ✅ | Météo | Open-Meteo au démarrage : pluie → vitesse −15 %, température → moteur |
| G12 🟡 | Stations-service | Code fait ; **stations estimées** car Overpass injoignable (relancer `--fuel-only`) |
| G13 ✅ | Validation | `validate_trajectories.py`, intégration Docker, test de bascule sous charge |

Reste côté générateur (facultatif) :
- G12 bis : relancer `python -m generator.build_routes --fuel-only` quand Overpass répond.
- Relire le code avec Abdelkader pour qu'il puisse le présenter à l'oral (c'est sa partie du plan).

## 2.2 Ingestion et mesures sur vraies données (A) — ✅ TERMINÉ (21/11)

| # | Tâche | Réalisation |
|---|---|---|
| A1 ✅ | Fusionner le générateur v2 | PR #10 fusionnée dans `develop` |
| A2 ✅ | `region` obligatoire | `required` + liste des 12 régions dans `init-db.js` ; document sans région ou région inconnue refusé (testé) |
| A3 ✅ | Base propre | `fleet.telemetry`, `vehicle_state`, `vehicles` vidées (8 000 docs v1) ; `fleet_test` supprimée ; validateurs recréés |
| A4 ✅ | Ingestion | **5 M de documents** (objectif révisé du plan : 5 à 10 M), 0 erreur |
| A5 ✅ | Benchmark du vrai générateur | `bench_generator.sh` : 2 000 / 5 000 camions × w:1 / majority |
| A6 ✅ | Explain « before » | `report/explain/before/` — **aucun index créé sur `telemetry` depuis** |
| A7 ✅ | Taille sur disque | `report/data/status_5M.txt` |
| A8 ✅ | Panne sous charge | `failover-under-load.sh s1-kill` + analyse de la bascule spontanée |

Reste facultatif :
- refaire les autres scénarios de panne sous charge (`failover-under-load.sh s2|s3|s4`) ;
- monter à 10 M de documents si le temps le permet (refaire alors l'explain « before »).

⚠️ **Ne pas relancer le générateur sur la base `fleet`** avant la mesure « after » du sprint 3 :
le jeu de 5 M de documents doit rester identique pour que la comparaison avant / après soit valable
(tests et démos : `-e DB_NAME=fleet_bench`).

## 2.3 Index (A) — ✅ TERMINÉ (21/11)

| # | Tâche | Réalisation |
|---|---|---|
| I1 ✅ | Script d'index | `init-indexes.sh` : 4 index du plan (72 s, 220 Mo) + 3 index ajoutés après mesure (`INDEX_SET=extra`) : partiel, composé géo, couvrant |
| I2 ✅ | Explain « after » | Mesures before / after / after-extra (médiane de 3) ; tableau `report/data/explain_comparison.md` ; analyse `report/index.md` |
| I3 ✅ | Coût sur l'ingestion | `bench_index_cost.sh` : −25 % (plan), −31 % (7 index) |

## 2.4 Agrégations et requêtes géo — ✅ TERMINÉ (21/11)

| # | Tâche | Réalisation |
|---|---|---|
| Q1 ✅ | Documenter les agrégations | `report/requetes.md` : a à f, question, pipeline, résultat sur 5 M docs, temps, index |
| Q2 ✅ | Documenter les requêtes géo | rayon (109 camions), polygone (76), vitesse dans une zone (24,4 km/h) ; règles `[lon, lat]` et `$geoNear` |
| Q3 🟢 | Agrégation supplémentaire | à faire si le temps le permet (ex. distance parcourue par camion) |

À faire avec Abdelkader : relire `report/requetes.md` pour qu'il puisse présenter les requêtes à
l'oral (le plan les lui attribuait).

## 2.5 Sharding et time series (A) — ✅ TERMINÉ (21/11)

| # | Tâche | Réalisation |
|---|---|---|
| S1 ✅ | Script de chargement | `shard-experiment.sh` : base par clé, collection shardée, chargement par le générateur via mongos, attente de l'équilibrage |
| S2 ✅ | Comparer 3 shard keys | Répartition, chunks, orphelins, plages de `region` ; démonstration du chunk jumbo (`split` et `moveChunk` refusés) |
| S3 ✅ | Ciblage et temps des requêtes | « une région », « un camion », « toutes les régions » : shards interrogés et temps |
| S4 ✅ | Time series | `timeseries_compare.py` : taille ÷8,3, agrégations ×2–3, requêtes ciblées plus lentes |

Facultatif : refaire l'expérience avec 3 shards ou plus (montrerait mieux la limite des 12
chunks de `region`) ; brancher le générateur sur une time series.

## 2.6 Dashboard (B) — sprints 4–5

**Technologie** : Streamlit + Plotly + PyDeck/Folium, dans Docker (service `dashboard` déjà prévu, commenté dans le compose).

| # | Tâche | Source |
|---|---|---|
| D1 🟠 | Carte des camions, rafraîchie toutes les 5–10 s | `vehicle_state` (pas `telemetry`) |
| D2 🟠 | Indicateurs : camions actifs, vitesse moyenne, consommation moyenne, alertes | pipelines a, b, d |
| D3 🟠 | Vitesse moyenne par région (barres) | pipeline a |
| D4 🟠 | Histogramme des vitesses | pipeline e |
| D5 🟠 | Liste des camions en alerte | pipeline d |
| D6 🟠 | Recherche géographique (rayon autour d'un point) | requête 12.1 |
| D7 🟠 | Résistance aux pannes : la page ne plante pas pendant un failover (message « reconnexion… ») | pour la démo |

Réutiliser `queries/pipelines.py` et `queries/ref_time.py` (déjà écrits).

## 2.7 Rapport et livrables (A + B) — sprint 5

| # | Tâche | Responsable |
|---|---|---|
| R1 🟠 | Rapport LaTeX 15–25 pages : architecture, choix, mesures, limites | A + B |
| R2 🟠 | Intégrer `partie-technique.md`, `failover.md`, `mesures.md` | A |
| R3 🟠 | Résultats, figures, captures du dashboard, carte des trajectoires | B |
| R4 🟠 | README racine (le README de `develop` est vide) : présentation, démarrage rapide, liens | A |
| R5 🟠 | Fusion `develop` → `main` (main est resté au 23/10) | A |
| R6 🟢 | Cluster réparti sur les 2 PC (Tailscale) | A + B, si le temps le permet |

## 2.8 Démonstration (A + B) — sprint 6

Scénario à répéter jusqu'à ce qu'il tourne sans accroc :

1. Lancer le générateur, montrer le débit en direct.
2. `check-status.sh` : 1 PRIMARY, 2 SECONDARY, réplication à jour.
3. **`docker kill` du primaire** → la carte se fige ~11 s puis repart, aucune donnée perdue.
4. Requête géo sur une zone, camions affichés sur la carte.
5. Agrégation « vitesse par région » + gain grâce à l'index (before / after).
6. Limites et pistes : Kafka, change streams, autres shard keys, déploiement multi-machines.

---

# Partie 3 — Ordre de travail proposé

```
FAIT         Générateur v2, Replica Set, pannes (aussi sous charge), benchmarks, 5 M docs,
             index (avant / après, partiels, couvrants), requêtes documentées,
             sharding (3 shard keys), time series
MAINTENANT   B : dashboard D1 → D7 (CHEMIN CRITIQUE) ; relire requetes.md, sharding.md, le générateur
             A : R4 (README racine), début du rapport LaTeX (R1/R2) ; aider B sur le dashboard
SPRINT 5     A + B : R1 → R5 (rapport LaTeX, figures, README racine, fusion dans main)
SPRINT 6     A + B : répétition de la démo
```

**Règles à ne pas oublier**

- Aucun index sur `telemetry` avant `explain --label before` (A6), sinon la comparaison est perdue.
- Toute modification du format des documents : `docs/data-model.md` **et** `init-db.js` dans la même PR.
- Les appels aux API externes (OSRM, Overpass, Open-Meteo) sont faits **une fois** et mis en
  fichier ; la démo ne doit pas dépendre d'Internet.
- Vérifier la date de rendu avec l'enseignant et réduire les bonus (sharding, time series,
  Tailscale) si le temps manque : le Replica Set, les agrégations, le géo et le dashboard sont
  obligatoires.
