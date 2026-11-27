"""Compare the building agent on the same ordered photographs and prompt in the central pool."""

import argparse
import hashlib
import json
import time
from pathlib import Path

from sqlalchemy import select

from assetforge_api.ai.router import AiRejected, AiRouter, NoKeyAvailable
from assetforge_api.config import get_settings
from assetforge_api.db import Database
from assetforge_api.models import AiKey
from assetforge_procedural.house import HouseSpec
from assetforge_vision import llm_spec


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("references", nargs="+", type=Path)
    parser.add_argument("--category", default="")
    args = parser.parse_args()
    if not 1 <= len(args.references) <= 4:
        parser.error("Provide one to four PNG views of the same building")
    images = [(path.read_bytes(), "image/png") for path in args.references]
    prompt = llm_spec.spec_prompt(len(images), args.category)
    comparison = {"prompt_version": llm_spec.PROMPT_VERSION, "category": args.category,
                  "reference_sha256": [hashlib.sha256(data).hexdigest() for data, _ in images],
                  "providers": {}}
    settings = get_settings()
    with Database(settings.database_url).session() as db:
        configured = set(db.scalars(select(AiKey.provider).where(AiKey.enabled.is_(True))))
        router = AiRouter(db, settings.resolved_secret())
        for provider in ("gemini", "grok"):
            if provider not in configured:
                comparison["providers"][provider] = {"status": "not_configured"}
                continue
            start = time.monotonic()
            try:
                answer = router.generate_json("spec", llm_spec.SYSTEM, prompt, images, llm_spec.SPEC_SCHEMA,
                                              llm_spec.PROMPT_VERSION, provider=provider)
            except (AiRejected, NoKeyAvailable):
                comparison["providers"][provider] = {"status": "unavailable", "seconds": round(time.monotonic() - start, 2)}
                continue
            row = {"status": "ok", "model": answer.model, "cached": answer.cached,
                   "total_tokens": answer.total_tokens, "seconds": round(time.monotonic() - start, 2),
                   "spec": answer.data}
            try:
                HouseSpec.from_dict(llm_spec.to_house_spec(answer.data))
            except (ValueError, TypeError, KeyError) as exc:
                row.update(status="invalid_spec", validation=str(exc))
            comparison["providers"][provider] = row
    print(json.dumps(comparison, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
