"""Pool trial effects into a design prior (steps 7 and 8).

Two priors are built from the same cohort:

  * literature-only  -- trials whose results we could find in the published
                        record (category A). This is what a trial designer
                        reading the literature would see.
  * registry-aware   -- category A plus trials that posted a registry result
                        but for which no publication could be identified
                        (category B). This adds back observable results that
                        the literature does not show.

The difference between the two is the observable part of publication
selection. It is measured, not assumed: if selection is absent, the two priors
coincide and the tool says so.
"""

import math
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from scipy import stats

from ..models.effects import EffectEstimate
from .cohort import Cohort
from .linkage import CATEGORY_A, CATEGORY_B

_Z95 = 1.959963984540054


@dataclass
class PooledEffect:
    """A random-effects pooled estimate on the log(HR) scale."""

    label: str
    k: int  # number of trials pooled
    log_hr: Optional[float] = None
    standard_error: Optional[float] = None
    tau_squared: Optional[float] = None
    i_squared: Optional[float] = None
    q_statistic: Optional[float] = None
    ci_lower_log: Optional[float] = None
    ci_upper_log: Optional[float] = None
    # Where the NEXT trial's true effect is expected to fall. This, not the
    # confidence interval, is the right input to designing a new study.
    prediction_lower_log: Optional[float] = None
    prediction_upper_log: Optional[float] = None
    nct_ids: List[str] = field(default_factory=list)
    note: str = ""

    @property
    def hazard_ratio(self) -> Optional[float]:
        return math.exp(self.log_hr) if self.log_hr is not None else None

    def _exp(self, value: Optional[float]) -> Optional[float]:
        return math.exp(value) if value is not None else None

    def to_dict(self) -> Dict[str, Any]:
        out = asdict(self)
        out.update(
            hazard_ratio=self.hazard_ratio,
            ci_lower=self._exp(self.ci_lower_log),
            ci_upper=self._exp(self.ci_upper_log),
            prediction_lower=self._exp(self.prediction_lower_log),
            prediction_upper=self._exp(self.prediction_upper_log),
        )
        return out


def pool(estimates: Sequence[EffectEstimate], label: str) -> PooledEffect:
    """DerSimonian-Laird random-effects pooling of log hazard ratios.

    Random effects rather than fixed: trials in a cohort differ in population,
    line of therapy and comparator, so assuming one shared true effect would
    understate uncertainty.
    """
    usable = [e for e in estimates if e.is_poolable]
    ids = [e.nct_id for e in usable]
    k = len(usable)

    if k == 0:
        return PooledEffect(label=label, k=0, note="No poolable hazard ratios available.")

    y = [e.log_value for e in usable]
    v = [(e.standard_error or 0.0) ** 2 for e in usable]

    if k == 1:
        se = math.sqrt(v[0])
        return PooledEffect(
            label=label, k=1, log_hr=y[0], standard_error=se, tau_squared=0.0,
            ci_lower_log=y[0] - _Z95 * se, ci_upper_log=y[0] + _Z95 * se,
            nct_ids=ids,
            note="Only one trial; between-trial heterogeneity cannot be estimated.",
        )

    weights = [1.0 / value for value in v]
    total_w = sum(weights)
    fixed_mean = sum(w * value for w, value in zip(weights, y)) / total_w

    q = sum(w * (value - fixed_mean) ** 2 for w, value in zip(weights, y))
    c = total_w - sum(w * w for w in weights) / total_w
    tau2 = max(0.0, (q - (k - 1)) / c) if c > 0 else 0.0

    rw = [1.0 / (value + tau2) for value in v]
    total_rw = sum(rw)
    mean = sum(w * value for w, value in zip(rw, y)) / total_rw
    se = math.sqrt(1.0 / total_rw)

    i2 = max(0.0, (q - (k - 1)) / q) * 100 if q > 0 else 0.0

    # Prediction interval uses a t distribution on k-2 df (Higgins et al.).
    prediction_lower = prediction_upper = None
    if k >= 3:
        t_crit = stats.t.ppf(0.975, k - 2)
        spread = t_crit * math.sqrt(tau2 + se * se)
        prediction_lower, prediction_upper = mean - spread, mean + spread

    return PooledEffect(
        label=label, k=k, log_hr=mean, standard_error=se, tau_squared=tau2,
        i_squared=i2, q_statistic=q,
        ci_lower_log=mean - _Z95 * se, ci_upper_log=mean + _Z95 * se,
        prediction_lower_log=prediction_lower, prediction_upper_log=prediction_upper,
        nct_ids=ids,
        note="" if k >= 3 else "Fewer than three trials; no prediction interval.",
    )


def _estimates_for(cohort: Cohort, categories: Sequence[str]) -> List[EffectEstimate]:
    out: List[EffectEstimate] = []
    for item in cohort.trials:
        if item.category(cohort.endpoint_class) not in categories:
            continue
        effect = item.best_effect(cohort.endpoint_class)
        if effect is not None:
            out.append(effect)
    return out


def literature_only_prior(cohort: Cohort) -> PooledEffect:
    """Pool only trials whose results appear in the identified literature."""
    return pool(_estimates_for(cohort, [CATEGORY_A]), "literature-only")


def registry_aware_prior(cohort: Cohort) -> PooledEffect:
    """Pool published trials plus registry-only trials with posted results."""
    return pool(_estimates_for(cohort, [CATEGORY_A, CATEGORY_B]), "registry-aware")


def compare_priors(cohort: Cohort) -> Dict[str, Any]:
    """Both priors plus the shift between them, with cautious interpretation."""
    literature = literature_only_prior(cohort)
    registry = registry_aware_prior(cohort)

    shift_log = None
    interpretation = "Not enough evidence on both sides to compare."
    if literature.log_hr is not None and registry.log_hr is not None:
        shift_log = registry.log_hr - literature.log_hr
        added = registry.k - literature.k
        if added == 0:
            interpretation = (
                "Every trial with a usable result also had an identified publication, "
                "so the two priors are identical for this cohort."
            )
        elif abs(shift_log) < 0.01:
            interpretation = (
                "Adding {} registry-only trial(s) barely moved the pooled estimate. "
                "No meaningful publication selection is observable here.".format(added)
            )
        elif shift_log > 0:
            interpretation = (
                "Adding {} registry-only trial(s) moved the pooled hazard ratio toward "
                "the null (from {:.3f} to {:.3f}). In this cohort the identified "
                "literature shows a larger treatment effect than the registry record "
                "as a whole.".format(added, math.exp(literature.log_hr), math.exp(registry.log_hr))
            )
        else:
            interpretation = (
                "Adding {} registry-only trial(s) moved the pooled hazard ratio away "
                "from the null (from {:.3f} to {:.3f}). Publication selection does not "
                "run in the usual direction in this cohort.".format(
                    added, math.exp(literature.log_hr), math.exp(registry.log_hr)
                )
            )

    return {
        "literature_only": literature.to_dict(),
        "registry_aware": registry.to_dict(),
        "shift_log_hr": shift_log,
        "hazard_ratio_shift": (
            math.exp(registry.log_hr) - math.exp(literature.log_hr)
            if shift_log is not None
            else None
        ),
        "trials_added": registry.k - literature.k,
        "interpretation": interpretation,
        "caveat": (
            "This compares only results that are observable. Trials with neither a "
            "publication nor a posted result are not included here; their influence "
            "is explored through sensitivity analysis instead."
        ),
    }
