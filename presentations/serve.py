#!/usr/bin/env python3
"""
Password-protected presentation server for Dyson Labs.

Features:
- Serves all presentations (NASA, DARPA, commercial, cofounder, stories)
- Renders markdown files (.md) as styled HTML (spec/, strategy/, research/)
- .htpasswd authentication (SHA256 or Apache MD5/bcrypt with passlib)
- Access logging for sharing detection (username, IP, browser, timestamp)
- Session fingerprinting to detect credential sharing

Usage:
    ./serve.py [port]
    ./serve.py --add-user username password

Configuration:
    .htpasswd - Password file (create with --add-user or htpasswd utility)
    access.log - JSON access log for analytics

Security Notes:
    - This server uses HTTP (not HTTPS). For production use, place behind
      a reverse proxy (nginx, caddy) that provides TLS termination.
    - Passwords are hashed with SHA256 + salt. For Apache MD5 ($apr1$) or
      bcrypt ($2y$) support, install passlib: pip install passlib
    - Access logs include IP and browser fingerprint for sharing detection.

Example:
    ./serve.py --add-user candidate1 secure_password
    ./serve.py
"""

import http.server
import socketserver
import os
import sys
import json
import hashlib
import base64
import secrets
from datetime import datetime, timezone

PORT = int(sys.argv[1]) if len(sys.argv) > 1 and not sys.argv[1].startswith('-') else 31415
BIND_ADDRESS = "0.0.0.0"
HTPASSWD_FILE = ".htpasswd"
ACCESS_LOG = "access.log"
REALM = "Dyson Labs Portal"
ADMIN_USERS = ["calvin", "bob"]

os.chdir(os.path.dirname(os.path.abspath(__file__)))


def sha256_hash(password: str, salt: str) -> str:
    """Create SHA256 hash for password storage."""
    return hashlib.sha256((salt + password).encode()).hexdigest()


def verify_htpasswd(username: str, password: str, htpasswd_path: str = HTPASSWD_FILE) -> bool:
    """Verify username/password against .htpasswd file.

    Supports:
    - SHA256 ($sha256$) - our custom format
    - SHA1 {SHA} - old htpasswd format
    - Plaintext (for testing only)
    - MD5 ($apr1$) and bcrypt ($2y$) if passlib is installed
    """
    if not os.path.exists(htpasswd_path):
        return False

    with open(htpasswd_path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if ':' not in line:
                continue

            stored_user, stored_hash = line.split(':', 1)
            if stored_user != username:
                continue

            # SHA256 format: $sha256$salt$hash
            if stored_hash.startswith('$sha256$'):
                parts = stored_hash.split('$')
                if len(parts) >= 4:
                    salt = parts[2]
                    expected_hash = parts[3]
                    return sha256_hash(password, salt) == expected_hash

            # Apache MD5 or bcrypt - try passlib
            if stored_hash.startswith('$apr1$') or stored_hash.startswith('$2'):
                try:
                    from passlib.apache import HtpasswdFile
                    htpasswd = HtpasswdFile(htpasswd_path)
                    result = htpasswd.check_password(username, password)
                    return result if result is not None else False
                except ImportError:
                    print("Warning: MD5/bcrypt hash found but passlib not installed")
                    print("  Install with: pip install passlib")
                    return False

            # SHA1 base64 (old htpasswd format) - deprecated but supported for compatibility
            if stored_hash.startswith('{SHA}'):
                print(f"Warning: User '{username}' uses deprecated SHA1 hash. Consider updating.")
                sha_hash = base64.b64encode(hashlib.sha1(password.encode()).digest()).decode()
                return stored_hash == '{SHA}' + sha_hash

            # Unknown hash format - reject (no plaintext fallback for security)
            print(f"Warning: Unknown hash format for user '{username}'. Use --add-user to create valid entry.")
            return False

    return False


def create_htpasswd_entry(username: str, password: str) -> str:
    """Create an htpasswd entry using SHA256."""
    salt = secrets.token_hex(8)
    hashed = sha256_hash(password, salt)
    return f"{username}:$sha256${salt}${hashed}"


def log_access(log_path: str, data: dict[str, str | int]) -> None:
    """Append access log entry as JSON line."""
    with open(log_path, 'a') as f:
        f.write(json.dumps(data) + '\n')


def generate_fingerprint(user_agent: str, accept_lang: str, accept_enc: str) -> str:
    """Generate a browser fingerprint from headers."""
    fp_data = f"{user_agent}|{accept_lang}|{accept_enc}"
    return hashlib.sha256(fp_data.encode()).hexdigest()[:16]


# Project root (parent of presentations/)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Markdown HTML template with GitHub-style rendering
MARKDOWN_TEMPLATE = '''<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{title} - Dyson Labs</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/github-markdown-css@5/github-markdown-dark.min.css">
    <style>
        body {{
            background: #0d1117;
            color: #e6edf3;
            padding: 2rem;
            max-width: 980px;
            margin: 0 auto;
        }}
        .markdown-body {{
            background: #0d1117;
        }}
        .nav {{
            margin-bottom: 2rem;
            padding-bottom: 1rem;
            border-bottom: 1px solid #30363d;
        }}
        .nav a {{
            color: #58a6ff;
            text-decoration: none;
            margin-right: 1rem;
        }}
        .nav a:hover {{
            text-decoration: underline;
        }}
    </style>
</head>
<body>
    <div class="nav">
        <a href="/">← Presentations</a>
        <a href="/docs/">Documentation Index</a>
    </div>
    <article class="markdown-body">
        <div id="content">Loading...</div>
    </article>
    <script src="https://cdn.jsdelivr.net/npm/marked@12/marked.min.js"></script>
    <script>
        const markdown = {markdown_content};
        document.getElementById('content').innerHTML = marked.parse(markdown);
    </script>
</body>
</html>
'''

ADMIN_TEMPLATE = '''<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Admin - Dyson Labs</title>
    <style>
        :root {{
            --bg: #0d1117;
            --card-bg: #161b22;
            --border: #30363d;
            --text: #e6edf3;
            --muted: #8b949e;
            --accent: #58a6ff;
            --green: #3fb950;
            --red: #f85149;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: var(--bg);
            color: var(--text);
            padding: 2rem;
            max-width: 900px;
            margin: 0 auto;
        }}
        h1 {{ color: var(--accent); margin-bottom: 0.5rem; }}
        h2 {{ color: var(--accent); font-size: 1.2rem; margin: 2rem 0 1rem; border-bottom: 1px solid var(--border); padding-bottom: 0.5rem; }}
        .nav {{ margin-bottom: 2rem; }}
        .nav a {{ color: var(--accent); text-decoration: none; }}
        .nav a:hover {{ text-decoration: underline; }}
        table {{ width: 100%; border-collapse: collapse; margin: 1rem 0; }}
        th, td {{ padding: 0.75rem; text-align: left; border-bottom: 1px solid var(--border); }}
        th {{ color: var(--muted); font-weight: 500; }}
        .warning {{ color: var(--red); font-weight: bold; }}
        .form-box {{
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 1.5rem;
            margin: 1rem 0;
        }}
        input[type="text"] {{
            background: var(--bg);
            border: 1px solid var(--border);
            border-radius: 4px;
            padding: 0.5rem 0.75rem;
            color: var(--text);
            font-size: 1rem;
            width: 200px;
        }}
        button {{
            background: var(--accent);
            color: var(--bg);
            border: none;
            border-radius: 4px;
            padding: 0.5rem 1rem;
            font-size: 1rem;
            cursor: pointer;
            margin-left: 0.5rem;
        }}
        button:hover {{ opacity: 0.9; }}
        .result {{
            background: var(--card-bg);
            border: 1px solid var(--green);
            border-radius: 8px;
            padding: 1rem;
            margin: 1rem 0;
        }}
        .result code {{
            background: var(--bg);
            padding: 0.2rem 0.5rem;
            border-radius: 4px;
            font-family: monospace;
            user-select: all;
        }}
        .muted {{ color: var(--muted); }}
    </style>
</head>
<body>
    <div class="nav"><a href="/">← Presentations</a></div>
    <h1>Admin Panel</h1>
    <p class="muted">Access restricted to: {admin_users}</p>

    {result_html}

    <h2>Add New User</h2>
    <div class="form-box">
        <form method="POST" action="/admin">
            <label for="username">Username:</label>
            <input type="text" id="username" name="username" required pattern="[a-zA-Z0-9_-]+" placeholder="newuser">
            <button type="submit">Generate Password</button>
        </form>
        <p class="muted" style="margin-top: 0.75rem; font-size: 0.85rem;">
            A random password will be generated and saved to .htpasswd
        </p>
    </div>

    <h2>Access Statistics</h2>
    <p class="muted">Users with 3+ unique IPs or devices are flagged for potential credential sharing.</p>
    <table>
        <tr>
            <th>User</th>
            <th>Accesses</th>
            <th>Unique IPs</th>
            <th>Devices</th>
            <th>Last Access</th>
        </tr>
        {stats_rows}
    </table>

    <h2>Registered Users</h2>
    <p class="muted">Users in .htpasswd file:</p>
    <ul style="margin: 1rem 0; padding-left: 1.5rem;">
        {user_list}
    </ul>
</body>
</html>
'''

DOCS_INDEX_TEMPLATE = '''<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Documentation - Dyson Labs</title>
    <style>
        :root {{
            --bg: #0d1117;
            --card-bg: #161b22;
            --border: #30363d;
            --text: #e6edf3;
            --muted: #8b949e;
            --accent: #58a6ff;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: var(--bg);
            color: var(--text);
            padding: 2rem;
            max-width: 900px;
            margin: 0 auto;
        }}
        h1 {{ color: var(--accent); margin-bottom: 0.5rem; }}
        .subtitle {{ color: var(--muted); margin-bottom: 2rem; }}
        h2 {{ color: var(--accent); font-size: 1.2rem; margin: 2rem 0 1rem; border-bottom: 1px solid var(--border); padding-bottom: 0.5rem; }}
        .nav {{ margin-bottom: 2rem; }}
        .nav a {{ color: var(--accent); text-decoration: none; }}
        .nav a:hover {{ text-decoration: underline; }}
        ul {{ list-style: none; }}
        li {{ margin: 0.5rem 0; }}
        a {{ color: var(--accent); text-decoration: none; }}
        a:hover {{ text-decoration: underline; }}
        .desc {{ color: var(--muted); font-size: 0.9rem; margin-left: 1rem; }}
    </style>
</head>
<body>
    <div class="nav"><a href="/">← Presentations</a></div>
    <h1>Documentation</h1>
    <p class="subtitle">SCRAP Protocol Specifications and Strategy Documents</p>

    <h2>Specifications</h2>
    <ul>
        <li><a href="/docs/spec/SCRAP.md">SCRAP.md</a> <span class="desc">Primary protocol specification</span></li>
        <li><a href="/docs/spec/SISL.md">SISL.md</a> <span class="desc">Secure Inter-Satellite Link protocol</span></li>
        <li><a href="/docs/spec/HTLC.md">HTLC.md</a> <span class="desc">Lightning HTLC payment protocol</span></li>
        <li><a href="/docs/spec/PTLC-FALLBACK.md">PTLC-FALLBACK.md</a> <span class="desc">On-chain PTLC payments</span></li>
        <li><a href="/docs/spec/OPERATOR_API.md">OPERATOR_API.md</a> <span class="desc">Operator service API</span></li>
    </ul>

    <h2>Strategy</h2>
    <ul>
        <li><a href="/docs/strategy/ROADMAP.md">ROADMAP.md</a> <span class="desc">Development roadmap</span></li>
        <li><a href="/docs/strategy/FUNDING.md">FUNDING.md</a> <span class="desc">Grant opportunities</span></li>
        <li><a href="/docs/strategy/TRL.md">TRL.md</a> <span class="desc">Technology readiness progression</span></li>
        <li><a href="/docs/strategy/STANDARDIZATION.md">STANDARDIZATION.md</a> <span class="desc">CCSDS/ITU path</span></li>
        <li><a href="/docs/strategy/REGULATORY.md">REGULATORY.md</a> <span class="desc">Spectrum and compliance</span></li>
    </ul>

    <h2>Research</h2>
    <ul>
        <li><a href="/docs/research/CNC_RESEARCH.md">CNC_RESEARCH.md</a> <span class="desc">Satellite C2 protocols survey</span></li>
        <li><a href="/docs/research/PAYMENT_RESEARCH.md">PAYMENT_RESEARCH.md</a> <span class="desc">Bitcoin L2 technologies</span></li>
    </ul>
</body>
</html>
'''


class PortalHandler(http.server.SimpleHTTPRequestHandler):
    """HTTP handler with .htpasswd auth and access logging."""

    def do_HEAD(self) -> None:
        if not self.authenticate():
            self.send_auth_required()
            return
        super().do_HEAD()

    def do_GET(self) -> None:
        username = self.authenticate()
        if not username:
            self.send_auth_required()
            return

        # Log access
        self.log_access(username)

        # Handle /admin - restricted to ADMIN_USERS
        if self.path == '/admin' or self.path == '/admin/':
            if username not in ADMIN_USERS:
                self.send_error(403, "Admin access denied")
                return
            self.serve_admin()
            return

        # Handle /docs/ paths - serve markdown as HTML
        if self.path == '/docs/' or self.path == '/docs':
            self.serve_docs_index()
            return
        elif self.path.startswith('/docs/') and self.path.endswith('.md'):
            self.serve_markdown(self.path[6:])  # Strip /docs/ prefix
            return
        elif self.path.startswith('/docs/') and (self.path.endswith('/') or '.' not in self.path.split('/')[-1]):
            # Directory listing under /docs/
            self.serve_docs_dir(self.path[6:].rstrip('/'))
            return

        super().do_GET()

    def do_POST(self) -> None:
        username = self.authenticate()
        if not username:
            self.send_auth_required()
            return

        self.log_access(username)

        # Only /admin accepts POST
        if self.path == '/admin' or self.path == '/admin/':
            if username not in ADMIN_USERS:
                self.send_error(403, "Admin access denied")
                return
            self.handle_admin_post()
            return

        self.send_error(405, "Method not allowed")

    def handle_admin_post(self) -> None:
        """Handle POST to /admin - add new user."""
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length).decode('utf-8')

        # Parse form data
        from urllib.parse import parse_qs
        params = parse_qs(post_data)
        new_username = params.get('username', [''])[0].strip()

        if not new_username or not new_username.replace('_', '').replace('-', '').isalnum():
            self.serve_admin(error="Invalid username. Use only letters, numbers, underscores, hyphens.")
            return

        # Generate random password (16 chars, alphanumeric + special)
        password = secrets.token_urlsafe(12)

        # Add user
        add_user(new_username, password)

        self.serve_admin(new_user=new_username, new_password=password)

    def serve_docs_index(self) -> None:
        """Serve the documentation index page."""
        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(DOCS_INDEX_TEMPLATE.encode('utf-8'))

    def serve_markdown(self, rel_path: str) -> None:
        """Serve a markdown file as rendered HTML."""
        # Resolve the file path relative to project root
        file_path = os.path.join(PROJECT_ROOT, rel_path)

        # Security: ensure path doesn't escape project root
        real_path = os.path.realpath(file_path)
        if not real_path.startswith(os.path.realpath(PROJECT_ROOT)):
            self.send_error(403, "Access denied")
            return

        if not os.path.isfile(real_path):
            self.send_error(404, f"File not found: {rel_path}")
            return

        try:
            with open(real_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Escape for JSON embedding
            escaped = json.dumps(content)

            # Extract title from first # heading or filename
            title = os.path.basename(rel_path)
            for line in content.split('\n'):
                if line.startswith('# '):
                    title = line[2:].strip()
                    break

            html = MARKDOWN_TEMPLATE.format(
                title=title,
                markdown_content=escaped
            )

            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(html.encode('utf-8'))

        except Exception as e:
            self.send_error(500, f"Error reading file: {e}")

    def serve_docs_dir(self, rel_dir: str) -> None:
        """Serve a directory listing for docs subdirectory."""
        dir_path = os.path.join(PROJECT_ROOT, rel_dir)

        # Security: ensure path doesn't escape project root
        real_path = os.path.realpath(dir_path)
        if not real_path.startswith(os.path.realpath(PROJECT_ROOT)):
            self.send_error(403, "Access denied")
            return

        if not os.path.isdir(real_path):
            self.send_error(404, f"Directory not found: {rel_dir}")
            return

        # List markdown files in directory
        try:
            files = sorted([f for f in os.listdir(real_path) if f.endswith('.md')])

            links = []
            for f in files:
                links.append(f'        <li><a href="/docs/{rel_dir}/{f}">{f}</a></li>')

            html = f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{rel_dir}/ - Dyson Labs</title>
    <style>
        body {{
            font-family: -apple-system, sans-serif;
            background: #0d1117;
            color: #e6edf3;
            padding: 2rem;
            max-width: 900px;
            margin: 0 auto;
        }}
        h1 {{ color: #58a6ff; }}
        .nav {{ margin-bottom: 2rem; }}
        .nav a {{ color: #58a6ff; text-decoration: none; margin-right: 1rem; }}
        .nav a:hover {{ text-decoration: underline; }}
        ul {{ list-style: none; padding: 0; }}
        li {{ margin: 0.5rem 0; }}
        a {{ color: #58a6ff; text-decoration: none; }}
        a:hover {{ text-decoration: underline; }}
    </style>
</head>
<body>
    <div class="nav">
        <a href="/">← Presentations</a>
        <a href="/docs/">Documentation Index</a>
    </div>
    <h1>{rel_dir}/</h1>
    <ul>
{chr(10).join(links)}
    </ul>
</body>
</html>
'''
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(html.encode('utf-8'))

        except Exception as e:
            self.send_error(500, f"Error listing directory: {e}")

    def serve_admin(self, new_user: str | None = None, new_password: str | None = None, error: str | None = None) -> None:
        """Serve admin panel with access stats and user management."""
        # Build result HTML if user was just created or error occurred
        result_html = ""
        if new_user and new_password:
            result_html = f'''<div class="result">
        <strong>User created:</strong> {new_user}<br>
        <strong>Password:</strong> <code>{new_password}</code><br>
        <em>Copy this password now - it cannot be retrieved later.</em>
    </div>'''
        elif error:
            result_html = f'<div class="result" style="border-color: var(--red);"><strong>Error:</strong> {error}</div>'

        # Get access stats
        stats = analyze_access_log()
        stats_rows = ""
        for user, data in stats.items():
            ips = data['unique_ips']
            fps = data['unique_fingerprints']
            ip_count = len(ips) if isinstance(ips, set) else 0
            fp_count = len(fps) if isinstance(fps, set) else 0
            warning_class = ' class="warning"' if ip_count > 3 or fp_count > 3 else ""
            last = str(data['last_access'])[:19]
            stats_rows += f'''<tr{warning_class}>
            <td>{user}</td>
            <td>{data['access_count']}</td>
            <td>{ip_count}</td>
            <td>{fp_count}</td>
            <td>{last}</td>
        </tr>
'''

        if not stats_rows:
            stats_rows = '<tr><td colspan="5" style="color: var(--muted);">No access logs yet</td></tr>'

        # Get registered users
        users = check_htpasswd() or []
        user_list = "\n".join(f"<li>{u}</li>" for u in users)

        html = ADMIN_TEMPLATE.format(
            admin_users=", ".join(ADMIN_USERS),
            result_html=result_html,
            stats_rows=stats_rows,
            user_list=user_list
        )

        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(html.encode('utf-8'))

    def send_auth_required(self) -> None:
        """Send 401 response requesting authentication."""
        self.send_response(401)
        self.send_header('WWW-Authenticate', f'Basic realm="{REALM}"')
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(b'''<!DOCTYPE html>
<html><head><title>Authentication Required</title>
<style>
body { font-family: -apple-system, sans-serif; background: #0d1117; color: #e6edf3;
       display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }
.box { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 2rem; text-align: center; }
h1 { color: #58a6ff; margin-bottom: 1rem; }
p { color: #8b949e; }
</style></head>
<body><div class="box"><h1>Dyson Labs</h1><p>Authentication required to access presentations.</p></div></body></html>
''')

    def authenticate(self) -> str | None:
        """Verify Basic auth credentials. Returns username if valid, None otherwise."""
        auth_header = self.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Basic '):
            return None

        try:
            credentials = base64.b64decode(auth_header[6:]).decode('utf-8')
            username, password = credentials.split(':', 1)

            if verify_htpasswd(username, password):
                return username
        except Exception as e:
            print(f"Auth error: {e}")

        return None

    def log_access(self, username: str) -> None:
        """Log access details for sharing detection."""
        # Extract headers for fingerprinting
        user_agent = self.headers.get('User-Agent', '')
        accept_lang = self.headers.get('Accept-Language', '')
        accept_enc = self.headers.get('Accept-Encoding', '')
        referer = self.headers.get('Referer', '')

        # Get client IP (handle X-Forwarded-For for reverse proxies)
        forwarded_for = self.headers.get('X-Forwarded-For')
        if forwarded_for:
            client_ip = forwarded_for.split(',')[0].strip()
        else:
            client_ip = self.client_address[0]

        # Generate browser fingerprint
        fingerprint = generate_fingerprint(user_agent, accept_lang, accept_enc)

        # Build log entry
        entry: dict[str, str | int] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "username": username,
            "ip": client_ip,
            "path": self.path,
            "method": self.command,
            "user_agent": user_agent,
            "accept_language": accept_lang,
            "referer": referer,
            "fingerprint": fingerprint,
        }

        log_access(ACCESS_LOG, entry)

    def log_message(self, format: str, *args: str) -> None:
        """Custom log format."""
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {self.address_string()} - {format % args}")


def check_htpasswd() -> list[str] | None:
    """Check if .htpasswd exists and has entries. Returns list of users or None."""
    if not os.path.exists(HTPASSWD_FILE):
        print(f"\n{'='*60}")
        print("  WARNING: No .htpasswd file found!")
        print(f"{'='*60}")
        print(f"\n  Create one with:")
        print(f"    htpasswd -c {HTPASSWD_FILE} username")
        print(f"\n  Or use this script:")
        print(f"    ./serve.py --add-user username password")
        print(f"\n  Quick setup (change password!):")
        print(f"    ./serve.py --add-user demo demo123")
        print()
        return None

    # Count users
    users: list[str] = []
    with open(HTPASSWD_FILE, 'r') as f:
        for line in f:
            if ':' in line and not line.startswith('#'):
                users.append(line.split(':')[0])

    if not users:
        print(f"  WARNING: {HTPASSWD_FILE} exists but has no valid entries!")
        return None

    return users


def analyze_access_log() -> dict[str, dict[str, int | str | set[str]]]:
    """Quick analysis of access log for sharing detection."""
    if not os.path.exists(ACCESS_LOG):
        return {}

    stats: dict[str, dict[str, int | str | set[str]]] = {}
    with open(ACCESS_LOG, 'r') as f:
        for line in f:
            try:
                entry = json.loads(line)
                user = entry.get('username', 'unknown')
                if user not in stats:
                    stats[user] = {
                        'access_count': 0,
                        'unique_ips': set(),
                        'unique_fingerprints': set(),
                        'last_access': ''
                    }
                user_stats = stats[user]
                access_count = user_stats['access_count']
                if isinstance(access_count, int):
                    user_stats['access_count'] = access_count + 1
                ips = user_stats['unique_ips']
                if isinstance(ips, set):
                    ips.add(entry.get('ip', ''))
                fps = user_stats['unique_fingerprints']
                if isinstance(fps, set):
                    fps.add(entry.get('fingerprint', ''))
                user_stats['last_access'] = entry.get('timestamp', '')
            except json.JSONDecodeError:
                continue

    return stats


def add_user(username: str, password: str) -> None:
    """Add or update a user in .htpasswd."""
    entries: dict[str, str] = {}

    # Read existing entries
    if os.path.exists(HTPASSWD_FILE):
        with open(HTPASSWD_FILE, 'r') as f:
            for line in f:
                line = line.strip()
                if ':' in line and not line.startswith('#'):
                    user, hashed = line.split(':', 1)
                    entries[user] = hashed

    # Add/update user
    entry = create_htpasswd_entry(username, password)
    entries[username] = entry.split(':', 1)[1]

    # Write back
    with open(HTPASSWD_FILE, 'w') as f:
        for user, hashed in entries.items():
            f.write(f"{user}:{hashed}\n")

    print(f"User '{username}' added/updated in {HTPASSWD_FILE}")


if __name__ == "__main__":
    # Handle --add-user command
    if len(sys.argv) >= 4 and sys.argv[1] == '--add-user':
        add_user(sys.argv[2], sys.argv[3])
        sys.exit(0)

    if len(sys.argv) == 2 and sys.argv[1] in ('--help', '-h'):
        print(__doc__)
        sys.exit(0)

    users = check_htpasswd()

    if not users:
        print("  Server will not start without valid .htpasswd")
        print()
        sys.exit(1)

    # Show access stats if log exists
    stats = analyze_access_log()

    print(f"\n{'='*60}")
    print(f"  Dyson Labs Presentation Portal")
    print(f"{'='*60}")
    print(f"  URL:          http://localhost:{PORT}/")
    print(f"  Auth file:    {HTPASSWD_FILE}")
    print(f"  Access log:   {ACCESS_LOG}")
    print(f"  Users:        {', '.join(users)}")
    print(f"{'='*60}")

    if stats:
        print(f"\n  Access Statistics (sharing detection):")
        print(f"  {'User':<15} {'Accesses':>10} {'IPs':>6} {'Devices':>8} {'Last Access'}")
        print(f"  {'-'*15} {'-'*10} {'-'*6} {'-'*8} {'-'*20}")
        for user, data in stats.items():
            ips = data['unique_ips']
            fps = data['unique_fingerprints']
            ip_count = len(ips) if isinstance(ips, set) else 0
            fp_count = len(fps) if isinstance(fps, set) else 0
            warning = " (!)" if ip_count > 3 or fp_count > 3 else ""
            last = str(data['last_access'])[:19]
            print(f"  {user:<15} {data['access_count']:>10} {ip_count:>6} {fp_count:>8} {last}{warning}")
        print()

    print(f"\n  Available presentations:")
    print(f"    http://YOUR_IP:{PORT}/              - Index (all presentations)")
    print(f"    http://YOUR_IP:{PORT}/cofounder.html - Co-founder opportunity")
    print(f"    http://YOUR_IP:{PORT}/commercial.html - Investor deck")
    print(f"    http://YOUR_IP:{PORT}/nasa.html      - NASA deck")
    print(f"    http://YOUR_IP:{PORT}/darpa.html     - DARPA deck")
    print(f"\n  Documentation (markdown rendered as HTML):")
    print(f"    http://YOUR_IP:{PORT}/docs/          - Documentation index")
    print(f"    http://YOUR_IP:{PORT}/docs/spec/SCRAP.md - Protocol spec")
    print(f"\n  Add new user:")
    print(f"    ./serve.py --add-user newuser password")
    print(f"\n  Press Ctrl+C to stop.\n")

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer((BIND_ADDRESS, PORT), PortalHandler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n\nShutting down.")
            print(f"Access log saved to: {ACCESS_LOG}")
