import getpass
import hmac
import json
import os
import queue
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import warnings
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from kiosk.core.credentials import validate_password
from tools.check_lan_https import BROWSER_RESULTS, LanFixture, execute, lan_ipv4, validate_addresses, validate_client_report


CONTROL_PATH = '/_lan-test/control'


class WizardFixture(LanFixture):
    def __init__(self, args, root, password):
        super().__init__(args, root, password)
        self.token = secrets.token_hex(32)
        self.commands = queue.Queue(maxsize=16)
        self.states = {}
        self.state_lock = threading.Lock()
        self.completed = False

    def app_factory(self, overrides):
        app = super().app_factory(overrides)
        application = app.wsgi_app

        def controlled(environ, start_response):
            if environ.get('PATH_INFO') != CONTROL_PATH:
                return application(environ, start_response)
            status, data = self.control(environ)
            body = json.dumps(data).encode('utf-8')
            start_response(status, [('Content-Type', 'application/json'), ('Cache-Control', 'no-store'), ('Content-Length', str(len(body)))])
            return [body]

        app.wsgi_app = controlled
        return app

    def control(self, environ):
        supplied = environ.get('HTTP_X_LAN_TEST_TOKEN', '')
        if (environ.get('REQUEST_METHOD') != 'POST' or environ.get('REMOTE_ADDR') != self.args.client_ip
                or environ.get('wsgi.url_scheme') != 'https' or not isinstance(supplied, str)
                or not supplied.isascii() or not hmac.compare_digest(supplied, self.token)):
            return '403 Forbidden', {'error': 'denied'}
        try:
            length = int(environ.get('CONTENT_LENGTH') or '0')
            if not 0 < length <= 32768:
                raise ValueError()
            data = json.loads(environ['wsgi.input'].read(length))
            if not isinstance(data, dict) or set(data) - {'action', 'value'} or 'action' not in data:
                raise ValueError()
            action = data['action']
            if action == 'status':
                value = data.get('value')
                if not isinstance(value, str):
                    raise ValueError()
                with self.state_lock:
                    state = self.states.get(value)
                if state is None:
                    raise ValueError()
                return '200 OK', {'state': state}
            if action not in {'restart', 'budget', 'update', 'record', 'report', 'complete', 'close', 'abort'}:
                raise ValueError()
            with self.state_lock:
                if len(self.states) >= 64:
                    return '429 Too Many Requests', {'error': 'capacity'}
                identifier = secrets.token_hex(8)
                self.states[identifier] = 'pending'
                try:
                    self.commands.put_nowait((identifier, action, data.get('value')))
                except queue.Full:
                    del self.states[identifier]
                    return '429 Too Many Requests', {'error': 'capacity'}
            return '202 Accepted', {'id': identifier}
        except (ValueError, TypeError, UnicodeError):
            return '400 Bad Request', {'error': 'invalid'}

    def process(self, action, value):
        if action in {'restart', 'budget', 'update'} and value is None:
            getattr(self, action)()
        elif action == 'record' and isinstance(value, dict) and set(value) == {'stage', 'result'}:
            if not all(isinstance(item, str) for item in value.values()):
                raise ValueError()
            execute(self, f"record {value['stage']} {value['result']}")
        elif action == 'report' and isinstance(value, dict):
            filename = self.root / 'wizard-client-report.json'
            filename.write_text(json.dumps(value), encoding='utf-8')
            self.client_report = validate_client_report(filename, self.session)
        elif (action == 'complete' and isinstance(value, dict) and set(value) == {'client_cleanup'}
              and value['client_cleanup'] is True):
            self.finish()
            self.completed = True
        elif action == 'close' and value is None and self.completed:
            return False
        elif action == 'abort' and value is None:
            raise EOFError()
        else:
            raise ValueError()
        return True

    def bundle(self, destination):
        bundle = self.manifest.parent
        source = Path(__file__).resolve().parent
        shutil.copy2(source.parent / 'LAN_Client.cmd', bundle / 'LAN_Client.cmd')
        shutil.copy2(source.parent / 'LAN_Diagnose.cmd', bundle / 'LAN_Diagnose.cmd')
        shutil.copy2(source / 'lan_wizard.ps1', bundle / 'lan_wizard.ps1')
        (bundle / 'wizard.json').write_text(json.dumps({'schema_version': 1, 'session': self.session, 'token': self.token}), encoding='utf-8')
        with zipfile.ZipFile(destination, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
            for name in ('LAN_Client.cmd', 'LAN_Diagnose.cmd', 'check_lan_https.ps1', 'browser_trust.ps1', 'lan_wizard.ps1',
                         'session.json', 'wizard.json', 'authority.pem', 'fixture.png'):
                archive.write(bundle / name, name)


def ask_yes(prompt):
    while True:
        answer = input(prompt + ' [1 — да, 2 — нет]: ').strip().lower()
        if answer in {'1', 'да', 'д', 'yes', 'y'}:
            return True
        if answer in {'2', 'нет', 'н', 'no', 'n'}:
            return False
        print('Введите 1 или 2.')


def read_password():
    while True:
        with warnings.catch_warnings():
            warnings.simplefilter('error', getpass.GetPassWarning)
            password = getpass.getpass('Придумайте временный пароль (12–128 символов): ')
            try:
                validate_password(password)
            except ValueError:
                print('Пароль слишком короткий или длинный. Попробуйте ещё раз.')
                continue
            if password == getpass.getpass('Повторите этот пароль: '):
                return password
            print('Пароли отличаются. Введите их заново.')


def firewall(args, session, action):
    helper = Path(__file__).with_name('lan_firewall.ps1')
    result = subprocess.run([str(args.pwsh), '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(helper),
        '-Action', action, '-ServerAddress', args.server_ip, '-ClientAddress', args.client_ip,
        '-Port', str(args.port), '-Session', session], capture_output=True, timeout=180,
        creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError('firewall_' + action)


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    print('ПРОВЕРКА KIOSK — СЕРВЕР\nРабочие события и пароли не меняются. Для выхода нажмите Ctrl+C.', flush=True)
    source = Path(__file__).resolve().parent.parent
    report = {'success': False, 'physical_lan': 'Pending', 'cleanup': {}}
    fixture = None
    rule_owned = False
    archive = None
    output = source / 'logs/https' / ('wizard-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    output.mkdir(parents=True)
    phase = 'addresses'
    try:
        print('\nШАГ 1. Адреса компьютеров')
        while True:
            try:
                client_ip = lan_ipv4(input('Введите IP второго компьютера: ').strip())
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as route:
                    route.connect((client_ip, 9))
                    suggested = route.getsockname()[0]
                server_ip = input(f'IP этого сервера [{suggested}], Enter — оставить: ').strip() or suggested
                server_ip, client_ip = validate_addresses(server_ip, client_ip, 8443)
                break
            except (ValueError, OSError):
                print('Адрес не подходит или порт 8443 занят. Проверьте IP и закройте предыдущую тестовую проверку. Попробуйте ещё раз.')
        pwsh = shutil.which('pwsh')
        if not pwsh:
            raise FileNotFoundError('pwsh')
        args = SimpleNamespace(server_ip=server_ip, client_ip=client_ip, port=8443,
            pwsh=Path(pwsh), caddy=source / 'logs/https-tools/caddy/caddy.exe')
        print('\nШАГ 2. Временный пароль. Запомните его для второго компьютера.')
        password = read_password()
        with tempfile.TemporaryDirectory(prefix='kiosk-lan-wizard-') as directory:
            fixture = WizardFixture(args, Path(directory), password)
            try:
                phase = 'firewall'
                print(f'\nШАГ 3. Временный доступ: только от {client_ip} к {server_ip}:8443.')
                if ask_yes('Создать временное правило брандмауэра? Windows попросит разрешение; правило удалится в конце'):
                    firewall(args, fixture.session, 'add')
                    rule_owned = True
                phase = 'startup'
                print('\nШАГ 4. Запускаю тестовый сервер. Подождите…', flush=True)
                fixture.prepare()
                archive = output / 'Kiosk-LAN-Client.zip'
                fixture.bundle(archive)
                try:
                    subprocess.Popen(['explorer.exe', '/select,', str(archive)])
                except OSError:
                    pass
                print('\nГОТОВО. Сервер запущен.', flush=True)
                print(f'\n1. Скопируйте этот архив на второй ПК:\n{archive}', flush=True)
                print('2. На втором ПК распакуйте архив и дважды нажмите LAN_Client.cmd.', flush=True)
                print('3. Оставьте это окно сервера открытым. Дальше всё выполняется на втором ПК.', flush=True)
                print('\nНа втором ПК будет показан отпечаток. Сравните его с этой строкой:', flush=True)
                print(' '.join(fixture.digest[index:index + 8] for index in range(0, 64, 8)), flush=True)
                print('\nОжидаю второй компьютер…', flush=True)
                phase = 'client'
                running = True
                deadline = time.monotonic() + 7200
                while running:
                    fixture.runtime.check_running()
                    if time.monotonic() >= deadline:
                        raise TimeoutError()
                    try:
                        identifier, action, value = fixture.commands.get(timeout=0.1)
                    except queue.Empty:
                        continue
                    try:
                        running = fixture.process(action, value)
                        with fixture.state_lock:
                            fixture.states[identifier] = 'done'
                        print({'restart': 'Сервер перезапущен.', 'budget': 'Адреса клиентов различаются: проверка пройдена.',
                            'report': 'Автоматический отчёт получен.', 'update': 'Тестовое событие обновлено.',
                            'complete': 'Все результаты и очистка клиента подтверждены.', 'close': 'Проверка завершена.'}.get(action, 'Результат этапа получен.'), flush=True)
                    except (ValueError, RuntimeError) as error:
                        with fixture.state_lock:
                            fixture.states[identifier] = 'failed'
                        print(f'Этап не пройден: {action} ({type(error).__name__}).', flush=True)
                report['client_checks'] = fixture.client_report['checks']
                report['http_statuses'] = fixture.client_report['http_statuses']
                report['browser_observations'] = dict(fixture.browser)
            finally:
                fixture.stop()
        report['success'] = True
        report['physical_lan'] = 'Verified'
    except (Exception, KeyboardInterrupt) as error:
        report['error'] = type(error).__name__
        report['phase'] = phase
        print('\nПроверка не завершена. Рабочая установка не изменена.', flush=True)
        if isinstance(error, TimeoutError) and phase == 'startup':
            print('Сервер не ответил на проверку HTTPS. Проверьте VPN, локальную сеть и защитные программы.', flush=True)
        elif phase == 'addresses':
            print('Проверьте IP обоих ПК и доступность порта 8443.', flush=True)
        else:
            print(f'Этап: {phase}. Код ошибки: {type(error).__name__}. Сохраните это сообщение.', flush=True)
    finally:
        if rule_owned:
            try:
                firewall(args, fixture.session, 'remove')
                report['cleanup']['firewall'] = True
                print('Временное правило брандмауэра удалено.', flush=True)
            except Exception:
                report['success'] = False
                report['cleanup']['firewall'] = False
                print(f'Нужно удалить только правило Kiosk-LAN-Wizard-{fixture.session}.', flush=True)
        if archive is not None:
            try:
                archive.unlink(missing_ok=True)
            except OSError:
                report['success'] = False
                report['cleanup']['archive'] = False
        if fixture:
            report['cleanup']['managed'] = fixture.cleanups
            report['cleanup']['temporary_removed'] = not fixture.root.exists()
            if not report['cleanup']['temporary_removed']:
                report['success'] = False
        if not report['success']:
            report['physical_lan'] = 'Pending'
        (output / 'result.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(f'\nОтчёт: {output / "result.json"}', flush=True)
        print('ПРОВЕРКА ПРОЙДЕНА.' if report['success'] else 'ПРОВЕРКА ПОКА НЕ ПРОЙДЕНА.', flush=True)
        print('Если клиент прерван: запустите LAN_Client.cmd снова и выберите очистку.', flush=True)
    return 0 if report['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
