"""Extract hazard ratios from publication text (spec section 10).

The model reads sentences, not papers: the Europe PMC adapter has already
reduced an article to the handful of sentences that could carry an estimate.
The model's job is language -- pairing each ratio with its endpoint and
interval when the sentence phrases them six different ways -- not judgement.

Every extracted value is validated against the text it came from before it is
accepted: the ratio must be positive, the interval must bracket it, and the
quoted evidence must actually appear in the input. A value that fails is sent
to the larger model once; if it still fails it is dropped, never guessed.
"""

import re
from typing import Any, Dict, List, Optional

from . import client

SCHEMA = {
    "type": "object",
    "properties": {
        "estimates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "endpoint": {"type": "string", "enum": ["os", "pfs", "other"]},
                    "hazard_ratio": {"type": "number"},
                    "ci_lower": {"type": ["number", "null"]},
                    "ci_upper": {"type": ["number", "null"]},
                    "comparison": {"type": "string"},
                    "evidence": {"type": "string"},
                },
                "required": ["endpoint", "hazard_ratio", "ci_lower", "ci_upper", "comparison", "evidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["estimates"],
    "additionalProperties": False,
}

SYSTEM = (
    "You extract hazard ratios from clinical trial text. Report only ratios that "
    "are stated explicitly, with their 95% confidence interval when given. "
    "Classify the endpoint as os (overall survival), pfs (progression-free, "
    "event-free, disease-free or recurrence-free survival, or time to "
    "progression) or other. In 'evidence', copy the exact sentence fragment the "
    "numbers came from. Never infer or compute a value that is not written."
)


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9.]", "", text.lower())


def _valid(item: Dict[str, Any], sentences: List[str]) -> bool:
    hr = item.get("hazard_ratio")
    lo, hi = item.get("ci_lower"), item.get("ci_upper")
    if not isinstance(hr, (int, float)) or hr <= 0 or hr > 20:
        return False
    if lo is not None and hi is not None and not (0 < lo <= hr <= hi):
        return False
    quote = _norm(item.get("evidence") or "")
    if len(quote) < 8:
        return False
    return any(quote in _norm(s) for s in sentences)


def extract_hazard_ratios(sentences: List[str], purpose: str = "extract_hr") -> Dict[str, Any]:
    """Structured estimates from sentences, with the cost of getting them."""
    if not sentences:
        return {"estimates": [], "model": None, "tokens": 0, "tokens_cached": 0, "tier": None, "rejected": 0}

    text = "\n".join("- " + s for s in sentences)
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": "Sentences from one paper:\n" + text},
    ]

    tokens = 0
    tokens_cached = 0
    rejected = 0
    for tier, model in (("small", client.TIER_SMALL), ("large", client.TIER_LARGE)):
        result = client.chat_json(messages, SCHEMA, "hazard_ratios", model=model, purpose=purpose)
        spent = result["usage"]["prompt_tokens"] + result["usage"]["completion_tokens"]
        if result["cached"]:
            tokens_cached += spent
        else:
            tokens += spent
        items = result["data"].get("estimates", [])
        accepted = [i for i in items if _valid(i, sentences)]
        rejected = len(items) - len(accepted)
        # The larger tier is only consulted when the small one produced something
        # that failed validation; an empty, valid answer is accepted as-is.
        if accepted or not items:
            return {"estimates": accepted, "model": model, "tokens": tokens, "tokens_cached": tokens_cached,
                    "tier": tier, "rejected": rejected, "cached": result["cached"]}
    return {"estimates": [], "model": client.TIER_LARGE, "tokens": tokens, "tokens_cached": tokens_cached,
            "tier": "large", "rejected": rejected, "cached": False}
