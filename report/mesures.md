# Mesures de performance (section 15 du plan)

Environnement : PC de A, Docker Desktop (WSL2, 16 Go, 12 CPU), Replica Set 3 nœuds `mongo:7`,
cache WiredTiger 0,5 Go et 1 Go de RAM par nœud. Toutes les mesures se relancent avec les
scripts indiqués. Données brutes : `report/data/`.

**Jeu de données de référence** (base `fleet`, 21/11/2026) : **5 000 000 documents** `telemetry`,
2 000 camions, 12 régions, **3 h 28 de données** (15:55 → 19:23 UTC), générateur v2 en mode
backfill, `SEED=42`. Aucun index secondaire sur `telemetry` (mesure « before » des index).

| Mesure | Objectif | Résultat | Statut | Source |
|---|---|---|---|---|
| Débit, vrai générateur, `w:1` | ≥ 1 000 msg/s | **≈ 13 200 msg/s** (base vide, 4 processus) | ✅ | `bench_generator.sh` |
| Débit, vrai générateur, `w:"majority"` | ≥ 1 000 msg/s | **≈ 10 600 msg/s** (base vide, 4 processus) | ✅ | `bench_generator.sh` |
| Débit, ingestion de 5 M docs (`majority`) | ≥ 1 000 msg/s | **4 676 msg/s** en moyenne (17,8 min), 0 erreur | ✅ | `ingestion_5M.log` |
| Débit temps réel, 2 000 camions | ≈ 400 msg/s (scénario minimal) | ≈ 400–500 msg/s, 0 erreur | ✅ | générateur v2 |
| Latence d'un `insert_many` | < 100 ms / lot | 17–41 ms (base vide) ; **111 ms** en fin d'ingestion de 5 M docs | 🟡 dépassé à grande échelle | générateur v2 |
| Débit plafond (banc synthétique) | — | 52 000 docs/s (w:1) ; 32 000 (majority) | info | `bench_write.py` |
| Temps de bascule, arrêt propre | quelques s | **0,58 s** (moyenne de 3) | ✅ | `failover.md` |
| Temps de bascule, crash | quelques s | **11,5 s** à vide ; **20,2 s** sous charge | ✅ | `failover.md` |
| Écritures confirmées perdues | 0 | **0** (10 essais + 1 bascule spontanée) | ✅ | `failover.md` |
| Temps de resynchronisation | — | 2,0 – 4,6 s | ✅ | `failover.md` |
| Requêtes **avant** index (5 M docs) | référence | **3,0 à 4,7 s** (médiane de 3), 5 000 000 docs examinés (COLLSCAN) | ✅ | `report/explain/before/` |
| Requêtes **après** index du plan | gain d'un ordre de grandeur | f **> ×1 000** ; a, b, e ×1,8–2,0 ; **d ÷2,5 et zone ÷4,5 (régressions)** | 🟡 | `report/index.md` |
| Requêtes **après** index ajustés | gain d'un ordre de grandeur | f > ×1 000 ; **d ×155 (23 ms)** ; zone ×4,6 ; a, b, e ×2,6–2,9 | ✅ | `report/index.md` |
| Coût des index sur l'ingestion | — | débit **−25 %** (index du plan), **−31 %** (7 index) ; `insert_many` 53 → 136 ms | ✅ | `bench_index_cost.txt` |
| Taille des index `telemetry` | — | 220 Mo (plan, créés en 72 s) ; 604 Mo au total avec les index ajoutés | ✅ | `indexes_extra.txt` |
| Répartition des chunks | équilibrée (hashé) | 1 M docs par clé : hashé **50,5 / 49,5 %** ; `{vehicle_id, ts}` 50,8 / 49,2 % ; `region` 50,1 / 49,9 % mais chunk de Tunis **indivisible et intransportable** (jumbo) | ✅ | `report/sharding.md` |
| Ciblage des requêtes (sharding) | — | « un camion » : **1 shard** avec vehicle_id (2–11 ms), 2 shards avec region (194 ms) ; « une région » : 1 shard seulement avec region | ✅ | `report/sharding.md` |
| Taille sur disque `telemetry` | standard vs time series | standard : 450 Mo + 604 Mo d'index ; **time series : 105 Mo + 23 Mo d'index (÷8,3)** | ✅ | `report/timeseries.md` |
| Agrégation temporelle : time series vs standard | — | a : **681 ms** (time series) contre 1 816 ms (index couvrant) et 5 718 ms (sans index) | ✅ | `report/timeseries.md` |

## 1. Débit du vrai générateur

`bash infra/scripts/bench_generator.sh 200000` — 200 000 documents par essai, base vide
`fleet_bench` (mêmes validateurs), mode backfill, 4 processus, lots de 500, sans météo.

| Camions | Write concern | Durée | Débit | `insert_many` | `vehicle_state` |
|---|---|---|---|---|---|
| 2 000 | `w:1` | 15,1 s | **13 264 msg/s** | 17,8 ms | 108,8 ms |
| 2 000 | `w:"majority"` | 18,9 s | **10 568 msg/s** | 41,2 ms | 126,3 ms |
| 5 000 | `w:1` | 15,2 s | **13 169 msg/s** | 16,5 ms | 89,2 ms |
| 5 000 | `w:"majority"` | 18,6 s | **10 764 msg/s** | 33,9 ms | 101,4 ms |

**Lecture** :
- `w:"majority"` coûte **≈ 20 %** de débit avec le vrai générateur (30 à 38 % sur le banc
  synthétique) : le calcul des trajectoires en Python masque une partie de l'attente de réplication.
- Le nombre de camions change peu le débit : c'est le volume de documents qui compte.
- La mise à jour de `vehicle_state` (upsert + index 2dsphere) coûte plus cher que l'insertion
  elle-même : 90–126 ms par lot contre 17–41 ms.

## 2. Ingestion de 5 M de documents

`python -m generator.main --mode backfill --docs 5000000 --trucks 2000 --workers 4` (w:majority)
→ `report/data/ingestion_5M.log`

| Indicateur | Valeur |
|---|---|
| Documents | 5 000 000 (2 000 camions × 2 500 cycles de 5 s) |
| Durée | 1 069 s (17,8 min) |
| Débit moyen | **4 676 msg/s** (1 170 msg/s par processus) |
| Erreurs / reprises | **0 / 0** |
| `insert_many` / `vehicle_state` | 111 ms / 300 ms par lot |

Le débit baisse quand la collection grossit (8 700 msg/s sur 200 000 docs, 4 676 sur 5 M) :
la collection (1,5 Go) dépasse vite le cache WiredTiger (0,5 Go par nœud) et MongoDB devient
le goulot (CPU des nœuds entre 135 et 345 %, mémoire proche de la limite de 1 Go).

**Bascule spontanée pendant l'ingestion** : à 19:33:17 UTC, les secondaires saturés n'ont plus reçu
de *heartbeat* du primaire (mongo3) pendant 10 s et ont lancé une élection (mongo2 élu à
19:33:22). Le générateur n'a vu **aucune erreur ni reprise** : le driver a rejoué l'écriture
interrompue (`retryWrites`). Exemple réel d'une panne « faux positif » due à la surcharge.

## 3. Taille sur disque (base `fleet`, par nœud)

`bash infra/scripts/check-status.sh` → `report/data/status_5M.txt`

| Collection | Documents | Données | Disque | Index |
|---|---|---|---|---|
| telemetry | 5 000 000 | 1 495,5 Mo | **448,9 Mo** | 140,1 Mo (`_id`) |
| vehicle_state | 2 000 | 0,4 Mo | 0,5 Mo | **125 Mo** (`_id` + 2dsphere) |
| vehicles | 2 000 | 0,2 Mo | 0,1 Mo | 0,1 Mo |

- Taille moyenne d'un document : **313 octets** ; compression WiredTiger (snappy) **×3,3**.
- Volume Docker de chaque nœud : ≈ 2,6 Go (données + index + oplog + journal) ; ×3 réplicas.
- **Anomalie à analyser** : l'index de `vehicle_state` pèse 125 Mo pour 2 000 documents. Chaque
  message déplace la position d'un camion : 5 M de mises à jour de l'index 2dsphere, dont
  WiredTiger ne libère pas l'espace. Piste : `db.runCommand({compact: "vehicle_state"})` et
  comparer la taille avant / après.
- Comparaison avec une **time series collection** : sprint 4 (tâche S4).

## 4. Requêtes avant index (première mesure, une exécution)

Première mesure du sprint 2 (`--label before`, **une seule exécution** par requête, juste après
l'ingestion). Au sprint 3, la mesure « before » a été refaite avec la méthode définitive
(médiane de 3 exécutions, index cachés) : **voir `report/index.md`** pour les chiffres officiels
avant / après. Les deux séries concordent (écarts de 4 à 13 %, effet du cache).

| Requête | Temps | Docs examinés | Clés examinées | Renvoyés | Étapes |
|---|---|---|---|---|---|
| a — vitesse moyenne par région (1 h) | **5 274 ms** | 5 000 000 | 0 | 1 442 000 | COLLSCAN |
| b — consommation par camion (1 h) | **4 281 ms** | 5 000 000 | 0 | 1 442 000 | COLLSCAN |
| c — camions par région (`vehicle_state`) | 19 ms | 2 000 | 0 | 2 000 | COLLSCAN |
| d — alertes de surchauffe (24 h) | **3 705 ms** | 5 000 000 | 0 | 20 346 | COLLSCAN |
| e — distribution des vitesses (1 h) | **4 510 ms** | 5 000 000 | 0 | 1 442 000 | COLLSCAN |
| f — historique d'un camion (100 derniers) | **3 132 ms** | 5 000 000 | 0 | 100 | COLLSCAN + SORT |
| géo — camions à 10 km de Tunis | 66 ms | 121 | 199 | 109 | GEO_NEAR_2DSPHERE (index de `vehicle_state`) |
| géo — camions dans un polygone | 2 ms | 80 | 94 | 76 | IXSCAN 2dsphere |
| géo — vitesse dans une zone (1 h) | **4 490 ms** | 5 000 000 | 0 | 66 631 | COLLSCAN |

**Lecture** :
- Sans index, **chaque** requête sur `telemetry` lit les 5 M de documents, même celle qui ne
  renvoie que 100 documents (f) : c'est la requête qui devrait gagner le plus avec
  `{vehicle_id: 1, ts: -1}`.
- La fenêtre « dernière heure » ne retient que 29 % des documents (1 442 000 / 5 M) : un index
  sur `ts` évitera d'en lire 71 % inutilement.
- Les requêtes sur `vehicle_state` sont déjà rapides : petite collection + index 2dsphere.

Suite (sprint 3) : index créés et mesurés → **`report/index.md`** (avant / après, index partiels
et couvrants, coût sur l'ingestion).

## 5. Banc synthétique (plafond de MongoDB)

`bench_write.py --docs 100000`, 2 répétitions, documents factices générés avant la mesure
(seul MongoDB est mesuré), collection sans validateur ni index secondaire.

| Write concern | Lot | Débit (docs/s) | Latence moyenne | Latence p95 |
|---|---|---|---|---|
| `w:1` | 500 | 51 834 | 9,7 ms | 11,2 ms |
| `w:"majority"` | 500 | 31 937 | 15,7 ms | 24,2 ms |
| `w:1` | 1 000 | 54 940 | 18,3 ms | 22,9 ms |
| `w:"majority"` | 1 000 | 38 580 | 25,9 ms | 45,2 ms |

Les 3 nœuds partagent la même machine : sur un vrai réseau, l'écart w:1 / majority serait plus
grand (latence réseau ajoutée à chaque confirmation).
