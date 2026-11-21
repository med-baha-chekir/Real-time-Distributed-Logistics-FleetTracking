# Time series collection vs collection standard (S4)

**Données** : les mêmes 5 000 000 messages (base `fleet`, 2 000 camions, 3 h 28).
**Outil** : `python -m queries.timeseries_compare` → `report/data/timeseries_compare.{txt,json}`.

La collection time series `telemetry_ts` est créée par un `$out` depuis `telemetry` :

```js
db.telemetry.aggregate([
  { $project: { _id: 0, ts: 1, meta: { vehicle_id: "$vehicle_id", region: "$region" },
                location: 1, speed_kmh: 1, fuel_level_pct: 1, fuel_rate_lph: 1,
                engine_temp_c: 1, odometer_km: 1, trip_id: 1, route_id: 1 } },
  { $out: { db: "fleet", coll: "telemetry_ts",
            timeseries: { timeField: "ts", metaField: "meta", granularity: "seconds" } } }
])
```

`vehicle_id` et `region` vont dans `meta` : ce sont les champs qui identifient la série. MongoDB
regroupe les mesures d'une même série et d'une même période dans des **buckets** (documents
internes compressés colonne par colonne).

Copie des 5 M de mesures : **256 s**.

## 1. Taille sur disque

| Collection | Données (non compressées) | Sur disque | Index | Total disque |
|---|---|---|---|---|
| `telemetry` (standard) | 1 495,5 Mo | 450,1 Mo | 604,0 Mo (8 index) | **1 054 Mo** |
| `telemetry` sans les index du sprint 3 | 1 495,5 Mo | 450,1 Mo | 140 Mo (`_id`) | 590 Mo |
| `telemetry_ts` (time series) | 182,0 Mo | **104,7 Mo** | **22,6 Mo** (`meta, ts`) | **127 Mo** |

- **18 284 buckets** pour 5 M de mesures (≈ 273 mesures par bucket).
- Données sur disque : **÷4,3** ; avec les index : **÷8,3**.
- Pourquoi : dans un bucket, les valeurs d'un même champ sont stockées ensemble et se suivent
  dans le temps (horodatages réguliers, positions proches, vitesses voisines) : elles se
  compressent très bien. `vehicle_id` et `region` ne sont stockés qu'une fois par bucket au lieu
  de 5 M de fois, et il n'y a plus d'`_id` par mesure.

## 2. Temps des requêtes (médiane de 3)

| Requête | Standard sans index | Standard + index (sprint 3) | Time series | Lignes |
|---|---|---|---|---|
| a — vitesse moyenne par région (1 h) | 5 718 ms | 1 816 ms (index couvrant) | **681 ms** | 12 |
| e — distribution des vitesses (1 h) | 4 921 ms | 1 824 ms (index couvrant) | **887 ms** | 6 |
| d — alertes de surchauffe (24 h) | 3 793 ms | **26 ms** (index partiel) | 234 ms | 22 |
| f — historique d'un camion | 3 048 ms | **3 ms** (`vehicle_ts`) | 109 ms | 100 |

Les résultats sont identiques dans les trois cas (vérifié par le script).

## 3. Analyse

- **Agrégations sur une période (a, e)** : la time series est la plus rapide (×2 à ×2,7 face au
  meilleur index, ×6 à ×8 sans index). Elle lit 4 fois moins de données, et ses buckets sont
  déjà rangés par période : MongoDB ne décompresse que ceux de la dernière heure.
- **Requêtes très ciblées (d, f)** : les index spécialisés de la collection standard restent
  meilleurs (index partiel de 0,6 Mo pour d ; index `{vehicle_id, ts}` pour f). La time series
  doit ouvrir et décompresser des buckets entiers pour trouver quelques mesures ; elle reste
  cependant 15 à 30 fois plus rapide que la collection standard sans index.
- **Écriture** : une time series accepte des insertions en masse comme une collection normale
  (`insert_many`), mais les mises à jour et suppressions de mesures sont limitées : elle convient
  aux données qui ne changent plus, ce qui est le cas de la télémétrie. La collection
  `vehicle_state` (dernière position, mise à jour en continu) doit rester une collection standard.

## 4. Conclusion

Pour l'historique de télémétrie, la time series est le meilleur choix de stockage : **8 fois
moins de place** (données + index) et des agrégations temporelles plus rapides, sans avoir à
concevoir d'index. Pour quelques requêtes très ciblées (alertes, historique d'un camion), on
peut lui ajouter des index secondaires (sur `meta.vehicle_id`, ou un index partiel), comme sur
une collection standard. Le générateur pourrait écrire directement dans une time series :
seul le format du document change (`vehicle_id` et `region` dans `meta`).
