#!/usr/bin/env bash
# Test de panne SOUS CHARGE (tâche A8) : le générateur v2 tourne en temps réel
# pendant qu'on lance un scénario de failover-scenarios.sh.
#
#   bash infra/scripts/failover-under-load.sh [scenario] [camions]
#   ex. bash infra/scripts/failover-under-load.sh s1-kill 2000
#
# Le générateur écrit dans la base "fleet_bench" (le jeu de référence fleet n'est
# pas modifié) ; la sonde écrit dans fleet.failover_probe comme d'habitude.
# Résultats : report/data/failover/<scenario>-runload.json / .log et load-generator-<scenario>.log
set -euo pipefail
export MSYS_NO_PATHCONV=1

SCENARIO="${1:-s1-kill}"
TRUCKS="${2:-2000}"
DB=fleet_bench
OUT=report/data/failover
GEN_LOG="$OUT/load-generator-${SCENARIO}.log"
RS_URI="mongodb://mongo1:27017,mongo2:27017,mongo3:27017/?replicaSet=rs0"

mkdir -p "$OUT"
docker start mongo1 mongo2 mongo3 >/dev/null
bash infra/scripts/init-rs.sh >/dev/null
docker exec mongo1 mongosh --quiet "$RS_URI" --eval "db.getSiblingDB('$DB').dropDatabase()" >/dev/null
DB_NAME=$DB bash infra/scripts/init-db.sh >/dev/null

echo "Générateur : $TRUCKS camions en temps réel (base $DB) pendant ~75 s"
docker compose -f infra/docker-compose.rs.yml --profile app run --rm -e DB_NAME=$DB generator \
  python -m generator.main --mode realtime --trucks "$TRUCKS" --duration 75 --no-weather \
  > "$GEN_LOG" 2>&1 &
GEN_PID=$!
sleep 15   # laisser le générateur atteindre son régime

bash infra/scripts/failover-scenarios.sh "$SCENARIO" load

wait "$GEN_PID" || true
echo
echo "=== Générateur pendant la panne ==="
grep -E "Bascule|Erreur|refusés|Documents insérés|Débit global|Latence" "$GEN_LOG" || true
echo
echo "=== Sonde ==="
grep -E "interruption|confirmées /|perdues" "$OUT/${SCENARIO}-runload.log" || true

docker exec mongo1 mongosh --quiet "$RS_URI" --eval "db.getSiblingDB('$DB').dropDatabase()" >/dev/null
