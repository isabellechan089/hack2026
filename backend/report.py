"""Assemble the trial->publication report shared by the CLI and the HTTP API.

Keeping this here means the terminal output and the web response are built from
exactly the same records, so the demo cannot drift between the two surfaces.
"""

from typing import Any, Dict, List, Optional

from .compare.trial_publication import compare
from .matching.publication_role import ROLE_LABELS, classify
from .matching.trial_paper_matcher import (
    find_publications_for_trial,
    find_trials_for_paper,
    score_match,
)
from .models.core import Paper, Trial
from .sources import clinical_trials, pubmed


def _trial_summary(trial: Trial) -> Dict[str, Any]:
    return {
        "nct_id": trial.nct_id,
        "title": trial.title,
        "status": trial.status,
        "phases": trial.phases,
        "enrollment": trial.enrollment,
        "enrollment_type": trial.enrollment_type,
        "lead_sponsor": trial.lead_sponsor,
        "conditions": trial.conditions,
        "primary_outcomes": [outcome.measure for outcome in trial.primary_outcomes],
        "url": "https://clinicaltrials.gov/study/{}".format(trial.nct_id),
    }


def _publication_entry(trial: Trial, paper: Paper, match) -> Dict[str, Any]:
    comparison = compare(trial, paper, match)
    role, rank, reasons = classify(trial, paper, comparison, match)
    return {
        "pmid": paper.pmid,
        "doi": paper.doi,
        "title": paper.title,
        "journal": paper.journal,
        "publication_date": paper.publication_date,
        "role": role,
        "role_label": ROLE_LABELS.get(role, role),
        "role_reasons": reasons,
        "rank": rank,
        "match": match.to_dict(),
        "comparison": comparison.to_dict(),
        "url": "https://pubmed.ncbi.nlm.nih.gov/{}/".format(paper.pmid or ""),
    }


def trial_report(nct_id: str, limit: int = 8) -> Dict[str, Any]:
    """A trial, plus the publications the registry links to it, best first."""
    trial = clinical_trials.get_trial(nct_id)
    entries: List[Dict[str, Any]] = []
    for match in find_publications_for_trial(trial):
        if not match.pmid:
            continue
        paper = pubmed.get_paper_by_pmid(match.pmid)
        if paper is not None:
            entries.append(_publication_entry(trial, paper, match))
    entries.sort(key=lambda entry: entry["rank"], reverse=True)
    return {
        "trial": _trial_summary(trial),
        "publications": entries[:limit],
        "publication_count": len(entries),
        "sampling": (
            "Publications are those the ClinicalTrials.gov record itself links, "
            "ranked by how much of the registered trial each one reports. This is "
            "not a literature search."
        ),
    }


def paper_report(pmid: str) -> Dict[str, Any]:
    """A publication, plus the trial(s) it can be linked to."""
    paper = pubmed.get_paper_by_pmid(pmid)
    if paper is None:
        raise ValueError("No PubMed record found for {}.".format(pmid))
    candidates = []
    for match in find_trials_for_paper(paper):
        trial = clinical_trials.get_trial(match.nct_id)
        candidates.append(
            {
                "trial": _trial_summary(trial),
                "match": match.to_dict(),
                "comparison": compare(trial, paper, match).to_dict(),
            }
        )
    return {
        "paper": {
            "pmid": paper.pmid,
            "doi": paper.doi,
            "title": paper.title,
            "journal": paper.journal,
            "publication_date": paper.publication_date,
            "declared_trial_ids": paper.registered_trial_ids,
            "url": "https://pubmed.ncbi.nlm.nih.gov/{}/".format(paper.pmid or ""),
        },
        "candidates": candidates,
    }


def comparison_report(nct_id: str, pmid: str) -> Dict[str, Any]:
    """The full field-by-field table for one explicitly chosen pair."""
    trial = clinical_trials.get_trial(nct_id)
    paper = pubmed.get_paper_by_pmid(pmid)
    if paper is None:
        raise ValueError("No PubMed record found for {}.".format(pmid))
    match = score_match(trial, paper)
    comparison = compare(trial, paper, match)
    role, rank, reasons = classify(trial, paper, comparison, match)
    return {
        "trial": _trial_summary(trial),
        "match": match.to_dict(),
        "role": role,
        "role_label": ROLE_LABELS.get(role, role),
        "role_reasons": reasons,
        "comparison": comparison.to_dict(),
    }
