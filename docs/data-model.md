# Modèle de données — contrat entre infra (A) et générateur (B)

Ce document fixe le format **exact** des documents. Le validateur
[`infra/scripts/init-db.js`](../infra/scripts/init-db.js) le fait respecter : un document
non conforme est **refusé** par MongoDB (`DocumentValidationFailure`).

> Toute modification du format se fait dans ce fichier **et** dans `init-db.js`, dans la même PR.

## Règles générales

| Règle | Détail |
|---|---|
| Coordonnées | GeoJSON `{ "type": "Point", "coordinates": [lon, lat] }` — **longitude d'abord**. Bornes acceptées : lon ∈ [7, 12], lat ∈ [30, 38] (Tunisie). |
| Dates | Objet `datetime` Python **avec fuseau UTC** (`datetime.now(timezone.utc)`), jamais une chaîne. |
| Nombres | `float` ou `int` Python, jamais une chaîne (`"50"` est refusé). |
| Identifiant camion | `VH-` + 6 chiffres : `f"VH-{n:06d}"` → `VH-000123`. |
| Région | Champ `region` **dupliqué** dans `telemetry` et `vehicle_state` (évite une jointure). |

## Régions

12 régions = les 12 villes de `generator/routes.py` (`CITIES`), orthographe exacte :

```
Tunis, Bizerte, Nabeul, Sousse, Monastir, Kairouan,
Sfax, Gabes, Gafsa, Kasserine, Beja, Kef
```

**Règle de calcul** : `region` = ville de `CITIES` la plus proche de la position courante
(distance de Haversine, déjà codée dans `vehicle.distance_km`). Simple, déterministe, testable.

> Remarque pour le rapport : 12 valeurs distinctes seulement → `region` est volontairement une
> mauvaise shard key (jumbo chunks, hot spots).

## Collection `vehicles` (référentiel, 1 document par camion)

| Champ | Type | Obligatoire | Exemple | Remarque |
|---|---|---|---|---|
| `_id` | string | ✅ | `"VH-000123"` | = `vehicle_id` |
| `model` | string | ✅ | `"Volvo FH 500"` | |
| `capacity_t` | nombre | ✅ | `26` | tonnes |
| `home_region` | string | ✅ | `"Tunis"` | une des 12 régions |
| `status` | string | ✅ | `"active"` | `active` \| `maintenance` \| `inactive` |
| `created_at` | date | | `datetime(2026,1,15,8,0,tzinfo=utc)` | |

Insertion : une fois au démarrage, `bulk_write([ReplaceOne({"_id": id}, doc, upsert=True), ...])`
(relançable sans doublon).

## Collection `telemetry` (1 document par message, toutes les 5 s par camion)

| Champ | Type | Obligatoire | Exemple | Unité / bornes |
|---|---|---|---|---|
| `vehicle_id` | string | ✅ | `"VH-000123"` | |
| `ts` | date | ✅ | `datetime(..., tzinfo=utc)` | |
| `location` | GeoJSON Point | ✅ | `[10.1815, 36.8065]` | [lon, lat] |
| `speed_kmh` | nombre | ✅ | `87.4` | km/h, ∈ [0, 160] |
| `region` | string | ✅ *(dès le v2)* | `"Tunis"` | une des 12 régions |
| `trip_id` | string | | `"TR-20261011-0042"` | change à chaque nouveau trajet |
| `route_id` | string | | `"R01"` | |
| `fuel_level_pct` | nombre | | `63.2` | %, ∈ [0, 100] |
| `fuel_rate_lph` | nombre | | `28.7` | L/h, ≥ 0 |
| `engine_temp_c` | nombre | | `92.1` | °C — **> 105 = surchauffe** (alerte, pipeline d) |
| `odometer_km` | nombre | | `154320.5` | km, ≥ 0 |

Insertion : `insert_many(batch, ordered=False)` par lots de 500 à 1 000,
write concern lue dans `WRITE_CONCERN` (`"majority"` ou `"1"`).

## Collection `vehicle_state` (dernière position, 1 document par camion)

| Champ | Type | Obligatoire | Exemple |
|---|---|---|---|
| `_id` | string | ✅ | `"VH-000123"` |
| `last_ts` | date | ✅ | = `ts` du dernier message |
| `location` | GeoJSON Point | ✅ | |
| `region` | string | | `"Tunis"` |
| `speed_kmh` | nombre | | |
| `engine_temp_c` | nombre | | |

Mise à jour **à chaque lot** :

```python
from pymongo import UpdateOne

ops = [
    UpdateOne(
        {"_id": d["vehicle_id"]},
        {"$set": {
            "last_ts": d["ts"], "location": d["location"], "region": d["region"],
            "speed_kmh": d["speed_kmh"], "engine_temp_c": d["engine_temp_c"],
        }},
        upsert=True,
    )
    for d in batch   # garder seulement le dernier document de chaque camion du lot
]
db.vehicle_state.bulk_write(ops, ordered=False)
```

Index 2dsphere déjà créé par `init-db.js` (carte temps réel, requêtes `$nearSphere`).

## Ce que le générateur v2 doit produire pour les mesures

| Besoin (pipeline / mesure) | Exigence sur les données |
|---|---|
| a, c — par région | `region` présente partout |
| d — alertes surchauffe | ~1 % des camions dépassent 105 °C de temps en temps |
| e — histogramme de vitesse | vitesses variées : arrêts (0), urbain (30–50), route (60–90), autoroute (90–110) |
| Fenêtres « dernière heure » | mode **backfill** : horloge simulée qui **se termine à maintenant** |
| w:1 vs w:majority | variable `WRITE_CONCERN` |
| Reproductibilité | variable `SEED` |

## Vérifier qu'un document est accepté

```bash
bash infra/scripts/init-db.sh            # applique le validateur
# puis lancer le générateur : "Erreurs : 0" = tous les documents sont conformes
docker compose -f infra/docker-compose.rs.yml --profile app run --rm -e DURATION_SECONDS=15 generator
```
