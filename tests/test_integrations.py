"""Offline tests for Europe PMC, the LLM layer, Elasticsearch and the cascade.

Nothing here touches a network or spends a token: every external call is
replaced with a stub, so the suite tests our logic -- validation, budgeting,
attribution, thresholds -- rather than a vendor's uptime.
"""

import json
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.models.core import Author, Paper, Trial
from backend.models.effects import EffectEstimate, HAZARD_RATIO
from backend.sources import europepmc


class EuropePMCTests(unittest.TestCase):
    def test_availability_reads_full_text_flags(self):
        payload = {"resultList": {"result": [
            {"pmid": "1", "pmcid": "PMC1", "isOpenAccess": "Y", "fullTextIdList": {"fullTextId": ["PMC1"]}},
            {"pmid": "2", "pmcid": None, "isOpenAccess": "N"},
        ]}}
        with patch.object(europepmc, "get_json", return_value=payload):
            av = europepmc.availability(["1", "2"])
        self.assertTrue(av["1"]["full_text"])
        self.assertEqual(av["1"]["pmcid"], "PMC1")
        self.assertFalse(av["2"]["full_text"])

    def test_full_text_requests_xml_and_splits_sections(self):
        xml = ("<article><body><sec><title>Results</title><p>Median OS was 26.3 months "
               "(hazard ratio, 0.62; 95% CI, 0.48 to 0.81).</p></sec>"
               "<sec><title>Discussion</title><p>We discuss things at length here.</p></sec></body></article>")
        calls = {}
        def fake_get_text(url, params=None, accept=None):
            calls["accept"] = accept
            return xml
        with patch.object(europepmc, "get_text", side_effect=fake_get_text):
            art = europepmc.full_text("PMC1")
        self.assertEqual(calls["accept"], "application/xml")
        self.assertEqual([s["title"] for s in art["sections"]], ["Results", "Discussion"])

    def test_hazard_ratio_sentences_keep_only_cued_numeric_sentences(self):
        art = {"sections": [
            {"title": "Results", "text": "Median OS was 26.3 months (hazard ratio, 0.62; 95% CI, 0.48 to 0.81). "
                                          "Patients were enrolled between 2014 and 2016 at 90 sites."},
            {"title": "Discussion", "text": "The hazard ratio is discussed but no number appears here."},
        ], "text": ""}
        sentences = europepmc.hazard_ratio_sentences(art)
        self.assertEqual(len(sentences), 1)
        self.assertIn("0.62", sentences[0])


    def test_hazard_ratio_sentences_accept_house_styles(self):
        """Phrasings that are ordinary in oncology journals but not in one regex.

        Each of these was silently dropped, so a paper that reported its hazard
        ratio only this way reached the model with nothing to read.
        """
        cases = {
            "lancet middle dot": "Overall survival favoured the combination "
                                 "(HR 0\u00b765, 95% CI 0\u00b750-0\u00b785; p=0\u00b70002).",
            "adjusted ratio": "The adjusted aHR for progression was 0.65 (95% CI, 0.50-0.85).",
            "plural": "HRs for the two subgroups were 0.65 and 0.72 respectively.",
            "terse caption": "PFS by treatment arm. HR 0.65 (0.50-0.85).",
        }
        for name, text in cases.items():
            with self.subTest(name):
                art = {"sections": [{"title": "Results", "text": text}], "text": text}
                self.assertTrue(europepmc.hazard_ratio_sentences(art))

    def test_hazard_ratio_sentences_reject_shared_abbreviations(self):
        """"HR" also abbreviates hours and health-related quality of life.

        Both appear beside decimals in the same papers, so accepting them costs
        model tokens on sentences that cannot contain an effect estimate.
        """
        cases = {
            "quality of life": "HR-QoL scores improved by 3.5 points over baseline in both arms.",
            "hours": "Mean AUC over the interval 0-24 hr was 3.5 mg/L.",
        }
        for name, text in cases.items():
            with self.subTest(name):
                art = {"sections": [{"title": "Results", "text": text}], "text": text}
                self.assertEqual(europepmc.hazard_ratio_sentences(art), [])

    def test_full_text_reads_figure_captions(self):
        """A Kaplan-Meier caption often carries the headline ratio.

        Captions sit in <fig><caption><p>, which a non-recursive search of a
        section's own paragraphs steps straight over.
        """
        xml = ("<article><body><sec><title>Results</title>"
               "<p>Median PFS was 10.4 months versus 6.8 months.</p>"
               "<fig><caption><p>Figure 2. Progression-free survival. "
               "HR 0.65 (95% CI, 0.50-0.85).</p></caption></fig>"
               "</sec></body></article>")
        with patch.object(europepmc, "get_text", return_value=xml):
            art = europepmc.full_text("PMC1")
        self.assertIn("figure", [s["title"] for s in art["sections"]])
        self.assertTrue(any("0.65" in s for s in europepmc.hazard_ratio_sentences(art)))

    def test_full_text_separates_table_cells(self):
        """Table cells need a separator or the cue words stop being words.

        Concatenating itertext() welds a header to the row beneath it --
        "EndpointHazard ratio95% CI" -- and the word boundaries the cue pattern
        depends on disappear, so an outcome table stops qualifying as a place a
        hazard ratio might be.
        """
        xml = ("<article><body><table-wrap><label>Table 2</label>"
               "<caption><p>Efficacy outcomes</p></caption><table>"
               "<tr><th>Endpoint</th><th>Hazard ratio</th><th>95% CI</th></tr>"
               "<tr><td>PFS</td><td>0.65</td><td>0.50-0.85</td></tr>"
               "</table></table-wrap></body></article>")
        with patch.object(europepmc, "get_text", return_value=xml):
            art = europepmc.full_text("PMC1")
        table = next(s for s in art["sections"] if s["title"] == "table")
        self.assertIn("Hazard ratio", table["text"])
        self.assertNotIn("EndpointHazard", table["text"])
        self.assertTrue(any("0.65" in s for s in europepmc.hazard_ratio_sentences(art)))

    def test_full_text_caps_table_length(self):
        """A long table is mostly per-site counts; the estimates are near the top."""
        rows = "".join("<tr><td>site {}</td><td>0.9{}</td></tr>".format(i, i % 10)
                       for i in range(400))
        xml = ("<article><body><table-wrap><table>"
               "<tr><th>Hazard ratio</th></tr>" + rows +
               "</table></table-wrap></body></article>")
        with patch.object(europepmc, "get_text", return_value=xml):
            art = europepmc.full_text("PMC1")
        table = next(s for s in art["sections"] if s["title"] == "table")
        self.assertLessEqual(len(table["text"]), europepmc._MAX_TABLE_CHARS)


class LLMClientTests(unittest.TestCase):
    def setUp(self):
        from backend.llm import client
        self.client = client
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self._cache = client.CACHE_DIR
        self._ledger = client.LEDGER
        client.CACHE_DIR = self.tmp
        client.LEDGER = os.path.join(self.tmp, "ledger.jsonl")
        client._calls_this_process = 0

    def tearDown(self):
        self.client.CACHE_DIR = self._cache
        self.client.LEDGER = self._ledger

    def _fake_post(self, content, prompt=100, completion=20):
        class R:
            ok = True; status_code = 200; text = ""
            def json(self_inner):
                return {"choices": [{"message": {"content": json.dumps(content)}}],
                        "usage": {"prompt_tokens": prompt, "completion_tokens": completion}}
        return R()

    def test_caches_identical_calls_and_records_the_ledger_once(self):
        schema = {"type": "object", "properties": {"x": {"type": "number"}}, "required": ["x"], "additionalProperties": False}
        with patch.object(self.client.config, "openai_key", return_value="k"), \
             patch.object(self.client.requests, "post", return_value=self._fake_post({"x": 1})) as post:
            first = self.client.chat_json([{"role": "user", "content": "hi"}], schema, "s", purpose="t")
            second = self.client.chat_json([{"role": "user", "content": "hi"}], schema, "s", purpose="t")
        self.assertFalse(first["cached"]); self.assertTrue(second["cached"])
        self.assertEqual(post.call_count, 1)
        self.assertEqual(len(self.client.ledger()), 1)
        self.assertEqual(self.client.ledger()[0]["prompt_tokens"], 100)

    def test_refuses_past_the_budget_cap(self):
        schema = {"type": "object", "properties": {}, "additionalProperties": False}
        self.client._calls_this_process = self.client.MAX_CALLS
        with patch.object(self.client.config, "openai_key", return_value="k"):
            with self.assertRaises(self.client.BudgetExceeded):
                self.client.chat_json([{"role": "user", "content": "new"}], schema, "s")

    def test_missing_key_is_an_explicit_error(self):
        schema = {"type": "object", "properties": {}, "additionalProperties": False}
        with patch.object(self.client.config, "openai_key", return_value=""):
            with self.assertRaises(self.client.LLMUnavailable):
                self.client.chat_json([{"role": "user", "content": "x"}], schema, "s")


class ExtractionValidationTests(unittest.TestCase):
    def _run(self, small, large=None):
        from backend.llm import extraction
        answers = iter([small] + ([large] if large is not None else []))
        def fake(messages, schema, name, model, purpose="", temperature=0.0):
            return {"data": next(answers), "usage": {"prompt_tokens": 50, "completion_tokens": 10},
                    "model": model, "cached": False}
        sentences = ["Median PFS was 10.3 vs 6.0 months (hazard ratio, 0.50; 95% CI, 0.37 to 0.68)."]
        with patch.object(extraction.client, "chat_json", side_effect=fake):
            return extraction.extract_hazard_ratios(sentences)

    def test_accepts_a_value_grounded_in_the_text(self):
        r = self._run({"estimates": [{"endpoint": "pfs", "hazard_ratio": 0.5, "ci_lower": 0.37, "ci_upper": 0.68,
                                      "comparison": "a vs b", "evidence": "hazard ratio, 0.50; 95% CI, 0.37 to 0.68"}]})
        self.assertEqual(len(r["estimates"]), 1); self.assertEqual(r["tier"], "small")

    def test_rejects_a_value_whose_evidence_is_not_in_the_text_then_escalates(self):
        bad = {"estimates": [{"endpoint": "os", "hazard_ratio": 0.7, "ci_lower": 0.5, "ci_upper": 0.9,
                              "comparison": "x", "evidence": "this sentence was invented"}]}
        good = {"estimates": [{"endpoint": "pfs", "hazard_ratio": 0.5, "ci_lower": 0.37, "ci_upper": 0.68,
                               "comparison": "a vs b", "evidence": "hazard ratio, 0.50; 95% CI, 0.37 to 0.68"}]}
        r = self._run(bad, good)
        self.assertEqual(r["tier"], "large"); self.assertEqual(r["estimates"][0]["hazard_ratio"], 0.5)

    def test_rejects_an_interval_that_does_not_bracket_the_point(self):
        r = self._run({"estimates": [{"endpoint": "pfs", "hazard_ratio": 0.5, "ci_lower": 0.6, "ci_upper": 0.9,
                                      "comparison": "x", "evidence": "hazard ratio, 0.50"}]},
                      {"estimates": []})
        self.assertEqual(r["estimates"], [])

    def test_empty_answer_from_small_tier_is_final(self):
        r = self._run({"estimates": []})
        self.assertEqual(r["tier"], "small"); self.assertEqual(r["estimates"], [])


def _trial(nct="NCT1", **kw):
    base = dict(nct_id=nct, title="t", interventions=[{"name": "drugX"}], conditions=["lung cancer"],
                investigators=["Ann Lee"], start_date="2015-01-01")
    base.update(kw)
    return Trial(**base)


class FuzzyCascadeTests(unittest.TestCase):
    def _cascade(self, papers, verdict=None, adjudicate=True):
        from backend.matching import trial_paper_matcher as m
        hits = [{"pmid": p.pmid, "_score": 10.0} for p in papers]
        # Patch the function, not the module: the cascade imports the package
        # attribute, which a sys.modules swap does not touch.
        patches = [patch("backend.search.elastic.candidates_for_trial", return_value=hits),
                   patch("backend.sources.pubmed.get_papers_by_pmid", return_value=papers)]
        if verdict is not None:
            patches.append(patch("backend.llm.matching.adjudicate", return_value=verdict))
        for p in patches: p.start()
        try:
            return m.find_publications_fuzzy(_trial(), adjudicate=adjudicate)
        finally:
            for p in patches: p.stop()

    def test_clear_scores_never_reach_the_model(self):
        unrelated = Paper(title="Something about kidneys", pmid="9", abstract="renal function",
                          authors=[Author(name="Zed Q")], publication_year=2019)
        with patch("backend.llm.matching.adjudicate") as adj:
            r = self._cascade([unrelated])
        self.assertEqual(r["candidates"][0]["decision"], "rejected")
        adj.assert_not_called()

    def test_middle_band_goes_to_the_model_and_is_flagged(self):
        plausible = Paper(title="drugX in lung cancer", pmid="5", abstract="drugX lung cancer patients randomized",
                          authors=[Author(name="Ann Lee")], publication_year=2018)
        r = self._cascade([plausible], verdict={"verdict": "reports_this_trial", "confidence": 0.9,
                                                "reason": "same arms", "model": "m", "tokens": 80, "cached": False})
        c = r["candidates"][0]
        self.assertEqual(c["decision"], "accepted_by_adjudication")
        self.assertEqual(c["llm"]["verdict"], "reports_this_trial")
        self.assertEqual(r["llm_tokens"], 80)

    def test_a_high_metadata_score_alone_never_accepts(self):
        # Same investigator, same drug, different trial: scores high, is not a match.
        lookalike = Paper(title="drugX with carboplatin in lung cancer", pmid="6",
                          abstract="drugX lung cancer randomized carboplatin patients enrolled 2015",
                          authors=[Author(name="Ann Lee")], publication_year=2018)
        r = self._cascade([lookalike], verdict={"verdict": "different_trial", "confidence": 0.9,
                                                "reason": "different arms", "model": "m", "tokens": 5, "cached": False})
        c = r["candidates"][0]
        self.assertGreaterEqual(c["match"]["score"], 0.45)
        self.assertNotEqual(c["decision"], "accepted")
        self.assertEqual(c["decision"], "rejected_by_adjudication")

    def test_unclear_verdict_leaves_the_pair_for_review(self):
        plausible = Paper(title="drugX in lung cancer", pmid="5", abstract="drugX lung cancer patients randomized",
                          authors=[Author(name="Ann Lee")], publication_year=2018)
        r = self._cascade([plausible], verdict={"verdict": "unclear", "confidence": 0.4,
                                                "reason": "?", "model": "m", "tokens": 1, "cached": False})
        self.assertEqual(r["candidates"][0]["decision"], "review")

    def test_search_outage_is_reported_not_disguised_as_no_candidates(self):
        from backend.matching import trial_paper_matcher as m
        with patch("backend.search.elastic.candidates_for_trial", side_effect=RuntimeError("down")):
            r = m.find_publications_fuzzy(_trial())
        self.assertEqual(r["retrieval"], "unavailable")


class RecoveryTests(unittest.TestCase):
    def test_recovered_estimates_are_labelled_publication_and_move_the_trial(self):
        from backend.publication_bias import fulltext
        from backend.publication_bias.cohort import Cohort
        from backend.publication_bias.linkage import CATEGORY_A, CATEGORY_C, CohortTrial, PublicationLink
        item = CohortTrial(trial=_trial(), effects=[], links=[PublicationLink(nct_id="NCT1", pmid="7")])
        cohort = Cohort(condition="c", endpoint_class="pfs", trials=[item])
        self.assertEqual(item.category("pfs"), CATEGORY_C)
        with patch.object(fulltext.europepmc, "availability", return_value={"7": {"full_text": True, "pmcid": "PMC7"}}), \
             patch.object(fulltext.europepmc, "full_text", return_value={"pmcid": "PMC7", "sections": [], "text": "x" * 4000}), \
             patch.object(fulltext.europepmc, "hazard_ratio_sentences", return_value=["hazard ratio 0.5 (0.4-0.6)"]), \
             patch.object(fulltext.extraction, "extract_hazard_ratios", return_value={
                 "estimates": [{"endpoint": "pfs", "hazard_ratio": 0.5, "ci_lower": 0.4, "ci_upper": 0.6, "comparison": "a"}],
                 "model": "m", "tokens": 300, "tier": "small", "rejected": 0, "cached": False}):
            report = fulltext.recover(cohort)
        self.assertEqual(report["trials_recovered"], 1)
        self.assertEqual(item.category("pfs"), CATEGORY_A)
        self.assertEqual(item.best_effect("pfs").source, "publication")
        self.assertEqual(report["tokens_measured"], 300)
        self.assertEqual(report["tokens_spent_total"], 300)
        self.assertGreater(report["token_reduction"], 0.5)


class CategoryBreakdownTests(unittest.TestCase):
    def test_no_result_reasons_are_distinguished(self):
        from backend.publication_bias.linkage import (
            REASON_NO_ANALYSIS, REASON_NO_VARIANCE, REASON_OTHER_ENDPOINT, REASON_OTHER_MEASURE, CohortTrial)
        def item(effects): return CohortTrial(trial=_trial(), effects=effects, links=[])
        self.assertEqual(item([]).missing_reason("pfs"), REASON_NO_ANALYSIS)
        self.assertEqual(item([EffectEstimate(nct_id="N", measure="Odds Ratio", value=2, ci_lower=1, ci_upper=3)]).missing_reason("pfs"), REASON_OTHER_MEASURE)
        self.assertEqual(item([EffectEstimate(nct_id="N", measure=HAZARD_RATIO, value=0.6, ci_lower=0.5, ci_upper=0.7, endpoint_class="os")]).missing_reason("pfs"), REASON_OTHER_ENDPOINT)
        self.assertEqual(item([EffectEstimate(nct_id="N", measure=HAZARD_RATIO, value=0.6, endpoint_class="pfs")]).missing_reason("pfs"), REASON_NO_VARIANCE)

    def test_a_trial_with_a_publication_but_no_estimate_is_C_not_no_publication(self):
        from backend.publication_bias.linkage import CATEGORY_C, CATEGORY_LABELS, CohortTrial, PublicationLink
        item = CohortTrial(trial=_trial(), effects=[], links=[PublicationLink(nct_id="NCT1", pmid="1")])
        self.assertEqual(item.category("pfs"), CATEGORY_C)
        self.assertTrue(item.has_publication)
        self.assertNotIn("publication", CATEGORY_LABELS[CATEGORY_C].lower())


class ElasticDocTests(unittest.TestCase):
    def test_trial_document_carries_matching_fields(self):
        from backend.search import elastic
        doc = elastic._trial_doc(_trial(official_title="A Phase 3 Study"), linked_pmids=["1"])
        self.assertEqual(doc["interventions"], ["drugX"])
        self.assertEqual(doc["investigators"], ["Ann Lee"])
        self.assertEqual(doc["start_year"], 2015)
        self.assertEqual(doc["linked_pmids"], ["1"])

    def test_unconfigured_search_raises_cleanly(self):
        from backend.search import elastic
        elastic._client = None
        with patch.object(elastic.config, "elastic", return_value={"cloud_id": "", "api_key": "", "url": ""}):
            with self.assertRaises(elastic.SearchUnavailable):
                elastic.client()
        elastic._client = None


if __name__ == "__main__":
    unittest.main(verbosity=2)
