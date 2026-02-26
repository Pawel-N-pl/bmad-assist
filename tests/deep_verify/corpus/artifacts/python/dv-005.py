"""HTTP API handler with validation issues."""

import json
from http.server import BaseHTTPRequestHandler


class APIHandler(BaseHTTPRequestHandler):
    """HTTP API request handler."""

    def do_post(self):
        """Handle POST requests."""
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length)

        # VULNERABILITY: No input validation (CQ-005)
        data = json.loads(body)  # May raise if body is not JSON

        # VULNERABILITY: No error handling for missing fields
        user_id = data['user_id']  # KeyError if missing
        action = data['action']

        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps({'status': 'ok'}).encode())

    def do_get(self):
        """Handle GET requests."""
        path = self.path

        # VULNERABILITY: Path traversal risk
        if path.startswith('/files/'):
            filename = path[7:]  # No validation
            # Could access arbitrary files

        self.send_response(200)
        self.end_headers()
