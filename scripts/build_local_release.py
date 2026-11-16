"""Package only distributable local app sources; never include runtime data."""
from pathlib import Path
import hashlib
import zipfile

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / 'MarketIntel-v6.4'
VERSION = '6.5.0'
TARGET = ROOT / 'public' / 'descargas' / f'MarketIntel-{VERSION}.zip'
REPAIR_TARGET = TARGET.with_name(f'Reparar-MarketIntel-{VERSION}.zip')
TOP = {'index.html', 'requirements.txt', 'LEEME.md', 'VALIDACION-v6.md',
       'INICIAR.bat', 'CONFIGURAR_APIS.bat', 'abrir_marketintel.py',
       'configurar_apis.py', 'servidor.py', 'marketintel_data.py',
       'marketintel_pulse.py', 'marketintel_storage.py', 'marketintel_sync.py',
       'marketintel_reports.py', 'marketintel_report_sources.py', 'iniciar_app.py',
       'CREAR_ACCESO_DIRECTO.bat', 'crear_acceso_directo.ps1',
       'DETENER_MARKETINTEL.bat', 'detener_app.ps1'}
INSTRUCTIONS = '''MarketIntel 6.5.0 · Reportes PDF y acceso directo

1. Exporta tus datos desde Portafolio > Exportar todo JSON como copia adicional.
2. Descomprime en una carpeta nueva; conserva todos los archivos y static.
3. Si usabas .env, cópialo desde tu carpeta anterior. No está incluido aquí.
4. Cierra el servidor anterior. Ejecuta CREAR_ACCESO_DIRECTO.bat una sola vez.
   Después abre el icono MarketIntel de tu escritorio. También puedes seguir
   usando INICIAR.bat de esta carpeta nueva.
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

Pulso macro: los ejemplos se recalculan al abrir, al volver a la pestaña,
al recuperar conexión y cada 5 minutos mientras la app está abierta.
También puedes pulsar Actualizar ahora. No hay un proceso programado cuando
la app está cerrada. Las fuentes pueden publicar con retraso; revisa el período,
la consulta y las advertencias de cada dato. El consenso, las revisiones oficiales
y la reacción del mercado se indican como no verificados si falta una fuente.
Se utilizan las APIs ya configuradas. No necesitas una clave de IA adicional.

Se retiró el bloque Noticias actuales del mercado de Pulso macro.
Si el sitio de ISM pide acceso, se consulta su comunicado público en PR Newswire.
Se verifican el autor, el sector, el mes, el año, la cifra y la publicación.
La consulta descubre los nuevos informes mensuales; no necesita otra clave API.

REPORTES
En Inicio están Reporte de apertura y Reporte de sesión. El reporte de apertura
se genera antes de la apertura regular; el de sesión, desde las 17:00 de Nueva
York en días bursátiles. Las ventanas se comprueban con el calendario real.
Cada PDF conserva la hora de corte, las fuentes y los datos que recibiste.
Se usan conexiones existentes: no contiene cifras de los bocetos ni inventa
consenso, cobertura, precios o resultados. Si un proveedor no ofrece un dato,
se identifica como no disponible. La cobertura puede depender de tu plan API.
El reporte de sesión revisa la watchlist guardada en ese navegador. Una lista
vacía se mantiene vacía; no se sustituye por empresas de ejemplo.
Una publicación posterior a las 17:00 queda fuera de ese corte.

ACCESO DIRECTO
Conserva esta carpeta en una ubicación fija antes de crear el acceso directo.
No requiere administrador. El icono arranca el servidor y abre la aplicación;
si ya responde esta misma instalación, reutiliza el servidor. Conserva el
navegador predeterminado y localhost para acceder a tus datos habituales.
La primera apertura puede necesitar instalar dependencias con conexión.
Si mueves la carpeta, vuelve a ejecutar CREAR_ACCESO_DIRECTO.bat.
Cerrar la ventana conserva el servidor en segundo plano. Antes de cambiar de
carpeta o actualizar, usa DETENER_MARKETINTEL.bat en la instalación que abriste
con el acceso directo. Solo detiene ese servidor si comprueba su identidad.
'''


def main():
    files = [SOURCE / name for name in sorted(TOP)]
    files += sorted(p for p in (SOURCE / 'static').rglob('*')
                    if p.is_file() and p.suffix in {'.js', '.css', '.ico'}
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
    # A separate flat archive lets an incomplete Windows installation restore
    # this required module without mixing folders or replacing private .env.
    repair_module = SOURCE / 'marketintel_sync.py'
    repair_instructions = '''Reparar MarketIntel 6.5.0: falta marketintel_sync.py

1. Cierra la ventana negra de MarketIntel.
2. Extrae este ZIP. Copia marketintel_sync.py a la carpeta de tu programa,
   junto a servidor.py e INICIAR.bat. El archivo no va dentro de static.
3. Ejecuta INICIAR.bat de esa carpeta.

Conserva tus archivos .env. Este paquete no incluye claves ni datos de usuario.
Si faltan otros archivos, descarga y extrae el paquete completo:
https://marketintel-nu.vercel.app/descargas/MarketIntel-6.5.0.zip
'''
    with zipfile.ZipFile(REPAIR_TARGET, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in [('marketintel_sync.py', repair_module.read_bytes()),
                           ('LEER-REPARACION.txt', repair_instructions.encode('utf-8'))]:
            info = zipfile.ZipInfo(name, (2026, 10, 26, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, data)
    with zipfile.ZipFile(REPAIR_TARGET) as archive:
        assert archive.testzip() is None
        assert archive.read('marketintel_sync.py') == repair_module.read_bytes()
    print(f'Validated repair package: 2 files, {REPAIR_TARGET.stat().st_size} bytes')


if __name__ == '__main__':
    main()
