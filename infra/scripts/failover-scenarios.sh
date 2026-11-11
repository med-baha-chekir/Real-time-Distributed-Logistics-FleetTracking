#!/usr/bin/env bash
# Scénarios de panne automatisés, avec la sonde failover_probe.py en parallèle.
#
#   bash infra/scripts/failover-scenarios.sh <scenario> [numéro_de_run]
#
# Scénarios :
#   s1-stop   arrêt propre du primaire (docker stop = SIGTERM, le primaire se retire)
#   s1-kill   crash du primaire       (docker kill = SIGKILL, élection après timeout)
#   s2        arrêt d'un secondaire   (aucune interruption attendue)
#   s3        perte de 2 nœuds        (plus de majorité : écritures impossibles)
#   s4        retour d'un nœud        (mesure du temps de resynchronisation)
#
# Résultats : report/data/failover/<scenario>-run<N>.json, .log et .probe.log
set -euo pipefail
export MSYS_NO_PATHCONV=1

SCENARIO="${1:?usage: failover-scenarios.sh s1-stop|s1-kill|s2|s3|s4 [run]}"
RUN="${2:-1}"
LABEL="${SCENARIO}-run${RUN}"
COMPOSE="docker compose -f infra/docker-compose.rs.yml"
OUT="report/data/failover"
NODES=(mongo1 mongo2 mongo3)

PROBE_DURATION=45   # durée de la sonde (s)
T_FAIL=8            # instant de la panne (s après le début)
T_BACK=25           # instant du retour (s après le début)

mkdir -p "$OUT"
LOG="$OUT/${LABEL}.log"
: > "$LOG"

log() { echo "[$(date -u +%H:%M:%S.%3N)] $*" | tee -a "$LOG"; }

# Exécute du JS sur le premier nœud joignable
mongo_eval() {
  for n in "${NODES[@]}"; do
    if docker exec "$n" mongosh --quiet --eval "$1" 2>/dev/null; then return 0; fi
  done
  return 1
}

primary()     { mongo_eval "rs.status().members.filter(m=>m.stateStr==='PRIMARY').map(m=>m.name.split(':')[0]).join('')" || true; }
secondaries() { mongo_eval "rs.status().members.filter(m=>m.stateStr==='SECONDARY').map(m=>m.name.split(':')[0]).join(' ')" || true; }

# Attend que le nœud $1 soit de nouveau PRIMARY ou SECONDARY, à jour (retard <= 1 s)
wait_resync() {
  local node="$1" t0 now state
  t0=$(date +%s.%N)
  for _ in $(seq 1 120); do
    state=$(mongo_eval "const s=rs.status(); const p=s.members.find(m=>m.stateStr==='PRIMARY'); const m=s.members.find(x=>x.name.startsWith('$node:')); (m && p && ['PRIMARY','SECONDARY'].includes(m.stateStr) && p.optimeDate-m.optimeDate<=1000) ? 'ok' : 'wait'" || echo wait)
    if [ "$state" = "ok" ]; then
      now=$(date +%s.%N)
      log "$node resynchronisé (retard <= 1 s) en $(awk "BEGIN{printf \"%.1f\", $now - $t0}") s"
      return 0
    fi
    sleep 0.5
  done
  log "$node pas resynchronisé après 60 s"
}

# Préparation : tous les nœuds démarrés et un primaire élu
docker start "${NODES[@]}" >/dev/null
bash infra/scripts/init-rs.sh >/dev/null
P=$(primary)
read -r S1 S2 <<< "$(secondaries)"
log "=== Scénario $SCENARIO (run $RUN) — primaire=$P secondaires=$S1 $S2 ==="

# Sonde en arrière-plan
$COMPOSE --profile tools run --rm tools \
  python infra/scripts/failover_probe.py --duration "$PROBE_DURATION" --label "$LABEL" --out "$OUT" \
  > "$OUT/${LABEL}.probe.log" 2>&1 &
PROBE_PID=$!
sleep "$T_FAIL"

case "$SCENARIO" in
  s1-stop)
    log "PANNE : docker stop $P (primaire)"; docker stop "$P" >/dev/null
    sleep 3; log "Nouveau primaire : $(primary)"
    sleep $((T_BACK - T_FAIL - 3))
    log "RETOUR : docker start $P"; docker start "$P" >/dev/null
    wait_resync "$P" ;;
  s1-kill)
    log "PANNE : docker kill $P (crash du primaire)"; docker kill "$P" >/dev/null
    sleep $((T_BACK - T_FAIL))
    log "Nouveau primaire : $(primary)"
    log "RETOUR : docker start $P"; docker start "$P" >/dev/null
    wait_resync "$P" ;;
  s2)
    log "PANNE : docker stop $S1 (secondaire)"; docker stop "$S1" >/dev/null
    sleep $((T_BACK - T_FAIL))
    log "Primaire toujours : $(primary)"
    log "RETOUR : docker start $S1"; docker start "$S1" >/dev/null
    wait_resync "$S1" ;;
  s3)
    log "PANNE : docker stop $S1 $S2 (2 nœuds sur 3)"; docker stop "$S1" "$S2" >/dev/null
    for wait_s in 5 9; do
      sleep "$wait_s"
      log "État de $P : $(docker exec "$P" mongosh --quiet --eval 'rs.status().myState==1?"PRIMARY":"SECONDARY (plus de majorité)"')"
    done
    sleep $((T_BACK - T_FAIL - 14))
    log "RETOUR : docker start $S1 $S2"; docker start "$S1" "$S2" >/dev/null
    wait_resync "$S1" ;;
  s4)
    log "PANNE : docker stop $S1 pendant ~30 s d'écritures"; docker stop "$S1" >/dev/null
    sleep $((T_BACK - T_FAIL))
    log "RETOUR : docker start $S1"; docker start "$S1" >/dev/null
    wait_resync "$S1" ;;
  *) echo "Scénario inconnu : $SCENARIO" >&2; kill "$PROBE_PID"; exit 1 ;;
esac

wait "$PROBE_PID" || true
# Sortie de la sonde recopiée à la fin (docker.exe sous Windows écrase un fichier ouvert en ajout)
grep -v "Container" "$OUT/${LABEL}.probe.log" >> "$LOG" || true
log "=== Fin du scénario $SCENARIO (run $RUN) ==="
