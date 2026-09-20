"""Link registered trials to the publications that report them.

Follows section 8 of PROJECT_CONTEXT.md: deterministic rules first. An explicit
registry identifier settles the question outright; only when no identifier
exists do we fall back to scoring overlapping metadata, and even then the result
is labeled `inferred` and carries every signal that produced it.
"""

import re
from typing import Any, Dict, List, Optional, Sequence, Set

from ..models.core import Paper, Trial
from ..models.matching import MatchSignal, TrialPaperMatch
from ..sources import clinical_trials, pubmed

# Weights for the ambiguous case. They sum to 1.0 so `score` stays a fraction.
WEIGHTS = {
    "investigator_overlap": 0.30,
    "intervention_match": 0.25,
    "condition_match": 0.20,
    "enrollment_similarity": 0.10,
    "date_compatibility": 0.10,
    "sponsor_overlap": 0.05,
}

_STOPWORDS = {
    "a", "an", "and", "of", "the", "in", "for", "with", "versus", "vs", "study",
    "trial", "phase", "randomized", "randomised", "patients", "treatment",
}


def _tokens(text: Optional[str]) -> Set[str]:
    if not text:
        return set()
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {word for word in words if len(word) > 2 and word not in _STOPWORDS}


def _normalize_person(name: str) -> str:
    """Reduce a name to first + last so "Sapna Patel" matches "Sapna P Patel"."""
    parts = re.findall(r"[A-Za-z'-]+", (name or "").lower())
    parts = [p for p in parts if len(p) > 1]  # drop middle initials
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return "{} {}".format(parts[0], parts[-1])


def _jaccard(left: Set[str], right: Set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / float(len(left | right))


def _investigator_signal(trial: Trial, paper: Paper) -> MatchSignal:
    registry = {_normalize_person(n) for n in trial.investigators}
    registry.discard("")
    authors = {_normalize_person(a.name) for a in paper.authors}
    authors.discard("")
    shared = sorted(registry & authors)

    if not registry or not authors:
        evidence = "No investigator list available on one side; signal unused."
        score = 0.0
    elif shared:
        # Any overlap is strong; more overlap is stronger.
        score = min(1.0, 0.6 + 0.2 * len(shared))
        evidence = "Registry investigator(s) also author the publication: {}.".format(
            ", ".join(shared)
        )
    else:
        score = 0.0
        evidence = "No registry investigator appears in the author list."
    return MatchSignal("investigator_overlap", WEIGHTS["investigator_overlap"], score, evidence)


def _intervention_signal(trial: Trial, paper: Paper) -> MatchSignal:
    names: Set[str] = set()
    for item in trial.interventions:
        names |= _tokens(item.get("name"))
        for other in item.get("other_names") or []:
            names |= _tokens(other)
    haystack = _tokens(paper.title) | _tokens(paper.abstract)
    shared = sorted(names & haystack)
    score = min(1.0, len(shared) / 2.0) if shared else 0.0
    evidence = (
        "Registered intervention term(s) appear in the publication: {}.".format(
            ", ".join(shared[:5])
        )
        if shared
        else "No registered intervention term appears in the publication text."
    )
    return MatchSignal("intervention_match", WEIGHTS["intervention_match"], score, evidence)


def _condition_signal(trial: Trial, paper: Paper) -> MatchSignal:
    conditions: Set[str] = set()
    for condition in trial.conditions:
        conditions |= _tokens(condition)
    haystack = _tokens(paper.title) | _tokens(paper.abstract)
    shared = sorted(conditions & haystack)
    score = min(1.0, len(shared) / 2.0) if shared else 0.0
    evidence = (
        "Registered condition term(s) appear in the publication: {}.".format(
            ", ".join(shared[:5])
        )
        if shared
        else "No registered condition term appears in the publication text."
    )
    return MatchSignal("condition_match", WEIGHTS["condition_match"], score, evidence)


def _reported_sample_sizes(paper: Paper) -> List[int]:
    """Pull candidate participant counts out of the abstract.

    Deliberately conservative: only numbers introduced by a phrase that in
    practice denotes a study population.
    """
    text = paper.abstract or ""
    pattern = re.compile(
        r"(?:among|enrolled|randomi[sz]ed|included|analy[sz]ed|total of|n\s*=)\s*"
        r"(?:a total of\s*)?([0-9][0-9,]{1,6})",
        re.IGNORECASE,
    )
    values = []
    for match in pattern.finditer(text):
        try:
            values.append(int(match.group(1).replace(",", "")))
        except ValueError:
            continue
    return values


def _enrollment_signal(trial: Trial, paper: Paper) -> MatchSignal:
    reported = _reported_sample_sizes(paper)
    if not trial.enrollment or not reported:
        return MatchSignal(
            "enrollment_similarity",
            WEIGHTS["enrollment_similarity"],
            0.0,
            "Enrollment not comparable (missing on one side).",
        )
    best = min(reported, key=lambda value: abs(value - trial.enrollment))
    ratio = abs(best - trial.enrollment) / float(max(trial.enrollment, best))
    score = max(0.0, 1.0 - ratio * 4)  # 25% off -> 0
    evidence = "Registered enrollment {} vs closest number reported in abstract {} ({:.0%} apart).".format(
        trial.enrollment, best, ratio
    )
    return MatchSignal("enrollment_similarity", WEIGHTS["enrollment_similarity"], score, evidence)


def _date_signal(trial: Trial, paper: Paper) -> MatchSignal:
    if not trial.start_date or not paper.publication_year:
        return MatchSignal(
            "date_compatibility",
            WEIGHTS["date_compatibility"],
            0.0,
            "Dates not comparable (missing on one side).",
        )
    start_year = int(trial.start_date[:4])
    gap = paper.publication_year - start_year
    if gap < 0:
        score, verdict = 0.0, "published before the trial started"
    elif gap <= 15:
        score, verdict = 1.0, "plausible reporting lag"
    else:
        score, verdict = 0.3, "unusually long lag"
    evidence = "Trial started {}, publication year {} ({}).".format(
        start_year, paper.publication_year, verdict
    )
    return MatchSignal("date_compatibility", WEIGHTS["date_compatibility"], score, evidence)


def _sponsor_signal(trial: Trial, paper: Paper) -> MatchSignal:
    sponsor = _tokens(trial.lead_sponsor)
    affiliations: Set[str] = set()
    for author in paper.authors:
        for institution in author.institutions:
            affiliations |= _tokens(institution)
    shared = sorted(sponsor & affiliations)
    score = 1.0 if shared else 0.0
    evidence = (
        "Lead sponsor terms appear in author affiliations: {}.".format(", ".join(shared[:4]))
        if shared
        else "Lead sponsor does not appear in author affiliations."
    )
    return MatchSignal("sponsor_overlap", WEIGHTS["sponsor_overlap"], score, evidence)


def score_match(trial: Trial, paper: Paper) -> TrialPaperMatch:
    """Score a candidate pair.

    If either side declares the other's identifier the match is decided by that
    identifier and marked `identifier`; the metadata signals are still computed
    and attached as corroborating evidence, but they cannot lower the score.
    """
    signals = [
        _investigator_signal(trial, paper),
        _intervention_signal(trial, paper),
        _condition_signal(trial, paper),
        _enrollment_signal(trial, paper),
        _date_signal(trial, paper),
        _sponsor_signal(trial, paper),
    ]

    basis = "inferred"
    score = sum(signal.contribution for signal in signals)

    declared = [nct.upper() for nct in paper.registered_trial_ids]
    registry_pmids = {ref["pmid"]: ref.get("type", "") for ref in trial.linked_references}

    if trial.nct_id.upper() in declared:
        basis = "identifier"
        score = 1.0
        signals.insert(
            0,
            MatchSignal(
                "declared_registry_id",
                1.0,
                1.0,
                "The publication itself declares registry identifier {}.".format(trial.nct_id),
            ),
        )
    elif paper.pmid and paper.pmid in registry_pmids:
        basis = "identifier"
        link_type = registry_pmids[paper.pmid]
        score = 0.95 if link_type == "RESULT" else 0.9
        signals.insert(
            0,
            MatchSignal(
                "registry_reference",
                1.0,
                1.0,
                "ClinicalTrials.gov record {} lists PMID {} as a {} reference.".format(
                    trial.nct_id, paper.pmid, link_type or "linked"
                ),
            ),
        )

    return TrialPaperMatch(
        nct_id=trial.nct_id,
        paper_id=paper.id,
        pmid=paper.pmid,
        doi=paper.doi,
        paper_title=paper.title,
        trial_title=trial.title,
        score=round(score, 3),
        basis=basis,
        signals=signals,
        provenance=[
            {
                "source": "clinicaltrials.gov",
                "id": trial.nct_id,
                "url": "https://clinicaltrials.gov/study/{}".format(trial.nct_id),
            },
            {
                "source": "pubmed",
                "id": paper.pmid or "",
                "url": "https://pubmed.ncbi.nlm.nih.gov/{}/".format(paper.pmid or ""),
            },
        ],
    )


def find_publications_for_trial(
    trial: Trial, include_derived: bool = True
) -> List[TrialPaperMatch]:
    """Return scored publications for a trial, best match first.

    The registry's own reference list is the starting point, so the common case
    needs no inference at all.
    """
    wanted = [
        ref["pmid"]
        for ref in trial.linked_references
        if include_derived or ref.get("type") == "RESULT"
    ]
    papers = pubmed.get_papers_by_pmid(wanted)
    matches = [score_match(trial, paper) for paper in papers]
    matches.sort(key=lambda match: match.score, reverse=True)
    return matches


def find_trials_for_paper(paper: Paper, fallback_search: bool = True) -> List[TrialPaperMatch]:
    """Return scored trials for a publication, best match first."""
    matches: List[TrialPaperMatch] = []
    seen: Set[str] = set()

    for nct_id in paper.registered_trial_ids:
        trial = clinical_trials.get_trial(nct_id)
        matches.append(score_match(trial, paper))
        seen.add(trial.nct_id.upper())

    # Ambiguous case: nothing declared, so fall back to searching the registry
    # with the publication's own title terms and scoring what comes back.
    if not matches and fallback_search and paper.title:
        for trial in clinical_trials.search_trials(paper.title, limit=10):
            if trial.nct_id.upper() in seen:
                continue
            seen.add(trial.nct_id.upper())
            matches.append(score_match(trial, paper))

    matches.sort(key=lambda match: match.score, reverse=True)
    return matches


# --- The fuzzy cascade ---------------------------------------------------
# candidate retrieval -> deterministic scoring -> cheap adjudication -> flag.
# Thresholds are on the deterministic score; the model is only consulted in
# the band between them, and can promote a pair to "accepted" only with a
# clear verdict. Everything it touches is marked llm_used.

ACCEPT_AT = 0.75
REJECT_BELOW = 0.45


def find_publications_fuzzy(
    trial: Trial, size: int = 12, adjudicate: bool = True, exclude_pmids: Sequence[str] = ()
) -> Dict[str, Any]:
    """Candidates for a trial with no identifier link, with each one's fate."""
    from ..search import elastic
    from ..sources import pubmed as _pubmed

    try:
        hits = elastic.candidates_for_trial(trial, size=size, exclude_pmids=exclude_pmids)
    except Exception as exc:  # search down: say so rather than return "none"
        return {"retrieval": "unavailable", "error": str(exc)[:160], "candidates": []}

    pmids = [h["pmid"] for h in hits if h.get("pmid")]
    papers = {p.pmid: p for p in _pubmed.get_papers_by_pmid(pmids) if p.pmid}
    out = []
    llm_tokens = 0
    for hit in hits:
        paper = papers.get(hit.get("pmid") or "")
        if paper is None:
            continue
        match = score_match(trial, paper)
        entry = {
            "pmid": paper.pmid, "doi": paper.doi, "title": paper.title,
            "year": paper.publication_year, "retrieval_score": hit.get("_score"),
            "match": match.to_dict(), "llm": None,
        }
        # A metadata score can reject on its own, but never accept: the same
        # investigator running a sibling trial of the same drug scores highly and
        # is still a different trial. Acceptance needs a reading of the paper.
        if match.score < REJECT_BELOW:
            entry["decision"] = "rejected"
        else:
            entry["decision"] = "strong_candidate" if match.score >= ACCEPT_AT else "review"
            if adjudicate:
                try:
                    from ..llm import matching as llm_matching
                    verdict = llm_matching.adjudicate(trial, paper)
                    entry["llm"] = verdict
                    llm_tokens += verdict["tokens"]
                    if verdict["verdict"] == "reports_this_trial" and verdict["confidence"] >= 0.7:
                        entry["decision"] = "accepted_by_adjudication"
                    elif verdict["verdict"] == "different_trial" and verdict["confidence"] >= 0.7:
                        entry["decision"] = "rejected_by_adjudication"
                except Exception as exc:
                    entry["llm"] = {"error": str(exc)[:120]}
        out.append(entry)
    order = {"accepted_by_adjudication": 0, "strong_candidate": 1, "review": 2, "rejected_by_adjudication": 3, "rejected": 4}
    out.sort(key=lambda e: (order.get(e["decision"], 9), -e["match"]["score"]))
    return {
        "retrieval": "elasticsearch", "candidates": out, "llm_tokens": llm_tokens,
        "thresholds": {"accept_at": ACCEPT_AT, "reject_below": REJECT_BELOW},
        "note": (
            "Candidates come from keyword retrieval over indexed works. The deterministic "
            "score rejects clear non-matches on its own but never accepts on its own: "
            "without a declared identifier, acceptance requires a small model to read the "
            "paper against the registration. Every such match carries the model's reason "
            "and is flagged as model-assisted, never presented as an extracted fact."
        ),
    }
