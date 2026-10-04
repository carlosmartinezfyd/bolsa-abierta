# Inventario de fuentes

El inventario descubre documentos y conserva lo pendiente entre ejecuciones. No modifica listas ni calcula puestos. El proceso de posiciones decide qué adaptadores puede aplicar y sólo marca una publicación como incorporada después de activar la generación en la API.

## Ejecución

```sh
python -m bolsa_abierta.source_inventory \
  --registry data/source-registry.json \
  --source data/position-source.json \
  --documents saved-state/source-documents.json \
  --state saved-state/source-inventory.json \
  --private-dir .runtime/source-inventory-private
```

`--documents` es opcional y puede no existir en la primera ejecución. Tiene la forma `{"documents": [...]}`: cada documento conserva `content_id`, `source_url`, `sha256` y, únicamente tras activarse, `incorporated: true`. Un hash revisado sin esa confirmación queda `pending_review` con `reviewed: true`. No equivale a haber publicado datos.

El estado se escribe de forma atómica incluso si la cobertura está incompleta; en ese caso la CLI devuelve 1. No descartar el archivo por ese código de salida. `--max-seconds` y `--max-requests` permiten ajustar el presupuesto del proceso.

## Descubrimiento y presupuesto

- El RSS general oficial se recorre por `?paged=N` hasta alcanzar el comienzo del curso configurado (`2026-06-01`, incluidas las listas preparadas durante el verano). Una página repetida, desordenada, inválida o un límite antes de esa frontera deja el índice incompleto.
- El mapa HTML oficial se usa como contraste del catálogo entero. Sus entradas no tienen fecha. Se conservan por una identidad opaca y se resuelven cinco fechas desconocidas por ejecución, rotando por el intento más antiguo. Los documentos anteriores al intervalo quedan fuera del curso, sin confundirlos con omisiones actuales.
- Las páginas de anuncios del intervalo se revisitan aunque el RSS conserve la misma fecha: pueden cambiar los adjuntos. Se recorren primero las menos recientemente comprobadas. La mitad del presupuesto restante de peticiones se reserva para documentos.
- Los documentos revisados reciben presupuesto antes del histórico de anuncios. Las colas recientes, históricas y sin fecha se conservan por separado. Saltarse una petición por falta de presupuesto no renueva su fecha de intento; se conserva el estado anterior y el trabajo aplazado.
- Los índices CARM se incluyen como fuentes independientes. Se siguen los enlaces observados de paginación, detalle y adjuntos HTML dentro de límites explícitos. Un índice vacío, bloqueado o inválido no demuestra que hayan desaparecido sus enlaces. La portada se revisita y las continuaciones pendientes reciben turno, incluso en fuentes recientes.
- El registro contiene 24 fuentes revisadas. Incluye las hojas de resultados de actos 24219 y 24183, el índice anual de Maestros 75501 y familias de listas urgentes, extraordinarias, abiertas y habilitaciones. Una familia inventariada no implica que todos sus documentos tengan adaptador ni estén incorporados.

Los límites son explícitos en el registro. Alcanzarlos produce cobertura pendiente, nunca ausencia de novedades. El cliente limita orígenes oficiales, redirecciones, DNS, bytes y duración. Un CAPTCHA se registra como fallo de acceso.

## Estado y procedencia

Cada documento expone `content_id`, `source_url`, `kind`, procedencias opacas (`source_ids`), hash descargado y fechas separadas. Los PDF se archivan sólo en el directorio privado como `{sha256}.pdf`, para que el adaptador procese exactamente los bytes inventariados.

| Estado | Significado |
| --- | --- |
| `discovered` | Localizado, pendiente de comprobación. |
| `unavailable` | No se pudo descargar o completar la comprobación. |
| `changed` | Los bytes difieren de la revisión conocida; necesita revisión. |
| `pending_review` | Descargado, pero todavía no incorporado con evidencia suficiente. |
| `incorporated` | Hash coincidente y activación confirmada por el proceso de publicación. |
| `not_applicable` | Provisional sin documento definitivo revisado asociado; no alimenta la posición. |
| `skipped` | Descarga aplazada por presupuesto; conserva el intento y resultado anteriores. |

La clasificación distingue listas, complementos, correcciones, admisiones, procedimientos urgentes, aperturas, adjudicaciones definitivas, ceses, reactivaciones, procedimientos desiertos, provisionales y documentos no clasificados. Clasificar un título no valida el contenido ni autoriza su incorporación. Un título que mezcla provisional y definitivo queda sin clasificar.

La desaparición de una fuente, anuncio o documento no borra su evidencia previa y solo se evalúa después de comprobar correctamente su padre. `content_history` conserva revisiones de bytes; `metadata_history`, revisiones de metadatos con huellas de los títulos. Una descarga fallida conserva `verified_at`; `attempted_at` registra intentos efectivos, y `downloaded_at` la última descarga. `checked_at` global sólo avanza si todo lo descubierto está comprobado e incorporado o descartado de forma admitida. Las fechas desconocidas del mapa se cuentan aparte de los anuncios pendientes del curso.

La cobertura se publica por fuente, familia, cuerpo y curso. `traversal_complete` describe los enlaces recorridos; `downloads_complete`, las descargas; `verification_complete`, los hashes revisados y comprobados en la ejecución. `scope_complete` exige recorrido y verificación. Los contadores de documentos pendientes, fallidos, aplazados y sin revisión explican los huecos. `history_complete` permanece falso: completar un recorrido acotado no acredita el historial administrativo completo.

El estado persistido no contiene nombres, títulos de anuncios, rutas nominales de RRHH ni texto extraído. Los enlaces públicos a descargas CARM permiten recuperar la fuente. Los originales HTML/PDF quedan en almacenamiento privado y no deben publicarse como artifacts, Pages o archivos Git.

## Límites actuales

La detección no implica cobertura total. Las fechas todavía desconocidas, formatos sin adaptador, índices bloqueados o documentos pendientes mantienen `review_complete: false`. Las adjudicaciones permiten acreditar hechos fechados; no reconstruyen por sí solas la disponibilidad actual. No se calcula una posición actual sin una secuencia completa y conciliada de listas y movimientos.

La comprobación real del 2 de octubre de 2026 recorrió 24 páginas RSS y encontró 239 anuncios desde el 1 de junio, frente a 3.629 entradas en el mapa histórico. La ejecución de prueba con 100 peticiones descubrió 30 documentos; sus comprobaciones no se declararon completas. Estos son resultados de esa ejecución, no un total permanente ni una garantía de acceso posterior.
