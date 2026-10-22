import importlib
import unittest
from unittest.mock import Mock, patch

import requests

import engine

# Importing the UI must not require a working audio device.
with patch('pygame.mixer.init', side_effect=RuntimeError('no audio device')) as mixer_init:
    from main import AnkiAutomataApp
    AUDIO_INITIALIZED_ON_IMPORT = mixer_init.called


class AppTests(unittest.TestCase):
    def make_app(self):
        app = Mock()
        app.word_var.get.return_value = 'cat'
        app.deck_var.get.return_value = 'Default'
        app.audio_choice.get.return_value = 'us'
        return app

    def test_import_does_not_initialize_audio(self):
        self.assertFalse(AUDIO_INITIALIZED_ON_IMPORT)

    @patch.object(engine, 'scrape_cambridge', side_effect=requests.Timeout('timed out'))
    @patch.object(engine, 'is_duplicate', return_value=False)
    def test_dictionary_failure_leaves_add_disabled(self, duplicate, scrape):
        app = self.make_app()
        AnkiAutomataApp.search_word(app)
        self.assertIsNone(app.current_scraped_data)
        app.add_btn.configure.assert_called_once_with(state='disabled')
        self.assertIn('Could not reach Cambridge', app.reset_editor.call_args.args[0])

    @patch.object(engine, 'scrape_cambridge')
    @patch.object(engine, 'is_duplicate', return_value=False)
    def test_falls_back_to_uk_when_us_audio_is_missing(self, duplicate, scrape):
        app = self.make_app()
        scrape.return_value = {'word': 'cat', 'uk_audio': '/uk.mp3', 'uk_ipa': '/cat/',
                               'us_audio': None, 'us_ipa': '', 'groups': []}
        AnkiAutomataApp.search_word(app)
        app.audio_choice.set.assert_called_once_with('uk')
        app.add_btn.configure.assert_called_with(state='normal')

    def test_clipboard_error_does_not_stop_trigger_polling(self):
        app = self.make_app()
        app.search_triggered = True
        app.process_clipboard.side_effect = RuntimeError('clipboard unavailable')
        with self.assertRaises(RuntimeError):
            AnkiAutomataApp.check_triggers(app)
        app.after.assert_called_once_with(200, app.check_triggers)

    @patch('main.pyperclip.paste')
    def test_clipboard_error_is_reported(self, paste):
        import pyperclip
        paste.side_effect = pyperclip.PyperclipException('no clipboard provider')
        app = self.make_app()
        AnkiAutomataApp.process_clipboard(app)
        self.assertIn('Clipboard Error', app.log.call_args.args[0])
        app.search_word.assert_not_called()

    @patch.object(engine, 'invoke_anki', return_value='renamed.mp3')
    @patch.object(engine, 'download_audio', return_value=b'audio')
    def test_export_escapes_front_and_uses_stored_media_filename(self, download, invoke):
        app = self.make_app()
        app.current_scraped_data = {'word': '<cat>', 'us_audio': '/us.mp3',
                                    'us_ipa': '/cat/', 'headers': {}}
        app.sentence_text.get.return_value = '<cat> & dog'
        app.def_area.get.return_value = '<cat> < dog'
        app.ex_area.get.return_value = '• <cat> & dog'
        AnkiAutomataApp.confirm_and_add(app)
        note = invoke.call_args.kwargs['note']
        self.assertEqual(note['fields']['Front'], '<b>&lt;cat&gt;</b>')
        self.assertEqual(note['fields']['Pronounciation'], '/cat/ [sound:renamed.mp3]')
        self.assertIn('&lt; dog', note['fields']['Back'])
        self.assertIn('&amp; dog', note['fields']['Example sentence'])

    @patch.object(engine, 'invoke_anki')
    def test_export_without_ipa_does_not_insert_none(self, invoke):
        app = self.make_app()
        app.current_scraped_data = {'word': 'cat', 'us_audio': None}
        app.sentence_text.get.return_value = ''
        app.def_area.get.return_value = 'animal'
        app.ex_area.get.return_value = ''
        AnkiAutomataApp.confirm_and_add(app)
        note = invoke.call_args.kwargs['note']
        self.assertNotIn('None', note['fields']['Pronounciation'])

    @patch('requests.post')
    def test_importing_manual_anki_script_does_not_add_note(self, post):
        importlib.import_module('ankil_test')
        post.assert_not_called()


if __name__ == '__main__':
    unittest.main()
