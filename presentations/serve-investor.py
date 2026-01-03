#!/usr/bin/env python3
"""
Password-protected presentation server for investor demos.
Usage: ./serve-investor.py [port] [username] [password]
"""

import http.server
import socketserver
import base64
import os
import sys

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8787
USERNAME = sys.argv[2] if len(sys.argv) > 2 else "investor"
PASSWORD = sys.argv[3] if len(sys.argv) > 3 else "dyson2025"

os.chdir(os.path.dirname(os.path.abspath(__file__)))

class AuthHandler(http.server.SimpleHTTPRequestHandler):
    def do_HEAD(self):
        if not self.authenticate():
            self.send_response(401)
            self.send_header('WWW-Authenticate', 'Basic realm="Dyson Labs Investor Portal"')
            self.end_headers()
            return
        super().do_HEAD()

    def do_GET(self):
        if not self.authenticate():
            self.send_response(401)
            self.send_header('WWW-Authenticate', 'Basic realm="Dyson Labs Investor Portal"')
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(b'<h1>Authentication Required</h1>')
            return
        super().do_GET()

    def authenticate(self):
        auth_header = self.headers.get('Authorization')
        if auth_header is None:
            return False
        if not auth_header.startswith('Basic '):
            return False
        try:
            credentials = base64.b64decode(auth_header[6:]).decode('utf-8')
            user, pwd = credentials.split(':', 1)
            return user == USERNAME and pwd == PASSWORD
        except:
            return False

    def log_message(self, format, *args):
        print(f"[{self.address_string()}] {format % args}")

if __name__ == "__main__":
    with socketserver.TCPServer(("", PORT), AuthHandler) as httpd:
        print(f"\n{'='*60}")
        print(f"  Dyson Labs Investor Portal")
        print(f"{'='*60}")
        print(f"  URL:      http://localhost:{PORT}/")
        print(f"  Username: {USERNAME}")
        print(f"  Password: {PASSWORD}")
        print(f"{'='*60}")
        print(f"\nShare with investor:")
        print(f"  http://YOUR_IP:{PORT}/")
        print(f"\nPress Ctrl+C to stop.\n")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down.")
