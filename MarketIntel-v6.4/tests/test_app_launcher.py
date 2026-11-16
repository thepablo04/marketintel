"""The desktop entry must preserve the browser and never stop foreign servers."""
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import iniciar_app as launcher


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'servidor.py').write_text("APP_VERSION = '9.1-test'\n", encoding='utf-8')

    def test_port_uses_env_override_or_dotenv_without_installing_anything(self):
        self.assertEqual(launcher.read_port(self.root, {}), 5050)
        (self.root / '.env').write_text('SECRET=not-read\nexport PORT="5061" # a comment\n', encoding='utf-8')
        self.assertEqual(launcher.read_port(self.root, {}), 5061)
        self.assertEqual(launcher.read_port(self.root, {'PORT':'5070'}), 5070)
        (self.root / '.env').write_text("PORT=5055\nPORT='${CUSTOM_PORT}'\n", encoding='utf-8')
        self.assertEqual(launcher.read_port(self.root, {'CUSTOM_PORT':'5080'}), 5080)
        for bad in ('0', '65536', 'private-invalid-value'):
            with self.subTest(port=bad), self.assertRaises(launcher.LaunchError) as error:
                launcher.read_port(self.root, {'PORT':bad})
            self.assertNotIn(bad, str(error.exception))

    def test_health_accepts_only_this_install_and_version(self):
        state={'service':'MarketIntel','install_id':launcher.install_id(self.root),'version':'9.1-test'}
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200);self.end_headers()
                self.wfile.write(json.dumps(state).encode())
            def log_message(self,*args):
                pass
        server=HTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        args=(server.server_port,launcher.install_id(self.root),'9.1-test')
        self.assertEqual(launcher.probe_server(*args),'ready')
        state['version']='old'
        self.assertEqual(launcher.probe_server(*args),'old-version')
        state['install_id']='other-folder'
        self.assertEqual(launcher.probe_server(*args),'foreign')
        state.clear()
        self.assertEqual(launcher.probe_server(*args),'foreign')

    def test_lock_serializes_double_click_then_can_be_reused(self):
        with launcher.StartupLock(self.root,self.root/'data') as first:
            self.assertTrue(first)
            with launcher.StartupLock(self.root,self.root/'data') as second:
                self.assertFalse(second)
        with launcher.StartupLock(self.root,self.root/'data') as again:
            self.assertTrue(again)

    def test_existing_correct_server_opens_same_browser_origin_without_install(self):
        with patch.object(launcher,'probe_server',return_value='ready'), \
             patch.object(launcher,'install_dependencies') as install, \
             patch.object(launcher,'open_app') as open_app, \
             patch.object(launcher.subprocess,'Popen') as popen, \
             patch.dict(launcher.os.environ,{'PORT':'5050'}):
            self.assertEqual(launcher.launch(self.root,Mock(),self.root/'data'),'reused')
        open_app.assert_called_once_with(5050)
        install.assert_not_called();popen.assert_not_called()

    def test_foreign_or_old_server_is_never_killed_or_overwritten(self):
        for state in ('foreign','old-version'):
            with self.subTest(state=state), \
                 patch.object(launcher,'probe_server',return_value=state), \
                 patch.object(launcher,'install_dependencies') as install, \
                 patch.object(launcher.subprocess,'Popen') as popen, \
                 patch.object(launcher,'open_app') as open_app:
                with self.assertRaises(launcher.LaunchError):
                    launcher.launch(self.root,Mock(),self.root/'data')
                install.assert_not_called();popen.assert_not_called();open_app.assert_not_called()

    def test_starts_only_once_then_waits_for_verified_health(self):
        child=Mock();child.poll.return_value=None;child.pid=123456
        with patch.object(launcher,'probe_server',side_effect=['offline','offline','ready']), \
             patch.object(launcher,'install_dependencies') as install, \
             patch.object(launcher.subprocess,'Popen',return_value=child) as popen, \
             patch.object(launcher,'open_app') as open_app, \
             patch.dict(launcher.os.environ,{'PORT':'5050'}):
            self.assertEqual(launcher.launch(self.root,Mock(),self.root/'data'),'started')
        install.assert_called_once();popen.assert_called_once();open_app.assert_called_once_with(5050)
        self.assertEqual(popen.call_args.kwargs['env']['PORT'],'5050')
        self.assertEqual(popen.call_args.kwargs['cwd'],self.root)
        child.terminate.assert_not_called()

    def test_detects_port_race_after_dependency_install_without_starting_server(self):
        with patch.object(launcher,'probe_server',side_effect=['offline','foreign']), \
             patch.object(launcher,'install_dependencies'), \
             patch.object(launcher.subprocess,'Popen') as popen:
            with self.assertRaises(launcher.LaunchError):
                launcher.launch(self.root,Mock(),self.root/'data')
            popen.assert_not_called()

    def test_startup_failure_never_opens_wrong_page(self):
        child=Mock();child.poll.return_value=1;child.pid=123456
        with patch.object(launcher,'probe_server',return_value='offline'), \
             patch.object(launcher,'install_dependencies'), \
             patch.object(launcher.subprocess,'Popen',return_value=child), \
             patch.object(launcher,'open_app') as open_app:
            with self.assertRaisesRegex(launcher.LaunchError,'servidor.log'):
                launcher.launch(self.root,Mock(),self.root/'data')
        open_app.assert_not_called();child.terminate.assert_not_called()

    def test_process_record_binds_pid_folder_token_port_and_creation_time(self):
        child=Mock(pid=123456)
        data=self.root/'data';data.mkdir()
        with patch.object(launcher,'process_start_filetime',return_value='133700000000000000'):
            path=launcher.record_server(data,self.root,child,5050,'9.1-test','a'*32)
        record=json.loads(path.read_text())
        self.assertEqual(record['pid'],123456)
        self.assertEqual(record['directory'],str(self.root))
        self.assertEqual(record['server'],str(self.root/'servidor.py'))
        self.assertEqual(record['launcher_token'],'a'*32)
        self.assertEqual(record['start_filetime'],'133700000000000000')
        self.assertEqual(record['install_id'],launcher.install_id(self.root))
        self.assertEqual(record['port'],5050)

    def test_default_browser_fallback_preserves_localhost_and_does_not_choose_edge(self):
        with patch.object(launcher,'default_app_browser',return_value=None), \
             patch.object(launcher.webbrowser,'open',return_value=True) as browser, \
             patch.object(launcher.subprocess,'Popen') as popen:
            launcher.open_app(5050)
        browser.assert_called_once_with('http://localhost:5050');popen.assert_not_called()

    def test_chrome_app_mode_never_creates_a_new_profile(self):
        with patch.object(launcher,'default_app_browser',return_value='C:/Chrome/chrome.exe'), \
             patch.object(launcher.subprocess,'Popen') as popen:
            launcher.open_app(5050)
        self.assertEqual(popen.call_args.args[0],['C:/Chrome/chrome.exe','--app=http://localhost:5050'])
        self.assertNotIn('shell',popen.call_args.kwargs)


if __name__=='__main__':
    unittest.main()
