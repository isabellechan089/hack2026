"""Records describing *why* a trial and a publication were linked.

Section 19 requires that an inferred match never look like an extracted fact.
Every match therefore carries its signals, its evidence and a confidence band,
and the UI is expected to show them rather than a bare score.
"""

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class MatchSignal:
    """One piece of evidence for or against a trial<->publication match."""

    name: str
    weight: float  # contribution to the score if fully satisfied
    score: float  # 0.0 - 1.0, how well this signal is satisfied
    evidence: str  # human-readable justification, quoting the source values

    @property
    def contribution(self) -> float:
        return self.weight * self.score


@dataclass
class TrialPaperMatch:
    nct_id: str
    paper_id: str
    pmid: Optional[str] = None
    doi: Optional[str] = None
    paper_title: str = ""
    trial_title: str = ""
    score: float = 0.0
    # "identifier" when the link is declared by a source, "inferred" when we
    # computed it from overlapping metadata. Never blur these two.
    basis: str = "inferred"
    signals: List[MatchSignal] = field(default_factory=list)
    provenance: List[Dict[str, str]] = field(default_factory=list)

    @property
    def confidence(self) -> str:
        if self.basis == "identifier":
            return "high"
        if self.score >= 0.75:
            return "high"
        if self.score >= 0.45:
            return "medium"
        return "low"

    @property
    def reasons(self) -> List[str]:
        return [signal.evidence for signal in self.signals if signal.score > 0]

    def to_dict(self) -> Dict[str, Any]:
        out = asdict(self)
        out["confidence"] = self.confidence
        out["reasons"] = self.reasons
        return out
