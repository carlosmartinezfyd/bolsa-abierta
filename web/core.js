/* Bolsa Abierta — shared pure helpers. SPDX-License-Identifier: AGPL-3.0-only */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.BA = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";
  const norm = (s) =>
    String(s ?? "")
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase();
  const escape = (s) =>
    String(s ?? "").replace(
      /[&<>"']/g,
      (c) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[c],
    );
  function filter(rows, f = {}) {
    const words = norm(f.q || "")
      .trim()
      .split(/\s+/)
      .filter(Boolean);
    return rows.filter((r) => {
      const text = norm(
        [
          "center_code",
          "center",
          "municipality",
          "function_code",
          "function",
          "body",
          "language",
        ]
          .map((k) => r[k] || "")
          .join(" "),
      );
      return (
        words.every((w) => text.includes(w)) &&
        [
          "function_code",
          "body_code",
          "municipality",
          "workload",
          "language",
          "cupo",
          "itinerant",
        ].every((k) => !f[k] || String(r[k]) === String(f[k]))
      );
    });
  }
  const places = (rows) =>
    rows.reduce((n, r) => n + Number(r.quantity || 0), 0);
  function sortRows(rows, key = "original", direction = "asc") {
    if (!["function", "municipality", "center", "quantity"].includes(key))
      return rows.slice();
    const order = direction === "desc" ? -1 : 1;
    const collator = new Intl.Collator("es", {
      sensitivity: "base",
      numeric: true,
    });
    return rows
      .slice()
      .sort(
        (a, b) =>
          order *
          (key === "quantity"
            ? Number(a.quantity) - Number(b.quantity)
            : collator.compare(a[key] || "", b[key] || "")),
      );
  }
  function csv(rows) {
    const fields = [
      ["center_code", "Código centro"],
      ["center", "Centro"],
      ["municipality", "Municipio"],
      ["function_code", "Código función"],
      ["function", "Función"],
      ["cupo", "Cupo"],
      ["itinerant", "Itinerancia"],
      ["jornada", "Jornada"],
      ["quantity", "Plazas"],
      ["page", "Página"],
      ["row_number", "Fila"],
      ["id", "ID registro"],
      ["document_id", "Documento"],
      ["document_published_at", "Fecha del documento"],
      ["document_sha256", "SHA-256"],
      ["source_url", "Origen"],
      ["artifact_url", "Copia conservada"],
    ];
    const safe = (v) => {
      let s = String(v ?? "");
      if (/^[\s]*[=+\-@\t\r\n]/.test(s)) s = "'" + s;
      return '"' + s.replace(/"/g, '""') + '"';
    };
    return (
      "\ufeff" +
      [
        fields.map((x) => safe(x[1])).join(";"),
        ...rows.map((r) => fields.map((x) => safe(r[x[0]])).join(";")),
      ].join("\r\n")
    );
  }
  function preferences(value) {
    const base = { favorites: [], functions: [], lastSeen: null };
    try {
      const v = typeof value === "string" ? JSON.parse(value) : value;
      if (!v || typeof v !== "object") return base;
      base.favorites = Array.isArray(v.favorites)
        ? [
            ...new Set(
              v.favorites.filter(
                (x) =>
                  typeof x === "string" && /^[a-f0-9]{64}:\d+:\d+$/.test(x),
              ),
            ),
          ].slice(0, 3000)
        : [];
      base.functions = Array.isArray(v.functions)
        ? [
            ...new Set(
              v.functions.filter(
                (x) => typeof x === "string" && /^0\d{3}[A-Z0-9]\d{2}$/.test(x),
              ),
            ),
          ].slice(0, 500)
        : [];
      base.lastSeen =
        typeof v.lastSeen === "string" && /^\d{4}-\d{2}-\d{2}/.test(v.lastSeen)
          ? v.lastSeen
          : null;
      return base;
    } catch {
      return base;
    }
  }
  function isPendingNotice(notice, docs, history = []) {
    if (!notice || notice.kind !== "vacancies") return false;
    if (
      [
        "fetch_failed",
        "extraction_failed",
        "detected_not_read",
        "pending",
      ].includes(notice.status)
    )
      return true;
    return (
      !notice.document_id ||
      ![...docs, ...(Array.isArray(history) ? history : [])].some(
        (d) =>
          ["approved", "superseded"].includes(d.status) &&
          d.id === notice.document_id,
      )
    );
  }
  function normalizeFilters(filters, rows) {
    const result = {};
    if (filters.q) result.q = filters.q;
    for (const key of [
      "function_code",
      "body_code",
      "municipality",
      "workload",
      "language",
      "cupo",
      "itinerant",
    ])
      if (
        filters[key] &&
        rows.some((r) => String(r[key]) === String(filters[key]))
      )
        result[key] = filters[key];
    return result;
  }
  function savedGroups(documents, favorites, filters = {}) {
    const ids = new Set(favorites);
    return documents
      .filter((d) => ["approved", "superseded"].includes(d.status))
      .map((document) => ({
        document,
        rows: filter(document.rows, filters).filter((r) => ids.has(r.id)),
      }))
      .filter((g) => g.rows.length);
  }
  function safeURL(value) {
    if (
      typeof value !== "string" ||
      !value ||
      /[\s\\\u0000-\u001f]/.test(value)
    )
      return "";
    try {
      if (/^https:\/\//.test(value)) {
        const u = new URL(value);
        return u.protocol === "https:" && !u.username && !u.password
          ? value
          : "";
      }
      const path = decodeURIComponent(value);
      if (
        path.includes("..") ||
        path.includes("\\") ||
        path.includes("//") ||
        path.includes(":") ||
        !/^\/?(?:api\/)?documents\/[a-zA-Z0-9._-]+\.pdf$/.test(path)
      )
        return "";
      return value;
    } catch {
      return "";
    }
  }
  function composeAPIURL(path, config = {}) {
    if (
      !/^(?:state|refresh(?:\/[a-zA-Z0-9_-]+)?|documents\/[a-zA-Z0-9._-]+\.pdf)$/.test(
        path,
      )
    )
      throw Error("Ruta de API no válida.");
    const base = config.apiBase || "";
    if (!base) return "api/" + path;
    const safe = safeURL(base);
    if (!safe) throw Error("La dirección de API debe usar HTTPS.");
    const url = new URL(safe);
    if (url.search || url.hash)
      throw Error("La dirección de API no admite parámetros.");
    return safe.replace(/\/+$/, "") + "/api/" + path;
  }
  function validateState(value) {
    if (
      !value ||
      !Array.isArray(value.documents) ||
      !value.catalog ||
      typeof value.catalog !== "object"
    )
      throw Error("La copia publicada no tiene un formato válido.");
    for (const d of value.documents) {
      if (
        typeof d.id !== "string" ||
        !Array.isArray(d.rows) ||
        !Array.isArray(d.warnings)
      )
        throw Error("Documento no válido.");
      for (const r of d.rows)
        if (
          typeof r.id !== "string" ||
          !Number.isInteger(r.quantity) ||
          r.quantity < 0 ||
          !Number.isInteger(r.page) ||
          !Number.isInteger(r.row_number)
        )
          throw Error("Fila no válida.");
    }
    return {
      ...value,
      events: Array.isArray(value.events) ? value.events : [],
      changes: Array.isArray(value.changes) ? value.changes : [],
      catalog: {
        ...value.catalog,
        sources: Array.isArray(value.catalog.sources)
          ? value.catalog.sources
          : [],
        notices: Array.isArray(value.catalog.notices)
          ? value.catalog.notices
          : value.catalog.latest_notice
            ? [
                {
                  ...value.catalog.latest_notice,
                  kind: value.catalog.latest_notice.kind || "vacancies",
                },
              ]
            : [],
      },
    };
  }
  async function readJSON(fetcher, url, options = {}) {
    const res = await fetcher(url, {
      cache: "no-store",
      signal: AbortSignal.timeout(20000),
      ...options,
    });
    let data;
    try {
      data = await res.json();
    } catch {
      throw Error("Respuesta no válida (" + res.status + ").");
    }
    if (!res.ok)
      throw Error(
        typeof data.detail === "string"
          ? data.detail
          : "No se pudo completar la consulta (" + res.status + ").",
      );
    return data;
  }
  async function loadState(fetcher, config = {}, snapshotOnly = false) {
    if (!snapshotOnly) {
      try {
        const state = validateState(
          await readJSON(fetcher, composeAPIURL("state", config)),
        );
        if (
          state.mode !== "server" ||
          state.capabilities?.source_check !== "available"
        )
          throw Error("API no disponible.");
        return state;
      } catch {}
    }
    const state = validateState(await readJSON(fetcher, "data/state.json"));
    return {
      ...state,
      mode: "static",
      capabilities: { ...state.capabilities, source_check: "snapshot_only" },
    };
  }
  async function refreshSource(
    fetcher,
    config = {},
    progress = () => {},
    wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
    timing = {},
  ) {
    const now = timing.now || (() => Date.now()),
      timeoutMs = timing.timeoutMs || 20 * 60 * 1000,
      intervalMs = timing.intervalMs || 10000,
      deadline = now() + timeoutMs;
    const pending = () =>
      Object.assign(
        Error(
          "La comprobación sigue pendiente; vuelve a cargar la página más tarde para consultar el resultado.",
        ),
        { code: "refresh_pending" },
      );
    let job = await readJSON(fetcher, composeAPIURL("refresh", config), {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-BA-Refresh": "1" },
      body: "{}",
    });
    while (true) {
      if (
        !job ||
        typeof job.id !== "string" ||
        !/^[a-zA-Z0-9_-]+$/.test(job.id) ||
        !["queued", "running", "completed", "partial", "failed"].includes(
          job.status,
        )
      )
        throw Error("Estado de comprobación no válido.");
      progress(job);
      if (["completed", "partial", "failed"].includes(job.status)) return job;
      if (now() >= deadline) throw pending();
      await wait(Math.min(intervalMs, deadline - now()));
      if (now() >= deadline) throw pending();
      try {
        job = await readJSON(
          fetcher,
          composeAPIURL("refresh/" + job.id, config),
          {
            signal: AbortSignal.timeout(
              Math.max(1, Math.min(20000, deadline - now())),
            ),
          },
        );
      } catch (error) {
        if (now() >= deadline) throw pending();
        throw error;
      }
    }
  }
  const date = (s, options = {}) => {
    const d = new Date(
      typeof s === "string" && s.length === 10 ? s + "T12:00:00" : s,
    );
    return s && !Number.isNaN(d.getTime())
      ? new Intl.DateTimeFormat("es-ES", {
          day: "numeric",
          month: "short",
          year: "numeric",
          timeZone: "Europe/Madrid",
          ...options,
        }).format(d)
      : "Sin fecha";
  };
  const title = (s) =>
    String(s ?? "")
      .toLocaleLowerCase("es")
      .replace(/(^|[\s/(])\p{L}/gu, (m) => m.toLocaleUpperCase("es"))
      .replace(/\bIes\b/g, "IES")
      .replace(/\bEoi\b/g, "EOI")
      .replace(/\bCifppu\b/g, "CIFP")
      .replace(/\bCpeibas\b/g, "CPEIBas");
  function unique(rows, key, label = key) {
    return [...new Map(rows.map((r) => [r[key], r[label]])).entries()].sort(
      (a, b) => String(a[1]).localeCompare(String(b[1]), "es"),
    );
  }
  return {
    norm,
    escape,
    filter,
    sortRows,
    places,
    csv,
    preferences,
    isPendingNotice,
    normalizeFilters,
    savedGroups,
    safeURL,
    composeAPIURL,
    validateState,
    loadState,
    refreshSource,
    date,
    title,
    unique,
  };
});
