# Integração do motor TRELLIS.2 do AssetPipeline (Hank) — análise / TRELLIS.2 integration analysis

Estado: **piloto em andamento (1 de 10 imagens medida), nada integrado ao AssetForge.** Nenhum resultado abaixo é de teste: tudo vem da leitura do código
e das licenças publicadas. / Status: analysis only; the pilot has not run.

Fonte estudada (somente leitura, o repositório do Hank não foi alterado): `github.com/gamerplay20p5-dotcom/AssetPipeline` — `mesh/Dockerfile`,
`mesh/meshgen.py` (1.637 linhas), `mesh/meshpost.py` (658), `mesh/spark.sh`, `mesh/README.md`, `pipeline.py`, `geometry.py`, `llm.py`.

## 1. O que o pipeline faz

```
descrição (gemma3:12b, Ollama) → foto 1536 px (Z-Image-Turbo) → juiz de foto (gemma3) → recorte (BiRefNet) → TRELLIS.2 (1536_cascade)
  → master GLB (to_glb, ~500 mil triângulos, textura 4096) → cópia de jogo (LOD near/far) + normal map baked + mask map
  → encaixe no modelo primitivo do item → .bytes (CZM2) + previews (nvdiffrast) → juiz de malha (gemma3)
```

Medido pelo Hank na Spark (README dele, **não reproduzido por nós**): 2,5 a 16 min por versão; pico de ~116 GB dos 124 GB de memória unificada
(item largo e plano em 1536); 1024_cascade reduz o pico para ~22 GB (item "boné"), contra 30 GB em 1536.

## 2. O que dá para reaproveitar e o que é específico do jogo dele

| Peça | Reaproveitar? | Observação |
| --- | --- | --- |
| `Dockerfile` (CUDA 12.9, torch 2.7.1+cu128, Triton nightly para sm_121a, transformers 4.56.0, flash-attn 2.8.3, commits fixados) | **Sim, como está** | É a parte difícil e já funciona na GB10 (aarch64). Seguir o `mmanco/spark-trellis2-docker`. |
| `meshgen.py`: `Generator.cutout` (BiRefNet + recorte em resolução cheia), `Generator.mesh` (TRELLIS.2 `run` + `to_glb`), `PINS`, `prepare` (pesos fixados, troca DINOv3/RMBG por versões sem conta) | **Sim** | Núcleo de imagem→malha. Precisa ser extraído do `Generator`, que também carrega Z-Image e Ollama. |
| Watchdog (`--stage-timeout`, faulthandler, `attempts.json`, desistir após 2 falhas), `Live` (amostragem de memória/GPU) | **Sim (ideia e boa parte do código)** | Cobre "falhas, timeouts e monitoramento de memória" do pedido. |
| `meshpost.export_master`, `drop_inner_shells`, `bake_normal_map`, `mask_map`, `render` (previews) | **Sim, com adaptação** | Genéricos. `bake_normal_map` e `render` dependem de nvdiffrast (ver licenças). |
| `meshpost.fit`/`frames`/`place`, `write_mesh_file` (.bytes CZM2), `reach` | **Não** | Encaixam a malha no *modelo primitivo de inventário* do jogo; o formato é proprietário. Para o CITY+++ o ajuste é por categoria (escala, pivot, orçamento) — já temos no AssetForge. |
| `llm.py`, `prompts/system.md`, `catalog.py`, `geometry.py`, `pipeline.py` (etapa cubos/esferas) | **Não** | Catálogo e formato de itens do jogo dele; o juiz de foto/malha será o Gemini (já integrado). |
| Z-Image-Turbo (texto→foto) | **Opcional** | Só quando o usuário pedir asset a partir de texto, como definido. |

## 3. Licenças (verificadas nos textos publicados em 2026-11-27; não é parecer jurídico)

| Componente | Licença | Uso comercial |
| --- | --- | --- |
| TRELLIS.2 (código e pesos 4B), o-voxel | MIT (Microsoft) | Sim |
| BiRefNet (código e pesos) | MIT | Sim (termos dos dados de treino não auditados) |
| CuMesh, **cubvh** (submódulo do CuMesh), **xatlas** (submódulo do CuMesh), FlexGEMM, utils3d, CuMesh | MIT | Sim |
| Z-Image-Turbo (opcional) | Apache-2.0 | Sim |
| flash-attn, PyTorch, pytorch-triton | BSD / MIT | Sim |
| DINOv3 (encoder do TRELLIS.2; `timm/vit_large_patch16_dinov3`) | Licença própria da Meta (19/08/2025): uso, cópia e modificação **royalty-free**; sem cláusula não comercial. Exige cumprir leis de controle comercial e **proíbe usos finais militares/de guerra, ITAR e "desenvolvimento ou uso de armas"**; a licença deve acompanhar qualquer redistribuição | **Sim, com condições** — revisão jurídica; evitar gerar armas com este pipeline |
| **nvdiffrast** e **nvdiffrec** | NVIDIA Source Code License (1-Way Commercial): "only may be used or intended for use non-commercially", definido como "research or evaluation purposes only" | **NÃO** sem licença da NVIDIA |
| `plyfile` (GPL), `easydict` (LGPL-3.0), `lpips` (metadado "UNKNOWN"), `tqdm` (MPL-2.0) — presentes na imagem do Hank | GPL/LGPL/MPL | Uso interno ok; **só importam se a imagem for redistribuída**; `lpips` é BSD-2 no repositório, metadado incompleto |
| RMBG-2.0 (padrão do TRELLIS.2, CC BY-NC) | Não comercial | **Não usado**: o pipeline do Hank já o troca por BiRefNet |

Onde o nvdiffrast/nvdiffrec são usados no TRELLIS.2: `to_glb` do o-voxel (rasterização de UV para baking, **único ponto do caminho imagem→3D**), e os renderizadores
de preview (`mesh_renderer`, `pbr_mesh_renderer`, `trellis2_texturing`; o nvdiffrec só aparece no `pbr_mesh_renderer`, para iluminação por mapa de ambiente). O
`meshpost.py` do Hank também usa nvdiffrast para previews e normal map, mas isso é código do jogo dele, que não reaproveitamos (usamos o Blender).

### O que foi feito para sair da dependência (código no nosso projeto)

* `generators/trellis2/assetforge_trellis2/uvraster.py`: rasterizador de UV em PyTorch puro (MIT), copiado **sem alteração** de
  `andrakis/TRELLIS.2-stableprojectorz` (o fork de TRELLIS.2 que tem exatamente a troca que precisamos), com a atribuição em `THIRD_PARTY_LICENSES.md`.
* `to_glb.py`: cópia do `to_glb` original do o-voxel (MIT) com **um bloco trocado** (a rasterização usa `rasterize_uv`); renomeada `to_glb_commercial`.
* `license_guard.py`: troca nvdiffrast/nvdiffrec por *stubs* que importam normalmente mas **lançam erro ao serem usados**, e registra toda tentativa de uso. Uma
  execução que termina com `--commercial` prova que o caminho não precisou deles (`licence_guard_violations` vazio no `metrics.json`).
* `deployment/Dockerfile.trellis2`: imagem derivada da do Hank **sem nvdiffrast e nvdiffrec** (escrita, **não construída**).
* Resultados separados por proveniência: `experimental/` (usou nvdiffrast, **não comercial**) e `commercial_candidate/`. Nada é marcado
  `commercial_ready` enquanto restarem itens em aberto (DINOv3, termos dos dados do BiRefNet, GPL/LGPL se a imagem for redistribuída).

**Remover o nvdiffrast não libera o pipeline sozinho**: as pendências acima continuam.

## 4. Desenho proposto (após o piloto aprovado)

* Provider `trellis2` no AssetForge, em container **separado** (aarch64/GB10), no mesmo padrão do `triposr-gpu` (HTTP + Bearer, fail-over, fila por ordem
  de pedido). Um job pesado por vez; o provider recusa novo job se a memória livre estiver abaixo do limite configurado.
* Fluxo: imagem enviada → BiRefNet → TRELLIS.2 → master GLB (guardado, nunca sobrescrito) → otimização/LOD/exportação pelo pipeline do AssetForge
  (GLB, FBX, BLEND) → renders frontal/lateral/traseiro/perspectiva → Gemini compara com a imagem original → **aprovação visual do usuário**.
* Parâmetros: resolução (512, 1024, 1024_cascade, 1536_cascade), orçamento de tokens, seed, regeneração seletiva (nova seed sem trocar a referência),
  histórico de versões, cancelamento/retomada.
* Orçamentos por categoria (NPC, veículo, casa, arranha-céu, prédio público, indústria, vegetação, monumento, objeto urbano): reaproveitar
  `CATEGORY_BUDGETS` e acrescentar texturas, dimensões, escala e pivot.
* 4090 (203): candidata a worker auxiliar **só nas configurações que cabem** em 24 GB de VRAM e 22 GB de RAM (provavelmente 512/1024); **hipótese, ainda
  não medida**.

## 5. Bloqueios e pendências

1. **Acesso à Spark.** `henrylawrencecahill@192.168.1.252` (conta usada pelos scripts do Hank) recusou as chaves da máquina de desenvolvimento
   (`Permission denied (publickey,password)`). Sem isso não dá para listar serviços, reaproveitar imagem Docker/pesos nem rodar o piloto. Preciso
   que o dono libere um acesso específico para o AssetForge (conta própria e chave autorizada), sem compartilhar a senha do Hank.
2. **A Spark está ocupada pelo pipeline do Hank** (README: ele usa a máquina "dia e noite", há cron de "keep-running" e trava com o Night Shift).
   Nada será iniciado lá enquanto isso não for combinado: o piloto precisa de uma janela em que o Hank pare o run (`mesh-stop`) ou autorize uso
   concorrente, e a memória (até 116 GB de 124 GB) não comporta os dois ao mesmo tempo.
3. **Licença do nvdiffrast/nvdiffrec** (seção 3) e confirmação da DINOv3.
4. **Pesos e imagem Docker**: o README cita `~/clonez-models` (~50 GB) e a imagem `clonez-mesh:1`. Reaproveitar exige autorização do Hank e leitura
   (sem alterar) desses diretórios.

## 6. Piloto planejado (não executado)

2 casas, 2 arranha-céus, 2 veículos, 2 NPCs, 2 objetos urbanos; 1024_cascade e, se a memória permitir, 1536_cascade. Registrar por modelo: tempo total, pico
de memória, triângulos (master e otimizado), texturas, falhas e fidelidade (comparação lado a lado + nota do Gemini como apoio, nunca como aprovação).
Resultados só entram aqui depois de rodados.

## 7. Piloto 1 — torre residencial (medido em 2026-11-27, DGX Spark, Docker `clonez-mesh:1`)

Imagem: a torre de 19 andares usada como referência (a mesma em que o TripoSR falhou). Script: `scripts/trellis2/pilot_reconstruct.py` +
`run_pilot.sh` (container separado; código e pesos do Hank montados **somente leitura**; saída em `~/assetforge-pilot`). Seed 1, 49.152 tokens, master 500 mil
vértices / textura 4096. Rodou com o run do Hank parado por pedido do dono.

| | 1024_cascade | 1536_cascade |
| --- | --- | --- |
| TRELLIS.2 | 424 s | 287 s |
| `to_glb` (master) | 57 s | 52 s |
| Total | 488 s | 344 s |
| Pico de memória do sistema | 93,2 GB | 93,6 GB |
| Pico alocado pelo PyTorch | 42,3 GB | 42,3 GB |
| Triângulos do master | 453.489 | 453.440 |
| Arquivo | 23,6 MB | 23,6 MB |
| Falhas | nenhuma | nenhuma |

Notas: carregar os modelos levou 78 s (pico 55,6 GB, residentes); recorte BiRefNet 1,4 s. **Os tempos não são comparáveis entre as duas colunas**: o 1536 rodou
depois do 1024 no mesmo processo (kernels já compilados/aquecidos). Os dois picos quase iguais sugerem que o limite de tokens (49.152) limita ambos; não foi
verificado no log.

Avaliação visual (folha `reports_out/trellis_pilot/tower/sheet.jpg`, mesma câmera): massa geral, ritmo de janelas, coluna de varandas com lajes, cobertura e térreo de vitrine
reconhecíveis e **muito mais próximos da referência que o TripoSR**. Diferenças visíveis: cores mais escuras/alaranjadas (a referência é bege claro com detalhes
oliva), faixa central de vidro escura menos nítida, detalhes da marquise e da casa de máquinas simplificados. 1024 e 1536 ficaram visualmente quase iguais.
**Ainda não avaliado:** qualidade após otimização (o master tem 453 mil triângulos; o orçamento de arranha-céu é 5–15 mil), comparação do Gemini, aprovação do usuário.

## 8. Piloto 1 (continuação) — correções, bake comercial, LODs, cor e Gemini (medido em 2026-11-27)

**Correções do piloto**: código de saída correto (0 ok · 1 falha · 2 sem objeto · 3 recusado · 4 guarda externo · 75 watchdog); exclusividade por `flock` e checagem de
`clonez-mesh`/outro job no início **e durante** a execução; guarda de memória externo (para só o nosso container acima de 108 GB) e watchdog interno (aborta se a memória
disponível cair de 12 GB); resolução efetiva registrada; repetição por resolução para aquecimento equivalente.

**Resolução efetiva e desempenho** (torre; 4 execuções com nvdiffrast + 3 com bake comercial, **nenhuma falha**):

| Pedido | Resolução efetiva | TRELLIS.2 | Total | Pico de memória |
| --- | --- | --- | --- | --- |
| 1024_cascade (1ª / repetida) | 1024 / 1024 | 284,6 s / 284,0 s | 403 s / 395 s | 74,5 / 71,5 GB |
| 1536_cascade (1ª / repetida), `--max-tokens 49152` | **1024 / 1024** | 285,0 s / 284,9 s | 414 s / 399 s | 75,2 / 69,1 GB |
| 1536_cascade, `--max-tokens 131072` | 1536 (amostragem concluída) | ≈ 6 min 35 s por etapa de amostragem | **abortado pelo watchdog**: sobraram 11,4 GB | — |

* **O "1536" anterior nunca foi 1536**: o limite de tokens o reduz para 1024 (por isso 1024 e 1536 saíram idênticos e com o mesmo tempo). O tempo "344 s do 1536" reportado antes **não vale**.
* **Aquecimento** não alterou o tempo (284,6 s → 284,0 s).
* O **1536 real não cabe** com os modelos residentes (~55 GB): precisa de carregamento mais enxuto (o fork stableprojectorz documenta pico de 14,6/18,9 GB em 1024/1536 contra 33/35 GB sem ele) — **não testado**.

**Bake comercial sem nvdiffrast**: o bloco `--commercial` (guarda de licença ligado) terminou com `licence_guard_violations: []` — o caminho **não usou** nvdiffrast nem nvdiffrec. Tempo e
pico iguais aos do bake original (bake 47–58 s; pico 72–74 GB). **Equivalência do rasterizador** (`test_uvraster.py`, mesma malha e UV, 2048 px): cobertura IoU **0,9937**
(2.348.760 contra 2.350.038 texels; diferenças só em bordas compartilhadas), erro médio de posição 3D **5,6×10⁻⁷** do tamanho do modelo (p99 1,5×10⁻⁶; máx. 0,0042 ≈ 8,7 texels).
Nosso rasterizador: 0,56 s e 3,1 GB; nvdiffrast: 0,15 s e 0,34 GB. **Observação**: o remalhamento do `to_glb` **não é determinístico** (460.943 contra 485.467 triângulos em duas chamadas),
por isso não se comparam texturas de GLBs gerados em chamadas diferentes.

**Cor** (valores primeiro, iluminação depois): a textura base color **já nasce escura do bake**: paredes claras ≈ 98/87/76 contra ≈ 218/192/164 na referência — mesmo matiz,
ganho ≈ 2,4× em todos os canais; nenhuma curva gamma simples explica (melhor ajuste y = 3,49·x^1,40). O Blender **não** escurece (AgX até clareia: 130/105/87). Conclusão: albedo mais escuro que a foto
iluminada (e o verde-oliva se perde). Opção planejada: calibração de albedo por ativo (parâmetro `albedo_gain` de `make_lods.py`), sem alterar o master. Não aplicada.

**LODs** (alvos 15.000 / 7.500 / 2.500 / 500 triângulos):
1. *Decimação por colapso no Blender* (`make_lods.py`): **inutilizável** — o master é ≈ 1.100 cascas soltas de ≤ 100 triângulos; o colapso rasga a malha já em 15 mil (e nem chega a 2,5 mil/500 sem apagar peças e remalhar por voxel).
2. *LODs pelo `to_glb` comercial* (`--lods`; 14.729 / 6.989 / 2.354 / 404 triângulos; ~26–29 s cada) + **normal map assado em Blender** a partir do master (`bake_normals.py`; 1–6 s cada):
   **LOD0 reconhecível, com buracos e riscos escuros; LOD1 degrada (varandas rasgadas); LOD2 e LOD3 inutilizáveis (espetos/lâminas)**. Os alvos de vértices precisam de calibração (triângulos ≈ 0,72–0,89 × vértices).
   **Conclusão: nenhum método genérico entrega 15k/7,5k/2,5k/500 com qualidade a partir deste master.** Direção a testar: proxies para edifícios (volume + textura de fachada assada) ou o próprio kit procedural/agente para LOD2–LOD3.

**Gemini** (`gemini-3.5-flash-lite`, comparação direta com a imagem original; nota é conselho, **não** aprova):

| | Nota | Veredito | Observação |
| --- | --- | --- | --- |
| Master 453 mil | 6,0 | acceptable_with_fixes | silhueta 8, proporções 7, materiais 5, cores 6; cor virou marrom, textura "empastada", gradil do telhado ausente |
| LOD0 14,7 mil | 2,5 | unfaithful | estrangulamentos, buracos nas paredes, textura esticada |
| LOD1 7,0 mil | 2,1 | unfaithful | idem, pior |

Aprovação visual do usuário: **pendente**. Folhas: `reports_out/trellis_pilot/tower/sheet.jpg` e `tower_v3/sheet_lods_v3.jpg` (não versionadas).
