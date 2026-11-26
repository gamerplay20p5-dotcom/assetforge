# Compatibilidade de hardware

Regra: **só é “compatível” o que foi executado e medido no hardware real.** Este arquivo é atualizado com evidências.
A infraestrutura-alvo é Intel (CPUs, muita RAM, GPUs Intel Arc). **Sem CUDA, sem NVIDIA Container Toolkit.**

## Estado atual

| Componente | CPU | Intel Arc / iGPU | Evidência |
|---|---|---|---|
| Geração procedural (Python) | ✅ | n/a (CPU) | testes automatizados, Windows 11, CPU Intel família 6 modelo 154 (12 threads) |
| Blender 4.5.17 headless — export GLB/BLEND/FBX + miniatura **Cycles CPU** | ✅ | n/a | testado no Windows; **Linux/contêiner não testado** |
| Blender com GPU Intel (oneAPI/Cycles) | — | ❓ **não testado** | Cycles aqui usa CPU de propósito (funciona em servidor sem GL) |
| Pixel3D‑Trellis (Pixal3D/TRELLIS.2) e Z‑Image‑Turbo via ComfyUI XPU (Intel AI Playground) | ❓ | ❓ **não validado** — preset marcado `high-vram`; 8 GB da A750 pode não caber | integração testada só com ComfyUI simulado; ver INTEL_AI.md §5 |
| Stable Diffusion / SDXL via OpenVINO (imagens/texturas) | ❓ | ❓ **não testado** | alternativa, Milestone 2 |
| Image‑to‑3D (TripoSR etc.) | ❓ | ❓ **não testado** | Milestone 2 |
| LLM local (planner) | ❓ | ❓ | adaptador testado só com servidor HTTP simulado |

Detecção automática (não é validação): `scripts/diagnose_hardware.py` lista CPU/RAM/disco, GPUs Intel visíveis ao SO
(`xpu-smi` → `sysfs/lspci` no Linux; WMI no Windows), `/dev/dri/renderD*`, Blender, OpenVINO/PyTorch **instalados**. VRAM e
utilização de GPU Intel são `null` quando o SO não os expõe (nunca inventados). O worker publica o mesmo no painel;
`capabilities.ai_runtimes.validated` fica **vazio** até um benchmark real preencher.
`scripts/validate_intel_gpu.py` roda um modelo‑sonda do OpenVINO em cada dispositivo (prova que o dispositivo executa grafos,
**não** que SD/SDXL/3D funcionam).

Medido nesta máquina de desenvolvimento (Intel UHD integrada, sem Arc): iGPU detectada via WMI, VRAM não medida;
OpenVINO/PyTorch não instalados → nenhuma capacidade de IA declarada.

## Modelos image‑to‑3D: o que a pesquisa nas fontes mostrou (2026‑11)
* **TRELLIS.2** — README oficial: “An NVIDIA GPU with at least 24GB … verified on A100/H100 … CUDA Toolkit needed”, testado
  só em Linux. O código upstream **não roda em Intel**; porém o preset da Intel (AI Playground) reempacota Pixal3D/TRELLIS.2 em int8 para ComfyUI/XPU — **viabilidade na A750 de 8 GB: a validar** (INTEL_AI.md).
* **TRELLIS (v1)**, **Hunyuan3D‑2.1**, **TripoSR**: requisitos de VRAM e suporte a CPU/XPU **a medir** no Milestone 2 (clonar,
  rodar em CPU e, se instalável, em PyTorch XPU/OpenVINO; registrar tempo, memória, saída). Até lá: “não validado”.
* Estratégia preferida (ver ROADMAP): geração **procedural parametrizada por LLM/regras** como caminho principal; IA 3D
  pesada só como complemento, se algum modelo for validado.

## Limites e coexistência
Padrão do worker: **metade** dos núcleos e da RAM; janelas de ociosidade, limite de CPU do host e lista “ceder a processos”
(ex.: `ai-stream-clipper`). Em Docker, `ASSETFORGE_WORKER_YIELD_TO` só enxerga processos do host com `pid: host` (opt‑in
comentado no compose); sem isso use o limite de CPU do host e as janelas de horário.
