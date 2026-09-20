"""Classify *how* a publication relates to the trial it declares.

A registry identifier proves that a paper concerns a trial. It does not say
whether the paper reports that trial's results. Registry reference lists mix
primary results papers, long-term follow-ups, secondary analyses and papers that
merely use the trial as an example, and all of them declare the same NCT id.

Ranking purely by "declares the identifier" therefore puts a methods paper next
to the primary results paper. This module separates them with explicit rules, so
the distinction stays inspectable rather than becoming another opaque score.
"""

import re
from typing import List, Optional, Tuple

from ..models.comparison import MATCH, TrialPublicationComparison
from ..models.core import Paper, Trial
from ..models.matching import TrialPaperMatch
from .trial_paper_matcher import _normalize_person

PRIMARY_RESULTS = "primary_results"
SECONDARY_ANALYSIS = "secondary_analysis"
FOLLOW_UP = "follow_up"
MENTIONS_TRIAL = "mentions_trial"

ROLE_LABELS = {
    PRIMARY_RESULTS: "Reports registered primary outcome",
    SECONDARY_ANALYSIS: "Secondary or sub-study analysis",
    FOLLOW_UP: "Extended follow-up of earlier results",
    MENTIONS_TRIAL: "References the trial without reporting its outcomes",
}

_FOLLOW_UP_PATTERNS = (
    r"\b\d+[- ]year\b", r"\blong[- ]term\b", r"\bfollow[- ]?up\b",
    r"\bextended\b", r"\bfinal analysis\b", r"\bupdated\b",
)
_SECONDARY_PATTERNS = (
    r"\bsecondary analysis\b", r"\bpost[- ]hoc\b", r"\bexploratory analysis\b",
    r"\bsubgroup\b", r"\bsub[- ]study\b", r"\bquality[- ]of[- ]life\b",
    r"\bpatient[- ]reported\b", r"\bbiomarker\b", r"\bcost[- ]effectiveness\b",
    r"\bindirect comparison\b", r"\bpooled analysis\b", r"\bmeta[- ]analysis\b",
)

_TRIAL_PUBLICATION_TYPES = {
    "randomized controlled trial",
    "clinical trial, phase i",
    "clinical trial, phase ii",
    "clinical trial, phase iii",
    "clinical trial, phase iv",
    "clinical trial",
}


def _matches_any(text: str, patterns) -> Optional[str]:
    lowered = (text or "").lower()
    for pattern in patterns:
        found = re.search(pattern, lowered)
        if found:
            return found.group(0)
    return None


def classify(
    trial: Trial,
    paper: Paper,
    comparison: TrialPublicationComparison,
    match: Optional[TrialPaperMatch] = None,
) -> Tuple[str, float, List[str]]:
    """Return (role, rank_score, reasons).

    `rank_score` orders candidate publications for display. It is a ranking aid
    only -- the role and its reasons are what the interface should show.
    """
    reasons: List[str] = []

    # A reporting role is a claim about a publication reporting *this* trial, so
    # it is only meaningful once the link itself is credible. Endpoint names are
    # generic -- "overall survival" appears in most oncology abstracts -- so
    # without a declared identifier, outcome coverage proves nothing about
    # which trial the paper reports.
    link_is_credible = match is None or match.basis == "identifier" or match.score >= 0.75
    if match is not None and not link_is_credible:
        return (
            MENTIONS_TRIAL,
            0.0,
            [
                "Link to {} is inferred with {} confidence (score {:.2f}); too weak to "
                "attribute any reporting role to this publication.".format(
                    trial.nct_id, match.confidence, match.score
                )
            ],
        )

    # How much of the registered primary endpoint set did we actually find?
    primary_rows = [
        row for row in comparison.fields if row.field_name.startswith("Primary outcome:")
    ]
    covered = [row for row in primary_rows if row.status == MATCH]
    coverage = len(covered) / float(len(primary_rows)) if primary_rows else 0.0
    if primary_rows:
        reasons.append(
            "Reports {} of {} registered primary outcome(s).".format(
                len(covered), len(primary_rows)
            )
        )

    # Does a registry investigator appear on the author list?
    registry = {_normalize_person(n) for n in trial.investigators} - {""}
    authors = {_normalize_person(a.name) for a in paper.authors} - {""}
    investigator_overlap = bool(registry & authors)
    if registry and authors:
        reasons.append(
            "Shares author(s) with the registry investigator list."
            if investigator_overlap
            else "No registry investigator appears on the author list."
        )

    is_trial_report = any(
        pub_type.lower() in _TRIAL_PUBLICATION_TYPES for pub_type in paper.publication_types
    )
    if is_trial_report:
        reasons.append(
            "Indexed by PubMed as a clinical trial report ({}).".format(
                ", ".join(paper.publication_types[:2])
            )
        )

    haystack = "{} {}".format(paper.title, paper.abstract or "")
    follow_up_hit = _matches_any(haystack, _FOLLOW_UP_PATTERNS)
    secondary_hit = _matches_any(paper.title, _SECONDARY_PATTERNS) or _matches_any(
        haystack, _SECONDARY_PATTERNS
    )

    designated_result = any(
        ref.get("pmid") == paper.pmid and ref.get("type") == "RESULT"
        for ref in trial.linked_references
    )
    if designated_result:
        reasons.append("Designated by the sponsor as a results publication in the registry.")

    # Decide the role. Order matters: the narrower descriptions win.
    if not investigator_overlap and coverage == 0.0 and not designated_result:
        role = MENTIONS_TRIAL
        reasons.append(
            "Declares the registry identifier but shows no sign of reporting the "
            "trial's own outcomes."
        )
    elif secondary_hit:
        role = SECONDARY_ANALYSIS
        reasons.append("Text signals a secondary analysis ('{}').".format(secondary_hit))
    elif follow_up_hit and coverage > 0:
        role = FOLLOW_UP
        reasons.append("Text signals extended follow-up ('{}').".format(follow_up_hit))
    elif coverage > 0 or designated_result:
        role = PRIMARY_RESULTS
    else:
        role = MENTIONS_TRIAL

    rank = (
        coverage * 0.45
        + (0.20 if investigator_overlap else 0.0)
        + (0.15 if is_trial_report else 0.0)
        + (0.20 if designated_result else 0.0)
    )
    if role == PRIMARY_RESULTS:
        rank += 0.15
    elif role == MENTIONS_TRIAL:
        rank -= 0.25

    return role, round(max(0.0, min(1.0, rank)), 3), reasons
