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
    radius = blast_radius(nodes, links, paper['id'])
    unknown = sum(n['retraction']['status'] == 'unknown' for n in nodes)
    if unknown:
        warnings.append(f'Retraction status is unknown for {unknown} papers. See individual records for details.')
    return {'seed': paper['id'], 'nodes': nodes, 'edges': links, 'blast_radius': radius, 'generated_at': datetime.now(timezone.utc).isoformat(), 'mode': 'live', 'depth': depth, 'warnings': sorted(set(warnings)), 'sampling': f'Top {limit} citing works by citation count at the first hop; up to 4 per paper at the second hop. Not an exhaustive network. Metadata cached for up to 24 hours.'}


def blast_radius(nodes, edges, seed):
    """Quantify how far a retracted work has propagated (spec section 5).

    Adds the timing dimension the graph view was missing: a citation published
    after a retraction notice appeared is a different fact from one published
    before it, when the citing authors could not have known.

    Structure and timing only. A paper that cites a retracted work may be
    criticising it or citing the notice itself, so nothing here is described as
    contaminated or invalid.
    """
    by_id = {n['id']: n for n in nodes}
    seed_node = by_id.get(seed) or {}
    notices = [n for n in seed_node.get('retraction', {}).get('notices', []) if n.get('type') == 'retraction']
    retraction_date = min((n['date'][:10] for n in notices if n.get('date')), default=None)

    exposed = [n for n in nodes if n['id'] != seed and n.get('exposure') in ('direct', 'indirect')]
    direct = [n for n in exposed if n.get('exposure') == 'direct']
    indirect = [n for n in exposed if n.get('exposure') == 'indirect']
    dated = [n for n in exposed if n.get('date')]

    after = [n for n in dated if retraction_date and n['date'][:10] > retraction_date]
    before = [n for n in dated if retraction_date and n['date'][:10] <= retraction_date]

    return {
        'retraction_date': retraction_date,
        'direct_citations': len(direct),
        'downstream_descendants': len(indirect),
        'total_exposed': len(exposed),
        # Citations accumulated by the exposed papers themselves: how much
        # further reading sits downstream of the retracted work in this sample.
        'weighted_downstream_citation_mass': sum(n.get('citations') or 0 for n in exposed),
        'cited_after_retraction': len(after),
        'cited_before_retraction': len(before),
        'undated': len(exposed) - len(dated),
        'earliest_downstream': min((n['date'][:10] for n in dated), default=None),
        'latest_downstream': max((n['date'][:10] for n in dated), default=None),
        'retracted_citers': sum(1 for n in exposed if n.get('retraction', {}).get('status') == 'retracted'),
        'after_retraction_examples': [
            {'id': n['id'], 'title': n['title'], 'date': n['date'], 'doi': n.get('doi')}
            for n in sorted(after, key=lambda n: n['date'], reverse=True)[:5]
        ],
        'note': (
            'Counts describe this sampled network only. A citation appearing after a '
            'retraction notice is a timing fact, not a judgement about the citing paper.'
            if retraction_date else
            'No dated retraction notice for the starting paper, so before/after timing '
            'could not be determined.'
        ),
    }
