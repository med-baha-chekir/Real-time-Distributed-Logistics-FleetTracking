#!/usr/bin/env bash
# Expérience de sharding (tâches S1 à S3) : même jeu de données chargé avec 3 shard keys.
#
#   docker compose -f infra/docker-compose.shard.yml up -d && bash infra/scripts/init-shard.sh
#   bash infra/scripts/shard-experiment.sh [docs] [clés...]
#   ex. bash infra/scripts/shard-experiment.sh 1000000 region hashed vehicle_ts
#
# Pour chaque clé : base fleet_<clé> recréée, collection telemetry shardée, chargement par
# le générateur v2 (backfill, 2 000 camions, SEED=42 : mêmes trajectoires pour les 3 clés)
# via mongos, puis attente de l'équilibrage. Rapport final : queries/shard_report.py.
#
# Taille de chunk réduite à CHUNK_MB (4 Mo par défaut au lieu de 128 Mo) : depuis MongoDB 6,
# le balancer ne déplace des données que si l'écart entre shards dépasse 3 chunks ; avec
# quelques centaines de Mo, rien ne bougerait avec la valeur par défaut.
# Résultats : report/data/shard_experiment.txt, report/data/shard_report.json
set -euo pipefail
export MSYS_NO_PATHCONV=1

DOCS="${1:-1000000}"; shift || true
KEYS=("${@:-region hashed vehicle_ts}")
read -r -a KEYS <<< "${KEYS[*]}"
CHUNK_MB="${CHUNK_MB:-4}"
OUT=report/data/shard_experiment.txt
REPO_WIN="$(pwd -W 2>/dev/null || pwd)"

declare -A KEY_SPEC=(
  [region]='{ region: 1 }'
  [hashed]='{ vehicle_id: "hashed" }'
  [vehicle_ts]='{ vehicle_id: 1, ts: 1 }'
)

mongos_eval() { docker exec mongos mongosh --quiet --eval "$1"; }

mkdir -p report/data
{
  echo "# Expérience de sharding — $(date -u +%FT%TZ)"
  echo "# $DOCS documents par clé, 2 000 camions, 4 processus, w:majority, chunk size $CHUNK_MB Mo"
  echo "# 2 shards (Replica Sets de 3 nœuds), 3 config servers, 1 mongos"
} > "$OUT"

mongos_eval "db.getSiblingDB('config').settings.updateOne({_id: 'chunksize'}, {\$set: {value: $CHUNK_MB}}, {upsert: true}); print('chunk size = $CHUNK_MB Mo')"

for key in "${KEYS[@]}"; do
  spec="${KEY_SPEC[$key]}"
  echo | tee -a "$OUT"
  echo "=== Clé $key : $spec ===" | tee -a "$OUT"
  mongos_eval "
    const d = db.getSiblingDB('fleet_$key'); d.dropDatabase();
    sh.enableSharding('fleet_$key');
    sh.shardCollection('fleet_$key.telemetry', $spec);
    print('fleet_$key.telemetry shardée sur ' + JSON.stringify($spec));" | tee -a "$OUT"

  t0=$(date +%s)
  log=$(docker run --rm --network fleet-shard-net \
          -e MONGO_URI=mongodb://mongos:27017 -e DB_NAME="fleet_$key" fleet-generator \
          python -m generator.main --mode backfill --docs "$DOCS" --trucks 2000 --workers 4 --no-weather 2>&1)
  echo "$log" | grep -E "^Documents insérés|^Durée|^Latence" | tee -a "$OUT"

  # Attente de l'équilibrage (15 min au plus)
  for i in $(seq 1 90); do
    ok=$(mongos_eval "db.adminCommand({balancerCollectionStatus: 'fleet_$key.telemetry'}).balancerCompliant")
    [ "$ok" = "true" ] && break
    sleep 10
  done
  echo "Équilibrage : conforme=$ok après $(( $(date +%s) - t0 )) s depuis le début du chargement" | tee -a "$OUT"
done

echo | tee -a "$OUT"
docker run --rm --network fleet-shard-net -v "$REPO_WIN:/work" -w /work \
  -e MONGO_URI=mongodb://mongos:27017 fleet-generator \
  python -m queries.shard_report "${KEYS[@]}" | tee -a "$OUT"
