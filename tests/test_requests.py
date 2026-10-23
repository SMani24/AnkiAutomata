from pathlib import Path
from queue import Queue
from http.client import HTTPConnection
import json
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import desktop
import engine
from ipc import LookupServer
import shortcut
from themes import PALETTES, palette, theme
import typewriter_client


def entry(word, pos='noun', audio='voice', region='uk'):
    return f'''<div class="entry-body__el"><div class="pos-header"><span class="hw dhw">{word}</span>
        <span class="pos dpos">{pos}</span><div class="{region}"><span class="ipa dipa">{audio}</span>
        <source type="audio/mpeg" src="/media/{audio}.mp3"></div></div>
        <div class="dsense"><span class="guideword">{pos}</span><div class="def-block ddef_block">
        <span class="def ddef_d">a {pos} definition</span><span class="eg deg">Use {word}.</span></div></div></div>'''


class PronunciationMatchingTests(unittest.TestCase):
    def scrape(self, word, html):
        response = Mock(status_code=200, text=html, url='https://dictionary.cambridge.org/dictionary/english/' + word)
        with patch.object(engine.network, 'get', return_value=response):
            return engine.scrape_cambridge(word)

    def test_redirected_inflection_does_not_use_base_word_voice(self):
        data = self.scrape('walked', entry('walk'))
        self.assertIsNone(data['uk_audio'])
        self.assertEqual(data['uk_ipa'], '')
        self.assertEqual(data['audio_match_version'], 1)

    def test_matching_entry_wins_over_unrelated_first_recording(self):
        data = self.scrape('cat', entry('dog') + entry('cat', audio='cat'))
        self.assertEqual(data['pronunciations']['1']['uk_audio'], 'https://dictionary.cambridge.org/media/cat.mp3')
        self.assertNotIn('0', data['pronunciations'])

    def test_part_of_speech_keeps_corresponding_voice_and_ipa(self):
        data = self.scrape('record', entry('record', 'noun', 'noun-record') + entry('record', 'verb', 'verb-record'))
        noun = engine.pronunciation_for_group(data, data['groups'][0])
        verb = engine.pronunciation_for_group(data, data['groups'][1])
        self.assertTrue(noun['uk_audio'].endswith('/noun-record.mp3'))
        self.assertTrue(verb['uk_audio'].endswith('/verb-record.mp3'))
        self.assertEqual(verb['uk_ipa'], '/verb-record/')

    def test_missing_region_does_not_borrow_from_another_word(self):
        data = self.scrape('cat', entry('cat', audio='cat') + entry('dog', region='us'))
        self.assertIsNone(data['us_audio'])
        self.assertEqual(data['us_ipa'], '')

    def test_only_cambridge_https_media_is_accepted(self):
        html = entry('cat').replace('/media/voice.mp3', 'https://other.example/voice.mp3')
        self.assertIsNone(self.scrape('cat', html)['uk_audio'])

    def test_case_and_whitespace_are_normalized_without_accepting_a_different_word(self):
        self.assertIsNotNone(self.scrape('Cat', entry(' CAT '))['uk_audio'])
        self.assertIsNone(self.scrape('cat', entry('catfish'))['uk_audio'])


class ThemeTests(unittest.TestCase):
    def test_all_palettes_supply_light_and_dark_widget_roles(self):
        for name in PALETTES:
            generated = theme(name)
            self.assertEqual(tuple(generated['CTk']['fg_color']), palette(name)['background'])
            self.assertEqual(tuple(generated['CTkButton']['fg_color']), palette(name)['accent'])
            self.assertEqual(tuple(generated['CTkTextbox']['text_color']), palette(name)['text'])
            self.assertIn('family', generated['CTkFont'])


class DesktopTests(unittest.TestCase):
    @patch.object(desktop.shutil, 'which', return_value=None)
    def test_install_adds_icon_and_desktop_entry_in_user_locations(self, which):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            target = desktop.install(base / 'data', base / 'Desktop')
            content = target.read_text()
            self.assertIn('StartupWMClass=Ankiautomata', content)
            self.assertIn(' --launch', content)
            self.assertTrue((base / 'Desktop/AnkiAutomata.desktop').is_file())
            self.assertTrue((base / 'data/icons/hicolor/256x256/apps/ankiautomata.png').is_file())

    @patch.object(desktop.shutil, 'which', return_value=None)
    def test_installer_preserves_unrelated_launchers(self, which):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            target = base / 'applications/ankiautomata.desktop'
            target.parent.mkdir()
            target.write_text('[Desktop Entry]\nName=Other\n')
            with self.assertRaisesRegex(ValueError, 'another application'):
                desktop.install(base)
            self.assertEqual(target.read_text(), '[Desktop Entry]\nName=Other\n')

    def test_desktop_exec_quotes_special_characters_and_keeps_virtual_environment(self):
        quoted = desktop.quote_exec('/tmp/Anki 100%/a$`b"c\\python')
        self.assertTrue(quoted.startswith('"'))
        self.assertIn('100%%', quoted)
        self.assertIn('\\\\$', quoted)
        with patch.object(desktop.sys, 'prefix', 'venv'), patch.object(desktop.sys, 'base_prefix', 'base'), \
                patch.object(desktop.sys, 'executable', '/tmp/venv/bin/python'):
            self.assertEqual(str(desktop.interpreter()), '/tmp/venv/bin/python')


class TypewriterTests(unittest.TestCase):
    def snapshot(self):
        return {'word': 'Cat', 'definition': 'an animal', 'sentence': 'A cat lives here.',
                'examples': '• My cat sleeps.'}

    def test_uses_reviewed_fields_and_preserves_user_sentence(self):
        item = typewriter_client.prepare_word(self.snapshot())
        self.assertEqual(item['word'], 'cat')
        self.assertEqual(item['sentence'], 'A cat lives here.')
        self.assertEqual(item['tag'], 'AnkiAutomata')

    def test_uses_first_matching_edited_example_if_context_is_empty(self):
        snapshot = self.snapshot()
        snapshot.update(sentence='', examples='• A dog sleeps.\n• My cat sleeps.')
        self.assertEqual(typewriter_client.prepare_word(snapshot)['sentence'], 'My cat sleeps.')

    def test_does_not_silently_truncate_material_or_drop_wrong_context(self):
        for changes in ({'definition': 'x' * 2001}, {'sentence': 'A dog sleeps.'}, {'word': '123'}):
            with self.assertRaises(ValueError):
                typewriter_client.prepare_word({**self.snapshot(), **changes})

    @patch.object(typewriter_client.requests, 'Session')
    def test_existing_csrf_token_protocol_and_duplicate_response(self, session_factory):
        session = session_factory.return_value.__enter__.return_value
        health = Mock(is_redirect=False)
        health.json.return_value = {'app': 'typewriter'}
        page = Mock(is_redirect=False, text='<meta name="typewriter-token" content="test-token">')
        session.get.side_effect = [health, page]
        response = Mock(status_code=201)
        response.json.return_value = {'added': [], 'duplicates': ['cat']}
        session.post.return_value = response
        result = typewriter_client.send_word(typewriter_client.prepare_word(self.snapshot()))
        self.assertEqual(result['duplicates'], ['cat'])
        self.assertEqual(session.post.call_args.kwargs['headers']['X-Typewriter-Token'], 'test-token')
        self.assertFalse(session.trust_env)

    @patch.object(typewriter_client.requests, 'Session')
    def test_no_remote_address_is_accepted(self, session):
        with self.assertRaises(ValueError):
            typewriter_client.send_word({}, 'http://example.org:8080')
        session.assert_not_called()

    @patch.object(typewriter_client.requests, 'Session')
    def test_wrong_server_is_rejected_before_sending_word(self, factory):
        session = factory.return_value.__enter__.return_value
        response = Mock(is_redirect=False)
        response.json.return_value = {'app': 'other'}
        session.get.return_value = response
        with self.assertRaisesRegex(ValueError, 'not a Typewriter'):
            typewriter_client.send_word({})
        session.post.assert_not_called()


class ContextProtocolTests(unittest.TestCase):
    def setUp(self):
        self.queue = Queue(maxsize=5)
        self.server = LookupServer(self.queue, ('127.0.0.1', 0))
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       kwargs={'poll_interval': 0.01}, daemon=True)
        self.thread.start()
        self.port = self.server.server_port

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=1)

    def request(self, method, path, body=None):
        connection = HTTPConnection('127.0.0.1', self.port, timeout=2)
        try:
            connection.request(method, path, body=body)
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def test_health_does_not_trigger_a_lookup(self):
        status, body = self.request('GET', '/health')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['app'], 'ankiautomata')
        self.assertTrue(self.queue.empty())

    def test_word_and_sentence_roundtrip(self):
        with patch.object(shortcut, 'PORT', self.port):
            shortcut.send_lookup('cat', 'The cat sleeps.')
        self.assertEqual(self.queue.get_nowait(), {'text': 'cat', 'sentence': 'The cat sleeps.'})

    def test_invalid_sentence_is_not_queued(self):
        for invalid in (12, None, []):
            status, _ = self.request('POST', '/lookup', json.dumps({'text': 'cat', 'sentence': invalid}))
            self.assertEqual(status, 400)
        self.assertTrue(self.queue.empty())

    def test_activate_does_not_read_or_replace_clipboard_text(self):
        self.assertEqual(self.request('GET', '/activate')[0], 200)
        self.assertEqual(self.queue.get_nowait(), {'action': 'activate'})


if __name__ == '__main__':
    unittest.main()
