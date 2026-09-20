"""Offline tests for the trial<->publication pipeline.

Every test runs against saved API payloads in tests/fixtures, so the suite needs
no network access and cannot be broken by an upstream outage during a demo.
"""

import json
import os
import sys
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.compare.trial_publication import _core_measure_phrase, compare
from backend.matching.publication_role import MENTIONS_TRIAL, SECONDARY_ANALYSIS, classify
from backend.matching.trial_paper_matcher import _normalize_person, score_match
from backend.models.comparison import DIFFERENCE, MATCH, NOT_FOUND
from backend.sources.clinical_trials import extract_nct_ids, looks_like_nct_id, normalize_study
from backend.sources.pubmed import parse_pubmed_article

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def load_trial(nct_id):
    with open(os.path.join(FIXTURES, "ctgov_{}.json".format(nct_id)), encoding="utf-8") as fh:
        return normalize_study(json.load(fh))


def load_paper(pmid):
    with open(os.path.join(FIXTURES, "pubmed_{}.xml".format(pmid)), encoding="utf-8") as fh:
        root = ET.fromstring(fh.read())
    return parse_pubmed_article(root.find(".//PubmedArticle"))


class TestClinicalTrialsAdapter(unittest.TestCase):
    def test_normalizes_core_fields(self):
        trial = load_trial("NCT02506153")
        self.assertEqual(trial.nct_id, "NCT02506153")
        self.assertEqual(trial.enrollment, 1301)
        self.assertEqual(trial.enrollment_type, "ACTUAL")
        self.assertEqual(trial.allocation, "RANDOMIZED")
        self.assertEqual(trial.phases, ["PHASE3"])
        self.assertEqual(trial.arm_count, 2)
        self.assertTrue(trial.primary_outcomes)
        self.assertEqual(trial.primary_outcomes[0].kind, "primary")

    def test_keeps_registry_provenance(self):
        trial = load_trial("NCT02506153")
        self.assertEqual(trial.provenance.source, "clinicaltrials.gov")
        self.assertIn("NCT02506153", trial.provenance.url)

    def test_links_publications_with_their_type(self):
        trial = load_trial("NCT02506153")
        self.assertTrue(any(ref["pmid"] == "36416836" for ref in trial.linked_references))

    def test_nct_id_detection(self):
        self.assertTrue(looks_like_nct_id("NCT02506153"))
        self.assertFalse(looks_like_nct_id("NCT123"))
        self.assertEqual(
            extract_nct_ids("see NCT02506153 and nct02142738, plus NCT02506153 again"),
            ["NCT02506153", "NCT02142738"],
        )


class TestPubMedAdapter(unittest.TestCase):
    def test_reads_article_ids_not_reference_ids(self):
        # The record's reference list also contains ArticleId elements; a
        # document-wide search would pick up a cited paper's DOI instead.
        paper = load_paper("36416836")
        self.assertEqual(paper.pmid, "36416836")
        self.assertEqual(paper.doi, "10.1001/jamaoncol.2022.5486")

    def test_extracts_registry_id_from_databank(self):
        self.assertEqual(load_paper("36416836").registered_trial_ids, ["NCT02506153"])

    def test_keeps_structured_abstract_sections(self):
        paper = load_paper("36416836")
        self.assertIn("RESULTS", paper.abstract_sections)
        self.assertIn("METHODS", load_paper("27718847").abstract_sections)

    def test_author_positions_and_dates(self):
        paper = load_paper("36416836")
        self.assertEqual(paper.authors[0].position, "first")
        self.assertEqual(paper.authors[-1].position, "last")
        self.assertEqual(paper.publication_year, 2023)


class TestMatching(unittest.TestCase):
    def test_declared_identifier_is_decisive(self):
        match = score_match(load_trial("NCT02506153"), load_paper("36416836"))
        self.assertEqual(match.basis, "identifier")
        self.assertEqual(match.score, 1.0)
        self.assertEqual(match.confidence, "high")
        self.assertEqual(match.signals[0].name, "declared_registry_id")

    def test_unrelated_pair_scores_low_and_stays_inferred(self):
        # A melanoma trial against a lung cancer publication.
        match = score_match(load_trial("NCT02506153"), load_paper("27718847"))
        self.assertEqual(match.basis, "inferred")
        self.assertLess(match.score, 0.6)

    def test_name_normalization_tolerates_middle_initials(self):
        self.assertEqual(_normalize_person("Sapna P Patel"), _normalize_person("Sapna Patel"))
        self.assertNotEqual(_normalize_person("Sapna Patel"), _normalize_person("Ravi Patel"))


class TestOutcomeNormalization(unittest.TestCase):
    def test_strips_registry_boilerplate(self):
        self.assertEqual(
            _core_measure_phrase("Progression Free Survival (PFS) Rate at Month 6"),
            "Progression Free Survival",
        )
        self.assertEqual(
            _core_measure_phrase("Percentage of Participants With Overall Survival (OS) at 12 Months"),
            "Overall Survival",
        )

    def test_does_not_over_strip_meaningful_text(self):
        # "Change From Baseline in X" must keep X, or the concept is lost.
        self.assertIn(
            "EORTC",
            _core_measure_phrase("Change From Baseline in EORTC QLQ-C30 Global Health Status"),
        )


class TestComparison(unittest.TestCase):
    def test_reports_enrollment_difference_without_judgement(self):
        trial, paper = load_trial("NCT02506153"), load_paper("36416836")
        row = next(f for f in compare(trial, paper).fields if f.field_name == "Enrollment")
        self.assertEqual(row.status, DIFFERENCE)
        self.assertEqual(row.registered, "1301 (actual)")
        self.assertEqual(row.published, "1303")
        # Section 4: a difference is never described as misconduct.
        for word in ("fraud", "misconduct", "manipulat", "falsif"):
            self.assertNotIn(word, row.note.lower())

    def test_detects_primary_outcome_in_abstract(self):
        trial, paper = load_trial("NCT02142738"), load_paper("27718847")
        rows = [f for f in compare(trial, paper).fields if f.field_name.startswith("Primary outcome")]
        found = [row for row in rows if row.status == MATCH]
        self.assertTrue(found, "expected PFS to be identified in the NEJM abstract")
        quotes = " ".join(e.quote.lower() for e in found[0].evidence if e.source == "pubmed")
        self.assertIn("progression-free survival", quotes)

    def test_unreported_outcome_is_flagged_but_hedged(self):
        trial, paper = load_trial("NCT02506153"), load_paper("36416836")
        rows = [f for f in compare(trial, paper).fields if f.field_name.startswith("Primary outcome")]
        self.assertEqual(rows[0].status, NOT_FOUND)
        self.assertIn("full text", rows[0].note)

    def test_every_row_carries_provenance_or_explains_its_absence(self):
        comparison = compare(load_trial("NCT02506153"), load_paper("36416836"))
        self.assertTrue(comparison.evidence_scope)
        self.assertTrue(all(item["url"] for item in comparison.provenance))
        for row in comparison.fields:
            if row.status in (MATCH, DIFFERENCE):
                self.assertTrue(row.evidence, "{} has no evidence".format(row.field_name))

    def test_serializes_to_json(self):
        payload = compare(load_trial("NCT02506153"), load_paper("36416836")).to_dict()
        json.dumps(payload)  # must not raise
        self.assertIn("counts", payload)


class TestPublicationRole(unittest.TestCase):
    def test_quality_of_life_paper_is_a_secondary_analysis(self):
        trial, paper = load_trial("NCT02506153"), load_paper("36416836")
        match = score_match(trial, paper)
        role, _, reasons = classify(trial, paper, compare(trial, paper, match), match)
        self.assertEqual(role, SECONDARY_ANALYSIS)
        self.assertTrue(reasons)

    def test_unrelated_paper_only_mentions_the_trial(self):
        trial, paper = load_trial("NCT02506153"), load_paper("27718847")
        match = score_match(trial, paper)
        role, rank, _ = classify(trial, paper, compare(trial, paper, match), match)
        self.assertEqual(role, MENTIONS_TRIAL)
        self.assertLess(rank, 0.3)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestReportLayer(unittest.TestCase):
    """The CLI and the HTTP API are both built from backend.report."""

    def _patched_report(self, nct_id, pmid):
        from unittest.mock import patch

        import backend.report as report

        trial, paper = load_trial(nct_id), load_paper(pmid)
        with patch.object(report.clinical_trials, "get_trial", return_value=trial), patch.object(
            report.pubmed, "get_paper_by_pmid", return_value=paper
        ):
            return report.comparison_report(nct_id, pmid)

    def test_comparison_report_is_json_serializable(self):
        payload = self._patched_report("NCT02506153", "36416836")
        json.dumps(payload)  # the HTTP layer serializes this directly
        self.assertEqual(payload["trial"]["nct_id"], "NCT02506153")
        self.assertEqual(payload["match"]["basis"], "identifier")
        self.assertIn("counts", payload["comparison"])
        self.assertTrue(payload["role_label"])

    def test_report_keeps_source_links(self):
        payload = self._patched_report("NCT02506153", "36416836")
        self.assertIn("clinicaltrials.gov", payload["trial"]["url"])
        self.assertTrue(all(item["url"] for item in payload["comparison"]["provenance"]))


class TestRegistryIdAttribution(unittest.TestCase):
    """Which identifiers attribute a paper to a trial, and which merely appear."""

    def test_databank_ids_are_kept_apart_from_abstract_mentions(self):
        paper = load_paper("36416836")
        # This record's databank field carries its own trial.
        self.assertEqual(paper.databank_trial_ids, ["NCT02506153"])
        # The merged list is a superset: it also picks up prose mentions.
        for nct in paper.databank_trial_ids:
            self.assertIn(nct, paper.registered_trial_ids)

    def test_an_abstract_mention_alone_does_not_attribute(self):
        import xml.etree.ElementTree as ET

        from backend.sources.pubmed import parse_pubmed_article

        xml = """<PubmedArticle><MedlineCitation><PMID>1</PMID><Article>
          <ArticleTitle>A comparison</ArticleTitle>
          <Abstract><AbstractText Label="METHODS">We compared our trial
            NCT11111111 against the published NCT22222222.</AbstractText></Abstract>
          <PublicationTypeList><PublicationType>Journal Article</PublicationType></PublicationTypeList>
          </Article>
          <DataBankList><DataBank><DataBankName>ClinicalTrials.gov</DataBankName>
            <AccessionNumberList><AccessionNumber>NCT11111111</AccessionNumber>
            </AccessionNumberList></DataBank></DataBankList>
          </MedlineCitation><PubmedData><ArticleIdList>
          <ArticleId IdType="pubmed">1</ArticleId></ArticleIdList></PubmedData></PubmedArticle>"""
        paper = parse_pubmed_article(ET.fromstring(xml))
        # Both identifiers are stated by the paper...
        self.assertEqual(paper.registered_trial_ids, ["NCT11111111", "NCT22222222"])
        # ...but only the first is the trial this paper reports.
        self.assertEqual(paper.databank_trial_ids, ["NCT11111111"])


class TestBulkLinkage(unittest.TestCase):
    """Batched cohort linkage must agree with the per-trial path."""

    def test_bulk_linkage_attributes_only_via_the_databank_field(self):
        from unittest.mock import patch

        import backend.publication_bias.linkage as linkage
        from backend.models.core import Paper

        trial_a = load_trial("NCT02506153")
        trial_b = load_trial("NCT02142738")
        reporting = Paper(title="Reports A", pmid="100",
                          registered_trial_ids=["NCT02506153"],
                          databank_trial_ids=["NCT02506153"])
        # Names trial B in its abstract but reports neither.
        mentioning = Paper(title="Mentions B", pmid="101",
                           registered_trial_ids=["NCT02142738"],
                           databank_trial_ids=[])

        with patch.object(linkage.pubmed, "search_by_nct_ids", return_value=["100", "101"]), \
             patch.object(linkage.pubmed, "get_papers_by_pmid", return_value=[reporting, mentioning]):
            links = linkage.find_links_bulk([trial_a, trial_b])

        self.assertEqual([l.pmid for l in links["NCT02506153"]], ["100"])
        # Trial B keeps only its registry references; the prose mention is not a link.
        self.assertNotIn("101", [l.pmid for l in links["NCT02142738"]])

    def test_registry_references_survive_a_failed_search(self):
        from unittest.mock import patch

        import backend.publication_bias.linkage as linkage
        from backend.sources.http import SourceError

        trial = load_trial("NCT02506153")
        paper = load_paper("36416836")
        with patch.object(linkage.pubmed, "search_by_nct_ids", side_effect=SourceError("down")), \
             patch.object(linkage.pubmed, "get_papers_by_pmid", return_value=[paper]):
            links = linkage.find_links_bulk([trial])
        # The registry's own reference list still links the publication.
        self.assertEqual([l.pmid for l in links["NCT02506153"]], ["36416836"])
        self.assertEqual(links["NCT02506153"][0].match_method, linkage.REGISTRY_REFERENCE)
