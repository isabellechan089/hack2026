# PROJECT_CONTEXT.md

## Project Working Title
**TrialTrace / EvidenceGraph**

Alternative names:
- TrialTrace
- EvidenceGraph
- ClinGraph
- TrialLineage
- ProvenanceRx

## One-Sentence Pitch
Build a registry-aware clinical trial design tool that measures publication bias by linking registered trials to published literature, corrects effect-size assumptions used in power calculations, and reuses the same OpenAlex graph for retraction propagation and reviewer-conflict analysis.

---

# 1. Core Thesis

The central insight is:

> **The effect sizes people use to design clinical trials come from published literature, but published literature is missing some of the trials that were registered and completed.**

The product combines two datasets that correct each other rather than merely displaying them side-by-side:

1. **ClinicalTrials.gov / AACT** gives the universe of registered trials, including completed trials that may never have been published.
2. **OpenAlex** gives the published scholarly record: papers, authors, institutions, citations, and coauthorship.

The set difference between completed registered trials and identifiable publications is the key signal.

The main product should estimate how publication selection changes the apparent effect size for a class of interventions, then feed that correction into trial-design calculations.

The graph infrastructure also naturally supports two secondary research-integrity tools:
- retraction blast-radius analysis,
- reviewer conflict-path analysis.

These are not separate products. They are alternate analyses over the same scholarly graph.

---

# 2. Primary Users

Primary:
- biostatisticians,
- clinical-trial designers,
- clinical researchers,
- wet-lab scientists planning translational studies.

Secondary:
- journal editors,
- research-integrity analysts,
- peer-review coordinators,
- meta-researchers.

The main user story is:

> “I am designing a trial. The published literature suggests an effect size of X. How much should I trust that number once I account for comparable completed trials that were registered but not clearly published?”

---

# 3. Hero Feature — Bias-Aware Trial Design

This is the main hackathon product and should receive most implementation effort.

## Pipeline

### Step 1 — Build the registry cohort

Pull trial records from ClinicalTrials.gov or AACT.

For the hackathon, intentionally narrow the statistical domain. Recommended first scope:

> **Randomized phase II/III oncology drug trials with time-to-event outcomes such as overall survival or progression-free survival reported as hazard ratios.**

Do not attempt to combine unrelated effect measures such as hazard ratios, odds ratios, response rates, blood pressure changes, and arbitrary continuous endpoints into one prior.

Useful trial fields:
- NCT ID,
- phase,
- condition,
- intervention,
- comparator,
- sponsor / sponsor type,
- enrollment,
- start/completion dates,
- recruitment status,
- primary outcomes,
- secondary outcomes,
- posted registry results,
- effect estimate where available.

### Step 2 — Pull the published record from OpenAlex

OpenAlex is the primary scholarly dataset.

Use it for:
- works,
- abstracts,
- authors,
- institutions,
- citations,
- coauthorship,
- publication years,
- DOI/OpenAlex IDs.

The key join is:

```text
TRIAL (NCT ID)
        |
        | MATCHED_TO
        v
OPENALEX WORK
```

### Step 3 — Trial → publication matching

This is one of the most important technical components.

#### Easy case: exact NCT identifier

If a paper contains the NCT ID, match directly.

Store:
- `nct_id`,
- `openalex_id`,
- `match_method = nct_exact`,
- `confidence = 1.0`.

#### Hard case: fuzzy matching

For trials without an explicit identifier, retrieve candidate papers using:
- intervention,
- condition,
- investigator / author overlap,
- sponsor,
- enrollment similarity,
- trial-completion/publication-year compatibility,
- endpoint similarity,
- institution overlap.

Suggested pipeline:

```text
Exact NCT match?
    |
    +-- yes --> accept match
    |
    +-- no
         |
         v
candidate retrieval with Elastic/OpenAlex
         |
         v
deterministic feature scoring
         |
    +----+----+
    |         |
 high       low
    |         |
 accept    reject

middle-confidence cases
         |
         v
cheap LLM / semantic adjudication
         |
         v
manual-review flag if still ambiguous
```

Do not use the LLM to fabricate a match. Every accepted match must preserve evidence and feature scores.

Suggested table:

```text
trial_publication_matches
- nct_id
- openalex_id
- match_method
- match_score
- nct_exact
- intervention_score
- condition_score
- author_overlap
- enrollment_score
- date_score
- sponsor_score
- outcome_score
- llm_used
- verified
```

### Step 4 — Identify publication dark matter

For an eligible completed-trial cohort:

```text
completed trials
minus
trials with an identified publication
=
trials with no corresponding publication identified
```

Use cautious language. Prefer:

> “No corresponding publication identified.”

Do not automatically label every unmatched trial as definitively unpublished, because matching has false negatives.

Compute publication-linkage rates by:
- phase,
- sponsor type,
- intervention class,
- condition,
- result direction,
- statistical significance if available,
- year.

### Step 5 — Separate observable from truly missing results

For bias analysis, distinguish:

```text
A. Published trial + registry result
B. No publication identified + registry result
C. No publication identified + no usable registry result
```

A vs B gives an observable test for publication selection.

C remains genuinely missing and should be handled through sensitivity analysis rather than silently imputed.

### Step 6 — Test whether publication probability relates to results

Do not assume unpublished trials are null. Test it.

Possible simple model:

```text
publication ~ effect direction / magnitude
            + phase
            + sponsor type
            + enrollment
            + year
```

For a coherent effect scale, transform hazard ratios via:

```text
log(HR)
```

This lets trials live on a comparable additive scale.

### Step 7 — Build a naive literature-only prior

Given a proposed trial:
- retrieve comparable published trials,
- extract their effect sizes,
- estimate a literature-only prior.

Conceptually:

```text
published comparable trials
        |
        v
estimated effect distribution
        |
        v
naive design prior
```

### Step 8 — Build a registry-aware prior

Add eligible registry-only trials with usable posted results.

Compare:

```text
literature-only prior
vs
registry-aware prior
```

The expected insight is that the registry-aware estimate may move toward the null if publication selection favors stronger effects — but the system must measure this rather than assume it.

### Step 9 — Feed the correction into power/design calculations

Example user input:

```text
Assumed HR = 0.65
Power = 80%
alpha = 0.05
```

Tool output should compare:

```text
User assumption
Published-literature estimate
Registry-aware estimate
```

Then estimate what happens to:
- actual power,
- required event count,
- required sample size,
- uncertainty.

The core value proposition is:

> “Your effect-size assumption comes from a literature where comparable completed trials are missing from publication. Here is how your design changes after accounting for the observable missingness.”

### Step 10 — Sensitivity analysis for truly missing studies

For category C — no publication and no registry result — do not hard-code a null effect.

Instead expose an assumption/sensitivity control.

Example:

```text
Assumed average effect among trials with unknown results
HR 0.80  <---- slider ---->  HR 1.10
```

Recalculate required power/sample size under those assumptions.

This is more scientifically defensible than pretending the missing result is known.

---

# 4. Evaluation — Back-Testing

The strongest technical validation is out-of-sample back-testing.

Procedure:

1. Select completed trials with known registry outcomes.
2. Hold one trial out.
3. Pretend it is a future proposed trial.
4. Estimate its expected effect using:
   - Model A: published literature only,
   - Model B: registry-aware evidence.
5. Reveal the held-out trial's result.
6. Repeat.

Useful metrics:
- prediction interval coverage,
- mean absolute error on `log(HR)`,
- calibration,
- bias,
- required-sample-size error if mapped into design decisions.

Judge-friendly result:

```text
Expected 80% prediction interval

Literature-only model:
actual held-out coverage = X%

Registry-aware model:
actual held-out coverage = Y%
```

If registry-aware evidence improves calibration or coverage, that is the core Voloridge result.

---

# 5. Secondary Feature — Retraction Blast Radius

This is already being implemented / scoped and should remain a secondary demonstration of the same OpenAlex graph.

Given a retracted work:
- find direct citers,
- find downstream citation descendants,
- identify citations that occurred after the retraction date,
- calculate downstream citation mass,
- optionally weight descendants by their own citation counts.

Possible metrics:
- direct citation count,
- downstream descendant count,
- citations after retraction,
- weighted downstream citation mass,
- field-level contamination/risk summaries.

Important interpretation rule:

A citation to a retracted paper is not automatically invalid or endorsing. The tool should describe graph structure and timing, not accuse downstream authors.

Optional extension:
flag currently unretracted papers that have structural patterns similar to known retracted papers, such as:
- unusually concentrated author clusters,
- suspicious citation velocity,
- venue-pattern similarity.

Present any such output as a **risk/triage score**, never as an accusation or factual claim of misconduct.

---

# 6. Secondary Feature — Reviewer Conflict Graph

Use OpenAlex's author/work graph to expose explainable reviewer relationships.

Input:
- manuscript authors,
- candidate reviewer,
- optional time window,
- maximum hop count.

Output:
- minimum graph distance,
- every relevant path up to cutoff,
- relationship evidence,
- dates,
- shared works / DOI / OpenAlex IDs.

Example:

```text
Candidate Reviewer
    |
    | coauthored with
    v
Researcher Y
    |
    | coauthored with
    v
Manuscript Author
```

Do not return only an opaque score such as `0.73`.

Return the exact path and let the editor apply journal policy.

Recommended relationship metadata:
- first collaboration year,
- most recent collaboration year,
- number of shared works,
- work IDs / DOIs,
- institution overlap where available.

MVP relationship type:
- coauthorship.

Possible later types:
- same institution,
- recent institutional overlap,
- shared grants if public data exists.

Example endpoint:

```http
POST /reviewer-conflict
```

Input:

```json
{
  "manuscript_authors": ["A123", "A456"],
  "candidate_reviewer": "A999",
  "max_hops": 3,
  "since_year": 2021
}
```

Output:

```json
{
  "minimum_distance": 1,
  "paths": [
    {
      "authors": ["A999", "A123"],
      "evidence": [
        {
          "openalex_work": "W...",
          "doi": "...",
          "year": 2025
        }
      ]
    }
  ]
}
```

Implementation guidance:
- resolve authors to OpenAlex Author IDs,
- fetch reviewer/manuscript-author ego neighborhoods,
- build a local NetworkX graph,
- use `all_simple_paths` or shortest-path traversal with a low cutoff,
- do **not** build the entire global coauthor graph for the hackathon.

---

# 7. Shared Data Model

The main entities are:

## Trial

```json
{
  "id": "NCT01234567",
  "condition": "...",
  "intervention": "...",
  "phase": "PHASE3",
  "sponsor_type": "INDUSTRY",
  "enrollment": 500,
  "primary_outcomes": [],
  "secondary_outcomes": [],
  "start_date": "...",
  "completion_date": "...",
  "status": "COMPLETED",
  "registry_results": {}
}
```

## Work

```json
{
  "id": "W123...",
  "doi": "...",
  "title": "...",
  "abstract": "...",
  "publication_date": "...",
  "authors": [],
  "cited_by_count": 0,
  "is_retracted": false
}
```

## Author

```json
{
  "id": "A123...",
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

Important edge types:
- `MATCHED_TO`
- `CITES`
- `AUTHORED_BY`
- `COAUTHORED_WITH`
- `AFFILIATED_WITH`
- `RETRACTED_BY`
- `CORRECTED_BY`

Always preserve:
- NCT ID,
- OpenAlex Work ID,
- OpenAlex Author ID,
- DOI,
- source provenance.

---

# 8. Data Sources

## AACT / ClinicalTrials.gov

Use AACT for:
- bulk cohort creation,
- complex SQL analytics,
- completed-trial enumeration,
- registry result extraction,
- local reproducible analysis.

Use the ClinicalTrials.gov API for:
- live trial lookup,
- demo details,
- fresh individual-study records.

For the Voloridge challenge, frame this as:

> **OpenAlex is the primary dataset; AACT / ClinicalTrials.gov provides the registry-side join key and the missing-observation universe.**

If sponsor eligibility depends on approval for AACT, confirm this with the Voloridge booth.

## OpenAlex

OpenAlex is the second core dataset and should be used substantially.

Use it for:
- paper discovery,
- author identity,
- citation edges,
- coauthorship,
- institution data,
- publication metadata,
- large-scale literature graph analysis.

## Crossref / Retraction data

Use for:
- DOI metadata,
- corrections/retractions where needed,
- retraction dates and relationships.

## Optional later sources

Only if needed:
- PubMed / NCBI,
- Europe PMC,
- ORCID,
- FDA/EMA documents,
- Semantic Scholar.

Do not add sources merely for sponsor count.

---

# 9. Elasticsearch Role

Do not use Elasticsearch as the primary numerical/statistical database.

Use it for retrieval.

Index OpenAlex works with fields such as:

```json
{
  "id": "W123",
  "title": "...",
  "abstract": "...",
  "authors": ["..."],
  "interventions": ["..."],
  "conditions": ["..."],
  "year": 2024
}
```

Optionally index trial text:

```json
{
  "id": "NCT...",
  "brief_title": "...",
  "criteria": "...",
  "conditions": [],
  "interventions": [],
  "outcomes": []
}
```

Core matching path:

```text
Trial
  |
  v
Elastic keyword/semantic retrieval
  |
  v
Top candidate OpenAlex works
  |
  v
Deterministic matcher
  |
  v
Optional LLM adjudication
```

This makes Elastic genuinely essential rather than decorative.

---

# 10. AI Responsibilities

Use OpenAI only where language understanding materially helps.

Good uses:
- normalize outcome descriptions,
- extract structured effect-size claims from text,
- compare semantically equivalent endpoints,
- adjudicate ambiguous trial-paper matches,
- explain why two records were matched,
- explain bias-aware trial design outputs,
- summarize graph paths for humans.

Bad uses:
- inventing graph paths,
- calculating deterministic graph distances,
- declaring a paper fraudulent,
- deciding reviewer conflicts as policy judgments,
- fabricating missing trial outcomes,
- replacing statistical simulation with prose.

Core rule:

> **Database + graph + statistics for facts; LLM for extraction, semantic matching, and explanation.**

---

# 11. Token / Cost Strategy

This project naturally supports the Token Company challenge.

Do not send full papers or full trial records repeatedly.

Pipeline:

```text
exact string / ID match
        |
        v
deterministic feature scoring
        |
        v
cheap semantic model for uncertain pairs
        |
        v
expensive model only for difficult final cases
```

Also:
- cache structured extraction,
- cache embeddings,
- cache API responses,
- retrieve only relevant abstract/sections,
- serialize graph neighborhoods compactly.

Measure:

```text
baseline tokens per matching decision
vs
optimized tokens per matching decision
```

If possible, report cost and accuracy before/after optimization.

---

# 12. Suggested Tech Stack

## Frontend
- Next.js
- React
- TypeScript
- Tailwind CSS

## Backend
- Python
- FastAPI

## Statistical/Data Work
- pandas
- NumPy
- SciPy
- statsmodels and/or scikit-learn

## Graph Algorithms
- NetworkX

Start with NetworkX. Do not introduce Neo4j unless a real need appears.

## Graph Visualization
Choose one:
- Cytoscape.js
- React Flow

Cytoscape.js is likely better for citation/coauthor graph interaction.

## Search
- Elasticsearch

## Persistence
- PostgreSQL / Supabase

## AI
- OpenAI API

## Deployment
- Vercel for frontend
- Railway / Render / Fly.io for FastAPI backend

## Development
- GitHub
- Codex
- Devin if pursuing Cognition

---

# 13. Recommended Repository Structure

```text
backend/
  sources/
    aact.py
    clinicaltrials.py
    openalex.py
    crossref.py

  models/
    trial.py
    work.py
    author.py
    edges.py

  matching/
    candidates.py
    features.py
    matcher.py
    llm_judge.py

  publication_bias/
    cohort.py
    effect_sizes.py
    publication_model.py
    priors.py
    power.py
    sensitivity.py
    backtest.py

  graph/
    citations.py
    retractions.py
    coauthors.py
    reviewer_conflicts.py

  search/
    elastic.py

  llm/
    extraction.py
    matching.py
    explanation.py

  api/
    trials.py
    design.py
    reviewers.py
    retractions.py

frontend/
  components/
    TrialSearch.tsx
    TrialPublicationMatch.tsx
    BiasSummary.tsx
    PowerComparison.tsx
    SensitivitySlider.tsx
    CitationGraph.tsx
    ReviewerConflict.tsx
    EvidenceCard.tsx
```

---

# 14. UI / Demo Structure

The product should not look like three unrelated dashboards.

Suggested navigation:

## Main page — Bias-Aware Trial Design

Inputs:
- disease / condition,
- intervention,
- phase,
- proposed HR,
- alpha,
- desired power,
- optional trial-design parameters.

Outputs:
- comparable registered trials,
- comparable published trials,
- publication-linkage fraction,
- observed selection pattern,
- literature-only prior,
- registry-aware prior,
- naive vs adjusted power/sample-size estimate,
- sensitivity analysis for unknown-result trials.

## Research Integrity — Retraction Graph

Inputs:
- DOI / OpenAlex Work ID / title.

Outputs:
- retraction status,
- citation blast radius,
- post-retraction citations,
- downstream paths.

## Reviewer Check

Inputs:
- manuscript author IDs/names,
- candidate reviewer,
- time window.

Outputs:
- minimum graph distance,
- exact relationship paths,
- evidence works,
- most recent collaboration dates.

---

# 15. Demo Story

The hero demo should be one coherent story.

## Act 1 — Trial design problem

User proposes a trial with an assumed hazard ratio.

Example:

```text
Intervention: X
Condition: Y
Assumed HR: 0.65
Power target: 80%
```

The system retrieves comparable registered and published trials.

## Act 2 — Show the publication gap

Display:
- number of completed comparable trials,
- number with matched publications,
- number with registry results but no matched publication,
- result distribution by publication status.

## Act 3 — Show the design consequence

Compare:

```text
User assumption
Published-only estimate
Registry-aware estimate
```

Then show how power/sample size changes.

## Act 4 — Prove it is useful

Show back-test performance:
- naive literature-only model,
- registry-aware model.

## Act 5 — Show shared graph extensions

Briefly demonstrate:
- a retraction blast radius,
- a reviewer conflict path.

Narrative:

> “We built one provenance graph connecting registered experiments to published science. The main use is correcting trial-design assumptions for publication selection. Because the graph also knows citations and authors, it can trace retraction propagation and reviewer relationships almost for free.”

---

# 16. Sponsor Strategy

## Regeneron — PRIMARY TARGET

Challenge theme:
**Help Patients: Make Clinical Trials and Biostatistics Better**

Why this fits:
- directly improves trial-design reasoning,
- analyzes registered vs published evidence,
- helps biostatisticians calibrate effect-size assumptions,
- includes simulation/back-testing,
- can be open source and reproducible.

This is the anchor challenge.

## Voloridge — STRONG SECONDARY TARGET

Challenge:
**Signal in the Noise**

Why this fits:
- OpenAlex is one of their listed datasets,
- combines a massive scholarly dataset with trial-registry data,
- the datasets correct a bias in one another rather than being concatenated,
- produces a novel measurable insight,
- involves matching, large-scale graph work, and statistical validation,
- supports retraction/citation analysis as a second OpenAlex-native use case.

Key framing:

> “We measured how much the published record can overstate expected treatment effects, then used the registry record to de-bias the assumptions used in future trial design.”

If AACT requires sponsor blessing, present it as:

> “OpenAlex is our primary dataset; AACT is the registry-side join key and missing-observation universe.”

## Elastic — STRONG SECONDARY TARGET

Challenge:
**Find the Signal**

Why this fits:
- indexes OpenAlex abstracts and trial text,
- retrieves candidate publications for fuzzy trial-paper matching,
- supports semantic/keyword exploration,
- helps convert messy scientific text into actionable matches.

## Long Lake — STRONG SECONDARY TARGET

Challenge:
**Convince a Non-Believer**

Target skeptic:
- a biostatistician or scientist who distrusts black-box AI.

Why this fits:
- every important number comes from a query, graph traversal, statistical model, or simulation,
- the LLM is not asked to invent scientific conclusions,
- outputs preserve source evidence,
- the system explains uncertainty and assumptions.

Product framing:

> “This is not an AI chatbot telling you what your trial should do. It is an evidence engine showing you what the registry + literature imply, how publication selection changes the prior, and what that does to power.”

## OpenAI — STRONG SECONDARY TARGET

Use OpenAI for:
- structured extraction,
- semantic endpoint normalization,
- hard trial-paper matches,
- human-readable evidence explanations.

Use Codex meaningfully during development and document a concrete contribution to:
- matching logic,
- tests,
- API integrations,
- evaluation,
- debugging,
- UI.

## The Token Company — GOOD SECONDARY TARGET

Why this fits:
- matching potentially involves many millions of candidate decisions,
- a staged cascade can sharply reduce LLM usage,
- structured caching avoids repeatedly sending long scientific records.

Measure real token/cost reduction.

## Cognition / Devin — POSSIBLE SECONDARY TARGET

If entering, use Devin for a substantial build component such as:
- an API integration,
- automated testing,
- graph component,
- data pipeline,
- deployment.

## Ramp — POSSIBLE BUT NOT CORE

Possible framing:
- bad effect-size assumptions waste trial budget,
- better calibration can reduce underpowered or oversized study designs.

Do not force this challenge if the connection feels weak.

## Warp — POSSIBLE FOR REVIEWER TOOLING

Could be argued as research/developer tooling, but not a priority.

## Arrowstreet — NOT A CURRENT TARGET

Their challenge is specifically about greenwashing. The current product does not satisfy it without a separate use case.

---

# 17. Priority Order

## P0 — Must work

- define one narrow coherent trial cohort,
- ingest AACT / ClinicalTrials.gov data,
- ingest/query OpenAlex,
- exact NCT-to-publication matching,
- manually validate a sample of matches,
- store `trial_publication_matches`,
- identify trials with no publication found,
- identify registry-result availability,
- produce one publication-linkage analysis,
- extract one consistent effect-size measure,
- compare literature-only vs registry-aware effect distributions,
- map the difference into a power/sample-size calculation,
- show source provenance.

## P1 — High value

- fuzzy matching using Elastic,
- cheap-model adjudication for ambiguous pairs,
- back-testing,
- publication-probability model,
- sensitivity analysis,
- clean interactive trial-design UI.

## P2 — Shared graph extensions

- finish retraction blast radius,
- post-retraction citation counts,
- reviewer conflict endpoint,
- author ego graph,
- exact relationship-path visualization.

## P3 — Only after the hero demo is solid

- global graph scaling,
- Neo4j,
- voice,
- complex auth,
- autonomous agents,
- lots of extra datasets,
- fancy dashboards.

---

# 18. Immediate Build Order

1. Pull approximately 100–1,000 completed trials from one narrow clinical domain.
2. Implement exact NCT → OpenAlex matching.
3. Manually inspect at least 20 matches and 20 misses.
4. Persist a `trial_publication_matches` table or CSV.
5. Add fuzzy candidate retrieval for misses.
6. Identify registry-posted results.
7. Extract one comparable effect measure such as HR.
8. Compute publication-linkage rate by phase/sponsor/result direction.
9. Compare published-only vs registry-aware effect distributions.
10. Implement one power/sample-size consequence.
11. Back-test on held-out completed trials.
12. Finish the reviewer-conflict endpoint.
13. Polish the retraction graph.
14. Integrate the three into one coherent UI.

Do not build an agent before steps 1–10 work.

---

# 19. Scientific Integrity Guardrails

This product operates in biomedical research and must be conservative in its claims.

Rules:

1. Preserve provenance for every important output.
2. Distinguish observed facts from inferred matches.
3. Show match confidence and match reasons.
4. Never fabricate missing outcomes.
5. Do not assume unmatched means definitely unpublished.
6. Do not assume unpublished means null.
7. Do not accuse authors of misconduct based on a registry-publication discrepancy.
8. Do not treat citation of a retracted paper as endorsement.
9. Do not treat a graph relationship as automatically disqualifying a reviewer.
10. Keep effect measures statistically comparable.
11. Clearly label sensitivity assumptions.
12. Store raw identifiers and source links.
13. LLM text is explanation, not primary evidence.

---

# 20. Coding Principles for Codex

When making implementation decisions:

- optimize for the P0 happy path,
- keep architecture minimal,
- prefer deterministic logic over LLM calls,
- keep external source adapters modular,
- cache API responses,
- use typed normalized schemas,
- preserve raw IDs,
- separate retrieval, matching, statistics, graph logic, and LLM explanation,
- add small reproducible fixtures,
- mock external APIs in unit tests,
- never commit secrets,
- make the live demo resilient to API failure by caching known demo records.

If there is a conflict between “technically impressive” and “reliable by demo time,” prefer a reliable implementation that produces a measurable result.

---

# 21. Definition of Success

A successful hackathon submission should demonstrate:

1. A real cohort of completed registered trials.
2. Real OpenAlex publication matches.
3. A measurable publication-linkage gap.
4. A comparison of result distributions for published vs registry-only trials where observable.
5. A literature-only prior and registry-aware prior.
6. A concrete difference in predicted power or required sample size.
7. A back-test or calibration result.
8. A working citation/retraction graph.
9. A working reviewer relationship path.
10. Source provenance throughout.
11. AI used for semantic tasks rather than invented scientific conclusions.
12. A coherent demo showing that one underlying evidence graph powers all features.

The audience should leave with:

> **“Published literature is only one view of the evidence. This system connects it back to the trial registry, measures the missingness, shows how that changes the assumptions used to design the next experiment, and exposes the citation and researcher graph behind the science.”**

---

# 22. Summary for Codex

Treat this file as the product specification and source of truth.

The hero product is **bias-aware clinical trial design**.

The two core datasets are:
- **ClinicalTrials.gov / AACT** for the registered-trial universe,
- **OpenAlex** for the published scholarly record and graph.

The central technical problem is:
- accurately linking trials to publications,
- identifying unmatched completed trials,
- comparing observable published vs registry-only results,
- correcting design assumptions,
- validating the correction with back-testing.

The retraction blast-radius and reviewer-conflict tools are secondary features built on the same OpenAlex graph.

Primary sponsor target:
- Regeneron

Strong secondary targets:
- Voloridge
- Elastic
- Long Lake
- OpenAI
- The Token Company

Possible additional targets:
- Cognition / Devin
- Ramp
- Warp

Core implementation rule:

> **Use databases, graph algorithms, and statistics for facts. Use LLMs for extraction, semantic matching, and explanation.**

Core UX rule:

> **Show evidence, assumptions, and paths — not opaque scores or unsupported conclusions.**
