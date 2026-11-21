# Agrégations et requêtes géospatiales (Q1, Q2)

**Données** : base `fleet`, 5 000 000 messages de 2 000 camions sur 3 h 28 (générateur v2).
**Heure de référence** : 19:23:43 UTC = `ts` le plus récent en base (`queries/ref_time.py`). Les
fenêtres « dernière heure » sont calculées par rapport à elle et non à `Date.now()`, sinon elles
seraient vides dès que les données ont quelques heures.

**Code** : `queries/pipelines.py` (une fonction par requête, réutilisable par le dashboard).
Exécution : `python -m queries.run_queries` → résultats complets dans `report/data/query_results.json`.
Temps : médiane de 3 exécutions (`report/index.md`).

Récapitulatif :

| Requête | Collection | Résultat | Sans index | Avec index | Index utilisé |
|---|---|---|---|---|---|
| a — vitesse moyenne par région | telemetry | 12 régions | 4 680 ms | 1 604 ms | `ts_covering` (couvrant) |
| b — consommation par camion | telemetry | top 20 | 4 411 ms | 1 604 ms | `ts_covering` (couvrant) |
| c — camions par région | vehicle_state | 12 régions | 1 ms | 1 ms | aucun (2 000 docs) |
| d — alertes de surchauffe | telemetry | 22 camions | 3 574 ms | 23 ms | `overheat_partial` (partiel, couvrant) |
| e — distribution des vitesses | telemetry | 6 tranches | 4 551 ms | 1 732 ms | `ts_covering` (couvrant) |
| f — historique d'un camion | telemetry | 100 messages | 2 968 ms | 1 ms | `vehicle_ts` |
| géo 1 — rayon de 10 km | vehicle_state | 109 camions | 5 ms | 4 ms | `location_2dsphere` (obligatoire) |
| géo 2 — polygone | vehicle_state | 76 camions | 2 ms | 2 ms | `location_2dsphere` |
| géo 3 — vitesse dans une zone | telemetry | 1 ligne | 4 525 ms | 987 ms | `ts_location` |

---

## Agrégations (Q1)

### a) Vitesse moyenne par région sur la dernière heure

**Question** : quelles régions roulent le plus vite ou le plus lentement en ce moment
(embouteillages, travaux) ?

```js
db.telemetry.aggregate([
  { $match: { ts: { $gte: ref - 1h, $lte: ref } } },
  { $group: { _id: "$region", avg_speed: { $avg: "$speed_kmh" }, messages: { $sum: 1 } } },
  { $sort: { avg_speed: -1 } }
])
```

| Région | Vitesse moyenne | Messages | | Région | Vitesse moyenne | Messages |
|---|---|---|---|---|---|---|
| Gabes | 66,0 km/h | 105 211 | | Kairouan | 56,1 km/h | 126 146 |
| Bizerte | 64,0 km/h | 57 696 | | Sfax | 55,6 km/h | 193 013 |
| Nabeul | 63,4 km/h | 102 553 | | Kef | 53,3 km/h | 50 992 |
| Sousse | 59,9 km/h | 194 471 | | Gafsa | 49,9 km/h | 133 273 |
| Beja | 59,2 km/h | 107 111 | | Kasserine | 49,8 km/h | 60 888 |
| Tunis | 58,8 km/h | 214 751 | | Monastir | 47,5 km/h | 95 895 |

Lecture : les régions traversées par des routes rapides (Gabes, Bizerte) ont les vitesses les
plus élevées ; Monastir, Kasserine et Gafsa, avec des routes plus lentes et des livraisons en
ville, les plus basses. La moyenne inclut les arrêts (vitesse 0).
**Pourquoi `region` est dupliquée dans chaque message** : sans elle, il faudrait une jointure
(`$lookup`) vers `vehicles` pour chaque document, bien plus coûteuse.

### b) Consommation moyenne par camion (top 20, dernière heure)

**Question** : quels camions consomment le plus (fuite, conduite, entretien) ?
Correction par rapport au plan initial : ajout de la fenêtre temporelle (`$match` sur `ts`),
sinon `$group` parcourt toute la collection.

```js
db.telemetry.aggregate([
  { $match: { ts: { $gte: ref - 1h, $lte: ref } } },
  { $group: { _id: "$vehicle_id", avg_fuel_rate: { $avg: "$fuel_rate_lph" } } },
  { $sort: { avg_fuel_rate: -1 } },
  { $limit: 20 }
])
```

Top 5 : VH-001941 (75,2 L/h), VH-001184 (66,2), VH-000833 (62,9), VH-000975 (56,7),
VH-001226 (52,4). La moyenne de la flotte est d'environ 30 L/h : les premiers camions sont
ceux dotés de l'anomalie « fuite » du générateur (consommation ×1,6). **L'agrégation retrouve
bien les anomalies injectées.**

### c) Nombre de véhicules par région (position actuelle)

**Question** : où se trouve la flotte en ce moment ?

```js
db.vehicle_state.aggregate([
  { $group: { _id: "$region", vehicles: { $sum: 1 } } },
  { $sort: { vehicles: -1 } }
])
```

Sousse 273, Tunis 270, Sfax 255, Gafsa 187, Kairouan 186, Nabeul 159, Gabes 158, Beja 138,
Monastir 121, Bizerte 87, Kef 84, Kasserine 82 (total 2 000).
Exécutée sur `vehicle_state` (1 document par camion, mis à jour à chaque message) : 1 ms,
contre plusieurs secondes s'il fallait retrouver le dernier message de chaque camion dans
`telemetry`.

### d) Alertes de surchauffe (24 h)

**Question** : quels camions ont dépassé 105 °C, combien de fois, et jusqu'à quelle température ?

```js
db.telemetry.aggregate([
  { $match: { engine_temp_c: { $gt: 105 }, ts: { $gte: ref - 24h, $lte: ref } } },
  { $group: { _id: "$vehicle_id", max_temp: { $max: "$engine_temp_c" }, count: { $sum: 1 } } },
  { $sort: { count: -1 } }
])
```

**22 camions** (1,1 % de la flotte, comme l'anomalie programmée de 1 %), 20 346 messages.
Top 5 : VH-000179 (1 322 messages, max 121,5 °C), VH-001774 (1 255, 122,1 °C), VH-001115
(1 225, 117,8 °C), VH-000804 (1 193, 121,6 °C), VH-000583 (1 192, 123,0 °C).
Avec l'index partiel `overheat_partial` : **23 ms au lieu de 3,6 s** (voir `report/index.md`).

### e) Distribution des vitesses (dernière heure)

**Question** : comment se répartit le temps de conduite (arrêts, ville, route) ?
Correction : fenêtre temporelle ajoutée (comme pour b).

```js
db.telemetry.aggregate([
  { $match: { ts: { $gte: ref - 1h, $lte: ref } } },
  { $bucket: { groupBy: "$speed_kmh", boundaries: [0, 20, 40, 60, 80, 100, 130],
               default: "hors plage", output: { count: { $sum: 1 } } } }
])
```

| Tranche (km/h) | 0–20 | 20–40 | 40–60 | 60–80 | 80–100 | 100–130 |
|---|---|---|---|---|---|---|
| Messages | 246 843 | 93 096 | 202 797 | 476 235 | 423 028 | 1 |
| Part | 17,1 % | 6,5 % | 14,1 % | 33,0 % | 29,3 % | ≈ 0 |

La tranche 0–20 correspond surtout aux arrêts (livraisons, feux, ravitaillement). Aucun camion
ne dépasse durablement 100 km/h (plafond du modèle). Avec le générateur v1, toutes les vitesses
étaient entre 60 et 90 km/h : l'histogramme n'avait que 2 barres.

### f) Historique d'un camion (requête supplémentaire)

```js
db.telemetry.aggregate([
  { $match: { vehicle_id: "VH-000001", ts: { $gte: ref - 24h, $lte: ref } } },
  { $sort: { ts: -1 } },
  { $limit: 100 }
])
```

Les 100 derniers messages de VH-000001 (arrêté à Tunis en fin de trajet `TR-20261121-000001-004`,
itinéraire R09). C'est la requête qui profite le plus d'un index (`{vehicle_id: 1, ts: -1}`) :
**3 s → moins de 1 ms**.

---

## Requêtes géospatiales (Q2)

Rappels :
- coordonnées GeoJSON en **`[longitude, latitude]`** (le validateur refuse l'ordre inverse) ;
- `$nearSphere` / `$geoNear` **exigent** un index 2dsphere (sans index : erreur) ;
- `$geoNear` doit être le **premier** étage du pipeline ; il renvoie la distance (`distanceField`).

### Géo 1 — Camions dans un rayon de 10 km autour de Tunis

```js
db.vehicle_state.aggregate([
  { $geoNear: { near: { type: "Point", coordinates: [10.1815, 36.8065] },
                distanceField: "distance_m", maxDistance: 10000, spherical: true } }
])
```

**109 camions**, triés du plus proche (162 m) au plus lointain (9,9 km) ; 43 sont à l'arrêt
(livraison en ville). Équivalent `find` du plan : `$nearSphere` avec `$maxDistance: 10000`.
Index utilisé : `location_2dsphere` de `vehicle_state` (121 documents examinés sur 2 000).

### Géo 2 — Camions dans un polygone (zone de livraison de Tunis)

```js
db.vehicle_state.find({ location: { $geoWithin: { $geometry: {
  type: "Polygon",
  coordinates: [[[10.10, 36.78], [10.25, 36.78], [10.25, 36.87], [10.10, 36.87], [10.10, 36.78]]]
} } } })
```

**76 camions** dans le rectangle, vitesse moyenne 23,4 km/h (trafic urbain et arrêts).
`$geoWithin` fonctionne sans index, mais l'index 2dsphere limite la lecture à 80 documents.

### Géo 3 — Vitesse moyenne des camions dans une zone (dernière heure)

```js
db.telemetry.aggregate([
  { $match: { ts: { $gte: ref - 1h, $lte: ref },
              location: { $geoWithin: { $geometry: <polygone de Tunis> } } } },
  { $group: { _id: null, avg_speed: { $avg: "$speed_kmh" }, messages: { $sum: 1 } } }
])
```

**24,4 km/h** sur 66 631 messages. Correction par rapport au plan : ajout de la fenêtre
temporelle (sans elle, la moyenne porterait sur toute l'histoire).
Cas d'étude d'index (voir `report/index.md`) : l'index 2dsphere seul **ralentit** la requête
(4,5 s → 20,4 s, lectures dispersées) ; l'index composé `{ts: -1, location: "2dsphere"}` la
ramène à **987 ms**.
