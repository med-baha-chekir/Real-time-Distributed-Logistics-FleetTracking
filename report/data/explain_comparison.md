Référence temporelle : 2026-11-21T19:23:43.040000+00:00 — 5 000 000 documents

| Requête | before (ms) | after (ms) | gain | after-extra (ms) | gain | Docs examinés (before → after → after-extra) | Étapes (dernier) |
|---|---|---|---|---|---|---|---|
| a_avg_speed_by_region | 4 680 | 2 342 | ×2.0 | 1 604 | ×2.9 | 5 000 000 → 1 442 000 → 0 | IXSCAN,PROJECTION_COVERED |
| b_avg_fuel_by_vehicle | 4 411 | 2 392 | ×1.8 | 1 604 | ×2.8 | 5 000 000 → 1 442 000 → 0 | IXSCAN,PROJECTION_COVERED |
| c_vehicles_by_region | 1 | 1 | ≈ | 1 | ≈ | 2 000 → 2 000 → 2 000 | COLLSCAN,PROJECTION_SIMPLE |
| d_overheat_alerts | 3 574 | 8 766 | **÷2.5** | 23 | ×155.4 | 5 000 000 → 5 000 000 → 0 | IXSCAN,PROJECTION_COVERED |
| e_speed_distribution | 4 551 | 2 474 | ×1.8 | 1 732 | ×2.6 | 5 000 000 → 1 442 000 → 0 | IXSCAN,PROJECTION_COVERED |
| f_vehicle_history | 2 968 | 0 | ×2 968+ | 1 | ×2968.0 | 5 000 000 → 100 → 100 | FETCH,IXSCAN,LIMIT |
| geo_near_point | 5 | 6 | ≈ | 4 | ≈ | 121 → 121 → 121 | FETCH,GEO_NEAR_2DSPHERE,IXSCAN |
| geo_in_zone | 2 | 2 | ≈ | 2 | ≈ | 80 → 80 → 80 | FETCH,IXSCAN |
| geo_zone_avg_speed | 4 525 | 20 386 | **÷4.5** | 987 | ×4.6 | 5 000 000 → 240 628 → 72 353 | FETCH,IXSCAN,PROJECTION_SIMPLE |

Index présents :
- **before** : _id_
- **after** : _id_, location_2dsphere, region_ts, ts, vehicle_ts
- **after-extra** : _id_, location_2dsphere, overheat_partial, region_ts, ts, ts_covering, ts_location, vehicle_ts
