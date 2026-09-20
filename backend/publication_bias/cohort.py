"""Build the narrow registry cohort the bias analysis runs on (step 1).

Section 3 deliberately restricts the statistical domain: randomized phase II/III
drug trials in one disease area, reporting time-to-event outcomes as hazard
ratios. Widening it would mix incomparable effect measures, which section 19
rule 10 forbids.
"""

import json
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

from ..sources import clinical_trials
from ..sources.http import CACHE_DIR, SourceError
from .linkage import CohortTrial, enrich_with_openalex, find_links, sponsor_type

COHORT_DIR = os.path.join(os.path.dirname(CACHE_DIR), "data", "cohorts")


@dataclass
class Cohort:
    """A registry cohort with its publication links and posted results."""

    condition: str
    endpoint_class: str
    trials: List[CohortTrial] = field(default_factory=list)
    phases: List[str] = field(default_factory=list)
    # Trials dropped before analysis, with the reason, so the cohort can be
    # described honestly rather than silently filtered.
    excluded: List[Dict[str, str]] = field(default_factory=list)
    built_at: Optional[str] = None

    def with_effect(self) -> List[CohortTrial]:
        return [t for t in self.trials if t.best_effect(self.endpoint_class) is not None]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "condition": self.condition,
            "endpoint_class": self.endpoint_class,
            "phases": self.phases,
            "built_at": self.built_at,
            "trial_count": len(self.trials),
            "excluded": self.excluded,
            "trials": [t.to_dict(self.endpoint_class) for t in self.trials],
        }


def build_cohort(
    condition: str,
    endpoint_class: str = "os",
    phases: Sequence[str] = ("2", "3"),
    max_studies: int = 300,
    progress: Optional[Callable[[int, int, str], None]] = None,
) -> Cohort:
    """Assemble a cohort: registry search -> results -> publication linkage.

    Every trial that the registry returns is kept in the cohort. Trials without
    a usable effect estimate are category C, not deleted, because they are part
    of the missingness the analysis is about.
    """
    from datetime import datetime, timezone

    studies = clinical_trials.search_cohort(
        condition, phases=phases, with_results=True, max_studies=max_studies
    )
    cohort = Cohort(
        condition=condition,
        endpoint_class=endpoint_class,
        phases=list(phases),
        built_at=datetime.now(timezone.utc).isoformat(),
    )

    total = len(studies)
    for index, payload in enumerate(studies, start=1):
        try:
            trial = clinical_trials.normalize_study(payload)
        except Exception:
            continue
        if not trial.nct_id:
            continue

        effects = clinical_trials.extract_effect_estimates(payload)
        try:
            links = find_links(trial)
        except SourceError:
            # A lookup failure must not be recorded as "no publication found".
            cohort.excluded.append(
                {"nct_id": trial.nct_id, "reason": "Publication lookup failed; trial omitted."}
            )
            continue

        cohort.trials.append(CohortTrial(trial=trial, effects=effects, links=links))
        if progress:
            progress(index, total, trial.nct_id)

    enrich_with_openalex(cohort.trials)
    return cohort


def cohort_path(condition: str, endpoint_class: str) -> str:
    slug = "".join(c if c.isalnum() else "-" for c in condition.lower()).strip("-")
    return os.path.join(COHORT_DIR, "{}-{}.json".format(slug, endpoint_class))


def save_cohort(cohort: Cohort, path: Optional[str] = None) -> str:
    path = path or cohort_path(cohort.condition, cohort.endpoint_class)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(cohort.to_dict(), handle, indent=1)
    return path


def describe(cohort: Cohort) -> Dict[str, Any]:
    """Counts a reader needs to judge whether the cohort supports the analysis."""
    from .linkage import CATEGORY_A, CATEGORY_B, CATEGORY_C

    categories: Dict[str, int] = {}
    sponsors: Dict[str, int] = {}
    for item in cohort.trials:
        category = item.category(cohort.endpoint_class)
        categories[category] = categories.get(category, 0) + 1
        kind = sponsor_type(item.trial)
        sponsors[kind] = sponsors.get(kind, 0) + 1

    linked = sum(1 for item in cohort.trials if item.has_publication)
    with_effect = len(cohort.with_effect())
    return {
        "condition": cohort.condition,
        "endpoint_class": cohort.endpoint_class,
        "phases": cohort.phases,
        "trials": len(cohort.trials),
        "with_publication_identified": linked,
        "publication_linkage_rate": round(linked / len(cohort.trials), 4)
        if cohort.trials
        else None,
        "with_usable_effect": with_effect,
        "categories": {
            "A_published_with_result": categories.get(CATEGORY_A, 0),
            "B_registry_only_with_result": categories.get(CATEGORY_B, 0),
            "C_no_publication_no_result": categories.get(CATEGORY_C, 0),
        },
        "sponsor_types": sponsors,
        "excluded": len(cohort.excluded),
    }


def load_cohort(path: str) -> Cohort:
    """Rebuild a Cohort from a saved snapshot.

    Lets a demo run with no network at all: the saved cohort carries the
    registry fields, the effect estimates and the publication links that the
    analysis needs, so every downstream number is reproducible offline.
    """
    from ..models.core import Trial
    from ..models.effects import EffectEstimate
    from .linkage import PublicationLink

    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)

    trials: List[CohortTrial] = []
    for record in payload.get("trials", []):
        trial = Trial(
            nct_id=record["nct_id"],
            title=record.get("title", ""),
            phases=record.get("phases") or [],
            status=record.get("status"),
            enrollment=record.get("enrollment"),
            lead_sponsor=record.get("lead_sponsor"),
            lead_sponsor_class=record.get("sponsor_type"),
            start_date=record.get("start_date"),
            completion_date=record.get("completion_date"),
            conditions=record.get("conditions") or [],
        )
        effect = record.get("effect")
        effects = []
        if effect:
            effects.append(
                EffectEstimate(
                    nct_id=effect.get("nct_id", trial.nct_id),
                    measure=effect.get("measure", ""),
                    value=effect.get("value"),
                    ci_lower=effect.get("ci_lower"),
                    ci_upper=effect.get("ci_upper"),
                    p_value=effect.get("p_value"),
                    outcome_title=effect.get("outcome_title"),
                    outcome_type=effect.get("outcome_type"),
                    endpoint_class=effect.get("endpoint_class"),
                    source=effect.get("source", "clinicaltrials.gov"),
                    source_url=effect.get("source_url", ""),
                    excluded_reason=effect.get("excluded_reason"),
                )
            )
        links = [
            PublicationLink(
                nct_id=link.get("nct_id", trial.nct_id),
                pmid=link.get("pmid"),
                doi=link.get("doi"),
                openalex_id=link.get("openalex_id"),
                title=link.get("title", ""),
                publication_date=link.get("publication_date"),
                citation_count=link.get("citation_count"),
                is_retracted=bool(link.get("is_retracted")),
                match_method=link.get("match_method", ""),
                match_score=link.get("match_score", 0.0),
                nct_exact=bool(link.get("nct_exact")),
                evidence=link.get("evidence") or [],
            )
            for link in record.get("links") or []
        ]
        trials.append(CohortTrial(trial=trial, effects=effects, links=links))

    return Cohort(
        condition=payload.get("condition", ""),
        endpoint_class=payload.get("endpoint_class", "os"),
        phases=payload.get("phases") or [],
        trials=trials,
        excluded=payload.get("excluded") or [],
        built_at=payload.get("built_at"),
    )


def load_or_build(
    condition: str,
    endpoint_class: str = "os",
    phases: Sequence[str] = ("2", "3"),
    max_studies: int = 300,
    rebuild: bool = False,
    progress: Optional[Callable[[int, int, str], None]] = None,
) -> Cohort:
    """Prefer a saved cohort; fall back to building one from the live APIs."""
    path = cohort_path(condition, endpoint_class)
    if not rebuild and os.path.exists(path):
        return load_cohort(path)
    return build_cohort(
        condition, endpoint_class=endpoint_class, phases=phases,
        max_studies=max_studies, progress=progress,
    )


def available_cohorts() -> List[Dict[str, str]]:
    """Cohorts already saved to disk, which can be analysed instantly."""
    if not os.path.isdir(COHORT_DIR):
        return []
    found = []
    for name in sorted(os.listdir(COHORT_DIR)):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(COHORT_DIR, name), "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, ValueError):
            continue
        found.append({
            "condition": payload.get("condition", ""),
            "endpoint_class": payload.get("endpoint_class", ""),
            "trials": len(payload.get("trials", [])),
            "built_at": payload.get("built_at"),
        })
    return found
