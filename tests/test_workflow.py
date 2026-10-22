from pathlib import Path
import tempfile
from threading import get_ident
import time
import unittest
from unittest.mock import Mock, patch

from background import BackgroundTasks
import engine
from storage import StateStore


def sample(word='cat'):
    return {'word': word, 'query': word, 'definition': f'{word} < dog',
            'examples': f'• {word} & dog', 'sentence': f'{word} & dog',
            'deck': 'Default', 'audio': 'us', 'sense': '1. animal',
            'data': {'word': word, 'us_audio': '/us.mp3', 'us_ipa': '/cat/', 'headers': {}}}


class DuplicateTests(unittest.TestCase):
    @patch.object(engine, 'invoke_anki')
    def test_examples_and_partial_front_matches_are_not_duplicates(self, invoke):
        invoke.side_effect = [[1, 2, 3], [
            {'noteId': 1, 'fields': {'Front': {'value': 'dog'}, 'Back': {'value': 'a cat'}}},
            {'noteId': 2, 'fields': {'Front': {'value': '<b>catapult</b>'}}},
            {'noteId': 3, 'fields': {'Front': {'value': '<b>CAT</b>'}}}]]
        self.assertEqual([note['noteId'] for note in engine.find_duplicate_notes('cat', 'Default')], [3])
        query = invoke.call_args_list[0].kwargs['query']
        self.assertIn('"Front:cat"', query)
        self.assertIn('"deck:Default"', query)

    @patch.object(engine, 'invoke_anki', return_value=[])
    def test_search_quotes_decks_phrases_and_literal_wildcards(self, invoke):
        engine.find_duplicate_notes('a*b_"c', 'English::My "Words"')
        query = invoke.call_args.kwargs['query']
        self.assertIn('"Front:a\\*b\\_\\"c"', query)
        self.assertIn('"deck:English::My \\"Words\\""', query)
        invoke.assert_called_once()

    @patch.object(engine, 'invoke_anki')
    def test_open_existing_note_uses_note_id(self, invoke):
        engine.open_notes([{'noteId': 42}])
        invoke.assert_called_once_with('guiBrowse', query='nid:42')


class ExportTests(unittest.TestCase):
    def test_build_note_escapes_text_and_preserves_indentation(self):
        snapshot = sample('<cat>')
        snapshot['definition'] = 'heading\n   <cat> < dog'
        note = engine.build_note(snapshot, 'renamed.mp3')
        self.assertEqual(note['fields']['Front'], '<b>&lt;cat&gt;</b>')
        self.assertEqual(note['fields']['Pronounciation'], '/cat/ [sound:renamed.mp3]')
        self.assertIn('&amp; dog', note['fields']['Example sentence'])
        self.assertIn('&nbsp;' * 6 + '<b>&lt;cat&gt;</b>', note['fields']['Back'])
        self.assertFalse(note['options']['allowDuplicate'])
        self.assertEqual(note['options']['duplicateScope'], 'deck')

    def test_missing_ipa_does_not_insert_none(self):
        snapshot = sample()
        snapshot['data'] = {}
        self.assertEqual(engine.build_note(snapshot)['fields']['Pronounciation'], '')

    @patch.object(engine, 'find_duplicate_notes', return_value=[{'noteId': 42}])
    @patch.object(engine, 'invoke_anki')
    @patch.object(engine, 'download_audio')
    def test_duplicate_recheck_prevents_media_upload_and_add(self, audio, invoke, duplicates):
        self.assertEqual(engine.export_note(sample()), {'duplicates': [{'noteId': 42}]})
        audio.assert_not_called()
        invoke.assert_not_called()

    @patch.object(engine, 'find_duplicate_notes', return_value=[])
    @patch.object(engine, 'invoke_anki', side_effect=['renamed.mp3', 123])
    @patch.object(engine, 'download_audio', return_value=b'audio')
    def test_export_uses_actual_stored_media_filename(self, audio, invoke, duplicates):
        self.assertEqual(engine.export_note(sample())['note_id'], 123)
        note = invoke.call_args.kwargs['note']
        self.assertIn('[sound:renamed.mp3]', note['fields']['Pronounciation'])

    @patch.object(engine, 'find_duplicate_notes', return_value=[])
    @patch.object(engine, 'invoke_anki', return_value=123)
    @patch.object(engine, 'download_audio', side_effect=RuntimeError('audio unavailable'))
    def test_audio_failure_is_reported_after_successful_add(self, audio, invoke, duplicates):
        result = engine.export_note(sample())
        self.assertEqual(result['note_id'], 123)
        self.assertIn('audio unavailable', result['warnings'][0])
        self.assertNotIn('[sound:', invoke.call_args.kwargs['note']['fields']['Pronounciation'])


class StateTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'state.json'

    def test_edits_survive_reopening(self):
        store = StateStore(self.path)
        snapshot = sample('déjà vu')
        store.save_draft(snapshot)
        reopened = StateStore(self.path)
        self.assertEqual(reopened.draft, snapshot)
        self.assertEqual(reopened.history, [snapshot])

    def test_history_is_limited_and_latest_edit_replaces_previous(self):
        store = StateStore(self.path)
        for number in range(25):
            store.save_draft(sample(f'word {number}'))
        revised = sample('WORD 24')
        revised['definition'] = 'my edit'
        store.save_draft(revised)
        self.assertEqual(len(store.history), 20)
        self.assertEqual(store.history[0]['definition'], 'my edit')
        self.assertEqual(store.history[-1]['word'], 'word 5')

    def test_clearing_successful_draft_keeps_history(self):
        store = StateStore(self.path)
        store.save_draft(sample())
        store.save_draft(None)
        reopened = StateStore(self.path)
        self.assertIsNone(reopened.draft)
        self.assertEqual(reopened.history[0]['word'], 'cat')

    def test_snapshots_are_independent_of_editor_mutations(self):
        store = StateStore(self.path)
        snapshot = sample()
        store.save_draft(snapshot)
        snapshot['data']['word'] = 'changed'
        self.assertEqual(store.draft['data']['word'], 'cat')

    def test_corrupt_state_does_not_prevent_startup(self):
        for contents in ('broken JSON', '[]', '{"history": "bad"}'):
            self.path.write_text(contents)
            store = StateStore(self.path)
            self.assertIsNotNone(store.error)
            self.assertIsNone(store.draft)

    def test_failed_write_preserves_previous_draft(self):
        store = StateStore(self.path)
        store.save_draft(sample())
        with patch('storage.os.replace', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                store.save_draft(sample('new'))
        self.assertEqual(StateStore(self.path).draft['word'], 'cat')
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])


class BackgroundTests(unittest.TestCase):
    def setUp(self):
        self.tasks = BackgroundTasks(workers=1)
        self.addCleanup(self.tasks.close)

    def wait_for_result(self):
        deadline = time.monotonic() + 2
        while self.tasks.results.empty() and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertFalse(self.tasks.results.empty(), 'background operation did not complete')

    def test_work_runs_off_gui_thread_and_callbacks_wait_for_poll(self):
        main_thread = get_ident()
        success, failure = Mock(), Mock()
        self.tasks.submit(get_ident, success, failure)
        self.wait_for_result()
        success.assert_not_called()
        self.tasks.poll()
        self.assertNotEqual(success.call_args.args[0], main_thread)
        failure.assert_not_called()

    def test_worker_error_is_delivered_to_gui(self):
        success, failure = Mock(), Mock()
        def fail():
            raise RuntimeError('network unavailable')
        self.tasks.submit(fail, success, failure)
        self.wait_for_result()
        self.tasks.poll()
        success.assert_not_called()
        self.assertIsInstance(failure.call_args.args[0], RuntimeError)

    def test_closed_window_discards_pending_callbacks(self):
        callback = Mock()
        self.tasks.submit(lambda: 'done', callback, callback)
        self.wait_for_result()
        self.tasks.close()
        self.tasks.poll()
        callback.assert_not_called()


if __name__ == '__main__':
    unittest.main()
