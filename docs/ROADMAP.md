# Roadmap

Diretriz atual (infraestrutura): **CPU + Intel (OpenVINO / PyTorch XPU / oneAPI)**; sem NVIDIA/CUDA. Três tipos de worker:
CPU, Intel GPU, Híbrido. Nada é declarado compatível sem validação.

## Milestone 1 — Fundação funcional (100 % CPU) ✅
API, banco, fila distribuída, auth, worker CPU, Blender headless, geradores de edifícios (13 categorias), GLB/BLEND/FBX,
validação, biblioteca com viewer 3D, lotes, logs, recuperação, limites/ociosidade, planner texto→parâmetros (regras + LLM local
opcional), Docker/scripts (não executados). Pendências conhecidas em TESTING.md (PostgreSQL, Docker, Linux).

## Milestone 2 — Intel GPU e IA local
> **Objetivo imediato:** validar geração 3D real em UMA Arc A750 (206, Docker, uma máquina) antes de qualquer expansão ou nova funcionalidade. Nenhum item abaixo avança antes de **um asset real** gerado e registrado em HARDWARE_COMPATIBILITY.md.
> **Andamento (2026‑11‑26):** integração com o Intel AI Playground implementada e testada com backend simulado — ver [INTEL_AI.md](INTEL_AI.md). **Falta executar nos nodes Arc** (validação, calibração de perfis/VRAM, comparação visual). Itens 2 e 4 abaixo passam a ser: validar Pixel3D‑Trellis (Pixal3D/TRELLIS.2) e Z‑Image‑Turbo na A750; SD/SDXL‑OpenVINO e TripoSR/Hunyuan ficam como alternativas se a A750 não comportar o workflow.
1. Executar `diagnose_hardware`/`validate_intel_gpu` nos nós Intel Arc; registrar evidências em HARDWARE_COMPATIBILITY.md.
2. Worker `intel`/`hybrid` com **providers** (interface `Provider.run(job)`): SD 1.5/SDXL via OpenVINO (optimum‑intel) para
   imagens e **texturas/materiais**; gerenciador de modelos local (download autorizado, SHA‑256, cache, offline).
3. **Planner com LLM local** (ver avaliação abaixo) integrado ao Asset Generator.
4. Pesquisa/teste de image‑to‑3D em CPU/XPU (TripoSR, TRELLIS v1, Hunyuan3D‑2.1 respeitando território). TRELLIS.2 passa a ser um interruptor do workflow da Intel (int8, ComfyUI/XPU): **viabilidade na A750 a validar** (o upstream exige NVIDIA grande). Aceite: só entra se rodar no hardware real com tempo/memória aceitáveis.
5. Geradores procedurais: veículos, infraestrutura urbana (estradas modulares, postes, semáforos, placas, bancos, hidrantes,
   vegetação, redes), pontes.
6. Migrações Alembic; testes em PostgreSQL; CI.

## Milestone 3 — Produção avançada
Batch Studio completo (agendas, reprocessar item), materiais/texturas por IA, **LODs** automáticos (decimação que preserva
detalhes importantes), **colisões** convexas/simplificadas, otimização, versionamento com *diff*, Asset Inspector (escala,
rotação, pivô, materiais — operações destrutivas geram nova versão), perfis de qualidade custom, presets artísticos
reutilizáveis (hoje: perfil padrão + presets de gerador).

## Milestone 4 — Animações
Animation Studio: estados de construção (terreno → fundação → estrutura → fachada → acabamento → concluído; abandono/dano) a
partir da mesma definição procedural; personagens modulares (esqueleto padrão, roupas, corpos, retargeting, validação de
skinning); animações procedurais (idle/walk/run/sit/stand/carry/work/enter/exit vehicle/construction); veículos e máquinas
(rodas, esterçamento, portas, luzes, hélices, guindastes, esteiras) com pivôs e hierarquia exportados.

## Milestone 5 — Integrações
Unity Editor Package (materiais URP, LODGroup, colisões, prefabs), importação automática, API para agentes (já há OpenAPI),
**MCP Server** do AssetForge, integração com Unity MCP/Blender MCP, benchmarks de carga.

## Avaliação: LLM local → parâmetros do gerador (pedido do proprietário)
**Viável e recomendado como caminho principal** (ADR‑007): o LLM só emite JSON no schema `BuildingParams`
(Ollama `format=<json-schema>`, validado por Pydantic com `extra=forbid`); o gerador procedural faz a geometria. Vantagens:
determinismo (mesma seed → mesma malha), zero VRAM de difusão 3D, assets nativamente coerentes com o contrato (pivô, escala,
orçamento), funciona em CPU. Riscos/limites: o LLM só controla o que o gerador expõe (por isso o roadmap amplia os
parâmetros: fachada/entradas/janelas por face, materiais por componente); precisa de modelo instruct pequeno (3–8 B) —
**qual modelo roda bem em CPU/Intel Arc ainda não foi medido**. Hoje: regras PT/EN testadas + adaptador LLM testado só com
servidor simulado. Próximo passo: medir 2–3 modelos (latência, taxa de JSON válido em 50 descrições) e fixar um.
Exemplo atual (regras): “hospital moderno de cinco andares, 40 x 20 m” → `{category: hospital, style: modern, floors: 5, width: 40, depth: 20}`.

## Dívida técnica conhecida
Alembic; troca de senha/gestão de usuários na UI; rotação de token de worker pela UI; LODs/colisão convexa; enriquecer
indústria/armazém/quartel (abaixo da faixa de triângulos); apartamentos com detalhe 2 estouram o orçamento; Cycles na GPU Intel
não explorado; thumbnails do motor sem Blender sem texturas (cor plana).
