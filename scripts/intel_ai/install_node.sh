#!/usr/bin/env bash
# Prepara UM node Ubuntu com Intel Arc para rodar o backend ComfyUI (headless) usado pelos workflows do Intel AI Playground.
#
#   ./scripts/intel_ai/install_node.sh            # instala em ~/assetforge-ai (usuário comum, SEM sudo)
#   ASSETFORGE_AI_HOME=/dados/ai ./scripts/intel_ai/install_node.sh
#
# O que faz: checa pré-requisitos, clona ComfyUI na versão fixada, instala o ambiente Python/torch XPU usando o
# pyproject.toml + uv.lock da própria Intel (AI Playground, commit fixado) e verifica se o torch enxerga a GPU.
# O que NÃO faz: não usa sudo, não instala/atualiza drivers, não toca em Docker, serviços ou outros projetos.
# Os comandos que exigem root (drivers/Level Zero) são apenas IMPRESSOS para o Hank rodar, se faltarem.
# Escrito para execução manual; NÃO foi executado em hardware Intel Arc pelo autor (veja docs/INTEL_AI.md).
set -euo pipefail

AIPG_COMMIT="1aa842352bebe454774c4c3840755451810ca8ab"   # intel/AI-Playground (release v3.3.0 beta)
COMFY_TAG="v0.34.0"                                       # WebUI/external/backend-versions.json nesse commit
HOME_DIR="${ASSETFORGE_AI_HOME:-$HOME/assetforge-ai}"
COMFY_DIR="$HOME_DIR/ComfyUI"
RAW="https://raw.githubusercontent.com/intel/AI-Playground/$AIPG_COMMIT"

say() { printf '\n== %s\n' "$*"; }
need_root=()

say "1/6 Pré-requisitos (somente verificação)"
[[ "$(uname -s)" == "Linux" ]] || { echo "Este script é para Linux (Ubuntu)."; exit 1; }
command -v git >/dev/null || need_root+=("apt-get install -y git")
command -v gcc >/dev/null || need_root+=("apt-get install -y build-essential python3-dev   # compila wheels como insightface")
if ls /dev/dri/renderD* >/dev/null 2>&1; then echo "render node: $(ls /dev/dri/renderD* | tr '\n' ' ')"; else need_root+=("# nenhum /dev/dri/renderD* — driver i915/xe não carregado?"); fi
id -nG | tr ' ' '\n' | grep -qx render || need_root+=("usermod -aG render,video $USER   # depois faça logout/login")
if ! ldconfig -p 2>/dev/null | grep -q libze_loader; then
  need_root+=("# Level Zero + driver de compute da Intel (repositório oficial; igual ao que o AI Playground faz no Linux):
apt-get install -y --no-install-recommends ca-certificates gpg wget
wget -qO /tmp/intel-graphics.key https://repositories.intel.com/gpu/intel-graphics.key
gpg --dearmor -o /usr/share/keyrings/intel-graphics.gpg /tmp/intel-graphics.key
. /etc/os-release
echo \"deb [arch=amd64 signed-by=/usr/share/keyrings/intel-graphics.gpg] https://repositories.intel.com/gpu/ubuntu \${VERSION_CODENAME} unified\" > /etc/apt/sources.list.d/intel-gpu.list
apt-get update && apt-get install -y libze1 libze-intel-gpu1 intel-opencl-icd   # (Ubuntu 22.04: level-zero intel-level-zero-gpu)")
fi
if ((${#need_root[@]})); then
  echo; echo "Faltam itens que exigem ROOT. Peça ao Hank para rodar, como root, na máquina $(hostname):"; echo
  printf '  %s\n' "${need_root[@]}"; echo
  echo "Depois rode este script de novo. (Nada disso foi executado por mim.)"; exit 3
fi

say "2/6 uv (gerenciador Python usado pela Intel) — instalação no diretório do usuário"
if ! command -v uv >/dev/null; then python3 -m pip install --user --quiet uv; export PATH="$HOME/.local/bin:$PATH"; fi
uv --version

say "3/6 ComfyUI $COMFY_TAG em $COMFY_DIR"
mkdir -p "$HOME_DIR"
[[ -d "$COMFY_DIR/.git" ]] || git clone --quiet --depth 1 --branch "$COMFY_TAG" https://github.com/comfyanonymous/ComfyUI.git "$COMFY_DIR"
git -C "$COMFY_DIR" describe --tags --always

say "4/6 Ambiente Python 3.12 + torch XPU (pyproject.toml/uv.lock da Intel no commit fixado)"
cd "$COMFY_DIR"
[[ -f pyproject.toml.aipg-upstream ]] || cp pyproject.toml pyproject.toml.aipg-upstream
curl -fsSL "$RAW/comfyui-deps/pyproject.toml" -o pyproject.toml
curl -fsSL "$RAW/comfyui-deps/uv.lock" -o uv.lock
uv python install 3.12
uv sync --extra xpu --python 3.12

say "5/6 Verificação do torch XPU"
set +e
.venv/bin/python - <<'PY'
import torch
print("torch", torch.__version__, "| xpu disponível:", torch.xpu.is_available(), "| dispositivos:", torch.xpu.device_count())
for i in range(torch.xpu.device_count()):
    print(" -", torch.xpu.get_device_name(i))
PY
set -e

say "6/6 Próximos passos"
cat <<EOF
  a) Modelos:  python3 scripts/intel_ai/download_models.py --models-dir $COMFY_DIR/models --accept-licenses
  b) Subir:    COMFY_HOME=$COMFY_DIR ./scripts/intel_ai/run_comfyui.sh      (escuta só em 127.0.0.1:8188)
  c) Validar:  python3 scripts/intel_ai/validate_node.py --state-dir <dir de estado do worker>
  d) Worker:   defina ASSETFORGE_COMFYUI_URL=http://127.0.0.1:8188 e ASSETFORGE_AI_MODELS_DIR=$COMFY_DIR/models
Instalado em: $COMFY_DIR   (para remover: apague a pasta $HOME_DIR)
EOF
