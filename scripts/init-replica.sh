#!/bin/bash
# Initialise le Replica Set rs0 (idempotent : sans effet s'il existe déjà).
set -e

mongosh --host mongo1:27017 --quiet --eval '
let initialized = true;
try {
  rs.status();
} catch (e) {
  initialized = false;
}

if (initialized) {
  print("Replica Set déjà initialisé.");
} else {
  printjson(rs.initiate({
    _id: "rs0",
    members: [
      { _id: 0, host: "mongo1:27017", priority: 2 },
      { _id: 1, host: "mongo2:27017", priority: 1 },
      { _id: 2, host: "mongo3:27017", priority: 1 }
    ]
  }));
  print("Replica Set initialisé.");
}
'

# Attend l'élection d'un primaire
for i in $(seq 1 30); do
  PRIMARY=$(mongosh --host mongo1:27017 --quiet --eval 'db.hello().primary' 2>/dev/null || true)
  if [ -n "$PRIMARY" ] && [ "$PRIMARY" != "undefined" ]; then
    echo "Primaire élu : $PRIMARY"
    exit 0
  fi
  sleep 2
done

echo "Aucun primaire élu après 60 s" >&2
exit 1
