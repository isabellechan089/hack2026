"""OpenAlex adapter -- the primary scholarly dataset (spec section 8).

Resolves publications to OpenAlex works so that a matched trial inherits the
scholarly graph: citation counts, author identities, institutions and
retraction flags. Lookups are batched, because OpenAlex charges one request per
call and a cohort can hold hundreds of publications.
"""

from typing import Any, Dict, Iterable, List, Optional

from ..models.core import Author, Paper, Provenance
from .http import SourceError, get_json, polite_params

API_BASE = "https://api.openalex.org"

# Requesting only the fields we use keeps cohort-sized responses small.
WORK_FIELDS = (
    "id,doi,ids,title,display_name,publication_year,publication_date,"
    "cited_by_count,is_retracted,authorships,primary_location,type"
)


def short_id(openalex_id: Optional[str]) -> str:
    return (openalex_id or "").rstrip("/").split("/")[-1]


def _authors(work: Dict[str, Any], limit: int = 25) -> List[Author]:
    authors: List[Author] = []
    authorships = work.get("authorships") or []
    for index, authorship in enumerate(authorships[:limit]):
        author = authorship.get("author") or {}
        name = author.get("display_name")
        if not name:
            continue
        position = "middle"
        if index == 0:
            position = "first"
        elif index == len(authorships) - 1:
            position = "last"
        authors.append(
            Author(
                name=name,
                openalex_id=author.get("id"),
                orcid=author.get("orcid"),
                institutions=[
                    inst.get("display_name", "")
                    for inst in authorship.get("institutions") or []
                    if inst.get("display_name")
                ],
                position=position,
            )
        )
    return authors


def normalize_work(work: Dict[str, Any]) -> Paper:
    """Map an OpenAlex work onto the shared `Paper` model."""
    ids = work.get("ids") or {}
    doi = (work.get("doi") or "").replace("https://doi.org/", "") or None
    pmid = (ids.get("pmid") or "").rstrip("/").split("/")[-1] or None
    source = (work.get("primary_location") or {}).get("source") or {}
    return Paper(
        title=work.get("display_name") or work.get("title") or "",
        doi=doi,
        pmid=pmid,
        openalex_id=work.get("id"),
        journal=source.get("display_name"),
        publication_date=work.get("publication_date"),
        publication_year=work.get("publication_year"),
        authors=_authors(work),
        citation_count=work.get("cited_by_count"),
        is_retracted=bool(work.get("is_retracted")),
        retraction_status="retracted" if work.get("is_retracted") else "unknown",
        provenance=[
            Provenance(
                source="openalex",
                source_id=work.get("id", ""),
                url=work.get("id", ""),
            )
        ],
    )


def _batched(values: List[str], size: int) -> Iterable[List[str]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def get_works_by_pmid(pmids: List[str], batch_size: int = 40) -> Dict[str, Paper]:
    """Resolve PubMed ids to OpenAlex works, keyed by PMID.

    A PMID with no OpenAlex record is simply absent from the result; that is a
    coverage gap, not an error, and the caller decides how to report it.
    """
    wanted = [str(pmid).strip() for pmid in pmids if str(pmid).strip()]
    found: Dict[str, Paper] = {}
    for batch in _batched(wanted, batch_size):
        try:
            payload = get_json(
                "{}/works".format(API_BASE),
                polite_params(
                    {
                        "filter": "pmid:" + "|".join(batch),
                        "select": WORK_FIELDS,
                        "per-page": len(batch),
                    }
                ),
            )
        except SourceError:
            continue
        for work in payload.get("results", []):
            paper = normalize_work(work)
            if paper.pmid:
                found[paper.pmid] = paper
    return found


def get_work_by_doi(doi: str) -> Optional[Paper]:
    clean = (doi or "").replace("https://doi.org/", "").strip()
    if not clean:
        return None
    try:
        work = get_json(
            "{}/works/https://doi.org/{}".format(API_BASE, clean), polite_params()
        )
    except SourceError:
        return None
    return normalize_work(work)


def get_author_works(author_id: str, limit: int = 200) -> List[Dict[str, Any]]:
    """Works authored by one OpenAlex author, newest first.

    Used to build a reviewer's coauthorship ego network without downloading the
    global graph (spec section 6).
    """
    payload = get_json(
        "{}/works".format(API_BASE),
        polite_params(
            {
                "filter": "author.id:{}".format(short_id(author_id)),
                "select": "id,doi,display_name,publication_year,authorships",
                "per-page": min(200, limit),
                "sort": "publication_year:desc",
            }
        ),
    )
    return payload.get("results", [])


def search_authors(name: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Resolve a person's name to candidate OpenAlex author records."""
    payload = get_json(
        "{}/authors".format(API_BASE),
        polite_params({"search": name, "per-page": limit}),
    )
    return payload.get("results", [])
