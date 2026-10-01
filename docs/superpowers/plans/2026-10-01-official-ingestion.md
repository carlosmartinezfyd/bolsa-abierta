# Official ingestion implementation plan

> For agentic workers: use test-driven development and independent task review. User explicitly approved investigation and implementation on 2026-10-01. Proceed continuously within this scope.

**Goal:** Reliably discover official Murcia vacancy publications, archive exact evidence, validate and publish observations, and offer public refresh through an optional service.
**Architecture:** Readable existing vanilla JS frontend; Python collector/parser; SQLite metadata and content-addressed artifacts; atomic static exports; small WSGI API with bounded refresh worker. Static Pages can receive scheduled validated exports; on-demand origin checks require the service. No hosting purchase or shared-branch merge.
**Tech stack:** Python 3.11+, pdfplumber, requests, BeautifulSoup, standard-library SQLite/WSGI, Node built-in tests.
**Spec:** ../specs/2026-10-01-public-refresh.md

## Global constraints

- Official origins only: rrhheducacion.carm.es, www.carm.es. Public API accepts no fetch URL or PDF upload.
- Preserve prior approved data on failed/partial collection or extraction. Never equate HTTP200 HTML with PDF success.
- Preserve original PDF bytes, hash, raw cells, page/row identity. Unknown template or empty extraction requires review.
- Existing public source is a packed static export with no backend. Restore readable sources without restyling.
- Use dedicated existing task clone and feature branch; no extra worktree needed for this isolated clone.
- Captcha/access challenges are recorded, not bypassed. HTTP time/size/redirect budgets and source cooldowns bound work.
- No private credentials or nominal applicant integration. Historical rows remain explicitly unverified against missing originals.

## Review focus

1. Partial failures after new discovery must not advance complete-source success timestamps.
2. Reused URL with changed bytes/process must be detected; same bytes must not duplicate records.
3. Query ordering or changed origin URLs must not lose identity; irrelevant announcements must not become vacancy tables.
4. PDF schema/page/row drift and malicious inputs must fail closed without replacing valid documents.
5. Concurrent refresh requests, restart, public path handling and corrupt persisted artifacts must preserve consistency.

## Task 1 official collection

Files: bolsa_abierta/sources.py, tests/test_sources.py.
Interface: SourceError(message, code='...'); FetchResult(url, final_url, body, content_type, status, headers); OfficialClient.fetch(url, *, kind='html', etag=None) -> FetchResult; discover_notices(client, known_notices=()) -> {'notices':list,'checks':list,'complete':bool}. Notices carry id,url,title,date,pdf_urls,kind; checks carry id,url,checked_at,status,error and success boolean. Fixed source roots and at most 20 bounded announcement reads per run. Include already-known recent notices for rectification checks.
- [x] Tests first: official RSS + HTML, irrelevant titles, malformed feed/HTML, direct PDF URLs, blocked redirects, size limits, private DNS, failures retain known candidates.
- [x] Run failing tests, implement, rerun unittest tests.test_sources.

## Task 2 strict PDF extraction

Files: bolsa_abierta/parser.py, tests/test_parser.py, tests/fixtures/carm-2026-09-30.pdf (+ fixture provenance).
Interface: ParseError(message); parse_pdf(data:bytes, source_url:str, retrieved_at:str) -> frontend-compatible document dict (id=sha256; rows as existing schema plus raw_cells/bbox; published_at extracted document issue time Europe/Madrid; process_id; pages/page_counts/row_count/places; parser_version; official_download provenance; authenticated false; status approved only known validated format). Provide semantic_sha256. Store download/source timestamps separately. No I/O/network in parser.
- [x] Test actual fixture yields process3133, 77 rows,85 places, pagecounts21/22/22/12/0, duplicate rows preserved, footers accepted; invalid magic, truncated/encrypted/unknown layout, bad quantities/codes rejected.
- [x] Add schema-level validation tests via extracted-table validation helper so malformed cells tested without binary rewriting.
- [x] Implement then run unittest tests.test_parser.

## Task 3 storage and ingestion coordinator

Files: bolsa_abierta/store.py, pipeline.py, tests/test_pipeline.py.
Interface: Store(root, seed_path); state() -> frontend dict; run_refresh(store, client=None) -> run dict; export_static(store, output_dir) archives/documents and data/state.json. Jobs and artifacts are durable; transaction publishes accepted documents and version pointers after archived bytes exist. Last attempt vs last successful complete check separated. Handle same-process revision, retain replaced document, historical distinct-process comparison.
- [x] Tests first: full valid run, HTML rejection, failed discovery retains state, partial PDF failure, same bytes twice, changed bytes same URL, chronological selection, original provenance bytes, atomic export.
- [x] Implement, run relevant suite, inspect fixture output.

## Task 4 frontend and honest capabilities

Files: web/*.js, index.html, tests/frontend.test.cjs, DESIGN.md.
Contract: fetch relative api/state; if unavailable fall back to data/state.json. API state mode server, capabilities.source_check='available'; static snapshot mode static, source_check='snapshot_only'. Refresh POST api/refresh with JSON{} and X-BA-Refresh:1 -> {id,status}; poll GET api/refresh/id. Job statuses queued/running/completed/partial/failed, phase/message optional. Reload state after terminal status. Static button reloads snapshot only and says so, never pretends origin checked. document.artifact_url for exact copy; source_url origin. Freshness object {last_attempt_at,last_success_at,status}; catalog.notices list alongside legacy catalog fields for compatibility.
- [x] Tests first for filter normalization, cross-copy favorites, pending identity, PDF archive links, no unsafe URL schemes.
- [x] Reuse original styling; document observed tokens. Remove packed loader path from entrypoint but leave archived old binary files unreferenced until final cleanup decision.
- [x] Correct texts promising unavailable ZIP/import functionality; frontend does not offer unsupported mutations.
- [x] Exercise real browser after integration.

## Task 5 API, CLI and deployment workflow

Files: bolsa_abierta/server.py,__main__.py; pyproject.toml; Dockerfile; .github/workflows/test.yml, refresh.yml; README.md; tests/test_server.py.
- [x] Tests first: 20 simultaneous refreshes share one job, cooldown, worker errors, process timeout, state/PDF HTTP and path traversal denial; JSON-only empty refresh body.
- [x] CLI init/refresh/export/serve; WSGI service serves only web assets/state/archived documents; never repository internals or arbitrary files. Production single worker process with threads and durable volume. Parser executes with resource/time limits through subprocess.
- [x] Scheduled export workflow preserves previous state+artifacts, tests before deploy and no repo secrets in browser; document scheduling limitations and GitHub Pages configuration.
- [x] Run complete Python and Node suites, live collector, browser integration, independent code review, then commit feature branch and prepare reviewable PR/artifact.

## Execution ledger

Ruling: implement within the existing clean task-specific clone on a feature branch. Native worktree attachment is tied to a projectless parent and provides no additional isolation benefit.
Ruling: provider-neutral WSGI service supports true on-demand checks; GitHub Pages receives a separate scheduled static export. UI distinguishes their capabilities. Hosting selection remains external configuration.
Pre-flight: task1 produces notices/checks consumed by3; task2 produces compatible documents consumed by3; task3 exports state consumed by4 and5; task4 API contract implemented by5. Files are separated across parallel implementers; parent owns3/5.


## Final execution evidence (2026-10-01)

- User priority: free public service. Implemented GitHub Pages + scheduled/manual GitHub Actions, with optional Cloudflare Workers Free/D1 gateway for public requests. WSGI remains an optional deployment alternative.
- Restored readable frontend; removed the obsolete packed loader and seven binaries. Existing visual design retained. Filter, multi-document favorites, pending revision and provenance links corrected.
- Successful official fetch recorded at 06:37:05 UTC: SHA25681cd8ac0cbf38e828198fe37b0f7fb7132aeaa585c1633fe749ef1b3cec41280,170551bytes,77rows/85places. Archived audited bytes parsed in subprocess and included in initial snapshot. Subsequent complete pipeline checks encountered an off-origin access challenge: freshness remains partial, complete-success timestamp null. No challenge bypass.
- Source checks now validate index structure and nonempty RSS; recent14day window/new notices avoids repeatedly crawling all history. Failed extraction archives its original bytes for maintainer review without publishing rows.
- Independent review found/fixed misleading pending state, discarded failed evidence, missing archive export, unvalidated historical hash reuse, maintenance-page freshness and 3minute/20minute job timeout mismatch.
- Offline verification:60Python tests +37Node tests, including real PDF subprocess/store/export/restore and real SQLite gateway SQL concurrency. Browser checked API/static mode,77rows/85places,archive link,copy filters,favorites and390px mobile layout.
- Public state limited to8MiB with explicit omitted-history notice; full durable state and available PDFs retained. Gateway protects16MiB and documents FreeCPU limits requiring observation after activation.
- Not performed: merge to main, Pages configuration change, production deploy, Cloudflare account/database/secret creation, real Cloudflare-to-Actions end-to-end test. Those activation steps remain documented in README/docs/free-gateway.md. Docker recipe supplied but container runtime not exercised.
- Final integration:feature branch and reviewable pull request; no shared-branch merge and no hosting purchase.
