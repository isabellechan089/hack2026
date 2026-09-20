"""Refresh the saved real-data demo; run before presenting, with internet access."""
import json
from pathlib import Path
from collections import Counter
from graph import build_graph
if __name__ == '__main__':
    graph = build_graph('10.1177/1758835920922055')
    graph['mode'] = 'snapshot'
    seed = next(n for n in graph['nodes'] if n['id'] == graph['seed'])
    if seed['retraction']['status'] != 'retracted':
        raise SystemExit('Seed notice was not confirmed; existing snapshot left untouched.')
    Path('data/demo.json').write_text(json.dumps(graph, indent=2))
    print(len(graph['nodes']), 'papers;', len(graph['edges']), 'links')
    print(Counter(n['retraction']['status'] for n in graph['nodes']))
