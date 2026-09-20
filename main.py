"""Run: python main.py. Open http://127.0.0.1:8000."""
import json
import os
import argparse
from pathlib import Path
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from graph import build_graph
from api_client import normalize_doi
from retraction_check import check_sources
from backend.report import comparison_report, paper_report, trial_report
from backend.publication_bias.analysis import analyze
from backend.publication_bias.cohort import available_cohorts, cohort_path, describe, load_or_build
from backend.graph.reviewer_conflicts import find_conflicts, resolve_author
from backend.sources.clinical_trials import looks_like_nct_id
from backend.sources.http import SourceError
ROOT = Path(__file__).parent
class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT / 'static'), **kwargs)
    def reply(self, payload, status=200):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in ('/api/demo', '/api/demo-sources'):
            name = 'demo.json' if parsed.path == '/api/demo' else 'demo_sources.json'
            path = ROOT / 'data' / name
            if not path.exists():
                return self.reply({'error': 'Saved snapshot is not available. Run capture_demo.py.'}, 503)
            return self.reply(json.loads(path.read_text()))
        if parsed.path == '/api/sources':
            query = parse_qs(parsed.query)
            try:
                doi = normalize_doi(query.get('doi', [''])[0])
                return self.reply(check_sources(doi, deep=query.get('deep', [''])[0] == '1'))
            except ValueError as error:
                return self.reply({'error': str(error)}, 400)
            except Exception:
                return self.reply({'error': 'This reference list could not be retrieved. Check the DOI, or try the saved demo.'}, 502)
        if parsed.path == '/api/graph':
            query = parse_qs(parsed.query)
            try:
                doi = normalize_doi(query.get('doi', [''])[0])
                depth = int(query.get('depth', ['2'])[0])
                if depth not in (1, 2):
                    raise ValueError('Choose one or two citation hops.')
                limit = max(5, min(50, int(query.get('limit', ['20'])[0])))
                return self.reply(build_graph(doi, depth, limit=limit,
                                              per_branch=max(2, min(10, limit // 4))))
            except ValueError as error:
                return self.reply({'error': str(error)}, 400)
            except Exception:
                return self.reply({'error': 'The metadata provider could not complete this lookup. Check your connection or OPENALEX_API_KEY, or use the saved demo.'}, 502)
        if parsed.path == '/api/cohorts':
            return self.reply({'cohorts': available_cohorts()})
        if parsed.path in ('/api/design', '/api/cohort'):
            query = parse_qs(parsed.query)
            try:
                condition = (query.get('condition', [''])[0] or '').strip()
                if not condition:
                    raise ValueError('Provide a condition, for example "non-small cell lung cancer".')
                endpoint = query.get('endpoint', ['os'])[0]
                if endpoint not in ('os', 'pfs'):
                    raise ValueError('endpoint must be os or pfs.')
                # A saved cohort answers instantly; anything else is built live,
                # which batched linkage brings down to roughly ten seconds.
                rebuild = query.get('rebuild', [''])[0] == '1'
                cohort = load_or_build(
                    condition,
                    endpoint_class=endpoint,
                    phases=tuple(query.get('phases', ['2,3'])[0].split(',')),
                    max_studies=min(400, int(query.get('max_studies', ['300'])[0])),
                    rebuild=rebuild,
                )
                if not cohort.trials:
                    raise ValueError(
                        'No completed trials with posted results found for "{}". Try a '
                        'broader disease term.'.format(condition))
                if parsed.path == '/api/cohort':
                    return self.reply(describe(cohort))
                return self.reply(analyze(
                    cohort,
                    assumed_hr=float(query.get('hr', ['0.65'])[0]),
                    alpha=float(query.get('alpha', ['0.05'])[0]),
                    target_power=float(query.get('power', ['0.8'])[0]),
                    event_probability=float(query['event_probability'][0])
                    if query.get('event_probability') else None,
                ))
            except ValueError as error:
                return self.reply({'error': str(error)}, 400)
            except SourceError:
                return self.reply({'error': 'A source could not complete this lookup. Try again shortly.'}, 502)
            except Exception:
                return self.reply({'error': 'This analysis could not be completed.'}, 502)
        if parsed.path in ('/api/trial', '/api/paper', '/api/compare'):
            query = parse_qs(parsed.query)
            try:
                if parsed.path == '/api/trial':
                    nct = (query.get('nct', [''])[0] or '').strip().upper()
                    if not looks_like_nct_id(nct):
                        raise ValueError('Enter a registry identifier such as NCT02142738.')
                    return self.reply(trial_report(nct, limit=int(query.get('limit', ['8'])[0])))
                if parsed.path == '/api/paper':
                    return self.reply(paper_report(query.get('pmid', [''])[0].strip()))
                nct = (query.get('nct', [''])[0] or '').strip().upper()
                if not looks_like_nct_id(nct):
                    raise ValueError('Enter a registry identifier such as NCT02142738.')
                return self.reply(comparison_report(nct, query.get('pmid', [''])[0].strip()))
            except ValueError as error:
                return self.reply({'error': str(error)}, 400)
            except SourceError:
                return self.reply({'error': 'ClinicalTrials.gov or PubMed could not complete this lookup. Try again shortly.'}, 502)
            except Exception:
                return self.reply({'error': 'This registry lookup could not be completed.'}, 502)
        if parsed.path.startswith('/api/'):
            return self.reply({'error': 'Not found'}, 404)
        super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != '/api/reviewer-conflict':
            return self.reply({'error': 'Not found'}, 404)
        try:
            length = int(self.headers.get('Content-Length') or 0)
            if length <= 0 or length > 1_000_000:
                raise ValueError('Send a JSON body describing the manuscript and reviewer.')
            body = json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            return self.reply({'error': 'Request body must be valid JSON.'}, 400)
        except ValueError as error:
            return self.reply({'error': str(error) or 'Request body must be JSON.'}, 400)

        try:
            reviewer_query = body.get('candidate_reviewer')
            authors_query = body.get('manuscript_authors') or []
            if not reviewer_query or not authors_query:
                raise ValueError('candidate_reviewer and manuscript_authors are both required.')

            reviewer = resolve_author(str(reviewer_query))
            if reviewer is None:
                raise ValueError('Could not resolve the candidate reviewer in OpenAlex.')
            authors, unresolved = [], []
            for name in authors_query:
                record = resolve_author(str(name))
                (authors.append(record['id']) if record else unresolved.append(name))
            if not authors:
                raise ValueError('None of the manuscript authors could be resolved in OpenAlex.')

            result = find_conflicts(
                reviewer['id'], authors,
                max_hops=max(1, min(4, int(body.get('max_hops', 2)))),
                since_year=body.get('since_year'),
            )
            result['unresolved_authors'] = unresolved
            return self.reply(result)
        except ValueError as error:
            return self.reply({'error': str(error)}, 400)
        except SourceError:
            return self.reply({'error': 'OpenAlex could not complete this lookup.'}, 502)
        except Exception:
            return self.reply({'error': 'This conflict check could not be completed.'}, 502)
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    print(f'Evidence Atlas → http://127.0.0.1:{args.port}', flush=True)
    ThreadingHTTPServer(('127.0.0.1', args.port), Handler).serve_forever()
