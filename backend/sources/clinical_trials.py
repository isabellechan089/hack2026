"""ClinicalTrials.gov API v2 adapter.

Normalizes a registry record into a `Trial`. Nothing here is inferred: a field
the registry does not publish is left as None so the comparison layer can
honestly report "not registered" rather than guessing.
"""

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..models.core import Outcome, Provenance, Trial
from .http import SourceError, get_json

API_BASE = "https://clinicaltrials.gov/api/v2"
NCT_PATTERN = re.compile(r"\bNCT0*\d{8}\b", re.IGNORECASE)


def looks_like_nct_id(text: str) -> bool:
    return bool(re.fullmatch(r"NCT\d{8}", (text or "").strip().upper()))


def extract_nct_ids(text: Optional[str]) -> List[str]:
    """Pull every ClinicalTrials.gov identifier out of free text, in order."""
    if not text:
        return []
    seen: List[str] = []
    for match in NCT_PATTERN.finditer(text):
        nct = match.group(0).upper()
        if nct not in seen:
            seen.append(nct)
    return seen


def _date(struct: Optional[Dict[str, Any]]) -> Optional[str]:
    return (struct or {}).get("date")


def _outcomes(raw: List[Dict[str, Any]], kind: str) -> List[Outcome]:
    return [
        Outcome(
            measure=item.get("measure", ""),
            description=item.get("description"),
            time_frame=item.get("timeFrame"),
            kind=kind,
        )
        for item in raw or []
        if item.get("measure")
    ]


def normalize_study(payload: Dict[str, Any]) -> Trial:
    """Map a raw API v2 study document onto our `Trial` model."""
    protocol = payload.get("protocolSection", {})
    ident = protocol.get("identificationModule", {})
    status = protocol.get("statusModule", {})
    design = protocol.get("designModule", {})
    arms = protocol.get("armsInterventionsModule", {})
    outcomes = protocol.get("outcomesModule", {})
    sponsor = protocol.get("sponsorCollaboratorsModule", {})
    eligibility = protocol.get("eligibilityModule", {})
    contacts = protocol.get("contactsLocationsModule", {})
    references = protocol.get("referencesModule", {})

    nct_id = ident.get("nctId", "")
    design_info = design.get("designInfo", {}) or {}
    enrollment_info = design.get("enrollmentInfo", {}) or {}
    arm_groups = arms.get("armGroups") or []

    return Trial(
        nct_id=nct_id,
        title=ident.get("briefTitle", ""),
        official_title=ident.get("officialTitle"),
        brief_summary=(protocol.get("descriptionModule", {}) or {}).get("briefSummary"),
        status=status.get("overallStatus"),
        phases=design.get("phases") or [],
        conditions=(protocol.get("conditionsModule", {}) or {}).get("conditions") or [],
        interventions=[
            {
                "type": item.get("type"),
                "name": item.get("name"),
                "description": item.get("description"),
                "other_names": item.get("otherNames") or [],
            }
            for item in arms.get("interventions") or []
        ],
        primary_outcomes=_outcomes(outcomes.get("primaryOutcomes"), "primary"),
        secondary_outcomes=_outcomes(outcomes.get("secondaryOutcomes"), "secondary"),
        enrollment=enrollment_info.get("count"),
        enrollment_type=enrollment_info.get("type"),
        arm_count=len(arm_groups) or None,
        allocation=design_info.get("allocation"),
        masking=(design_info.get("maskingInfo", {}) or {}).get("masking"),
        start_date=_date(status.get("startDateStruct")),
        primary_completion_date=_date(status.get("primaryCompletionDateStruct")),
        completion_date=_date(status.get("completionDateStruct")),
        lead_sponsor=(sponsor.get("leadSponsor", {}) or {}).get("name"),
        lead_sponsor_class=(sponsor.get("leadSponsor", {}) or {}).get("class"),
        investigators=[
            official.get("name", "")
            for official in contacts.get("overallOfficials") or []
            if official.get("name")
        ],
        eligibility_criteria=eligibility.get("eligibilityCriteria"),
        has_results=bool(payload.get("hasResults")),
        linked_references=[
            {
                "pmid": ref.get("pmid", ""),
                # DERIVED = PubMed linked it via the NCT id in the article.
                # RESULT  = the sponsor designated it as a results publication.
                "type": ref.get("type", ""),
                "citation": ref.get("citation", ""),
            }
            for ref in references.get("references") or []
            if ref.get("pmid")
        ],
        provenance=Provenance(
            source="clinicaltrials.gov",
            source_id=nct_id,
            url="https://clinicaltrials.gov/study/{}".format(nct_id),
        ),
    )


def get_trial(nct_id: str) -> Trial:
    """Fetch and normalize one registered trial by NCT id."""
    nct_id = nct_id.strip().upper()
    if not looks_like_nct_id(nct_id):
        raise SourceError("{!r} is not a valid NCT id".format(nct_id))
    payload = get_json("{}/studies/{}".format(API_BASE, nct_id), {"format": "json"})
    return normalize_study(payload)


def search_trials(query: str, limit: int = 10) -> List[Trial]:
    """Free-text search across the registry (condition, intervention, title)."""
    payload = get_json(
        "{}/studies".format(API_BASE),
        {"query.term": query, "pageSize": limit, "format": "json"},
    )
    return [normalize_study(study) for study in payload.get("studies", [])]


# --- Posted results: effect estimates ------------------------------------
# Registry result postings carry the analysis a sponsor actually ran, including
# hazard ratios with confidence intervals. This is the "registry-side" evidence
# that section 3 compares against the published record.

_OS_TERMS = ("overall survival", "os rate", "(os)")
_PFS_TERMS = ("progression free", "progression-free", "pfs", "event free",
              "event-free", "disease free", "disease-free", "recurrence free",
              "time to progression")


def classify_endpoint(title: Optional[str]) -> str:
    """Bucket an outcome title into os / pfs / other.

    Pooling requires endpoints that mean the same thing; an overall-survival
    hazard ratio and a progression-free-survival hazard ratio are not
    interchangeable even though both are hazard ratios.
    """
    text = (title or "").lower()
    if any(term in text for term in _OS_TERMS):
        return "os"
    if any(term in text for term in _PFS_TERMS):
        return "pfs"
    return "other"


def _to_float(value: Any) -> Optional[float]:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def extract_effect_estimates(payload: Dict[str, Any]) -> List["EffectEstimate"]:
    """Pull every posted analysis out of a study's results section.

    Non-hazard-ratio analyses are still returned, carrying `excluded_reason`, so
    that a cohort can report honestly on what it had to drop.
    """
    from ..models.effects import HAZARD_RATIO, EffectEstimate

    nct_id = (
        payload.get("protocolSection", {}).get("identificationModule", {}).get("nctId", "")
    )
    url = "https://clinicaltrials.gov/study/{}?tab=results".format(nct_id)
    measures = (
        payload.get("resultsSection", {})
        .get("outcomeMeasuresModule", {})
        .get("outcomeMeasures", [])
        or []
    )

    estimates: List[EffectEstimate] = []
    for measure in measures:
        title = measure.get("title")
        for analysis in measure.get("analyses") or []:
            param_type = (analysis.get("paramType") or "").strip()
            label = param_type.lower()
            # Sponsors label the same quantity several ways. A Cox model's
            # parameter is a hazard ratio, and stratified or unstratified ones
            # still are. "Min Hazard" in a biomarker threshold is not, and a
            # ratio reported on the log scale is a different number entirely,
            # so it is excluded rather than silently misread as a ratio.
            is_log_scale = "log" in label
            is_hr = not is_log_scale and (
                "hazard ratio" in label or "cox proportional hazard" in label
            )
            value = _to_float(analysis.get("paramValue"))
            lower = _to_float(analysis.get("ciLowerLimit"))
            upper = _to_float(analysis.get("ciUpperLimit"))

            reason = None
            if is_log_scale and "hazard" in label:
                reason = (
                    "Reported as '{}' on the log scale, not as a ratio.".format(param_type)
                )
            elif not is_hr:
                reason = "Effect measure is '{}', not a hazard ratio.".format(
                    param_type or "unlabeled"
                )
            elif value is None:
                reason = "Hazard ratio has no numeric point estimate."
            elif lower is None or upper is None:
                reason = "Hazard ratio has no confidence interval, so its variance is unknown."

            estimates.append(
                EffectEstimate(
                    nct_id=nct_id,
                    measure=HAZARD_RATIO if is_hr else (param_type or "unlabeled"),
                    value=value,
                    ci_lower=lower,
                    ci_upper=upper,
                    p_value=analysis.get("pValue"),
                    outcome_title=title,
                    outcome_type=measure.get("type"),
                    endpoint_class=classify_endpoint(title),
                    groups=[
                        group.get("title", "")
                        for group in measure.get("groups") or []
                        if group.get("title")
                    ][:4],
                    source_url=url,
                    excluded_reason=reason,
                )
            )
    return estimates


def get_trial_with_results(nct_id: str) -> Tuple[Trial, List["EffectEstimate"]]:
    """Fetch one trial together with the effect estimates it has posted."""
    nct_id = nct_id.strip().upper()
    if not looks_like_nct_id(nct_id):
        raise SourceError("{!r} is not a valid NCT id".format(nct_id))
    payload = get_json("{}/studies/{}".format(API_BASE, nct_id), {"format": "json"})
    return normalize_study(payload), extract_effect_estimates(payload)


# --- Cohort construction --------------------------------------------------


def search_cohort(
    condition: str,
    phases: Sequence[str] = ("2", "3"),
    with_results: bool = True,
    status: str = "COMPLETED",
    max_studies: int = 400,
) -> List[Dict[str, Any]]:
    """Enumerate a narrow registry cohort, returning raw study payloads.

    Raw payloads are returned rather than `Trial` objects so the caller can pull
    both protocol fields and posted results without a second fetch.
    """
    agg = ["studyType:int"]
    if phases:
        agg.append("phase:" + " ".join(phases))
    if with_results:
        agg.append("results:with")

    studies: List[Dict[str, Any]] = []
    token: Optional[str] = None
    while len(studies) < max_studies:
        params: Dict[str, Any] = {
            "query.cond": condition,
            "filter.overallStatus": status,
            "aggFilters": ",".join(agg),
            "pageSize": min(100, max_studies - len(studies)),
            "format": "json",
        }
        if token:
            params["pageToken"] = token
        payload = get_json("{}/studies".format(API_BASE), params)
        batch = payload.get("studies", [])
        if not batch:
            break
        studies.extend(batch)
        token = payload.get("nextPageToken")
        if not token:
            break
    return studies[:max_studies]
