"""Optional check against Typewriter source using an isolated temporary notebook.

Run using Typewriter's Python environment:
  ../Typewriter/.venv/bin/python tests/typewriter_integration.py --typewriter-root ../Typewriter
"""
import argparse
from pathlib import Path
import sys
import tempfile
from threading import Thread

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--typewriter-root', type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.typewriter_root.resolve()))
    from typewriter.web import create_app
    from werkzeug.serving import make_server
    from typewriter_client import prepare_word, send_word
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory)
        app = create_app(data_dir=path / 'notebook', keys_path=path / 'no-api-keys', background=False)
        server = make_server('127.0.0.1', 0, app)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            address = f'http://127.0.0.1:{server.server_port}'
            item = prepare_word({'word': 'serendipity', 'definition': 'a happy discovery',
                                 'sentence': 'It was pure serendipity.'})
            result = send_word(item, address)
            assert len(result['added']) == 1 and not result['duplicates']
            identity = result['added'][0]
            store = app.extensions['store']
            store.edit_word(identity, {'definition': 'an existing personal definition'})
            before = store.word(identity)
            again = send_word(item, address)
            assert again == {'added': [], 'duplicates': ['serendipity']}
            after = store.word(identity)
            assert all(after[key] == before[key] for key in ('definition', 'stage', 'due', 'created'))
            assert len(store.list_words()) == 1
            print('Typewriter integration passed: token handshake, import, duplicate detection, and progress preservation.')
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == '__main__':
    main()
