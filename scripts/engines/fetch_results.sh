#!/usr/bin/env bash
# Run from the repo root in Git Bash or Linux. Only successful, complete engine runs are copied.
set -euo pipefail

key="${ASSETFORGE_SSH_KEY:-$HOME/.ssh/id_ed25519_asc}"
dest="${ASSETFORGE_RESULTS_DIR:-reports_out/engines/results}"
ssh_bin="${ASSETFORGE_SSH_BIN:-ssh}"
sftp_bin="${ASSETFORGE_SFTP_BIN:-sftp}"
mkdir -p "$dest"
files=(summary.json mem.csv raw.log model.glb)
options=(-i "$key" -o BatchMode=yes -o ConnectTimeout=8 -o ConnectionAttempts=2
         -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o UpdateHostKeys=no)

matching_files() {
  local dir="$1" i
  shift
  for i in "${!files[@]}"; do
    [[ -f "$dir/${files[i]}" ]] && [[ "$(stat -c %s "$dir/${files[i]}")" = "${1}" ]] || return 1
    shift
  done
}

fetch_host() (
  set -e
  host="$1"
  cd "$dest"
  stage="$(mktemp -d .fetch.XXXXXXXX)"
  trap 'rm -f -- "$stage/batch" "$stage/manifest" "$stage"/*/{summary.json,mem.csv,raw.log,model.glb}; rmdir -- "$stage"/*/ "$stage" 2>/dev/null || true' EXIT

  "$ssh_bin" "${options[@]}" "$host" 'cd ~/assetforge-engines/out || exit 1
    for d in */; do
      n=${d%/}
      case "$n" in ""|*[!A-Za-z0-9_-]*) continue;; esac
      [ -s "$d/model.glb" ] && [ -s "$d/mem.csv" ] && [ -s "$d/raw.log" ] &&
        grep -qE "\"exit_code\"[[:space:]]*:[[:space:]]*0[[:space:]]*[,}]" "$d/summary.json" || continue
      printf "%s " "$n"
      stat -c %s "$d/summary.json" "$d/mem.csv" "$d/raw.log" "$d/model.glb" | paste -sd " " -
    done' </dev/null > "$stage/manifest"

  : > "$stage/batch"
  while read -r name summary_size mem_size log_size model_size; do
    matching_files "$name" "$summary_size" "$mem_size" "$log_size" "$model_size" && continue
    mkdir "$stage/$name"
    for file in "${files[@]}"; do
      printf 'get assetforge-engines/out/%s/%s %s/%s/%s\n' "$name" "$file" "$stage" "$name" "$file" >> "$stage/batch"
    done
  done < "$stage/manifest"

  if [[ ! -s "$stage/batch" ]]; then
    printf '%s: %s resultados já presentes\n' "$host" "$(wc -l < "$stage/manifest")"
    exit 0
  fi
  "$sftp_bin" -q "${options[@]}" -b "$stage/batch" "$host" > /dev/null
  while read -r name summary_size mem_size log_size model_size; do
    [[ -d "$stage/$name" ]] || continue
    matching_files "$stage/$name" "$summary_size" "$mem_size" "$log_size" "$model_size"
    mkdir -p "$name"
    for file in "${files[@]}"; do
      mv -- "$stage/$name/$file" "$name/$file"
    done
    printf 'fetched %s\n' "$name"
  done < "$stage/manifest"
)

hosts=("$@")
if (( ${#hosts[@]} == 0 )); then
  hosts=(afforge@192.168.1.203 henrylawrencecahill@192.168.1.252)
fi
for host in "${hosts[@]}"; do
  fetch_host "$host"
done
