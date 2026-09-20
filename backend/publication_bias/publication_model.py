"""Test whether publication linkage relates to a trial's results (step 6).

Section 3 is explicit: do not assume unpublished trials are null -- test it.

Two views are produced, deliberately in this order:

  1. Linkage rates cross-tabulated by result direction, significance, sponsor
     class and phase. These are counts. They are robust at hackathon cohort
     sizes and are what the demo should lead with.
  2. A logistic regression of publication linkage on the effect estimate and
     covariates. This is more informative but unstable on small cohorts, so it
     reports its own standard errors and refuses to fit when there is too
     little data or no outcome variation.

Only trials with a usable registry result can enter either view, because a
trial with no result tells us nothing about whether results drive publication.
"""

import math
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
from scipy import optimize, stats

from .cohort import Cohort
from .linkage import sponsor_type


@dataclass
class Coefficient:
    name: str
    estimate: float
    standard_error: Optional[float] = None
    z_value: Optional[float] = None
    p_value: Optional[float] = None
    odds_ratio: Optional[float] = None
    ci_lower: Optional[float] = None
    ci_upper: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PublicationModel:
    fitted: bool
    n: int
    events: int  # trials with an identified publication
    coefficients: List[Coefficient] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fitted": self.fitted,
            "n": self.n,
            "events": self.events,
            "coefficients": [c.to_dict() for c in self.coefficients],
            "note": self.note,
        }


def _rows(cohort: Cohort) -> List[Dict[str, Any]]:
    """One row per trial that has a usable effect estimate."""
    rows: List[Dict[str, Any]] = []
    for item in cohort.trials:
        effect = item.best_effect(cohort.endpoint_class)
        if effect is None or effect.log_value is None:
            continue
        rows.append(
            {
                "nct_id": item.trial.nct_id,
                "published": 1 if item.has_publication else 0,
                "log_hr": effect.log_value,
                "significant": 1 if effect.is_significant else 0,
                "favors_treatment": 1 if effect.favors_treatment else 0,
                "industry": 1 if sponsor_type(item.trial) == "INDUSTRY" else 0,
                "phase3": 1 if any("3" in p for p in item.trial.phases) else 0,
                "log_enrollment": math.log(item.trial.enrollment)
                if item.trial.enrollment and item.trial.enrollment > 0
                else None,
                "start_year": int(item.trial.start_date[:4])
                if item.trial.start_date and len(item.trial.start_date) >= 4
                else None,
            }
        )
    return rows


def _rate(rows: Sequence[Dict[str, Any]]) -> Optional[float]:
    return round(sum(r["published"] for r in rows) / len(rows), 4) if rows else None


def linkage_rates(cohort: Cohort) -> Dict[str, Any]:
    """Publication-linkage rates cross-tabulated by trial and result features."""
    rows = _rows(cohort)
    if not rows:
        return {"n": 0, "note": "No trials with a usable effect estimate."}

    def split(key: str, true_label: str, false_label: str) -> Dict[str, Any]:
        yes = [r for r in rows if r[key] == 1]
        no = [r for r in rows if r[key] == 0]
        return {
            true_label: {"n": len(yes), "linkage_rate": _rate(yes)},
            false_label: {"n": len(no), "linkage_rate": _rate(no)},
        }

    return {
        "n": len(rows),
        "overall_linkage_rate": _rate(rows),
        "by_significance": split("significant", "significant", "not_significant"),
        "by_direction": split("favors_treatment", "favors_treatment", "favors_control"),
        "by_sponsor": split("industry", "industry", "non_industry"),
        "by_phase": split("phase3", "phase_3", "phase_2"),
        "caveat": (
            "Rates describe trials that posted a usable result. A trial counted as "
            "having no identified publication may still be published; matching has "
            "false negatives."
        ),
    }


def _design_matrix(rows: Sequence[Dict[str, Any]]) -> Tuple[np.ndarray, np.ndarray, List[str]]:
    """Build the model matrix, dropping covariates that are missing or constant."""
    names = ["intercept", "log_hr", "significant", "industry", "phase3"]
    columns: List[List[float]] = [
        [1.0] * len(rows),
        [float(r["log_hr"]) for r in rows],
        [float(r["significant"]) for r in rows],
        [float(r["industry"]) for r in rows],
        [float(r["phase3"]) for r in rows],
    ]
    if all(r["log_enrollment"] is not None for r in rows):
        names.append("log_enrollment")
        columns.append([float(r["log_enrollment"]) for r in rows])

    keep_names, keep_columns = [names[0]], [columns[0]]
    for name, column in zip(names[1:], columns[1:]):
        if len(set(column)) > 1:  # a constant covariate carries no information
            keep_names.append(name)
            keep_columns.append(column)

    x = np.array(keep_columns, dtype=float).T
    y = np.array([float(r["published"]) for r in rows])
    return x, y, keep_names


def fit_publication_model(cohort: Cohort, min_per_group: int = 5) -> PublicationModel:
    """Logistic regression of publication linkage on results and covariates."""
    rows = _rows(cohort)
    n = len(rows)
    events = sum(r["published"] for r in rows)

    if n < 2 * min_per_group or events < min_per_group or (n - events) < min_per_group:
        return PublicationModel(
            fitted=False, n=n, events=events,
            note=(
                "Not enough trials on both sides to fit a model ({} with an identified "
                "publication, {} without, of {} with usable results). Read the linkage "
                "rates instead.".format(events, n - events, n)
            ),
        )

    x, y, names = _design_matrix(rows)

    # Standardize continuous covariates before fitting. Raw columns differ by
    # orders of magnitude (log_hr is around -0.25, log_enrollment around 5.3),
    # which conditions the optimizer badly. Coefficients are transformed back to
    # the original scale afterwards so they stay interpretable.
    centers = np.zeros(x.shape[1])
    scales = np.ones(x.shape[1])
    for column in range(1, x.shape[1]):
        values = x[:, column]
        if len(np.unique(values)) > 2:  # leave indicator columns alone
            centers[column] = values.mean()
            scale = values.std(ddof=0)
            scales[column] = scale if scale > 0 else 1.0
    z = (x - centers) / scales
    z[:, 0] = 1.0

    # A small ridge penalty keeps the fit finite under separation, which is a
    # real risk when a cohort has few trials in one cell.
    ridge = 1e-3

    # numpy 2.0 on macOS Accelerate emits spurious divide/overflow warnings from
    # matmul even for finite operands. Real overflow is prevented by logaddexp
    # and the clipped logistic below, so these warnings are suppressed rather
    # than worked around.
    def negative_log_likelihood(beta: np.ndarray) -> float:
        with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
            eta = z @ beta
        # logaddexp(0, eta) is log(1 + exp(eta)) without overflowing.
        loss = float(np.sum(np.logaddexp(0.0, eta) - y * eta))
        return loss + ridge * float(np.dot(beta[1:], beta[1:]))

    def gradient(beta: np.ndarray) -> np.ndarray:
        with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
            probability = 1.0 / (1.0 + np.exp(-np.clip(z @ beta, -500, 500)))
            grad = z.T @ (probability - y)
        penalty = 2 * ridge * beta
        penalty[0] = 0.0
        return grad + penalty

    result = optimize.minimize(
        negative_log_likelihood, np.zeros(z.shape[1]), jac=gradient, method="BFGS"
    )
    if not np.all(np.isfinite(result.x)):
        return PublicationModel(fitted=False, n=n, events=events,
                                note="The logistic model did not converge on this cohort.")

    beta_z = result.x
    with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
        probability = 1.0 / (1.0 + np.exp(-np.clip(z @ beta_z, -500, 500)))
        weights = np.clip(probability * (1 - probability), 1e-10, None)
        try:
            covariance_z = np.linalg.inv(z.T @ (z * weights[:, None]))
            errors_z = np.sqrt(np.diag(covariance_z))
        except np.linalg.LinAlgError:
            errors_z = np.full(len(beta_z), np.nan)

    # Back-transform to the original covariate scale.
    beta = beta_z / scales
    beta[0] = beta_z[0] - float(np.sum(beta_z[1:] * centers[1:] / scales[1:]))
    errors = errors_z / scales

    coefficients = []
    for name, value, error in zip(names, beta, errors):
        z_value = value / error if error and np.isfinite(error) and error > 0 else None
        coefficients.append(
            Coefficient(
                name=name,
                estimate=float(value),
                standard_error=float(error) if np.isfinite(error) else None,
                z_value=float(z_value) if z_value is not None else None,
                p_value=float(2 * (1 - stats.norm.cdf(abs(z_value))))
                if z_value is not None
                else None,
                odds_ratio=float(np.exp(np.clip(value, -30, 30))),
                ci_lower=float(np.exp(np.clip(value - 1.96 * error, -30, 30)))
                if z_value is not None
                else None,
                ci_upper=float(np.exp(np.clip(value + 1.96 * error, -30, 30)))
                if z_value is not None
                else None,
            )
        )

    return PublicationModel(
        fitted=True, n=n, events=events, coefficients=coefficients,
        note=(
            "Outcome is whether a publication was identified. A positive log_hr "
            "coefficient means trials with weaker treatment effects were MORE likely "
            "to be linked to a publication; a negative one means they were less "
            "likely. Small cohorts give wide intervals -- read the interval, not the "
            "point estimate."
        ),
    )
