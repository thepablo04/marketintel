"""Abre MarketIntel cuando el servidor local ya responde."""

import time
import webbrowser
import hashlib
import json
import os
from pathlib import Path
from urllib.request import urlopen
from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name('.env'))


def main():
    deadline = time.monotonic() + 45
    port = int(os.environ.get('PORT', 5050))
    install_id = hashlib.sha256(str(Path(__file__).resolve().parent).encode()).hexdigest()[:16]
    url = f'http://127.0.0.1:{port}/health'
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=1) as response:
                if response.status == 200:
                    data = json.load(response)
                    if data.get('install_id') != install_id:
                        print('Hay otra carpeta/version de MarketIntel abierta. Cierrala y ejecuta INICIAR.bat de esta carpeta.')
                        return
                    webbrowser.open(f'http://localhost:{port}')
                    return
        except Exception:
            time.sleep(0.5)
    print('No se pudo abrir MarketIntel: el servidor no respondio en 45 segundos.')


if __name__ == '__main__':
    main()
