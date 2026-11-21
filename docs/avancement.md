# Avancement du projet — Real-time Distributed Logistics & Fleet Tracking

> État au **21/11/2026** — générateur v2 terminé sur la branche `feature/generator-v2`
> (à fusionner dans `develop`).
> Binôme : **Baha (A)** — infrastructure et mesures · **Abdelkader (B)** — générateur, dashboard.
> Référence : plan d'exécution détaillé (PDF, 6 semaines à partir du 11/10/2026).

## Vue d'ensemble

| Brique | État | Responsable |
|---|---|---|
| ① Générateur de télémétrie | ✅ v2 terminé : routes réelles OSRM, régions, anomalies, météo, testé | B (+ A) |
| ② Ingestion par lots | ✅ v2 : `vehicle_state`, `vehicles`, backfill, write concern, multiprocessing, reprise après bascule | B (+ A) |
| ③ Replica Set + tolérance aux pannes | ✅ terminé et mesuré | A |
| ④ Agrégations + requêtes géo | 🟡 écrites et vérifiées sur données v2 (base `fleet_test`) ; mesures officielles à faire | A (mesure) / B (doc) |
| ⑤ Index (explain avant / après) | ⏳ outillage prêt, mesures à faire | A |
| ⑥ Sharding (bonus) | 🟡 cluster prêt et testé, expérience des shard keys à faire | A |
| ⑦ Dashboard | ❌ pas commencé | B |
| ⑧ Rapport | 🟡 partie technique (A) en brouillon | A + B |

**Retard** : le plan prévoyait la semaine 5 (mesures finales, dashboard complet) ; nous sommes au
niveau de la semaine 3. Le générateur v2, qui bloquait tout, est **terminé** : le chemin critique
passe maintenant par l'ingestion de 1 M de documents (A3–A4), l'explain « before » (A6), puis le
dashboard (B).

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
- Une base de test **`fleet_test`** (≈ 420 000 documents) est restée sur le cluster ; elle peut être
  supprimée (`db.getSiblingDB("fleet_test").dropDatabase()`). La base `fleet` n'a pas été touchée.

## 1.8 Rapport

| Fichier | Contenu |
|---|---|
| [`report/partie-technique.md`](../report/partie-technique.md) | Architecture, Replica Set, deux types de panne, validation, plan d'index, choix des shard keys |
| [`report/failover.md`](../report/failover.md) | Tests de panne détaillés et analysés |
| [`report/mesures.md`](../report/mesures.md) | Tableau des mesures de la section 15 du plan |

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

## 2.2 Ingestion et mesures sur vraies données (A) — débloqué, à faire maintenant

| # | Tâche | Détail | Fini quand |
|---|---|---|---|
| A1 🟠 | Fusionner `feature/generator-v2` dans `develop` | Revue avec Abdelkader | PR fusionnée |
| A2 🟠 | Rendre `region` obligatoire | Ajouter `"region"` aux `required` de `telemetry` dans `init-db.js` (TODO), relancer `init-db.sh` | Un document sans région est refusé |
| A3 🔴 | **Repartir d'une base propre** | Vider `telemetry`, `vehicle_state`, `vehicles` (données v1 sans région) | Base vide, validateurs en place |
| A4 🔴 | **Ingérer 1 M de documents** (puis viser 5 à 10 M) | `python -m generator.main --mode backfill --docs 1000000 --trucks 2000 --workers 4` (≈ 2 min) ; vérifier régions, alertes, `vehicle_state` | `check-status.sh` montre ≥ 1 M docs |
| A5 🟠 | Benchmark avec le vrai générateur | Débit et latence avec `WRITE_CONCERN=1` puis `majority`, 2 000 et 5 000 camions | Ligne « vrai générateur » de `mesures.md` remplie |
| A6 🔴 | **Explain « before »** | `python -m queries.explain_baseline --label before` — **avant toute création d'index sur `telemetry`** | `report/explain/before/` |
| A7 🟠 | Taille sur disque | `check-status.sh` : taille des données, stockage, index | Ligne de `mesures.md` remplie |
| A8 🟠 | Refaire un test de panne sous charge | `failover-scenarios.sh s1-kill` pendant que le générateur tourne | Section « sous charge » de `failover.md` |

## 2.3 Index (A) — sprint 3

| # | Tâche | Détail | Fini quand |
|---|---|---|---|
| I1 🟠 | Script `infra/scripts/init-indexes.js` | `{vehicle_id:1, ts:-1}`, `{region:1, ts:-1}`, `{ts:-1}`, `{location:"2dsphere"}` sur `telemetry` ; mesurer la durée de création | Index créés, durée notée |
| I2 🟠 | **Explain « after »** | `--label after` puis tableau comparatif before / after (temps, docs examinés, COLLSCAN → IXSCAN) | Gain chiffré dans `mesures.md` |
| I3 🟠 | Coût des index sur l'ingestion | Débit du générateur avec et sans index | Compromis lecture / écriture expliqué |

## 2.4 Agrégations et requêtes géo (B, avec A)

| # | Tâche | Détail | Fini quand |
|---|---|---|---|
| Q1 🟠 | Documenter les 5 agrégations | Pour chacune : question métier, pipeline, résultat sur 1 M de docs, capture | Section du rapport |
| Q2 🟠 | Documenter les requêtes géo | Rayon, polygone, vitesse dans une zone ; rappel `[lon, lat]`, `$geoNear` en premier étage | Section du rapport |
| Q3 🟢 | Agrégation supplémentaire | Ex. distance parcourue par camion, ou alertes météo | Bonus |

## 2.5 Sharding (A) 🟢 — sprint 4

| # | Tâche | Détail | Fini quand |
|---|---|---|---|
| S1 | Script de chargement | Charger le **même** jeu de données dans le cluster shardé avec chaque clé | Script versionné |
| S2 | Comparer 3 shard keys | `region` (mauvaise, volontaire), `{vehicle_id:"hashed"}`, `{vehicle_id:1, ts:1}` : `getShardDistribution()`, `sh.status()`, *jumbo chunks* | Tableau de répartition |
| S3 | Temps des requêtes | Agrégation par région (ciblée ou diffusée) et historique d'un camion, pour chaque clé | Tableau + analyse |
| S4 | Time series | Collection `telemetry_ts` : taille sur disque et temps d'agrégation vs collection standard (peut passer à B) | Tableau comparatif |

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
FAIT         Générateur v2 (G1–G13), Replica Set, pannes, benchmark, outils explain, cluster shardé
MAINTENANT   A : A1 (fusion v2) → A2 → A3 → A4 (1 M docs) → A6 (explain before) → A5 → A7 → A8
             B : relire le générateur v2, Q1/Q2 (documenter les requêtes), commencer le dashboard D1
SPRINT 3     A : I1 → I2 (explain after) → I3          B : D1 → D4
SPRINT 4     A : S1 → S2 → S3 → S4                     B : D5 → D7
SPRINT 5     A + B : R1 → R5
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
