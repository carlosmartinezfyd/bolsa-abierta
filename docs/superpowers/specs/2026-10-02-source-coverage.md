# Cobertura de fuentes oficiales

## Problema y alcance autorizado

La búsqueda sólo incorpora una lista ordinaria y dos correcciones revisadas. Los procedimientos extraordinarios y funciones bilingües quedan fuera, aunque sus documentos sean públicos. Ampliar una búsqueda textual no corrige esa ausencia.

## Arquitectura

1. Inventario persistente de publicaciones oficiales: catálogo completo de RRHH y secciones CARM del curso, con procedencia, clasificación y estado por documento. Un límite de tiempo, cambio de contenido o descarga fallida deja cobertura pendiente; nunca equivale a ausencia de novedades.
2. Adaptadores explícitos por formato. La lista ordinaria conserva su extracción estricta. Las adjudicaciones definitivas aportan hechos fechados, con todas las filas del documento, sin inferir posición ni disponibilidad. Las resoluciones de admisión necesitan su propio adaptador; un documento descubierto no se declara incorporado.
3. Generación inmutable de búsqueda con documentos revisados, hashes, páginas, conteos y registros. Cada registro tiene su propia fuente y tipo. Se admiten códigos bilingües. Los documentos no ordenados no pueden producir un puesto.
4. Publicación atómica: validar antes de activar, preservar la generación anterior en cualquier fallo. Los datos personales permanecen en D1 y archivos privados, nunca en Pages, Git o logs.
5. UI: misma búsqueda sencilla. Una coincidencia puede mostrar un puesto en una lista fechada o una adjudicación fechada. El detalle contiene las fuentes; no se mezclan personas o publicaciones por mera similitud de nombre.

## Contratos

El manifiesto amplía `position-source.json` con `documents`: content_id, source_url, sha256, published_at, pages, kind, row_count y conteos por función. Inicialmente `kind=award` para adjudicaciones definitivas. Nuevos formatos permanecen pendientes hasta validación.

Las filas adicionales llevan `record_type=award`, source_id, specialty, specialty_name, body_name, name, list_number, page, rank=null, block vacío, block_name vacío, destination y workload. La identidad incluye documento, función, número y nombre; no depende del orden del resultado. Las filas ordinarias mantienen sus identificadores y rank.

La versión multi_source usa la tabla nueva position_entries; las versiones antiguas siguen siendo legibles. El alta valida conteos por documento y función, rangos de las listas ordenadas y ausencia de rangos en hechos. La fecha visible corresponde a la fuente de la fila.

El inventario guarda metadatos públicos sin títulos nominales en la rama de estado, y evidencias completas sólo en almacenamiento privado del proceso. Los estados son discovered, unavailable, changed, pending_review, incorporated y not_applicable, con fecha de intento separada de fecha de comprobación. Incorporado requiere hash coincidente con manifiesto revisado; no basta con descargar.

## Límites explícitos

Ninguna adjudicación demuestra por sí sola quién está disponible hoy. No calcular posición actual sin una secuencia completa y reconciliada de altas, bajas, correcciones y reactivaciones. No usar CAPTCHA resuelto como prueba de acceso automatizado. No servicios de pago ni claves en cliente.

## Validación

Pruebas de paginación/catálogo, documentos desconocidos, fallos/revisiones y persistencia; PDF completo, filas omitidas, códigos bilingües y totales; API y UI para filas sin rango, fuente propia, publicación atómica y compatibilidad. Revisión independiente, pruebas completas, comprobación visual móvil y consultas reales antes de declarar desplegado.
