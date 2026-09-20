"""Offline tests for the bias-aware design pipeline.

The statistics are checked against closed-form values and against synthetic
data with a known answer, so a regression in the maths shows up as a failure
rather than as a plausible-looking number.
"""

import math
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.models.core import Trial
from backend.models.effects import HAZARD_RATIO, EffectEstimate
from backend.publication_bias import backtest, priors, publication_model, sensitivity
from backend.publication_bias.cohort import Cohort
from backend.publication_bias.linkage import (
    CATEGORY_A,
    CATEGORY_B,
    CATEGORY_C,
    CohortTrial,
    PublicationLink,
    sponsor_type,
)
from backend.publication_bias.power import (
    participants_for_events,
    power_at_events,
    required_events,
)
from backend.sources.clinical_trials import classify_endpoint, extract_effect_estimates


def hr(value, lower, upper, nct="NCT1", kind="PRIMARY", endpoint="os"):
    return EffectEstimate(
        nct_id=nct, measure=HAZARD_RATIO, value=value, ci_lower=lower, ci_upper=upper,
        outcome_type=kind, endpoint_class=endpoint,
    )


class TestEffectEstimate(unittest.TestCase):
    def test_log_scale_and_standard_error(self):
        effect = hr(0.50, 0.37, 0.68)
        self.assertAlmostEqual(effect.log_value, math.log(0.50), places=10)
        # SE recovered from a 95% CI on the log scale.
        expected = (math.log(0.68) - math.log(0.37)) / (2 * 1.959963984540054)
        self.assertAlmostEqual(effect.standard_error, expected, places=10)

    def test_significance_is_read_from_the_interval(self):
        self.assertTrue(hr(0.63, 0.47, 0.86).is_significant)
        self.assertFalse(hr(0.95, 0.80, 1.13).is_significant)

    def test_non_hazard_ratios_are_excluded_not_converted(self):
        odds = EffectEstimate(nct_id="N", measure="Odds Ratio (OR)", value=2.0,
                              ci_lower=1.2, ci_upper=3.1)
        self.assertFalse(odds.is_poolable)

    def test_hazard_ratio_without_interval_is_not_poolable(self):
        self.assertFalse(hr(0.7, None, None).is_poolable)


class TestRegistryExtraction(unittest.TestCase):
    def test_endpoint_classification(self):
        self.assertEqual(classify_endpoint("Overall Survival (OS) Rate"), "os")
        self.assertEqual(classify_endpoint("Progression Free Survival (PFS)"), "pfs")
        self.assertEqual(classify_endpoint("Objective Response Rate"), "other")

    def test_extracts_hazard_ratio_and_flags_others(self):
        payload = {
            "protocolSection": {"identificationModule": {"nctId": "NCT99"}},
            "resultsSection": {"outcomeMeasuresModule": {"outcomeMeasures": [
                {"type": "PRIMARY", "title": "Overall Survival (OS)", "analyses": [
                    {"paramType": "Hazard Ratio (HR)", "paramValue": "0.63",
                     "ciLowerLimit": "0.47", "ciUpperLimit": "0.86", "pValue": "0.002"}]},
                {"type": "SECONDARY", "title": "Response Rate", "analyses": [
                    {"paramType": "Difference in percentages", "paramValue": "16.6"}]},
            ]}},
        }
        estimates = extract_effect_estimates(payload)
        self.assertEqual(len(estimates), 2)
        self.assertTrue(estimates[0].is_poolable)
        self.assertEqual(estimates[0].endpoint_class, "os")
        self.assertFalse(estimates[1].is_poolable)
        self.assertIn("not a hazard ratio", estimates[1].excluded_reason)


class TestPooling(unittest.TestCase):
    def test_identical_trials_pool_to_their_common_value(self):
        estimates = [hr(0.70, 0.55, 0.89, nct="N%d" % i) for i in range(4)]
        pooled = priors.pool(estimates, "t")
        self.assertAlmostEqual(pooled.hazard_ratio, 0.70, places=6)
        self.assertEqual(pooled.tau_squared, 0.0)  # no heterogeneity

    def test_heterogeneity_is_detected(self):
        estimates = [hr(v, l, u, nct="N%d" % i) for i, (v, l, u) in enumerate(
            [(0.50, 0.37, 0.68), (0.63, 0.47, 0.86), (0.78, 0.65, 0.94), (0.95, 0.80, 1.13)])]
        pooled = priors.pool(estimates, "t")
        self.assertGreater(pooled.i_squared, 50)
        self.assertGreater(pooled.tau_squared, 0)
        # A prediction interval must be wider than the confidence interval.
        self.assertLess(pooled.prediction_lower_log, pooled.ci_lower_log)
        self.assertGreater(pooled.prediction_upper_log, pooled.ci_upper_log)

    def test_more_precise_trials_get_more_weight(self):
        precise = hr(0.60, 0.55, 0.65, nct="A")
        vague = hr(1.00, 0.50, 2.00, nct="B")
        pooled = priors.pool([precise, vague], "t")
        self.assertLess(pooled.hazard_ratio, 0.75)

    def test_empty_input_is_reported_not_crashed(self):
        pooled = priors.pool([], "t")
        self.assertEqual(pooled.k, 0)
        self.assertIsNone(pooled.hazard_ratio)


class TestPower(unittest.TestCase):
    def test_schoenfeld_required_events(self):
        # 4 (1.95996 + 0.84162)^2 / ln(0.65)^2 = 169.2 -> 170
        self.assertEqual(required_events(0.65, 0.05, 0.80), 170)
        self.assertEqual(required_events(0.70, 0.05, 0.80), 247)

    def test_power_inverts_the_event_formula(self):
        for ratio in (0.55, 0.65, 0.75):
            events = required_events(ratio, 0.05, 0.80)
            self.assertAlmostEqual(power_at_events(ratio, events, 0.05), 0.80, delta=0.01)

    def test_weaker_true_effect_means_less_power(self):
        events = required_events(0.65, 0.05, 0.80)
        self.assertLess(power_at_events(0.78, events), 0.80)

    def test_null_effect_has_no_finite_answer(self):
        self.assertIsNone(required_events(1.0))
        self.assertIsNone(power_at_events(1.0, 500))

    def test_participants_scale_with_event_probability(self):
        self.assertEqual(participants_for_events(170, 0.5), 340)
        self.assertIsNone(participants_for_events(170, 0))

    def test_invalid_alpha_is_rejected(self):
        with self.assertRaises(ValueError):
            required_events(0.65, alpha=1.5)


def _cohort(spec):
    """Build a cohort from (hr, lower, upper, published) tuples."""
    trials = []
    for index, (value, lower, upper, published) in enumerate(spec):
        trial = Trial(nct_id="NCT%04d" % index, title="t%d" % index,
                      lead_sponsor_class="INDUSTRY", phases=["PHASE3"], enrollment=400,
                      start_date="2015-01-01")
        effects = []
        if value is not None:
            effects = [hr(value, lower, upper, nct=trial.nct_id)]
        links = [PublicationLink(nct_id=trial.nct_id, pmid="1%03d" % index)] if published else []
        trials.append(CohortTrial(trial=trial, effects=effects, links=links))
    return Cohort(condition="test", endpoint_class="os", trials=trials, phases=["3"])


class TestCategories(unittest.TestCase):
    def test_three_categories_are_assigned_correctly(self):
        cohort = _cohort([
            (0.70, 0.55, 0.89, True),   # A
            (0.95, 0.80, 1.13, False),  # B
            (None, None, None, False),  # C
        ])
        got = [t.category("os") for t in cohort.trials]
        self.assertEqual(got, [CATEGORY_A, CATEGORY_B, CATEGORY_C])

    def test_registry_sponsor_class_beats_the_name_heuristic(self):
        trial = Trial(nct_id="N", title="t", lead_sponsor="University Hospital X",
                      lead_sponsor_class="INDUSTRY")
        self.assertEqual(sponsor_type(trial), "INDUSTRY")

    def test_primary_outcome_wins_over_secondary(self):
        trial = Trial(nct_id="N", title="t")
        item = CohortTrial(trial=trial, effects=[
            hr(0.90, 0.80, 1.01, kind="SECONDARY"),
            hr(0.60, 0.50, 0.72, kind="PRIMARY"),
        ])
        self.assertEqual(item.best_effect("os").value, 0.60)


class TestPriorComparison(unittest.TestCase):
    def test_registry_only_trials_move_the_prior(self):
        cohort = _cohort([
            (0.55, 0.45, 0.67, True), (0.60, 0.50, 0.72, True), (0.58, 0.47, 0.71, True),
            (0.98, 0.85, 1.13, False), (1.02, 0.88, 1.18, False),
        ])
        result = priors.compare_priors(cohort)
        self.assertEqual(result["literature_only"]["k"], 3)
        self.assertEqual(result["registry_aware"]["k"], 5)
        self.assertGreater(result["shift_log_hr"], 0)  # moves toward the null
        self.assertIn("toward", result["interpretation"])

    def test_identical_priors_are_described_as_such(self):
        cohort = _cohort([(0.70, 0.6, 0.82, True), (0.72, 0.61, 0.85, True),
                          (0.68, 0.57, 0.81, True)])
        result = priors.compare_priors(cohort)
        self.assertEqual(result["trials_added"], 0)
        self.assertIn("identical", result["interpretation"])


class TestSensitivity(unittest.TestCase):
    def test_pseudo_trials_round_trip_their_standard_error(self):
        pseudo = sensitivity._pseudo_trials(3, 0.95, 0.15)
        self.assertEqual(len(pseudo), 3)
        self.assertAlmostEqual(pseudo[0].standard_error, 0.15, places=9)
        self.assertAlmostEqual(pseudo[0].value, 0.95, places=9)

    def test_sweep_moves_monotonically_with_the_assumption(self):
        cohort = _cohort([
            (0.60, 0.50, 0.72, True), (0.65, 0.54, 0.78, True), (0.70, 0.58, 0.84, True),
            (None, None, None, False), (None, None, None, False),
        ])
        result = sensitivity.sweep(cohort, assumed_hazard_ratios=(0.8, 1.0, 1.2))
        self.assertEqual(result["unknown_trials"], 2)
        ratios = [p["pooled_hazard_ratio"] for p in result["points"]]
        self.assertEqual(ratios, sorted(ratios))

    def test_no_unknowns_leaves_the_estimate_alone(self):
        cohort = _cohort([(0.60, 0.50, 0.72, True), (0.65, 0.54, 0.78, True),
                          (0.70, 0.58, 0.84, True)])
        result = sensitivity.sweep(cohort, assumed_hazard_ratios=(0.8, 1.2))
        self.assertEqual(result["unknown_trials"], 0)
        self.assertAlmostEqual(result["points"][0]["pooled_hazard_ratio"],
                               result["points"][1]["pooled_hazard_ratio"], places=9)


class TestBacktest(unittest.TestCase):
    def test_small_cohorts_refuse_to_run(self):
        cohort = _cohort([(0.70, 0.6, 0.82, True), (0.72, 0.61, 0.85, True)])
        result = backtest.run(cohort)
        self.assertFalse(result["ran"])
        self.assertIn("needs more", result["note"])

    def test_leave_one_out_scores_every_trial_once(self):
        spec = [(0.60 + 0.03 * i, 0.50 + 0.03 * i, 0.74 + 0.03 * i, i % 2 == 0)
                for i in range(10)]
        result = backtest.run(_cohort(spec), level=0.80)
        self.assertTrue(result["ran"])
        self.assertEqual(result["n"], 10)
        self.assertEqual(len(result["folds"]), 10)
        for key in ("literature_only", "registry_aware"):
            block = result["summary"][key]
            self.assertLessEqual(block["coverage"], 1.0)
            self.assertGreaterEqual(block["coverage"], 0.0)

    def test_a_held_out_trial_never_trains_its_own_prediction(self):
        spec = [(0.60, 0.50, 0.72, True)] * 5 + [(2.00, 1.60, 2.50, True)]
        result = backtest.run(_cohort(spec), level=0.80)
        outlier = result["folds"][-1]
        # If the outlier had trained on itself, the prediction would sit near 2.0.
        self.assertLess(outlier["predictions"]["registry_aware"]["predicted_hazard_ratio"], 1.0)

    def test_intervals_are_calibrated_on_data_matching_the_model(self):
        """Coverage should land near the nominal level when the model is right.

        Trials are generated the way the random-effects model assumes: a true
        effect drawn around a common mean with between-trial spread tau, then an
        observed estimate drawn around that true effect with its own standard
        error, which is what the reported interval encodes.
        """
        rng = np.random.default_rng(7)
        tau, standard_error = 0.15, 0.12
        half = 1.959963984540054 * standard_error
        coverages = []
        for _ in range(30):
            spec = []
            for _ in range(20):
                true_log = rng.normal(math.log(0.70), tau)
                observed = float(np.exp(rng.normal(true_log, standard_error)))
                spec.append((observed, observed * math.exp(-half), observed * math.exp(half), True))
            result = backtest.run(_cohort(spec), level=0.80)
            coverages.append(result["summary"]["literature_only"]["coverage"])
        mean_coverage = sum(coverages) / len(coverages)
        self.assertGreater(mean_coverage, 0.70, "intervals are too narrow")
        self.assertLess(mean_coverage, 0.92, "intervals are too wide")


class TestPublicationModel(unittest.TestCase):
    def test_refuses_to_fit_without_variation(self):
        cohort = _cohort([(0.7, 0.6, 0.82, True)] * 8)
        model = publication_model.fit_publication_model(cohort)
        self.assertFalse(model.fitted)
        self.assertIn("Not enough trials", model.note)

    def test_linkage_rates_split_by_significance(self):
        cohort = _cohort([
            (0.60, 0.50, 0.72, True), (0.62, 0.51, 0.75, True),
            (0.98, 0.85, 1.13, False), (1.01, 0.88, 1.16, False),
        ])
        rates = publication_model.linkage_rates(cohort)
        self.assertEqual(rates["n"], 4)
        self.assertEqual(rates["by_significance"]["significant"]["linkage_rate"], 1.0)
        self.assertEqual(rates["by_significance"]["not_significant"]["linkage_rate"], 0.0)

    def test_recovers_a_known_coefficient(self):
        rng = np.random.default_rng(3)
        rows = []
        for index in range(400):
            log_hr = float(rng.normal(-0.25, 0.35))
            probability = 1 / (1 + np.exp(-(0.5 - 4.0 * log_hr)))
            rows.append({
                "nct_id": "N%d" % index,
                "published": int(rng.random() < probability),
                "log_hr": log_hr, "significant": int(rng.random() < 0.5),
                "favors_treatment": int(log_hr < 0), "industry": index % 2,
                "phase3": int(index % 3 == 0), "log_enrollment": float(np.log(200 + index)),
                "start_year": 2015,
            })
        original = publication_model._rows
        try:
            publication_model._rows = lambda cohort: rows
            model = publication_model.fit_publication_model(object())
        finally:
            publication_model._rows = original
        self.assertTrue(model.fitted)
        beta = next(c for c in model.coefficients if c.name == "log_hr")
        self.assertLessEqual(beta.estimate - 1.96 * beta.standard_error, -4.0)
        self.assertGreaterEqual(beta.estimate + 1.96 * beta.standard_error, -4.0)


class TestBlastRadius(unittest.TestCase):
    def test_counts_citations_after_the_retraction_date(self):
        from graph import blast_radius

        nodes = [
            {"id": "s", "title": "seed", "date": "2020-01-01", "citations": 10,
             "exposure": "retracted", "retraction": {"status": "retracted", "notices": [
                 {"type": "retraction", "date": "2023-04-22T00:00:00Z"}]}},
            {"id": "a", "title": "before", "date": "2022-01-01", "citations": 5,
             "exposure": "direct", "retraction": {"status": "no_notice_found", "notices": []}},
            {"id": "b", "title": "after", "date": "2024-01-01", "citations": 7,
             "exposure": "direct", "retraction": {"status": "no_notice_found", "notices": []}},
            {"id": "c", "title": "downstream", "date": "2025-01-01", "citations": 2,
             "exposure": "indirect", "retraction": {"status": "no_notice_found", "notices": []}},
        ]
        result = blast_radius(nodes, [], "s")
        self.assertEqual(result["retraction_date"], "2023-04-22")
        self.assertEqual(result["direct_citations"], 2)
        self.assertEqual(result["downstream_descendants"], 1)
        self.assertEqual(result["cited_after_retraction"], 2)
        self.assertEqual(result["cited_before_retraction"], 1)
        self.assertEqual(result["weighted_downstream_citation_mass"], 14)

    def test_missing_retraction_date_is_reported(self):
        from graph import blast_radius

        nodes = [{"id": "s", "title": "s", "date": "2020-01-01", "citations": 1,
                  "exposure": "none", "retraction": {"status": "unknown", "notices": []}}]
        result = blast_radius(nodes, [], "s")
        self.assertIsNone(result["retraction_date"])
        self.assertIn("could not be determined", result["note"])


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestCohortPersistence(unittest.TestCase):
    """A saved cohort must reproduce the analysis with no network access."""

    def test_round_trip_preserves_every_number(self):
        import tempfile

        from backend.publication_bias.analysis import analyze
        from backend.publication_bias.cohort import load_cohort, save_cohort

        cohort = _cohort([
            (0.55, 0.45, 0.67, True), (0.60, 0.50, 0.72, True), (0.58, 0.47, 0.71, True),
            (0.71, 0.60, 0.84, True), (0.98, 0.85, 1.13, False), (1.02, 0.88, 1.18, False),
            (None, None, None, False),
        ])
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as handle:
            path = handle.name
        try:
            save_cohort(cohort, path)
            restored = load_cohort(path)

            self.assertEqual(len(restored.trials), len(cohort.trials))
            self.assertEqual(
                [t.category("os") for t in restored.trials],
                [t.category("os") for t in cohort.trials],
            )
            before = analyze(cohort, assumed_hr=0.65)
            after = analyze(restored, assumed_hr=0.65)
            self.assertEqual(before["cohort"]["categories"], after["cohort"]["categories"])
            self.assertAlmostEqual(
                before["priors"]["registry_aware"]["hazard_ratio"],
                after["priors"]["registry_aware"]["hazard_ratio"], places=10)
            self.assertEqual(
                before["design"]["consequence"]["planned_events"],
                after["design"]["consequence"]["planned_events"])
        finally:
            os.unlink(path)
