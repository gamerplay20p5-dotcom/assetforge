"""Text -> structured generator parameters ("planner").

Two interchangeable strategies, both producing a validated ``BuildingParams``:

1. ``plan_with_rules``  - deterministic PT-BR/EN keyword parser. Always available, offline, no model needed.
2. ``plan_with_llm``    - optional adapter for a LOCAL language model served over HTTP (Ollama-compatible
   ``/api/chat``). The model is asked for JSON constrained to the BuildingParams schema; the answer is
   validated with pydantic (``extra=forbid``) so it can only ever select known parameters - it can never
   inject code or arbitrary fields. Any failure falls back to the rules planner.

The planner only chooses parameters; geometry is always produced by the procedural Blender/trimesh pipeline.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field

import httpx
from assetforge_contract import BuildingParams
from pydantic import ValidationError

NUMBER_WORDS = {
    "um": 1, "uma": 1, "one": 1, "dois": 2, "duas": 2, "two": 2, "tres": 3, "three": 3, "quatro": 4, "four": 4,
    "cinco": 5, "five": 5, "seis": 6, "six": 6, "sete": 7, "seven": 7, "oito": 8, "eight": 8, "nove": 9, "nine": 9,
    "dez": 10, "ten": 10, "onze": 11, "doze": 12, "twelve": 12, "quinze": 15, "fifteen": 15, "vinte": 20,
    "twenty": 20, "trinta": 30, "thirty": 30, "quarenta": 40, "forty": 40,
}

# order matters: the first match wins (more specific phrases first)
CATEGORY_KEYWORDS: list[tuple[str, list[str]]] = [
    ("hospital", ["hospital", "clinica", "pronto-socorro", "pronto socorro"]),
    ("university", ["universidade", "university", "campus", "faculdade"]),
    ("school", ["escola", "school", "colegio", "creche"]),
    ("police", ["delegacia", "policia", "police"]),
    ("fire_station", ["bombeiro", "bombeiros", "quartel", "fire station", "firehouse"]),
    ("transport_station", ["estacao", "station", "terminal", "metro", "rodoviaria"]),
    ("government", ["prefeitura", "governo", "governamental", "camara", "city hall", "government", "tribunal"]),
    ("skyscraper", ["arranha-ceu", "arranha ceu", "skyscraper", "torre", "tower"]),
    ("warehouse", ["armazem", "galpao", "warehouse", "deposito"]),
    ("industrial", ["industria", "industrial", "fabrica", "factory", "usina"]),
    ("commercial", ["supermercado", "mercado", "loja", "shopping", "comercial", "commercial", "shop", "store", "escritorio", "office"]),
    ("apartment", ["apartamento", "apartment", "condominio", "residencial multifamiliar", "predio residencial", "edificio residencial"]),
    ("house", ["casa", "house", "sobrado", "residencia", "chale", "home", "bangalo", "bungalow"]),
]
STYLE_KEYWORDS: list[tuple[str, list[str]]] = [
    ("mediterranean", ["mediterraneo", "mediterranean", "toscana", "colonial"]),
    ("nordic", ["nordico", "nordic", "escandinavo", "scandinavian", "cabana"]),
    ("industrial", ["estilo industrial", "industrial style", "loft"]),
    ("classic", ["classico", "classic", "tijolo", "brick", "tradicional", "traditional", "neoclassico", "historico"]),
    ("modern", ["moderno", "moderna", "modern", "contemporaneo", "contemporary", "minimalista", "minimalist"]),
]
ROOF_KEYWORDS: list[tuple[str, list[str]]] = [
    ("flat", ["telhado plano", "laje", "flat roof", "teto plano", "cobertura plana"]),
    ("hip", ["quatro aguas", "4 aguas", "hip roof", "hipped"]),
    ("gable", ["duas aguas", "2 aguas", "gable", "empena"]),
    ("sawtooth", ["dente de serra", "sawtooth", "shed industrial"]),
    ("shed", ["uma agua", "shed roof"]),
]


def _norm(text: str) -> str:
    t = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def _has(text: str, kw: str) -> bool:
    return re.search(rf"(?<![a-z]){re.escape(kw)}", text) is not None


@dataclass
class PlanResult:
    params: dict
    name: str
    source: str  # "rules" | "llm"
    confidence: float
    matched: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _number(token: str) -> int | None:
    if token.isdigit():
        return int(token)
    return NUMBER_WORDS.get(token)


def plan_with_rules(description: str) -> PlanResult:
    t = _norm(description)
    params: dict = {}
    matched: list[str] = []
    notes: list[str] = []
    category = None
    for cat, kws in CATEGORY_KEYWORDS:
        hit = next((k for k in kws if _has(t, k)), None)
        if hit:
            category = cat
            matched.append(f"categoria={cat} ('{hit}')")
            break
    if category is None:
        category = "house"
        notes.append("nenhuma categoria reconhecida; usando 'house'")
    params["category"] = category

    for style, kws in STYLE_KEYWORDS:
        hit = next((k for k in kws if _has(t, k)), None)
        if hit:
            params["style"] = style
            matched.append(f"estilo={style} ('{hit}')")
            break

    m = re.search(r"([a-z0-9]+)\s*(?:-\s*)?(?:andares|andar|pavimentos|pavimento|floors|floor|stories|story|storey|storeys)", t)
    if m and (n := _number(m.group(1))):
        params["floors"] = max(1, min(80, n))
        matched.append(f"andares={params['floors']}")
    dims = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:m|metros)?\s*(?:x|por|by)\s*(\d+(?:[.,]\d+)?)\s*(?:m|metros)", t)
    if dims:
        params["width"] = float(dims.group(1).replace(",", "."))
        params["depth"] = float(dims.group(2).replace(",", "."))
        matched.append(f"dimensoes={params['width']}x{params['depth']} m")
    else:
        w = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:m|metros)\s*(?:de\s+)?(?:largura|comprimento|wide|width|long)", t)
        d = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:m|metros)\s*(?:de\s+)?(?:profundidade|depth|deep)", t)
        if w:
            params["width"] = float(w.group(1).replace(",", "."))
            matched.append(f"largura={params['width']} m")
        if d:
            params["depth"] = float(d.group(1).replace(",", "."))
            matched.append(f"profundidade={params['depth']} m")
    h = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:m|metros)\s*(?:de\s+)?(?:altura|tall|high|height)", t)
    if h and "floors" not in params:
        height = float(h.group(1).replace(",", "."))
        fh = 3.5 if category not in ("house",) else 2.9
        params["floors"] = max(1, min(80, round(height / fh)))
        matched.append(f"altura={height} m -> andares={params['floors']}")

    for roof, kws in ROOF_KEYWORDS:
        hit = next((k for k in kws if _has(t, k)), None)
        if hit:
            params["roof"] = roof
            matched.append(f"telhado={roof}")
            break
    if re.search(r"(sem|no|without)\s+(varanda|sacada|balcon)", t):
        params["balconies"] = False
        matched.append("varandas=nao")
    elif re.search(r"(varanda|sacada|balcon)", t):
        params["balconies"] = True
        matched.append("varandas=sim")
    if re.search(r"(sem|no|without)\s+garagem|without\s+garage", t):
        params["garage"] = False
        matched.append("garagem=nao")
    elif re.search(r"garagem|garage", t):
        params["garage"] = True
        matched.append("garagem=sim")
    if re.search(r"\b(novo|nova|novinho|pristine|new|recem|impecavel)\b", t):
        params["wear"] = 0.0
        matched.append("conservacao=nova")
    elif re.search(r"\b(velho|velha|antigo|antiga|desgastad[oa]|abandonad[oa]|worn|old|decadente|ruim)\b", t):
        params["wear"] = 0.7
        matched.append("conservacao=desgastada")
    if re.search(r"detalhad|detailed|ricos? em detalhes|muito detalhe", t):
        params["detail"] = 2
        matched.append("detalhe=2")
    seed = re.search(r"seed\s*[:=]?\s*(\d+)", t)
    if seed:
        params["seed"] = int(seed.group(1))

    BuildingParams.model_validate(params)  # must always be valid
    confidence = min(1.0, 0.25 + 0.15 * len(matched)) if matched else 0.1
    return PlanResult(params=params, name=_suggest_name(description, category), source="rules",
                      confidence=round(confidence, 2), matched=matched, notes=notes)


def _suggest_name(description: str, category: str) -> str:
    first = description.strip().split("\n")[0][:60].strip(" .,;")
    return first[:1].upper() + first[1:] if first else category


SYSTEM_PROMPT = (
    "You convert a short description of a building into parameters for a procedural building generator. "
    "Reply with ONE JSON object that follows the provided JSON schema exactly. Only include fields you can infer "
    "from the description; omit the rest. Dimensions are meters. Do not add any explanation."
)


def plan_with_llm(description: str, base_url: str, model: str, timeout: float = 120.0,
                  client: httpx.Client | None = None) -> PlanResult:
    """Ask a local Ollama-compatible server. Raises ValueError if the answer is unusable."""
    schema = BuildingParams.model_json_schema()
    body = {"model": model, "stream": False, "format": schema, "options": {"temperature": 0},
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": description}]}
    http = client or httpx.Client(timeout=timeout)
    try:
        resp = http.post(base_url.rstrip("/") + "/api/chat", json=body)
        resp.raise_for_status()
        content = resp.json()["message"]["content"]
        params = json.loads(content)
        validated = BuildingParams.model_validate(params)  # rejects unknown fields and out-of-range values
    except (httpx.HTTPError, KeyError, json.JSONDecodeError, ValidationError, TypeError) as exc:
        raise ValueError(f"LLM planner failed: {type(exc).__name__}: {str(exc)[:200]}") from exc
    finally:
        if client is None:
            http.close()
    return PlanResult(params=validated.model_dump(exclude_unset=True, mode="json"), name=_suggest_name(description, validated.category),
                      source="llm", confidence=0.8, matched=[f"llm:{model}"])


def plan(description: str, llm_url: str | None = None, llm_model: str | None = None) -> PlanResult:
    """Use the local LLM when configured, otherwise (or on failure) the deterministic rules."""
    if llm_url and llm_model:
        try:
            return plan_with_llm(description, llm_url, llm_model)
        except ValueError as exc:
            result = plan_with_rules(description)
            result.notes.append(f"LLM indisponível, usei regras ({exc})")
            return result
    return plan_with_rules(description)
