"""Bounded loopback HTTP adapter. This is a local demo, not a hosting server."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3
from urllib.parse import parse_qs, urlsplit

from .store import MAX_BYTES, ValidationError

STATIC = Path(__file__).with_name('static')
ASSETS = {
    '/': ('index.html', 'text/html; charset=utf-8'),
    '/styles.css': ('styles.css', 'text/css; charset=utf-8'),
    '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
    '/model.js': ('model.js', 'text/javascript; charset=utf-8'),
    '/favicon.svg': ('favicon.svg', 'image/svg+xml'),
}


def create_server(store, port=8765):
    class Handler(BaseHTTPRequestHandler):
        server_version = 'ImpactLedger/1.0'
        sys_version = ''

        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def log_message(self, format, *args):
            pass

        def respond(self, status, body, content_type='application/json; charset=utf-8', extra=None):
            if isinstance(body, dict):
                body = json.dumps(body, ensure_ascii=False, allow_nan=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
            self.send_header('Connection', 'close')
            for name, value in (extra or {}).items():
                self.send_header(name, value)
            self.end_headers()
            self.close_connection = True
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def error(self, status, message):
            self.respond(status, {'error': message})

        def query(self, allowed):
            try:
                params = parse_qs(urlsplit(self.path).query, keep_blank_values=True, encoding='utf-8', errors='strict', max_num_fields=10)
            except (UnicodeError, ValueError) as exc:
                raise ValidationError('Malformed query parameters.') from exc
            if any(key not in allowed or len(value) != 1 for key, value in params.items()):
                raise ValidationError('Unknown or repeated query parameter.')
            return {key: value[0] or None for key, value in params.items()}

        def allowed_host(self):
            port_number = self.server.server_address[1]
            return self.headers.get_all('Host', []) in [[f'127.0.0.1:{port_number}'], [f'localhost:{port_number}']]

        def dispatch(self):
            if not self.allowed_host():
                self.error(403, 'Only the local service host is allowed.')
                return
            try:
                try:
                    target = urlsplit(self.path)
                except ValueError as exc:
                    raise ValidationError('Malformed HTTP request target.') from exc
                if not self.path.startswith('/') or target.scheme or target.netloc or target.fragment:
                    raise ValidationError('Use an origin-form HTTP request target without a fragment.')
                path = target.path
                if self.command == 'GET':
                    if path in ASSETS:
                        name, content_type = ASSETS[path]
                        asset = STATIC / name
                        if not asset.is_file():
                            self.error(503, 'Frontend assets are missing. Run npm ci && npm run build.')
                            return
                        self.respond(200, asset.read_bytes(), content_type)
                    elif path == '/api/health':
                        self.query(set())
                        self.respond(200, {'status': 'ok', 'synthetic': True})
                    elif path == '/api/meta':
                        self.query(set())
                        self.respond(200, store.metadata())
                    elif path in ('/api/summary', '/api/snapshot'):
                        params = self.query({'start', 'end', 'program'})
                        result = store.summary(**params) if path.endswith('summary') else store.snapshot(**params)
                        self.respond(200, result)
                    elif path == '/api/export':
                        params = self.query({'kind', 'start', 'end', 'program'})
                        kind = params.pop('kind', None)
                        self.respond(200, store.export_csv(kind, **params), 'text/csv; charset=utf-8', {'Content-Disposition': f'attachment; filename="impact-ledger-{kind}.csv"'})
                    elif path == '/api/import':
                        self.error(405, 'Use POST for CSV imports.')
                    else:
                        self.error(404, 'Route not found.')
                elif self.command == 'POST' and path == '/api/import':
                    self.import_request()
                elif path in {'/api/health', '/api/meta', '/api/summary', '/api/snapshot', '/api/export'}:
                    self.error(405, 'Method not allowed for this route.')
                else:
                    self.error(404, 'Route not found.')
            except ValidationError as exc:
                self.error(400, str(exc))
            except (TimeoutError, ConnectionError):
                self.error(408, 'Request body was not received in time.')
            except sqlite3.Error:
                self.error(503, 'Local database is unavailable or busy. Try again.')

        def import_request(self):
            params = self.query({'kind'})
            origin = self.headers.get('Origin')
            if self.headers.get('Sec-Fetch-Site') == 'cross-site' or (origin is not None and origin != 'http://' + self.headers.get('Host', '')):
                self.error(403, 'Cross-origin imports are not allowed.')
                return
            if self.headers.get('Transfer-Encoding'):
                self.error(400, 'Transfer-Encoding is not supported. Send Content-Length.')
                return
            lengths = self.headers.get_all('Content-Length', [])
            if not lengths:
                self.error(411, 'Content-Length is required.')
                return
            if len(lengths) != 1 or len(lengths[0]) > 10 or not lengths[0].isascii() or not lengths[0].isdigit():
                self.error(400, 'Invalid Content-Length.')
                return
            length = int(lengths[0])
            if length > MAX_BYTES:
                self.error(413, 'CSV exceeds the 1 MiB limit.')
                return
            if self.headers.get_content_type() != 'text/csv' or self.headers.get_content_charset('utf-8') != 'utf-8':
                self.error(415, 'Send text/csv encoded as UTF-8.')
                return
            payload = self.rfile.read(length)
            if len(payload) != length:
                self.error(400, 'Incomplete request body.')
                return
            self.respond(201, store.import_csv(params.get('kind'), payload))

        do_GET = dispatch
        do_POST = dispatch
        do_DELETE = dispatch
        do_PUT = dispatch
        do_PATCH = dispatch
        do_OPTIONS = dispatch
        do_HEAD = dispatch

    return ThreadingHTTPServer(('127.0.0.1', port), Handler)
