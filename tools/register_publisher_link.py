"""Per-user kiosk:// publisher link registration (HKCU only; no administrator).

Run during guided first-device setup on the Windows publisher PC. The browser's
"Open on an authorized publisher device" link then starts the local publisher app
with the exact candidate link; no identifier typing or repeated file transfer.
This changes only the current user's file-association class.
"""
import argparse
import sys
from pathlib import Path
import winreg

KEY = r'Software\Classes\kiosk'


def command(executable, arguments):
    parts = ['"' + str(Path(executable).absolute()) + '"']
    if arguments:
        parts.append(arguments.strip())
    parts.append('"%1"')
    return ' '.join(parts)


def register(executable, arguments=''):
    if not Path(executable).is_file():
        raise ValueError('publisher_executable_missing')
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, KEY) as root:
        winreg.SetValueEx(root, '', 0, winreg.REG_SZ, 'URL:Kiosk publisher link')
        winreg.SetValueEx(root, 'URL Protocol', 0, winreg.REG_SZ, '')
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, KEY + r'\shell\open\command') as shell:
        winreg.SetValueEx(shell, '', 0, winreg.REG_SZ, command(executable, arguments))
    return command(executable, arguments)


def unregister():
    def remove(path):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_ALL_ACCESS) as key:
                while True:
                    try:
                        name = winreg.EnumKey(key, 0)
                    except OSError:
                        break
                    remove(path + '\\' + name)
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
        except FileNotFoundError:
            pass
    remove(KEY)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path, help='Built KioskPublisher executable')
    parser.add_argument('--arguments', default='', help='Fixed arguments such as --root/--origin/--ca')
    parser.add_argument('--unregister', action='store_true')
    options = parser.parse_args(argv)
    if sys.platform != 'win32':
        print('Windows only; no registration performed.')
        return 1
    try:
        if options.unregister:
            unregister()
            print('Removed the current user kiosk:// association.')
            return 0
        if options.exe is None:
            parser.error('--exe is required to register')
        print('Registered current-user kiosk:// -> ' + register(options.exe, options.arguments))
        return 0
    except (OSError, ValueError):
        print('Registration refused; existing association preserved.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
