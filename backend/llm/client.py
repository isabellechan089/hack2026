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
    global _calls_this_process
    key = json.dumps({"m": model, "msg": messages, "s": schema}, sort_keys=True)
    path = _cache_path(key)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as handle:
            cached = json.load(handle)
        cached["cached"] = True
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
        "seconds": round(time.time() - started, 2),
    })
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(result, handle)
    return result
