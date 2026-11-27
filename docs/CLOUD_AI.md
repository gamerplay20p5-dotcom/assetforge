# IA na nuvem (Gemini / Grok) — agente de modelagem procedural

O AssetForge pode usar um modelo de visão **na nuvem** como "arquiteto": ele lê as imagens de referência, escreve a especificação completa do
prédio (HouseSpec) num JSON com schema fixo, o kit procedural monta o modelo em Blender, renderiza vistas, e a IA compara os renders com as
referências e devolve a especificação corrigida. O loop repete até a nota alvo ou o limite de rodadas. A melhor especificação é exportada pelo
pipeline normal (mesma validação, texturas, LOD, pacote).

```
referências ─▶ IA: especificação ─▶ validador ─▶ kit + Blender ─▶ renders ─▶ IA: nota + problemas + spec corrigida ─┐
                     ▲   (erro de validação volta para a IA)                                                          │
                     └────────────────────────────── até nota ≥ alvo ou limite de rodadas ◀─────────────────────────────┘
```

**Nada que o modelo devolve é executado.** Ele só preenche campos do schema (`assetforge_vision/llm_spec.py`), que são convertidos e validados
por `HouseSpec.from_dict` antes de virar geometria.

## Onde roda

| Peça | Onde |
| --- | --- |
| Chaves, pool de chaves, cache, histórico, limites | API central (206), tabelas `ai_keys`, `ai_requests`, `ai_cache` |
| Loop do agente (montar, renderizar, exportar) | worker com Blender (206), job `agent.building` |
| Chamada à IA | o worker chama `POST /api/v1/worker/jobs/{id}/ai` com o lease do job; **o worker nunca vê a chave** |
| 4090 (203) | continua para geração 3D (TripoSR) e para o Qwen local, que fica como opção |

## Chaves de API

* Cadastre em **IA na nuvem** no painel (apenas admin). A chave é testada (lista de modelos) **antes** de ser salva; chave que não funciona não
  é guardada.
* Fica **criptografada** no banco (Fernet, derivada de `ASSETFORGE_SECRET_KEY`). Nunca volta para o navegador, não aparece em logs, histórico
  nem no GitHub; o painel mostra só os 4 últimos caracteres. Se o `ASSETFORGE_SECRET_KEY` mudar, as chaves salvas ficam ilegíveis e são
  desativadas: cadastre de novo.
* **Várias chaves**: a lista tem ordem. O sistema usa a primeira disponível; quando ela recebe *429* (cota), é recusada (401/403) ou falha, ele
  passa para a próxima na hora. A chave em cota entra em espera:
  * cota por minuto → espera o `retryDelay` que o Google informa;
  * cota diária (Gemini) → espera até a meia-noite do horário do Pacífico, quando o Google renova.
* Limites próprios por chave (**por minuto** e **por dia**) contados no histórico; com 0 = sem limite próprio.
* Se **todas** as chaves estão no limite, o job volta para a fila com `not_before` = quando a primeira renovar, **sem gastar tentativa**, e
  retoma sozinho (esperas curtas, até 90 s, acontecem dentro do próprio job).

### Gemini (Google)

* SDK oficial `google-genai` com *Structured Outputs* (`response_mime_type=application/json` + `response_json_schema`).
* Crie a chave em <https://aistudio.google.com/> → *Get API key*. Projeto **sem faturamento** = nível gratuito.
* Modelo: o painel lista os modelos da sua chave e sugere, nesta ordem, `gemini-3.8-flash`, `gemini-3-flash`, `gemini-2.5-flash`… — só o que a
  chave realmente lista. (A existência do `gemini-3.8-flash` não foi verificada sem uma chave; se não aparecer, o melhor disponível é escolhido.)
* **Aviso:** imagens enviadas ao nível gratuito da API Gemini **podem ser usadas pelo Google para melhorar seus produtos**. Não envie imagens
  confidenciais.

### Grok (xAI)

* API compatível com OpenAI (`https://api.x.ai/v1`, *chat completions* com imagem e `json_schema`).
* **Não tem nível gratuito.** Com o **modo exclusivamente gratuito** ligado (padrão), uma chave Grok só é usada se você marcar
  "permitir uso pago" nela. Nada migra para pago sozinho.

## Usar

1. **IA na nuvem** → adicionar chave → *Testar e listar modelos* → escolher o modelo → salvar.
2. **Imagem → 3D** → aba **IA na nuvem** → enviar ou colar (Ctrl+V) de 1 a 4 vistas do **mesmo** prédio → tipo, rodadas, nota alvo,
   acabamento, estado de obra → *Gerar com o agente*.
3. No resultado, o painel da direita mostra as **rodadas do agente**: nota, problemas apontados e os renders de cada rodada
   (`agent/history.json` e `agent/iterN/*.png` vão junto no asset).

Custo por modelo: 1 pedido para a especificação + 1 por rodada (+1 se o validador recusar e a IA precisar corrigir). Respostas idênticas
(mesmas imagens, prompt, versão do prompt e modelo) vêm do **cache** sem gastar cota.

## Endpoints

| Método | Caminho | Quem |
| --- | --- | --- |
| GET/PUT | `/api/v1/ai/settings` | ver: viewer · alterar: admin (modo gratuito, rodadas padrão, nota alvo) |
| GET/POST | `/api/v1/ai/keys` | admin (lista mascarada · cadastrar, testando antes) |
| PATCH/DELETE | `/api/v1/ai/keys/{id}` | admin (ordem, limites, ativar, permitir pago, liberar espera) |
| POST | `/api/v1/ai/keys/{id}/test`, `/api/v1/ai/models` | admin (testar chave salva · testar chave nova) |
| GET | `/api/v1/ai/status`, `/ai/usage`, `/ai/requests` | viewer (disponibilidade, tokens, histórico — nunca a chave) |
| POST | `/api/v1/worker/jobs/{id}/ai` | worker com o lease de um job `agent.building` |

## Benchmark

`scripts/ai/benchmark_cloud.py` gera, para cada referência, a folha lado a lado **referência | kit escrito à mão | Qwen 7B | agente na nuvem**
(mesma câmera) e um `results.json` com notas, tokens e tempo. A chave vem só da variável de ambiente (`GEMINI_API_KEY` / `XAI_API_KEY`).

```powershell
$env:GEMINI_API_KEY = "<sua chave>"   # só nesta janela
.venv\Scripts\python scripts\ai\benchmark_cloud.py --out reports_out\cloud_bench --iterations 2 --judge `
  --case ref01=C:\caminho\ref01.png:ref01 --case torre=C:\caminho\torre.png:ref_tower `
  --qwen-json reports_out\vlm\Qwen2.5-VL-7B-Instruct.json
```

As notas são a opinião do próprio modelo (ele se avalia). **O que decide é a folha visual**; JSON válido não conta como qualidade.

## Testes

`tests/integration/test_cloud_ai.py` sobe servidores locais que falam o protocolo REST do Gemini e do xAI e exercita o SDK oficial de verdade:
teste antes de salvar, criptografia, chave nunca devolvida, fail-over na cota, cota diária até a meia-noite do Pacífico, limite por minuto, cache,
modo gratuito bloqueando o Grok, chave recusada, regras do proxy (lease, tipo de job, imagens). `tests/integration/test_agent_pipeline.py` roda o
loop completo com uma IA roteirizada e Blender de verdade.
