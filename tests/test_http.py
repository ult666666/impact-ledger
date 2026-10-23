import http.client
import json
from pathlib import Path
import tempfile
import socket
import threading
import unittest

from impact_ledger.server import create_server
from impact_ledger.store import Store, MAX_BYTES
from test_store import SESSIONS, ATTENDANCE, SESSION_HEADER


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / 'ledger.db')
        self.server = create_server(self.store, port=0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': 0.01}, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=3)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def populated(self):
        self.store.import_csv('sessions', SESSIONS.encode())
        self.store.import_csv('attendance', ATTENDANCE.encode())

    def test_real_http_summary_filters_and_metadata(self):
        self.populated()
        status, _, body = self.request('GET', '/api/summary?start=2026-02-10&end=2026-02-10&program=Learning%20Lab')
        self.assertEqual(status, 200)
        totals = json.loads(body)['totals']
        self.assertEqual((totals['attendance'], totals['budget'], totals['variance']), (1, 50, 25))
        status, _, body = self.request('GET', '/api/meta')
        self.assertEqual(json.loads(body)['sessions'], 4)
        self.assertTrue(json.loads(body)['synthetic'])

    def test_real_csv_import_and_export(self):
        status, _, body = self.request('POST', '/api/import?kind=sessions', SESSIONS.encode(), {'Content-Type': 'text/csv; charset=utf-8'})
        self.assertEqual((status, json.loads(body)['imported']), (201, 4))
        status, headers, body = self.request('GET', '/api/export?kind=sessions&start=2026-02-10&end=2026-02-10')
        self.assertEqual(status, 200)
        self.assertEqual(headers['Content-Type'], 'text/csv; charset=utf-8')
        self.assertIn('attachment;', headers['Content-Disposition'])
        self.assertIn(b's2,Learning Lab,2026-02-10,2.00,50.00,75.00', body)
        self.assertNotIn(b's1,', body)

    def test_http_import_failure_is_atomic(self):
        payload = SESSION_HEADER + 'new,Lab,2026-01-01,1,1,1\nbad,Lab,2026-02-30,1,1,1\n'
        status, _, body = self.request('POST', '/api/import?kind=sessions', payload.encode(), {'Content-Type': 'text/csv'})
        self.assertEqual(status, 400)
        self.assertIn('error', json.loads(body))
        self.assertEqual(self.store.summary()['totals']['sessions'], 0)

    def test_oversize_body_is_rejected_without_persistence(self):
        status, _, _ = self.request('POST', '/api/import?kind=sessions', b'x', {'Content-Type': 'text/csv', 'Content-Length': str(MAX_BYTES + 1)})
        self.assertEqual(status, 413)
        self.assertEqual(self.store.summary()['totals']['sessions'], 0)

    def test_invalid_lengths_and_chunked_requests_are_rejected(self):
        for headers in [{'Content-Length': '-1'}, {'Content-Length': 'abc'}, {'Content-Length': '9' * 5000}, {'Transfer-Encoding': 'chunked'}]:
            status, _, body = self.request('POST', '/api/import?kind=sessions', b'', {'Content-Type': 'text/csv', **headers})
            self.assertEqual(status, 400)
            self.assertIn('error', json.loads(body))

    def test_truncated_body_and_missing_length_have_readable_errors(self):
        for headers, expected in [('Content-Length: 100\r\n', b'400'), ('', b'411')]:
            with socket.create_connection(('127.0.0.1', self.port), timeout=3) as connection:
                request = f'POST /api/import?kind=sessions HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\nContent-Type: text/csv\r\n{headers}\r\nx'
                connection.sendall(request.encode())
                connection.shutdown(socket.SHUT_WR)
                received = b''
                while chunk := connection.recv(4096):
                    received += chunk
            self.assertIn(expected, received.split(b'\r\n', 1)[0])
            self.assertIn(b'"error"', received)
        self.assertEqual(self.store.summary()['totals']['sessions'], 0)

    def test_malformed_or_absolute_request_targets_return_json_400(self):
        for target in ['http://[', f'http://127.0.0.1:{self.port}/api/health']:
            with socket.create_connection(('127.0.0.1', self.port), timeout=3) as connection:
                connection.sendall(f'GET {target} HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\nConnection: close\r\n\r\n'.encode())
                received = b''
                while chunk := connection.recv(4096):
                    received += chunk
            self.assertIn(b'400', received.split(b'\r\n', 1)[0])
            self.assertIn('error', json.loads(received.split(b'\r\n\r\n', 1)[1]))

    def test_content_type_and_invalid_utf8_are_rejected(self):
        for payload, headers, expected in [(b'{}', {'Content-Type': 'application/json'}, 415), (b'\xff', {'Content-Type': 'text/csv'}, 400), (b'x', {'Content-Type': 'text/csv; charset=latin1'}, 415)]:
            status, _, _ = self.request('POST', '/api/import?kind=sessions', payload, headers)
            self.assertEqual(status, expected)

    def test_rebinding_and_cross_site_writes_are_rejected(self):
        for headers in [{'Host': f'evil.example:{self.port}'}, {'Origin': 'https://evil.example'}, {'Sec-Fetch-Site': 'cross-site'}, {'Origin': 'null'}]:
            status, _, _ = self.request('POST', '/api/import?kind=sessions', SESSIONS.encode(), {'Content-Type': 'text/csv', **headers})
            self.assertEqual(status, 403)
        self.assertEqual(self.store.summary()['totals']['sessions'], 0)
        status, _, _ = self.request('POST', '/api/import?kind=sessions', SESSIONS.encode(), {'Content-Type': 'text/csv', 'Origin': f'http://127.0.0.1:{self.port}'})
        self.assertEqual(status, 201)

    def test_malformed_and_duplicate_query_parameters_are_errors(self):
        for query in ['start=2026-02-30', 'start=2026-03-01&end=2026-01-01', 'program=A&program=B', 'unknown=1', 'program=%FF']:
            status, _, body = self.request('GET', '/api/summary?' + query)
            self.assertEqual(status, 400)
            self.assertIn('error', json.loads(body))

    def test_unknown_routes_and_methods_use_json_errors(self):
        for method, path, expected in [('GET', '/api/nope', 404), ('DELETE', '/api/summary', 405), ('POST', '/api/summary', 405), ('GET', '/api/import?kind=sessions', 405), ('GET', '/../../README.md', 404)]:
            status, _, body = self.request(method, path)
            self.assertEqual(status, expected)
            self.assertIn('error', json.loads(body))

    def test_static_root_and_security_headers(self):
        status, headers, body = self.request('GET', '/')
        self.assertEqual(status, 200)
        self.assertIn(b'Impact Ledger', body)
        self.assertIn("default-src 'self'", headers['Content-Security-Policy'])
        self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(headers['Cache-Control'], 'no-store')

    def test_snapshot_and_health_do_not_expose_database_path(self):
        self.populated()
        status, _, body = self.request('GET', '/api/snapshot')
        self.assertEqual(status, 200)
        rows = json.loads(body)['sessions']
        self.assertEqual(rows[0]['participants'], ['p1', 'p2'])
        status, _, body = self.request('GET', '/api/health')
        self.assertEqual(json.loads(body), {'status': 'ok', 'synthetic': True})
        self.assertNotIn(self.temp.name.encode(), body)
        self.assertEqual(self.server.server_address[0], '127.0.0.1')


if __name__ == '__main__':
    unittest.main()
