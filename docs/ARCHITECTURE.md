# Arquitetura

## Visão geral

```
 Navegador ──HTTP/SSE──▶  API (FastAPI) ──SQL──▶ PostgreSQL (SQLite em dev/testes)
 Agente IA ──HTTP────▶     │  scheduler + reaper (no processo da API)
                           │  storage: assets/<id>/v<n>/…  (disco local ou volume)
        ▲ lease/heartbeat/events/upload (HTTP, token por worker)
        │
 Worker CPU ─┐   cada job = subprocesso isolado:
 Worker Intel/Híbrido ─┤   gerador procedural → otimização → validação → texturas →
 (outros nós) ─┘            exportação (Blender | motor próprio) → miniatura → validação dos arquivos → pacote
```

Tipos de worker (campo `kind`): **cpu**, **intel** (GPU Intel, OpenVINO/XPU), **hybrid** (CPU + GPU Intel).
NVIDIA/CUDA **não** é suportado nem exigido nesta fase (decisão do proprietário da infraestrutura); poderá ser um `kind`
futuro sem alterar a API.

## Decisões (ADR resumido)

**ADR‑001 — Geometria em Python, acabamento no Blender.** O gerador procedural (`generators/procedural`) produz uma
`MeshSpec` (numpy) determinística e testável sem Blender. O Blender headless recebe essa malha e faz materiais,
`.blend`, GLB, FBX e miniatura Cycles. Sem Blender, o motor `trimesh`/próprio exporta GLB + miniatura por software, de modo
que o Milestone 1 funciona em qualquer CPU; `.blend`/`.fbx` são **recusados** (não simulados) sem Blender.

**ADR‑002 — Fila no banco de dados em vez de Celery+Redis.** Os workers *puxam* jobs por *lease*. Motivos: roteamento por
capacidade/recursos (features, núcleos, RAM, VRAM reservados) é consulta SQL; todo o estado é durável (recuperação após
reinício sem esforço); um serviço a menos para operar nos servidores compartilhados. Claim atômico:
`UPDATE … WHERE status='queued'` (exatamente um vencedor). Cada lease tem token opaco; eventos/uploads/conclusão exigem o token
(workers zumbis recebem 409). Lease expira sem heartbeat → tentativa `abandoned` → re‑fila com backoff até `max_attempts`.
Se a escala exigir, o ponto de troca é `scheduler/core.py`.

**ADR‑003 — Progresso real.** O worker envia um plano de etapas com pesos; o servidor só avança o progresso quando uma etapa
termina de fato. ETA só aparece com ≥ 3 execuções reais do mesmo tipo.

**ADR‑004 — “Concluído” só com arquivos.** `POST /worker/jobs/{id}/complete` re‑calcula SHA‑256 e tamanho de cada arquivo
enviado, exige `model.glb`, `thumbnail.png`, `manifest.json`, `validation.json`, re‑parseia o GLB e confere o manifesto com o
lease. Só então o asset/versão é registrado. Operação idempotente.

**ADR‑005 — Tempo real por SSE lendo a tabela `events`.** Funciona com várias réplicas da API; o navegador recebe um token
de download de vida curta (EventSource/`<img>`/WebGL não enviam cabeçalhos) que só vale em GETs.

**ADR‑006 — Coexistência com outros serviços.** O worker só *inicia* jobs quando: dentro da janela horária configurada,
CPU do host abaixo do limite e nenhum processo da lista “ceder” em execução; roda com prioridade reduzida; reserva lógica
(núcleos/RAM) por node, editável no painel; Docker aplica limites rígidos. Jobs em andamento nunca são mortos pelo portão.

**ADR‑007 — Planner texto→parâmetros.** `generators/procedural/planner.py`: regras determinísticas PT/EN (sempre
disponíveis) + adaptador opcional para LLM **local** (Ollama‑compatível, `ASSETFORGE_LLM_URL/MODEL`) com saída restrita ao
schema `BuildingParams` (`extra=forbid`): o modelo só escolhe parâmetros conhecidos; qualquer resposta inválida cai nas
regras. O LLM nunca gera geometria nem código. Ver avaliação em ROADMAP.md.

**ADR‑008 — IA generativa como complemento, via ComfyUI headless.** `generators/intel_ai` (provider) conversa por HTTP com um
ComfyUI local (127.0.0.1) que executa os workflows **da Intel** (vendorizados). O worker só anuncia `ai.*` com GPU + modelos + nó
**validado**; VRAM é recurso do scheduler (reserva lógica) e checada de verdade antes de iniciar (outros serviços dividem a Arc).
Pós‑processamento (escala, LODs, export) é do Blender, no mesmo contrato de manifesto. Detalhes: INTEL_AI.md.

**ADR‑009 — Implantação inicial em uma máquina.** Um `deployment/docker-compose.yml` com perfis (`standalone` | `external-db`, `ai`, `tools`)
roda API+dashboard+scheduler, worker CPU, worker híbrido Intel, ComfyUI/XPU e (opcional) PostgreSQL local; só a API publica porta; GPU por `/dev/dri`
(sem privileged/CUDA). A distribuição continua: a fila não depende do número de workers, e outros nós se registram na mesma API depois.
Tokens de registro vêm do ambiente (`ASSETFORGE_BOOTSTRAP_ENROLLMENT_TOKENS`) para subir sem passo manual. Detalhes: DEPLOYMENT.md.

## Desvios da estrutura de pastas pedida
* `services/scheduler` vive em `apps/api/assetforge_api/scheduler` (compartilha modelos ORM e transações; separar criaria
  dependência circular). A pasta `services/` fica reservada.
* Cada pasta de componente contém um pacote Python próprio, montado via `PYTHONPATH` (ver `pyproject.toml`) em vez de oito
  distribuições minúsculas.
* Alembic ainda não é usado: `create_all` cria o esquema. **Antes de produção real** é preciso adicionar migrações (ROADMAP).

## Segurança
JWT HS256 (12 h) + papéis admin/operator/viewer; senhas scrypt; tokens de worker e de enrollment guardados só como SHA‑256;
limitação de tentativas de login; uploads: allow‑list de extensões, componentes `[A‑Za‑z0‑9._-]`, profundidade ≤ 3, limite de
tamanho, SHA‑256 obrigatório; `safe_join` contra path traversal; jobs validados por Pydantic (sem execução de código de
usuário); subprocessos com timeout e encerramento da árvore; auditoria de ações administrativas; containers sem privilégios,
`cap_drop: ALL`, `no-new-privileges`; PostgreSQL não publicado.
