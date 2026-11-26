# Integração com o Intel AI Playground (ComfyUI headless) — **DESABILITADA por padrão**

> **2026-11-26:** na 206 o PyTorch XPU não enxerga a A750 sem Resizable BAR (e não vamos mexer em BIOS/driver/reinício). Este caminho ficou como **opção futura**
> (`ASSETFORGE_ENABLE_INTEL_AI=1`). O método de IA em uso é a geração só com CPU: **[CPU3D.md](CPU3D.md)**.


Fontes consultadas em **2026‑11‑26** (GitHub/Hugging Face): `intel/AI-Playground` (MIT, release **v3.3.0 beta**, commit
`1aa8423…`), cards dos modelos e READMEs upstream. Tudo marcado **“não validado”** só será afirmado após rodar no hardware do Hank.

## 1. O que a investigação encontrou

**Workflow Pixel3D‑Trellis** (`modes/base/presets/pixel3d-trellis.json`) — *“Create a detailed 3D model with PBR textures from a single image”*.
* É um grafo **ComfyUI API** com nós **nativos** (`requiredCustomNodes: []`): `Pixal3D*`, `Trellis2*`, `MoGe*`, `RemoveBackground`
  (BiRefNet), `RemeshMesh` (Narrow‑Band DC), `DecimateMesh`, `UnwrapMesh`, `BakeTextureFromVoxel`, `BakeNormalMapFromMesh`,
  `BakeAmbientOcclusion`, `ApplyTextureToMesh`, `SaveGLB`. **Pixal3D é o padrão; TRELLIS.2 é um interruptor** (`Use TRELLIS.2`).
* Entrada: **uma imagem** (objeto isolado, fundo liso). **Não aceita prompt de texto** → o “texto→3D” é composto: texto→imagem→3D.
* Controles expostos: passos (12), resolução de textura (1024–4096, padrão 4096), contagem alvo de faces (padrão 7000), remover fundo.
* Pesos: Pixal3D int8 (**5,6 GB**), TRELLIS.2 int8, DINOv3 (encoder), MoGe‑2, BiRefNet, 2 VAEs. Parâmetro exigido do ComfyUI: `--use-quad-cross-attention`.
* O preset vem **etiquetado `high-vram`**. O README do TRELLIS.2 upstream diz “NVIDIA ≥ 24 GB”; o AI Playground reempacota em int8 e
  roda em Arc, mas **não há dado público de que caiba/rode numa A750 de 8 GB** (as notas da release listam “Arc A Series com 8 GB+” para o app em geral, não para este workflow).
**Backend**: ComfyUI **v0.34.0** (`backend-versions.json`), Python 3.12, `torch==2.13.0` XPU via `uv` (`comfyui-deps/pyproject.toml` + `uv.lock`), parâmetros padrão do app `--lowvram --reserve-vram 6.0`.
O app é Electron/Windows‑first, mas o código contém **caminho Linux** (detecção de Level Zero, instalação de `libze1`, `libze-intel-gpu1`, `intel-opencl-icd` pelo repositório da Intel e `LD_LIBRARY_PATH` de oneAPI) — foi reaproveitado em `scripts/intel_ai/`.
**Texto→imagem**: preset `z-image` (**Z‑Image‑Turbo**, Apache‑2.0). Usa 2 custom nodes (SafetyChecker NSFW, ComfyMath) que removemos em tempo de execução (ver abaixo).

## 2. Reaproveitado × implementado por nós

| Capacidade | Origem |
|---|---|
| Grafos dos workflows (Pixel3D‑Trellis, Z‑Image) | **Intel, vendorizados sem alteração** (`vendor/aipg`, MIT, commit fixado, `NOTICE.md`) |
| ComfyUI, torch XPU, dependências, `uv.lock`, parâmetros, libs oneAPI | **Intel** (baixados no commit fixado pelo `install_node.sh`) |
| **Retopologia + preservação de detalhe** | **Intel (dentro do workflow)**: remesh DC → decimate p/ contagem alvo → UV unwrap → bake de normal map e AO a partir do high‑poly → PBR |
| Redução automática de polígonos | alvo vem do **orçamento do contrato** (categoria × perfil); Intel decima no workflow; Blender (Collapse) limita o LOD0 se ainda exceder |
| Cliente ComfyUI headless, injeção `nodeTitle/nodeInput`, normalização de caminhos Windows→Linux | nosso (`assetforge_intel_ai`) — formato idêntico ao do AI Playground |
| Gerenciador/cache de modelos (layout `models/<tipo>/<dono>---<repo>/…`, SHA‑256 do HF, retomada, offline) | nosso; **layout compatível** com um AI Playground já instalado |
| Perfis de qualidade, LODs, normalização de escala/pivô, FBX com `_LODn` (LODGroup na Unity), BLEND, miniatura, validação, manifesto | nosso (Blender, `ai_runner.py`) |
| Fila, VRAM como recurso, distribuição entre nodes, gate de validação | nosso (usa as filas existentes) |

**Retopologia**: NÃO há quad‑remesh (Quadriflow) com reprojeção de textura — seria reimplementar o que o workflow da Intel já resolve
(remesh + decimate + unwrap + bake). Fica como item futuro **só se** a validação visual mostrar topologia inadequada.

## 3. Pipeline implementado

```
texto ─ Z‑Image‑Turbo (ComfyUI) ─▶ imagem ─┐
referência enviada (validada/re‑codificada)┴▶ Pixal3D | TRELLIS.2 (ComfyUI) ─▶ GLB bruto
   ─▶ Blender: importa, normaliza (1 u = 1 m, pivô base‑centro, altura real), limita ao orçamento,
      LOD0..N (Decimate Collapse, UVs/normal maps preservados) ─▶ model.glb, model_lodN.glb, model.fbx (LOD0.._LODn), model.blend, miniatura
   ─▶ validação (GLB re‑lido, LODs monotônicos, orçamento, densidade “não protótipo”) ─▶ manifesto (ai_model, licenças, proveniência, hashes) ─▶ pacote
```
Tipos de job: `ai.text_to_3d`, `ai.image_to_3d` (mesma fila; requisitos: features `comfyui`+`blender`, **VRAM 7000 MB** reservada, 8 GB de RAM).
Distribuição: qualquer node que anuncie as features e tenha VRAM livre puxa o job; vários nodes = trabalho distribuído automaticamente.

### Segurança e coexistência (GPU compartilhada com o AI Stream Clipper)
1. **Gate de validação**: o worker só anuncia `ai.*` se ComfyUI responde com GPU, **todos os modelos estão presentes** e existe
   `ai_validated.json` gerado por `validate_node.py` após uma execução real bem‑sucedida (ou `ASSETFORGE_AI_ALLOW_UNVALIDATED=1`, por conta do operador).
2. **Pré‑checagem de VRAM**: antes de iniciar, se a VRAM livre real (medida pelo ComfyUI) < 90 % da reserva, o job volta à fila — não disputa a GPU.
3. VRAM real (`/system_stats`) aparece na telemetria/painel; pico por etapa vai no manifesto. Cancelar interrompe o ComfyUI, não só o processo.
4. ComfyUI escuta **só em 127.0.0.1**; o worker é o único cliente. Mesmas janelas de ociosidade/“ceder a processos” dos workers CPU.
5. **Não instale nos nodes 200/201/210 enquanto o worker de visão do Stream Clipper usar a mesma Arc** sem combinar janela/limite — a VRAM é de 8 GB. O node **206** (A750 sem worker de visão, segundo seu guia) é o candidato natural para a primeira validação.

### Perfis de qualidade (valores INICIAIS, a calibrar no hardware)
| Perfil | passos | textura | remesh | bake normal/AO | alvo de triângulos |
|---|---|---|---|---|---|
| prototype | 8 | 1024 | 384 | 1024/512 | 80 % do orçamento |
| stylized_standard | 12 | 2048 | 512 | 2048/1024 | 90 % |
| stylized_detailed | 16 | 4096 | 640 | 2048/1024 | 90 % (orçamento ×2) |
| high_quality | 20 | 4096 | 768 | 4096/2048 | 95 % (orçamento ×4) |
Parte dos defaults do preset da Intel (12 passos, 4096, 7000 faces). “Premium Stylized”: o prompt de texto recebe um sufixo de direção de arte; e a validação alerta (`not_prototype_like`) se o LOD0 ficar < 20 % do mínimo da categoria. **Qualidade visual real só se avalia olhando resultados no hardware** (`benchmark_ai.py` gera a folha *referência | IA | procedural*).

## 4. Licenças para uso comercial no Brasil (verificadas nas fontes; não é parecer jurídico)
| Peso | Licença | Comercial no Brasil |
|---|---|---|
| Pixal3D (`TencentARC/Pixal3D`, repack Comfy‑Org) | MIT | ✅ sem restrição territorial |
| TRELLIS.2 (`microsoft/TRELLIS.2-4B`) | MIT | ✅ |
| MoGe‑2, BiRefNet | MIT | ✅ |
| Z‑Image‑Turbo (`Tongyi-MAI`), Qwen3‑4B (text encoder) | Apache‑2.0 | ✅ |
| VAE `ae.safetensors` (Z‑Image) | card do repack: Apache‑2.0; é o VAE da família FLUX | ⚠ **confirmar origem** (o mesmo arquivo circula também no FLUX.1‑dev, não comercial) |
| **DINOv3 `dino_v3_L_naf_fp32`** (encoder do Pixal3D) | **DINOv3 License (Meta)** — o card Comfy‑Org diz MIT, mas deriva do DINOv3. Licença lida: royalty‑free, mundial, uso/derivados permitidos; repassar a licença; leis de controle de exportação; **proíbe ITAR/uso militar** | ⚠ **provavelmente ok (Brasil não é excluído), exige confirmação humana**; a variante “NAF” não teve licença própria verificada |
| Hunyuan3D‑2.1 | Tencent Community (exclui UE/UK/Coreia do Sul) | **não usado** nesta integração |
Os pesos **não são redistribuídos** pelo AssetForge: cada node baixa direto do Hugging Face por ação explícita (`--accept-licenses`), com a tabela acima exibida antes. Os assets gerados registram modelos e licenças no manifesto.
Direitos sobre a **saída** de IA e eventuais restrições de uso (ex.: OpenRAIL) devem ser revistos por quem responde pelo jogo.

## 5. Procedimento nos nodes
> **Caminho recomendado agora: Docker em uma máquina — [DEPLOYMENT.md](DEPLOYMENT.md) §2–4** (`install_single_node.sh` + `docker_tasks.sh`). O procedimento sem Docker abaixo continua válido para um node isolado.

### 5b. Sem Docker (você/Hank executa; eu não instalei nada)
Em cada node candidato (comece pelo 206), **como usuário comum**:
```bash
git clone https://github.com/gamerplay20p5-dotcom/assetforge.git && cd assetforge
python3 scripts/diagnose_hardware.py                       # confere GPU/render node/RAM
./scripts/intel_ai/install_node.sh                         # imprime comandos de ROOT se faltar Level Zero/driver; senão instala em ~/assetforge-ai
python3 scripts/intel_ai/download_models.py --models-dir ~/assetforge-ai/ComfyUI/models --list     # veja tamanho/licenças
python3 scripts/intel_ai/download_models.py --models-dir ~/assetforge-ai/ComfyUI/models --accept-licenses
COMFY_HOME=~/assetforge-ai/ComfyUI ./scripts/intel_ai/run_comfyui.sh &    # headless, 127.0.0.1:8188
python3 scripts/intel_ai/validate_node.py --state-dir ~/assetforge-worker-state    # RODA texto→imagem→3D de verdade
python3 scripts/intel_ai/benchmark_ai.py --out bench_ai --from-procedural 4 --profiles prototype stylized_standard
```
Cole o JSON do `validate_node.py` e o `results.md`/`comparison_*.png` do benchmark de volta aqui para eu registrar a compatibilidade em
`HARDWARE_COMPATIBILITY.md`. Depois: no `.env.worker` do node defina `ASSETFORGE_COMFYUI_URL=http://127.0.0.1:8188`,
`ASSETFORGE_AI_MODELS_DIR=…/ComfyUI/models` e (worker em Docker) dê acesso à rede do host ou rode o worker nativamente.
Se a **A750 de 8 GB falhar por memória**, ajustes a testar, em ordem: `COMFY_RESERVE_VRAM` menor/maior, perfil `prototype`, resolução de textura 1024, `--novram` do ComfyUI
(`COMFY_EXTRA_ARGS`; flags a confirmar na versão fixada), e por fim aceitar que este workflow não cabe e usar só o caminho procedural nessa placa.

## 6. O que foi e o que NÃO foi testado
**Testado (109 testes pytest, incluindo Blender real):** vendor dos presets e grafo esperado; injeção de parâmetros por `nodeTitle`;
normalização de caminhos; remoção do SafetyChecker mantendo o grafo íntegro; cliente ComfyUI (upload, fila, polling, erro de execução, cancelamento →
`/interrupt`) contra um **ComfyUI falso** com sockets reais; monitor de VRAM; download com SHA‑256, retomada e rejeição de hash errado; licenças de todos os modelos;
contrato dos jobs de IA; pipeline completo com Blender real sobre um GLB texturizado (LODs, escala, orçamento, FBX/BLEND, manifesto); upload/validação de referência;
worker real + API real: gate fechado → validado → job executado, VRAM real na telemetria, job só em worker com features/VRAM.
**NÃO testado:** qualquer execução de modelo de IA; ComfyUI/torch XPU; Linux; Arc A750 (ou qualquer Arc); VRAM/tempo reais; qualidade visual do resultado dos modelos;
`install_node.sh` e `run_comfyui.sh` (escritos a partir do código da Intel, nunca executados); URLs/HF em download real (testado só com transporte simulado);
nomes exatos das chaves de saída do `SaveGLB` (o cliente varre qualquer lista com `filename`).
**Compatibilidade com a Arc A750: NÃO declarada.**
