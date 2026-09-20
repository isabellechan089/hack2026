# Evidence Atlas — two-minute demo

The demo tells one story: *a paper you trust cites something that was retracted,
and here is how far that goes.*

## Before presenting

1. `venv/bin/python capture_demo.py` — refreshes both saved snapshots. It
   refuses to overwrite them if the seed retraction cannot be confirmed, so a
   clean run is your green light.
2. `venv/bin/python main.py`, open http://127.0.0.1:8000.
3. The app opens in **Bias-aware design** on the saved lung-cancer cohort.
   Switch to **Check my sources** once so the saved example is warm too.
4. Use a wide window — the graph and evidence panel sit side by side above
   1000px.
5. Both modes work from saved snapshots with no network. Never present a
   snapshot as a fresh live lookup; the panel labels which it is.

Two ways to run the story. The retraction-first version below is the one that
lands with a general audience; for Regeneron, open on the design view and give
the last section first, then the funnel plot ("Where the missing trials sit")
and the ten-cohort table ("Does it repeat in other disease areas?").

## 0:00–0:20 — The question researchers actually have

“Every paper rests on its references. When one of those is retracted, nobody
tells you. This checks.”

Paste a DOI, or use the loaded example: a *Nature Reviews Clinical Oncology*
review with 182 references.

## 0:20–0:45 — The answer, with evidence

“One of the 179 references we could resolve has been retracted.”

Point at the verdict, then the flagged card: the retraction notice, dated
2023-04-22, confirmed by Retraction Watch *and* the publisher, linked so anyone
can check it.

Note the coverage line: 179 of 182 resolved, and what the screen did and did not
check. The tool does not claim the other 178 are clean — only that nothing was
found.

## 0:45–1:15 — How far did it spread?

Click **See how far this spread →** on the flagged card. That re-centres the
citation graph on the retracted paper.

“20 of its 52 direct citations are shown, and 66 of the connected papers were
published *after* the retraction notice appeared.”

Point at the stat tile. Then select an outer node: the panel shows a shortest
citation path back to the retraction, one clickable step at a time.

## 1:15–1:40 — Why it is trustworthy

“Orange cites the retracted work directly, blue connects through another
paper. A citation is a reason to look, not a verdict — a paper may be citing the
retraction itself.”

Show **Make this the starting paper** to continue the chain from any node, and
**Check this paper's own references** to jump back the other way.

Mention the sampling honestly: “showing 20 of 52” is on screen, not buried.

## 1:40–2:00 — The bigger product

Click **Bias-aware design** in the Clinical design group. It answers instantly
from the saved cohort.

“Same graph, the other direction. 400 completed lung-cancer trials. Trials that
worked are published 92% of the time; trials that did not, 62%. Correct for
that and the pooled hazard ratio moves from 0.76 to 0.80 — and a trial you
sized for 80% power actually delivers 32%.”

Scroll to the funnel plot: “every trial by its effect and its precision. The
orange ones, the results that never reached a paper, sit in the corner the
literature is missing: small and unimpressive. Egger's test puts a number on
it.” Then the back-test: “out of sample, the literature-only model is
systematically optimistic, the registry-aware one is close to unbiased.” Then
the ten-cohort table: “and it is not a lung-cancer quirk. In all ten cohorts
significant trials were linked more often; in nine of ten the correction moved
the prior toward the null.”

If asked where the AI is: tick **Read open full text** and point at section 7.
“The model reads only the sentences that could carry a hazard ratio — 13
thousand tokens instead of 354 thousand, every value checked against the
sentence it came from. Then in Trial ↔ paper, *Search for unlinked
publications*: it retrieved six look-alikes for this trial, and the model
rejected all six, naming the design mismatch each time. A metadata score alone
is never allowed to accept.”

If asked what the AI cost: scroll to the last card. “Four tenths of a cent so
far, measured from the API's own usage counts. The same work at the next tier
up would have been four times that.”

## If asked about AI

“No language model is in this path. Citation structure, retraction status,
graph distances and the statistics are all computed. An LLM would be for
normalising endpoint wording, not for deciding what is retracted.”

## If live retrieval fails

Click **Load saved example** in either mode. Say plainly that it is a saved
snapshot of real previously fetched metadata.
