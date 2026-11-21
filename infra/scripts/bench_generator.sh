#!/usr/bin/env bash
# Benchmark d'ingestion avec le VRAI générateur v2 (tâche A5).
#   bash infra/scripts/bench_generator.sh [docs_par_essai]
#
# Combinaisons : 2 000 / 5 000 camions  x  w:1 / w:"majority", 4 processus, lots de 500.
# Chaque essai repart d'une base vide "fleet_bench" (mêmes validateurs que fleet),
# pour ne pas modifier le jeu de données de référence de la base fleet.
# Résultats : report/data/bench_generator.txt
set -euo pipefail
export MSYS_NO_PATHCONV=1

DOCS="${1:-200000}"
DB=fleet_bench
OUT=report/data/bench_generator.txt
RS_URI="mongodb://mongo1:27017,mongo2:27017,mongo3:27017/?replicaSet=rs0"
COMPOSE="docker compose -f infra/docker-compose.rs.yml --profile app"

mkdir -p report/data
{
  echo "# Benchmark du générateur v2 — $(date -u +%FT%TZ)"
  echo "# $DOCS documents par essai, mode backfill, 4 processus, lots de 500, base $DB"
  printf "%-8s %-9s %-10s %-12s %-14s %-16s %s\n" camions w docs "durée (s)" "débit (msg/s)" "insert_many (ms)" "vehicle_state (ms)"
} > "$OUT"

for trucks in 2000 5000; do
  for wc in 1 majority; do
    # Base vide, validateurs recréés
    docker exec mongo1 mongosh --quiet "$RS_URI" --eval "db.getSiblingDB('$DB').dropDatabase()" >/dev/null
    DB_NAME=$DB bash infra/scripts/init-db.sh >/dev/null

    log=$($COMPOSE run --rm -e DB_NAME=$DB generator python -m generator.main \
            --mode backfill --docs "$DOCS" --trucks "$trucks" --workers 4 \
            --write-concern "$wc" --no-weather 2>&1)
    docs=$(echo "$log" | sed -n 's/^Documents insérés : \([0-9]*\).*/\1/p')
    errors=$(echo "$log" | sed -n 's/.*| Erreurs : \([0-9]*\) |.*/\1/p' | tail -1)
    dur=$(echo "$log" | sed -n 's/^Durée : \([0-9.]*\) s.*/\1/p')
    rate=$(echo "$log" | sed -n 's/.*Débit global : \([0-9]*\) msg\/s.*/\1/p')
    ins=$(echo "$log" | sed -n "s/^Latence moyenne d'un insert_many : \([0-9.]*\) ms.*/\1/p")
    st=$(echo "$log" | sed -n 's/.*vehicle_state : \([0-9.]*\) ms.*/\1/p')
    printf "%-8s %-9s %-10s %-12s %-14s %-16s %s\n" "$trucks" "$wc" "$docs" "$dur" "$rate" "$ins" "$st" | tee -a "$OUT"
    if [ "${errors:-0}" != "0" ]; then echo "  !! $errors erreurs" | tee -a "$OUT"; fi
  done
done

docker exec mongo1 mongosh --quiet "$RS_URI" --eval "db.getSiblingDB('$DB').dropDatabase()" >/dev/null
echo "Base $DB supprimée. Résultats : $OUT"
