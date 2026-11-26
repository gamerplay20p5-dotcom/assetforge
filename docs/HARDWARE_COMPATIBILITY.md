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

## Nó 206 — diagnóstico real (2026‑11‑26, SSH somente leitura; nada foi alterado)
| Item | Medido |
|---|---|
| Host | Servidor de aplicações (nó 206), Ubuntu 26.04.1, kernel 7.0.0‑44 |
| CPU/RAM/disco | **AMD** Ryzen Threadripper PRO 3955WX, 32 threads · 200 GB RAM (≈196 GB livres) · swap 8 GB · 613 GB livres |
| GPU | Intel **Arc A750** (DG2, `8086:56a1`), `/dev/dri/card0` (grupo `video`, gid 44) e `renderD128` (grupo `render`, **gid 993**) |
| Driver do kernel | `i915` em uso (módulo `xe` também carregado). **Level Zero/OpenCL/oneAPI no host: ausentes** (não é problema: ficam dentro do container do ComfyUI) |
| **Resizable BAR** | **desativado** — janela de VRAM de **256 MB** (`Region 2 … size=256M`). Habilitar no BIOS (Above 4G Decoding + Resizable BAR) costuma ser importante para o desempenho das Arc; é decisão do Hank |
| Docker / Compose | 29.8.1 / v5.5.1 instalados |
| **Permissão** | o usuário `asc` **não tem acesso ao Docker** (`permission denied … docker.sock`) e não está no grupo `render`; o único sudo é `asc-ctl` (sem `compose up`). **Quem for subir o AssetForge precisa de acesso ao Docker (Hank/root)** |
| Portas | 8000 e 5432 livres (conferido; demais portas omitidas) |
| Uso da GPU por outros serviços | os 3 workers do Stream Clipper na 206 (`capture`, `audio`, `render`) **não mapeiam `/dev/dri`** no compose → a Arc está livre; **não é preciso suspendê‑los** |
| Python do host | 3.14.4 (irrelevante: tudo roda em containers); `uv`/`gcc` ausentes no host |
**Isto é diagnóstico, não validação:** ainda não há prova de que PyTorch XPU/ComfyUI/Pixal3D rodem nessa A750 (Resizable BAR desligado e 8 GB são riscos de desempenho/memória).
Observação: a 206 tem CPU **AMD**; “CPUs Intel” valia só para outros nós.

## Nó 206 — execução real de 2026‑11‑26 (usuário dedicado `afforge`, projeto Compose `assetforge`)
| Teste | Resultado (medido) |
|---|---|
| Docker + PostgreSQL 16 + API + worker CPU (Linux) | ✅ saudáveis |
| Lote procedural (3 casas, GLB+FBX+BLEND, Blender 4.5.17 em container Linux) | ✅ 3/3 válidos em 20 s |
| **PyTorch XPU / ComfyUI na A750** | ❌ **BLOQUEADO**: `WARNING: Small BAR detected for device 0000:43:00.0` → `XPU device count is zero`; o ComfyUI cai no caminho CUDA e falha |
**Causa (documentada pela Intel, `compute-runtime/documentation/FAQ.md`):** sem **Resizable BAR** o driver de compute “não inicializa, por design”. A 206 está com a janela de VRAM em 256 MB (ReBAR desativado no BIOS).
**Ação necessária (Hank, no BIOS da 206, exige reiniciar o servidor):** ativar *Above 4G Decoding* e *Resizable BAR*. Depois, repetir `docker_tasks.sh comfy-check` e `validate`.
**Nenhum modelo de IA foi executado; a A750 continua NÃO validada.**

## Limites e coexistência
Padrão do worker: **metade** dos núcleos e da RAM; janelas de ociosidade, limite de CPU do host e lista “ceder a processos”
(ex.: `ai-stream-clipper`). Em Docker, `ASSETFORGE_WORKER_YIELD_TO` só enxerga processos do host com `pid: host` (opt‑in
comentado no compose); sem isso use o limite de CPU do host e as janelas de horário.
