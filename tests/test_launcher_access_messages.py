import io
import tempfile
import threading
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import launcher_maintenance
from kiosk.launcher.errors import AdministratorRequired, ElevationUnavailable, StatusAccessDenied, access_message
from kiosk.launcher.client import read_status
from kiosk.launcher.gui import Launcher, elevate
from kiosk.launcher.installation import require_administrator
from kiosk.launcher.storage import Storage


class LauncherAccessMessageTests(unittest.TestCase):
    def controller(self):
        controller = Launcher.__new__(Launcher)
        controller.root = Mock()
        controller.details = Mock()
        controller.busy = False
        controller.autostart = False
        return controller

    def test_administrative_denial_is_actionable_and_does_not_reach_storage(self):
        output = io.StringIO()
        with patch('kiosk.launcher.installation.administrator', return_value=False):
            with self.assertRaises(AdministratorRequired) as caught:
                require_administrator()
            self.assertIn('от имени администратора', access_message(caught.exception))
            with patch('sys.argv', ['KioskMaintenance', 'setup-admin']), patch('launcher_maintenance.common_root') as root, redirect_stderr(output):
                self.assertEqual(launcher_maintenance.run(), 1)
                root.assert_not_called()
        self.assertIn('terminal opened as administrator', output.getvalue())
        self.assertNotIn('Traceback', output.getvalue())

    def test_elevation_refusal_does_not_perform_the_system_action(self):
        controller = self.controller()
        controller.error = Mock()
        with patch('kiosk.launcher.gui.administrator', return_value=False), patch('kiosk.launcher.gui.elevate', side_effect=ElevationUnavailable()) as approval, patch('kiosk.launcher.gui.control_service') as control:
            controller.administrative('start')
            approval.assert_called_once_with('start')
            control.assert_not_called()
        error, context = controller.error.call_args.args
        text = access_message(error, context)
        self.assertIn('Операция не выполнена', text)
        self.assertIn('подтвердите запрос Windows', text)
        with patch('kiosk.launcher.gui.ctypes.WinDLL', return_value=SimpleNamespace(ShellExecuteW=Mock(return_value=5))), patch('kiosk.launcher.gui.executable_command', return_value=['fixture.exe', '--start']):
            with self.assertRaises(ElevationUnavailable):
                elevate('start')

    def test_export_denial_offers_a_writable_folder_without_secret_details(self):
        controller = self.controller()
        controller.storage = Mock()
        controller.background = lambda action, success=None, error_context=None: self.assert_export_error(controller, action, error_context)
        with patch('kiosk.launcher.gui.filedialog.asksaveasfilename', return_value='unwritable.zip'), patch('kiosk.launcher.gui.export_diagnostics', side_effect=PermissionError('private exception detail')), patch('kiosk.launcher.gui.messagebox.showerror') as dialog:
            controller.export()
        text = dialog.call_args.args[1]
        self.assertIn('Выберите другую папку', text)
        self.assertNotIn('от имени администратора', text)
        self.assertNotIn('private exception detail', text)

    def assert_export_error(self, controller, action, context):
        try:
            action()
        except PermissionError as error:
            controller.error(error, context)
        else:
            self.fail('Expected the fixture export failure')

    def test_source_status_denial_is_not_reported_as_an_export_destination_problem(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = Storage(Path(directory))
            with patch('pathlib.Path.open', side_effect=PermissionError('private source path')):
                with self.assertRaises(StatusAccessDenied) as caught:
                    read_status(storage)
            text = access_message(caught.exception, 'export')
            self.assertIn('Нет доступа к состоянию службы', text)
            self.assertNotIn('Выберите другую папку', text)
            self.assertNotIn('private source path', text)

    def test_poll_distinguishes_access_denial_from_stopped_and_never_opens_a_dialog(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = self.controller()
            controller.storage = Storage(Path(directory))
            controller.background = lambda action, success: success(action())
            with patch('kiosk.launcher.gui.read_status', side_effect=PermissionError('private path')), patch('kiosk.launcher.gui.check_ready') as ready, patch('kiosk.launcher.gui.available_memory', return_value=4 * 1024 ** 3), patch('kiosk.launcher.gui.messagebox.showerror') as dialog:
                controller.poll()
            text = controller.details.set.call_args.args[0]
            self.assertIn('Нет доступа к состоянию службы', text)
            self.assertNotIn('Сервер остановлен или', text)
            self.assertNotIn('private path', text)
            ready.assert_not_called()
            dialog.assert_not_called()

    def test_user_settings_and_display_do_not_elevate(self):
        controller = self.controller()
        controller.storage = Mock()
        controller.startup = Mock()
        controller.startup.get.return_value = True
        controller.background = lambda action, success=None, error_context=None: action()
        status = {'origin': 'http://127.0.0.1:5000', 'mode': 'kiosk'}
        with patch('kiosk.launcher.gui.elevate') as approval, patch('kiosk.launcher.gui.configure_user_startup', side_effect=PermissionError()), patch('kiosk.launcher.gui.messagebox.showerror') as dialog, patch('kiosk.launcher.gui.read_status', return_value=status), patch('kiosk.launcher.gui.check_ready', return_value=True), patch('kiosk.launcher.gui.open_display') as display:
            controller.change_startup()
            controller.display()
            controller.display('admin')
        controller.startup.set.assert_called_once_with(False)
        self.assertIn('текущего пользователя', dialog.call_args.args[1])
        approval.assert_not_called()
        self.assertEqual(display.call_count, 2)

    def test_background_preserves_error_context_on_the_gui_callback(self):
        controller = self.controller()
        received = threading.Event()
        controller.root.after.side_effect = lambda delay, callback: callback()
        controller.error = Mock(side_effect=lambda error, context: received.set())
        error = PermissionError('fixture')
        controller.background(Mock(side_effect=error), error_context='export')
        self.assertTrue(received.wait(3))
        controller.error.assert_called_once_with(error, 'export')


if __name__ == '__main__':
    unittest.main()
