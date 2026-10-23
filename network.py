"""Explicit internet routing shared by dictionary lookups and audio downloads."""
import ipaddress
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import quote, urlparse

import requests

DEFAULTS = {'enabled': False, 'type': 'socks5h', 'host': '127.0.0.1', 'port': 10808,
            'username': '', 'password': ''}
PROTOCOLS = {'SOCKS5 (proxy DNS)': 'socks5h', 'HTTP': 'http'}


class NetworkError(RuntimeError):
    pass


def settings_path():
    base = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config')
    return base / 'AnkiAutomata' / 'network.json'


def validate_settings(values):
    result = {key: values.get(key, default) for key, default in DEFAULTS.items()}
    if type(result['enabled']) is not bool:
        raise ValueError('Choose whether to enable the proxy.')
    if result['type'] not in PROTOCOLS.values():
        raise ValueError('Choose HTTP or SOCKS5 for the proxy protocol.')
    host = result['host']
    if not isinstance(host, str):
        raise ValueError('Enter a proxy hostname or IP address, without a URL prefix.')
    host = host.strip()
    if host.startswith('[') and host.endswith(']'):
        host = host[1:-1]
    if ':' in host:
        try:
            ipaddress.IPv6Address(host)
        except ValueError:
            raise ValueError('Enter a valid IPv6 proxy address.') from None
    elif not re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9.-]{0,251}[a-zA-Z0-9.])?', host):
        raise ValueError('Enter a proxy hostname or IP address, without a URL prefix or port.')
    result['host'] = host
    if type(result['port']) is not int or not 1 <= result['port'] <= 65535:
        raise ValueError('Proxy port must be a whole number between 1 and 65535.')
    for key in ('username', 'password'):
        value = result[key]
        if not isinstance(value, str) or len(value) > 200 or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError('Proxy credentials must be text of at most 200 characters, without control characters.')
    if result['password'] and not result['username']:
        raise ValueError('Enter a username when using a proxy password.')
    return result


def load_settings(path=None):
    path = Path(path) if path is not None else settings_path()
    try:
        values = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(values, dict):
            raise ValueError()
        return validate_settings(values)
    except FileNotFoundError:
        return dict(DEFAULTS)
    except (OSError, ValueError, TypeError):
        raise NetworkError('Could not read network settings. Open Settings → Network and save your proxy settings again.') from None


def save_settings(values, path=None):
    values = validate_settings(values)
    path = Path(path) if path is not None else settings_path()
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # NamedTemporaryFile uses owner-only permissions, including after replacement.
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as file:
            temporary = file.name
            json.dump(values, file, indent=2)
        os.replace(temporary, path)
    except OSError:
        raise NetworkError('Could not save network settings. Check that your local configuration folder is writable.') from None
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
    return values


def is_loopback(url):
    host = urlparse(url).hostname or ''
    if host.lower().rstrip('.') == 'localhost' or host.lower().rstrip('.').endswith('.localhost'):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def session(settings=None, direct=False):
    values = dict(DEFAULTS) if direct else validate_settings(settings) if settings is not None else load_settings()
    client = requests.Session()
    # App settings control the route, regardless of HTTP_PROXY, NO_PROXY, or .netrc.
    client.trust_env = False
    if values['enabled']:
        host = values['host']
        if ':' in host:
            host = f'[{host}]'
        auth = ''
        if values['username']:
            auth = quote(values['username'], safe='') + ':' + quote(values['password'], safe='') + '@'
        proxy = f'{values["type"]}://{auth}{host}:{values["port"]}'
        client.proxies = {'http': proxy, 'https': proxy}
    return client


def request(method, url, *, settings=None, direct=False, **kwargs):
    direct = direct or is_loopback(url)
    kwargs.setdefault('timeout', (5, 15))
    with session(settings, direct=direct) as client:
        try:
            return client.request(method, url, **kwargs)
        except requests.Timeout:
            raise NetworkError('The connection timed out. Check your internet connection or proxy in Settings → Network.') from None
        except requests.RequestException:
            # Requests exceptions can contain proxy credentials. Do not log or display them.
            message = ('Could not connect through the proxy. Check its protocol, host, port, and authentication.'
                       if client.proxies else 'Could not connect. Check your connection and Settings → Network.')
            raise NetworkError(message) from None


def get(url, **kwargs):
    return request('GET', url, **kwargs)


def post(url, **kwargs):
    return request('POST', url, **kwargs)


def test_connection(settings):
    settings = validate_settings(settings)
    response = get('https://dictionary.cambridge.org/robots.txt', settings=settings,
                   stream=True, allow_redirects=False, timeout=(5, 10))
    try:
        if response.status_code == 407:
            raise NetworkError('The proxy requires authentication. Check your username and password.')
        if not 200 <= response.status_code < 400:
            raise NetworkError(f'Reached the network route, but Cambridge returned HTTP {response.status_code}.')
        return 'Connected through your proxy.' if settings['enabled'] else 'Direct internet connection is working.'
    finally:
        response.close()
