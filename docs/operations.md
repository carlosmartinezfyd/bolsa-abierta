# Operación, evidencia y despliegue

## Qué se registra y qué queda pendiente

`data-state/operations.json` conserva exclusivamente metadatos de ejecución: identificador del run/intento, SHA, disparador, correlación de solicitud, inicio, fin, duración y estado, más las mismas medidas por fase `inventory`, `positions`, `vacancies` y `build`. No guarda comandos, variables de entorno, salida de procesos, excepciones, URLs nominales ni filas de personas. El envoltorio descarta stdout y stderr del proceso hijo; sus errores se expresan mediante códigos y resúmenes permitidos. Un proceso interrumpido conserva `running`, sin inventar un cierre satisfactorio.

La retención es de **30 días y como máximo 1.024 runs**. Los recuentos públicos corresponden a esa ventana retenida; `discarded_runs` deja visible lo retirado. La rama `data-state` mantiene el estado fuera de la retención de logs de Actions. Su historial Git conserva las versiones anteriores de estos metadatos; el límite se aplica al fichero vigente, no promete borrar el historial de Git.

El exportador publica `operations.public_summary`: recuentos por estado/fase, último run limitado, intervalos observados, duración de seguimiento y campos de evidencia aún pendiente. No publica el historial de runs completo. La lista de campos se reconstruye, por lo que añadir campos privados al fichero no los publica.

El resultado de ejecutar la automatización y la completitud de las fuentes son distintos. `inventory` sale con código **3** cuando ha guardado un inventario parcial por límites de recorrido, revisión pendiente o indisponibilidad externa reconocida. Los errores de formato, integridad y seguridad conservan el código **1**. `position_sync` usa **2** para `pending_budget` y **3** para caché verificada o para una fuente temporalmente inaccesible cuando una consulta autenticada confirma que la generación anterior sigue activa y lista. Un puntero local antiguo no basta. Si algún original presenta un error de integridad, este prevalece sobre los bloqueos de otros originales.

El envoltorio conserva siempre el código real del proceso y su estado en `operations.json`. Solo las fases de captación del workflow usan `--allow-partial`: una pausa o resultado parcial documentado permite continuar con la publicación de diagnósticos. El agregado sigue siendo `partial`, y la web y `gateway-status.json` no lo convierten en una comprobación oficial completada. Los errores de programa, configuración, extracción, archivo, persistencia o despliegue siguen haciendo fallar Actions. En vacantes, `freshness.operational_status=failed` diferencia errores de procesamiento de una indisponibilidad temporal, aunque `freshness.status` siga siendo `partial` para conservar los datos válidos.

`SOURCE_RETRY_STATE` activa una espera persistente por recurso, compartida entre las tres fases y guardada en `data-state/source-retries.json`. Tras fallos temporales se reintenta a 1, 2, 4 y como máximo 6 horas; un `Retry-After` mayor se respeta. Cada URL se trata por separado: un bloqueo no desactiva el dominio. Las consultas aplazadas no consumen el presupuesto HTTP del inventario, y una respuesta válida elimina la espera. Solo se guardan hashes de identidad, códigos fijos, contador y plazo, sin URLs ni contenido. La espera no renueva la fecha de comprobación oficial. Los tests no utilizan ese estado de producción.
 Solo el SQLite de estado y `runtime/artifacts` de vacantes validadas entran en Git; `runtime/private-artifacts` y los originales de posiciones/inventario en claro permanecen excluidos. Con `PRIVATE_ARCHIVE_KEY`, `position_sync --archive-dir saved-state/private-originals` restaura o guarda exclusivamente bundles AESGCM autenticados. La persistencia valida integridad, hashes y manifiesto completos antes de añadir ficheros `.baenc`; ignora PDFs/JSON en claro. Los límites son 100 bundles, 512 MiB cifrados y 100 PDF únicos/128 MiB en claro. Los recibos que autorizan la recuperación están autenticados dentro del bundle, no en un JSON público. Un fallo de validación de caché conserva los diagnósticos y deja explícitamente pendiente su persistencia. El borrado de artefactos antes públicos se incluye con `git add -u runtime/artifacts`, sin reescribir el historial.

Ejemplo local, sin datos personales:

```bash
export GITHUB_RUN_ID=123 GITHUB_RUN_ATTEMPT=1
python -m bolsa_abierta.operations --state .runtime/operations.json start
python -m bolsa_abierta.operations --state .runtime/operations.json run --phase build -- python -c 'print("diagnostic output suppressed")'
python -m bolsa_abierta.operations --state .runtime/operations.json finish --status success
python -m bolsa_abierta.operations --state .runtime/operations.json summary
```

## Seguimiento de 14 días: 672 ventanas nominales

El primer run inicia la recogida de metadatos. **No equivale a haber completado el ensayo de acceso, CPU o cadencia de Cloudflare.** `elapsed_nominal_windows` cuenta tiempo transcurrido desde ese comienzo; no cuenta intentos exitosos ni demuestra observaciones por fuente. Después de 14 días el estado pasa a `evaluation_pending`, nunca a una aceptación automática.

Los dispatch del Worker conservan `scheduled_time`, `clock_received_at`, `dispatch_at`, `trigger=worker_cron` y `request_id`. `scheduled_time` es el `scheduledTime` real del controlador, en ISO UTC. Para Actions nativo se deja nulo: una ejecución `schedule` no acredita el instante cron causal. Se muestran intervalos entre runs; la mediana de retraso programado se calcula únicamente para runs Worker con un tiempo real válido. No se reconstruyen supuestos disparos omitidos. La correlación de la solicitud pública mantiene el identificador exacto y la confirmación de la instantánea correspondiente.

Antes de evaluar el ensayo debe fijarse el conjunto de fuentes que superan el acceso inicial y conservarlo durante las 672 ventanas, sin excluir después las que fallen. La aceptación propuesta exige antigüedad del último éxito validado ≤60 minutos en al menos 95 % de los cortes de cada fuente de ese conjunto, CPU P95 del comprobador <8 ms y margen de presupuesto ≥30 %. Debe publicarse también cobertura total, incluidas las fuentes bloqueadas al inicio. Estos son objetivos; los campos de antigüedad, CPU y margen permanecen **nulos/pending** hasta tener observaciones y métricas de la cuenta. Los metadatos de fase no bastan para rellenarlos. Referencia: informe aprobado, sección 7.5.

El Cron Worker sigue desactivado por defecto (`CRON_ENABLED=false`). Su configuración opcional usa `17,47 * * * *` y un sondeo HEAD acotado, sin descargar originales. Solo un cambio comprobado solicita procesamiento. Al habilitarlo, configurar también la variable GitHub `WORKER_CRON_ENABLED=true` para desactivar el reloj nativo y evitar dos procesamientos programados. Hacer un dispatch manual de prueba y comprobar correlación y cuotas antes de esa conmutación. Para volver al reloj nativo, desactivar Cron Worker y cambiar `WORKER_CRON_ENABLED=false`; verificar el siguiente run. Las solicitudes públicas y el Cron comparten los límites de la pasarela. Los límites y retrasos de `schedule` están documentados por [GitHub](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).

## GitHub Pages y publicación de código

La pasarela anterior al soporte de `metadata` responde 409 «La versión publicada es inmutable» tras autenticar esa consulta. Solo en ese caso, el captador confirma la misma generación en `GET /api/positions`, que selecciona exclusivamente la generación activa y lista. Esta compatibilidad no se aplica a escrituras, errores de autorización ni otras respuestas 409, y no modifica la fecha de comprobación oficial.

`refresh.yml` se ejecuta por schedule, dispatch y cambios de código/interfaz en `main`. Ese push reconstruye y despliega Pages desde el nuevo SHA. La concurrencia `official-source-publication` serializa las publicaciones. Los cuatro procesos quedan envueltos por el registro de fase, y se vuelve a exportar el resumen después de cerrar el run para que la instantánea contenga el estado final. Un fallo de captura no borra la generación validada ni cambia su fecha de éxito.

Se publica además `data/gateway-status.json`, con solo `freshness.request_id`, `status` y `last_attempt_at`. `completed` exige éxito de inventario, posiciones, vacantes y construcción; cualquier fase parcial, fallida, ausente o pendiente impide confirmar el cambio observado por el Cron. Esto permite confirmar la publicación sin cargar el snapshot grande ni depender de que un visitante consulte el progreso.

La medida del run termina tras construir la instantánea; no representa confirmación de despliegue de Pages ni latencia de caché. El resultado real de `deploy-pages` permanece en el job. Los tests de Python/Node se ejecutan antes de obtener fuentes; CI valida además los workflows con actionlint.

## Despliegue y actualización con las credenciales existentes

La operación utiliza el Worker y la D1 `bolsa-abierta-gateway` existentes. No crea cuentas, bases ni recursos de pago. La publicación periódica de datos requiere únicamente `PUBLIC_API_BASE` y el secreto `POSITION_INGEST_TOKEN`, ya compartido entre Actions y el Worker. El token de despliegue de Cloudflare solo es necesario para modificar código desde CI; su ausencia no impide refrescar datos.

Para desplegar código con la sesión local de Wrangler:

1. Crear `gateway/wrangler.toml` desde el ejemplo con el UUID de la D1 existente y `POSITION_STORAGE="blocks-v1"`.
2. Ejecutar `python scripts/prepare_compact_gateway.py`. En Windows puede indicarse el entrypoint oficial de Wrangler mediante `WRANGLER_ENTRYPOINT`. El instalador reserva el coste aditivo y conserva todas las generaciones y el ledger.
3. Ejecutar los tests y `wrangler versions upload --preview-alias reliability --config gateway/wrangler.toml`. La candidata comparte intencionadamente la base, pero no recibe tráfico de producción.
4. Cargar originales recién comprobados contra la candidata y usar `action=validate`: verifica recuentos y revisión sin activar. No activar bloques mientras producción siga usando código antiguo.
5. Desplegar el código verificado con `wrangler deploy --config gateway/wrangler.toml`. Confirmar que la generación anterior sigue consultable y ejecutar `refresh.yml`; solo entonces la publicación normal activa los bloques validados.

`deploy-gateway.yml` permite el mismo despliegue aditivo desde CI si existe `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID` y `CLOUDFLARE_D1_DATABASE_ID`. Sin esa configuración lo indica expresamente; no representa una actualización de datos. Se ha retirado el antiguo trabajo diario que reconstruía índices históricos.

## Almacenamiento compacto y presupuestos

Cada generación identifica explícitamente su formato. Los registros aprobados se agrupan por los dos primeros dígitos hexadecimales de su ID: hasta 256 bloques, cada uno con un máximo de 256 registros y 512.000 bytes. Cada bloque es inmutable, ordenado y solo contiene los campos permitidos. Repetir una carga idéntica no reescribe sus datos. Una generación solo se activa tras comprobar totales, puestos únicos, continuidad de rangos, documentos de adjudicación y Maestros, y una revisión invariable durante la activación atómica.

Las generaciones históricas se conservan. El formato nuevo evita reescribir una fila y múltiples índices FTS por cada registro. La consulta nominal conserva búsqueda sin acentos, apellidos repetidos, filtro de lista, 20 resultados por página y cursor ligado a la generación. Un máximo de 5.000 candidatos exige concretar las búsquedas amplias; no es una medida del coste de escanear los bloques.

La ingesta mantiene el ledger UTC de D1, reservas con caducidad y límite de 70.000 unidades diarias, liquidando los contadores reales. Las consultas compactas reservan una estimación antes de ejecutar SQL y liquidan `rows_read` cuando está disponible, con un presupuesto independiente de tres millones de lecturas y 2.000 solicitudes diarias. El margen restante cubre metadatos, validación y controles; no acredita el consumo de otros recursos de la cuenta. Al alcanzar el presupuesto, la API devuelve 429 explícito y no habilita facturación.

La recuperación de originales cifrados requiere `PRIVATE_ARCHIVE_KEY`. Sin ella se descargan y verifican de nuevo las fuentes oficiales. Un original almacenado nunca renueva por sí solo la fecha de comprobación de CARM.

## Volver atrás

La API administrativa `action=rollback` solo selecciona una generación previamente validada. El Worker compacto puede leer también generaciones históricas sin FTS. Para volver a un Worker anterior que no conoce bloques, primero restaurar una generación histórica compatible mediante la API administrativa y comprobar sus consultas; después ejecutar `wrangler rollback VERSION_ID --config gateway/wrangler.toml`. Un rollback de código no revierte D1. Nunca borrar el ledger o los datos para eludir cuotas.
