# HANDOFF — AssetForge (estado em 2026-11-27)

Escrito para: outro agente de código (Codex) que vai continuar o trabalho sem o histórico da conversa. Idioma do projeto, da UI e dos docs: **PT-BR**.
Commits em Conventional Commits; PRs em português **e** inglês. Atribuição nos commits: `Co-Authored-By: <modelo> <noreply@anthropic.com>` se feitos por Claude.

## 0. Regras do dono (valem sempre)

* **Honestidade**: nunca apresentar resultado simulado; só reportar o que foi medido. Não declarar sucesso porque "gerou um GLB válido". A nota de uma IA **nunca**
  substitui a aprovação visual do usuário.
* **Qualidade artística obrigatória**: "Premium Stylized Low/Mid Poly" (jogo CITY+++).
* **Tudo roda em Docker**, sempre ("lembre-se de usar docker sempre").
* **Segredos**: nunca imprimir chaves SSH/API nem colocar em logs, frontend ou GitHub. Chave SSH: `~/.ssh/id_ed25519_asc` (a pública é a que o dono autorizou nas máquinas).
  Detalhes de acesso em `Desktop/ACESSO-SERVIDORES-HANK.txt` (**não commitar, não imprimir**). Chaves Gemini/Grok são cadastradas **no painel** (guardadas criptografadas no banco).
* **Nunca tocar**: 192.168.1.200 e 192.168.1.210. Sem BIOS/firmware/driver/kernel. Não mexer em serviços de outros projetos.
* **Não modificar o repositório original do Hank** (`AssetPipeline`); na Spark só ler o código/pesos dele (montagem `:ro`).
* Não iniciar produção em massa antes da aprovação visual do piloto e da resolução das licenças. Não iniciar o "Projeto Dragão de Três Cabeças".
* Pedidos de geração seguem **ordem de chegada** (FIFO), sem prioridade por categoria.

## 1. Repositórios

| Repo | Visibilidade | Local |
| --- | --- | --- |
| `gamerplay20p5-dotcom/assetforge` (principal) | público | `C:\Users\Malaio\Desktop\geração 3D` (branch `master`; PR #1 na branch `docs/trellis2-analysis`) |
| `gamerplay20p5-dotcom/AssetPipeline` (do Hank, cópia privada nossa) | **privado** | `C:\Users\Malaio\Downloads\AssetPipeline` |
| `gamerplay20p5-dotcom/HTS-Bot-Multi-servers` (bot do dono; usa `gemini-3.5-flash-lite`) | público | só leitura |

**Cuidado com branches**: o PR #1 (`docs/trellis2-analysis`) tem scripts que `master` não tem (`scripts/trellis2/*`, a opção de escala em `scripts/review/blender_views.py`).
Trocar de branch com arquivos não rastreados conflitantes já deu problema. Trabalhe na branch do PR para o que for TRELLIS.2.

## 2. Infraestrutura

| Máquina | Papel | Observações |
| --- | --- | --- |
| **192.168.1.206** (`afforge`) | Central: API, dashboard, PostgreSQL, filas, workers CPU, Blender | Ubuntu 26.04, Threadripper 3955WX (32 threads), 200 GB RAM, só CPU. Pode usar até 70% de CPU/RAM. Repo em `~/assetforge`. Deploy: `docker compose --env-file .env -f deployment/docker-compose.yml up -d --build <serviço>` (**nunca** `asc-ctl compose up/down`). Container da API tem rootfs **somente leitura**: para scripts avulsos use `docker compose ... run --rm --no-deps -T -v ... api python ...`. |
| **192.168.1.203** (`afforge`, host `htsllm2`) | **Só GPU**: RTX 4090 24 GB, i9-11900K, 22 GB RAM | Roda `vlm-gpu` (Qwen, :8081) e `triposr-gpu` (:8082) via `scripts/vlm/gpu_box.sh` (só Docker, sem compose plugin; token em `~/assetforge/.env.gpu`). Sem sudo. Trabalho pesado de CPU/RAM fica na 206. |
| **192.168.1.252** (`henrylawrencecahill@`, host `spark-f146`) | **NVIDIA DGX Spark (GB10, aarch64, 121 GB de memória unificada)**: máquina principal de geração 3D | A chave do AssetForge foi autorizada na conta do Hank. Código/pesos do Hank em `~/clonez-pipeline` e `~/clonez-models` (ler só). Nosso trabalho em `~/assetforge-pilot`. O run do Hank (`clonez-mesh`, tmux + cron `keep-running`) está **parado por decisão do dono** ("Stopped by hand"); o cron continua instalado, mas inerte até alguém rodar `mesh-start`. |

## 3. O que já existe no AssetForge (tudo em `master`, testado: 244 testes + 11 do dashboard passavam)

* API FastAPI/SQLAlchemy/PostgreSQL, fila com workers e *leases*, dashboard React (Studio estilo Tripo, Fila, Biblioteca, Workers, Painel, **IA na nuvem**).
* **Kit procedural "Premium Stylized"** (`generators/procedural`): casas (arquétipos `ref01..ref06`, etc.), 6 estados de obra, prédios altos (`ref_tower`: térreo alto, vitrine, coluna de varandas, pano de vidro, pilastras, marquise).
* **Visão local**: Qwen2.5-VL 7B (CPU na 206 e GPU na 203, com fail-over). Fluxo "Imagem → casa (IA)".
* **TripoSR** (GPU 203 + CPU 206): provider experimental, resultado ruim para casas/prédios (de propósito não é o padrão).
* **IA na nuvem (Gemini/Grok)** — `docs/CLOUD_AI.md`: várias chaves com ordem e fail-over automático, cota 429 → espera e retoma sozinho, limites por minuto/dia, cache, histórico,
  modo só-gratuito, chaves criptografadas, **agente** `agent.building` (IA escreve HouseSpec → validador → kit+Blender → renders → IA critica e corrige). Modelo padrão
  `gemini-3.5-flash-lite` (o mesmo do bot HTS). Chave do dono já cadastrada na 206. O Gemini recusa schemas com muitos limites: `simplify_schema` os remove.
* Limitação conhecida do agente: a IA (flash-lite) ainda quebra a torre em volumes separados; a nota própria dela é inflada. Prompt já foi endurecido (`spec-v2`).

## 4. Projeto atual: integrar o TRELLIS.2 do Hank (PR #1) — **estado**

Análise completa e licenças em `docs/TRELLIS2_INTEGRATION.md` (ler primeiro). Resumo:

* O pipeline do Hank (imagem → BiRefNet → TRELLIS.2 → master GLB) roda na Spark. Reaproveitar: Dockerfile GB10, recorte BiRefNet, TRELLIS.2 + `to_glb`, watchdog/monitoramento.
  **Não** reaproveitar: encaixe em modelo primitivo, formato `.bytes`, catálogo/juízes gemma (o juiz é o Gemini).
* **Bloqueio de licença**: nvdiffrast e nvdiffrec = só pesquisa/avaliação. Único uso no caminho imagem→3D é a rasterização de UV do `to_glb`. **Já resolvido em código**
  (`generators/trellis2/assetforge_trellis2/`: `uvraster.py` copiado do fork MIT `andrakis/TRELLIS.2-stableprojectorz`, `to_glb.py` derivado do o-voxel, `license_guard.py` que prova que
  nvdiffrast/nvdiffrec não são usados). Auditoria: CuMesh/cubvh/xatlas/FlexGEMM/BiRefNet/TRELLIS.2 = MIT; DINOv3 = comercial permitido **com condições** (controle de exportação, sem usos militares/armas)
  → **revisão jurídica pendente**. Remover nvdiffrast **não** libera o pipeline sozinho.
* `deployment/Dockerfile.trellis2` (sem nvdiffrast/nvdiffrec): **escrito, NÃO construído** (≈1 h de build; pedir autorização e janela, a Spark não comporta dois jobs pesados).

### Medido (torre de referência, 1 de 10 imagens do piloto)

* `1024_cascade` e `1536_cascade` rodaram sem falhas na Spark: ~344–488 s por modelo, pico de memória 74–94 GB (inclui ~55 GB dos modelos residentes), master ≈ 453 mil triângulos.
  Os dois resultados são visualmente quase iguais. Qualidade: muito melhor que TripoSR, mas **cores escuras/marrons** (verde-oliva perdido) e detalhes simplificados.
* **Cor**: a textura base color já nasce escura do bake (paredes ≈98/87/76 contra ≈218/192/164 na referência; mesmo matiz, ganho ≈2,4× em todos os canais; nenhum gamma simples explica).
  **Não** é o Blender (AgX até clareia). Plano: calibração opcional de albedo por ativo (`make_lods.py` tem o parâmetro `albedo_gain`), sem alterar o master.
* **Gemini** (chamada real, `gemini-3.5-flash-lite`) sobre o master: nota 6,0/10, `acceptable_with_fixes`; apontou cor, textura "empastada", gradil do telhado ausente.
  Resultado em `reports_out/trellis_pilot/tower/gemini_master.json`. Módulo reutilizável: `generators/vision/assetforge_vision/compare.py` + `scripts/ai/gemini_compare.py`.
* **Otimização**: decimação por colapso do Blender **destrói** o master (≈1.100 cascas soltas de ≤100 triângulos; LODs ficam rasgados, e para 2,5k/500 nem atinge o alvo sem apagar peças/voxel remesh).
  Conclusão: **gerar os LODs dentro do `to_glb`** (`decimation_target` em vértices; remalhamento estruturado, como o Hank faz) e só assar o **normal map** em Blender (`scripts/trellis2/bake_normals.py`).
  A opção `--lods` do `pilot_reconstruct.py` já gera esses LODs (calibrar vértices→triângulos; alvo 15k/7,5k/2,5k/500 triângulos). **Ainda não executado.**
* **Descoberta**: o remalhamento do `to_glb` **não é determinístico** (duas chamadas deram 460.943 e 485.467 triângulos), então não dá para comparar texturas de dois GLBs gerados em chamadas
  diferentes. A comparação correta é `scripts/trellis2/test_uvraster.py` (nvdiffrast × nosso rasterizador na **mesma** malha/UV). **Ainda não executado.**

### Atualização (mesmo dia, depois do HANDOFF inicial): os blocos da Spark TERMINARAM — ver a seção 8 de `docs/TRELLIS2_INTEGRATION.md` com todos os números (1536 real aborta por memória; rasterizador equivalente IoU 0,9937; bake comercial limpo; LODs pelo to_glb só aguentam ≈15k; Gemini 6,0/2,5/2,1). Pendências 1–3 abaixo estão concluídas; a Spark está livre (nenhum job). O texto a seguir é o estado antigo:

### Em execução quando este arquivo foi escrito

Na Spark (`~/assetforge-pilot`), `chain.sh` roda em sequência: (1) `tower_v2_both` (`--bake both`, resoluções 1024,1024,1536,1536, repetidas p/ aquecimento equivalente) e
(2) `tower_v2_commercial` (`--commercial`, guarda de licença ligado). Estado: `cat ~/assetforge-pilot/chain.status` (linhas `EXIT_BOTH=` / `EXIT_COMMERCIAL=`), métricas em
`~/assetforge-pilot/out/<nome>/metrics.json`, logs `tower_v2_*.log`. Primeiro run do bloco 1 já deu: 1024_cascade 284,6 s TRELLIS + bakes ~50–56 s, pico 74,5 GB, resolução efetiva 1024 (sem redução por limite de tokens).

## 5. Como rodar as coisas

* **Piloto na Spark** (sempre Docker, imagem do Hank `clonez-mesh:1`, código/pesos só leitura): enviar `scripts/trellis2/*` e `generators/trellis2/assetforge_trellis2` para `~/assetforge-pilot/code/`,
  imagem em `~/assetforge-pilot/in/`, e `bash run_pilot.sh <imagem> <nome> --bake torch --commercial --res 1024_cascade ...`. O runner recusa iniciar se `clonez-mesh` ou outro job estiver rodando, tem
  **guarda externo de memória** (para só o nosso container acima de 108 GB ou se o run do Hank voltar), trava de exclusividade (`flock`) e **watchdog interno** (aborta com código 75 se faltar memória).
  Códigos de saída: 0 ok · 1 falhou · 2 BiRefNet sem objeto · 3 recusado · 4 parado pelo guarda · 75 watchdog. Outros scripts: `PILOT_SCRIPT=test_uvraster.py bash run_pilot.sh --glb ... --json ...`.
* **LODs com bake em Blender**: `blender -b -P scripts/trellis2/make_lods.py -- master.glb saida [alvos] [texturas] [albedo_gain]` (decimação; serve de comparação, **não** é o caminho recomendado)
  e `bake_normals.py` (recomendado, sobre LODs vindos do `to_glb`). Blender local: `.tools/blender/*/blender.exe`.
* **Renders de revisão**: `scripts/review/blender_views.py -- modelo.glb prefixo amostras tamanho vistas plain frame_h portrait escala`. Para masters do TRELLIS.2 (caixa unitária) passe `plain 65 portrait 65`.
  **Use caminhos ABSOLUTOS** (relativos saíram em `C:\reports_out`, que o dono deve apagar à mão junto com `C:\view_*.png`).
* **Gemini comparar**: copiar imagens para a 206 (`~/cmp`) e `docker compose ... run --rm --no-deps -T -v $HOME/cmp:/cmp api python /cmp/gemini_compare.py --db --ref ... --views nome=arq ... --out ...` (a chave nunca sai do servidor).
* Testes: `PYTHONPATH=<todos os caminhos de pyproject + tests> python -m pytest -q` (o filho do worker herda o PYTHONPATH); dashboard: `cd apps/dashboard && npx tsc --noEmit -p . && npx vitest run`.

## 6. Pendências (em ordem)

1. Quando `chain.status` mostrar os dois `EXIT_*`: ler `metrics.json` de `tower_v2_both` e `tower_v2_commercial` e reportar tempos **quentes** (repetição 2), resolução efetiva e picos. Confirmar `licence_guard_violations == []` e `failed == false` na execução comercial.
2. Rodar `test_uvraster.py` (equivalência do rasterizador) com a Spark livre; só então considerar o `uvraster` equivalente ao nvdiffrast.
3. Rodar `--lods` (LODs pelo `to_glb`), calibrar vértices→triângulos (15k/7,5k/2,5k/500), assar normal em Blender, renderizar todos com as **mesmas** câmeras/luz, comparar e passar pelo Gemini.
4. Decidir/implementar a **calibração de cor** (ganho de albedo ~2×) como opção por ativo, sem tocar no master.
5. Comparar 1024 × 1536 com aquecimento equivalente; manter **1024_cascade como padrão** e 1536 como alta qualidade.
6. Atualizar o PR #1 com resultados **em português e inglês**, e corrigir informações desatualizadas do corpo do PR (diz "nenhum teste executado").
7. Só depois do piloto aprovado visualmente e das licenças resolvidas: provider `trellis2` definitivo no AssetForge (container separado na Spark, HTTP+Bearer como `triposr-gpu`, 1 job pesado por vez, 4090 como auxiliar só para configurações que caibam em 24 GB — **hipótese não medida**),
   orçamentos por categoria (NPC, veículo, casa, arranha-céu, prédio público, indústria, vegetação, monumento, objeto urbano), exportação GLB/FBX/BLEND pelo pipeline existente, histórico de versões, cancelamento/retomada, upload em massa, painel com visualização interativa.
8. Piloto completo (10 imagens): faltam referências de veículo, NPC, objeto urbano e um segundo arranha-céu (peça ao dono).
9. Dono deve: apagar `C:\reports_out` e `C:\view_*.png` (criados por engano); decidir sobre a licença do nvdiffrast na produção; revisar o DINOv3; autorizar o build do `Dockerfile.trellis2`.

## 7. Armadilhas já encontradas

* Windows/PowerShell+Git Bash: caminhos com acento/espaço (`geração 3D`) — sempre entre aspas. CRLF avisa mas não atrapalha.
* `docker cp` falha no container da API (rootfs somente leitura): use container descartável.
* Gemini 400 "too many states": remover `minimum/maximum/maxItems/pattern` do schema antes de enviar (já em `simplify_schema`); 400 é erro do pedido, **não** cota (não fazer fail-over nem esperar).
* `nvdiffrast`: o `import nvdiffrast.torch as dr` busca o atributo `torch` no pacote — o stub do guarda já cobre isso.
* TRELLIS.2 `Tee`: a mensagem "resolution is reduced to N" (limite de tokens) é capturada por regex em `pilot_reconstruct.py`; o campo `tokens` do metrics é o nº de voxels esparsos, não tokens (renomear).
* O pico de memória da Spark varia entre execuções (74–94 GB); o controle precisa ser contínuo (guarda + watchdog), não só a checagem inicial.

---

# FASE 2 — Comparativo de motores (pixal3d.cpp Q8 × TRELLIS.2 Python × Pixal3D) — atualizado em 2026-11-27/28

Pedido do dono: usar **Spark e RTX 4090 integralmente** como workers de produção 3D; **pixal3d.cpp Q8 nas duas máquinas com prioridade**, sem abandonar o TRELLIS.2 Python; comparar com as **mesmas
referências/câmeras/luz**: TRELLIS.2 Python · TRELLIS.2 GGUF Q8 · Pixal3D.cpp Q8 single-view · Pixal3D.cpp Q8 multi-view · Pixal3D Python na Spark · kit procedural · Gemini+procedural · híbrido.
Registrar: resolução efetiva, tempo, pico RAM/VRAM por etapa, triângulos, textura, fidelidade, componentes desconectados, qualidade após otimização, estabilidade em gerações consecutivas.
**Não** declarar vencedor só pela nota do Gemini. **Não** iniciar desenvolvimentos complexos antes de ter os primeiros modelos reais do Pixal3D. Manter Qwen/TripoSR na 203 (estão ociosos: ~506 MiB de VRAM).

## Código e pesos usados

* `raven38/pixal3d.cpp` commit **`d1b4926452f9e09702b891db5f05acc845e153ed`** (MIT; fork de `pwilkin/trellis.cpp`; ggml vendorizado MIT). Sem Python em execução, **sem nvdiffrast/nvdiffrec** no código (só citados em docs).
* Pesos GGUF (públicos, sem token), em `~/assetforge-models/` de **cada máquina** (script `~/assetforge-engines/download_weights.sh`, retomável):
  * `trellis2-q8/` = `ilintar/trellis2-gguf` pasta `q8` (≈9,3 GB; licença "other" = a do modelo-fonte, MIT) e `trellis2-q4/` (≈6,1 GB).
  * `pixal3d-mv-q8/` = `raven38/pixal3d-q8_0-v1` e `pixal3d-sv-q8/` = `raven38/pixal3d-sv-q8_0-v1` (≈7,5 GB cada; MIT, exceto `dinov3.gguf` = licença DINOv3 — ver `LICENSE.md` na pasta).
  * Pixal3D original (Python): `TencentARC/Pixal3D` (MIT; padrão 1536; `inference.py`, `inference_mv.py`; depende do ambiente TRELLIS.2 + MoGe + natten + utils3d). **Ainda não executado.**
* Imagem Docker: `deployment/Dockerfile.pixal3d-cuda` (Ubuntu 24.04 + CUDA 13.1; compila `trellis-cli`/`trellis-server` do commit fixado). Build:
  `docker build -f Dockerfile.pixal3d-cuda --build-arg CUDA_ARCHS=<arch> --build-arg BUILD_JOBS=<n> -t assetforge-pixal3d:cuda<arch> .` — **203: `89` (tag cuda89)**; **Spark: `121` (tag cuda121)**.
  Os pesos NÃO ficam na imagem (montados em `/models:ro`).

## Erros encontrados e soluções (para não repetir)

1. CMake 3.22 (Ubuntu 22.04) falha com `FetchContent ... DOWNLOAD_EXTRACT_TIMESTAMP` (libwebp) → usar **Ubuntu 24.04**.
2. Link falha com `undefined reference to cuMemCreate...` → no build não há driver: usar o **stub** (`LIBRARY_PATH=/usr/local/cuda/lib64/stubs` + `-Wl,-rpath-link`).
3. `COPY --from=build /src/build/bin` não existe → coletar com `find /src/build -name '*.so*'` para `/out`.
4. **Spark é sm_121**: compilar com `CUDA_ARCHS=120` dá `CUDA error: no kernel image is available` → usar **`121`**.
5. `pkill -f 'docker build'` mata a própria sessão SSH → usar padrão ancorado `'^docker build'`.
6. Scripts `.sh` com CRLF quebram no Linux (`set: pipefail: invalid option`) → `sed -i 's/\r$//'`; `.gitattributes` agora força LF em `*.sh`.
7. Container gravando como root deixa arquivos que não dá para apagar → `docker run --user $(id -u):$(id -g)` (já no `run_cpp.sh`).
8. Substituir `run_cpp.sh` enquanto roda corrompe o bash em execução → copiar para `.new` e `mv` (atômico).

## Como rodar (Docker, medido)

`scripts/engines/run_cpp.sh <nome> <imagem-docker> <subpasta-de-pesos> <subpasta-de-entradas> -- <args do trellis-cli>` em `~/assetforge-engines` de cada máquina. Mede tempo, pico de RAM do sistema, pico de VRAM (4090), grava
`mem.csv` (a cada 0,5 s) e `summary.json`; recusa iniciar se outro job/`clonez-mesh` estiver rodando e para o container se a RAM disponível cair de `MIN_AVAIL_GB` (padrão 10). Entradas em `~/assetforge-engines/refs/`
(`tower.png`, `house_stage6.png`, `house_stage5.png`, `house_stage3_frame.png`, `tower_rgba.png` = recorte BiRefNet gerado pelo próprio trellis-cli com `--dump-bg`). Cadeia de testes: `chain_engines.sh <imagem> <rótulo>`.
Flags úteis do `trellis-cli`: `--res 512|1024|1536`, `--max-tokens`, `--atlas PX`, `--decim` (padrão: 300K faces; `0` = sem decimar), `--sv-image` (+ `--pixal3d-weights sv`), `--views DIR` (+ `--pixal3d-weights mv`), `--trellis2-mv DIR`, `--birefnet`, `--dump-bg`, `--profile`.

## Resultados até agora (torre; sempre medidos, nunca estimados)

| Motor | Máquina | Res. efetiva | Tempo | Pico RAM (sistema) | Pico VRAM | Triângulos / componentes | Obs. |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TRELLIS.2 **Python** (original) | Spark | 1024 (o "1536" também virou 1024 pelo limite de tokens) | ≈285 s TRELLIS.2 + 48–58 s textura | 69–75 GB | n/d (memória unificada) | ≈453 mil (master 500k vért.) | ver `docs/TRELLIS2_INTEGRATION.md` §7–8 |
| TRELLIS.2 **GGUF Q8** (C++) | RTX 4090 | 1024 | **232,6 s** | **8,6 GB** (+6,6 GB sobre a base) | **12,0 GB** (+11,5) | 297.650 tri (decimação padrão 300K) / 19 componentes UV; atlas 4096; GLB 12 MB | 1ª geração real; dir `~/assetforge-engines/out/tower_t2q8_1024_4090` |

Visual (mesmas câmeras do piloto 1): estrutura **mais limpa** que o master Python (coluna de varandas com lajes, faixa central de vidro, cobertura e casa de máquinas legíveis); cor ainda dourada/escura; fachada traseira
inferida plana. **Impressão visual do assistente, não aprovação.** Falta: Gemini, componentes soltos do GLB, qualidade pós-otimização, estabilidade (3 execuções), Pixal3D SV/MV, 1536, Pixal3D Python.

## Estado em execução / pendências (ordem)

1. **4090**: `chain_engines.sh assetforge-pixal3d:cuda89 4090` rodando (Pixal3D SV 1024 → TRELLIS.2 Q8 1536 → 2 repetições do Q8 1024). Resultados: `~/assetforge-engines/chain.status` e `out/*/summary.json`.
2. **Spark**: build `assetforge-pixal3d:cuda121` (log `~/assetforge-engines/build_pixal3d121.log`); ao terminar, rodar a mesma cadeia com `bash chain_engines.sh assetforge-pixal3d:cuda121 spark`. O run do Hank continua **parado**.
3. **Multi-view**: o `trellis-cli --views` precisa de 4 vistas + `transforms.json`. Não temos vistas reais da torre; usar o exemplo oficial `assets/mv_images/example` do repositório TencentARC/Pixal3D (marcar como "exemplo do upstream") e/ou pedir vistas ao dono.
4. **Pixal3D Python na Spark** (derivar da imagem `clonez-mesh:1`; trocar o `to_glb` por `assetforge_trellis2.to_glb_commercial`).
5. Medir por etapa (usar `--profile`, `--profile-cond` e `mem.csv`), contar componentes soltos (`tools/glb_metrics.py` do pixal3d.cpp ou o nosso union-find), LODs/otimização, Gemini (`scripts/ai/gemini_compare.py`), kit procedural e Gemini+procedural com as **mesmas** referências/câmeras.
6. Só depois: scheduler/workers de produção (Spark e 4090) respeitando FIFO e consumo real de recursos.

---

## FASE 2 — ATUALIZAÇÃO FINAL DESTA SESSÃO (2026-11-27/28) — leia isto primeiro

### Referências enviadas pelo dono (já extraídas e preparadas — NÃO refazer)

* Zips em `C:\Users\Malaio\Downloads\`: `CityPlusPlus_Lote_Piloto_40_Referencias.zip` (10 designs × 4 vistas), `CityPlusPlus_Lote_02_20_Referencias.zip` (5 designs × 4 vistas), `CityPlusPlus_52_PNGs_Individuais.zip` (casas e hospitais por etapa de obra).
  Cada design tem as vistas `front`, `right`, `back` e `34` (3/4), 1254×1254, fundo cinza claro, estilo "Premium Stylized Low/Mid Poly". São 15 designs: arranha-céus (commercial_001, residential_001/002, special_001), NPCs (civilian_001/002, government_001, public_service_001, worker_001/002) e veículos (civilian_001/002, emergency_001, industrial_001, public_transport_001).
  O manifesto avisa: as vistas são referências **independentes** e podem ter pequenas diferenças de escala, pose e módulos; conferir contra a frente.
* Extraídas em `reports_out/engines/refs_city/{piloto40,lote02_20,png52}` (com `python -I`, sem caminhos suspeitos).
* **Recorte BiRefNet em quadro cheio** (sem recropar), feito na Spark em Docker com a imagem e os pesos do Hank (somente leitura): `scripts/engines/matte_birefnet.py` → `reports_out/engines/city_rgba/` (60 PNGs RGBA).
* **Entradas por motor**: `scripts/engines/prep_views.py` → `reports_out/engines/city_inputs/<ativo>/`: `front.png` (RGB original; TRELLIS.2), `sv_rgba.png` (RGBA; Pixal3D single-view), `mv4/` (front, right, back e 3/4 com `transforms.json`, azimutes 0/90/180/**45**) e `mv3/` (3 vistas).
  Regras do pixal3d.cpp respeitadas: alfa real, sem recrop, mesma escala em todas as vistas, objeto a ≈85 % do quadro, centrado. Câmera canônica: distância 3,119, FOV 20°, elevação 0, mundo z-up, azimute 0 = frente e 90 = direita (convenção do `transforms.json` do exemplo oficial).
  **Suposição não verificada**: a vista "34" é frente-direita a 45°. Se o multi-view sair torto, testar `mv3` ou trocar o azimute (315).
* Já copiadas para `~/assetforge-engines/refs/city/` nas duas máquinas.

### O que está rodando AGORA (não repetir; só acompanhar)

Duas cadeias independentes, uma por máquina, **um job por vez em cada** (`scripts/engines/chain_city.sh`; ignora o que já terminou e tenta de novo quando o lock está ocupado):

* **RTX 4090** (usuário `afforge` na máquina da 4090): `bash chain_city.sh assetforge-pixal3d:cuda89 4090 1024 <6 ativos>`. Os 6 ativos são `bldg_skyscraper_residential_001 bldg_skyscraper_commercial_001 npc_civilian_001 npc_worker_001 veh_civilian_001 veh_industrial_001`. Por ativo: **t2q8** (TRELLIS.2 Q8, vista frontal), **sv** (Pixal3D single-view Q8) e **mv4** (Pixal3D multi-view Q8, 4 vistas). Resolução **1024**.
* **Spark** (conta do Hank): a mesma lista em **1536**, com a imagem `assetforge-pixal3d:cuda121`.
* Acompanhar: `cat ~/assetforge-engines/chain_city.status` (linhas `<nome> EXIT=<código>`; `CITY_CHAIN_DONE` no fim). Resultados em `~/assetforge-engines/out/<ativo>_<motor>_<res>_<máquina>/` (`model.glb`, `summary.json`, `mem.csv`, `raw.log`).
  Códigos: 0 ok · 3 lock ocupado (a cadeia repete) · 4 parado pelo guarda de memória · outro valor = falha do `trellis-cli` (ver `raw.log`).
* O run do Hank na Spark segue **parado**. Qwen e TripoSR na 4090 seguem ativos (VRAM ociosa ≈ 506 MiB).
* Duração estimada (não medida): 4090 ≈ 50–70 min; Spark em 1536 ≈ 1–2 h.

### Como analisar quando terminar (comandos)

```
bash scripts/engines/fetch_results.sh     # baixa os runs concluídos das duas máquinas para reports_out/engines/results/
.venv/Scripts/python scripts/engines/analyze_city.py --results reports_out/engines/results --refs reports_out/engines/city_inputs --out reports_out/engines/analysis
```

Por modelo: triângulos, componentes soltos, nivelamento (`level_glb.py`, não destrutivo) e 4 renders com as mesmas câmeras. Por ativo: folha em `reports_out/engines/analysis/sheets/<ativo>.jpg` e `analysis/all.json`.
Depois: Gemini (só conselho) com `scripts/ai/gemini_compare.py` (rodar num container descartável na central, ver a seção "Gemini comparar" acima) e **aprovação visual do dono**. Não declarar vencedor só pela nota.

### Resultados medidos nesta fase (todos reais)

| Execução | Máquina | Res. | Tempo | Pico RAM (acima da base) | Pico VRAM | Triângulos / componentes |
| --- | --- | --- | --- | --- | --- | --- |
| Torre · TRELLIS.2 Q8 | 4090 | 1024 | 232,6 s | +6,6 GB | 12,0 GB | 297.650 / 19 (UV) |
| Torre · TRELLIS.2 Q8 | 4090 | **1536** | 336,5 s | +7,9 GB | 14,6 GB | ver `out/tower_t2q8_1536_4090` |
| Torre · Pixal3D single-view Q8 | 4090 | 1024 | **127,1 s** | +3,1 GB | **7,2 GB** | 931.734 |
| Residencial_001 · TRELLIS.2 Q8 | 4090 | 1024 | 160,0 s | +4,1 GB | 8,1 GB | 295.794 / **1 componente** |
| (referência) Torre · TRELLIS.2 **Python** | Spark | 1024 | ≈ 285 s + 50 s de textura | 69–75 GB (sistema) | n/d | ≈ 453 mil |

* **Pixal3D single-view é ≈ 45 % mais rápido que o TRELLIS.2 Q8 e usa ≈ 40 % menos VRAM**. Cor e detalhe de fachada ficam **mais fiéis** à referência (bege com verde-oliva, caixilhos, pilastras), mas o modelo sai **no referencial da câmera, inclinado** (≈ 9,9° na torre).
* **Correção de orientação** (`scripts/engines/level_glb.py`): estima a inclinação do eixo dominante e grava um GLB NOVO só com um nó pai (rotação + translação: de pé, pivô na base). Vértices e texturas ficam byte a byte iguais ao original, então o master é preservado. Torre single-view: profundidade 0,655 → 0,535; o TRELLIS.2 já vinha ≈ 1,2°. Limite de segurança `--max-tilt 40`.
* **TRELLIS.2 Q8 em 1536 funciona em C++** (o Python original não coube/foi reduzido a 1024): 336 s e 14,6 GB de VRAM.
* O TRELLIS.2 com **uma** vista inventa a traseira lisa; esperado. O multi-view é o teste que deve resolver isso.
* Erro do runner já corrigido: processos filhos do guarda herdavam o `flock` (fd 9) e o job seguinte era recusado (código 3 em cascata). Agora o guarda e o `docker run` fecham o fd 9 e a cadeia repete em código 3.

### Arquivos novos desta fase (branch `feat/engines-comparison`)

`deployment/Dockerfile.pixal3d-cuda` · `scripts/engines/{run_cpp.sh, chain_city.sh, matte_birefnet.py, prep_views.py, level_glb.py, analyze_city.py, fetch_results.sh}` · `scripts/trellis2/*` (fase 1) · `.gitattributes` (LF em `*.sh`).

Nas máquinas, em `~/assetforge-engines`: `refs/` (entradas), `out/` (resultados), `run_cpp.sh`, `chain_city.sh`, `download_weights.sh`, `city_inputs.tgz`, `build_pixal3d*.log`. Pesos em `~/assetforge-models/{trellis2-q8,trellis2-q4,pixal3d-mv-q8,pixal3d-sv-q8}` (≈ 31 GB em cada máquina).
Imagens Docker: `assetforge-pixal3d:cuda89` (4090), `:cuda120` (Spark, **não serve**: a GB10 é sm_121) e `:cuda121` (Spark).

### Próximas etapas (em ordem; NÃO repetir o que está acima)

1. Esperar `CITY_CHAIN_DONE` nas duas máquinas, depois `fetch_results.sh` e `analyze_city.py`, e ler as folhas `analysis/sheets/*.jpg` e o `all.json`.
2. Comparar a **fidelidade visual por categoria** (arranha-céus, NPCs, veículos): T2 Q8 × single-view × MV4, em 1024 e 1536. Contar componentes soltos e medir **estabilidade** (repetir 3× o mesmo motor/ativo; ainda não feito).
3. **Multi-view com 3 vistas** (`mv3`) e a suposição do azimute 45° (ver acima); usar o exemplo oficial do Pixal3D como controle.
4. **Pixal3D Python na Spark** (derivar de `clonez-mesh:1`; MoGe, natten, utils3d; trocar o `to_glb` por `assetforge_trellis2.to_glb_commercial`). **Não iniciado.**
5. **Otimização não destrutiva e LODs** a partir dos masters do Pixal3D (≈ 930 mil triângulos). O colapso do Blender destrói masters feitos de cascas soltas; conferir primeiro os componentes dos masters do pixal3d.cpp (o T2 Q8 já dá 1). Testar decimação com preservação de arestas e normal map assado em Blender (`scripts/trellis2/bake_normals.py`).
6. **Cor e textura**: comparar a base color com a referência (método do piloto 1: valores primeiro, depois o Blender). O single-view mostrou cor bem mais próxima.
7. Kit procedural, Gemini + procedural e híbrido competem com as **mesmas** referências e câmeras (ainda não rodados nesta fase).
8. **Scheduler e workers de produção** (Spark e 4090, FIFO, consumo real de recursos) só depois do piloto aprovado: provider HTTP em container separado (ver a seção 4 da Fase 1). Não iniciar produção comercial sem aprovação; a licença do DINOv3 segue pendente de revisão jurídica.
