#!/usr/bin/env bash
set -euo pipefail

mode="${1:?use build or run}"
packages="$(realpath "${2:?point to the directory with building, npc and vehicle packages}")"
out="$(realpath -m "${3:?choose an output directory}")"
src="$(cd -- "$(dirname -- "$0")" && pwd)"
mkdir -p "$out"

case "$mode" in
  build)
    : "${UNITY_EDITOR_IMAGE:?set a licensed Unity 6000.0.65f1 Linux Editor image with Linux Build Support}"
    docker run --rm --name assetforge-unity-benchmark-build \
      -e ASSETFORGE_PACKAGES=/packages -e ASSETFORGE_PLAYER=/out/player/AssetForgeBench \
      -v "$packages:/packages:ro" -v "$src:/template:ro" -v "$out:/out" \
      --entrypoint /bin/bash "$UNITY_EDITOR_IMAGE" -ec '
        mkdir -p /out/project /out/player
        cp -a /template/Assets /template/Packages /template/ProjectSettings /out/project/
        unity="${UNITY_BIN:-/opt/unity/Editor/Unity}"
        "$unity" -batchmode -nographics -quit -projectPath /out/project \
          -executeMethod CityBenchBuild.Build -logFile /out/build.log
        test -x /out/player/AssetForgeBench
      '
    ;;
  run)
    : "${UNITY_PLAYER_IMAGE:?set the player runtime image}"
    : "${DISPLAY:?select a GPU-backed X11 display on this Docker host}"
    : "${XAUTHORITY:?set the X11 access file for that display}"
    docker run --rm --name assetforge-unity-benchmark-run --gpus all --network none \
      -e DISPLAY -e XAUTHORITY=/display.auth -e NVIDIA_DRIVER_CAPABILITIES=graphics,display,utility,compute \
      -e ASSETFORGE_BENCH_OUTPUT=/out/results -v "$out:/out" \
      -v "$XAUTHORITY:/display.auth:ro" -v /tmp/.X11-unix:/tmp/.X11-unix:ro \
      --entrypoint /out/player/AssetForgeBench "$UNITY_PLAYER_IMAGE" \
      -force-vulkan -screen-fullscreen 0 -screen-width 1920 -screen-height 1080 -logFile /out/player.log
    ;;
  *) exit 2 ;;
esac
