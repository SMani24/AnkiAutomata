"""Local drafts and the twenty most recent lookups, separate from app configuration."""

from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile


class StateStore:
    def __init__(self, path=None):
        base = Path(os.environ.get('XDG_STATE_HOME') or Path.home() / '.local' / 'state')
        self.path = Path(path) if path is not None else base / 'AnkiAutomata' / 'state.json'
        self.history = []
        self.draft = None
        self.error = None
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(data, dict) or not isinstance(data.get('history', []), list):
                raise ValueError('Invalid saved state')
            self.history = [item for item in data.get('history', []) if self._valid(item)][:20]
            self.draft = data.get('draft') if self._valid(data.get('draft')) else None
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as error:
            self.error = str(error)

    @staticmethod
    def _valid(snapshot):
        return (isinstance(snapshot, dict) and isinstance(snapshot.get('word'), str)
                and bool(snapshot['word'].strip())
                and all(isinstance(snapshot.get(key, ''), str)
                        for key in ('definition', 'examples', 'sentence', 'deck', 'audio', 'sense', 'query'))
                and isinstance(snapshot.get('data'), (dict, type(None))))

    def save_draft(self, snapshot):
        self.draft = deepcopy(snapshot)
        if snapshot and self._valid(snapshot):
            key = snapshot['word'].casefold()
            self.history = [deepcopy(snapshot)] + [
                item for item in self.history if item['word'].casefold() != key
            ][:19]
        self._write()

    def _write(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
                                             dir=self.path.parent, delete=False) as file:
                temporary = file.name
                json.dump({'version': 1, 'history': self.history, 'draft': self.draft},
                          file, ensure_ascii=False, indent=2)
            os.replace(temporary, self.path)
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)
