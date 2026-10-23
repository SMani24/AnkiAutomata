import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import socketserver
import tempfile
from threading import Thread
import unittest
from unittest.mock import Mock, patch

import requests

import audio_sources
import engine
import network


class ProxySettingsTests(unittest.TestCase):
    def test_credentials_are_encoded_and_ipv6_is_bracketed(self):
        values = {**network.DEFAULTS, 'enabled': True, 'host': '[::1]',
                  'username': 'a@b', 'password': 'p:q/#'}
        with network.session(values) as session:
            self.assertFalse(session.trust_env)
            self.assertEqual(session.proxies['https'], 'socks5h://a%40b:p%3Aq%2F%23@[::1]:10808')
            self.assertEqual(session.proxies['http'], session.proxies['https'])

    def test_validation_rejects_invalid_connection_details(self):
        for key, value in (('host', 'http://127.0.0.1'), ('host', 'localhost:1080'), ('host', ''),
                           ('host', 'bad host'), ('port', 0), ('port', 65536), ('port', True),
                           ('type', 'ftp'), ('username', 'name\nsecret'), ('enabled', 'true')):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                network.validate_settings({**network.DEFAULTS, key: value})

    def test_settings_are_atomic_private_and_separate_from_repo_config(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings' / 'network.json'
            values = {**network.DEFAULTS, 'enabled': True, 'username': 'user', 'password': 'secret'}
            network.save_settings(values, path)
            self.assertEqual(network.load_settings(path), values)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with patch.object(network.os, 'replace', side_effect=OSError('secret-file-name')):
                with self.assertRaisesRegex(network.NetworkError, 'Could not save'):
                    network.save_settings({**values, 'port': 80}, path)
            self.assertEqual(network.load_settings(path), values)
            self.assertEqual(list(path.parent.iterdir()), [path])
            self.assertNotEqual(path, engine.CONFIG_FILE)

    def test_bad_saved_settings_do_not_silently_disable_proxy(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'network.json'
            path.write_text('{"enabled": true, "port": "bad"}')
            with self.assertRaises(network.NetworkError):
                network.load_settings(path)
            path.unlink()
            self.assertEqual(network.load_settings(path), network.DEFAULTS)

    @patch.dict(os.environ, {'HTTP_PROXY': 'http://invalid:1', 'HTTPS_PROXY': 'http://invalid:1',
                             'ALL_PROXY': 'socks5://invalid:1', 'NO_PROXY': '*'})
    def test_disabled_proxy_and_local_requests_ignore_environment(self):
        with network.session(network.DEFAULTS) as session:
            self.assertFalse(session.trust_env)
            self.assertEqual(session.proxies, {})
        for url in ('http://localhost:8080', 'http://127.0.0.1:8765', 'http://[::1]:8080'):
            with self.subTest(url=url), patch.object(network, 'load_settings', side_effect=AssertionError('must stay local')), \
                 patch.object(network.requests.Session, 'request', return_value=Mock()) as request:
                network.get(url)
                request.assert_called_once()

    @patch.object(network, 'load_settings', return_value={**network.DEFAULTS, 'enabled': True})
    def test_proxy_failures_hide_credentials_and_never_retry_direct(self, settings):
        with patch.object(network.requests.Session, 'request', side_effect=requests.exceptions.ProxyError('secret@proxy')) as request:
            with self.assertRaises(network.NetworkError) as error:
                network.get('https://dictionary.cambridge.org/')
        self.assertNotIn('secret', str(error.exception))
        self.assertIn('through the proxy', str(error.exception))
        self.assertEqual(request.call_count, 1)

    @patch.object(network.requests.Session, 'request', side_effect=requests.Timeout('secret'))
    def test_timeout_has_a_safe_actionable_message(self, request):
        with self.assertRaisesRegex(network.NetworkError, 'timed out') as error:
            network.get('https://dictionary.cambridge.org/', settings=network.DEFAULTS)
        self.assertNotIn('secret', str(error.exception))

    @patch.object(network, 'get')
    def test_connection_test_uses_unsaved_values_and_closes_response(self, get):
        get.return_value = Mock(status_code=200)
        values = {**network.DEFAULTS, 'enabled': True, 'port': 1234}
        self.assertEqual(network.test_connection(values), 'Connected through your proxy.')
        self.assertEqual(get.call_args.kwargs['settings']['port'], 1234)
        self.assertTrue(get.call_args.kwargs['stream'])
        get.return_value.close.assert_called_once()
        get.return_value = Mock(status_code=407)
        with self.assertRaisesRegex(network.NetworkError, 'authentication'):
            network.test_connection(values)
        get.return_value.close.assert_called_once()

    def test_all_dictionary_and_audio_requests_use_shared_transport(self):
        with patch.object(network, 'request') as request:
            request.return_value = Mock(status_code=404)
            engine.scrape_cambridge('necessary')
            self.assertEqual(request.call_args.args[0], 'GET')
            engine.download_audio('https://dictionary.cambridge.org/audio.mp3', {})
            self.assertIn('audio.mp3', request.call_args.args[1])
            response = Mock(status_code=200)
            response.iter_content.return_value = [b'content']
            request.return_value = response
            for url in ('https://www.oxfordlearnersdictionaries.com/definition/english/necessary',
                        'https://en.wiktionary.org/wiki/necessary', 'https://commons.wikimedia.org/w/api.php',
                        'https://api.dictionaryapi.dev/api/v2/entries/en/necessary'):
                audio_sources.AudioSources().read(url)
                self.assertEqual(request.call_args.args[1], url)
                self.assertTrue(request.call_args.kwargs['stream'])

    @patch.object(network, 'post')
    def test_anki_is_always_direct(self, post):
        post.return_value.json.return_value = {'result': [], 'error': None}
        engine.invoke_anki('deckNames')
        self.assertTrue(post.call_args.kwargs['direct'])


class ProxyIntegrationTests(unittest.TestCase):
    def server(self, server_type, handler):
        server = server_type(('127.0.0.1', 0), handler)
        server.daemon_threads = True
        thread = Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.shutdown)
        return server

    def test_http_proxy_carries_requests_and_loopback_stays_direct(self):
        seen = []
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                seen.append((self.path, self.headers.get('Proxy-Authorization')))
                self.send_response(200)
                self.send_header('Content-Length', '5')
                self.end_headers()
                self.wfile.write(b'works')
            def log_message(self, *args):
                pass
        proxy = self.server(ThreadingHTTPServer, Handler)
        values = {**network.DEFAULTS, 'enabled': True, 'type': 'http',
                  'port': proxy.server_port, 'username': 'a@b', 'password': 'p:q'}
        with patch.dict(os.environ, {'NO_PROXY': '*', 'HTTP_PROXY': 'http://invalid:1'}):
            response = network.get('http://dictionary.invalid/lookup', settings=values, stream=True)
            self.assertEqual(response.content, b'works')
            response.close()
            self.assertEqual(seen[0], ('http://dictionary.invalid/lookup',
                                      'Basic ' + base64.b64encode(b'a@b:p:q').decode()))
            response = network.get(f'http://127.0.0.1:{proxy.server_port}/local', settings=values)
            response.close()
            self.assertEqual(seen[1], ('/local', None))

    def test_socks5_resolves_target_hostname_at_proxy(self):
        seen = []
        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                version, methods = self.rfile.read(2)
                self.rfile.read(methods)
                self.wfile.write(b'\x05\x00')
                request = self.rfile.read(4)
                if request != b'\x05\x01\x00\x03':
                    return
                length = self.rfile.read(1)[0]
                seen.append((self.rfile.read(length).decode(), int.from_bytes(self.rfile.read(2), 'big')))
                self.wfile.write(b'\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00')
                while self.rfile.readline() not in (b'\r\n', b''):
                    pass
                self.wfile.write(b'HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\nworks')
        proxy = self.server(socketserver.ThreadingTCPServer, Handler)
        values = {**network.DEFAULTS, 'enabled': True, 'port': proxy.server_address[1]}
        response = network.get('http://dictionary.invalid/lookup', settings=values)
        self.assertEqual(response.content, b'works')
        response.close()
        self.assertEqual(seen, [('dictionary.invalid', 80)])


if __name__ == '__main__':
    unittest.main()
