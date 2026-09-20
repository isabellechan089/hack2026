"""Screen a paper's own reference list for retractions.

The citation graph answers "who cites this retracted work?". This answers the
question a researcher actually has: "is anything I cite retracted?"

That is the opposite direction through the graph -- outgoing references rather
than incoming citations -- and it needs a different strategy. A reference list
can hold hundreds of entries, so checking each one against Crossref would take
minutes. Instead OpenAlex screens the whole list in a handful of batched calls
using its own retraction flag, and Crossref is consulted only for the entries
that screen positive, to recover the notice, its date and its source.

The cost of that trade is stated in the output: an entry OpenAlex does not flag
was not individually checked against Crossref, so a clean result is "nothing
found by this screen", never "your sources are fine".
"""

from concurrent.futures import ThreadPoolExecutor

from api_client import fetch, normalize_doi
from crossref import get_retraction_evidence

OPENALEX = 'https://api.openalex.org/works'
BATCH = 50
# Reference lists longer than this are truncated; review articles can cite
# several hundred works and each batch is another round trip.
MAX_REFERENCES = 400

WORK_FIELDS = 'id,doi,display_name,publication_year,publication_date,is_retracted,cited_by_count'


def _short(openalex_id):
    return (openalex_id or '').rstrip('/').split('/')[-1]


def _clean_doi(value):
    return (value or '').replace('https://doi.org/', '') or None


def get_references(doi):
    """The work itself plus the OpenAlex ids of everything it cites."""
    work = fetch(OPENALEX + '/https://doi.org/' + normalize_doi(doi),
                 {'select': 'id,doi,display_name,publication_year,publication_date,'
                            'referenced_works,referenced_works_count,cited_by_count,'
                            'is_retracted,authorships,primary_location'})
    return work, [_short(r) for r in work.get('referenced_works') or []]


def _screen_batch(ids):
    payload = fetch(OPENALEX, {'filter': 'openalex_id:' + '|'.join(ids),
                               'select': WORK_FIELDS, 'per-page': len(ids)})
    return payload.get('results', [])


def check_sources(doi, deep=False):
    """Report which of a paper's references carry a retraction.

    With `deep`, every reference is also checked against Crossref. That is far
    slower but removes the reliance on OpenAlex's flag, so a negative result
    means considerably more.
    """
    work, reference_ids = get_references(doi)
    total = work.get('referenced_works_count') or len(reference_ids)
    warnings = []

    if len(reference_ids) > MAX_REFERENCES:
        warnings.append(
            'This paper cites {} works; only the first {} were screened.'.format(
                len(reference_ids), MAX_REFERENCES))
        reference_ids = reference_ids[:MAX_REFERENCES]

    screened = []
    batches = [reference_ids[i:i + BATCH] for i in range(0, len(reference_ids), BATCH)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        for result in pool.map(_screen_batch, batches):
            screened.extend(result)

    missing = len(reference_ids) - len(screened)
    if missing > 0:
        warnings.append(
            '{} reference(s) could not be resolved in OpenAlex and were not screened.'.format(missing))

    # Confirm the flagged entries against Crossref to recover notice details.
    to_confirm = [w for w in screened if w.get('is_retracted')] if not deep else screened
    with ThreadPoolExecutor(max_workers=4) as pool:
        evidence = list(pool.map(lambda w: get_retraction_evidence(_clean_doi(w.get('doi'))), to_confirm))

    by_id = {}
    for reference, notice in zip(to_confirm, evidence):
        by_id[reference['id']] = notice

    flagged = []
    for reference in screened:
        notice = by_id.get(reference['id'])
        openalex_flag = bool(reference.get('is_retracted'))
        crossref_status = (notice or {}).get('status')
        if not openalex_flag and crossref_status not in ('retracted', 'updated'):
            continue
        flagged.append({
            'id': reference['id'],
            'doi': _clean_doi(reference.get('doi')),
            'title': reference.get('display_name') or 'Untitled work',
            'year': reference.get('publication_year'),
            'date': reference.get('publication_date'),
            'citations': reference.get('cited_by_count', 0),
            'openalex_retracted': openalex_flag,
            'retraction': notice or {'status': 'unknown', 'notices': [],
                                     'reason': 'Not checked against Crossref.'},
        })
    flagged.sort(key=lambda item: (item['retraction'].get('status') != 'retracted',
                                   -(item.get('citations') or 0)))

    confirmed = [f for f in flagged if f['retraction'].get('status') == 'retracted']
    updated = [f for f in flagged if f['retraction'].get('status') == 'updated']

    source = (work.get('primary_location') or {}).get('source') or {}
    return {
        'paper': {
            'id': work.get('id'),
            'doi': _clean_doi(work.get('doi')),
            'title': work.get('display_name') or 'Untitled work',
            'year': work.get('publication_year'),
            'date': work.get('publication_date'),
            'citations': work.get('cited_by_count', 0),
            'journal': source.get('display_name', 'Source unavailable'),
            'is_retracted': bool(work.get('is_retracted')),
            'authors': [a['author']['display_name']
                        for a in (work.get('authorships') or [])[:5]
                        if a.get('author', {}).get('display_name')],
        },
        'references_total': total,
        'references_screened': len(screened),
        'retracted_references': len(confirmed),
        'updated_references': len(updated),
        'flagged': flagged,
        'deep': deep,
        'warnings': warnings,
        'method': (
            'Every reference was checked individually against Crossref update notices.'
            if deep else
            'References were screened using OpenAlex retraction flags; only flagged '
            'entries were confirmed against Crossref. A reference that OpenAlex does '
            'not flag was not individually checked, so "none found" means none found '
            'by this screen, not that the reference list is clean.'
        ),
        'interpretation': (
            'Citing a retracted paper is not itself an error. The citation may discuss '
            'the retraction, or concern a part of the work the notice does not affect. '
            'These are entries worth looking at, not verdicts.'
        ),
    }
