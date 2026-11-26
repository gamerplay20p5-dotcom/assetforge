# Geração image-to-3D só com CPU e RAM (Stable Fast 3D e TripoSR)

**Decisão (2026-11-26):** não vamos alterar BIOS/firmware/drivers/kernel nem reiniciar os servidores. A Arc A750 da 206 não inicializa o
runtime de compute sem *Resizable BAR* (ver HARDWARE_COMPATIBILITY.md), então o **PyTorch XPU / Intel AI Playground foi desabilitado como método
principal**. O código Intel continua no repositório como opção futura, **desligado por padrão** (`ASSETFORGE_ENABLE_INTEL_AI=1` para ligar).
A geração por IA agora usa **PyTorch CPU** em containers independentes. Não há text-to-image: as imagens de referência vêm de fora (ChatGPT) e
são enviadas pelo painel. Os geradores procedurais continuam sendo o método principal; a IA é complementar.

## Estado (medido na 206, não estimado)
| Provider | Imagem Docker | Execução real | Estado |
|---|---|---|---|
| **TripoSR** (CPU) | ✅ construída | ✅ ~12 execuções reais (warm-up, jobs pela fila, benchmark) | **VALIDADO para 1 asset real** (ver resultados) |
| **Stable Fast 3D** (CPU, `SF3D_USE_CPU=1`) | ✅ construída (os módulos C++ `texture_baker`/`uv_unwrapper` compilam em CPU) | ❌ **nunca executado** | **NÃO validado**: os pesos são *gated* — precisa de um token do Hugging Face de uma conta que aceitou a licença (ver "Pendência") |

## Licenças (verificadas nas fontes em 2026-11-26; não é parecer jurídico)
| Item | Licença | Uso comercial no Brasil |
|---|---|---|
| **TripoSR** código + pesos (`stabilityai/TripoSR`) | MIT (© Tripo AI & Stability AI) | ✅ sem restrição territorial; manter o aviso de copyright |
| **Stable Fast 3D** código + pesos | **Stability AI Community License** | ⚠ **condicionada**: uso comercial exige **registro na Stability** (stability.ai/community-license) e vale enquanto a organização (com afiliadas) tiver **< US$ 1 milhão/ano de receita**; acima disso, licença Enterprise. Exige "Powered by Stability AI" visível + arquivo Notice e cumprimento da AUP; proíbe usar saídas para treinar modelos fundacionais; a saída (o 3D) é de quem gera "na medida da lei". Sem exclusão territorial ao Brasil |
| `texture_baker`, `uv_unwrapper` (dentro do repo SF3D) | sem arquivo próprio → cobertos pela licença do repositório | idem SF3D |
| DINOv2-large (baixado pelo SF3D) | Apache-2.0 | ✅ |
| CLIP ViT-H-14 laion (baixado pelo SF3D) | MIT | ✅ |
| rembg, trimesh, einops, open_clip, jaxtyping, xatlas, moderngl, gpytoolbox, onnxruntime | MIT | ✅ |
| torch (CPU), omegaconf, imageio, psutil, pynanoinstantmeshes | BSD | ✅ |
| transformers, pesos u2net (rembg), DINOv2 | Apache-2.0 | ✅ |
| `torchmcubes` | **MPL-2.0** (copyleft por arquivo; usado sem modificação) | ✅ |
O manifesto de cada asset grava a licença do provider usado. **Recomendação:** o TripoSR é o único liberado sem condição para produção; o SF3D só entra
em produção depois do registro na Stability e da decisão do Hank sobre o limite de receita.

## Arquitetura
```
painel ── upload da referência (validada/re-codificada) ──▶ API ──▶ fila (jobs ai.image_to_3d, provider=sf3d|triposr)
worker-ai (kind cpu, 1 job por vez) ──http interno──▶ container triposr | container sf3d  (PyTorch CPU; CLI oficial em subprocesso)
        └─▶ Blender: normaliza escala/pivô → REDUÇÃO por bake → LODs → GLB/FBX/BLEND → validação → manifesto → asset
```
* **Containers independentes** (`deployment/Dockerfile.triposr|sf3d`): cada um roda um servidor HTTP mínimo (stdlib) que executa o **CLI oficial** do projeto
  em subprocesso: cancelável, com timeout, parâmetros validados por whitelist, medição de RAM/CPU do processo. Porta 8080 **só na rede interna**.
* **Cache persistente** de pesos no volume `cpu3d-models` (`HF_HOME`); `CPU3D_OFFLINE=1` depois do download.
* **Integração com as filas:** o worker só anuncia `provider.<nome>` quando o container responde **e** os pesos estão em cache. O scheduler reserva
  `CPU3D_JOB_RAM_MB` (16 GB) e 12 núcleos por job; sem VRAM. Cancelar um job cancela o processamento dentro do provider.
* **Configuração:** `.env` → `CPU3D_THREADS`, `CPU3D_CONCURRENCY`, `CPU3D_DOCKER_CPUS`, `CPU3D_DOCKER_MEM`, `AI_WORKER_*`, `CPU3D_JOB_TIMEOUT`; limites do worker editáveis no painel.
* **Painel:** Asset Generator → "Imagem → 3D (IA, CPU)": escolhe o modelo, envia a imagem, perfil, resolução de textura, malha (TripoSR) ou remalhamento (SF3D), máx. de triângulos e LODs.
  Workers → consumo (RAM do container, jobs ativos) por provider.

## Pós-processamento (o que foi preciso corrigir olhando o resultado real)
1. **Orientação:** o TripoSR entrega +Z para cima; aplicamos as mesmas rotações do app dele (`to_gradio_3d_orientation`) e, medindo o GLB (encosto no lado +Z),
   mais 180° em Y para a **frente ficar em +Z**. (Medido num único objeto; confirmar com as suas imagens.)
2. **Redução de polígonos:** a decimação direta **rasgava** a malha (as ilhas de UV do xatlas dividem vértices) e não chegava ao orçamento. Agora: **solda de vértices
   + decimação sem UV + novo UV (smart project) + bake de cor e normal (tangente) do modelo de alta resolução** (Cycles CPU); rugosidade também é baked quando
   a fonte tem mapa (SF3D). O metálico do GLB sem PBR vem como 1 (padrão do glTF) e **fazia o bake sair preto**: é neutralizado só durante o bake (teste de regressão).
   LOD0 respeita `max_triangles` (ou o orçamento da categoria); LODs saem na razão pedida; pivô e dimensões são recalculados do LOD0 final.
3. **Textura do TripoSR:** o bake usa moderngl, que precisa de display: roda sob `xvfb` (GL por software). Sem isso o serviço cai para cor por vértice.
**Limitações conhecidas:** metálico não é preservado (vai a zero); o bake é de cor+normal(+rugosidade) — não há AO; o estilo "Premium Stylized" vem da imagem de referência (nada
estiliza a malha); a IA inventa o lado não visto da imagem.

## Resultados reais (206: Threadripper PRO 3955WX 32 threads, 200 GB RAM; TripoSR, 12 threads; objeto: cadeira de exemplo do repositório do TripoSR)
| Perfil | tempo total | provider | RAM pico do provider | CPU pico | triângulos bruto → LODs |
|---|---|---|---|---|---|
| prototype | 37,3 s | 32,1 s | 3,5 GB | 1.202 % (12 núcleos) | 47.316 → 400/200/100/50 |
| stylized_standard | 67,6 s | 57,6 s | 3,6 GB | 1.202 % | 84.160 → 1000/500/250/100 |
| stylized_detailed | 125,7 s | 109,2 s | 4,4 GB | 1.203 % | 132.778 → 2000/1000/500/200 |
* Job real pela API/fila/worker/Blender (stylized_standard): **104 s**, asset validado, GLB+FBX+BLEND+3 LODs; RAM do host no pico 12,6–13,3 GB (inclui os outros serviços).
* **Temperatura:** com 12 threads a CPU chegou a **95 °C no sensor `k10temp Tctl`** (dies `Tccd` ≈ 80 °C; GPU Intel 48 °C; NVMe/NIC menores). É um servidor compartilhado: considere
  `CPU3D_THREADS=8`/`CPU3D_DOCKER_CPUS=8` ou janelas de horário — **o efeito disso ainda não foi medido**.
* Qualidade visual: avaliada olhando `comparison_<perfil>.png` (referência | bruto | otimizado) em **uma** imagem. O otimizado preserva silhueta, cor e o capitonê do encosto; no perfil
  `prototype` (400 tri) as pernas finas ficam um pouco facetadas. **Isso não é uma avaliação geral de qualidade**: faltam as suas imagens de referência (estilo Premium Stylized).
* Estabilidade: nenhuma falha de execução do provider (sem OOM/travamento) nas ~12 execuções; as falhas que ocorreram foram bugs nossos de build/pós-processamento, já corrigidos.

## Procedimento na 206 (já executado até o item 4)
```bash
./scripts/install_single_node.sh standalone --no-start      # .env (perfis: standalone,cpu3d)
./scripts/cpu3d/tasks.sh build                              # imagens dos providers
./scripts/cpu3d/tasks.sh setup triposr                      # baixa pesos (MIT) + inferência real de aquecimento
./scripts/cpu3d/tasks.sh up                                 # providers + worker-ai
./scripts/cpu3d/tasks.sh benchmark ./referencias prototype stylized_standard   # SUAS imagens → tempo/RAM/CPU + comparação visual
./scripts/cpu3d/tasks.sh export                             # resultados em ./reports_out/bench (results.md, comparison_*.png, modelos)
```
### Pendência — Stable Fast 3D (precisa de você)
1. Em https://huggingface.co/stabilityai/stable-fast-3d aceite a licença **com a sua conta** (e avalie o registro comercial na Stability).
2. Crie um token de leitura (huggingface.co/settings/tokens).
3. Na 206: `HF_TOKEN=hf_xxx ./scripts/cpu3d/tasks.sh setup sf3d` — o token é usado **só** nessa tarefa (não fica nos serviços em execução); depois `tasks.sh up` e o benchmark compara os dois providers.
Até lá o painel/worker mostram "sf3d: pesos não baixados" e **nenhum resultado do SF3D é afirmado**.
