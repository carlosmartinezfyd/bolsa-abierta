# Comunicación integral — Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline, with one final independent branch review.

**Goal:** Apply the approved communication audit end to end, preserving source evidence and privacy.
**Architecture:** Keep the vanilla JavaScript application and source contracts. Pure presentation and comparison helpers in core.js; views and controllers retain their existing boundaries. No new paid services or frontend dependencies.
**Tech Stack:** JavaScript, HTML/CSS, Python exporter, Node test runner, GitHub Pages.
**Spec:** ../../../../audit-report-source.md (local approved report; public implementation decisions recorded in DESIGN.md).

## Global Constraints
- Spanish, direct language; no motivational copy or invented facts.
- Preserve source-scoped identity, dates, rows, duplicates and original values.
- Ordinal is not current availability; disappearance is not adjudication.
- Retain IBM Plex Sans, existing palette, self-hosted assets and old route links.
- Never record personal queries or nominal originals in public artifacts.

## Review Focus
- Saved identity survives search, failed reload and temporary 404; viewing without remembering never overwrites it.
- Comparison pairs have compatible scope, deterministic direction, correct duplicate multiplicity and source evidence on both sides.
- Unknown dates/authors/coverage/duration do not become confident assertions.
- Filters, historical favorites and keyboard focus remain usable after re-render and empty results.
- Mobile and large text retain all data with no page-wide horizontal overflow.

### Task 1: Personal evidence and state contract
**Files:** web/core.js, web/position.js, tests/position-ui.test.cjs, tests/communication.test.cjs, DESIGN.md.
**Interfaces:** Preserve API; add publicationContext(doc,currentId), durationLabel(row), createModel.beginSearch(), remember(), forget(), confirm({remember:false}).
- [ ] Add behavioral tests for saved/unsaved selections, 404 recovery, visible dated limitations, unknown evidence.
- [ ] Run Node tests; expect new tests FAIL before implementation.
- [ ] Implement model, visible evidence, result type/body filtering, typography contract.
- [ ] Run node --test tests/*.test.cjs tests/*.test.mjs; expect PASS. Commit.

### Task 2: Navigation, vacancies, comparison and saved items
**Files:** web/core.js, web/ui.js, web/views.js, web/app.js, tests/communication.test.cjs.
**Interfaces:** Task 1 publicationContext; add comparison(previous,later), compatiblePublications(a,b); selected IDs and filter state remain UI-local.
- [ ] Tests: duplicate counts, reversed/incompatible pairs rejected, unchanged pair empty, missing originals visible, no meaningless empty pagination, saved groups per publication.
- [ ] Run tests; expect FAIL. Implement navigation, home, details, comparison selectors/filtering/table and Guardados.
- [ ] Run full Node suite; expect PASS. Commit.

### Task 3: Publications and sources
**Files:** web/core.js, web/views.js, web/app.js, tests/communication.test.cjs.
**Interfaces:** Add publicationEntries(state), filterPublications(entries,filters); catalog filters and pagination local state, source anchors use stable nonnominal IDs.
- [ ] Tests: notice authorship separate from host, date-range and body/course filtering, unknown dates explicit, partial scopes and pending counts distinct.
- [ ] Run tests; expect FAIL. Implement filterable archive, scope summaries, document evidence and folded technical inventory; real correction channel only when provided.
- [ ] Run full Node suite; expect PASS. Commit.

### Task 4: Responsive design and verification
**Files:** web/styles.css, web/position.css, web/landing.css, DESIGN.md, docs/communication-validation.md.
**Interfaces:** Existing class names plus semantic components from tasks 1–3.
- [ ] Consolidate typography 16px body, 13–14px secondary, 28–32px h1; spacing 4/8/16/24/32; 44px comfortable controls.
- [ ] Inspect real browser at 320/390/768/1440, keyboard and enlarged text; reproduce/fix any functional regression with a failing test.
- [ ] Run Python and Node suites, design lint and syntax checks. Expected: passing suites and no unexplained errors.
- [ ] Independent whole-branch review, resolve important findings, integrate and verify deployment, current data and source checks.
- [ ] Document all A01–A30 outcomes, evidence and actual limits. Do not invent human usability sessions.
