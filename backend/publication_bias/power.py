"""Turn an effect-size assumption into a trial-design consequence (step 9).

Time-to-event designs are sized by the number of events, not the number of
participants, so everything here works in events first and converts to sample
size only when the caller supplies an event probability.

Schoenfeld's approximation for the log-rank test with 1:1 allocation:

    events = 4 (z_{1-alpha/2} + z_{1-beta})^2 / (ln HR)^2

and, inverted, the power delivered by a given number of events:

    power = Phi( |ln HR| * sqrt(events) / 2 - z_{1-alpha/2} )

The point of this module is the second form: a trial is sized using an assumed
hazard ratio, but its real power depends on the true effect. If the assumption
came from a literature that omits some completed trials, the delivered power is
lower than the design claims.
"""

import math
from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional

from scipy import stats


@dataclass
class DesignResult:
    label: str
    hazard_ratio: float
    required_events: Optional[int] = None
    required_participants: Optional[int] = None
    power_at_planned_events: Optional[float] = None
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _z(probability: float) -> float:
    return float(stats.norm.ppf(probability))


# Beyond this, a trial is not a design option -- no oncology programme randomizes
# to a hundred thousand events. Returning the exact figure invites a reader to
# treat an effect indistinguishable from null as merely "a big study".
MAX_FEASIBLE_EVENTS = 100000


def required_events(
    hazard_ratio: float, alpha: float = 0.05, power: float = 0.80, cap: bool = True
) -> Optional[int]:
    """Events needed to detect `hazard_ratio` with the requested power.

    Returns None when the effect is too close to the null to be detectable at
    any feasible size; the event count diverges as the hazard ratio approaches
    1, so an exact number there is arithmetically true but practically
    meaningless.
    """
    if hazard_ratio <= 0 or hazard_ratio == 1.0:
        return None
    if not 0 < alpha < 1 or not 0 < power < 1:
        raise ValueError("alpha and power must each lie strictly between 0 and 1.")
    numerator = 4 * (_z(1 - alpha / 2) + _z(power)) ** 2
    events = int(math.ceil(numerator / (math.log(hazard_ratio) ** 2)))
    if cap and events > MAX_FEASIBLE_EVENTS:
        return None
    return events


def power_at_events(hazard_ratio: float, events: int, alpha: float = 0.05) -> Optional[float]:
    """Power that `events` events deliver if the true hazard ratio is as given."""
    if hazard_ratio <= 0 or hazard_ratio == 1.0 or events <= 0:
        return None
    statistic = abs(math.log(hazard_ratio)) * math.sqrt(events) / 2 - _z(1 - alpha / 2)
    return float(stats.norm.cdf(statistic))


def participants_for_events(events: int, event_probability: float) -> Optional[int]:
    """Participants needed to observe `events`, given an overall event rate."""
    if not 0 < event_probability <= 1:
        return None
    return int(math.ceil(events / event_probability))


def evaluate(
    assumed_hr: float,
    true_hr: float,
    label: str,
    alpha: float = 0.05,
    target_power: float = 0.80,
    event_probability: Optional[float] = None,
) -> DesignResult:
    """What a trial sized on `assumed_hr` actually delivers if truth is `true_hr`."""
    planned = required_events(assumed_hr, alpha, target_power)
    needed = required_events(true_hr, alpha, target_power)
    delivered = power_at_events(true_hr, planned, alpha) if planned else None
    return DesignResult(
        label=label,
        hazard_ratio=true_hr,
        required_events=needed,
        required_participants=participants_for_events(needed, event_probability)
        if needed and event_probability
        else None,
        power_at_planned_events=delivered,
    )


def design_comparison(
    assumed_hr: float,
    literature_hr: Optional[float],
    registry_hr: Optional[float],
    alpha: float = 0.05,
    target_power: float = 0.80,
    event_probability: Optional[float] = None,
) -> Dict[str, Any]:
    """Compare the user's assumption against both evidence-based estimates.

    Returns the design each estimate implies, and what the user's own design
    would actually deliver if the registry-aware estimate is closer to the truth.
    """
    planned_events = required_events(assumed_hr, alpha, target_power)
    rows = [
        DesignResult(
            label="Your assumption",
            hazard_ratio=assumed_hr,
            required_events=planned_events,
            required_participants=participants_for_events(planned_events, event_probability)
            if planned_events and event_probability
            else None,
            power_at_planned_events=target_power,
            note="The design as proposed, by construction hitting its power target.",
        )
    ]
    for label, value in (
        ("Published-literature estimate", literature_hr),
        ("Registry-aware estimate", registry_hr),
    ):
        if value is None:
            rows.append(DesignResult(label=label, hazard_ratio=float("nan"),
                                     note="Not enough poolable evidence in this cohort."))
            continue
        rows.append(
            evaluate(assumed_hr, value, label, alpha, target_power, event_probability)
        )

    consequence = None
    registry_row = next(
        (r for r in rows if r.label == "Registry-aware estimate" and r.required_events), None
    )
    if registry_row and planned_events:
        delivered = registry_row.power_at_planned_events or 0.0
        extra = registry_row.required_events - planned_events
        consequence = {
            "planned_events": planned_events,
            "delivered_power_if_registry_aware_is_true": delivered,
            "power_shortfall": max(0.0, target_power - delivered),
            "additional_events_needed": max(0, extra),
            "summary": (
                "A trial sized for HR {:.2f} needs {} events. If the registry-aware "
                "estimate of HR {:.2f} is closer to the truth, those {} events deliver "
                "{:.0%} power rather than {:.0%}, and reaching the target would take "
                "{} events ({:+,} more).".format(
                    assumed_hr, planned_events, registry_row.hazard_ratio, planned_events,
                    delivered, target_power, registry_row.required_events, extra,
                )
            ),
        }

    return {
        "alpha": alpha,
        "target_power": target_power,
        "assumed_hazard_ratio": assumed_hr,
        "event_probability": event_probability,
        "rows": [row.to_dict() for row in rows],
        "consequence": consequence,
        "method": (
            "Schoenfeld approximation for the log-rank test, 1:1 allocation. "
            "Event counts drive the calculation; participant counts appear only "
            "when an overall event probability is supplied."
        ),
    }
