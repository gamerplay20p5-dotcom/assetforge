# Implantação em uma única máquina (Docker)

**Alvo imediato:** tudo no **nó 206** (Intel Arc A750 8 GB), validando a geração 3D em UMA placa antes de expandir.
Nenhum endereço de rede é fixado no código ou nos arquivos de implantação.

> **Nada aqui foi executado.** Os Dockerfiles/Compose foram escritos e verificados estaticamente (YAML, sintaxe de shell e testes de
> política em `tests/unit/test_deployment_files.py`), mas **nunca construídos nem iniciados**: o ambiente de desenvolvimento não tem
> Docker nem Intel Arc, e **nenhuma ação remota foi feita** (o acesso SSH à 206 deu timeout). A compatibilidade com a A750 **não está
> validada** até o passo 4 abaixo rodar de verdade.

## Visão

```
                     ┌──────────────────────── máquina única (Docker Compose, projeto "assetforge") ───────────────────────┐
 navegador ─8000──▶  │ api (API + dashboard + scheduler)  ──▶ postgres (perfil standalone)  OU  PostgreSQL externo (ex.: 212) │
                     │   ▲ worker-cpu  (procedural + Blender headless)                                                      │
                     │   ▲ worker-gpu  (híbrido, 1 job por vez) ──http──▶ comfyui (PyTorch XPU, workflows da Intel)           │
                     │ volumes: assets · ai-models · pgdata · estado dos workers · outputs do ComfyUI                       │
                     └ GPU: /dev/dri (sem privileged, sem CUDA) · só a porta da API é publicada ────────────────────────────┘
```
Continua sendo a arquitetura distribuída: a API/fila não sabem quantos workers existem. Para crescer, registre outro worker (outra
máquina, ex.: a 201, ou mais containers) — veja “Expansão”. **Nada exige mais de um servidor.**

## Perfis
| Perfil | Banco | Como |
|---|---|---|
| **Standalone** | PostgreSQL local em Docker | `./scripts/install_single_node.sh standalone` |
| **External Database** | PostgreSQL em outro servidor, banco+usuário **exclusivos** | `./scripts/install_single_node.sh external-db` |
Ambos aceitam `--no-ai` (só CPU: sem ComfyUI nem worker Intel). O perfil é o `COMPOSE_PROFILES` do `.env`
(`standalone,ai` / `external-db,ai`). Modelos de `.env`: `deployment/standalone.env.example`, `deployment/external-db.env.example`.

## Situação real da 206 (diagnóstico de 2026‑11‑26)
Docker 29.8.1/Compose v5.5.1 presentes; GPU A750 com `i915`; render gid **993**, video gid 44; portas 8000/5432 livres; workers do Stream Clipper **não usam** `/dev/dri`.
**Estado após a instalação (2026‑11‑26):** serviços CPU rodando na 206 (postgres, api, worker-cpu; painel na porta 8000); **IA bloqueada: Resizable BAR desativado → driver Intel não inicializa a A750** (medido; veja HARDWARE_COMPATIBILITY.md). O ReBAR passa de recomendado a **obrigatório**.
**Bloqueios a resolver pelo Hank:** (1) quem executar o `install_single_node.sh` precisa de **acesso ao Docker** (o usuário `asc` não tem); (2) *opcional, recomendado*: ativar **Resizable BAR** no BIOS (hoje a janela é de 256 MB).
Use um projeto Compose próprio (`assetforge`) — **nunca** o `asc-ctl compose up/down` do Stream Clipper.

## 0. Pré‑requisitos (somente verifique; mudanças de root são do administrador)
* Ubuntu com **Docker + Compose v2**, `openssl`, `git`; GPU Intel com `/dev/dri/renderD*` e driver do kernel (`i915`/`xe`) já carregado.
* Rode antes, só leitura: `bash scripts/intel_ai/diagnose_node.sh` (cola o `diagnostico_<host>.txt` na conversa). Se faltar driver do host, **não** é
  instalado por nenhum script daqui — o administrador decide.
* O usuário que roda o Compose precisa poder usar Docker. Os containers usam os **gids dos grupos `render`/`video` do host** (detectados pelo instalador).

## 1. Banco externo (só no perfil External Database)
No servidor de banco, **quem o administra** executa uma vez `scripts/db/create_assetforge_db.sql` (cria role e banco exclusivos; não toca
em outros). Depois, no `.env` da máquina do AssetForge: `ASSETFORGE_DATABASE_URL=postgresql://assetforge:SENHA@<host-do-banco>:5432/assetforge`.

## 2. Subir
```bash
git clone https://github.com/gamerplay20p5-dotcom/assetforge.git && cd assetforge
./scripts/install_single_node.sh standalone          # ou external-db ; adicione --no-start para só preparar/validar o .env
```
O instalador: gera `.env` (600) com segredos, **tokens de registro dos workers** (criados na subida da API — sem passo manual no painel), detecta os gids
da GPU, valida `docker compose config` e executa `up -d --build`. A senha inicial do admin é impressa uma vez. Health checks: API
`/api/v1/health/ready`, Postgres `pg_isready`, ComfyUI `/system_stats`, workers por processo; os workers só iniciam com API (e ComfyUI) saudáveis.
O build da imagem do ComfyUI baixa vários GB (torch XPU); a primeira subida demora.

## 3. Liberar VRAM (se necessário)
Pelo seu guia, a Arc da 206 **não tem worker de visão**; em tese não há o que suspender. Se `diagnose_node.sh` mostrar processos usando `/dev/dri`, o
Stream Clipper pode ser suspenso **por você**, de forma que preserve os dados: `sudo -n /usr/local/sbin/asc-ctl compose stop …` (somente `stop`, **nunca**
`compose up/down`, `--remove-orphans` ou remover volumes). Este projeto não faz isso por conta própria. Retome depois pelo mesmo caminho do Hank.

## 4. Validar a IA de verdade (nenhuma IA é oferecida antes disso)
```bash
./scripts/intel_ai/docker_tasks.sh comfy-check          # torch XPU enxerga a A750? (não gera nada)
./scripts/intel_ai/docker_tasks.sh models-list          # tamanhos e licenças
./scripts/intel_ai/docker_tasks.sh models-download      # confirma licenças; SHA-256 conferido; ~dezenas de GB
./scripts/intel_ai/docker_tasks.sh validate --repeat 3  # texto→imagem→3D reais, 3 vezes: tempo, pico VRAM/RAM/temperatura, estabilidade, LODs, FBX
docker compose --env-file .env -f deployment/docker-compose.yml restart worker-gpu    # só se VALIDADO
./scripts/intel_ai/docker_tasks.sh benchmark ./minhas_referencias stylized_standard prototype   # SUAS imagens → folha “referência | IA”
./scripts/intel_ai/docker_tasks.sh export-reports       # relatórios/benchmarks para ./reports_out (cole aqui)
```
O `validate` só grava `ai_validated.json` (que libera `ai.*`) se TODAS as execuções passarem com GLB texturizado, LODs e FBX; falha grava o relatório e **não libera nada**.
**Pixal3D em 8 GB**: o preset da Intel é `high-vram`. Se falhar por memória, ajuste no `.env` e repita o `validate`: `COMFY_MEMORY_ARGS=--novram` (offload para RAM; a máquina
tem muita), `COMFY_RESERVE_VRAM`, perfil `prototype`, textura menor. Se ainda assim não couber, o plano é investigar alternativas (CPU/híbrido) — **sem declarar compatibilidade**.

## 5. Limites, monitoramento e coexistência
* **Limites**: `.env` (`CPU_WORKER_*`, `GPU_WORKER_*`, `COMFY_DOCKER_*`, `ASSETFORGE_*_MEM/CPUS`) aplicados pelo Docker **e** pela reserva lógica do scheduler (editável no painel → Workers).
* **Monitoramento** (painel Dashboard/Workers): CPU, RAM, temperatura (hwmon, quando exposta), VRAM total/usada **medida pelo ComfyUI**; utilização da GPU Intel e temperatura da GPU
  podem não estar disponíveis sem `xpu-smi` (aparecem como “não medida”, nunca inventadas). `validate` registra picos de VRAM/RAM/temperatura.
* **Offload para RAM**: `COMFY_MEMORY_ARGS` (`--lowvram`/`--novram`); `comfyui` tem teto de RAM alto (`COMFY_DOCKER_MEM`) para isso.
* **Idle/ceder a outros serviços**: `ASSETFORGE_WORKER_ACTIVE_HOURS`, `…_MAX_HOST_CPU_PERCENT`, `…_YIELD_TO`.
* **Filas persistentes**: no banco (sobrevivem a reinício); jobs órfãos voltam à fila após o lease.

## 6. Backup e recuperação
`./scripts/backup.sh [--with-models]` → `backups/<data>/` com dump do banco (local **ou** externo, só leitura), volume de assets, estado dos workers, `.env` (cópia 600) e SHA256SUMS; mantém 14.
`./scripts/restore.sh backups/<data>` (pede confirmação). No banco externo restaura **somente** o banco dedicado do AssetForge. Modelos não entram por padrão (baixáveis de novo, verificados por SHA‑256).
Atualizar: `git pull && ./scripts/update.sh` (faz backup antes; **sem Alembic ainda** — leia o changelog).
Falhas: API/Postgres reiniciam sozinhos (`restart: unless-stopped`); worker perdido → lease expira → job volta à fila (até 3 tentativas); disco cheio → `health/ready` 503.

## 7. Expansão futura (sem mudar a arquitetura)
* **Mais workers na mesma máquina**: duplique o serviço `worker-cpu` (nome e volume de estado próprios) e gere outro token em Workers → *Novo token*.
* **Outra máquina (ex.: a 201)**: `deployment/docker-compose.worker-cpu.yml` (+ `docker-compose.worker-intel.yml`) apontando `ASSETFORGE_SERVER_URL` para a API da 206; mesmo gate de validação (rode
  `diagnose_node.sh`/`validate` lá antes). Não instalar nada em outras máquinas sem sua autorização.
* Os arquivos `docker-compose.central.yml` e `docker-compose.worker-*.yml` são o modo **multi‑servidor** (legado, igualmente não testado).

## Checklist de aceitação (na 206)
1 `install_single_node.sh` ok e `health/ready` 200 · 2 workers `…-cpu` e `…-gpu` online no painel · 3 job procedural gera GLB · 4 `comfy-check` mostra `xpu: True` · 5 `validate --repeat 3` VALIDADO ·
6 job de IA pelo painel (texto e imagem) conclui · 7 `backup.sh` + `restore.sh` em ambiente de teste · 8 reiniciar `api` durante um lote e ver recuperação.
