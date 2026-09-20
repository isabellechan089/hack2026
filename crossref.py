from api_client import fetch, normalize_doi
from urllib.parse import quote
from datetime import datetime, timezone
import requests

def get_crossref_data(doi):
    return fetch('https://api.crossref.org/works/' + quote(normalize_doi(doi), safe='/'))['message']

def get_retraction_evidence(doi):
    result = {'status': 'unknown', 'notices': [], 'checked_at': datetime.now(timezone.utc).isoformat(), 'source': 'Crossref'}
    if not doi:
        result['reason'] = 'No DOI available.'
        return result
    try:
        clean = normalize_doi(doi)
        message = fetch('https://api.crossref.org/works', {'filter': f'updates:{clean}', 'rows': 1000})['message']
        for item in message['items']:
            for update in item.get('update-to', []):
                if update.get('DOI', '').lower() == clean:
                    result['notices'].append({'doi': item.get('DOI'), 'title': (item.get('title') or ['Update notice'])[0], 'type': update.get('type', 'update'), 'date': update.get('updated', {}).get('date-time'), 'source': update.get('source', 'Crossref')})
        merged = {}
        for notice in result['notices']:
            key = (notice['doi'], notice['type'], notice['date'])
            if key in merged:
                merged[key]['source'] += ' + ' + notice['source']
            else:
                merged[key] = notice
        result['notices'] = list(merged.values())
        kinds = {x['type'] for x in result['notices']}
        result['status'] = 'retracted' if 'retraction' in kinds else 'updated' if kinds else 'no_notice_found'
        if message.get('total-results', 0) > len(message['items']) and result['status'] != 'retracted':
            result['status'] = 'unknown'
            result['reason'] = 'Update results were truncated.'
    except (requests.RequestException, ValueError, KeyError):
        result['reason'] = 'Crossref lookup unavailable. Try again later.'
    return result

def get_retraction_status(doi):
    return get_retraction_evidence(doi)['status']
