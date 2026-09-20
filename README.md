# TrialTrace

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
  statistically significant                92%   (n=39)
  not significant                          62%   (n=45)

  favours treatment                        85%   (n=61)
  favours control                          52%   (n=23)
```

Trials that worked are far more likely to be findable in the literature. That
shifts the pooled effect estimate:

```
  PRIOR                     HR          95% CI      TRIALS
  Literature-only        0.761   (0.712, 0.814)         64
  Registry-aware         0.796   (0.752, 0.843)         84
```

And that shift has a design consequence:

```
  BASIS                            HR    EVENTS   POWER DELIVERED
  Your assumption                0.65       170               80%
  Published-literature estimate  0.76       422               43%
  Registry-aware estimate        0.80       606               32%
```

Leave-one-out back-test over the 84 trials with usable hazard ratios:

```
  MODEL                  COVERAGE   MAE log(HR)     BIAS
  Literature-only             81%         0.278   -0.036
  Registry-aware              79%         0.267   +0.010
```

Both models are well calibrated. The difference is in **bias**: the
literature-only model systematically predicts a stronger effect than held-out
trials actually delivered, while the registry-aware model is close to unbiased.
That direction is exactly what publication selection predicts.

---

## Run

```sh
python3 -m venv venv
venv/bin/python -m pip install -r requirements.txt
```

### Hero feature — bias-aware trial design

```sh
venv/bin/python cli.py design --condition "non-small cell lung cancer" \
    --endpoint pfs --hr 0.65 --power 0.80
```

First run builds the cohort from live APIs and takes about 4 minutes; every
response is cached, so later runs are seconds. `--save` writes the cohort to
`data/cohorts/`.

### Research integrity — retraction blast radius

```sh
venv/bin/python main.py       # then open http://127.0.0.1:8000
```

Enter a DOI, get a sampled citation network with source-linked retraction
evidence and a shortest path from any paper back to the retracted work.

### Reviewer conflict check

```sh
venv/bin/python cli.py reviewer --reviewer "Martin Reck" \
    --authors "Tony Mok" --max-hops 2 --since-year 2020
```

### Tests

```sh
venv/bin/python -m unittest discover -s tests -t . -v
```

63 tests, all offline. The statistics are checked against closed-form values
(Schoenfeld event counts, DerSimonian-Laird pooling) and against synthetic data
with a known answer, so a regression in the maths fails a test rather than
producing a plausible-looking number.

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

### Linking trials to publications

Three channels, most authoritative first, because a false "unpublished" verdict
is the most damaging error this system can make:

1. `nct_registry_reference` — the registry lists a PMID.
2. `nct_pubmed_si` — PubMed indexes the NCT id as a secondary source id. This
   catches publications the registry never listed.
3. `fuzzy` — deterministic metadata scoring (investigator overlap, intervention,
   condition, enrollment, dates, sponsor), used only when neither identifier
   channel returns anything.

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

- **Databases, graphs and statistics for facts; LLMs for language.** No language
  model is used anywhere in this codebase yet. Every number is a query, a graph
  traversal, or a statistical model.
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
| `GET /api/graph?doi=&depth=1\|2` | Citation graph, retraction evidence, blast radius |
| `GET /api/demo` | Bundled citation-graph snapshot |
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
                      analysis.py       orchestrator
  graph/              coauthors.py, reviewer_conflicts.py
  render.py           terminal report
cli.py                design | cohort | reviewer | trial | paper | compare
main.py               HTTP server + static UI
graph.py              citation graph, exposure BFS, blast_radius
static/               SVG citation graph UI
data/cohorts/         saved cohorts      data/demo.json  saved graph snapshot
tests/                63 offline tests
```

---

## What is not built

Stated plainly so the gaps are not mistaken for claims:

- **No Elasticsearch.** Candidate retrieval for fuzzy matching currently uses
  the registry and PubMed directly. The fuzzy scorer exists and is tested; it is
  the retrieval layer in front of it that is missing.
- **No LLM adjudication.** The middle-confidence branch of the matching cascade
  falls through to "no link identified" rather than to a cheap model.
- **No web UI for the hero feature.** Bias-aware design is CLI and API only; the
  browser UI covers the citation/retraction graph.
- **One disease area, one endpoint class at a time.** Widening this is a cohort
  parameter, not new code, but nothing cross-disease has been validated.
- **Fuzzy matching is not used in cohort construction.** Only the two identifier
  channels run there, which is conservative: it may under-count publications and
  therefore over-state the gap. Turning it on is a one-line change once its
  false-positive rate has been measured.
- **Category C dominates this cohort** (316 of 400). Most completed trials post
  no analyzable hazard ratio at all, which limits how much the observable A-vs-B
  comparison can carry.
