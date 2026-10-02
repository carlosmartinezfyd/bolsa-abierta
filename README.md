# Bolsa Abierta

Consulta y comparación de publicaciones de vacantes docentes de Murcia, con fuentes, fecha del documento, fecha de comprobación y evidencia descargable. Es un proyecto independiente: la publicación administrativa oficial prevalece.

## Información que obtiene

El captador consulta el [RSS de RRHH Educación](https://rrhheducacion.carm.es/feed/), su [índice de Personal Docente](https://rrhheducacion.carm.es/servicio-de-personal-docente/) y los anuncios enlazados. Incorpora tablas del formato revisado **«Vacantes sin cubrir de Secundaria y otros cuerpos»**. Otros avisos quedan como información enlazada, sin convertirlos en plazas ni deducir adjudicaciones.

Cada ejecución vuelve a consultar anuncios recientes (14 días), anuncios nuevos y los que no tienen fecha conocida, con un máximo de 20 páginas de anuncio. El RSS es limitado y el índice puede cambiar: esta cobertura no garantiza descubrir todos los actos administrativos ni rectificaciones antiguas. La web muestra los fallos y el ámbito comprobado.

La copia inicial del 30/09/2026 contiene **77 filas y 85 plazas**, proceso 3133. Su PDF oficial se descargó el 01/10/2026 y su hash se contrastó con el original archivado. Las copias históricas del 18 y 25 de septiembre conservan los datos del prototipo; sus PDF originales no estaban en el repositorio y se identifican como no contrastados por este captador. Una comprobación posterior bloqueada no renueva la fecha de comprobación completa.

## Fiabilidad y límites

- Se comprueban origen HTTPS, destinos de red, redirecciones, tipo de contenido, firma PDF, tamaño y tiempo. No se sortean CAPTCHA ni verificaciones de acceso.
- El extractor valida cabeceras, fechas, proceso, páginas, columnas, códigos y cantidades. Conserva celdas originales, coordenadas y filas duplicadas. Las especialidades nuevas con código válido conservan su nombre original.
- Los bytes se archivan por SHA-256 antes de extraer. Una extracción rechazada conserva evidencia para revisión del mantenedor, pero no publica sus filas como válidas. HTML, errores y extracciones vacías nunca sustituyen datos aprobados.
- La fecha de emisión, descarga e intento de comprobación son distintas. «Comprobación completada» se refiere a las fuentes cubiertas en esa ejecución; no acredita que cada plaza siga disponible en tiempo real.
- La firma electrónica **no se autentica criptográficamente**. No hay OCR; los PDF escaneados, otros diseños o estructuras no revisadas requieren ampliar el corpus y el parser.
- La comparación describe diferencias entre publicaciones de procesos distintos. Una desaparición no demuestra adjudicación, retirada ni resultado administrativo. Se guardan también revisiones del mismo proceso.
- No se consultan cuentas de Educarm ni listas nominales. Favoritos y preferencias permanecen en el navegador, sin analítica.
- La descarga de datos para el navegador se limita a 8 MiB: conserva siempre las dos copias comparadas y omite primero las filas más antiguas, avisando en la interfaz. El historial íntegro permanece en SQLite y los PDF en el archivo; las omisiones no eliminan los favoritos guardados. Se publican hasta 300 avisos recientes. La pasarela acepta hasta 16 MiB para dejar margen al transporte.

## Publicación gratuita

La ruta principal utiliza **GitHub Pages + GitHub Actions en este repositorio público**. [GitHub documenta el uso gratuito de runners estándar para repositorios públicos](https://docs.github.com/en/actions/concepts/billing-and-usage). No requiere instalar nada a los visitantes.

1. Integrar esta rama en `main` tras revisar el cambio.
2. En Settings → Pages → Build and deployment, seleccionar **GitHub Actions**. El despliegue anterior desde la raíz de `main` debe cambiarse a este modo.
3. Ejecutar **Official source refresh** desde Actions. El workflow consulta fuentes, guarda SQLite y PDF en la rama `data-state`, genera la web y publica Pages. La rama de datos debe conservarse para mantener historial y evidencia.
4. El calendario solicita dos ejecuciones por hora, en los minutos 17 y 47 UTC. GitHub puede retrasar o desactivar calendarios por inactividad; no es una garantía de actualización puntual. La fecha visible permite detectar una automatización detenida.

Sin pasarela, **Recargar datos** vuelve a cargar el último resultado publicado; no activa una consulta oficial. El botón **Actualizar** solicita una comprobación oficial y conserva su resultado visible, incluso cuando no hay un listado nuevo. Para activarlo en otro despliegue, configurar la [pasarela gratuita Cloudflare Worker + D1](docs/free-gateway.md) y la variable de repositorio `PUBLIC_API_BASE`. El token de GitHub se guarda únicamente como secreto del Worker. Sus peticiones comparten trabajo y tienen límites de frecuencia y cuota diaria; el resultado puede tardar varios minutos por la cola de Actions. La pasarela exige una cuenta y configuración externa; no queda activada al clonar este código.

La web mantiene una copia estática cuando la API no está disponible y explica qué acción puede realizar. Los planes gratuitos tienen límites; no se contratan servicios ni se habilita facturación desde este repositorio.

## Desarrollo y servicio opcional

Código del navegador legible en `web/`; sin empaquetador ni cargas binarias ocultas. Python 3.11+ para el captador; Node 22.13+ para pruebas del navegador y pasarela.

```sh
python -m pip install -e .
python -m bolsa_abierta init
python -m bolsa_abierta refresh
python -m bolsa_abierta export --output site
python -m bolsa_abierta serve --port 8000
```

`--data-dir DIRECTORIO` antes del subcomando permite elegir almacenamiento persistente; por defecto `.runtime/`. El primer arranque importa `data/state.json` y sus PDF archivados, verificando hashes. El servidor de desarrollo escucha solo en `127.0.0.1`; los visitantes de la web publicada no lo necesitan.

Hay un contenedor opcional para infraestructura propia: `docker build -t bolsa-abierta .` y `docker run -p 8000:8000 -v bolsa-data:/data bolsa-abierta`. Usa un solo proceso Gunicorn con cuatro hilos y un trabajador de captación. Un proxy HTTPS debe publicar el servicio. No se ha contratado ni desplegado un servidor; esta alternativa no forma parte del coste de la solución principal gratuita.

La API ofrece `GET /api/state`, `POST /api/refresh` (JSON `{}`, cabecera `X-BA-Refresh: 1`), `GET /api/refresh/{id}` y `GET /api/documents/{sha256}.pdf`. No admite URL de descarga arbitraria, credenciales de usuarios ni importación pública. El servicio agrupa peticiones simultáneas y aplica espera mínima de 60 segundos; la pasarela tiene límites superiores.

## Verificación

```sh
python -m unittest discover -s tests -p 'test_*.py'
node --test tests/*.test.cjs tests/*.test.mjs
```

Las pruebas cubren PDF reales y sintéticos, extracción incompleta, fuentes bloqueadas/vacías, redirecciones no autorizadas, revisión de un mismo URL, hashes históricos recuperados, archivo ausente/corrupto, concurrencia y restauración del estado, UI estática/servidor, filtros, favoritos y pasarela. El fixture oficial conserva [procedencia y límites de validación](tests/fixtures/carm-2026-09-30.provenance.json). Las pruebas no necesitan la red; las comprobaciones reales son observaciones puntuales, no garantías de disponibilidad.

## Licencia

Código GNU AGPL-3.0-only. Los documentos y datos de terceros mantienen sus condiciones de reutilización y no quedan relicenciados. Véase `NOTICE`.
