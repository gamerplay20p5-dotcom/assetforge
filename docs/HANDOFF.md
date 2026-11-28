# HANDOFF — AssetForge (estado em 2026-11-28)

Escrito para: outro agente de código (Codex) que vai continuar o trabalho sem o histórico da conversa. A documentação usa PT-BR e o dashboard oferece português e inglês.
Commits em Conventional Commits; PRs em português **e** inglês. Atribuição nos commits: `Co-Authored-By: <modelo> <noreply@anthropic.com>` se feitos por Claude.

## Preparação integrada de assets · 28/11/2026

A tela **Preparação de assets** aceita seleção automática ou manual de híbrido planar, voxel com baking, Instant Meshes, QuadriFlow e gltfpack conservador. Os alvos de Low, Mid e High Poly são editáveis e provisórios. O perfil Master integral continua disponível na exportação clássica. O worker anuncia o pipeline quando encontra Blender e gltfpack e anuncia Instant Meshes separadamente. Os leases continuam entregando o GLB da versão original. O SHA-256 é conferido ao final da preparação.

O automático usa categoria, proporção de área alinhada aos eixos e fração de bordas abertas na malha intermediária soldada. Em quatro câmeras fixas, a checagem mede sobreposição de silhueta, perda interna, diferenças RGB sob a mesma luz, manchas novas, bordas de contraste e distância de superfície nos dois sentidos. As regiões indicativas de portas, janelas, rodas e membros exigem revisão visual. Se o método escolhido reprovar, o pipeline pode tentar projeção fixa, simplificação com UV e materiais existentes ou manter a geometria do nível anterior. `quality.json` registra métricas, limiares, tentativas, contagem efetiva, tamanho e divergência do alvo. Em **Biblioteca → Comparar**, o usuário pode abrir o master de origem, alternar os níveis em 3D, ver as vistas alinhadas das tentativas e inspecionar o atlas do impostor.

No caminhão `veh_industrial_001_sv_1024_4090`, o teste A/B manteve a mesma malha híbrida de 26.981 triângulos e as mesmas quatro câmeras. A pior diferença RGB foi de 10,62% com o cage adaptativo e 7,47% com distância fixa. A maior incidência de manchas escuras caiu de 1,74% para 0,68%. As sondas sem interseção passaram de 6,74% para 0,92%. A silhueta mínima foi de 97,29% nos dois. A malha soldada mostrou uma ilha relevante e o ensaio manteve a carroceria conectada. A projeção fixa ainda deixou marcas visíveis no teto e na traseira. Os PNGs, a folha `comparativo-projecao.jpg` e o relatório estão em `reports_out/engines/preparation-integration/truck/`.

O ZIP reúne GLB, FBX, BLEND, texturas, metadados de importação, scripts de Editor/Runtime e atlas opcional. Instale os scripts uma vez no projeto URP e use **Assets → AssetForge → Build URP prefab** com o manifesto selecionado. O importador configura escala em metros, materiais URP, colisão simples e LODGroup, com textura de impostor alternada por direção de câmera. A execução no Editor Unity e os orçamentos finais de geometria continuam pendentes. [Instruções do pacote](../integrations/unity-export/README.md) · [Unity LODGroup.SetLODs](https://docs.unity3d.com/6000.0/Documentation/ScriptReference/LODGroup.SetLODs.html) · [Blender BakeSettings](https://docs.blender.org/api/current/bpy.types.BakeSettings.html)

Para repetir a bateria no worker Docker, monte o arquivo dos 40 masters como somente leitura e um diretório de resultados gravável pelo usuário do contêiner. Ajuste a concorrência do ensaio às cargas existentes.

```sh
docker build -f deployment/Dockerfile.worker -t assetforge-worker:preparation .
docker run --rm \
  --mount type=bind,source=/caminho/archive40-source/results,target=/masters,readonly \
  --mount type=bind,source=/caminho/resultados,target=/out \
  assetforge-worker:preparation python scripts/engines/benchmark_preparation.py /masters /out \
    --jobs 2 --threads 4 --metrics-only
```

A central 206 e a Spark apresentaram timeout no SSH durante a integração, por isso a versão do painel em produção ainda requer implantação. No GitHub, o [run Docker 46105438889](https://github.com/gamerplay20p5-dotcom/assetforge/actions/runs/46105438889) foi bloqueado antes do build por uma pendência de cobrança da conta. O workflow `preparation-container.yml` testa roteamento, publicação e pacote com um fixture sintético. Os dois testes passaram localmente com Blender 4.5.17 e gltfpack 1.3. O Playwright confirmou o formulário e o comparador com respostas controladas da API. A reimportação do FBX do caminhão no Blender confirmou as três malhas e as respectivas contagens. O BLEND reabriu com quatro texturas empacotadas. A RTX 4090 segue em manutenção.

Os SHA-256 dos 40 masters disponíveis localmente coincidiram com os usados no benchmark Docker anterior. A reaplicação dos limiares de silhueta e cor aos três renders arquivados aprovou nesses dois critérios 8/40 LOD0 híbridos, 28/40 LOD1 voxel e 25/40 LOD2 voxel. O gltfpack conservador passou nos dois critérios nos 40 masters, com contagens frequentemente acima dos alvos de geometria. Essa auditoria parcial cobre as três câmeras antigas. As medidas adicionais de desvio, baking e regiões vêm da nova execução.

## Otimização experimental CITY+++ · 28/11/2026

A bateria de retopologia usa os 40 masters de `~/assetforge-phase3/archive40-source/results` montados como somente leitura. O relatório [Retopologia e LODs do CITY+++](CITY_RETOPOLOGY_BENCHMARK.md) registra os métodos, os orçamentos provisórios, a qualidade visual e a reprodução em Docker. Os candidatos ficam separados dos masters e do catálogo. A decisão sobre o perfil padrão permanece vinculada à revisão artística e ao benchmark na Unity.

O residencial TRELLIS.2 gerou LODs de 7.997, 2.400 e 600 triângulos a partir de 295.794, com 98,96% de IoU na pior vista do LOD2. Os 40 pares de LOD voxel foram exportados com baking. O Instant Meshes apresentou buracos em vários candidatos e o QuadriFlow completou cinco NPCs. A 206 guarda GLBs e logs em `~/assetforge-phase3/city-retopo-bench-v5`. A cópia local das 40 folhas, métricas e atlas fica em `reports_out/engines/city-retopology-2026-11-28`.

## Reconstrução e Biblioteca CITY+++ · 27/11/2026

### Studio e execução por etapas

O Studio reúne imagem, múltiplas vistas e descrição. O visualizador ocupa a área central e a lista de assets abre sob demanda. O resumo exibe o motor e o worker recomendado. A geração registra a resolução solicitada e mostra a efetiva quando o motor a reporta. A preparação para Unity recebe Low, Mid e High Poly e grava outra versão. Receitas arquivadas preservam a configuração original de exportação.

Na fila central, o scheduler compara workers compatíveis usando telemetria, reservas, histórico por motor, categoria, resolução, tokens e textura. A opção manual fixa o worker. A RTX 4090 está em **manutenção**, sem jobs ativos na central, até Hank confirmar a estabilidade da memória.

O Studio envia descrições para `POST /api/v1/studio/text`. A central cria ou reaproveita um job `reference.generate` por descrição, seed e revisão do gerador. O worker com Z-Image publica um PNG verificado por SHA-256. O job de reconstrução recebe o ID da referência ao obter a lease e pode rodar em outra máquina. O manifesto registra o ID do job de referência. Repetir a reconstrução pelo Studio reaproveita o PNG salvo. **Gerar nova referência** força outra execução. O job de preparação baixa a versão exata do master e reaproveita derivados com os mesmos parâmetros quando os arquivos estão disponíveis.

O teste pelo navegador publicou **Validação Studio - Lanterna** (`ast_9ac97d50cf`). A Spark produziu a referência `ref_f959501840ae` em 117 s e o primeiro master TRELLIS.2 em 114 s, com 2.221.316 triângulos. A regeneração mudou a seed de 2705 para 2706, reutilizou a mesma referência e publicou a v2 em 138 s, com 1.976.952 triângulos. O Studio abriu o comparador de referência e de versões. O worker CPU da 206 criou a v3 Low Poly da v2 em 34 s, com 296.542 triângulos e exportações GLB, FBX e BLEND. Repetir a preparação com os mesmos parâmetros retornou o job concluído. Os SHA-256 dos masters e dos arquivos exportados foram verificados. A evidência está em `~/assetforge-phase3/studio-7ad5362-validation.log` na 206.

Passaram 8 testes Playwright, 38 testes de integração da API e 11 unitários do dashboard. O teste de múltiplas vistas no navegador conferiu os quatro uploads, a seleção manual e a manutenção dos 1536 solicitados, com o motor simulado nesse teste. A entrega do PNG a um segundo worker NVIDIA foi exercitada na integração; a validação física usou Spark e 206.

### Entradas e perfis de geometria

Use o seletor **Português / English** no login ou na barra superior. A preferência fica no navegador e muda os textos da interface sem reiniciar o formulário. O catálogo em `apps/dashboard/src/english.ts` usa o texto original em português como chave. Nomes cadastrados, relatórios gerados e mensagens brutas dos workers e provedores conservam o idioma de origem.

No estúdio, o botão × remove a imagem de uma vista ou um arquivo do lote. **Limpar lote** remove toda a seleção local. Os mesmos arquivos podem ser selecionados novamente.

**Reconstrução 3D** abre com Imagem, Múltiplas vistas e Descrição. A área de entrada mostra as referências e as miniaturas por vista. Motor, resolução, textura, worker, seed, tokens e projeção ficam em **Ajustes avançados**. O botão **Assets** abre a lista e as propriedades. O botão de expansão do visualizador oculta o formulário.

**Descrição** gera a referência PNG de 1024 px com Z-Image-Turbo no sidecar Python da Spark. A reconstrução aceita TRELLIS.2 GGUF ou Pixal3D Single-View. O worker atualizado anuncia `engine.split-reference` quando o sidecar está disponível. Receitas anteriores continuam usando `engine.text-reference`. A configuração Docker está em `deployment/docker-compose.text-reference.yml`. Na Spark, os pesos ficam em `/text-model` em modo somente leitura.

A máquina de venda do teste texto → GLB passou pela validação estrutural na Spark e está na Biblioteca como `ast_b540108ab6` v1. O TRELLIS.2 a 512 com decimação desmarcada exportou 3.677.152 triângulos. A fila registrou 523,5 s no total. A conferência validou o PNG e os hashes da referência e do GLB. A evidência está em `~/assetforge-phase3/workflow-text-evidence.log` na 206.

O segundo teste usou a categoria Veículo e a decimação selecionada explicitamente. O carrinho de entregas `ast_b0ca4a0d14` v1 passou na validação com 135.784 triângulos em 237,3 s. O PNG e os hashes foram conferidos. A evidência está em `~/assetforge-phase3/workflow-text-vehicle-evidence.log`.

**Master integral**, **High Poly**, **Mid Poly** e **Low Poly** oferecem proporções ajustáveis de 1, 0,80, 0,45 e 0,15 do master na Preparação. A Preparação pede altura e confirmação da geometria. O Blender ajusta a escala e o pivô com base no LOD0 simplificado e aplica o mesmo ajuste a todos os LODs. A torre de teste na 206 saiu de 297.650 para 44.647 triângulos no Low Poly, com um LOD adicional de 23.812. O SHA-256 do master foi conferido antes e depois.

Na 206, `~/assetforge-phase3/workflow.override.yml` seleciona `assetforge-central:studio-7ad5362` e `assetforge-worker:workflow-density`. O Compose recriou somente a API e a conferência dos IDs confirmou os demais contêineres. O rollback para a versão anterior ao Studio usa `~/assetforge-phase3/workflow-before-studio-distributed.override.yml`. Na Spark, o worker principal usa `assetforge-engine-worker:studio-c81a5c4`, com o contêiner anterior parado sob o nome `assetforge-spark-worker-before-studio-c81a5c4`. O sidecar segue em `workflow-ae1c4b5`.

O layout do estúdio anterior à reorganização (commit `5769f95`) voltou à tela **Reconstrução 3D**. O painel de geração fica à esquerda, o palco central preserva as bolinhas e o percentual original, e a coluna da direita reúne os assets e propriedades. O palco acompanha os pedidos de Pixal3D e TRELLIS.2 e abre a versão exata do GLB ao terminar. **Estúdio clássico** abre o painel anterior com seus modos originais.

Na 206, `~/assetforge-phase3/studio.override.yml` publica a imagem `assetforge-central:studio-ac8b456`. A verificação HTTP confirmou o bundle nas duas rotas do estúdio. O rollback usa `~/assetforge-phase3/archive40.override.yml`.

O login abre **Reconstrução 3D**. A navegação tem Visão geral, Reconstrução 3D, Agente de construções, Preparação de assets, Biblioteca e Infraestrutura. TRELLIS.2 GGUF e as três variantes do Pixal3D são os motores da reconstrução direta. TripoSR e Stable Fast 3D ficam em Motores legados. Gemini, Grok e os kits manuais ficam no fluxo de construção. A fila, os lotes, os workers e os provedores estão em Infraestrutura.

### Acervo e reprodução

`scripts/engines/import_library.py` importa os 40 experimentos a partir de `~/assetforge-phase3/archive40-source` na 206. Cada execução ocupa uma entrada da Biblioteca, com o master GLB em v1 e revisão humana pendente. Use o filtro **Experimentos CITY+++**. A versão inclui os PNGs de referência e de inferência, as poses multivista, os relatórios, as revisões dos pesos e o SHA-256 dos arquivos. Os GLBs nivelados, os pacotes Unity e os pilotos de otimização e impostores ficam em **Arquivos**. Os vínculos dos derivados com os masters dos pilotos usam o SHA-256 da fonte.

A importação publicou 14 masters TRELLIS.2 GGUF, 13 Pixal3D SV, 12 Pixal3D MV e um Pixal3D Python, sendo 21 da RTX e 19 da Spark. A comparação entre a origem e o armazenamento da central confirmou os 40 SHA-256. A verificação também conferiu 62 PNGs de referência distintos, 47 arquivos ou pacotes derivados e 10 pareceres Gemini. As evidências estão em `archive40-central-dry-run.jsonl`, `archive40-library-import.jsonl` e `archive40-live-verification.json` na 206. A importação reutilizou os GLBs existentes.

**Repetir geração** carrega a receita da versão em exibição. Mantém as imagens, a resolução solicitada, o orçamento de tokens, a seed, as configurações do exportador e os padrões históricos do CLI. A resolução efetiva e o tempo arquivados descrevem a execução anterior. Alterar a seed mantém os demais campos. Alterar uma imagem solicita nova preparação das vistas. A RTX permanece em manutenção no scheduler por causa das divergências de RAM. Para as receitas da RTX, é possível escolher a Spark, com a diferença de hardware e do build CUDA registrada como limitação de reprodutibilidade.

A reconstrução nova tem a decimação desmarcada por padrão. A exportação nativa ainda pode limpar ou remalhar a superfície conforme o motor. O master importado conserva o GLB gerado no experimento, inclusive as escolhas históricas de exportação.

### Preparação para Unity

Na Biblioteca, **Preparar para Unity** seleciona uma versão original. O worker CPU baixa o GLB da versão de origem por uma rota vinculada à lease, registra seu SHA-256 e exporta uma versão derivada com metragem, rotação explícita, pivô, PBR, colisão e arquivos GLB, FBX e BLEND. Os LODs simplificados exigem proporções informadas pelo usuário. A versão do master continua acessível em **Versões**.

O teste de ponta a ponta passou por API, fila e Blender em Docker isolado na 206. A torre a 48 m manteve 297.650 triângulos no LOD0 e gerou 148.825 no LOD1 de teste. O SHA-256 de v1 permaneceu `9432a1580d8725ec7db3d0d4ccf666057d90a1b7e3da9b69ddd45e2eed9a68ca`. O benchmark dentro da Unity continua pendente de um Editor licenciado.

### Agente de construções

O prompt `spec-v3` pede conciliação das vistas, proporções dos volumes, ritmo de fachada, contagem de pavimentos e registro das inferências sobre lados ocultos. `scripts/ai/compare_building_providers.py` usa os mesmos PNGs na mesma ordem, registra os hashes e valida a especificação dos dois provedores no pool central. Gemini `gemini-3.5-flash-lite` produziu especificações válidas para o residencial e o comercial, com tempos de 5,10 s e 6,56 s. Os dois relatórios estão em `~/assetforge-phase3/agent-spec-v3-*.json` na 206. A comparação lado a lado depende da ativação do Grok no painel de IA. Na Biblioteca, o visualizador e a avaliação Gemini usam as referências originais quando presentes. A revisão visual e as liberações comerciais permanecem pendentes.

### Docker

Na 206, `~/assetforge-phase3/archive40.override.yml` seleciona a API `assetforge-central:archive40-original-refs` e o worker CPU `assetforge-worker:archive40-118e531`. O rollback da central usa `~/assetforge-phase3/live.override.yml`. Na Spark, os workers GGUF e Python usam as imagens `archive40-118e531`. Os contêineres anteriores estão parados com sufixo `-before-archive40`. Os logs de importação e validação ficam em `~/assetforge-phase3/archive40-*` na 206. A alteração da RTX ficou restrita ao estado do worker na central.

A suíte de backend passou com 253 testes em Docker. A rodada de regressão após o ajuste da avaliação Gemini passou com quatro testes. Os 11 testes Vitest e os três testes Playwright também passaram. O Playwright confirmou a alteração isolada da seed, a fila e o download HTTP do GLB.

## Reteste da memória da RTX 4090 · 27/11/2026

Na tentativa seguinte de repetir `memtester 4G 1`, o host da RTX 4090 ficou inacessível por SSH. O acesso direto expirou e a central retornou `No route to host` nas duas tentativas. Nenhum novo teste iniciou. O último resultado confirmado segue sendo o teste após o ajuste Manual descrito abaixo.

### Após o ajuste de AI Overclock / Tuning para Manual

O SSH voltou com a chave já cadastrada após a reinicialização. O SMBIOS continuou reportando quatro módulos DDR4 de 32 GiB configurados a 2.666 MT/s. O Linux reportou 126.227 MiB utilizáveis.

O mesmo contêiner executou `memtester 4G 1`. Os 4.096 MiB foram alocados e bloqueados. O `Checkerboard` completou e as duas divergências foram registradas em `Bit Flip`, nos offsets `0x732d4a68` e `0x7ceb7558`. Em ambas, o XOR foi `0x02000000`, igual ao bit divergente do reteste anterior. O monitor encerrou o contêiner aos 275 s, às 19h31min08s de Brasília. A menor memória disponível foi 120.327 MiB.

A falha em 4 GiB bloqueou a progressão para 16, 32 e 64 GiB, os benchmarks de concorrência e os pilotos Python. Os três serviços da RTX mantiveram o tempo de execução e os dois workers reportaram heartbeat à central. Os logs estão em `~/assetforge-city-validation/ram-manual-20261127T222633Z/` e a cópia local verificada por SHA-256 está em `reports_out/engines/rtx4090-memory-manual/`.

### Reteste anterior ao ajuste Manual

O acesso SSH ao host `htsllm2` foi restabelecido com verificação estrita. Tanto o acesso direto quanto o caminho pela central apresentaram a chave ED25519 que já estava cadastrada. A divergência encontrada anteriormente não apareceu nessas duas conexões. A confirmação por e-mail foi solicitada a Hank e estava pendente ao encerrar o reteste.

O SMBIOS reportou quatro módulos DDR4 de 32 GiB, configurados a **2.666 MT/s**, com 128 GiB instalados. O Linux reportou 126.227 MiB utilizáveis, ante 126.326 MiB na leitura anterior. A frequência efetiva da configuração anterior não foi registrada. A inspeção usou a tabela SMBIOS em modo somente leitura.

| Teste em Docker | Resultado | Evidência |
| --- | --- | --- |
| Antes da alteração, `memtester 4G 1` | Falhou | 12 mensagens de falha. A execução percorreu os padrões seguintes. |
| Após a alteração, `memtester 4G 1` | Falhou em 179 s | 4.096 MiB alocados e bloqueados. O monitor encerrou o contêiner ao detectar erros em `Checkerboard`. Seis divergências ficaram registradas antes da parada. |

As seis divergências do reteste ocorreram em endereços distintos e repetiram a diferença de um bit (`0x02000000`) entre `0xaaaaaaaaaaaaaaaa` e `0xaaaaaaaaa8aaaaaa`, já presente em uma falha anterior. As contagens vêm de ciclos com condições de parada diferentes. A execução começou às 18h46min50s e terminou às 18h49min49s, horário de Brasília. A menor memória disponível foi de 119.732 MiB. O encerramento foi comandado pelo monitor por `memory_mismatch`. Os serviços `assetforge-4090-worker`, `vlm-gpu` e `triposr-gpu` mantiveram o tempo de execução. A central continuou pronta e recebeu heartbeat dos dois workers.

O reteste de 4 GiB bloqueou a progressão para 16, 32 e 64 GiB, a nova rodada de concorrência e os pilotos Pixal3D Python e TRELLIS.2 Python na RTX. Os logs e a telemetria ficaram em `~/assetforge-city-validation/ram-retest-20261127T214650Z/`. A cópia local fica em `reports_out/engines/rtx4090-memory-retest/` e reúne também o memtester anterior e a pilha original do GDB. O SHA-256 do arquivo de evidências coincidiu após a transferência.

## Preparação para CITY+++ · 27/11/2026

### Workers e memória

A RTX 4090 está instalada em um host com 128 GB nominais. O Linux reporta 126.326 MiB de RAM utilizável e a GPU reporta 24.564 MiB de VRAM. A Spark reporta 124.608 MiB unificados. O agendamento NVIDIA considera a telemetria real e a reserva disponível. Os dois contêineres continuaram emitindo heartbeat na central durante o diagnóstico.

O GDB reproduziu um SIGSEGV na inferência concorrente de três NPCs a 1024 na RTX. A thread principal caiu em `trellis::build_neighbor_table`, chamada por `sparse_c2s`, `decode_unet` e `shape_decode`. Os dois outros processos terminaram. Uma tentativa de baixar a imagem CUDA qualificadora falhou com erro de digest, e o compilador da imagem instrumentada com AddressSanitizer também sofreu segfault.

O teste independente `memtester 4G 1`, em Docker sem GPU, registrou 12 falhas em endereços distintos. Os padrões incluíram endereço possivelmente inválido e divergências de bits em leituras vindas de escritas conhecidas. A falha de memória do host é demonstrada. A origem física entre módulo, canal e controlador ainda está em aberto. A pilha do GDB mostra onde o processo caiu, sem identificar onde os dados foram corrompidos. Os ensaios de carga e builds de diagnóstico do AssetForge na RTX foram interrompidos. Os serviços existentes e o worker mantiveram seus processos. A chave SSH apresentada pela RTX mudou mais tarde. O OpenSSH recusou recuperar os logs e a verificação da chave foi mantida.

O build Python ganhou parâmetros de CUDA e arquitetura para a RTX, o Pixal3D aceita `--cpu-offload` e o piloto TRELLIS.2 Python usa pesos locais com offload opcional. Os pesos principais foram baixados, mas a RTX ainda não produziu GLBs Python verificáveis. A confirmação do hardware e da identidade SSH antecede a repetição desses dois pilotos. A memória real do worker substitui a indicação anterior de 22 GiB. Os números de 22 GiB em medições antigas são históricos.

### Referências e uso do painel

A entrada aceita PNG, JPEG e WebP, com normalização da rotação EXIF, e o envio em lote cria um pedido por conjunto de vistas. Para motores multivista, o lote associa nomes `asset__front`, `asset__right`, `asset__back` e `asset__three_quarter`. O usuário informa as vistas que possui. A preparação usa BiRefNet, reaproveita as máscaras existentes, alinha o enquadramento e registra referências repetidas e diferenças de enquadramento. A imagem enviada permanece na Biblioteca como referência original. O worker antigo pode atender imagens já recortadas no Pixal3D. O scheduler reserva a remoção automática no Pixal3D para workers que anunciam essa capacidade.

A regeneração parte da versão escolhida na Biblioteca e permite substituir apenas as vistas necessárias. A fila apresenta preparação, condicionamento, inferência, malha e texturas, validação e empacotamento. No navegador isolado, um JPEG e um WebP criaram dois jobs de um lote. Na Spark, o JPEG passou por recorte automático e Pixal3D SV e produziu um GLB que passou na validação estrutural. Outro teste preparou quatro vistas, com dois recortes automáticos e duas máscaras preservadas. O Playwright também confirmou uma regeneração Pixal3D MV que trocou apenas a frente e reutilizou as outras três referências da versão.

A central executa `assetforge-central:city-live` e a Spark executa `assetforge-engine-worker:city-live` com a capacidade `engine.reference-prep`. A RTX segue registrada e anuncia os motores GGUF. A troca recriou somente a API do AssetForge e o worker NVIDIA da Spark. A imagem anterior da API está registrada em `before-city.override.yml` na central e o contêiner anterior da Spark ficou parado como `assetforge-spark-worker-before-city`. Os 45 testes de API e fila passaram em Docker antes da troca.

### Pacotes para Unity

`scripts/engines/prepare_game.py` gera derivados em Blender Docker com correção de orientação explícita, metragem, pivô na base, colisão simplificada, mapas para Unity URP, GLBs separados por LOD, FBX, BLEND e `assetforge-import.json`. Os masters foram montados apenas para leitura e tiveram SHA-256 conferido. Os pacotes reais estão em `~/assetforge-phase3/unity-packs/` na central.

| Piloto | Altura (m) | Triângulos LOD0 | Triângulos LOD1 | Triângulos LOD2 | Colisão |
| --- | ---: | ---: | ---: | ---: | --- |
| Residencial | 42 | 929.723 | 418.314 | 139.263 | Caixa |
| Operário | 1,8 | 967.151 | 435.204 | 145.010 | Cápsula |
| Caminhão | 3,4 | 960.367 | 432.153 | 144.024 | Caixa |

As proporções de ensaio foram 1, 0,45 e 0,15. O pipeline de importação e exportação do Blender alterou ligeiramente a contagem do LOD0. As proporções servem para comparar candidatos em Unity. A auditoria reabriu os três BLEND, importou os três FBX e conferiu a altura física e o piso no zero. Os hashes das duas texturas embutidas coincidiram entre os três LODs de cada pacote. As evidências de importação e os metadados estão em `reports_out/engines/city-validation/`.

O piloto de rigging montou 13 ossos no operário retopologizado, mas o automatic weights do Blender deixou os 20.551 vértices sem peso. O caminhão não apresentou rodas destacáveis pelo teste de componentes conectados. O residencial gerou uma seção aberta a 21 m, com 487.619 triângulos. Esse corte permite estudar estágios de obra sem kit e requer geometria de acabamento para virar um estágio utilizável.

O projeto `integrations/unity-benchmark` está isolado e prepara o URP, a matriz de cenas e os CSVs de frame time, FPS, draw calls, triângulos, memória e transições visíveis de LOD. O usuário confirmou que ainda não há um Editor Unity licenciado disponível. A execução do player e os orçamentos geométricos ficam pendentes.

## Integração experimental de motores · 27/11/2026

A aba **Motores** cria jobs de TRELLIS.2 GGUF, Pixal3D Single-View, Multi-View e Python. O kit procedural continua disponível pelo gerador existente. A aba valida as vistas, expõe os parâmetros de inferência e lista os workers que anunciam o motor. Pixal3D SV e MV usam PNGs com transparência. Os motores GGUF permitem pular a decimação nativa do exportador. A Biblioteca carrega o GLB no visualizador, compara vistas originais ou duas versões e registra a revisão humana por versão. As avaliações Gemini usam a configuração de IA da central e têm parecer próprio. Os quatro motores e seus pesos continuam experimentais, com revisão de licença comercial pendente.

Um teste do exportador TRELLIS.2 com `--decim 0` na RTX 4090 escreveu 1.118.836 triângulos, textura de 4096 px e GLB de 40,5 MB em 64,7 s, com resolução 512. O piso de referência do visualizador se alinha à base de cada GLB para não cobrir masters que vêm centrados na origem.

O worker NVIDIA corre em Docker e anuncia temperatura, utilização e memória. A admissão usa histórico por motor, categoria, resolução, tokens e textura, com reservas transitórias após falhas. Na Spark, a reserva usa RAM unificada e o executor Python compartilha a fila com os GGUF por um volume local. O executor Python fica sem rede e usa pesos montados somente para leitura. O GGUF da Spark inclui o patch da grade CUDA registrado neste HANDOFF.

| Cenário TRELLIS.2 GGUF, 1024 efetivos · seed 1 · textura 4096 | RTX 4090 | DGX Spark |
| --- | --- | --- |
| Dois NPCs com as mesmas imagens | 2/2, 69 e 72 s | 2/2, 231 e 230 s |
| Três simultâneos | Falhas nativas 139, inclusive com `OMP_NUM_THREADS=1` | — |
| Quatro simultâneos, uma thread por processo | 4/4, quatro GLBs entre 109 e 120 s | — |
| Operário pela fila do AssetForge, TRELLIS.2 | 50,0 s, 4.938 tokens | 340,6 s, 4.848 tokens, sobreposto a SV e MV |

Nos ensaios de três e quatro jobs da RTX 4090, a telemetria continuou com mais de 15 GiB livres de VRAM e pico de 73 °C no ensaio de uma thread. Uma falha apresentou `double free or corruption (!prev)`. A leitura final dos quatro `result.txt` da rodada de quatro jobs confirma 4/4, corrigindo a leitura provisória de 3/4. O ensaio de três jobs teve falhas nativas. `scripts/engines/benchmark_capacity.sh` reproduz a carga de NPCs e registra o tempo, o código de saída e a telemetria. Cada rodada deve usar um diretório novo.

Na fila isolada, a Spark publicou três masters válidos de 1024 efetivos no mesmo lote. TRELLIS.2, Pixal3D SV e Pixal3D MV levaram 340,6 s, 331,0 s e 378,2 s, respectivamente, com a inferência sobreposta. O checkpoint DINOv3 existente estava em modo 0600 e o UID do executor Python não conseguia abrir o arquivo. Uma cópia local do AssetForge foi montada somente para leitura. O novo teste publicou o GLB com 1024 efetivos em 265,6 s. A RTX 4090 também publicou a segunda versão do operário via Pixal3D SV em 60,3 s. Foram seis gerações concluídas pela fila.

### Validação visual

Dez pareceres Gemini foram produzidos com os renders arquivados e a referência frontal, passando por `AiRouter` e pelo pool central. A avaliação depende das vistas e do enquadramento. Cada linha abaixo usa um exemplo real da categoria.

| Modelo de teste | TRELLIS.2 GGUF | Pixal3D SV | Pixal3D MV | Pixal3D Python |
| --- | ---: | ---: | ---: | ---: |
| Residencial | 7,5 | 3,5 | 6,5 | 6,5 |
| Caminhão industrial | 6,5 | 8,5 | 2,5 | — |
| NPC operário | 8,5 | 9,2 | 8,5 | — |

O piloto de derivados em Blender manteve os SHA-256 dos masters. O residencial passou de 930.515 para 725.222 triângulos com dissolução planar e preservação de bordas de UV e material. O caminhão passou de 960.926 para 817.861 com tolerância angular menor. A limpeza de componentes do operário gerou 966.377 triângulos a partir de 967.602. Os três candidatos conservaram os hashes das texturas incorporadas. A busca por placa de chão separada no residencial não encontrou componente dentro do critério. O atlas de impostor do caminhão foi exportado com oito vistas de 256 px e fundo transparente. Os candidatos precisam de validação visual e de desempenho na Unity antes de definir LODs ou uma distância de troca.

A retopologia do operário falhou nas malhas voxelizadas com células de 0,006, 0,009 e 0,013 da maior dimensão. A célula de 0,018 gerou um proxy de 10.286 triângulos com cor, normal tangente e rugosidade reprojetadas a 512 px. As tentativas preservaram o master. O proxy é uma amostra para benchmark e revisão de silhueta.

Os pareceres, derivados, atlas e capturas de tela foram reunidos localmente em `reports_out/engines/phase3/`. Em Playwright, o dashboard ofereceu os workers compatíveis, abriu um GLB com a imagem original, renderizou duas versões lado a lado, capturou uma vista e registrou aprovação e rejeição no ambiente isolado. A versão foi devolvida a pendente ao final do teste.

### Docker

Em 27/11, o dashboard e a API experimental foram publicados na central. O Compose recriou somente o contêiner da API e o endpoint de prontidão confirmou banco e armazenamento. Os workers `assetforge-4090` e `assetforge-spark` registraram heartbeat no ambiente principal. Na central, `~/assetforge-phase3/live.override.yml` seleciona a imagem testada e a tag `assetforge-central:before-phase3` guarda a imagem imediatamente anterior. As credenciais de registro são privadas.

O commit `8027a48` trata a falha de autenticação do servidor CPU3D em Windows. Bytes pendentes de um POST recusado causavam fechamento abrupto do TCP e o cliente podia receber `WinError 10053` antes do 401. A resposta é enviada e o sentido de escrita é fechado primeiro, seguido de drenagem limitada. A regressão de autenticação passou seis vezes em Windows.

Use `deployment/docker-compose.engines.yml` nos hosts com Compose. A variável `ENGINE_IMAGE` aponta para a imagem CUDA já construída para a arquitetura. `ENGINE_MODELS_DIR` aponta para os subdiretórios `trellis2-q8`, `pixal3d-sv-q8` e `pixal3d-mv-q8`. Passe a URL da API, nome do worker e token de primeiro registro por `ENGINE_WORKER_ENV_FILE` em arquivo privado. O nome do worker e o volume persistente identificam a credencial após o registro.

Na Spark, ative `--profile pixal3d-python` e informe `PIXAL3D_MODELS_DIR`, `PIXAL3D_DINOV3_DIR` e `PIXAL3D_CACHE_DIR`. O UID 10002 precisa ler as configurações e pesos e gravar somente no cache e no volume de execução. O cache de NAF deve estar preparado para uso offline. Na RTX 4090, onde o plugin Compose estava ausente, o equivalente é `docker run` com `--gpus all --ipc host --init`, pesos em `/models:ro`, volume persistente em `/state` e arquivo de ambiente privado.

Para avaliação de LODs, execute `scripts/engines/derive_master.py` e `scripts/engines/impostor_atlas.py` dentro da imagem Blender de revisão. Monte os masters somente para leitura e grave em outro volume. A retopologia experimental usa QuadriFlow, com voxelização opcional e reprojeção de cor, normal tangente e rugosidade quando disponível. Candidatos que falham na retopologia ficam sem publicação. O atlas inclui azimutes, extensão do enquadramento, centro e layout para a integração futura na Unity.

## Continuidade do AssetForge em 2026-11-27

Esta seção registra o estado depois da retomada. Os dados mais antigos ficam abaixo para referência histórica.

### Bateria CITY+++

Às 14h50 (Brasília), as duas cadeias registravam `CITY_CHAIN_DONE`. A RTX 4090 concluiu 18 de 18 execuções do lote com 1024 solicitados. A Spark concluiu 17 de 18. O TRELLIS.2 Q8 do veículo civil saiu com código 133 durante a cópia CUDA. O log registra 1536 efetivos e 45.835 tokens antes da falha.

A 4090 deixou de responder ao SSH durante a recuperação e voltou a responder às 15h42 (Brasília). Após o retorno, o Linux via 123 GiB de RAM e a RTX 4090 reportava 24.564 MiB de VRAM. A configuração de RAM medida antes do retorno era de 22 GiB. `fetch_results.sh` recuperou os 15 modelos restantes. Os SHA-256 dos 21 GLBs da RTX 4090 (18 do lote e três testes da torre) e dos 17 GLBs concluídos na bateria original da Spark coincidiram com os arquivos de origem.

A tabela reúne as medianas de tempo total e as resoluções efetivas nos logs das execuções concluídas na Spark.

| Categoria | TRELLIS.2 Q8 | Pixal3D single-view Q8 | Pixal3D multi-view Q8 |
| --- | --- | --- | --- |
| Arranha-céus | 765,3 s · 1280–1536 | 325,4 s · 1024 | 1.014,8 s · 1280–1536 |
| NPCs | 244,2 s · 1536 | 106,3 s · 1024 | 243,8 s · 1536 |
| Veículos | 1.303,8 s · 1152 (um modelo) | 771,4 s · 1024 | 1.636,2 s · 1408–1536 |

Medianas do tempo total na RTX 4090, com 1024 efetivos confirmados no log das 18 execuções.

| Categoria | TRELLIS.2 Q8 | Pixal3D single-view Q8 | Pixal3D multi-view Q8 |
| --- | --- | --- | --- |
| Arranha-céus | 117,25 s | 122,60 s | 176,05 s |
| NPCs | 54,55 s | 64,35 s | 77,35 s |
| Veículos | 190,85 s | 198,15 s | 173,95 s |

O `analyze_city.py` registrou 40 análises e 160 vistas conferidas em `reports_out/engines/analysis/`. São os 36 modelos do lote com a recuperação do veículo corrigido, os três testes da torre e o residencial Python. Há sete folhas de modelos e uma de otimização em `reports_out/engines/analysis/sheets/`. O arquivo `all.json` inclui a resolução efetiva de cada modelo e os tokens registrados nos logs. O script também foi validado na 206, em Docker, com o master multi-view do prédio comercial.

* **Arranha-céus.** O multi-view manteve varandas e janelas nas costas do residencial. O TRELLIS.2 gerou uma fachada traseira lisa. No comercial, o multi-view manteve o vidro azul e o volume lateral, com artefatos no chão. O single-view do residencial apresentou eixo principal quase horizontal nas duas máquinas.
* **NPCs.** O multi-view manteve o padrão refletivo do colete do operário. No civil, os três motores escureceram a camiseta. O multi-view acrescentou volumes nos sapatos e o TRELLIS.2 teve a menor contagem de triângulos.
* **Veículos.** O single-view e o TRELLIS.2 corrigido mantiveram a silhueta do carro civil, com lanternas simplificadas e carroceria mais escura. O multi-view do caminhão acrescentou janelas no baú na Spark e deformou a porta traseira na 4090. O single-view abriu a traseira na Spark. O TRELLIS.2 escureceu a cabine e mudou a cor do baú.

As câmeras são fixadas em relação aos eixos do GLB. A frente e as costas podem aparecer trocadas quando o motor gera o asset girado. O ângulo PCA mede o eixo principal da geometria, que costuma ser horizontal em veículos. A coluna de RAM mede o aumento no host durante a execução e inclui outras cargas concorrentes.

### Limite de grade CUDA

No `cpy.cu` do GGML fixado pelo motor, o caminho otimizado de transposição agrupa oito matrizes por bloco em Z. O limite de CUDA para esse eixo é 65.535 blocos. A quantidade de matrizes vem da forma do tensor, por isso o teto de tokens do piloto ainda deixa passar casos que acionam a asserção. O patch em `deployment/ggml-cuda-transpose-grid.patch` conserva o caminho otimizado dentro da grade válida e usa o kernel genérico de cópia por strides para grades maiores. [Código GGML fixado](https://github.com/pwilkin/ggml/blob/737e88f25d4f62254f3b7a726fd9663036cc94da/src/ggml-cuda/cpy.cu#L207-L243) · [Limites CUDA](https://docs.nvidia.com/cuda/cuda-programming-guide/05-appendices/compute-capabilities.html)

Em Docker na GB10, a imagem de referência retornou 133 em `grid_z=65535`. A imagem corrigida passou em 1, 65.535 e 65.536 blocos em Z. No maior caso, os 10.485.620 valores foram iguais aos da transposição de referência. O teste pode ser executado com o alvo Docker `cuda-grid-check` e `CUDA_ARCHS=121`.

O veículo civil foi reexecutado em `veh_civilian_001_t2q8_1536_spark_gridfix`. A execução com a imagem corrigida usou os mesmos 1536 efetivos, 45.835 tokens e seed 1. Exportou o GLB de 298.460 triângulos em um componente em **2.129,3 s**, incluindo o período de sobreposição com o piloto Python. O resultado foi recuperado com `fetch_results.sh`, conferido pelo SHA-256 e incluído na folha do veículo civil. O log e o diretório originais da falha foram preservados.

```bash
docker build --target cuda-grid-check --build-arg CUDA_ARCHS=121 \
  -t assetforge-ggml-grid:verify -f deployment/Dockerfile.pixal3d-cuda .
docker run --rm --network none --ulimit core=0 --gpus all assetforge-ggml-grid:verify
```

### Pixal3D Python e otimização

O piloto Python usa o código e os pesos multi-view fixados, uma imagem Docker derivada para a Spark e um diretório de trabalho separado (`~/assetforge-pixal3d-python`). As vistas entram com máscara alfa, o DINOv3 existente é montado somente para leitura e a exportação usa o bake do AssetForge protegido por `license_guard`. O build e o download dos 14 arquivos do modelo terminaram. O teste de importação executou uma soma CUDA na GB10 com PyTorch 2.7.1 e NATTEN 0.21.0. O residencial foi exportado a **1536 efetivos** em **1.567,06 s**, com 52.993.226 faces decodificadas antes da exportação. O JSON de execução registra zero chamadas às bibliotecas bloqueadas. O master e as métricas estão em `result/bldg_skyscraper_residential_001_mvpy_1536_spark/`.

O GLB final de 38,4 MiB tem 930.515 triângulos e 472 componentes após soldar posições equivalentes. São 26.758 triângulos fora do maior componente. As vistas mostram o prédio completo e uma placa de chão gerada pelo motor. O multi-view C++ da Spark gerou um único componente para o mesmo residencial a 1280 efetivos. A cópia local do GLB Python foi conferida pelo SHA-256 e está incluída na folha do residencial.

Os dois containers de geração dividiram a Spark durante o teste. A memória disponível chegou a 20,7 GiB no bake Python. Na amostragem C++, as três primeiras etapas levaram 109–115 s por etapa. Na sobreposição com a forma e textura do Python, houve etapas de 225–253 s. O teste demonstra que as duas cargas podem coexistir nesta configuração e que a latência aumenta quando ambas saturam a GPU.

Na RTX 4090, dois jobs Docker de NPC a 1024 efetivos rodaram simultaneamente, com seed 1 e atlas de 4096. O TRELLIS.2 Q8 gerou `npc_government_001` em 81 s e o Pixal3D multi-view Q8 gerou `npc_public_service_001` em 97 s. O pico de VRAM total foi 6.825 MiB, com 120.328 MiB de RAM disponíveis no menor ponto. VLM e TripoSR continuaram ativos. Os dados estão em `~/assetforge-engines/concurrency-city-20261127/` na RTX 4090. Os GLBs de 276.134 e 976.810 triângulos estão com os logs em `reports_out/engines/concurrency/rtx4090/`, conferidos pelo SHA-256. A medição cobre duas cargas leves e complementa a bateria original.

O arquivo `scripts/engines/pixal3d_python.py` oferece `download --models /models` e `generate`. O comando abaixo usa os pesos já baixados e um diretório novo para a saída. Execute-o no checkout do AssetForge na Spark.

```bash
pilot="$HOME/assetforge-pixal3d-python"
views="$HOME/assetforge-engines/refs/city/bldg_skyscraper_residential_001/mv4"
mkdir -p "$pilot/result/residential-1536-revisao" "$pilot/cache"
docker build -f deployment/Dockerfile.pixal3d-python -t assetforge-pixal3d-python:spark .
docker run --rm --gpus all --ipc host --user "$(id -u):$(id -g)" \
  -e HOME=/tmp -e TORCH_HOME=/cache/torch -e TORCHINDUCTOR_CACHE_DIR=/cache/inductor \
  -e ATTN_BACKEND=flash_attn -e HF_HUB_OFFLINE=1 \
  -v "$PWD:/assetforge:ro" -v "$pilot/cache:/cache" -v "$pilot/models:/models:ro" \
  -v "$views:/views:ro" -v "$HOME/clonez-models/dinov3-vitl16-hf:/dino:ro" \
  -v "$pilot/result/residential-1536-revisao:/out" \
  --entrypoint python assetforge-pixal3d-python:spark /assetforge/scripts/engines/pixal3d_python.py generate \
  --views /views --models /models --dinov3 /dino --output /out/model.glb \
  --resolution 1536 --max-tokens 131072 --seed 1
```

O piloto de otimização usa `gltfpack` em Docker e exige os mesmos SHA-256 para as texturas incorporadas antes de entregar o GLB derivado. No prédio comercial multi-view da Spark, o master de 997.086 triângulos e 42.219.256 bytes deu derivados de 498.536 triângulos e 26.021.812 bytes (alvo 50%) e 249.270 triângulos e 16.628.760 bytes (alvo 25%). O SHA-256 do master permaneceu idêntico. A silhueta, as fachadas e as faixas do topo se mantiveram nas duas vistas revisadas. A folha local está em `reports_out/engines/analysis/sheets/comparativo-otimizacao.jpg`. A repetição em outras categorias segue pendente.

Para os alvos 15.000, 7.500, 2.500 e 500 triângulos, o simplificador conservador parou entre 120.820 e 120.878 triângulos nesse master. Os derivados preservaram as texturas. Na folha de 120.820 triângulos aparecem ondulações e interrupções nas linhas da fachada. LODs mais leves exigem avaliar outra estratégia de simplificação ou reprojeção.

A aprovação artística é do dono. A integração dos motores ao dashboard segue a aprovação de cada motor, e o uso comercial depende da revisão das licenças. Os testes de concorrência cobrem duas cargas específicas por máquina. Falta medir a vazão sob demanda e a coexistência de duas cargas pesadas na 4090.

Na suíte local, 245 testes passaram. O teste de autenticação do provider CPU3D reproduziu `WinError 10053` no commit anterior `1085197` e foi executado separadamente.

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
| **192.168.1.203** (`afforge`, host `htsllm2`) | RTX 4090 24 GB, i9-11900K, 128 GB RAM instalados, 126.326 MiB utilizáveis no Linux | Roda `vlm-gpu` (Qwen, :8081), `triposr-gpu` (:8082) e o worker AssetForge em Docker, sem plugin Compose. O primeiro teste de integridade da RAM falhou. Ver o diagnóstico CITY+++ no início deste documento. |
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
| Torre · TRELLIS.2 Q8 (pedido 1536) | 4090 | **1152 efetiva** (1536 recuou 1536→1408→1280→1152 pelo limite de 49.152 tokens) | 336,5 s | +7,9 GB | 14,6 GB | 293.090 / 1 |
| Torre · Pixal3D single-view Q8 | 4090 | 1024 | **127,1 s** | +3,1 GB | **7,2 GB** | 931.734 |
| Residencial_001 · TRELLIS.2 Q8 | 4090 | 1024 | 160,0 s | +4,1 GB | 8,1 GB | 295.794 / **1 componente** |
| (referência) Torre · TRELLIS.2 **Python** | Spark | 1024 | ≈ 285 s + 50 s de textura | 69–75 GB (sistema) | n/d | ≈ 453 mil |

* **Pixal3D single-view é ≈ 45 % mais rápido que o TRELLIS.2 Q8 e usa ≈ 40 % menos VRAM**. Cor e detalhe de fachada ficam **mais fiéis** à referência (bege com verde-oliva, caixilhos, pilastras), mas o modelo sai **no referencial da câmera, inclinado** (≈ 9,9° na torre).
* **Correção de orientação** (`scripts/engines/level_glb.py`): estima a inclinação do eixo dominante e grava um GLB NOVO só com um nó pai (rotação + translação: de pé, pivô na base). Vértices e texturas ficam byte a byte iguais ao original, então o master é preservado. Torre single-view: profundidade 0,655 → 0,535; o TRELLIS.2 já vinha ≈ 1,2°. Limite de segurança `--max-tilt 40`.
* **CORREÇÃO**: o "TRELLIS.2 Q8 1536" da torre NÃO rodou em 1536: o limite de 49.152 tokens recuou a resolução para **1152** (log: `res1536 -> 75244 tokens >= 49152, backing off`). O 1536 real exige `--max-tokens` ≥ ~75k (a torre) e provavelmente mais para outros ativos. O `trellis-cli` loga o recuo, mas é preciso ler o `raw.log` (`grep -i backing`). Resolução efetiva deve ser sempre registrada.
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

### Primeiro comparativo real das referências do dono — `bldg_skyscraper_residential_001`, RTX 4090, 1024 (medido; folha: `reports_out/engines/analysis/sheets/bldg_skyscraper_residential_001.jpg`)

| Motor | Tempo | Pico RAM (acima da base) | Pico VRAM | Triângulos | Componentes | Inclinação estimada | Observação visual (impressão do assistente, NÃO aprovação) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **Pixal3D multi-view Q8 (4 vistas)** | 219,0 s | +4,8 GB | 8,4 GB | 982.020 | 1 | 1,9° | **Melhor**: colunas verde-oliva, pilastras e varandas, **janelas em todas as faces (traseira inclusive)**; cor um pouco mais escura/dourada que a referência |
| TRELLIS.2 Q8 (vista frontal) | 160,0 s | +4,1 GB | 8,1 GB | 295.794 | 1 | 2,3° | boa frente; **traseira inventada e lisa**; sem verde-oliva |
| Pixal3D single-view Q8 (RGBA frontal) | 149,1 s | +3 GB | 7,3 GB | 955.714 | 1 | **88,6°** (modelo "deitado") | **Falhou**: modelo fora de eixo (acima do `--max-tilt 40`, o nivelamento recusou corrigir) e textura estragada. Na torre o mesmo motor funcionou, então é **instável conforme a imagem** |

* Aprendizados: (1) o multi-view foi o único a reproduzir a traseira; (2) o single-view do Pixal3D exige a imagem no enquadramento de câmera (FOV 20°) e é sensível: investigar com `--fov`, recorte normalizado (o `prep_views.py` gera `mv4/view00_front_azim000.png` já normalizado a 85 %, usar como entrada do `--sv-image`) e vista com elevação; (3) a correção de orientação só vale para inclinações pequenas, não resolve modelo deitado.
* **Sem vencedor declarado**: só 1 ativo analisado; aguardar a bateria completa (as duas cadeias seguem rodando) e a aprovação visual do dono.
* Ainda sem Gemini nestes modelos (rodar `scripts/ai/gemini_compare.py` na central; ver §Gemini comparar).

### Correção de rumo (resolução efetiva) e reinício da Spark

* A cadeia da Spark foi **reiniciada** com `MAXTOK=131072` (`chain_city.sh` agora aceita a variável `MAXTOK`, padrão 49152) para que o pedido de 1536 seja realmente 1536. Comando: `MAXTOK=131072 nohup bash chain_city.sh assetforge-pixal3d:cuda121 spark 1536 <ativos>`. Resultados antigos da Spark (resolução reduzida) foram descartados.
* Ao analisar cada run, conferir no `raw.log` as linhas `backing off` e `-> quantized @resNNNN` para a **resolução efetiva**. Na 4090 em 1024 não há recuo (a torre usa 31.965 tokens e o prédio residencial 23.079, abaixo de 49.152).
* Memória: o 1536 real é mais pesado; o guarda de RAM do `run_cpp.sh` (`MIN_AVAIL_GB`, padrão 10) para só o container do AssetForge. A Spark tem ≈ 121 GB de memória unificada.

---

# REGISTRO HISTÓRICO (consolidado em 2026-11-27 ~02:00 CST na Spark / 07:50 UTC)

**Antes de tudo**: o Codex deve **estudar o projeto inteiro antes de modificar qualquer arquivo** (ler este HANDOFF do início ao fim, `docs/CLOUD_AI.md`, `docs/TRELLIS2_INTEGRATION.md`, `docs/GPU.md`, `docs/VISION.md`, `scripts/engines/*`, `scripts/trellis2/*`), **recuperar os resultados das baterias existentes** (comandos abaixo) e continuar exatamente daqui, **sem repetir testes já feitos**.
**Não** iniciar baterias novas desnecessárias antes de concluir as atuais. **Não** tornar os kits procedurais obrigatórios (eles competem como mais um motor). **Preservar a RTX 4090 e a Spark como workers ativos de geração 3D.** **Não** iniciar o Projeto Dragão de Três Cabeças.
O **Pixal3D multi-view é o principal candidato, mas NÃO foi escolhido definitivamente.** Nenhum vencedor está declarado: a aprovação visual é do dono.

## 1. Processos em execução agora (estado exato)

| Máquina | Processo | O que faz | Estado |
| --- | --- | --- | --- |
| **4090** (`afforge@192.168.1.203`) | `bash chain_city.sh assetforge-pixal3d:cuda89 4090 1024 <6 ativos>` (PID 105691 no momento da escrita) | 6 ativos × 3 motores (t2q8, sv, mv4), res. 1024, um job por vez | Faltavam: `npc_worker_001` (sv, mv4), `veh_civilian_001` (t2q8, sv, mv4), `veh_industrial_001` (t2q8, sv, mv4). Container `assetforge-engine` ativo. |
| **Spark** (`henrylawrencecahill@192.168.1.252`) | `bash chain_city.sh assetforge-pixal3d:cuda121 spark 1536 <6 ativos>` (PID 1010572) | Os mesmos 6 ativos × 3 motores; t2q8 e mv4 pedem **1536** (resolução efetiva menor, ver §3); sv sempre **1024** | **Reiniciada do zero** às ~02:00 (CST da Spark) depois de duas falhas (ver §5). Nenhum resultado válido ainda. |

* O container GPU do AssetForge tem sempre o nome `assetforge-engine`; só existe um por máquina (lock `~/assetforge-engines/.lock`).
* Qwen (`vlm-gpu`) e TripoSR (`triposr-gpu`) seguem ativos na 4090, ociosos (~506 MiB de VRAM, ~2 GB de RAM): **não** foram suspensos nem interferiram. O run do Hank (`clonez-mesh`) na Spark continua **parado por decisão do dono** (cron inerte).
* Tempo restante estimado (não medido): 4090 ≈ 15–30 min; Spark ≈ 1–2 h.

### Como acompanhar e recuperar (cada máquina)

```
ssh -i ~/.ssh/id_ed25519_asc -o BatchMode=yes <usuário>@<ip> 'cat ~/assetforge-engines/chain_city.status; docker ps --format "{{.Names}}" | grep engine'
# linhas "<ativo>_<motor>_<res>_<máquina> EXIT=<código>"; "CITY_CHAIN_DONE" = terminou. Códigos: 0 ok · 3 lock ocupado (a cadeia repete) · 4 guarda de memória/Hank · 133/1/outro = falha (ver raw.log)
ssh ... 'tr "\r" "\n" < ~/assetforge-engines/out/<run>/raw.log | grep -v "\[flow\]" | tail -30'   # log de um run
bash scripts/engines/fetch_results.sh          # (PC do dono, Git Bash, raiz do repo) baixa todos os runs OK das duas máquinas -> reports_out/engines/results/<run>/
.venv/Scripts/python scripts/engines/analyze_city.py --results reports_out/engines/results --refs reports_out/engines/city_inputs --out reports_out/engines/analysis
```

Para parar uma cadeia com segurança: `pkill -f '^bash chain_city.sh'` (padrão ANCORADO; sem o `^` o pkill mata a própria sessão SSH) e `docker stop assetforge-engine`. Reiniciar: `cd ~/assetforge-engines && nohup bash chain_city.sh <imagem> <rótulo> <res> <ativos...> &` (pula o que já deu certo, repete em código 3).
Resultados antigos/falhos ficam em `~/assetforge-engines/old/`.

## 2. Ativos: processados e pendentes (lote CITY+++ piloto; 15 designs existem, **6 foram escolhidos** para esta bateria)

Escolhidos: `bldg_skyscraper_residential_001`, `bldg_skyscraper_commercial_001`, `npc_civilian_001`, `npc_worker_001`, `veh_civilian_001`, `veh_industrial_001`. **Não escolhidos (pendentes para uma 2ª fase)**: `bldg_skyscraper_residential_002`, `bldg_skyscraper_special_001`, `npc_civilian_002`, `npc_government_001`, `npc_public_service_001`, `npc_worker_002`, `veh_civilian_002`, `veh_emergency_001`, `veh_public_transport_001` (entradas já preparadas em `reports_out/engines/city_inputs/` e nas máquinas em `~/assetforge-engines/refs/city/`).
Também usada como referência extra: a torre `reports_out/engines/refs/tower.png` (imagem do dono; sem multi-view).

**RTX 4090 (res. 1024) — concluídos com sucesso (todos `exit=0`):** `bldg_skyscraper_residential_001` (t2q8, sv, mv4), `bldg_skyscraper_commercial_001` (t2q8, sv, mv4), `npc_civilian_001` (t2q8, sv, mv4), `npc_worker_001` (t2q8). Torre (imagem única): t2q8 1024, t2q8 "1536", sv 1024.
**Pendentes na 4090:** `npc_worker_001` sv e mv4, `veh_civilian_001` ×3, `veh_industrial_001` ×3. **Spark:** os 6 ativos × 3 motores (nada concluído).
**Ainda NÃO baixados/analisados localmente:** tudo depois de `bldg_skyscraper_residential_001` (rodar `fetch_results.sh` + `analyze_city.py`). Analisado e visto: só `bldg_skyscraper_residential_001` (folha em `reports_out/engines/analysis/sheets/`) e a torre.

## 3. Resoluções solicitadas × efetivamente usadas (lidas dos `raw.log`)

* **1024 (todos os runs da 4090)**: efetiva = **1024**, sem recuo (`backing off` = 0). Tokens HR por ativo: torre 31.965 (t2q8), residencial_001 23.079 (mv4).
* **"1536" da torre (TRELLIS.2 Q8, 4090, `--max-tokens` padrão 49.152): efetiva = 1152.** O limite recuou 1536 → 1408 → 1280 → 1152 (`res1536 -> 75244 tokens >= 49152, backing off`). **Não foi 1536.** (O "1536 funciona" dito antes estava errado e foi corrigido.)
* **1536 real não é alcançável neste commit**: com `--max-tokens 131072` o `trellis-cli` na Spark quantizou em `@res1536 (grid 96) = 63460 tokens` e **abortou** com `GGML_ASSERT(grid_z < USHRT_MAX)` em `thirdparty/ggml/src/ggml-cuda/cpy.cu:229` (código 133). Portanto **não subir `--max-tokens` acima de ~49 mil**; a resolução efetiva fica entre 1152 e 1280 conforme o ativo. Corrigir exigiria patch no ggml (kernel de cópia com `gridDim.z > 65535`) — **não feito**; reportar upstream/patch é uma pendência.
* **Pixal3D single-view: só `--res 1024`** (`--sv-image supports --res 1024 only in this release`). Pixal3D multi-view aceita 1024 e 1536 (e 512 não).
* **Regra**: sempre registrar a resolução efetiva por run (`grep -E "backing off|quantized @res" raw.log`); nunca reduzir em silêncio.

## 4. Pesos e commits exatos

* **Motor C++**: `raven38/pixal3d.cpp` commit **`d1b4926452f9e09702b891db5f05acc845e153ed`** (MIT); ggml vendorizado `pwilkin/ggml` commit **`737e88f25d4f62254f3b7a726fd9663036cc94da`** (branch `trellis-patches`, MIT); base `pwilkin/trellis.cpp` (MIT). Imagem: `deployment/Dockerfile.pixal3d-cuda` (Ubuntu 24.04, CUDA 13.1.0, `CUDA_ARCHS=89` na 4090 → tag `cuda89`; `121` na Spark → tag `cuda121`; `cuda120` da Spark NÃO serve).
* **Pesos GGUF** (em `~/assetforge-models/` das duas máquinas, ≈ 9,4 + 7,6 + 7,6 GB; baixados por `~/assetforge-engines/download_weights.sh`):
  * `trellis2-q8/` = HF `ilintar/trellis2-gguf` pasta `q8`, revisão **`a57397bd3d351599d9729fc144b3f87c3f87d65b`** (licença "other" = a do modelo-fonte MIT; contém `birefnet.gguf` e `dinov3.gguf`). SHA256 de `shape_flow_1024.gguf` = `997e9fc10ab95fda11c4cd1cbaf425101980ac36a2ef80e9c83e0b9c4bfc9680` (na 4090).
  * `pixal3d-mv-q8/` = HF `raven38/pixal3d-q8_0-v1`, revisão **`1c4f4bdddb5fef1dc5efa512d4b88e899b10bd91`** (MIT + `dinov3.gguf` sob a licença DINOv3). SHA256 de `pixal3d_shape_flow_1024_mv.gguf` = `50cd892247d73d4750b720d5612cef03cc0c02ec806b9e37d0d54d7ec579a94b`.
  * `pixal3d-sv-q8/` = HF `raven38/pixal3d-sv-q8_0-v1`, revisão **`46d399ac986f45a0d7f5b1ca5058614d8729a131`**. SHA256 de `pixal3d_shape_flow_1024_sv.gguf` = `7cb1ecb189719edbbb991d16271ad0f8ab8bf54154df7795830aadba27f0efae`.
  * `trellis2-q4/` (≈ 6,1 GB, mesma origem, pasta `q4`) baixado, **ainda não testado**.
  * Fonte dos modelos originais: `TencentARC/Pixal3D` (MIT) revisão `b0cb2e1b794cab9aa0ac38a95d794a4d9337437f`, código `TencentARC/Pixal3D` commit `f7cf38429b0bd264f1995f0f8743a88b1c728b94`; `microsoft/TRELLIS.2-4B` revisão `af44b45f2e35a493886929c6d786e563ec68364d` (MIT).
* **TRELLIS.2 Python (piloto 1, Spark)**: imagem do Hank `clonez-mesh:1`, pesos em `~/clonez-models` (PINS em `AssetPipeline/mesh/meshgen.py`; TRELLIS.2 commit `75fbf0183001ed9876c8dbb35de6b68552ee08bd`).
* **Repositório AssetForge** no momento desta escrita: branch `feat/engines-comparison` (= `docs/trellis2-analysis`, PR #1); ver `git log`.

## 5. Resultados de memória, tempo e qualidade (4090, res. 1024, atlas 4096, seed 1; RAM = pico do sistema acima da base; todos medidos)

| Ativo | Motor | Tempo | RAM Δ | VRAM pico | Triângulos (após decimação padrão) |
| --- | --- | --- | --- | --- | --- |
| bldg_skyscraper_residential_001 | t2q8 / sv / **mv4** | 160,0 / 149,1 / **219,0** s | 4,1 / 3,7 / 4,8 GB | 8,1 / 7,3 / 8,4 GB | 295.794 / 955.714 / 982.020 |
| bldg_skyscraper_commercial_001 | t2q8 / sv / **mv4** | 74,5 / 96,1 / **133,1** s | 2,2 / 2,0 / 2,2 GB | 5,1 / 4,7 / 5,3 GB | 282.142 / 983.554 / 974.768 |
| npc_civilian_001 | t2q8 / sv / **mv4** | 51,8 / 61,1 / **77,7** s | 2,5 / 1,3 / 1,8 GB | 3,0 / 3,9 / 3,9 GB | 282.968 / 889.856 / 990.614 |
| npc_worker_001 | t2q8 | 57,3 s | 3,0 GB | 3,9 GB | 297.618 |
| Torre (1 imagem) | t2q8 1024 / sv / t2q8 "1536"=1152 | 232,6 / 127,1 / 336,5 s | 6,6 / 3,1 / 7,9 GB | 12,0 / 7,2 / 14,6 GB | 297.650 / 931.734 / 293.090 |
| (ref.) Torre, TRELLIS.2 **Python** | Spark | ≈ 285 s + ~50 s de textura | 69–75 GB (sistema) | n/d | ≈ 453 mil |

* O C++ Q8 usa **uma ordem de grandeza menos memória** que o Python (≤ 15 GB de VRAM e ≤ 8 GB de RAM contra 69–75 GB) e cabe folgado na 4090 (24 GB VRAM / 22 GB RAM).
* Defaults de decimação: TRELLIS.2 ≈ 300 mil faces; Pixal3D ≈ 1 milhão (atlas 4096). Para "não limitar o master" no TRELLIS.2 usar `--decim 0` (não testado; pode gerar dezenas de milhões de faces).
* **Qualidade** (apenas `bldg_skyscraper_residential_001` e a torre foram vistos; impressão visual do assistente, NÃO aprovação):
  * **mv4 (Pixal3D multi-view, 4 vistas)**: melhor: reproduz a **traseira** com janelas, colunas verde-oliva, pilastras e varandas; de pé (inclinação 1,9°), 1 componente.
  * **t2q8**: boa frente; **traseira inventada e lisa**; sem verde-oliva; 1 componente (a torre tinha 19 em 1024).
  * **sv (Pixal3D single-view)**: na torre deu cor e detalhe excelentes mas **inclinado ~9,9°** (corrigível com `level_glb.py`); no `residential_001` **falhou** (modelo deitado, 88,6°, textura estragada). **Instável conforme a imagem.**
  * Cor: o Pixal3D (sv e mv4) fica muito mais perto da referência que o TRELLIS.2 Python/Q8 (que sai dourado/escuro).
* **Pendente de análise**: os demais ativos já gerados (rodar `fetch_results.sh` + `analyze_city.py`), contagem de componentes soltos, **estabilidade** (repetir 3× o mesmo motor/ativo; as repetições `tower_*_r2/_r3` da 4090 foram recusadas por lock e **não rodaram**; os diretórios `out/tower_t2q8_1024_r2_4090` e `_r3_4090` são lixo sem resultado), Gemini (só conselho, `scripts/ai/gemini_compare.py`) e aprovação visual do dono.

## 6. Problemas encontrados e soluções (lista completa desta fase)

1. CMake 3.22 falha em `FetchContent ... DOWNLOAD_EXTRACT_TIMESTAMP` → base **Ubuntu 24.04**.
2. Link `undefined reference to cuMemCreate...` → **stub libcuda** (`LIBRARY_PATH=/usr/local/cuda/lib64/stubs` + `-Wl,-rpath-link`).
3. `COPY /src/build/bin` inexistente → coletar `.so` com `find` para `/out`.
4. Spark é **sm_121**: build `120` dá `no kernel image is available` → usar `CUDA_ARCHS=121`.
5. `pkill -f 'docker build'` mata a própria sessão SSH → padrão ancorado `'^docker build'`.
6. `.sh` com CRLF quebra no Linux → `sed -i 's/\r$//'`; `.gitattributes` força LF.
7. Container como root deixa arquivos que não dá para apagar → `--user $(id -u):$(id -g)` (já no `run_cpp.sh`).
8. Substituir `run_cpp.sh` com ele em execução corrompe o bash → copiar para `.new` e `mv`.
9. Lock herdado (fd 9) pelo guarda recusava o job seguinte (código 3 em cascata) → `9>&-` no guarda e no `docker run`; cadeia repete em 3.
10. `tar czf C:\...` interpreta `C:` como host → usar caminho relativo.
11. Blender grava em `C:\` quando recebe caminho relativo → **sempre caminhos absolutos** (o dono deve apagar `C:\reports_out` e `C:\view_*.png` que sobraram).
12. Heredoc longo no shell quebra com aspas → escrever arquivos com a ferramenta de escrita e depois `cat >>`.
13. `--sv-image` só aceita `--res 1024`; `--max-tokens` alto → `GGML_ASSERT(grid_z < USHRT_MAX)` (ver §3).
14. Single-view instável (ver §5); `level_glb.py` não corrige modelo deitado (recusa acima de `--max-tilt 40`).

## 7. Política de utilização máxima SEGURA do hardware (sem limitações artificiais)

* **Sem tetos artificiais** de resolução, complexidade do master, VRAM ou RAM: usar a capacidade real de cada máquina (4090: os 24 GB de VRAM; Spark: até a memória unificada disponível). Não reduzir qualidade em silêncio: registrar sempre a resolução efetiva.
* **Segurança (não é limite de qualidade)**: (a) **um job pesado por máquina por vez** (lock `~/assetforge-engines/.lock`); (b) o guarda do `run_cpp.sh` para **só o nosso container** se a RAM disponível cair abaixo de `MIN_AVAIL_GB` (padrão 10 GB; na 4090 há 22 GB de RAM no total) ou se o run do Hank (`clonez-mesh`) voltar; (c) nunca encerrar/alterar processos de outros projetos; (d) Qwen e TripoSR ficam disponíveis enquanto não interferirem — se algum job deles disputar a GPU, **pedir autorização** antes de suspendê-los, preservando os dados; (e) sem mudar BIOS/firmware/driver/kernel sem autorização; (f) Spark: usar a conta do Hank só para ler código/pesos dele e para rodar os nossos containers em `~/assetforge-engines`.
* Meta: manter **ambas as máquinas trabalhando** quando houver demanda. O scheduler de produção (FIFO, compatibilidade, disponibilidade e consumo real) **ainda não existe**: ver §8.

## 8. Pendências (ordem sugerida; nada disto foi iniciado além do dito)

1. **Concluir as baterias atuais**, recuperar e analisar (§1), comparar por categoria (arranha-céus/NPCs/veículos) e levar ao dono para **aprovação visual**. Rodar Gemini (só conselho).
2. **Estabilidade**: 3 repetições do mesmo motor/ativo (mesma seed e seeds diferentes) em cada máquina.
3. **Pixal3D Python na Spark** (resolução nativa 1536, `inference.py`/`inference_mv.py`; base `clonez-mesh:1` + MoGe, natten, utils3d; usar `assetforge_trellis2.to_glb_commercial` no lugar do `to_glb` com nvdiffrast) — **não iniciado**; é o caminho para 1536 real sem o limite do ggml.
4. **Otimização não destrutiva e LODs** (15k/7,5k/2,5k/500) a partir dos masters ≈ 1M de triângulos do Pixal3D. Preservar o master. O colapso do Blender destrói masters feitos de cascas soltas (ver piloto 1); verificar componentes dos masters (os do Pixal3D deram 1 componente), testar decimação com preservação de arestas, normal map assado em Blender (`scripts/trellis2/bake_normals.py`), reprojeção de texturas, UVs e PBR, e comparar todos os LODs com as mesmas câmeras/luz.
5. **Cor/textura**: comparar base color com a referência (valores primeiro, depois iluminação/gerenciamento de cor do Blender) nos masters do Pixal3D.
6. **Licenciamento** (nenhum pipeline está liberado para uso comercial): DINOv3 (licença da Meta: uso comercial permitido com condições, sem usos militares/armas; **revisão jurídica pendente**; vem dentro dos GGUF); termos dos dados do BiRefNet; `plyfile` (GPL)/`easydict` (LGPL) na imagem do Hank se for redistribuída; confirmar licença dos pesos GGUF de terceiros (`raven38`, `ilintar`: o arquivo `LICENSE.md` do repositório diz "MIT + DINOv3"). O `pixal3d.cpp` **não usa nvdiffrast/nvdiffrec**; o caminho Python usa e foi substituído por `assetforge_trellis2`. Separar ativos experimentais dos produzidos por pipeline comercialmente compatível (`experimental/` × `commercial_candidate/`).
7. **Corrigir/reportar o limite do ggml** (`cpy.cu:229`) para habilitar 1536 real no C++ (patch ou issue upstream).
8. **Workers de produção** (Spark e 4090 ativos) com scheduler FIFO por compatibilidade/disponibilidade/consumo real, provider HTTP em container separado (como `triposr-gpu`), cancelamento/retomada, histórico de versões, upload em massa, painel com visualização interativa — **só depois** da aprovação do piloto. **Não iniciar produção comercial sem aprovação.**
9. Kits procedurais, Gemini + procedural e híbrido devem competir com as **mesmas** referências/câmeras/luz (ainda não rodados nesta fase); **não são obrigatórios**.
