# AssetForge

Fábrica de assets 3D para jogos, **self-hosted, distribuída e sem serviços pagos**. Gera edifícios proceduralmente
(Blender headless ou motor CPU puro), valida, exporta (GLB / BLEND / FBX), cataloga e distribui o trabalho entre
vários servidores Linux. Estilo inicial: *Premium Stylized Low/Mid Poly*.

> **Estado: Milestone 1 concluído** (fundação funcional, 100 % CPU). Milestones 2–5 (IA local em Intel Arc/OpenVINO,
> LODs/colisões/Inspector, animações, Unity/MCP) estão em [docs/ROADMAP.md](docs/ROADMAP.md). Nada abaixo é simulado:
> o que está marcado "planejado" não aparece como funcional na interface.

## O que já funciona (e foi testado)

| Área | Situação |
|---|---|
| Geradores procedurais de edifícios (13 categorias, 5 estilos, 15 paletas) | ✅ testado |
| Exportação GLB (motor próprio) + BLEND/FBX/miniatura Cycles via **Blender 4.5 LTS headless** | ✅ testado (Windows) |
| Pipeline de validação (malha + GLB re‑lido por leitor independente) e manifesto JSON | ✅ testado |
| API FastAPI, auth (JWT/roles), tokens de worker, auditoria, OpenAPI em `/api/docs` | ✅ testado |
| Fila distribuída (lease/heartbeat/retry/cancelamento/dependências/agendamento/recuperação) | ✅ testado |
| Worker CPU com limites, janelas de ociosidade e “ceder” a outros serviços | ✅ testado (lógica); ⚠ não em contêiner |
| Dashboard React (Dashboard, Generator, Batch Studio, Queue, Library + viewer 3D, Workers) | ✅ testado (Vitest + Playwright) |
| Planner texto→parâmetros (regras PT/EN; LLM local opcional) | ✅ regras testadas; ⚠ LLM só com servidor simulado |
| **Implantação em uma máquina** (Docker: API, dashboard, scheduler, worker CPU, worker Intel, ComfyUI/XPU, Blender, PostgreSQL local ou externo) | ⚠ **escrita e verificada estaticamente; nunca construída/executada** (sem Docker/Arc aqui) — [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) |
| PostgreSQL | ⚠ **não testado** (testes rodaram em SQLite); suíte aceita `ASSETFORGE_TEST_PG_URL` |
| **IA image-to-3D só com CPU** (TripoSR validado na 206; Stable Fast 3D construído, aguarda token HF): containers Docker, fila, painel, redução por bake, LODs, FBX/GLB/BLEND, benchmark | ✅ **1 asset real gerado e validado na 206** (TripoSR, 104 s); ❌ SF3D não executado — [docs/CPU3D.md](docs/CPU3D.md) |
| Provider **Intel AI** (DESABILITADO por padrão) (workflows do Intel AI Playground via ComfyUI headless): texto→imagem→3D, imagem→3D, perfis, LODs, FBX/GLB/BLEND, VRAM, cache de modelos, gate de validação | ✅ integração testada com ComfyUI **simulado** + Blender real; ❌ **nenhum modelo foi executado**, Arc A750 **não validada** — [docs/INTEL_AI.md](docs/INTEL_AI.md) |

Resultados reais dos testes: [docs/TESTING.md](docs/TESTING.md).

## Implantar em uma máquina (ex.: a 206)
```bash
./scripts/install_single_node.sh standalone      # ou external-db   (veja docs/DEPLOYMENT.md)
./scripts/intel_ai/docker_tasks.sh validate --repeat 3   # só depois: IA validada de verdade
```

## Início rápido (desenvolvimento, sem Docker)

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt      # Windows: .venv\Scripts\pip
cd apps/dashboard && npm ci && npm run build && cd ../..
BLENDER_BIN=/caminho/blender python tests/e2e/stack.py --port 8130      # API + dashboard + worker, banco temporário
# abra http://127.0.0.1:8130  (senha admin impressa no console)
```

Testes: `pytest` (149 testes), `cd apps/dashboard && npm test && npx playwright test`.
Implantação em servidores: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md). Arquitetura: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Estrutura

```
apps/api            API FastAPI + scheduler (assetforge_api)
apps/dashboard      React + TypeScript + Vite + Three.js
workers/cpu         agente de worker (CPU / intel / hybrid)
generators/procedural  gerador de edifícios, texturas, planner texto→parâmetros
pipeline/{optimization,validation,export}  limpeza, validação, GLB, Blender
packages/asset-contract  modelos Pydantic: parâmetros, manifesto, orçamentos
deployment · scripts · tests · docs
generators/{image,mesh,animation} · integrations/{unity,mcp}   reservados (Milestones 2–5)
```
Desvios da estrutura sugerida (scheduler dentro da API; um pacote Python por pasta) estão justificados em ARCHITECTURE.md.

## Segurança em uma frase
Sem execução de código/shell pela API; uploads com allow‑list, limite de tamanho, SHA‑256 e proteção contra path traversal;
workers autenticados por token próprio (guardado só como hash); jobs executam em subprocesso com timeout e diretório temporário.
