"""Password-protected proxy for the complete local workbench."""
import base64
from contextlib import closing
import hmac
import http.client
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

CREDENTIALS = Path(__file__).resolve().parents[1]/'runtime/public-workbench-credentials.json'


class Gateway(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def proxy(self):
        credentials = json.loads(CREDENTIALS.read_text())
        expected = 'Basic ' + base64.b64encode(
            (credentials['username'] + ':' + credentials['password']).encode()).decode()
        if not hmac.compare_digest(self.headers.get('Authorization', ''), expected):
            self.send_response(401)
            self.send_header('WWW-Authenticate', 'Basic realm="Novel Workbench", charset="UTF-8"')
            self.send_header('Content-Length', '0')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            return
        if not self.path.startswith('/') or self.path.startswith('//') or urlsplit(self.path).scheme:
            self.send_error(400)
            return
        if self.command == 'POST':
            host = self.headers.get('Host', '')
            if self.headers.get('Origin') not in {'https://' + host, 'http://127.0.0.1:8766'}:
                self.send_error(403)
                return
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if size < 0 or size > 1024 * 1024 or self.headers.get('Transfer-Encoding'):
                self.send_error(413)
                return
            body = self.rfile.read(size) if size else None
            headers = {'Host': '127.0.0.1:8765'}
            for key in ('Content-Type', 'Range', 'If-Range', 'Accept'):
                if self.headers.get(key):
                    headers[key] = self.headers[key]
            if self.command == 'POST':
                headers['Origin'] = 'http://127.0.0.1:8765'
            with closing(http.client.HTTPConnection('127.0.0.1', 8765, timeout=120)) as conn:
                conn.request(self.command, self.path, body=body, headers=headers)
                response = conn.getresponse()
                self.send_response(response.status)
                for key, value in response.getheaders():
                    if key.lower() not in {'connection', 'transfer-encoding', 'server', 'date', 'cache-control'}:
                        self.send_header(key, value)
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Referrer-Policy', 'same-origin')
                self.end_headers()
                while chunk := response.read(65536):
                    self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except (ValueError, OSError, http.client.HTTPException):
            self.close_connection = True

    do_GET = proxy
    do_POST = proxy


if __name__ == '__main__':
    ThreadingHTTPServer(('127.0.0.1', 8766), Gateway).serve_forever()
