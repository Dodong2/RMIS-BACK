# RMIS Backend — Current Status

## Module we're on
Module 9: Project Monitoring, Checkpoints, and Evaluation

## Backend status (this repo)
- Module 1 (Auth/RBAC): done, stable. Don't revisit unless something breaks.
- Module 2 (research_projects: Program/Project/Study/Milestone): done, stable.
- Module 3 (personnel app): done, stable.
- Module 4 (budget_lib app): done, migrated, `manage.py check` passes. Known simplification: the ₱100k institutional-dry-research cap is validated per budget *version total*, not per fiscal year (no year/period field on the model yet) — flagged to user, left as-is pending confirmation.
- Module 5 (financial_monitoring app): done, migrated, core logic verified via shell/view-level smoke tests (rolled back, no data persisted). BOR-tier realignment review is `system_admin`-only (client-confirmed 2026-09-22); major tier still allows `university_admin` too.
- Module 6 (compliance app): done, migrated, verified via shell smoke test AND live frontend testing (CompliancePage). One real bug found+fixed there (`AIUseDeclarationSerializer.declared_by` missing from `read_only_fields`) — commit `27ed3d6`.
- Module 7 (document_management app): done, migrated, **confirmed working end-to-end against real Supabase Storage** 2026-09-22 (upload → signed URL → download → content match → cleanup, all passed). Bucket is named `research-documents` (not `documents` — user created it with that name; `.env` and `settings.py`'s default both updated to match). Two real setup issues found+fixed during this test: (1) `storage.py` was only sending an `Authorization` header — Supabase's gateway also requires `apikey`, otherwise it 403s with "Invalid Compact JWS"; (2) the bucket has MIME-type restrictions configured (rejected `text/plain`, accepted `application/pdf`) — user should check/expand the allowed MIME types in the Supabase dashboard if Module 7 needs to accept non-PDF document types (.docx, .csv, .zip for datasets, etc.), otherwise valid uploads may get rejected server-side by Supabase.
- Module 8 (outputs app): done, migrated, `manage.py check` passes, incentive-computation logic verified via shell smoke test against the Manual's actual peso figures (rolled back, no data persisted). Reused the pre-existing empty `outputs/` placeholder dir (same hand-written-files approach as `compliance/`, since `startapp` refuses when the directory already exists).
- Module 9 (monitoring app): done, migrated, `manage.py check` passes. Verified two ways: (1) shell smoke test of the computed helpers (`compute_escalation_status`, `compute_budget_used_pct`, `compute_deliverables_pct`, `compute_renewal_eligible`) against constructed project/budget/disbursement/milestone data — all thresholds (3mo/6mo escalation, 70% budget-OR-70%-deliverables-with-justification renewal rule) matched expected output; (2) `APIRequestFactory`+`force_authenticate` view-level test confirming URL wiring, role-gated 403s (riuh correctly blocked from the evaluation-panel-only endpoint), and the certify/decide action endpoints — all rolled back, no data persisted. First app in this repo built fresh with `startapp` (no pre-existing empty placeholder dir like `outputs`/`compliance` had) — deleted the auto-generated `tests.py` to match the other apps' convention of not having one.

## What the frontend still needs from this module
- Modules 4 (budget_lib) and 5 (financial_monitoring) — frontend pages (BudgetPage,
  DisbursementsPage) are built and call these endpoints, but haven't been
  browser-tested against a live server yet (unlike Modules 6-8, below).
- Module 6 endpoints (ethics-reviews, similarity-checks, ai-declarations, coi-disclosures, misconduct-cases) — confirmed working via frontend's CompliancePage
- Module 7 endpoints (documents list/create/detail/archive) — confirmed working
  via frontend's DocumentsPage, browser-tested against real Supabase Storage
  2026-09-22 (upload → signed download_url → byte-identical download →
  archive, no bugs found this time)
- Module 8 endpoints (publications, sense-publishers, ip-records, creative-works) —
  confirmed working via frontend's OutputsPage, browser-tested 2026-09-22:
  compute_publication_incentive verified correct for both the ISI-journal path
  (₱60,000 at impact factor 2.5) and the SENSE-publisher book path (₱75,000);
  compute_ip_incentive_eligible verified correct through the full
  disclosed→registered→claimed lifecycle. No bugs found this time.
- Module 9 endpoints (monthly-reports, midterm-reports, terminal-reports (+certify),
  evaluations, renewal-applications (+decide), status/<project_id>) — built but NOT
  yet wired into or tested against the frontend.

## Known open questions / decisions pending
- Module 7's `research-documents` Supabase bucket may need its allowed MIME types expanded beyond PDF (see above) — user to check in the dashboard when frontend upload of non-PDF document types starts failing.
- Module 8 simplifications (reasonable defaults from the Manual's Article V R&D Incentive System, not explicitly confirmed with client):
  - `estimated_incentive` on `PublicationRecord` and `incentive_eligible` on `IPRecord` are computed live (SerializerMethodField, not stored) — always reflects current data, never stale, but also means nothing prevents someone from editing a record after the incentive was actually disbursed elsewhere. `IPRecord.incentive_claimed` is a manual RIUH-set flag to prevent double-counting the "once per patent/UM" rule, but there's no equivalent flag on `PublicationRecord` yet — if that turns out to matter (e.g. someone re-submits the same paper), add one.
  - IP incentive is eligibility-only (bool), not a peso amount — the Manual explicitly defers "schedule of incentive/royalty" to a separate IP Policy document not available to check against.
  - Research Citation incentives (₱1,000/citation, 10/year cap) and R&D Award incentives (Best Paper/Best Researcher, international/national/regional tiers) are both detailed in the Manual's Article V but were NOT built — Module 8's docx feature list only calls out Publications/IP/Creative Works/SENSE-lookup, not Citations/Awards, so this was scoped out to match the stated module boundary. Flag if the client wants these added.
  - `SenseRankedPublisher` is an empty lookup table RIUH/system_admin must populate manually — the actual SENSE-ranked publisher list (Manual Appendix Q) wasn't available to seed it.
  - No `HasRole` write role exists for "Creative Works Management Unit" specifically (docx names it as a primary user) — no such role code exists in the 12 fixed roles or the client's confirmed role list, so `CreativeWorkRecord` writes are gated to riuh/system_admin/project_leader/study_leader/project_staff instead.
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
- See memory `client-priorities-module5plus` for the client's pinned feature list (Forecasting, Monitoring, Data Viz, best-performer analysis, Approved BOR, External Projects) — relevant when scoping Modules 10/11 later. Best-performer analysis will likely need a `college` field somewhere; only `campus` exists today on `Project`.
- Module 9 simplifications (reasonable defaults from the Manual's Article on Monitoring/Renewal/Extension/Archiving, not explicitly confirmed with client):
  - **No proactive notification** — the Manual says "if a project fails to submit monthly progress reports for three consecutive months, the Dean and RIUH will be notified" and terminates at six, but this repo has no Celery/Redis (per project convention, not adding without discussing first), so there's no scheduled job to detect the gap as it happens. `compute_escalation_status()` / `GET /api/monitoring/status/<project_id>/` computes it live on read instead — someone (RIUH/Dean) has to check the endpoint rather than getting pushed an alert. Flag if the client needs actual email notification (`accounts/emails.py`'s `send_brevo_email()` could be wired in once a scheduling mechanism exists).
  - "3/6 consecutive months without a report" is simplified to "months since the most recent `MonthlyProgressReport.period` (or project `start_date` if none exists yet)" — not literally checking each intervening month for a submission, so a project that submits sporadically (e.g. skips month 2, submits month 3) would read as caught up rather than having had a gap. Reasonable given monthly cadence is usually sequential, but flag if the client wants strict month-by-month gap detection.
  - No "Dean" or "Project Monitoring and Evaluation Unit" role exists in the 12 fixed roles — `riuh` is reused as the RDO/monitoring-unit surrogate (consistent with how Module 6/7 already treat RIUH as the de facto RDO representative). Evaluation-panel actions (recording `ProjectEvaluation` outcomes) are gated to `vprei`/`drd`/`crc_chair`/`system_admin` per the Manual's explicit "VPRDE, DRD, CRCs sitting en banc" panel composition; `panel_members` (incl. any external member) is a free-text field, not modeled as user FKs, since an invited external member isn't necessarily a system user.
  - `RenewalApplication.underspend_justification` + the 70%-budget-OR-(70%-deliverables-AND-justification) eligibility rule is computed live (`compute_renewal_eligible`), mirroring Module 8's incentive-eligibility pattern — the RIUH/DRD/VPREI still has to `POST .../decide/` to actually approve/deny; the computed flag is advisory, not a gate.
  - `MidtermReport`/`TerminalReport`/`MonthlyProgressReport` each have an optional FK to `document_management.Document` (whose `TYPE_CHOICES` already had `midterm_report`/`terminal_report` from Module 7) rather than duplicating file storage — same "worth linking later" note the Module 7 entry above made about compliance records, done here from the start.
  - `project_year` (on `MidtermReport`, `ProjectEvaluation`, `RenewalApplication`) is a plain positive integer with no FK to a "project-year" record — there's no such model in `research_projects`, so multi-year cadence is just tracked as a number the submitter enters, not validated against actual project duration.

## Last thing done in this repo
Built monitoring app for Module 9 (MonthlyProgressReport/MidtermReport/TerminalReport for the reporting cadence + certify action; ProjectEvaluation for the annual panel; RenewalApplication with live 70%/70% eligibility computation + decide action; a ProjectMonitoringStatusView giving a live per-project snapshot of escalation status, budget/deliverables %, and report history), wired into settings/urls, migration generated and applied, `manage.py check` passes. Verified via shell smoke test (computed helpers against constructed data) and `APIRequestFactory`+`force_authenticate` view-level test (URL wiring, role-gated 403s, action endpoints) — both rolled back, no data persisted.

## Next thing to do in this repo
Commit this work. Then decide whether to build Module 10 (Dashboard and Institutional Reporting) next per the module structure doc, or wire up frontend calls for Modules 4/5/9 (Modules 6, 7, 8 already have frontend integration).
