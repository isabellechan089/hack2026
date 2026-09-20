"""Load .env once, before anything reads the environment.

A tiny loader rather than a dependency: the file format we need is
KEY=value with optional quotes and # comments, and nothing here should
fail if the file is absent.

Real environment variables always win, so a shell export or a CI secret
overrides the file rather than the other way round.
"""

import os
from typing import Optional

_LOADED = False


def load_env(path: Optional[str] = None) -> None:
    global _LOADED
    if _LOADED:
        return
    _LOADED = True
    path = path or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"
    )
    try:
        with open(path, "r", encoding="utf-8") as handle:
            lines = handle.readlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value


load_env()


def get(*names: str, default: str = "") -> str:
    """First of `names` that is set. Lets us accept more than one spelling."""
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return default


# The key is commonly written either way; accept both rather than fail silently.
def openai_key() -> str:
    return get("OPENAI_API_KEY", "OPEN_AI_API_KEY")


def elastic() -> dict:
    """Elastic connection settings, accepting either a Cloud ID or an endpoint URL.

    The two are easy to confuse when copying from the Cloud console, so a URL
    pasted into the Cloud ID slot is used as the URL rather than rejected.
    """
    cloud_id = get("ELASTIC_CLOUD_ID")
    url = get("ELASTIC_URL")
    if cloud_id.startswith(("http://", "https://")) and not url:
        url, cloud_id = cloud_id, ""
    return {"cloud_id": cloud_id, "api_key": get("ELASTIC_API_KEY"), "url": url}
