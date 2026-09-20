"""Adjudicate middle-confidence trial-publication matches (spec section 3).

The deterministic scorer settles most pairs: a declared identifier accepts,
disjoint interventions reject. What is left is the band where the metadata
overlaps but does not decide -- same drug, same disease, plausible dates, and
still unclear whether this paper reports *this* trial or a sibling.

That is a reading-comprehension question, so it goes to a small model with the
trial's registration and the paper's abstract, and comes back as a verdict with
a reason. The model never creates a match on its own: it only sees pairs the
scorer already found plausible, its verdict is recorded alongside the scorer's
features, and `llm_used` is set so the two kinds of evidence are never
confused (section 19).
"""

from typing import Any, Dict

from ..models.core import Paper, Trial
from . import client

SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["reports_this_trial", "different_trial", "unclear"]},
        "confidence": {"type": "number"},
        "reason": {"type": "string"},
    },
    "required": ["verdict", "confidence", "reason"],
    "additionalProperties": False,
}

SYSTEM = (
    "You decide whether a publication reports the results of a specific registered "
    "clinical trial. Compare the registration (design, arms, interventions, "
    "enrollment, dates, investigators) with the paper's abstract. Answer "
    "'reports_this_trial' only if the paper describes this study, not merely the same "
    "drug or disease. Sibling trials of the same drug are 'different_trial'. If the "
    "abstract does not say enough, answer 'unclear'. Give one sentence of reason "
    "citing the specific detail that decided it."
)


def _trial_card(trial: Trial) -> str:
    outcomes = "; ".join(o.measure for o in trial.primary_outcomes[:3])
    interventions = ", ".join(i.get("name", "") for i in trial.interventions[:6] if i.get("name"))
    return (
        "Registry {}\nTitle: {}\nPhase: {}\nInterventions: {}\nConditions: {}\n"
        "Primary outcomes: {}\nEnrollment: {}\nStart: {}  Completion: {}\nInvestigators: {}\nSponsor: {}"
    ).format(
        trial.nct_id, trial.official_title or trial.title, "/".join(trial.phases) or "?",
        interventions, ", ".join(trial.conditions[:4]), outcomes, trial.enrollment,
        trial.start_date, trial.completion_date, ", ".join(trial.investigators[:4]),
        trial.lead_sponsor,
    )


def _paper_card(paper: Paper) -> str:
    # Only the abstract sections that carry design facts, not the whole record.
    keep = ("METHODS", "DESIGN", "PARTICIPANTS", "INTERVENTIONS", "RESULTS", "TRIAL REGISTRATION")
    sections = paper.abstract_sections or {}
    picked = [v for k, v in sections.items() if any(w in k.upper() for w in keep)]
    body = " ".join(picked) if picked else (paper.abstract or "")
    return "Title: {}\nJournal: {} ({})\nAuthors: {}\nAbstract: {}".format(
        paper.title, paper.journal, paper.publication_year,
        ", ".join(a.name for a in paper.authors[:6]), body[:2400],
    )


def adjudicate(trial: Trial, paper: Paper) -> Dict[str, Any]:
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": _trial_card(trial) + "\n\n---\n\n" + _paper_card(paper)},
    ]
    result = client.chat_json(messages, SCHEMA, "match_verdict", model=client.TIER_SMALL,
                              purpose="adjudicate:{}:{}".format(trial.nct_id, paper.pmid))
    data = result["data"]
    return {
        "verdict": data["verdict"],
        "confidence": max(0.0, min(1.0, float(data.get("confidence", 0)))),
        "reason": data.get("reason", ""),
        "model": result["model"],
        "tokens": 0 if result["cached"] else result["usage"]["prompt_tokens"] + result["usage"]["completion_tokens"],
        "cached": result["cached"],
    }
