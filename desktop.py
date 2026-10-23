"""Install a Linux launcher/icon, or activate the existing AnkiAutomata window."""

import argparse
from http.client import HTTPConnection
import os
from pathlib import Path
import shutil
import subprocess
import sys

from ipc import HOST, PORT

ROOT = Path(__file__).resolve().parent
MARKER = '# Installed by AnkiAutomata'


def quote_exec(value):
    value = str(value).replace('%', '%%')
    for character in ('\\', '"', '$', '`'):
        value = value.replace(character, '\\' + character)
    return '"' + value.replace('\\', '\\\\') + '"'


def desktop_value(value):
    return str(value).replace('\\', '\\\\').replace('\n', '\\n')


def interpreter():
    if sys.prefix != sys.base_prefix:
        return Path(sys.executable).absolute()
    for path in (ROOT / 'envAnkiAutomata/bin/python', ROOT / '.venv/bin/python'):
        if path.is_file():
            return path
    return Path(sys.executable).absolute()


def entry(icon):
    command = quote_exec(interpreter()) + ' ' + quote_exec(ROOT / 'desktop.py') + ' --launch'
    return f'''{MARKER}
[Desktop Entry]
Type=Application
Name=AnkiAutomata
GenericName=Vocabulary to Anki
Comment=Look up words and build your Anki vocabulary
Exec={command}
Path={desktop_value(ROOT)}
Icon={desktop_value(icon)}
Terminal=false
StartupNotify=false
StartupWMClass=Ankiautomata
Categories=Education;Languages;
Keywords=Anki;dictionary;vocabulary;Cambridge;
'''


def _write_entry(target, content):
    if target.exists():
        previous = target.read_text(encoding='utf-8')
        # Recognize this project's older launcher as well as entries we installed.
        if not previous.startswith(MARKER) and not ('Name=AnkiAutomata\n' in previous and str(ROOT) in previous):
            raise ValueError(f'{target} belongs to another application; it has not been changed.')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding='utf-8')
    target.chmod(0o755)


def install(data_home=None, desktop_dir=None):
    base = Path(data_home) if data_home else Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local/share')
    icon_dir = base / 'icons/hicolor/256x256/apps'
    icon_dir.mkdir(parents=True, exist_ok=True)
    icon = icon_dir / 'ankiautomata.png'
    shutil.copyfile(ROOT / 'assets/ankiautomata.png', icon)
    target = base / 'applications/ankiautomata.desktop'
    content = entry(icon)
    _write_entry(target, content)
    if shutil.which('desktop-file-validate'):
        subprocess.run(['desktop-file-validate', str(target)], check=True)
    if shutil.which('update-desktop-database'):
        subprocess.run(['update-desktop-database', str(target.parent)], capture_output=True, check=False)
    if desktop_dir is not None:
        shortcut = Path(desktop_dir) / 'AnkiAutomata.desktop'
        _write_entry(shortcut, content)
        if shutil.which('gio'):
            subprocess.run(['gio', 'set', str(shortcut), 'metadata::trusted', 'true'],
                           capture_output=True, check=False)
    return target


def launch():
    connection = HTTPConnection(HOST, PORT, timeout=3)
    try:
        connection.request('GET', '/activate')
        response = connection.getresponse()
        response.read()
        if response.status != 200:
            raise RuntimeError('Could not activate AnkiAutomata. Restart the application.')
    except ConnectionRefusedError:
        subprocess.Popen([str(interpreter()), str(ROOT / 'main.py')], cwd=ROOT, start_new_session=True)
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--launch', action='store_true', help='open or focus AnkiAutomata')
    parser.add_argument('--desktop', action='store_true', help='also add a shortcut to the desktop')
    args = parser.parse_args()
    if args.launch:
        launch()
        return
    desktop_dir = None
    if args.desktop:
        result = subprocess.run(['xdg-user-dir', 'DESKTOP'], capture_output=True, text=True, check=True)
        desktop_dir = result.stdout.strip()
        if not desktop_dir or Path(desktop_dir) == Path.home():
            raise ValueError('No desktop directory is configured. The menu launcher can be installed without --desktop.')
    print(f'Installed {install(desktop_dir=desktop_dir)}')


if __name__ == '__main__':
    main()
