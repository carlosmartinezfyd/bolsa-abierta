# Plan de implementación: Mi posición

**Objetivo:** consulta pública y gratuita del puesto en una publicación oficial, con selección personal local e información de procedencia bajo demanda.

**Ejecución:** en la rama feat/personal-position. Desarrollo con pruebas primero, revisión independiente al terminar. No es una reconstrucción de disponibilidad actual.

1. Parser `bolsa_abierta/positions.py`: filas admitidas, límites de anexos, integridad y procedencia. Pruebas `tests/test_positions.py`, auditoría del PDF real en `.runtime/position-research`.
2. API `gateway/positions.mjs` y tablas `gateway/positions.sql`: catálogo, búsqueda limitada, lectura de fila, versiones y carga autenticada; probar con SQLite real y el handler de producción.
3. Recolector `bolsa_abierta/position_sync.py`: comprobación oficial, hash, carga en lotes y activación; workflow periódico, sin datos nominales en artefactos públicos ni logs.
4. `web/position.js` y CSS: selección, confirmación, tarjeta, detalle y recarga; integrar ruta y entrada principal. Actualizar DESIGN.md.
5. Suites Python/Node, navegador, revisión independiente; desplegar D1/Worker y nueva web. Verificar respuestas públicas y límites de vigencia antes de informar de finalización.

**Contratos:** catálogo `{version, specialties}`, búsqueda `{version, results, more}`, fila `{version, person}`. Versión incluye `id, published_at, checked_at, source_url, sha256, row_count, scope:'published_list', coverage:'baseline_only'`. Nunca exponer `available_rank` sin evidencia completa.
