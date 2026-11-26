"""Registry of the CPU-only image-to-3D providers (facts verified 2026-11-26 from the upstream repos and Hugging Face)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    title: str
    repo: str
    commit: str  # pinned upstream commit used by the Docker image
    weights_repo: str
    weights_gated: bool
    code_license: str
    weights_license: str
    commercial: str  # short, honest summary for Brazil
    output: str
    notes: list[str] = field(default_factory=list)


PROVIDERS: dict[str, ProviderSpec] = {
    "sf3d": ProviderSpec(
        name="sf3d", title="Stable Fast 3D (CPU)", repo="Stability-AI/stable-fast-3d", commit="ff21fc491b4dc5314bf6734c7c0dabd86b5f5bb2",
        weights_repo="stabilityai/stable-fast-3d", weights_gated=True,
        code_license="Stability AI Community License (LICENSE.md do repositório)",
        weights_license="Stability AI Community License (card HF: other / stabilityai-ai-community)",
        commercial="CONDICIONAL: uso comercial permitido mediante REGISTRO na Stability AI e enquanto a organização (com afiliadas) gerar < US$ 1 milhão/ano; "
                   "acima disso exige licença Enterprise. Exige aviso 'Powered by Stability AI' + arquivo Notice e adesão à AUP. Sem restrição territorial ao Brasil. "
                   "A saída (o modelo 3D) é de quem gerou, na medida da lei. NÃO pode ser usada para treinar modelos de IA fundacionais.",
        output="GLB texturizado (UV + albedo/roughness/metallic/normal)",
        notes=["Pesos 'gated': é preciso aceitar a licença no Hugging Face com a SUA conta e fornecer um token de leitura (HF_TOKEN) para baixar.",
               "Baixa também DINOv2-large (Apache-2.0) e CLIP ViT-H-14 laion (MIT) na primeira execução (via open_clip/transformers)."],
    ),
    "triposr": ProviderSpec(
        name="triposr", title="TripoSR (CPU)", repo="VAST-AI-Research/TripoSR", commit="107cefdc244c39106fa830359024f6a2f1c78871",
        weights_repo="stabilityai/TripoSR", weights_gated=False,
        code_license="MIT", weights_license="MIT (card HF)",
        commercial="OK: MIT no código e nos pesos, sem restrição territorial; manter o aviso de copyright (Tripo AI & Stability AI).",
        output="OBJ + textura baked (convertido para GLB) ou GLB com cor por vértice",
        notes=["Pesos não 'gated'. Bake de textura usa moderngl (precisa de contexto OpenGL; em servidor sem GPU usa Mesa por software — pode falhar: então cai para cor por vértice)."],
    ),
}

# Third-party components pulled in by the images. Verified on PyPI/GitHub/HF on 2026-11-26 (not legal advice).
DEPENDENCY_LICENSES: dict[str, str] = {
    "torch (CPU)": "BSD-3-Clause", "transformers": "Apache-2.0", "rembg": "MIT", "u2net (pesos baixados pelo rembg)": "Apache-2.0 (repo xuebinqin/U-2-Net)",
    "trimesh": "MIT", "einops": "MIT", "omegaconf": "BSD", "open_clip_torch": "MIT", "jaxtyping": "MIT", "onnxruntime": "MIT",
    "xatlas": "MIT", "moderngl": "MIT", "torchmcubes": "MPL-2.0 (copyleft por arquivo; usado sem modificação)",
    "gpytoolbox": "MIT", "pynanoinstantmeshes": "BSD", "imageio": "BSD-2-Clause", "psutil": "BSD-3-Clause",
    "texture_baker / uv_unwrapper (dentro do repo SF3D)": "sem arquivo próprio: cobertos pela Stability AI Community License do repositório",
    "facebook/dinov2-large (pesos)": "Apache-2.0", "laion/CLIP-ViT-H-14 (pesos)": "MIT",
}
