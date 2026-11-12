"""Bounded in-app Windows administration launcher.

The existing native shell renders the ordinary server admin HTML/CSS/JS in a
WebView2 window. This module only launches that mode with the exact origin taken
from the already verified saved connection and a dedicated profile directory.
It never receives, stores or injects an administrator password, and it does not
grant the TV/Kiosk display credential any administrative authority.
"""
from pathlib import Path
import json
import subprocess

from .delivery_authority import origin as parse_origin


ADMIN_DIRECTORY = 'admin-webview'
ADMIN_ENTRY = '/admin/devices/pair'
ADMIN_STATUS = 'admin-status.json'
DISPLAY_DIRECTORIES = ('private', 'store', 'cache', 'state', 'profile', 'capture', 'control', 'diagnostics')

MESSAGES = {
    'admin_already_open': 'Окно администрирования уже открыто.',
    'admin_shell_missing': 'Не найден встроенный просмотрщик приложения. Обновите сборку.',
    'admin_unavailable': 'Не удалось запустить встроенное администрирование.',
    'admin_origin_required': 'Сначала загрузите проверенное сохранённое подключение.',
    'admin_origin_refused': 'Адрес сохранённого подключения не является точным HTTPS-источником.',
    'admin_exit_policy': 'Администрирование не запущено: неверный адрес или профиль.',
    'admin_exit_storage': 'Администрирование не запущено: профиль или хранилище недоступны.',
    'admin_exit_busy': 'Окно администрирования уже использует этот профиль.',
    'admin_failed': 'Окно администрирования завершилось с ошибкой.',
    'admin_cleanup_unconfirmed': 'Окно администрирования закрыто. Локальные данные очищены не полностью; очистка повторится при следующем запуске. Серверная сессия завершена.',
}


class AdminError(Exception):
    """Fixed local error label only; never arbitrary exception text."""


def admin_root(root):
    return Path(root).absolute() / ADMIN_DIRECTORY


def display_root(root):
    return Path(root).absolute() / 'profile'


def _plain(value):
    return str(Path(value).absolute()).rstrip('\\/')


def _overlap(first, second):
    one, two = _plain(first).lower(), _plain(second).lower()
    return one == two or one.startswith(two + '\\') or two.startswith(one + '\\')


def checked_profiles(root):
    """Return (administration, display) roots and refuse any overlap."""
    admin = admin_root(root)
    display = display_root(root)
    if _overlap(admin, display) or any(_overlap(admin, Path(root).absolute() / name)
                                       for name in DISPLAY_DIRECTORIES):
        raise AdminError('admin_exit_storage')
    return admin, display


def diagnostic_port(environ=None):
    """Diagnostic DevTools port is never derived from the process environment.

    Normal packaged operation has no remote-debugging listener. Acceptance
    tooling must launch the native shell explicitly with ``--diagnostic-port``;
    the product connection window always passes 0.
    """
    return 0


def admin_command(shell, root, origin_value, *, diagnostic=0):
    """Exact argv for the native administration mode; no credentials."""
    parse_origin(origin_value)
    admin, display = checked_profiles(root)
    if type(diagnostic) is not int or diagnostic and not 1024 <= diagnostic <= 65535:
        raise AdminError('admin_origin_refused')
    command = [str(Path(shell).absolute()), '--admin', '--origin', origin_value,
               '--profile', str(admin), '--display-profile', str(display)]
    if diagnostic:
        command += ['--diagnostic-port', str(int(diagnostic))]
    return command


def exit_message(code, status=None):
    if code == 2:
        return MESSAGES['admin_exit_policy']
    if code == 3:
        return MESSAGES['admin_exit_storage']
    if code == 4:
        return MESSAGES['admin_exit_busy']
    if code == 0:
        if not qualified_exit(status):
            return MESSAGES['admin_cleanup_unconfirmed']
        return 'Окно администрирования закрыто. Локальная сессия очищена.'
    return MESSAGES['admin_failed']


def qualified_exit(status):
    """Only a shell report with confirmed profile removal allows a clean claim."""
    if not isinstance(status, dict):
        return False
    if status.get('logout_posted') and status.get('logout_cleared') is not True:
        return False
    return status.get('cleanup') in ('profile_data_deleted', 'profile_data_deleted_on_start')


class AdminSession:
    """One administration window per control window; launch never blocks Tk."""

    def __init__(self, shell, root, *, popen=None):
        self.shell = Path(shell).absolute()
        self.root = Path(root).absolute()
        self._popen = popen or subprocess.Popen
        self.process = None
        self.last_exit = None

    @property
    def running(self):
        return self.process is not None and self.process.poll() is None

    @property
    def status_path(self):
        return admin_root(self.root) / ADMIN_STATUS

    def open(self, origin_value, *, diagnostic=0):
        if self.running:
            raise AdminError('admin_already_open')
        self.process = None
        try:
            command = admin_command(self.shell, self.root, origin_value, diagnostic=diagnostic)
        except Exception:
            raise AdminError('admin_origin_refused') from None
        try:
            self.process = self._popen(command, cwd=str(self.shell.parent),
                                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL, close_fds=True)
        except FileNotFoundError:
            raise AdminError('admin_shell_missing') from None
        except OSError:
            raise AdminError('admin_unavailable') from None
        return self.process

    def last_status(self):
        """Read the shell's own cleanup report; never raise for absent/invalid JSON."""
        try:
            payload = self.status_path.read_bytes()
            if len(payload) > 65536:
                return None
            value = json.loads(payload)
            return value if isinstance(value, dict) else None
        except (OSError, ValueError, RecursionError):
            return None

    def poll(self):
        """Return the exit code once; None while closed or still running."""
        if self.process is None:
            return None
        code = self.process.poll()
        if code is None:
            return None
        self.last_exit = code
        self.process = None
        return code
