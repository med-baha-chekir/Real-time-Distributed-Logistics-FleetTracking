# Rapport — partie technique (A) : brouillon

> Brouillon à intégrer au rapport LaTeX. Les chiffres viennent de `report/mesures.md`.

## 1. Architecture

```
                         PC de A (Docker Desktop / WSL2)
 ┌──────────────────────────────────────────────────────────────────────┐
 │  réseau fleet-net                                                    │
 │                                                                      │
 │  [generator] ──insert_many (lots 500-1000, w:majority)──┐            │
 │                                                         ▼            │
 │                         ┌──────── Replica Set rs0 ────────┐          │
 │  [dashboard] ──lectures─▶ mongo1     mongo2     mongo3    │          │
 │                         │ PRIMARY ─▶ SECONDARY  SECONDARY │          │
 │                         └─────────── réplication ─────────┘          │
 │  [tools] : failover_probe, bench_write, explain_baseline             │
 └──────────────────────────────────────────────────────────────────────┘
   ports publiés sur 127.0.0.1 uniquement : 27017, 27018, 27019
```

Un second environnement, séparé, sert à l'expérience de sharding
(`docker-compose.shard.yml`) : 3 config servers, 2 shards de 3 nœuds, 1 `mongos`.

**Choix « tout sur un PC »** : le cluster réparti sur deux machines (Tailscale) apporterait
de la latence réseau qui fausserait les mesures (débit, temps d'élection) et un risque de
panne pendant la démonstration. Le Replica Set à 3 nœuds sur une machine démontre les
mêmes mécanismes (élection, majorité, resynchronisation). Limite assumée : une panne de
la machine hôte arrête les 3 nœuds ; en production chaque nœud serait sur un serveur
(idéalement une zone) différent.

**Ressources** : chaque `mongod` est limité à 0,5 Go de cache WiredTiger et 1 Go de mémoire
conteneur ; la VM WSL2 de Docker dispose de 16 Go.

## 2. Replica Set

- 3 membres votants de même priorité ⇒ majorité = 2. Le cluster tolère la perte d'**un** nœud.
- Écritures du générateur en `w: "majority"` : une écriture n'est confirmée qu'une fois
  présente sur 2 nœuds, elle survit donc à la perte du primaire (pas de *rollback*).
- Les clients se connectent avec `replicaSet=rs0` : le driver découvre la topologie et suit
  le primaire après une élection ; `retryWrites` (activé par défaut) rejoue une fois une
  écriture interrompue par la bascule.

### Deux sortes de panne du primaire

| Panne | Mécanisme | Interruption attendue |
|---|---|---|
| Arrêt propre (`docker stop`, SIGTERM) | Le primaire se retire (*stepdown*) et désigne lui-même un secondaire à jour (*election handoff*) | < 1 s |
| Crash (`docker kill`, SIGKILL) | Les secondaires ne reçoivent plus de *heartbeat* ; ils attendent `electionTimeoutMillis` (10 s par défaut) avant d'élire | ≈ 10–12 s |

C'est le résultat le plus parlant des tests de panne : la durée d'indisponibilité dépend
surtout de la **détection** de la panne, pas de l'élection elle-même.

### Perte de deux nœuds

Le nœud restant ne voit plus de majorité : il redevient SECONDARY et **refuse les écritures**
(aucun primaire). C'est voulu : accepter des écritures sans majorité permettrait deux
primaires en cas de partition réseau (*split brain*). Les lectures restent possibles avec
`readPreference=secondaryPreferred`.

## 3. Validation de schéma

MongoDB n'impose pas de schéma ; un bug du générateur (date en chaîne, lat/lng inversées)
passerait inaperçu jusqu'aux agrégations. Un validateur `$jsonSchema`
(`validationAction: "error"`) est posé sur les 3 collections :

- `ts` de type `date` (sinon les fenêtres temporelles et les tris ne marchent pas) ;
- `location` : GeoJSON `Point` avec longitude ∈ [7, 12] et latitude ∈ [30, 38] — une
  inversion lat/lng est rejetée dès l'insertion ;
- champs de mesure numériques avec bornes (vitesse ∈ [0, 160], carburant ∈ [0, 100]) ;
- `vehicle_id` au format `VH-000123`.

Coût : la validation est faite à chaque écriture ; à mesurer (débit avec et sans validateur).

## 4. Index (plan, mesuré au sprint 3)

| Collection | Index | Requêtes servies |
|---|---|---|
| telemetry | `{ vehicle_id: 1, ts: -1 }` | historique d'un camion |
| telemetry | `{ region: 1, ts: -1 }` | statistiques régionales récentes (a) |
| telemetry | `{ ts: -1 }` | fenêtres temporelles (b, d, e), heure de référence |
| telemetry | `{ location: "2dsphere" }` | zone (12.3) |
| vehicle_state | `{ location: "2dsphere" }` | carte, rayon (12.1), polygone (12.2) — créé dès le départ |

Protocole : `explain("executionStats")` de chaque requête **sans** index secondaire sur
`telemetry` (`report/explain/before/`), puis **avec** (`report/explain/after/`) ; on compare
`executionTimeMillis`, `totalDocsExamined`, `totalKeysExamined` et l'étape (COLLSCAN → IXSCAN).

Compromis à discuter : chaque index accélère les lectures mais ralentit l'ingestion
(un index de plus à mettre à jour par document) et occupe de la RAM/disque. On mesurera le
débit d'ingestion avant/après index.

**Heure de référence** : les fenêtres « dernière heure » sont calculées par rapport au `ts`
le plus récent en base, et non à `Date.now()`, pour rester valides sur des données générées
en différé.

## 5. Sharding : choix de la shard key

| Clé | Cardinalité | Répartition des écritures | Requêtes par région | Verdict |
|---|---|---|---|---|
| `{ region: 1 }` | 12 valeurs | déséquilibrée (Tunis, Sfax concentrent le trafic) | ciblées sur 1 shard | **mauvais choix, volontaire** |
| `{ vehicle_id: "hashed" }` | 5 000 | uniforme | diffusées à tous les shards (*scatter-gather*) | bon pour l'ingestion |
| `{ vehicle_id: 1, ts: 1 }` | très élevée | bonne (beaucoup de camions écrivent en parallèle) | diffusées | réaliste pour l'historique d'un camion |

**Pourquoi `region` est mauvaise** : un chunk ne peut être découpé qu'entre deux valeurs
différentes de la clé. Avec 12 régions, il ne peut exister au plus que 12 chunks utiles ; une
région très active donne un chunk qui grossit sans pouvoir être coupé (*jumbo chunk*), que le
*balancer* ne peut plus déplacer. Toutes les écritures de cette région frappent le même shard
(*hot spot*) : ajouter des shards n'apporte rien.

**Pourquoi éviter `{ ts: 1 }` seul** : clé monotone croissante, toutes les insertions vont dans
le dernier chunk, donc sur un seul shard.

Mesures prévues : `getShardDistribution()` et `sh.status()` après chargement du même jeu de
données avec chaque clé ; temps des requêtes a (par région) et historique d'un camion.
