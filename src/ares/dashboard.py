"""Single-screen dashboard bridge for Google Colab (and plain Jupyter).

In Colab the HTML panel calls ``google.colab.kernel.invokeFunction('ares_api')``
and every action is executed by the Python engine in this kernel. Outside Colab
the same panel is served by a local HTTP server and embedded in an IFrame.
"""
import json
import threading
from pathlib import Path

from .api import Session, handle_json

ROOT = Path(__file__).resolve().parents[2]


class Dashboard:
    def __init__(self, session=None, height=880, **config):
        config.setdefault('event_rate', .03)  # F3: the panel starts with 3 % random events
        self.session = session or Session(**config)
        self.height = int(height)

    def html(self):
        page = (ROOT / 'web' / 'index.html').read_text(encoding='utf-8')
        # Inside a notebook output the viewport is the output frame: fix its height.
        return page.replace('--app-h:100vh;', f'--app-h:{self.height}px;', 1)

    def _callback(self, fn, args_json):
        from IPython.display import JSON
        return JSON(json.loads(handle_json(self.session, fn, args_json)))

    def show(self):
        from IPython.display import HTML, IFrame, display
        try:
            from google.colab import output
        except ImportError:
            port = self.serve()
            display(IFrame(f'http://127.0.0.1:{port}/', width='100%', height=self.height + 10))
            return
        output.register_callback('ares_api', self._callback)
        display(HTML(self.html()))

    def serve(self, port=0):
        """Serve this session locally (non-Colab notebooks)."""
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        session, page, lock = self.session, (ROOT / 'web' / 'index.html').read_text(encoding='utf-8'), threading.Lock()

        class Handler(BaseHTTPRequestHandler):
            def _send(self, body, content_type):
                data = body.encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                self._send(page, 'text/html; charset=utf-8')

            def do_POST(self):
                request = json.loads(self.rfile.read(int(self.headers.get('Content-Length') or 0)) or b'{}')
                with lock:
                    body = handle_json(session, request.get('fn'), json.dumps(request.get('args') or {}))
                self._send(body, 'application/json; charset=utf-8')

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return server.server_address[1]
