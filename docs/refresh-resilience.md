# Resistencia a fallos del refresco

La referencia de posiciones sólo avanza después de descargar o recuperar los originales exactos, validar la extracción completa y activar una generación inmutable. `verified` describe los originales de esa generación; la cobertura del inventario se comunica por separado y puede seguir siendo parcial.

## Consultas y presupuesto

Cada bloque privado tiene un índice de trigramas y números de lista, derivado dentro del Worker a partir del bloque almacenado. No se aceptan índices aportados por el cliente. La clave y la relación foránea compuestas vinculan índice y original; el marcador de formato 1 sólo se instala cuando la generación está validada y todos sus bloques están indexados. Un reinicio repara un marcador pendiente. Mientras falte un bloque se conserva la búsqueda anterior.

La selección compara como máximo doce trigramas en una sola consulta y utiliza el más selectivo. Los filtros completos, incluidos apellidos repetidos y fragmentos cortos, y la paginación permanecen activos. El límite de candidatos se aplica después de comprobar los tokens largos.

El presupuesto común sigue siendo 3 millones de lecturas y 2.000 consultas diarias, con liquidación según los contadores reales de D1. La admisión global precede a las escrituras de los contadores por conexión. Cada conexión dispone de hasta 120 consultas diarias; se guarda un HMAC distinto cada día, nunca la IP en claro. El observador elimina contadores con más de siete días en lotes acotados. La ingesta conserva su presupuesto separado de 70.000 escrituras y la fecha UTC de D1; no se reinicia manualmente.

Medición inicial del candidato sobre 22.393 registros (incluye sobrecarga conservadora del presupuesto):

| Caso | Lecturas anteriores aproximadas | Lecturas cobradas con índice |
| --- | ---: | ---: |
| Apellido común | 30.457 | 11.636 |
| Apellido repetido | 27.952 | 9.131 |
| Sin coincidencia | 22.653 | 804 |
| Número sin coincidencia | 22.653 | 804 |
| Fragmento amplio en Maestros | 33.061 | 19.199 |

Son ejemplos medidos, no una garantía para cualquier consulta ni un ensayo de carga sostenida. Los resultados nominales y las consultas no se publican en los informes de diagnóstico.

## Publicación y recuperación

Las operaciones idempotentes reintentan hasta tres veces sólo los fallos de transporte y HTTP 500/502/503/504, con espera creciente y variación aleatoria. Un rechazo de autenticación, conflicto o agotamiento del presupuesto conserva su error. Los bloques existentes se comparan con los datos recién extraídos y no se reescriben; el índice omite los bloques ya derivados. Una activación con respuesta perdida puede repetirse si esa generación sigue activa, sin sustituir otra más nueva.

La fecha de verificación se actualiza después de activar y mediante una condición monotónica en D1. La comprobación final del workflow exige que API y Pages coincidan en generación, recuento y fecha real, permitiendo una espera acotada para la propagación de Pages.

`PRIVATE_ARCHIVE_KEY` es una clave AES independiente de la credencial de ingesta. Cada ejecución restaura los paquetes autenticados en un directorio temporal privado y comprueba los hashes de todos los originales actuales. La restauración nunca registra una comprobación de CARM. La retención sólo retira paquetes después de una restauración correcta: conserva todos los originales activos, al menos 90 días, los dos paquetes fechados más recientes y cualquier paquete de fecha desconocida. El historial cifrado anterior de Git no se reescribe. No se publican PDF nominales en claro.

## Observador independiente

`WATCHDOG_ENABLED=true` activa un cron a los minutos 7 y 37. **La variable de GitHub `WORKER_CRON_ENABLED` debe permanecer ausente o ser distinta de `true`**: el watchdog es un respaldo y el horario nativo de GitHub continúa a los minutos 17 y 47.

El observador lee un estado pequeño de Pages y los metadatos activos de D1. Detecta comprobaciones reales o publicaciones de más de 90 minutos, origen no verificado, errores de colección y discrepancias API/Pages. Tolera veinte minutos para una publicación en curso. Una indisponibilidad aislada necesita otra observación. La cobertura incompleta y la recuperación no preparada se mantienen visibles sin provocar reintentos infinitos de documentos pendientes de revisión.

Antes de solicitar un refresco consulta los estados no terminales del workflow en `main`. Usa la misma compuerta que el botón público, una reserva previa al envío, un intervalo mínimo de una hora y un máximo de cuatro solicitudes diarias. Una respuesta incierta consume el intento. `/api/health` expone únicamente el estado agregado persistente y el resultado del último intento. Una caída de GitHub, Cloudflare o CARM puede impedir la recuperación; los errores no se convierten en verificaciones nuevas.

## Alcance de CARM observado antes del despliegue

Los siete originales de la generación activa estaban comprobados en origen. El inventario del 12 de octubre de 2026 mantenía 29 documentos pendientes: 19 sin clasificar, cuatro provisionales, una corrección, dos avisos de procedimiento cerrado, una observación de participantes y dos aperturas. Otros 17 documentos inaccesibles estaban clasificados como provisionales del bloque de procedimientos urgentes.

Estas etiquetas no acreditan por sí solas una exclusión ni autorizan a incorporar filas. Se conserva el hash, la procedencia, la cola de reintento y el estado parcial hasta revisar el original y su vigencia. Los indicadores `index_complete`, `downloads_complete` y `review_complete` deben ser todos verdaderos para declarar cobertura completa, aunque los contadores de pendientes sean cero. Un PDF alterado, un formato desconocido o una extracción incompleta siguen impidiendo sustituir la referencia validada.

La estabilidad durante varios días requiere observación real posterior al despliegue; no se deduce de una ejecución correcta.
