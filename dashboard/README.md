# Dashboard — suivi de flotte en quasi temps réel

Streamlit + Plotly + PyDeck. Lit MongoDB (Replica Set `rs0`) et réutilise les requêtes mesurées
de `queries/pipelines.py`.

## Lancer

```bash
# cluster démarré (infra/README.md), puis :
docker compose -f infra/docker-compose.rs.yml --profile app up -d --build dashboard
# → http://localhost:8501
```

Autre base (par exemple la base de démonstration alimentée en direct) :

```bash
DB_NAME=fleet_demo docker compose -f infra/docker-compose.rs.yml --profile app up -d dashboard
```

Sans Docker (depuis la racine du dépôt, Python 3.11+) :
`pip install -r dashboard/requirements.txt` puis `streamlit run dashboard/app.py`
(avec `MONGO_URI` pointant vers un nœud joignable).

## Contenu de la page

| # | Section | Source | Rafraîchissement |
|---|---|---|---|
| D7 | État du Replica Set (PRIMARY / SECONDARY / injoignable), message de reconnexion | `replSetGetStatus` | 5–30 s (réglable) |
| D2 | Indicateurs : camions actifs, vitesse moyenne, consommation moyenne (5 min), surchauffe en cours, alertes 24 h | `vehicle_state`, `telemetry`, pipeline d | 5–30 s |
| D1 | Carte des 2 000 camions sur les itinéraires réels (vert : en route, gris : arrêt, rouge : surchauffe) | `vehicle_state` (pas `telemetry`) | 5–30 s |
| D3 | Vitesse moyenne par région | pipeline a | 30 s |
| D4 | Distribution des vitesses | pipeline e | 30 s |
| D5 | Camions en alerte de surchauffe, avec région et température actuelles | pipeline d + `vehicle_state` | 30 s |
| D6 | Recherche géographique : camions dans un rayon autour d'une ville ou d'un point | `$geoNear` (index 2dsphere de `vehicle_state`) | à la demande |

Rafraîchissement par requêtes périodiques (`st.fragment(run_every=…)`), sans connexion push.

## « Les camions ne bougent pas »

Le dashboard n'affiche que ce qui est **dans la base** : les camions bougent seulement si le
générateur tourne en mode **temps réel** sur la même base. La base `fleet` contient le jeu de
référence de 5 M de documents (mode backfill, terminé) : ses camions sont figés à leur dernière
position. Dans ce cas, la page affiche « ⏸️ Aucun nouveau message depuis … ».

Pour les voir rouler (base `fleet_demo`, sans toucher au jeu de référence) :

```bash
docker compose -f infra/docker-compose.rs.yml --profile app run -d --name fleet-demo-generator \
    -e DB_NAME=fleet_demo generator python -m generator.main --mode realtime --trucks 2000 --duration 0
DB_NAME=fleet_demo docker compose -f infra/docker-compose.rs.yml --profile app up -d dashboard
# arrêt : docker stop fleet-demo-generator && docker rm fleet-demo-generator
```

À l'échelle du pays, un camion ne parcourt que 200 à 250 m entre deux rafraîchissements
(10 s à 80–90 km/h) : **zoomer sur une ville** (molette ou « + ») pour voir le mouvement, ou
régler le rafraîchissement à 5 s dans la barre latérale.

## Résistance aux pannes (D7)

- Lecture en **`readPreference: primaryPreferred`** : si le primaire tombe, les lectures passent
  aussitôt sur un secondaire ; la page continue d'afficher des données pendant l'élection
  (« ⏳ Élection en cours — lectures servies par un secondaire »).
- Délais courts (3 s) : une panne est signalée vite. Si aucun nœud ne répond, la page affiche
  « ⚠️ Cluster injoignable… reconnexion », garde les **dernières données reçues** (heure
  indiquée) et ne lance plus les autres requêtes ; elle repart seule au retour du cluster.

Vérifié le 21/11/2026 (générateur à 2 000 camions en direct) :

| Panne | Affichage |
|---|---|
| `docker kill` du primaire | +4 s : nœud « not reachable », « Élection en cours », données toujours affichées ; +12 s : nouveau PRIMARY ; +22 s : nouvelles données |
| Arrêt des 3 nœuds | message de reconnexion, nœuds « état inconnu », « Aucun nœud ne répond », dernière carte et derniers indicateurs conservés |
| Redémarrage des nœuds | retour automatique (nouveau PRIMARY, données fraîches) sans recharger la page |

## Scénario de démonstration

```bash
DB_NAME=fleet_demo bash infra/scripts/init-db.sh
DB_NAME=fleet_demo INDEX_SET=extra bash infra/scripts/init-indexes.sh
docker compose -f infra/docker-compose.rs.yml --profile app run -d --name demo-gen -e DB_NAME=fleet_demo \
    generator python -m generator.main --mode realtime --trucks 2000 --duration 1800
DB_NAME=fleet_demo docker compose -f infra/docker-compose.rs.yml --profile app up -d dashboard
# ouvrir http://localhost:8501, puis pendant la démo :
bash infra/scripts/check-status.sh      # repérer le PRIMARY
docker kill <primaire>                  # observer l'élection sur le dashboard
docker start <primaire>
```

La base `fleet_demo` évite de modifier le jeu de référence `fleet` (5 M de documents utilisés
pour les mesures).

## Fichiers

| Fichier | Rôle |
|---|---|
| `app.py` | Page Streamlit (sections, rafraîchissement, gestion des pannes) |
| `data.py` | Requêtes MongoDB → DataFrames, testables sans Streamlit |
| `tests/test_data.py` | 8 tests (statuts, indicateurs, histogramme, tracés, read preference) |
| `Dockerfile` | Image `fleet-dashboard` (contexte de build : racine du dépôt) |
