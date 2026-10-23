"""Explicit, local-only exports to Typewriter's existing token-protected API."""

import re
import unicodedata
from urllib.parse import urlparse

from bs4 import BeautifulSoup
import requests


def prepare_word(snapshot):
    word = ' '.join(unicodedata.normalize('NFKC', snapshot['word']).lower().split())
    if len(word) > 80 or not re.fullmatch(r"[a-z]+(?:[ '\-][a-z]+)*", word):
        raise ValueError('Typewriter accepts English words and short phrases up to 80 characters.')
    definition = snapshot.get('definition', '').strip()
    sentence = snapshot.get('sentence', '').strip()
    pattern = re.compile(r'(?<!\w)' + re.escape(word) + r'(?!\w)', re.IGNORECASE)
    if not sentence:
        sentence = next((line.lstrip('• ').strip() for line in snapshot.get('examples', '').splitlines()
                         if pattern.search(line)), '')
    if sentence and not pattern.search(sentence):
        raise ValueError('Your sentence must contain the exact word before sending it to Typewriter.')
    if len(definition) > 2000 or len(sentence) > 2000:
        raise ValueError('Typewriter accepts up to 2,000 characters per definition or sentence. Shorten the selection first.')
    return {'word': word, 'definition': definition, 'sentence': sentence, 'tag': 'AnkiAutomata'}


def send_word(item, base_url='http://127.0.0.1:8080'):
    parsed = urlparse(base_url)
    if (parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost', '::1')
            or parsed.username or parsed.password or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
        raise ValueError('Typewriter must use a local HTTP address, such as http://127.0.0.1:8080.')
    base_url = base_url.rstrip('/')
    with requests.Session() as session:
        session.trust_env = False
        def get(path):
            response = session.get(base_url + path, timeout=(3, 10), allow_redirects=False)
            response.raise_for_status()
            if response.is_redirect:
                raise ValueError('Unexpected redirect from Typewriter. Check its local address.')
            return response
        if get('/api/health').json().get('app') != 'typewriter':
            raise ValueError('The selected address is not a Typewriter server.')
        meta = BeautifulSoup(get('/').text, 'html.parser').select_one('meta[name="typewriter-token"]')
        token = meta.get('content') if meta else None
        if not isinstance(token, str) or not token:
            raise ValueError('Typewriter did not provide its local request token. Restart Typewriter and try again.')
        response = session.post(base_url + '/api/words', json={'words': [item]},
                                headers={'X-Typewriter-Token': token, 'Origin': base_url},
                                timeout=(3, 10), allow_redirects=False)
        result = response.json()
        if response.status_code != 201:
            raise ValueError(result.get('error', 'Typewriter could not save this word.'))
        if not isinstance(result.get('added'), list) or not isinstance(result.get('duplicates'), list):
            raise ValueError('Unexpected response from Typewriter.')
        if not result['added'] and not result['duplicates']:
            raise ValueError('Typewriter did not confirm saving this word.')
        return result
