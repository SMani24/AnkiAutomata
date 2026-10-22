from http.client import HTTPConnection
import json
from queue import Queue
import threading
import unittest
from unittest.mock import Mock, patch

from ipc import LookupServer, MAX_TEXT_BYTES
import shortcut


class SelectionTests(unittest.TestCase):
    @patch.dict(shortcut.os.environ, {'XDG_SESSION_TYPE': 'x11'}, clear=True)
    @patch.object(shortcut.shutil, 'which', return_value='/usr/bin/xclip')
    @patch.object(shortcut.subprocess, 'run')
    def test_reads_x11_selection_without_copying(self, run, which):
        run.return_value = Mock(returncode=0, stdout='  selected\nphrase  ')
        self.assertEqual(shortcut.selected_text(), 'selected phrase')
        self.assertEqual(run.call_args.args[0], ['xclip', '-selection', 'primary', '-out'])

    @patch.dict(shortcut.os.environ, {'XDG_SESSION_TYPE': 'wayland'}, clear=True)
    @patch.object(shortcut.shutil, 'which', return_value='/usr/bin/wl-paste')
    @patch.object(shortcut.subprocess, 'run')
    def test_wayland_uses_primary_selection(self, run, which):
        run.return_value = Mock(returncode=0, stdout='word')
        self.assertEqual(shortcut.selected_text(), 'word')
        self.assertEqual(run.call_args.args[0], ['wl-paste', '--primary', '--no-newline'])

    @patch.object(shortcut.shutil, 'which', return_value=None)
    def test_missing_selection_tool_explains_dependency(self, which):
        with self.assertRaisesRegex(RuntimeError, 'Install'):
            shortcut.selected_text()

    @patch.object(shortcut.shutil, 'which', return_value='tool')
    @patch.object(shortcut.subprocess, 'run')
    def test_failed_or_empty_selection_does_not_use_stale_clipboard(self, run, which):
        for returncode, text in ((1, ''), (0, ' \n ')):
            run.return_value = Mock(returncode=returncode, stdout=text)
            with self.assertRaisesRegex(RuntimeError, 'Highlight'):
                shortcut.selected_text()

    @patch.object(shortcut.shutil, 'which', return_value='tool')
    @patch.object(shortcut.subprocess, 'run')
    def test_long_selection_is_rejected_before_launch(self, run, which):
        run.return_value = Mock(returncode=0, stdout='a' * MAX_TEXT_BYTES)
        with self.assertRaisesRegex(RuntimeError, 'too long'):
            shortcut.selected_text()

    @patch.object(shortcut, 'selected_text', return_value='cat')
    @patch.object(shortcut, 'send_lookup')
    @patch.object(shortcut.subprocess, 'Popen')
    def test_running_app_receives_selection_without_launch(self, launch, send, selection):
        shortcut.search_selection()
        send.assert_called_once_with('cat')
        launch.assert_not_called()

    @patch.object(shortcut, 'selected_text', return_value='cat')
    @patch.object(shortcut, 'send_lookup', side_effect=ConnectionRefusedError)
    @patch.object(shortcut.subprocess, 'Popen')
    def test_closed_app_is_started_with_captured_text(self, launch, send, selection):
        shortcut.search_selection()
        self.assertEqual(launch.call_args.args[0][-1], '--lookup=cat')
        self.assertTrue(launch.call_args.kwargs['start_new_session'])

    @patch.object(shortcut, 'selected_text', return_value='--help')
    @patch.object(shortcut, 'send_lookup', side_effect=ConnectionRefusedError)
    @patch.object(shortcut.subprocess, 'Popen')
    def test_selection_starting_with_dash_is_passed_as_text(self, launch, send, selection):
        shortcut.search_selection()
        self.assertEqual(launch.call_args.args[0][-1], '--lookup=--help')

    @patch.object(shortcut, 'selected_text', return_value='cat')
    @patch.object(shortcut, 'send_lookup', side_effect=TimeoutError)
    @patch.object(shortcut.subprocess, 'Popen')
    def test_busy_app_does_not_launch_duplicate_window(self, launch, send, selection):
        with self.assertRaises(TimeoutError):
            shortcut.search_selection()
        launch.assert_not_called()


class InstallerTests(unittest.TestCase):
    @patch.object(shortcut, '_set_setting')
    @patch.object(shortcut, '_setting')
    def test_repairs_old_binding_without_changing_other_shortcuts(self, get, set_value):
        path = '/existing-ankiautomata/'
        get.side_effect = [[path, '/other/'], shortcut.SHORTCUT_NAME, '<Primary><Alt>w']
        self.assertEqual(shortcut.install_shortcut(), '<Primary><Alt>w')
        set_value.assert_called_once()
        self.assertEqual(set_value.call_args.args[:2], (f'{shortcut.CUSTOM_BINDING}:{path}', 'command'))
        self.assertIn('shortcut.py', set_value.call_args.args[2])

    @patch.object(shortcut, '_set_setting')
    @patch.object(shortcut, '_setting')
    def test_new_binding_is_added_without_replacing_existing_list(self, get, set_value):
        get.side_effect = [['/other/'], 'Other shortcut', '<Super>t']
        shortcut.install_shortcut()
        set_value.assert_called_with(shortcut.MEDIA_KEYS, 'custom-keybindings', ['/other/', shortcut.BINDING_PATH])

    @patch.object(shortcut, '_set_setting')
    @patch.object(shortcut, '_setting')
    def test_existing_unrelated_binding_is_not_overwritten(self, get, set_value):
        get.side_effect = [['/other/'], 'Other shortcut', '<Primary><Alt>w']
        with self.assertRaisesRegex(RuntimeError, 'already assigned'):
            shortcut.install_shortcut()
        set_value.assert_not_called()


class LookupProtocolTests(unittest.TestCase):
    def setUp(self):
        self.queue = Queue(maxsize=2)
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
            response.read()
            return response.status
        finally:
            connection.close()

    def test_client_and_server_pass_unicode_selection(self):
        with patch.object(shortcut, 'PORT', self.port):
            shortcut.send_lookup('déjà vu')
        self.assertEqual(self.queue.get_nowait(), 'déjà vu')

    def test_old_curl_trigger_still_queues_clipboard_lookup(self):
        self.assertEqual(self.request('GET', '/'), 200)
        self.assertIsNone(self.queue.get_nowait())

    def test_invalid_requests_do_not_schedule_lookup(self):
        for body in ('broken json', '{}', '[]', '{"text": " "}'):
            self.assertEqual(self.request('POST', '/lookup', body), 400)
        self.assertTrue(self.queue.empty())
        self.assertEqual(self.request('POST', '/lookup', 'x' * (MAX_TEXT_BYTES + 1)), 413)

    def test_unknown_paths_do_not_trigger_search(self):
        self.assertEqual(self.request('GET', '/favicon.ico'), 404)
        self.assertTrue(self.queue.empty())

    def test_queue_full_is_reported(self):
        self.queue.put_nowait('first')
        self.queue.put_nowait('second')
        self.assertEqual(self.request('POST', '/lookup', json.dumps({'text': 'third'})), 429)


if __name__ == '__main__':
    unittest.main()
