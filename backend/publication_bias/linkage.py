"""Link registry trials to the published record, and measure what is missing.

Implements steps 3-5 of the hero pipeline. Three independent linkage channels
are tried in order of authority, because a false "unpublished" verdict is the
most damaging error this system can make (section 19, rule 5):

  1. registry_reference -- the ClinicalTrials.gov record lists a PMID.
  2. pubmed_si          -- PubMed indexes the NCT id as a secondary source id,
                           which catches publications the registry never listed.
  3. fuzzy              -- deterministic metadata scoring, used only when
                           neither identifier channel returns anything.

A trial with no link from any channel is reported as "no publication
identified", never as "unpublished".
"""

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from ..models.core import Paper, Trial
from ..models.effects import EffectEstimate
from ..sources import openalex, pubmed
from ..sources.http import SourceError

# Linkage channels, most authoritative first.
REGISTRY_REFERENCE = "nct_registry_reference"
PUBMED_SECONDARY_ID = "nct_pubmed_si"
FUZZY = "fuzzy"

# Step 5 categories. A and B differ only in whether the result reached the
# literature, which is what makes them a test of publication selection.
CATEGORY_A = "published_with_result"       # publication identified + usable result
CATEGORY_B = "registry_only_with_result"   # no publication identified + usable result
CATEGORY_C = "no_usable_result"            # no usable effect estimate, either way

CATEGORY_LABELS = {
    CATEGORY_A: "Usable result, publication identified",
    CATEGORY_B: "Usable result, no publication identified",
    CATEGORY_C: "No usable effect estimate for this endpoint",
}

# C is not one thing, and saying "no publication" about it was wrong: most of
# these trials do have publications. What they lack is an effect estimate this
# analysis can pool. The reasons differ in what could be done about them.
REASON_NO_ANALYSIS = "no_analysis_posted"        # results posted, but no analysis
REASON_OTHER_MEASURE = "incomparable_measure"    # odds ratio, response rate, ...
REASON_OTHER_ENDPOINT = "other_endpoint"         # a hazard ratio, different endpoint
REASON_NO_VARIANCE = "no_confidence_interval"    # point estimate with no interval

REASON_LABELS = {
    REASON_NO_ANALYSIS: "Results posted without any statistical analysis",
    REASON_OTHER_MEASURE: "Reported on a scale that cannot be pooled with hazard ratios",
    REASON_OTHER_ENDPOINT: "Hazard ratio posted, but for a different endpoint",
    REASON_NO_VARIANCE: "Hazard ratio posted without a confidence interval",
}


@dataclass
class PublicationLink:
    """One trial-publication link, with the evidence that produced it."""

    nct_id: str
    pmid: Optional[str] = None
    doi: Optional[str] = None
    openalex_id: Optional[str] = None
    title: str = ""
    publication_date: Optional[str] = None
    citation_count: Optional[int] = None
    is_retracted: bool = False
    match_method: str = FUZZY
    match_score: float = 0.0
    nct_exact: bool = False
    features: Dict[str, float] = field(default_factory=dict)
    evidence: List[str] = field(default_factory=list)
    llm_used: bool = False
    verified: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CohortTrial:
    """A registry trial with its publication links and its posted results."""

    trial: Trial
    effects: List[EffectEstimate] = field(default_factory=list)
    links: List[PublicationLink] = field(default_factory=list)

    @property
    def has_publication(self) -> bool:
        return bool(self.links)

    @property
    def poolable_effects(self) -> List[EffectEstimate]:
        return [effect for effect in self.effects if effect.is_poolable]

    def best_effect(self, endpoint_class: str = "os") -> Optional[EffectEstimate]:
        """The trial's estimate for one endpoint, preferring a primary outcome.

        Pooling needs at most one estimate per trial, or a trial reporting the
        same endpoint several ways would be counted repeatedly.
        """
        candidates = [
            effect
            for effect in self.poolable_effects
            if effect.endpoint_class == endpoint_class
        ]
        if not candidates:
            return None
        candidates.sort(
            key=lambda effect: (
                effect.outcome_type != "PRIMARY",  # primary outcomes first
                effect.standard_error or float("inf"),  # then most precise
            )
        )
        return candidates[0]

    def category(self, endpoint_class: str = "os") -> str:
        has_result = self.best_effect(endpoint_class) is not None
        if not has_result:
            return CATEGORY_C
        return CATEGORY_A if self.has_publication else CATEGORY_B

    def missing_reason(self, endpoint_class: str = "os") -> Optional[str]:
        """Why this trial has no poolable estimate, when it has none."""
        if self.best_effect(endpoint_class) is not None:
            return None
        if not self.effects:
            return REASON_NO_ANALYSIS
        if any(e.is_poolable for e in self.effects):
            return REASON_OTHER_ENDPOINT
        hazard = [e for e in self.effects if e.measure == "hazard_ratio"]
        if hazard and all((e.standard_error or 0) <= 0 for e in hazard):
            return REASON_NO_VARIANCE
        return REASON_OTHER_MEASURE

    def to_dict(self, endpoint_class: str = "os") -> Dict[str, Any]:
        effect = self.best_effect(endpoint_class)
        return {
            "nct_id": self.trial.nct_id,
            "title": self.trial.title,
            "phases": self.trial.phases,
            "status": self.trial.status,
            "enrollment": self.trial.enrollment,
            "lead_sponsor": self.trial.lead_sponsor,
            "sponsor_type": sponsor_type(self.trial),
            "start_date": self.trial.start_date,
            "completion_date": self.trial.completion_date,
            "conditions": self.trial.conditions,
            "official_title": self.trial.official_title,
            "brief_summary": self.trial.brief_summary,
            "interventions": self.trial.interventions,
            "investigators": self.trial.investigators,
            "primary_outcomes": [{"measure": o.measure, "time_frame": o.time_frame} for o in self.trial.primary_outcomes],
            "secondary_outcomes": [{"measure": o.measure, "time_frame": o.time_frame} for o in self.trial.secondary_outcomes],
            "linked_references": self.trial.linked_references,
            "category": self.category(endpoint_class),
            "missing_reason": self.missing_reason(endpoint_class),
            "has_publication": self.has_publication,
            "links": [link.to_dict() for link in self.links],
            "effect": effect.to_dict() if effect else None,
            # Every posted estimate, so a saved cohort can still explain why a
            # trial has no poolable result rather than only that it has none.
            "effects": [e.to_dict() for e in self.effects],
            "effect_count": len(self.effects),
            "poolable_effect_count": len(self.poolable_effects),
            "registry_url": "https://clinicaltrials.gov/study/{}".format(self.trial.nct_id),
        }


# Industry sponsors dominate registry postings and behave differently from
# academic ones, so sponsor class is a covariate in the publication model.
_INDUSTRY_HINTS = (
    "inc", "ltd", "llc", "corp", "gmbh", "pharma", "pharmaceutic", "therapeutic",
    "biosciences", "bioscience", "laboratories", "s.a", "co.", "ag", "plc",
)
_ACADEMIC_HINTS = (
    "university", "universit", "hospital", "institute", "college", "school",
    "center", "centre", "clinic", "foundation", "trust", "nhs", "cancer network",
    "group", "consortium", "national", "ministry", "nci", "nih",
)


def sponsor_type(trial: Trial) -> str:
    """Classify the lead sponsor, preferring the registry's own label.

    ClinicalTrials.gov publishes a `class` for the lead sponsor (INDUSTRY, NIH,
    OTHER_GOV, NETWORK, OTHER). Using it beats guessing from the sponsor name;
    the name heuristic below is only a fallback for records that omit it.
    """
    declared = (trial.lead_sponsor_class or "").upper()
    if declared == "INDUSTRY":
        return "INDUSTRY"
    if declared in ("NIH", "OTHER_GOV", "NETWORK", "INDIV", "OTHER", "FED", "UNKNOWN"):
        return "NON_INDUSTRY"

    name = (trial.lead_sponsor or "").lower()
    if not name:
        return "UNKNOWN"
    if any(hint in name for hint in _INDUSTRY_HINTS):
        return "INDUSTRY"
    if any(hint in name for hint in _ACADEMIC_HINTS):
        return "NON_INDUSTRY"
    return "UNKNOWN"


def _link_from_paper(
    nct_id: str, paper: Paper, method: str, score: float, evidence: str
) -> PublicationLink:
    return PublicationLink(
        nct_id=nct_id,
        pmid=paper.pmid,
        doi=paper.doi,
        openalex_id=paper.openalex_id,
        title=paper.title,
        publication_date=paper.publication_date,
        citation_count=paper.citation_count,
        is_retracted=paper.is_retracted,
        match_method=method,
        match_score=score,
        nct_exact=method in (REGISTRY_REFERENCE, PUBMED_SECONDARY_ID),
        evidence=[evidence],
    )


def find_links(trial: Trial, use_fuzzy: bool = False) -> List[PublicationLink]:
    """Find publications for one trial across the three channels."""
    links: Dict[str, PublicationLink] = {}

    # Channel 1: the registry's own reference list.
    registry_pmids = {
        ref["pmid"]: ref.get("type", "") for ref in trial.linked_references if ref.get("pmid")
    }

    # Channel 2: PubMed's secondary-source-id index.
    si_pmids: List[str] = []
    try:
        si_pmids = pubmed.search_by_nct_id(trial.nct_id)
    except SourceError:
        pass

    all_pmids = list(registry_pmids) + [p for p in si_pmids if p not in registry_pmids]
    if not all_pmids and not use_fuzzy:
        return []

    papers = {paper.pmid: paper for paper in pubmed.get_papers_by_pmid(all_pmids) if paper.pmid}

    for pmid in all_pmids:
        paper = papers.get(pmid)
        if paper is None:
            continue
        if pmid in registry_pmids:
            method = REGISTRY_REFERENCE
            link_type = registry_pmids[pmid] or "linked"
            evidence = "ClinicalTrials.gov record {} lists PMID {} as a {} reference.".format(
                trial.nct_id, pmid, link_type
            )
            score = 0.95 if link_type == "RESULT" else 0.9
        else:
            method = PUBMED_SECONDARY_ID
            evidence = "PubMed indexes PMID {} under registry identifier {}.".format(
                pmid, trial.nct_id
            )
            score = 1.0
        # A publication that declares the NCT id itself is the strongest evidence.
        if trial.nct_id.upper() in [n.upper() for n in paper.registered_trial_ids]:
            score = 1.0
            evidence += " The publication declares this identifier."
        links[pmid] = _link_from_paper(trial.nct_id, paper, method, score, evidence)

    return list(links.values())


def enrich_with_openalex(cohort: Sequence[CohortTrial]) -> int:
    """Attach OpenAlex ids, citation counts and retraction flags to every link.

    OpenAlex is the scholarly graph the secondary features run on, but its PMID
    coverage is incomplete. A link that OpenAlex cannot resolve keeps its PubMed
    identity and is never downgraded to "no publication".
    """
    pmids = [link.pmid for item in cohort for link in item.links if link.pmid]
    if not pmids:
        return 0
    works = openalex.get_works_by_pmid(sorted(set(pmids)))
    resolved = 0
    for item in cohort:
        for link in item.links:
            work = works.get(link.pmid or "")
            if work is None:
                continue
            link.openalex_id = work.openalex_id
            link.citation_count = work.citation_count
            link.is_retracted = work.is_retracted
            link.doi = link.doi or work.doi
            resolved += 1
    return resolved


def find_links_bulk(trials: Sequence[Trial], chunk: int = 50) -> Dict[str, List[PublicationLink]]:
    """Link a whole cohort to the published record in a handful of requests.

    Doing this per trial costs two PubMed calls each, which is four minutes for
    a 400-trial cohort and makes an on-demand analysis impossible. Both calls
    batch: one search covers fifty registry identifiers, and records are fetched
    fifty at a time, so the same cohort resolves in roughly twenty requests.

    The channels are unchanged -- registry reference list and PubMed's
    secondary-id index -- only the number of round trips is.
    """
    by_nct: Dict[str, List[PublicationLink]] = {t.nct_id: [] for t in trials}
    registry_pmids: Dict[str, Dict[str, str]] = {
        t.nct_id: {ref["pmid"]: ref.get("type", "") for ref in t.linked_references if ref.get("pmid")}
        for t in trials
    }

    wanted: List[str] = []
    seen = set()
    for mapping in registry_pmids.values():
        for pmid in mapping:
            if pmid not in seen:
                seen.add(pmid)
                wanted.append(pmid)

    try:
        for pmid in pubmed.search_by_nct_ids([t.nct_id for t in trials], chunk=chunk):
            if pmid not in seen:
                seen.add(pmid)
                wanted.append(pmid)
    except SourceError:
        pass

    papers: Dict[str, Paper] = {}
    for start in range(0, len(wanted), chunk):
        try:
            for paper in pubmed.get_papers_by_pmid(wanted[start : start + chunk]):
                if paper.pmid:
                    papers[paper.pmid] = paper
        except SourceError:
            continue

    # Attribution uses the databank field only. A batched search returns one
    # merged list, and an identifier that appears merely in a paper's abstract
    # prose -- a trial it compares against, say -- would otherwise be read as a
    # publication reporting that trial.
    declared: Dict[str, List[str]] = {}
    for paper in papers.values():
        for nct in paper.databank_trial_ids:
            declared.setdefault(nct.upper(), []).append(paper.pmid or "")

    for trial in trials:
        nct = trial.nct_id
        links: Dict[str, PublicationLink] = {}
        for pmid, link_type in registry_pmids.get(nct, {}).items():
            paper = papers.get(pmid)
            if paper is None:
                continue
            score = 0.95 if link_type == "RESULT" else 0.9
            evidence = "ClinicalTrials.gov record {} lists PMID {} as a {} reference.".format(
                nct, pmid, link_type or "linked")
            if nct.upper() in [n.upper() for n in paper.registered_trial_ids]:
                score = 1.0
                evidence += " The publication declares this identifier."
            links[pmid] = _link_from_paper(nct, paper, REGISTRY_REFERENCE, score, evidence)

        for pmid in declared.get(nct.upper(), []):
            if pmid in links or pmid not in papers:
                continue
            links[pmid] = _link_from_paper(
                nct, papers[pmid], PUBMED_SECONDARY_ID, 1.0,
                "PubMed indexes PMID {} under registry identifier {}.".format(pmid, nct))

        by_nct[nct] = list(links.values())
    return by_nct
