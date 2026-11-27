#!/usr/bin/env bash
# Runs ONE pixal3d.cpp (trellis-cli) generation in Docker and MEASURES it: wall time, peak host RAM, peak GPU memory, a memory timeline, exit code.
# Used on the RTX 4090 box (203) and the DGX Spark (252). Inputs/weights are mounted read-only; outputs go to ~/assetforge-engines/out/<name>/.
#
#   bash run_cpp.sh <name> <docker-image> <models-subdir> <inputs-subpath> -- <trellis-cli args using /in and /out paths>
#   e.g. bash run_cpp.sh tower_sv_q8 assetforge-pixal3d:cuda89 pixal3d-sv-q8 refs -- --sv-image /in/tower_rgba.png --models /models --res 1024 --atlas 4096 -o /out/model.glb
#
# Safety: one AssetForge GPU job at a time (flock); on the Spark it also refuses to start (and stops) if the Hank's clonez-mesh run is active;
# the container is stopped (never other people's processes) when available host RAM drops under MIN_AVAIL_GB.
# Exit codes: the tool's own; 3 refused; 4 stopped by the guard.
set -uo pipefail
NAME="${1:?name}"; IMAGE="${2:?docker image}"; MODELS_SUB="${3:?models subdir}"; IN_SUB="${4:?inputs subpath under ~/assetforge-engines}"; shift 4
[ "${1:-}" = "--" ] && shift
BASE="$HOME/assetforge-engines"; OUT="$BASE/out/$NAME"; MODELS="$HOME/assetforge-models/$MODELS_SUB"
MIN_AVAIL_GB="${MIN_AVAIL_GB:-10}"
mkdir -p "$OUT"; exec 9>"$BASE/.lock"
flock -n 9 || { echo "another AssetForge engine job holds the lock; not starting"; exit 3; }
if docker ps --format '{{.Names}}' | grep -qE '^(clonez-mesh|assetforge-pilot|assetforge-engine)$'; then echo "another GPU job is running; not starting"; exit 3; fi

mem_used_mb() { free -m | awk 'NR==2{print $3}'; }
mem_avail_mb() { free -m | awk 'NR==2{print $7}'; }
gpu_used_mb() { nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | head -1 | tr -d ' ' | grep -E '^[0-9]+$' || echo NA; }
BASE_RAM=$(mem_used_mb); BASE_GPU=$(gpu_used_mb)
echo "t_s,ram_used_mb,ram_avail_mb,gpu_used_mb" > "$OUT/mem.csv"
START=$(date +%s.%N)
docker run --rm --name assetforge-engine --gpus all --ipc host --user "$(id -u):$(id -g)" -e HOME=/tmp \
  -v "$MODELS":/models:ro -v "$BASE/$IN_SUB":/in:ro -v "$OUT":/out "$IMAGE" trellis-cli "$@" > "$OUT/raw.log" 2>&1 &
PID=$!
STOPPED=0
(
  while kill -0 "$PID" 2>/dev/null; do
    t=$(awk -v a="$(date +%s.%N)" -v b="$START" 'BEGIN{printf "%.2f", a-b}')
    echo "$t,$(mem_used_mb),$(mem_avail_mb),$(gpu_used_mb)" >> "$OUT/mem.csv"
    if [ "$(mem_avail_mb)" -lt $((MIN_AVAIL_GB * 1024)) ]; then echo "guard: available RAM < ${MIN_AVAIL_GB} GB, stopping engine container" >> "$OUT/guard.log"; docker stop assetforge-engine >/dev/null 2>&1; break; fi
    if docker ps --format '{{.Names}}' | grep -q '^clonez-mesh$'; then echo "guard: Hank run started, stopping engine container" >> "$OUT/guard.log"; docker stop assetforge-engine >/dev/null 2>&1; break; fi
    sleep 0.5
  done
) &
GUARD=$!
wait "$PID"; CODE=$?
kill "$GUARD" 2>/dev/null; wait "$GUARD" 2>/dev/null
END=$(date +%s.%N)
[ -s "$OUT/guard.log" ] && [ "$CODE" -ne 0 ] && CODE=4
awk -F, -v b="$BASE_RAM" -v g="$BASE_GPU" -v code="$CODE" -v wall="$(awk -v a="$END" -v b="$START" 'BEGIN{printf "%.2f", a-b}')" -v name="$NAME" 'NR>1{ if($2>pr)pr=$2; if($4!="NA" && $4>pg)pg=$4; if(mn==""||$3<mn)mn=$3 }
  END{ printf "{\"name\":\"%s\",\"exit_code\":%d,\"wall_seconds\":%.1f,\"baseline_ram_mb\":%d,\"peak_ram_mb\":%d,\"peak_ram_delta_mb\":%d,\"min_ram_available_mb\":%d,\"baseline_gpu_mb\":\"%s\",\"peak_gpu_mb\":\"%s\",\"peak_gpu_delta_mb\":\"%s\"}\n", name, code, wall, b, pr, pr-b, mn, g, (g=="NA"?"NA":pg), (g=="NA"?"NA":pg-g) }' "$OUT/mem.csv" > "$OUT/summary.json"
cat "$OUT/summary.json"
exit "$CODE"
