"""Run: python main.py. Open http://127.0.0.1:8000."""
import json
import argparse
from pathlib import Path
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from graph import build_graph
from api_client import normalize_doi
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
        if parsed.path == '/api/demo':
            path = ROOT / 'data/demo.json'
            if not path.exists():
                return self.reply({'error': 'Demo snapshot is not available.'}, 503)
            return self.reply(json.loads(path.read_text()))
        if parsed.path == '/api/graph':
            query = parse_qs(parsed.query)
            try:
                doi = normalize_doi(query.get('doi', [''])[0])
                depth = int(query.get('depth', ['2'])[0])
                if depth not in (1, 2):
                    raise ValueError('Choose one or two citation hops.')
                return self.reply(build_graph(doi, depth))
            except ValueError as error:
                return self.reply({'error': str(error)}, 400)
            except Exception:
                return self.reply({'error': 'The metadata provider could not complete this lookup. Check your connection or OPENALEX_API_KEY, or use the saved demo.'}, 502)
        if parsed.path.startswith('/api/'):
            return self.reply({'error': 'Not found'}, 404)
        super().do_GET()
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    print(f'Evidence Atlas → http://127.0.0.1:{args.port}', flush=True)
    ThreadingHTTPServer(('127.0.0.1', args.port), Handler).serve_forever()
