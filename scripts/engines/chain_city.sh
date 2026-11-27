#!/usr/bin/env bash
# usage: chain_city.sh <docker-image> <machine-label> <res> <asset> [<asset> ...]   (sequential: ONE engine job at a time)
# per asset: TRELLIS.2 Q8 (front view), Pixal3D single-view Q8 (matted front), Pixal3D multi-view Q8 (4 views). Results: out/<asset>_<engine>_<res>_<machine>/
cd ~/assetforge-engines || exit 1
IMG="$1"; M="$2"; RES="$3"; shift 3
MAXTOK="${MAXTOK:-49152}"   # HR token budget. Above it the cascade backs the resolution off (1536 -> 1152...), logged as "backing off". Do NOT raise it to ~63k+: ggml-cuda aborts (GGML_ASSERT(grid_z < USHRT_MAX), cpy.cu) at pixal3d.cpp d1b4926
wait_free() { for i in $(seq 1 60); do docker ps --format '{{.Names}}' | grep -qE '^(assetforge-engine|clonez-mesh)$' || return 0; sleep 3; done; }
done_ok() { [ -f "out/$1/summary.json" ] && grep -q '"exit_code":0' "out/$1/summary.json"; }
run() {  # skips what already finished OK; retries while the lock/GPU is busy (exit 3) instead of failing the whole batch
  name="$1"; models="$2"; shift 2
  for try in $(seq 1 120); do
    done_ok "$name" && { echo "$name SKIP (done)" >> chain_city.status; return; }
    wait_free; bash run_cpp.sh "$name" "$IMG" "$models" refs -- "$@" > "out_$name.txt" 2>&1; code=$?
    [ "$code" -ne 3 ] && break; sleep 5
  done
  echo "$name EXIT=$code" >> chain_city.status
}
for A in "$@"; do
  run ${A}_t2q8_${RES}_$M trellis2-q8 --image /in/city/$A/front.png --models /models --res $RES --atlas 4096 --max-tokens $MAXTOK --seed 1 --require-gpu --birefnet --dump-bg -o /out/model.glb
  run ${A}_sv_1024_$M pixal3d-sv-q8 --sv-image /in/city/$A/sv_rgba.png --models /models --pixal3d-weights sv --res 1024 --atlas 4096 --max-tokens $MAXTOK --seed 1 --require-gpu -o /out/model.glb
  run ${A}_mv4_${RES}_$M pixal3d-mv-q8 --views /in/city/$A/mv4 --models /models --pixal3d-weights mv --res $RES --atlas 4096 --max-tokens $MAXTOK --seed 1 --require-gpu -o /out/model.glb
done
echo CITY_CHAIN_DONE >> chain_city.status
