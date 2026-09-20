"""Offline tests for the funnel plot, cost ledger, search facets and overview.

Same rule as the rest of the suite: nothing here touches a network or spends a
token. The statistics are checked against a closed-form regression and against
synthetic data whose asymmetry is built in, so a wrong sign or a wrong degree
of freedom fails a test rather than producing a plausible number.
"""

import json
import math
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.models.core import Trial
from backend.models.effects import HAZARD_RATIO, EffectEstimate
from backend.publication_bias import funnel
from backend.publication_bias.cohort import Cohort, describe, save_cohort
from backend.publication_bias.linkage import CATEGORY_A, CATEGORY_B, CohortTrial, PublicationLink

_Z = 1.959963984540054


def _effect(nct, log_hr, se, endpoint="os"):
    value = math.exp(log_hr)
    return EffectEstimate(nct_id=nct, measure=HAZARD_RATIO, value=value,
                          ci_lower=math.exp(log_hr - _Z * se), ci_upper=math.exp(log_hr + _Z * se),
                          outcome_type="PRIMARY", endpoint_class=endpoint)


def _cohort(rows):
    """rows: (log_hr, se, published)."""
    trials = []
    for i, (log_hr, se, published) in enumerate(rows):
        trial = Trial(nct_id="NCT%04d" % i, title="t%d" % i, lead_sponsor_class="INDUSTRY",
                      phases=["PHASE3"], enrollment=300, start_date="2015-01-01")
        links = [PublicationLink(nct_id=trial.nct_id, pmid="9%03d" % i, openalex_id="W%d" % i)] if published else []
        trials.append(CohortTrial(trial=trial, effects=[_effect(trial.nct_id, log_hr, se)], links=links))
    return Cohort(condition="synthetic", endpoint_class="os", trials=trials, phases=["3"])


class EggerTests(unittest.TestCase):
    def test_matches_the_closed_form_regression(self):
        rng = np.random.default_rng(3)
        rows = [(float(rng.normal(-0.3, 0.2)), float(rng.uniform(0.08, 0.4)), True) for _ in range(25)]
        cohort = _cohort(rows)
        result = funnel.egger_test([t.effects[0] for t in cohort.trials], "x")
        snd = np.array([r[0] / r[1] for r in rows]); prec = np.array([1 / r[1] for r in rows])
        design = np.column_stack([np.ones_like(prec), prec])
        beta, *_ = np.linalg.lstsq(design, snd, rcond=None)
        resid = snd - design @ beta
        cov = (resid @ resid) / (len(rows) - 2) * np.linalg.inv(design.T @ design)
        self.assertAlmostEqual(result["intercept"], beta[0], places=6)
        self.assertAlmostEqual(result["intercept_se"], math.sqrt(cov[0, 0]), places=6)
        self.assertTrue(result["ran"] and result["reliable"])

    def test_symmetric_funnel_is_not_flagged(self):
        # Effects independent of precision: the intercept should be near zero.
        rng = np.random.default_rng(11)
        rows = []
        for _ in range(40):
            se = float(rng.uniform(0.05, 0.5))
            rows.append((float(rng.normal(math.log(0.75), se)), se, True))
        result = funnel.egger_test([t.effects[0] for t in _cohort(rows).trials], "sym")
        self.assertGreater(result["p_value"], 0.05)
        self.assertIn("No significant asymmetry", result["note"])

    def test_small_trials_with_strong_effects_are_flagged_with_a_negative_intercept(self):
        rows = []
        for i in range(12):                      # large, precise trials near the truth
            rows.append((math.log(0.85) + 0.01 * (i % 3 - 1), 0.06, True))
        for i in range(12):                      # small, imprecise trials that all "worked"
            rows.append((math.log(0.45) + 0.02 * (i % 4 - 2), 0.35, True))
        result = funnel.egger_test([t.effects[0] for t in _cohort(rows).trials], "asym")
        self.assertLess(result["intercept"], 0)
        self.assertLess(result["p_value"], 0.05)
        self.assertIn("stronger effects", result["note"])

    def test_too_few_trials_reports_rather_than_decides(self):
        few = [_effect("A", -0.2, 0.1), _effect("B", -0.3, 0.2)]
        self.assertFalse(funnel.egger_test(few, "few")["ran"])
        rng = np.random.default_rng(5)
        six = [_effect("N%d" % i, float(rng.normal(-0.25, 0.15)), float(rng.uniform(0.08, 0.4))) for i in range(6)]
        result = funnel.egger_test(six, "six")
        self.assertTrue(result["ran"])
        self.assertFalse(result["reliable"])
        self.assertIn("unreliable", result["note"])
        same = [_effect("S%d" % i, -0.2 - 0.1 * i, 0.2) for i in range(5)]
        self.assertFalse(funnel.egger_test(same, "same")["ran"])

    def test_p_values_are_floored_not_printed_as_zero(self):
        self.assertEqual(funnel.format_p(1e-9), "p < 0.001")
        self.assertEqual(funnel.format_p(0.0042), "p = 0.004")
        self.assertEqual(funnel.format_p(0.31), "p = 0.31")
        self.assertEqual(funnel.format_p(None), "p unavailable")


class FunnelTests(unittest.TestCase):
    def test_points_carry_category_and_bounds_bracket_the_pooled_centre(self):
        rows = [(-0.3, 0.1, True), (-0.25, 0.12, True), (-0.1, 0.3, False), (0.05, 0.35, False), (-0.35, 0.08, True)]
        result = funnel.funnel(_cohort(rows))
        self.assertEqual(result["k"], 5)
        self.assertEqual(sum(1 for p in result["points"] if p["category"] == CATEGORY_B), 2)
        self.assertEqual(sum(1 for p in result["points"] if p["category"] == CATEGORY_A), 3)
        for bound in result["bounds"]:
            self.assertLess(bound["lower"], result["pooled_hazard_ratio"])
            self.assertGreater(bound["upper"], result["pooled_hazard_ratio"])
        # Bounds widen as the standard error grows.
        widths = [b["upper"] - b["lower"] for b in result["bounds"]]
        self.assertEqual(widths, sorted(widths))

    def test_placement_counts_registry_only_trials_in_the_missing_corner(self):
        rows = [(-0.3, 0.1, True), (-0.32, 0.12, True), (-0.28, 0.09, True),
                (0.1, 0.4, False), (0.2, 0.5, False)]  # weak and imprecise, unpublished
        result = funnel.funnel(_cohort(rows))
        placement = result["placement"]
        self.assertEqual(placement["registry_only"], 2)
        self.assertEqual(placement["less_precise_than_published_median"], 2)
        self.assertEqual(placement["weaker_than_pooled"], 2)

    def test_trials_without_a_usable_estimate_are_absent_not_at_the_null(self):
        cohort = _cohort([(-0.3, 0.1, True), (-0.2, 0.1, True)])
        cohort.trials.append(CohortTrial(trial=Trial(nct_id="NCTX", title="no result"), effects=[], links=[]))
        result = funnel.funnel(cohort)
        self.assertEqual(result["k"], 2)
        self.assertNotIn("NCTX", [p["nct_id"] for p in result["points"]])

    def test_empty_cohort_says_so(self):
        self.assertEqual(funnel.funnel(Cohort(condition="c", endpoint_class="os"))["k"], 0)


class LedgerSummaryTests(unittest.TestCase):
    def setUp(self):
        from backend.llm import client
        self.client = client
        self.tmp = tempfile.mkdtemp()
        self._cache, self._ledger = client.CACHE_DIR, client.LEDGER
        client.CACHE_DIR = self.tmp
        client.LEDGER = os.path.join(self.tmp, "ledger.jsonl")
        client._calls_this_process = 0
        client._cache_hits = 0
        client._tokens_avoided_by_cache = 0

    def tearDown(self):
        self.client.CACHE_DIR, self.client.LEDGER = self._cache, self._ledger
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_costs_are_priced_from_measured_tokens(self):
        with open(self.client.LEDGER, "w") as handle:
            handle.write(json.dumps({"model": "gpt-4.1-nano", "purpose": "recover:NCT1", "prompt_tokens": 1_000_000, "completion_tokens": 0}) + "\n")
            handle.write(json.dumps({"model": "gpt-4.1-nano", "purpose": "adjudicate:NCT1:1", "prompt_tokens": 0, "completion_tokens": 1_000_000}) + "\n")
        s = self.client.summary()
        self.assertEqual(s["calls"], 2)
        self.assertAlmostEqual(s["cost_usd"], 0.10 + 0.40, places=4)
        self.assertAlmostEqual(s["by_purpose"]["recover"]["cost_usd"], 0.10, places=4)
        # The same tokens at the larger tier cost more: that is the saving from the cascade.
        self.assertGreater(s["cost_usd_if_all_large_tier"], s["cost_usd"])

    def test_cache_hits_are_tallied_with_the_tokens_they_avoided(self):
        schema = {"type": "object", "properties": {"x": {"type": "number"}}, "required": ["x"], "additionalProperties": False}

        class R:
            ok = True; status_code = 200; text = ""
            def json(self_inner):
                return {"choices": [{"message": {"content": json.dumps({"x": 1})}}],
                        "usage": {"prompt_tokens": 120, "completion_tokens": 30}}
        with patch.object(self.client.config, "openai_key", return_value="k"), \
             patch.object(self.client.requests, "post", return_value=R()) as post:
            self.client.chat_json([{"role": "user", "content": "hi"}], schema, "s", purpose="t")
            self.client.chat_json([{"role": "user", "content": "hi"}], schema, "s", purpose="t")
            self.client.chat_json([{"role": "user", "content": "hi"}], schema, "s", purpose="t")
        self.assertEqual(post.call_count, 1)
        body = post.call_args.kwargs["json"]
        self.assertEqual(body["max_tokens"], self.client.MAX_COMPLETION_TOKENS)
        s = self.client.summary()
        self.assertEqual(s["cache"]["hits_this_process"], 2)
        self.assertEqual(s["cache"]["tokens_avoided_this_process"], 300)
        self.assertEqual(s["calls"], 1)
        self.assertIsNotNone(self.client.ledger()[0]["cost_usd"])

    def test_unknown_model_gives_no_price_rather_than_a_wrong_one(self):
        self.assertIsNone(self.client.cost_usd(10, 10, "some-future-model"))


class FacetTests(unittest.TestCase):
    def test_trial_document_carries_gap_facets(self):
        from backend.search import elastic
        trial = Trial(nct_id="NCT1", title="t", start_date="2015-03-01")
        doc = elastic._trial_doc(trial, linked_pmids=[], posted_hazard_ratio=True, cohort="lung")
        self.assertFalse(doc["has_publication"])
        self.assertTrue(doc["posted_hazard_ratio"])
        self.assertEqual(doc["kind"], "trial")
        self.assertEqual(doc["cohort"], "lung")
        self.assertTrue(elastic._trial_doc(trial, linked_pmids=["1"])["has_publication"])

    def test_aggregation_buckets_flatten_to_value_count_pairs(self):
        from backend.search import elastic
        response = {"aggregations": {
            "has_publication": {"buckets": [{"key": 1, "key_as_string": "true", "doc_count": 7}, {"key": 0, "key_as_string": "false", "doc_count": 3}]},
            "start_years": {"buckets": [{"key": 2010.0, "doc_count": 4}, {"key": 2015.0, "doc_count": 6}]},
            "empty": {"buckets": []},
        }}
        facets = elastic._facets(response)
        self.assertEqual(facets["has_publication"], [{"value": "true", "count": 7}, {"value": "false", "count": 3}])
        self.assertEqual(facets["start_years"][0], {"value": 2010, "count": 4})
        self.assertNotIn("empty", facets)

    def test_search_applies_kind_and_boolean_filters(self):
        from backend.search import elastic
        captured = {}

        class FakeES:
            def search(self_inner, **kwargs):
                captured.update(kwargs)
                return {"hits": {"hits": [], "total": {"value": 0}}, "aggregations": {}}
        with patch.object(elastic, "client", return_value=FakeES()):
            out = elastic.search_with_facets("pembrolizumab", kind="trial", filters={"has_publication": False, "phases": "PHASE3"})
        filters = captured["query"]["bool"]["filter"]
        self.assertIn({"term": {"kind": "trial"}}, filters)
        self.assertIn({"term": {"has_publication": False}}, filters)
        self.assertIn({"term": {"phases": "PHASE3"}}, filters)
        self.assertIn("aggs", captured)
        self.assertEqual(out["total"], 0)


class ProvenanceAndOverviewTests(unittest.TestCase):
    def test_describe_counts_the_sources_a_cohort_drew_on(self):
        cohort = _cohort([(-0.3, 0.1, True), (-0.2, 0.2, True), (0.0, 0.3, False)])
        shape = describe(cohort)["sources"]
        self.assertEqual(shape["registry_trials"], 3)
        self.assertEqual(shape["publications_linked"], 2)
        self.assertEqual(shape["openalex_resolved"], 2)
        self.assertEqual(shape["retracted_publications"], 0)

    def test_overview_summarises_every_saved_cohort_and_caches_by_mtime(self):
        from backend.publication_bias import overview as ov
        tmp = tempfile.mkdtemp()
        try:
            rows = [(-0.4, 0.1, True), (-0.35, 0.1, True), (-0.3, 0.1, True), (-0.05, 0.3, False)]
            save_cohort(_cohort(rows), os.path.join(tmp, "synthetic-os.json"))
            with patch.object(ov, "COHORT_DIR", tmp), patch.dict(ov._CACHE, {}, clear=True):
                first = ov.overview()
                self.assertEqual(len(first["cohorts"]), 1)
                row = first["cohorts"][0]
                self.assertEqual(row["trials"], 4)
                self.assertEqual(row["priors"]["trials_added"], 1)
                self.assertGreater(row["priors"]["shift_log_hr"], 0)   # the null-ish trial pulls toward 1
                self.assertEqual(first["pattern"]["prior_moved_toward_null_in"], 1)
                with patch.object(ov, "summarize_cohort", side_effect=AssertionError("should be cached")):
                    second = ov.overview()
                self.assertEqual(second["cohorts"][0]["file"], "synthetic-os.json")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class FirstRunTests(unittest.TestCase):
    """What someone gets on a machine that is not this one."""

    def test_the_server_starts_without_the_optional_search_package(self):
        # Elasticsearch powers one tab. Before this was guarded, not having the
        # package meant an ImportError on launch and no application at all.
        import subprocess
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        script = (
            "import sys\n"
            "class Block:\n"
            "    def find_module(self, name, path=None):\n"
            "        return self if name.split('.')[0] == 'elasticsearch' else None\n"
            "    def load_module(self, name):\n"
            "        raise ImportError(name)\n"
            "sys.meta_path.insert(0, Block())\n"
            "import main\n"
            "print('ok')\n"
        )
        result = subprocess.run([sys.executable, "-c", script], cwd=repo,
                                capture_output=True, text=True, timeout=120)
        self.assertIn("ok", result.stdout, result.stderr[-600:])

    def test_readiness_reports_what_is_missing_without_printing_a_secret(self):
        import main
        secrets = {"OPENAI_API_KEY": "sk-test-SHOULD-NEVER-APPEAR",
                   "ELASTIC_API_KEY": "elastic-SHOULD-NEVER-APPEAR",
                   "NCBI_API_KEY": "ncbi-SHOULD-NEVER-APPEAR"}
        saved = {k: os.environ.get(k) for k in secrets}
        os.environ.update(secrets)
        try:
            text = "\n".join(main.readiness())
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
        for value in secrets.values():
            self.assertNotIn(value, text, "readiness leaked a key value")
        self.assertIn("python", text)
        self.assertIn("saved cohorts", text)
        # It must say which features are off, not merely that something is unset.
        self.assertIn("working", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
