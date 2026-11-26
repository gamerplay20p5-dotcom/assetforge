#!/usr/bin/env bash
# Atualiza os presets vendorizados do Intel AI Playground para um commit específico (revise o diff antes de commitar!).
#   ./scripts/intel_ai/update_vendor.sh <commit-sha>
set -euo pipefail
cd "$(dirname "$0")/../.."
sha="${1:?informe o SHA do commit de intel/AI-Playground}"
dest=generators/intel_ai/assetforge_intel_ai/vendor/aipg
for p in pixel3d-trellis z-image; do
  curl -fsSL "https://raw.githubusercontent.com/intel/AI-Playground/$sha/modes/base/presets/$p.json" -o "$dest/$p.json"
done
curl -fsSL "https://raw.githubusercontent.com/intel/AI-Playground/$sha/LICENSE" -o "$dest/LICENSE"
sed -i "s/^AIPG_COMMIT = .*/AIPG_COMMIT = \"$sha\"/" generators/intel_ai/assetforge_intel_ai/presets.py
echo "atualizado para $sha. Atualize também COMFYUI_VERSION (WebUI/external/backend-versions.json), install_node.sh e rode: pytest tests/unit/test_intel_ai.py"
