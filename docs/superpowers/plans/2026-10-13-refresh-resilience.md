# Refresh resilience

**Goal:** Keep genuinely verified CARM data available on the existing free services, with bounded recovery and honest freshness.
**Architecture:** Immutable source generations remain authoritative. Add a server-derived compact search index, resumable idempotent publication, a separate freshness watchdog, and authenticated original recovery.
**Tech Stack:** Python, SQLite/D1, Cloudflare Workers, GitHub Actions/Pages.
**Spec:** User-approved six-point robustness review in this task (2026-10-13).
**Global constraints:** No new login or paid service. Never advance verification after cached recovery, hide source failures, publish partial PDFs, expose originals/names in logs, reset quota ledgers, or replace active data before validation. Preserve search semantics and backwards compatibility.
**Review focus:** Search completeness and quota accounting; retry races; source-vs-publication dates; authenticated recovery; watchdog deduplication and independent failure evidence.

## Implementation sequence
1. `gateway/positions.mjs`, new search module/migration, publisher and regression tests: index each immutable bucket by trigram/list number, derive on server, resumable backfill, activate only complete generations, measure actual D1 reads. Preserve existing fallback during rollout.
2. `bolsa_abierta/position_sync.py` and tests: compare acknowledged blocks without rewriting, skip already derived search blocks, bounded transient retries, idempotent activation, update real checked_at after publication and assert public metadata consistency.
3. `private_archive.py`, operations, workflow and tests: portable atomic archive writes, dedicated protected recovery key, authenticated restore drill, bounded retention and explicit archive errors.
4. `gateway/worker.mjs`, watchdog module/schema/config and tests: independently observe compact published status and active API metadata; persist stale/mismatched/unavailable incidents; bounded redispatch using existing shared gate. No CARM HEAD dependency.
5. Inventory/coverage audit: classify documented exclusions, retain unresolved current documents as explicit partial coverage, verify discovery/parser failure tests and required current sources.
6. Run full suites, review patch, deploy additive schema/Worker, merge and trigger real CARM refresh. Check API/Pages consistency, private restore and measured queries. Configure quiet multi-day observation and document remaining external limits.

## Validation
Write failing regression tests before behavior changes. Exercise partial upload, timeout after accepted write, concurrent activation, altered PDF, archive corruption, stale/future timestamps, unavailable status, duplicate cron and exhausted budgets. Require full Python/Node CI and one fresh end-to-end source check. Stability over days remains pending until observed, not inferred from a single successful run.
