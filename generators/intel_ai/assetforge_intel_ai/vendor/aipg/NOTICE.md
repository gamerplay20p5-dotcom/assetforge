# Origem dos arquivos vendorizados

`pixel3d-trellis.json` e `z-image.json` são cópias **sem modificação** de `modes/base/presets/` do projeto
[intel/AI-Playground](https://github.com/intel/AI-Playground) (licença MIT, arquivo `LICENSE` ao lado),
commit `1aa842352bebe454774c4c3840755451810ca8ab` (release v3.3.0 beta). Copyright © Intel Corporation.
Adaptações (remoção do nó SafetyChecker, normalização de caminhos, ajuste de resoluções) são feitas em tempo de execução
em `presets.py`/`provider.py`, nunca nestes arquivos. Para atualizar: `scripts/intel_ai/update_vendor.sh <commit>`.
