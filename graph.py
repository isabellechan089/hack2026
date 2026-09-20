"""Citation arrows point from the citing paper to the cited paper."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from collections import deque
from openalex import get_paper, get_citing_papers
from crossref import get_retraction_evidence

def annotate(nodes, edges, seed):
    by_id = {n['id']: n for n in nodes}
    outward = {n['id']: [] for n in nodes}
    for edge in edges:
        outward[edge['target']].append(edge['source'])
    distances = {seed: 0}
    queue = deque([seed])
    while queue:
        current = queue.popleft()
        for child in outward[current]:
            if child not in distances:
                distances[child] = distances[current] + 1
                queue.append(child)
    for node in nodes:
        node.update(distance=distances.get(node['id']), exposure='none', evidence_path=[])
    queue = deque()
    for node in nodes:
        if node['retraction']['status'] == 'retracted':
            node.update(exposure='retracted', evidence_path=[node['id']])
            queue.append(node['id'])
    while queue:
        current = queue.popleft()
        for child in outward[current]:
            node = by_id[child]
            if not node['evidence_path']:
                node['evidence_path'] = [child] + by_id[current]['evidence_path']
                node['exposure'] = 'direct' if len(node['evidence_path']) == 2 else 'indirect'
                queue.append(child)
    return nodes

def build_graph(doi, depth=2, limit=8):
    paper = get_paper(doi)
    works, edges, warnings = {paper['id']: paper}, set(), []
    frontier = [paper['id']]
    for hop in range(depth):
        following = []
        for work_id in frontier:
            try:
                children = get_citing_papers(work_id, limit if hop == 0 else 4)
            except Exception:
                warnings.append('Some citation branches could not be retrieved; this graph is incomplete.')
                continue
            for child in children:
                cid = child['id']
                if cid == work_id:
                    continue
                edges.add((cid, work_id))
                if cid not in works:
                    works[cid] = child
                    following.append(cid)
        frontier = following
    def convert(work):
        evidence = get_retraction_evidence(work.get('doi'))
        return {'id': work['id'], 'title': work.get('display_name') or 'Untitled work', 'doi': work.get('doi'), 'year': work.get('publication_year'), 'date': work.get('publication_date'), 'citations': work.get('cited_by_count', 0), 'authors': [a['author']['display_name'] for a in work.get('authorships', [])[:5]], 'journal': ((work.get('primary_location') or {}).get('source') or {}).get('display_name', 'Source unavailable'), 'openalex_retracted': work.get('is_retracted', False), 'retraction': evidence}
    with ThreadPoolExecutor(max_workers=2) as pool:
        nodes = list(pool.map(convert, works.values()))
    links = [{'source': a, 'target': b} for a, b in sorted(edges)]
    annotate(nodes, links, paper['id'])
    unknown = sum(n['retraction']['status'] == 'unknown' for n in nodes)
    if unknown:
        warnings.append(f'Retraction status is unknown for {unknown} papers. See individual records for details.')
    return {'seed': paper['id'], 'nodes': nodes, 'edges': links, 'generated_at': datetime.now(timezone.utc).isoformat(), 'mode': 'live', 'depth': depth, 'warnings': sorted(set(warnings)), 'sampling': f'Top {limit} citing works by citation count at the first hop; up to 4 per paper at the second hop. Not an exhaustive network. Metadata cached for up to 24 hours.'}
