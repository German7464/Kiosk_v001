import ctypes
import json
import os
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from kiosk.app import create_app
from kiosk.core.credentials import save_admin_password, validate_password
from kiosk.launcher.client import check_ready, export_diagnostics, maintenance_enabled, read_status, set_maintenance
from kiosk.launcher.display import open_display
from kiosk.launcher.errors import ElevationUnavailable, access_message
from kiosk.launcher.installation import binary_directory, configure_user_startup, control_service, initialize_directories, install, register_service, service_state, user_startup_enabled
from kiosk.launcher.runtime import VERSION
from kiosk.launcher.storage import Storage, common_root, needs_administrator, new_profile, read_profile, save_profile
from kiosk.launcher.windows import administrator, available_memory


def executable_command(*arguments):
    if getattr(sys, "frozen", False):
        return [str(Path(sys.executable)), *arguments]
    return [sys.executable, str(Path(__file__).resolve().parents[2] / "launcher.py"), *arguments]


def elevate(action):
    if action not in {"configure", "start", "stop", "install"}:
        raise ValueError("Unsupported local administrative operation.")
    command = executable_command("--" + action)
    api = ctypes.WinDLL("shell32", use_last_error=True)
    api.ShellExecuteW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_int]
    api.ShellExecuteW.restype = ctypes.c_void_p
    result = api.ShellExecuteW(None, "runas", command[0], subprocess.list2cmdline(command[1:]), None, 1)
    if not result or result <= 32:
        raise ElevationUnavailable("Windows administrator approval was cancelled or unavailable.")


class Launcher:
    def __init__(self, root, storage, autostart=False, configure=False):
        self.root = root
        self.storage = storage
        self.status = None
        self.busy = False
        self.autostart = autostart
        self.autostart_attempts = 0
        root.title("Kiosk Launcher")
        root.geometry("760x590")
        root.minsize(660, 510)
        frame = ttk.Frame(root, padding=20)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Kiosk Launcher", font=("Segoe UI", 20)).pack(anchor="w")
        ttk.Label(frame, text="Локальный сервер и экран • " + VERSION).pack(anchor="w", pady=(0, 15))
        self.details = tk.StringVar(value="Проверка состояния…")
        ttk.Label(frame, textvariable=self.details, justify="left", wraplength=690).pack(fill="x", anchor="w")
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=18)
        for index, (label, command) in enumerate((("Запустить сервер", lambda: self.administrative("start")),
                                                  ("Остановить сервер", self.stop), ("Настройки", lambda: self.administrative("configure")),
                                                  ("Открыть экран", self.display), ("Администрирование", lambda: self.display("admin")),
                                                  ("Экспорт диагностики", self.export))):
            ttk.Button(buttons, text=label, command=command).grid(row=index // 3, column=index % 3, sticky="ew", padx=3, pady=4)
        for column in range(3):
            buttons.columnconfigure(column, weight=1)
        ttk.Label(frame, text="Для установки, управления службой и изменения системных настроек требуются права администратора. Windows запросит подтверждение. Экран и веб-админка открываются без повышения прав.", wraplength=690).pack(anchor="w", pady=(0, 8))
        self.startup = tk.BooleanVar(value=user_startup_enabled())
        ttk.Checkbutton(frame, text="Открывать экран после моего входа в Windows", variable=self.startup, command=self.change_startup).pack(anchor="w", pady=5)
        self.maintenance = tk.BooleanVar(value=maintenance_enabled())
        ttk.Checkbutton(frame, text="Обслуживание: временно не открывать экран автоматически", variable=self.maintenance, command=self.change_maintenance).pack(anchor="w", pady=5)
        ttk.Label(frame, text="Для обслуживания экрана: Esc/F11 или Alt+F4. Полный экран не блокирует Windows.\nГруппы и сопряжение появятся в этапе 5; резервные копии и обновления — в этапе 7.", wraplength=690).pack(anchor="w", pady=15)
        if not getattr(sys, "frozen", False):
            ttk.Label(frame, text="Режим разработки: системная установка и автозапуск требуют собранного комплекта.", wraplength=690).pack(anchor="w")
        elif Path(sys.executable).parent != binary_directory():
            ttk.Button(frame, text="Установить на этот компьютер", command=lambda: self.administrative("install")).pack(anchor="w")
        self.poll()
        if configure:
            self.root.after(100, self.configure)

    def error(self, error, context=None):
        messagebox.showerror("Kiosk", access_message(error, context), parent=self.root)

    def background(self, action, success=None, error_context=None):
        if self.busy:
            return
        self.busy = True

        def work():
            try:
                value = action()
                if success:
                    self.root.after(0, lambda: success(value))
            except Exception as error:
                self.root.after(0, lambda error=error: self.error(error, error_context))
            finally:
                self.busy = False

        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        if not self.busy:
            def inspect():
                access_error = None
                try:
                    status = read_status(self.storage)
                    ready = check_ready(self.storage, status)
                except PermissionError as error:
                    status, ready = None, False
                    access_error = access_message(error, "status")
                except (OSError, ValueError):
                    status, ready = None, False
                try:
                    free = shutil.disk_usage(self.storage.root.anchor).free
                except OSError:
                    free = None
                return status, ready, free, available_memory(), access_error

            def shown(result):
                self.status, ready, free, memory, access_error = result
                if access_error:
                    lines = [access_error]
                elif self.status:
                    data = self.status
                    state = data["state"] if ready or data["state"] != "running" else "недоступен"
                    lines = [f"Устройство: {data['device_name']}\nUUID: {data['device_id']}",
                             f"Сервер: {state}\nАдрес: {data['origin'] or 'не настроен'}",
                             f"Режим: {data['mode']} • Ориентация: {data['orientation']}"]
                    if data["error"]:
                        lines.append("Последняя ошибка: " + str(data["error"]))
                else:
                    lines = ["Сервер остановлен или установка ещё не настроена."]
                lines.append("Свободное место недоступно для проверки." if free is None else f"Свободно на диске: {free // (1024 * 1024)} МиБ" + (" — мало места" if free < 1024 ** 3 else ""))
                lines.append(f"Доступно ОЗУ: {memory // (1024 * 1024)} МиБ" + (" — мало памяти" if memory < 256 * 1024 ** 2 else ""))
                lines.append("Группа / синхронизация / репликация: ещё не реализованы")
                self.details.set("\n\n".join(lines))
                if self.autostart:
                    self.autostart_attempts += 1
                    if maintenance_enabled() or self.autostart_attempts >= 60:
                        self.autostart = False
                    elif ready:
                        self.autostart = False
                        self.display()

            self.background(inspect, shown)
        self.root.after(2000, self.poll)

    def administrative(self, action):
        if not administrator():
            try:
                elevate(action)
            except Exception as error:
                self.error(error, "system")
            return
        if action == "configure":
            self.configure()
        elif action == "install":
            self.background(install, lambda result: messagebox.showinfo("Kiosk", "Программа установлена для всех пользователей этого компьютера. Запустите KioskLauncher.exe из Program Files\\Kiosk и откройте настройки. Автозапуск экрана каждый пользователь включает в своём сеансе."), error_context="system")
        else:
            self.background(lambda: control_service(action), error_context="system")

    def stop(self):
        if messagebox.askyesno("Остановка сервера", "Редактирование и обновления экранов станут недоступны. Автономный перезапуск экрана ещё не реализован.\n\nОстановить сервер?", parent=self.root):
            self.administrative("stop")

    def display(self, mode=None):
        def launch():
            data = read_status(self.storage)
            if not check_ready(self.storage, data):
                raise RuntimeError("Свой сервер ещё не готов. Проверьте состояние и сертификат.")
            open_display(data["origin"], mode or data["mode"], fullscreen=mode != "admin")
        self.background(launch, error_context="status")

    def change_startup(self):
        try:
            configure_user_startup(self.startup.get())
        except Exception as error:
            self.startup.set(not self.startup.get())
            self.error(error, "user_settings")

    def change_maintenance(self):
        try:
            set_maintenance(self.maintenance.get())
        except Exception as error:
            self.error(error, "user_settings")

    def export(self):
        target = filedialog.asksaveasfilename(parent=self.root, defaultextension=".zip", initialfile="Kiosk-diagnostics.zip")
        if target:
            self.background(lambda: export_diagnostics(self.storage, target), lambda result: messagebox.showinfo("Kiosk", "Диагностика сохранена."), error_context="export")

    def configure(self):
        if not administrator():
            try:
                elevate("configure")
            except Exception as error:
                self.error(error, "system")
            return
        try:
            current = read_profile(self.storage.profile) if self.storage.profile.exists() else None
            if service_state() not in {"absent", "stopped"}:
                raise RuntimeError("Перед настройкой корректно остановите сервер.")
        except Exception as error:
            self.error(error, "system")
            return
        window = tk.Toplevel(self.root)
        window.title("Настройка локального устройства")
        window.geometry("620x650")
        panel = ttk.Frame(window, padding=20)
        panel.pack(fill="both", expand=True)
        values = {}
        selections = (("device_name", "Название устройства", "Kiosk", None), ("language", "Язык экранов", "ru", ("ru", "en", "de")),
                      ("mode", "Режим экрана", "kiosk", ("kiosk", "tv")), ("orientation", "Ориентация дисплея Windows", "landscape", ("landscape", "portrait")),
                      ("port", "Локальный порт", "5000", None))
        for key, label, default, options in selections:
            ttk.Label(panel, text=label).pack(anchor="w", pady=(7, 0))
            values[key] = tk.StringVar(value=str(current[key]) if current else default)
            widget = ttk.Combobox(panel, textvariable=values[key], values=options, state="readonly") if options else ttk.Entry(panel, textvariable=values[key])
            widget.pack(fill="x")
        auto = tk.BooleanVar(value=current["server_autostart"] if current else True)
        ttk.Checkbutton(panel, text="Запускать сервер при загрузке Windows", variable=auto).pack(anchor="w", pady=12)
        ttk.Label(panel, text="Windows автоматически не поворачиваем. Настройте ориентацию дисплея в параметрах ОС.\nГрупповые роли недоступны до этапа 5.", wraplength=560).pack(anchor="w")
        password = tk.StringVar()
        repeat = tk.StringVar()
        if needs_administrator(self.storage):
            ttk.Label(panel, text="Пароль администратора (12–128 символов)").pack(anchor="w", pady=(10, 0))
            ttk.Entry(panel, textvariable=password, show="*").pack(fill="x")
            ttk.Label(panel, text="Повтор пароля").pack(anchor="w")
            ttk.Entry(panel, textvariable=repeat, show="*").pack(fill="x")
        elif not current:
            ttk.Label(panel, text="Будут сохранены существующие учётные записи.").pack(anchor="w", pady=12)

        def save():
            try:
                if not getattr(sys, "frozen", False) or Path(sys.executable).parent != binary_directory():
                    raise ValueError("Сначала установите собранный комплект и откройте Launcher из Program Files\\Kiosk.")
                profile = {**current} if current else new_profile(values["device_name"].get())
                profile.update({key: value.get() for key, value in values.items()})
                profile["port"] = int(profile["port"])
                profile["server_autostart"] = auto.get()
                from kiosk.launcher.storage import validate_profile

                validate_profile(profile)
                new_account = needs_administrator(self.storage)
                if new_account:
                    validate_password(password.get())
                    if password.get() != repeat.get():
                        raise ValueError("Пароли не совпадают.")
                initialize_directories(self.storage)
                app = create_app(self.storage.app_config())
                if new_account:
                    save_admin_password(app, password.get(), setup=True)
                password.set("")
                repeat.set("")
                save_profile(self.storage, profile)
                with app.app_context():
                    from kiosk.database import get_database, increase_content_version

                    database = get_database()
                    language = database.execute("SELECT value FROM settings WHERE key = 'interface_language'").fetchone()[0]
                    if language != profile["language"]:
                        database.execute("UPDATE settings SET value = ? WHERE key = 'interface_language'", (profile["language"],))
                        increase_content_version(database)
                        database.commit()
                register_service(self.storage)
                window.destroy()
                messagebox.showinfo("Kiosk", "Настройки сохранены. Запустите сервер. Автозапуск экрана включается отдельно в главном окне.", parent=self.root)
            except Exception as error:
                self.error(error, "system")

        ttk.Button(panel, text="Сохранить локальную установку", command=save).pack(fill="x", pady=18)


def run_gui(autostart=False, configure=False, storage=None):
    root = tk.Tk()
    Launcher(root, storage or Storage(common_root()), autostart=autostart, configure=configure)
    root.mainloop()
