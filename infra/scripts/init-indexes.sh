#!/usr/bin/env bash
# Crée les index de telemetry (init-indexes.js) sur le primaire et mesure leur coût.
#   bash infra/scripts/init-indexes.sh                  # index du plan
#   INDEX_SET=extra bash infra/scripts/init-indexes.sh  # + index ajoutés après mesure
#   DB_NAME=fleet_bench bash infra/scripts/init-indexes.sh
set -euo pipefail
export MSYS_NO_PATHCONV=1

RS_URI="mongodb://mongo1:27017,mongo2:27017,mongo3:27017/?replicaSet=rs0"

docker exec -e DB_NAME="${DB_NAME:-fleet}" -e INDEX_SET="${INDEX_SET:-plan}" \
  mongo1 mongosh --quiet "$RS_URI" /scripts/init-indexes.js
