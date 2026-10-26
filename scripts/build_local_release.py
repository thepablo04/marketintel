"""Package only distributable local app sources; never include runtime data."""
from pathlib import Path
import hashlib
import zipfile

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / 'MarketIntel-v6.4'
VERSION = '6.4.4'
TARGET = ROOT / 'public' / 'descargas' / f'MarketIntel-{VERSION}.zip'
TOP = {'index.html', 'requirements.txt', 'LEEME.md', 'VALIDACION-v6.md',
       'INICIAR.bat', 'CONFIGURAR_APIS.bat', 'abrir_marketintel.py',
       'configurar_apis.py', 'servidor.py', 'marketintel_data.py',
       'marketintel_pulse.py', 'marketintel_storage.py', 'marketintel_sync.py'}
INSTRUCTIONS = '''MarketIntel 6.4.4 · Sincronización entre dispositivos

1. Exporta tus datos desde Portafolio > Exportar todo JSON como copia adicional.
2. Descomprime en una carpeta nueva; conserva todos los archivos y static.
3. Si usabas .env, cópialo desde tu carpeta anterior. No está incluido aquí.
4. Cierra el servidor anterior y ejecuta INICIAR.bat de esta carpeta nueva.
5. Usa el mismo navegador y http://localhost:5050 para conservar tus datos.
6. Abre Sincronizar en Portafolio. Crea tu sincronización en el dispositivo
   que ya tiene tus datos y guarda la clave privada.
7. En https://marketintel-nu.vercel.app abre Sincronizar y pega esa clave
   en Vincular dispositivo. Haz lo mismo en los otros dispositivos que uses.

Se sincronizan cuentas y operaciones, notas y watchlist. Sin conexión puedes
seguir trabajando en local; los cambios se enviarán al recuperar internet.
Si dos dispositivos cambian la misma cuenta o nota, revisa las versiones.
Las claves API, preferencias, grupos del heatmap y respaldos quedan locales.
No abras index.html directamente: usa el servidor de INICIAR.bat.
La sincronización es opcional. Guarda la clave privada; quien la tenga puede
acceder a tu copia. No se puede recuperar si no queda un dispositivo vinculado.
'''


def main():
    files = [SOURCE / name for name in sorted(TOP)]
    files += sorted(p for p in (SOURCE / 'static').rglob('*')
                    if p.is_file() and p.suffix in {'.js', '.css'}
                    and not any(part.startswith('.') for part in p.relative_to(SOURCE).parts))
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    # Stable timestamps make this artifact reproducible and easy to compare.
    with zipfile.ZipFile(TARGET, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            info = zipfile.ZipInfo(str(Path(SOURCE.name) / path.relative_to(SOURCE)), (2026, 10, 26, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes())
        info = zipfile.ZipInfo(SOURCE.name + '/ACTUALIZAR.txt', (2026, 10, 26, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(info, INSTRUCTIONS)
    with zipfile.ZipFile(TARGET) as archive:
        assert archive.testzip() is None
        for path in files:
            assert archive.read(str(Path(SOURCE.name) / path.relative_to(SOURCE))) == path.read_bytes()
    print(f'Validated local package: {len(files) + 1} files, {TARGET.stat().st_size} bytes')
    print('SHA-256:', hashlib.sha256(TARGET.read_bytes()).hexdigest())


if __name__ == '__main__':
    main()
