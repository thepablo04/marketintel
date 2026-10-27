# Frangi · calendario de trades

Abre `frangi.html` en la misma carpeta y navegador que usabas antes. Lee las marcas antiguas `TP`/`SL` como un trade por día; al guardar usa identificadores por trade para conservar cambios independientes de varios dispositivos.

La sincronización es opcional. **Crear clave nueva** genera una clave `FR1-…`. **Iniciar calendario con esta clave** acepta también una clave `MI1-…` de MarketIntel; las claves de cifrado y los espacios remotos de ambas aplicaciones están separados. En otro equipo o en https://marketintel-nu.vercel.app/frangi/index.html, usa **Vincular este dispositivo** con la misma clave. La página local usa un puente de mensajes alojado en el mismo dominio que la API, sin enviar la clave en la URL. El servidor guarda únicamente datos cifrados.

Los trades siguen disponibles sin conexión en el navegador; cuando vuelve la conexión se envían los cambios pendientes. Los trades creados en dispositivos distintos se reúnen por identificador. Si ambos modifican el mismo trade de forma incompatible, el usuario elige qué conservar. El win rate es `TP / (TP + SL)` sobre trades, y “Días operados” cuenta fechas distintas.

Conserva el archivo en la misma ruta si tus registros anteriores estaban en el almacenamiento de un archivo local. El almacenamiento del navegador depende del origen; cambiar de ruta, navegador o borrar los datos del sitio puede ocultar los registros locales. **Descargar copia JSON** guarda una copia adicional. La clave privada es necesaria para vincular nuevos equipos; no existe recuperación de la clave si se pierde en todos los equipos vinculados.
