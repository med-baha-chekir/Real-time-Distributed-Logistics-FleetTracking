#!/usr/bin/env bash
# Initialise le Replica Set rs0 puis attend l'élection d'un primaire.
# Idempotent. Lancement depuis la racine du dépôt : bash infra/scripts/init-rs.sh
set -euo pipefail
export MSYS_NO_PATHCONV=1   # Git Bash (Windows) : ne pas réécrire /scripts/...

docker exec mongo1 mongosh --quiet /scripts/init-rs.js

echo "Attente de l'élection d'un primaire..."
for _ in $(seq 1 30); do
  primary=$(docker exec mongo1 mongosh --quiet --eval \
    "try { rs.status().members.filter(m => m.stateStr === 'PRIMARY').map(m => m.name).join('') } catch (e) { '' }")
  if [ -n "$primary" ]; then
    echo "Primaire élu : $primary"
    exit 0
  fi
  sleep 2
done

echo "Aucun primaire après 60 s : vérifier 'docker compose logs'." >&2
exit 1
