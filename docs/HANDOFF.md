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
