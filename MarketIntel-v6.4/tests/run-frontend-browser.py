"""Optional Chromium regression: pip requirements + Node playwright and chart.js.

Run with the same Python environment as the app. NODE_PATH may point to an
external development-only Node installation; no package files are modified.
All browser/provider data and the Flask database are disposable fixtures.
"""
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen


def main():
    root = Path(__file__).resolve().parent.parent
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix='marketintel-browser-') as directory:
        env = dict(os.environ, MARKETINTEL_DATA_DIR=directory, PORT=str(port),
                   MARKETINTEL_TEST_URL=f'http://127.0.0.1:{port}')
        with open(Path(directory) / 'server.log', 'w+') as log:
            server = subprocess.Popen([sys.executable, '-u', 'servidor.py'], cwd=root,
                                      env=env, stdout=log, stderr=log)
            try:
                for _ in range(100):
                    try:
                        with urlopen(env['MARKETINTEL_TEST_URL'] + '/health', timeout=1) as response:
                            if response.status == 200:
                                break
                    except Exception:
                        if server.poll() is not None:
                            log.seek(0)
                            raise RuntimeError('El servidor de prueba no inició:\n' + log.read())
                        time.sleep(.25)
                else:
                    raise RuntimeError('El servidor de prueba no respondió.')
                return subprocess.run(['node', 'tests/frontend-browser.cjs'], cwd=root,
                                      env=env, timeout=300).returncode
            finally:
                server.terminate()
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait()


if __name__ == '__main__':
    raise SystemExit(main())
