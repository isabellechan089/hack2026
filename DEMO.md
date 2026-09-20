# Evidence Atlas — two-minute demo

## Before presenting

1. Start `venv/bin/python main.py` and open http://127.0.0.1:8000.
2. Click **Load saved example**. Keep the saved snapshot for the presentation; live APIs are optional.
3. Use a wide browser window so the graph and evidence panel appear side by side.
4. Confirm the seed has a linked retraction notice. Read the displayed counts; don't imply this is the entire citation network.

## 0:00–0:20 — The problem

“Research papers don't exist in isolation. When a paper is retracted, researchers need to understand where it appears in the evidence trail. Evidence Atlas makes those connections visible and inspectable.”

## 0:20–0:45 — The real example

“This is a real osteosarcoma paper, retrieved through OpenAlex. The red starting node has a retraction notice. We show the source and link directly to the notice, so you can verify the evidence yourself.”

Point to the starting paper's update evidence and the dated Crossref notice. The snapshot contains 40 papers and 40 citation links: one confirmed retracted seed, eight direct connections, and 31 indirect connections.

## 0:45–1:15 — Follow the trail

Click a yellow outer-ring node, or switch to **Papers** and choose an indirect connection.

“Orange papers directly cite a retracted work; yellow papers connect through another paper. Selecting a paper reveals a shortest citation path back to the retraction. Every step is inspectable.”

Click a path step to navigate. Explain that arrows point from the citing paper to the cited paper.

## 1:15–1:40 — What makes the result useful

“We keep a paper's own retraction status separate from its citation connections. A connection is a reason to investigate, not a claim that a paper is invalid. Unknown checks remain unknown, and we disclose the sample limits.”

Show the graph filter, paper search, and the source/coverage section. Export evidence JSON if helpful.

## 1:40–2:00 — The product and broader vision

“You can enter another DOI to explore its citation neighborhood. The underlying graph is also designed to connect to trial–publication comparisons and researcher relationships. Today we have a complete, source-linked citation provenance workflow with a saved demo that doesn't depend on live API availability.”

## If asked about AI

“The graph paths are deterministic. We don't use an LLM to invent connections or assign credibility scores. A future extraction module can compare reported trial outcomes with registered plans and attach cited evidence to this graph.”

## If live retrieval fails

Click **Load saved example**. Explain that the clearly labeled snapshot contains real previously fetched metadata. Never present it as a fresh live lookup.
