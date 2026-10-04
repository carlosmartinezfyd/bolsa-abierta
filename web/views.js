/* View functions are presentation-only; data stays tied to its source snapshot. */
(function () {
  "use strict";
  const E = BA.escape,
    U = BAUI;
  const sortOptions = [
    ["original", "Original"],
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
      m.refreshing
        ? "Comprobando…"
        : canCheck(m)
          ? "Actualizar"
          : "Recargar datos",
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
        checked: "Comprobado",
        ok: "Correcto",
        not_modified: "Sin cambios",
        fetch_failed: "Error de descarga",
        extraction_failed: "Extracción fallida",
        detected_not_read: "Pendiente de lectura",
        approved: "Incorporado",
        pending: "Pendiente",
        blocked: "Acceso bloqueado",
        skipped: "Omitido por presupuesto",
        verified: "Documento verificado",
        incorporated: "Incorporado",
        pending_review: "Pendiente de revisión",
        unavailable: "Acceso sin resolver",
        not_applicable: "Fuera del ámbito",
        budget_deferred: "Pendiente por presupuesto",
        queued: "En cola",
        removed: "Enlace no observado",
        deferred: "Pendiente por presupuesto",
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
  function refreshFeedback(m) {
    if (!m.refreshing && !m.refreshFeedback) return "";
    const feedback = m.refreshFeedback || {};
    return `<div class="refresh-feedback ${E(feedback.kind || "neutral")}" role="status">${m.refreshing ? '<span class="spinner" aria-hidden="true"></span>' : U.icon("info")}<span id="refresh-status">${E(m.refreshing ? m.refreshMessage || "Comprobando fuentes…" : feedback.message)}</span>${m.refreshing ? "" : U.button("dismiss-refresh", "", "close", "icon-button", 'aria-label="Cerrar aviso"')}</div>`;
  }
  function coverage(m) {
    const pending = m.state.catalog.notices.filter((n) =>
      BA.isPendingNotice(n, m.state.documents, m.state.history_documents),
    );
    const f = m.state.freshness || {};
    const warning = pending.length || ["partial", "failed"].includes(f.status);
    const label = warning
      ? `${f.status && f.status !== "never" ? "Comprobación " + statusName(f.status).toLocaleLowerCase("es") : "Fuentes sin comprobar"}${pending.length ? " · " + U.count(pending.length, "publicación pendiente", "publicaciones pendientes") : ""}`
      : f.last_success_at
        ? `Fuentes comprobadas: ${E(BA.date(f.last_success_at, { hour: "2-digit", minute: "2-digit" }))}`
        : "Fuentes sin comprobar";
    return `<div class="source-line ${warning ? "source-warning" : ""}"><span>Disponibilidad actual sin confirmar.</span><button class="inline-link" data-view="sources">${label}${U.icon("arrow")}</button></div>`;
  }
  function header(title, actions = "") {
    return `<div class="page-header"><h1>${E(title)}</h1>${actions ? `<div class="buttons">${actions}</div>` : ""}</div>`;
  }
  function vacancies(m) {
    const doc = current(m),
      rows = m.onlySaved ? allRows(m) : doc?.rows || [];
    const approved = m.state.documents.filter((d) => d.status === "approved");
    const extraCount =
      ["body_code", "language", "cupo", "itinerant"].filter(
        (key) => m.filters[key],
      ).length +
      Number(!!m.onlySaved) +
      Number(!!m.onlyProfile);
    return `<section class="workspace-toolbar" id="workspace-toolbar" aria-label="Consulta de vacantes">
      <div class="workspace-heading"><h1>Vacantes sin cubrir</h1><div class="publication-actions"><label for="copy-select" class="copy-label">Publicación<select id="copy-select" aria-label="Publicación consultada" ${m.onlySaved ? "disabled" : ""}>${approved.map((d) => `<option value="${E(d.id)}" ${doc?.id === d.id ? "selected" : ""}>${E(BA.date(d.published_at))}</option>`).join("")}</select></label>${refreshButton(m)}</div></div>
      <div class="primary-filters" aria-label="Filtros de vacantes"><label class="search-input"><span class="sr-only">Buscar vacantes</span>${U.icon("search")}<input class="input" id="search" type="search" value="${E(m.filters.q || "")}" placeholder="Buscar centro o código…"></label>
      ${U.select("function_code", "Función", BA.unique(rows, "function_code", "function"), m.filters.function_code, "Todas las funciones")}
      ${U.select("municipality", "Municipio", BA.unique(rows, "municipality"), m.filters.municipality, "Todos")}
      ${U.select(
        "workload",
        "Jornada",
        [
          ["full", "Completa"],
          ["partial", "Parcial"],
        ],
        m.filters.workload,
        "Todas",
      )}
      <details id="extra-filters" class="extra-filters" ${m.extraFiltersOpen ? "open" : ""}><summary>Más filtros<span id="extra-filter-count" ${extraCount ? "" : "hidden"}>${extraCount || ""}</span>${U.icon("arrow")}</summary><div class="extra-filter-panel"><div class="secondary-filters">
      ${U.select("body_code", "Cuerpo", BA.unique(rows, "body_code", "body"), m.filters.body_code, "Todos")}
      ${U.select("language", "Bilingüe", BA.unique(rows, "language"), m.filters.language, "Todas")}
      ${U.select(
        "cupo",
        "Cupo",
        [
          ["VP", "VP"],
          ["VS", "VS"],
        ],
        m.filters.cupo,
        "Todos",
      )}
      ${U.select(
        "itinerant",
        "Itinerancia",
        [
          ["S", "Sí"],
          ["N", "No"],
        ],
        m.filters.itinerant,
        "Todas",
      )}</div>
      <div class="secondary-checks"><label class="inline-check"><input id="only-saved" type="checkbox" ${m.onlySaved ? "checked" : ""}>Solo guardadas <span class="muted">(${allRows(m).filter((r) => m.prefs.favorites.includes(r.id)).length})</span></label><label class="inline-check"><input id="only-profile" type="checkbox" ${m.onlyProfile ? "checked" : ""}>Mis funciones</label></div><div class="extra-filter-footer">${U.button("clear-filters", "Limpiar filtros", "", "text")}${U.button("close-filters", "Ver resultados", "", "primary")}</div></div></details></div>
      ${coverage(m)}${refreshFeedback(m)}</section>
      <section id="results" class="results comfortable" aria-label="Resultados">${results(m)}</section><div class="data-actions">${U.button("export-csv", "Exportar CSV", "download", "text")}</div>`;
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
    return `<div class="result-tools"><label class="sort-label" for="sort-by">Ordenar<select id="sort-by">${sortOptions.map(([key, label]) => `<option value="${key}" ${(m.sortBy || "original") === key ? "selected" : ""}>${label}</option>`).join("")}</select></label>${m.sortBy && m.sortBy !== "original" ? U.button("sort-direction", m.sortDirection === "desc" ? "Descendente" : "Ascendente", m.sortDirection === "desc" ? "sort-down" : "sort-up", "direction", 'id="sort-direction"') : ""}</div>`;
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
      : `<strong>${U.count(BA.places(rows), "plaza")} <span class="muted">en ${U.count(rows.length, "registro")}</span></strong>`;
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
 <div><section class="panel section"><h2>Mi posición</h2><p><a href="#position" data-view="position">Consultar mi ficha en la lista publicada</a></p><div class="buttons mt16">${U.external(m.state.catalog.sources.find((s) => s.id === "educarm-position")?.url, "Ir a Educarm")}</div></section>
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
  const scopeCourse=course=>course==='unknown'?'Curso desconocido':course||'Sin curso';
  function scopeEvidence(scope) {
    const value=(key,yes,no,unknown)=>scope[key]===true?yes:scope[key]===false?no:unknown;
    return `<p>Recorrido observado: ${value('traversal_complete','completado','pendiente','no consignado')} · Descargas: ${value('downloads_complete','completadas','pendientes','no consignadas')} · Evidencia revisada: ${value('verification_complete','completada','pendiente','no consignada')}</p><p>Cobertura del ámbito: ${value('scope_complete','completa','parcial','no consignada')} · ${scope.history_complete===true?'Historial completo acreditado':scope.history_complete===false?'Historial incompleto':'Historial no consignado'}</p>`;
  }
  function scopeDocuments(scope) {
    const counts=[['document_count','documento inventariado','documentos inventariados','Documentos inventariados: no consignados'],['pending_documents','documento pendiente','documentos pendientes','Documentos pendientes: no consignados'],['failed_documents','documento con error','documentos con error','Documentos con error: no consignados'],['skipped_documents','documento omitido por presupuesto','documentos omitidos por presupuesto','Documentos omitidos por presupuesto: no consignados'],['unreviewed_documents','documento sin revisar','documentos sin revisar','Documentos sin revisar: no consignados']];
    return `<p>${counts.map(([key,single,plural,unknown])=>Number.isInteger(scope[key])?U.count(scope[key],single,plural):unknown).join(' · ')}</p>`;
  }
  function inventoryCoverage(m) {
    const inventory=m.state.source_inventory||m.state.catalog.source_inventory;
    if(!inventory)return `<section class="panel section"><h2>Cobertura del inventario</h2><p>No hay metadatos de cobertura por fuente, familia y curso en esta copia. Los documentos incorporados no representan el corpus oficial completo.</p></section>`;
    const coverage=inventory.coverage||{}, sources=coverage.sources||inventory.scopes||[], families=coverage.families||[];
    const counts=inventory.status_counts||inventory.statuses||{};
    const rows=sources.filter(x=>x&&typeof x==='object');
    const total=inventory.document_count??inventory.total??(Object.keys(counts).length?Object.values(counts).reduce((n,x)=>n+Number(x||0),0):null);
    const totalLabel=total===null?'Recuento de documentos sin publicar.':`${E(total)} documentos inventariados.`;
    const pending=(x,key,label)=>Number.isInteger(x[key])?`${x[key]} ${label}`:`${label}: sin datos`;
    return `<section class="panel section"><h2>Cobertura del inventario</h2><p>${totalLabel} Completar un recorrido no acredita la descarga y revisión de sus documentos, un historial completo ni disponibilidad actual. Ampliar las fuentes iniciales no incorpora automáticamente sus documentos.</p>${Object.keys(counts).length?`<dl class="freshness-grid">${Object.entries(counts).map(([key,value])=>`<div><dt>${E(statusName(key))}</dt><dd>${E(value)}</dd></div>`).join('')}</dl>`:''}${rows.length?`<div class="data-table-wrap"><table class="table-small"><thead><tr><th>Fuente</th><th>Familia / cuerpo / curso</th><th>Recorrido, evidencia y pendientes</th><th>Fechas de evidencia</th></tr></thead><tbody>${rows.map(x=>`<tr><td>${E(x.source_id||x.source||'Sin identificar')}</td><td>${E(x.family||'Sin clasificar')} · ${E(x.body||'Sin cuerpo')} · ${E(scopeCourse(x.course))}</td><td><p>${E(statusName(x.status))}</p>${scopeEvidence(x)}${scopeDocuments(x)}<p>${E(pending(x,'pending_pages','páginas pendientes'))} · ${E(pending(x,'pending_details','detalles pendientes'))}</p></td><td>${checkDates(x)||"Sin fechas registradas"}</td></tr>`).join('')}</tbody></table></div>`:'<p>Desglose por fuente y curso pendiente de publicar.'}${families.length?`<details class="technical-details"><summary>Familias de publicaciones</summary><ul>${families.filter(x=>x&&typeof x==='object').map(x=>`<li>${E(x.family)} · ${E(x.body||'Sin cuerpo')} · ${E(scopeCourse(x.course))}${scopeEvidence(x)}${scopeDocuments(x)}</li>`).join('')}</ul></details>`:''}<details class="technical-details"><summary>Cómo interpretar los estados</summary><p>Omitido por presupuesto indica trabajo aplazado, sin un nuevo intento de descarga. Las fechas de comprobación o descarga anteriores siguen siendo evidencia histórica. Que un enlace deje de observarse no acredita la revocación del documento. La cobertura del ámbito combina el recorrido observado y la verificación de los documentos; las etapas sin datos siguen sin confirmar.</p></details></section>`;
  }
  function checkDates(check) {
    const fmt={hour:"2-digit",minute:"2-digit"};
    const deferred=['skipped','budget_deferred','deferred'].includes(check.work_status||check.status);
    return `${check.queued_at?`<p>En cola desde: ${E(BA.date(check.queued_at,fmt))}</p>`:''}${check.attempted_at?`<p>Último intento: ${E(BA.date(check.attempted_at,fmt))}</p>`:!deferred&&check.checked_at?`<p>Comprobación registrada: ${E(BA.date(check.checked_at,fmt))}</p>`:''}${check.checked_at&&check.attempted_at?`<p>Última comprobación: ${E(BA.date(check.checked_at,fmt))}</p>`:deferred&&check.checked_at?`<p>Comprobación anterior: ${E(BA.date(check.checked_at,fmt))}</p>`:''}${check.downloaded_at?`<p>Última descarga: ${E(BA.date(check.downloaded_at,fmt))}</p>`:''}${deferred?'<p>Trabajo pendiente por presupuesto; no hubo un nuevo intento de descarga.</p>':''}`;
  }
  function positionCheck(m) {
    const p=m.state.position_status;
    if(!p||typeof p!=='object')return '';
    const label={verified:'Comprobación verificada',failed:'Comprobación fallida',pending_budget:'Pausada por presupuesto',degraded:'Evidencia revisada conservada'}[p.status]||'Comprobación pendiente';
    const dates=[['Último intento',p.attempted_at],['Última comprobación satisfactoria',p.checked_at],['Reanudar a partir de',p.resume_after]].filter(([key,value])=>value||key==='Última comprobación satisfactoria');
    const counts=[Number.isInteger(p.record_count)?`${p.record_count.toLocaleString('es')} registros declarados en la comprobación`:null,Number.isInteger(p.verified_documents)?`${p.verified_documents} documentos verificados`:null,Number.isInteger(p.pending_documents)?`${p.pending_documents} documentos pendientes`:null].filter(Boolean);
    const originCounts=[['origin_verified_documents','documento comprobado en origen','documentos comprobados en origen'],['origin_failed_documents','documento con fallo de origen','documentos con fallo de origen'],['cached_documents','documento servido desde evidencia conservada','documentos servidos desde evidencia conservada']].filter(([key])=>Number.isInteger(p[key])).map(([key,single,plural])=>U.count(p[key],single,plural));
    const officialCheck=p.origin_check_complete===true?'La comprobación oficial registrada está completa.':p.origin_check_complete===false?(p.origin_verified_documents>0?'La última comprobación oficial fue parcial.':p.origin_failed_documents>0?'La última comprobación oficial falló.':'La última comprobación oficial está incompleta.'):'El resultado de la última comprobación oficial no está consignado.';
    const notice=p.status==='degraded'?`${officialCheck} La generación activa puede incorporar evidencia revisada conservada tras el fallo de acceso al origen; servir esa generación no acredita una nueva comprobación oficial completa.`:p.status==='verified'?'La comprobación registrada no acredita disponibilidad actual ni cobertura completa del corpus.':`${p.status==='pending_budget'?'La comprobación está pausada al alcanzar el presupuesto de escritura.':'No se ha completado la comprobación de estas publicaciones.'} ${p.active_version?'Se conserva la generación activa y su evidencia fechada en las consultas.':'No se acredita una generación activa en estos metadatos.'}`;
    const cacheLabel={unconfigured:'No configurada',ready:'Disponible',failed:'Con fallo'}[p.cache_status];
    return `<section class="panel section" data-position-check><div class="act-top"><h2>Comprobación de listas y adjudicaciones</h2><span class="pill ${p.status==='verified'?'observed':'pending'}">${E(label)}</span></div><p>${E(notice)}</p><dl class="freshness-grid">${dates.map(([key,value])=>`<div><dt>${key}</dt><dd>${E(value?BA.date(value,{hour:'2-digit',minute:'2-digit'}):'Sin fecha acreditada')}</dd></div>`).join('')}</dl>${counts.length?`<p>${E(counts.join(' · '))}.</p>`:''}${originCounts.length?`<p>${E(originCounts.join(' · '))}.</p>`:''}${p.active_version||p.staged_version||p.error_code||cacheLabel?`<details class="technical-details"><summary>Estado de las generaciones</summary><dl>${p.active_version?`<dt>Generación activa</dt><dd class="hash">${E(p.active_version)}</dd>`:''}${p.staged_version?`<dt>Generación preparada, pendiente de activar</dt><dd class="hash">${E(p.staged_version)}</dd>`:''}${cacheLabel?`<dt>Conservación de evidencia</dt><dd>${cacheLabel}</dd>`:''}${p.error_code?`<dt>Motivo registrado</dt><dd><code>${E(p.error_code)}</code></dd>`:''}</dl></details>`:''}</section>`;
  }
  function sources(m) {
    const cat = m.state.catalog,
      checks = m.state.checks || cat.checks || [],
      pending = cat.notices.filter((n) =>
        BA.isPendingNotice(n, m.state.documents, m.state.history_documents),
      );
    return (
      header("Fuentes", refreshButton(m)) +
      refreshFeedback(m) +
      historyNotice(m) +
      `<section class="panel section source-overview"><div class="act-top"><h2>Comprobaciones</h2></div>${freshness(m)}<p><strong>${U.count(pending.length, "publicación pendiente", "publicaciones pendientes")}.</strong> Los documentos sin validar no sustituyen al último listado válido.</p></section>` +
      positionCheck(m) +
      inventoryCoverage(m) +
      U.notice(
        "Alcance de esta vista: vacantes sin cubrir de Secundaria y otros cuerpos",
        `${canCheck(m) ? "Consulta del RSS, índice y anuncios de RRHH." : "Recargar datos consulta la última copia publicada. La comprobación a petición no está conectada."} Convocatorias, resultados e incidencias: cobertura incompleta.`,
        "neutral",
      ) +
      `<section class="section"><div class="section-head"><div><h2>Documentos y procedencia</h2></div><span class="count">${m.state.documents.length}</span></div><div class="document-grid">${m.state.documents.map((d) => `<article class="panel document-card"><div class="act-top"><h3>${E(BA.date(d.published_at))}</h3><span class="pill ${d.status === "pending" ? "pending" : "observed"}">${E({ approved: "Incorporada", pending: "En revisión", superseded: "Sustituida" }[d.status] || d.status)}</span></div><div class="document-counts"><strong>${E(d.places)} plazas</strong><span>${E(d.row_count)} registros</span></div><p>${E(U.provenance(d))}</p><div class="buttons mt13">${U.pdfLink(d)}${U.external(d.source_url, "Origen oficial")}</div><details class="technical-details"><summary>Huella del documento · SHA-256</summary><div class="hash">${E(d.sha256)}</div>${d.warnings.length ? `<p>${E(d.warnings.join(" "))}</p>` : ""}</details></article>`).join("")}</div></section>` +
      `<section class="section"><div class="section-head"><div><h2>Registro de fuentes</h2></div><span class="count">${cat.sources.length}</span></div><div class="data-table-wrap">${cat.sources
        .map((s) => {
          const check = checks
            .filter((c) => c.id === s.id || sameSourceUrl(c.url, s.url))
            .at(-1);
          return `<article class="source-row"><div><h3>${E(s.name || s.id)}</h3><div class="source-role">${E(s.type || s.role || "Referencia oficial")}</div>${check ? `${checkDates(check)}${check.error?`<p>${E(check.error)}</p>`:""}` : "<p>Sin comprobación reciente registrada para esta referencia.</p>"}<details class="technical-details"><summary>Observaciones</summary><p>${E(s.id === "aepd-information" ? "Las preferencias se guardan en este navegador." : s.note || "Sin nota adicional.")}</p></details></div><div class="source-status ${check?.success&&!(["skipped","budget_deferred","deferred"].includes(check.work_status||check.status)) ? "ok" : ""}"><span class="dot"></span>${E(check ? statusName(check.work_status||check.status) : "Referencia de auditoría")}</div><div class="source-external">${U.external(s.url, "Abrir", "")}</div></article>`;
        })
        .join("")}</div></section>` +
      (checks.length
        ? `<details class="panel section technical-log"><summary>Trabajo y comprobaciones por recurso <span class="count">${checks.length}</span></summary><ol class="event-list">${checks.map((c) => `<li class="event"><div><strong>${E(statusName(c.work_status||c.status))}</strong>${checkDates(c)}<p>${E(c.error || "")} ${U.external(c.url, "Recurso oficial", "")}</p><code class="resource-id">${E(c.id)}</code></div></li>`).join("")}</ol></details>`
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
  function home(m) {
    const doc = (m.state?.documents || []).find(
      (d) => d.id === m.state?.current_id && d.status === "approved",
    );
    const seen = new Set();
    const sample = (doc?.rows || [])
      .filter((row) => {
        if (seen.has(row.function_code)) return false;
        seen.add(row.function_code);
        return true;
      })
      .slice(0, 3);
    const places = (doc?.rows || []).reduce(
      (total, row) => total + row.quantity,
      0,
    );
    return `<div class="landing">
      <header class="landing-header"><a class="brand landing-brand" href="#home" data-view="home" aria-label="Bolsa Abierta · Inicio"><span class="brand-symbol" aria-hidden="true">b.</span><span class="brand-name">Bolsa Abierta</span></a><nav class="landing-nav" aria-label="Navegación principal"><a href="#sources" data-view="sources">Fuentes</a><a href="#position" data-view="position">Mi posición ${U.icon("arrow")}</a></nav></header>
      <main id="main" class="landing-main" tabindex="-1">
        <section class="landing-hero" aria-labelledby="landing-title"><div class="landing-intro"><p class="landing-eyebrow">Listas docentes y adjudicaciones publicadas</p><h1 id="landing-title">Consulta tu puesto en las listas docentes de Murcia.</h1><p class="landing-lead">Busca tu ficha en las publicaciones incorporadas y consulta su ordinal oficial o su adjudicación fechada. La cobertura es parcial y la disponibilidad actual no está confirmada.</p><a class="button primary landing-cta" href="#position" data-view="position">Consultar mi posición ${U.icon("arrow")}</a><p class="landing-access">Gratis y sin registro.</p></div>
        <aside class="landing-publication" aria-label="Última publicación incorporada"><div class="landing-publication-head"><span>Último listado incorporado</span>${U.icon("calendar")}</div>${doc ? `<h2>${E(BA.date(doc.published_at))}</h2><p class="landing-scope">Vacantes sin cubrir</p><ul class="landing-sample">${sample.map((row) => `<li><strong>${E(BA.title(row.function))}</strong><span>${E(BA.title(row.municipality))} · ${row.workload === "full" ? "Jornada completa" : E(row.hours) + " h"}</span></li>`).join("")}</ul><button class="landing-publication-link" data-action="open-copy" data-id="${E(doc.id)}">Ver ${U.count(places, "plaza", "plazas")}${U.icon("arrow")}</button><p class="landing-availability">La publicación no confirma la disponibilidad actual.</p>` : `<h2>Consulta de publicaciones</h2><p class="landing-scope">Todavía no hay un listado validado disponible.</p><a class="landing-publication-link" href="#sources" data-view="sources">Ver fuentes ${U.icon("arrow")}</a>`}</aside></section>
        <section class="landing-uses" aria-label="Qué puedes hacer"><article><span class="landing-step" aria-hidden="true">01</span><h2>Encuentra tu ficha</h2><p>Busca por nombre o número de lista y filtra por lista o función.</p><a href="#position" data-view="position">Consultar mi posición ${U.icon("arrow")}</a></article><article><span class="landing-step" aria-hidden="true">02</span><h2>Compara los listados</h2><p>Consulta qué registros aparecen, dejan de figurar o cambian entre publicaciones, sin inferir adjudicaciones o revocaciones.</p><a href="#changes" data-view="changes">Ver cambios ${U.icon("arrow")}</a></article><article><span class="landing-step" aria-hidden="true">03</span><h2>Consulta las vacantes</h2><p>Busca las plazas por especialidad, municipio y jornada.</p><a href="#vacancies" data-view="vacancies">Buscar vacantes ${U.icon("arrow")}</a></article></section>
        <section class="landing-origin" aria-labelledby="landing-origin-title"><div><h2 id="landing-origin-title">El origen de los datos</h2><p>Los datos proceden de RRHH Educación y CARM. Puedes consultar la fecha de cada publicación y abrir su fuente.</p></div><a href="#sources" data-view="sources">Consultar fuentes ${U.icon("arrow")}</a></section>
      </main><footer class="landing-footer"><p>Bolsa Abierta es un proyecto independiente de la CARM. Las solicitudes y adjudicaciones se tramitan por los canales oficiales.</p><button data-action="about">Sobre el proyecto</button></footer></div>`;
  }
  function position() {
    return '<div class="position-workspace"><header class="position-heading"><h1>Mi posición</h1></header><div id="position-root"></div></div>';
  }
  const views = { position, vacancies, changes, acts, profile, sources };
  function shell(m) {
    if (m.view === "home") return home(m);
    const nav = [
      ["position", "Mi posición", "person"],
      ["vacancies", "Vacantes", "grid"],
      ["changes", "Cambios", "changes"],
      ["acts", "Actos", "calendar"],
      ["profile", "Mi seguimiento", "bookmark"],
      ["sources", "Fuentes", "shield"],
    ];
    const navItem=([id,name,ico])=>`<button class="nav-button ${m.view===id?'active':''}" data-view="${id}" ${m.view===id?'aria-current="page"':''}>${U.icon(ico)}<span>${name}</span></button>`;
    const secondary=nav.slice(2), selected=secondary.find(([id])=>id===m.view);
    const more=`<details class="mobile-more"><summary class="nav-button ${selected?'active':''}"><span aria-hidden="true">☰</span><span>Más</span></summary><div class="mobile-more-panel">${secondary.map(navItem).join('')}<button class="nav-button" data-action="about">${U.icon('info')}<span>Sobre el proyecto</span></button></div></details>`;
    return `<div class="shell"><aside class="sidebar" id="site-nav"><a class="brand brand-home" href="#home" data-view="home" aria-label="Bolsa Abierta · Inicio"><span class="brand-symbol" aria-hidden="true">b.</span><span><span class="brand-name">Bolsa Abierta</span><span class="brand-subtitle">Región de Murcia</span></span></a><nav class="nav" aria-label="Navegación principal">${nav.map(navItem).join('')}${more}</nav><div class="sidebar-bottom"><button class="about" data-action="about">${U.icon("code")}Sobre el proyecto</button></div></aside><div class="content"><main id="main" class="main" tabindex="-1">${m.state || m.view === "position" ? views[m.view](m) : '<p role="status">No se han podido cargar las publicaciones. <a href="#position" data-view="position">Consultar mi posición</a></p>'}</main></div></div>`;
  }
  window.BAV = { current, allRows, displayed, shell, results };
})();
