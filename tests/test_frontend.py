"""Execute static/app.js against a DOM stub and drive both modes.

A syntax check and an element-id cross-reference both pass on a handler that
runs and then does the wrong thing. This actually clicks the mode tabs and
checks what the page would show, which is the only way that class of bug gets
caught without a browser.

Requires JavaScriptCore via `osascript`, so it skips on non-macOS.
"""

import os
import shutil
import subprocess
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DRIVER = os.path.join(REPO, "tests", "frontend", "drive.js")


def run_driver():
    env = dict(os.environ, REPO=REPO)
    result = subprocess.run(
        ["osascript", "-l", "JavaScript", DRIVER],
        capture_output=True, text=True, env=env, timeout=120,
    )
    pairs = {}
    for line in result.stdout.splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            pairs[key.strip()] = value.strip()
    return pairs, result


@unittest.skipUnless(shutil.which("osascript"), "needs JavaScriptCore via osascript")
class FrontendBehaviourTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.state, cls.result = run_driver()

    def test_the_script_runs_without_throwing(self):
        self.assertNotIn("THREW", self.state,
                         "app.js threw: {}\n{}".format(self.state.get("THREW"), self.result.stderr))
        self.assertTrue(self.state, "driver produced no output: " + self.result.stderr)

    def test_opens_on_the_hero_feature(self):
        # The landing view is bias-aware design: it answers from a saved cohort
        # in well under a second, so nothing is lost by starting there.
        self.assertEqual(self.state["initial_mode"], "design")
        self.assertEqual(self.state["start_designpanel_visible"], "true")
        self.assertEqual(self.state["start_workspace_hidden"], "true")
        self.assertEqual(self.state["start_sourcepanel_hidden"], "true")
        self.assertEqual(self.state["sources_mode_switch"], "true")

    def test_reference_check_renders_its_findings(self):
        for key in ("sources_rendered", "sources_has_flagcard",
                    "sources_has_trace_link", "sources_names_retraction"):
            self.assertEqual(self.state[key], "true", key)

    def test_trace_tab_actually_switches_to_the_graph(self):
        # Regression: the mode switch once called setMode('sources') instead of
        # load(true), so this tab bounced straight back to the other mode.
        self.assertEqual(self.state["trace_mode_is_trace"], "true")
        self.assertEqual(self.state["trace_shows_workspace"], "true")
        self.assertEqual(self.state["trace_hides_sourcepanel"], "true")

    def test_graph_renders_nodes_edges_and_coverage(self):
        self.assertEqual(self.state["graph_nodes_drawn"], "true")
        self.assertEqual(self.state["graph_edges_drawn"], "true")
        self.assertEqual(self.state["stat_tiles"], "4")
        # Sampling must be stated, not implied away.
        self.assertEqual(self.state["coverage_shown"], "true")

    def test_any_node_can_continue_the_chain(self):
        self.assertEqual(self.state["node_offers_recenter"], "true")
        self.assertEqual(self.state["node_offers_checkrefs"], "true")
        self.assertEqual(self.state["node_shows_evidence_trail"], "true")
        # Re-rooting on the current centre would be a no-op, so it is not offered.
        self.assertEqual(self.state["seed_has_no_recenter"], "true")

    def test_switching_back_restores_the_reference_check(self):
        self.assertEqual(self.state["back_to_sources"], "true")

    def test_bias_aware_design_view_renders_every_section(self):
        self.assertEqual(self.state["design_mode"], "true")
        self.assertEqual(self.state["design_panel_visible"], "true")
        self.assertEqual(self.state["design_line_visible"], "true")
        for key in ("design_has_stackbar", "design_has_linkage_bars", "design_has_forest",
                    "design_has_meters", "design_has_backtest", "design_has_sensitivity"):
            self.assertEqual(self.state[key], "true", key)

    def test_funnel_plot_and_small_study_test_render(self):
        self.assertEqual(self.state["design_has_funnel"], "true")
        self.assertEqual(self.state["design_funnel_has_points"], "true")
        self.assertEqual(self.state["design_has_egger"], "true")
        self.assertEqual(self.state["design_names_provenance"], "true")
        # The fixture was captured with an event probability, so participants appear.
        self.assertEqual(self.state["design_has_participants"], "true")

    def test_overview_and_ledger_cards_fill_in(self):
        self.assertEqual(self.state["design_has_lazy_cards"], "true")
        self.assertEqual(self.state["overview_lists_cohorts"], "true")
        self.assertEqual(self.state["overview_states_pattern"], "true")
        self.assertEqual(self.state["ledger_shows_dollars"], "true")
        self.assertEqual(self.state["ledger_shows_counterfactual"], "true")
        self.assertEqual(self.state["ledger_has_purpose_bars"], "true")

    def test_search_view_offers_facets_over_every_match(self):
        self.assertEqual(self.state["search_has_facets"], "true")
        self.assertEqual(self.state["search_facet_publication"], "true")
        self.assertEqual(self.state["search_shows_total"], "true")

    def test_reviewer_view_shows_paths_and_their_evidence(self):
        self.assertEqual(self.state["reviewer_mode"], "true")
        self.assertEqual(self.state["reviewer_panel_visible"], "true")
        self.assertEqual(self.state["reviewer_has_verdict"], "true")
        self.assertEqual(self.state["reviewer_has_path"], "true")
        # A path without its shared works would be an opaque score.
        self.assertEqual(self.state["reviewer_has_evidence"], "true")

    def test_trial_view_lists_publications_and_compares_fields(self):
        self.assertEqual(self.state["trial_mode"], "true")
        self.assertEqual(self.state["trial_panel_visible"], "true")
        self.assertEqual(self.state["trial_has_publist"], "true")
        self.assertEqual(self.state["trial_has_table"], "true")
        self.assertEqual(self.state["trial_has_status_tags"], "true")

    def test_recovery_panel_shows_sources_and_cost(self):
        self.assertEqual(self.state["design_has_recovery_panel"], "true")
        self.assertEqual(self.state["design_recovery_has_meter"], "true")
        self.assertEqual(self.state["design_recovery_lists_trials"], "true")
        # Registry-posted and publication-extracted estimates are never conflated.
        self.assertEqual(self.state["design_names_sources"], "true")

    def test_cascade_renders_model_assisted_decisions_and_reasons(self):
        self.assertEqual(self.state["trial_has_cascade_card"], "true")
        self.assertEqual(self.state["cascade_renders_decisions"], "true")
        self.assertEqual(self.state["cascade_shows_model_reason"], "true")
        # A metadata score alone can never produce an "accepted" row.
        self.assertEqual(self.state["cascade_never_shows_plain_accepted"], "true")

    def test_search_view_renders_hits_over_the_index(self):
        self.assertEqual(self.state["search_mode"], "true")
        self.assertEqual(self.state["search_panel_visible"], "true")
        self.assertEqual(self.state["search_line_visible"], "true")
        self.assertEqual(self.state["search_has_hits"], "true")
        self.assertEqual(self.state["search_shows_index_size"], "true")

    def test_no_view_renders_undefined_or_nan(self):
        # A misspelled payload key surfaces as "undefined" in the markup rather
        # than as an exception, so it has to be asserted against directly.
        for key in ("design_no_undefined", "reviewer_no_undefined", "trial_no_undefined",
                    "cascade_no_undefined", "search_no_undefined", "overview_no_undefined",
                    "ledger_no_undefined"):
            self.assertEqual(self.state[key], "true", key)


if __name__ == "__main__":
    unittest.main(verbosity=2)
