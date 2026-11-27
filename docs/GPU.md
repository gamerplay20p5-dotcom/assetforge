# Caixa só-GPU (a 203, RTX 4090) + nó principal (a 206)

**Regra do usuário:** a 203 fornece **só GPU**. API, banco, Blender, CPU e RAM pesada ficam na 206. A 203 roda apenas serviços de inferência, com poucos núcleos e pouca RAM.
A 252 (NVIDIA Spark) ainda NÃO é usada: sem acesso e sem mudanças até o usuário liberar.

## O que roda na 203 (Docker, sem compose: `scripts/vlm/gpu_box.sh`)
| Serviço | Porta | O que faz | Auth |
|---|---|---|---|
| `vlm-gpu` | 8081 | Qwen2.5-VL 7B (bf16) lê a imagem e devolve a descrição | token (`VLM_TOKEN`) |
| `triposr-gpu` | 8082 | TripoSR (image-to-3D) em CUDA | o mesmo token |
Ambos com `--cap-drop ALL`, limites de CPU/RAM e `/health` aberto (o resto exige `Authorization: Bearer`). A 206 usa **GPU primeiro e CPU como reserva**
(`ASSETFORGE_VLM_URL=gpu,cpu` e `ASSETFORGE_CPU3D_PROVIDERS=triposr=gpu|cpu`).

## Medido (mesmas imagens)
| | CPU da 206 | GPU da 203 |
|---|---|---|
| Qwen2.5-VL 7B, análise de uma casa | ~250 s | **~3,7 s** (65x) |
| Qwen, RAM no host | 32 GB | ~4 GB |
| TripoSR, job completo (cadeira, perfil padrão) | 104 s | 60 s |
| TripoSR, job completo (perfil detalhado) | ~126 s | 67 s |
Onde vai o tempo do TripoSR na GPU (cadeira, malha 320, textura 1024): carregar o modelo 5,8 s, rodar o modelo 0,35 s, extrair a malha 2,1 s, **assar a textura 38,8 s (CPU, OpenGL por software)**,
exportar 0,7 s. A GPU já não é o gargalo; o próximo ganho vem de tirar o assamento da textura da CPU ou mantê-lo fora do caminho (ex.: cor por vértice e assar no Blender), e de manter o modelo
carregado entre jobs em vez de reiniciar o processo a cada job.

## Limites conhecidos
* A 4090 tem 24 GB e é dividida entre os dois serviços: o Qwen usa ~17,8 GB enquanto carregado, por isso se descarrega 20 s após cada análise e devolve a VRAM (`empty_cache`).
  Se um job do TripoSR cair exatamente durante uma análise, falta VRAM, a tentativa falha e a nova tentativa (10 s depois) passa (medido: 108 s em vez de 67 s).
* A 203 tem 22 GB de RAM (o container do Qwen usa ~4 GB, o do TripoSR ~4,4 GB).
* O TripoSR continua sendo ruim para casas e prédios; serve para objetos isolados em fundo liso. Para casas o caminho é Imagem → casa (Qwen + kit).
* Bug do TripoSR corrigido na imagem GPU: o assamento de textura criava as posições na CPU com o modelo na GPU (`cuda:0 and cpu`).
