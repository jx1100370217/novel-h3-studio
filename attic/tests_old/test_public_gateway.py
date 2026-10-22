import base64
import http.client
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.parse import urlencode

from novel_h3.public_gateway import (Gateway, SESSION_COOKIE, SESSION_SECONDS,
                                      create_session, local_return, valid_session)

Connection = http.client.HTTPConnection


class GatewayAuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.credentials = {'username': 'test-user', 'password': 'test-password'}
        path = Path(self.temp.name) / 'credentials.json'
        path.write_text(json.dumps(self.credentials))
        credentials_patch = patch('novel_h3.public_gateway.CREDENTIALS', path)
        credentials_patch.start()
        self.addCleanup(credentials_patch.stop)
        self.upstream = MagicMock()
        self.upstream.getresponse.return_value.status = 200
        self.upstream.getresponse.return_value.getheaders.return_value = [
            ('Content-Type', 'application/json'), ('Content-Length', '14')]
        self.upstream.getresponse.return_value.read.side_effect = [b'{"ready":true}', b'']
        upstream_patch = patch('novel_h3.public_gateway.http.client.HTTPConnection', return_value=self.upstream)
        upstream_patch.start()
        self.addCleanup(upstream_patch.stop)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Gateway)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, path, method='GET', body=None, **headers):
        headers = {'Host': 'workbench.example', **headers}
        connection = Connection('127.0.0.1', self.server.server_port, timeout=5)
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return result

    def login(self, password='test-password', origin='https://workbench.example', next_path='/?view=progress'):
        return self.request('/login', 'POST', urlencode({'username': 'test-user', 'password': password,
            'next': next_path}), **{'Origin': origin, 'Content-Type': 'application/x-www-form-urlencoded'})

    def test_browser_navigation_goes_to_login_without_basic_auth_challenge(self):
        status, headers, body = self.request('/?view=progress')
        self.assertEqual(status, 303)
        self.assertEqual(headers['Location'], '/login?next=%2F%3Fview%3Dprogress')
        self.assertNotIn('WWW-Authenticate', headers)
        status, headers, body = self.request(headers['Location'])
        self.assertEqual(status, 200)
        self.assertIn('登录影视制片工作台'.encode(), body)
        self.assertNotIn(self.credentials['password'].encode(), body)
        self.assertNotIn('WWW-Authenticate', headers)
        self.upstream.request.assert_not_called()

    def test_wrong_login_stays_on_form_without_session(self):
        status, headers, body = self.login(password='wrong')
        self.assertEqual(status, 200)
        self.assertNotIn('Set-Cookie', headers)
        self.assertIn('账号或密码不正确'.encode(), body)
        self.assertNotIn('WWW-Authenticate', headers)

    def test_existing_private_lan_login_remains_usable(self):
        status, headers, _ = self.request('/login', 'POST', urlencode(self.credentials),
            Host='192.168.1.10:8766', Origin='http://192.168.1.10:8766',
            **{'Content-Type': 'application/x-www-form-urlencoded'})
        self.assertEqual(status, 303)
        self.assertIn('HttpOnly', headers['Set-Cookie'])
        self.assertNotIn('; Secure', headers['Set-Cookie'])

    def test_valid_login_cookie_authorizes_progress_and_native_media(self):
        status, headers, _ = self.login(next_path='/?view=review')
        self.assertEqual(status, 303)
        self.assertEqual(headers['Location'], '/?view=review')
        cookie = headers['Set-Cookie']
        for flag in ('HttpOnly', 'Secure', 'SameSite=Strict', 'Path=/'):
            self.assertIn(flag, cookie)
        self.assertNotIn('test-password', cookie)
        status, _, body = self.request('/api/production-progress', Cookie=cookie.split(';')[0])
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {'ready': True})
        self.upstream.request.assert_called_once()
        self.assertNotIn('Cookie', self.upstream.request.call_args.kwargs['headers'])

    def test_unauthenticated_api_and_media_remain_private(self):
        for path in ('/api/production-progress', '/media?path=review.mp4'):
            status, headers, body = self.request(path)
            self.assertEqual(status, 401)
            self.assertNotIn('WWW-Authenticate', headers)
            self.assertIn('error', json.loads(body))
        self.upstream.request.assert_not_called()

    def test_basic_api_clients_continue_to_work(self):
        auth = 'Basic ' + base64.b64encode(b'test-user:test-password').decode()
        self.assertEqual(self.request('/api/production-progress', Authorization=auth)[0], 200)

    def test_cross_site_login_and_workbench_mutations_are_blocked(self):
        self.assertEqual(self.login(origin='https://other.example')[0], 403)
        cookie = SESSION_COOKIE + '=' + create_session(self.credentials)
        status, _, _ = self.request('/api/video-control', 'POST', '{}',
            Cookie=cookie, Origin='https://other.example', **{'Content-Type': 'application/json'})
        self.assertEqual(status, 403)
        self.upstream.request.assert_not_called()

    def test_session_tampering_expiry_and_password_change_invalidate_access(self):
        with patch('novel_h3.public_gateway.time.time', return_value=1000):
            token = create_session(self.credentials)
            self.assertTrue(valid_session(self.credentials, token))
            self.assertFalse(valid_session(self.credentials, token + 'x'))
            self.assertFalse(valid_session(dict(self.credentials, password='changed'), token))
        with patch('novel_h3.public_gateway.time.time', return_value=1000 + SESSION_SECONDS):
            self.assertFalse(valid_session(self.credentials, token))
        status, _, _ = self.request('/api/production-progress', Cookie=SESSION_COOKIE + '=invalid')
        self.assertEqual(status, 401)
        self.upstream.request.assert_not_called()

    def test_return_url_cannot_redirect_offsite_or_inject_headers(self):
        for value in ('https://other.example', '//other.example', '/\\other.example', '/\r\nSet-Cookie: bad=1'):
            self.assertEqual(local_return(value), '/?view=progress')
        self.assertEqual(local_return('/?view=review'), '/?view=review')
        self.assertEqual(self.login(next_path='//other.example')[1]['Location'], '/?view=progress')


if __name__ == '__main__': unittest.main()
