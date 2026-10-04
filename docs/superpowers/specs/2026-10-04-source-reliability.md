# Fiabilidad de fuentes y cobertura: diseño aprobado

El 4 de octubre de 2026 el titular del proyecto pidió aplicar el informe de auditoría y su plan. Esta especificación recoge el alcance de esa autorización para implementación, comprobación y publicación del proyecto.

## Resultado esperado

La aplicación conserva y consulta hechos acreditados por originales oficiales completos. Diferencia listas publicadas, adjudicaciones y disponibilidad. Amplía el inventario a Maestros, resultados de actos, listas urgentes, extraordinarias y abiertas, habilitaciones y sus correcciones. Un fallo de acceso o de lectura mantiene la última generación validada y deja visible lo pendiente.

## Reglas vinculantes

- No se calcula posición entre disponibles mientras falte una población oficial completa y sus reglas de precedencia.
- La identidad de pertenencia a una lista incluye curso, cuerpo, lista/bloque y número; el número solo y la coincidencia aproximada de nombres no unen personas.
- La lista única de Maestros se identifica como ámbito de cuerpo `0597`, nunca como una especialidad ficticia. Las habilitaciones conservan sus códigos oficiales y el ordinal pertenece a la lista única.
- Cada documento conserva URL oficial, identificador, hash, fechas de publicación/comprobación y páginas. Un cambio de bytes o de interpretación requiere una nueva versión validada.
- Las adjudicaciones conservan ordinal nulo. Sus fechas de incorporación y posibles reservas provisionales son hechos separados de la fecha de publicación. No se guardan observaciones médicas ni datos de personas sustituidas.
- No visitar un padre no demuestra desaparición de sus enlaces. Alcanzar el presupuesto de recorrido no es un intento fallido de descarga.
- Los originales nominales se mantienen fuera de Git, artefactos públicos y registros de ejecución. La ingesta usa una credencial administrativa y una lista cerrada de orígenes.
- Una generación se activa atómicamente después de verificar documentos, recuentos y ordinales. La anterior sigue disponible si hay fallo.
- No se habilita facturación ni se promete gratuidad ilimitada. Los trabajos tienen presupuestos y prioridad para fuentes activas.
- La solicitud al organismo queda preparada y sin enviar. Lo dependiente de esa respuesta queda señalado como pendiente.

## Interfaces de integración

Los documentos semanales mantienen `kind: award`. Sus filas pueden añadir `incorporation_at` (fecha ISO) y `appointment_status` (`definitive` o `provisional`), con evidencia de documento/página. La observación «optan» se archiva e identifica sin inferir efectos sobre la disponibilidad.

Maestros se incorpora como documento `kind: maestros_roster`, `rank_scope: maestros_unique_list`, con un grupo `code: 0597` denominado «Lista única de Maestros». Sus filas usan `record_type: list`, `specialty: 0597`, ordinal único y habilitaciones separadas. Correcciones y relación entre identificadores deben validarse contra el original antes de consolidar.

El inventario añade estados de trabajo omitido por presupuesto y cobertura por fuente/familia. La interfaz debe tolerar estados anteriores y no convertir una cobertura parcial en completa.

## Aceptación

Pruebas de regresión de los defectos auditados; extracción integral de los originales 209126 y 209314 (147 y 137 registros); validación independiente de Maestros y su corrección; consultas limitadas e indexadas; preservación de la generación anterior ante fallos; verificación de la publicación al commit aplicado. El seguimiento de catorce días se inicia y no se presenta como ya completado.
