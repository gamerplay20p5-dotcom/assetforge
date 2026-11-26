# Licenças de modelos e dependências

> Modelos da integração com o Intel AI Playground (Pixal3D, TRELLIS.2, MoGe, BiRefNet, DINOv3, Z‑Image‑Turbo) e o parecer de uso comercial no Brasil: **[INTEL_AI.md §4](INTEL_AI.md)**. Atenção a DINOv3 (licença Meta) e à origem do `ae.safetensors`.

Verificado em **2026‑11‑26** diretamente nas fontes (arquivos `LICENSE` no GitHub e metadados da API do Hugging Face).
Antes de integrar qualquer modelo no Milestone 2, reconferir o texto vigente e registrar aqui. Isto não é parecer jurídico.

| Modelo | Código | Pesos | Uso comercial | Restrições / observações |
|---|---|---|---|---|
| **TripoSR** (VAST‑AI) | MIT (© Tripo AI & Stability AI) | `stabilityai/TripoSR`: MIT | Permitido pela MIT | Compatibilidade CPU/Intel **não validada** |
| **TRELLIS** (Microsoft) | MIT | `microsoft/TRELLIS-image-large`: MIT | Permitido pela MIT | CUDA provável; **não validado** em Intel |
| **TRELLIS.2** (Microsoft) | MIT | `microsoft/TRELLIS.2-4B`: MIT | Permitido pela MIT | README upstream: NVIDIA ≥ 24 GB + CUDA. O preset da Intel o oferece em int8 via ComfyUI/XPU: **viabilidade na A750 a validar** (INTEL_AI.md) |
| **Hunyuan3D‑2.1** (Tencent) | *Tencent Hunyuan 3D 2.1 Community License* | idem (`other: tencent-hunyuan-community`) | Condicionado à licença | **Não se aplica na UE, Reino Unido e Coreia do Sul** (território limitado); política de uso aceitável; ler cláusulas de escala/saída antes de usar |
| **Stable Diffusion 1.5** | — | `creativeml-openrail-m` | Permitido com restrições de uso (OpenRAIL‑M) | Repassar as restrições de uso a terceiros |
| **SDXL base 1.0** | — | `openrail++` | Permitido com restrições de uso (OpenRAIL++) | idem; sem *gating* no HF |

Código do AssetForge: gerado proceduralmente; assets exportados declaram `license: CC0-1.0 (procedurally generated, no third-party assets)` no
manifesto e `provenance.inputs = "parameters only"`. Quando um modelo de IA participar, o manifesto passará a registrar
`ai_model`, versão dos pesos e licença.

Dependências de runtime (todas permissivas): FastAPI/Starlette/Pydantic (MIT), SQLAlchemy (MIT), numpy (BSD), trimesh (MIT),
Pillow (HPND), psutil (BSD), React (MIT), Three.js (MIT), TanStack Query (MIT). Blender: GPL v3 — usado como executável
externo (não é incorporado ao código); os arquivos exportados não herdam a GPL. Playwright/Chromium usados só em testes.

Downloads de pesos (Milestone 2): somente por ação explícita do operador, com SHA‑256 verificado e cache local; o sistema
deve funcionar offline depois de instalado.
