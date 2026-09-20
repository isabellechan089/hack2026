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

from .. import config  # loads .env before anything reads the environment

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

# Europe PMC serves whole articles rather than metadata and is slow by nature --
# tens of seconds for a long one -- so it needs a longer deadline. It was
# previously the one host given a single attempt, on the shared 30-second
# deadline, which made a transient timeout indistinguishable from an article
# that does not exist. Combined with a miss list that never expired, that lost
# rather more than half of the full-text fetches in a cohort, permanently.
# Three attempts rather than four, at 60 seconds rather than 90: an article
# that has not arrived twice is usually not arriving, and this path runs inside
# a synchronous request while somebody waits. Worst case per article is about
# three minutes, against thirty seconds before -- which is the price of not
# losing the article permanently -- and `recover` caps the run as a whole.
_TIMEOUT_SECONDS = {"www.ebi.ac.uk": 60}
_ATTEMPTS = {"www.ebi.ac.uk": 3}
_DEFAULT_TIMEOUT = 30

# Per-host pacing. NCBI E-utilities allows 3 requests/second without an API
# key (10/s with one); the scholarly APIs are far more permissive.
_MIN_INTERVAL_SECONDS = {
    "eutils.ncbi.nlm.nih.gov": 0.15 if os.environ.get("NCBI_API_KEY") else 0.40,
}
_DEFAULT_MIN_INTERVAL = 0.12
_last_request_at: Dict[str, float] = {}


class SourceError(RuntimeError):
    """An external source failed in a way the caller should handle gracefully."""


class SourceNotFound(SourceError):
    """The source answered, and the record genuinely is not there.

    Kept distinct from SourceError so a caller can tell "this will never work"
    from "this did not work just now", and decide whether it is worth asking
    again later. Retrying a 404 cannot change the answer; retrying a timeout
    often can.
    """


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


def _fetch(url: str, params: Optional[Dict[str, Any]], as_json: bool, accept: Optional[str] = None) -> Any:
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
    attempts = _ATTEMPTS.get(_host(url), MAX_RETRIES)
    for attempt in range(attempts):
        _throttle(url)
        try:
            response = requests.get(
                url,
                params=params,
                headers={"User-Agent": USER_AGENT, "Accept": accept or ("application/json" if as_json else "*/*")},
                timeout=_TIMEOUT_SECONDS.get(_host(url), _DEFAULT_TIMEOUT),
            )
            # A missing record is an answer, not a failure. Retrying it wastes
            # three more requests and several seconds to be told the same thing.
            if response.status_code in (404, 410):
                raise SourceNotFound("{} returned HTTP {}".format(url, response.status_code))
            # Back off and retry on rate limiting or a transient server error.
            if response.status_code in (429, 500, 502, 503, 504):
                last_error = "HTTP {}".format(response.status_code)
                if attempt + 1 < attempts:
                    time.sleep(BACKOFF_SECONDS * (2 ** attempt))
                continue
            response.raise_for_status()
            body = response.json() if as_json else response.text
            break
        except requests.RequestException as exc:
            last_error = str(exc)
            if attempt + 1 < attempts:
                time.sleep(BACKOFF_SECONDS * (2 ** attempt))
        except ValueError as exc:
            raise SourceError("response from {} was not valid JSON".format(url)) from exc
    else:
        raise SourceError("request to {} failed after {} attempt(s): {}".format(
            url, attempts, last_error))

    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"url": url, "params": params, "body": body}, handle)

    return body


def get_json(url: str, params: Optional[Dict[str, Any]] = None) -> Any:
    return _fetch(url, params, as_json=True)


def get_text(url: str, params: Optional[Dict[str, Any]] = None, accept: Optional[str] = None) -> str:
    return _fetch(url, params, as_json=False, accept=accept)


def polite_params(params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Add the contact email that OpenAlex/Crossref use for their polite pool."""
    out = dict(params or {})
    if CONTACT_EMAIL:
        out["mailto"] = CONTACT_EMAIL
    return out
