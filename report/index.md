# Index — mesures avant / après (sprint 3)

**Jeu de données** : base `fleet`, 5 000 000 documents `telemetry` (2 000 camions, 3 h 28,
générateur v2, `SEED=42`), heure de référence 19:23:43 UTC. Replica Set 3 nœuds, cache
WiredTiger 0,5 Go par nœud.

**Méthode** : `python -m queries.explain_baseline --label <label>` exécute chaque requête de
`queries/pipelines.py` avec `explain("executionStats")`, **3 fois**, et retient la **médiane**
(la première exécution est souvent « à froid »). Pour la mesure sans index, les index secondaires
sont **cachés** (`collMod … hidden: true`, `--hide-indexes`) : le planificateur les ignore, sans
qu'il faille les supprimer et les reconstruire.

| Étape | Commande | Index sur `telemetry` |
|---|---|---|
| **before** | `explain_baseline --label before --hide-indexes` | `_id` seulement |
| **after** | `init-indexes.sh` puis `explain_baseline --label after` | + 4 index du plan (section 7) |
| **after-extra** | `INDEX_SET=extra init-indexes.sh` puis `--label after-extra` | + 3 index ajoutés après analyse |

Tableau généré : `python -m queries.compare_explain before after after-extra`
→ `report/data/explain_comparison.md`. Explain complets : `report/explain/<label>/`.

## 1. Index créés (I1)

`bash infra/scripts/init-indexes.sh` (+ `INDEX_SET=extra`) → `report/data/indexes_plan.txt`, `indexes_extra.txt`

| Index | Clé | Création (5 M docs) | Taille | Rôle |
|---|---|---|---|---|
| `vehicle_ts` | `{vehicle_id: 1, ts: -1}` | 14,0 s | 62,6 Mo | historique d'un camion (f) |
| `region_ts` | `{region: 1, ts: -1}` | 14,6 s | 48,0 Mo | statistiques d'une région |
| `ts` | `{ts: -1}` | 13,7 s | 39,1 Mo | fenêtres temporelles |
| `location_2dsphere` | `{location: "2dsphere"}` | 30,2 s | 70,6 Mo | requêtes géographiques |
| *ajouté* `overheat_partial` | `{ts: -1, vehicle_id: 1, engine_temp_c: 1}`, **partiel** `engine_temp_c > 105` | 9,6 s | **0,6 Mo** | alertes (d) |
| *ajouté* `ts_location` | `{ts: -1, location: "2dsphere"}` | 36,8 s | 88,2 Mo | vitesse dans une zone |
| *ajouté* `ts_covering` | `{ts: -1, region: 1, vehicle_id: 1, speed_kmh: 1, fuel_rate_lph: 1}` | 32,4 s | 154,3 Mo | **couvrant** pour a, b, e |

Index du plan : 220 Mo, 72 s de création. Avec les index ajoutés : **604 Mo d'index pour 450 Mo
de données sur disque** (index `_id` compris).

## 2. Temps des requêtes (I2)

| Requête | Sans index | Index du plan | Gain | + index ajoutés | Gain total | Documents lus |
|---|---|---|---|---|---|---|
| a — vitesse moyenne par région (1 h) | 4 680 ms | 2 342 ms | ×2,0 | **1 604 ms** | **×2,9** | 5 M → 1,44 M → **0** |
| b — consommation par camion (1 h) | 4 411 ms | 2 392 ms | ×1,8 | **1 604 ms** | **×2,8** | 5 M → 1,44 M → **0** |
| c — camions par région (`vehicle_state`) | 1 ms | 1 ms | ≈ | 1 ms | ≈ | 2 000 |
| d — alertes de surchauffe (24 h) | 3 574 ms | 8 766 ms | **÷2,5** | **23 ms** | **×155** | 5 M → 5 M → **0** |
| e — distribution des vitesses (1 h) | 4 551 ms | 2 474 ms | ×1,8 | **1 732 ms** | **×2,6** | 5 M → 1,44 M → **0** |
| f — historique d'un camion | 2 968 ms | **0 ms** | **> ×1 000** | 1 ms | **> ×1 000** | 5 M → **100** |
| géo — rayon 10 km (`vehicle_state`) | 5 ms | 6 ms | ≈ | 4 ms | ≈ | 121 |
| géo — polygone (`vehicle_state`) | 2 ms | 2 ms | ≈ | 2 ms | ≈ | 80 |
| géo — vitesse dans une zone (1 h) | 4 525 ms | 20 386 ms | **÷4,5** | **987 ms** | **×4,6** | 5 M → 240 628 → 72 353 |

« 0 document lu » = requête **couverte** (`PROJECTION_COVERED`) : MongoDB répond avec l'index seul.

## 3. Analyse

### Ce qui marche immédiatement : requête très sélective (f)
L'historique d'un camion ne concerne que 100 documents sur 5 M. Sans index, MongoDB lit tout
(COLLSCAN, 3 s) ; avec `{vehicle_id: 1, ts: -1}` il descend directement aux 100 dernières entrées
de ce camion, déjà triées : **moins d'une milliseconde**. C'est le cas d'école de l'index.

### Gain modeste : requête peu sélective (a, b, e)
La fenêtre « dernière heure » contient **29 %** des documents (1 442 000). Avec l'index `ts`,
MongoDB lit 1,44 M de documents au lieu de 5 M, mais doit aller chercher chacun d'eux : le gain
n'est que de ×2. Une règle connue : au-delà de 10–30 % de la collection, un index apporte peu.
Il reste efficace ici parce que les documents ont été insérés dans l'ordre de `ts` : la plage
de temps correspond à une zone contiguë du disque.
**Solution : index couvrant** `ts_covering`, qui contient tous les champs utilisés par a, b et e.
MongoDB ne lit plus aucun document (0 au lieu de 1,44 M) : ×2,9 au total.

### Régression 1 : un index inutile choisi quand même (d)
La fenêtre de d (24 h) couvre **toutes** les données (3 h 28). Le planificateur choisit pourtant
l'index `ts` : il parcourt 5 M d'entrées d'index **puis** les 5 M de documents dans le désordre
(÷2,5, 8,8 s). Un index n'est pas toujours un gain ; il faut vérifier avec `explain`.
**Solution : index partiel** `overheat_partial`, qui n'indexe que les messages > 105 °C
(20 346, soit 0,4 %). Il pèse **0,6 Mo** et, étant aussi couvrant, répond en **23 ms (×155)**.

### Régression 2 : l'index géo disperse les lectures (zone)
Avec `location_2dsphere`, MongoDB trouve les 240 628 messages situés dans la zone (sur toute la
période), puis filtre la dernière heure. Ces documents sont **dispersés sur tout le disque** :
lectures aléatoires, cache de 0,5 Go dépassé → 20 s (÷4,5).
**Solution : index composé** `{ts: -1, location: "2dsphere"}` : la période **et** la zone sont
filtrées dans l'index ; il ne reste que 72 353 documents à lire, regroupés dans le temps → 987 ms.

### Requêtes sur `vehicle_state`
2 000 documents (un par camion) + index 2dsphere : déjà quelques millisecondes. C'est l'intérêt
de cette collection : la carte du dashboard ne touche jamais aux 5 M de messages.

## 4. Coût des index sur l'ingestion (I3)

`bash infra/scripts/bench_index_cost.sh 500000` : même ingestion (générateur v2, backfill,
2 000 camions, 4 processus, `w:"majority"`) dans une base vide, avec 3 jeux d'index
→ `report/data/bench_index_cost.txt`

| Index sur `telemetry` | Nombre | Débit | Écart | `insert_many` | Taille des index (500 000 docs) |
|---|---|---|---|---|---|
| aucun | 1 (`_id`) | 7 945 msg/s | — | 53 ms | 13,5 Mo |
| plan | 5 | 5 941 msg/s | **−25 %** | 104 ms | 91,6 Mo |
| plan + ajoutés | 8 | 5 457 msg/s | **−31 %** | 136 ms | 142,5 Mo |

Chaque document inséré doit être ajouté à **chaque** index : l'écriture ralentit et les index
occupent de la mémoire (ils entrent en concurrence avec les données dans le cache WiredTiger).

## 5. Conclusion — compromis lecture / écriture

| | Lecture | Écriture | Mémoire / disque |
|---|---|---|---|
| Sans index | 3 à 5 s par requête | 7 945 msg/s | 0 |
| Index du plan | f instantanée, a/b/e ×2, **d et zone plus lentes** | −25 % | +220 Mo |
| Index ajustés après mesure | **toutes les requêtes ≤ 1,7 s, d en 23 ms** | −31 % | +384 Mo de plus |

- Pour une application de suivi en temps réel (beaucoup d'écritures, quelques requêtes
  fréquentes), il faut **peu d'index, choisis d'après les requêtes réelles et vérifiés avec
  `explain`** : un index « logique » (`ts` pour d) peut ralentir une requête.
- Les index **partiels** (petits, ciblés) et **couvrants** (pas de lecture des documents) sont
  les plus rentables ici.
- L'objectif du plan (« gain d'un ordre de grandeur ») est atteint pour f (> ×1 000) et d (×155) ;
  pour les agrégations sur 29 % des données, le gain plafonne à ×3 : seule une pré-agrégation
  (par exemple un résumé par minute et par région) ferait mieux.
