"""Leave-one-out back-test of the two priors (spec section 4).

The question is not which prior is lower, but which one a trial designer should
have believed. So each trial with a known result is held out in turn, treated
as a "future" trial, and predicted from the remaining evidence under both
models:

  Model A -- literature-only: pool the held-out trial's published peers.
  Model B -- registry-aware:  pool published peers plus registry-only results.

The held-out result is then revealed and scored. The headline metric is
prediction-interval coverage: an honest 80% interval should contain the truth
about 80% of the time. A model whose intervals are too narrow, or centred in
the wrong place, will under-cover.
"""

import math
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from scipy import stats

from .cohort import Cohort
from .linkage import CATEGORY_A, CATEGORY_B
from .power import required_events
from .priors import pool


@dataclass
class FoldResult:
    nct_id: str
    actual_log_hr: float
    actual_hazard_ratio: float
    held_out_category: str
    predictions: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _interval(pooled, level: float, new_trial_variance: float = 0.0) -> Optional[Dict[str, float]]:
    """A prediction interval for the next trial's OBSERVED estimate, on log(HR).

    Deliberately a prediction interval, not a confidence interval: the designer
    asks where one new trial will land, not where the mean of all trials lies.

    Three sources of uncertainty are added, and all three are needed:
      * tau^2                  -- real differences between trials,
      * SE(pooled)^2           -- uncertainty about the pooled mean itself,
      * the new trial's own variance -- because a back-test is scored against
        what the held-out trial *reported*, which carries its own sampling
        error. Omitting this term makes every interval too narrow and both
        models look badly calibrated.
    """
    if pooled.log_hr is None or pooled.standard_error is None:
        return None
    tau2 = pooled.tau_squared or 0.0
    spread_variance = tau2 + pooled.standard_error ** 2 + max(0.0, new_trial_variance)
    if pooled.k >= 3:
        critical = float(stats.t.ppf(0.5 + level / 2, pooled.k - 2))
    else:
        critical = float(stats.norm.ppf(0.5 + level / 2))
    half = critical * math.sqrt(spread_variance)
    return {
        "center_log": pooled.log_hr,
        "lower_log": pooled.log_hr - half,
        "upper_log": pooled.log_hr + half,
        "k": pooled.k,
    }


def run(
    cohort: Cohort,
    level: float = 0.80,
    min_training: int = 3,
    design_alpha: float = 0.05,
    design_power: float = 0.80,
) -> Dict[str, Any]:
    """Leave-one-out back-test over every trial with a usable result."""
    items = []
    for item in cohort.trials:
        category = item.category(cohort.endpoint_class)
        if category not in (CATEGORY_A, CATEGORY_B):
            continue
        effect = item.best_effect(cohort.endpoint_class)
        if effect is not None and effect.is_poolable:
            items.append((item, effect, category))

    if len(items) <= min_training:
        return {
            "ran": False,
            "n": len(items),
            "note": (
                "Only {} trial(s) with a poolable result; a leave-one-out back-test "
                "needs more than {}.".format(len(items), min_training)
            ),
        }

    folds: List[FoldResult] = []
    for index, (held_item, held_effect, held_category) in enumerate(items):
        rest = [(i, e, c) for j, (i, e, c) in enumerate(items) if j != index]
        training = {
            "literature_only": [e for _, e, c in rest if c == CATEGORY_A],
            "registry_aware": [e for _, e, c in rest],
        }
        fold = FoldResult(
            nct_id=held_item.trial.nct_id,
            actual_log_hr=held_effect.log_value,
            actual_hazard_ratio=held_effect.value,
            held_out_category=held_category,
        )
        for name, estimates in training.items():
            if len(estimates) < min_training:
                fold.predictions[name] = {"available": False}
                continue
            pooled = pool(estimates, name)
            held_variance = (held_effect.standard_error or 0.0) ** 2
            interval = _interval(pooled, level, held_variance)
            if interval is None:
                fold.predictions[name] = {"available": False}
                continue
            covered = interval["lower_log"] <= held_effect.log_value <= interval["upper_log"]
            fold.predictions[name] = {
                "available": True,
                "k_training": pooled.k,
                "predicted_log_hr": interval["center_log"],
                "predicted_hazard_ratio": math.exp(interval["center_log"]),
                "lower": math.exp(interval["lower_log"]),
                "upper": math.exp(interval["upper_log"]),
                "covered": bool(covered),
                "absolute_error_log_hr": abs(interval["center_log"] - held_effect.log_value),
                "signed_error_log_hr": interval["center_log"] - held_effect.log_value,
            }
        folds.append(fold)

    summary: Dict[str, Any] = {}
    for name in ("literature_only", "registry_aware"):
        scored = [f.predictions[name] for f in folds if f.predictions.get(name, {}).get("available")]
        if not scored:
            summary[name] = {"n": 0}
            continue
        errors = [s["absolute_error_log_hr"] for s in scored]
        signed = [s["signed_error_log_hr"] for s in scored]
        covered = sum(1 for s in scored if s["covered"])
        summary[name] = {
            "n": len(scored),
            "coverage": round(covered / len(scored), 4),
            "target_coverage": level,
            "mean_absolute_error_log_hr": round(sum(errors) / len(errors), 4),
            "bias_log_hr": round(sum(signed) / len(signed), 4),
            "median_absolute_error_log_hr": round(sorted(errors)[len(errors) // 2], 4),
        }

    verdict = _verdict(summary, level)
    return {
        "ran": True,
        "n": len(folds),
        "level": level,
        "endpoint_class": cohort.endpoint_class,
        "summary": summary,
        "verdict": verdict,
        "folds": [f.to_dict() for f in folds],
        "method": (
            "Leave-one-out. Each held-out trial is predicted from a random-effects "
            "pool of the remaining trials, using a prediction interval for the next "
            "trial rather than a confidence interval for the mean."
        ),
    }


def _verdict(summary: Dict[str, Any], level: float) -> str:
    """State what the back-test showed, including when it showed nothing."""
    literature = summary.get("literature_only", {})
    registry = summary.get("registry_aware", {})
    if not literature.get("n") or not registry.get("n"):
        return "Not enough folds to compare the two models."

    lit_gap = abs(literature["coverage"] - level)
    reg_gap = abs(registry["coverage"] - level)
    lit_mae, reg_mae = literature["mean_absolute_error_log_hr"], registry["mean_absolute_error_log_hr"]

    parts = [
        "At a target of {:.0%}, literature-only covered {:.0%} and registry-aware "
        "covered {:.0%}.".format(level, literature["coverage"], registry["coverage"]),
        "Mean absolute error on log(HR) was {:.3f} versus {:.3f}.".format(lit_mae, reg_mae),
    ]

    # Bias is the measure that speaks directly to publication selection: a
    # model that systematically predicts stronger effects than trials deliver
    # is the failure mode this whole pipeline is about.
    lit_bias, reg_bias = literature["bias_log_hr"], registry["bias_log_hr"]
    if lit_bias < -0.01 and abs(reg_bias) < abs(lit_bias):
        parts.append(
            "Literature-only predicted a stronger effect than the held-out trials "
            "delivered (bias {:+.3f} on log(HR)); registry-aware was closer to "
            "unbiased ({:+.3f}). That direction is what publication selection "
            "predicts.".format(lit_bias, reg_bias)
        )
    elif abs(reg_bias) > abs(lit_bias):
        parts.append(
            "Literature-only was the less biased of the two here ({:+.3f} versus "
            "{:+.3f} on log(HR)).".format(lit_bias, reg_bias)
        )
    if reg_gap < lit_gap and reg_mae <= lit_mae:
        parts.append("Registry-aware evidence was better calibrated and no less accurate.")
    elif reg_gap > lit_gap and reg_mae >= lit_mae:
        parts.append("Literature-only was better on both measures in this cohort.")
    else:
        parts.append(
            "The two models traded off: one was better calibrated, the other more "
            "accurate. This cohort does not settle the question."
        )
    parts.append(
        "With a cohort this size, a few folds move these numbers materially; treat "
        "the comparison as indicative rather than conclusive."
    )
    return " ".join(parts)
