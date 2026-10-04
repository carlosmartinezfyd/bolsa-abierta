# Recepción administrativa y recuperación de originales

La recepción registra un original aportado por el responsable y comprueba su correspondencia con los manifiestos revisados. **Este procedimiento no activa una generación.** La publicación sigue pasando por las verificaciones y activación atómica de `position_sync`; una recepción, una copia recuperada o un PDF distinto no pueden sustituirlas.

## Formulario del responsable

En Actions, ejecutar **Administrative original intake** sobre `main`. El formulario exige URL oficial HTTPS de `www.carm.es/web/descarga`, IDCONTENIDO, SHA256 esperado, fecha de publicación administrativa y clase de documento. Las clases admitidas son `award`, `optan_observation`, `maestros_roster` y `maestros_correction`. Declarar también los segundos empleados por el responsable. GitHub registra quién solicita la ejecución. Los recibos públicos usan la URL del manifiesto revisado o una URL oficial con solo IDCONTENIDO cuando el original es desconocido; los valores adicionales de la consulta aportada no se publican. Los campos llegan a variables de entorno y argumentos entre comillas; el contenido del formulario no se interpola como instrucciones de shell.

Configurar el entorno `administrative-intake` para que solo responsables autorizados puedan utilizarlo y para restringir despliegues a `main`, según las posibilidades y política del repositorio. El trabajo solo solicita `contents: write`, comparte la exclusión `official-source-publication` con la actualización y conserva los metadatos seguros en `data-state/admin-intake.json`. No necesita `POSITION_INGEST_TOKEN`, permisos Pages ni permiso para activar D1.

La hora real de recepción se calcula después de terminar la descarga. No sustituye `published_at`. Una aportación local conserva `received_via: local_file`, sin afirmar comprobación del origen; una descarga oficial registra por separado `origin_downloaded_at`. Un fallo de acceso no inventa una recepción ni una fecha nueva de comprobación de la generación activa.

## Recepción local de un archivo

Mantener el archivo y los temporales fuera de los directorios versionados. No adjuntar el PDF nominal a incidencias, registros ni artefactos públicos. Ejemplo con un original ya aprobado en el manifiesto:

```bash
python -m bolsa_abierta.admin_documents \
  --file /ruta/privada/original.pdf \
  --url 'https://www.carm.es/web/descarga?IDCONTENIDO=209126' \
  --content-id 209126 \
  --sha256 1b06bc4d1e55b615cfdb64acd12c28392385d0b13f941e83409608081e6aa2c1 \
  --published-at 2026-09-24 --kind award --human-seconds 180 \
  --state .runtime/admin-intake.json \
  --private-dir .runtime/admin-originals
```

El programa usa `data/position-documents.json` y, si existe, `data/position-maestros.json`. Esos manifiestos se revisan junto con el código, antes de admitir nuevos bytes o interpretaciones. Para validar Maestros y su corrección se necesita el original de la lista única y todos sus anexos correctores en el directorio privado con nombres `<sha256>.pdf`; se utiliza el mismo `read_maestros` que la publicación. La lista única no adquiere una especialidad ficticia. Su recibo distingue `row_count` del original base de `collection_row_count` del conjunto consolidado. Un recibo de corrección expone `source_inclusion_count` y `source_operation_count`, junto al recuento consolidado; no atribuye las filas de toda la lista a sus cuatro páginas. La observación «optan» devuelve únicamente recuentos y `semantic_status: unconfirmed`.

## Estados y revisión pendiente

`validated` significa que el original coincide con su hash y fecha revisados y supera su adaptador estricto. La recepción expone `reviewed_eligible: true`, `activated: false` y los recuentos; no devuelve filas nominales. Un original desconocido, bytes diferentes, una fecha distinta, un formato inválido o una corrección incompleta quedan `quarantined`. Los motivos son códigos cerrados. La frontera de análisis descarta stdout y stderr, incluidos sus descriptores nativos, y silencia los manejadores de logging configurados durante la extracción. Restaura después su configuración. Las advertencias y las excepciones del analizador podrían contener texto del PDF y no se imprimen.

La identidad de una recepción es IDCONTENIDO, hash de los bytes recibidos y clase. Repetir un original mantiene una sola entrada y un solo archivo privado, conserva la primera recepción y anota la última y el número de intentos. Los segundos declarados se acumulan por intento; `pending_documents` cuenta las entradas pendientes actuales. Una nueva validación correcta de los mismos bytes retira esa entrada del recuento pendiente. Un documento anterior distinto permanece pendiente hasta una resolución explícita, sin borrado automático.

Una corrección de Maestros recibida antes de la lista base puede almacenarse cifrada, pero permanece pendiente hasta disponer del conjunto completo. Repetir la recepción de la corrección con la base presente permite validarla; no duplica personas ni filas. El historial de recibos no equivale al inventario de fuentes activas.

## Archivo cifrado opcional

Configurar **únicamente** `PRIVATE_ARCHIVE_KEY` como secreto del entorno o del repositorio: base64 canónico de 32 bytes aleatorios, creado y custodiado por el responsable fuera de registros de ejecución. Mantener una copia de recuperación del secreto en la custodia administrativa habitual. La aplicación no genera claves, no las imprime y no reutiliza el token de ingesta. El código utiliza AES-256-GCM de `cryptography` (dependencia instalada por la cadena de `pdfplumber`).

Para activar el archivo local, añadir `--archive-dir /ruta/durable/private-originals` al comando de recepción, con el secreto disponible en el entorno. Actions utiliza `saved-state/private-originals`. Cada paquete `.baenc` contiene originales y manifiesto bajo cifrado autenticado; sus nombres son hashes estrictos. La publicación de un paquete escribe primero un temporal privado, lo sincroniza con `fsync` y lo instala atómicamente sin reemplazar un paquete existente. Una interrupción no deja un `.baenc` parcial y el temporal se elimina ante un error. Una exportación equivalente reutiliza el paquete existente y nunca lo sobrescribe. El nonce es aleatorio y la versión del formato está autenticada. Solo el recibo no nominal y estos paquetes cifrados se añaden a `data-state`; los originales y las filas permanecen en `.runtime` del runner y se eliminan al terminar. No se suben artefactos de originales.

Sin el secreto, `cache_status: unconfigured` indica que los archivos solo permanecen en el runner. Con un secreto inválido o un fallo de archivo se conserva el recibo con `cache_status: archive_failed`; no se persiste un original en claro. La ausencia de archivo no se presenta como respaldo logrado. Un paquete cifrado sigue siendo información confidencial recuperable por quien posee la clave; controlar acceso y custodia del secreto durante toda la retención. El crecimiento del historial cifrado requiere mantenimiento administrativo explícito, sin borrado automático por este trabajo.

## Exportar y recuperar

```bash
python -m bolsa_abierta.private_archive export \
  --private-dir .runtime/admin-originals --archive-dir /ruta/durable/private-originals

python -m bolsa_abierta.private_archive restore \
  --bundle /ruta/durable/private-originals/HASH_DEL_PAQUETE.baenc \
  --private-dir .runtime/recovered-originals
```

Sustituir el nombre ilustrativo por el hash real. La exportación acepta únicamente originales PDF cuyos nombres y bytes concuerdan. La recuperación autentica el paquete y valida todas las entradas antes de escribir: SHA256, tamaño, número de documentos, nombres y límites. Rechaza clave distinta, corrupción, datos incompletos, destinos en conflicto, enlaces simbólicos o rutas arbitrarias. No utiliza tar ni extrae nombres proporcionados por el paquete. Los límites por paquete son 100 documentos, 32 MiB por documento, 128 MiB de originales y 180 MiB cifrados. Actions limita además el número de paquetes recuperados y el conjunto final de originales; alcanzar esos límites exige reorganización administrativa.

Las funciones Python `export_bundle(..., expected_hashes=[...], metadata={...})` y `restore_bundle(..., expected_hashes=[...])` permiten exigir el conjunto exacto de hashes. El manifiesto cifrado conserva los recuentos aportados por la validación y la recuperación devuelve `hashes`, `document_count`, `total_bytes` y `metadata` para comprobarlos. La metadata cifrada de recepción incluye `receipt` y `receipts` con los campos permitidos, la procedencia de cada original y sus fechas separadas, para su posterior validación por el colector. El CLI no imprime la metadata cifrada. Los recuentos de registros se vuelven a comprobar ejecutando los adaptadores, porque la integridad de una copia no sustituye la validación de su interpretación.

Para comprobar la recuperación contra la generación revisada:

```bash
python -m bolsa_abierta.position_sync --validate-only \
  --local-evidence .runtime/recovered-originals \
  --validation-report .runtime/recovery-validation.json
```

Deben recuperarse todos los hashes requeridos por el manifiesto combinado, incluidos la referencia de Secundaria y sus correcciones. Un paquete administrativo que solo contiene algunos originales no equivale a una copia completa de toda la generación. Esta comprobación no publica y debe devolver los mismos recuentos e identidad de generación. `origin_check_performed: false` deja explícito que recuperar y volver a extraer una copia **no es una comprobación reciente del origen oficial**. La activación de una generación mantiene su protocolo independiente; ante un fallo sigue disponible la última generación válida.
