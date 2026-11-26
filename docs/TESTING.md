# Testes — resultados reais

Ambiente de desenvolvimento: Windows 11, CPU Intel (12 threads), 16 GB RAM, Python 3.14, Node 24, Blender 4.5.17 portátil
(SHA‑256 conferido), Chromium do Playwright. **Sem Docker, sem PostgreSQL, sem Linux, sem GPU Intel Arc.**

## Executados e aprovados (2026‑11‑26)

| Suíte | Comando | Resultado |
|---|---|---|
| Python (unitários + integração + Blender real + IA com ComfyUI simulado) | `pytest` | **121 passed** (~2 min) |
| Frontend unitário | `cd apps/dashboard && npm test` | **9 passed** (Vitest) |
| Typecheck + build do dashboard | `npm run build` | ok (1643 módulos) |
| **E2E no Chromium contra pilha real** (API + dashboard + worker + Blender) | `npx playwright test` | **2 passed** (5,0 min) |
| Benchmark CPU, motor `trimesh` (14 assets, 7 categorias, 512 px) | `python scripts/benchmark.py` | mediana 2,9 s/asset, p95 4,0 s, 20,9 assets/min, **14/14 válidos** (12 threads, esta máquina) |
| Blender 4.5 (GLB + BLEND + FBX + Cycles 24 spp 512²) | via worker, lote de 10 | 10/10 concluídos, ~11–17 s/asset (2 threads) |

O que os testes cobrem de verdade:
* **Geradores**: 13 categorias × geometria válida; determinismo por seed; seeds diferentes → malhas diferentes; normais
  voltadas para fora; pivô base‑centro; orçamento de triângulos.
* **Validação**: NaN, triângulos degenerados, orçamento (aviso, não falha), GLB truncado/corrompido, referências do glTF.
* **Fila/scheduler**: um único worker vence a disputa; prioridade e FIFO; capacidade (jobs com `fbx` só em worker com
  Blender); worker fixado; reserva de núcleos; agendamento; dependências (bloqueio, liberação, propagação de falha); pausa/retomada;
  desabilitar/manutenção; cancelamento imediato e cooperativo; token de lease; retries com histórico e logs; **abandono por lease
  expirado** e re‑fila; heartbeat estende lease e informa jobs perdidos; **reinício da API** (instância nova no mesmo banco
  enxerga fila e job em execução); idempotência.
* **Integridade de resultados**: conclusão rejeitada sem upload, com checksum errado, com GLB corrompido, com validação
  reprovada; conclusão idempotente; nova versão preserva a original; arquivos servidos idênticos ao gerado.
* **Segurança**: 401 sem token, papéis, throttling de login, enrollment de uso único, tipo de token, path traversal em upload
  e download, extensão proibida; `kind: nvidia` recusado.
* **Idle/coexistência**: janelas que cruzam meia‑noite, limite de CPU do host, “ceder” ao processo `ai-stream-clipper`.
* **Planner**: exemplo “hospital moderno de cinco andares”, PT/EN, texto desconhecido não inventa parâmetros; resposta de LLM
  com campo extra/valor fora da faixa é rejeitada e cai nas regras.

## Testado na 206 (Linux/Docker reais, 2026‑11‑26)
Build das 3 imagens (central, worker com Blender Linux, ComfyUI/XPU) ok; **PostgreSQL 16 real**, API, worker CPU saudáveis; lote de 3 assets procedurais pelo worker em container (GLB/FBX/BLEND válidos).
Defeitos encontrados e corrigidos: `cap_drop: ALL` quebrava o Postgres (corrigido, `cap_add` mínimo). **Bloqueio de hardware**: ComfyUI/XPU não enxerga a A750 com Resizable BAR desativado (ver HARDWARE_COMPATIBILITY.md).

## Limitações conhecidas do que foi testado
* **Implantação Docker em uma máquina (`deployment/docker-compose.yml`, `Dockerfile.comfyui`, `install_single_node.sh`, `docker_tasks.sh`, backup/restore)**: só verificação estática (YAML, `bash -n`, testes de política); **nada foi construído ou executado**; sem acesso remoto à 206.
* ~~PostgreSQL não foi testado~~ — **agora testado na 206 (PostgreSQL 16 em Docker)** apenas no fluxo de lote; a suíte pytest completa ainda não rodou contra PostgreSQL (use `ASSETFORGE_TEST_PG_URL`). Texto antigo: **PostgreSQL não foi testado.** Tentativa de subir binários oficiais do PostgreSQL 16 foi bloqueada pela política do
  ambiente (diretório fora do projeto) e o caminho com acentos do repositório quebra o `initdb`. Rode no servidor:
  `ASSETFORGE_TEST_PG_URL=postgresql://assetforge:...@host:5432/assetforge_test pytest tests/integration`
  (a fixture cria e apaga as tabelas do banco de teste — use um banco descartável).
* **Docker Compose / Dockerfiles não foram construídos nem executados.** Revise e teste no servidor (DEPLOYMENT.md).
* **Linux**: nenhum teste em Linux (incluindo Blender Linux, `lspci`/`xpu-smi`, `/dev/dri`, `nice`, limites cgroup).
* **Intel Arc/OpenVINO**: nada foi executado em GPU Intel dedicada. Só a iGPU deste PC foi *detectada* (WMI).
* **LLM local**: o adaptador foi testado com servidor HTTP simulado, não com um modelo real.
* **Carga**: nenhum teste com centenas de jobs/dezenas de workers; SQLite foi usado nos testes.
* Orçamento: **apartamentos** com `detail=2` e muitos andares chegam a 11.678 triângulos (> 10.000): o validador emite *aviso*
  como especificado (varredura 3 estilos × 3 seeds × detail 1–2; demais categorias dentro do orçamento).
  Categorias como indústria/armazém (≈ 800 tri) e quartel/estação (≈ 2.100) ficam *abaixo* da faixa‑alvo — são simples demais
  e serão enriquecidas.
* `npm audit` reporta avisos em dependências de desenvolvimento (Vite/esbuild do servidor de dev); o build de produção serve
  arquivos estáticos pela API.

## Como reproduzir
```bash
pytest                                   # tudo (os testes Blender pulam sozinhos sem BLENDER_BIN/.tools)
pytest -m "not blender"                  # sem Blender
cd apps/dashboard && npm ci && npm test && npm run build
BLENDER_BIN=/caminho/blender npx playwright test   # sobe tests/e2e/stack.py (porta 8130)
python scripts/benchmark.py --engine blender --blender /caminho/blender --count 14
```

## Testes que dependem dos servidores físicos (a executar pelo proprietário)
1. Subir central + worker CPU via Compose; criar lote de 10 e conferir 10 assets (critérios do Milestone 1, itens 1–13).
2. Reiniciar `api`/`postgres` durante um lote e confirmar recuperação.
3. `scripts/benchmark.py --engine blender` em cada node, fora do horário de pico.
4. Worker com `ASSETFORGE_WORKER_YIELD_TO=ai-stream-clipper` (+ `pid: host`) e janela de horário: confirmar que não inicia jobs
   enquanto o Stream Clipper roda e que o Clipper não degrada.
5. `scripts/diagnose_hardware.py` e `scripts/validate_intel_gpu.py` nos nós com Intel Arc.
