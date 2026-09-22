"""Password-protected proxy for the complete local workbench."""
import base64
from contextlib import closing
import gzip
import hmac
import http.client
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

CREDENTIALS = Path(__file__).resolve().parents[1]/'runtime/public-workbench-credentials.json'


class Gateway(BaseHTTPRequestHandler):
    # Keep the browser/public-tunnel side of the proxy alive.  The previous
    # HTTP/1.0 default forced a new TCP connection for every three-second
    # progress poll and made navigation feel much slower over the tunnel.
    protocol_version = 'HTTP/1.1'

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
            for key in ('Content-Type', 'Range', 'If-Range', 'If-None-Match',
                        'If-Modified-Since', 'Accept', 'Accept-Encoding', 'User-Agent'):
                if self.headers.get(key):
                    headers[key] = self.headers[key]
            if self.command == 'POST':
                headers['Origin'] = 'http://127.0.0.1:8765'
            with closing(http.client.HTTPConnection('127.0.0.1', 8765, timeout=120)) as conn:
                conn.request(self.command, self.path, body=body, headers=headers)
                response = conn.getresponse()
                response_headers = response.getheaders()
                content_type = next((value for key, value in response_headers
                                     if key.lower() == 'content-type'), '')
                content_length = next((value for key, value in response_headers
                                       if key.lower() == 'content-length'), None)
                compressible = (self.command != 'HEAD' and response.status == 200
                                 and (content_type.startswith('text/')
                                      or content_type.startswith('application/json'))
                                 and 'gzip' in self.headers.get('Accept-Encoding', '').lower())
                payload = None
                if compressible:
                    raw = response.read()
                    packed = gzip.compress(raw, compresslevel=6, mtime=0)
                    if len(packed) < len(raw):
                        payload = packed
                    else:
                        payload = raw
                self.send_response(response.status)
                for key, value in response_headers:
                    if key.lower() not in {'connection', 'transfer-encoding', 'server', 'date',
                                           'cache-control', 'content-length', 'content-encoding'}:
                        self.send_header(key, value)
                if compressible and payload is not None and len(payload) < len(raw):
                    self.send_header('Content-Encoding', 'gzip')
                    self.send_header('Vary', 'Accept-Encoding')
                if payload is not None:
                    self.send_header('Content-Length', str(len(payload)))
                elif content_length is not None:
                    self.send_header('Content-Length', content_length)
                else:
                    # An upstream response without a length cannot safely be
                    # reused under HTTP/1.1 while it is streamed to the client.
                    self.close_connection = True
                    self.send_header('Connection', 'close')
                if not self.close_connection:
                    self.send_header('Connection', 'keep-alive')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Referrer-Policy', 'same-origin')
                self.end_headers()
                if payload is not None:
                    self.wfile.write(payload)
                else:
                    while chunk := response.read(65536):
                        self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except (ValueError, OSError, http.client.HTTPException):
            self.close_connection = True

    do_GET = proxy
    do_HEAD = proxy
    do_POST = proxy


if __name__ == '__main__':
    # The gateway remains password-protected, but listens on the host's
    # network interfaces so a LAN client, router port-forward, or Tailscale
    # Funnel can use the server without a temporary tunnel-specific bind.
    ThreadingHTTPServer(('0.0.0.0', 8766), Gateway).serve_forever()
