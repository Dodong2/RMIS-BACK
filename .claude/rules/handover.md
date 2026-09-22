# RMIS Backend — Current Status

## Module we're on
Module 7: Document and Records Management

## Backend status (this repo)
- Module 1 (Auth/RBAC): done, stable. Don't revisit unless something breaks.
- Module 2 (research_projects: Program/Project/Study/Milestone): done, stable.
- Module 3 (personnel app): done, stable.
- Module 4 (budget_lib app): done, migrated, `manage.py check` passes. Known simplification: the ₱100k institutional-dry-research cap is validated per budget *version total*, not per fiscal year (no year/period field on the model yet) — flagged to user, left as-is pending confirmation.
- Module 5 (financial_monitoring app): done, migrated, core logic verified via shell/view-level smoke tests (rolled back, no data persisted). BOR-tier realignment review is `system_admin`-only (client-confirmed 2026-09-22); major tier still allows `university_admin` too.
- Module 6 (compliance app): done, migrated, verified via shell smoke test AND live frontend testing (CompliancePage). One real bug found+fixed there (`AIUseDeclarationSerializer.declared_by` missing from `read_only_fields`) — commit `27ed3d6`.
- Module 7 (document_management app): models, serializers, views, urls, migration done and migrated. Versioning logic (per document_type version sequences, auto-demote prior `is_current`, retention date, 25MB size cap) verified via shell smoke test with Supabase calls mocked out — **the actual Supabase Storage upload/signed-URL path is UNTESTED end-to-end**, because `SUPABASE_SERVICE_ROLE_KEY` is still blank in `.env` (placeholder added, user needs to create the storage bucket in the Supabase dashboard and paste the service role key in). Until that key is filled in, POST /api/documents/documents/ will fail at the `upload_document()` call.

## What the frontend still needs from this module
- POST/GET /api/budget/budgets/, /api/budget/line-items/, POST .../certify/ — Module 4, not yet called from frontend
- POST/GET /api/financial/disbursements/, /api/financial/realignments/, POST .../review/, GET /api/financial/budgets/<id>/summary/ — Module 5, not yet called from frontend
- Module 6 endpoints (ethics-reviews, similarity-checks, ai-declarations, coi-disclosures, misconduct-cases) — confirmed working via frontend's CompliancePage
- POST/GET /api/documents/documents/ (multipart, `file` field) — upload/list versioned project documents; blocked until the Supabase service role key is set (see above)
- GET /api/documents/documents/<id>/ — retrieve one document, includes a signed `download_url` (1hr expiry); list view intentionally omits `download_url` to avoid N+1 Supabase calls
- POST /api/documents/documents/<id>/archive/ — riuh/system_admin only

## Known open questions / decisions pending
- **Blocking Module 7**: needs a Supabase Storage bucket named `documents` (or set `SUPABASE_STORAGE_BUCKET` to match an existing one) created as **private**, plus `SUPABASE_SERVICE_ROLE_KEY` filled into `.env` (Project Settings → API in the Supabase dashboard). Nothing else in the app will work until this is done.
- Empty stale placeholder dir `outputs/` at repo root (not registered as a Django app) — likely reserved for Module 8, left untouched.
- Module 4: version_number auto-increments per project on create, and creating a new version auto-demotes the prior `is_current` version — an assumption made from context, not explicitly confirmed with client/frontend yet.
- Module 5 realignment design decisions, confirmed with client 2026-09-22:
  - Tier boundary is computed as `amount / from_line_item.amount` (the source line item's *original approved* amount, not its currently-adjusted balance) — per the Manual's "realignment within 33% of existing expense items."
  - >100%/new-expense-item tier (Board of Regents, no BOR role exists) is reference-only: `system_admin` (only — client re-confirmed 2026-09-22, not `university_admin`) records a `bor_resolution_number` once externally approved by BOR. Major tier (33-100%) still allows both `system_admin` and `university_admin` to review.
  - "Once per calendar/project year" enforced as: at most one non-rejected `BudgetRealignment` per project per calendar year (by `created_at.year`). The Manual's "except in highly meritorious cases" override is NOT modeled — no bypass path exists yet.
  - "At least 2 months before project end" enforced as a flat 60-day lead time against `Project.target_end_date`; skipped entirely if that field is null.
- Module 6 simplifications (not explicitly confirmed with client — reasonable defaults from the Manual, flag if they need to change):
  - `SimilarityCheckRecord.document_type = "other"` defaults to the stricter 20% threshold (only "published_article"=15% and "thesis_dissertation"=20% are specified in the Manual).
  - `EthicsReviewReference`/`MisconductCaseReference` status choices are a reasonable generic set — the Manual doesn't specify an exact status vocabulary for these.
- Module 7 simplifications (reasonable defaults, not explicitly confirmed with client):
  - `retention_until` = upload date + 3650 days (10 years, ignoring leap-year drift) — the Manual's 10-year rule is stated specifically for hard-copy thesis/dissertation records endorsed to the Records Office, but applied here to every document type for simplicity.
  - `stage` choices (inception/midterm/terminal/post_completion) are inferred from the project lifecycle terminology used elsewhere in the Manual (Module 9's midterm/terminal reporting cadence) — the Manual doesn't define an explicit stage vocabulary for Module 7 specifically.
  - No hard-delete on `Document` (matches the User-record convention already established) — only `is_archived` toggling via the archive endpoint; superseded versions stay in the table with `is_current=False`.
  - 25MB upload size cap is an arbitrary reasonable default, not manual-specified.
  - Ethics-review/similarity-check records in `compliance` app (Module 6) still don't FK into `document_management.Document` — they were built before this module existed. Worth linking later if the frontend wants "view the actual similarity report PDF" type features.
- See memory `client-priorities-module5plus` for the client's pinned feature list (Forecasting, Monitoring, Data Viz, best-performer analysis, Approved BOR, External Projects) — relevant when scoping Modules 9/10/11 later. Best-performer analysis will likely need a `college` field somewhere; only `campus` exists today on `Project`.

## Last thing done in this repo
Built document_management app for Module 7 (Document model with per-type version sequences, Supabase Storage integration via direct REST calls mirroring the existing `accounts/emails.py` Brevo pattern, signed-URL downloads, 10-year retention clock, archive endpoint), wired into settings/urls, migration generated and applied, `manage.py check` passes, versioning logic verified via shell smoke test (Supabase calls mocked, rolled back). Added `SUPABASE_SERVICE_ROLE_KEY`/`SUPABASE_STORAGE_BUCKET` env vars with safe blank/default values so nothing crashes before the user fills in the real key.

## Next thing to do in this repo
Commit this work. User still needs to: (1) create a private `documents` bucket in the Supabase dashboard, (2) paste the service role key into `.env`'s `SUPABASE_SERVICE_ROLE_KEY`. After that, do a real end-to-end upload test (not just the mocked shell test) before considering Module 7 fully done. Then decide whether to build Module 8 (Research Output and IP Tracking) next per the module structure doc.
