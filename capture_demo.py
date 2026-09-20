"""Refresh the saved real-data demos; run before presenting, with internet access.

Two snapshots are written, one per mode, so the whole demo survives an API
outage or bad conference wifi:

  data/demo.json          the citation graph around a retracted paper
  data/demo_sources.json  a reference-integrity check on a paper that cites it
"""
import json
from pathlib import Path
from collections import Counter
from graph import build_graph
from retraction_check import check_sources

# A real retracted osteosarcoma paper, and a Nature Reviews Clinical Oncology
# review that cites it among 182 references.
SEED_DOI = '10.1177/1758835920922055'
CITING_DOI = '10.1038/s41571-021-00519-8'

if __name__ == '__main__':
    graph = build_graph(SEED_DOI)
    graph['mode'] = 'snapshot'
    seed = next(n for n in graph['nodes'] if n['id'] == graph['seed'])
    if seed['retraction']['status'] != 'retracted':
        raise SystemExit('Seed notice was not confirmed; existing snapshots left untouched.')

    sources = check_sources(CITING_DOI)
    sources['mode'] = 'snapshot'
    if not sources['retracted_references']:
        raise SystemExit('Saved source check found no retracted reference; snapshots left untouched.')

    Path('data/demo.json').write_text(json.dumps(graph, indent=1))
    Path('data/demo_sources.json').write_text(json.dumps(sources, indent=1))

    print(len(graph['nodes']), 'papers;', len(graph['edges']), 'links')
    print(Counter(n['retraction']['status'] for n in graph['nodes']))
    print('blast radius: {} cited after {}'.format(
        graph['blast_radius']['cited_after_retraction'], graph['blast_radius']['retraction_date']))
    print('source check: {} of {} references retracted'.format(
        sources['retracted_references'], sources['references_screened']))
