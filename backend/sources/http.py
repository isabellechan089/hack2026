"""Shared HTTP layer: disk-cached GETs with polite-pool identification.

Every external API call in the project goes through `get_json` or `get_text` so
that a demo can be replayed offline and so we never hammer a public API.
"""

import hashlib
import json
import os
import time
from typing import Any, Dict, Optional

import requests

from urllib.parse import urlparse

CACHE_DIR = os.environ.get(
    "PROVENANCE_CACHE_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".cache"),
)

# OpenAlex and Crossref both give faster, more reliable service to callers who
# identify themselves. Set CONTACT_EMAIL in .env.
CONTACT_EMAIL = os.environ.get("CONTACT_EMAIL", "")

USER_AGENT = "provenance-graph/0.1 (https://github.com/; mailto:{})".format(
    CONTACT_EMAIL or "anonymous"
)

# Set to False to force fresh network calls.
USE_CACHE = os.environ.get("PROVENANCE_USE_CACHE", "1") != "0"

# An NCBI API key raises the E-utilities limit from 3 to 10 requests/second.
NCBI_API_KEY = os.environ.get("NCBI_API_KEY", "")

MAX_RETRIES = 4
BACKOFF_SECONDS = 1.0

# Per-host pacing. NCBI E-utilities allows 3 requests/second without an API
# key (10/s with one); the scholarly APIs are far more permissive.
_MIN_INTERVAL_SECONDS = {
    "eutils.ncbi.nlm.nih.gov": 0.15 if os.environ.get("NCBI_API_KEY") else 0.40,
}
_DEFAULT_MIN_INTERVAL = 0.12
_last_request_at: Dict[str, float] = {}


class SourceError(RuntimeError):
    """An external source failed in a way the caller should handle gracefully."""


def _cache_path(url: str, params: Optional[Dict[str, Any]]) -> str:
    key = url + "?" + json.dumps(params or {}, sort_keys=True)
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
    return os.path.join(CACHE_DIR, digest + ".json")


def _host(url: str) -> str:
    return urlparse(url).netloc


def _throttle(url: str) -> None:
    host = _host(url)
    minimum = _MIN_INTERVAL_SECONDS.get(host, _DEFAULT_MIN_INTERVAL)
    elapsed = time.time() - _last_request_at.get(host, 0.0)
    if elapsed < minimum:
        time.sleep(minimum - elapsed)
    _last_request_at[host] = time.time()


def _fetch(url: str, params: Optional[Dict[str, Any]], as_json: bool) -> Any:
    """Return a cached response body, fetching it over the network if needed."""
    path = _cache_path(url, params)

    if USE_CACHE and os.path.exists(path):
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)["body"]

    params = dict(params or {})
    if _host(url).endswith("ncbi.nlm.nih.gov") and NCBI_API_KEY:
        params.setdefault("api_key", NCBI_API_KEY)

    body = None
    last_error = None
    for attempt in range(MAX_RETRIES):
        _throttle(url)
        try:
            response = requests.get(
                url,
                params=params,
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                timeout=30,
            )
            # Back off and retry on rate limiting or a transient server error.
            if response.status_code in (429, 500, 502, 503, 504):
                last_error = "HTTP {}".format(response.status_code)
                time.sleep(BACKOFF_SECONDS * (2 ** attempt))
                continue
            response.raise_for_status()
            body = response.json() if as_json else response.text
            break
        except requests.RequestException as exc:
            last_error = str(exc)
            time.sleep(BACKOFF_SECONDS * (2 ** attempt))
        except ValueError as exc:
            raise SourceError("response from {} was not valid JSON".format(url)) from exc
    else:
        raise SourceError("request to {} failed after {} attempts: {}".format(
            url, MAX_RETRIES, last_error))

    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"url": url, "params": params, "body": body}, handle)

    return body


def get_json(url: str, params: Optional[Dict[str, Any]] = None) -> Any:
    return _fetch(url, params, as_json=True)


def get_text(url: str, params: Optional[Dict[str, Any]] = None) -> str:
    return _fetch(url, params, as_json=False)


def polite_params(params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Add the contact email that OpenAlex/Crossref use for their polite pool."""
    out = dict(params or {})
    if CONTACT_EMAIL:
        out["mailto"] = CONTACT_EMAIL
    return out
