# Acceso automático a CARM

El cliente HTTP simple recibía la verificación de Radware en lugar de los PDF.
La prueba del 12 de octubre de 2026 en GitHub Actions obtuvo el original 209571
con Chromium normal y una pantalla virtual; el modo headless seguía bloqueado.
No se resolvió ningún CAPTCHA ni se utilizaron proxies externos o cookies de una persona.

`OFFICIAL_SOURCE_TRANSPORT=chromium` activa ese transporte exclusivamente para
HTTPS de `www.carm.es`. El RSS y los anuncios de RRHH mantienen el cliente HTTP.
Los workflows instalan `.[browser]` y Chromium, y ejecutan cada fase de captación
con `xvfb-run -a`. No depende de que el PC del responsable esté encendido.

El navegador recibe una página vacía generada localmente para establecer el
origen. Esa página no es una consulta ni evidencia oficial. Las peticiones reales
son GET con lectura por bloques y límites de tiempo y bytes. No se ejecuta HTML
remoto; se bloquean navegaciones, subrecursos, service workers y otros orígenes.
Las redirecciones opacas se rechazan sin seguirlas. Se verifican las direcciones
DNS públicas y se fija su resolución en Chromium. El navegador no recibe los
secretos de publicación en su entorno ni conserva un perfil entre ejecuciones.

`OfficialClient` conserva sus comprobaciones de tipo MIME, firma PDF, tamaño,
contenido de verificación y presupuestos. Las esperas por HTTP 429/Retry-After
se comparten entre transportes; un bloqueo exclusivo del cliente HTTP no impide
probar por primera vez el navegador. Un fallo nuevo del navegador tiene su propia
espera. Descargar un original no evita la revisión de un hash cambiado o de un
formato desconocido.

El original del [anuncio del 7 de octubre](https://rrhheducacion.carm.es/07-10-2026-relacion-de-vacantes-sin-cubrir-secundaria-y-otros-cuerpos/)
se conserva como fixture público `tests/fixtures/carm-2026-10-07.pdf`, con SHA-256
`b668022511f140042b3422f1ed045a2d3be46a31d265fff63790b05e744d65c7`.
Contiene 24 filas y 26 plazas en dos páginas, proceso 3137, emitido a las 14:49
del 7 de octubre en Murcia. La firma aparece debajo de la última tabla. El lector
acepta exactamente el bloque ya revisado en esa posición o en una página final
separada, y sigue rechazando firmas incompletas, cambiadas, con otra fecha o
seguidas de contenido desconocido.

Las pruebas de navegador se ejecutan con:

```sh
RUN_BROWSER_TESTS=1 xvfb-run -a python -m unittest tests.test_browser_runtime
```

Estas pruebas usan respuestas controladas para verificar límites y redirecciones.
La evidencia de actualización real es adicional: una ejecución de captación debe
descargar y validar el original, incorporarlo al estado y publicarlo. El estado
parcial del inventario y los documentos pendientes de revisión siguen siendo
independientes del éxito de un PDF concreto.
