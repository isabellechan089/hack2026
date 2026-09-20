from api_client import fetch, normalize_doi
from urllib.parse import quote

def get_paper(doi):
    return fetch('https://api.openalex.org/works/https://doi.org/' + quote(normalize_doi(doi), safe='/'))

def get_citing_papers(openalex_id, limit=10):
    return fetch('https://api.openalex.org/works', {'filter': 'cites:' + openalex_id.split('/')[-1], 'per-page': max(1, min(limit, 50)), 'sort': 'cited_by_count:desc'})['results']
