from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import audio_sources as audio
import engine
from storage import StateStore


SOURCE = 'https://commons.wikimedia.org/wiki/File:En-us-necessary.ogg'
MEDIA = 'https://upload.wikimedia.org/wikipedia/commons/1/15/En-us-necessary.ogg'
CAMBRIDGE = 'https://dictionary.cambridge.org/media/english/uk_pron/necessary.mp3'


def recording(word='necessary'):
    return audio.AudioSources.record(word, 'wiktionary', MEDIA, 'us', SOURCE,
                                     'Example speaker', 'CC BY-SA 4.0',
                                     'https://creativecommons.org/licenses/by-sa/4.0/')


def approved(word='necessary'):
    return {**recording(word), 'selection': 'manual', 'approved_at': '2026-10-23T12:00:00+00:00'}


def snapshot():
    return {'word': 'necessary', 'definition': 'needed', 'examples': '', 'sentence': '',
            'deck': 'Default', 'audio': 'uk',
            'data': {'word': 'necessary', 'uk_audio': CAMBRIDGE, 'uk_ipa': '/cambridge/',
                     'selected_audio': approved()}}


def response(content=b'OggSrecording', status=200, headers=None):
    result = Mock(status_code=status, headers=headers or {})
    result.iter_content.return_value = [content]
    return result


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.sources = audio.AudioSources()

    def test_metadata_is_bound_to_the_exact_word(self):
        with self.assertRaises(ValueError):
            audio.validate_record(recording(), 'necessity')
        with self.assertRaises(ValueError):
            audio.selected_record({'word': 'necessary', 'selected_audio': recording()})
        self.assertEqual(audio.selected_record(snapshot()['data'])['id'], recording()['id'])

    def test_rejected_approval_cannot_be_used(self):
        data = snapshot()['data']
        data['rejected_audio'] = [recording()['id']]
        with self.assertRaisesRegex(ValueError, 'rejected'):
            audio.selected_record(data)

    def test_metadata_requires_supported_media_and_credits(self):
        for field, value in [('url', 'https://example.com/voice.ogg'),
                             ('url', MEDIA.replace('https://', 'http://')),
                             ('url', MEDIA.replace('.org/', '.org:8080/')),
                             ('url', MEDIA.replace('https://', 'https://user:secret@')),
                             ('source_url', 'https://example.com/page'),
                             ('license_url', 'https://example.com/license'),
                             ('author', ''), ('license_name', ''), ('approved_at', '2026-10-23')]:
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                audio.validate_record({**approved(), field: value}, 'necessary')

    def test_oxford_does_not_accept_a_redirected_base_word(self):
        html = '''<div class="top-container"><h1 class="headword">high</h1>
        <div class="sound pron-uk" data-src-mp3="/media/english/high.mp3"></div></div>'''
        url = 'https://www.oxfordlearnersdictionaries.com/definition/english/high'
        self.assertEqual(self.sources.oxford('highest', html, url), [])
        records = self.sources.oxford('high', html, url)
        self.assertEqual(records[0]['accent'], 'uk')
        self.assertEqual(records[0]['author'], 'Oxford University Press')

    def test_wiktionary_uses_only_exact_word_audio_in_english_section(self):
        html = '''<h1 id="firstHeading">highest</h1><h2><span id="English">English</span></h2>
        <table class="audiotable"><tr><td><audio data-mwtitle="En-us-high.ogg"></audio>
        <audio data-mwtitle="En-us-highest.ogg"></audio></td></tr></table>
        <h2 id="German">German</h2><table class="audiotable"><audio data-mwtitle="De-highest.ogg"></audio></table>'''
        self.assertEqual(self.sources.wiki_titles('highest', html), ['File:En-us-highest.ogg'])
        self.assertEqual(self.sources.wiki_titles('high', html), [])

    def test_wiktionary_current_heading_and_multiword_filename(self):
        html = '''<h1 id="firstHeading">ice cream</h1><div class="mw-heading"><h2 id="English">English</h2></div>
        <table class="audiotable"><audio data-mwtitle="En-us-ice_cream.ogg"></audio></table>'''
        self.assertEqual(self.sources.wiki_titles('ice cream', html), ['File:En-us-ice_cream.ogg'])

    def test_commons_metadata_is_plain_text_and_requires_matching_filename(self):
        payload = {'query': {'pages': {'1': {'title': 'File:En-us-necessary.ogg', 'imageinfo': [{
            'url': MEDIA, 'descriptionurl': SOURCE, 'extmetadata': {
                'Artist': {'value': '<a href="/speaker">Example speaker</a>'},
                'LicenseShortName': {'value': 'CC BY-SA 4.0'},
                'LicenseUrl': {'value': 'http://creativecommons.org/licenses/by-sa/4.0/'}}}]}}}}
        with patch.object(self.sources, 'read', return_value=(json.dumps(payload), 'url')):
            metadata = self.sources.commons(titles=['File:En-us-necessary.ogg'])
        records = self.sources.wiki_records('necessary', metadata, 'wiktionary')
        self.assertEqual(records[0]['author'], 'Example speaker')
        self.assertEqual(records[0]['accent'], 'us')
        self.assertEqual(self.sources.wiki_records('necessity', metadata, 'wiktionary'), [])

    def test_free_dictionary_resolves_credited_commons_files_for_exact_word(self):
        payload = [{'word': 'necessity', 'phonetics': [{'audio': MEDIA, 'sourceUrl': 'https://commons.wikimedia.org/?curid=1'}]},
                   {'word': 'necessary', 'phonetics': [
                       {'audio': 'https://example.com/unknown.mp3'},
                       {'audio': MEDIA, 'sourceUrl': 'https://commons.wikimedia.org/?curid=2'}]}]
        with patch.object(self.sources, 'read', return_value=(json.dumps(payload), 'url')), \
             patch.object(self.sources, 'commons', return_value=[]) as commons:
            self.assertEqual(self.sources.fetch('Necessary', 'free_dictionary'), [])
        commons.assert_called_once_with(pageids=['2'])

    @patch.object(audio.network, 'get')
    def test_redirects_cannot_escape_provider_hosts(self, get):
        redirect = response(status=302, headers={'Location': 'https://127.0.0.1/private'})
        get.return_value = redirect
        with self.assertRaises(ValueError):
            self.sources.recording(recording())
        self.assertEqual(get.call_count, 1)
        redirect.close.assert_called_once()
        self.assertFalse(get.call_args.kwargs['allow_redirects'])

    @patch.object(audio.network, 'get')
    def test_audio_download_is_bounded_and_checks_the_file_format(self, get):
        for content in (b'<html>unavailable</html>', b'ID3wrong extension', b'x' * (5*1024*1024 + 1)):
            get.return_value = response(content)
            with self.subTest(size=len(content)), self.assertRaises(ValueError):
                self.sources.recording(recording())
            get.return_value.close.assert_called_once()
        get.return_value = response()
        self.assertEqual(self.sources.recording(recording()), b'OggSrecording')

    @patch.object(audio.network, 'get')
    def test_missing_provider_entry_returns_no_options(self, get):
        get.return_value = response(status=404)
        self.assertEqual(self.sources.fetch('nonexistent', 'oxford'), [])
        get.return_value.close.assert_called_once()


class AlternativeExportTests(unittest.TestCase):
    @patch.object(engine, 'find_duplicate_notes', return_value=[])
    @patch.object(engine, 'invoke_anki', side_effect=['renamed.ogg', 123])
    @patch.object(audio.AudioSources, 'recording', return_value=b'OggSrecording')
    @patch.object(engine, 'download_audio')
    def test_export_uses_chosen_recording_format_and_attribution(self, original, download, invoke, duplicates):
        result = engine.export_note(snapshot())
        self.assertEqual(result['note_id'], 123)
        original.assert_not_called()
        download.assert_called_once_with(approved() | {'label': audio.LABELS['wiktionary']})
        self.assertTrue(invoke.call_args_list[0].kwargs['filename'].endswith('.ogg'))
        field = invoke.call_args.kwargs['note']['fields']['Pronounciation']
        self.assertIn('[sound:renamed.ogg]', field)
        self.assertIn(SOURCE, field)
        self.assertIn('Example speaker', field)
        self.assertIn('creativecommons.org/licenses/by-sa/4.0/', field)
        self.assertNotIn('/cambridge/', field)

    @patch.object(engine, 'find_duplicate_notes', return_value=[])
    @patch.object(engine, 'invoke_anki', return_value=123)
    @patch.object(engine, 'download_audio')
    def test_flagged_voice_is_not_saved_or_silently_replaced(self, download, invoke, duplicates):
        item = snapshot()
        item['data'].pop('selected_audio')
        item['data'].update(audio_review_required=True, us_audio=CAMBRIDGE.replace('uk_pron', 'us_pron'))
        engine.export_note(item)
        download.assert_not_called()
        self.assertEqual(invoke.call_args.kwargs['note']['fields']['Pronounciation'], '')

    @patch.object(engine, 'find_duplicate_notes', return_value=[])
    @patch.object(engine, 'invoke_anki')
    def test_other_word_approval_cannot_be_exported(self, invoke, duplicates):
        item = snapshot()
        item['word'] = 'necessity'
        with self.assertRaises(ValueError):
            engine.export_note(item)
        invoke.assert_not_called()

    @patch.object(engine, 'find_duplicate_notes', return_value=[])
    @patch.object(engine, 'invoke_anki', return_value=123)
    @patch.object(audio.AudioSources, 'recording', side_effect=ValueError('unavailable'))
    def test_alternative_download_failure_adds_card_without_wrong_ipa(self, download, invoke, duplicates):
        result = engine.export_note(snapshot())
        self.assertIn('unavailable', result['warnings'][0])
        self.assertEqual(invoke.call_args.kwargs['note']['fields']['Pronounciation'], '')

    def test_credit_text_is_escaped(self):
        record = {**approved(), 'author': '<script>speaker</script>'}
        self.assertNotIn('<script>', audio.attribution(record))
        self.assertIn('&lt;script&gt;', audio.attribution(record))


class AudioDecisionTests(unittest.TestCase):
    def test_old_history_cannot_restore_an_approval_that_was_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(Path(directory) / 'state.json')
            old = snapshot()
            store.save_draft(old)
            rejected = deepcopy(old)
            rejected['data'].pop('selected_audio')
            rejected['data'].update(rejected_audio=[], audio_review_required=True)
            store.save_draft(rejected)
            store.restore_audio_choices(old['data'])
            self.assertNotIn('selected_audio', old['data'])
            self.assertTrue(old['data']['audio_review_required'])

    def test_decisions_survive_refresh_restart_and_history_eviction(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            store = StateStore(path)
            item = snapshot()
            item['data']['rejected_audio'] = [audio.candidate_id(CAMBRIDGE)]
            store.save_draft(item)
            for index in range(22):
                store.save_draft({'word': str(index), 'data': None})
            store = StateStore(path)
            data = {'word': 'NECESSARY', 'uk_audio': CAMBRIDGE}
            store.restore_audio_choices(data)
            self.assertEqual(data['selected_audio'], approved())
            self.assertEqual(data['rejected_audio'], item['data']['rejected_audio'])
            other = {'word': 'necessity'}
            store.restore_audio_choices(other)
            self.assertNotIn('selected_audio', other)


if __name__ == '__main__':
    unittest.main()
