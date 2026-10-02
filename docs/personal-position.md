# Consulta de posición publicada

`#position` busca por especialidad y nombre o número oficial de lista. Exige confirmar la ficha y recuerda únicamente su identificador en el navegador. El número destacado es el ordinal de la fila admitida en una publicación concreta, contando sus bloques en el orden del documento. No representa disponibilidad actual ni probabilidad de adjudicación.

## Referencia incorporada

Resolución definitiva CARM de 22 de julio de 2026, curso 2026/2027. SHA y URL en `data/position-source.json`. Auditoría: 728 páginas en el PDF; 12.895 filas admitidas, 208 especialidades, 557 bloques. Los anexos de exclusiones y reclamaciones se excluyen. Se conservan los números de siete cifras y se distinguen los números repetidos entre bloques.

El manifiesto contiene solo metadatos y cantidades por especialidad. Los nombres se guardan en D1, sin DNI ni puntuaciones. No se añaden datos nominales o PDFs de estas listas al repositorio, a `data-state` ni a Pages. La API devuelve hasta 20 coincidencias por especialidad y exige al menos tres caracteres. Las consultas viajan en POST, no en la URL; respuestas sin caché y con `X-Robots-Tag: noindex`.

## Operación

1. Aplicar `gateway/positions.sql` a la misma D1 del gateway.
2. Desplegar el Worker que importa `gateway/positions.mjs`.
3. Crear un secreto aleatorio de al menos 40 caracteres, específico para ingesta. Guardar `POSITION_INGEST_TOKEN` en Worker y GitHub Actions; nunca en vars, archivos versionados ni frontend. Es independiente de `GITHUB_TOKEN` (permiso de ejecutar comprobaciones).
4. Ejecutar `python -m bolsa_abierta.position_sync` con `PUBLIC_API_BASE` y `POSITION_INGEST_TOKEN`. El workflow existente lo ejecuta también cada media hora. El runner no publica su directorio privado.

Una descarga con el mismo hash actualiza la fecha de comprobación sin reinsertar filas. Un hash distinto requiere revisar publicación, formato y manifiesto: no se asigna automáticamente la fecha antigua a nuevos bytes. Las versiones pasan por staging, totales y rangos completos por especialidad; la activación es atómica. Un fallo mantiene la versión anterior. El workflow marca el fallo sin destruir el resto de las publicaciones.

El endpoint `/internal/positions` permite solo begin/rows/activate/checked autenticados con el secreto de ingesta. Cada lote admite 40 filas. Las versiones activadas no permiten cambios en sus filas. La lectura usa la sesión primaria de D1. Pruebas de integración usan SQLite real y el handler de producción.

## Cobertura pendiente

La referencia no consolida aún la corrección y orden complementaria posteriores de la CARM. Sus descargas han devuelto una verificación de seguridad y no se ha sorteado. El colector de posición comprueba el PDF fijado por su hash; **no descubre automáticamente nuevas listas ni incorpora modificaciones**. La vista lo identifica como una publicación fechada y detalla esta cobertura. Antes de sustituirla por una lista consolidada hace falta obtener los documentos, validar su semántica y conservar evidencia de cada modificación.

La posición entre disponibles requiere además adjudicaciones definitivas, ceses/reactivaciones y cobertura completa a una fecha de corte. No se calcula restando vacantes o adjudicados sin esos datos. El enlace oficial de Educarm sigue disponible en Mi seguimiento.

Si no está configurado el secreto GITHUB_TOKEN, el control de la ficha dice “Volver a consultar”; vuelve a leer D1 y no afirma consultar las fuentes. Con el permiso configurado, solicita la comprobación mediante el gateway y vuelve a leer la ficha al terminar. La fecha de la publicación permanece siempre visible.
