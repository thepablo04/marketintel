"""Optional DOM integration test: requires Node and development dependency jsdom.

Uses a temporary database and fixture prices, never the user's portfolio.
This checks JavaScript behavior, not browser layout or chart rendering.
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
    with tempfile.TemporaryDirectory(prefix='marketintel-dom-') as directory:
        env = dict(os.environ, MARKETINTEL_DATA_DIR=directory, PORT=str(port),
                   MARKETINTEL_TEST_URL=f'http://127.0.0.1:{port}')
        server = subprocess.Popen([sys.executable, '-u', 'servidor.py'], cwd=root,
                                  env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(100):
                try:
                    with urlopen(env['MARKETINTEL_TEST_URL']+'/health', timeout=1) as response:
                        if response.status == 200:
                            break
                except Exception:
                    if server.poll() is not None:
                        raise RuntimeError('El servidor de prueba no inició. Revisa requirements.txt.')
                    time.sleep(.25)
            else:
                raise RuntimeError('El servidor de prueba no respondió.')
            return subprocess.run(['node', 'tests/frontend-dom.cjs'], cwd=root,
                                  env=env, timeout=60).returncode
        finally:
            server.terminate()
            server.wait(timeout=10)


if __name__ == '__main__':
    raise SystemExit(main())
