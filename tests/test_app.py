import importlib
from queue import Queue
import unittest
from unittest.mock import Mock, patch

import requests

import engine

with patch('pygame.mixer.init', side_effect=RuntimeError('no audio device')) as mixer_init:
    from main import AnkiAutomataApp
    AUDIO_INITIALIZED_ON_IMPORT = mixer_init.called


class AppTests(unittest.TestCase):
    def make_app(self):
        app = Mock()
        app.word_var.get.return_value = 'cat'
        app.deck_var.get.return_value = 'Default'
        app.audio_choice.get.return_value = 'us'
        app.lookup_requests = Queue()
        app._exporting = False
        app._searching = False
        app._closing = False
        app._compact = False
        app._duplicate_notes = []
        app._search_id = 1
        app._audio_id = 1
        app._typewriter_sending = False
        return app

    def test_import_does_not_initialize_audio(self):
        self.assertFalse(AUDIO_INITIALIZED_ON_IMPORT)

    @patch.object(engine, 'scrape_cambridge')
    def test_search_schedules_network_work_without_blocking_gui(self, scrape):
        app = self.make_app()
        AnkiAutomataApp.search_word(app)
        scrape.assert_not_called()
        app.set_searching.assert_called_once_with(True)
        app.run_task.assert_called_once()

    @patch.object(engine, 'find_duplicate_notes', return_value=[])
    @patch.object(engine, 'scrape_cambridge', return_value={'word': 'cat'})
    def test_scheduled_lookup_uses_captured_word_and_deck(self, scrape, duplicates):
        app = self.make_app()
        AnkiAutomataApp.search_word(app)
        operation = app.run_task.call_args.args[0]
        app.word_var.get.return_value = 'dog'
        app.deck_var.get.return_value = 'Other'
        operation()
        scrape.assert_called_once_with('cat', None)
        duplicates.assert_called_once_with('cat', 'Default')

    def test_dictionary_failure_leaves_add_disabled(self):
        app = self.make_app()
        app.current_scraped_data = None
        AnkiAutomataApp.lookup_failed(app, 1, requests.Timeout('timed out'))
        app.reset_editor.assert_called_once()
        self.assertIsNone(app.current_scraped_data)
        self.assertIn('lookup failed', app.log.call_args.args[0])

    def test_old_lookup_result_cannot_replace_newer_word(self):
        app = self.make_app()
        app.current_scraped_data = {'word': 'newer'}
        AnkiAutomataApp.lookup_finished(app, 0, 'old', None, ({'word': 'old'}, [], None))
        self.assertEqual(app.current_scraped_data['word'], 'newer')
        app.populate_editor.assert_not_called()

    def test_dictionary_result_is_usable_when_anki_is_offline(self):
        app = self.make_app()
        data = {'word': 'cat', 'groups': []}
        AnkiAutomataApp.lookup_finished(app, 1, 'cat', None, (data, [], 'connection refused'))
        self.assertEqual(app.current_scraped_data, data)
        app.populate_editor.assert_called_once_with(data, 'cat')
        self.assertIn('Start Anki', app.log.call_args.args[0])
        app.save_draft.assert_called_once()

    def test_falls_back_to_uk_when_us_audio_is_missing(self):
        app = self.make_app()
        app.current_scraped_data = {'word': 'cat', 'uk_audio': '/uk.mp3', 'uk_ipa': '/cat/',
                                    'us_audio': None, 'us_ipa': ''}
        AnkiAutomataApp.update_audio_ui(app)
        app.audio_choice.set.assert_called_once_with('uk')

    def test_clipboard_error_does_not_stop_trigger_polling(self):
        app = self.make_app()
        app.lookup_requests.put_nowait(None)
        app.process_clipboard.side_effect = RuntimeError('clipboard unavailable')
        with self.assertRaises(RuntimeError):
            AnkiAutomataApp.check_triggers(app)
        app.after.assert_called_once_with(200, app.check_triggers)

    def test_selected_text_is_handled_on_gui_thread(self):
        app = self.make_app()
        app.lookup_requests.put_nowait('selected word')
        AnkiAutomataApp.check_triggers(app)
        app.process_text.assert_called_once_with('selected word')
        app.process_clipboard.assert_not_called()

    def test_shortcut_waits_until_export_finishes(self):
        app = self.make_app()
        app._exporting = True
        app.lookup_requests.put_nowait('selected word')
        AnkiAutomataApp.check_triggers(app)
        app.process_text.assert_not_called()
        self.assertEqual(app.lookup_requests.get_nowait(), 'selected word')

    def test_empty_lookup_queue_keeps_polling(self):
        app = self.make_app()
        AnkiAutomataApp.check_triggers(app)
        app.process_text.assert_not_called()
        app.after.assert_called_once_with(200, app.check_triggers)

    def test_selected_pdf_text_is_normalized_and_window_focused(self):
        app = self.make_app()
        AnkiAutomataApp.process_text(app, '  selected\n word  ')
        app.word_var.set.assert_called_once_with('selected word')
        app.activate_window.assert_called_once()
        app.search_word.assert_called_once()

    @patch('main.pyperclip.paste')
    def test_clipboard_error_is_reported(self, paste):
        import pyperclip
        paste.side_effect = pyperclip.PyperclipException('no clipboard provider')
        app = self.make_app()
        AnkiAutomataApp.process_clipboard(app)
        self.assertIn('Clipboard Error', app.log.call_args.args[0])
        app.search_word.assert_not_called()

    def test_export_failure_preserves_editable_draft(self):
        app = self.make_app()
        app.current_scraped_data = {'word': 'cat'}
        app.snapshot.return_value = {'word': 'cat', 'definition': 'animal', 'deck': 'Default'}
        AnkiAutomataApp.confirm_and_add(app)
        failure = app.run_task.call_args.args[2]
        failure(RuntimeError('Anki offline'))
        self.assertEqual(app.current_scraped_data['word'], 'cat')
        app.set_exporting.assert_called_with(False)
        app.reset_editor.assert_not_called()
        self.assertIn('draft is safe', app.log.call_args.args[0])

    def test_confirm_cannot_start_second_export(self):
        app = self.make_app()
        app._exporting = True
        AnkiAutomataApp.confirm_and_add(app)
        app.run_task.assert_not_called()

    def test_duplicate_blocks_export_and_offers_existing_note(self):
        app = self.make_app()
        app.current_scraped_data = {'word': 'cat'}
        app._duplicate_notes = [{'noteId': 42}]
        AnkiAutomataApp.confirm_and_add(app)
        app.run_task.assert_not_called()
        AnkiAutomataApp.set_duplicates(app, [{'noteId': 42}])
        app.duplicate_frame.grid.assert_called_once()

    def test_restore_draft_reinstates_edits_and_rechecks_duplicates(self):
        app = self.make_app()
        snapshot = {'word': 'cat', 'definition': 'my definition', 'examples': 'my example',
                    'sentence': 'my sentence', 'deck': 'Vocabulary', 'audio': 'uk',
                    'data': {'word': 'cat'}, 'sense': '1. animal'}
        AnkiAutomataApp.restore_snapshot(app, snapshot)
        app.def_area.insert.assert_called_once_with('1.0', 'my definition')
        app.ex_area.insert.assert_called_once_with('1.0', 'my example')
        app.sentence_text.insert.assert_called_once_with('1.0', 'my sentence')
        app.deck_var.set.assert_called_once_with('Vocabulary')
        app.recheck_duplicates.assert_called_once()

    @patch('requests.post')
    def test_importing_manual_anki_script_does_not_add_note(self, post):
        importlib.import_module('ankil_test')
        post.assert_not_called()


if __name__ == '__main__':
    unittest.main()
