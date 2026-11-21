#!/usr/bin/env bash
# Coût des index sur l'ingestion (tâche I3).
#   bash infra/scripts/bench_index_cost.sh [docs_par_essai]
#
# Même ingestion (générateur v2, backfill, 2 000 camions, 4 processus, w:majority)
# dans une base vide "fleet_bench" avec 3 jeux d'index sur telemetry :
#   aucun (seulement _id)  /  index du plan (4)  /  plan + index ajoutés (7)
# Résultats : report/data/bench_index_cost.txt
set -euo pipefail
export MSYS_NO_PATHCONV=1

DOCS="${1:-500000}"
DB=fleet_bench
OUT=report/data/bench_index_cost.txt
RS_URI="mongodb://mongo1:27017,mongo2:27017,mongo3:27017/?replicaSet=rs0"
COMPOSE="docker compose -f infra/docker-compose.rs.yml --profile app"

mkdir -p report/data
{
  echo "# Coût des index sur l'ingestion — $(date -u +%FT%TZ)"
  echo "# $DOCS documents par essai, backfill, 2 000 camions, 4 processus, w:majority, base $DB"
  printf "%-16s %-8s %-10s %-12s %-14s %-17s %s\n" index nb docs "durée (s)" "débit (msg/s)" "insert_many (ms)" "taille index (Mo)"
} > "$OUT"

for set in none plan extra; do
  docker exec mongo1 mongosh --quiet "$RS_URI" --eval "db.getSiblingDB('$DB').dropDatabase()" >/dev/null
  DB_NAME=$DB bash infra/scripts/init-db.sh >/dev/null
  if [ "$set" != "none" ]; then
    DB_NAME=$DB INDEX_SET=$set bash infra/scripts/init-indexes.sh >/dev/null
  fi

  log=$($COMPOSE run --rm -e DB_NAME=$DB generator python -m generator.main \
          --mode backfill --docs "$DOCS" --trucks 2000 --workers 4 --no-weather 2>&1)
  docs=$(echo "$log" | sed -n 's/^Documents insérés : \([0-9]*\).*/\1/p')
  errors=$(echo "$log" | sed -n 's/^Documents insérés : [0-9]* | Erreurs : \([0-9]*\).*/\1/p')
  dur=$(echo "$log" | sed -n 's/^Durée : \([0-9.]*\) s.*/\1/p')
  rate=$(echo "$log" | sed -n 's/.*Débit global : \([0-9]*\) msg\/s.*/\1/p')
  ins=$(echo "$log" | sed -n "s/^Latence moyenne d'un insert_many : \([0-9.]*\) ms.*/\1/p")
  read -r nidx size <<< "$(docker exec mongo1 mongosh --quiet "$RS_URI" --eval \
    "const s=db.getSiblingDB('$DB').telemetry.stats(); print(s.nindexes + ' ' + (s.totalIndexSize/1048576).toFixed(1))")"
  printf "%-16s %-8s %-10s %-12s %-14s %-17s %s\n" "$set" "$nidx" "$docs" "$dur" "$rate" "$ins" "$size" | tee -a "$OUT"
  if [ "${errors:-0}" != "0" ]; then echo "  !! $errors erreurs" | tee -a "$OUT"; fi
done

docker exec mongo1 mongosh --quiet "$RS_URI" --eval "db.getSiblingDB('$DB').dropDatabase()" >/dev/null
echo "Base $DB supprimée. Résultats : $OUT"
