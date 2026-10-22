"""Optional GUI checks: xvfb-run -a envAnkiAutomata/bin/python tests/gui_smoke.py."""

from pathlib import Path
import sys
import tempfile
from threading import Event
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import engine
from main import AnkiAutomataApp
from storage import StateStore


def dictionary_entry(word='serendipity'):
    return {'word': word, 'definition': 'a happy discovery',
            'groups': [{'pos': 'noun', 'guideword': 'DISCOVERY',
                        'definitions': ['a happy discovery'], 'examples': [f'A little {word}.']}],
            'examples_raw': [f'A little {word}.'],
            'uk_audio': '/uk.mp3', 'us_audio': None, 'uk_ipa': '/test/', 'us_ipa': '', 'headers': {}}


class GuiSmokeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.state_path = Path(self.directory.name) / 'state.json'
        self.preferences = {'font_scale': 'Normal (100%)', 'window_width': 1040, 'window_height': 900}
        self.patches = [patch.dict(engine.config, preferences=self.preferences),
                        patch('main.StateStore', side_effect=lambda: StateStore(self.state_path)),
                        patch.object(engine, 'save_preference'), patch.object(engine, 'save_preferences'),
                        patch.object(engine, 'find_duplicate_notes', return_value=[]),
                        patch.object(AnkiAutomataApp, 'start_local_server')]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        self.callback_errors = []
        self.app = self.create_app()

    def create_app(self):
        app = AnkiAutomataApp()
        app.report_callback_exception = lambda *args: self.callback_errors.append(args)
        app.update()
        return app

    def tearDown(self):
        if not self.app._closing:
            self.app.on_closing()
        self.assertEqual(self.callback_errors, [])

    def pump_until(self, predicate, timeout=3):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            self.app.update()
            time.sleep(0.005)
        self.assertTrue(predicate(), 'GUI did not reach expected state')
        self.app.update()

    def show_word(self, word='serendipity'):
        self.app.current_scraped_data = dictionary_entry(word)
        self.app.word_var.set(word)
        self.app.populate_editor(self.app.current_scraped_data, word)
        self.app.update_audio_ui()
        self.app.refresh_add_state()
        self.app.update()

    def test_slow_lookup_keeps_event_loop_responsive(self):
        release = Event()
        self.addCleanup(release.set)
        def slow(word, url):
            release.wait(2)
            return dictionary_entry(word)
        with patch.object(engine, 'scrape_cambridge', side_effect=slow):
            self.app.word_var.set('serendipity')
            self.app.search_word()
            heartbeat = []
            self.app.after(0, lambda: heartbeat.append(True))
            self.pump_until(lambda: bool(heartbeat))
            self.assertTrue(self.app._searching)
            release.set()
            self.pump_until(lambda: not self.app._searching)
        self.assertEqual(self.app.word_header.cget('text'), 'serendipity')
        self.assertEqual(self.app.add_btn.cget('state'), 'normal')

    def test_slow_old_result_does_not_replace_new_lookup(self):
        release = Event()
        self.addCleanup(release.set)
        def scrape(word, url):
            if word == 'old':
                release.wait(2)
            return dictionary_entry(word)
        with patch.object(engine, 'scrape_cambridge', side_effect=scrape):
            self.app.word_var.set('old')
            self.app.search_word()
            self.app.word_var.set('new')
            self.app.search_word()
            self.pump_until(lambda: self.app.current_scraped_data is not None)
            self.assertEqual(self.app.current_scraped_data['word'], 'new')
            release.set()
            deadline = time.monotonic() + 0.15
            self.pump_until(lambda: time.monotonic() > deadline)
        self.assertEqual(self.app.word_header.cget('text'), 'new')

    def test_edits_are_recovered_after_closing_and_reopening(self):
        self.show_word()
        self.app.def_area.delete('1.0', 'end')
        self.app.def_area.insert('1.0', 'my edited definition')
        self.app.sentence_text.insert('1.0', 'my original sentence')
        self.app.on_closing()
        self.app = self.create_app()
        self.pump_until(lambda: not self.app._searching)
        self.assertEqual(self.app.def_area.get('1.0', 'end-1c'), 'my edited definition')
        self.assertEqual(self.app.sentence_text.get('1.0', 'end-1c'), 'my original sentence')

    def test_compact_mode_preserves_content_and_restores_geometry(self):
        self.show_word()
        definition = self.app.def_area.get('1.0', 'end-1c')
        self.app.toggle_compact()
        self.app.update()
        self.assertEqual(self.app.winfo_width(), 640)
        self.assertFalse(self.app.context_frame.winfo_ismapped())
        self.assertGreater(self.app.ex_area.winfo_height(), 30)
        self.app.toggle_compact()
        self.app.update()
        self.assertEqual(self.app.winfo_width(), 1040)
        self.assertTrue(self.app.context_frame.winfo_ismapped())
        self.assertEqual(self.app.def_area.get('1.0', 'end-1c'), definition)

    def test_splitter_preserves_space_for_examples(self):
        self.show_word()
        self.app._on_splitter_press(SimpleNamespace(y_root=0))
        self.app._on_splitter_drag(SimpleNamespace(y_root=10000))
        self.app.update()
        self.assertGreaterEqual(self.app.ex_area.winfo_height(), 75)

    def test_successful_export_clears_draft_and_retains_history(self):
        self.show_word()
        with patch.object(engine, 'export_note', return_value={'note_id': 123, 'warnings': []}) as export:
            self.app.confirm_and_add()
            self.assertTrue(self.app._exporting)
            self.pump_until(lambda: not self.app._exporting)
        export.assert_called_once()
        self.assertIsNone(self.app.store.draft)
        self.assertEqual(self.app.store.history[0]['word'], 'serendipity')
        self.assertEqual(self.app.add_btn.cget('state'), 'disabled')

    def test_export_failure_keeps_editors_and_draft(self):
        self.show_word()
        with patch.object(engine, 'export_note', side_effect=RuntimeError('Anki unavailable')):
            self.app.confirm_and_add()
            self.pump_until(lambda: not self.app._exporting)
        self.assertEqual(self.app.def_area.cget('state'), 'normal')
        self.assertIsNotNone(self.app.current_scraped_data)
        self.assertIsNotNone(self.app.store.draft)

    def test_control_enter_exports_without_inserting_an_example_bullet(self):
        self.show_word()
        examples = self.app.ex_area.get('1.0', 'end-1c')
        with patch.object(engine, 'export_note', return_value={'note_id': 123, 'warnings': []}) as export:
            self.app.ex_area._textbox.focus_force()
            self.app.ex_area._textbox.event_generate('<Control-Return>')
            self.pump_until(lambda: export.called and not self.app._exporting)
        self.assertEqual(export.call_args.args[0]['examples'], examples)

    def test_duplicate_banner_and_large_font_compact_layout(self):
        self.show_word()
        self.app.on_font_scale_changed('XL (145%)')
        self.app.toggle_compact()
        note = {'noteId': 42, 'fields': {'Back': {'value': '<b>an existing happy discovery</b>'}}}
        self.app.set_duplicates([note])
        self.app.update()
        self.assertTrue(self.app.duplicate_frame.winfo_ismapped())
        self.assertEqual(self.app.add_btn.cget('state'), 'disabled')
        self.assertGreater(self.app.ex_area.winfo_height(), 20)
        self.assertTrue(self.app.open_note_btn.winfo_ismapped())


if __name__ == '__main__':
    unittest.main(verbosity=2)
