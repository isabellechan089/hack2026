# EvidenceAtlas

**The effect sizes people use to design clinical trials come from published
literature — but published literature is missing some of the trials that were
registered and completed.**

TrialTrace links the trial registry to the scholarly record, measures that gap,
and shows what it does to a trial design. The same graph also powers retraction
propagation and reviewer-conflict analysis.

Full product specification: [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md).

---

## The result, on real data

400 completed phase II/III non-small-cell lung cancer trials with posted
registry results, progression-free survival:

```
                                    linked to a publication
  statistically significant                93%   (n=41)
  not significant                          60%   (n=45)

  favours treatment                        85%   (n=61)
  favours control                          52%   (n=25)
```

Trials that worked are far more likely to be findable in the literature. That
shifts the pooled effect estimate:

```
  PRIOR                     HR          95% CI      TRIALS
  Literature-only        0.761   (0.711, 0.814)         65
  Registry-aware         0.801   (0.756, 0.848)         86
```

And that shift has a design consequence:

```
  BASIS                            HR    EVENTS   POWER DELIVERED
  Your assumption                0.65       170               80%
  Published-literature estimate  0.76       422               43%
  Registry-aware estimate        0.80       636               30%
```

Leave-one-out back-test over the 86 trials with usable hazard ratios:

```
  MODEL                  COVERAGE   MAE log(HR)     BIAS
  Literature-only             79%         0.291   -0.044
  Registry-aware              76%         0.279   +0.007
```

Both models are well calibrated. The difference is in **bias**: the
literature-only model systematically predicts a stronger effect than held-out
trials actually delivered, while the registry-aware model is close to unbiased.
That direction is exactly what publication selection predicts.

### Where the missing trials sit

A funnel plot puts every trial at its effect and its precision. Publication
selection hollows out one corner: small trials with unimpressive results.
Egger's regression test measures that asymmetry.

```
  EGGER'S TEST            TRIALS      INTERCEPT          P
  Literature-only             65   -2.36 ± 0.31     <0.001
  Registry-aware              86   -1.87 ± 0.27     <0.001


  17 of the 21 registry-only trials are less precise than the median
  published trial, and 17 report a weaker effect than the pooled estimate.
```

The registry-only trials land in exactly the corner the literature is missing,
and adding them back moves the intercept toward zero. It does not reach zero:
the registry itself is incomplete, and small-study effects have other causes.

### Does it repeat in other disease areas?

Eleven cohorts, six disease areas, the same pipeline (`/api/overview`):

```
  COHORT                      LINKED · SIGNIFICANT   LINKED · NOT SIG.   HR LITERATURE → REGISTRY
  breast cancer          OS        100%  (n=8)          94%  (n=32)        0.891 → 0.886
  breast cancer          PFS        96%  (n=26)         77%  (n=26)        0.755 → 0.771
  colorectal cancer      OS        100%  (n=14)         73%  (n=30)        0.878 → 0.890
  colorectal cancer      PFS        95%  (n=19)         66%  (n=35)        0.802 → 0.845
  melanoma               OS        100%  (n=12)         82%  (n=28)        0.812 → 0.828
  melanoma               PFS        92%  (n=25)         68%  (n=19)        0.702 → 0.712
  NSCLC                  OS        100%  (n=14)         75%  (n=59)        0.905 → 0.918
  NSCLC                  PFS        93%  (n=41)         60%  (n=45)        0.761 → 0.801
  glioblastoma           PFS        78%  (n=9)          85%  (n=13)       0.927 → 0.957
  prostate cancer        OS        100%  (n=10)         86%  (n=28)        0.927 → 0.935
  prostate cancer        PFS        95%  (n=21)         78%  (n=18)        0.728 → 0.757
```

In ten of the eleven, statistically significant trials were more likely to be
linked to a publication, and adding the registry-only trials moved the pooled
hazard ratio toward the null. Glioblastoma is the exception on both counts, and
the tool reports that rather than hiding it. The counts are descriptive; they
say how often the direction repeated, not that it must.

---

## Run

```sh
python3 -m venv venv
venv/bin/python -m pip install -r requirements.txt
```

### The web app

```sh
venv/bin/python main.py       # then open http://127.0.0.1:8000
venv/bin/python main.py --check   # print what is installed and configured, then exit
```

`--check` is the first thing to run on a new machine. It reports the Python
version, which packages are present, how many cohorts are saved, and which
features are switched off for want of a key. It never prints a key's value.

**Running it for the first time.** A fresh clone needs only
`pip install -r requirements.txt`. No `.env` is required: the bias-aware design
view, the trial comparison, the reference check, the retraction graph and the
reviewer check all work without one, because the saved cohorts and demo
snapshots are committed. Two things do need keys, and the app says so rather
than failing: *Search the index* needs Elasticsearch, and full-text recovery
and candidate adjudication need an OpenAI key. Copy `.env.example` to `.env`
to add them.

If the server will not start, the usual causes are a system Python instead of
the virtual environment, which shows as `No module named requests`, or port
8000 already in use, which the app now reports with the command to clear it.

Or in a container, with no local Python at all:

```sh
docker build -t trialtrace . && docker run --rm -p 8000:8000 --env-file .env trialtrace
```

Six views over one evidence graph, grouped the way the product is. The app
opens on the hero feature, which answers from a saved cohort in well under a
second.

**Clinical design** — *Bias-aware design* runs the whole publication-bias
pipeline in the browser: the A/B/C composition of the cohort, linkage rates by
result direction and significance, the two pooled priors as a forest plot, the
funnel plot with Egger's test, the power your design actually delivers (and the
participant count, if you give an event probability), the sensitivity sweep,
the back-test, the same numbers for every other saved cohort, and what the
model layer cost in dollars. Any disease area works: a saved cohort answers in
under a second, and a new one builds live in about ten seconds and is kept.
*Trial ↔ paper* takes a registry identifier and shows which publication
actually reports the trial, with the field-by-field comparison.

**Research integrity** — *Check my sources* screens a paper's whole reference
list for retractions. *Retraction spread* is the citation blast radius, with
re-rooting on any node. *Reviewer conflicts* returns exact coauthorship paths
with the shared works behind each step.

**Evidence index** — free-text search over every indexed trial and paper
(Elasticsearch, 2,123 trials and 2,763 papers across six disease areas), the
same retrieval that proposes candidates when a trial has no identifier link.
Facets are aggregations over every match, not the page shown: search a drug and
read off how many of its completed trials have a publication, how many posted a
hazard ratio, and their phases and sponsors. Click a facet to filter.

### The same analysis from the command line

```sh
venv/bin/python cli.py design --condition "non-small cell lung cancer" \
    --endpoint pfs --hr 0.65 --power 0.80
```

First run builds the cohort from live APIs and takes about 4 minutes; every
response is cached, so later runs are seconds. `--save` writes the cohort to
`data/cohorts/`.

### What the integrity views show

**Check my sources** — paste a paper you are citing, writing or reviewing. Every
work it cites is screened for retraction notices. On the bundled example, a
*Nature Reviews Clinical Oncology* review with 182 references, one retracted
reference is found in about half a second. Flagged entries show the notice, its
date and its source, linked so anyone can verify it. A clean result is reported
as "nothing found by this screen", never as a clean bill of health.

**Trace citations forward** — the blast radius of a retracted paper. Direct
citers, downstream descendants, weighted citation mass, and how many cite it
*after* the retraction date. Any node can be made the new starting paper, or
handed to the source check, so a chain can be followed in either direction for
as long as it goes.

Sampling is stated on screen ("showing 20 of 52 direct citations") rather than
implied away, and breadth is adjustable from the search bar.

### Reviewer conflict check

```sh
venv/bin/python cli.py reviewer --reviewer "Martin Reck" \
    --authors "Tony Mok" --max-hops 2 --since-year 2020
```

### Tests

```sh
venv/bin/python -m unittest discover -s tests -t . -v
```

154 tests, all offline. The statistics are checked against closed-form values
(Schoenfeld event counts, DerSimonian-Laird pooling, the Egger regression) and
against synthetic data with a known answer, so a regression in the maths fails
a test rather than producing a plausible-looking number. The interface is
tested by executing it: the page scripts run in a DOM stub, every view is
driven the way a user would, and the markup is checked for what it must show
and for what it must never show.

---

## How the pipeline works

```
ClinicalTrials.gov ──► cohort ──► posted results (hazard ratios)
                          │
                          ├──► publication linkage ──► PubMed ──► OpenAlex
                          │        3 channels                     (graph)
                          ▼
              A / B / C categories
                          │
        ┌─────────────────┼─────────────────┐
        ▼                 ▼                 ▼
  literature-only   registry-aware    sensitivity for
      prior             prior          unknown results
        └─────────────────┼─────────────────┘
                          ▼
              power / sample size  ──►  leave-one-out back-test
```

### Reading the papers the registry left out

Most trials without a usable estimate *do* have a publication — 149 of 314 in
the lung-cancer cohort. The registry posted an outcome table with no analysis;
the paper reports the hazard ratio. With **Read open full text** ticked, the
design view fetches open-access full text from Europe PMC for those trials,
reduces each article to the sentences that could carry a hazard ratio, and has
a small model pair each ratio with its endpoint and interval.

Every extracted value is validated against the sentence it came from — the
ratio must be positive, the interval must bracket it, and the quoted evidence
must appear in the text — or it is dropped, never guessed. Recovered estimates
are labelled `source: publication` and reported separately from registry
postings, so the two are never conflated.

The reduction step decides what the model is allowed to see, so a phrasing it
does not recognise is an estimate silently lost. Four kinds were, and are
covered by tests now: Lancet journals set decimals with a middle dot (`0·65`);
`aHR` and `HRs` carry no word boundary around the bare abbreviation; figure
captions live in `<fig><caption>`, which a search of a section's own paragraphs
steps over; and table cells concatenated without a separator weld the header to
the row beneath it (`EndpointHazard ratio95% CI`), destroying the very words
the filter matches on. Tables are where secondary-endpoint ratios usually sit.
`HR` also abbreviates hours and health-related quality of life, so those are
excluded by name rather than paid for.

Measured on the lung-cancer cohort: 93 trials had open full text, 41 parsed,
**5 trials recovered** for PFS (A: 65 → 70) and 6 for OS. Model input was
**12,996 tokens against 354,412** had whole papers been sent — a 96% reduction,
with every call answered by the smallest tier and none escalated. On one paper
measured both ways, 478 prompt tokens versus 3,735 (87%).

Note what this does and does not fix: a recovered trial has a publication by
construction, so it joins the *published* arm. The registry-only arm cannot be
rescued from the literature, because there is nothing to read.

### Linking trials to publications

Three channels, most authoritative first, because a false "unpublished" verdict
is the most damaging error this system can make. All of them batch: one PubMed
search covers fifty registry identifiers and records are fetched fifty at a
time, so a 400-trial cohort links in about ten seconds rather than four minutes.

1. `nct_registry_reference` — the registry lists a PMID.
2. `nct_pubmed_si` — PubMed indexes the NCT id as a secondary source id. This
   catches publications the registry never listed. Attribution uses that
   databank field alone: an identifier appearing only in a paper's abstract
   prose — a trial it compares against, say — is recorded but does not link.
3. `fuzzy` — a cascade, used only when neither identifier channel returns
   anything: Elasticsearch retrieves candidate papers from the trial's
   interventions, conditions and investigators; the deterministic scorer
   (investigator overlap, intervention, condition, enrollment, dates, sponsor)
   rejects clear non-matches on its own; and a small model reads the paper's
   abstract against the registration for everything left. **A metadata score
   never accepts on its own.** The same investigator running a sibling trial of
   the same drug scores 0.90 and is still a different trial — the model caught
   exactly that case and said why. Every model-assisted decision carries its
   reason and is flagged as such.

A trial with no link from any channel is reported as **"no publication
identified"**, never as "unpublished".

### The three categories

| | |
|---|---|
| **A** | publication identified + registry result — what the literature shows |
| **B** | registry result, no publication identified — **the observable gap** |
| **C** | neither — genuinely unknown, handled by sensitivity analysis only |

A vs B is an observable test of publication selection. C is never imputed to
null; instead an explicit assumption is swept across a range and the conclusion
is reported at each point.

---

## Design rules

- **Databases, graphs and statistics for facts; LLMs for language.** A small
  model is used for exactly two language tasks — reading a hazard ratio out of
  a sentence, and judging whether an abstract describes a given registration —
  and never sees a whole paper. Its output is validated against the text it
  read, labelled as model-assisted, and never becomes primary evidence. Every
  number in the statistics is a query, a graph traversal, or a model fit.
- **Measured, not assumed.** The registry-aware prior may move toward the null,
  away from it, or not at all. The tool reports which, and says when the two
  priors are identical.
- **One effect scale.** Only hazard ratios for one endpoint class are pooled.
  Odds ratios and response-rate differences are recorded with an exclusion
  reason rather than converted.
- **Prediction intervals, not confidence intervals.** A designer asks where the
  *next* trial will land, so the back-test scores prediction intervals that
  include between-trial heterogeneity, uncertainty in the pooled mean, and the
  new trial's own sampling variance.
- **Absence of evidence is not evidence of absence.** No publication found ≠
  unpublished. No retraction notice ≠ not retracted. Both are stated in the
  output, not just in this README.
- **Descriptive, never accusatory.** A registry-publication difference is
  reported as a difference. A citation to a retracted paper is a timing fact.
  A coauthorship path is a relationship, and whether it is a conflict is the
  editor's decision.

---

## HTTP API

```sh
venv/bin/python main.py
```

| Endpoint | Returns |
|---|---|
| `GET /api/design?condition=&endpoint=&hr=&alpha=&power=` | The full bias-aware design report |
| `GET /api/cohort?condition=&endpoint=` | Cohort composition and linkage counts |
| `POST /api/reviewer-conflict` | Conflict paths with evidence |
| `GET /api/cohorts` | Which cohorts are saved and analyse instantly |
| `GET /api/overview` | Every saved cohort through the same pipeline, with the cross-cohort pattern |
| `GET /api/design?…&recover=1` | The same report, with hazard ratios recovered from open full text |
| `GET /api/candidates?nct=` | The fuzzy cascade for one trial: retrieved, scored, adjudicated |
| `GET /api/search?q=&kind=trial\|work&has_publication=&phases=&sponsor_class=` | Faceted search over the Elasticsearch index |
| `GET /api/llm-ledger` | Every model call made: tokens and dollars by purpose, cache hits, budget |
| `GET /api/sources?doi=&deep=1` | Screen a paper's whole reference list for retractions |
| `GET /api/graph?doi=&depth=1\|2&limit=` | Citation graph, retraction evidence, blast radius |
| `GET /api/demo` · `/api/demo-sources` | Bundled snapshots, for offline demos |
| `GET /api/trial?nct=` · `/api/paper?pmid=` · `/api/compare?nct=&pmid=` | Registered-vs-published comparison |

```sh
curl -X POST localhost:8000/api/reviewer-conflict -H 'Content-Type: application/json' \
  -d '{"candidate_reviewer":"Martin Reck","manuscript_authors":["Tony Mok"],"max_hops":2}'
```

---

## Layout

```
backend/
  sources/            http.py (cache, per-host throttle, retry)
                      clinical_trials.py  registry cohort, posted results
                      pubmed.py           NCT<->publication join
                      openalex.py         scholarly graph
                      europepmc.py        open full text, reduced to HR sentences
  models/             core.py, effects.py, matching.py, comparison.py
  matching/           trial_paper_matcher.py, publication_role.py
  compare/            trial_publication.py    registered-vs-published table
  publication_bias/   cohort.py         step 1  narrow registry cohort
                      linkage.py        steps 3-5  channels, dark matter
                      priors.py         steps 7-8  the two priors
                      publication_model.py  step 6  does publication track results?
                      power.py          step 9   Schoenfeld design consequence
                      sensitivity.py    step 10  unknown-result sweep
                      backtest.py       section 4  leave-one-out validation
                      funnel.py         funnel plot, Egger's test, placement
                      overview.py       every saved cohort, cached by mtime
                      analysis.py       orchestrator
  graph/              coauthors.py, reviewer_conflicts.py
  search/elastic.py   index + retrieval: candidate generation, faceted search
  llm/                client.py (cache, ledger, budget cap), extraction.py, matching.py
  publication_bias/fulltext.py   recover estimates from Europe PMC full text
  config.py           loads .env; accepts a Cloud ID or an endpoint URL
  render.py           terminal report
cli.py                design | cohort | reviewer | trial | paper | compare
static/charts.js      inline-SVG chart primitives (bars, forest, funnel, meter, line)
static/views.js       design, reviewer and trial-comparison views
main.py               HTTP server + static UI
graph.py              citation graph, exposure BFS, blast_radius
retraction_check.py   screen a paper's own reference list
static/               SVG citation graph UI
data/cohorts/         saved cohorts      data/demo.json  saved graph snapshot
Dockerfile            python:3.11-slim, no build step
tests/                154 offline tests, including the executed frontend
```

---

## What is not built

Stated plainly so the gaps are not mistaken for claims:

- **The index holds the analysed cohorts, not the literature.** Elasticsearch
  is populated from the cohorts that have been built (2,123 trials and 2,763
  papers across six disease areas, and every new cohort is indexed as it is
  built). A trial's true paper is only findable by the cascade if it is in the
  index, so candidate search currently mainly *prevents* false links.
- **Full-text recovery is bounded by what Europe PMC will serve.** 43% of the
  eligible papers had open full text and just under half of those returned an
  article; recovery reached 5 of 149 trials. The bottleneck was the fetch, not
  the reduction step: of 97 remembered failures, 97 were fetch errors and none
  was a parse error. Europe PMC was the one host pinned to a single attempt on
  the shared 30-second deadline, and a failure was remembered forever, so one
  slow afternoon removed an article from the corpus permanently. It now gets
  three attempts at a 60-second deadline instead of one at 30, a transient miss
  expires after a week, and only an article Europe PMC says it does not have is
  remembered for good. Because recovery runs inside a request, the whole pass
  is also capped at two minutes and reports where it stopped. The 5-of-149 figure predates that fix
  and has not been re-measured against the live API. Measured over the 58 articles that did come back, 34
  contain no hazard ratio anywhere — single-arm phase I/II studies, plain-
  language summaries and pharmacokinetic papers, none of which can produce one
  — 21 extract cleanly, and 3 mention hazard ratios only in a methods sentence
  carrying no value. The sentence filter itself missed no estimate in that
  sample, though it did leak within papers until the house-style fixes
  described above.
- **Cohort size is capped at 400 trials** per analysis, and a very broad disease
  term will be truncated rather than sampled.
- **The reference screen leans on OpenAlex.** Only entries OpenAlex flags are
  confirmed against Crossref, so an unflagged reference was not individually
  checked. `deep=1` checks every one, at roughly a hundred times the API calls.
- **One disease area, one endpoint class at a time.** Widening this is a cohort
  parameter, not new code, but nothing cross-disease has been validated.
- **Fuzzy matching is not used in cohort construction.** Only the two identifier
  channels run there, which is conservative: it may under-count publications and
  therefore over-state the gap. Turning it on is a one-line change once its
  false-positive rate has been measured.
- **Category C dominates every cohort** (314 of 400 for lung cancer, and more
  elsewhere). Most completed trials post no analyzable hazard ratio at all,
  which limits how much the observable A-vs-B comparison can carry.
- **Funnel asymmetry is not proof of selection.** Egger's test detects
  small-study effects, which have other causes; the tool says so on screen.
  Below ten trials the test is shown but labelled unreliable.
- **Model prices are list prices**, entered as data. If they change, the token
  counts remain exact and the dollar figures need one table updated.
