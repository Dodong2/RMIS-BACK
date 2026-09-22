# RMIS Backend — Current Status

## Module we're on
Module 8: Research Output and IP Tracking

## Backend status (this repo)
- Module 1 (Auth/RBAC): done, stable. Don't revisit unless something breaks.
- Module 2 (research_projects: Program/Project/Study/Milestone): done, stable.
- Module 3 (personnel app): done, stable.
- Module 4 (budget_lib app): done, migrated, `manage.py check` passes. Known simplification: the ₱100k institutional-dry-research cap is validated per budget *version total*, not per fiscal year (no year/period field on the model yet) — flagged to user, left as-is pending confirmation.
- Module 5 (financial_monitoring app): done, migrated, core logic verified via shell/view-level smoke tests (rolled back, no data persisted). BOR-tier realignment review is `system_admin`-only (client-confirmed 2026-09-22); major tier still allows `university_admin` too.
- Module 6 (compliance app): done, migrated, verified via shell smoke test AND live frontend testing (CompliancePage). One real bug found+fixed there (`AIUseDeclarationSerializer.declared_by` missing from `read_only_fields`) — commit `27ed3d6`.
- Module 7 (document_management app): done, migrated, **confirmed working end-to-end against real Supabase Storage** 2026-09-22 (upload → signed URL → download → content match → cleanup, all passed). Bucket is named `research-documents` (not `documents` — user created it with that name; `.env` and `settings.py`'s default both updated to match). Two real setup issues found+fixed during this test: (1) `storage.py` was only sending an `Authorization` header — Supabase's gateway also requires `apikey`, otherwise it 403s with "Invalid Compact JWS"; (2) the bucket has MIME-type restrictions configured (rejected `text/plain`, accepted `application/pdf`) — user should check/expand the allowed MIME types in the Supabase dashboard if Module 7 needs to accept non-PDF document types (.docx, .csv, .zip for datasets, etc.), otherwise valid uploads may get rejected server-side by Supabase.
- Module 8 (outputs app): done, migrated, `manage.py check` passes, incentive-computation logic verified via shell smoke test against the Manual's actual peso figures (rolled back, no data persisted). Reused the pre-existing empty `outputs/` placeholder dir (same hand-written-files approach as `compliance/`, since `startapp` refuses when the directory already exists).

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
- See memory `client-priorities-module5plus` for the client's pinned feature list (Forecasting, Monitoring, Data Viz, best-performer analysis, Approved BOR, External Projects) — relevant when scoping Modules 9/10/11 later. Best-performer analysis will likely need a `college` field somewhere; only `campus` exists today on `Project`.

## Last thing done in this repo
Built outputs app for Module 8 (PublicationRecord + SenseRankedPublisher with a publication-incentive calculator matching the Manual's Article V cash-award table exactly; IPRecord with TRL/adoption-MOA incentive-eligibility logic; CreativeWorkRecord), wired into settings/urls, migration generated and applied, `manage.py check` passes. All 15 incentive-table assertions (book/book-chapter/instructional-material/journal-article tiers, thesis-derivation exception, IP trademark exclusion, TRL threshold, community-adoption exception, once-per-patent claim flag) verified via shell smoke test against the Manual's actual peso figures — rolled back, no data persisted.

## Next thing to do in this repo
Commit this work. Then decide whether to build Module 9 (Project Monitoring, Checkpoints, and Evaluation) next per the module structure doc, or wire up frontend calls for Modules 4/5/8 (Modules 6 and 7 already have frontend integration).
