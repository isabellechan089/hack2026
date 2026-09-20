"""Coauthorship ego networks from OpenAlex (spec section 6).

Building the global coauthor graph is out of scope for a hackathon and
unnecessary: a reviewer conflict check only needs the neighbourhood around a
handful of named people. This module expands outward from specific authors and
records the works that justify each edge, so every relationship can be shown
with its evidence rather than asserted.
"""

from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import networkx as nx

from ..sources import openalex
from ..sources.http import SourceError


def _work_authors(work: Dict[str, Any]) -> List[Tuple[str, str]]:
    out = []
    for authorship in work.get("authorships") or []:
        author = authorship.get("author") or {}
        if author.get("id"):
            out.append((author["id"], author.get("display_name") or ""))
    return out


def expand(
    graph: nx.Graph,
    author_ids: Iterable[str],
    since_year: Optional[int] = None,
    works_per_author: int = 200,
    max_authors_per_work: int = 60,
) -> Set[str]:
    """Add each author's coauthors to the graph; return the new frontier.

    Very large author lists (consortium papers) are skipped: they connect
    hundreds of people who never worked together directly, which would make
    every path look like a conflict.
    """
    frontier: Set[str] = set()
    for author_id in author_ids:
        if graph.nodes.get(author_id, {}).get("expanded"):
            continue
        try:
            works = openalex.get_author_works(author_id, limit=works_per_author)
        except SourceError:
            graph.add_node(author_id, expanded=False, lookup_failed=True)
            continue

        graph.add_node(author_id, expanded=True)
        for work in works:
            year = work.get("publication_year")
            if since_year and (year is None or year < since_year):
                continue
            authors = _work_authors(work)
            if len(authors) > max_authors_per_work:
                continue
            ids = [a for a, _ in authors]
            if author_id not in ids:
                continue
            evidence = {
                "openalex_work": work.get("id"),
                "doi": (work.get("doi") or "").replace("https://doi.org/", "") or None,
                "title": work.get("display_name"),
                "year": year,
            }
            for other_id, other_name in authors:
                if other_id == author_id:
                    continue
                if other_id not in graph:
                    graph.add_node(other_id, name=other_name, expanded=False)
                    frontier.add(other_id)
                elif not graph.nodes[other_id].get("name"):
                    graph.nodes[other_id]["name"] = other_name

                if graph.has_edge(author_id, other_id):
                    works_list = graph.edges[author_id, other_id]["works"]
                    if not any(w["openalex_work"] == evidence["openalex_work"] for w in works_list):
                        works_list.append(evidence)
                else:
                    graph.add_edge(author_id, other_id, works=[evidence])
    return frontier


def build_bridge_graph(
    reviewer_id: str,
    manuscript_author_ids: Sequence[str],
    max_hops: int = 2,
    since_year: Optional[int] = None,
) -> nx.Graph:
    """Expand from both ends until paths up to `max_hops` are resolvable.

    Expanding from both sides and meeting in the middle keeps the number of API
    calls proportional to the people involved rather than to the literature. A
    path of length L is found once both sides have expanded ceil(L/2) times.
    """
    graph = nx.Graph()
    graph.add_node(reviewer_id, expanded=False, role="reviewer")
    for author_id in manuscript_author_ids:
        graph.add_node(author_id, expanded=False, role="manuscript_author")

    rounds = max(1, (max_hops + 1) // 2)
    reviewer_side: Set[str] = {reviewer_id}
    author_side: Set[str] = set(manuscript_author_ids)

    for _ in range(rounds):
        reviewer_side = expand(graph, reviewer_side, since_year)
        author_side = expand(graph, author_side, since_year)
        # Stop as soon as every manuscript author is reachable; expanding
        # further would cost API calls without changing any shortest path.
        if all(
            graph.has_node(author_id) and nx.has_path(graph, reviewer_id, author_id)
            for author_id in manuscript_author_ids
        ):
            break
    return graph


def edge_evidence(graph: nx.Graph, left: str, right: str, limit: int = 5) -> Dict[str, Any]:
    """Summarize a coauthorship edge: shared works, first and last year."""
    works = graph.edges[left, right]["works"]
    years = sorted(w["year"] for w in works if w.get("year"))
    return {
        "shared_work_count": len(works),
        "first_collaboration_year": years[0] if years else None,
        "most_recent_collaboration_year": years[-1] if years else None,
        "works": sorted(works, key=lambda w: w.get("year") or 0, reverse=True)[:limit],
    }
