"""Effect estimates on a single comparable scale.

Section 3 step 6 requires one coherent effect scale. Hazard ratios are
analysed as log(HR), which is additive and approximately normal, so trials can
be pooled. Section 19 rule 10 forbids mixing incomparable measures, so anything
that is not a hazard ratio is recorded and then excluded from pooling rather
than silently coerced.
"""

import math
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

HAZARD_RATIO = "hazard_ratio"

# Two-sided 95% CI multiplier; registry analyses report 95% intervals.
_Z95 = 1.959963984540054


@dataclass
class EffectEstimate:
    """One reported effect, kept with everything needed to judge it."""

    nct_id: str
    measure: str  # "hazard_ratio", or the raw registry label when unusable
    value: Optional[float] = None
    ci_lower: Optional[float] = None
    ci_upper: Optional[float] = None
    p_value: Optional[str] = None
    outcome_title: Optional[str] = None
    outcome_type: Optional[str] = None  # PRIMARY | SECONDARY
    endpoint_class: Optional[str] = None  # "os" | "pfs" | "other"
    groups: List[str] = field(default_factory=list)
    source: str = "clinicaltrials.gov"
    source_url: str = ""
    # Set when the estimate cannot be pooled, with the reason why.
    excluded_reason: Optional[str] = None

    @property
    def log_value(self) -> Optional[float]:
        if self.value is None or self.value <= 0:
            return None
        return math.log(self.value)

    @property
    def standard_error(self) -> Optional[float]:
        """SE of log(HR), derived from the reported 95% confidence interval.

        There is no other way to recover precision from registry postings, which
        publish an interval rather than a variance.
        """
        if self.ci_lower is None or self.ci_upper is None:
            return None
        if self.ci_lower <= 0 or self.ci_upper <= 0 or self.ci_upper <= self.ci_lower:
            return None
        return (math.log(self.ci_upper) - math.log(self.ci_lower)) / (2 * _Z95)

    @property
    def is_poolable(self) -> bool:
        """Usable in a pooled estimate: a hazard ratio with recoverable variance."""
        return (
            self.measure == HAZARD_RATIO
            and self.excluded_reason is None
            and self.log_value is not None
            and (self.standard_error or 0) > 0
        )

    @property
    def favors_treatment(self) -> Optional[bool]:
        """True when the point estimate is below 1 (fewer events on treatment)."""
        if self.value is None:
            return None
        return self.value < 1.0

    @property
    def is_significant(self) -> Optional[bool]:
        """Significance read from the CI, not from the reported p-value string.

        Registry p-values arrive as free text such as "<0.001" or "0.002", so the
        interval is the more reliable and uniform signal.
        """
        if self.ci_lower is None or self.ci_upper is None:
            return None
        return not (self.ci_lower <= 1.0 <= self.ci_upper)

    def to_dict(self) -> Dict[str, Any]:
        out = asdict(self)
        out.update(
            log_value=self.log_value,
            standard_error=self.standard_error,
            is_poolable=self.is_poolable,
            favors_treatment=self.favors_treatment,
            is_significant=self.is_significant,
        )
        return out
