"""M0 placeholder — replaced by the real FastAPI chat endpoint in M2 (see
specs/001-ai-car-matchmaker/tasks.md, T018). Exists only to prove the
docker-compose service boots and is reachable.
"""
from http.server import BaseHTTPRequestHandler, HTTPServer


class Health(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status":"ok","service":"agent-backend","phase":"M0-stub"}')

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", 8000), Health).serve_forever()
