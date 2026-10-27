"""Build a standalone calendar and its local ZIP from reviewed sources."""
from pathlib import Path
import base64
import hashlib
import zipfile

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / 'Frangi'
OUTPUT = SOURCE / 'frangi.html'
DOWNLOAD = ROOT / 'public' / 'descargas' / 'Frangi-sincronizado.zip'


def main():
    template = (SOURCE / 'template.html').read_text(encoding='utf-8')
    preflight = (SOURCE / 'sync-preflight.js').read_text(encoding='utf-8')
    core = (SOURCE / 'sync-core.js').read_text(encoding='utf-8')
    ui = (SOURCE / 'sync-ui.js').read_text(encoding='utf-8')
    engine = (SOURCE / 'sync-engine.js').read_text(encoding='utf-8')
    for part in (preflight, core, ui, engine):
        if '</script' in part.lower():
            raise RuntimeError('Embedded script contains an HTML closing tag')
    if template.count('<!-- FRANGI_PREFLIGHT -->') != 1 or template.count('</body>') != 1:
        raise RuntimeError('Incomplete Frangi HTML template')
    html = template.replace('<!-- FRANGI_PREFLIGHT -->', '<script>\n' + preflight + '\n</script>')
    html = html.replace('</body>', '\n'.join([
        '<script>' + core + '</script>',
        '<script>' + ui + '</script>',
        '<script>' + engine + '</script>',
        '<script>readyTrades.then(window.FrangiStartSync);</script>',
        '</body>',
    ]))
    OUTPUT.write_text(html, encoding='utf-8')
    DOWNLOAD.parent.mkdir(parents=True, exist_ok=True)
    readme = '''Frangi: calendario TP / SL con sincronización cifrada

1. Conserva una copia de tu frangi.html anterior.
2. Reemplázalo por este frangi.html en la misma carpeta y ábrelo en el mismo navegador.
   Así podrá leer las marcas guardadas en ese navegador.
3. Abre Sincronizar. Puedes crear una clave FR1 nueva o usar tu clave MI1 de
   MarketIntel para iniciar un calendario separado.
4. En la otra PC, abre este mismo frangi.html y usa Vincular con la misma clave.
5. También puedes abrir https://marketintel-nu.vercel.app/frangi/index.html
   y vincular la misma clave allí.

Los cambios sin conexión permanecen en el navegador y se envían al reconectar.
El ZIP no contiene tus trades ni claves privadas. La opción Descargar copia JSON
permite guardar otra copia de los registros. La clave es necesaria para vincular
otros navegadores; guárdala en privado.
'''
    with zipfile.ZipFile(DOWNLOAD, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.write(OUTPUT, 'frangi.html')
        archive.writestr('LEEME.txt', readme)
    with zipfile.ZipFile(DOWNLOAD) as archive:
        assert archive.testzip() is None
        assert archive.read('frangi.html') == OUTPUT.read_bytes()
    encoded = base64.b64encode(DOWNLOAD.read_bytes()).decode('ascii')
    download_page = f'''<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Descargar Frangi</title>
<style>body{{min-height:100vh;margin:0;padding:24px;display:grid;place-items:center;background:#0f1115;color:#e7e9ee;font:16px/1.5 system-ui}}main{{max-width:420px;padding:28px;border:1px solid #2a2e37;border-radius:14px;background:#171a21;text-align:center}}h1{{font-size:23px}}a{{display:block;background:#4f8cff;color:white;padding:13px;border-radius:8px;text-decoration:none;font-weight:700}}p,small{{color:#aab0bc}}</style>
<main><h1>Calendario de trading</h1><p>Varios trades por día y sincronización privada entre tus equipos.</p><a download="Frangi-sincronizado.zip" href="data:application/zip;base64,{encoded}">Descargar ZIP</a><p>Extrae el ZIP y reemplaza frangi.html en la misma carpeta.</p></main></html>'''
    (ROOT.parent / 'Descargar-frangi.html').write_text(download_page, encoding='utf-8')
    (ROOT.parent / 'frangi.html').write_bytes(OUTPUT.read_bytes())
    (ROOT.parent / 'frangi-actualizado.html').write_bytes(OUTPUT.read_bytes())
    (ROOT.parent / 'frangi-actualizado.zip').write_bytes(DOWNLOAD.read_bytes())
    print(f'Validated Frangi: {OUTPUT.stat().st_size} HTML bytes; {DOWNLOAD.stat().st_size} ZIP bytes')
    print('Frangi SHA-256:', hashlib.sha256(DOWNLOAD.read_bytes()).hexdigest())


if __name__ == '__main__':
    main()
