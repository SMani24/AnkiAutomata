"""Search selected text from a Linux desktop shortcut without changing the clipboard."""

import argparse
import ast
from http.client import HTTPConnection
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

from ipc import HOST, MAX_TEXT_BYTES, PORT

ROOT = Path(__file__).resolve().parent
MEDIA_KEYS = 'org.gnome.settings-daemon.plugins.media-keys'
CUSTOM_BINDING = MEDIA_KEYS + '.custom-keybinding'
BINDING_PATH = '/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/ankiautomata/'
SHORTCUT_NAME = 'AnkiAutomata Search'
DEFAULT_BINDING = '<Control><Alt>w'


def selected_text():
    if os.environ.get('XDG_SESSION_TYPE') == 'wayland' or os.environ.get('WAYLAND_DISPLAY'):
        command = ['wl-paste', '--primary', '--no-newline']
    else:
        command = ['xclip', '-selection', 'primary', '-out']
    if not shutil.which(command[0]):
        raise RuntimeError(f'Install {command[0]} to read highlighted text on this desktop.')
    result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8',
                            timeout=3, check=False)
    if result.returncode:
        raise RuntimeError('Could not read the selection. Highlight a word in your PDF reader first.')
    text = ' '.join(result.stdout.split())
    if not text:
        raise RuntimeError('No text selected. Highlight a word in your PDF reader first.')
    if len(json.dumps({'text': text}, ensure_ascii=False).encode('utf-8')) > MAX_TEXT_BYTES:
        raise RuntimeError('Selection is too long. Highlight a word or short phrase.')
    return text


def send_lookup(text, sentence=None):
    connection = HTTPConnection(HOST, PORT, timeout=3)
    try:
        payload = {'text': text}
        if sentence is not None:
            payload['sentence'] = sentence
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        if len(body) > MAX_TEXT_BYTES:
            raise ValueError('The word and sentence together must fit within 4 KB.')
        connection.request('POST', '/lookup', body=body,
                           headers={'Content-Type': 'application/json; charset=utf-8'})
        response = connection.getresponse()
        message = response.read().decode('utf-8')
        if response.status != 200:
            raise RuntimeError(f'Lookup failed: {message}')
    finally:
        connection.close()


def search_selection(text=None, sentence=None):
    # Capture first: starting or focusing the GUI can change the desktop selection.
    text = selected_text() if text is None else text.strip()
    if not text:
        raise ValueError('Enter a nonempty word or phrase.')
    try:
        if sentence is None:
            send_lookup(text)
        else:
            send_lookup(text, sentence)
    except ConnectionRefusedError:
        command = [sys.executable, str(ROOT / 'main.py'), f'--lookup={text}']
        if sentence is not None:
            command.append(f'--sentence={sentence}')
        subprocess.Popen(command,
                         cwd=ROOT, start_new_session=True)


def _setting(schema, key):
    result = subprocess.run(['gsettings', 'get', schema, key], capture_output=True,
                            text=True, check=True, timeout=5)
    return ast.literal_eval(result.stdout.strip().removeprefix('@as '))


def _set_setting(schema, key, value):
    subprocess.run(['gsettings', 'set', schema, key, json.dumps(value)],
                   check=True, timeout=5)


def install_shortcut():
    """Reuse the old AnkiAutomata binding and preserve all unrelated shortcuts."""
    paths = _setting(MEDIA_KEYS, 'custom-keybindings')
    path = next((p for p in paths if _setting(f'{CUSTOM_BINDING}:{p}', 'name') == SHORTCUT_NAME),
                BINDING_PATH)
    schema = f'{CUSTOM_BINDING}:{path}'
    command = shlex.join([sys.executable, str(ROOT / 'shortcut.py')])
    if path in paths:
        _set_setting(schema, 'command', command)
        return _setting(schema, 'binding')
    for existing in paths:
        binding = _setting(f'{CUSTOM_BINDING}:{existing}', 'binding')
        if binding.replace('<Primary>', '<Control>').lower() == DEFAULT_BINDING.lower():
            raise RuntimeError('Ctrl+Alt+W is already assigned. Add a custom shortcut in Keyboard Settings.')
    _set_setting(schema, 'name', SHORTCUT_NAME)
    _set_setting(schema, 'command', command)
    _set_setting(schema, 'binding', DEFAULT_BINDING)
    _set_setting(MEDIA_KEYS, 'custom-keybindings', paths + [path])
    return DEFAULT_BINDING


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install', action='store_true', help='install or repair the GNOME/Pop!_OS shortcut')
    parser.add_argument('--text', help='look up supplied text instead of the desktop selection')
    parser.add_argument('--sentence', help='sentence context to send with the lookup')
    args = parser.parse_args()
    try:
        if args.install:
            binding = install_shortcut()
            print(f'AnkiAutomata shortcut installed: {binding}')
        else:
            search_selection(args.text, args.sentence)
    except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as error:
        print(f'AnkiAutomata: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
