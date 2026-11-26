# Imagem → casa: modelo de visão local + kit procedural

**Decisão (2026-11-26):** o TripoSR não serve para casas (malhas deformadas). O fluxo padrão de "Imagem → casa" é:

1. **Qwen2.5-VL 7B** (local, só CPU, container `vlm`) lê a imagem e devolve uma **descrição estruturada** da casa (JSON validado: andares, tipo de telhado, materiais, cores, porta, varanda, garagem…).
2. Você **revisa e corrige** os campos no painel (o modelo erra janelas, volumes e tipo de telhado com frequência).
3. O **kit procedural** (Blender) monta a casa a partir de uma casa-base parecida e dos campos corrigidos, com GLB/FBX/BLEND, LODs e **os 6 estados de obra** da mesma geometria.
4. Opção de **acabamento** (Padrão / Polido): textura 1024 ou 2048 px, desgaste da pintura, semente de variação.

O TripoSR continua no painel como provider **experimental**.

## Medido na 206 (Threadripper PRO 3955WX, 32 threads; limite combinado de 70% de CPU e RAM)
Seis casas da pasta de referência do usuário; verdade escrita por uma pessoa olhando cada imagem; acerto por campo (cores contam por família).

| Modelo | Licença | Tempo/imagem | RAM pico | CPU média | Campos corretos |
|---|---|---|---|---|---|
| Qwen2.5-VL 3B | **Qwen Research** (não comercial) | 108 s | 15,3 GB | ~950% | 68/91 (75%) |
| Qwen2.5-VL 7B | **Apache-2.0** | 210 s | 32,3 GB | ~650% | 74/91 (81%) |

O 7B acerta andares, posição/cor da porta, cor da parede, garagem, chaminé e bay (6/6). Erra: janelas por andar (3/6), volumes (3/6), varanda (4/6),
cor do telhado (4/6), tipo de telhado (5/6) e **inventa parede inferior** em 4/6 casas (por isso só vale tijolo sob outro material). Com essa regra,
5 das 6 casas ficaram reconhecíveis ao montar no kit; o sobrado azul saiu errado. **Não é um fluxo 100% automático: é "ler, revisar, gerar".**
Só o 7B (Apache-2.0) é liberado para uso comercial.

## Ligar na máquina
```bash
./scripts/vlm/tasks.sh download      # pesos do 7B (~16 GB) para o volume vlm-models (precisa de internet)
./scripts/vlm/tasks.sh up            # liga o container vlm (perfil vision) e define ASSETFORGE_VLM_URL no .env
```
O serviço carrega o modelo no primeiro pedido e o descarrega da RAM após `VLM_IDLE_UNLOAD_SECONDS` (900) sem uso. Limites: `VLM_DOCKER_CPUS=22`, `VLM_DOCKER_MEM=64g`.
Porta 8080 só na rede interna. Benchmark: `./scripts/vlm/tasks.sh benchmark ./pasta` (+ `scripts/vlm/report_vlm.py`).

## API
* `GET /api/v1/vision/status` — serviço ligado? pesos no cache? modelo carregado?
* `POST /api/v1/vision/describe {reference_id}` → `{id}` (202); `GET /api/v1/vision/describe/{id}` → status e, quando pronto, `description` validada + casa-base.
* `POST /api/v1/vision/preview {description}` — valida a descrição editada e diz sobre qual casa do kit será montada.
* Job: `params.house_description` (validada na criação) + `construction_stage` 1–6 + `texture_resolution`/`wear`/`seed`.

## Segurança
O modelo só preenche campos de um esquema fechado; nada do que ele escreve é executado. A API valida a resposta (valores fora das listas são rejeitados),
só repassa imagens já validadas/re-codificadas e o serviço aceita apenas imagens (PNG/JPEG/WEBP até 12 MB) na rede interna.

## Análise de qualquer imagem (categoria) — medido em 2026-11-26
O prompt de análise pergunta primeiro a **categoria** (`house`, `vehicle`, `character`, `tree`, `prop`, `other`), o assunto e se é um objeto isolado; só para casas devolve a descrição detalhada.
`assetforge_vision/kits.py` decide a rota: casa → kit; objeto isolado → TripoSR (**experimental**, aviso de que costuma deformar); o resto → nenhuma rota, dizendo o motivo.
**Só existe kit de casas.** Veículos, personagens e árvores têm categoria detectada, mas ainda **não têm gerador** (marcados como "planejado" em `KITS`).

Medido com o 7B (fp32, 640 px): as 6 casas foram classificadas como `house` (6/6) e 82 de 97 campos da casa estavam corretos (85%); uma cadeira foi lida como `prop` (1/1).
Falha medida: um terreno vazio foi lido como "baseball field, objeto isolado". O ajuste do prompt não corrigiu; por isso `looks_flat()` bloqueia a rota do TripoSR quando o assunto soa
como terreno/chão/mapa. **Só 2 imagens fora de casas foram testadas**: a classificação de carros e pessoas ainda NÃO foi medida (faltam imagens de exemplo).

### Velocidade (206, 20 threads) — o tempo está na geração do texto, não na imagem
| Variante | Geração | RAM | Resultado |
|---|---|---|---|
| fp32 (padrão) | 0,81 palavra/s (prefill da imagem 25–30 s) | 32 GB | correto, ~250 s por análise |
| imagem 448 px em vez de 640 | sem ganho (249 s) | 32 GB | o tamanho da imagem não é o gargalo |
| bf16 | travou (>58 min, CPU sem suporte nativo) | – | inviável |
| int8 em tudo | 4,2 palavras/s | 39 GB | o modelo deixou de seguir o prompt |
| int8 só nas camadas de texto (`VLM_QUANT=int8lm`) | 2,7 palavras/s, metade da RAM | 16 GB | **6 de 8 respostas inválidas**: não usar como padrão |
Conclusão: fica em fp32. Para ganhar velocidade de verdade a opção é GPU (o Spark 252 está reservado para depois, sem uso por enquanto).
