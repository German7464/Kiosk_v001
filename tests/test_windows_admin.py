"""Focused checks for the Windows in-app administration launcher.

These are policy/launch checks only. Actual WebView2 TLS, navigation and logout
behaviour is exercised by the packaged journey and is not claimed here.
"""
from pathlib import Path
import os
import queue
import tempfile
import unittest
from unittest.mock import Mock, patch

from kiosk.display import admin
from kiosk.publication.exporter import PackageError


ORIGIN = 'https://192.168.1.165:18543'
SHELL = Path(r'C:\candidate\shell\KioskOfflineDisplay.exe')


class FakeProcess:
    def __init__(self, code=None):
        self.code = code

    def poll(self):
        return self.code


class LaunchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_command_uses_exact_origin_and_isolated_profile(self):
        command = admin.admin_command(SHELL, self.root, ORIGIN)
        self.assertEqual(command[0], str(SHELL))
        self.assertEqual(command[1], '--admin')
        self.assertEqual(command[2], '--origin')
        self.assertEqual(command[3], ORIGIN)
        self.assertEqual(command[4], '--profile')
        self.assertEqual(Path(command[5]), self.root / 'admin-webview')
        self.assertEqual(command[6], '--display-profile')
        self.assertEqual(Path(command[7]), self.root / 'profile')
        self.assertNotEqual(Path(command[5]), Path(command[7]))
        self.assertFalse(any('password' in item.lower() or '@' in item for item in command[4:]))

    def test_unsafe_or_inexact_origins_are_refused(self):
        for value in ('http://192.168.1.165:18543', 'https://192.168.1.165:18543/',
                      'https://192.168.1.165:18543/admin', 'https://192.168.1.165:18543?x=1',
                      'https://192.168.1.165:18543#v=1', 'https://user:pass@192.168.1.165:18543',
                      'https://192.168.1.165', 'https://пример.рф:18543', 'file:///C:/Windows',
                      'https://192.168.1.165:18543/../evil'):
            with self.subTest(value=value), self.assertRaises(PackageError):
                admin.admin_command(SHELL, self.root, value)

    def test_diagnostic_port_is_explicit_only(self):
        command = admin.admin_command(SHELL, self.root, ORIGIN)
        self.assertNotIn('--diagnostic-port', command)
        command = admin.admin_command(SHELL, self.root, ORIGIN, diagnostic=19222)
        self.assertEqual(command[-2:], ['--diagnostic-port', '19222'])
        self.assertNotIn('--diagnostic-port', admin.admin_command(SHELL, self.root, ORIGIN, diagnostic=0))
        for value in (80, 70000, -1, '19222', True):
            with self.subTest(value=value), self.assertRaises(admin.AdminError):
                admin.admin_command(SHELL, self.root, ORIGIN, diagnostic=value)
        # An ambient environment value never enables the acceptance-harness listener.
        self.assertEqual(admin.diagnostic_port({'KIOSK_ADMIN_DIAGNOSTIC_PORT': '19222'}), 0)

    def test_session_never_derives_diagnostic_port_from_environment(self):
        calls = []
        session = admin.AdminSession(SHELL, self.root, popen=lambda command, **options: calls.append(command) or FakeProcess())
        with patch.dict(os.environ, {'KIOSK_ADMIN_DIAGNOSTIC_PORT': '19223'}):
            session.open(ORIGIN)
        self.assertNotIn('--diagnostic-port', calls[0])
        session.process.code = 0
        session.poll()
        session.open(ORIGIN, diagnostic=19224)
        self.assertEqual(calls[1][-2:], ['--diagnostic-port', '19224'])

    def test_profiles_are_separate_from_display_state(self):
        admin_root, display_root = admin.checked_profiles(self.root)
        self.assertEqual(admin_root, self.root / 'admin-webview')
        self.assertEqual(display_root, self.root / 'profile')
        self.assertFalse(admin._overlap(admin_root, display_root))
        for name in admin.DISPLAY_DIRECTORIES:
            self.assertFalse(admin._overlap(admin_root, self.root / name))

    def test_duplicate_window_refused_and_restart_allowed(self):
        calls = []

        def popen(command, **options):
            calls.append((command, options))
            return FakeProcess()

        session = admin.AdminSession(SHELL, self.root, popen=popen)
        session.open(ORIGIN)
        self.assertTrue(session.running)
        with self.assertRaises(admin.AdminError):
            session.open(ORIGIN)
        self.assertEqual(len(calls), 1)
        session.process.code = 0
        self.assertEqual(session.poll(), 0)
        self.assertFalse(session.running)
        self.assertIsNone(session.poll())
        session.open(ORIGIN)
        self.assertEqual(len(calls), 2)
        self.assertEqual(Path(calls[0][0][5]), self.root / 'admin-webview')
        self.assertEqual(calls[0][1]['cwd'], str(SHELL.parent))

    def test_launch_failures_are_fixed_local_labels(self):
        def missing(command, **options):
            raise FileNotFoundError()

        def denied(command, **options):
            raise OSError()

        session = admin.AdminSession(SHELL, self.root, popen=missing)
        with self.assertRaises(admin.AdminError) as error:
            session.open(ORIGIN)
        self.assertEqual(str(error.exception), 'admin_shell_missing')
        session = admin.AdminSession(SHELL, self.root, popen=denied)
        with self.assertRaises(admin.AdminError) as error:
            session.open(ORIGIN)
        self.assertEqual(str(error.exception), 'admin_unavailable')
        session = admin.AdminSession(SHELL, self.root, popen=denied)
        with self.assertRaises(admin.AdminError) as error:
            session.open('http://192.168.1.165:18543')
        self.assertEqual(str(error.exception), 'admin_origin_refused')

    def test_exit_messages_are_fixed_and_cleanup_is_qualified(self):
        self.assertIn('профиль', admin.exit_message(3))
        self.assertIn('адрес', admin.exit_message(2))
        self.assertIn('уже', admin.exit_message(4))
        self.assertEqual(admin.exit_message(9), admin.MESSAGES['admin_failed'])
        clean = {'cleanup': 'profile_data_deleted', 'logout_posted': True, 'logout_cleared': True}
        self.assertIn('очищена', admin.exit_message(0, clean))
        for status in (None, {}, {'cleanup': 'profile_data_delete_pending_next_launch'},
                       {'cleanup': 'profile_data_deleted', 'logout_posted': True, 'logout_cleared': False},
                       {'cleanup': 'profile_data_cleanup_pending'}):
            with self.subTest(status=status):
                self.assertEqual(admin.exit_message(0, status), admin.MESSAGES['admin_cleanup_unconfirmed'])

    def test_last_status_is_optional_and_bounded(self):
        session = admin.AdminSession(SHELL, self.root)
        self.assertIsNone(session.last_status())
        session.status_path.parent.mkdir(parents=True, exist_ok=True)
        session.status_path.write_text('{"cleanup": "profile_data_deleted"}', encoding='utf-8')
        self.assertEqual(session.last_status()['cleanup'], 'profile_data_deleted')
        session.status_path.write_text('not json', encoding='utf-8')
        self.assertIsNone(session.last_status())
        session.status_path.write_text('[' * 40000, encoding='utf-8')
        self.assertIsNone(session.last_status())


class ConnectWindowTests(unittest.TestCase):
    def test_button_opens_only_saved_verified_origin(self):
        import tkinter as tk
        from kiosk.display.connect_ui import Window

        connection = Mock()
        connection.events = queue.Queue()
        connection.busy = False
        connection.shell = SHELL
        connection.root = Path(tempfile.gettempdir()) / 'kiosk-admin-ui-test'
        root = tk.Tk()
        root.withdraw()
        try:
            window = Window(root, connection)
            fake = Mock()
            window.admin_session = fake
            window.admin()
            fake.open.assert_not_called()
            self.assertIn('подключение', window.status.get())
            window.saved = True
            window.facts = {'origin': ORIGIN}
            window.admin()
            fake.open.assert_called_once_with(ORIGIN)
            fake.open.side_effect = admin.AdminError('admin_shell_missing')
            window.admin()
            self.assertIn('просмотрщик', window.status.get())
        finally:
            try:
                root.destroy()
            except tk.TclError:
                pass


if __name__ == '__main__':
    unittest.main()
