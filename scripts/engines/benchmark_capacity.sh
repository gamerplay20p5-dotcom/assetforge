#!/usr/bin/env bash
# Usage: benchmark_capacity.sh <engine image> <weights dir> <refs dir> <new output dir> [1 2 3 4]
set -euo pipefail

image="$1"
weights="$(realpath "$2")"
refs="$(realpath "$3")"
out="$(realpath -m "$4")"
shift 4
count_sequence=("$@")
if (( ${#count_sequence[@]} == 0 )); then count_sequence=(1 2 3 4); fi
assets=(npc_government_001 npc_public_service_001 npc_worker_002 npc_civilian_002)
threads="${ENGINE_CPU_THREADS:-1}"
prefix="assetforge-capacity-$(date -u +%Y%m%d%H%M%S)-$$"
mkdir "$out"

stop_tests() {
  docker ps --filter "name=^/$prefix-" --format '{{.Names}}' | xargs -r docker stop -t 10 >/dev/null
}

sample() {
  while :; do
    local free temp utilization ram
    IFS=, read -r free temp utilization < <(
      nvidia-smi --query-gpu=memory.free,temperature.gpu,utilization.gpu --format=csv,noheader,nounits
    )
    ram="$(awk '/MemAvailable:/{print int($2/1024)}' /proc/meminfo)"
    echo "$(date +%s),$free,$temp,$utilization,$ram" >> "$out/telemetry.csv"
    if (( temp >= 84 || ram < 12288 )) || { [[ "$free" =~ ^[0-9]+$ ]] && (( free < 3600 )); }; then
      touch "$out/headroom-stop"
      stop_tests
      return
    fi
    sleep 2
  done
}

generate() {
  local stage="$1" asset="$2" start code=0
  local folder="$out/n$stage/$asset"
  mkdir -p "$folder"
  start="$(date +%s)"
  docker run --rm --name "$prefix-$stage-$asset" --gpus all --ipc host --ulimit core=0 \
    --user "$(id -u):$(id -g)" -e HOME=/tmp -e OMP_NUM_THREADS="$threads" \
    -v "$weights:/models:ro" -v "$refs:/in:ro" -v "$folder:/out" "$image" trellis-cli \
    --image "/in/city/$asset/front.png" --models /models --res 1024 --atlas 4096 \
    --max-tokens 49152 --seed 1 --threads "$threads" --require-gpu --birefnet --dump-bg \
    -o /out/model.glb > "$folder/raw.log" 2>&1 || code=$?
  if [[ "$code" == 0 && ! -s "$folder/model.glb" ]]; then code=1; fi
  echo "$asset $code $(($(date +%s)-start))" | tee "$folder/result.txt"
  return "$code"
}

sample &
sampler="$!"
trap 'kill "$sampler" 2>/dev/null || true; stop_tests' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
overall=0

for count in "${count_sequence[@]}"; do
  [[ "$count" =~ ^[1-4]$ ]] || exit 2
  [[ ! -e "$out/headroom-stop" ]] || exit 1
  pids=()
  for ((i=0; i<count; i++)); do
    generate "$count" "${assets[i]}" &
    pids+=("$!")
  done
  for pid in "${pids[@]}"; do wait "$pid" || overall=1; done
  if (( overall )) && [[ "${CONTINUE_AFTER_FAILURE:-0}" != 1 ]]; then exit 1; fi
done
exit "$overall"
