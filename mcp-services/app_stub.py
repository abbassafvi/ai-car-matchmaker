"""M0 placeholder — replaced by the real marketplace/booking/payment MCP
servers in M1/M3/M4 (see specs/001-ai-car-matchmaker/tasks.md, T023/T033/T039).
"""
from http.server import BaseHTTPRequestHandler, HTTPServer


class Health(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status":"ok","service":"mcp-services","phase":"M0-stub"}')

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", 8100), Health).serve_forever()
