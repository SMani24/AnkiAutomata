"""Exact-word pronunciation sources, bounded downloads, and recording credits.

Adapted from Typewriter's audio_sources/audio_metadata without its notebook database.
"""
import hashlib
import json
import re
import unicodedata
from datetime import datetime
from html import escape
from urllib.parse import parse_qs, quote, unquote, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup
import network

ALTERNATIVE_PROVIDERS = ('oxford', 'wiktionary', 'free_dictionary')
PROVIDERS = ('cambridge', *ALTERNATIVE_PROVIDERS)
LABELS = {
    'cambridge': 'Cambridge Dictionary',
    'oxford': 'Oxford Learner’s Dictionaries',
    'wiktionary': 'Wiktionary · Wikimedia Commons',
    'free_dictionary': 'Free Dictionary API · Wikimedia Commons',
}
LOOKUP_HOSTS = ('www.oxfordlearnersdictionaries.com', 'en.wiktionary.org',
                'commons.wikimedia.org', 'api.dictionaryapi.dev')
AGENT = 'AnkiAutomata/1.0 (personal dictionary lookup; https://github.com/SMani24/AnkiAutomata)'


def normalize_word(word):
    return ' '.join(unicodedata.normalize('NFKC', word).casefold().split())


def canonical_url(value):
    if not isinstance(value, str) or len(value) > 2000 or any(c.isspace() for c in value):
        raise ValueError('Invalid pronunciation URL.')
    parsed = urlparse('https:' + value if value.startswith('//') else value)
    if (parsed.scheme != 'https' or parsed.username or parsed.password or
            parsed.port not in (None, 443) or not parsed.hostname):
        raise ValueError('Use a supported HTTPS pronunciation source.')
    return urlunparse(parsed._replace(query='', fragment=''))


def allowed_url(value, provider, kind='media'):
    value = canonical_url(value)
    parsed = urlparse(value)
    host, path = parsed.hostname, parsed.path
    if kind == 'media':
        allowed = (
            provider == 'cambridge' and host == 'dictionary.cambridge.org' or
            provider == 'oxford' and host == 'www.oxfordlearnersdictionaries.com' and
            path.startswith('/media/english/') or
            provider in ('wiktionary', 'free_dictionary') and host == 'upload.wikimedia.org' and
            path.startswith('/wikipedia/commons/'))
        if not allowed or not path.lower().endswith(('.mp3', '.ogg', '.wav')):
            raise ValueError('Unsupported pronunciation recording source.')
    else:
        allowed = (
            provider == 'cambridge' and host == 'dictionary.cambridge.org' and
            path.startswith('/dictionary/english/') or
            provider == 'oxford' and host == 'www.oxfordlearnersdictionaries.com' and
            path.startswith('/definition/english/') or
            provider in ('wiktionary', 'free_dictionary') and host == 'commons.wikimedia.org' and
            path.startswith('/wiki/File:'))
        if not allowed:
            raise ValueError('Unsupported pronunciation reference page.')
    return value


def candidate_id(url):
    return hashlib.sha256(canonical_url(url).encode()).hexdigest()[:32]


def validate_record(data, word):
    if (not isinstance(data, dict) or data.get('version') != 1 or
            data.get('provider') not in PROVIDERS or data.get('word') != word):
        raise ValueError('Unsupported alternative pronunciation metadata.')
    provider = data['provider']
    url = allowed_url(data.get('url'), provider)
    if data.get('id') != candidate_id(url) or data.get('accent') not in ('uk', 'us', 'au', 'other', 'unknown'):
        raise ValueError('Invalid alternative pronunciation identity.')
    source = allowed_url(data.get('source_url'), provider, 'source')
    result = {key: data[key] for key in ('version', 'id', 'word', 'provider', 'accent')}
    result.update(url=url, source_url=source, label=LABELS[provider])
    for field, limit in (('author', 500), ('license_name', 120)):
        value = data.get(field, '')
        if not isinstance(value, str) or len(value) > limit:
            raise ValueError('Invalid recording attribution.')
        result[field] = value
    license_url = data.get('license_url', '')
    if provider in ('wiktionary', 'free_dictionary'):
        license_url = canonical_url(license_url)
        license_page = urlparse(license_url)
        if (license_page.hostname != 'creativecommons.org' or
                not license_page.path.startswith(('/licenses/', '/publicdomain/'))):
            raise ValueError('Missing supported recording license.')
        if not result['author'] or not result['license_name']:
            raise ValueError('Missing recording attribution.')
    elif license_url:
        license_url = allowed_url(license_url, provider, 'source')
    result['license_url'] = license_url
    if 'selection' in data:
        if data['selection'] != 'manual':
            raise ValueError('Invalid pronunciation selection method.')
        result['selection'] = data['selection']
    if 'approved_at' in data:
        try:
            if datetime.fromisoformat(data['approved_at']).tzinfo is None:
                raise ValueError()
        except (ValueError, TypeError):
            raise ValueError('Invalid pronunciation approval date.') from None
        result['approved_at'] = data['approved_at']
    return result


def filename_matches(word, filename):
    pattern = r'(?<![a-z])' + re.escape(word).replace(r'\ ', r'[ _-]+') + r'(?![a-z])'
    return bool(re.search(pattern, unquote(filename).casefold()))


class AudioSources:
    def read(self, url, params=None, media_provider=None, limit=2*1024*1024):
        # Validate every redirect, including those returned by media hosts.
        for _ in range(4):
            if media_provider:
                url = allowed_url(url, media_provider)
            else:
                parsed = urlparse(url)
                if (parsed.scheme != 'https' or parsed.hostname not in LOOKUP_HOSTS or
                        parsed.username or parsed.password or parsed.port not in (None, 443)):
                    raise ValueError('Unsupported pronunciation lookup source.')
            agent = ('Mozilla/5.0 (compatible; AnkiAutomata personal dictionary lookup)'
                     if urlparse(url).hostname == LOOKUP_HOSTS[0] else AGENT)
            response = network.get(url, params=params, stream=True, allow_redirects=False,
                                    timeout=(5, 12), headers={'User-Agent': agent})
            try:
                if response.status_code in (301, 302, 303, 307, 308):
                    url = urljoin(url, response.headers.get('Location', ''))
                    params = None
                    continue
                if response.status_code == 404:
                    return None, url
                if response.status_code != 200:
                    raise ValueError('This pronunciation source is unavailable right now.')
                chunks, size = [], 0
                for chunk in response.iter_content(65536):
                    size += len(chunk)
                    if size > limit:
                        raise ValueError('The pronunciation response is too large.')
                    chunks.append(chunk)
                return b''.join(chunks), url
            except requests.RequestException:
                raise ValueError('The pronunciation download was interrupted. Try the next voice.') from None
            finally:
                response.close()
        raise ValueError('This pronunciation source redirected too many times.')

    @staticmethod
    def record(word, provider, url, accent, source, author='', license_name='Publisher recording', license_url=''):
        url = canonical_url(url)
        return validate_record({
            'version': 1, 'id': candidate_id(url), 'word': word, 'provider': provider,
            'url': url, 'accent': accent, 'source_url': source, 'author': author,
            'license_name': license_name, 'license_url': license_url,
        }, word)

    @staticmethod
    def oxford(word, html, url):
        soup = BeautifulSoup(html, 'html.parser')
        result = []
        for heading in soup.select('h1.headword'):
            if normalize_word(heading.get_text(' ', strip=True)) != word:
                continue
            container = heading.find_parent(class_='top-container')
            if not container:
                continue
            for node in container.select('.sound[data-src-mp3]'):
                classes = node.get('class', [])
                accent = 'uk' if 'pron-uk' in classes else 'us' if 'pron-us' in classes else 'unknown'
                try:
                    result.append(AudioSources.record(
                        word, 'oxford', urljoin(url, node['data-src-mp3']), accent, url,
                        'Oxford University Press', license_url=url))
                except ValueError:
                    continue
        return result

    @staticmethod
    def wiki_titles(word, html):
        soup = BeautifulSoup(html, 'html.parser')
        title = soup.select_one('#firstHeading,.mw-page-title-main')
        if not title or normalize_word(title.get_text(' ', strip=True)) != word:
            return []
        heading = soup.select_one('h2#English, h2:has(#English)')
        if not heading:
            return []
        titles = []
        for node in heading.find_all_next(['h2', 'audio']):
            if node.name == 'h2':
                break
            name = node.get('data-mwtitle', '')
            if (node.find_parent(class_='audiotable') and filename_matches(word, name) and
                    name.lower().endswith(('.mp3', '.ogg', '.wav'))):
                titles.append('File:' + name)
        return list(dict.fromkeys(titles))[:8]

    def commons(self, titles=None, pageids=None):
        params = {'action': 'query', 'prop': 'imageinfo', 'iiprop': 'url|extmetadata', 'format': 'json',
                  'iiextmetadatafilter': 'Artist|LicenseShortName|LicenseUrl'}
        params['titles' if titles else 'pageids'] = '|'.join(titles or pageids)
        content, _ = self.read('https://commons.wikimedia.org/w/api.php', params=params)
        if not content:
            return []
        pages = json.loads(content).get('query', {}).get('pages', {})
        result = []
        for page in pages.values():
            for info in page.get('imageinfo', []):
                metadata = info.get('extmetadata', {})
                def text(field):
                    value = str(metadata.get(field, {}).get('value', ''))
                    return BeautifulSoup('<span>' + value + '</span>', 'html.parser').get_text(' ', strip=True)
                result.append({
                    'url': info.get('url'), 'source_url': info.get('descriptionurl'), 'title': page.get('title', ''),
                    'author': text('Artist'), 'license_name': text('LicenseShortName'),
                    'license_url': text('LicenseUrl').replace('http://', 'https://', 1),
                })
        return result

    @staticmethod
    def accent(filename):
        name = unquote(filename).casefold()
        for accent, tokens in (('uk', 'uk|gb|rp'), ('us', 'us'), ('au', 'au')):
            if re.search(r'(?:^|[ _-])(?:' + tokens + r')(?:[ _.-]|$)', name):
                return accent
        return 'unknown'

    def wiki_records(self, word, metadata, provider):
        records = []
        for info in metadata:
            if not filename_matches(word, info['title']):
                continue
            try:
                records.append(self.record(
                    word, provider, info['url'], self.accent(info['title']), info['source_url'],
                    info['author'], info['license_name'], info['license_url']))
            except ValueError:
                continue
        return records

    def fetch(self, word, provider):
        target = normalize_word(word)
        if provider not in ALTERNATIVE_PROVIDERS:
            raise ValueError('Choose a supported pronunciation source.')
        if provider == 'oxford':
            url = 'https://www.oxfordlearnersdictionaries.com/definition/english/' + quote(target.replace(' ', '-'), safe='')
            content, final = self.read(url)
            return self.oxford(target, content, final) if content else []
        if provider == 'wiktionary':
            content, _ = self.read('https://en.wiktionary.org/wiki/' + quote(target.replace(' ', '_'), safe=''))
            titles = self.wiki_titles(target, content) if content else []
            return self.wiki_records(target, self.commons(titles=titles), provider) if titles else []
        content, _ = self.read('https://api.dictionaryapi.dev/api/v2/entries/en/' + quote(target, safe=''))
        payload = json.loads(content) if content else []
        ids = []
        if isinstance(payload, list):
            for entry in payload[:10]:
                if not isinstance(entry, dict) or normalize_word(entry.get('word', '')) != target:
                    continue
                for phonetic in entry.get('phonetics', [])[:10]:
                    parsed = urlparse(phonetic.get('sourceUrl', ''))
                    identity = parse_qs(parsed.query).get('curid', [''])[0]
                    if (phonetic.get('audio') and parsed.scheme == 'https' and
                            parsed.hostname == 'commons.wikimedia.org' and identity.isdigit()):
                        ids.append(identity)
        ids = list(dict.fromkeys(ids))[:8]
        return self.wiki_records(target, self.commons(pageids=ids), provider) if ids else []

    def recording(self, record):
        record = validate_record(record, record['word'])
        content, _ = self.read(record['url'], media_provider=record['provider'], limit=5*1024*1024)
        extension = urlparse(record['url']).path.lower().rsplit('.', 1)[-1]
        valid = content and (
            extension == 'mp3' and (content.startswith(b'ID3') or
                                    len(content) > 2 and content[0] == 255 and content[1] & 224 == 224) or
            extension == 'ogg' and content.startswith(b'OggS') or
            extension == 'wav' and content[:4] == b'RIFF' and content[8:12] == b'WAVE')
        if not valid:
            raise ValueError('This source did not return an audio recording. Try the next voice.')
        return content


def selected_record(data, word=None):
    record = data.get('selected_audio')
    if not record:
        return None
    record = validate_record(record, normalize_word(word if word is not None else data['word']))
    if record.get('selection') != 'manual' or not record.get('approved_at'):
        raise ValueError('Preview and choose this recording before saving it.')
    if record['id'] in data.get('rejected_audio', []):
        raise ValueError('This recording was rejected. Choose another voice.')
    return record


def regional_url(data, region):
    url = data.get(f'{region}_audio')
    if url and data.get('rejected_audio') and candidate_id(url) in data['rejected_audio']:
        return None
    return url


def attribution(record):
    source = f'<a href="{escape(record["source_url"], quote=True)}">{escape(record["label"])}</a>'
    credit = escape(record['author'])
    license_name = escape(record['license_name'])
    if record['license_url']:
        license_name = f'<a href="{escape(record["license_url"], quote=True)}">{license_name}</a>'
    return f'<small>Audio: {source} · {credit} · {license_name}</small>'
