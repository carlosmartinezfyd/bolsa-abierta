# Official position updates

> Execution: superpowers:executing-plans, in this session. Scope approved in the conversation on 2 October 2026.

**Goal:** obtain and validate corrections to the published roster, and audit the feasibility of current availability for one specialty.

**Architecture:** Keep private official documents and an explicit review inventory. Source discovery never implies that a correction is applied. Apply only inspected, hash-pinned resolutions with exact preconditions. Preserve the active version on any failure. Do not infer current availability from past awards.

**Constraints:** free services; no nominal PDFs/rows in Git or Pages; no DNI collection; no extra main-screen warnings; do not bypass official access challenges. Existing dedicated checkout, clean feature branch, no concurrent implementers.

## Tasks

- [x] Discover roster PDFs from the official course index, preserving exact URLs and official content IDs. Test provisional/final distinction, new unknown documents, duplicated links, missing baseline and malformed index.
- [x] Collect evidence privately and report blocked downloads, replaced documents and pending review without advancing a successful check. Tests use synthetic files and the production collector.
- [x] Obtain the two known correction PDFs, inspect their complete contents, implement exact changes and compare affected specialties with the original pages. Three admissions, 12,898 total; existing IDs retained.
- [x] Audit the public Educarm generic query for Mathematics block 69. Record its lack of availability/cessation fields and pagination discrepancy. Do not implement a current-position calculation without complete official coverage.
- [ ] Complete a dated movement ledger from definitive awards, cessations and reactivations. This remains separate from the published-list consolidation; Educarm's generic roster is insufficient.
- [x] Run full Python/Node suites and independent review; document verified findings and limits.
- [ ] Deploy compatible Worker and frontend before activating amended data; verify the public API and UI.

## Review focus

Changed bytes at the same official ID; provisional corrections incorrectly applied to definitive lists; missing or truncated index treated as success; a blocked download overwriting evidence; a publication timestamp presented as current availability.

## Verified state, 2 October 2026

- User authorized CAPTCHA completion. Normal browser challenges solved; both official PDF downloads and the public generic query succeeded.
- Mathematics baseline: 762 rows, PDF pages 61–84; 763 with the reviewed supplement. Block 69: 427 consolidated numbers versus 425 observed in Educarm. Its 12 pages returned 562 rows, two repeated pairs, while the counter claimed 560. The query supplies no availability state. Do not infer removals or current rank.
- Independent code review found ambiguous provisional labels and conflicting download targets under one official ID. Both now fail closed, with regressions.
- Full suites passed: 90 Python and 65 Node tests. Independent review checked all real admission fields, hashes, counts, stable IDs and consecutive ranks. No blocking findings remain. Deployment pending.
