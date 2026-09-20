# Evidence Atlas

Trace the provenance of clinical evidence. Link registered trials to the papers
that report them, compare what was planned against what was published, and
follow a retracted result through the citation network.

Full product specification: [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md).

---

## Run

```sh
python3 -m venv venv
venv/bin/python -m pip install -r requirements.txt
venv/bin/python main.py
```

Open http://127.0.0.1:8000. The app starts with the bundled real-data snapshot
and works without API access in saved-demo mode. Use `--port 8001` if 8000 is
occupied.

Live lookups need outbound access to OpenAlex, Crossref, ClinicalTrials.gov and
PubMed. Optional environment variables are documented in [.env.example](.env.example);
`.env` files are not loaded automatically. Responses are cached under `.cache/`,
so a second lookup is instant and a demo does not depend on a live network.

### Tests

```sh
venv/bin/python -m unittest discover -s tests -t . -v
```

30 tests, all offline. Citation-graph logic is tested against mocks; the
trial-comparison pipeline runs on saved API payloads in [tests/fixtures/](tests/fixtures/).
An upstream outage cannot break the suite.

---

## What is here

Two capabilities over one provenance graph.

### 1. Citation propagation and retraction tracking — web UI

Enter a DOI, get a sampled citation network, and follow source-linked retraction
evidence. Select any paper to see a shortest citation path back to a retracted
work, one clickable step at a time.

The saved sample starts at `10.1177/1758835920922055` — a real retracted
osteosarcoma paper — with real OpenAlex citation edges and a Crossref notice at
`10.1177/17588359231172420`. All counts describe that bounded sample, not the
whole literature.

Refresh the snapshot before presenting, with internet access:

```sh
venv/bin/python capture_demo.py
```

The script refuses to replace the snapshot if the starting paper's retraction
cannot be confirmed.

### 2. Registered trial vs published paper — CLI and API

```sh
# A trial and every publication the registry links to it, ranked by how much
# of the registered trial each one actually reports.
venv/bin/python cli.py trial NCT02142738

# Start from a paper and find the trial behind it.
venv/bin/python cli.py paper 27718847

# Compare one pair, and show why the two records were linked.
venv/bin/python cli.py compare NCT02506153 36416836 --evidence
```

```
FIELD                                    REGISTERED        PUBLISHED
Registry identifier                      NCT02506153       NCT02506153    match
Enrollment                               1301 (actual)     1303           DIFFERENCE
Interventions                            Biospecimen Col…  Described      match
Masking                                  DOUBLE            --             not identified
Primary outcome: Overall Survival (OS)   Overall Surviva…  --             not identified
```

Each row comes from an explicit rule over registry fields and the publication's
structured abstract, and carries the source spans it was derived from.

---

## HTTP API

| Endpoint | Returns |
|---|---|
| `GET /api/demo` | The bundled citation-graph snapshot |
| `GET /api/graph?doi=&depth=1\|2` | A live citation graph with retraction evidence |
| `GET /api/trial?nct=&limit=` | A trial and its ranked publications |
| `GET /api/paper?pmid=` | A publication and its candidate trials |
| `GET /api/compare?nct=&pmid=` | The full field-by-field comparison table |

The trial endpoints and the CLI are built from the same records in
[backend/report.py](backend/report.py), so the two surfaces cannot drift.

---

## Design rules

- **Deterministic code for facts.** Graph paths, distances and comparison rows
  are computed, not generated. No LLM is used anywhere yet; when one is added it
  is for extraction and explanation only.
- **A citation is not a verdict.** A paper may cite a retracted work in order to
  criticise it. The UI shows connections and says so in as many words.
- **Absence of evidence is not evidence of absence.** Crossref returning no
  notice yields `no_notice_found`, never `not_retracted`; a truncated result set
  downgrades to `unknown` rather than reporting a false negative. Comparison
  evidence comes from abstracts, so `not identified` never means "absent from
  the paper", and the output states that.
- **Differences are differences.** The comparison vocabulary is `match`,
  `difference`, `not identified`, `not registered`, `not comparable`. Nothing
  here calls a discrepancy misconduct — enrollment counts routinely differ
  between enrolled, eligible and analyzed populations.
- **Extracted facts and inferred links never blur.** A trial-paper match carries
  `basis: identifier` when a source declares the link and `basis: inferred` when
  it was computed, along with every signal that produced the score.
- **Provenance on everything.** DOI, PMID, NCT and OpenAlex ids are preserved
  and every claim links back to its source.

---

## How the trial link works

The spec calls trial↔publication matching the hardest problem. Most of it
dissolves with the right source: PubMed records a ClinicalTrials.gov accession
number whenever an article declares one, and the registry lists PMIDs back. So
the common case is an **identifier match**, with no inference at all. When
nothing is declared, [trial_paper_matcher.py](backend/matching/trial_paper_matcher.py)
falls back to weighted metadata signals and labels the result `inferred`.

But a declared identifier proves a paper *concerns* a trial, not that it
*reports* it. Registry reference lists mix primary results, long-term follow-ups,
secondary analyses and passing mentions — all declaring the same id, so ranking
by the identifier alone puts a 2025 LLM-methods paper beside the primary results
paper. [publication_role.py](backend/matching/publication_role.py) separates them
using registered-outcome coverage, investigator overlap, PubMed publication type
and sponsor designation.

Because endpoint names are generic — "overall survival" appears in most oncology
abstracts — a reporting role is only assigned once the link itself is credible.

---

## Layout

```
main.py             HTTP server: static files + JSON API
graph.py            citation graph construction, distance and exposure BFS
openalex.py         citation edges          crossref.py   retraction notices
api_client.py       cached fetch, retry, DOI validation
static/             SVG citation graph UI, no framework
data/demo.json      saved real-data snapshot     capture_demo.py  regenerates it

backend/
  sources/          http.py (cache, throttle, retry)
                    clinical_trials.py, pubmed.py
  models/           core.py, matching.py, comparison.py
  matching/         trial_paper_matcher.py, publication_role.py
  compare/          trial_publication.py   <- the deterministic comparison
  report.py         shared by the CLI and the API
cli.py              terminal surface for the comparison
tests/              offline: mocks for the graph, fixtures for the comparison
legacy_plot.py      superseded matplotlib rendering, kept for reference
```

---

## Known limitations

- **Abstracts only.** No full text, so outcomes reported solely in tables or
  supplements read as `not identified`. Europe PMC full text would fix this.
- **Lexical outcome matching.** Registered names are reduced to their core
  concept before matching, but an endpoint a paper renames entirely is missed.
  This is where the LLM normalization step in section 9 belongs.
- **Enrollment parsing is regex-based.** It reports the abstract count closest
  to the registered figure and quotes the sentence, so a wrong pick is visible.
- **The citation graph is sampled**, not exhaustive — top citing works at the
  first hop, up to four per paper at the second.
- **No "cited after retraction" metric yet.** Node dates and notice dates are
  both already in the payload, so this is a small addition.
- **The trial comparison has no UI yet** — it is CLI and API only.

## Next

1. Surface the trial comparison as a third tab in the web UI.
2. Add the "published after the retraction date" metric to the graph.
3. Feature 3: coauthorship graph and reviewer conflict paths.
