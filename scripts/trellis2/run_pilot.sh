#!/usr/bin/env bash
# Runs pilot_reconstruct.py in the AssetPipeline image (clonez-mesh:1) on the DGX Spark. Everything is Docker.
# The Hank pipeline's code and weights are mounted READ-ONLY; outputs go to ~/assetforge-pilot only.
#
#   bash run_pilot.sh <image-under-~/assetforge-pilot/in> <out-name> [pilot_reconstruct.py args...]
# Exit codes are the script's (0 ok, 1 failed, 2 no object, 3 refused, 75 aborted by the memory watchdog); 4 = the host guard stopped the container.
set -uo pipefail
PILOT="$HOME/assetforge-pilot"
SCRIPT="${PILOT_SCRIPT:-pilot_reconstruct.py}"   # other scripts (e.g. test_uvraster.py) get all arguments as they are
if [ "$SCRIPT" = "pilot_reconstruct.py" ]; then
  IMG="${1:?image file name inside $PILOT/in}"; OUT="${2:?output name}"; shift 2
  SCRIPT_ARGS=(--image "/pilot/in/$IMG" --out "/pilot/out/$OUT" "$@")
else
  SCRIPT_ARGS=("$@")
fi
LIMIT_GB="${ASSETFORGE_PILOT_MEM_LIMIT_GB:-108}"   # host guard: stop OUR container above this much used memory
mkdir -p "$PILOT/out" "$PILOT/hf" "$PILOT/home"; touch "$PILOT/.lock"

# Exclusivity (checked at start AND while running): never share the Spark with the Hank run or another AssetForge job.
other_running() { docker ps --format '{{.Names}}' | grep -qE '^(clonez-mesh|assetforge-pilot)$'; }
if other_running; then echo "another GPU job is running (clonez-mesh or assetforge-pilot); not starting"; exit 3; fi

guard() {  # runs beside the container; ends when the container does
  while docker ps --format '{{.Names}}' | grep -q '^assetforge-pilot$'; do
    used=$(free -m | awk 'NR==2{print int($3/1024)}')
    if [ "$used" -ge "$LIMIT_GB" ]; then echo "$(date +%T) used=${used}GB >= ${LIMIT_GB}: stopping assetforge-pilot" >> "$PILOT/guard.log"; docker stop assetforge-pilot >/dev/null; return 4; fi
    if docker ps --format '{{.Names}}' | grep -q '^clonez-mesh$'; then echo "$(date +%T) the Hank run started: stopping assetforge-pilot" >> "$PILOT/guard.log"; docker stop assetforge-pilot >/dev/null; return 4; fi
    sleep 1
  done
}

docker run --rm --name assetforge-pilot --gpus all --shm-size 8g --user "$(id -u):$(id -g)" \
  -e HOME=/pilot/home -e HF_HOME=/pilot/hf -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 -e PYTHONIOENCODING=utf-8 -e CLONEZ_MODELS=/models \
  -v "$HOME/clonez-models":/models:ro -v "$HOME/clonez-pipeline":/hank:ro -v "$PILOT":/pilot \
  -w /pilot clonez-mesh:1 python "/pilot/code/$SCRIPT" "${SCRIPT_ARGS[@]}" &
DOCKER_PID=$!
sleep 3; guard & GUARD_PID=$!
wait "$DOCKER_PID"; CODE=$?
kill "$GUARD_PID" 2>/dev/null; wait "$GUARD_PID" 2>/dev/null
[ "$CODE" -eq 137 ] || [ "$CODE" -eq 143 ] && [ -s "$PILOT/guard.log" ] && CODE=4
exit "$CODE"
