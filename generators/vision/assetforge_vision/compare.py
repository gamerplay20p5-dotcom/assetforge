"""Visual inspector: compares renders of a generated model with the ORIGINAL reference image (used for TRELLIS.2 masters and their LODs).

The AI's score is advice for the reviewer, never an approval: the user's visual approval is what releases an asset. Schema has no numeric limits on
purpose (Gemini rejects schemas with too many constraint states); values are clamped by ``clean``.
"""

from __future__ import annotations

from typing import Any

PROMPT_VERSION = "compare-v1"
CRITERIA = ["silhouette", "proportions", "materials", "colors", "components", "deformations"]
COMPARE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "overall": {"type": "number"},
        "criteria": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string", "enum": CRITERIA}, "score": {"type": "number"}, "notes": {"type": "string"}}, "required": ["name", "score", "notes"]}},
        "main_differences": {"type": "array", "items": {"type": "string"}},
        "defects": {"type": "array", "items": {"type": "string"}},
        "verdict": {"type": "string", "enum": ["faithful", "acceptable_with_fixes", "unfaithful"]},
    },
    "required": ["overall", "criteria", "main_differences", "defects", "verdict"],
}
SYSTEM = ("You are a strict 3D art reviewer for a game studio (Premium Stylized low/mid poly). You compare renders of a generated 3D model with "
          "the original reference image. You only describe what you see; you do not write code.")


def compare_prompt(view_names: list[str], label: str, extra: str = "", reference_names: list[str] | None = None) -> str:
    originals = (f"The first {len(reference_names)} images are ORIGINAL references, in this order: "
                 + ", ".join(reference_names) + ".") if reference_names else "The FIRST image is the ORIGINAL reference."
    return "\n\n".join([
        f"{originals} The next {len(view_names)} images are renders of the generated model '{label}', in this order: "
        + ", ".join(view_names) + ". The render camera may show different angles of the object.",
        "Judge the model against the references on: silhouette, proportions, materials, colors, characteristic components, "
        "deformations (warped or melted surfaces, holes, floating parts). The renders use a neutral studio light and no photographic shading, so judge hue and "
        "relative tones, and say separately if the model is globally darker or lighter than the reference.",
        "Scores are 0-10 (10 = indistinguishable at game scale; 7 = same design with visible differences; below 5 = different object). Be strict and "
        "list at least 3 concrete differences unless the match is nearly perfect. The overall score is advice for a human reviewer, not an approval." + (("\n" + extra) if extra else ""),
    ])


def clean(data: dict) -> dict:
    """Clamp scores to 0-10 and drop unknown criteria; the model is trusted for opinions, not for ranges."""
    def c(x: Any) -> float:
        try:
            return max(0.0, min(10.0, float(x)))
        except (TypeError, ValueError):
            return 0.0

    return {"overall": c(data.get("overall")),
            "criteria": [{"name": k["name"], "score": c(k.get("score")), "notes": str(k.get("notes", ""))[:400]} for k in data.get("criteria", []) if k.get("name") in CRITERIA],
            "main_differences": [str(x)[:300] for x in data.get("main_differences", [])][:12], "defects": [str(x)[:300] for x in data.get("defects", [])][:12],
            "verdict": data.get("verdict") if data.get("verdict") in ("faithful", "acceptable_with_fixes", "unfaithful") else "unfaithful"}
