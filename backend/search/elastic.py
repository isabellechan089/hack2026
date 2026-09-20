"""Elasticsearch: retrieval over trials and works (spec section 9).

Elastic is the retrieval layer, not the store of record. Its one structural
job is candidate generation for fuzzy trial-publication matching: the
deterministic scorer has existed for a while, but nothing fed it candidates
when neither identifier channel returned anything. A BM25 query built from a
trial's interventions, conditions and investigators now does.

The same two indices back a free-text search across the cohort for the
interface. Keyword retrieval only -- no embeddings -- which keeps the cluster
stateless and the results explainable: a hit is a hit because its text
contains the terms, and the explanation says which.
"""

from typing import Any, Dict, Iterable, List, Optional, Sequence

# Search enriches the app but nothing else depends on it, so a missing package
# must not stop the server from starting. Before this guard, a teammate who had
# not installed every requirement got an ImportError on launch and no app at
# all, when the only thing they were missing was one optional tab.
try:
    from elasticsearch import Elasticsearch, helpers
except ImportError:  # pragma: no cover - exercised by a test that blocks the import
    Elasticsearch = None
    helpers = None

from .. import config
from ..models.core import Paper, Trial

TRIALS = "trialtrace-trials"
WORKS = "trialtrace-works"

_client: Optional["Elasticsearch"] = None


class SearchUnavailable(RuntimeError):
    pass


def client() -> "Elasticsearch":
    global _client
    if _client is None:
        if Elasticsearch is None:
            raise SearchUnavailable(
                "The elasticsearch package is not installed. Run: "
                "venv/bin/python -m pip install -r requirements.txt")
        settings = config.elastic()
        if not settings["api_key"] or not (settings["url"] or settings["cloud_id"]):
            raise SearchUnavailable("Elasticsearch is not configured.")
        if settings["url"]:
            _client = Elasticsearch(settings["url"], api_key=settings["api_key"], request_timeout=30)
        else:
            _client = Elasticsearch(cloud_id=settings["cloud_id"], api_key=settings["api_key"], request_timeout=30)
    return _client


def available() -> bool:
    try:
        return bool(client().ping())
    except Exception:
        return False


_TEXT = {"type": "text", "analyzer": "english"}
_KW = {"type": "keyword"}

TRIAL_MAPPING = {
    "properties": {
        "nct_id": _KW, "title": _TEXT, "official_title": _TEXT, "summary": _TEXT,
        "conditions": _TEXT, "interventions": _TEXT, "outcomes": _TEXT,
        "investigators": _TEXT, "sponsor": _TEXT, "sponsor_class": _KW,
        "phases": _KW, "status": _KW, "enrollment": {"type": "integer"},
        "start_year": {"type": "integer"}, "linked_pmids": _KW,
        # Publication-gap facets, so a search can answer "how many of this
        # drug's completed trials have a paper?" directly from the index.
        "has_publication": {"type": "boolean"}, "posted_hazard_ratio": {"type": "boolean"},
        "cohort": _KW, "kind": _KW,
    }
}
WORK_MAPPING = {
    "properties": {
        "pmid": _KW, "doi": _KW, "openalex_id": _KW, "title": _TEXT, "abstract": _TEXT,
        "journal": _TEXT, "authors": _TEXT, "year": {"type": "integer"},
        "nct_ids": _KW, "publication_types": _KW, "is_retracted": {"type": "boolean"},
        "kind": _KW,
    }
}


def ensure_indices() -> None:
    """Create the indices, or add any fields the mapping has gained since.

    Adding a field to an existing mapping is allowed; changing one is not, and
    the facets need their fields declared as keyword/boolean rather than left to
    dynamic mapping, which would make them text and refuse to aggregate.
    """
    es = client()
    for name, mapping in ((TRIALS, TRIAL_MAPPING), (WORKS, WORK_MAPPING)):
        if not es.indices.exists(index=name):
            es.indices.create(index=name, mappings=mapping)
            continue
        existing = es.indices.get_mapping(index=name)[name]["mappings"].get("properties", {})
        missing = {k: v for k, v in mapping["properties"].items() if k not in existing}
        if missing:
            es.indices.put_mapping(index=name, properties=missing)


def _trial_doc(trial: Trial, linked_pmids: Sequence[str] = (), posted_hazard_ratio: Optional[bool] = None,
               cohort: Optional[str] = None) -> Dict[str, Any]:
    return {
        "_index": TRIALS, "_id": trial.nct_id, "kind": "trial",
        "has_publication": bool(linked_pmids), "posted_hazard_ratio": posted_hazard_ratio, "cohort": cohort,
        "nct_id": trial.nct_id, "title": trial.title, "official_title": trial.official_title,
        "summary": trial.brief_summary, "conditions": trial.conditions,
        "interventions": [i.get("name") for i in trial.interventions if i.get("name")],
        "outcomes": [o.measure for o in trial.primary_outcomes + trial.secondary_outcomes],
        "investigators": trial.investigators, "sponsor": trial.lead_sponsor,
        "sponsor_class": trial.lead_sponsor_class, "phases": trial.phases, "status": trial.status,
        "enrollment": trial.enrollment,
        "start_year": int(trial.start_date[:4]) if trial.start_date and len(trial.start_date) >= 4 else None,
        "linked_pmids": list(linked_pmids),
    }


def _work_doc(paper: Paper) -> Dict[str, Any]:
    return {
        "_index": WORKS, "_id": paper.pmid or paper.doi or paper.openalex_id or paper.id, "kind": "work",
        "pmid": paper.pmid, "doi": paper.doi, "openalex_id": paper.openalex_id,
        "title": paper.title, "abstract": paper.abstract, "journal": paper.journal,
        "authors": [a.name for a in paper.authors], "year": paper.publication_year,
        "nct_ids": paper.registered_trial_ids, "publication_types": paper.publication_types,
        "is_retracted": paper.is_retracted,
    }


def index_trials(trials: Iterable[Trial], links: Optional[Dict[str, Sequence[str]]] = None) -> int:
    ensure_indices()
    docs = [_trial_doc(t, (links or {}).get(t.nct_id, ())) for t in trials]
    ok, _ = helpers.bulk(client(), docs, raise_on_error=False)
    client().indices.refresh(index=TRIALS)
    return ok


def index_works(papers: Iterable[Paper]) -> int:
    ensure_indices()
    docs = [_work_doc(p) for p in papers if p.title]
    ok, _ = helpers.bulk(client(), docs, raise_on_error=False)
    client().indices.refresh(index=WORKS)
    return ok


def index_cohort(cohort: Any, fetch_papers: bool = True) -> Dict[str, int]:
    """Index a built cohort: its trials with their gap facets, and their papers.

    Papers come from PubMed in batches of fifty; the HTTP cache means a cohort
    that has already been linked costs no new requests.
    """
    from ..sources import pubmed

    trials = []
    links: Dict[str, Sequence[str]] = {}
    posted: Dict[str, bool] = {}
    for item in cohort.trials:
        trials.append(item.trial)
        links[item.trial.nct_id] = [l.pmid for l in item.links if l.pmid]
        posted[item.trial.nct_id] = any(e.is_poolable for e in item.effects)
    ensure_indices()
    docs = [_trial_doc(t, links.get(t.nct_id, ()), posted.get(t.nct_id), cohort.condition) for t in trials]
    ok_trials, _ = helpers.bulk(client(), docs, raise_on_error=False)
    client().indices.refresh(index=TRIALS)

    ok_works = 0
    if fetch_papers:
        pmids = sorted({p for ps in links.values() for p in ps})
        papers = []
        for start in range(0, len(pmids), 50):
            try:
                papers.extend(pubmed.get_papers_by_pmid(pmids[start:start + 50]))
            except Exception:
                continue
        if papers:
            ok_works = index_works(papers)
    return {"trials": ok_trials, "works": ok_works}


FACETS = {
    "kind": {"terms": {"field": "kind"}},
    "phases": {"terms": {"field": "phases", "size": 6}},
    "sponsor_class": {"terms": {"field": "sponsor_class", "size": 6}},
    "has_publication": {"terms": {"field": "has_publication"}},
    "posted_hazard_ratio": {"terms": {"field": "posted_hazard_ratio"}},
    "is_retracted": {"terms": {"field": "is_retracted"}},
    "years": {"histogram": {"field": "year", "interval": 5, "min_doc_count": 1}},
    "start_years": {"histogram": {"field": "start_year", "interval": 5, "min_doc_count": 1}},
}


def _facets(response: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """Flatten aggregation buckets to {facet: [{value, count}]}."""
    out: Dict[str, List[Dict[str, Any]]] = {}
    for name, agg in (response.get("aggregations") or {}).items():
        buckets = []
        for b in agg.get("buckets", []):
            value = b.get("key_as_string", b.get("key"))
            if isinstance(value, float) and value.is_integer():
                value = int(value)
            buckets.append({"value": value, "count": b.get("doc_count", 0)})
        if buckets:
            out[name] = buckets
    return out


def _hits(response: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for hit in response.get("hits", {}).get("hits", []):
        doc = dict(hit["_source"])
        doc["_score"] = hit.get("_score")
        doc["_index"] = hit.get("_index")
        if "highlight" in hit:
            doc["_highlight"] = hit["highlight"]
        out.append(doc)
    return out


def search(query: str, index: str = "{},{}".format(TRIALS, WORKS), size: int = 10,
           kind: Optional[str] = None, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Free-text search across trials and works, with highlighted matches."""
    return search_with_facets(query, index=index, size=size, kind=kind, filters=filters)["hits"]


def search_with_facets(query: str, index: str = "{},{}".format(TRIALS, WORKS), size: int = 10,
                       kind: Optional[str] = None, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Hits plus the facet counts over everything that matched, not only the page.

    The facets are what turn a keyword search into an answer: "pembrolizumab"
    returns not just twelve documents but how many matching trials have a
    publication and how many posted a hazard ratio.
    """
    must: List[Dict[str, Any]] = [{"multi_match": {
        "query": query, "type": "best_fields",
        "fields": ["title^3", "official_title^2", "abstract", "summary", "conditions^2",
                   "interventions^2", "outcomes", "investigators", "authors", "sponsor", "journal"],
    }}]
    filter_clauses: List[Dict[str, Any]] = []
    if kind in ("trial", "work"):
        filter_clauses.append({"term": {"kind": kind}})
    for field, value in (filters or {}).items():
        if value is None or value == "":
            continue
        filter_clauses.append({"term": {field: value}})
    body_query: Dict[str, Any] = {"bool": {"must": must}}
    if filter_clauses:
        body_query["bool"]["filter"] = filter_clauses
    response = client().search(
        index=index, size=size, query=body_query, aggs=FACETS, track_total_hits=True,
        highlight={"fields": {"title": {}, "abstract": {"fragment_size": 160}, "summary": {"fragment_size": 160}}},
    )
    total = response.get("hits", {}).get("total", {})
    return {
        "hits": _hits(response),
        "facets": _facets(response),
        "total": total.get("value", 0) if isinstance(total, dict) else total,
    }


def candidates_for_trial(trial: Trial, size: int = 20, exclude_pmids: Sequence[str] = ()) -> List[Dict[str, Any]]:
    """Works that could report this trial, for the deterministic scorer to judge.

    Interventions carry the most weight: a paper about the same drug in the
    same disease is a candidate; a paper about the disease alone is not.
    """
    interventions = [i.get("name") for i in trial.interventions if i.get("name")]
    should: List[Dict[str, Any]] = []
    for name in interventions[:6]:
        should.append({"match": {"title": {"query": name, "boost": 3}}})
        should.append({"match": {"abstract": {"query": name, "boost": 2}}})
    for condition in trial.conditions[:4]:
        should.append({"multi_match": {"query": condition, "fields": ["title^2", "abstract"]}})
    for person in trial.investigators[:5]:
        should.append({"match": {"authors": {"query": person, "boost": 2}}})
    if trial.official_title:
        should.append({"match": {"title": {"query": trial.official_title, "boost": 1}}})
    if not should:
        return []
    query: Dict[str, Any] = {"bool": {"should": should, "minimum_should_match": 1}}
    if exclude_pmids:
        query["bool"]["must_not"] = [{"terms": {"pmid": list(exclude_pmids)}}]
    response = client().search(index=WORKS, size=size, query=query,
                               highlight={"fields": {"title": {}, "abstract": {"fragment_size": 120}}})
    return _hits(response)


def stats() -> Dict[str, Any]:
    es = client()
    out = {}
    for name in (TRIALS, WORKS):
        out[name] = es.count(index=name)["count"] if es.indices.exists(index=name) else 0
    return out
