#!/usr/bin/env bash
# Initialise le cluster shardé : config servers, 2 shards, enregistrement dans mongos.
# Idempotent. Lancement depuis la racine du dépôt : bash infra/scripts/init-shard.sh
set -euo pipefail
export MSYS_NO_PATHCONV=1

# initiate <conteneur> <port> <replSet> <membres...> [--configsvr]
initiate() {
  local node="$1" port="$2" rs="$3"; shift 3
  local cfg="false" members="" i=0
  for m in "$@"; do
    if [ "$m" = "--configsvr" ]; then cfg="true"; continue; fi
    members+="{_id:$i,host:'$m:$port'},"; i=$((i + 1))
  done
  docker exec "$node" mongosh --quiet --port "$port" --eval "
    try { rs.status(); print('$rs : déjà initialisé'); }
    catch (e) { rs.initiate({_id:'$rs', configsvr:$cfg, members:[${members%,}]}); print('$rs : initialisé'); }"
}

wait_primary() {
  local node="$1" port="$2" rs="$3"
  for _ in $(seq 1 30); do
    if [ "$(docker exec "$node" mongosh --quiet --port "$port" --eval \
         "try { rs.isMaster().primary ? 'ok' : '' } catch (e) { '' }")" = "ok" ]; then
      echo "$rs : primaire élu"; return 0
    fi
    sleep 2
  done
  echo "$rs : pas de primaire après 60 s" >&2; return 1
}

initiate cfg1 27019 cfgrs cfg1 cfg2 cfg3 --configsvr
initiate sh1a 27018 shard1 sh1a sh1b sh1c
initiate sh2a 27018 shard2 sh2a sh2b sh2c

wait_primary cfg1 27019 cfgrs
wait_primary sh1a 27018 shard1
wait_primary sh2a 27018 shard2

# mongos peut mettre quelques secondes à joindre les config servers
for _ in $(seq 1 30); do
  docker exec mongos mongosh --quiet --eval "db.adminCommand('ping').ok" >/dev/null 2>&1 && break
  sleep 2
done

docker exec mongos mongosh --quiet --eval "
  const existing = db.adminCommand({ listShards: 1 }).shards.map(s => s._id);
  for (const [id, hosts] of [['shard1', 'shard1/sh1a:27018,sh1b:27018,sh1c:27018'],
                             ['shard2', 'shard2/sh2a:27018,sh2b:27018,sh2c:27018']]) {
    if (existing.includes(id)) { print(id + ' : déjà ajouté'); }
    else { sh.addShard(hosts); print(id + ' : ajouté'); }
  }
  sh.enableSharding('fleet');
  print('Shards : ' + db.adminCommand({ listShards: 1 }).shards.map(s => s._id + ' (' + s.host + ')').join(', '));
"
