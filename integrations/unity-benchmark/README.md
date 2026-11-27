# Benchmarks AssetForge para Unity

Projeto isolado com Unity 6000.0.65f1 e URP 17.0.4. O editor importa três pacotes de teste e cria a cena de benchmark, os prefabs, as colisões e os LODGroups. O player faz uma passagem de câmera fixa por cenário e grava métricas por frame.

Use `scripts/engines/prepare_game.py` em Blender Docker para criar os pacotes `building`, `npc` e `vehicle` em um diretório comum. Passe a altura real em metros, a correção de orientação e as proporções de LOD a ensaiar. O LOD0 usa razão 1. A importação e a exportação do Blender podem alterar a contagem de faces. Compare cada proporção com a mesma matéria-prima, versões e qualidade gráfica.

```bash
bash integrations/unity-benchmark/run_docker.sh build /path/packages /path/results
bash integrations/unity-benchmark/run_docker.sh run /path/packages /path/results
python integrations/unity-benchmark/summarize.py /path/results/results
```

O build requer uma imagem do Editor com Linux Build Support e licença ativa provisionada por operação. Informe a imagem em `UNITY_EDITOR_IMAGE`. O player requer uma imagem de runtime com Vulkan e X11, indicada em `UNITY_PLAYER_IMAGE`, e um display acelerado com `DISPLAY` e `XAUTHORITY`. O editor pode compilar com `-nographics`. O player mede os frames com o dispositivo gráfico ativo.

O CSV inclui frame time, draw calls, triângulos submetidos ao renderizador, memória usada e mudanças de LOD entre níveis visíveis consecutivos, com fade desligado. As colunas de contador permanecem vazias se o player não os expuser. O resumo inclui FPS médio e percentis de frame time. Para definir orçamentos por categoria, compare p95 e cobertura dos LODs com a referência de desempenho e o hardware-alvo do CITY+++.

Referências [ProfilerRecorder](https://docs.unity3d.com/6000.0/Documentation/ScriptReference/Unity.Profiling.ProfilerRecorder.html) · [Contadores da Unity](https://docs.unity3d.com/6000.0/Documentation/Manual/ProfilerRendering.html)
