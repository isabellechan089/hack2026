"""Records for the registered-vs-published comparison (section 4)."""

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

# Status vocabulary. Deliberately descriptive: none of these words implies that
# a difference is improper. Section 4 forbids labeling differences as misconduct.
MATCH = "match"
DIFFERENCE = "difference"
NOT_FOUND = "not_found"  # registered, but not identified in the publication
NOT_REGISTERED = "not_registered"  # reported, but absent from the registration
NOT_COMPARABLE = "not_comparable"  # missing on one side, or not machine-comparable


@dataclass
class Evidence:
    """A quotable span backing one side of a comparison."""

    source: str  # "clinicaltrials.gov" | "pubmed"
    locator: str  # field path or abstract section label
    quote: str
    url: Optional[str] = None


@dataclass
class FieldComparison:
    field_name: str
    registered: Optional[str]
    published: Optional[str]
    status: str
    note: str = ""
    evidence: List[Evidence] = field(default_factory=list)


@dataclass
class TrialPublicationComparison:
    nct_id: str
    pmid: Optional[str]
    doi: Optional[str]
    trial_title: str
    paper_title: str
    match_basis: str
    match_confidence: str
    match_score: float
    fields: List[FieldComparison] = field(default_factory=list)
    # What text we were actually able to read. Stated explicitly so a
    # "not identified" result is never mistaken for "absent from the paper".
    evidence_scope: str = ""
    provenance: List[Dict[str, str]] = field(default_factory=list)

    @property
    def counts(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for item in self.fields:
            out[item.status] = out.get(item.status, 0) + 1
        return out

    def to_dict(self) -> Dict[str, Any]:
        out = asdict(self)
        out["counts"] = self.counts
        return out
