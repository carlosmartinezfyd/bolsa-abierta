const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const BA = require("../web/core.js");
const context = { BA, window: {}, URL };
vm.createContext(context);
vm.runInContext(
  fs.readFileSync(require.resolve("../web/ui.js"), "utf8"),
  context,
);
const U = context.window.BAUI;

test("archived bytes do not imply an official download", () => {
  assert.equal(
    U.provenance({
      evidence_status: "archived",
      provenance: "official_download",
    }),
    "PDF descargado de la fuente oficial.",
  );
  assert.equal(
    U.provenance({
      evidence_status: "archived",
      provenance: "third_party_reproduction",
    }),
    "Reproducción de terceros.",
  );
  assert.equal(
    U.provenance({ evidence_status: "archived", provenance: "local_copy" }),
    "Copia local del documento.",
  );
  assert.equal(
    U.provenance({
      evidence_status: "original_unavailable",
      provenance: "third_party_reproduction",
    }),
    "Histórico sin PDF original para contrastar.",
  );
});
context.BAUI = U;
vm.runInContext(
  fs.readFileSync(require.resolve("../web/views.js"), "utf8"),
  context,
);
const doc = (id, date, rows) => ({
  id,
  sha256: id,
  status: "approved",
  published_at: date,
  rows,
  warnings: [],
});
const row = (id, code = "A") => ({
  id,
  function_code: code,
  body_code: "0590",
  municipality: "Murcia",
  workload: "full",
  language: "No",
  cupo: "VP",
  itinerant: "N",
  quantity: 1,
});

test("sorting uses Spanish text and numeric quantities without changing source order", () => {
  const rows = [
    { ...row("a"), municipality: "Zaragoza", quantity: 2 },
    { ...row("b"), municipality: "Águilas", quantity: 10 },
    { ...row("c"), municipality: "Murcia", quantity: 1 },
  ];
  assert.deepEqual(
    BA.sortRows(rows, "municipality", "asc").map((r) => r.id),
    ["b", "c", "a"],
  );
  assert.deepEqual(
    BA.sortRows(rows, "quantity", "desc").map((r) => r.id),
    ["b", "a", "c"],
  );
  assert.deepEqual(
    BA.sortRows(rows, "original", "desc").map((r) => r.id),
    ["a", "b", "c"],
  );
  assert.deepEqual(
    BA.sortRows(rows, "unknown").map((r) => r.id),
    ["a", "b", "c"],
  );
  assert.deepEqual(
    rows.map((r) => r.id),
    ["a", "b", "c"],
  );
});

test("equal sort values retain document order in both directions", () => {
  const rows = [row("a"), row("b"), row("c")];
  for (const direction of ["asc", "desc"])
    assert.deepEqual(
      BA.sortRows(rows, "municipality", direction).map((r) => r.id),
      ["a", "b", "c"],
    );
});

test("saved results sort within each publication and pagination keeps that order", () => {
  const m = model();
  m.onlySaved = true;
  m.sortBy = "quantity";
  m.sortDirection = "desc";
  m.pageSize = 25;
  m.state.documents = [
    doc("a", "2026-09-01", [
      { ...row("a:1"), quantity: 1 },
      { ...row("a:2"), quantity: 3 },
    ]),
    doc("b", "2026-09-30", [
      { ...row("b:1"), quantity: 2 },
      { ...row("b:2"), quantity: 4 },
    ]),
  ];
  m.prefs.favorites = ["a:1", "a:2", "b:1", "b:2"];
  assert.deepEqual(
    Array.from(context.window.BAV.displayed(m), (r) => r.id),
    ["a:2", "a:1", "b:2", "b:1"],
  );
  const html = context.window.BAV.results(m);
  assert.ok(html.indexOf('data-id="a:2"') < html.indexOf('data-id="a:1"'));
  assert.ok(html.indexOf('data-id="b:2"') < html.indexOf('data-id="b:1"'));
});

test("changing copy clears only categorical filters missing in the new copy", () => {
  assert.deepEqual(
    BA.normalizeFilters(
      { q: "matemáticas", function_code: "old", cupo: "VS", workload: "full" },
      [row("x")],
    ),
    { q: "matemáticas", workload: "full" },
  );
});
test("saved groups retain matching rows from every document with its own date", () => {
  const docs = [
    doc("a", "2026-09-01", [row("a:1:1")]),
    doc("b", "2026-09-30", [row("b:1:1")]),
  ];
  const groups = BA.savedGroups(docs, ["a:1:1", "b:1:1"]);
  assert.deepEqual(
    groups.map((g) => [g.document.id, g.document.published_at, g.rows.length]),
    [
      ["a", "2026-09-01", 1],
      ["b", "2026-09-30", 1],
    ],
  );
});
test("a reused official URL cannot mark a new revision incorporated", () => {
  assert.equal(
    BA.isPendingNotice(
      {
        kind: "vacancies",
        pdf_url: "https://www.carm.es/a.pdf",
        document_id: "new",
      },
      [
        {
          id: "old",
          status: "approved",
          source_url: "https://www.carm.es/a.pdf",
        },
      ],
    ),
    true,
  );
  assert.equal(
    BA.isPendingNotice({ kind: "vacancies", document_id: "old" }, [
      { id: "old", status: "approved" },
    ]),
    false,
  );
  assert.equal(
    BA.isPendingNotice(
      { kind: "vacancies", pdf_url: "https://www.carm.es/a.pdf" },
      [
        {
          id: "old",
          status: "approved",
          source_url: "https://www.carm.es/a.pdf",
        },
      ],
    ),
    true,
  );
});
test("PDF download uses archived bytes and separate origin when archive missing", () => {
  assert.equal(U.pdfUrl({ source_url: "https://www.carm.es/latest.pdf" }), "");
  assert.match(
    U.pdfLink({ source_url: "https://www.carm.es/latest.pdf" }),
    /Copia no conservada/,
  );
  assert.equal(
    U.pdfUrl({ artifact_url: "documents/a.pdf" }, 3),
    "documents/a.pdf#page=3",
  );
  assert.equal(
    U.pdfUrl({ artifact_url: "/api/documents/a.pdf" }, 2),
    "/api/documents/a.pdf#page=2",
  );
});
test("unsafe link schemes, credentials and path traversal are rejected", () => {
  for (const url of [
    "javascript:alert(1)",
    "data:a",
    "//evil.test/a",
    "../a.pdf",
    "documents/../secret",
    "documents/%2e%2e/a",
    "https://user:pass@example.com/a",
    "documents/a\\b",
  ])
    assert.equal(BA.safeURL(url), "", url);
  assert.equal(
    BA.safeURL("https://www.carm.es/a.pdf"),
    "https://www.carm.es/a.pdf",
  );
  assert.equal(U.pdfUrl({ artifact_url: "javascript:alert(1)" }), "");
});
test("API composition supports relative hosting and configured HTTPS gateway", () => {
  assert.equal(BA.composeAPIURL("state", {}), "api/state");
  assert.equal(
    BA.composeAPIURL("state", { apiBase: "https://gateway.example/base/" }),
    "https://gateway.example/base/api/state",
  );
  for (const apiBase of [
    "http://gateway.example",
    "https://user:pass@example.com",
    "//evil.test",
    "https://gateway.example/?x=1",
  ])
    assert.throws(() => BA.composeAPIURL("state", { apiBase }));
});
test("load state falls back to a static snapshot with honest capabilities", async () => {
  const paths = [];
  const result = await BA.loadState(async (url) => {
    paths.push(url);
    return url === "api/state"
      ? { ok: false }
      : {
          ok: true,
          json: async () => ({
            documents: [],
            catalog: {},
            events: [],
            changes: [],
            mode: "server",
            capabilities: { source_check: "available" },
          }),
        };
  }, {});
  assert.deepEqual(paths, ["api/state", "data/state.json"]);
  assert.equal(result.mode, "static");
  assert.equal(result.capabilities.source_check, "snapshot_only");
});
test("refresh uses bounded job protocol and returns terminal partial status", async () => {
  const calls = [],
    jobs = [
      { id: "job", status: "queued" },
      { id: "job", status: "running" },
      { id: "job", status: "partial" },
    ];
  const result = await BA.refreshSource(
    async (url, options) => {
      calls.push([url, options]);
      return { ok: true, json: async () => jobs.shift() };
    },
    {},
    () => {},
    async () => {},
  );
  assert.equal(result.status, "partial");
  assert.equal(calls[0][0], "api/refresh");
  assert.equal(calls[0][1].body, "{}");
  assert.equal(calls[0][1].headers["X-BA-Refresh"], "1");
  assert.equal(calls[1][0], "api/refresh/job");
});
const seed = JSON.parse(
  fs.readFileSync(require.resolve("../data/seed-state.json"), "utf8"),
);
const model = () => ({
  state: BA.validateState({
    ...seed,
    mode: "static",
    capabilities: { source_check: "snapshot_only" },
    freshness: {
      status: "partial",
      last_attempt_at: "2026-10-01T08:00:00Z",
      last_success_at: "2026-09-30T08:00:00Z",
    },
  }),
  selectedDoc: seed.current_id,
  prefs: { favorites: [], functions: [], lastSeen: null },
  filters: {},
  page: 1,
  view: "sources",
});

test("refresh feedback distinguishes source checks from unchanged published data", () => {
  const before = model().state;
  const same = structuredClone(before);
  assert.match(
    BA.refreshFeedback(before, same, { sourceCheck: false }).message,
    /No hay una copia publicada más reciente/,
  );
  assert.match(
    BA.refreshFeedback(before, same, { sourceCheck: false }).message,
    /Consulta directa.*no disponible/,
  );
  assert.match(
    BA.refreshFeedback(before, same, { sourceCheck: true, status: "completed" })
      .message,
    /Fuentes comprobadas.*sigue siendo/,
  );
  assert.equal(
    BA.refreshFeedback(before, same, { sourceCheck: true, status: "partial" })
      .kind,
    "warning",
  );
  assert.equal(
    BA.refreshFeedback(before, same, { sourceCheck: true, status: "failed" })
      .kind,
    "error",
  );
  const next = {
    ...same,
    current_id: "new",
    documents: [
      { ...same.documents[0], id: "new", published_at: "2026-10-02" },
    ],
  };
  assert.match(
    BA.refreshFeedback(before, next, { sourceCheck: true, status: "completed" })
      .message,
    /Nuevo listado.*2 oct 2026/,
  );
});
test("static sources only offers snapshot refresh and separates successful and attempted checks", () => {
  const html = context.window.BAV.shell(model());
  assert.match(html, /Recargar datos/);
  assert.match(html, /Último intento/);
  assert.match(html, /Última comprobación completa/);
  assert.doesNotMatch(
    html,
    /Importar PDF|servidor local|ZIP|Revisar e incorporar/,
  );
});
test("saved search displays each document group without combining vacancy totals", () => {
  const m = model();
  m.view = "vacancies";
  m.onlySaved = true;
  m.prefs.favorites = seed.documents.map((d) => d.rows[0].id);
  const html = context.window.BAV.results(m);
  for (const d of seed.documents)
    assert.match(html, new RegExp(BA.escape(BA.date(d.published_at))));
  assert.match(html, /Registros guardados por copia/);
  assert.doesNotMatch(html, /plazas<\/strong> en/);
});
async function controller(fetcher, config = {}, hash = "#vacancies") {
  const listeners = {},
    dialogListeners = {},
    windowListeners = {},
    historyEntries = [],
    main = { focused: false, focus() { this.focused = true; } },
    app = { innerHTML: "" },
    toast = { textContent: "", classList: { add() {}, remove() {} } },
    dialog = {
      addEventListener(kind, handler) { dialogListeners[kind] = handler; },
      showModal() { this.open = true; },
      close() { this.open = false; dialogListeners.close?.(); },
      open: false,
    };
  const document = {
    getElementById: (id) =>
      ({ app, toast, main, "detail-dialog": dialog })[id] || null,
    addEventListener: (kind, handler) => {
      listeners[kind] = handler;
    },
  };
  const sandbox = {
    BA,
    BAUI: U,
    BAV: context.window.BAV,
    document,
    fetch: fetcher,
    localStorage: { getItem: () => null, setItem() {} },
    location: { hash },
    history: {
      pushState(_state, _title, url) {
        historyEntries.push(url);
        sandbox.location.hash = url;
      },
    },
    setTimeout: () => 1,
    clearTimeout() {},
    window: {
      BA_CONFIG: config,
      BOOTSTRAP: { documents: [] },
      addEventListener(kind, handler) {
        windowListeners[kind] = handler;
      },
      scrollTo() {},
    },
  };
  vm.createContext(sandbox);
  vm.runInContext(
    fs.readFileSync(require.resolve("../web/app.js"), "utf8"),
    sandbox,
  );
  await new Promise((resolve) => setImmediate(resolve));
  return {
    app,
    document,
    dialog,
    toast,
    listeners,
    historyEntries,
    main,
    skip: () => listeners.click({
      target: { closest: selector => selector === ".skip" ? {} : null },
      preventDefault() {},
    }),
    navigate: (view, modifiers = {}) =>
      listeners.click({
        target: {
          closest: (selector) =>
            selector === "[data-view]" ? { dataset: { view } } : null,
        },
        preventDefault() {},
        ...modifiers,
      }),
    changeHash: (hash) => {
      sandbox.location.hash = hash;
      windowListeners.hashchange();
    },
    click: async () => {
      const button = {
        disabled: false,
        dataset: { action: "sync" },
        innerHTML: "",
      };
      await listeners.click({
        target: {
          closest: (selector) => (selector === "[data-action]" ? button : null),
        },
      });
      await new Promise((resolve) => setImmediate(resolve));
    },
  };
}
test("root entry introduces the project while direct links keep opening the requested workspace", async () => {
  const fetcher = async () => ({ ok: true, json: async () => seed });
  const home = await controller(fetcher, {}, "");
  assert.match(home.app.innerHTML, /Consulta tu puesto en las listas docentes de Murcia/);
  assert.doesNotMatch(home.app.innerHTML, /id="workspace-toolbar"/);
  const direct = await controller(fetcher, {}, "#vacancies");
  assert.match(direct.app.innerHTML, /id="workspace-toolbar"/);
  assert.doesNotMatch(direct.app.innerHTML, /class="landing-hero"/);
});
test("personal position opens directly even when the vacancy snapshot fails", async () => {
  const c = await controller(async () => { throw Error('vacancy service offline'); }, {}, '#position');
  assert.match(c.app.innerHTML, /id="position-root"/);
  assert.doesNotMatch(c.app.innerHTML, /No se pudo cargar la consulta/);
});
test("home links create history and returning to the root restores the introduction", async () => {
  const c = await controller(
    async () => ({ ok: true, json: async () => seed }),
    {},
    "",
  );
  c.navigate("vacancies", { ctrlKey: true });
  assert.deepEqual(c.historyEntries, []);
  c.navigate("vacancies");
  assert.deepEqual(c.historyEntries, ["#vacancies"]);
  assert.match(c.app.innerHTML, /id="workspace-toolbar"/);
  c.changeHash("");
  assert.match(c.app.innerHTML, /class="landing-hero"/);
  c.navigate("sources");
  assert.match(c.app.innerHTML, /Documentos y procedencia/);
  c.navigate("home");
  assert.match(c.app.innerHTML, /class="landing-hero"/);
});
test("skip link focuses the workspace without routing back to the introduction", async () => {
  for (const hash of ["#vacancies", "#sources"]) {
    const c = await controller(async () => ({ ok: true, json: async () => seed }), {}, hash);
    const before = c.app.innerHTML;
    c.skip();
    assert.equal(c.main.focused, true);
    assert.deepEqual(c.historyEntries, []);
    assert.equal(c.app.innerHTML, before);
    assert.doesNotMatch(c.app.innerHTML, /class="landing-hero"/);
  }
});
test("home preview stays tied to the latest approved publication, not a selected historical copy", () => {
  const m = model();
  m.view = "home";
  const latest = m.state.documents.find((d) => d.id === m.state.current_id);
  m.selectedDoc = m.state.documents.find((d) => d.id !== latest.id).id;
  const html = context.window.BAV.shell(m);
  assert.match(
    html,
    new RegExp('data-action="open-copy" data-id="' + latest.id + '"'),
  );
  assert.match(html, new RegExp(BA.escape(BA.date(latest.published_at))));
  assert.match(html, /no confirma la disponibilidad actual/);
  latest.status = "pending";
  const empty = context.window.BAV.shell(m);
  assert.match(empty, /Todavía no hay un listado validado/);
  assert.doesNotMatch(empty, /data-action="open-copy"/);
});
test("controller loads static snapshot and reloads snapshot without origin POST", async () => {
  const calls = [];
  const c = await controller(async (url, options) => {
    calls.push([url, options]);
    return url === "api/state"
      ? { ok: false, status: 404, json: async () => ({}) }
      : { ok: true, json: async () => seed };
  });
  assert.match(c.app.innerHTML, /Vacantes sin cubrir/);
  await c.click();
  assert.deepEqual(
    calls.map((c) => c[0]),
    ["api/state", "data/state.json", "data/state.json"],
  );
  assert.match(c.app.innerHTML, /No hay una copia publicada más reciente/);
  assert.match(c.app.innerHTML, /Consulta directa a las fuentes no disponible/);
});
test("controller keeps prior visible data after refresh transport failure", async () => {
  const state = {
    ...seed,
    mode: "server",
    capabilities: { source_check: "available" },
  };
  const c = await controller(async (url) => {
    if (url === "api/state") return { ok: true, json: async () => state };
    throw Error("Fallo de conexión");
  });
  const before = c.app.innerHTML;
  await c.click();
  const rowsBefore = before.match(/data-id="[^"]+"/g);
  assert.deepEqual(c.app.innerHTML.match(/data-id="[^"]+"/g), rowsBefore);
  assert.match(c.app.innerHTML, /Fallo de conexión/);
  assert.match(c.app.innerHTML, /refresh-feedback error/);
});
test("controller reconnects the configured gateway after an initial static fallback", async () => {
  const calls = [];
  let loads = 0;
  const state = {
    ...seed,
    mode: "server",
    capabilities: { source_check: "available" },
  };
  const c = await controller(
    async (url, options) => {
      calls.push([url, options?.method || "GET"]);
      if (url === "https://gateway.example/api/state" && ++loads === 1)
        return { ok: false, status: 503, json: async () => ({}) };
      return {
        ok: true,
        json: async () =>
          url.endsWith("api/refresh")
            ? { id: "job", status: "completed" }
            : url === "data/state.json"
              ? seed
              : state,
      };
    },
    { apiBase: "https://gateway.example" },
  );
  assert.match(c.app.innerHTML, /Recargar datos/);
  await c.click();
  assert.deepEqual(calls, [
    ["https://gateway.example/api/state", "GET"],
    ["data/state.json", "GET"],
    ["https://gateway.example/api/state", "GET"],
    ["https://gateway.example/api/refresh", "POST"],
    ["https://gateway.example/api/state", "GET"],
  ]);
  assert.match(c.app.innerHTML, /Fuentes comprobadas/);
  assert.match(c.app.innerHTML, /Actualizar/);
});
test("controller still accepts a newer static copy while the configured gateway stays down", async () => {
  let loads = 0;
  const id = "d".repeat(64);
  const updated = {
    ...seed,
    current_id: id,
    documents: [
      {
        ...seed.documents[0],
        id,
        sha256: id,
        published_at: "2026-10-02T12:00:00Z",
        rows: [
          {
            ...seed.documents[0].rows[0],
            id: id + ":1:1",
            center: "NUEVO CENTRO ESTÁTICO",
          },
        ],
      },
      ...seed.documents,
    ],
  };
  const c = await controller(
    async (url) =>
      url.startsWith("https://gateway.example/")
        ? { ok: false, status: 503, json: async () => ({}) }
        : { ok: true, json: async () => (++loads === 1 ? seed : updated) },
    { apiBase: "https://gateway.example" },
  );
  await c.click();
  assert.match(c.app.innerHTML, /Nuevo Centro Estático/);
  assert.doesNotMatch(c.app.innerHTML, /refresh-feedback error/);
  assert.match(c.app.innerHTML, /Recargar datos/);
});
test("sources has a single live progress message during a refresh", () => {
  const m = model();
  m.view = "sources";
  m.refreshing = true;
  m.refreshMessage = "Comprobación solicitada";
  const html = context.window.BAV.shell(m);
  assert.equal((html.match(/id="refresh-status"/g) || []).length, 1);
});
test("CSV preserves the document date, hash, origin and archived link", () => {
  const text = BA.csv([
    {
      ...row("a:1:1"),
      document_id: "a",
      document_published_at: "2026-09-30",
      document_sha256: "a",
      source_url: "https://www.carm.es/source.pdf",
      artifact_url: "documents/a.pdf",
    },
  ]);
  assert.match(text, /Fecha del documento/);
  assert.match(text, /2026-09-30/);
  assert.match(text, /documents\/a.pdf/);
});
test("saved copies do not show merged headline vacancy statistics", () => {
  const m = model();
  m.view = "vacancies";
  m.onlySaved = true;
  assert.doesNotMatch(context.window.BAV.shell(m), /class="stats"/);
});
test("a completed refresh advances the currently viewed latest copy", async () => {
  const initial = {
    ...seed,
    mode: "server",
    capabilities: { source_check: "available" },
  };
  const id = "c".repeat(64),
    added = {
      ...seed.documents[0],
      id,
      sha256: id,
      published_at: "2026-10-01T12:00:00Z",
      rows: [
        {
          ...seed.documents[0].rows[0],
          id: id + ":1:1",
          center: "NUEVO CENTRO VALIDADO",
        },
      ],
    };
  const updated = {
    ...initial,
    current_id: id,
    documents: [added, ...initial.documents],
  };
  let loads = 0;
  const c = await controller(async (url) => ({
    ok: true,
    json: async () =>
      url === "api/refresh"
        ? { id: "job", status: "completed" }
        : ++loads === 1
          ? initial
          : updated,
  }));
  await c.click();
  assert.match(c.app.innerHTML, /Nuevo Centro Validado/);
});
test("published relative archives remain on the web host with an external API gateway", () => {
  context.window.BA_CONFIG = { apiBase: "https://gateway.example" };
  assert.equal(
    U.pdfUrl({ artifact_url: "documents/a.pdf" }),
    "documents/a.pdf#page=1",
  );
  assert.equal(
    U.pdfUrl({ artifact_url: "/api/documents/a.pdf" }),
    "https://gateway.example/api/documents/a.pdf#page=1",
  );
  context.window.BA_CONFIG = {};
});
test("failed same-URL revision remains pending even with an older incorporated document", () => {
  for (const status of [
    "fetch_failed",
    "extraction_failed",
    "detected_not_read",
    "pending",
  ])
    assert.equal(
      BA.isPendingNotice({ kind: "vacancies", status, document_id: "old" }, [
        { id: "old", status: "approved" },
      ]),
      true,
      status,
    );
});
test("announcements outside the vacancy parser scope are informational", () => {
  assert.equal(
    BA.isPendingNotice(
      { kind: "announcement", status: "detected_not_read" },
      [],
    ),
    false,
  );
  const m = model();
  m.view = "acts";
  m.state.catalog.notices = [
    {
      id: "info",
      kind: "announcement",
      title: "Aviso oficial",
      status: "detected_not_read",
    },
  ];
  assert.match(context.window.BAV.shell(m), /Aviso informativo/);
});
test("refresh continues through a nineteen minute deployment queue", async () => {
  let clock = 0;
  const waits = [];
  const result = await BA.refreshSource(
    async () => ({
      ok: true,
      json: async () => ({
        id: "job",
        status: clock >= 19 * 60 * 1000 ? "completed" : "running",
      }),
    }),
    {},
    () => {},
    async (ms) => {
      waits.push(ms);
      clock += ms;
    },
    { now: () => clock },
  );
  assert.equal(result.status, "completed");
  assert.equal(clock, 19 * 60 * 1000);
  assert.ok(waits.every((ms) => ms === 10000));
});
test("refresh twenty minute deadline reports pending without marking the job failed", async () => {
  let clock = 0,
    lastStatus;
  await assert.rejects(
    BA.refreshSource(
      async () => ({
        ok: true,
        json: async () => ({ id: "job", status: "queued" }),
      }),
      {},
      (job) => {
        lastStatus = job.status;
      },
      async (ms) => {
        clock += ms;
      },
      { now: () => clock },
    ),
    (error) =>
      error.code === "refresh_pending" &&
      /sigue pendiente.*vuelve a cargar/i.test(error.message),
  );
  assert.equal(clock, 20 * 60 * 1000);
  assert.equal(lastStatus, "queued");
});
test("refresh deadline includes the time spent fetching job status", async () => {
  let clock = 0,
    calls = 0;
  await assert.rejects(
    BA.refreshSource(
      async () => {
        calls++;
        clock += 1000;
        return {
          ok: true,
          json: async () => ({ id: "job", status: "running" }),
        };
      },
      {},
      () => {},
      async (ms) => {
        clock += ms;
      },
      { now: () => clock },
    ),
    (error) => error.code === "refresh_pending",
  );
  assert.equal(clock, 20 * 60 * 1000);
  assert.ok(calls <= 110);
});
test("sources and favorites explain a bounded public history window", () => {
  const m = model();
  m.state.history_window = {
    omitted_documents: 4,
    note: "El historial completo se conserva en el almacén privado.",
  };
  for (const view of ["sources", "profile"]) {
    m.view = view;
    assert.match(context.window.BAV.shell(m), /Historial publicado limitado/);
    assert.match(context.window.BAV.shell(m), /historial completo se conserva/);
  }
  m.onlySaved = true;
  assert.match(
    context.window.BAV.results(m),
    /favoritos.*copias.*no incluidas/i,
  );
});
test("approved historical metadata keeps an omitted copy incorporated", () => {
  const notice = { kind: "vacancies", document_id: "old", status: "approved" },
    history = [{ id: "old", status: "approved" }];
  assert.equal(BA.isPendingNotice(notice, [], history), false);
  assert.equal(
    BA.isPendingNotice({ ...notice, status: "fetch_failed" }, [], history),
    true,
  );
  assert.equal(
    BA.isPendingNotice({ ...notice, status: "extraction_failed" }, [], history),
    true,
  );
  const m = model();
  m.state.documents = [];
  m.state.history_documents = history;
  m.state.catalog.notices = [notice];
  m.view = "acts";
  assert.match(context.window.BAV.shell(m), /Documento incorporado/);
  assert.doesNotMatch(context.window.BAV.shell(m), /Documento sin incorporar/);
  m.view = "sources";
  assert.match(context.window.BAV.shell(m), /0 publicaciones pendientes/);
});
test("official source status matches reordered and encoded equivalent PDF query parameters", () => {
  const m = model();
  m.view = "sources";
  m.state.catalog.sources = [
    {
      id: "carm-pdf",
      name: "PDF oficial",
      url: "https://www.carm.es/web/descarga?ALIAS=ARCH&IDCONTENIDO=209318&RASTRO=c77%24m22725%2C22759",
    },
  ];
  m.state.catalog.checks = [
    {
      id: "bytes-hash",
      url: "https://www.carm.es/web/descarga?RASTRO=c77$m22725,22759&IDCONTENIDO=209318&ALIAS=ARCH",
      checked_at: "2026-10-01T09:03:17Z",
      status: "read",
      success: true,
    },
  ];
  assert.doesNotMatch(
    context.window.BAV.shell(m),
    /Sin comprobación reciente registrada para esta referencia/,
  );
  m.state.catalog.checks[0].url = m.state.catalog.checks[0].url.replace(
    "209318",
    "209319",
  );
  assert.match(
    context.window.BAV.shell(m),
    /Sin comprobación reciente registrada para esta referencia/,
  );
});


test('Escape in the specialty modal is not intercepted by previously open vacancy filters',async()=>{
  const c=await controller(async()=>({ok:true,json:async()=>seed}));
  c.listeners.toggle({target:{id:'extra-filters',isConnected:true,open:true}});
  c.navigate('position');
  c.document.querySelector=selector=>selector==='dialog[open]'?{open:true}:null;
  let prevented=false;
  c.listeners.keydown({key:'Escape',preventDefault(){prevented=true;}});
  assert.equal(prevented,false);
});

test('closing About opened from the mobile menu restores focus to its visible summary',async()=>{
  const c=await controller(async()=>({ok:true,json:async()=>seed}));
  let focused=null;
  const summary={isConnected:true,focus(){focused=this;c.document.activeElement=this;}};
  const button={isConnected:true,dataset:{action:'about'},focus(){focused=this;}};
  const menu={open:true,contains:()=>true,querySelector:()=>summary};
  c.document.activeElement=button;
  c.document.querySelector=selector=>selector==='.mobile-more[open]'&&menu.open?menu:null;
  c.listeners.click({target:{closest:selector=>['[data-action],[data-view]','[data-action="about"]','[data-action]'].includes(selector)?button:null}});
  assert.equal(menu.open,false);assert.equal(c.dialog.open,true);
  focused=null;c.dialog.close();assert.equal(focused,summary);
});
