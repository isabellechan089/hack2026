"""A thin, budgeted OpenAI client.

Three rules, all in service of a ten-dollar budget and an auditable cost story:

  * every response is cached on disk by (model, messages, schema), so a rerun
    of the same extraction costs nothing;
  * every uncached call is written to a ledger with its token counts and
    purpose, which is what the before/after cost comparison is computed from;
  * a hard cap on uncached calls per process refuses rather than overspends.

No SDK: the API is one POST, and a dependency would add nothing we use.
"""

import hashlib
import json
import os
import time
from typing import Any, Dict, List, Optional

import requests

from .. import config
from ..sources.http import CACHE_DIR

ENDPOINT = "https://api.openai.com/v1/chat/completions"
LEDGER = os.path.join(CACHE_DIR, "llm_ledger.jsonl")
MAX_CALLS = int(os.environ.get("LLM_MAX_CALLS", "300"))

# The cascade. The small model answers first; the larger one is consulted only
# when the small one's answer fails validation.
TIER_SMALL = os.environ.get("LLM_MODEL_SMALL", "gpt-4.1-nano")
TIER_LARGE = os.environ.get("LLM_MODEL_LARGE", "gpt-4.1-mini")

_calls_this_process = 0

# Published list prices, USD per million tokens, so the ledger can say what
# was spent in money and not only in tokens. Kept as data: if a price changes,
# the comparison logic does not.
PRICES_PER_MILLION = {
    "gpt-4.1-nano": {"prompt": 0.10, "completion": 0.40},
    "gpt-4.1-mini": {"prompt": 0.40, "completion": 1.60},
    "gpt-4.1": {"prompt": 2.00, "completion": 8.00},
    "gpt-4o-mini": {"prompt": 0.15, "completion": 0.60},
    "gpt-4o": {"prompt": 2.50, "completion": 10.00},
}

# A completion cap. Structured outputs are short by construction; a runaway
# answer is a bug, not a cost we should pay for.
MAX_COMPLETION_TOKENS = int(os.environ.get("LLM_MAX_COMPLETION_TOKENS", "800"))

# Cache hits are not written to the ledger (nothing was spent), but they are
# the other half of the cost story, so they are tallied in memory.
_cache_hits = 0
_tokens_avoided_by_cache = 0


class BudgetExceeded(RuntimeError):
    pass


class LLMUnavailable(RuntimeError):
    pass


def _cache_path(key: str) -> str:
    return os.path.join(CACHE_DIR, "llm", hashlib.sha256(key.encode()).hexdigest()[:32] + ".json")


def _record(entry: Dict[str, Any]) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(LEDGER, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")


def ledger() -> List[Dict[str, Any]]:
    try:
        with open(LEDGER, "r", encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]
    except OSError:
        return []


def cost_usd(prompt_tokens: int, completion_tokens: int, model: str) -> Optional[float]:
    """Dollar cost of one call at list price, or None for an unknown model."""
    price = PRICES_PER_MILLION.get(model)
    if price is None:
        return None
    return (prompt_tokens * price["prompt"] + completion_tokens * price["completion"]) / 1_000_000


def summary() -> Dict[str, Any]:
    """What the model layer has cost, for the ledger endpoint and the interface.

    Everything here is measured: token counts come from the API's own usage
    field, and the counterfactual columns re-price the same tokens at the
    larger tier rather than guessing at a different workload.
    """
    rows = ledger()
    by_purpose: Dict[str, Dict[str, Any]] = {}
    by_model: Dict[str, Dict[str, Any]] = {}
    total_cost = 0.0
    priced = True
    for row in rows:
        key = (row.get("purpose") or "other").split(":")[0] or "other"
        bucket = by_purpose.setdefault(key, {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0})
        model_bucket = by_model.setdefault(row.get("model", "?"), {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0})
        prompt, completion = row.get("prompt_tokens", 0), row.get("completion_tokens", 0)
        cost = cost_usd(prompt, completion, row.get("model", ""))
        if cost is None:
            priced = False
            cost = 0.0
        for b in (bucket, model_bucket):
            b["calls"] += 1
            b["prompt_tokens"] += prompt
            b["completion_tokens"] += completion
            b["cost_usd"] += cost
        total_cost += cost

    for buckets in (by_purpose, by_model):
        for bucket in buckets.values():
            bucket["cost_usd"] = round(bucket["cost_usd"], 5)
    prompt_total = sum(r.get("prompt_tokens", 0) for r in rows)
    completion_total = sum(r.get("completion_tokens", 0) for r in rows)
    # The same calls at the larger tier: what the cascade's "small model first"
    # rule saved, holding the workload fixed.
    at_large_tier = cost_usd(prompt_total, completion_total, TIER_LARGE)
    return {
        "calls": len(rows),
        "prompt_tokens": prompt_total,
        "completion_tokens": completion_total,
        "total_tokens": prompt_total + completion_total,
        "cost_usd": round(total_cost, 4) if priced else None,
        "cost_usd_if_all_large_tier": round(at_large_tier, 4) if at_large_tier is not None else None,
        "by_purpose": by_purpose,
        "by_model": by_model,
        "tiers": {"small": TIER_SMALL, "large": TIER_LARGE},
        "pricing_usd_per_million": {m: PRICES_PER_MILLION[m] for m in (TIER_SMALL, TIER_LARGE) if m in PRICES_PER_MILLION},
        "cache": {
            "hits_this_process": _cache_hits,
            "tokens_avoided_this_process": _tokens_avoided_by_cache,
        },
        "budget": {"max_calls": MAX_CALLS, "calls_this_process": _calls_this_process},
    }


def estimate_tokens(text: str) -> int:
    """A length-based estimate, used only for the baseline we choose not to run."""
    return max(1, len(text) // 4)


def chat_json(
    messages: List[Dict[str, str]],
    schema: Dict[str, Any],
    schema_name: str,
    model: str = TIER_SMALL,
    purpose: str = "",
    temperature: float = 0.0,
) -> Dict[str, Any]:
    """One structured-output call. Returns {"data", "usage", "model", "cached"}."""
    global _calls_this_process, _cache_hits, _tokens_avoided_by_cache
    key = json.dumps({"m": model, "msg": messages, "s": schema}, sort_keys=True)
    path = _cache_path(key)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as handle:
            cached = json.load(handle)
        cached["cached"] = True
        _cache_hits += 1
        usage = cached.get("usage") or {}
        _tokens_avoided_by_cache += usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)
        return cached

    api_key = config.openai_key()
    if not api_key:
        raise LLMUnavailable("No OpenAI API key configured.")
    if _calls_this_process >= MAX_CALLS:
        raise BudgetExceeded("Refusing call {}: LLM_MAX_CALLS={}".format(_calls_this_process + 1, MAX_CALLS))

    body = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": MAX_COMPLETION_TOKENS,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": schema_name, "strict": True, "schema": schema},
        },
    }
    started = time.time()
    response = requests.post(
        ENDPOINT,
        headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"},
        json=body,
        timeout=60,
    )
    _calls_this_process += 1
    if not response.ok:
        raise LLMUnavailable("OpenAI {}: {}".format(response.status_code, response.text[:200]))
    payload = response.json()
    usage = payload.get("usage", {})
    content = payload["choices"][0]["message"]["content"]
    result = {
        "data": json.loads(content),
        "usage": {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
        },
        "model": model,
        "cached": False,
    }
    _record({
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "model": model,
        "purpose": purpose,
        "prompt_tokens": result["usage"]["prompt_tokens"],
        "completion_tokens": result["usage"]["completion_tokens"],
        "cost_usd": cost_usd(result["usage"]["prompt_tokens"], result["usage"]["completion_tokens"], model),
        "seconds": round(time.time() - started, 2),
    })
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(result, handle)
    return result
