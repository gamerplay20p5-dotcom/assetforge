# Especificação de assets (contrato 1.0.0)

Fonte da verdade: `packages/asset-contract/assetforge_contract/models.py` (Pydantic). Todo asset tem id persistente
(`ast_<hex>`), versões imutáveis (`v1`, `v2`, …) e um pacote `manifest.json`.

## Convenções
* Unidades: **metros (1 unidade = 1 m)**. glTF: Y‑up, mão direita, frente do asset = **+Z**. Pivô: **centro da base**
  (`pivot: bottom_center`, `min y = 0`, centro XZ = 0), verificado na validação.
* FBX (Blender): eixos `-Z forward / +Y up`, `bake_space_transform`, `FBX_SCALE_UNITS`, texturas embutidas — configurado para
  importar na Unity em escala 1:1 (**validação dentro da Unity ainda não feita**; Unity Package é Milestone 5).
* Cores no manifesto: sRGB hex. No glTF/Blender: fatores lineares.
* Assets visuais não contêm regras econômicas/políticas/de jogo. Trocar um modelo por versão melhor mantém `asset_id`,
  dimensões funcionais e pontos de conexão (nova versão do mesmo asset).

## Arquivos de uma versão
| Arquivo | Papel | Quando |
|---|---|---|
| `model.glb` | intercâmbio (texturas embutidas, REPEAT + mipmaps) | sempre |
| `model.blend` | editável | worker com Blender |
| `model.fbx` | integração Unity | worker com Blender |
| `textures/tex_<tipo>_<res>.png` | texturas tileáveis | sempre |
| `thumbnail.png` | miniatura 512² | sempre |
| `validation.json` | relatório (checks, métricas) | sempre |
| `manifest.json` | metadados | sempre |
| `<asset>_v<n>.zip` | pacote completo | sempre |

## manifest.json (campos)
`contract_version, asset_id, name, category, version, art_profile, seed, generator_id, generator_version, ai_model (null),
quality_profile, dimensions_m, footprint_m, bounding_box, pivot, connection_points[{name,position,direction}],
materials[{name,base_color,texture,roughness,metallic,tile_meters}], textures[], lods[{level,triangles,file}],
colliders[{type,center,size}], skeleton (null), animations [], construction_states [], triangle_count, triangle_budget,
license, provenance{generator,engine,job_id,inputs}, engine, generation_params, files[{name,role,format,size,sha256}], created_at`.
* `files` lista os arquivos com SHA‑256 exceto o próprio `manifest.json` e o `.zip` (calculados depois); o servidor guarda
  também os checksums de todos os arquivos no banco.
* **Hoje**: `lods` tem só LOD0; `colliders` = caixa da bounding box; `skeleton/animations/construction_states` vazios (M3–M4).
* Pontos de conexão atuais: `entrance` (porta principal), `roof_access`, `platform_edge` (estações).

## Orçamento de triângulos (LOD0, Stylized Standard — configurável)
casa 1.000–4.000 · prédio 3.000–10.000 · arranha‑céu 5.000–15.000 · veículo 2.000–6.000 · personagem 2.000–5.000 ·
árvore 300–1.500 · prop 50–1.000. Perfis multiplicam: prototype ×0,4 · standard ×1 · detailed ×2 · high ×4 · custom (informa o limite).
Ultrapassar o máximo gera **aviso** `triangle_budget` na validação (não bloqueia). Medido: apartamentos com detalhe 2 e muitos
andares chegam a ~11,7 k (aviso); veja TESTING.md.

## Validação (todo asset)
Malha: geometria presente, vértices finitos, triângulos degenerados, normais × winding, UV presentes/faixa, escala sã, pivô,
orçamento, nº de materiais. Arquivo: contêiner GLB (magic/versão/tamanho/chunks), referências glTF, **re‑leitura com trimesh**
(triângulos e dimensões idênticos ao gerado), pivô, existência dos arquivos pedidos. Otimização aplicada: remoção de triângulos
degenerados, *weld* de vértices idênticos, normais coerentes, normalização de pivô — **sem decimar** (nada de redução de
polígonos destrutiva nesta fase).

## Gerador `procedural.building@0.1.0`
Categorias: house, apartment, commercial, skyscraper, industrial, hospital, school, university, police, fire_station,
transport_station, warehouse, government. Parâmetros: `style, seed, width, depth, floors, floor_height, roof, bay_width,
balconies, garage, palette, wear, detail (0–2), texture_resolution`. `None` = automático por categoria+seed.
Mesmos `params` + mesma versão do gerador ⇒ mesma malha (testado).
