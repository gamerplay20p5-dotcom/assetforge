# Implantação manual (sem SSH do desenvolvedor)

> Os Dockerfiles e Composes foram escritos com cuidado mas **não foram executados** no ambiente de desenvolvimento
> (sem Docker). Faça a primeira implantação em um nó de teste. Nada aqui altera serviços, drivers ou containers existentes:
> tudo vive em projetos Compose próprios (`assetforge-central`, `assetforge-worker-*`) e em arquivos dentro da pasta do repositório.

## Pré‑requisitos
Linux com Docker + Compose v2, `openssl`, `git`. Rede entre workers e o servidor central (porta da API, padrão 8000).
Nenhum IP é fixado no código: use `ASSETFORGE_SERVER_URL` (DNS ou IP da sua rede).

## 1. Servidor central
```bash
git clone <repo> assetforge && cd assetforge
./scripts/install.sh central        # cria .env com segredos gerados (mostra a senha admin) e sobe postgres + api
curl -fsS http://localhost:8000/api/v1/health/ready
```
* Banco **não** é publicado. A API publica `${ASSETFORGE_BIND}:${ASSETFORGE_PORT}`; fora de rede confiável coloque um proxy TLS
  (nginx/Caddy) à frente (SSE precisa de `proxy_buffering off`).
* Entre no painel, troque a senha (`POST /api/v1/auth/users` para criar usuários; senha do admin só via recriação por ora).

## 2. Workers
No painel: **Workers → Novo token de registro** (uso único, 24 h). No servidor do worker:
```bash
git clone <repo> assetforge && cd assetforge
./scripts/install.sh worker-cpu     # cria .env.worker; edite: SERVER_URL, WORKER_NAME, ENROLLMENT_TOKEN, limites
./scripts/install.sh worker-cpu     # sobe o worker
```
Após o primeiro registro o token fica em `/state/worker.json` (volume); o `ASSETFORGE_ENROLLMENT_TOKEN` não é mais necessário.
Intel (híbrido): `./scripts/install.sh worker-intel` (acrescenta `/dev/dri` e `group_add: render`; **sem `privileged`**).
Os workers de IA (OpenVINO) chegam no Milestone 2; hoje um worker `hybrid` roda jobs de CPU e *publica* a GPU detectada.

### Não prejudicar outros serviços (ex.: AI Stream Clipper)
Configure no `.env.worker`:
```
ASSETFORGE_WORKER_ACTIVE_HOURS=22:00-07:00        # só inicia jobs à noite
ASSETFORGE_WORKER_MAX_HOST_CPU_PERCENT=40         # não inicia se o host passa de 40% de CPU (média)
ASSETFORGE_WORKER_YIELD_TO=ai-stream-clipper      # não inicia enquanto esse processo rodar
ASSETFORGE_WORKER_CPU_CORES=4  ASSETFORGE_WORKER_RAM_MB=6144   # reserva lógica
ASSETFORGE_WORKER_DOCKER_CPUS=4 ASSETFORGE_WORKER_DOCKER_MEM=6g # teto rígido do Docker
```
`YIELD_TO` dentro de container só vê processos do host se você ativar `pid: host` (linha comentada no compose). O painel mostra
“Despacho em espera neste node: <motivo>” quando o portão está fechado, e os limites podem ser alterados em **Workers →
Limites** sem reiniciar. O worker roda com prioridade reduzida.

### Worker com IA (Intel Arc) — opcional, só após validar
Veja o procedimento completo em [INTEL_AI.md §5](INTEL_AI.md) (`scripts/intel_ai/*`). Resumo: ComfyUI headless em loopback no node,
`validate_node.py` (execução real), e então `ASSETFORGE_COMFYUI_URL`/`ASSETFORGE_AI_MODELS_DIR` no worker. Nada disso é instalado pelo `install.sh`.

## 3. Diagnóstico e benchmark (antes de definir limites)
```bash
python3 scripts/diagnose_hardware.py            # CPU/RAM/GPU Intel/Blender/OpenVINO detectados
python3 scripts/benchmark.py --count 14 --json bench.json      # mede de verdade neste nó
python3 scripts/validate_intel_gpu.py           # (nó Intel) enumera dispositivos OpenVINO — não valida modelos
```

## 4. Atualização
`./scripts/update.sh central` (faz backup antes) · `./scripts/update.sh worker-cpu`. **Atenção:** o esquema é criado por
`create_all`; mudanças de esquema entre versões exigirão migrações (Alembic — pendente). Leia o changelog antes de atualizar.

## 5. Backup e recuperação
* `./scripts/backup.sh` → `backups/<data>/{assetforge.dump,assets.tar.gz,SHA256SUMS}` (mantém 14). Agende no `cron` do servidor.
* Restaurar: `./scripts/restore.sh backups/<data>` (confirma digitando `restore`; para a API, recria o banco, restaura assets).
* **Queda do servidor central**: o worker continua o job atual e tenta enviar/concluir por alguns segundos (backoff curto);
  se o servidor ficar fora por mais tempo o resultado é descartado e o job será refeito. Ao voltar, a API espera `lease_seconds`
  (60 s) antes de abandonar jobs, para dar tempo aos heartbeats dos workers vivos. **Queda de um worker**: o lease expira e o job volta à fila
  (até 3 tentativas; histórico no painel). **Disco cheio**: `/api/v1/health/ready` fica 503 se o storage não for gravável.
* Segredos: só em `.env`/`.env.worker` (permissão 600), nunca no repositório.

## 6. Checklist de aceitação do Milestone 1 no servidor
1. `docker compose … up` ok e `health/ready` 200. 2. Worker aparece online com Blender detectado. 3. Criar job no painel.
4. Blender processa. 5. Edifício gerado. 6. GLB válido (aba Validação). 7. Miniatura. 8. Asset na biblioteca. 9. Viewer 3D.
10. Download. 11. Lote de 10 variações. 12. Reiniciar `api` durante o lote e ver a recuperação. 13. Forçar falha e ler logs.
