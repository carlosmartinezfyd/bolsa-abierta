# Comunicación: implementación y validación

Fecha de comprobación local: 13 de octubre de 2026. La implementación conserva el servicio de datos, las fuentes, las rutas existentes y las preferencias del navegador. No añade analítica, fuentes remotas ni servicios de pago.

## Aplicación de la auditoría

| Recomendación | Resultado |
|---|---|
| A01. Modelo de estados | Tipo, publicación, acto, firma, comprobación, cobertura y disponibilidad se presentan por separado. La ausencia de metadatos permanece explícita. |
| A02. Mi ficha | Navegación y resultados distinguen lista y adjudicación, cuerpo y curso. |
| A03. Límites visibles | El ordinal se identifica como puesto en el orden publicado. La adjudicación muestra fecha y no acredita disponibilidad actual. |
| A04. Comprobaciones por conjunto | Vacantes y listas/adjudicaciones tienen fechas y pendientes propios. Un cero no se extiende a todo el inventario. |
| A05. Fuentes en móvil | Inventario convertido en bloques con etiqueta/valor; comprobado a 320 y 390 px. |
| A06. Históricos | Cabecera y detalle indican publicación histórica y falta de PDF conservado. |
| A07. Buscar y olvidar | Buscar otra ficha conserva el identificador recordado. Un 404 temporal tampoco lo borra. Se puede recuperarlo expresamente. |
| A08. Ver y recordar | Ver una ficha no la guarda. Recordar y olvidar son acciones separadas. |
| A09. Coincidencias | Tipo, cuerpo y fechas visibles; filtros de tipo/cuerpo sobre coincidencias cargadas y filtro de cuerpo en especialidades. No se fusionan identidades. |
| A10. Navegación | Mi ficha, Vacantes, Publicaciones, Guardados, Fuentes y cobertura. Comparación dentro de Vacantes; hashes antiguos preservados. |
| A11. Inicio | Dos accesos principales visibles en móvil; última publicación con fecha, plazas y registros. |
| A12. Fuentes | Conjuntos consultables, límites y documentos antes del inventario, versiones y registro técnico plegados. |
| A13. Archivo | Búsqueda, tipo, cuerpo, curso, intervalo de publicación y paginación. Autoría separada del portal que aloja el aviso. |
| A14. Fechas | Publicación, acto y firma rotulados independientemente; nunca se usa detección como publicación. |
| A15. Estados | Etiquetas comprensibles y detalle técnico accesible; no se presenta un aplazamiento como un nuevo intento. |
| A16. Tabla de comparación | Tabla semántica con encabezados de columna y fila, fuentes anterior/posterior y desplazamiento propio. Árbol accesible inspeccionado; falta sesión con lector de pantalla real. |
| A17. Comparaciones | Selección cronológica de documentos compatibles, filtros y cantidades agregadas preservando duplicados. Desaparecer no significa adjudicación. |
| A18. Detalle | Jornada y plazas antes de códigos; fuente y página visibles. |
| A19. Duración | Valor explícito, ausencia acreditada y campo no extraído tienen mensajes diferentes. Los documentos actuales sin extracción no se describen como carentes de duración. |
| A20. Edición | Diccionario cerrado de tildes, conectores, siglas y números romanos. Los valores originales siguen en el detalle. No se completan centros truncados ni se alteran claves o datos fuente. |
| A21. Guardados | Grupos por publicación, incluidos históricos, funciones seguidas y estado vacío con acción útil. |
| A22. Estados de carga | Carga, fallo, vacío y evidencia conservada diferenciados. La llegada de metadatos conserva búsqueda sin enviar, foco, despliegues y posición. |
| A23. Correcciones | Configuración validada preparada en `web/contact.js`; requiere responsable y formulario HTTPS privado o correo autorizado. Permanece sin activar hasta recibir un contacto real. No se solicitan datos nominales en incidencias públicas. |
| A24. Tipografía | Cuerpo 16 px, secundarios 14 px, jerarquía de títulos, campos cómodos y foco visible. Cuatro anchuras verificadas. |
| A25. Vacíos | Sin ordenación, exportación ni paginación redundantes. El CSV conserva contexto de publicación. |
| A26. Inicio sin pasos | Eliminada numeración decorativa de tareas independientes. |
| A27. Contraste | Medidas de colores principales y bordes, foco reforzado; desactivados conservan semántica `disabled`. No se declara certificación global WCAG. |
| A28. Cronología | Archivo ordenado por fecha y guardados agrupados por publicación. No se añade una gráfica de evolución que sugiera disponibilidad o una serie personal no acreditada. |
| A29. Contrato de diseño | `DESIGN.md` documenta jerarquía, voz, estados, evidencia, privacidad y adaptación. |
| A30. Validación | Pruebas funcionales y recorrido real con datos de publicación y fichas sintéticas locales. Protocolo de participantes preparado abajo. No se han realizado sesiones con personas usuarias. |

## Evidencia de verificación

- Node: 155 pruebas superadas. Incluyen cantidades duplicadas, incompatibilidad y dirección de comparaciones, históricos sin PDF, metadatos desconocidos, filtros, contacto, persistencia de fichas, llegada tardía de metadatos y ciclo de foco.
- Python: 295 pruebas, resultado OK; cuatro omitidas por disponibilidad del entorno o navegador. La ejecución específica del navegador de extracción se comprueba además en CI.
- `designmd lint DESIGN.md`: cero errores y cero advertencias.
- Navegador real integrado de Codex: siete vistas por cuatro anchuras (320, 390, 768 y 1440), 28 mediciones sin desbordamiento horizontal del documento. También se abrió el inventario técnico a 320 px.
- Archivo: búsqueda textual, tipo y fecha combinados, limpieza, avance de página. Se observaron 62 entradas en esta copia; es una observación fechada, no una cifra fija del producto.
- Vacantes: filtrado a un municipio, vacío sin controles sobrantes, detalle y retorno de foco, favorito histórico consultable desde Guardados.
- Comparación: publicaciones del 30 de septiembre y 7 de octubre; 64 grupos cambiados (6 aparecen, 58 desaparecen). Las unidades son grupos documentales, no personas ni adjudicaciones. Cambio de pareja y filtro de Murcia comprobados.
- Ficha sintética local: búsqueda, selección por tipo, consulta sin recordar, recordar, buscar otra, recuperar y olvidar; especialidades por cuerpo y cierre con Escape. No se usaron consultas nominales reales para generar evidencias.
- Teclado: Escape devuelve el foco al origen; Tab y Shift+Tab cierran el ciclo entre controles visibles de los diálogos. Se corrigió un escape de foco observado durante esta comprobación.
- Sin errores ni advertencias de consola en el recorrido local observado.

Contrastes calculados con los colores usados: texto principal/fondo 12,29:1; secundario/fondo 4,98:1; acción o foco/blanco 6,67:1; aviso/fondo de aviso 6,44:1; borde de control/blanco 3,18:1. Son pares medidos, no una auditoría exhaustiva de toda combinación de estados.

El navegador integrado no aplicó zoom con el atajo enviado; no se atribuye una prueba al 200 % que no ocurrió. La comprobación a 320 px acredita reflujo a esa anchura, pero no sustituye una prueba de ampliación de texto. Tampoco se ha ejecutado NVDA/VoiceOver ni una sesión en dispositivo físico.

## Protocolo de validación con participantes

Reclutar 5–8 docentes, repartiendo experiencia con listas y adjudicaciones y uso de móvil/escritorio. Utilizar fichas sintéticas, consentir cualquier grabación y evitar recoger nombres, DNI o consultas personales. No enviar comunicaciones a participantes sin autorización específica.

Tareas: (1) encontrar qué se puede consultar; (2) localizar y distinguir lista/adjudicación; (3) explicar qué significa el ordinal y su fecha; (4) filtrar una vacante y abrir su fuente; (5) reconocer un documento histórico sin PDF; (6) comparar dos publicaciones sin inferir adjudicación; (7) guardar y recuperar una plaza; (8) explicar qué significa cobertura parcial y qué fecha se comprobó realmente; (9) consultar otra ficha sin borrar la recordada.

Registrar éxito sin ayuda, tiempo, errores, primeras rutas, comprensión de unidades y de límites. Criterio de salida: ninguna interpretación crítica de ordinal como disponibilidad actual o desaparición como adjudicación; al menos 80 % de tareas completadas sin ayuda. Es un criterio propuesto, no un resultado observado. Corregir los problemas que aparezcan y repetir solo las tareas afectadas.

Accesibilidad pendiente: NVDA con Chrome/Firefox, teclado completo, zoom 200 % y ampliación de texto, alto contraste del sistema y móvil físico. Revisar tabla de comparación, cierre y retorno de foco de ambos diálogos, anuncios de resultados y orden de lectura. No declarar conformidad general hasta completar esa comprobación.

## Contacto y publicación

Para activar el canal de correcciones, completar ambos campos de `web/contact.js` con un responsable y destino autorizados. La configuración se conserva al generar la configuración del API; no contiene secretos. No se aceptan enlaces con credenciales, esquemas ejecutables ni texto personal preinsertado. Una solicitud enviada a ese canal no modifica por sí sola los datos oficiales.

La publicación se integra mediante PR, comprobaciones CI y el flujo existente de GitHub Pages. La evidencia final de ejecución y la comprobación de API/Pages se entrega al terminar el despliegue. No cambian el motor de extracción, el acceso a CARM ni los datos nominales.
