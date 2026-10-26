# MarketIntel en Vercel

Sitio publicado: https://marketintel-nu.vercel.app.

El repositorio se despliega desde su raíz, con **Framework: Flask** y **Root Directory: `.`**. `app.py` carga la aplicación de `MarketIntel-v6.4/servidor.py`. El arranque local mediante `INICIAR.bat` sigue usando esa carpeta y no necesita Vercel ni Node.

La configuración usa Python 3.12 y las mismas dependencias que la instalación local. El enlace `public/static` apunta a `MarketIntel-v6.4/static` para servir los mismos archivos mediante la CDN. `scripts/build_vercel.py` comprueba las dependencias y la integridad de esos recursos. La página principal y las API siguen en Flask; no se debe publicar solo `index.html`.

## Publicar una actualización

Con Node y Vercel CLI disponibles, desde la raíz del repositorio:

```sh
npx vercel login
npx vercel link --project marketintel
python scripts/build_local_release.py
npx vercel deploy
```

Comprueba el despliegue de prueba antes de publicar la versión de producción:

```sh
npx vercel deploy --prod
```

El CLI muestra las direcciones reales al terminar. No copies credenciales a archivos de configuración versionados. `.vercelignore` excluye claves `.env`, bases locales, copias, dependencias instaladas y pruebas.

## Datos locales y datos web

- **En local:** operaciones y preferencias siguen en el navegador; los respaldos y el seguimiento de señales permanecen en SQLite fuera de la carpeta de instalación.
- **En Vercel:** operaciones y preferencias siguen en el navegador; respaldos y seguimiento de señales usan IndexedDB del mismo navegador y dominio. Las funciones del servidor no guardan esos datos personales en disco. Solo la caché desechable de Yahoo se escribe en `/tmp`.
- El diario web conserva una lectura por ventana válida, evalúa resultados con cierres de sesiones anteriores verificados por el servidor y permite exportar el historial completo desde Inicio.
- Cada dominio de prueba y producción tiene sus propios datos. Para trasladar portafolio, watchlist, notas y grupos del heatmap, usa **Exportar todo JSON** en local y **Importar JSON** en el dominio de producción. El historial de señales tiene su propia exportación.

La sincronización opcional de la versión 6.4.4 comparte cuentas/operaciones, notas y watchlist entre dispositivos vinculados. Los respaldos y el historial de señales mantienen su almacenamiento local. Conserva tu clave privada y una exportación adicional antes de borrar datos del navegador.

## Almacenamiento de sincronización

Producción usa el almacén **privado** Vercel Blob `marketintel-sync`, conectado al proyecto. La variable `BLOB_READ_WRITE_TOKEN` es exclusiva del servidor; no debe incluirse en HTML, JavaScript, ZIP ni respuestas. El adaptador también admite `BLOB_STORE_ID` con `VERCEL_OIDC_TOKEN`. Una instalación sin estas credenciales devuelve sincronización no disponible, manteniendo el resto de la app.

Los navegadores guardan una clave privada aleatoria de 256 bits. Derivan por separado la capacidad de autenticación y la clave AES-256-GCM; cada escritura usa un IV nuevo. El servidor recibe solo la capacidad derivada y el sobre cifrado. Las rutas `/sync/data` requieren esa capacidad y usan ETags condicionales para evitar sobrescrituras concurrentes. No hay registro por correo ni recuperación central de la clave. La app local contacta la API de producción mediante CORS limitado a orígenes loopback; las rutas de respaldos locales conservan sus controles originales.

El plan Hobby tiene cuotas limitadas de Blob; si se agotan, la sincronización queda pendiente y el trabajo local continúa. No se activó un plan de pago. El límite por copia es 2 MB de texto antes del cifrado. La protección de ráfagas del servidor es por instancia, no una cuota distribuida.

`scripts/build_local_release.py` crea el ZIP sin credenciales ni datos de usuario en `public/descargas/MarketIntel-6.4.4.zip`. Ejecútalo **antes** del CLI de despliegue, porque Vercel recoge los archivos públicos antes del build. El paquete se descarga desde `/descargas/MarketIntel-6.4.4.zip` y permite actualizar la PC sin depender del visor de archivos del chat.

## Fuentes y MarketBot

Yahoo Finance y las fuentes públicas mantienen sus conexiones originales. FRED usa su descarga CSV oficial cuando no hay clave; si configuras `FRED_API_KEY`, conserva la API como fuente preferida. `FMP_API_KEY` y `SEC_USER_AGENT` permiten habilitar fuentes adicionales. Configura estas variables en el entorno correspondiente de Vercel y vuelve a publicar después de cambiarlas.

MarketBot conserva el campo para introducir tu propia clave del proveedor en la interfaz. Las copias JSON excluyen las claves, por lo que tendrás que introducirla también al usar un dominio nuevo. No se incluye una clave compartida en el despliegue.

El servidor identifica datos ausentes, antiguos o errores de los proveedores. Un despliegue correcto no evita límites de cuota o interrupciones de esos servicios.

En la comprobación del 12 de octubre de 2026 respondieron nueve de diez indicadores macro y las dos series de crédito/curva. El informe PMI de ISM devolvió 404 o acceso restringido; esa tarjeta permanece sin dato, sin sustituirla por una cifra inventada.

## Comprobar un despliegue

`/health` debe devolver JSON con `status: ok`, `service: MarketIntel` y la versión desplegada. Verifica Inicio, todas las secciones, cotizaciones e históricos con un símbolo válido, una compra/venta de prueba en una cuenta separada y guardar/exportar un respaldo. En la web, `/local-state`, `/local-backups` y `/signal-history` deben devolver 403: la interfaz utiliza sus almacenes del navegador.

Las pruebas de servidor están en `MarketIntel-v6.4/tests/test_vercel_runtime.py`; los archivos `tests/run-frontend-browser.py` y `tests/run-frontend-dom.py` verifican la interfaz con datos controlados. Consulta `MarketIntel-v6.4/VALIDACION-v6.md` para distinguir esas pruebas de la disponibilidad real de proveedores.
