# Tests de tolérance aux pannes — Replica Set rs0

**Date** : 10/11/2026, PC de A (Docker Desktop, 3 nœuds `mongo:7` sur une machine).
**Outil** : `infra/scripts/failover-scenarios.sh` + sonde `infra/scripts/failover_probe.py`
(1 écriture `w:"majority"` toutes les 100 ms pendant 45 s ; panne à t ≈ 8 s, retour à t ≈ 25 s).
**Données brutes** : `report/data/failover/<scenario>-run<N>.json` et `.log`.

Relancer un scénario :

```bash
bash infra/scripts/failover-scenarios.sh s1-kill 1
```

## Synthèse

| Scénario | Commande | Interruption des écritures | Écritures échouées | Écritures confirmées perdues | Resynchronisation |
|---|---|---|---|---|---|
| **1a** Arrêt propre du primaire (×3) | `docker stop <primaire>` | **0,58 s** (0,59 / 0,59 / 0,55) | 0 | **0** | 2,0 – 3,2 s |
| **1b** Crash du primaire (×3) | `docker kill <primaire>` | **11,5 s** (11,37 / 12,44 / 10,61) | 4 – 5 | **0** | 2,0 – 3,2 s |
| **2** Arrêt d'un secondaire | `docker stop <secondaire>` | aucune (0,10 s = pas de la sonde) | 0 | **0** | 2,0 s |
| **3** Perte de 2 nœuds sur 3 | `docker stop <sec1> <sec2>` | **30,7 s** = toute la durée de la panne + élection au retour | 10 | **0** | 11,6 s (élection comprise) |
| **4** Retour d'un nœud après ~20 s d'écritures | `docker start <nœud>` | aucune | 0 | **0** | **3,2 s** |

## Analyse

### Scénario 1 : arrêt propre vs crash du primaire

L'écart (0,6 s contre 11,5 s) vient de la **détection** de la panne, pas de l'élection :

- `docker stop` envoie SIGTERM : le primaire se retire lui-même (*stepdown*) et demande à un
  secondaire à jour de se présenter immédiatement (*election handoff*). Le client ne voit
  qu'une demi-seconde d'interruption, absorbée par `retryWrites`.
- `docker kill` envoie SIGKILL : personne ne prévient les secondaires. Ils attendent de ne plus
  recevoir de *heartbeat* pendant `electionTimeoutMillis` (**10 s** par défaut) avant de lancer
  l'élection. L'élection elle-même dure ensuite environ 1 s.

Réglage possible : réduire `settings.electionTimeoutMillis` accélère la bascule, mais augmente le
risque d'élections inutiles sur un réseau lent (compromis disponibilité / stabilité).

**Aucune écriture confirmée n'a été perdue** (`acked_but_lost = 0` sur tous les essais) : avec
`w:"majority"`, une écriture confirmée est déjà sur 2 nœuds, donc sur le futur primaire.
Les 4 ou 5 écritures **échouées** du crash ont été signalées en erreur au client
(`AutoReconnect`, `ServerSelectionTimeoutError`), qui sait qu'il doit les rejouer.

### Scénario 2 : arrêt d'un secondaire

Il reste 2 nœuds sur 3, soit la majorité : le primaire continue et `w:"majority"` est satisfait
par le secondaire restant. Aucune interruption.

### Scénario 3 : perte de 2 nœuds

Chronologie relevée (run 1) :

| Instant | Événement |
|---|---|
| t ≈ 8 s | `docker stop mongo2 mongo3` |
| t ≈ 10,4 s | dernière écriture confirmée : `w:"majority"` ne peut plus être atteint |
| +5 s après la panne | `mongo1` est **encore PRIMARY** |
| +14 s après la panne | `mongo1` est passé **SECONDARY** : il ne voit plus de majorité et se retire |
| t ≈ 29 s | `docker start mongo2 mongo3` |
| t ≈ 41 s | nouveau primaire élu, les écritures reprennent |

Le nœud seul refuse d'être primaire **par conception** : s'il acceptait des écritures sans
majorité, une partition réseau pourrait produire deux primaires (*split brain*) et des données
divergentes. Pendant ces ~10 s où il était encore primaire, les écritures `w:"majority"`
attendaient sans être confirmées (`WriteConcernError`) : elles n'ont pas été comptées comme
réussies.

### Scénario 4 : resynchronisation

Après ~20 s d'arrêt pendant lesquelles ~200 écritures ont eu lieu, le nœud relancé rattrape son
retard en lisant l'**oplog** du primaire et redevient un secondaire à jour en **3,2 s**.
L'oplog doit donc être assez grand pour couvrir la durée de la panne (sinon : resynchronisation
complète, *initial sync*).

## Limites de l'expérience

- Les 3 nœuds sont sur la même machine : latence réseau quasi nulle, panne de la machine = perte
  des 3 nœuds.
- Charge faible (10 écritures/s) : à refaire pendant une ingestion du générateur v2 pour la démo.
