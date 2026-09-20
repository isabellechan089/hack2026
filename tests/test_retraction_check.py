"""Tests for the reference-integrity check and the OpenAlex-screened graph."""

import os
import sys
import unittest
from unittest.mock import patch

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import retraction_check
from graph import blast_radius, build_graph


def work(index, retracted=False, doi=None):
    return {
        "id": "https://openalex.org/W{}".format(index),
        "doi": "https://doi.org/10.1234/w{}".format(index) if doi is None else doi,
        "display_name": "Work {}".format(index),
        "publication_year": 2020,
        "publication_date": "2020-01-01",
        "is_retracted": retracted,
        "cited_by_count": index,
    }


class SourceCheckTests(unittest.TestCase):
    def _run(self, references, flags, notices=None, deep=False, unresolvable=()):
        """Run check_sources against a stubbed OpenAlex and Crossref."""
        seed = {
            "id": "https://openalex.org/W1", "doi": "https://doi.org/10.1234/seed",
            "display_name": "My paper", "publication_year": 2023,
            "publication_date": "2023-01-01", "cited_by_count": 10,
            "referenced_works": ["https://openalex.org/W{}".format(i) for i in references],
            "referenced_works_count": len(references), "is_retracted": False,
            "authorships": [], "primary_location": {"source": {"display_name": "J"}},
        }

        def fake_fetch(url, params=None):
            # The seed lookup asks for fields; the batch screen asks with a filter.
            if not params or "filter" not in params:
                return seed
            wanted = params["filter"].split(":", 1)[1].split("|")
            # Ids in `unresolvable` are simply absent from the response, the way
            # OpenAlex omits a reference it does not hold.
            return {"results": [work(int(w[1:]), w[1:] in flags) for w in wanted
                                if int(w[1:]) in references
                                and int(w[1:]) not in unresolvable]}

        with patch.object(retraction_check, "fetch", side_effect=fake_fetch), \
             patch.object(retraction_check, "get_retraction_evidence",
                          side_effect=lambda doi: (notices or {}).get(
                              doi, {"status": "no_notice_found", "notices": []})):
            return retraction_check.check_sources("10.1234/seed", deep=deep)

    def test_flags_a_retracted_reference_with_its_notice(self):
        notice = {"status": "retracted", "notices": [
            {"doi": "10.1234/notice", "title": "Retraction", "type": "retraction",
             "date": "2023-04-22T00:00:00Z", "source": "retraction-watch"}]}
        result = self._run([2, 3, 4], flags={"3"}, notices={"10.1234/w3": notice})
        self.assertEqual(result["retracted_references"], 1)
        self.assertEqual(len(result["flagged"]), 1)
        self.assertEqual(result["flagged"][0]["title"], "Work 3")
        self.assertEqual(result["flagged"][0]["retraction"]["notices"][0]["type"], "retraction")

    def test_clean_result_does_not_claim_the_list_is_clean(self):
        result = self._run([2, 3], flags=set())
        self.assertEqual(result["retracted_references"], 0)
        self.assertEqual(result["flagged"], [])
        # Section 19: absence of evidence is not evidence of absence.
        self.assertIn("not that the reference list is clean", result["method"])

    def test_deep_mode_checks_every_reference(self):
        notice = {"status": "updated", "notices": [
            {"doi": "10.1234/c", "title": "Correction", "type": "correction",
             "date": "2022-01-01T00:00:00Z", "source": "publisher"}]}
        # OpenAlex does not flag it; only a per-reference Crossref check finds it.
        shallow = self._run([2, 3], flags=set(), notices={"10.1234/w3": notice})
        self.assertEqual(len(shallow["flagged"]), 0)
        deep = self._run([2, 3], flags=set(), notices={"10.1234/w3": notice}, deep=True)
        self.assertEqual(len(deep["flagged"]), 1)
        self.assertEqual(deep["updated_references"], 1)
        self.assertIn("checked individually", deep["method"])

    def test_unresolved_references_are_reported_not_hidden(self):
        # Reference 9 is never returned by the stubbed OpenAlex batch.
        self.assertEqual(self._run([2, 3], flags=set())["references_screened"], 2)
        gapped = self._run([2, 3, 99], flags=set(), unresolvable=(99,))
        self.assertEqual(gapped["references_screened"], 2)
        self.assertEqual(gapped["references_total"], 3)
        self.assertTrue(any("could not be resolved" in w for w in gapped["warnings"]))

    def test_confirmed_retractions_sort_above_softer_notices(self):
        notices = {
            "10.1234/w2": {"status": "updated", "notices": [
                {"doi": "x", "title": "Correction", "type": "correction",
                 "date": None, "source": "publisher"}]},
            "10.1234/w3": {"status": "retracted", "notices": [
                {"doi": "y", "title": "Retraction", "type": "retraction",
                 "date": None, "source": "publisher"}]},
        }
        result = self._run([2, 3], flags={"2", "3"}, notices=notices)
        self.assertEqual(result["flagged"][0]["retraction"]["status"], "retracted")

    def test_citing_a_retracted_paper_is_not_called_an_error(self):
        result = self._run([2], flags=set())
        for word in ("fraud", "misconduct", "invalid", "compromised"):
            self.assertNotIn(word, result["interpretation"].lower())
        self.assertIn("not itself an error", result["interpretation"])


class ScreenedGraphTests(unittest.TestCase):
    """The graph screens with OpenAlex and confirms only what it flags."""

    def _graph(self, citers, confirm):
        seed = {"id": "https://openalex.org/S", "doi": "https://doi.org/10.1/seed",
                "display_name": "Seed", "publication_year": 2020,
                "publication_date": "2020-01-01", "cited_by_count": 5,
                "is_retracted": True, "authorships": []}
        with patch("graph.get_paper", return_value=seed), \
             patch("graph.get_citing_papers", side_effect=lambda i, n: citers if i == seed["id"] else []), \
             patch("graph.count_citing_papers", return_value=99), \
             patch("graph.get_retraction_evidence", side_effect=confirm):
            return build_graph("10.1/seed", depth=1, limit=2)

    def test_crossref_is_called_only_for_the_seed_and_flagged_works(self):
        calls = []

        def confirm(doi):
            calls.append(doi)
            return {"status": "retracted", "notices": [
                {"doi": "n", "title": "N", "type": "retraction",
                 "date": "2023-04-22T00:00:00Z", "source": "s"}]}

        citers = [work(2), work(3, retracted=True)]
        graph = self._graph(citers, confirm)
        # Seed plus the one OpenAlex flagged; the unflagged citer is not fetched.
        self.assertEqual(len(calls), 2)
        unflagged = next(n for n in graph["nodes"] if n["id"].endswith("W2"))
        self.assertEqual(unflagged["retraction"]["status"], "screened")
        self.assertIn("Not individually checked", unflagged["retraction"]["reason"])

    def test_screened_is_distinct_from_unknown(self):
        graph = self._graph([work(2)], lambda doi: {"status": "retracted", "notices": []})
        statuses = {n["retraction"]["status"] for n in graph["nodes"]}
        self.assertIn("screened", statuses)
        self.assertNotIn("unknown", statuses)

    def test_coverage_reports_the_true_citation_total(self):
        graph = self._graph([work(2), work(3)], lambda doi: {"status": "retracted", "notices": []})
        self.assertEqual(graph["coverage"]["direct_citations_total"], 99)
        self.assertEqual(graph["coverage"]["direct_citations_shown"], 2)
        self.assertTrue(
            any("2 most-cited of 99" in w for w in graph["warnings"]),
            graph["warnings"],
        )

    def test_a_screened_node_is_never_treated_as_retracted(self):
        graph = self._graph([work(2)], lambda doi: {"status": "retracted", "notices": [
            {"doi": "n", "title": "N", "type": "retraction",
             "date": "2023-01-01T00:00:00Z", "source": "s"}]})
        screened = next(n for n in graph["nodes"] if n["id"].endswith("W2"))
        self.assertNotEqual(screened["exposure"], "retracted")
        self.assertEqual(screened["exposure"], "direct")


if __name__ == "__main__":
    unittest.main(verbosity=2)
