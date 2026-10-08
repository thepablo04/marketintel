# Validación de MarketIntel 6.4

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

- Chromium no pudo iniciarse en el entorno de prueba. No se certificó el diseño visual final, la disposición móvil ni el dibujo real de gráficos. jsdom ejecuta la lógica y los controles, pero no sustituye un navegador gráfico.
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
npm install --no-save jsdom
python tests/run-frontend-dom.py
```

El ejecutor de integración inicia y cierra su propio servidor en un puerto libre, usa cotizaciones de prueba y elimina su base temporal. No modifica el portafolio del usuario. Node y jsdom no son necesarios para usar MarketIntel normalmente.
