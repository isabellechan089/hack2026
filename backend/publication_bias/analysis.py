"""Run the whole bias-aware design pipeline and return one report.

Ties steps 1-10 and the back-test together so the CLI and the HTTP API produce
identical numbers from identical records.
"""

from typing import Any, Dict, Optional, Sequence

from . import backtest, funnel, publication_model, sensitivity
from .cohort import Cohort, describe
from .power import design_comparison
from .priors import compare_priors


def _sources(cohort: Cohort) -> Dict[str, int]:
    """Where the pooled estimates came from, so the two are never conflated."""
    counts = {"registry_posted": 0, "publication_extracted": 0}
    for item in cohort.trials:
        effect = item.best_effect(cohort.endpoint_class)
        if effect is None:
            continue
        counts["publication_extracted" if effect.source == "publication" else "registry_posted"] += 1
    return counts


def analyze(
    cohort: Cohort,
    assumed_hr: float = 0.65,
    recover: bool = False,
    max_recover_papers: int = 80,
    alpha: float = 0.05,
    target_power: float = 0.80,
    event_probability: Optional[float] = None,
    run_backtest: bool = True,
    assumed_hazard_ratios: Sequence[float] = (0.80, 0.85, 0.90, 0.95, 1.00, 1.05, 1.10),
) -> Dict[str, Any]:
    """The full analysis for one cohort and one proposed design."""
    recovery = None
    if recover:
        from . import fulltext
        recovery = fulltext.recover(cohort, max_papers=max_recover_papers)
    priors = compare_priors(cohort)
    literature_hr = priors["literature_only"].get("hazard_ratio")
    registry_hr = priors["registry_aware"].get("hazard_ratio")

    return {
        "cohort": describe(cohort),
        "linkage": publication_model.linkage_rates(cohort),
        "publication_model": publication_model.fit_publication_model(cohort).to_dict(),
        "priors": priors,
        "funnel": funnel.funnel(cohort),
        "design": design_comparison(
            assumed_hr=assumed_hr,
            literature_hr=literature_hr,
            registry_hr=registry_hr,
            alpha=alpha,
            target_power=target_power,
            event_probability=event_probability,
        ),
        "sensitivity": sensitivity.sweep(
            cohort,
            assumed_hazard_ratios=assumed_hazard_ratios,
            design_hr=assumed_hr,
            alpha=alpha,
            target_power=target_power,
        ),
        "backtest": backtest.run(cohort, level=target_power)
        if run_backtest
        else {"ran": False, "note": "Back-test skipped."},
        "recovery": recovery,
        "evidence_sources": _sources(cohort),
        "guardrails": [
            "A trial with no identified publication is not necessarily unpublished; "
            "matching has false negatives.",
            "A trial with no identified publication is not assumed to be null. Its "
            "influence is explored through sensitivity analysis.",
            "Registered-versus-published differences are described, never "
            "characterized as misconduct.",
            "Only hazard ratios for one endpoint class are pooled; other effect "
            "measures are excluded rather than converted.",
        ],
    }
