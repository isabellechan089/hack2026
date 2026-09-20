"""Explainable reviewer-conflict paths (spec section 6).

The output is deliberately not a score. An editor is given the exact
coauthorship path between a candidate reviewer and each manuscript author,
the works that establish every step, and the dates -- then applies their own
journal's policy. Section 19 rule 9 is explicit that a graph relationship does
not by itself disqualify a reviewer.
"""

from typing import Any, Dict, List, Optional, Sequence

import networkx as nx

from ..sources import openalex
from ..sources.http import SourceError
from .coauthors import build_bridge_graph, edge_evidence

RELATIONSHIP = "coauthored_with"


def resolve_author(query: str) -> Optional[Dict[str, Any]]:
    """Resolve a name, ORCID or OpenAlex id to one author record."""
    query = (query or "").strip()
    if not query:
        return None
    # An OpenAlex author id is already resolved; only a name needs searching.
    bare = query.rstrip("/").split("/")[-1]
    if bare.upper().startswith("A") and bare[1:].isdigit():
        return {"id": "https://openalex.org/" + bare.upper(), "display_name": None}
    try:
        candidates = openalex.search_authors(query, limit=1)
    except SourceError:
        return None
    return candidates[0] if candidates else None


def _name(graph: nx.Graph, node: str) -> str:
    return graph.nodes.get(node, {}).get("name") or node


def find_conflicts(
    reviewer_id: str,
    manuscript_author_ids: Sequence[str],
    max_hops: int = 2,
    since_year: Optional[int] = None,
    max_paths_per_author: int = 5,
) -> Dict[str, Any]:
    """Every coauthorship path from a reviewer to each manuscript author."""
    manuscript_author_ids = [a for a in manuscript_author_ids if a]
    if not manuscript_author_ids:
        raise ValueError("At least one manuscript author is required.")
    if reviewer_id in manuscript_author_ids:
        return {
            "reviewer": reviewer_id,
            "minimum_distance": 0,
            "results": [
                {
                    "manuscript_author": reviewer_id,
                    "distance": 0,
                    "paths": [],
                    "note": "The candidate reviewer is also a manuscript author.",
                }
            ],
            "searched_max_hops": max_hops,
            "since_year": since_year,
        }

    graph = build_bridge_graph(reviewer_id, manuscript_author_ids, max_hops, since_year)

    results: List[Dict[str, Any]] = []
    distances: List[int] = []
    for author_id in manuscript_author_ids:
        entry: Dict[str, Any] = {
            "manuscript_author": author_id,
            "manuscript_author_name": _name(graph, author_id),
            "distance": None,
            "paths": [],
        }
        if not graph.has_node(author_id) or not nx.has_path(graph, reviewer_id, author_id):
            entry["note"] = (
                "No coauthorship path found within {} hop(s){}. This is not proof "
                "that no relationship exists -- only that none appears in the "
                "OpenAlex coauthorship graph inside the searched range.".format(
                    max_hops, " since {}".format(since_year) if since_year else ""
                )
            )
            results.append(entry)
            continue

        distance = nx.shortest_path_length(graph, reviewer_id, author_id)
        entry["distance"] = distance
        distances.append(distance)

        paths = []
        for path in nx.all_simple_paths(graph, reviewer_id, author_id, cutoff=max_hops):
            steps = []
            for left, right in zip(path, path[1:]):
                evidence = edge_evidence(graph, left, right)
                steps.append(
                    {
                        "from": left,
                        "from_name": _name(graph, left),
                        "to": right,
                        "to_name": _name(graph, right),
                        "relationship": RELATIONSHIP,
                        **evidence,
                    }
                )
            paths.append(
                {
                    "authors": path,
                    "author_names": [_name(graph, node) for node in path],
                    "length": len(path) - 1,
                    "steps": steps,
                }
            )
        paths.sort(key=lambda item: item["length"])
        entry["paths"] = paths[:max_paths_per_author]
        entry["path_count"] = len(paths)
        entry["summary"] = _summarize(entry["paths"][0]) if entry["paths"] else ""
        results.append(entry)

    return {
        "reviewer": reviewer_id,
        "reviewer_name": _name(graph, reviewer_id),
        "minimum_distance": min(distances) if distances else None,
        "results": results,
        "searched_max_hops": max_hops,
        "since_year": since_year,
        "graph_size": {"authors": graph.number_of_nodes(), "edges": graph.number_of_edges()},
        "interpretation": (
            "Distances and paths are computed from the OpenAlex coauthorship graph. "
            "A path is a described relationship, not a policy judgement: whether it "
            "constitutes a conflict is the editor's decision."
        ),
    }


def _summarize(path: Dict[str, Any]) -> str:
    """One sentence per step, naming the people and the collaboration dates."""
    sentences = []
    for step in path["steps"]:
        window = ""
        first, last = step.get("first_collaboration_year"), step.get("most_recent_collaboration_year")
        if first and last:
            window = " ({})".format(first if first == last else "{}-{}".format(first, last))
        sentences.append(
            "{} coauthored {} work(s) with {}{}.".format(
                step["from_name"] or "this author",
                step["shared_work_count"],
                step["to_name"] or "that author",
                window,
            )
        )
    return " ".join(sentences)
