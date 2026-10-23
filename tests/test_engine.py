import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import requests

import engine


class ConfigTests(unittest.TestCase):
    def test_import_from_another_directory(self):
        script = (
            f'import sys; sys.path.insert(0, {str(Path(engine.__file__).parent)!r}); '
            'import engine; assert engine.config["anki"]["url"]'
        )
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run([sys.executable, '-c', script], cwd=directory, check=True)

    def test_save_keeps_other_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            original = {'anki': {'url': 'localhost'}, 'preferences': {'audio_choice': 'uk'}}
            with patch.object(engine, 'CONFIG_FILE', path), patch.object(engine, 'config', original):
                engine.save_preference('font_scale', 'Large (130%)')
            saved = json.loads(path.read_text())
            self.assertEqual(saved['anki'], {'url': 'localhost'})
            self.assertEqual(saved['preferences'], {'audio_choice': 'uk', 'font_scale': 'Large (130%)'})
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_failed_replace_preserves_existing_file_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            path.write_text('{"preferences": {}}')
            with patch.object(engine, 'CONFIG_FILE', path), patch.object(engine, 'config', {}), \
                    patch.object(engine.os, 'replace', side_effect=OSError('disk full')), patch('builtins.print'):
                engine.save_preferences({'audio_choice': 'us'})
            self.assertEqual(json.loads(path.read_text()), {'preferences': {}})
            self.assertEqual(list(Path(directory).iterdir()), [path])


class FormattingTests(unittest.TestCase):
    def test_bolding_preserves_case_and_escapes_plain_text(self):
        self.assertEqual(engine.bold_word('cat', 'Cat < dog & CAT'),
                         '<b>Cat</b> &lt; dog &amp; <b>CAT</b>')

    def test_highlighting_matches_original_text_not_html_entities(self):
        self.assertEqual(engine.bold_word('amp', '& amp'), '&amp; <b>amp</b>')
        self.assertEqual(engine.bold_word('<tag>', '<TAG>'), '<b>&lt;TAG&gt;</b>')

    def test_sentence_uses_configured_tags(self):
        templates = {'highlight_open_tag': '<mark>', 'highlight_close_tag': '</mark>'}
        with patch.dict(engine.config, templates=templates):
            self.assertEqual(engine.format_sentence('c++', 'C++ & Python'), '<mark>C++</mark> &amp; Python')

    def test_empty_word_and_text(self):
        self.assertEqual(engine.bold_word('', '<text>'), '&lt;text&gt;')
        self.assertEqual(engine.bold_word('word', ''), '')


class NetworkTests(unittest.TestCase):
    @patch.object(engine.requests, 'post')
    def test_anki_request_checks_status_and_has_timeout(self, post):
        post.return_value.json.return_value = {'result': ['Default'], 'error': None}
        self.assertEqual(engine.invoke_anki('deckNames'), ['Default'])
        self.assertEqual(post.call_args.kwargs['timeout'], engine.REQUEST_TIMEOUT)
        post.return_value.raise_for_status.assert_called_once()

    @patch.object(engine.requests, 'post')
    def test_anki_error_and_malformed_response(self, post):
        post.return_value.json.return_value = {'result': None, 'error': 'unknown model'}
        with self.assertRaisesRegex(Exception, 'unknown model'):
            engine.invoke_anki('addNote')
        for malformed in ({}, [], {'result': None}):
            post.return_value.json.return_value = malformed
            with self.assertRaisesRegex(ValueError, 'Invalid response'):
                engine.invoke_anki('deckNames')

    @patch.object(engine.requests, 'get')
    def test_audio_http_error_is_not_saved_as_audio(self, get):
        get.return_value.raise_for_status.side_effect = requests.HTTPError('503')
        with self.assertRaises(requests.HTTPError):
            engine.download_audio('https://example.org/audio.mp3', {})
        self.assertEqual(get.call_args.kwargs['timeout'], engine.REQUEST_TIMEOUT)

    @patch.object(engine.requests, 'get')
    def test_audio_download_returns_bytes(self, get):
        get.return_value.content = b'mp3 data'
        self.assertEqual(engine.download_audio('https://example.org/audio.mp3', {}), b'mp3 data')


class ScraperTests(unittest.TestCase):
    HTML = '''
        <div class="pr entry-body__el">
          <span class="hw dhw">cat</span>
          <div class="pos-header"><span class="pos dpos">noun</span></div>
          <div class="uk"><span class="ipa dipa">kæt</span>
            <source type="audio/mpeg" src="/media/cat.mp3"></div>
          <div class="us"><source type="audio/mpeg" src="https://dictionary.cambridge.org/media/us-cat.mp3"></div>
          <div class="dsense"><span class="guideword">(ANIMAL)</span>
            <div class="def-block ddef_block"><div class="def ddef_d">a small animal:</div>
              <span class="eg deg">A cat lives here.</span></div>
            <div class="def-block ddef_block"><div class="def ddef_d">a wild animal:</div>
              <span class="eg deg">A wild cat.</span></div>
          </div>
        </div>'''

    @patch.object(engine.requests, 'get')
    def test_groups_definitions_and_resolves_audio_urls(self, get):
        get.return_value = Mock(status_code=200, text=self.HTML)
        data = engine.scrape_cambridge('cat')
        self.assertEqual(data['groups'][0]['definitions'], ['a small animal', 'a wild animal'])
        self.assertEqual(data['groups'][0]['guideword'], 'ANIMAL')
        self.assertEqual(data['examples_raw'], ['A cat lives here.', 'A wild cat.'])
        self.assertEqual(data['uk_ipa'], '/kæt/')
        self.assertEqual(data['uk_audio'], 'https://dictionary.cambridge.org/media/cat.mp3')
        self.assertEqual(data['us_audio'], 'https://dictionary.cambridge.org/media/us-cat.mp3')
        self.assertEqual(get.call_args.kwargs['timeout'], engine.REQUEST_TIMEOUT)

    @patch.object(engine.requests, 'get')
    def test_word_is_encoded_as_single_url_path_component(self, get):
        get.return_value = Mock(status_code=404)
        self.assertIsNone(engine.scrape_cambridge(' A/B? # '))
        self.assertTrue(get.call_args.args[0].endswith('a%2Fb%3F-%23'))

    @patch.object(engine.requests, 'get')
    def test_http_failure_is_distinct_from_missing_word(self, get):
        get.return_value.raise_for_status.side_effect = requests.HTTPError('503')
        with self.assertRaises(requests.HTTPError):
            engine.scrape_cambridge('cat')


if __name__ == '__main__':
    unittest.main()
