"""Local lookup requests; the GUI consumes the queue on its own thread."""

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from queue import Full

HOST = '127.0.0.1'
PORT = 24536
MAX_TEXT_BYTES = 4096


class LookupServer(HTTPServer):
    def __init__(self, lookup_requests, address=(HOST, PORT)):
        self.lookup_requests = lookup_requests
        super().__init__(address, LookupHandler)

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(2)
        return connection, address


class LookupHandler(BaseHTTPRequestHandler):
    def reply(self, status, message, content_type='text/plain; charset=utf-8'):
        body = message.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def enqueue(self, text):
        try:
            self.server.lookup_requests.put_nowait(text)
        except Full:
            self.reply(429, 'Lookup queue is full')
        else:
            self.reply(200, 'Lookup queued')

    def do_GET(self):
        if self.path == '/health':
            self.reply(200, json.dumps({'app': 'ankiautomata', 'api_version': 1,
                                       'capabilities': ['lookup', 'sentence', 'activate']}), 'application/json')
            return
        if self.path == '/activate':
            self.enqueue({'action': 'activate'})
            return
        if self.path != '/':
            self.reply(404, 'Not found')
            return
        # Preserve the original curl/clipboard trigger.
        self.enqueue(None)

    def do_POST(self):
        if self.path != '/lookup':
            self.reply(404, 'Not found')
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= MAX_TEXT_BYTES:
                self.reply(413, 'Selection is empty or too long')
                return
            payload = json.loads(self.rfile.read(length))
            text = payload.get('text') if isinstance(payload, dict) else None
            if not isinstance(text, str) or not text.strip():
                raise ValueError('Missing text')
            sentence = payload.get('sentence')
            if 'sentence' in payload and not isinstance(sentence, str):
                raise ValueError('Sentence must be text')
        except (ValueError, UnicodeError):
            self.reply(400, 'Expected JSON containing nonempty text')
            return
        text = ' '.join(text.split())
        self.enqueue({'text': text, 'sentence': ' '.join(sentence.split())} if sentence is not None else text)

    def log_message(self, format, *args):
        pass
