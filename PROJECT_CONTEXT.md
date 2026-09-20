# PROJECT_CONTEXT.md

## Project Working Title
**Scientific Provenance Graph for Clinical Research**

Alternative names:
- TrialTrace
- EvidenceGraph
- ClinGraph
- ProvenanceRx
- TrialLineage

## One-Sentence Pitch
Build a scientific provenance graph that links registered clinical trials to published results, traces how retracted or corrected work propagates through citation networks, and exposes researcher relationships such as reviewer conflicts.

---

# 1. Problem

Clinical researchers, biostatisticians, wet-lab scientists, editors, and reviewers often need to answer questions that are currently fragmented across many systems:

1. **What experiment was originally registered?**
2. **What was eventually published?**
3. **Did the published endpoints, enrollment, timing, or analyses differ from what was registered?**
4. **Did a paper rely on evidence that was later corrected or retracted?**
5. **How far has a questionable result propagated through the citation graph?**
6. **Is a candidate reviewer connected to the manuscript authors through prior coauthorship or institutional relationships?**
7. **Can we show the exact path creating that conflict rather than giving an opaque “conflict score”?**

Today, users often inspect registries, papers, citation networks, retraction notices, and author histories separately.

The product should unify these into a single evidence/provenance graph.

---

# 2. Product Thesis

The core product is **not three unrelated features**.

The core object is a **scientific knowledge/provenance graph**.

Nodes may include:
- Clinical trials
- Publications
- Authors
- Institutions
- Retraction/correction notices
- Diseases
- Drugs/interventions
- Outcomes/endpoints

Edges may include:
- `RESULT_OF_TRIAL`
- `CITES`
- `AUTHORED_BY`
- `COAUTHORED_WITH`
- `AFFILIATED_WITH`
- `RETRACTED_BY`
- `CORRECTED_BY`
- `STUDIES`
- `USES_INTERVENTION`

Once this graph exists, multiple workflows become possible.

---

# 3. Primary User Workflow

The main user is a:
- biostatistician,
- clinical researcher,
- wet-lab scientist,
- research-integrity analyst,
- journal editor,
- or peer-review coordinator.

## Main workflow

User searches a topic, intervention, disease, trial ID, DOI, or paper.

Example:

> pembrolizumab melanoma

System returns:
- related registered trials,
- linked publications,
- trial-to-publication comparison,
- citation graph,
- retraction/correction status,
- related authors,
- possible reviewer conflicts.

The product should answer:

> “What happened to this line of research, and can I trace the evidence behind it?”

---

# 4. MVP Feature 1 — Registered Trial vs Published Paper

This is the **primary MVP feature**.

Given a clinical trial and a publication that appears to report its results:

1. Extract important fields from the trial registration.
2. Extract corresponding fields from the publication.
3. Compare them deterministically.
4. Surface differences.
5. Link each claim back to source evidence.

Potential comparison fields:

- ClinicalTrials.gov identifier / NCT ID
- Primary outcome
- Secondary outcomes
- Enrollment
- Intervention
- Comparator
- Inclusion/exclusion criteria
- Study design
- Number of arms
- Blinding
- Randomization
- Outcome time frames
- Analysis population
- Completion status
- Study dates
- Reported adverse events

Example UI:

| Field | Registered | Published | Status |
|---|---|---|---|
| Enrollment | 500 | 327 analyzed | Difference |
| Primary endpoint | Tumor progression at 12 months | Tumor progression at 6 months | Difference |
| Overall survival | Secondary outcome | Not found | Missing |
| Adverse events | Planned | Reported | Match |

Important product principle:

**Do not automatically label differences as misconduct.**

The tool should say:
- “These fields differ.”
- “This registered outcome was not identified in the publication.”
- “This publication reports an analysis not found in the registration.”

It should not say:
- “This study is fraudulent.”
- “The authors manipulated the trial.”

unless the source itself explicitly establishes such a conclusion.

---

# 5. MVP Feature 2 — Citation Propagation + Retraction Tracking

Given a paper:

1. Build its citation neighborhood.
2. Determine whether it has been:
   - retracted,
   - corrected,
   - withdrawn,
   - or otherwise updated.
3. Identify papers that cite it directly.
4. Optionally identify downstream descendants.
5. Visualize propagation.

Example:

```text
                 RETRACTED PAPER
                 /      |      \
                ↓       ↓       ↓
             Paper B  Paper C  Paper D
                ↓                ↓
             Paper E          Paper F
                ↓
             Paper G
```

Desired display:

- Retracted paper: red
- Direct citers: orange
- Downstream descendants: yellow
- Unaffected/other nodes: neutral

Useful metrics:
- number of direct citations,
- number of downstream descendants,
- earliest/latest downstream citation,
- number of downstream papers published after the retraction date,
- paths from retracted paper to selected descendant.

Important distinction:
A citation to a retracted work is **not automatically invalid**. A paper may cite the retraction itself or discuss the work critically.

Therefore:
- graph structure should be factual,
- LLM explanations should preserve uncertainty,
- do not automatically call every descendant “compromised.”

---

# 6. MVP Feature 3 — Reviewer Conflict Graph

Given:

- manuscript authors,
- candidate reviewer,

return:

1. graph distance between reviewer and each manuscript author,
2. every relevant path up to a configurable depth,
3. evidence for each path,
4. relationship types and dates where possible.

Example:

```text
Reviewer X
   ↓ coauthored_with
Researcher Y
   ↓ coauthored_with
Manuscript Author Z
```

Output:

> Distance: 2  
> Reviewer X coauthored with Researcher Y.  
> Researcher Y coauthored with manuscript author Z.

Possible relationship types:
- direct coauthorship,
- coauthor-of-coauthor,
- same institution,
- prior institution,
- shared grants if data exists,
- prior reviewing/editorial relationship if public data exists.

For MVP, **coauthorship is enough**.

Important design principle:

Do not return only:

> conflict score = 0.73

Instead return:
- exact graph paths,
- why each path exists,
- source evidence.

The human editor decides whether that path constitutes a conflict.

---

# 7. Data Sources

Preferred public data sources:

## ClinicalTrials.gov
Use for:
- trial metadata,
- interventions,
- outcomes,
- study design,
- enrollment,
- dates,
- status,
- sponsors,
- results when available.

## PubMed / NCBI
Use for:
- biomedical paper metadata,
- abstracts,
- authors,
- identifiers,
- publication details.

## OpenAlex
Use heavily for:
- papers,
- authors,
- institutions,
- citations,
- coauthorship,
- scholarly graph construction.

This is especially useful because OpenAlex is part of the Voloridge public-dataset challenge list.

## Crossref
Use for:
- DOI metadata,
- citation metadata,
- publication relations,
- retractions/corrections where available.

## Retraction Watch / Crossref-integrated retraction data
Use for:
- retracted publications,
- correction/retraction metadata.

Potential later sources:
- Semantic Scholar
- Europe PMC
- ORCID
- FDA / EMA public documents
- bioRxiv / medRxiv
- journal APIs

Do not depend on too many sources for MVP.

---

# 8. Hardest Technical Problem — Trial ↔ Publication Matching

The hardest part is likely not graph traversal.

It is:

> Which publication corresponds to which registered clinical trial?

## Easy case
Publication contains a trial identifier such as:

```text
NCT01234567
```

Then create:

```text
Trial NCT01234567
    RESULT_OF_TRIAL
Publication DOI:...
```

## Ambiguous case
No explicit trial identifier.

Candidate matching signals:
- overlapping investigators/authors,
- same disease,
- same intervention,
- same sponsor,
- similar enrollment,
- compatible study dates,
- same number of arms,
- similar study design,
- institution overlap,
- endpoint similarity.

Potential matching strategy:

```text
score =
    exact NCT identifier              very high
    investigator overlap             high
    intervention match               high
    disease match                    medium/high
    enrollment similarity            medium
    study date compatibility         medium
    endpoint similarity              medium
    institution overlap              low/medium
```

Use deterministic rules first.

Use an LLM only for ambiguous cases or structured semantic comparison.

Every match should have:
- confidence,
- reasons,
- evidence,
- provenance.

---

# 9. AI Responsibilities

AI should be used where language understanding is needed.

Good uses of an LLM:
- extract structured endpoints from trial/publication text,
- normalize differently worded outcomes,
- identify likely trial-publication matches,
- summarize differences,
- explain graph paths,
- generate concise evidence-backed research summaries,
- categorize citation context if time permits.

Bad uses:
- asking the LLM to invent graph paths,
- asking the LLM whether two authors collaborated when graph data can answer exactly,
- letting the LLM independently declare misconduct,
- using the LLM for deterministic field comparisons.

Rule:

> **Graph/database for facts. LLM for extraction, semantic matching, and explanation.**

---

# 10. Suggested Tech Stack

## Frontend
- Next.js
- React
- TypeScript
- Tailwind CSS

## Graph Visualization
Choose one:
- Cytoscape.js
- React Flow

Cytoscape.js may be preferable for graph-heavy analysis.

## Backend
Recommended:
- Python
- FastAPI

Reason:
- easy scientific/data tooling,
- good support for pandas and graph processing,
- familiar ML ecosystem.

Next.js API routes can still be used for small frontend/server actions.

## Graph Algorithms
- NetworkX

Start here.

Do **not** introduce Neo4j until necessary.

NetworkX can handle:
- shortest paths,
- all simple paths,
- neighborhoods,
- descendants,
- connected components,
- graph construction.

## Search
- Elasticsearch

Use for:
- paper search,
- trial search,
- fuzzy text retrieval,
- semantic search / embeddings,
- sponsor challenge eligibility.

## Database
- Supabase / PostgreSQL

Store:
- normalized papers,
- trial records,
- graph edges,
- cached API responses,
- user searches,
- extracted fields,
- match scores,
- provenance.

## AI
- OpenAI API

Potential uses:
- structured extraction,
- semantic normalization,
- ambiguous matching,
- evidence explanations.

## Deployment
- Vercel for frontend
- Railway / Render / Fly.io for FastAPI backend

## Development
- GitHub
- Codex
- Devin if pursuing the Cognition challenge

---

# 11. Suggested Architecture

```text
ClinicalTrials.gov
PubMed
OpenAlex
Crossref
Retraction data
       |
       v
DATA INGESTION + NORMALIZATION
       |
       +----------------------+
       |                      |
       v                      v
 PostgreSQL / Supabase    Elasticsearch
       |                      |
       +----------+-----------+
                  |
                  v
            GRAPH BUILDER
              NetworkX
                  |
        +---------+---------+
        |         |         |
        v         v         v
Trial/Paper   Citation   Reviewer
Comparison    Graph      Conflict
        \         |         /
         \        |        /
          +-------+-------+
                  |
                  v
             OpenAI API
   extraction / matching / explanation
                  |
                  v
             Next.js UI
```

---

# 12. Proposed Data Model

## Paper

```json
{
  "id": "doi:...",
  "doi": "...",
  "title": "...",
  "abstract": "...",
  "publication_date": "...",
  "journal": "...",
  "authors": [],
  "citation_count": 0,
  "is_retracted": false
}
```

## Trial

```json
{
  "id": "NCT01234567",
  "title": "...",
  "conditions": [],
  "interventions": [],
  "primary_outcomes": [],
  "secondary_outcomes": [],
  "enrollment": 500,
  "start_date": "...",
  "completion_date": "...",
  "status": "...",
  "investigators": []
}
```

## Author

```json
{
  "id": "openalex-author-id",
  "name": "...",
  "orcid": "...",
  "institutions": []
}
```

## Edge

```json
{
  "source": "...",
  "target": "...",
  "type": "CITES",
  "metadata": {}
}
```

Possible edge types:
- `CITES`
- `AUTHORED_BY`
- `RESULT_OF_TRIAL`
- `COAUTHORED_WITH`
- `AFFILIATED_WITH`
- `RETRACTED_BY`

---

# 13. Suggested UI

## Homepage

One prominent search bar:

> Search a trial, paper, disease, drug, DOI, NCT ID, or researcher

Examples:
- `NCT01234567`
- `pembrolizumab melanoma`
- DOI
- paper title

## Result page

Three main tabs.

### Tab 1 — Trial vs Publication

Show:
- matched trial,
- matched paper,
- match confidence,
- field-by-field comparison,
- source links,
- warnings/differences.

### Tab 2 — Evidence Graph

Interactive citation graph.

Controls:
- depth,
- direct citations only,
- show retractions,
- show corrections,
- publication date filter.

### Tab 3 — People / Reviewer Check

Inputs:
- manuscript DOI or author list,
- reviewer name / ORCID / OpenAlex ID.

Output:
- direct conflicts,
- path distances,
- graph visualization,
- paths with dates and citations.

---

# 14. Demo Story

The demo should tell **one story**, not show random features.

Possible sequence:

1. Search a real clinical trial or intervention.
2. Show registered design.
3. Show matched publication.
4. Highlight one or more differences.
5. Click “Trace Evidence.”
6. Expand citation network.
7. Reveal that one relevant paper was retracted/corrected.
8. Show the downstream citation propagation.
9. Switch to reviewer check.
10. Enter a candidate reviewer.
11. Show exact relationship path to a manuscript author.

Goal:

Audience should understand that the SAME graph powers all three capabilities.

---

# 15. Sponsor Challenges

These sponsor descriptions are based on the HackMIT sponsor challenge list provided by the team.

## Regeneron — PRIMARY TARGET

Challenge theme:
**Help Patients: Make Clinical Trials and Biostatistics Better**

They want open-source solutions that solve bottlenecks in:
- planning,
- conducting,
- analyzing,
- or submitting clinical trials.

They care about:
- utility/relevance,
- functional readiness,
- reproducibility,
- intuitive design,
- documentation/demo.

Why this project fits:
- directly helps inspect clinical-trial evidence,
- helps biostatisticians/researchers understand registered vs published results,
- supports research integrity,
- can be open source,
- operates directly on clinical-research workflows.

This should be the anchor sponsor challenge.

---

## Voloridge — STRONG SECONDARY TARGET

Challenge:
**Signal in the Noise**

They want projects using real-world public datasets that:
- uncover useful patterns,
- clean/enrich messy data,
- build visualizations,
- create novel search/exploration tools,
- train models,
- combine datasets,
- process large datasets.

They provide OpenAlex among their suggested datasets.

Why this project fits:
- combines multiple public research datasets,
- uses OpenAlex directly,
- builds citation/coauthorship graphs,
- extracts structure from messy research data,
- discovers relationships between trials, publications, authors, and retractions,
- provides interactive graph exploration.

---

## Elastic — STRONG SECONDARY TARGET

Challenge:
**Find the Signal**

Best use of Elasticsearch to turn complex, messy data into:
- insights,
- answers,
- or actions.

Why this project fits:
- biomedical literature is large and messy,
- trials and publications need cross-source retrieval,
- Elasticsearch can power:
  - paper search,
  - trial search,
  - semantic matching,
  - evidence retrieval,
  - related-document discovery.

Elastic should be used meaningfully, not added just for eligibility.

---

## OpenAI — STRONG SECONDARY TARGET

Challenge:
Use the OpenAI API to build something ambitious, and use Codex meaningfully as a development teammate.

Judging includes:
- creative/effective API use,
- meaningful Codex use during planning/building/testing/debugging,
- polished demo,
- showing one concrete way Codex improved development.

Why this project fits:
OpenAI can power:
- structured extraction,
- semantic endpoint normalization,
- ambiguous trial-paper matching,
- explanation of discrepancies,
- graph-path explanations.

Codex should also be used to:
- build integrations,
- write tests,
- generate API clients,
- debug matching logic,
- improve UI,
- create evaluation fixtures.

Document at least one concrete Codex contribution for the final demo.

---

## Cognition / Devin — POSSIBLE SECONDARY TARGET

Challenge:
**Best Use of Devin**

They reward:
- creativity,
- novelty,
- polish,
- ambitious projects enabled by Devin.

If entering:
use Devin for a real portion of the build, such as:
- one API integration,
- automated test generation,
- frontend graph component,
- data normalization pipeline,
- deployment/debugging.

Do not claim meaningful Devin usage unless it actually happened.

---

## The Token Company — POSSIBLE SECONDARY TARGET

Challenge:
Reduce LLM costs inside the product.

They care about:
- smaller prompts,
- cheaper models,
- caching,
- compression,
- denser outputs,
- creative token savings.

Potential fit:
scientific papers and trial records are long.

Possible optimization:
1. retrieve only relevant sections,
2. cache extracted structured fields,
3. never repeatedly send full documents,
4. compress graph neighborhoods into structured records,
5. compare token usage before/after optimization.

Useful metric:

```text
baseline tokens per comparison
vs.
optimized tokens per comparison
```

Only pursue this if measurable.

---

## Dropbox — WEAK/POSSIBLE EXTENSION

Their challenge focuses on turning digital content into organized/actionable knowledge.

Possible extension:
allow researchers to upload:
- protocols,
- PDFs,
- notes,
- manuscripts,
and integrate them into the provenance graph.

Not required for MVP.

---

## Deepgram / ElevenLabs — OPTIONAL

Voice is not core.

Potential demo extension:
researcher asks:

> “Show me every trial publication where the primary endpoint changed.”

Voice agent speaks/explains the graph.

Only add if core product is finished.

---

## Arrowstreet Capital — NOT A NATURAL SUBMISSION WITHOUT EXTRA WORK

Their challenge specifically asks for AI analysis of corporate greenwashing claims.

Our architecture is transferable, but the current clinical-research product does not directly satisfy the requested use case.

Do not submit unless we explicitly implement the greenwashing workflow.

---

# 16. Sponsor Strategy

Do NOT optimize for maximum sponsor count.

Prioritize:

1. **Regeneron**
2. **Voloridge**
3. **Elastic**
4. **OpenAI**

Then, if implementation naturally supports them:

5. Cognition / Devin
6. Token Company

Optional later:
- Dropbox
- voice sponsors

The product should remain coherent even if sponsor names are removed.

---

# 17. Build Priorities

## P0 — MUST WORK

- Search by NCT ID / DOI / paper title.
- Fetch a trial.
- Fetch a publication.
- Link at least one real trial to at least one real paper.
- Extract structured comparison fields.
- Show registered vs published comparison.
- Build a small citation graph.
- Show retraction status if available.
- Render graph in UI.
- Show source links/provenance.

## P1 — HIGH VALUE

- automatic trial-publication matching,
- OpenAlex citation expansion,
- author/coauthor graph,
- reviewer conflict path search,
- Elasticsearch search,
- discrepancy explanations using OpenAI.

## P2 — IF TIME

- downstream retraction propagation,
- publication-after-retraction metric,
- richer endpoint normalization,
- multi-hop reviewer conflict display,
- filters,
- graph timelines,
- cached LLM extraction,
- token optimization metrics.

## P3 — ONLY AFTER CORE DEMO IS SOLID

- voice,
- Dropbox ingestion,
- Neo4j,
- autonomous agents,
- complicated authentication,
- large-scale background processing,
- fancy dashboards.

---

# 18. Suggested Build Order

## Phase 1 — One happy path

Hardcode / manually choose:
- one trial,
- one matched publication.

Build:
- data fetch,
- normalization,
- comparison UI.

This validates the product.

## Phase 2 — Citation graph

For that publication:
- retrieve citations,
- build NetworkX graph,
- show visualization.

## Phase 3 — Retraction metadata

Add:
- retraction/correction lookup,
- node status,
- visual highlighting.

## Phase 4 — Reviewer graph

Add:
- paper authors,
- coauthor graph,
- shortest/all relevant paths.

## Phase 5 — Search

Add:
- Elasticsearch,
- topic search,
- richer retrieval.

## Phase 6 — AI

Add OpenAI only where useful:
- extraction,
- normalization,
- fuzzy matching,
- explanations.

## Phase 7 — Polish

- clean UI,
- loading states,
- citations,
- error handling,
- demo dataset,
- README,
- tests.

---

# 19. Reliability / Scientific Integrity Requirements

This product deals with biomedical research.

Therefore:

1. Every important factual output should preserve provenance.
2. Keep source IDs such as:
   - DOI,
   - PMID,
   - NCT ID,
   - OpenAlex IDs.
3. Distinguish:
   - extracted facts,
   - inferred matches,
   - LLM-generated explanations.
4. Show confidence for fuzzy matching.
5. Never fabricate missing paper/trial fields.
6. Never treat an LLM answer as primary evidence.
7. Do not accuse researchers of misconduct from a mismatch alone.
8. A citation to a retracted paper does not imply endorsement.
9. Reviewer conflict paths should be descriptive, not a final ethical judgment.
10. Where dates matter, store relationship/publication dates.

---

# 20. Coding Principles for Codex

When implementing:

- Prefer the smallest working architecture.
- Do not introduce infrastructure unless required.
- Keep API integrations modular.
- Cache external API responses.
- Use typed schemas for normalized objects.
- Write adapters around external sources.
- Separate deterministic logic from LLM logic.
- Preserve raw source IDs and provenance.
- Add fixtures for offline testing.
- Mock external APIs in unit tests.
- Use environment variables for API keys.
- Never commit secrets.
- Add graceful fallbacks if one external API fails.
- Make the demo path reliable even if external services are slow.

Suggested modules:

```text
backend/
  sources/
    clinical_trials.py
    pubmed.py
    openalex.py
    crossref.py

  models/
    trial.py
    paper.py
    author.py
    edges.py

  matching/
    trial_paper_matcher.py
    outcome_normalizer.py

  graph/
    citation_graph.py
    coauthor_graph.py
    conflicts.py

  llm/
    extraction.py
    explanation.py

  api/
    routes.py

frontend/
  components/
    TrialComparison.tsx
    CitationGraph.tsx
    ReviewerConflict.tsx
    SearchBar.tsx
    EvidenceCard.tsx
```

---

# 21. Definition of Success

A strong hackathon demo should be able to show:

1. A real trial.
2. A real related publication.
3. At least one useful registered-vs-published comparison.
4. A real citation network.
5. A retraction/correction state if possible.
6. A real researcher/coauthorship path.
7. An interactive and understandable UI.
8. Source provenance.
9. AI used for something language-heavy rather than as decoration.
10. A coherent explanation of why this helps clinical research.

The audience should leave with:

> “This lets me trace the provenance of clinical evidence rather than manually jumping between registries, papers, citations, and author histories.”

---

# 22. Current Product Summary for Codex

When making implementation decisions, optimize for this product:

> A web application for exploring the provenance of clinical scientific evidence. It links clinical trial registrations with publications, compares what was planned with what was reported, visualizes citation/retraction propagation, and finds explainable coauthorship paths between manuscript authors and candidate reviewers.

Primary users:
- biostatisticians,
- clinical researchers,
- wet-lab scientists,
- journal editors,
- research-integrity teams.

Primary sponsor target:
- Regeneron

Strong secondary sponsor targets:
- Voloridge
- Elastic
- OpenAI

Potential additional targets:
- Cognition / Devin
- The Token Company

The core technical object is:
**a provenance-aware scientific knowledge graph.**

The core UX rule is:
**show evidence and paths, not opaque scores.**

The core implementation rule is:
**use deterministic code for facts/graph operations and LLMs for extraction, semantic normalization, ambiguous matching, and explanation.**
