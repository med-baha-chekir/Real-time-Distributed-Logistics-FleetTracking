# Mesures de performance (section 15 du plan)

Environnement : PC de A, Docker Desktop (WSL2, 16 Go, 12 CPU), Replica Set 3 nœuds `mongo:7`,
cache WiredTiger 0,5 Go et 1 Go de RAM par nœud. Toutes les mesures se relancent avec les
scripts indiqués.

| Mesure | Objectif | Résultat | Statut | Source |
|---|---|---|---|---|
| Débit d'ingestion `w:1` | ≥ 1 000 msg/s | **≈ 52 000 docs/s** (lots de 500) | ✅ banc synthétique | `bench_write.py` |
| Débit d'ingestion `w:"majority"` | ≥ 1 000 msg/s | **≈ 32 000 docs/s** (lots de 500) | ✅ banc synthétique | `bench_write.py` |
| Latence d'un `insert_many` | < 100 ms / lot | 9,7 ms (w:1) – 25,9 ms (majority, lot 1000) ; p95 ≤ 45 ms | ✅ | `bench_write.py` |
| Débit avec le vrai générateur | ≥ 1 000 msg/s | *à mesurer avec le générateur v2* | ⏳ | générateur v2 |
| Temps de bascule, arrêt propre | quelques s | **0,58 s** (moyenne de 3) | ✅ | `failover.md` |
| Temps de bascule, crash | quelques s | **11,5 s** (moyenne de 3) | ✅ | `failover.md` |
| Écritures confirmées perdues | 0 | **0** (9 essais) | ✅ | `failover.md` |
| Temps de resynchronisation | — | 2,0 – 3,2 s | ✅ | `failover.md` |
| Requêtes avant / après index | gain d'un ordre de grandeur | *before : sur 1 M docs v2 ; after : sprint 3* | ⏳ | `queries/explain_baseline.py` |
| Répartition des chunks | équilibrée (hashé) | test : 49 % / 51 % sur 20 000 docs | 🟡 test fumée | `init-shard.sh` |
| Taille sur disque | standard vs time series | *après ingestion de 1 M docs* | ⏳ | `check-status.sh` |

## Write concern × taille de lot

`bench_write.py --docs 100000`, 2 répétitions, documents factices générés avant la mesure
(seul MongoDB est mesuré), collection sans validateur ni index secondaire.

| Write concern | Lot | Débit (docs/s) | Latence moyenne | Latence p95 |
|---|---|---|---|---|
| `w:1` | 500 | 51 834 | 9,7 ms | 11,2 ms |
| `w:"majority"` | 500 | 31 937 | 15,7 ms | 24,2 ms |
| `w:1` | 1 000 | 54 940 | 18,3 ms | 22,9 ms |
| `w:"majority"` | 1 000 | 38 580 | 25,9 ms | 45,2 ms |

**Lecture** :
- `w:"majority"` coûte **30 à 38 % de débit** : chaque lot attend qu'un secondaire l'ait répliqué
  avant d'être confirmé. C'est le prix de la garantie « aucune écriture confirmée perdue »
  vérifiée dans `failover.md`.
- Doubler la taille de lot augmente peu le débit (+6 % en w:1, +21 % en majority) mais double la
  latence par lot : avec majority, des lots plus gros amortissent mieux l'attente de réplication.
- Les 3 nœuds partagent la même machine : sur un vrai réseau, l'écart w:1 / majority serait plus
  grand (latence réseau ajoutée à chaque confirmation).
- Ces chiffres sont un **plafond** : le générateur Python calcule aussi les trajectoires.
  Le débit réel est à mesurer avec le générateur v2 (`WRITE_CONCERN=1` puis `majority`).

## Explain : test sur données v1 (pas la mesure officielle)

`explain_baseline.py --label test-v1` sur 8 000 documents du générateur v1, sans index sur
`telemetry` : toutes les requêtes sur `telemetry` font un **COLLSCAN** et examinent les 8 000
documents ; les requêtes géo sur `vehicle_state` utilisent déjà l'index 2dsphere.

Ce test confirme deux défauts du générateur v1 à corriger dans le v2 :
- pipeline d (surchauffe) : **0 résultat**, la température converge vers 90 °C ;
- zone de Tunis : **3 392 messages sur 8 000** dans un petit rectangle, car tous les camions
  démarrent à leur ville d'origine.

La mesure **before** officielle se fera sur 1 M de documents v2, **avant** toute création d'index
sur `telemetry`.
