/* Shared interface primitives. SPDX-License-Identifier: AGPL-3.0-only */
(function () {
  "use strict";
  const E = BA.escape;
  const paths = {
    "sort-up": '<path d="M7 20V4m-4 4 4-4 4 4M14 6h7m-7 6h5m-5 6h3"/>',
    "sort-down": '<path d="M7 4v16m-4-4 4 4 4-4M14 6h3m-3 6h5m-5 6h7"/>',
    search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4 4"/>',
    grid: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
    changes: '<path d="M4 7h15m-4-4 4 4-4 4M20 17H5m4-4-4 4 4 4"/>',
    calendar:
      '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M16 3v4M8 3v4M3 11h18M7 15h2m4 0h2m-8 3h2"/>',
    bookmark: '<path d="M6 3h12v18l-6-4-6 4z"/>',
    shield:
      '<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6z"/><path d="m8 12 3 3 5-6"/>',
    external:
      '<path d="M14 3h7v7m0-7L11 13M10 5H5a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-5"/>',
    download: '<path d="M12 3v12m-5-5 5 5 5-5M5 15v6h14v-6"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10v.01"/>',
    arrow: '<path d="m9 5 7 7-7 7"/>',
    close: '<path d="m6 6 12 12M6 18 18 6"/>',
    check: '<path d="m5 12 4 4L19 6"/>',
    refresh:
      '<path d="M20 7v5h-5M4 17v-5h5"/><path d="M6 6a8 8 0 0 1 13 2M5 16a8 8 0 0 0 13 2"/>',
    code: '<path d="m8 5-6 7 6 7m8-14 6 7-6 7m-3-16-2 18"/>',
    upload: '<path d="M12 16V3m-5 5 5-5 5 5M4 16v5h16v-5"/>',
    bell: '<path d="M5 17h14l-2-3V9a5 5 0 0 0-10 0v5zm5 3h4"/>',
  };
  function count(n, singular, plural = singular + "s") {
    return `${E(n)} ${Number(n) === 1 ? singular : plural}`;
  }
  function icon(name) {
    return `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">${paths[name] || paths.info}</svg>`;
  }
  function external(url, label, classes = "button") {
    const safe = BA.safeURL(url);
    if (!safe || !safe.startsWith("https://")) return "";
    return `<a class="${classes}" href="${E(safe)}" target="_blank" rel="noopener noreferrer">${E(label)}${icon("external")}</a>`;
  }
  function button(action, label, ico = "", classes = "", extra = "") {
    return `<button class="button ${classes}" data-action="${E(action)}" ${extra}>${ico ? icon(ico) : ""}${E(label)}</button>`;
  }
  function pdfUrl(doc, page = 1) {
    let url = BA.safeURL(doc?.artifact_url);
    if (!url) return "";
    if (url.startsWith("/api/") && window.BA_CONFIG?.apiBase)
      url = BA.composeAPIURL(url.slice(5), window.BA_CONFIG);
    return (
      url.split("#")[0] + "#page=" + Math.max(1, Math.trunc(Number(page) || 1))
    );
  }
  function pdfLink(doc, page = 1, label = "Documento utilizado") {
    const url = pdfUrl(doc, page);
    return url
      ? `<a class="button" href="${E(url)}" target="_blank" rel="noopener noreferrer">${icon("external")}${E(label)}</a>`
      : '<span class="small muted">Copia no conservada</span>';
  }
  function select(key, label, values, selected, placeholder = "Todas") {
    return `<label class="field">${E(label)}<select data-filter="${E(key)}" aria-label="${E(label)}"><option value="">${E(placeholder)}</option>${values.map(([v, l]) => `<option value="${E(v)}" ${selected === v ? "selected" : ""}>${E(["function_code", "body_code", "municipality"].includes(key) ? BA.title(l) : l)}</option>`).join("")}</select></label>`;
  }
  function notice(text, description = "", kind = "warning") {
    return `<div class="notice ${kind === "warning" ? "" : kind}" role="note">${icon("info")}<div><strong>${text}</strong>${description ? `<p>${description}</p>` : ""}</div></div>`;
  }
  function rowMarkup(r, prefs) {
    const saved = prefs.favorites.includes(r.id);
    return `<tr>
<td class="favorite-cell"><button class="icon-button ${saved ? "saved" : ""}" data-action="favorite" data-id="${E(r.id)}" aria-label="${saved ? "Quitar de guardadas" : "Guardar plaza"}: ${E(r.center)}" aria-pressed="${saved}">${icon("bookmark")}</button></td>
<td class="function-cell"><button class="row-link row-primary" data-action="detail" data-id="${E(r.id)}" aria-label="${E(BA.title(r.function))}: detalle de ${E(BA.title(r.center))}">${E(BA.title(r.function))}</button><div class="row-secondary mono">${E(r.function_code)}</div></td>
<td class="municipality-cell"><div class="row-primary">${E(BA.title(r.municipality))}</div></td>
<td class="center-cell"><div class="row-primary row-center">${E(BA.title(r.center))}</div><div class="row-secondary mono">${E(r.center_code)}</div></td>
<td class="workload-cell"><span class="pill ${r.workload === "full" ? "full" : ""}">${r.workload === "full" ? "Completa" : E(r.hours) + " h · parcial"}</span></td>
<td class="cupo-cell">${E(r.cupo)}</td><td class="quantity-cell">${r.quantity}<span class="quantity-label"> ${r.quantity === 1 ? "plaza" : "plazas"}</span></td>
<td class="detail-cell"><button class="icon-button" data-action="detail" data-id="${E(r.id)}" aria-label="Ver detalle de ${E(r.center)}">${icon("arrow")}</button></td></tr>`;
  }
  function table(rows, prefs) {
    return `<div class="data-table-wrap"><table class="data-table"><caption class="sr-only">Registros de vacantes de esta publicación</caption><thead><tr><th scope="col" class="favorite-cell"><span class="sr-only">Guardar</span>${icon("bookmark")}</th><th scope="col" class="function-cell">Función</th><th scope="col" class="municipality-cell">Municipio</th><th scope="col" class="center-cell">Centro</th><th scope="col" class="workload-cell">Jornada</th><th scope="col" class="cupo-cell">Cupo</th><th scope="col" class="quantity-cell">Plazas</th><th scope="col" class="detail-cell"><span class="sr-only">Detalle</span></th></tr></thead><tbody>${rows.map((r) => rowMarkup(r, prefs)).join("")}</tbody></table></div>`;
  }
  function empty(title, description, action = "") {
    return `<div class="data-table-wrap"><div class="empty"><h3>${E(title)}</h3><p>${E(description)}</p>${action}</div></div>`;
  }
  function pagination(page, total, size, action = "page", chooseSize = false) {
    const max = Math.max(1, Math.ceil(total / size));
    return `<div class="pagination"><div class="page-summary"><span>${total ? (page - 1) * size + 1 + "–" + Math.min(page * size, total) : "0"} de ${total} registros</span>${chooseSize ? `<label for="page-size">Por página <select id="page-size">${[25, 50, 100].map((value) => `<option value="${value}" ${size === value ? "selected" : ""}>${value}</option>`).join("")}</select></label>` : ""}</div><div class="buttons">${button(action, "Anterior", "", "", `data-page="${page - 1}" ${page <= 1 ? "disabled" : ""}`)}<span>Página ${page} de ${max}</span>${button(action, "Siguiente", "", "", `data-page="${page + 1}" ${page >= max ? "disabled" : ""}`)}</div></div>`;
  }
  function provenance(doc) {
    if (doc.evidence_status === "original_unavailable")
      return "Histórico sin PDF original para contrastar.";
    const labels = {
      official_download: "PDF descargado de la fuente oficial.",
      third_party_reproduction: "Reproducción de terceros.",
      local_copy: "Copia local del documento.",
    };
    return (
      labels[doc.provenance] ||
      doc.provenance_label ||
      "Procedencia no documentada."
    );
  }
  function detail(row, doc, prefs) {
    const saved = prefs.favorites.includes(row.id);
    return `<div class="dialog-head"><div><h2 id="dialog-title">${E(BA.title(row.function))}</h2><p>${E(BA.title(row.center))} · ${E(BA.title(row.municipality))}</p></div><button class="icon-button" data-action="close-dialog" aria-label="Cerrar detalle">${icon("close")}</button></div>
<div class="dialog-body">${notice(`Publicación del ${E(BA.date(doc.published_at))}`, "Disponibilidad actual sin confirmar.")}
<dl class="detail-grid"><div><dt>Código de función</dt><dd class="mono">${E(row.function_code)}</dd></div><div><dt>Código de centro</dt><dd class="mono">${E(row.center_code)}</dd></div><div><dt>Jornada publicada</dt><dd>${E(row.jornada)}</dd></div><div><dt>Plazas en esta fila</dt><dd>${row.quantity}</dd></div><div><dt>Cupo publicado</dt><dd>${E(row.cupo)}</dd></div><div><dt>Itinerancia publicada</dt><dd>${row.itinerant === "S" ? "Sí (S)" : "No (N)"}</dd></div><div><dt>Mención bilingüe de la función</dt><dd>${E(row.language)}</dd></div><div><dt>Duración</dt><dd>No indicada</dd></div><div><dt>Acto · proceso</dt><dd>${E(BA.date(doc.act_date))} · ${E(doc.process_id)}</dd></div><div><dt>Ubicación en el PDF</dt><dd>Página ${row.page} · fila de datos ${row.row_number}</dd></div></dl>
<h3>Procedencia del dato</h3><p>${E(provenance(doc))}</p><details class="technical-details"><summary>Extracción y huella del documento</summary><p>Extracción: ${E(doc.parser_version)}. La huella identifica el archivo; no valida su firma electrónica.</p><div class="hash">SHA-256 · ${E(doc.sha256)}</div></details>
${doc.warnings.length ? `<p class="detail-footer-note">${E(doc.warnings.join(" "))}</p>` : ""}</div>
<div class="dialog-footer"><div class="buttons">${pdfLink(doc, row.page, "Abrir página " + row.page)}${external(doc.source_url, "Fuente oficial")}</div>${button("favorite", saved ? "Quitar guardada" : "Guardar", "bookmark", saved ? "" : "primary", `data-id="${E(row.id)}" data-modal="true"`)}</div>`;
  }
  window.BAUI = {
    count,
    icon,
    external,
    button,
    pdfUrl,
    pdfLink,
    select,
    notice,
    rowMarkup,
    table,
    empty,
    pagination,
    provenance,
    detail,
  };
})();
