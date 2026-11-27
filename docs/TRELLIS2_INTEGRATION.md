# Integração do motor TRELLIS.2 do AssetPipeline (Hank) — análise / TRELLIS.2 integration analysis

Estado: **análise concluída, nada integrado.** O piloto ainda não rodou (ver "Bloqueios"). Nenhum resultado abaixo é de teste: tudo vem da leitura do código
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

## 3. Licenças (o que foi verificado)

| Componente | Licença | Uso comercial |
| --- | --- | --- |
| TRELLIS.2 (código e pesos 4B), BiRefNet, CuMesh, FlexGEMM, utils3d | MIT | Sim |
| Z-Image-Turbo | Apache-2.0 | Sim |
| flash-attn, PyTorch | BSD | Sim |
| DINOv3 (encoder do TRELLIS.2, via `timm/vit_large_patch16_dinov3`) | Licença própria da Meta (`dinov3-license`) | **A confirmar** com a licença completa antes de produção |
| **nvdiffrast** e **nvdiffrec** (NVIDIA Source Code License, "1-Way Commercial") | O texto diz que o trabalho "only may be used or intended for use non-commercially", e define isso como "research or evaluation purposes only" | **NÃO sem licença da NVIDIA** |

**Bloqueio de licença.** O `to_glb` do o-voxel (que gera as texturas PBR do master) e os previews/baking do `meshpost.py` usam o nvdiffrast. Isso é
adequado para **avaliação/pesquisa** (o piloto), mas a produção em massa de assets comerciais do CITY+++ exige **ou** uma licença comercial da NVIDIA
**ou** trocar o nvdiffrast (rasterização para baking e previews) por alternativa livre. Esta análise não é parecer jurídico; a decisão é do dono do projeto.

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
