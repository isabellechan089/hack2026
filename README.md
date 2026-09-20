# Evidence Atlas

A hackathon-ready citation provenance explorer. Enter a DOI, inspect a sampled network of citing papers, and follow source-linked retraction evidence.

## Run

```sh
python3 -m venv venv
venv/bin/python -m pip install -r requirements.txt
venv/bin/python main.py
```

Open http://127.0.0.1:8000. The app starts with the bundled real-data snapshot and works without API access in saved-demo mode. Fonts fall back to system fonts when offline. Use `--port 8001` if port 8000 is occupied.

Live searches require outbound access to OpenAlex and Crossref. If OpenAlex requests a key, set `OPENALEX_API_KEY` in the server environment before starting. The key is never sent to the browser or written to the metadata cache. `.env` files are not automatically loaded.

## Demo

See [DEMO.md](DEMO.md) for a two-minute presentation script. The in-app **Guided demo** walks through the same story. **Load saved example** restores the example; **Export evidence JSON** downloads the full current graph, source notices, timestamps, and evidence paths.

The saved sample starts at DOI `10.1177/1758835920922055`, with real OpenAlex citation edges and a Crossref notice at `10.1177/17588359231172420`. All numeric results describe this bounded sample, not the whole literature.

Refresh the snapshot before a presentation, with internet access:

```sh
venv/bin/python capture_demo.py
```

The script refuses to replace the snapshot if the starting paper's retraction cannot be confirmed.

## What is included

- Interactive, keyboard-selectable SVG citation graph with pan, zoom, filtering, and paper search.
- Paper list, metadata, direct publication links, source notices, and one shortest path to a confirmed retraction.
- Separate labels for confirmed retraction, other update, no notice found, and unknown.
- Live one- or two-hop DOI lookups and 24-hour on-disk metadata caching.
- Timeouts, bounded retries, partial-result warnings, and a real saved demo.
- Downloadable JSON for teammate integration.

## API / teammate integration

`GET /api/demo` returns the saved graph. `GET /api/graph?doi=10.1177/1758835920922055&depth=2` builds a live graph.

The result contains `seed`, `nodes`, `edges`, `generated_at`, `mode`, `depth`, `sampling`, and `warnings`. Nodes have stable OpenAlex `id`, `doi`, `title`, `authors`, `year`, `retraction` evidence, `exposure`, `distance`, and `evidence_path`. Edges contain `source` and `target`: **source cites target**. A trial module can join publications by normalized DOI; a people module can reuse the OpenAlex IDs. These two modules are not implemented here.

Citation retrieval takes the eight most-cited first-hop works and up to four works per first-hop paper at hop two. BFS calculates shortest distances and traces incoming citations from every confirmed retracted node. This prevents duplicate discoveries from overwriting the shortest distance or retraction status.

## Interpretation and limits

A citation connection does not demonstrate endorsement, invalidity, or misconduct. The app does not analyze full text, compare registered trial outcomes, identify reviewer conflicts, or establish whether a citation was made after retraction. Unknown means missing DOI, incomplete lookup, or provider failure. No notice found is not proof that a paper is unretracted or reliable. OpenAlex's boolean flag is reported separately when it differs from Crossref evidence.

Live results can use metadata fetched within the past 24 hours. `checked_at` records the lookup time, which can use that cache; `generated_at` records graph construction. Snapshots preserve the data captured at that time and are not automatically refreshed. Crossref notices include their source and update date. Providers can have coverage gaps. The current HTTP server is a local demo server, not a production deployment.

## Verify

```sh
venv/bin/python -m unittest discover -s tests -v
node --check static/app.js
```

`legacy_plot.py` preserves the original plotting script (requires the original NetworkX/Matplotlib environment). `main.py` is now the app entry point.
