#!/usr/bin/env bash
# Downloads every FINISHED engine run (summary.json with exit_code 0) from both machines into reports_out/engines/results/<name>/ (model.glb, summary.json, mem.csv, log).
# Safe to re-run (skips what is already local). Run from the repo root in Git Bash:   bash scripts/engines/fetch_results.sh
K="$HOME/.ssh/id_ed25519_asc"; DEST="reports_out/engines/results"; mkdir -p "$DEST"
for h in afforge@192.168.1.203 henrylawrencecahill@192.168.1.252; do
  for n in $(ssh -i "$K" -o BatchMode=yes "$h" 'cd ~/assetforge-engines/out && for d in */; do d=${d%/}; grep -q "\"exit_code\":0" $d/summary.json 2>/dev/null && [ -f $d/model.glb ] && echo $d; done' </dev/null); do
    [ -f "$DEST/$n/model.glb" ] && continue
    mkdir -p "$DEST/$n"
    for f in model.glb summary.json mem.csv raw.log; do scp -q -i "$K" "$h:assetforge-engines/out/$n/$f" "$DEST/$n/" 2>/dev/null; done
    echo "fetched $n"
  done
done
