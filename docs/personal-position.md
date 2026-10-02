# Consulta de posición publicada

`#position` busca por especialidad y nombre o número oficial de lista. Exige confirmar la ficha y recuerda únicamente su identificador en el navegador. El número destacado es el ordinal de la fila admitida en una publicación concreta, contando sus bloques en el orden del documento. No representa disponibilidad actual ni probabilidad de adjudicación.

## Referencia incorporada

Resolución definitiva CARM de 22 de julio de 2026, curso 2026/2027, con las dos órdenes posteriores revisadas. SHA y URL de cada documento en `data/position-source.json`. La base contiene 728 páginas, 12.895 filas admitidas, 208 especialidades y 557 bloques. La orden complementaria firmada el 28 de julio (208249, dos páginas) añade una persona en Matemáticas y otra en Intervención Sociocomunitaria. La corrección firmada el 4 de agosto (208379, una página) añade una en Trompeta. Resultado: **12.898 filas**, con los identificadores de las 12.895 anteriores intactos. Las fechas de las órdenes son las de firma, no una fecha de publicación inferida.

Los anexos de exclusiones y reclamaciones se excluyen, incluida la segunda página de la orden complementaria. Se conservan los números de siete cifras y se distinguen los números repetidos entre bloques. Cada incorporación conserva su documento y página propios; el enlace de la ficha conduce a esa evidencia. El puesto se recalcula respetando el orden de los bloques y el número dentro del bloque. La corrección de Trompeta exige además los dos números contiguos comprobados en la página 504 de la base.

El manifiesto contiene solo metadatos y cantidades por especialidad. Los nombres se guardan en D1, sin DNI ni puntuaciones. No se añaden datos nominales o PDFs de estas listas al repositorio, a `data-state` ni a Pages. La API devuelve hasta 20 coincidencias por especialidad y exige al menos tres caracteres. Las consultas viajan en POST, no en la URL; respuestas sin caché y con `X-Robots-Tag: noindex`.

## Operación

1. Aplicar `gateway/positions.sql` a la misma D1 del gateway.
2. Desplegar el Worker que importa `gateway/positions.mjs`.
3. Crear un secreto aleatorio de al menos 40 caracteres, específico para ingesta. Guardar `POSITION_INGEST_TOKEN` en Worker y GitHub Actions; nunca en vars, archivos versionados ni frontend. Es independiente de `GITHUB_TOKEN` (permiso de ejecutar comprobaciones).
4. Ejecutar `python -m bolsa_abierta.position_sync` con `PUBLIC_API_BASE` y `POSITION_INGEST_TOKEN`. El workflow existente lo ejecuta también cada media hora. El runner no publica su directorio privado.

Solo la descarga y verificación de **todos** los documentos incorporados actualiza la fecha de comprobación. La identidad de la versión incluye los hashes de la base, las órdenes y la versión del transformador. Un hash distinto requiere revisar publicación, formato y manifiesto: no se asigna automáticamente la fecha antigua a nuevos bytes. Las versiones pasan por staging, totales y rangos completos por especialidad; la activación es atómica. Un fallo mantiene la versión anterior. El workflow marca el fallo sin destruir el resto de las publicaciones. Para desplegar un formato nuevo: primero Worker compatible, después frontend, y por último activación de los datos. La compatibilidad se despliega en una entrega previa al cambio de manifiesto. La sincronización precede al snapshot que anuncia la finalización de una comprobación.

El endpoint `/internal/positions` permite solo begin/rows/activate/checked autenticados con el secreto de ingesta. Cada lote admite 40 filas. Las versiones activadas no permiten cambios en sus filas. La lectura usa la sesión primaria de D1. Pruebas de integración usan SQLite real y el handler de producción.

## Vigilancia de nuevas resoluciones

Los CAPTCHA de CARM y Educarm se completaron en el navegador con autorización del usuario. Se obtuvieron y revisaron ambos originales, incluidos sus sellos de firma. Esta sesión de navegador no elimina la posibilidad de que una descarga automatizada posterior vuelva a recibir un desafío. El colector lo registra como `access_challenge`; conserva la referencia anterior y no adelanta su fecha de comprobación.

`python -m bolsa_abierta.position_updates` descubre los documentos del índice oficial del curso y conserva las descargas por SHA en `.runtime/position-updates`. `data/position-updates.json` exige la presencia de la lista base (208095), la corrección (208379) y la orden complementaria (208249). Sus hashes revisados proceden del manifiesto. Si falta una, el índice falla, cambian sus bytes o aparece otra resolución, la auditoría no se da por completa. Las correcciones provisionales no se aplican a la lista definitiva.

El workflow ejecuta esta auditoría independientemente de la publicación de vacantes y deja su resultado en el resumen de Actions. Los PDFs y el informe completo permanecen en el runner efímero: no se suben a Git, Pages ni artifacts. Solo se imprimen estados y cantidades. Esta etapa **descubre y comprueba documentos; no modifica posiciones**. La consolidación corresponde a `position_amendments` y `position_sync`, con transformaciones explícitas para cada resolución revisada. Su éxito tampoco acredita ceses, disponibilidad o una posición actual. Una incorporación futura deberá añadir la transformación revisada y sus pruebas, no solo un hash.

## Disponibilidad actual: pendiente

La posición entre disponibles requiere además adjudicaciones definitivas, ceses/reactivaciones y cobertura completa a una fecha de corte. No se calcula restando vacantes o adjudicados sin esos datos. El enlace oficial de Educarm sigue disponible en Mi seguimiento.

Piloto del 2 de octubre: Matemáticas (0590006) tiene 762 filas en la base, comprobadas directamente en las páginas PDF 61–84, y 763 tras la orden complementaria. Se consultó el formulario público genérico de Educarm por Secundaria, Matemáticas y bloque 2 de oposición 2025 (69), sin introducir NIF. El resultado muestra número de lista y función, pero no estado de disponibilidad ni fechas de cese. Las doce páginas devolvieron 562 filas frente a las 560 indicadas por el contador, con dos pares número/función repetidos; quedan 560 pares distintos y 425 números de lista. Las variantes bilingües explican parte de la multiplicidad. La incorporación de Matemáticas figura en la consulta.

Ese bloque contiene 427 números en la lista consolidada. Dos no aparecieron en el recorrido de Educarm. Ni esta diferencia ni la anomalía de paginación permiten atribuir bajas, adjudicaciones o disponibilidad: no se modifica la lista por una ausencia en esta consulta. El contraste de adjudicaciones definitivas, ceses y reactivaciones sigue pendiente; no se ha demostrado cobertura completa de movimientos. No se conserva una copia de los NIF o puntuaciones mostrados por Educarm.

Se obtuvo también el [resultado definitivo del acto del 24 de septiembre](https://www.carm.es/web/descarga?ALIAS=ARCH&ARCHIVO=ADJCONPLAZASECUNDARIA-210732.pdf&IDCONTENIDO=209126&RASTRO=c77%24m22725%2C22759%2C4254), enlazado por el Servicio de Personal Docente. Sus 25 páginas y SHA `1b06bc4d1e55b615cfdb64acd12c28392385d0b13f941e83409608081e6aa2c1` se verificaron en privado. Las diez adjudicaciones de Matemáticas de las páginas 9–10 coinciden por especialidad, bloque y número con la lista consolidada. Nueve pertenecen al bloque 69 y sus números siguen apareciendo en la consulta de Educarm. Las observaciones del PDF incluyen fechas de incorporación distintas de la general; no deben ignorarse al construir eventos. Este documento acredita un acto, no la situación posterior de cada persona. No se han aplicado estas adjudicaciones como bajas permanentes ni se han publicado datos de sustituidos.

## Despliegue verificado el 2 de octubre

La compatibilidad se publicó primero en el Worker y Pages (PR 7, ejecución `37058070271`). El manifiesto se activó después (PR 8). La ejecución `37058410313` publicó Pages, pero la ingesta automática encontró `access_challenge` al descargar una orden y conservó la referencia anterior. El índice oficial también quedó sin comprobación completa.

La consolidación se publicó administrativamente en D1 a partir de los originales descargados en el navegador: se volvieron a extraer los tres PDFs, se validaron las filas con el handler de producción, se cargó una versión inactiva y se comprobaron remotamente los 208 totales y rangos antes de activarla. La generación activa es `a573ef5d5e01c1b202b9672320283c45e56fb136100758566d5ea45595f92262`. Su fecha de comprobación conserva la más antigua de las descargas utilizadas (`2026-10-02T17:19:32.306403Z`), sin fingir una consulta nueva al origen.

La API pública confirmó las tres altas, su documento y página, y un identificador anterior cuyo puesto se desplazó. La ficha se comprobó también en la web publicada. Las revisiones automáticas posteriores deben seguir descargando y verificando todos los documentos; si reaparece el desafío, no adelantan la fecha ni desactivan la generación verificada.

Si no está configurado el secreto GITHUB_TOKEN, el control de la ficha dice “Volver a consultar”; vuelve a leer D1 y no afirma consultar las fuentes. Con el permiso configurado, solicita la comprobación mediante el gateway y vuelve a leer la ficha al terminar. La fecha de la publicación permanece siempre visible.
