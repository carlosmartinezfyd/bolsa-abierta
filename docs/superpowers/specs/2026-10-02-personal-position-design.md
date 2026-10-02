# Mi posición

## Resultado
Una persona elige especialidad, busca su nombre o número de lista y confirma la fila. La pantalla muestra su puesto en la publicación, la especialidad y la fecha. La selección se conserva solo en su navegador. Fuentes y método quedan en un desplegable.

El puesto publicado se obtiene contando filas admitidas en el orden del documento, conservando el orden de sus bloques. No equivale al número oficial de lista ni a la posición actual entre disponibles. No se resta ninguna adjudicación ni vacante para inventar esa segunda cifra.

## Evidencia y límites
La resolución definitiva de 22 de julio de 2026 contiene 728 páginas: la relación admitida acaba antes de las exclusiones y reclamaciones. Estas últimas no se indexan. Existen números repetidos entre bloques y números de siete cifras: la identidad de una fila incluye cuerpo, especialidad, bloque y número.

Las correcciones y la disponibilidad actual todavía no tienen cobertura completa verificable. Esta primera consulta se etiqueta siempre como puesto en la lista de una fecha concreta. No se declara una lista consolidada ni una posición actual. La primera entrega comprueba una referencia de hash revisado; la detección e incorporación de publicaciones posteriores queda pendiente de un adaptador de correcciones validado. Nunca se aplican con inferencias libres.

## Arquitectura
- Parser específico y estricto. Valida curso, cabeceras, paginación consecutiva, filas, orden dentro del bloque y duplicados. Cualquier fila desconocida impide publicar toda la versión.
- Versiones inmutables en D1, con fuente, hash, fecha, páginas y totales. Carga por lotes autenticada y activación atómica tras comprobar cantidades y rangos. Un fallo conserva la versión anterior.
- API acotada por especialidad y búsqueda. Sin DNI, puntuaciones ni motivos de exclusión en la base publicada. Sin listado nominal completo en GitHub o Pages.
- Recolector programado de fuentes oficiales. Un hash sin cambios evita reescrituras. Se separa fecha de consulta de fecha del documento. Ingesta mediante secreto específico, distinto del permiso para ejecutar Actions.
- Vista Mi posición independiente de la carga de vacantes. No muestra números de ejemplo ni confirma coincidencias automáticamente. La recarga informa de lo que realmente ha podido comprobar.

## Comprobación
Pruebas de extracción con fixtures sintéticos, auditoría privada de todas las filas del PDF real, integración SQLite/API para activación y consultas, navegación y estados en navegador. Los originales y resultados nominales de auditoría permanecen fuera de Git.
