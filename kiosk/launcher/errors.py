class AdministratorRequired(PermissionError):
    pass


class ElevationUnavailable(RuntimeError):
    pass


class StatusAccessDenied(PermissionError):
    pass


def access_message(error, context=None):
    if isinstance(error, AdministratorRequired):
        return "Для этой системной операции требуются права администратора. Запустите Kiosk Launcher от имени администратора или обратитесь к администратору компьютера."
    if isinstance(error, ElevationUnavailable):
        return "Разрешение администратора не получено: запрос Windows отменён или недоступен. Операция не выполнена. Повторите действие и подтвердите запрос Windows либо обратитесь к администратору компьютера."
    if isinstance(error, StatusAccessDenied):
        context = "status"
    if isinstance(error, PermissionError):
        if context == "export":
            return "Нет доступа к выбранной папке для сохранения диагностики. Выберите другую папку, в которую вам разрешено записывать файлы."
        if context == "user_settings":
            return "Нет доступа к настройкам текущего пользователя Windows. Проверьте разрешения его папки LocalAppData или обратитесь к администратору компьютера."
        if context == "status":
            return "Нет доступа к состоянию службы. Это не означает, что сервер остановлен. Обратитесь к администратору для проверки разрешений установки."
        if context == "system":
            return "Недостаточно прав для доступа к системным файлам программы. Запустите Kiosk Launcher от имени администратора. Если ошибка повторяется, администратору необходимо проверить разрешения установки."
        return "Нет доступа к файлу или папке. Проверьте разрешения выбранного расположения или обратитесь к администратору компьютера."
    return f"Операция не выполнена ({type(error).__name__}).\n{error}"
