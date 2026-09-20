"""One row per saved cohort: does the pattern hold across disease areas?

A single cohort can show publication tracking the result; several cohorts show
whether that is a property of lung cancer trials or of the literature. This
computes the cheap, robust numbers for every saved cohort -- linkage rate by
significance, the two priors, the shift between them, and the funnel-asymmetry
intercepts -- and caches them by file modification time, so the landing view
never waits on a rebuild.
"""

import os
from typing import Any, Dict, List, Tuple

from . import funnel, publication_model
from .cohort import COHORT_DIR, describe, load_cohort
from .priors import compare_priors

_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}


def summarize_cohort(path: str) -> Dict[str, Any]:
    cohort = load_cohort(path)
    shape = describe(cohort)
    rates = publication_model.linkage_rates(cohort)
    priors = compare_priors(cohort)
    shape_funnel = funnel.funnel(cohort)
    egger = shape_funnel.get("egger") or {}
    significance = rates.get("by_significance") or {}
    direction = rates.get("by_direction") or {}
    return {
        "condition": cohort.condition,
        "endpoint_class": cohort.endpoint_class,
        "phases": cohort.phases,
        "built_at": cohort.built_at,
        "file": os.path.basename(path),
        "trials": shape["trials"],
        "with_publication_identified": shape["with_publication_identified"],
        "categories": shape["categories"],
        "linkage": {
            "n": rates.get("n", 0),
            "significant": (significance.get("significant") or {}),
            "not_significant": (significance.get("not_significant") or {}),
            "favors_treatment": (direction.get("favors_treatment") or {}),
            "favors_control": (direction.get("favors_control") or {}),
        },
        "priors": {
            "literature_only": {k: priors["literature_only"].get(k) for k in ("hazard_ratio", "ci_lower", "ci_upper", "k")},
            "registry_aware": {k: priors["registry_aware"].get(k) for k in ("hazard_ratio", "ci_lower", "ci_upper", "k")},
            "shift_log_hr": priors.get("shift_log_hr"),
            "trials_added": priors.get("trials_added"),
        },
        "egger": {
            name: {k: block.get(k) for k in ("k", "ran", "reliable", "intercept", "p_value")}
            for name, block in egger.items()
        },
    }


def overview() -> Dict[str, Any]:
    """Every saved cohort, summarised, newest file first."""
    rows: List[Dict[str, Any]] = []
    if os.path.isdir(COHORT_DIR):
        for name in sorted(os.listdir(COHORT_DIR)):
            if not name.endswith(".json") or name.endswith("-recovered.json"):
                continue
            path = os.path.join(COHORT_DIR, name)
            try:
                mtime = os.path.getmtime(path)
                cached = _CACHE.get(path)
                if cached is None or cached[0] != mtime:
                    cached = (mtime, summarize_cohort(path))
                    _CACHE[path] = cached
                rows.append(cached[1])
            except (OSError, ValueError, KeyError):
                continue

    # The cross-cohort reading: in how many cohorts did significant trials link
    # more often, and did adding registry-only trials move the prior toward null?
    comparable = [r for r in rows if r["linkage"]["significant"].get("n") and r["linkage"]["not_significant"].get("n")]
    tracks_result = sum(
        1 for r in comparable
        if (r["linkage"]["significant"].get("linkage_rate") or 0) > (r["linkage"]["not_significant"].get("linkage_rate") or 0)
    )
    shifted = [r for r in rows if r["priors"].get("shift_log_hr") is not None and r["priors"].get("trials_added")]
    toward_null = sum(1 for r in shifted if r["priors"]["shift_log_hr"] > 0)
    return {
        "cohorts": rows,
        "pattern": {
            "cohorts_compared": len(comparable),
            "significant_linked_more_often_in": tracks_result,
            "cohorts_with_registry_only_trials": len(shifted),
            "prior_moved_toward_null_in": toward_null,
        },
        "note": (
            "Each row is one saved cohort, analysed the same way. The pattern counts are "
            "descriptive: they say how often the direction repeated, not that it must."
        ),
    }
