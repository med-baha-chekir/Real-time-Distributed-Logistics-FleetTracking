# Sharding — comparaison de trois shard keys (S1 à S3)

## Dispositif

| Élément | Valeur |
|---|---|
| Cluster | 2 shards (`shard1`, `shard2`, chacun un Replica Set de 3 nœuds), 3 config servers, 1 `mongos` — `infra/docker-compose.shard.yml` |
| Ressources | 10 conteneurs, cache WiredTiger 0,25 Go et 768 Mo de RAM par nœud ; le Replica Set `rs0` est arrêté pendant l'expérience |
| Données | **1 000 000 de documents par clé**, générateur v2, 2 000 camions, `SEED=42` (mêmes trajectoires pour les 3 clés), 4 processus, `w:"majority"`, via `mongos` |
| Chunk size | **4 Mo** au lieu de 128 Mo : depuis MongoDB 6, le balancer ne déplace des données que si l'écart entre shards dépasse 3 chunks ; avec 300 Mo de données par clé, rien ne bougerait avec la valeur par défaut |
| Scripts | `bash infra/scripts/shard-experiment.sh 1000000 region hashed vehicle_ts` (chargement + attente de l'équilibrage) puis `python -m queries.shard_report` |
| Résultats bruts | `report/data/shard_experiment.txt`, `shard_report.{txt,json}`, `shard_jumbo_demo.txt` |

Trois clés comparées (section 8 du plan, plus une clé réaliste) :

| Clé | Type | Commande |
|---|---|---|
| `region` | plage, 12 valeurs | `sh.shardCollection("fleet_region.telemetry", { region: 1 })` |
| `vehicle_id` haché | hachage | `sh.shardCollection("fleet_hashed.telemetry", { vehicle_id: "hashed" })` |
| `vehicle_id` + `ts` | plage composée | `sh.shardCollection("fleet_vehicle_ts.telemetry", { vehicle_id: 1, ts: 1 })` |

## 1. Chargement (débit à travers mongos)

| Clé | Durée | Débit | `insert_many` | Erreurs |
|---|---|---|---|---|
| `region` | 149 s | **6 698 msg/s** | 81 ms | 0 |
| `vehicle_id` haché | 162 s | **6 189 msg/s** | 97 ms | 0 |
| `{vehicle_id, ts}` | 203 s | **4 929 msg/s** | 98 ms | 0 |

Avec une clé **par plage**, la collection vide commence par un seul chunk sur un seul shard :
toutes les écritures y vont, puis le balancer découpe et déplace des plages **pendant** le
chargement (migrations = lectures, copies, suppressions en plus). Avec la clé **hachée**, MongoDB
pré-découpe l'espace des valeurs dès la création (2 chunks par shard) : les écritures sont
réparties dès le premier document. L'écart reste modéré ici parce que 4 processus écrivent en
parallèle sur 2 shards seulement et que les nœuds partagent la même machine.

## 2. Répartition des données (après équilibrage et nettoyage des orphelins)

| Clé | shard1 | shard2 | Chunks (shard1 / shard2) | Jumbo |
|---|---|---|---|---|
| `region` | 500 937 docs (50,1 %) | 499 063 docs (49,9 %) | 7 (5 / 2) | voir § 4 |
| `vehicle_id` haché | 505 000 (50,5 %) | 495 000 (49,5 %) | 4 (2 / 2) | 0 |
| `{vehicle_id, ts}` | 507 559 (50,8 %) | 492 441 (49,2 %) | 6 (1 / 5) | 0 |

Plages de la clé `region` :

| Chunk | Shard | Régions |
|---|---|---|
| [MinKey ; Kairouan[ … [Monastir ; Nabeul[ (5 chunks) | shard1 | Beja, Bizerte, Gabes, Gafsa, Kairouan, Kasserine, Kef, Monastir |
| [Nabeul ; Tunis[ | shard2 | Nabeul, Sfax, Sousse |
| [Tunis ; MaxKey[ | shard2 | Tunis |

Avec **2 shards**, les trois clés finissent équilibrées à ±1 % : le balancer a pu regrouper les
régions en deux paquets de taille voisine. **L'équilibre en volume ne dit pas tout** : les
problèmes de `region` apparaissent dans le ciblage des requêtes et dans la capacité à grandir.

Remarque de méthode : juste après le chargement, `$collStats` comptait 1 065 476 documents pour
`region` et 1 069 707 pour `{vehicle_id, ts}`. La différence correspond aux **documents
orphelins** : après une migration, l'ancien shard garde une copie des documents déplacés,
effacée après `orphanCleanupDelaySecs` (900 s). Les requêtes via `mongos` les ignorent ; les
chiffres ci-dessus ont été mesurés après le nettoyage (0 orphelin).

## 3. Ciblage des requêtes (S3)

`explain` via `mongos` donne les shards interrogés ; temps = médiane de 3 exécutions.

| Requête | `region` | `vehicle_id` haché | `{vehicle_id, ts}` |
|---|---|---|---|
| Statistiques de **Tunis** (1 h) | **1 shard** — 239 ms | 2 shards — 337 ms | 2 shards — 367 ms |
| **Historique d'un camion** (100 derniers) | 2 shards — 194 ms | **1 shard — 11 ms** | **1 shard — 2 ms** |
| Vitesse par région, toutes régions (1 h) | 2 shards — 764 ms | 2 shards — 878 ms | 2 shards — 909 ms |

- Une requête qui contient la shard key (égalité ou plage sur son préfixe) est **ciblée** : `mongos`
  ne l'envoie qu'au shard concerné. Sinon elle est **diffusée** à tous les shards
  (*scatter-gather*) et `mongos` fusionne les réponses.
- `region` cible les statistiques d'une région, mais **diffuse** l'historique d'un camion
  (un camion traverse plusieurs régions) : 194 ms au lieu de 2 à 11 ms.
- `{vehicle_id, ts}` est la plus rapide pour l'historique d'un camion : les messages d'un camion
  sont contigus et déjà triés par date sur un seul shard (index de la shard key).
- La vue d'ensemble (toutes les régions) est diffusée avec toutes les clés : avec 2 shards, le
  surcoût est faible ; il croît avec le nombre de shards.

## 4. Pourquoi `region` est une mauvaise shard key (démonstration)

Un chunk ne peut être découpé qu'**entre deux valeurs différentes** de la clé. Tunis compte
143 822 documents (≈ 43 Mo, soit 10 fois la taille de chunk) :

```
> db.adminCommand({ split: "fleet_region.telemetry", find: { region: "Tunis" } })
  REFUSÉ : Unable to find median in chunk because chunk is indivisible.
> db.adminCommand({ moveChunk: "fleet_region.telemetry", find: { region: "Tunis" }, to: "shard1" })
  REFUSÉ : Cannot move chunk: the maximum number of documents for a chunk is 26800 […]
           Found 143822 documents in chunk
```

Le chunk de Tunis est **indivisible et intransportable** : c'est un chunk *jumbo*. Conséquences :

- **12 chunks utiles au maximum** : au-delà de 12 shards, les shards supplémentaires restent vides ;
  en pratique beaucoup moins, car Tunis, Sousse et Sfax pèsent 3 à 4 fois plus que Bizerte ou Kef.
- **Point chaud (*hot spot*)** : en temps réel, toutes les écritures d'une région vont au même
  shard ; ici shard2 reçoit Nabeul, Sfax, Sousse et Tunis, soit 50 % du trafic sur 4 régions.
  Si l'activité de Tunis double, rien ne peut la répartir.
- Le choix était **volontairement mauvais** (plan, correction n° 6) pour illustrer ce problème.

À l'inverse, `vehicle_id` a 2 000 valeurs (5 000 en production) et `{vehicle_id, ts}` une
cardinalité quasi illimitée : les chunks peuvent toujours être découpés.

## 5. Conclusion

| Critère | `region` | `vehicle_id` haché | `{vehicle_id, ts}` |
|---|---|---|---|
| Cardinalité | 12 ❌ | 2 000 ✅ | illimitée ✅ |
| Répartition des écritures dès le départ | non (1 chunk au départ, puis points chauds) | **oui (pré-découpage)** ✅ | non au départ, puis bonne |
| Débit de chargement mesuré | 6 698 msg/s | 6 189 msg/s | 4 929 msg/s |
| Requête « une région » | **ciblée** ✅ | diffusée | diffusée |
| Requête « un camion » | diffusée ❌ | **ciblée** ✅ | **ciblée et triée** ✅ |
| Capacité à grandir | bloquée (jumbo, 12 chunks max) ❌ | ✅ | ✅ |

**Choix recommandé pour la télémétrie : `{ vehicle_id: "hashed" }`** (ou `{vehicle_id, ts}` si
l'historique par camion est la requête principale). Les deux répartissent la charge et ciblent les
requêtes par camion ; les statistiques par région sont diffusées, ce qui reste acceptable car
elles sont moins fréquentes et peuvent être servies par des pré-agrégations. Ne jamais utiliser
`ts` seul (clé croissante : toutes les insertions dans le dernier chunk, donc un seul shard).

Limites : 2 shards seulement sur une même machine (pas de latence réseau), chunk size réduite
pour l'expérience, 1 M de documents par clé.
