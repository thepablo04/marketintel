# Validación de MarketIntel 6.4

## Sincronización · 6.4.4 · 26 de octubre de 2026

Pasaron 84 pruebas Python, incluidas 20 de autenticación, aislamiento, CORS, límites y escrituras condicionales de sincronización. La fixture macro que dependía de un mes fijo se actualizó para conservar su intención al avanzar el calendario, sin modificar el comportamiento de producción.

Pasaron las suites JavaScript existentes y 28 pruebas nuevas del núcleo, motor e interfaz de sincronización. Cubren cuentas atómicas, orden de operaciones, borrado frente a edición, conservación de ambas versiones, datos malformados, exclusión de secretos, cifrado autenticado, subida automática de cambios, cambios durante una subida, conflicto de ETags, revisión de decisiones obsoletas, fallos de respaldo/almacenamiento y recuperación de una aplicación interrumpida.

Chromium comprobó dos contextos independientes (local y web) con criptografía y Web Locks reales y un transporte remoto controlado: vinculación, cuentas/operaciones, watchlist, notas, cambios sin conexión que sobreviven a una recarga, revisión de conflictos y desvinculación sin borrado. Se verificaron el bloqueo de recepción con otra pestaña abierta, la conservación de un formulario de operación sin terminar, secretos ausentes de las exportaciones y el diálogo a 320 px en ambos temas. Sin excepciones JavaScript ni alertas inesperadas.

La regresión completa aprobó nuevamente las once secciones, ambos temas, escritorio de 1440 px y móvil de 390 px, en local y web. Se conservaron gráficos, compra/venta del mismo día, notas, cálculos, respaldos, heatmap, navegación y preferencias. La integración jsdom local/web también pasó.

El adaptador se comprobó contra el almacén privado real de Vercel con datos de prueba: creación y lectura, rechazo de creación duplicada, nueva revisión al cambiar contenido, rechazo 409 de una escritura con ETag antiguo y lectura consistente tras guardar. Las cuotas y disponibilidad del proveedor siguen siendo límites externos; una interrupción mantiene pendientes los cambios locales.

La comprobación inicial de producción detectó que el intermediario de Vercel transformaba una creación con `If-None-Match: *` en una respuesta 304 vacía. El navegador ahora usa `X-Sync-If-None-Match` y `X-Sync-If-Match`; el servidor valida esas condiciones y mantiene las escrituras atómicas del proveedor. Los encabezados estándar siguen admitidos para clientes directos, y se rechazan condiciones ambiguas.

Las lecturas de Blob solicitan `Accept-Encoding: identity` para obtener el ETag fuerte de la copia original. Las respuestas comprimidas del proveedor entregaban un ETag débil que impedía actualizar copias de mayor tamaño; se comprobó el caso con una copia cifrada real y se añadió cobertura para rechazar revisiones débiles.

Las pruebas automatizadas no ejecutan `INICIAR.bat` en Windows ni certifican la disponibilidad permanente de fuentes financieras. El paquete local contiene los mismos archivos de aplicación probados, sin claves ni datos de usuario.

La revisión del 5 de octubre de 2026 corrigió el plazo de vigencia del PIB trimestral. Se añadió una prueba que comprueba que el segundo trimestre se admite el 5 de octubre y que la misma observación queda fuera de plazo en diciembre si no aparece un trimestre nuevo. El NFP de +29.000 se muestra como «Enfriamiento» en vigilancia; los otros indicadores determinan el balance final. Pasaron 25 pruebas de calidad de datos y la suite de actualización macro en JavaScript. No se repitió una ejecución integral con fuentes reales en este entorno.

Fecha: 25 de septiembre de 2026. La primera revisión fue el 24 de septiembre. Esta actualización parte del ZIP privado v5 y conserva la configuración de acceso a las fuentes; no se incluyen operaciones ni bases de datos de prueba en el instalador.

La versión 6.2 repara un fallo observado en la captura del usuario: las observaciones de julio de Core PCE y UMCSENT podían excluirse por superar 75 días desde el **primer día del mes observado**, aunque aún fueran las últimas disponibles. El plazo de ambos indicadores es ahora 105 días y, si un dato supera ese plazo, se muestra con su fecha pero queda fuera del semáforo. El lector de ISM admite la marca ® en su título y valida mes, año y número del encabezado. Se añadieron alternativas oficiales de BEA y de la Universidad de Michigan; los datos preliminares se identifican y los fallos conservan su causa visible.

En 6.3, el semáforo usa PIB **real interanual** (GDPC1) y consulta cada cinco minutos. La encuesta de Michigan y el Core PCE comparan la fecha del período entre su fuente oficial y FRED. Si una fuente devuelve un período anterior a la última lectura verificada, o una lectura preliminar tras una final del mismo mes, el semáforo no la cuenta como actualización reciente. Las respuestas macro del servidor se envían sin caché HTTP. La API pública de BLS puede demorar hasta una hora en reflejar una publicación nueva; FRED se comprueba en paralelo para CPI.

## Resultado de las pruebas

En la revisión 6.3 se aprobaron 24 pruebas de calidad de datos, las tres suites de JavaScript y la validación sintáctica del Python y del JavaScript interno. Incluyen PIB real interanual, revisión final de Michigan, preferencia por el período más reciente de BEA/FRED y protección contra regresiones cuando una fuente responde con datos antiguos. La integración completa con Flask y jsdom no pudo repetirse en ese entorno porque no estaba instalado Flask; los resultados de esa integración en la tabla corresponden a la validación anterior de 6.2.

| Comprobación | Resultado | Alcance |
| --- | --- | --- |
| Python 6.4 | 25 pruebas aprobadas | Calidad de datos macro, fechas, revisiones, plazos del PIB y selección de fuentes. |
| JavaScript 6.3 | 3 suites aprobadas | Contabilidad del portafolio, autorrellenado de valuación y conexiones de actualización macro/pulso. |
| Integración de interfaz 6.2 | Aprobada con jsdom | Verificación anterior: ocho señales macro, diez tarjetas macro y respaldo. No repetida para 6.3. |
| Arranque local 6.2 | Aprobado en Linux | Verificación anterior del servidor Flask. No repetida para 6.3. |

Los escenarios de mercado de las pruebas automatizadas usan datos sintéticos. Sirven para verificar el comportamiento del código y no demuestran precisión predictiva ni acceso continuo a un proveedor.

Las pruebas cubren mercados alcistas y bajistas, cotizaciones antiguas o de otra sesión, zonas horarias ausentes, barras futuras, datos parciales, falta de SPY, reducción de cobertura y exclusión del cierre diario incompleto. Verifican festivos, horario de verano y cierres anticipados, además del bloqueo de cálculos cuando no se puede confirmar el calendario. También comprueban que una cotización enviada por el navegador no sustituye los datos del servidor y que un fallo total de precios limita los reintentos durante cinco minutos.

Las pruebas de respaldo comprueban persistencia, recuperación exacta de cadenas, versiones inmutables, deduplicación automática, rechazo de claves privadas y bloqueo de solicitudes externas. Se verificó acceso a copias anteriores a las primeras 100 y exportación del seguimiento completo. La integración usa una base temporal separada de la del usuario.

## Consulta real de las fuentes

El 25 de septiembre de 2026, la consulta directa al servicio desde este entorno agotó el tiempo de espera para FRED e ISM; BEA respondió en un intento y expiró en otro. Las páginas oficiales publicaban la observación de julio de Core PCE y el informe de agosto de ISM; la Universidad de Michigan mostraba una encuesta preliminar de septiembre antes de la hora de su publicación final. La integración con esos sitios se comprobó mediante pruebas de sus formatos de respuesta, pero esta ejecución no garantiza que respondan en la PC del usuario. No se empaquetan valores fijos de esas páginas.

Las siguientes respuestas son de la comprobación anterior, el 24 de septiembre de 2026:

| Fuente | Resultado observado |
| --- | --- |
| BLS | Respondió; se obtuvo CPI con período de agosto de 2026. |
| FRED | Respondió para las series macro configuradas. |
| Yahoo Finance noticias | Respondió con 12 artículos. |
| Yahoo Finance precios | Devolvió HTTP 429 al consultar históricos/cotizaciones. La lectura intradía con precios reales no quedó validada de extremo a extremo. |
| ISM | La conexión agotó el tiempo de espera. El analizador se verificó con documentos de prueba, incluida la protección frente a informes de otro año. |
| FMP y SEC | Integraciones y configuración conservadas; su funcionamiento en vivo no se certificó en esta revisión. |

Estas respuestas describen esa consulta puntual. Las cuotas, los permisos y la disponibilidad pueden cambiar. La aplicación identifica fuentes ausentes o antiguas; no rellena datos económicos ni asigna una lectura neutral ficticia cuando faltan precios.

## Límites de esta verificación

- En la verificación anterior de 6.4, Chromium no pudo iniciarse; se utilizó jsdom. La revisión de interfaz 6.4.2 descrita más abajo añade la comprobación con un navegador gráfico.
- El archivo INICIAR.bat se revisó, pero no se ejecutó en Windows. El servidor y la prueba de integración se ejecutaron en Linux.
- El indicador intradía es una regla heurística experimental. No se realizó un estudio estadístico fuera de muestra ni se promete una tasa de acierto. El seguimiento empieza con lecturas nuevas de la instalación.
- Las copias se guardan en la misma PC. Para trasladar portafolios o protegerse frente a la pérdida del disco, exporta JSON y conserva otra copia fuera de esa PC.

## Repetir las pruebas

Desde la carpeta de MarketIntel, con las dependencias instaladas:

```text
python -m unittest discover -s tests -v
node tests/portfolio-core.test.js
node tests/valuation-auto.test.js
node tests/macro-auto.test.js
```

La prueba de integración es opcional y requiere Node con jsdom, solo para desarrollo:

```text
npm install --no-save --package-lock=false jsdom@29.0.0 fake-indexeddb@6.2.5
node tests/browser-backup-store.test.cjs
node tests/backup-ui.test.cjs
node tests/heatmap-import.test.cjs
python tests/run-frontend-dom.py
```

El ejecutor de integración inicia y cierra su propio servidor en un puerto libre, usa cotizaciones de prueba y elimina su base temporal. Ejecuta la interfaz en modo local y en un origen web simulado con IndexedDB. No modifica el portafolio del usuario. Node, jsdom y fake-indexeddb solo son herramientas de desarrollo y no se necesitan para usar MarketIntel normalmente.

## Ampliación de respaldos: local y web

La cobertura añade notas de análisis, notas de ficha técnica y grupos personalizados del heatmap, manteniendo el formato de copia v2. Se comprueban la vista previa y cancelación, la copia previa a restaurar, la conservación de notas ausentes en copias antiguas, la exclusión de claves privadas y la recuperación frente a fallos de almacenamiento. Los nombres y símbolos del heatmap importado se representan como texto y conservan sus controles.

Las pruebas de IndexedDB comprueban persistencia entre conexiones, deduplicación por perfil, paginación, concurrencia y errores de cuota/abort. La integración web impide que los respaldos usen las rutas del servidor local. Estas pruebas simulan un dominio publicado; no constituyen una publicación ni validación real en Vercel, ni una revisión visual en un navegador gráfico.

## Interfaz 6.4.2 · 10 de octubre de 2026

La revisión incorpora estilos compartidos para las once secciones, tema claro/oscuro, adaptación móvil y mejoras de teclado. Las capas visuales se aplican a pantalla y conservan los estilos de impresión existentes. No añaden dependencias para ejecutar la aplicación.

Se repitieron las 51 pruebas Python, las suites de portafolio, valuación y macro, 8 grupos de almacenamiento IndexedDB, 12 pruebas de la interfaz de respaldos, 6 de accesibilidad, heatmap local/web e integración jsdom local/web: todas aprobadas. Los tres archivos CSS nuevos se analizaron sin errores de sintaxis.

La prueba completa de Chromium aprobó las once secciones en temas claro/oscuro, en escritorio de 1440 px y móvil de 390 px, tanto con servidor local como con dominio web simulado. También se comprobó la disposición a 1024 y 320 px. Se revisaron capturas del dashboard, macro, portafolio, valuación, watchlist, heatmap y vistas cargadas de screener/ficha.

El navegador verificó gráficos reales, altas/bajas de watchlist, cálculo Graham, guardado de notas, compra y venta del mismo día, persistencia de operaciones, vista previa/cancelación de respaldos, grupos de heatmap, navegación por teclado, búsqueda, presentación, densidad, escala y visibilidad de paneles. Las cifras del portafolio de prueba caben en una línea a esos anchos. No hubo excepciones JavaScript sin capturar ni diálogos inesperados.

Durante la prueba real de compra y venta se detectó que dos operaciones con la misma fecha podían ordenarse por su UUID, colocando una venta antes de su compra. Las operaciones nuevas ahora conservan una secuencia de registro. El núcleo verifica posiciones largas y cortas, persistencia JSON, orden de exportación CSV, prioridad de la fecha y compatibilidad con copias antiguas. Las operaciones antiguas sin secuencia conservan su desempate anterior; no se inventa su orden de registro.

### Repetir la prueba visual y funcional

Requiere herramientas de desarrollo adicionales; no se instalan para usar la app:

```text
npm install --no-save --package-lock=false playwright chart.js@4.4.0 @fontsource/inter@5.2.8 @fontsource/syne@5.2.7 @fontsource/ibm-plex-mono@5.2.7
python tests/run-frontend-browser.py
```

El ejecutor usa Chromium en `/usr/bin/chromium`; `MARKETINTEL_CHROMIUM` permite indicar otro ejecutable, incluido Chrome instalado en Windows. `MARKETINTEL_SCREENSHOT_DIR` permite guardar capturas. Inicia su propio servidor Flask con base temporal, usa perfiles de navegador nuevos y elimina esos datos al terminar. Cotizaciones, fundamentales y respuestas macro son sintéticos; Chart.js, archivos de la app y respaldos se ejecutan realmente.

Esta verificación no implica haber publicado en Vercel, ejecutado INICIAR.bat en Windows ni comprobado la disponibilidad actual de los proveedores externos. El modo web comprueba el comportamiento del navegador ante un dominio alojado y bloquea el uso de rutas de respaldo local.

## Publicación Vercel · 12 de octubre de 2026

Se compiló y publicó Flask con Python 3.12 y 13 archivos estáticos en la CDN, conservando el arranque local. Las 64 pruebas Python pasaron: incluyen aislamiento de Vercel, caché temporal de Yahoo, bloqueo de rutas locales, cierres verificados para el historial del navegador y descarga CSV pública de FRED. Las nueve suites JavaScript y la integración jsdom local/web también pasaron.

Chromium verificó nuevamente las once secciones y ambos temas en local/web, escritorio/móvil, compras y ventas, notas, cálculos, respaldos y preferencias. El historial web se comprobó con IndexedDB real: registro sin duplicados, evaluación con cierres posteriores, recarga y exportación JSON. Un bloqueo del modal observado en una ejecución anterior no se reprodujo en la ejecución completa final; se conservó el diagnóstico de error en la prueba.

En el dominio publicado respondieron `/health`, la página principal y sus recursos estáticos. Los 14 archivos de página/recursos coincidieron byte a byte con los archivos probados. Las consultas reales devolvieron cotizaciones de AAPL, SPY, QQQ y MSFT, 251 puntos de histórico de AAPL, fundamentales, noticias y las 16 cotizaciones del pulso. MarketBot devuelve el error esperado cuando no se proporciona clave; no se verificó una conversación con una clave de pago o privada.

La consulta pública de FRED recuperó nueve de diez indicadores macro y dos series de crédito/curva. ISM sigue sin proporcionar un informe PMI verificable a estas consultas. Las claves opcionales de FMP/SEC no están configuradas y no se certificó su acceso en vivo. Los datos locales de un navegador no se trasladan automáticamente al dominio web.

Producción: https://marketintel-nu.vercel.app. La comprobación final sobre ese dominio confirmó nueve indicadores macro, 16 cotizaciones del pulso y 251 cierres verificados para el diario. También se recorrieron las once secciones con respuestas reales del despliegue, usando HTTPS verificado mediante el proxy del entorno; el gráfico de AAPL recibió 251 puntos y la ficha mostró su precio. El iframe externo de TradingView produjo dos rechazos de acceso en el navegador de prueba: su funcionamiento completo no quedó certificado por esa ejecución. Los gráficos propios de Chart.js sí se comprobaron con datos reales.
