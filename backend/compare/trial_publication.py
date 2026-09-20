"""Deterministic registered-vs-published field comparison (MVP feature 1).

No LLM is involved here. Every row is produced by explicit rules over normalized
registry fields and the publication text, and every row carries the source spans
it was derived from.

Two limits are stated in the output rather than hidden:
  * we read the abstract, not the full text, so "not identified" means exactly
    that and not "absent from the paper";
  * a difference is reported as a difference. Section 4 forbids this tool from
    characterizing any difference as misconduct.
"""

import re
from typing import List, Optional, Set, Tuple

from ..models.comparison import (
    DIFFERENCE,
    Evidence,
    FieldComparison,
    MATCH,
    NOT_COMPARABLE,
    NOT_FOUND,
    TrialPublicationComparison,
)
from ..models.core import Outcome, Paper, Trial
from ..models.matching import TrialPaperMatch

_STOPWORDS = {
    "the", "of", "and", "in", "for", "with", "to", "at", "on", "by", "from",
    "rate", "time", "number", "participants", "patients", "assessed", "measure",
}


def _ctgov_url(nct_id: str) -> str:
    return "https://clinicaltrials.gov/study/{}".format(nct_id)


def _pubmed_url(pmid: Optional[str]) -> Optional[str]:
    return "https://pubmed.ncbi.nlm.nih.gov/{}/".format(pmid) if pmid else None


def _content_tokens(text: str) -> Set[str]:
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {word for word in words if len(word) > 2 and word not in _STOPWORDS}


def _abbreviations(text: str) -> Set[str]:
    """Capture parenthetical abbreviations such as the "OS" in "Overall Survival (OS)"."""
    return {
        match.group(1)
        for match in re.finditer(r"\(([A-Z][A-Za-z0-9-]{1,6})\)", text or "")
    }


def _sentences(text: str) -> List[str]:
    return [s.strip() for s in re.split(r"(?<=[.;])\s+", text or "") if s.strip()]


# Registry outcome names carry boilerplate that dilutes the concept being
# measured: an abbreviation, the assessment method, the time frame, and a
# "number of participants with ..." counting prefix. Stripping them leaves the
# clinical concept, which is what a publication would actually name.
_METHOD_CLAUSE = re.compile(
    r"\s+(?:according to|as assessed|as measured|as determined|as evaluated|"
    r"assessed by|measured by|determined by|per rec|based on|using|by means of|"
    r"by response evaluation|by recist|by investigator|by independent|by blinded|"
    r"by central|by local)\b.*",
    re.IGNORECASE,
)
_TIME_TAIL = re.compile(
    r"\s+(?:rate\s+)?(?:at|after|within|up to)\s+"
    r"(?:month|week|day|year|randomi|\d).*",
    re.IGNORECASE,
)
_COUNT_PREFIX = re.compile(
    r"^\s*(?:number|percentage|proportion|count|incidence|frequency)\s+of\s+"
    r"(?:participants|patients|subjects)?\s*(?:with|who|experiencing|reporting)?\s*",
    re.IGNORECASE,
)


def _core_measure_phrase(measure: str) -> str:
    """Reduce a registered outcome name to the clinical concept it measures."""
    text = re.sub(r"\([^)]*\)", " ", measure or "")  # abbreviations handled separately
    text = _COUNT_PREFIX.sub("", text)
    text = _METHOD_CLAUSE.sub("", text)
    text = _TIME_TAIL.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    # If stripping left too little to identify the concept, keep the original.
    if len(_content_tokens(text)) < 2:
        return re.sub(r"\s+", " ", re.sub(r"\([^)]*\)", " ", measure or "")).strip() or (measure or "")
    return text


def _locate_outcome(outcome: Outcome, paper: Paper) -> Tuple[bool, Optional[Evidence], str]:
    """Look for a registered outcome in the publication text.

    Returns (found, evidence, explanation). Matching is lexical and runs against
    the outcome's core concept: either most of its content words appear together
    in one sentence, or one of its declared abbreviations appears as a token.
    """
    core = _core_measure_phrase(outcome.measure)
    wanted = _content_tokens(core)
    abbreviations = _abbreviations(outcome.measure)
    if not wanted and not abbreviations:
        return False, None, "Registered outcome has no comparable text."

    for label, section in (paper.abstract_sections or {"ABSTRACT": paper.abstract or ""}).items():
        for sentence in _sentences(section):
            tokens = _content_tokens(sentence)
            overlap = wanted & tokens
            ratio = len(overlap) / float(len(wanted)) if wanted else 0.0
            abbreviation_hit = any(
                re.search(r"\b{}\b".format(re.escape(abbr)), sentence)
                for abbr in abbreviations
            )
            if ratio >= 0.7 or abbreviation_hit:
                evidence = Evidence(
                    source="pubmed",
                    locator="abstract:{}".format(label),
                    quote=sentence[:400],
                    url=_pubmed_url(paper.pmid),
                )
                how = (
                    "abbreviation {}".format(", ".join(sorted(abbreviations)))
                    if abbreviation_hit and ratio < 0.7
                    else "terms {}".format(", ".join(sorted(overlap)))
                )
                return True, evidence, "Identified in the abstract via {} (matched on '{}').".format(
                    how, core
                )

    return False, None, (
        "Not identified in the abstract text (searched for '{}'). The publication "
        "may still report this outcome in its full text, tables or supplement.".format(core)
    )


def _outcome_rows(trial: Trial, paper: Paper) -> List[FieldComparison]:
    rows: List[FieldComparison] = []
    outcomes = list(trial.primary_outcomes) + list(trial.secondary_outcomes)
    for outcome in outcomes:
        found, evidence, note = _locate_outcome(outcome, paper)
        registry_evidence = Evidence(
            source="clinicaltrials.gov",
            locator="outcomesModule.{}Outcomes".format(outcome.kind),
            quote="{}{}".format(
                outcome.measure,
                " [time frame: {}]".format(outcome.time_frame) if outcome.time_frame else "",
            ),
            url=_ctgov_url(trial.nct_id),
        )
        rows.append(
            FieldComparison(
                field_name="{} outcome: {}".format(outcome.kind.capitalize(), outcome.measure),
                registered=outcome.measure
                + (" ({})".format(outcome.time_frame) if outcome.time_frame else ""),
                published="Reported" if found else None,
                status=MATCH if found else NOT_FOUND,
                note=note,
                evidence=[registry_evidence] + ([evidence] if evidence else []),
            )
        )
    return rows


def _reported_counts(paper: Paper) -> List[Tuple[int, str, str]]:
    """Candidate participant counts in the abstract, with their sentence and label."""
    pattern = re.compile(
        r"(?:among|enrolled|randomi[sz]ed|included|analy[sz]ed|total of|n\s*=)\s*"
        r"(?:a total of\s*)?([0-9][0-9,]{1,6})",
        re.IGNORECASE,
    )
    found: List[Tuple[int, str, str]] = []
    for label, section in (paper.abstract_sections or {"ABSTRACT": paper.abstract or ""}).items():
        for sentence in _sentences(section):
            for match in pattern.finditer(sentence):
                try:
                    found.append((int(match.group(1).replace(",", "")), sentence, label))
                except ValueError:
                    continue
    return found


def _enrollment_row(trial: Trial, paper: Paper) -> FieldComparison:
    registered = (
        "{} ({})".format(trial.enrollment, (trial.enrollment_type or "").lower())
        if trial.enrollment is not None
        else None
    )
    candidates = _reported_counts(paper)

    if trial.enrollment is None or not candidates:
        return FieldComparison(
            field_name="Enrollment",
            registered=registered,
            published=None,
            status=NOT_COMPARABLE,
            note="No participant count could be read from the abstract."
            if trial.enrollment is not None
            else "Enrollment is not stated in the registration.",
            evidence=[],
        )

    value, sentence, label = min(candidates, key=lambda c: abs(c[0] - trial.enrollment))
    status = MATCH if value == trial.enrollment else DIFFERENCE
    delta = value - trial.enrollment
    note = (
        "Registered and reported counts agree."
        if status == MATCH
        else (
            "Registered enrollment and the count reported in the abstract differ by {:+d}. "
            "Counts routinely differ for legitimate reasons, such as the difference "
            "between enrolled, eligible and analyzed populations.".format(delta)
        )
    )
    return FieldComparison(
        field_name="Enrollment",
        registered=registered,
        published=str(value),
        status=status,
        note=note,
        evidence=[
            Evidence(
                source="clinicaltrials.gov",
                locator="designModule.enrollmentInfo",
                quote=registered or "",
                url=_ctgov_url(trial.nct_id),
            ),
            Evidence(
                source="pubmed",
                locator="abstract:{}".format(label),
                quote=sentence[:400],
                url=_pubmed_url(paper.pmid),
            ),
        ],
    )


def _text_presence_row(
    field_name: str,
    registered_value: Optional[str],
    terms: Set[str],
    trial: Trial,
    paper: Paper,
    locator: str,
) -> FieldComparison:
    """Generic row: is a registered design attribute echoed in the abstract?"""
    if not registered_value:
        return FieldComparison(
            field_name=field_name,
            registered=None,
            published=None,
            status=NOT_COMPARABLE,
            note="Not stated in the registration.",
        )

    haystack_sections = paper.abstract_sections or {"ABSTRACT": paper.abstract or ""}
    for label, section in haystack_sections.items():
        for sentence in _sentences(section):
            tokens = _content_tokens(sentence)
            hit = terms & tokens
            if hit:
                return FieldComparison(
                    field_name=field_name,
                    registered=registered_value,
                    published="Described",
                    status=MATCH,
                    note="Described in the abstract ({}).".format(", ".join(sorted(hit))),
                    evidence=[
                        Evidence(
                            source="clinicaltrials.gov",
                            locator=locator,
                            quote=registered_value,
                            url=_ctgov_url(trial.nct_id),
                        ),
                        Evidence(
                            source="pubmed",
                            locator="abstract:{}".format(label),
                            quote=sentence[:400],
                            url=_pubmed_url(paper.pmid),
                        ),
                    ],
                )

    return FieldComparison(
        field_name=field_name,
        registered=registered_value,
        published=None,
        status=NOT_FOUND,
        note="Not described in the abstract text.",
        evidence=[
            Evidence(
                source="clinicaltrials.gov",
                locator=locator,
                quote=registered_value,
                url=_ctgov_url(trial.nct_id),
            )
        ],
    )


def compare(trial: Trial, paper: Paper, match: Optional[TrialPaperMatch] = None) -> TrialPublicationComparison:
    """Produce the full registered-vs-published table for one trial/paper pair."""
    rows: List[FieldComparison] = []

    # Registry identifier: does the publication declare the trial it reports?
    declared = [nct.upper() for nct in paper.registered_trial_ids]
    rows.append(
        FieldComparison(
            field_name="Registry identifier",
            registered=trial.nct_id,
            published=", ".join(declared) if declared else None,
            status=MATCH if trial.nct_id.upper() in declared else NOT_FOUND,
            note="Publication declares this registration."
            if trial.nct_id.upper() in declared
            else "The publication text does not state this registry identifier.",
            evidence=[
                Evidence(
                    source="clinicaltrials.gov",
                    locator="identificationModule.nctId",
                    quote=trial.nct_id,
                    url=_ctgov_url(trial.nct_id),
                )
            ],
        )
    )

    rows.append(_enrollment_row(trial, paper))

    intervention_terms: Set[str] = set()
    for item in trial.interventions:
        intervention_terms |= _content_tokens(item.get("name") or "")
    rows.append(
        _text_presence_row(
            "Interventions",
            ", ".join(
                filter(None, [item.get("name") for item in trial.interventions])
            )[:200]
            or None,
            intervention_terms,
            trial,
            paper,
            "armsInterventionsModule.interventions",
        )
    )

    rows.append(
        _text_presence_row(
            "Allocation",
            trial.allocation,
            _content_tokens((trial.allocation or "").replace("_", " "))
            | {"randomized", "randomised"},
            trial,
            paper,
            "designModule.designInfo.allocation",
        )
    )

    rows.append(
        _text_presence_row(
            "Masking",
            trial.masking,
            _content_tokens((trial.masking or "").replace("_", " "))
            | {"blind", "blinded", "masked", "open-label", "openlabel"},
            trial,
            paper,
            "designModule.designInfo.maskingInfo.masking",
        )
    )

    rows.append(
        _text_presence_row(
            "Study phase",
            ", ".join(trial.phases) or None,
            {phase.lower().replace("phase", "phase ") for phase in trial.phases}
            | {"phase"},
            trial,
            paper,
            "designModule.phases",
        )
    )

    rows.extend(_outcome_rows(trial, paper))

    # Adverse events: registered as a measured outcome vs discussed in abstract.
    safety_terms = {"adverse", "toxicity", "toxicities", "safety", "tolerability"}
    registered_safety = any(
        _content_tokens(outcome.measure) & safety_terms
        for outcome in trial.primary_outcomes + trial.secondary_outcomes
    )
    rows.append(
        _text_presence_row(
            "Adverse events",
            "Planned as an outcome measure" if registered_safety else None,
            safety_terms,
            trial,
            paper,
            "outcomesModule",
        )
    )

    return TrialPublicationComparison(
        nct_id=trial.nct_id,
        pmid=paper.pmid,
        doi=paper.doi,
        trial_title=trial.title,
        paper_title=paper.title,
        match_basis=match.basis if match else "unspecified",
        match_confidence=match.confidence if match else "unspecified",
        match_score=match.score if match else 0.0,
        fields=rows,
        evidence_scope=(
            "Publication evidence is limited to the PubMed record and its "
            "structured abstract. Full text, tables and supplements were not read, "
            "so a 'not identified' row does not mean the item is absent from the paper."
        ),
        provenance=[
            {"source": "clinicaltrials.gov", "id": trial.nct_id, "url": _ctgov_url(trial.nct_id)},
            {"source": "pubmed", "id": paper.pmid or "", "url": _pubmed_url(paper.pmid) or ""},
        ],
    )
