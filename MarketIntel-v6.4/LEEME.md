# MarketIntel local · versión 6.4

## Sincronización opcional · 6.4.4

En **Portafolio → Sincronizar**, crea una sincronización en el dispositivo que ya tiene tus datos. Guarda la clave privada y pégala en **Vincular dispositivo** en https://marketintel-nu.vercel.app y en los otros equipos. También está disponible en el menú de herramientas. Actualiza primero la instalación local completa y sigue usando `INICIAR.bat`, el mismo navegador y `http://localhost:5050`.

Se sincronizan cuentas y operaciones, notas del análisis y de la ficha, y watchlist. La copia se cifra en tu navegador antes de enviarse a un almacén privado en Vercel. La clave permite acceder a esa copia: compártela solo con tus dispositivos. Si la pierdes y no queda un dispositivo vinculado, no hay recuperación de la clave.

Puedes seguir trabajando en local sin conexión. Los cambios guardados se envían cuando vuelve internet; la app también consulta cambios al volver a la pestaña, cada cinco minutos mientras está visible o al pulsar **Sincronizar ahora**. Si dos dispositivos cambian la misma cuenta o nota, revisa las versiones y elige cuál conservar o conserva ambas. Las cuentas se comparan completas para respetar el orden de las operaciones. Antes de aplicar datos recibidos se guarda un respaldo.

Cierra otras pestañas de MarketIntel del mismo navegador para recibir cambios. Si hay un formulario abierto o estás editando, termina antes de aplicarlos. Desvincular conserva los datos de ese dispositivo. La sincronización necesita un navegador actualizado con Web Crypto y Web Locks, usando HTTPS en web o el servidor local; no funciona abriendo `index.html` directamente.

La copia sincronizada admite hasta 2 MB de datos. Si el servicio no está disponible o agota su cuota, los datos locales permanecen y puedes reintentar. Las claves API, preferencias visuales, selección de cuenta, grupos del heatmap, respaldos e historial de señales siguen en cada dispositivo. Exportar/importar JSON continúa disponible como copia adicional o traslado manual.

## Publicación web · 6.4.3

La aplicación incluye un punto de entrada Flask para Vercel en la raíz del repositorio. Se conservan las mismas secciones, rutas y funciones al iniciar con `INICIAR.bat`.

Los indicadores de FRED también se consultan mediante su descarga CSV pública oficial cuando no hay `FRED_API_KEY`. Si ya configuraste esa clave, se conserva el uso de la API. Las fórmulas, períodos y comprobaciones de antigüedad siguen siendo los mismos.

El seguimiento de señales de la versión web también se conserva en IndexedDB de tu navegador. Registra una lectura por ventana válida, evalúa resultados con cierres anteriores verificados por el servidor y permite **Exportar seguimiento** desde Inicio. En local continúa usando SQLite. Los datos de cada navegador y dominio son independientes; el sitio publicado no lee los datos de tu instalación local automáticamente. Usa **Exportar todo JSON** e **Importar JSON** para trasladar tus cuentas, notas y listas.

## Interfaz renovada · 6.4.2

La actualización conserva el dashboard y sus herramientas, con una navegación más legible, tarjetas y formularios coherentes, mejor contraste y temas oscuro/claro. Incluye Inicio, Pulso macro, Screener, Ficha técnica, Valuación, Portafolio, Watchlist, Heatmap, 7 principios, Fundamental y MarketBot.

En móvil, la navegación inferior y el menú **Más** permiten acceder a todas las secciones. El portafolio mantiene sus columnas y totales en una tabla que puedes deslizar horizontalmente. Se conservan Personalizar, organización y ancho de paneles, escala visual, densidad, comparación, enfoque, presentación y respaldos. Los controles de navegación también funcionan con teclado.

Ejecuta **INICIAR.bat** desde la carpeta completa actualizada; abrir `index.html` directamente no inicia la aplicación completa. Si el navegador conserva estilos anteriores, recarga con **Ctrl + F5**. Los cambios visuales usan los mismos archivos estáticos y rutas tanto en local como en un servidor web; no añaden dependencias para ejecutar la aplicación. Publicar en Vercel sigue requiriendo desplegar Flask y sus rutas, además de los archivos estáticos.

## Datos y cálculos de la versión 6.4

En 6.4, el PIB del segundo trimestre se conserva en la lectura macro mientras siga dentro de su plazo de publicación trimestral: la fecha de la observación en FRED es el primer día del trimestre, por lo que el umbral anterior de 180 días lo excluía antes de publicarse el tercer trimestre. En el NFP, un incremento pequeño se identifica como «Enfriamiento» y se deja en vigilancia: menos contratación puede reducir presión inflacionaria, pero también puede señalar debilidad. No se convierte automáticamente en una señal favorable para la bolsa.

En 6.3, los indicadores macro se consultan automáticamente al abrir la aplicación, cada cinco minutos mientras está abierta y al volver al navegador. Cada tarjeta muestra el período observado, la fuente y cuándo se recuperó; la fecha del período no se presenta como fecha de publicación. Si una fuente responde con un período más antiguo que otro disponible, se conserva el más reciente. Cuando falla o retrocede, la última lectura se muestra como no confirmada y queda fuera del semáforo. No se incluyen cifras precargadas.

El Core PCE se compara entre FRED y BEA: se elige el período más reciente, y para el mismo período se mantiene la mayor precisión de FRED. La encuesta de Michigan se compara con FRED cuando ambos están accesibles y se identifica si su publicación oficial es preliminar o final. El PIB ahora refleja crecimiento **real** interanual (GDPC1) y no el crecimiento nominal que antes podía exagerar la interpretación.

El semáforo muestra señales favorables, desfavorables, en vigilancia y cuántas de las ocho pudieron leerse. Distingue un sesgo leve de uno moderado según el balance relativo entre señales disponibles. La etiqueta puede cambiar al recuperar datos nuevos: nunca se fuerza «alcista». Este semáforo describe el entorno macro, no la dirección de la bolsa durante la sesión. Las lecturas guardadas sin nueva confirmación se muestran, pero no influyen en el semáforo.

En Windows, cierra las ventanas anteriores de MarketIntel, descomprime el ZIP privado en una carpeta nueva y ejecuta INICIAR.bat. Usa el mismo navegador y http://localhost:5050 para conservar tus datos de esa PC. El arranque comprueba que abrió la carpeta correcta y avisa si otra versión ocupa el puerto.

Conserva tu archivo `.env` al actualizar: contiene configuración privada y no debes compartirlo ni publicarlo. El paquete actualizado no incluye credenciales; si ya usabas `.env`, cópialo desde tu carpeta anterior. La aplicación instala las dependencias faltantes la primera vez; necesita Python y conexión. Para iniciar manualmente: python -m pip install -r requirements.txt y después python servidor.py.

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

Los respaldos completos incluyen también las notas del análisis y de la ficha técnica de cada símbolo, y todos los grupos personalizados del heatmap. Editar una nota o un grupo programa una copia, al igual que editar operaciones. En **Portafolio**, usa **Guardar ahora**, **Respaldos**, **Exportar todo JSON** o **Importar JSON**. La exportación completa también sigue disponible desde las herramientas generales; **Copia de cuenta** mantiene su alcance de una sola cuenta.

Antes de importar o restaurar se muestra una vista previa con cuentas, operaciones, posiciones, notas, grupos y watchlist antes y después, y un detalle de las entradas que se añadirán, reemplazarán o eliminarán. **Cancelar** deja los datos intactos. Solo al confirmar se guarda la copia previa y se aplica el cambio. Una importación conserva las claves no incluidas en el archivo; una restauración reemplaza los datos respaldables. En ambos casos se conservan las notas y la configuración del heatmap ausentes en la copia, para que las copias antiguas no borren datos que todavía no respaldaban. Si la copia sí contiene `hm_custom`, sus grupos reemplazan la configuración actual completa.

En Windows las copias y el seguimiento se guardan fuera de la instalación, en la carpeta MarketIntel dentro de LOCALAPPDATA. En Linux/macOS se usa XDG_DATA_HOME/MarketIntel o .local/share/MarketIntel en la carpeta personal. El archivo se llama marketintel.sqlite3. La variable MARKETINTEL_DATA_DIR permite elegir otra ubicación. Respaldos, en el portafolio, muestra la ruta real y permite restaurar o descargar JSON; Ver copias anteriores permite recorrer versiones más antiguas. Se conservan las versiones, sin borrado automático; vigila el espacio si guardas grandes cantidades de datos.

Las copias solo son accesibles desde esta PC y excluyen claves API. Una copia en el mismo disco protege frente a un borrado del navegador, pero no frente a la pérdida del disco: conserva también un JSON en otro lugar. Para cambiar de PC, exporta/importa JSON; el ZIP de instalación no incluye tus operaciones del navegador ni el historial creado después de instalar. Los respaldos antiguos no se eliminan al actualizar el programa.

### Uso web, incluido Vercel

Al abrir MarketIntel mediante `localhost`, `127.0.0.1` o `::1`, los respaldos siguen usando SQLite en la carpeta local indicada arriba. En cualquier otro dominio, los respaldos de usuario se guardan en **IndexedDB del navegador**, separados de los datos activos. El panel indica qué almacenamiento se está usando. La web no envía estos respaldos a las rutas de almacenamiento local del servidor ni depende de un disco persistente de Vercel. Si el navegador impide guardar una copia previa, la acción protegida se cancela y se muestra el error; la exportación JSON sigue disponible.

Los respaldos web pertenecen a ese navegador y dominio; la sincronización opcional comparte los datos activos indicados arriba, no el historial de respaldos. Borrar los datos del sitio puede borrar también sus respaldos y su clave de sincronización. Guarda tu clave y una exportación adicional. El traslado manual mediante **Exportar todo JSON** e **Importar JSON** sigue disponible, con vista previa. Las claves API quedan excluidas y deben configurarse por separado. Las copias JSON anteriores siguen siendo compatibles.

La configuración completa de Flask para Vercel está en la raíz del repositorio, junto con `DEPLOY_VERCEL.md`. En Vercel, el servidor usa disco temporal únicamente para la caché de Yahoo; respaldos e historial de señales se conservan por navegador. El seguimiento mantiene su exportación separada y no forma parte del JSON de portafolios/notas. Las conexiones a proveedores y las fuentes opcionales siguen necesitando sus permisos o claves correspondientes.

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

Las operaciones nuevas registradas con la misma fecha conservan su orden de entrada: una venta posterior ya no puede adelantarse a su compra por el identificador aleatorio. Las copias antiguas siguen siendo compatibles.

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
- En móvil, las tablas de análisis se adaptan al espacio disponible; el portafolio permite desplazar horizontalmente sus columnas y totales.
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
