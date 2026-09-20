"""Check the stylesheet against the markup it styles.

This exists because of a bug no other test could see. Every input row carries
the class `.searchline`, and the stylesheet sets `display:flex` on it. An
author rule that sets `display` outranks the browser's own `[hidden]
{display:none}` rule, so setting `.hidden = true` in JavaScript hid nothing:
all five input rows rendered on every tab at once.

The JavaScript was correct and the DOM stub agreed with it, because the stub
models the `hidden` property and not the cascade. Only a rule about the
stylesheet itself catches this.
"""

import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSS = os.path.join(REPO, "static", "style.css")
HTML = os.path.join(REPO, "static", "index.html")
APP = os.path.join(REPO, "static", "app.js")


def read(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def rules(css):
    """(selector, body) for every rule, with comments and at-rule wrappers dropped."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    css = re.sub(r"@media[^{]*\{", "", css)          # flatten; the risk is the same inside
    return re.findall(r"([^{}]+)\{([^{}]*)\}", css)


def hidden_toggled_ids(app_js, html):
    """Element ids the page hides by setting `.hidden`, and the classes they carry."""
    ids = set(re.findall(r"\$\('#(\w+)'\)\.hidden\s*=", app_js))
    for listname in ("PANELS", "LINES"):
        match = re.search(listname + r"\s*=\s*\[([^\]]*)\]", app_js)
        if match:
            ids |= set(re.findall(r"'(\w+)'", match.group(1)))
    found = {}
    for element_id in ids:
        tag = re.search(r"<[^>]*\bid=\"" + element_id + r"\"[^>]*>", html)
        if tag is None:
            tag = re.search(r"<[^>]*\bclass=\"([^\"]*)\"[^>]*\bid=\"" + element_id + r"\"", html)
            found[element_id] = set(tag.group(1).split()) if tag else set()
            continue
        classes = re.search(r"class=\"([^\"]*)\"", tag.group(0))
        found[element_id] = set(classes.group(1).split()) if classes else set()
    return found


class HiddenElementsStayHidden(unittest.TestCase):
    """A hidden element must not be re-shown by a `display` rule in the stylesheet."""

    @classmethod
    def setUpClass(cls):
        cls.css = read(CSS)
        cls.html = read(HTML)
        cls.app = read(APP)
        cls.rules = rules(cls.css)

    def test_the_page_hides_something_by_this_mechanism(self):
        # If this ever finds nothing, the test below is vacuously passing.
        toggled = hidden_toggled_ids(self.app, self.html)
        self.assertGreaterEqual(len(toggled), 8, "expected the page to toggle .hidden on many elements")

    def test_no_display_rule_outranks_the_hidden_attribute(self):
        toggled = hidden_toggled_ids(self.app, self.html)
        neutralized = any(
            "[hidden]" in selector and re.search(r"display\s*:\s*none", body)
            for selector, body in self.rules
        )
        offenders = []
        for selector, body in self.rules:
            if not re.search(r"(^|;)\s*display\s*:", body):
                continue
            for part in selector.split(","):
                part = part.strip()
                if "[hidden]" in part:
                    continue
                for element_id, classes in toggled.items():
                    hits = ("#" + element_id) in part or any("." + c in part for c in classes)
                    if hits:
                        offenders.append((part, element_id, body.strip()[:40]))
        if offenders and not neutralized:
            self.fail(
                "these rules set `display` on an element the page hides, and nothing "
                "restores [hidden]:\n  "
                + "\n  ".join("{}  (hides #{})  {}".format(*o) for o in offenders)
            )
        if offenders:
            self.assertTrue(neutralized)

    def test_the_hidden_rule_is_strong_enough_to_win(self):
        # A bare `[hidden]{display:none}` loses to `.searchline{display:flex}`
        # on specificity, so the override has to be marked important.
        match = [body for selector, body in self.rules if "[hidden]" in selector]
        self.assertTrue(match, "no [hidden] rule in the stylesheet")
        self.assertTrue(
            any(re.search(r"display\s*:\s*none\s*!important", body) for body in match),
            "the [hidden] rule must be !important to beat a class that sets display",
        )


class ChartsAreNotStretched(unittest.TestCase):
    """A chart's height must come from its content, not from its container."""

    def test_only_the_stacked_bar_disables_aspect_ratio(self):
        # preserveAspectRatio="none" stretches glyphs and makes a tall viewBox
        # render enormous when the width is 100%. Only the single stacked bar,
        # which holds no text, is allowed to do it.
        charts = read(os.path.join(REPO, "static", "charts.js"))
        stretched = re.findall(r'aria-label="\$\{CH\.esc\(opts\.title \|\| \'([^\']+)\'', charts)
        none_used = charts.count('preserveAspectRatio="none"')
        self.assertEqual(none_used, 1, "only the stacked bar may set preserveAspectRatio=none")
        self.assertIn("class=\"chart stack\"", charts)

    def test_every_plot_draws_a_scale(self):
        charts = read(os.path.join(REPO, "static", "charts.js"))
        for name in ("function hbar", "function forest", "function linechart"):
            start = charts.index(name)
            end = charts.index("\n/**", start + 1) if "\n/**" in charts[start:] else len(charts)
            body = charts[start:end]
            self.assertIn("<text", body, name + " must label its scale")
            self.assertIn("stroke=\"${VIZ.grid}\"", body, name + " must draw gridlines or an axis")


if __name__ == "__main__":
    unittest.main(verbosity=2)
