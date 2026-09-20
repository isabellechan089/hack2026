"""Europe PMC adapter: open full text for the papers that have it.

Registry postings are often incomplete -- most completed trials post outcome
tables with no analysis -- while the paper usually reports the hazard ratio in
its results section. Europe PMC serves the full text of open-access articles
as XML, which is how those estimates become recoverable.

Two things are deliberate here:
  * availability is checked in batches (one query covers many PMIDs), so a
    cohort can be surveyed cheaply before any full text is fetched;
  * the text is reduced to the sentences that could carry a hazard ratio
    before anything downstream sees it. A results section is a few dozen
    sentences; the article is thousands of words. Sending the whole article to
    a language model would cost roughly twenty times as much for no more
    information.
"""

import json
import os
import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, Iterable, List, Optional

from .http import CACHE_DIR, SourceError, get_json, get_text

API = "https://www.ebi.ac.uk/europepmc/webservices/rest"

# Full-text fetches that fail are remembered, because Europe PMC is slow (tens
# of seconds per article) and the shared HTTP cache only stores successes. Without
# this, every pass over a cohort re-attempted the same unavailable articles.
_MISSES = os.path.join(CACHE_DIR, "europepmc_misses.json")


def _load_misses() -> Dict[str, str]:
    try:
        with open(_MISSES, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def _remember_miss(pmcid: str, reason: str) -> None:
    misses = _load_misses()
    misses[pmcid] = reason
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(_MISSES, "w", encoding="utf-8") as handle:
        json.dump(misses, handle)

# Cue words that mark a sentence as possibly carrying a hazard ratio.
#
# The abbreviation alternation is case-sensitive on purpose: lowercase "hr" is
# an hour in a pharmacokinetics paper, not a hazard ratio. The optional leading
# letter catches "aHR" and "cHR", the trailing "s?" catches "HRs", and HR-QoL
# (health-related quality of life) is excluded because it shares the
# abbreviation and nothing else.
_HR_CUE = re.compile(
    r"\bhazard[ -]?ratios?\b"
    r"|(?-i:\b[a-zA-Z]?HRs?\b)(?![ -]?QoL)"
    r"|\bcox\b"
    r"|\bstratified\b",
    re.IGNORECASE,
)

# Lancet journals set decimals with a middle dot ("0·65") and publish a large
# share of phase III oncology trials, so a period-only pattern skips them.
_NUMBER = re.compile(r"\d[.\u00b7]\d")

# A hazard ratio in a figure caption can be terser than a prose sentence:
# "HR 0.65 (0.50-0.85)" is twenty characters and still a complete finding.
_MIN_SENTENCE = 12

# Tables are worth reading but not worth paying for whole; an outcome table
# carries its estimates near the top, and a long one is mostly per-site counts.
_MAX_TABLE_CHARS = 1500


def availability(pmids: Iterable[str], chunk: int = 25) -> Dict[str, Dict[str, Any]]:
    """For each PMID: whether full text exists, and its PMCID if so."""
    wanted = [str(p).strip() for p in pmids if str(p).strip()]
    out: Dict[str, Dict[str, Any]] = {}
    for start in range(0, len(wanted), chunk):
        batch = wanted[start : start + chunk]
        query = "(" + " OR ".join("EXT_ID:{}".format(p) for p in batch) + ") AND SRC:MED"
        try:
            payload = get_json(
                "{}/search".format(API),
                {"query": query, "format": "json", "resultType": "core", "pageSize": chunk},
            )
        except SourceError:
            continue
        for record in payload.get("resultList", {}).get("result", []):
            pmid = str(record.get("pmid") or record.get("id") or "")
            if not pmid:
                continue
            out[pmid] = {
                "pmcid": record.get("pmcid"),
                "open_access": record.get("isOpenAccess") == "Y",
                "full_text": bool(record.get("fullTextIdList")),
                "title": record.get("title"),
            }
    return out


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def full_text(pmcid: str) -> Optional[Dict[str, Any]]:
    """Plain text of an article, split into sections where the XML marks them."""
    if not pmcid:
        return None
    if pmcid in _load_misses():
        return None
    try:
        xml = get_text("{}/{}/fullTextXML".format(API, pmcid), accept="application/xml")
    except SourceError as exc:
        _remember_miss(pmcid, "fetch: {}".format(str(exc)[:80]))
        return None
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        _remember_miss(pmcid, "parse")
        return None

    sections: List[Dict[str, str]] = []
    for sec in root.iter("sec"):
        title = _clean("".join(sec.find("title").itertext())) if sec.find("title") is not None else ""
        body = _clean(" ".join("".join(p.itertext()) for p in sec.findall("p")))
        if body:
            sections.append({"title": title, "text": body})
    body_all = _clean(" ".join("".join(p.itertext()) for p in root.iter("p")))

    # Figure captions carry the headline estimate more often than they look as
    # though they would -- a Kaplan-Meier panel is captioned with its hazard
    # ratio -- and nothing above reaches them, because `sec.findall("p")` does
    # not descend into <fig><caption>.
    for figure in root.iter("fig"):
        caption = _clean(" ".join(figure.itertext()))
        if caption:
            sections.append({"title": "figure", "text": caption})

    # Tables hold the secondary-endpoint estimates. Cells have to be joined with
    # a separator: concatenating them welds each header to the row beneath it
    # ("EndpointHazard ratio95% CI"), which destroys the word boundaries the cue
    # pattern matches on, so a table that plainly says "Hazard ratio" stopped
    # qualifying as a place a hazard ratio might be.
    for table in root.iter("table-wrap"):
        cells = [_clean("".join(cell.itertext()))
                 for cell in table.iter() if cell.tag in ("td", "th")]
        text = " | ".join(cell for cell in cells if cell)
        if text:
            label = _clean(" ".join(
                "".join(part.itertext())
                for part in list(table.iter("label")) + list(table.iter("caption"))))
            text = "{} {}".format(label, text).strip()
        else:
            # No marked-up cells (some publishers ship tables as graphics);
            # fall back to whatever text the wrapper carries.
            text = _clean("".join(table.itertext()))
        if text:
            sections.append({"title": "table", "text": text[:_MAX_TABLE_CHARS]})

    return {"pmcid": pmcid, "sections": sections, "text": body_all, "chars": len(body_all)}


def hazard_ratio_sentences(article: Dict[str, Any], limit: int = 40) -> List[str]:
    """Only the sentences that could carry a hazard ratio, results first.

    This is the retrieval step that keeps model input small: a cue word plus a
    decimal number, taken from results and abstract sections before anything
    else, capped so a long paper cannot blow the budget.
    """
    ordered: List[str] = []
    seen = set()

    def take(text: str) -> None:
        for sentence in re.split(r"(?<=[.;])\s+(?=[A-Z(])", text or ""):
            s = _clean(sentence)
            if len(s) < _MIN_SENTENCE or s in seen:
                continue
            if _HR_CUE.search(s) and _NUMBER.search(s):
                seen.add(s)
                ordered.append(s)

    sections = article.get("sections") or []
    priority = [s for s in sections if re.search(r"result|abstract|efficacy|survival|outcome", s["title"], re.I)]
    rest = [s for s in sections if s not in priority]
    for sec in priority + rest:
        take(sec["text"])
    if not ordered:
        take(article.get("text", ""))
    return ordered[:limit]
