import hashlib
import json
import os
import re
import time
import tempfile
from pathlib import Path
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
CACHE = Path(__file__).parent / '.cache'
def fetch(url, params=None):
    params = dict(params or {})
    key = hashlib.sha256(json.dumps([url, params], sort_keys=True).encode()).hexdigest()
    path = CACHE / (key + '.json')
    if path.exists() and time.time() - path.stat().st_mtime < 86400:
        return json.loads(path.read_text())
    if 'api.openalex.org' in url and os.getenv('OPENALEX_API_KEY'):
        params['api_key'] = os.environ['OPENALEX_API_KEY']
    session = requests.Session()
    session.mount('https://', HTTPAdapter(max_retries=Retry(total=2, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504], respect_retry_after_header=False)))
    with session:
        response = session.get(url, params=params, timeout=(5, 15), headers={'User-Agent': 'EvidenceAtlas-Hackathon/1.0'})
    response.raise_for_status()
    result = response.json()
    CACHE.mkdir(exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', dir=CACHE, delete=False) as temporary:
        json.dump(result, temporary)
    Path(temporary.name).replace(path)
    return result

def normalize_doi(value):
    value = re.sub(r'^https?://(?:dx\.)?doi\.org/', '', (value or '').strip(), flags=re.I)
    value = re.sub(r'^doi:\s*', '', value, flags=re.I).lower()
    if not re.fullmatch(r'10\.\d{4,9}/\S+', value) or len(value) > 300:
        raise ValueError('Enter a DOI such as 10.1177/1758835920922055.')
    return value
