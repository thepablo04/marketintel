"""Arranca MarketIntel desde el acceso directo, sin una consola de servidor.

Solo usa la biblioteca estándar hasta comprobar/instalar requirements.txt.
Conserva localhost y el navegador predeterminado para reutilizar los datos.
"""
from contextlib import AbstractContextManager
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, build_opener
import webbrowser


APP_DIR = Path(__file__).resolve().parent
DEPENDENCIES = ('flask', 'flask_cors', 'yfinance', 'pandas', 'requests',
                'dotenv', 'exchange_calendars', 'tzdata', 'reportlab')


class LaunchError(RuntimeError):
    pass


def install_id(directory):
    return hashlib.sha256(str(Path(directory).resolve()).encode()).hexdigest()[:16]


def app_version(directory):
    text = (Path(directory) / 'servidor.py').read_text(encoding='utf-8')
    match = re.search(r"^APP_VERSION\s*=\s*['\"]([^'\"]+)['\"]", text, re.M)
    if not match:
        raise LaunchError('No se pudo identificar esta versión de MarketIntel. Extrae de nuevo el paquete completo.')
    return match.group(1)


def read_port(directory, environ=None):
    """Read just PORT before python-dotenv is installed; never log .env values."""
    env = os.environ if environ is None else environ
    value = env.get('PORT')
    if value is None:
        path = Path(directory) / '.env'
        try:
            for line in path.read_text(encoding='utf-8-sig').splitlines():
                match = re.match(r'^\s*(?:export\s+)?PORT\s*=\s*(.*?)\s*$', line)
                if match:
                    raw = match.group(1)
                    if raw.startswith(('"', "'")):
                        quote = raw[0]
                        value = raw[1:raw.find(quote, 1)] if quote in raw[1:] else raw
                    else:
                        value = raw.split('#', 1)[0].strip()
                    # dotenv normally expands ${NAME} from the environment.
                    value = re.sub(r'\$\{([A-Za-z_][A-Za-z0-9_]*)\}', lambda m: env.get(m.group(1), ''), value)
        except FileNotFoundError:
            pass
    try:
        port = int(value if value is not None else 5050)
    except (ValueError, TypeError):
        raise LaunchError('PORT debe ser un número entre 1 y 65535. Revisa esa variable en tu archivo .env.') from None
    if not 1 <= port <= 65535:
        raise LaunchError('PORT debe estar entre 1 y 65535. Revisa esa variable en tu archivo .env.')
    return port


def log_directory(environ=None):
    env = os.environ if environ is None else environ
    if env.get('MARKETINTEL_DATA_DIR'):
        return Path(env['MARKETINTEL_DATA_DIR']).expanduser().resolve()
    if os.name == 'nt':
        return Path(env.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local') / 'MarketIntel'
    return Path(env.get('XDG_DATA_HOME') or Path.home() / '.local' / 'share') / 'MarketIntel'


def prepare_log(path):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.exists() and path.stat().st_size > 2_000_000:
        path.replace(path.with_suffix(path.suffix + '.1'))
    return path.open('a', encoding='utf-8')


def hidden_process_options():
    return {'creationflags': subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt' else {'start_new_session': True}


def process_start_filetime(pid):
    """Windows creation time is stable even if a numeric PID is later reused."""
    if os.name != 'nt':
        return None
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        raise LaunchError('No se pudo registrar el proceso para detenerlo con seguridad.')
    try:
        created, ended, kernel_time, user_time = [wintypes.FILETIME() for _ in range(4)]
        if not kernel.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(ended), ctypes.byref(kernel_time), ctypes.byref(user_time)):
            raise LaunchError('No se pudo registrar la hora de inicio del servidor.')
        return str((created.dwHighDateTime << 32) | created.dwLowDateTime)
    finally:
        kernel.CloseHandle(handle)


def record_server(data_dir, directory, child, port, version, token):
    record = {
        'pid': int(child.pid), 'directory': str(directory), 'install_id': install_id(directory),
        'server': str(directory / 'servidor.py'), 'python': str(Path(python_console()).resolve()),
        'port': port, 'version': version, 'launcher_token': token,
        'start_filetime': process_start_filetime(child.pid),
    }
    path = Path(data_dir) / ('servidor-' + record['install_id'] + '.json')
    temporary = path.with_suffix('.' + token + '.tmp')
    temporary.write_text(json.dumps(record, ensure_ascii=False), encoding='utf-8')
    temporary.replace(path)
    return path


def python_console():
    executable = Path(sys.executable)
    if executable.name.lower() == 'pythonw.exe' and executable.with_name('python.exe').exists():
        return str(executable.with_name('python.exe'))
    return str(executable)


def probe_server(port, expected_install, expected_version):
    """Return offline, ready, old-version or foreign; never accept another app."""
    opener = build_opener(ProxyHandler({}))
    try:
        with opener.open(f'http://127.0.0.1:{port}/health', timeout=.8) as response:
            payload = response.read(65537)
            if len(payload) > 65536:
                return 'foreign'
            data = json.loads(payload)
            if data.get('service') != 'MarketIntel' or data.get('install_id') != expected_install:
                return 'foreign'
            return 'ready' if data.get('version') == expected_version else 'old-version'
    except HTTPError:
        return 'foreign'
    except (ValueError, TypeError, AttributeError, UnicodeError):
        return 'foreign'
    except (URLError, TimeoutError, OSError):
        # A different process may be listening without a /health response.
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=.3):
                return 'foreign'
        except OSError:
            return 'offline'


def require_available(state):
    if state == 'old-version':
        raise LaunchError('Hay una versión anterior de MarketIntel usando este puerto. Cierra su servidor y vuelve a abrir el acceso directo.')
    if state == 'foreign':
        raise LaunchError('Otra aplicación o carpeta de MarketIntel está usando este puerto. Cierra ese servidor o revisa PORT en .env. No se cerró ningún proceso.')


class StartupLock(AbstractContextManager):
    """Only one launcher for this folder can install/start the server at a time."""
    def __init__(self, directory, data_dir):
        self.identity = install_id(directory)
        self.data_dir = Path(data_dir)
        self.handle = None
        self.file = None
        self.acquired = False

    def __enter__(self):
        if os.name == 'nt':
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
            kernel.CreateMutexW.restype = ctypes.c_void_p
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel.ReleaseMutex.argtypes = [ctypes.c_void_p]
            self.kernel = kernel
            self.handle = kernel.CreateMutexW(None, True, 'Local\\MarketIntelLauncher-' + self.identity)
            if not self.handle:
                raise LaunchError('No se pudo reservar el inicio de MarketIntel.')
            self.acquired = ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS
            if not self.acquired:
                kernel.CloseHandle(self.handle)
                self.handle = None
        else:
            import fcntl
            self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.file = (self.data_dir / ('inicio-' + self.identity + '.lock')).open('a')
            try:
                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.acquired = True
            except BlockingIOError:
                self.file.close()
                self.file = None
        return self.acquired

    def __exit__(self, *exc):
        if self.handle:
            self.kernel.ReleaseMutex(self.handle)
            self.kernel.CloseHandle(self.handle)
        if self.file:
            import fcntl
            fcntl.flock(self.file, fcntl.LOCK_UN)
            self.file.close()
        return False


class Progress:
    def __init__(self):
        self.root = None
        self.cancelled = False
        try:
            import tkinter as tk
            from tkinter import ttk
            root = tk.Tk()
            root.title('MarketIntel')
            root.geometry('450x145')
            root.resizable(False, False)
            self.message = tk.StringVar(value='Abriendo MarketIntel…')
            ttk.Label(root, textvariable=self.message, padding=(20, 20), wraplength=410).pack(fill='x')
            bar = ttk.Progressbar(root, mode='indeterminate')
            bar.pack(fill='x', padx=20)
            bar.start(12)
            root.protocol('WM_DELETE_WINDOW', self.cancel)
            self.root = root
            self.pump()
        except Exception:
            self.root = None

    def cancel(self):
        self.cancelled = True

    def pump(self):
        if self.cancelled:
            raise LaunchError('Se canceló el inicio de MarketIntel. Puedes volver a abrirlo desde el acceso directo.')
        if self.root:
            self.root.update_idletasks()
            self.root.update()

    def status(self, message):
        if self.root:
            self.message.set(message)
        self.pump()

    def close(self):
        if self.root:
            self.root.destroy()
            self.root = None


def wait_child(child, progress, timeout):
    deadline = time.monotonic() + timeout
    try:
        while child.poll() is None:
            progress.pump()
            if time.monotonic() >= deadline:
                raise LaunchError('La instalación tardó demasiado. Revisa tu conexión y vuelve a abrir MarketIntel.')
            time.sleep(.1)
        return child.returncode
    except BaseException:
        if child.poll() is None:
            child.terminate()
        raise


def install_dependencies(directory, progress, log):
    progress.status('Comprobando las dependencias de MarketIntel…')
    command = [python_console(), '-c', '; '.join('import ' + module for module in DEPENDENCIES)]
    check = subprocess.Popen(command, cwd=directory, stdin=subprocess.DEVNULL,
                             stdout=log, stderr=subprocess.STDOUT, **hidden_process_options())
    if wait_child(check, progress, 40) == 0:
        return
    progress.status('Primera apertura: instalando dependencias. Puede tardar unos minutos…')
    child = subprocess.Popen([python_console(), '-m', 'pip', 'install', '-r', str(Path(directory) / 'requirements.txt')],
                             cwd=directory, stdin=subprocess.DEVNULL, stdout=log,
                             stderr=subprocess.STDOUT, **hidden_process_options())
    if wait_child(child, progress, 600) != 0:
        raise LaunchError('No se pudieron instalar las dependencias. Revisa tu conexión y Python. Puedes consultar inicio.log en la carpeta de datos de MarketIntel.')


def default_app_browser():
    """App-mode only for the actual default Edge/Chrome, without a new profile."""
    if os.name != 'nt':
        return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\Shell\Associations\UrlAssociations\http\UserChoice') as key:
            progid = winreg.QueryValueEx(key, 'ProgId')[0]
        if progid.lower().startswith('chromehtml'):
            browser = 'chrome.exe'
        elif progid.lower().startswith('msedgehtm'):
            browser = 'msedge.exe'
        else:
            return None
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(hive, 'Software\\Microsoft\\Windows\\CurrentVersion\\App Paths\\' + browser) as key:
                    path = winreg.QueryValueEx(key, None)[0]
                if Path(path).is_file():
                    return path
            except OSError:
                pass
        return shutil.which(browser)
    except (OSError, ImportError):
        return None


def installed_app_browsers():
    """Only registered Chrome/Edge executables; never trust executable paths in settings."""
    paths = []
    default = default_app_browser()
    if default:
        paths.append(default)
    if os.name == 'nt':
        import winreg
        for name in ('chrome.exe', 'msedge.exe'):
            for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                try:
                    with winreg.OpenKey(hive, 'Software\\Microsoft\\Windows\\CurrentVersion\\App Paths\\' + name) as key:
                        candidate = winreg.QueryValueEx(key, None)[0]
                    if Path(candidate).is_file():
                        paths.append(candidate)
                except OSError:
                    pass
    return list(dict.fromkeys(str(Path(p)) for p in paths))


def browser_profiles(browsers=None, local_appdata=None):
    """Read profile names only. Never access or copy browser databases or credentials."""
    base = Path(local_appdata or os.environ.get('LOCALAPPDATA') or '')
    if not str(base) or str(base) == '.':
        return []
    result = []
    for executable in installed_app_browsers() if browsers is None else browsers:
        executable = str(executable)
        name = Path(executable).name.lower()
        if name == 'chrome.exe':
            brand, relative = 'Google Chrome', 'Google/Chrome/User Data'
        elif name == 'msedge.exe':
            brand, relative = 'Microsoft Edge', 'Microsoft/Edge/User Data'
        else:
            continue
        # Alternate channels have distinct data roots. Fall back to the regular
        # browser if the corresponding Local State is not available.
        lower = executable.lower().replace('\\', '/')
        if name == 'chrome.exe':
            for channel in ('Chrome Beta', 'Chrome Dev', 'Chrome SxS'):
                if '/'+channel.lower()+'/' in lower:
                    relative = 'Google/'+channel+'/User Data'; brand = channel
        else:
            for channel in ('Edge Beta', 'Edge Dev', 'Edge SxS'):
                if '/'+channel.lower()+'/' in lower:
                    relative = 'Microsoft/'+channel+'/User Data'; brand = channel
        data_root = base / relative
        try:
            state_file = data_root / 'Local State'
            if state_file.stat().st_size > 8_000_000:
                continue
            profile_state = json.loads(state_file.read_text(encoding='utf-8')).get('profile', {})
            entries = profile_state.get('info_cache', {})
            if not isinstance(entries, dict):
                continue
            for directory, meta in entries.items():
                if (not isinstance(directory, str) or not isinstance(meta, dict)
                    or not re.fullmatch(r'Default|Profile [0-9]+', directory)
                    or not (data_root / directory).is_dir() or meta.get('is_omitted')):
                    continue
                display = str(meta.get('name') or directory)[:80]
                result.append({'executable': executable, 'directory': directory,
                               'label': brand+' · '+display+' ('+directory+')',
                               'last_used': directory == profile_state.get('last_used')})
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    return result


def select_browser_profile(profiles, preferred=0):
    """A one-time choice avoids guessing where a multi-profile user keeps their portfolio."""
    try:
        import tkinter as tk
        from tkinter import ttk
        parent = tk._default_root
        window = tk.Toplevel(parent) if parent else tk.Tk()
        window.title('MarketIntel · Elegir perfil')
        window.geometry('600x285'); window.resizable(False, False)
        if parent:
            window.transient(parent)
        ttk.Label(window, text='¿En qué perfil ves tu portafolio al abrir localhost?',
                  font=('', 12, 'bold'), padding=(18, 16), wraplength=560).pack(fill='x')
        ttk.Label(window, text='Elige el mismo navegador y perfil donde aparecen tus cuentas.\nSe recordará para las siguientes aperturas del icono.',
                  padding=(18, 0), wraplength=560).pack(fill='x')
        combo = ttk.Combobox(window, state='readonly', values=[p['label'] for p in profiles])
        combo.pack(fill='x', padx=18, pady=18); combo.current(preferred)
        ttk.Label(window, text='Tus datos permanecen en el navegador. No se trasladan ni se reemplazan.',
                  padding=(18, 0), wraplength=560).pack(fill='x')
        selected = [False]
        def choose(value):
            selected[0] = value
            window.destroy()
        buttons = ttk.Frame(window, padding=(18, 14));buttons.pack(fill='x')
        ttk.Button(buttons, text='Usar este perfil', command=lambda: choose(dict(profiles[combo.current()]))).pack(side='right')
        ttk.Button(buttons, text='Abrir en el navegador habitual', command=lambda: choose(None)).pack(side='left')
        window.protocol('WM_DELETE_WINDOW', lambda: choose(False))
        window.grab_set();combo.focus_set()
        window.wait_window()
        return selected[0]
    except Exception:
        # No GUI/profile detection must fall back to the same URL-opening method
        # as INICIAR.bat, rather than guess a profile or create a new one.
        return None


def app_browser_choice(force=False, *, profiles=None, settings_path=None, picker=None):
    path = Path(settings_path) if settings_path else log_directory() / 'navegador.json'
    catalog = browser_profiles() if profiles is None else profiles
    saved = {}
    try:
        if path.stat().st_size <= 4096:
            saved = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(saved, dict):
            saved = {}
    except (OSError, ValueError):
        pass
    if not force and saved.get('version') == 1:
        if saved.get('mode') == 'browser':
            return None
        for profile in catalog:
            if (saved.get('executable') == profile['executable']
                and saved.get('directory') == profile['directory']):
                return profile
    if not catalog:
        return None
    default = default_app_browser()
    default_profiles = [p for p in catalog if p['executable'] == default]
    preferred = next((i for i,p in enumerate(catalog) if p in default_profiles and p.get('last_used')), 0)
    if not force and len(default_profiles) == 1:
        choice = default_profiles[0]
    else:
        choice = (picker or select_browser_profile)(catalog, preferred)
    if choice is False:
        raise LaunchError('Se canceló la selección de perfil. Tus datos no se modificaron.')
    # Store only a selection, never account records, browser keys or .env data.
    record = {'version': 1, 'mode': 'app' if choice else 'browser'}
    if choice:
        record.update(executable=choice['executable'], directory=choice['directory'])
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = path.with_suffix('.tmp')
        with temporary.open('w', encoding='utf-8') as stream:
            json.dump(record, stream)
        temporary.replace(path)
    except OSError:
        # The current launch may still use the selected profile if persistence
        # isn't writable; a subsequent run will ask rather than guess.
        pass
    return choice


def open_app(port):
    url = f'http://localhost:{port}'
    profile = app_browser_choice()
    if profile:
        try:
            subprocess.Popen([profile['executable'], '--profile-directory='+profile['directory'], '--app=' + url], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except OSError:
            pass
    if not webbrowser.open(url):
        raise LaunchError('El servidor está listo, pero no se pudo abrir tu navegador. Abre ' + url)


def launch(directory, progress, data_dir=None):
    directory = Path(directory).resolve()
    data_dir = Path(data_dir) if data_dir else log_directory()
    port = read_port(directory)
    identity, version = install_id(directory), app_version(directory)
    with StartupLock(directory, data_dir) as acquired:
        if not acquired:
            return 'already-starting'
        state = probe_server(port, identity, version)
        require_available(state)
        if state == 'ready':
            open_app(port)
            return 'reused'
        with prepare_log(data_dir / 'inicio.log') as setup_log:
            install_dependencies(directory, progress, setup_log)
        # Recheck after installation in case another launcher/INICIAR.bat started.
        state = probe_server(port, identity, version)
        require_available(state)
        if state == 'ready':
            open_app(port)
            return 'reused'
        progress.status('Iniciando el servidor local…')
        env = dict(os.environ, PORT=str(port))
        token = secrets.token_hex(16)
        log = prepare_log(data_dir / 'servidor.log')
        try:
            child = subprocess.Popen([python_console(), '-u', str(directory / 'servidor.py'), '--marketintel-launcher-token', token],
                                     cwd=directory, env=env, stdin=subprocess.DEVNULL,
                                     stdout=log, stderr=subprocess.STDOUT, **hidden_process_options())
        finally:
            log.close()
        try:
            record_server(data_dir, directory, child, port, version, token)
            deadline = time.monotonic() + 65
            while time.monotonic() < deadline:
                progress.pump()
                state = probe_server(port, identity, version)
                require_available(state)
                if state == 'ready':
                    progress.status('Abriendo tu navegador…')
                    open_app(port)
                    return 'started'
                if child.poll() is not None:
                    raise LaunchError('El servidor no pudo iniciarse. Revisa servidor.log en la carpeta de datos de MarketIntel o ejecuta INICIAR.bat para ver el detalle.')
                time.sleep(.4)
            raise LaunchError('El servidor no respondió a tiempo. Revisa servidor.log en la carpeta de datos de MarketIntel.')
        except BaseException:
            # Only terminate the process this launcher created, never a foreign server.
            if child.poll() is None:
                child.terminate()
            raise


def show_error(message):
    if os.name == 'nt':
        ctypes.windll.user32.MessageBoxW(None, message, 'MarketIntel', 0x10)
    else:
        print(message, file=sys.stderr)


def main():
    progress = Progress()
    try:
        if '--elegir-perfil' in sys.argv[1:]:
            app_browser_choice(force=True)
        launch(APP_DIR, progress)
        return 0
    except LaunchError as exc:
        progress.close()
        show_error(str(exc))
        return 1
    except Exception:
        progress.close()
        show_error('No se pudo abrir MarketIntel. Comprueba que la carpeta esté completa y que tengas permiso de lectura. Prueba INICIAR.bat para ver el detalle.')
        return 1
    finally:
        progress.close()


if __name__ == '__main__':
    raise SystemExit(main())
