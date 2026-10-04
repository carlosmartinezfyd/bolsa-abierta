# Plan de implementación de fiabilidad y cobertura

**Goal:** aplicar el informe aprobado y publicar cambios verificados que mejoren cobertura sin inventar estados administrativos.

**Architecture:** adaptadores estrictos de Python, inventario persistente de metadatos, ingesta autenticada y activación atómica en D1, consulta y presentación accesible en JavaScript, trabajos acotados en GitHub Actions y sondeo ligero opcional del Worker.

**Stack:** Python 3.12, requests/BeautifulSoup/pdfplumber, JavaScript nativo, SQLite/D1, Cloudflare Workers, GitHub Actions/Pages.

**Spec:** `docs/superpowers/specs/2026-10-04-source-reliability.md`.

## Global constraints

Aplican todas las reglas de la especificación. No se versionan originales nominales. Los agentes trabajan sobre archivos asignados y no modifican la rama compartida ni publican por su cuenta. La integración y publicación corresponden al coordinador.

## Review focus

1. Un documento incompleto no puede cambiar la generación activa.
2. Las fechas y estados parciales no se convierten en disponibilidad.
3. Maestros conserva la lista única y la semántica de sus correcciones.
4. Cambios de contenido, límites de recorrido y padres no visitados no se confunden con retirada oficial.
5. Las consultas y los trabajos respetan límites de recursos y no filtran identificadores o datos sensibles.

## Task 1: Descubrimiento e inventario

- [ ] Reproducir los fallos de clasificación, enlace extraño, límite y padre no visitado.
- [ ] Corregirlos; separar fechas, versiones, cobertura y colas recientes/históricas.
- [ ] Ampliar raíces y paginación acotada para las familias comprobadas en la auditoría.
- [ ] Verificar con pruebas sintéticas y metadatos sin nombres.

## Task 2: Documentos de adjudicación

- [ ] Reproducir el rechazo de la última página con filas.
- [ ] Admitir las 137 filas de 209314 manteniendo validación estructural completa.
- [ ] Extraer únicamente fecha de incorporación y reserva provisional; preservar ordinal nulo.
- [ ] Incorporar los manifiestos revisados y registrar «optan» como observación sin efecto inferido.

## Task 3: Lista única de Maestros

- [ ] Inspeccionar íntegramente los originales 208253 y 208782 y sus anexos.
- [ ] Crear adaptador, manifiesto y consolidación revisada, con pruebas sintéticas de truncamiento/corrección.
- [ ] Mantener habilitaciones separadas del ordinal único y aportar recuentos independientes.

## Task 4: Consulta, almacenamiento y programación

- [ ] Extender validación de ingesta y consulta para nuevos campos y Maestros.
- [ ] Añadir índices y búsqueda acotada con medición de planes de consulta.
- [ ] Reforzar reintento idempotente, activación y recuperación; presupuestos de actualización.
- [ ] Añadir sondeo cron ligero y mediciones, sin ejecutar análisis de PDF en el Worker ni activar facturación.

## Task 5: Presentación de cobertura y evidencia

- [ ] Presentar ámbito, fecha y calidad de la evidencia de cada resultado.
- [ ] Mostrar lista única/habilitaciones de Maestros, incorporación y reservas provisionales.
- [ ] Separar fuentes pendientes, comprobadas y omitidas por presupuesto; revisar textos de privacidad y disponibilidad.
- [ ] Verificar regresiones de interfaz y accesibilidad.

## Task 6: Integración, operación y publicación

- [ ] Integrar ingesta privada con caché verificada, manifiestos y relación de identidades.
- [ ] Añadir recepción administrativa controlada, copias/recuperación y métricas de ejecución.
- [ ] Actualizar documentación y solicitud preparada, sin enviarla.
- [ ] Ejecutar pruebas y validaciones integrales con los originales; revisión independiente del conjunto.
- [ ] Publicar al repositorio y comprobar CI/despliegue, enumerando cualquier dependencia de credenciales o datos oficiales.
