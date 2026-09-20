"""Terminal rendering for the bias-aware design report.

Kept apart from the analysis so that formatting can never alter a number.
"""

from typing import Any, Dict, List, Optional

BOLD, DIM, RESET = "\033[1m", "\033[2m", "\033[0m"
RED, YELLOW, GREEN, CYAN = "\033[31m", "\033[33m", "\033[32m", "\033[36m"


def rule(char: str = "-", width: int = 96) -> str:
    return DIM + char * width + RESET


def _fmt(value: Optional[float], digits: int = 3) -> str:
    return "--" if value is None else "{:.{}f}".format(value, digits)


def _pct(value: Optional[float]) -> str:
    return "--" if value is None else "{:.0%}".format(value)


def wrap(text: str, width: int = 92, indent: str = "  ") -> str:
    import textwrap

    return "\n".join(textwrap.wrap(text, width, initial_indent=indent, subsequent_indent=indent))


def render(report: Dict[str, Any]) -> str:
    out: List[str] = []
    cohort = report["cohort"]
    categories = cohort["categories"]

    out.append("")
    out.append(BOLD + "BIAS-AWARE TRIAL DESIGN" + RESET)
    out.append(rule("="))
    out.append("  Cohort   {} | phases {} | endpoint {}".format(
        cohort["condition"], "/".join(cohort["phases"]), cohort["endpoint_class"].upper()))
    out.append("  Registry {} completed trials with posted results".format(cohort["trials"]))
    out.append("")

    # --- Act 2: the publication gap
    out.append(BOLD + "1. THE PUBLICATION GAP" + RESET)
    out.append(rule())
    out.append("  {:<52} {:>6}".format("Completed trials in cohort", cohort["trials"]))
    out.append("  {:<52} {:>6}  {}".format(
        "With a publication identified", cohort["with_publication_identified"],
        DIM + _pct(cohort["publication_linkage_rate"]) + RESET))
    out.append("  {:<52} {:>6}".format("With a usable hazard ratio", cohort["with_usable_effect"]))
    out.append("")
    out.append("  {}A{} published + registry result        {:>4}".format(
        GREEN, RESET, categories["A_published_with_result"]))
    out.append("  {}B{} registry result, no publication found {:>4}   {}the observable gap{}".format(
        YELLOW, RESET, categories["B_registry_only_with_result"], DIM, RESET))
    out.append("  {}C{} no usable effect estimate            {:>4}   {}sensitivity analysis only{}".format(
        RED, RESET, categories["C_no_usable_result"], DIM, RESET))
    breakdown = cohort.get("no_result_breakdown") or {}
    for reason, count in (breakdown.get("reasons") or {}).items():
        out.append("      {}{:<48} {:>4}{}".format(DIM, reason[:48], count, RESET))
    if breakdown:
        out.append("      {}{} of these have a publication; {} do not{}".format(
            DIM, breakdown.get("with_publication_identified", 0),
            breakdown.get("without_publication_identified", 0), RESET))

    linkage = report["linkage"]
    if linkage.get("n"):
        out.append("")
        out.append("  Linkage rate among trials that posted a result:")
        for key, label in (("by_significance", "statistically significant"),
                           ("by_direction", "favours treatment"),
                           ("by_sponsor", "industry sponsored")):
            block = linkage.get(key, {})
            pair = list(block.items())
            if len(pair) == 2:
                (ln, lv), (rn, rv) = pair
                out.append("    {:<26} {} {} (n={})   vs   {} (n={})".format(
                    label, DIM + "·" + RESET, _pct(lv["linkage_rate"]), lv["n"],
                    _pct(rv["linkage_rate"]), rv["n"]))

    # --- Act 3: the two priors
    priors = report["priors"]
    lit, reg = priors["literature_only"], priors["registry_aware"]
    out.append("")
    out.append(BOLD + "2. WHAT THE EVIDENCE IMPLIES" + RESET)
    out.append(rule())
    out.append("  {:<26} {:>7} {:>20} {:>8}".format("PRIOR", "HR", "95% CI", "TRIALS"))
    for label, block in (("Literature-only", lit), ("Registry-aware", reg)):
        out.append("  {:<26} {:>7} {:>20} {:>8}".format(
            label, _fmt(block.get("hazard_ratio")),
            "({}, {})".format(_fmt(block.get("ci_lower")), _fmt(block.get("ci_upper")))
            if block.get("ci_lower") else "--",
            block.get("k", 0)))
    out.append("")
    out.append(wrap(priors["interpretation"]))
    out.append(wrap(DIM + priors["caveat"] + RESET))

    # --- Act 3b: the design consequence
    design = report["design"]
    out.append("")
    out.append(BOLD + "3. WHAT THAT DOES TO YOUR DESIGN" + RESET)
    out.append(rule())
    out.append("  alpha {} | target power {} ".format(design["alpha"], _pct(design["target_power"])))
    out.append("  {:<32} {:>7} {:>10} {:>14}".format("BASIS", "HR", "EVENTS", "POWER DELIVERED"))
    for row in design["rows"]:
        hr = row["hazard_ratio"]
        out.append("  {:<32} {:>7} {:>10} {:>14}".format(
            row["label"],
            "--" if hr != hr else _fmt(hr, 2),
            row["required_events"] if row["required_events"] else "not feasible",
            _pct(row["power_at_planned_events"])))
    consequence = design.get("consequence")
    if consequence:
        out.append("")
        out.append(wrap(CYAN + consequence["summary"] + RESET))

    # --- Step 10: sensitivity
    sens = report["sensitivity"]
    if sens.get("points"):
        out.append("")
        out.append(BOLD + "4. IF THE UNKNOWN TRIALS WERE KNOWN" + RESET)
        out.append(rule())
        out.append("  {} trial(s) have neither a publication nor a posted result.".format(
            sens["unknown_trials"]))
        out.append("  {:<40} {:>10} {:>10}".format(
            "ASSUMED HR FOR THOSE TRIALS", "POOLED HR", "EVENTS"))
        for point in sens["points"]:
            out.append("  {:<40} {:>10} {:>10}".format(
                "  {:.2f}".format(point["assumed_hazard_ratio_for_unknowns"]),
                _fmt(point["pooled_hazard_ratio"]),
                point["required_events"] if point["required_events"] else "not feasible"))
        out.append(wrap(DIM + sens["note"] + RESET))

    # --- Section 4: back-test
    back = report["backtest"]
    out.append("")
    out.append(BOLD + "5. DOES THE CORRECTION ACTUALLY HELP?" + RESET)
    out.append(rule())
    if not back.get("ran"):
        out.append(wrap(back.get("note", "Back-test did not run.")))
    else:
        out.append("  Leave-one-out over {} trials, {} prediction interval".format(
            back["n"], _pct(back["level"])))
        out.append("  {:<26} {:>10} {:>12} {:>10}".format("MODEL", "COVERAGE", "MAE log(HR)", "BIAS"))
        for key, label in (("literature_only", "Literature-only"),
                           ("registry_aware", "Registry-aware")):
            block = back["summary"].get(key, {})
            if not block.get("n"):
                out.append("  {:<26} {:>10}".format(label, "--"))
                continue
            out.append("  {:<26} {:>10} {:>12} {:>10}".format(
                label, _pct(block["coverage"]),
                _fmt(block["mean_absolute_error_log_hr"]),
                "{:+.3f}".format(block["bias_log_hr"])))
        out.append("")
        out.append(wrap(back["verdict"]))

    out.append("")
    out.append(rule())
    for line in report["guardrails"]:
        out.append(wrap(DIM + "- " + line + RESET))
    out.append("")
    return "\n".join(out)
