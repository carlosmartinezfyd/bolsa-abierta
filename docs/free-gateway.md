# Comprobación pública con Workers Free, D1 y GitHub Actions

Esta pasarela permite que el visitante pulse «Comprobar ahora» desde GitHub Pages sin instalar nada. Cloudflare conserva una solicitud compartida y activa exclusivamente `refresh.yml` del repositorio configurado. GitHub Actions obtiene las fuentes oficiales y publica la instantánea; la pasarela confirma el resultado cuando ve su identificador en esa publicación. No se ha creado ninguna cuenta ni desplegado la pasarela durante esta implementación.

El captador y el parser siguen ejecutándose en GitHub Actions. El Worker no recibe URLs de fuentes, PDFs, referencias Git ni nombres de workflow desde el navegador. El esquema D1 guarda trabajos y límites, sin documentos ni credenciales públicas.

La lectura de `state.json` tiene un límite de protección de 16 MiB. El exportador limita la ventana pública a 8 MiB: mantiene las dos copias comparadas y retira primero las filas históricas más antiguas, conservando sus metadatos y PDF; SQLite conserva el historial íntegro. También debe comprobarse el tiempo de CPU de Workers Free con el tamaño real; el límite de bytes no garantiza que un JSON grande entre en el presupuesto de CPU. Si se aproxima al límite de CPU, reducir la ventana o separar el catálogo del contenido por documento antes de ampliar el uso.

## Alcance y límites

El plan Workers Free admite 100.000 peticiones diarias por cuenta, con límite de CPU por petición; D1 Free incluye 5 millones de filas leídas y 100.000 escritas al día y 5 GB totales. Son límites de plataforma que deben revisarse antes de activar el servicio y vigilarse en el panel; al agotarse el plan gratuito puede dejar de responder. Fuentes: [límites de Workers](https://developers.cloudflare.com/workers/platform/limits/) y [precios y límites de D1](https://developers.cloudflare.com/d1/platform/pricing/).

GitHub Actions es gratuito para repositorios públicos que utilizan runners estándar, sujeto a sus reglas y disponibilidad. El almacenamiento de artifacts y caché tiene sus propios límites: GitHub Free incluye 500 MB de artifacts compartidos con Packages y 10 GB de caché por repositorio; revisa la retención y el presupuesto configurado. Sus colas, el despliegue de Pages y la caché pueden retrasar una publicación; esta arquitectura no garantiza una respuesta instantánea ni una hora de publicación. Fuentes: [facturación de Actions](https://docs.github.com/en/billing/concepts/product-billing/github-actions) y [retrasos de ejecuciones programadas](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).

La pasarela aplica límites propios por D1:

| Control | Comportamiento |
| --- | --- |
| Solicitudes simultáneas | Comparten un identificador de 32 caracteres hexadecimales y un único envío a GitHub. |
| Pausa global | Como mínimo 5 minutos entre nuevas reservas; se reutiliza el trabajo existente durante la pausa. |
| Trabajo pendiente | Mantiene una reserva activa hasta 20 minutos. |
| Cuota UTC | Hasta 96 reservas al día, incluyendo envíos rechazados o inciertos. |
| Consulta de progreso | Como máximo una lectura de la instantánea cada 10 segundos por trabajo pendiente. |
| Resultado incierto del envío | Mantiene la reserva y espera; no vuelve a enviar automáticamente. |
| Falta de confirmación | Tras 20 minutos devuelve fallo y conserva la copia publicada anterior. El workflow podría terminar más tarde. |

CORS permite el origen exacto configurado. El servicio continúa siendo público: un cliente HTTP puede solicitar trabajos dentro de estos límites. Los secretos permanecen en Cloudflare y el límite diario se comparte entre clientes. Se usan sesiones D1 dirigidas al primario y actualizaciones SQL condicionales para que la exclusión sobreviva a reinicios o instancias distintas.

## Preparación del repositorio

Antes de activar la pasarela, la rama `main` debe contener `.github/workflows/refresh.yml` con `workflow_dispatch.inputs.request_id`, y Pages debe publicar `data/state.json` y `documents/`. La respuesta terminal se reconoce solo si:

```json
{
  "freshness": {
    "request_id": "32_caracteres_hexadecimales",
    "status": "completed",
    "last_attempt_at": "2026-10-01T12:00:00+00:00"
  }
}
```

Los otros resultados terminales son `partial` y `failed`. El workflow también debe publicar ese registro cuando falle la captura, conservando los datos válidos. Una publicación anterior o de otro trabajo no confirma esta solicitud. Si `last_attempt_at` existe, debe ser igual o posterior al inicio del trabajo (se permite un segundo de redondeo). Las ejecuciones programadas sin `request_id` no confirman una solicitud pública pendiente.

## Configuración de Cloudflare

Los siguientes comandos son para el administrador y no se han ejecutado en esta entrega. Requieren una cuenta Cloudflare con Workers Free y Node.js para usar Wrangler. Los visitantes solo necesitan el navegador. También se pueden crear el Worker, la base y el secreto desde el panel de Cloudflare.

Desde la raíz del repositorio, en PowerShell:

```powershell
Set-Location gateway
Copy-Item -LiteralPath wrangler.example.toml -Destination wrangler.toml
npx wrangler login
npx wrangler d1 create bolsa-abierta-gateway
```

Sustituye `REPLACE_WITH_D1_DATABASE_ID` en `wrangler.toml` por el identificador mostrado. Mantén el binding exactamente `DB`. Ajusta las variables:

| Variable | Valor esperado |
| --- | --- |
| `ALLOWED_ORIGIN` | `https://carlosmartinezfyd.github.io`, sin ruta ni barra final. |
| `SNAPSHOT_URL` | `https://carlosmartinezfyd.github.io/bolsa-abierta/data/state.json`, sin consulta ni fragmento. Actualmente se admite HTTPS en `*.github.io`. |
| `GITHUB_REPOSITORY` | `carlosmartinezfyd/bolsa-abierta`, un único `owner/repo`. |
| `GITHUB_REF` | `main`, fijo en la configuración del servidor. |

Inicializa las tablas en D1 remoto y carga el secreto mediante el prompt de Wrangler:

```powershell
npx wrangler d1 execute bolsa-abierta-gateway --remote --file schema.sql
npx wrangler secret put GITHUB_TOKEN
```

`GITHUB_TOKEN` debe ser un token personal de acceso detallado, limitado a este repositorio y con permiso de repositorio **Actions: write**. GitHub documenta este permiso para [Create a workflow dispatch event](https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event). El token se pega únicamente en el prompt del secreto; no va en TOML, HTML, `BA_CONFIG`, documentación ni Git. Anota su caducidad y renuévalo desde la administración cuando corresponda.

Comprueba y, cuando se decida activar el servicio, despliega:

```powershell
npx wrangler deploy --dry-run
npx wrangler deploy
```

La segunda orden publica el Worker; no es necesaria para las pruebas locales. Guarda la URL HTTPS `https://bolsa-abierta-gateway.<cuenta>.workers.dev` que devuelve Wrangler. Referencias: [comandos D1](https://developers.cloudflare.com/workers/wrangler/commands/#d1) y [secretos de Workers](https://developers.cloudflare.com/workers/configuration/secrets/).

## Conexión del frontend

Configura, antes de cargar la aplicación, el origen HTTPS de la pasarela:

En el despliegue incluido, basta con añadir la variable de repositorio `PUBLIC_API_BASE` con esa URL y ejecutar de nuevo **Official source refresh**. El workflow genera `web/config.js` sin secretos. Para un despliegue manual, la configuración equivalente es:

```html
<script>
window.BA_CONFIG = { apiBase: "https://bolsa-abierta-gateway.CUENTA.workers.dev" };
</script>
```

No añadas `/api` al valor: los endpoints ya incluyen esa ruta. `GET /api/state` conserva los enlaces relativos `documents/...`, para que el frontend Pages descargue las copias archivadas desde Pages. Añade `mode: server` y `capabilities.source_check: available` solo cuando la pasarela tiene las variables y el secreto necesarios. Si falta configuración, indica `snapshot_only`. Si falla la instantánea, devuelve 502 y el frontend puede cargar su instantánea local.

El botón envía `POST /api/refresh`, `Content-Type: application/json`, `X-BA-Refresh: 1`, cuerpo `{}` y el origen del navegador. Se rechazan parámetros de consulta, propiedades JSON adicionales, cuerpos grandes y otros orígenes. Después se consulta `GET /api/refresh/{id}` hasta un resultado terminal. Al terminar, vuelve a leerse `/api/state`.

## Verificación y operación

Las pruebas no llaman a GitHub ni Cloudflare ni necesitan paquetes npm:

```powershell
node --test tests/gateway.test.mjs
```

Requieren Node.js 22.13 o posterior por el módulo integrado `node:sqlite`. Incluyen el SQL de producción sobre SQLite real, 20 solicitudes simultáneas, persistencia entre handlers, recuperación después de reserva interrumpida, cuota diaria, CORS, límites del cuerpo, progreso compartido, resultado incierto y publicaciones antiguas/fuera de orden. No sustituyen una prueba real después del despliegue.

Tras activarlo, comprueba primero `GET https://<worker>/api/state` y los enlaces a documentos. Haz una solicitud desde el botón de Pages, verifica que aparece un único workflow con su `request_id` y que el trabajo termina solo tras publicarse la instantánea correspondiente. Repite con dos pestañas. Observa las métricas de Workers y filas D1; las lecturas de progreso comparten acceso a la instantánea, pero cada petición pública sigue consumiendo recursos.

Si se alcanza la cuota diaria y no hay trabajo reutilizable, se devuelve 429. Un fallo D1 devuelve 503 y no dispara otra captura. Para desactivar las solicitudes públicas, elimina el secreto `GITHUB_TOKEN` del Worker y conserva la instantánea de Pages. La limpieza de trabajos antiguos es administrativa; nunca borres la fila `gateway_gate` para eludir la cuota activa.
