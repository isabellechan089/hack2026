#!/usr/bin/env python
"""Command-line entry point.

Hero feature -- bias-aware trial design:

    python cli.py design --condition "non-small cell lung cancer" --hr 0.65

Supporting views:

    python cli.py cohort --condition "non-small cell lung cancer"
    python cli.py reviewer --reviewer "Martin Reck" --authors "Tony Mok"
    python cli.py trial NCT01866319          # trial -> its publications
    python cli.py paper 36416836             # publication -> its trial(s)
    python cli.py compare NCT02506153 36416836

Every number printed here comes from registry records, the scholarly graph, or
a statistical model. No language model is involved.
"""

import argparse
import json
import sys
from typing import List, Optional

from backend.compare.trial_publication import compare
from backend.matching.publication_role import ROLE_LABELS, classify
from backend.matching.trial_paper_matcher import (
    find_publications_for_trial,
    find_trials_for_paper,
    score_match,
)
from backend.models.comparison import (
    DIFFERENCE,
    MATCH,
    NOT_COMPARABLE,
    NOT_FOUND,
    NOT_REGISTERED,
    TrialPublicationComparison,
)
from backend.publication_bias.analysis import analyze
from backend.publication_bias.cohort import describe, load_or_build, save_cohort
from backend.render import BOLD, DIM, RESET, render, rule, wrap
from backend.sources import clinical_trials, pubmed
from backend.sources.http import SourceError

BOLD, DIM, RESET = "\033[1m", "\033[2m", "\033[0m"
COLORS = {
    MATCH: "\033[32m",
    DIFFERENCE: "\033[33m",
    NOT_FOUND: "\033[35m",
    NOT_REGISTERED: "\033[35m",
    NOT_COMPARABLE: "\033[2m",
}
SYMBOLS = {
    MATCH: "match",
    DIFFERENCE: "DIFFERENCE",
    NOT_FOUND: "not identified",
    NOT_REGISTERED: "not registered",
    NOT_COMPARABLE: "not comparable",
}


def _truncate(text: Optional[str], width: int) -> str:
    text = (text or "--").replace("\n", " ")
    return text if len(text) <= width else text[: width - 1] + "…"


def _rule(char: str = "-", width: int = 104) -> str:
    return DIM + char * width + RESET


def print_comparison(comparison: TrialPublicationComparison, show_evidence: bool) -> None:
    print()
    print(BOLD + "REGISTERED vs PUBLISHED" + RESET)
    print(_rule("="))
    print("  Trial       {}  {}".format(comparison.nct_id, _truncate(comparison.trial_title, 62)))
    print("  Publication PMID {:<9}  {}".format(
        comparison.pmid or "--", _truncate(comparison.paper_title, 62)))
    if comparison.doi:
        print("  DOI         {}".format(comparison.doi))
    print("  Link basis  {} (confidence: {})".format(
        "declared identifier" if comparison.match_basis == "identifier" else comparison.match_basis,
        comparison.match_confidence,
    ))
    print(_rule())
    print("  {:<46} {:<22} {:<16}".format("FIELD", "REGISTERED", "PUBLISHED"))
    print(_rule())

    for row in comparison.fields:
        color = COLORS.get(row.status, "")
        print("  {:<46} {:<22} {:<16} {}{}{}".format(
            _truncate(row.field_name, 45),
            _truncate(row.registered, 21),
            _truncate(row.published, 15),
            color, SYMBOLS.get(row.status, row.status), RESET,
        ))
        if row.status in (DIFFERENCE, NOT_FOUND) and row.note:
            print("    {}{}{}".format(DIM, _truncate(row.note, 98), RESET))
        if show_evidence:
            for item in row.evidence:
                print("    {}> [{}] {}{}".format(
                    DIM, item.locator, _truncate(item.quote, 88), RESET))

    print(_rule())
    counts = comparison.counts
    print("  " + "   ".join(
        "{}{}: {}{}".format(COLORS.get(status, ""), SYMBOLS.get(status, status), count, RESET)
        for status, count in sorted(counts.items())
    ))
    print()
    print("  {}Scope: {}{}".format(DIM, comparison.evidence_scope, RESET))
    print("  {}Differences are reported as differences. They are not, on their own,{}".format(DIM, RESET))
    print("  {}evidence of error or misconduct.{}".format(DIM, RESET))
    print()
    print("  Sources: " + "  ".join(item["url"] for item in comparison.provenance if item.get("url")))
    print()


def cmd_trial(args: argparse.Namespace) -> int:
    trial = clinical_trials.get_trial(args.nct_id)
    print()
    print(BOLD + "TRIAL " + trial.nct_id + RESET + "  " + _truncate(trial.title, 74))
    print("  Sponsor {} | {} | enrollment {} ({}) | {}".format(
        _truncate(trial.lead_sponsor, 34), ", ".join(trial.phases) or "phase n/a",
        trial.enrollment, (trial.enrollment_type or "n/a").lower(), trial.status))
    print("  Registered primary outcome(s): " + (
        "; ".join(outcome.measure for outcome in trial.primary_outcomes) or "none listed"))

    matches = find_publications_for_trial(trial)
    if not matches:
        print("\n  No linked publications found in the registry record.\n")
        return 0

    rows = []
    for match in matches:
        paper = pubmed.get_paper_by_pmid(match.pmid) if match.pmid else None
        if paper is None:
            continue
        comparison = compare(trial, paper, match)
        role, rank, reasons = classify(trial, paper, comparison, match)
        rows.append((rank, role, reasons, paper, comparison))
    rows.sort(key=lambda row: row[0], reverse=True)

    print()
    print(BOLD + "LINKED PUBLICATIONS" + RESET + DIM + "  (ranked by how much of the registered "
          "trial each one actually reports)" + RESET)
    print(_rule())
    for rank, role, reasons, paper, comparison in rows[: args.limit]:
        counts = comparison.counts
        print("  {:<10} {:<19} {:<52} {}".format(
            paper.publication_date or "----",
            role,
            _truncate(paper.title, 51),
            DIM + "PMID " + (paper.pmid or "--") + RESET,
        ))
        print("    {}{}  |  {}{}".format(
            DIM, ROLE_LABELS.get(role, role),
            "  ".join("{} {}".format(SYMBOLS.get(k, k), v) for k, v in sorted(counts.items())),
            RESET,
        ))
        if args.why:
            for reason in reasons:
                print("      {}- {}{}".format(DIM, reason, RESET))
    print(_rule())

    if rows and not args.no_table:
        print_comparison(rows[0][4], args.evidence)
    return 0


def cmd_paper(args: argparse.Namespace) -> int:
    paper = pubmed.get_paper_by_pmid(args.pmid)
    if paper is None:
        print("No PubMed record found for {}".format(args.pmid), file=sys.stderr)
        return 1
    print()
    print(BOLD + "PUBLICATION PMID " + (paper.pmid or "--") + RESET)
    print("  " + _truncate(paper.title, 96))
    print("  {} | {} | DOI {}".format(
        paper.journal or "journal n/a", paper.publication_date or "date n/a", paper.doi or "--"))
    print("  Declared registry identifiers: " + (
        ", ".join(paper.registered_trial_ids) or "none declared in the PubMed record"))

    matches = find_trials_for_paper(paper)
    if not matches:
        print("\n  No candidate trial found.\n")
        return 0

    best = matches[0]
    trial = clinical_trials.get_trial(best.nct_id)
    print_comparison(compare(trial, paper, best), args.evidence)
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    trial = clinical_trials.get_trial(args.nct_id)
    paper = pubmed.get_paper_by_pmid(args.pmid)
    if paper is None:
        print("No PubMed record found for {}".format(args.pmid), file=sys.stderr)
        return 1
    match = score_match(trial, paper)
    comparison = compare(trial, paper, match)
    if args.json:
        print(json.dumps(comparison.to_dict(), indent=2))
        return 0
    print()
    print(BOLD + "MATCH SIGNALS" + RESET + DIM + "  (why these two records were linked)" + RESET)
    print(_rule())
    for signal in match.signals:
        print("  {:<24} {:>5.2f}  {}".format(
            signal.name, signal.contribution, _truncate(signal.evidence, 68)))
    print(_rule())
    print("  score {:.3f}  basis {}  confidence {}".format(
        match.score, match.basis, match.confidence))
    print_comparison(comparison, args.evidence)
    return 0


def _progress(index: int, total: int, nct_id: str) -> None:
    if index % 25 == 0 or index == total:
        print("  building cohort {}/{} ({})".format(index, total, nct_id), file=sys.stderr)


def _load_cohort(args: argparse.Namespace):
    """Use a saved cohort when one exists, so a demo never depends on the APIs."""
    return load_or_build(
        args.condition,
        endpoint_class=args.endpoint,
        phases=tuple(args.phases.split(",")),
        max_studies=args.max_studies,
        rebuild=args.rebuild,
        progress=None if args.quiet else _progress,
    )


def cmd_design(args: argparse.Namespace) -> int:
    cohort = _load_cohort(args)
    if args.save:
        print("  cohort saved to {}".format(save_cohort(cohort)), file=sys.stderr)
    report = analyze(
        cohort,
        assumed_hr=args.hr,
        alpha=args.alpha,
        target_power=args.power,
        event_probability=args.event_probability,
        run_backtest=not args.no_backtest,
    )
    if args.json:
        print(json.dumps(report, indent=2, default=str))
        return 0
    print(render(report))
    return 0


def cmd_cohort(args: argparse.Namespace) -> int:
    cohort = _load_cohort(args)
    path = save_cohort(cohort) if args.save else None
    summary = describe(cohort)
    if args.json:
        print(json.dumps(summary, indent=2))
        return 0
    print()
    print(BOLD + "COHORT " + summary["condition"] + RESET)
    print(rule())
    for key in ("trials", "with_publication_identified", "publication_linkage_rate",
                "with_usable_effect", "excluded"):
        print("  {:<36} {}".format(key.replace("_", " "), summary[key]))
    print("  categories                           {}".format(summary["categories"]))
    print("  sponsor types                        {}".format(summary["sponsor_types"]))
    if path:
        print("  saved to                             {}".format(path))
    print()
    return 0


def cmd_reviewer(args: argparse.Namespace) -> int:
    from backend.graph.reviewer_conflicts import find_conflicts, resolve_author

    reviewer = resolve_author(args.reviewer)
    if reviewer is None:
        print("Could not resolve reviewer {!r} in OpenAlex.".format(args.reviewer), file=sys.stderr)
        return 1
    authors = []
    for name in [a.strip() for a in args.authors.split(",") if a.strip()]:
        record = resolve_author(name)
        if record is None:
            print("Could not resolve manuscript author {!r}.".format(name), file=sys.stderr)
            continue
        authors.append(record["id"])
    if not authors:
        print("No manuscript authors could be resolved.", file=sys.stderr)
        return 1

    result = find_conflicts(
        reviewer["id"], authors, max_hops=args.max_hops, since_year=args.since_year
    )
    if args.json:
        print(json.dumps(result, indent=2))
        return 0

    print()
    print(BOLD + "REVIEWER CONFLICT CHECK" + RESET)
    print(rule("="))
    print("  Reviewer  {} ({})".format(result.get("reviewer_name") or args.reviewer, result["reviewer"]))
    print("  Searched  up to {} hop(s){}".format(
        result["searched_max_hops"],
        " since {}".format(result["since_year"]) if result["since_year"] else ""))
    print("  Minimum graph distance: {}".format(
        result["minimum_distance"] if result["minimum_distance"] is not None else "no path found"))
    print(rule())
    for entry in result["results"]:
        print("  {}{}{}  distance {}".format(
            BOLD, entry.get("manuscript_author_name") or entry["manuscript_author"], RESET,
            entry["distance"] if entry["distance"] is not None else "--"))
        if entry.get("note"):
            print(wrap(DIM + entry["note"] + RESET, indent="    "))
        if entry.get("summary"):
            print(wrap(entry["summary"], indent="    "))
        for path in entry.get("paths", [])[:args.max_paths]:
            print("    " + DIM + " -> ".join(path["author_names"]) + RESET)
            for step in path["steps"]:
                for work in step["works"][:2]:
                    print("       {} {} {}".format(
                        DIM, work.get("year") or "----",
                        (work.get("title") or "")[:66] + RESET))
        print()
    print(wrap(DIM + result["interpretation"] + RESET))
    print()
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--evidence", action="store_true", help="print source quotes for every row")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_cohort_args(parser_obj):
        parser_obj.add_argument("--condition", required=True, help="disease area for the cohort")
        parser_obj.add_argument("--endpoint", default="os", choices=("os", "pfs"))
        parser_obj.add_argument("--phases", default="2,3")
        parser_obj.add_argument("--max-studies", type=int, default=300, dest="max_studies")
        parser_obj.add_argument("--save", action="store_true", help="write the cohort to data/cohorts/")
        parser_obj.add_argument("--rebuild", action="store_true",
                                help="ignore any saved cohort and refetch from the live APIs")
        parser_obj.add_argument("--quiet", action="store_true")
        parser_obj.add_argument("--json", action="store_true")

    design_parser = subparsers.add_parser("design", help="bias-aware trial design (hero feature)")
    add_cohort_args(design_parser)
    design_parser.add_argument("--hr", type=float, default=0.65, help="your assumed hazard ratio")
    design_parser.add_argument("--alpha", type=float, default=0.05)
    design_parser.add_argument("--power", type=float, default=0.80)
    design_parser.add_argument("--event-probability", type=float, default=None,
                               dest="event_probability",
                               help="overall event probability, to convert events into participants")
    design_parser.add_argument("--no-backtest", action="store_true", dest="no_backtest")
    design_parser.set_defaults(func=cmd_design)

    cohort_parser = subparsers.add_parser("cohort", help="build and summarize a registry cohort")
    add_cohort_args(cohort_parser)
    cohort_parser.set_defaults(func=cmd_cohort)

    reviewer_parser = subparsers.add_parser("reviewer", help="reviewer conflict paths")
    reviewer_parser.add_argument("--reviewer", required=True)
    reviewer_parser.add_argument("--authors", required=True, help="comma-separated manuscript authors")
    reviewer_parser.add_argument("--max-hops", type=int, default=2, dest="max_hops")
    reviewer_parser.add_argument("--since-year", type=int, default=None, dest="since_year")
    reviewer_parser.add_argument("--max-paths", type=int, default=3, dest="max_paths")
    reviewer_parser.add_argument("--json", action="store_true")
    reviewer_parser.set_defaults(func=cmd_reviewer)

    trial_parser = subparsers.add_parser("trial", help="compare a trial against its publications")
    trial_parser.add_argument("nct_id")
    trial_parser.add_argument("--limit", type=int, default=8)
    trial_parser.add_argument("--why", action="store_true", help="explain each role classification")
    trial_parser.add_argument("--no-table", action="store_true", help="list publications only")
    trial_parser.set_defaults(func=cmd_trial)

    paper_parser = subparsers.add_parser("paper", help="find the trial behind a publication")
    paper_parser.add_argument("pmid")
    paper_parser.set_defaults(func=cmd_paper)

    compare_parser = subparsers.add_parser("compare", help="compare one specific pair")
    compare_parser.add_argument("nct_id")
    compare_parser.add_argument("pmid")
    compare_parser.add_argument("--json", action="store_true")
    compare_parser.set_defaults(func=cmd_compare)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except SourceError as exc:
        print("Source error: {}".format(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
