# RMIS Backend — Current Status

## Module we're on
Module 5: Disbursement, Realignment, and Financial Monitoring

## Backend status (this repo)
- Module 1 (Auth/RBAC): done, stable. Don't revisit unless something breaks.
- Module 2 (research_projects: Program/Project/Study/Milestone): done, stable.
- Module 3 (personnel app): done, stable.
- Module 4 (budget_lib app): done, migrated, `manage.py check` passes. Known simplification: the ₱100k institutional-dry-research cap is validated per budget *version total*, not per fiscal year (no year/period field on the model yet) — flagged to user, left as-is pending confirmation.
- Module 5 (financial_monitoring app): models, serializers, views, urls, and initial migration done and migrated. Core logic (tier computation, Approved/Adjusted/Actual balance math, once-per-year gate, over-disbursement block, BOR new-item creation, rejection exclusion) verified via a rolled-back shell smoke test — not yet tested against a running server or real frontend calls.

## What the frontend still needs from this module
- POST/GET /api/budget/budgets/, /api/budget/line-items/, POST .../certify/ — Module 4, not yet called from frontend
- POST/GET /api/financial/disbursements/ — record actual spend against a line item (finance_budget/system_admin only), not yet called from frontend
- POST/GET /api/financial/realignments/ — request a fund transfer (project_leader/system_admin only); tier (minor/major/bor) and status are server-computed, not client-settable
- POST /api/financial/realignments/<id>/review/ — approve/reject a major or BOR-tier realignment (university_admin/system_admin only); BOR tier requires `bor_resolution_number` on approval
- GET /api/financial/budgets/<id>/summary/ — Approved/Adjusted/Actual/Available per line item + totals for a certified budget — no frontend page yet

## Known open questions / decisions pending
- Empty stale placeholder dirs (`budget/`, `compliance/`, `outputs/` at repo root, not registered as Django apps) — flagged to user, left untouched pending their call on cleanup.
- Module 4: version_number auto-increments per project on create, and creating a new version auto-demotes the prior `is_current` version — an assumption made from context, not explicitly confirmed with client/frontend yet.
- Module 5 realignment design decisions, confirmed with client 2026-09-22 ("pwede sa admin muna" — route through university_admin, refine later if the Manual said otherwise):
  - Tier boundary is computed as `amount / from_line_item.amount` (the source line item's *original approved* amount, not its currently-adjusted balance) — per the Manual's "realignment within 33% of existing expense items."
  - >100%/new-expense-item tier (Board of Regents, no BOR role exists) is reference-only: `system_admin` (only — client re-confirmed 2026-09-22, not `university_admin`) records a `bor_resolution_number` once externally approved by BOR; there's no in-system BOR approval workflow. Client confirmed this matches their "Approved BOR" pinned feature. Major tier (33-100%) still allows both `system_admin` and `university_admin` to review.
  - "Once per calendar/project year" is enforced as: at most one non-rejected `BudgetRealignment` per project per calendar year (by `created_at.year`). The Manual's "except in highly meritorious cases" override is NOT modeled — no bypass path exists yet.
  - "At least 2 months before project end" is enforced as a flat 60-day lead time against `Project.target_end_date`; skipped entirely if that field is null.
  - See memory `client-priorities-module5plus` for the client's pinned feature list (Forecasting, Monitoring, Data Viz, best-performer analysis, Approved BOR, External Projects) — relevant when scoping Modules 9/10/11 later. Best-performer analysis will likely need a `college` field somewhere; only `campus` exists today on `Project`.

## Last thing done in this repo
Built financial_monitoring app for Module 5 (Disbursement + BudgetRealignment models, tiered approval routing per the 2026 R&D Manual, Approved/Adjusted/Actual balance calculation, budget summary endpoint), wired into settings/urls, migration generated and applied, `manage.py check` passes, core logic verified via shell smoke test (rolled back, no data persisted).

## Next thing to do in this repo
Commit this work, then smoke-test the /api/financial/ endpoints against a running server with real HTTP requests (not just shell), and decide whether to build Module 6 (Ethics/Integrity/Compliance) next per the module structure doc.
