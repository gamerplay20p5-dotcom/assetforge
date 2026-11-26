# Direção de arte — Premium Stylized Low/Mid Poly

> As duas imagens de referência citadas no briefing **não chegaram à sessão de desenvolvimento** (só o texto foi recebido).
> Esta direção foi derivada da descrição escrita (kit urbano profissional estilizado; não o estilo simplificado demais).
> Revise os resultados visuais contra as imagens e ajuste paletas/detalhes (são dados, não código).

## Princípios implementados
* **Geometria estilizada com detalhe arquitetônico real**: paredes são painéis com *aberturas verdadeiras* (reveals), esquadrias
  com caixilho e travessas, peitoris, vergas, venezianas, portas com almofadas e vidro, degraus, marquises, varandas com guarda‑corpo,
  cornijas, faixas de pavimento, cunhais (estilo clássico), platibandas, chaminés, equipamentos de cobertura, torres d’água, heliponto.
* **Proporções urbanas**: pé‑direito, largura de módulo (bay), janelas e portas em escala humana (porta 2,2 m; peitoril 0,9 m);
  1 unidade = 1 m.
* **Materiais bem definidos e poucos**: ~13–17 materiais por prédio (wall, brick, trim, base, roof, metal, glass/lit, curtain,
  door, awning…). Texturas **tileáveis neutras** (reboco, tijolo, telha, concreto, vidro, madeira, metal, pedra, tecido) geradas por
  código; a cor vem do fator de cor do material (sRGB→linear), então uma textura serve a todas as paletas.
* **Cores harmoniosas**: 15 paletas escritas à mão (3 por estilo: modern, classic, mediterranean, nordic, industrial) com
  parede/acabamento/base/telhado/acento/porta; “conservação” (0–1) escurece e dessatura.
* **Variedade controlada por seed**: dimensões, andares, telhado (gable/hip/flat/sawtooth), garagem, varandas, janelas acesas/
  cortinas, equipamentos — tudo determinístico.
* **Otimização para instâncias**: orçamentos por categoria (ver contrato), poucos materiais por asset, malha *flat‑shaded* sem
  vértices duplicados, UV em escala métrica (densidade de texel consistente).
* **Perfis**: `Premium Stylized` (id `premium-stylized-v1`) é salvo no banco (`/api/v1/art-profiles`) e referenciado no manifesto.
  Novos perfis (paletas/estilos/densidade) podem ser salvos e reutilizados; o Generator já salva/carrega **presets** de configuração.

## Limitações atuais (honestas)
* Sem LODs, normal maps ou AO bakeado; sem *trim sheets* atlas (usa texturas tileáveis por material).
* Personagens, veículos, vegetação e infraestrutura ainda não existem (Milestones 2–4).
* Indústria/armazém/quartel/estação são mais simples que casas/prédios (abaixo da faixa de triângulos).
* A miniatura sem Blender usa cor plana (sem textura); com Blender é renderizada com Cycles.
* Fachadas não usam ainda uma biblioteca de módulos intercambiáveis por face (planejado: parâmetros por face para o planner).
