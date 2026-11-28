# Retopologia e LODs do CITY+++

O corpus reúne os 40 masters arquivados, com 16 construções, 12 veículos e 12 NPCs. A 206 executou a bateria em Docker com o volume de masters em modo somente leitura. Cada ensaio escreveu GLBs e relatórios em outra pasta e verificou o SHA-256 da origem antes e depois. A bateria reutilizou as malhas e texturas geradas nos experimentos.

## Métodos

- **gltfpack conservador** simplifica a malha com os atributos existentes. O controle mantém as texturas do arquivo de origem e usa a tolerância padrão do simplificador. [meshoptimizer](https://github.com/zeux/meshoptimizer)
- **Instant Meshes** reconstrói a topologia por um campo de orientação. Usamos uma malha intermediária soldada, alinhamento em bordas abertas e ângulos de vinco distintos para fachadas, carrocerias e NPCs. O alvo de faces do solver gera uma contagem final variável após triangulação. [Projeto Instant Field-Aligned Meshes](https://igl.ethz.ch/projects/instant-meshes/)
- **QuadriFlow** tenta gerar quadriláteros após um remesh por voxel. O tamanho da célula foi de 1,2% da maior dimensão para construções, 1,4% para veículos e 1,8% para NPCs. [Implementação do QuadriFlow](https://github.com/hjwdzh/QuadriFlow)
- **LOD permissivo** parte do LOD0 do Instant Meshes com as texturas já projetadas. O gltfpack pode simplificar costuras de atributos com `-sp` e tolerância de 2,5%. [Referência do simplificador](https://github.com/zeux/meshoptimizer#simplification)
- **Híbrido** solda costuras da malha intermediária e dissolve planos com tolerância de 1° em construções e 0,25° em veículos. Em seguida ajusta a geometria ao alvo e projeta os materiais diretamente do master em cada LOD. Usamos mapas a 512, 256 e 128 px. O método preserva o master e permite comparar se uma topologia mínima é preferível ao retopo por campo num asset específico.
- **LOD voxel** conserva o LOD0 híbrido e reconstrói uma superfície por voxels para os dois LODs distantes. O tamanho da célula aumenta com a distância. As duas malhas recebem baking próprio a partir do master.

Os testes com baking geraram UVs novas e projetaram cor, normal tangente, rugosidade e metalicidade do master. O GLB usa um mapa combinado de rugosidade e metalicidade. A resolução dos mapas faz parte deste ensaio e pode ser alterada.

## Orçamentos de teste e medidas

| Categoria | LOD0 | LOD1 | LOD2 |
| --- | ---: | ---: | ---: |
| Construção | 8.000 | 2.400 | 600 |
| Veículo | 6.000 | 1.800 | 450 |
| NPC | 4.000 | 1.200 | 300 |

São alvos experimentais. O argumento `--budget-file` recebe um JSON com as chaves `building`, `vehicle` e `npc` e três valores decrescentes em cada categoria. O CSV registra o alvo e a triangulação efetiva de cada GLB. O tempo de processamento cobre importação, geometria, baking e exportação conforme o método. O tempo total inclui os renders.

As três vistas usam câmera e luz fixas em relação ao master. A IoU mede a interseção sobre a união das máscaras de silhueta. O CSV registra a menor IoU das três vistas e a diferença média de RGB nas regiões que se sobrepõem. Essas medidas ajudam a localizar perdas de forma ou material. Fachadas, rodas, membros finos, recortes e manchas de projeção exigem inspeção nas folhas. A aprovação artística e as transições de LOD serão validadas separadamente, com os orçamentos definitivos definidos após os benchmarks na Unity.

## Resultados de LOD0

Os masters tinham mediana de 935.225 triângulos e 36,87 MB. Os valores abaixo são medianas dos casos concluídos em cada método. A silhueta usa a pior das três vistas de cada asset.

| Método | GLBs concluídos | Triângulos | Tamanho | Processamento | IoU da silhueta | Alvo alcançado |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| gltfpack conservador | 40/40 | 87.142 | 7,59 MB | 3,46 s | 99,7% | 0 |
| Instant Meshes com baking | 37/40 | 2.017 | 1,07 MB | 15,32 s | 71,0% | 37 |
| QuadriFlow com baking | 5/40 | 3.606 | 1,12 MB | 12,83 s | 94,3% | 5 |
| Híbrido | 40/40 | 16.052 | 2,29 MB | 43,11 s | 94,7% | 8 |

O gltfpack preservou o contorno com alta consistência e atingiu um piso de geometria bem acima dos alvos. O Instant Meshes abriu buracos em fachadas, no baú do caminhão e nas pernas de NPCs. Dois casos produziram OBJ vazio e um expirou ao preencher buracos. Os cinco resultados QuadriFlow vieram de NPCs. Os outros 35 casos falharam na entrada exigida pelo solver ou na geração da nova superfície.

O residencial TRELLIS.2 saiu de **295.794 para 7.997 triângulos** no híbrido, com **99,85% de IoU** na pior vista. O erro RGB subiu de 2,71 no controle para 9,02 no híbrido. As folhas permitem examinar a diferença de cor e detalhe da fachada. O caminhão Pixal3D Single-View caiu de 944.282 para 26.852 e preservou 94,84% da silhueta. O híbrido ainda excedeu o alvo nesse veículo e ficou acima do alvo nos 12 NPCs.

## LODs distantes

O colapso sobre a malha soldada manteve a contagem mediana de 16.052 triângulos nos LODs híbridos 1 e 2. O modo permissivo reduziu os LODs do Instant Meshes e conservou os buracos já presentes no LOD0. O remesh voxelizado com baking individual gerou os 40 pares de LOD distantes.

| Categoria | LOD1 mediano | IoU LOD1 | LOD2 mediano | IoU LOD2 |
| --- | ---: | ---: | ---: | ---: |
| Construção | 2.400 | 97,7% | 600 | 96,2% |
| Veículo | 2.087 | 95,1% | 450 | 97,4% |
| NPC | 1.200 | 96,9% | 300 | 92,0% |

O LOD1 ficou dentro do alvo em 30 de 40 casos, com mediana de 456 KB. No LOD2 foram 33 de 40, com 116 KB. O par de LODs levou 28,12 s de processamento mediano. A inspeção dos GLBs confirmou texturas de cor, normal tangente e rugosidade/metalicidade. O residencial teve **7.997 / 2.400 / 600 triângulos**, com IoU de 99,85%, 99,58% e 98,96%. O caminhão ainda excedeu os dois alvos distantes com 2.243 e 698 triângulos. O operário chegou a 1.200 e 300, com IoU de 97,16% e 93,07%.

Nas folhas, o residencial conserva o volume, o recuo do telhado e as linhas principais da fachada. Os LODs do caminhão apresentam manchas e listras no baú e perda de definição no encontro com a cabine. O operário conserva as massas do capacete e do colete nos LODs voxelizados, com alteração no contorno dos braços e pernas. A silhueta isoladamente deixaria passar os defeitos de material do caminhão.

Foram renderizados três impostores de oito azimutes com tiles transparentes de 256 px. Os atlas do residencial, caminhão e operário levaram 10, 15 e 8 s e ficaram entre 351 e 464 KB. Cada JSON registra o centro, o enquadramento e a posição dos frames. O atlas usa uma elevação fixa de 12° para esta bateria. Transições, paralaxe e aparência com a câmera em outros ângulos ainda precisam de avaliação no jogo.

O melhor ponto de partida para construções é o híbrido próximo e o voxel com bake à distância. Veículos e NPCs pedem seleção por asset. Preserve o gltfpack como controle de detalhe e compare os candidatos com o master antes da aprovação artística.

## Evidências

Os GLBs experimentais e os logs estão em `~/assetforge-phase3/city-retopo-bench-v5` na 206. A cópia local em `reports_out/engines/city-retopology-2026-11-28` inclui o CSV, os JSONs, as 40 folhas e os três atlas. O SHA-256 do pacote de evidências é `3c0263de8223ec264f4bf12104f2b6b1fce504ce5ddafade2b7fb29e9fb3e08c`.

## Reprodução

Construa `deployment/Dockerfile.city-retopology` sobre a imagem de revisão disponível. Monte o checkout em `/code`, o diretório de resultados arquivados em `/masters` como somente leitura e uma pasta nova em `/out` com permissão de escrita. A imagem de revisão fornece `BLENDER_BIN` e gltfpack.

```sh
python /code/scripts/engines/benchmark_retopology.py /masters /out \
  --methods baseline instant quadri hybrid --jobs 6 --threads 2
python /code/scripts/engines/benchmark_retopology.py /masters /out \
  --methods lod-permissive lod-voxel --jobs 6 --threads 2
```

Cada resultado concluído tem métricas próprias. Use outra pasta de saída para comparar alterações nos parâmetros. Os recortes ortográficos com transparência para objetos distantes são gerados à parte por `scripts/engines/impostor_atlas.py`.
