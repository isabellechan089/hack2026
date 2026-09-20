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

    def test_opens_in_reference_check_mode(self):
        self.assertEqual(self.state["initial_mode"], "sources")
        self.assertEqual(self.state["start_sourcepanel_visible"], "true")
        self.assertEqual(self.state["start_workspace_hidden"], "true")

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
