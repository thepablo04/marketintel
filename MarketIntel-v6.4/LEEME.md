# MarketIntel local · versión 6.4

En 6.4, el PIB del segundo trimestre se conserva en la lectura macro mientras siga dentro de su plazo de publicación trimestral: la fecha de la observación en FRED es el primer día del trimestre, por lo que el umbral anterior de 180 días lo excluía antes de publicarse el tercer trimestre. En el NFP, un incremento pequeño se identifica como «Enfriamiento» y se deja en vigilancia: menos contratación puede reducir presión inflacionaria, pero también puede señalar debilidad. No se convierte automáticamente en una señal favorable para la bolsa.

En 6.3, los indicadores macro se consultan automáticamente al abrir la aplicación, cada cinco minutos mientras está abierta y al volver al navegador. Cada tarjeta muestra el período observado, la fuente y cuándo se recuperó; la fecha del período no se presenta como fecha de publicación. Si una fuente responde con un período más antiguo que otro disponible, se conserva el más reciente. Cuando falla o retrocede, la última lectura se muestra como no confirmada y queda fuera del semáforo. No se incluyen cifras precargadas.

El Core PCE se compara entre FRED y BEA: se elige el período más reciente, y para el mismo período se mantiene la mayor precisión de FRED. La encuesta de Michigan se compara con FRED cuando ambos están accesibles y se identifica si su publicación oficial es preliminar o final. El PIB ahora refleja crecimiento **real** interanual (GDPC1) y no el crecimiento nominal que antes podía exagerar la interpretación.

El semáforo muestra señales favorables, desfavorables, en vigilancia y cuántas de las ocho pudieron leerse. Distingue un sesgo leve de uno moderado según el balance relativo entre señales disponibles. La etiqueta puede cambiar al recuperar datos nuevos: nunca se fuerza «alcista». Este semáforo describe el entorno macro, no la dirección de la bolsa durante la sesión. Las lecturas guardadas sin nueva confirmación se muestran, pero no influyen en el semáforo.

En Windows, cierra las ventanas anteriores de MarketIntel, descomprime el ZIP privado en una carpeta nueva y ejecuta INICIAR.bat. Usa el mismo navegador y http://localhost:5050 para conservar tus datos de esa PC. El arranque comprueba que abrió la carpeta correcta y avisa si otra versión ocupa el puerto.

El ZIP privado conserva tu .env. No lo compartas ni lo publiques. La aplicación instala las dependencias faltantes la primera vez; necesita Python y conexión. Para iniciar manualmente: python -m pip install -r requirements.txt y después python servidor.py.

## Sesgo intradía y contexto

La lectura principal describe la sesión actual usando velas de un minuto de Yahoo Finance: SPY, QQQ, IWM, 11 ETFs sectoriales, VIX y HYG. Solo incluye datos de la sesión correcta, con zona horaria y antigüedad máxima de cinco minutos. El indicador es heurístico y experimental; no es una probabilidad ni una recomendación para operar.

Los bloques intradía pesan 45% índices, 25% participación sectorial, 20% VIX y 10% riesgo. Se combinan apertura, cierre anterior, movimiento de 30 minutos y VWAP cuando están disponibles. Los pesos efectivos se reducen al faltar señales. Se requieren SPY y QQQ o IWM, además de cobertura mínima de 45%. Sin suficiente información aparece Sin lectura intradía, sin convertir el vacío en 50/100. Los primeros 15 minutos se identifican como provisionales.

El contexto de varios días aparece aparte. Conserva los bloques 30/20/20/15/15 de tendencia, sectores, volatilidad, riesgo y macro. Corrige el promedio del VIX, el tratamiento de empates en percentiles y las unidades porcentuales de la curva 10Y–2Y. Usa solo cierres completos con fechas válidas. No representa lo que hará el mercado hoy.

Calidad de señales mide cobertura y coincidencia; 80/100 no significa 80% de probabilidad de acertar. La clasificación es bajista hasta 40 inclusive, mixta por encima de 40 y por debajo de 60, y alcista desde 60 inclusive.

El calendario XNYS considera festivos, horario de Nueva York, cambio de hora y cierres anticipados. Si no puede verificarse, se desactiva la lectura intradía. Las interrupciones extraordinarias dependen de la actualización del calendario y de la disponibilidad de precios; no se garantizan datos tick a tick.

## Actualización y fuentes

Mientras Inicio está visible, precios del panel y pulso se consultan cada minuto, al volver a la pestaña y al recuperar internet. El botón Actualizar fuerza una consulta con un mínimo de 15 segundos entre cálculos. Si fallan todos los precios del pulso, espera cinco minutos antes de reintentar para reducir las llamadas repetidas. Las cotizaciones antiguas del navegador nunca reemplazan las entradas descargadas por el servidor. La caché conserva su hora original.

Macro se consulta al abrirse, al volver a la pestaña del navegador y cada cinco minutos con la página abierta. FRED, BEA, ISM y Michigan tienen caché de cinco minutos; BLS conserva una hora por los límites de la API pública. La misma serie CPI NSA de FRED se comprueba por si tiene un período más nuevo. Si se usa ese respaldo, se identifica explícitamente. CPI/PCE/PIB comparan el mismo período entre años, y nóminas el mes anterior exacto. No se introdujeron valores económicos fijos.

Cada tarjeta distingue período, obtención por la fuente y consulta de la aplicación. Cuando la respuesta no suministra fecha de publicación, lo indica; no la inventa. FED y Treasury mantienen observaciones diarias. El PIB compara el valor real del trimestre con el mismo trimestre del año anterior: no es la variación nominal ni la tasa trimestral anualizada.

ISM se lee desde su informe oficial y exige mes y año verificables. Si cambia el formato o no responde, indica Sin dato. Ya no consulta NAPM como si siempre estuviera disponible. Las diez tarjetas permanecen visibles; los últimos valores conservados tras un error se marcan como antiguos y se excluyen del semáforo, igual que los valores vacíos.

Noticias consulta Yahoo Finance cada cinco minutos y conserva el respaldo Google News RSS. FMP y SEC siguen disponibles en la auditoría financiera. La disponibilidad depende de permisos, cuotas y conexiones de cada proveedor. Cerrar la aplicación detiene las consultas; se reanudan al abrirla.

## Seguimiento del indicador

Desde esta versión, el servidor registra como máximo una lectura por ventana de 30 minutos mientras Inicio está abierto, con al menos 45 minutos hasta el cierre y dentro de los primeros 10 minutos de cada ventana. No rellena el pasado con señales inventadas. El precio de referencia es SPY en la hora registrada; la comparación es contra el cierre de esa misma sesión, con zona neutral de ±0.10%.

Los resultados se completan cuando una sesión posterior permite verificar el cierre diario. Las lecturas mixtas no se cuentan como apuestas direccionales; los cierres neutrales no cuentan como acierto de una señal alcista/bajista. Muestra lecturas y días distintos porque varias señales del mismo día están correlacionadas. El porcentaje observado no incluye costos, no es rentabilidad y no garantiza resultados futuros. El historial completo puede exportarse en JSON, también cuando supera 100 lecturas.

## Respaldo automático y traslado

Portafolios, operaciones, watchlists y notas siguen en el navegador. Además, cada cambio de operaciones programa una copia local y se comprueban otros cambios cada 30 segundos mientras la página está visible. Se crea otra versión antes de importar, restaurar o eliminar operaciones/cuentas. Si esa copia previa falla, el cambio se cancela y muestra el motivo.

En Windows las copias y el seguimiento se guardan fuera de la instalación, en la carpeta MarketIntel dentro de LOCALAPPDATA. En Linux/macOS se usa XDG_DATA_HOME/MarketIntel o .local/share/MarketIntel en la carpeta personal. El archivo se llama marketintel.sqlite3. La variable MARKETINTEL_DATA_DIR permite elegir otra ubicación. Respaldos, en el portafolio, muestra la ruta real y permite restaurar o descargar JSON; Ver copias anteriores permite recorrer versiones más antiguas. Se conservan las versiones, sin borrado automático; vigila el espacio si guardas grandes cantidades de datos.

Las copias solo son accesibles desde esta PC y excluyen claves API. Una copia en el mismo disco protege frente a un borrado del navegador, pero no frente a la pérdida del disco: conserva también un JSON en otro lugar. Para cambiar de PC, exporta/importa JSON; el ZIP de instalación no incluye tus operaciones del navegador ni el historial creado después de instalar. Los respaldos antiguos no se eliminan al actualizar el programa.

## Verificación

Consulta VALIDACION-v6.md para las pruebas ejecutadas y sus límites. Pruebas de Python: python -m unittest discover -s tests -v. Pruebas de JavaScript: node tests/portfolio-core.test.js, node tests/valuation-auto.test.js y node tests/macro-auto.test.js. Las pruebas no requieren claves reales; los escenarios de cálculo usan datos sintéticos identificados como tales.

Documentación de las fuentes y dependencias:

- Yahoo Finance: https://help.yahoo.com/kb/SLN2310.html
- yfinance: https://ranaroussi.github.io/yfinance/reference/api/yfinance.download.html
- Calendario: https://github.com/gerrymanoim/exchange_calendars
- Horarios NYSE: https://www.nyse.com/trade/hours-calendars
- BLS: https://www.bls.gov/developers/api_signature_v2.htm
- FRED curva: https://fred.stlouisfed.org/series/T10Y2Y
- BEA Core PCE: https://www.bea.gov/data/personal-consumption-expenditures-price-index-excluding-food-and-energy
- PIB real interanual: https://fred.stlouisfed.org/series/GDPC1
- Encuesta de Michigan: https://www.sca.isr.umich.edu/
- ISM manufacturero: https://www.ismworld.org/supply-management-news-and-reports/reports/ism-pmi-reports/

## Portafolio estilo broker

El portafolio usa las transacciones como libro contable y conserva automáticamente las posiciones creadas con versiones anteriores. Ahora permite registrar:

- Compras, ventas parciales o totales, posiciones cortas y coberturas.
- Depósitos, retiros, dividendos y comisiones.
- Efectivo inicial para cada cuenta.

El resumen separa valor neto liquidativo, efectivo, poder de compra sin margen, P&L diario, P&L realizado y P&L no realizado. El precio promedio incorpora las comisiones de compra; las comisiones de venta se descuentan del resultado realizado.

El gráfico histórico respeta la fecha de cada operación: una posición no aparece antes de su compra. La cuenta también puede compararse con S&P 500 y Nasdaq 100.

Usa **Exportar CSV** para descargar el historial de movimientos. **Copia de cuenta** crea un archivo JSON que puede importarse en otra computadora sin reemplazar las cuentas existentes. Las API keys no forman parte de esa copia.

## Fuentes de datos opcionales

La app funciona sin claves adicionales. Yahoo Finance sigue siendo la fuente base y nunca se elimina. Si la pantalla muestra **“Opcional · sin configurar”**, no es un error: esa fuente adicional todavía no tiene sus datos de acceso.

La forma más sencilla de configurarlas en Windows es:

1. Cierra MarketIntel.
2. Haz doble clic en `CONFIGURAR_APIS.bat`.
3. Pega las claves que tengas y escribe tu correo real para SEC.
4. Abre nuevamente `INICIAR.bat`.

También puedes configurarlas manualmente:

1. Duplica `.env.example` y renómbralo `.env`.
2. Completa solamente las claves que quieras usar.
3. Reinicia `INICIAR.bat`.

- `FMP_API_KEY`: Financial Modeling Prep para ratios, fundamentales y estimaciones normalizadas. Si un dato no existe en Yahoo, puede completar esa métrica avanzada.
- `FRED_API_KEY`: Federal Reserve Economic Data para la tasa FED y otros indicadores macro oficiales.
- `SEC_USER_AGENT`: nombre de la app y tu correo. SEC EDGAR **no necesita API key**, pero exige un User-Agent identificable. El asistente lo crea con el correo que escribas.

Las claves se leen únicamente en `servidor.py`; nunca se envían ni se guardan en el HTML. Si una integración falla, MarketIntel muestra su estado y conserva los datos de Yahoo Finance.

Para proteger las cuotas, FMP y SEC solo se consultan al abrir una **Ficha Técnica** con auditoría. El ticker superior, el dashboard y las listas continúan usando Yahoo Finance y no consumen llamadas complementarias.

Documentación oficial:

- FMP: https://site.financialmodelingprep.com/developer/docs
- FRED: https://fred.stlouisfed.org/docs/api/fred/
- SEC EDGAR: https://www.sec.gov/search-filings/edgar-application-programming-interfaces

## Auditoría financiera

La Ficha Técnica incluye dos paneles desplegables:

- **Métricas financieras avanzadas**: márgenes, ROA, ROE, P/B, PEG, EV/Revenue, EV/EBITDA, P/FCF, ratio corriente, flujo de caja, I+D, acciones, D/E normalizado e historial anual/trimestral.
- **Auditoría y fuentes**: muestra el valor recibido, valor calculado, fórmula, periodo, fuente y actualización de cada métrica. También verifica `Market Cap ≈ precio × acciones`, `P/E ≈ precio ÷ EPS`, `margen neto ≈ ganancia neta ÷ ingresos` y `Revenue TTM = suma de cuatro trimestres`.

Las etiquetas `TTM`, `Forward`, `FY`, `Q`, `Estimado`, `14D` y `200D` aclaran el periodo o tipo de cada dato.

Cada alerta de auditoría significa “revisar”, no necesariamente “dato incorrecto”: dos proveedores pueden usar periodos, acciones diluidas o definiciones de deuda distintas.

## Controles visuales

- Usa el botón de líneas en la barra superior para activar o desactivar el **modo compacto**. Atajo: `Alt + C`.
- Las herramientas secundarias —comparación, presentación, densidad y tema— están agrupadas en el botón de **tres puntos** de la cabecera.
- En **Personalizar → Escala visual** puedes elegir `Pequeña`, `Normal` o `Grande` sin cambiar la cantidad de información mostrada.
- Usa el botón de ampliar de cada gráfico para abrir el **modo enfoque**. Presiona `Esc` para salir.
- El gráfico del screener permite cambiar entre `1M`, `6M`, `1A` y `5A`.
- En móvil, las tablas se convierten automáticamente en tarjetas legibles.
- El botón **Comparar** permite revisar hasta tres acciones lado a lado.
- En **Personalizar → Organizar**, puedes arrastrar paneles y cambiar su ancho. Fuera de ese modo, el dashboard permanece bloqueado.
- En el portafolio puedes elegir las columnas visibles.
- El modo **Presentación** oculta los controles secundarios. Atajo: `Shift + P`.

El runway conserva la fórmula original: **Cash total ÷ (Operating Expenses anuales ÷ 12)**. Los datos de flujo de caja trimestral siguen disponibles en la API y no se eliminó ninguna conexión con Yahoo Finance. Si Yahoo Finance no publica una métrica, la interfaz indica **No disponible**.

El D/E se muestra como ratio (`3.89x`, por ejemplo), el dividend yield se normaliza para evitar mostrar `167%` cuando la fuente significa `1.67%`, y el crecimiento negativo de la fórmula de Graham se limita a `0%`; nunca se convierte en crecimiento positivo.

## Autorrellenado de valuación

Al cargar un ticker, MarketIntel estima el **Market Cap futuro** y lo coloca en las dos calculadoras del Principio 01. Prioriza la fórmula **EPS Forward × P/E objetivo × acciones en circulación**; si esos datos no están disponibles, intenta una proyección por Revenue y P/S o, como último recurso, el consenso de analistas. La interfaz siempre indica qué método utilizó.

La proyección es editable. Al cambiarla, ambas calculadoras se sincronizan y aplican tu fórmula original: **Price Target = Precio actual × (Market Cap futuro ÷ Market Cap presente)**. El upside/downside es la diferencia porcentual real entre ese Price Target y el precio actual.

Variables opcionales: `PORT`, `MARKETINTEL_CACHE_TTL`, `MARKETINTEL_ALLOWED_ORIGINS`, `FMP_API_KEY`, `FRED_API_KEY` y `SEC_USER_AGENT`.
