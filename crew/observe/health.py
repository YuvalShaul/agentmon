"""The health check: http://crew:8001/health answers as long as the process runs.

It says the crew is alive, not that it is making progress: that is what the
heartbeats are for.
"""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Health(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200 if self.path == "/health" else 404)
        self.end_headers()
        self.wfile.write(b'{"status": "ok"}')

    def log_message(self, *args):
        pass


server = ThreadingHTTPServer(("", 8001), Health)
threading.Thread(target=server.serve_forever, daemon=True).start()
