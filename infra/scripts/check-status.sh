#!/usr/bin/env bash
# État complet du cluster : nœuds, retard de réplication, volumes de données.
# Lancement depuis la racine du dépôt : bash infra/scripts/check-status.sh
# Pour le rapport : bash infra/scripts/check-status.sh > infra/rs-status.txt
set -euo pipefail
export MSYS_NO_PATHCONV=1

RS_URI="mongodb://mongo1:27017,mongo2:27017,mongo3:27017/?replicaSet=rs0"

echo "=== Conteneurs ==="
docker ps -a --filter "name=mongo" --format "table {{.Names}}\t{{.Status}}"
echo

docker exec mongo1 mongosh --quiet "$RS_URI" --eval '
const st = rs.status();
print("=== Replica Set " + st.set + " (" + new Date().toISOString() + ") ===");
const primary = st.members.find(m => m.stateStr === "PRIMARY");
for (const m of st.members) {
  const lagS = primary && m.optimeDate
    ? ((primary.optimeDate - m.optimeDate) / 1000).toFixed(1) + " s"
    : "-";
  print(
    m.name.padEnd(16) + m.stateStr.padEnd(12) +
    "health=" + m.health + "  retard=" + lagS +
    (m.stateStr === "PRIMARY" ? "  (élu " + m.electionDate.toISOString() + ")" : "")
  );
}

print("\n=== Base fleet ===");
const fleet = db.getSiblingDB("fleet");
const MB = 1024 * 1024;
for (const name of fleet.getCollectionNames().sort()) {
  const s = fleet.runCommand({ collStats: name });
  print(
    name.padEnd(16) +
    ("docs=" + s.count).padEnd(16) +
    "données=" + (s.size / MB).toFixed(1) + " Mo  " +
    "disque=" + (s.storageSize / MB).toFixed(1) + " Mo  " +
    "index=" + (s.totalIndexSize / MB).toFixed(1) + " Mo (" + s.nindexes + ")"
  );
}
'
