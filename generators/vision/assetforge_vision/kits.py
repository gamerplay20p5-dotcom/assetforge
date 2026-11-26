"""Which generator handles which category. This is the single place to extend when a new kit is added."""

from __future__ import annotations

from typing import Any

from .schema import AssetAnalysis

KITS: dict[str, dict[str, Any]] = {
    "house": dict(status="available", generator="procedural.house", label="Kit de casas", stages=6),
    "vehicle": dict(status="planned", generator="procedural.vehicle", label="Kit de veículos"),
    "character": dict(status="planned", generator="procedural.character", label="Kit de personagens"),
    "tree": dict(status="planned", generator="procedural.tree", label="Kit de árvores e plantas"),
    "prop": dict(status="fallback", generator=None, label="Objeto isolado"),
    "other": dict(status="none", generator=None, label="Sem categoria"),
}


# The model once called flat ground "a baseball field, isolated object" (measured), and image-to-mesh models produce garbage from flat ground.
# So the subject it wrote is checked as well: anything that reads like ground/terrain/map is never sent to the mesh provider.
FLAT_WORDS = ("field", "ground", "terrain", "land", "plot", "lawn", "grass", "map", "landscape", "floor", "screenshot", "dirt", "soil", "foundation", "slab")


def looks_flat(subject: str) -> bool:
    words = subject.lower().replace("-", " ").split()
    return any(w.strip(".,") in FLAT_WORDS for w in words)


def route(a: AssetAnalysis, image_size: tuple[int, int] | None = None) -> dict[str, Any]:
    """Decide how an analysed image becomes a model, saying plainly when there is no kit yet."""
    kit = KITS[a.category]
    if kit["status"] == "available":
        return dict(mode="kit", kit=a.category, label=kit["label"], message=f"{kit['label']}: revise a descrição e gere.")
    if looks_flat(a.subject):
        return dict(mode="none", kit=None, label=kit["label"], fallback=None,
                    message=f"O modelo leu isto como \"{a.subject}\" (terreno, chão ou cena). Um modelo 3D bom não sai daqui: envie o objeto sozinho, em fundo liso.")
    if a.isolated_object and a.category in ("prop", "tree", "vehicle", "character"):
        planned = " Ainda não existe um kit para essa categoria." if kit["status"] == "planned" else ""
        small = " A imagem é pequena (menos de 256 px); o resultado tende a ser pior." if image_size and min(image_size) < 256 else ""
        return dict(mode="fallback", kit=None, label=kit["label"], fallback="triposr",
                    message=f"Objeto isolado ({a.subject or a.category}).{planned}{small} Dá para tentar o TripoSR, que é experimental e costuma deformar a malha.")
    return dict(mode="none", kit=None, label=kit["label"], fallback=None,
                message="Não é uma casa nem um objeto isolado em fundo liso; não há como gerar um modelo bom daqui. Envie o objeto sozinho, em fundo liso.")
