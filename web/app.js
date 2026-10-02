/* Bolsa Abierta — controller. No analytics, remote assets or personal credentials. */
(function () {
  "use strict";
  const E = BA.escape,
    U = BAUI,
    V = BAV,
    KEY = "bolsa-abierta:v1:preferences";
  const app = document.getElementById("app"),
    dialog = document.getElementById("detail-dialog");
  const model = {
    state: null,
    prefs: { favorites: [], functions: [], lastSeen: null },
    view: "vacancies",
    filters: {},
    selectedDoc: null,
    page: 1,
    pageSize: 25,
    sortBy: "original",
    sortDirection: "asc",
    density: "compact",
    changePage: 1,
    changeKind: "",
    onlySaved: false,
    onlyProfile: false,
  };
  let toastTimer,
    activeDetail = null,
    dialogOrigin = null;
  model.storageAvailable = true;
  function toast(message) {
    const box = document.getElementById("toast");
    box.textContent = message;
    box.classList.add("visible");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => box.classList.remove("visible"), 4500);
  }
  function save() {
    try {
      localStorage.setItem(KEY, JSON.stringify(model.prefs));
      model.storageAvailable = true;
      return true;
    } catch {
      model.storageAvailable = false;
      return false;
    }
  }
  function render() {
    app.innerHTML = V.shell(model);
  }
  function renderResults() {
    const target = document.getElementById("results"),
      active = document.activeElement;
    const restore = target?.contains(active)
      ? {
          id: active.id,
          action: active.dataset.action,
          row: active.dataset.id,
          density: active.dataset.density,
          page: active.dataset.page,
        }
      : null;
    if (target) {
      target.innerHTML = V.results(model);
      target.classList.toggle("comfortable", model.density === "comfortable");
      target.classList.toggle("compact", model.density !== "comfortable");
    }
    if (restore) {
      const focus = restore.id
        ? document.getElementById(restore.id)
        : Array.from(target.querySelectorAll("[data-action]")).find(
            (el) =>
              el.dataset.action === restore.action &&
              el.dataset.id === restore.row &&
              el.dataset.density === restore.density &&
              el.dataset.page === restore.page,
          );
      (focus && !focus.disabled
        ? focus
        : document.getElementById("result-count")
      )?.focus({ preventScroll: true });
    }
    const count = document
      .getElementById("only-saved")
      ?.closest("label")
      ?.querySelector(".muted");
    if (count)
      count.textContent =
        "(" +
        V.allRows(model).filter((r) => model.prefs.favorites.includes(r.id))
          .length +
        ")";
  }
  function navigate(view) {
    model.view = view;
    render();
    document.getElementById("main")?.focus({ preventScroll: true });
    window.scrollTo({ top: 0 });
    try {
      history.replaceState(null, "", "#" + view);
    } catch {}
  }
  function show(content) {
    if (!dialog.open) {
      const el = document.activeElement;
      dialogOrigin = el
        ? { element: el, action: el.dataset?.action, id: el.dataset?.id }
        : null;
    }
    dialog.innerHTML = content;
    if (!dialog.open) dialog.showModal();
  }
  function close() {
    dialog.close();
    activeDetail = null;
  }
  function findRow(id) {
    for (const doc of model.state.documents) {
      const row = doc.rows.find((r) => r.id === id);
      if (row) return { row, doc };
    }
    return null;
  }
  function detail(id) {
    const match = findRow(id);
    if (!match) return;
    activeDetail = id;
    show(U.detail(match.row, match.doc, model.prefs));
  }
  function favorite(id) {
    if (!findRow(id)) return;
    const index = model.prefs.favorites.indexOf(id);
    if (index < 0) model.prefs.favorites.push(id);
    else model.prefs.favorites.splice(index, 1);
    const persisted = save();
    renderResults();
    if (activeDetail) {
      const refocus = document.activeElement?.dataset?.action === "favorite";
      detail(activeDetail);
      if (refocus)
        dialog
          .querySelector('[data-action="favorite"]')
          ?.focus({ preventScroll: true });
    }
    toast(
      index < 0
        ? persisted
          ? "Registro guardado."
          : "Guardado solo durante esta sesión: almacenamiento local no disponible."
        : "Registro eliminado de guardadas.",
    );
  }
  function download(content, name, type) {
    const blob = new Blob([content], { type });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 3000);
  }
  async function reload(snapshotOnly = false, requireAPI = false) {
    const state = await BA.loadState(
      fetch,
      window.BA_CONFIG || {},
      snapshotOnly,
    );
    if (requireAPI && state.mode !== "server")
      throw Error(
        "No se pudo leer el resultado del servicio. Se conserva la copia anterior.",
      );
    const previous = model.selectedDoc,
      wasLatest = previous === model.state?.current_id;
    model.state = state;
    if (
      wasLatest ||
      !state.documents.some((d) => d.id === previous && d.status === "approved")
    )
      model.selectedDoc = state.current_id;
    model.filters = BA.normalizeFilters(
      model.filters,
      model.onlySaved ? V.allRows(model) : V.current(model)?.rows || [],
    );
  }
  function busy(button, label) {
    if (!button) return;
    button.disabled = true;
    button.innerHTML =
      '<span class="spinner" aria-hidden="true"></span>' + E(label);
  }
  function dialogHeader(title, subtitle = "") {
    return `<div class="dialog-head"><div><h2 id="dialog-title">${E(title)}</h2>${subtitle ? `<p>${E(subtitle)}</p>` : ""}</div><button class="icon-button" data-action="close-dialog" aria-label="Cerrar">${U.icon("close")}</button></div>`;
  }
  async function sync(button) {
    if (model.refreshing) return;
    model.refreshing = true;
    model.refreshMessage = "Buscando…";
    busy(button, "Buscando…");
    render();
    try {
      if (
        model.state.mode !== "server" ||
        model.state.capabilities?.source_check !== "available"
      ) {
        await reload(true);
        toast(
          "Copia publicada consultada. No se han comprobado las fuentes oficiales.",
        );
      } else {
        const result = await BA.refreshSource(
          fetch,
          window.BA_CONFIG || {},
          (job) => {
            model.refreshMessage =
              job.message ||
              {
                queued: "Esperando comprobación…",
                running: "Buscando publicaciones, descargando y validando…",
              }[job.status] ||
              "Leyendo resultado…";
            const status = document.getElementById("refresh-status");
            if (status) status.textContent = model.refreshMessage;
          },
        );
        await reload(false, true);
        toast(
          result.status === "failed"
            ? "Comprobación fallida. Se conservan las copias válidas."
            : result.status === "partial"
              ? "Comprobación parcial. Revisa los intentos y documentos sin incorporar."
              : "Comprobación completada dentro del alcance. Revisa las publicaciones detectadas.",
        );
      }
    } catch (err) {
      toast(err.message);
    } finally {
      model.refreshing = false;
      model.refreshMessage = "";
      render();
    }
  }
  function about() {
    activeDetail = null;
    show(
      dialogHeader("Bolsa Abierta") +
        `<div class="dialog-body"><h3>Vacantes docentes de la Región de Murcia</h3><p>Listados de Secundaria y otros cuerpos. Las fechas y documentos originales están en Fuentes.</p><h3 class="mt18">Privacidad</h3><p>Las preferencias se guardan en este navegador. Sin cuentas, analítica ni cookies de seguimiento.</p><h3 class="mt18">Licencia</h3><p>Código bajo GNU AGPLv3. Los documentos oficiales conservan su propia procedencia y condiciones de uso.</p></div><div class="dialog-footer"><div class="buttons">${U.external("https://github.com/carlosmartinezfyd/bolsa-abierta", "Código fuente")}${U.external("https://www.gnu.org/licenses/agpl-3.0.html", "AGPLv3")}</div>${U.button("close-dialog", "Cerrar")}</div>`,
    );
  }
  function clearFilters() {
    model.filters = {};
    model.onlyProfile = false;
    model.onlySaved = false;
    model.page = 1;
    render();
    document.getElementById("search")?.focus({ preventScroll: true });
  }

  document.addEventListener("click", (event) => {
    const nav = event.target.closest("[data-view]");
    if (nav) {
      navigate(nav.dataset.view);
      return;
    }
    const button = event.target.closest("[data-action]");
    if (!button || button.disabled) return;
    const action = button.dataset.action;
    if (action === "show-results") {
      document.getElementById("results")?.scrollIntoView({ block: "start" });
      document.getElementById("result-count")?.focus({ preventScroll: true });
    } else if (action === "detail") detail(button.dataset.id);
    else if (action === "favorite") favorite(button.dataset.id);
    else if (action === "close-dialog") close();
    else if (action === "clear-filters") clearFilters();
    else if (action === "remove-filter") {
      delete model.filters[button.dataset.key];
      model.page = 1;
      render();
      document.getElementById("search")?.focus({ preventScroll: true });
    } else if (action === "sort-direction") {
      model.sortDirection = model.sortDirection === "asc" ? "desc" : "asc";
      model.page = 1;
      renderResults();
    } else if (action === "density") {
      model.density =
        button.dataset.density === "comfortable" ? "comfortable" : "compact";
      renderResults();
    } else if (action === "page") {
      model.page = Number(button.dataset.page);
      renderResults();
      document.getElementById("results")?.scrollIntoView({ block: "start" });
    } else if (action === "change-page") {
      model.changePage = Number(button.dataset.page);
      render();
      window.scrollTo({ top: 0 });
    } else if (action === "change-kind") {
      model.changeKind = button.dataset.kind;
      model.changePage = 1;
      render();
      Array.from(document.querySelectorAll('[data-action="change-kind"]'))
        .find((el) => el.dataset.kind === model.changeKind)
        ?.focus({ preventScroll: true });
    } else if (action === "export-csv") {
      const doc = V.current(model);
      download(
        BA.csv(
          V.displayed(model).map((row) => {
            const doc = findRow(row.id)?.doc;
            return {
              ...row,
              document_id: doc?.id,
              document_published_at: doc?.published_at,
              document_sha256: doc?.sha256,
              source_url: doc?.source_url,
              artifact_url: doc?.artifact_url,
            };
          }),
        ),
        model.onlySaved
          ? "vacantes-guardadas-por-documento.csv"
          : "vacantes-copia-" +
              (doc?.published_at.slice(0, 10) || "sin-datos") +
              ".csv",
        "text/csv;charset=utf-8",
      );
      toast("CSV exportado.");
    } else if (action === "open-copy") {
      model.selectedDoc = button.dataset.id;
      model.page = 1;
      model.filters = {};
      model.onlySaved = false;
      model.onlyProfile = false;
      navigate("vacancies");
    } else if (action === "apply-profile") {
      if (!model.prefs.functions.length) {
        toast("Selecciona al menos una función.");
        return;
      }
      model.onlyProfile = true;
      model.onlySaved = false;
      model.filters = {};
      model.page = 1;
      navigate("vacancies");
    } else if (action === "view-saved") {
      model.onlySaved = true;
      model.onlyProfile = false;
      model.filters = {};
      model.page = 1;
      navigate("vacancies");
    } else if (action === "export-preferences")
      download(
        JSON.stringify({ version: 1, ...model.prefs }, null, 2),
        "bolsa-abierta-preferencias.json",
        "application/json",
      );
    else if (action === "mark-seen") {
      model.prefs.lastSeen = new Date().toISOString();
      save();
      toast("Revisión guardada.");
    } else if (action === "reset-preferences") {
      show(
        dialogHeader("Borrar preferencias locales") +
          `<div class="dialog-body"><p>Se eliminarán favoritos, funciones seguidas y fecha de revisión de este navegador. No se borrarán documentos ni datos del servidor.</p></div><div class="dialog-footer">${U.button("close-dialog", "Cancelar")}${U.button("confirm-reset", "Borrar preferencias", "", "danger")}</div>`,
      );
    } else if (action === "confirm-reset") {
      model.prefs = BA.preferences(null);
      save();
      model.onlyProfile = false;
      model.onlySaved = false;
      close();
      render();
      toast("Preferencias locales eliminadas.");
    } else if (action === "about") about();
    else if (action === "sync") return sync(button);
  });
  document.addEventListener("input", (event) => {
    const el = event.target;
    if (el.id === "search") {
      model.filters.q = el.value;
      model.page = 1;
      renderResults();
    }
    if (el.id === "profile-search") {
      const words = BA.norm(el.value).split(/\s+/).filter(Boolean);
      let visible = 0;
      document.querySelectorAll("[data-function-search]").forEach((node) => {
        const match = words.every((w) =>
          node.dataset.functionSearch.includes(w),
        );
        node.classList.toggle("hidden", !match);
        if (match) visible++;
      });
      document
        .getElementById("profile-empty")
        ?.classList.toggle("hidden", visible > 0);
    }
  });
  document.addEventListener("change", (event) => {
    const el = event.target;
    if (el.id === "sort-by") {
      model.sortBy = [
        "original",
        "function",
        "municipality",
        "center",
        "quantity",
      ].includes(el.value)
        ? el.value
        : "original";
      model.page = 1;
      renderResults();
    }
    if (el.id === "page-size") {
      model.pageSize = [25, 50, 100].includes(Number(el.value))
        ? Number(el.value)
        : 25;
      model.page = 1;
      renderResults();
      document.getElementById("results")?.scrollIntoView({ block: "start" });
    }
    if (el.dataset.filter) {
      model.filters[el.dataset.filter] = el.value;
      model.page = 1;
      renderResults();
    }
    if (el.id === "copy-select") {
      model.selectedDoc = el.value;
      model.page = 1;
      const before = JSON.stringify(model.filters);
      model.onlySaved = false;
      model.filters = BA.normalizeFilters(
        model.filters,
        V.current(model)?.rows || [],
      );
      render();
      if (before !== JSON.stringify(model.filters))
        toast("Se han quitado los filtros que no existen en esta copia.");
      document.getElementById("copy-select")?.focus();
    }
    if (el.id === "only-saved") {
      model.onlySaved = el.checked;
      model.page = 1;
      model.filters = BA.normalizeFilters(
        model.filters,
        el.checked ? V.allRows(model) : V.current(model)?.rows || [],
      );
      render();
      document.getElementById("only-saved")?.focus();
    }
    if (el.id === "only-profile") {
      model.onlyProfile = el.checked;
      model.page = 1;
      renderResults();
      if (el.checked && !model.prefs.functions.length)
        toast(
          "Todavía no has elegido funciones. Configúralas en Mi seguimiento.",
        );
    }
    if (el.dataset.profileFunction) {
      const code = el.dataset.profileFunction;
      model.prefs.functions = el.checked
        ? [...new Set([...model.prefs.functions, code])]
        : model.prefs.functions.filter((c) => c !== code);
      save();
      const count = document.getElementById("profile-count");
      if (count)
        count.textContent = U.count(
          model.prefs.functions.length,
          "función seleccionada",
          "funciones seleccionadas",
        );
    }
  });
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) {
      const r = dialog.getBoundingClientRect();
      if (
        event.clientX < r.left ||
        event.clientX > r.right ||
        event.clientY < r.top ||
        event.clientY > r.bottom
      )
        close();
    }
  });
  dialog.addEventListener("cancel", () => {
    activeDetail = null;
  });
  dialog.addEventListener("close", () => {
    const origin = dialogOrigin;
    dialogOrigin = null;
    if (!origin) return;
    const target = origin.element.isConnected
      ? origin.element
      : Array.from(document.querySelectorAll("[data-action]")).find(
          (el) =>
            el.dataset.action === origin.action && el.dataset.id === origin.id,
        );
    (
      target ||
      document.getElementById("result-count") ||
      document.getElementById("main")
    )?.focus({ preventScroll: true });
  });
  window.addEventListener("hashchange", () => {
    const view = location.hash.slice(1);
    if (["vacancies", "changes", "acts", "profile", "sources"].includes(view)) {
      model.view = view;
      render();
      document.getElementById("main")?.focus({ preventScroll: true });
    }
  });
  (async () => {
    try {
      try {
        model.prefs = BA.preferences(localStorage.getItem(KEY));
      } catch {
        model.storageAvailable = false;
      }
      model.view = [
        "vacancies",
        "changes",
        "acts",
        "profile",
        "sources",
      ].includes(location.hash.slice(1))
        ? location.hash.slice(1)
        : "vacancies";
      await reload();
      render();
    } catch (err) {
      app.innerHTML = `<div class="loading"><span class="brand-symbol">b.</span><h1>No se pudo cargar la consulta</h1><p>${E(err.message)}</p><p>No se ha podido leer el servicio ni la copia publicada. Vuelve a cargar la página cuando esté disponible la conexión.</p></div>`;
    }
  })();
})();
