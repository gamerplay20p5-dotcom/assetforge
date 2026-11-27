#!/usr/bin/env bash
# Runs pilot_reconstruct.py in the AssetPipeline image (clonez-mesh:1) on the DGX Spark. Everything is Docker.
# The Hank pipeline's code and weights are mounted READ-ONLY; outputs go to ~/assetforge-pilot only.
#
#   bash run_pilot.sh <image-under-~/assetforge-pilot/in> <out-name> [pilot_reconstruct.py args...]
set -euo pipefail
PILOT="$HOME/assetforge-pilot"
IMG="${1:?image file name inside $PILOT/in}"; OUT="${2:?output name}"; shift 2
mkdir -p "$PILOT/out" "$PILOT/hf" "$PILOT/home"

# Refuse to run beside the Hank's run (it would compete for the unified memory and could get it killed).
if docker ps --format '{{.Names}}' | grep -q '^clonez-mesh$'; then echo "the Hank mesh run is active; not starting"; exit 3; fi
if [ -e "$PILOT/.lock" ] && docker ps --format '{{.Names}}' | grep -q '^assetforge-pilot$'; then echo "an AssetForge pilot is already running"; exit 3; fi

docker run --rm --name assetforge-pilot --gpus all --shm-size 8g --user "$(id -u):$(id -g)" \
  -e HOME=/pilot/home -e HF_HOME=/pilot/hf -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 -e PYTHONIOENCODING=utf-8 -e CLONEZ_MODELS=/models \
  -v "$HOME/clonez-models":/models:ro -v "$HOME/clonez-pipeline":/hank:ro -v "$PILOT":/pilot \
  -w /pilot clonez-mesh:1 python /pilot/code/pilot_reconstruct.py --image "/pilot/in/$IMG" --out "/pilot/out/$OUT" "$@"
