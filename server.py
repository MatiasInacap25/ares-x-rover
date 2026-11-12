"""Local development server: serves the dashboard and the Python engine API.

Usage: python server.py [--port 8765]
The same ``Session.dispatch`` is used by the Colab bridge and by Pyodide.
"""
import argparse
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'src'))

from ares.api import Session  # noqa: E402

SESSION = Session(event_rate=.03)  # F3: the panel starts with 3 % random events
LOCK = threading.Lock()
INDEX = ROOT / 'web' / 'index.html'


class Handler(BaseHTTPRequestHandler):
    def _send(self, status, body, content_type):
        data = body.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path in ('/', '/index.html'):
            self._send(200, INDEX.read_text(encoding='utf-8'), 'text/html; charset=utf-8')
        else:
            self._send(404, 'No encontrado', 'text/plain; charset=utf-8')

    def do_POST(self):
        if self.path.rstrip('/') != '/api':
            self._send(404, '{"error": "No encontrado"}', 'application/json')
            return
        length = int(self.headers.get('Content-Length') or 0)
        try:
            request = json.loads(self.rfile.read(length) or b'{}')
            fn, args = request.get('fn'), request.get('args') or {}
        except (json.JSONDecodeError, AttributeError):
            self._send(400, '{"error": "JSON inválido"}', 'application/json')
            return
        with LOCK:
            result = SESSION.dispatch(fn, args)
        self._send(200, json.dumps(result, ensure_ascii=False, allow_nan=False), 'application/json; charset=utf-8')

    def log_message(self, fmt, *args):
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--host', default='127.0.0.1')
    options = parser.parse_args()
    server = ThreadingHTTPServer((options.host, options.port), Handler)
    print(f'ARES-X listo en http://{options.host}:{options.port}', flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
