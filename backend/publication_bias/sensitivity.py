"""Sensitivity analysis for trials whose results are genuinely unknown (step 10).

Category C trials have neither an identified publication nor a posted registry
result. Section 3 is explicit that their effect must not be hard-coded to the
null, and section 19 rule 4 forbids fabricating outcomes. So instead of
imputing a value, this module sweeps an *assumption* across a range and reports
how the conclusion moves.

Each unknown trial is represented by one pseudo-trial at the assumed hazard
ratio, carrying the median standard error of the trials that did report, so the
unknowns are neither more nor less precise than the observed evidence.
"""

import math
from statistics import median
from typing import Any, Dict, List, Optional, Sequence

from ..models.effects import HAZARD_RATIO, EffectEstimate
from .cohort import Cohort
from .linkage import CATEGORY_A, CATEGORY_B, CATEGORY_C
from .power import required_events
from .priors import pool


def _observed_estimates(cohort: Cohort) -> List[EffectEstimate]:
    out = []
    for item in cohort.trials:
        if item.category(cohort.endpoint_class) in (CATEGORY_A, CATEGORY_B):
            effect = item.best_effect(cohort.endpoint_class)
            if effect is not None:
                out.append(effect)
    return out


def count_unknown(cohort: Cohort) -> int:
    return sum(
        1 for item in cohort.trials if item.category(cohort.endpoint_class) == CATEGORY_C
    )


def _pseudo_trials(
    count: int, assumed_hr: float, standard_error: float
) -> List[EffectEstimate]:
    """Stand-ins for unknown trials, built from an explicit assumption."""
    spread = 1.959963984540054 * standard_error
    return [
        EffectEstimate(
            nct_id="ASSUMED-{}".format(index + 1),
            measure=HAZARD_RATIO,
            value=assumed_hr,
            ci_lower=math.exp(math.log(assumed_hr) - spread),
            ci_upper=math.exp(math.log(assumed_hr) + spread),
            outcome_title="Assumed effect for a trial with no identified result",
            source="assumption",
        )
        for index in range(count)
    ]


def sweep(
    cohort: Cohort,
    assumed_hazard_ratios: Sequence[float] = (0.80, 0.85, 0.90, 0.95, 1.00, 1.05, 1.10),
    design_hr: Optional[float] = None,
    alpha: float = 0.05,
    target_power: float = 0.80,
) -> Dict[str, Any]:
    """Recompute the pooled estimate across a range of assumptions for unknowns."""
    observed = _observed_estimates(cohort)
    unknown = count_unknown(cohort)
    poolable = [e for e in observed if e.is_poolable]

    if not poolable:
        return {
            "unknown_trials": unknown,
            "points": [],
            "note": "No observed results to anchor a sensitivity analysis.",
        }

    typical_se = median([e.standard_error for e in poolable if e.standard_error])
    baseline = pool(poolable, "observed-only")

    points = []
    for assumed in assumed_hazard_ratios:
        combined = list(poolable) + _pseudo_trials(unknown, assumed, typical_se)
        pooled = pool(combined, "with-assumption-{:.2f}".format(assumed))
        events = (
            required_events(pooled.hazard_ratio, alpha, target_power)
            if pooled.hazard_ratio
            else None
        )
        points.append(
            {
                "assumed_hazard_ratio_for_unknowns": assumed,
                "pooled_hazard_ratio": pooled.hazard_ratio,
                "pooled_ci_lower": math.exp(pooled.ci_lower_log)
                if pooled.ci_lower_log is not None
                else None,
                "pooled_ci_upper": math.exp(pooled.ci_upper_log)
                if pooled.ci_upper_log is not None
                else None,
                "k": pooled.k,
                "required_events": events,
            }
        )

    ratios = [p["pooled_hazard_ratio"] for p in points if p["pooled_hazard_ratio"]]
    return {
        "unknown_trials": unknown,
        "observed_trials": baseline.k,
        "observed_pooled_hazard_ratio": baseline.hazard_ratio,
        "assumed_standard_error": typical_se,
        "points": points,
        "range_of_pooled_hazard_ratio": [min(ratios), max(ratios)] if ratios else None,
        "design_hazard_ratio": design_hr,
        "note": (
            "Each of the {} trial(s) with no identified publication and no posted "
            "result is represented by one pseudo-trial at the assumed hazard ratio, "
            "given the median precision of the {} trial(s) that did report. These "
            "are assumptions under test, not findings.".format(unknown, baseline.k)
        ),
    }
