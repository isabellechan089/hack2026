"""Recover effect estimates from publications when the registry posted none.

Most trials in category C posted outcome tables with no analysis, yet many of
them have a paper that reports the hazard ratio. This module reads those
papers -- open full text from Europe PMC, reduced to hazard-ratio sentences --
and attaches what a language model extracts, validated against the sentence it
came from.

Estimates recovered this way are marked `source="publication"`, kept apart from
registry postings (section 19: extracted facts are labelled as such). Note what
this does and does not fix: a trial recovered here has a publication by
construction, so it joins category A. The registry-only arm (B) cannot be
rescued from the literature, because there is nothing to read.
"""

import time
from typing import Any, Dict, List, Optional

from ..llm import client, extraction
from ..models.effects import HAZARD_RATIO, EffectEstimate
from ..sources import europepmc
from .cohort import Cohort
from .linkage import CATEGORY_C


# This runs inside a request while somebody waits, and Europe PMC is slow
# enough that a paper count alone does not bound it: eighty articles that each
# time out would hold the connection open for hours. The run is capped by the
# clock as well, and reports where it stopped rather than pretending it
# finished -- a partial recovery is a partial recovery.
_TIME_BUDGET_SECONDS = 120.0


def recover(cohort: Cohort, max_papers: int = 80, run_one_baseline: bool = False,
            time_budget: float = _TIME_BUDGET_SECONDS) -> Dict[str, Any]:
    """Attach publication-extracted hazard ratios to trials that lack one."""
    deadline = time.time() + time_budget
    endpoint = cohort.endpoint_class
    targets = [t for t in cohort.trials if t.category(endpoint) == CATEGORY_C and t.links]
    pmids = [l.pmid for t in targets for l in t.links if l.pmid]
    avail = europepmc.availability(pmids)

    report: Dict[str, Any] = {
        "candidates": len(targets),
        "with_full_text": 0,
        "papers_read": 0,
        "estimates_extracted": 0,
        "trials_recovered": 0,
        "trials_recovered_other_endpoint": 0,
        "tokens_measured": 0,
        "tokens_previously_spent": 0,   # served from cache this run, paid for once before
        "tokens_if_whole_papers": 0,
        "tier_counts": {"small": 0, "large": 0, "cached": 0},
        "baseline_measured": None,
        "stopped_early": None,
        "recovered": [],
    }

    for trial in targets:
        if report["papers_read"] >= max_papers:
            report["stopped_early"] = "paper limit ({})".format(max_papers)
            break
        if time.time() > deadline:
            report["stopped_early"] = "time budget ({:.0f}s)".format(time_budget)
            break
        link = next((l for l in trial.links if l.pmid and avail.get(l.pmid, {}).get("full_text")), None)
        if link is None:
            continue
        report["with_full_text"] += 1
        article = europepmc.full_text(avail[link.pmid]["pmcid"])
        if not article:
            continue
        sentences = europepmc.hazard_ratio_sentences(article)
        report["papers_read"] += 1
        report["tokens_if_whole_papers"] += client.estimate_tokens(article["text"])
        if not sentences:
            continue

        try:
            result = extraction.extract_hazard_ratios(sentences, purpose="recover:{}".format(trial.trial.nct_id))
        except (client.BudgetExceeded, client.LLMUnavailable) as stop:
            report["stopped_early"] = "model unavailable: {}".format(str(stop)[:60])
            break
        report["tokens_measured"] += result["tokens"]
        report["tokens_previously_spent"] += result.get("tokens_cached", 0)
        report["tier_counts"]["cached" if result.get("cached") else result["tier"]] += 1

        added = 0
        for est in result["estimates"]:
            trial.effects.append(EffectEstimate(
                nct_id=trial.trial.nct_id,
                measure=HAZARD_RATIO,
                value=est["hazard_ratio"],
                ci_lower=est.get("ci_lower"),
                ci_upper=est.get("ci_upper"),
                outcome_title=est.get("comparison") or "extracted from publication",
                outcome_type="PUBLISHED",
                endpoint_class=est["endpoint"],
                source="publication",
                source_url="https://europepmc.org/article/PMC/{}".format(article["pmcid"]),
                excluded_reason=None,
            ))
            added += 1
        report["estimates_extracted"] += added
        if added:
            if trial.best_effect(endpoint) is not None:
                report["trials_recovered"] += 1
                report["recovered"].append({
                    "nct_id": trial.trial.nct_id, "pmid": link.pmid,
                    "pmcid": article["pmcid"], "estimates": result["estimates"][:3],
                    "model": result["model"], "sentences_sent": len(sentences),
                })
            else:
                report["trials_recovered_other_endpoint"] += 1

    # One whole-paper call, measured for real, so the baseline is not only an estimate.
    if run_one_baseline and report["recovered"]:
        first = report["recovered"][0]
        article = europepmc.full_text(first["pmcid"])
        if article:
            try:
                res = client.chat_json(
                    [{"role": "system", "content": extraction.SYSTEM},
                     {"role": "user", "content": "Full paper:\n" + article["text"][:60000]}],
                    extraction.SCHEMA, "hazard_ratios", model=client.TIER_SMALL, purpose="baseline_whole_paper",
                )
                report["baseline_measured"] = {
                    "pmcid": first["pmcid"],
                    "prompt_tokens": res["usage"]["prompt_tokens"],
                    "vs_optimized_prompt_tokens_for_same_paper": None,
                }
            except (client.BudgetExceeded, client.LLMUnavailable):
                pass

    spent_total = report["tokens_measured"] + report["tokens_previously_spent"]
    if report["tokens_if_whole_papers"]:
        report["token_reduction"] = round(1 - spent_total / report["tokens_if_whole_papers"], 3)
        report["tokens_spent_total"] = spent_total
    return report
