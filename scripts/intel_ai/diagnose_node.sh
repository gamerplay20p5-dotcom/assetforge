#!/usr/bin/env bash
# Diagnóstico SOMENTE LEITURA de um node Ubuntu com Intel Arc para o AssetForge. Não instala, não altera nada, não usa sudo
# (só lista o que o sudo permitiria, sem executar). Saída: texto no terminal + arquivo diagnostico_<host>.txt na pasta atual.
#   bash scripts/intel_ai/diagnose_node.sh
# Cole o conteúdo do arquivo gerado de volta na conversa.
set -u
OUT="diagnostico_$(hostname).txt"
{
echo "== host"; hostname; . /etc/os-release; echo "$PRETTY_NAME"; uname -r; date -Is
echo "== cpu/ram/disco"; lscpu | grep -E "Model name|^CPU\(s\)"; free -m | head -2; df -h / "$HOME" | tail -2
echo "== usuario/grupos (precisa de 'render' para usar a GPU)"; id
echo "== /dev/dri"; ls -l /dev/dri 2>&1
echo "== GPUs (PCI)"; lspci -nn 2>/dev/null | grep -i -E "vga|display|3d"
echo "== driver do kernel"; lsmod | grep -E "^(i915|xe) " || echo "nem i915 nem xe carregados"
echo "== VRAM/ReBAR (sysfs)"
for c in /sys/class/drm/card[0-9]; do
  [ -r "$c/device/vendor" ] && [ "$(cat $c/device/vendor)" = "0x8086" ] && {
    echo "$c device=$(cat $c/device/device) "; ls $c/device 2>/dev/null | grep -E "lmem|mem_info" ; }
done
lspci -vv -d 8086: 2>/dev/null | grep -E "VGA|Display|Region [0-9].*Memory.*size|Resizable BAR|BAR [0-9]: current size" | head -12
echo "== Level Zero / OpenCL instalados"
ldconfig -p | grep -E "libze_loader|libze_intel_gpu|libigdrcl" | head
dpkg -l 2>/dev/null | grep -E "level-zero|libze|intel-opencl|intel-level|xpu-smi|libigc|intel-gsc" | awk '{print $2, $3}'
echo "== xpu-smi (se existir)"; command -v xpu-smi >/dev/null && xpu-smi discovery 2>&1 | head -20 || echo "xpu-smi ausente"
echo "== ferramentas"
for t in git python3 uv curl gcc docker; do printf "%s: " "$t"; command -v "$t" || echo ausente; done; python3 --version
echo "== processos que usam a GPU agora (outros serviços!)"
for f in /dev/dri/renderD*; do [ -e "$f" ] && (fuser -v "$f" 2>&1 || true); done
command -v intel_gpu_top >/dev/null && echo "intel_gpu_top disponível" || echo "intel_gpu_top ausente"
echo "== docker: containers em execução (somente listagem)"
(docker ps --format '{{.Names}}\t{{.Status}}' 2>&1 || sudo -n /usr/local/sbin/asc-ctl status 2>&1) | head -20
echo "== sudo permitido (somente listagem)"; sudo -n -l 2>&1 | head -8
} 2>&1 | tee "$OUT"
echo; echo "Relatório salvo em $PWD/$OUT"
