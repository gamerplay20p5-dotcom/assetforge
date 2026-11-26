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


def route(a: AssetAnalysis) -> dict[str, Any]:
    """Decide how an analysed image becomes a model, saying plainly when there is no kit yet."""
    kit = KITS[a.category]
    if kit["status"] == "available":
        return dict(mode="kit", kit=a.category, label=kit["label"], message=f"{kit['label']}: revise a descrição e gere.")
    if a.isolated_object and a.category in ("prop", "tree", "vehicle", "character"):
        planned = " Ainda não existe um kit para essa categoria." if kit["status"] == "planned" else ""
        return dict(mode="fallback", kit=None, label=kit["label"], fallback="triposr",
                    message=f"Objeto isolado ({a.subject or a.category}).{planned} Dá para tentar o TripoSR, que é experimental e costuma deformar a malha.")
    return dict(mode="none", kit=None, label=kit["label"], fallback=None,
                message="Não é uma casa nem um objeto isolado em fundo liso; não há como gerar um modelo bom daqui. Envie o objeto sozinho, em fundo liso.")
