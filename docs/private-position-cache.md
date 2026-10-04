# Recuperación de originales privados de posición

La sincronización puede recuperar un original revisado cuando falla la descarga automatizada del origen. La recuperación forma parte de la generación normal: no sustituye la extracción completa, sus recuentos, la comprobación de identificadores ni la activación atómica de la API.

## Orden de comprobación

1. Se intenta descargar cada original requerido desde su URL oficial revisada.
2. Una descarga válida debe conservar exactamente el SHA-256 del manifiesto. Si cambia, la generación queda pendiente de revisión, aunque exista una copia anterior.
3. Ante un fallo de acceso o transporte, se buscan originales en paquetes `.baenc` autenticados mediante la clave independiente `PRIVATE_ARCHIVE_KEY`.
4. La identidad del documento, su hash, clase, URL oficial y fecha documental deben coincidir con el manifiesto actual. También se vuelve a comprobar el hash de los bytes recuperados. Los recibos administrativos deben figurar como `validated` y `reviewed_eligible: true` dentro de los metadatos cifrados.
5. Los originales aceptados pasan por los mismos lectores estrictos y la misma publicación que las descargas nuevas. Un recibo, un PDF suelto o un estado JSON por sí solos no activan ninguna generación.

No se utiliza la copia anterior para ocultar un PDF oficial cuyo hash haya cambiado. Los errores de configuración de origen, las URL no autorizadas y las discrepancias de hash tampoco habilitan la recuperación.

## Fechas y procedencia

Las fechas de publicación, recepción y comprobación oficial representan hechos diferentes:

| Campo | Significado |
| --- | --- |
| `published_at` / `signed_at` | Fecha documental revisada. No acredita cuándo se comprobó el acceso al origen. |
| `received_at` | Recepción de los bytes. Un archivo entregado localmente conserva `received_via: local_file`. |
| `attempted_at` | Intento de descarga de esta ejecución, incluido un intento fallido. |
| `origin_checked_at` | Última comprobación oficial demostrable para ese hash. La recuperación no la renueva. |
| `checked_at` de la generación | Fecha conservadora mínima de las comprobaciones demostrables de todos sus originales; es `null` si falta alguna. |

Se admite una comprobación previa registrada en un manifiesto revisado, en un paquete autenticado o en el estado de una generación activada cuyo documento incorporado coincide en ID y hash. Un recibo local nunca convierte su fecha de recepción en una comprobación oficial. La fecha de publicación tampoco sirve como sustituto.

La generación publicada guarda `source_evidence` con identificadores de documentos, hashes, procedencia y fechas. Este registro no contiene filas nominales. Los datos operativos quedan fuera de la identidad semántica: comprobar de nuevo o recuperar los mismos originales no genera una copia nueva de idénticas filas.

## Estado visible y códigos de salida

| Resultado | Estado | Salida |
| --- | --- | --- |
| Todos los originales se comprueban en origen y la generación queda activa | `verified` | `0` |
| Falla la obtención o validación necesaria, o la API rechaza la publicación | `failed`; se mantiene la generación anterior | `1` |
| Se agota el presupuesto diario de escritura durante la ingesta | `pending_budget`; se conserva la generación anterior y se puede reanudar | `2` |
| La generación queda activa utilizando uno o más originales revisados recuperados | `degraded`, con `origin_unavailable_cached_evidence` | `3` |

El último caso indica que los datos publicados se validaron con evidencia conservada y que la comprobación oficial actual fue incompleta. No se presenta como una actualización completamente comprobada. El resumen contiene `origin_check_complete`, `origin_verified_documents`, `origin_failed_documents`, `cached_documents` y `cache_status`, además del intento actual y la fecha conservadora anterior.

El workflow registra la salida `3` como fase parcial y conserva el fallo final después de publicar los diagnósticos. Una pausa por presupuesto o un rechazo de la API no sobrescribe la referencia activa ni su fecha.

## Conservación cifrada

El workflow pasa `--archive-dir saved-state/private-originals` y proporciona `PRIVATE_ARCHIVE_KEY` como secreto. La clave debe codificar 32 bytes en base64 y es independiente de `POSITION_INGEST_TOKEN`. Sin ella siguen siendo posibles las descargas nuevas, pero no hay recuperación ni copia duradera de originales; `cache_status` queda `unconfigured`.

Los originales recién comprobados se cifran antes de iniciar la publicación. Así se conservan aunque la API rechace la credencial o se alcance una pausa por presupuesto. Si ya hay una copia autenticada con comprobación oficial demostrable del mismo documento, otra comprobación no crea un paquete idéntico con una fecha nueva. Los paquetes son inmutables y su escritura es atómica.

La recuperación permite hasta 100 paquetes y 512 MiB cifrados por ejecución. Cada paquete mantiene, además, los límites de número y tamaño del archivo privado. Los workflows sólo persisten paquetes completos, autenticados y con hashes válidos; sus límites de originales únicos son 100 PDF y 128 MiB. Los PDF en claro permanecen en directorios privados del proceso y no se incluyen en Git, artefactos públicos ni registros. Las salidas de los lectores PDF, incluidas advertencias emitidas antes de rechazar un documento, se descartan en una frontera específica de privacidad.

Una clave incorrecta, un paquete incompleto, una alteración o una discrepancia de metadatos no autoriza un fallback. El resumen marca el problema de caché; si tampoco hay descarga nueva válida, se mantiene la generación previa.

La recepción administrativa usa el mismo archivo cifrado y añade recibos autenticados. Véase [Recepción administrativa](administrative-intake.md). Recibir un documento únicamente lo deja preparado para la próxima sincronización normal.
