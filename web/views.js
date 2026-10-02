/* View functions are presentation-only; data stays tied to its source snapshot. */
(function () {
  "use strict";
  const E = BA.escape,
    U = BAUI;
  const sortOptions = [
    ["original", "Documento original"],
    ["function", "Función"],
    ["municipality", "Municipio"],
    ["center", "Centro"],
    ["quantity", "Plazas"],
  ];
  function current(m) {
    return (
      m.state.documents.find((d) => d.id === m.selectedDoc) ||
      m.state.documents.find((d) => d.id === m.state.current_id)
    );
  }
  function allRows(m) {
    return m.state.documents
      .filter((d) => ["approved", "superseded"].includes(d.status))
      .flatMap((d) => d.rows);
  }
  function displayed(m) {
    const groups = m.onlySaved
      ? BA.savedGroups(m.state.documents, m.prefs.favorites, m.filters)
      : [{ rows: BA.filter(current(m)?.rows || [], m.filters) }];
    return groups.flatMap((g) =>
      BA.sortRows(
        m.onlyProfile
          ? g.rows.filter((r) => m.prefs.functions.includes(r.function_code))
          : g.rows,
        m.sortBy,
        m.sortDirection,
      ),
    );
  }
  function canCheck(m) {
    return (
      m.state.mode === "server" &&
      m.state.capabilities?.source_check === "available"
    );
  }
  function refreshButton(m) {
    return U.button(
      "sync",
      canCheck(m) ? "Comprobar fuentes" : "Actualizar copia",
      "refresh",
      "primary",
      m.refreshing ? "disabled" : "",
    );
  }
  function statusName(value) {
    return (
      {
        completed: "Completada",
        partial: "Parcial",
        failed: "Fallida",
        running: "En curso",
        never: "Sin comprobación",
        read: "Leído",
        ok: "Correcto",
        not_modified: "Sin cambios",
        fetch_failed: "Error de descarga",
        extraction_failed: "Extracción fallida",
        detected_not_read: "Pendiente de lectura",
        approved: "Incorporado",
        pending: "Pendiente",
        blocked: "Acceso bloqueado",
      }[value] ||
      value ||
      "Sin comprobación"
    );
  }
  function freshness(m) {
    const f = m.state.freshness || {},
      time = { hour: "2-digit", minute: "2-digit" };
    return `<dl class="freshness-grid"><div><dt>Último intento</dt><dd>${E(BA.date(f.last_attempt_at, time))}</dd></div><div><dt>Última comprobación completa</dt><dd>${E(BA.date(f.last_success_at, time))}</dd></div><div><dt>Estado</dt><dd>${E(statusName(f.status))}</dd></div></dl>`;
  }
  function historyNotice(m) {
    const h = m.state.history_window;
    if (!(Number(h?.omitted_documents) > 0)) return "";
    return U.notice(
      "Historial publicado limitado",
      `${E(h.note || "Esta copia pública solo incluye las publicaciones recientes.")} Se omiten ${E(h.omitted_documents)} documentos. Los favoritos de copias no incluidas siguen guardados en este navegador, pero sus filas no están disponibles en esta consulta.`,
      "neutral",
    );
  }
  function coverage(m) {
    const pending = m.state.catalog.notices.filter((n) =>
        BA.isPendingNotice(n, m.state.documents, m.state.history_documents),
      ),
      f = m.state.freshness || {};
    const warning = pending.length || ["partial", "failed"].includes(f.status);
    return `<div class="coverage ${warning ? "coverage-warning" : ""}"><div class="coverage-summary">${U.icon("info")}<span>Disponibilidad actual sin confirmar.</span><span class="check-summary">Fuentes: <strong>${E(statusName(f.status))}</strong> · ${E(BA.date(f.last_attempt_at, { hour: "2-digit", minute: "2-digit" }))}</span>${pending.length ? `<strong class="pending-summary">${U.count(pending.length, "publicación pendiente", "publicaciones pendientes")}</strong>` : ""}<button class="inline-link" data-view="sources">Ver fuentes ${U.icon("arrow")}</button></div></div>${m.refreshing ? `<div class="notice neutral" role="status"><span class="spinner" aria-hidden="true"></span><span id="refresh-status">${E(m.refreshMessage || "Buscando publicaciones…")}</span></div>` : ""}`;
  }
  function header(title, actions = "") {
    return `<div class="page-header"><h1>${E(title)}</h1>${actions ? `<div class="buttons">${actions}</div>` : ""}</div>`;
  }
  function vacancies(m) {
    const doc = current(m),
      rows = m.onlySaved ? allRows(m) : doc?.rows || [],
      approved = m.state.documents.filter((d) => d.status === "approved");
    return (
      header(
        "Vacantes sin cubrir",
        refreshButton(m) + U.button("export-csv", "Exportar CSV", "download"),
      ) +
      `<section class="publication-bar" aria-label="Publicación consultada"><label class="publication-select" for="copy-select"><span>${m.onlySaved ? "Publicaciones guardadas" : "Publicación"}</span><select id="copy-select" ${m.onlySaved ? "disabled" : ""} aria-label="Copia consultada">${approved.map((d) => `<option value="${E(d.id)}" ${doc?.id === d.id ? "selected" : ""}>${E(BA.date(d.published_at))}${d.id === m.state.current_id ? " · más reciente" : ""}</option>`).join("")}</select></label>${m.onlySaved ? '<p class="muted">Guardadas por fecha de publicación.</p>' : `<div class="stats" aria-label="Totales de la copia"><button class="stat-jump" data-action="show-results" aria-label="${BA.places(rows)} plazas: ir a los resultados"><strong>${BA.places(rows)}</strong> plazas <span aria-hidden="true">↓</span></button><span><strong>${rows.length}</strong> registros</span><span><strong>${BA.unique(rows, "function_code").length}</strong> funciones</span><span><strong>${BA.unique(rows, "municipality").length}</strong> municipios</span></div>`}</section>` +
      coverage(m) +
      `
 <section class="filters" aria-label="Filtros de vacantes"><div class="search-row"><div class="search-input">${U.icon("search")}<input class="input" id="search" type="search" value="${E(m.filters.q || "")}" placeholder="Función, centro, municipio o código…" aria-label="Buscar vacantes"></div><div class="checks"><label class="inline-check"><input id="only-saved" type="checkbox" ${m.onlySaved ? "checked" : ""}>Guardadas <span class="muted">(${allRows(m).filter((r) => m.prefs.favorites.includes(r.id)).length})</span></label><label class="inline-check"><input id="only-profile" type="checkbox" ${m.onlyProfile ? "checked" : ""}>Mis funciones <span class="muted">(${m.prefs.functions.length})</span></label></div>${U.button("clear-filters", "Limpiar", "", "text")}</div>
 <div class="filter-grid">${U.select("function_code", "Función", BA.unique(rows, "function_code", "function"), m.filters.function_code, "Todas las funciones")}${U.select("body_code", "Cuerpo", BA.unique(rows, "body_code", "body"), m.filters.body_code, "Todos")}${U.select("municipality", "Municipio", BA.unique(rows, "municipality"), m.filters.municipality, "Todos")}${U.select(
   "workload",
   "Jornada",
   [
     ["full", "Completa"],
     ["partial", "Parcial"],
   ],
   m.filters.workload,
   "Todas",
 )}${U.select("language", "Bilingüe", BA.unique(rows, "language"), m.filters.language, "Todas")}${U.select(
   "cupo",
   "Cupo",
   [
     ["VP", "VP"],
     ["VS", "VS"],
   ],
   m.filters.cupo,
   "Todos",
 )}${U.select(
   "itinerant",
   "Itinerancia",
   [
     ["S", "Sí"],
     ["N", "No"],
   ],
   m.filters.itinerant,
   "Todas",
 )}</div></section>
 <section id="results" class="results ${m.density === "comfortable" ? "comfortable" : "compact"}" aria-label="Resultados">${results(m)}</section><div class="footnote">${U.icon("info")}<p>Plazas: columna «Sin cubrir» del PDF. Registros: filas del documento, incluidas las repetidas.</p></div>`
    );
  }
  function filterChips(m) {
    const labels = {
      q: "Búsqueda",
      function_code: "Función",
      body_code: "Cuerpo",
      municipality: "Municipio",
      workload: "Jornada",
      language: "Bilingüe",
      cupo: "Cupo",
      itinerant: "Itinerancia",
    };
    const rows = m.onlySaved ? allRows(m) : current(m)?.rows || [];
    const chips = Object.entries(m.filters)
      .filter(([, value]) => value)
      .map(([key, value]) => {
        const row = rows.find((r) => String(r[key]) === String(value));
        const label =
          key === "function_code"
            ? BA.title(row?.function || value)
            : key === "body_code"
              ? BA.title(row?.body || value)
              : key === "workload"
                ? { full: "Completa", partial: "Parcial" }[value] || value
                : key === "itinerant"
                  ? { S: "Sí", N: "No" }[value] || value
                  : value;
        return `<button class="filter-chip" data-action="remove-filter" data-key="${E(key)}" aria-label="Quitar ${E(labels[key] || key)}: ${E(label)}">${E(labels[key] || key)}: ${E(label)}${U.icon("close")}</button>`;
      });
    return chips.length
      ? `<div class="active-filters" aria-label="Filtros activos">${chips.join("")}</div>`
      : "";
  }
  function resultTools(m) {
    return `<div class="result-tools"><label class="sort-label" for="sort-by">Ordenar<select id="sort-by">${sortOptions.map(([key, label]) => `<option value="${key}" ${(m.sortBy || "original") === key ? "selected" : ""}>${label}</option>`).join("")}</select></label>${U.button("sort-direction", m.sortDirection === "desc" ? "Descendente" : "Ascendente", m.sortDirection === "desc" ? "sort-down" : "sort-up", "direction", `id="sort-direction" ${!m.sortBy || m.sortBy === "original" ? "disabled" : ""}`)}<div class="density-switch" role="group" aria-label="Densidad de filas">${U.button("density", "Compacta", "", "", `data-density="compact" aria-pressed="${m.density !== "comfortable"}"`)}${U.button("density", "Cómoda", "", "", `data-density="comfortable" aria-pressed="${m.density === "comfortable"}"`)}</div></div>`;
  }
  function results(m) {
    const rows = displayed(m),
      size = [25, 50, 100].includes(m.pageSize) ? m.pageSize : 25;
    m.page = Math.min(
      Math.max(1, m.page),
      Math.max(1, Math.ceil(rows.length / size)),
    );
    const start = (m.page - 1) * size,
      visible = rows.slice(start, start + size);
    const summary = m.onlySaved
      ? `<strong>Registros guardados por copia · ${U.count(rows.length, "registro")}</strong><span class="result-caption">Agrupados por publicación</span>`
      : `<strong>${U.count(BA.places(rows), "plaza")} <span class="muted">en ${U.count(rows.length, "registro")}</span></strong><span class="result-caption">${Object.values(m.filters).some(Boolean) || m.onlyProfile ? "Resultados filtrados" : "En esta publicación"}</span>`;
    const head =
      filterChips(m) +
      `<div class="results-head"><div id="result-count" role="status" aria-live="polite" aria-atomic="true" tabindex="-1">${summary}</div>${resultTools(m)}</div>`;
    let content;
    if (m.onlySaved) {
      const groups = m.state.documents
        .map((document) => ({
          document,
          rows: visible.filter((r) =>
            document.rows.some((source) => source.id === r.id),
          ),
        }))
        .filter((g) => g.rows.length);
      content =
        historyNotice(m) +
        (groups
          .map(
            (g) =>
              `<section class="saved-group"><div class="section-head"><h2>${E(BA.date(g.document.published_at))} <span class="muted">· proceso ${E(g.document.process_id)}</span></h2><span>${U.count(g.rows.length, "registro")} · ${BA.places(g.rows)} plazas en esta copia</span></div>${U.table(g.rows, m.prefs)}</section>`,
          )
          .join("") ||
          U.empty(
            "No hay registros guardados que coincidan",
            "Usa el marcador de una vacante para guardarla.",
            U.button("clear-filters", "Ver todas las vacantes"),
          ));
    } else
      content = rows.length
        ? U.table(visible, m.prefs)
        : U.empty(
            "No hay coincidencias en esta copia",
            "Prueba con otros filtros.",
            U.button("clear-filters", "Restablecer filtros"),
          );
    return (
      head + content + U.pagination(m.page, rows.length, size, "page", true)
    );
  }
  function changes(m) {
    const prev = m.state.documents.find((d) => d.id === m.state.previous_id),
      latest = m.state.documents.find((d) => d.id === m.state.current_id),
      all = m.state.changes;
    const filtered = all.filter(
        (c) => !m.changeKind || c.kind === m.changeKind,
      ),
      names = {
        appeared: "Figuran ahora",
        disappeared: "Ya no figuran",
        quantity_changed: "Cambia la cantidad",
      };
    const size = 25;
    m.changePage = Math.min(
      Math.max(1, m.changePage),
      Math.max(1, Math.ceil(filtered.length / size)),
    );
    return (
      header("Cambios entre publicaciones") +
      U.notice(
        "Los cambios entre listados no confirman adjudicaciones.",
        "",
        "neutral",
      ) +
      (prev && latest
        ? `<section class="comparison-bar"><div><span class="eyebrow">Publicación anterior</span><h2>${E(BA.date(prev.published_at))}</h2><p>Proceso ${E(prev.process_id)} · ${E(prev.places)} plazas</p></div>${U.icon("arrow")}<div><span class="eyebrow">Publicación más reciente</span><h2>${E(BA.date(latest.published_at))}</h2><p>Proceso ${E(latest.process_id)} · ${E(latest.places)} plazas</p></div><span class="pill observed">Comparación histórica</span></section><details class="technical-details comparison-note"><summary>Procedencia de los listados</summary><p>Anterior: ${E(U.provenance(prev))} Actual: ${E(U.provenance(latest))}</p></details>
 <div class="tabs" role="group" aria-label="Tipo de cambio"><button class="tab ${!m.changeKind ? "active" : ""}" data-action="change-kind" aria-pressed="${!m.changeKind}" data-kind="">Todos <span>${all.length}</span></button>${Object.entries(
   names,
 )
   .map(
     ([k, v]) =>
       `<button class="tab ${m.changeKind === k ? "active" : ""}" data-action="change-kind" aria-pressed="${m.changeKind === k}" data-kind="${k}">${v} <span>${all.filter((c) => c.kind === k).length}</span></button>`,
   )
   .join("")}</div>
 <div class="data-table-wrap"><div class="change-row change-heading" aria-hidden="true"><span>Cambio observado</span><span>Función</span><span>Destino</span><span>Plazas</span></div>${
   filtered
     .slice((m.changePage - 1) * size, m.changePage * size)
     .map(
       (c) =>
         `<div class="change-row"><div class="change-type"><span class="pill ${c.kind === "appeared" ? "full" : c.kind === "disappeared" ? "pending" : "observed"}">${names[c.kind]}</span></div><div><div class="row-primary">${E(BA.title(c.row.function))}</div><div class="row-secondary mono">${E(c.row.function_code)} · ${E(c.row.jornada)}</div></div><div><div class="row-primary">${E(BA.title(c.row.municipality))}</div><div class="row-secondary">${E(BA.title(c.row.center))}</div></div><div class="change-delta">${E(c.before)} <span class="muted">→</span> ${E(c.after)}</div></div>`,
     )
     .join("") || '<div class="empty">Sin cambios de este tipo.</div>'
 }</div>${U.pagination(m.changePage, filtered.length, size, "change-page")}`
        : U.empty(
            "Se necesitan dos copias aprobadas",
            "La comparación aparecerá al incorporar dos procesos distintos.",
          ))
    );
  }
  function acts(m) {
    const notices = m.state.catalog.notices || [],
      docs = m.state.documents.filter((d) => d.status === "approved");
    return (
      header(
        "Actos y publicaciones",
        U.button("mark-seen", "Marcar mi revisión", "check"),
      ) +
      U.notice(
        "Consulta la convocatoria oficial para conocer plazos y requisitos.",
        "",
        "neutral",
      ) +
      `<div class="section-head"><h2>Listados de vacantes <span class="count">${docs.length}</span></h2></div><div class="document-grid">${docs.map((d) => `<article class="panel document-card"><div class="act-top"><div><span class="eyebrow">Acto · proceso ${E(d.process_id)}</span><h2>${E(BA.date(d.act_date))}</h2></div><span class="pill observed">Listado disponible</span></div><p>${E(d.act_title)}</p><div class="document-counts"><strong>${E(d.places)} plazas</strong><span>${E(d.row_count)} registros · ${E(d.pages)} páginas</span></div><p>Publicada: ${E(BA.date(d.published_at, { hour: "2-digit", minute: "2-digit" }))}</p><p>${E(U.provenance(d))}</p><div class="buttons mt16">${U.button("open-copy", "Ver vacantes", "grid", "primary", `data-id="${E(d.id)}"`)}${U.pdfLink(d)}${U.external(d.source_url, "Origen oficial")}</div></article>`).join("")}</div>
 <div class="section-head"><h2>Anuncios oficiales <span class="count">${notices.length}</span></h2></div><div class="timeline">${
   notices
     .map(
       (n) =>
         `<article class="act ${BA.isPendingNotice(n, m.state.documents, m.state.history_documents) ? "pending" : ""}"><div class="act-top"><div><div class="eyebrow">${E(BA.date(n.date))}</div><h3>${E(n.title || "Publicación")}</h3></div><span class="pill ${BA.isPendingNotice(n, m.state.documents, m.state.history_documents) ? "pending" : ""}">${n.kind !== "vacancies" ? "Aviso informativo" : BA.isPendingNotice(n, m.state.documents, m.state.history_documents) ? "Documento sin incorporar" : "Documento incorporado"}</span></div><p>${E(n.note || statusName(n.status) || "Anuncio oficial detectado")}</p><div class="buttons">${U.external(n.url, "Página oficial")}${(
           n.pdf_urls || [n.pdf_url]
         )
           .filter(Boolean)
           .map((url) => U.external(url, "PDF en origen"))
           .join("")}</div></article>`,
     )
     .join("") || '<p class="muted">Sin anuncios en esta copia.</p>'
 }</div>` +
      U.notice(
        "Convocatorias, resultados e incidencias: cobertura incompleta.",
        "",
        "neutral",
      ) +
      (m.state.catalog.weekly_schedule?.length
        ? `<details class="panel schedule"><summary>Calendario semanal orientativo de RRHH</summary><p>${E(m.state.catalog.schedule_warning)}</p><table class="table-small"><thead><tr><th>Día</th><th>Hora</th><th>Previsión general</th></tr></thead><tbody>${m.state.catalog.weekly_schedule.map((x) => `<tr><td>${E(x.day)}</td><td>${E(x.time)}</td><td>${E(x.event)}</td></tr>`).join("")}</tbody></table></details>`
        : "")
    );
  }
  function profile(m) {
    const functions = BA.unique(allRows(m), "function_code", "function"),
      saved = allRows(m).filter((r) => m.prefs.favorites.includes(r.id));
    return (
      header("Mi seguimiento") +
      historyNotice(m) +
      (m.storageAvailable === false
        ? U.notice(
            "Almacenamiento local no disponible.",
            "Las preferencias solo durarán esta sesión. El navegador no permite conservarlas al cerrar.",
          )
        : "") +
      `<section class="saved-summary panel"><div>${U.icon("bookmark")}<div><h2>${U.count(saved.length, "registro guardado", "registros guardados")}${Number(m.state.history_window?.omitted_documents) > 0 ? " disponibles" : ""}</h2><p>Guardados por publicación.</p></div></div><div class="buttons">${U.button("view-saved", "Ver guardadas", "arrow", "primary")}${U.button("export-preferences", "Exportar preferencias", "download")}</div></section>
 <div class="two-col"><section class="panel"><h2>Funciones que sigo</h2><p>Funciones presentes en los listados disponibles.</p><div class="search-input mt15">${U.icon("search")}<input class="input" id="profile-search" type="search" placeholder="Función o código…" aria-label="Buscar funciones"></div><div class="profile-functions" id="function-list">${functions.map(([code, name]) => `<label class="function-option" data-function-search="${E(BA.norm(code + " " + name))}"><input type="checkbox" data-profile-function="${E(code)}" ${m.prefs.functions.includes(code) ? "checked" : ""}><span>${E(BA.title(name))}<span class="row-secondary mono">${E(code)}</span></span></label>`).join("")}</div><p id="profile-empty" class="hidden" role="status">No hay funciones que coincidan con la búsqueda.</p><div class="profile-footer"><p class="profile-count" id="profile-count">${U.count(m.prefs.functions.length, "función seleccionada", "funciones seleccionadas")}</p>${U.button("apply-profile", "Aplicar mis funciones", "arrow", "primary")}</div></section>
 <div><section class="panel section"><h2>Mi posición en lista</h2><p>Disponible en Educarm. Los listados de vacantes no permiten calcular tu posición.</p><div class="buttons mt16">${U.external(m.state.catalog.sources.find((s) => s.id === "educarm-position")?.url, "Ir a Educarm")}</div></section>
 <section class="panel"><h2>Preferencias y privacidad</h2><p>Las preferencias se guardan en este navegador. Las alertas externas no están disponibles.</p><p>Última revisión personal: <strong>${E(BA.date(m.prefs.lastSeen))}</strong>.</p><div class="buttons mt16">${U.button("reset-preferences", "Borrar preferencias locales", "", "danger")}</div></section></div></div>`
    );
  }
  function sameSourceUrl(a, b) {
    if (!a || !b) return false;
    try {
      const left = new URL(a),
        right = new URL(b);
      left.hash = "";
      right.hash = "";
      left.searchParams.sort();
      right.searchParams.sort();
      return left.href === right.href;
    } catch {
      return false;
    }
  }
  function sources(m) {
    const cat = m.state.catalog,
      checks = m.state.checks || cat.checks || [],
      pending = cat.notices.filter((n) =>
        BA.isPendingNotice(n, m.state.documents, m.state.history_documents),
      );
    return (
      header("Fuentes", refreshButton(m)) +
      historyNotice(m) +
      `<section class="panel section source-overview"><div class="act-top"><h2>Comprobaciones</h2></div>${freshness(m)}<p><strong>${U.count(pending.length, "publicación pendiente", "publicaciones pendientes")}.</strong> Los documentos sin validar no sustituyen al último listado válido.</p>${m.refreshing ? `<p id="refresh-status" role="status">${E(m.refreshMessage || "Buscando publicaciones…")}</p>` : ""}</section>` +
      U.notice(
        "Alcance: vacantes sin cubrir de Secundaria y otros cuerpos",
        `${canCheck(m) ? "Consulta del RSS, índice y anuncios de RRHH." : "Actualizar copia carga los datos publicados; no ejecuta una nueva consulta a las fuentes."} Convocatorias, resultados e incidencias: cobertura incompleta.`,
        "neutral",
      ) +
      `<section class="section"><div class="section-head"><div><h2>Documentos y procedencia</h2></div><span class="count">${m.state.documents.length}</span></div><div class="document-grid">${m.state.documents.map((d) => `<article class="panel document-card"><div class="act-top"><h3>${E(BA.date(d.published_at))}</h3><span class="pill ${d.status === "pending" ? "pending" : "observed"}">${E({ approved: "Incorporada", pending: "En revisión", superseded: "Sustituida" }[d.status] || d.status)}</span></div><div class="document-counts"><strong>${E(d.places)} plazas</strong><span>${E(d.row_count)} registros</span></div><p>${E(U.provenance(d))}</p><div class="buttons mt13">${U.pdfLink(d)}${U.external(d.source_url, "Origen oficial")}</div><details class="technical-details"><summary>Huella del documento · SHA-256</summary><div class="hash">${E(d.sha256)}</div>${d.warnings.length ? `<p>${E(d.warnings.join(" "))}</p>` : ""}</details></article>`).join("")}</div></section>` +
      `<section class="section"><div class="section-head"><div><h2>Registro de fuentes</h2></div><span class="count">${cat.sources.length}</span></div><div class="data-table-wrap">${cat.sources
        .map((s) => {
          const check = checks
            .filter((c) => c.id === s.id || sameSourceUrl(c.url, s.url))
            .at(-1);
          return `<article class="source-row"><div><h3>${E(s.name || s.id)}</h3><div class="source-role">${E(s.type || s.role || "Referencia oficial")}</div>${check ? `<p>Intento: ${E(BA.date(check.checked_at, { hour: "2-digit", minute: "2-digit" }))}${check.error ? " · " + E(check.error) : ""}</p>` : "<p>Sin comprobación reciente registrada para esta referencia.</p>"}<details class="technical-details"><summary>Observaciones</summary><p>${E(s.note || "Sin nota adicional.")}</p></details></div><div class="source-status ${check?.success ? "ok" : ""}"><span class="dot"></span>${E(check ? statusName(check.status) : "Referencia de auditoría")}</div><div class="source-external">${U.external(s.url, "Abrir", "")}</div></article>`;
        })
        .join("")}</div></section>` +
      (checks.length
        ? `<details class="panel section technical-log"><summary>Últimos intentos por recurso <span class="count">${checks.length}</span></summary><ol class="event-list">${checks.map((c) => `<li class="event"><time>${E(BA.date(c.checked_at, { hour: "2-digit", minute: "2-digit" }))}</time><div><strong>${E(statusName(c.status))}</strong><p>${E(c.error || "")} ${U.external(c.url, "Recurso oficial", "")}</p><code class="resource-id">${E(c.id)}</code></div></li>`).join("")}</ol></details>`
        : "") +
      `<details class="panel technical-log"><summary>Registro de operaciones</summary><ol class="event-list">${
        m.state.events
          .slice(0, 12)
          .map(
            (e) =>
              `<li class="event"><time>${E(BA.date(e.created_at, { hour: "2-digit", minute: "2-digit" }))}</time><div><strong>${E(e.title)}</strong>${e.details?.reason ? `<p>${E(e.details.reason)}</p>` : ""}${e.details?.failures?.length ? `<p>${E(e.details.failures.join(" · "))}</p>` : ""}</div></li>`,
          )
          .join("") || '<li class="event">Sin operaciones registradas.</li>'
      }</ol></details>`
    );
  }
  const views = { vacancies, changes, acts, profile, sources };
  function shell(m) {
    const nav = [
      ["vacancies", "Vacantes", "grid"],
      ["changes", "Cambios", "changes"],
      ["acts", "Actos", "calendar"],
      ["profile", "Mi seguimiento", "bookmark"],
      ["sources", "Fuentes", "shield"],
    ];
    return `<div class="shell"><aside class="sidebar"><div class="brand"><span class="brand-symbol" aria-hidden="true">b.</span><div><div class="brand-name">Bolsa Abierta</div><div class="brand-subtitle">Información docente abierta</div></div></div><nav class="nav" aria-label="Navegación principal">${nav.map(([id, name, ico]) => `<button class="nav-button ${m.view === id ? "active" : ""}" data-view="${id}" ${m.view === id ? 'aria-current="page"' : ""}>${U.icon(ico)}<span>${name}</span></button>`).join("")}</nav><div class="sidebar-bottom"><button class="about" data-action="about">${U.icon("code")}Sobre el proyecto</button></div></aside><div class="content"><header class="topbar"><div class="breadcrumb"><strong><span class="desktop-only">Región de </span>Murcia</strong><span>/</span><span>Secundaria y otros cuerpos</span></div><button class="top-status" data-view="sources">${U.icon("shield")}${canCheck(m) ? "Comprobación disponible" : "Copia publicada"}</button></header><main id="main" class="main" tabindex="-1">${views[m.view](m)}</main></div></div>`;
  }
  window.BAV = { current, allRows, displayed, shell, results };
})();
