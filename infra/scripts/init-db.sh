#!/usr/bin/env bash
# Crée les collections et validateurs (init-db.js) sur le primaire.
# Lancement depuis la racine du dépôt : bash infra/scripts/init-db.sh
set -euo pipefail
export MSYS_NO_PATHCONV=1

RS_URI="mongodb://mongo1:27017,mongo2:27017,mongo3:27017/?replicaSet=rs0"

docker exec mongo1 mongosh --quiet "$RS_URI" /scripts/init-db.js
