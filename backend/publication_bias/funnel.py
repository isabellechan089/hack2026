"""Funnel plot and small-study test: where do the missing trials sit?

The registry-aware correction says publication tracks the result. A funnel
plot shows it: each trial is a point at its effect (x) and its precision (y).
With no selection, points scatter symmetrically about the pooled estimate and
narrow as precision rises. Publication selection hollows out one corner --
small trials with unimpressive results are the ones that go missing from the
literature -- and registry-only trials should land in exactly that corner.

Egger's regression test puts a number on the asymmetry: regress each trial's
standardized effect (log HR / SE) on its precision (1 / SE). Under symmetry the
intercept is zero; a non-zero intercept means small trials report
systematically different effects from large ones. The test is run twice, on
the literature-only set and on the registry-aware set, because the point is to
see whether adding the registry's trials removes the asymmetry.

Only computed facts: no imputation, no trim-and-fill. Trials with no usable
estimate do not appear, and the plot says so.
"""

import math
from typing import Any, Dict, List, Optional, Sequence

from scipy import stats

from ..models.effects import EffectEstimate
from .cohort import Cohort
from .linkage import CATEGORY_A, CATEGORY_B
from .priors import pool

# Sterne et al. (BMJ 2011): tests for funnel asymmetry are unreliable with
# fewer than ten trials, so below that the test reports rather than decides.
MIN_TRIALS_FOR_TEST = 10

_Z95 = 1.959963984540054


def format_p(p_value: Optional[float]) -> str:
    """p-values the way a reader expects them: a floor, never 'p = 0.000'."""
    if p_value is None:
        return "p unavailable"
    if p_value < 0.001:
        return "p < 0.001"
    return "p = {:.3f}".format(p_value) if p_value < 0.01 else "p = {:.2f}".format(p_value)


def egger_test(estimates: Sequence[EffectEstimate], label: str) -> Dict[str, Any]:
    """Egger's regression of standardized effect on precision, with its verdict."""
    usable = [e for e in estimates if e.is_poolable]
    k = len(usable)
    if k < 3:
        return {"label": label, "k": k, "ran": False,
                "note": "Fewer than three trials; asymmetry cannot be tested."}

    snd = [e.log_value / e.standard_error for e in usable]  # standard normal deviate
    precision = [1.0 / e.standard_error for e in usable]
    if max(precision) - min(precision) < 1e-9:
        return {"label": label, "k": k, "ran": False,
                "note": "Every trial has the same precision; asymmetry cannot be tested."}
    fit = stats.linregress(precision, snd)
    intercept = float(fit.intercept)
    intercept_se = float(fit.intercept_stderr)
    t_value = intercept / intercept_se if intercept_se > 0 else None
    p_value = float(2 * stats.t.sf(abs(t_value), k - 2)) if t_value is not None else None

    reliable = k >= MIN_TRIALS_FOR_TEST
    if p_value is None:
        note = "The intercept's standard error could not be estimated."
    elif not reliable:
        note = ("Only {} trials; Egger's test is unreliable below {} and is shown "
                "for completeness only.".format(k, MIN_TRIALS_FOR_TEST))
    elif p_value < 0.05:
        note = ("Small trials report systematically {} effects than large ones "
                "(intercept {:+.2f}, {}). That is the shape publication "
                "selection leaves.".format("stronger" if intercept < 0 else "weaker",
                                           intercept, format_p(p_value)))
    else:
        note = ("No significant asymmetry (intercept {:+.2f}, {}). Absence of "
                "asymmetry is not proof of absence of selection.".format(
                    intercept, format_p(p_value)))

    return {
        "label": label,
        "k": k,
        "ran": True,
        "reliable": reliable,
        "intercept": intercept,
        "intercept_se": intercept_se,
        "t_value": float(t_value) if t_value is not None else None,
        "p_value": p_value,
        "slope": float(fit.slope),
        "note": note,
    }


def _bounds(center_log: float, se_values: Sequence[float]) -> List[Dict[str, float]]:
    """Pseudo 95% limits around the pooled estimate at each standard error."""
    return [
        {"se": se,
         "lower": math.exp(center_log - _Z95 * se),
         "upper": math.exp(center_log + _Z95 * se)}
        for se in se_values
    ]


def funnel(cohort: Cohort) -> Dict[str, Any]:
    """Per-trial points, pooled centre, funnel bounds and Egger's test."""
    endpoint = cohort.endpoint_class
    points: List[Dict[str, Any]] = []
    literature: List[EffectEstimate] = []
    everything: List[EffectEstimate] = []

    for item in cohort.trials:
        category = item.category(endpoint)
        if category not in (CATEGORY_A, CATEGORY_B):
            continue
        effect = item.best_effect(endpoint)
        if effect is None or not effect.is_poolable:
            continue
        everything.append(effect)
        if category == CATEGORY_A:
            literature.append(effect)
        points.append({
            "nct_id": item.trial.nct_id,
            "title": item.trial.title,
            "category": category,
            "has_publication": item.has_publication,
            "hazard_ratio": effect.value,
            "log_hr": effect.log_value,
            "standard_error": effect.standard_error,
            "ci_lower": effect.ci_lower,
            "ci_upper": effect.ci_upper,
            "significant": bool(effect.is_significant),
            "enrollment": item.trial.enrollment,
            "source": effect.source,
        })

    if not everything:
        return {"points": [], "k": 0, "note": "No poolable hazard ratios to plot."}

    pooled = pool(everything, "registry-aware")
    max_se = max(p["standard_error"] for p in points)
    se_grid = [max_se * step / 6.0 for step in range(1, 7)]

    registry_only = [p for p in points if p["category"] == CATEGORY_B]
    # Where the registry-only trials sit relative to the published ones: the
    # share that are less precise than the published median, and the share
    # that favour treatment less than the pooled estimate.
    published_se = sorted(p["standard_error"] for p in points if p["category"] == CATEGORY_A)
    median_published_se = published_se[len(published_se) // 2] if published_se else None
    placement = None
    if registry_only and median_published_se is not None and pooled.log_hr is not None:
        less_precise = sum(1 for p in registry_only if p["standard_error"] > median_published_se)
        weaker = sum(1 for p in registry_only if p["log_hr"] > pooled.log_hr)
        placement = {
            "registry_only": len(registry_only),
            "less_precise_than_published_median": less_precise,
            "weaker_than_pooled": weaker,
            "note": (
                "{} of the {} registry-only trials are less precise than the median "
                "published trial, and {} report a weaker effect than the pooled "
                "estimate.".format(less_precise, len(registry_only), weaker)
            ),
        }

    return {
        "k": len(points),
        "points": points,
        "pooled_hazard_ratio": pooled.hazard_ratio,
        "pooled_log_hr": pooled.log_hr,
        "bounds": _bounds(pooled.log_hr, se_grid) if pooled.log_hr is not None else [],
        "egger": {
            "literature_only": egger_test(literature, "literature-only"),
            "registry_aware": egger_test(everything, "registry-aware"),
        },
        "placement": placement,
        "note": (
            "Each point is one trial with a poolable hazard ratio; trials with no usable "
            "estimate are absent, not at the null. The funnel is a pseudo 95% region "
            "around the registry-aware pooled estimate. Asymmetry has causes other than "
            "publication selection, such as genuine small-study effects."
        ),
    }
