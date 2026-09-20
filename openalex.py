from api_client import fetch, normalize_doi
from urllib.parse import quote

WORKS = 'https://api.openalex.org/works'


def get_paper(doi):
    return fetch(WORKS + '/https://doi.org/' + quote(normalize_doi(doi), safe='/'))


def get_citing_papers(openalex_id, limit=10):
    return fetch(WORKS, {
        'filter': 'cites:' + openalex_id.split('/')[-1],
        'per-page': max(1, min(limit, 200)),
        'sort': 'cited_by_count:desc',
    })['results']


def count_citing_papers(openalex_id):
    """How many works cite this one, in total.

    One cheap call gives the real size of the citation network, so a sampled
    graph can say "showing 20 of 52" instead of implying it shows everything.
    """
    try:
        return fetch(WORKS, {
            'filter': 'cites:' + openalex_id.split('/')[-1],
            'per-page': 1,
            'select': 'id',
        })['meta']['count']
    except Exception:
        return None
