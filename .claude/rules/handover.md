# RMIS Backend — Current Status

## Module we're on
Module 6: Ethics, Integrity, and Compliance Tracking

## Backend status (this repo)
- Module 1 (Auth/RBAC): done, stable. Don't revisit unless something breaks.
- Module 2 (research_projects: Program/Project/Study/Milestone): done, stable.
- Module 3 (personnel app): done, stable.
- Module 4 (budget_lib app): done, migrated, `manage.py check` passes. Known simplification: the ₱100k institutional-dry-research cap is validated per budget *version total*, not per fiscal year (no year/period field on the model yet) — flagged to user, left as-is pending confirmation.
- Module 5 (financial_monitoring app): done, migrated, core logic verified via shell/view-level smoke tests (rolled back, no data persisted). BOR-tier realignment review is `system_admin`-only (client-confirmed 2026-09-22); major tier still allows `university_admin` too.
- Module 6 (compliance app): done, migrated, `manage.py check` passes, core logic (similarity threshold auto-flagging, study/project consistency, misconduct subject validation) verified via shell smoke test (rolled back). Reused the pre-existing empty `compliance/` placeholder dir instead of `startapp` (Django refused `startapp compliance` because the directory already existed — files were hand-written to match the same structure as the other apps).

## What the frontend still needs from this module
- POST/GET /api/budget/budgets/, /api/budget/line-items/, POST .../certify/ — Module 4, not yet called from frontend
- POST/GET /api/financial/disbursements/, /api/financial/realignments/, POST .../review/, GET /api/financial/budgets/<id>/summary/ — Module 5, not yet called from frontend
- POST/GET /api/compliance/ethics-reviews/, /similarity-checks/ — RIUH/system_admin only, logs external review outcomes (TRC/Ethics Review Board/IACUC) and similarity-check results, not yet called from frontend
- POST/GET /api/compliance/ai-declarations/, /coi-disclosures/ — self-service, any authenticated user can declare/disclose their own; COI status/mitigation updates are RIUH-only via PATCH
- POST/GET /api/compliance/misconduct-cases/ — RIUH/system_admin only, logs plagiarism/fabrication/falsification case status references

## Known open questions / decisions pending
- Empty stale placeholder dirs `budget/` and `outputs/` at repo root (not registered as Django apps, unrelated to the now-used `compliance/`) — flagged to user, left untouched pending their call on cleanup.
- Module 4: version_number auto-increments per project on create, and creating a new version auto-demotes the prior `is_current` version — an assumption made from context, not explicitly confirmed with client/frontend yet.
- Module 5 realignment design decisions, confirmed with client 2026-09-22:
  - Tier boundary is computed as `amount / from_line_item.amount` (the source line item's *original approved* amount, not its currently-adjusted balance) — per the Manual's "realignment within 33% of existing expense items."
  - >100%/new-expense-item tier (Board of Regents, no BOR role exists) is reference-only: `system_admin` (only — client re-confirmed 2026-09-22, not `university_admin`) records a `bor_resolution_number` once externally approved by BOR. Major tier (33-100%) still allows both `system_admin` and `university_admin` to review.
  - "Once per calendar/project year" enforced as: at most one non-rejected `BudgetRealignment` per project per calendar year (by `created_at.year`). The Manual's "except in highly meritorious cases" override is NOT modeled — no bypass path exists yet.
  - "At least 2 months before project end" enforced as a flat 60-day lead time against `Project.target_end_date`; skipped entirely if that field is null.
- Module 6 simplifications (not explicitly confirmed with client — reasonable defaults from the Manual, flag if they need to change):
  - `SimilarityCheckRecord.document_type = "other"` defaults to the stricter 20% threshold (only "published_article"=15% and "thesis_dissertation"=20% are specified in the Manual).
  - No document-management FK yet (Module 7 not started) — similarity checks and ethics reviews reference `project`/`study` directly plus a free-text `document_title`, not an actual document record.
  - `EthicsReviewReference`/`MisconductCaseReference` status choices are a reasonable generic set (pending/approved/conditional/revision_required/rejected, and reported/under_investigation/upheld/dismissed) — the Manual doesn't specify an exact status vocabulary for these.
- See memory `client-priorities-module5plus` for the client's pinned feature list (Forecasting, Monitoring, Data Viz, best-performer analysis, Approved BOR, External Projects) — relevant when scoping Modules 9/10/11 later. Best-performer analysis will likely need a `college` field somewhere; only `campus` exists today on `Project`.

## Last thing done in this repo
Built compliance app for Module 6 (EthicsReviewReference, SimilarityCheckRecord, AIUseDeclaration, ConflictOfInterestDisclosure, MisconductCaseReference — all reference/log models per the Manual's Article IV, no approval workflow since the module explicitly doesn't simulate external processes), wired into settings/urls, migration generated and applied, `manage.py check` passes, core logic verified via shell smoke test (rolled back, no data persisted).

## Next thing to do in this repo
Commit this work, then smoke-test the /api/compliance/ endpoints against a running server with real HTTP requests, and decide whether to build Module 7 (Document and Records Management) next per the module structure doc.
