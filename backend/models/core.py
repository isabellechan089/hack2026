"""Typed, normalized records shared across sources.

Design rules from PROJECT_CONTEXT.md sections 19-20:
  * every record keeps its raw source identifiers (NCT / DOI / PMID / OpenAlex),
  * every record records where it came from,
  * a field that the source did not provide stays `None` -- we never invent one.
"""

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


@dataclass
class Provenance:
    """Where a record came from, so any claim can be traced back."""

    source: str  # "clinicaltrials.gov" | "pubmed" | "openalex" | "crossref"
    source_id: str  # NCT id, PMID, OpenAlex id, DOI
    url: str
    retrieved_at: Optional[str] = None


@dataclass
class Outcome:
    """A registered or reported study endpoint."""

    measure: str
    description: Optional[str] = None
    time_frame: Optional[str] = None
    kind: str = "primary"  # "primary" | "secondary"


@dataclass
class Trial:
    """A clinical trial registration (ClinicalTrials.gov)."""

    nct_id: str
    title: str
    official_title: Optional[str] = None
    brief_summary: Optional[str] = None
    status: Optional[str] = None
    phases: List[str] = field(default_factory=list)
    conditions: List[str] = field(default_factory=list)
    interventions: List[Dict[str, Any]] = field(default_factory=list)
    primary_outcomes: List[Outcome] = field(default_factory=list)
    secondary_outcomes: List[Outcome] = field(default_factory=list)
    enrollment: Optional[int] = None
    enrollment_type: Optional[str] = None  # ACTUAL | ESTIMATED
    arm_count: Optional[int] = None
    allocation: Optional[str] = None  # RANDOMIZED | NON_RANDOMIZED
    masking: Optional[str] = None
    start_date: Optional[str] = None
    primary_completion_date: Optional[str] = None
    completion_date: Optional[str] = None
    lead_sponsor: Optional[str] = None
    investigators: List[str] = field(default_factory=list)
    eligibility_criteria: Optional[str] = None
    has_results: bool = False
    # PMIDs the registry itself links to this trial, with their link type.
    linked_references: List[Dict[str, str]] = field(default_factory=list)
    provenance: Optional[Provenance] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Author:
    name: str
    openalex_id: Optional[str] = None
    orcid: Optional[str] = None
    institutions: List[str] = field(default_factory=list)
    position: Optional[str] = None  # first | middle | last


@dataclass
class Paper:
    """A publication, merged from PubMed / OpenAlex / Crossref."""

    title: str
    doi: Optional[str] = None
    pmid: Optional[str] = None
    openalex_id: Optional[str] = None
    abstract: Optional[str] = None
    # Structured abstract sections keyed by their PubMed label, when present.
    abstract_sections: Dict[str, str] = field(default_factory=dict)
    journal: Optional[str] = None
    publication_date: Optional[str] = None
    publication_year: Optional[int] = None
    authors: List[Author] = field(default_factory=list)
    publication_types: List[str] = field(default_factory=list)
    # NCT ids the publication itself declares (PubMed databank or abstract text).
    registered_trial_ids: List[str] = field(default_factory=list)
    citation_count: Optional[int] = None
    is_retracted: bool = False
    retraction_status: str = "unknown"  # retracted | not_retracted | unknown
    retraction_date: Optional[str] = None
    retraction_notice_doi: Optional[str] = None
    provenance: List[Provenance] = field(default_factory=list)

    @property
    def id(self) -> str:
        """A stable identifier, preferring the most portable id available."""
        if self.doi:
            return "doi:" + self.doi
        if self.pmid:
            return "pmid:" + self.pmid
        if self.openalex_id:
            return self.openalex_id
        return "title:" + self.title[:80]

    def to_dict(self) -> Dict[str, Any]:
        out = asdict(self)
        out["id"] = self.id
        return out
