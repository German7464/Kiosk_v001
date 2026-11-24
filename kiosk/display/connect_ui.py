"""Portable Tk control window for the existing native Windows Events client."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import admin as admin_ui
from .connect import Connection, confirmed_time, public_input
from .qr_pairing import pairing_url, qr_image


MESSAGES = {
    'saved': 'Состояние загружено. Для первого подключения введите адрес и публичные данные.',
    'pending': 'Ожидается решение администратора. Сверьте устройство и введите код в админке.',
    'rate_limited': 'Сервер ограничил частоту запросов. Повтор после паузы, без перезапуска сервера; сохранённые данные не изменены.',
    'approved': 'Подключение одобрено. Запустите Events с синхронизацией.',
    'cancelled': 'Операция остановлена. Сохранённые данные не удалены.',
    'denied': 'Администратор отказал. Данные сохранены; автоматического нового запроса нет.',
    'expired': 'Срок доступа истёк. Принятое содержимое сохранено; восстановите сопряжение с одобрением администратора.',
    'access_refused': 'Доступ отозван или заменён сервером. Принятое содержимое остаётся доступно; восстановите сопряжение.',
    'authority_expired': 'Срок доверия группы на сервере истёк. Администратор должен продлить доверие; принятое содержимое сохранено.',
    'time_required': 'Для нового приёма подтвердите независимо проверенное время UTC.',
    'time_confirmed': 'Время явно подтверждено. Регистрация сохранена.',
    'network_unavailable': 'Сервер недоступен. Принятые Events можно открыть без сети.',
    'server_refused': 'Сервер отказал в операции. Сохранённые данные не удалены.',
    'operation_refused': 'Операция не выполнена: проверьте данные доверия и состояние доступа.',
    'no_content': 'Принятого содержимого пока нет. Нужна публикация и связь с сервером.',
    'synchronizing': 'Получение и проверка публикации. Готовность ещё не подтверждена.',
    'ready': 'Events открыты: нативное окно подтвердило готовность.',
    'connected': 'Events открыты; синхронизация и отправка подтверждений работают.',
    'display_closed': 'Нативный показ остановлен. Принятое содержимое сохранено.',
}


class Window:
    def __init__(self, root, connection, *, events=None):
        self.root, self.connection, self.events = root, connection, events
        self.closing, self.saved, self.raw = False, False, None
        self.facts = {}
        self.hints = []
        self.admin_session = None
        self.updating = False
        root.title('Kiosk — подключение Windows')
        root.geometry(f'900x{min(850, root.winfo_screenheight() - 100)}')
        root.minsize(780, 550)
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.address = tk.StringVar()
        self.digest = tk.StringVar()
        self.file_name = tk.StringVar()
        self.confirmed = tk.BooleanVar()
        self.clock_checked = tk.BooleanVar()
        self.clock = tk.StringVar(value=datetime.now(timezone.utc).isoformat(timespec='seconds'))
        self.mode = tk.StringVar(value='tv')
        self.status = tk.StringVar(value='Введите адрес и публичные данные от доверенного администратора.')
        self.code = tk.StringVar(value='—')
        self.details = tk.StringVar(value='Публичные данные ещё не проверены.')
        canvas = tk.Canvas(root, highlightthickness=0)
        scrollbar = ttk.Scrollbar(root, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)
        box = ttk.Frame(canvas, padding=16)
        content = canvas.create_window((0, 0), window=box, anchor='nw')
        box.bind('<Configure>', lambda event: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda event: canvas.itemconfigure(content, width=event.width))
        root.bind('<MouseWheel>', lambda event: canvas.yview_scroll(-int(event.delta / 120), 'units'))
        ttk.Label(box, text='Подключение к серверу Events', font=('Segoe UI', 16)).pack(anchor='w')
        row = ttk.Frame(box); row.pack(fill='x', pady=5)
        self.search_button = ttk.Button(row, text='Найти сервер в LAN', command=self.search)
        self.search_button.pack(side='left')
        self.select_button = ttk.Button(row, text='Выбрать адрес', command=self.select)
        self.select_button.pack(side='left', padx=8)
        ttk.Label(box, text='Результаты не проверены: выбор заполняет только адрес.', wraplength=825).pack(anchor='w')
        self.results = tk.Listbox(box, height=3, exportselection=False)
        self.results.pack(fill='x')
        ttk.Label(box, text='HTTPS-адрес сервера с портом').pack(anchor='w', pady=(10, 0))
        self.address_entry = ttk.Entry(box, textvariable=self.address)
        self.address_entry.pack(fill='x')
        ttk.Label(box, text='Публичный bootstrap из уже доверенного канала: файл или вставка').pack(anchor='w', pady=(8, 0))
        self.public = tk.Text(box, height=3, wrap='word')
        self.public.pack(fill='x')
        ttk.Label(box, text='Или путь к полученному публичному файлу bootstrap').pack(anchor='w')
        self.file_entry = ttk.Entry(box, textvariable=self.file_name)
        self.file_entry.pack(fill='x')
        row = ttk.Frame(box); row.pack(fill='x', pady=5)
        self.load_button = ttk.Button(row, text='Открыть публичный файл', command=self.load)
        self.load_button.pack(side='left')
        self.review_button = ttk.Button(row, text='Проверить данные', command=self.review)
        self.review_button.pack(side='left', padx=8)
        ttk.Label(box, textvariable=self.details, wraplength=825, justify='left').pack(anchor='w', pady=5)
        ttk.Label(box, text='SHA256 из независимого доверенного источника').pack(anchor='w')
        self.digest_entry = ttk.Entry(box, textvariable=self.digest); self.digest_entry.pack(fill='x')
        self.confirm_box = ttk.Checkbutton(box, text='Сверены адрес, группа, сервер, ключ и независимый SHA256', variable=self.confirmed)
        self.confirm_box.pack(anchor='w')
        ttk.Label(box, text='Независимо проверенное время UTC (например 2026-11-06T00:00:00Z)').pack(anchor='w', pady=(6, 0))
        self.clock_entry = ttk.Entry(box, textvariable=self.clock); self.clock_entry.pack(fill='x')
        self.clock_box = ttk.Checkbutton(box, text='Время проверено независимо; разрешаю явное подтверждение', variable=self.clock_checked)
        self.clock_box.pack(anchor='w')
        row = ttk.Frame(box); row.pack(fill='x', pady=6)
        self.enroll_button = ttk.Button(row, text='Подключить / продолжить', command=self.enroll)
        self.enroll_button.pack(side='left')
        self.time_button = ttk.Button(row, text='Подтвердить время', command=self.time)
        self.time_button.pack(side='left', padx=6)
        self.recover_button = ttk.Button(row, text='Восстановить сопряжение', command=self.recover,
                                        state='disabled')
        self.recover_button.pack(side='left', padx=6)
        self.admin_button = ttk.Button(row, text='Администрирование', command=self.admin)
        self.admin_button.pack(side='left')
        ttk.Label(box, text='Код сопряжения (действует не более 10 минут)').pack(anchor='w')
        ttk.Label(box, textvariable=self.code, font=('Consolas', 22, 'bold')).pack(anchor='w')
        ttk.Label(box, text='QR для сопряжения со смартфона (тот же код, генерируется локально)').pack(anchor='w')
        self.qr_label = ttk.Label(box, text='QR появится после запроса сопряжения.', anchor='w')
        self.qr_label.pack(anchor='w')
        self.qr_photo = None
        row = ttk.Frame(box); row.pack(fill='x', pady=8)
        self.mode_box = ttk.Combobox(row, textvariable=self.mode, values=('tv', 'kiosk'), width=9, state='readonly')
        self.mode_box.pack(side='left')
        self.run_button = ttk.Button(row, text='Запустить с синхронизацией', command=lambda: self.run(True))
        self.run_button.pack(side='left', padx=7)
        self.offline_button = ttk.Button(row, text='Открыть сохранённое без сети', command=lambda: self.run(False))
        self.offline_button.pack(side='left')
        self.cancel_button = ttk.Button(row, text='Остановить / назад', command=self.cancel)
        self.cancel_button.pack(side='left', padx=7)
        ttk.Label(box, textvariable=self.status, wraplength=825, justify='left', font=('Segoe UI', 10)).pack(anchor='w', pady=7)
        ttk.Label(box, text='Поиск LAN — только подсказка. Доверие и сопряжение проверяются отдельно.', wraplength=825).pack(anchor='w')
        self.update_button = ttk.Button(box, text='Обновление из файла', command=self.update_from_file)
        self.update_button.pack(anchor='w', pady=(6, 0))
        self.editables = [self.address_entry, self.public, self.file_entry, self.load_button, self.review_button,
                          self.digest_entry, self.confirm_box, self.clock_entry, self.clock_box,
                          self.enroll_button, self.time_button, self.recover_button, self.run_button,
                          self.offline_button,
                          self.search_button, self.select_button, self.results, self.update_button]
        connection.start('inspect')
        root.after(100, self.tick)

    def search(self):
        if self.saved or self.connection.busy:
            return
        self.hints = []
        self.results.delete(0, 'end')
        if self.connection.start('discover'):
            self.status.set('Поиск до 3 секунд. Можно остановить; ручной адрес доступен после поиска.')

    def select(self):
        if self.saved or self.connection.busy:
            return
        selected = self.results.curselection()
        if not selected or selected[0] >= len(self.hints):
            self.status.set('Выберите строку или введите адрес вручную.')
            return
        self.address.set(self.hints[selected[0]]['origin'])
        self.confirmed.set(False)
        self.raw = None
        self.details.set('Адрес выбран из непроверенной подсказки. Сверьте независимые публичные данные.')
        self.status.set('Заполнен только адрес. Подключение не начато; нужны независимые данные доверия.')

    def load(self):
        name = self.file_name.get().strip()
        if name:
            try:
                with open(name, 'rb') as stream:
                    raw = stream.read(16385)
                if len(raw) > 16384:
                    raise ValueError()
                self.public.delete('1.0', 'end'); self.public.insert('1.0', raw.decode('utf-8'))
                self.review()
            except (OSError, ValueError):
                self.status.set('Не удалось прочитать публичный файл (предел 16 КиБ).')
        else:
            self.status.set('Укажите путь к публичному файлу или вставьте его содержимое выше.')

    def review(self):
        try:
            raw = self.public.get('1.0', 'end-1c').encode('utf-8')
            value = public_input(raw, self.address.get().strip())
            self.raw = raw
            self.confirmed.set(False)
            expiry = datetime.fromtimestamp(value['expires_at'], timezone.utc).isoformat()
            self.details.set(f"Адрес: {value['origin']}\nГруппа: {value['group_id']}\nСервер: {value['server_id']}\nКлюч: {value['group_key_id']}\nBootstrap действует до {expiry}")
            self.status.set('Сверьте эти данные и SHA256 через независимый доверенный канал.')
            return True
        except Exception:
            self.raw = None
            self.confirmed.set(False)
            self.status.set('Проверьте точный HTTPS-адрес, формат и срок bootstrap. Адрес должен совпадать.')
            return False

    def enroll(self):
        try:
            if self.saved:
                self.connection.start('enroll')
                return
            raw = self.public.get('1.0', 'end-1c').encode('utf-8')
            public_input(raw, self.address.get().strip(), confirmation=self.digest.get().strip(), confirmed=self.confirmed.get())
            utc = confirmed_time(self.clock.get(), self.clock_checked.get())
            self.connection.start('enroll', raw=raw, address=self.address.get().strip(),
                                  digest=self.digest.get().strip(), confirmed=self.confirmed.get(), utc=utc)
        except Exception:
            self.status.set('Подключение не начато: нужны совпадающий адрес, действующий bootstrap, независимый SHA256 и подтверждённое UTC-время.')

    def time(self):
        try:
            self.connection.start('time', utc=confirmed_time(self.clock.get(), self.clock_checked.get()))
        except Exception:
            self.status.set(MESSAGES['time_required'])

    def recover(self):
        if not self.saved or self.connection.busy:
            return
        self.connection.start('recover')
        self.status.set('Запрошено повторное одобрение того же устройства. Принятое содержимое сохранено.')

    def admin(self):
        # Only the origin from the already verified saved anchor is accepted. The
        # native window renders the ordinary server admin pages in an isolated
        # WebView2 profile; this UI never sees or supplies the admin password.
        origin = self.facts.get('origin') if self.saved else ''
        if not origin:
            self.status.set(admin_ui.MESSAGES['admin_origin_required'])
            return
        if self.admin_session is None:
            self.admin_session = admin_ui.AdminSession(self.connection.shell, self.connection.root)
        try:
            self.admin_session.open(origin)
        except admin_ui.AdminError as error:
            self.status.set(admin_ui.MESSAGES.get(str(error), admin_ui.MESSAGES['admin_unavailable']))
            return
        self.status.set('Открыто встроенное администрирование с отдельным профилем. Пароль вводится только в серверной форме.')

    def show_qr(self, origin, code):
        # Locally renders the coordinator pairing contract for the trusted saved origin.
        try:
            from PIL import ImageTk
            if not origin or not code or len(code) != 8:
                self.clear_qr()
                return
            photo = ImageTk.PhotoImage(qr_image(pairing_url(origin, code)), master=self.root)
            self.qr_label.configure(image=photo, text='')
            self.qr_photo = photo  # Keep a reference so Tk does not garbage-collect it.
        except Exception:
            self.clear_qr()

    def clear_qr(self):
        self.qr_photo = None
        self.qr_label.configure(image='', text='QR появится после запроса сопряжения.')

    def run(self, online):
        self.connection.start('display', mode=self.mode.get(), online=online)

    def cancel(self):
        self.connection.cancel()
        self.status.set('Остановка текущей операции; ожидание завершения ограниченного запроса…')

    def update_from_file(self):
        from . import updater

        if self.updating or self.connection.busy:
            return
        if self.admin_session is not None and self.admin_session.poll() is None:
            messagebox.showinfo('Обновление', 'Закройте окно администрирования перед обновлением.', parent=self.root)
            return
        package = filedialog.askdirectory(parent=self.root, title='Выберите папку подписанного пакета обновления')
        if not package:
            return
        try:
            manifest = updater.verify(package)
        except Exception as error:
            messagebox.showerror('Kiosk', 'Пакет отклонён: ' + str(error), parent=self.root)
            return
        if not messagebox.askyesno('Обновление',
                                   f'Установить обновление до версии {manifest["version"]}? Приложение закроется. После завершения обновления откройте KioskConnect снова; сохранённые данные и подключение останутся.',
                                   parent=self.root):
            return
        self.update_button.configure(state='disabled')
        self.updating = True
        self.status.set('Установка обновления… не закрывайте приложение.')

        def work():
            try:
                result = updater.upgrade(package, relaunch=True)
                self.root.after(0, lambda: self.update_staged(result))
            except Exception as error:
                self.root.after(0, lambda error=error: self.update_failed(error))

        threading.Thread(target=work, daemon=True).start()

    def update_failed(self, error):
        self.updating = False
        messagebox.showerror('Kiosk', 'Обновление не установлено: ' + str(error), parent=self.root)
        self.update_button.configure(state='normal')

    def update_staged(self, result):
        # Activation is handed to the detached helper, which waits for this window
        # to exit before swapping. Honest completion: the window closes (releasing
        # its files) and the helper relaunches the new client; we do not claim
        # "installed" here because the swap has not completed yet.
        self.status.set('Обновление до версии ' + result['to_version'] + ' подготовлено. Приложение закроется; данные и подключение сохранятся. Запустите его снова после завершения обновления.')
        self.root.after(1000, self.root.destroy)

    def close(self):
        if self.updating:
            self.status.set('Обновление подготавливается. Дождитесь передачи на активацию; окно закроется автоматически.')
            return
        self.closing = True
        self.cancel()

    def tick(self):
        try:
            while True:
                value = self.connection.events.get_nowait()
                if self.events:
                    with self.events.open('a', encoding='utf-8') as out:
                        # Active pairing codes never enter persistent diagnostics.
                        recorded = {key: item for key, item in value.items() if key != 'code'}
                        out.write(json.dumps(recorded, ensure_ascii=False) + '\n')
                state = value['state']
                if state == 'discovered':
                    self.hints = value['hints']
                    self.results.configure(state='normal')
                    self.results.delete(0, 'end')
                    for hint in self.hints:
                        self.results.insert('end', f"{hint['label']} | {hint['origin']}")
                    self.status.set('Выберите сервер и отдельно проверьте доверие.' if self.hints else
                                    'Ответов нет. Это не доказывает отсутствие сервера; введите адрес вручную.')
                elif state == 'discovery_cancelled':
                    self.hints = []
                    self.results.configure(state='normal')
                    self.results.delete(0, 'end')
                    self.status.set('Поиск остановлен. Можно ввести адрес вручную.')
                elif state == 'discovery_failed':
                    self.status.set('Поиск недоступен. Введите HTTPS-адрес вручную; данные сохранены.')
                if 'saved' in value:
                    self.facts = value
                    self.saved = value['saved']
                    if self.saved:
                        self.hints = []
                        self.results.configure(state='normal')
                        self.results.delete(0, 'end')
                        self.mode.set(value['mode'])
                        self.address.set(value['origin'])
                        self.details.set(f"Группа: {value['group']}\nСервер: {value['server']}\nУстройство: {value['device']}\nЗапрос: {value['request']}\nNonce: {value['nonce']}\nПрофиль: {value['profile']}\nСохранённые Events: {'есть' if value['content'] else 'пока нет'}; доступ: {'отозван' if value['revoked'] else 'одобрен' if value['approved'] else 'ожидает одобрения'}"
                                          + (f"\nСостояние доступа: {value['recovery']} ({value['recovery_code']})" if value.get('recovery') else ''))
                        self.recover_button.configure(
                            state='normal' if value.get('recovery') in ('expired', 'revoked_or_replaced') else 'disabled')
                if state == 'pending':
                    self.code.set(value['code'])
                    self.show_qr(value.get('origin', ''), value.get('code', ''))
                elif state in ('approved', 'denied', 'expired', 'access_refused', 'authority_expired',
                               'cancelled', 'idle'):
                    self.code.set('—')
                    self.clear_qr()
                if state in MESSAGES:
                    text = MESSAGES[state]
                    if state == 'saved' and value.get('saved'):
                        text = 'Сохранённое подключение загружено. Для принятого содержимого сеть не нужна.'
                    if value.get('wait'):
                        text += f" Повтор через {value['wait']} с."
                    if value.get('http'):
                        text += f" HTTP {value['http']}."
                    if value.get('retained'):
                        text += ' Уже открытое содержимое сохранено.'
                    self.status.set(text)
        except queue.Empty:
            pass
        busy = self.connection.busy or self.updating
        if self.admin_session is not None:
            code = self.admin_session.poll()
            if code is not None:
                self.status.set(admin_ui.exit_message(code, self.admin_session.last_status()))
        for widget in self.editables:
            widget.configure(state='disabled' if busy else 'normal')
        self.mode_box.configure(state='disabled' if busy else 'readonly')
        self.time_button.configure(state='normal' if self.saved and not busy else 'disabled')
        self.cancel_button.configure(state='normal' if busy else 'disabled')
        if self.saved:
            for widget in (self.address_entry, self.public, self.file_entry, self.load_button, self.review_button,
                           self.digest_entry, self.confirm_box, self.search_button, self.select_button, self.results):
                widget.configure(state='disabled')
        if self.closing and not busy:
            self.root.destroy()
            return
        self.root.after(100, self.tick)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'KioskConnect')
    parser.add_argument('--shell', type=Path)
    parser.add_argument('--audit', type=Path)
    parser.add_argument('--events', type=Path, help='Fixed public UI states only; never native private state')
    parser.add_argument('--upgrade', type=Path, help='Stage a signed update, exit, then reopen the client manually after activation')
    parser.add_argument('--upgrade-status', action='store_true', help='Report the handed-off update outcome to a file')
    args = parser.parse_args()

    def write_command_report(report):
        try:
            from pathlib import Path as _P

            (_P(os.environ.get("LOCALAPPDATA", _P.home())) / "KioskConnect" / "upgrade-command.json").write_text(
                json.dumps(report), encoding="utf-8")
        except Exception:
            pass

    if args.upgrade:
        from . import updater

        import traceback

        report = {}
        try:
            report = updater.upgrade(args.upgrade)
        except Exception:
            report = {"error": traceback.format_exc()}
        write_command_report(report)
        print(json.dumps(report))
        return 1 if report.get('error') else 0
    if args.upgrade_status:
        from . import updater

        report = updater.upgrade_status()
        write_command_report(report)
        print(json.dumps(report))
        return 1 if report.get('state') in ('failed', 'recovery-required', 'rolled_back') else 0
    executable = Path(sys.executable if getattr(sys, 'frozen', False) else __file__).resolve()
    shell = args.shell or executable.parents[2] / 'shell' / 'KioskOfflineDisplay.exe'

    def audit(value):
        if args.audit:
            with args.audit.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(value) + '\n')

    root = tk.Tk()
    Window(root, Connection(args.root, shell, audit=audit), events=args.events)
    root.mainloop()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
