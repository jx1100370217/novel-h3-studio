"""Password-protected proxy for the complete local workbench."""
import base64
from contextlib import closing
import gzip
import hashlib
import html
import hmac
import http.client
import ipaddress
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import CookieError, SimpleCookie
from pathlib import Path
import secrets
import time
from urllib.parse import parse_qs, urlencode, urlsplit

CREDENTIALS = Path(__file__).resolve().parents[1]/'runtime/public-workbench-credentials.json'
SESSION_COOKIE = 'novel_workbench_session'
SESSION_SECONDS = 8 * 60 * 60


def session_signature(credentials, payload):
    key = hashlib.sha256((credentials['username'] + '\0' + credentials['password']).encode()).digest()
    return hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()


def create_session(credentials):
    payload = str(int(time.time()) + SESSION_SECONDS) + '.' + secrets.token_urlsafe(24)
    return payload + '.' + session_signature(credentials, payload)


def valid_session(credentials, token):
    try:
        expiry, nonce, signature = token.split('.')
        return (int(time.time()) < int(expiry) <= int(time.time()) + SESSION_SECONDS
                and hmac.compare_digest(signature, session_signature(credentials, expiry + '.' + nonce)))
    except (ValueError, TypeError):
        return False


def local_return(value):
    return value if (value.startswith('/') and not value.startswith('//')
                     and not any(ord(c) < 32 or c == '\\' for c in value)
                     and not urlsplit(value).scheme) else '/?view=progress'


class Gateway(BaseHTTPRequestHandler):
    # Keep the browser/public-tunnel side of the proxy alive.  The previous
    # HTTP/1.0 default forced a new TCP connection for every three-second
    # progress poll and made navigation feel much slower over the tunnel.
    protocol_version = 'HTTP/1.1'

    def log_message(self, *args):
        pass

    def respond(self, status, body=b'', *, content_type='text/html; charset=utf-8', headers=()):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Referrer-Policy', 'same-origin')
        self.send_header('X-Content-Type-Options', 'nosniff')
        if self.command == 'POST':
            self.close_connection = True
            self.send_header('Connection', 'close')
        for key, value in headers:
            self.send_header(key, value)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def valid_origin(self):
        host = self.headers.get('Host', '')
        hostname = urlsplit('//' + host).hostname
        try:
            local = ipaddress.ip_address(hostname).is_private
        except ValueError:
            local = hostname == 'localhost'
        origin = self.headers.get('Origin')
        return origin == 'https://' + host or local and origin == 'http://' + host

    def login_page(self, next_path, error=''):
        target = html.escape(local_return(next_path), quote=True)
        message = html.escape(error)
        page = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>登录影视制片工作台</title>
<style>html{{color-scheme:dark;background:#0b110e;color:#f4f2e9;font:16px/1.7 system-ui}}body{{margin:0;min-height:100vh;display:grid;place-items:center}}main{{width:min(360px,85vw);padding:32px;border:1px solid #476052;border-radius:18px;background:#142019}}h1{{font-size:24px;color:#edcf98}}label{{display:block;margin:16px 0 6px}}input,button{{box-sizing:border-box;width:100%;padding:12px;border:1px solid #476052;border-radius:8px;font:inherit}}input{{background:#0b110e;color:inherit}}button{{margin-top:24px;background:#d9ae67;color:#182019;cursor:pointer}}.muted{{color:#9aaba0;font-size:14px}}.error{{color:#f2a399}}</style>
<main><h1>登录影视制片工作台</h1><p class="muted">使用工作台现有账号密码，查看实时制作进度与章节视频。</p>
<form method="post" action="/login"><input type="hidden" name="next" value="{target}">
<label for="username">账号</label><input id="username" name="username" autocomplete="username" required autofocus>
<label for="password">密码</label><input id="password" name="password" type="password" autocomplete="current-password" required>
<p class="error" role="alert">{message}</p><button type="submit">登录工作台</button></form></main></html>'''
        self.respond(200, page.encode(), headers=(('Content-Security-Policy', "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"),))

    def login(self, credentials):
        if not self.valid_origin():
            return self.respond(403, b'Forbidden')
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 8192 or self.headers.get('Transfer-Encoding'):
                return self.respond(413, b'Payload too large')
            if self.headers.get('Content-Type', '').split(';')[0] != 'application/x-www-form-urlencoded':
                return self.respond(415, b'Unsupported form type')
            fields = parse_qs(self.rfile.read(size).decode(), keep_blank_values=True)
        except (ValueError, UnicodeError):
            return self.respond(400, b'Invalid login form')
        next_path = local_return(fields.get('next', ['/?view=progress'])[0])
        username, password = fields.get('username', [''])[0], fields.get('password', [''])[0]
        if not (hmac.compare_digest(username.encode(), credentials['username'].encode())
                and hmac.compare_digest(password.encode(), credentials['password'].encode())):
            return self.login_page(next_path, '账号或密码不正确，请重新输入。')
        secure = '; Secure' if self.headers.get('Origin', '').startswith('https://') else ''
        cookie = f'{SESSION_COOKIE}={create_session(credentials)}; Path=/; HttpOnly; SameSite=Strict{secure}'
        return self.respond(303, headers=(('Location', next_path), ('Set-Cookie', cookie)))

    def proxy(self):
        credentials = json.loads(CREDENTIALS.read_text())
        if not self.path.startswith('/') or self.path.startswith('//') or urlsplit(self.path).scheme:
            self.send_error(400)
            return
        url = urlsplit(self.path)
        if url.path == '/login':
            if self.command == 'POST':
                return self.login(credentials)
            return self.login_page(parse_qs(url.query).get('next', ['/?view=progress'])[0])
        expected = 'Basic ' + base64.b64encode(
            (credentials['username'] + ':' + credentials['password']).encode()).decode()
        cookies = SimpleCookie()
        try:
            cookies.load(self.headers.get('Cookie', ''))
        except CookieError:
            cookies = SimpleCookie()
        session = cookies.get(SESSION_COOKIE)
        if not (hmac.compare_digest(self.headers.get('Authorization', ''), expected)
                or session and valid_session(credentials, session.value)):
            if url.path.startswith(('/api/', '/media')) or self.command == 'POST':
                return self.respond(401, json.dumps({'error': '请先登录工作台'}, ensure_ascii=False).encode(),
                                    content_type='application/json; charset=utf-8')
            return self.respond(303, headers=(('Location', '/login?' + urlencode({'next': local_return(self.path)})),))
        if self.command == 'POST':
            if not self.valid_origin():
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
