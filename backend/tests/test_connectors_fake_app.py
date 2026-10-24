"""Test connectors against fake app cases."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from app.services.connectors import HttpConnector


class FastHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        self.rfile.read(content_length)
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({"answer": "fast response"}).encode())
    
    def log_message(self, *args):
        pass


def test_fast_app():
    server = HTTPServer(('localhost', 0), FastHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    try:
        connector = HttpConnector(allow_private=True)
        trace = connector.render_and_send(
            url=f'http://localhost:{port}/test',
            body_template='{"question": {{input}}}',
            input_text="test",
            timeout_seconds=5,
        )
        assert trace.output == "fast response"
    finally:
        server.shutdown()
