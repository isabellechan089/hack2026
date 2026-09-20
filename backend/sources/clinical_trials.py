"""ClinicalTrials.gov API v2 adapter.

Normalizes a registry record into a `Trial`. Nothing here is inferred: a field
the registry does not publish is left as None so the comparison layer can
honestly report "not registered" rather than guessing.
"""

import re
from typing import Any, Dict, List, Optional

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
