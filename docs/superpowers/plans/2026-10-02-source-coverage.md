# Source coverage implementation plan

> For agentic workers: apply executing-plans and test-driven-development. Parallel independent source investigation and inventory implementation are permitted by dispatching-parallel-agents.

**Goal:** find people across verified official publication families and make missing coverage observable.

**Architecture:** durable discovery inventory, strict document adapters, immutable source-backed search generations, truthful compact UI.

**Tech stack:** Python, SQLite/D1, Cloudflare Workers, vanilla JS, GitHub Actions/Pages.

**Spec:** docs/superpowers/specs/2026-10-02-source-coverage.md

## Global constraints

Preserve existing ranks/IDs. No personal data in committed fixtures or reports. No inferred availability or rank from awards. Free infrastructure. Hidden Windows helpers. Existing dedicated task checkout, feature branch feat/source-coverage.

## Review focus

False completeness, dropped pages/records, stale evidence advertised fresh, cross-publication identity/rank collisions, partial activation, personal data exposure, compatibility with existing saved selections.

## Tasks

- [ ] 1. Official discovery inventory and persistence: source_inventory.py, tests/test_source_inventory.py, data/source-registry.json. Test historical coverage beyond feed limits, origin restrictions, classification and retention of failed/changed/pending documents. Run Python suite.
- [ ] 2. Strict complete-document award adapter and reviewed manifests: position_documents.py, tests, position-source.json. Inspect official PDFs, establish independent counts; watch malformed/missing-row tests fail, then implement. Add all rows of reviewed documents.
- [ ] 3. Multi-source search generation: position_sync.py, gateway/positions.mjs, gateway/positions.sql and API tests. Nullable ranks only for evidence records, per-document counts, atomic activation, stable ordinary IDs and bilingual functions. Run Python and Node suites.
- [ ] 4. Calm source-specific result display: web/position.js, DESIGN.md and UI tests. Render correct date/type/source, no fake ordinal for awards. Test and inspect mobile.
- [ ] 5. CI persistence and operational coverage: refresh workflow, README, source inventory reports. Persist metadata, preserve last verified snapshot on failure and distinguish attempt/success. Exercise collector against official services.
- [ ] 6. Independent review, regressions, publication and live verification. Commit and PR, attach PR, deploy compatible schema/Worker before dataset and UI, inspect actual results and remaining coverage gaps.
