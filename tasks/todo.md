# TODO: DPMIS-Based RMIS Spec Alignment

Context, verified gap list, role mapping, and Unknowns are in `tasks/plan.md`.
**Rules:** follow the docx · 12 role codes are final (map, never add) · list unknowns, don't guess.

Standard verification (repo convention, no test files): `python manage.py check` ·
`python manage.py makemigrations --check` after migrating · shell / `APIRequestFactory` smoke test
inside `transaction.atomic()` + savepoint rollback, then a follow-up query to confirm no leaked rows.

---

## Phase 0: Decisions + access matrix — CLOSED
> 2026-09-24: Carl said don't touch auth/RBAC ("RBAC is done na yun"), and the 12 roles are final. T2 code
> was reverted. T3, T4, T5, T5b, T5c, T5d, and T7 are DROPPED. They stay below for the record only.

### T1: Confirm role mapping + unknowns ✅ DONE 2026-09-24
**Description:** Carl/client answer the Unknowns in `plan.md`, at least #1, #2, #12, which block T2.
**Acceptance:** role-mapping table in `plan.md` marked confirmed.
**Dependencies:** None · **Scope:** — (no code)

### T2: `MODULE_ACCESS` matrix + helper ✅ DONE 2026-09-24
**Description:** In `accounts/permissions.py`, add a `MODULE_ACCESS` dict that encodes the docx's
Role-to-Module Access Matrix using the confirmed 12 codes: per module, `full` (read+write), `view`
(read-only), `limited`. Add a helper so a view can declare `module = "budget"` and get `HasRole` for
reads (full+view) and writes (full) automatically. This reuses `HasRole` and adds no new permission
logic.
**Acceptance:**
- [ ] All 15 matrix rows encoded
- [ ] Helper returns read roles for SAFE_METHODS and write roles otherwise
**Verification:** shell: assert a few matrix cells (e.g. project_staff not in budget read)
**Dependencies:** T1 · **Files:** `accounts/permissions.py` · **Scope:** S

**T2 result:** `SPEC_ROLES`, `MODULE_ACCESS`, and `module_roles(module, write=False)` are in
`accounts/permissions.py`. Verified: all 12 DB role codes mapped, 15 modules, spot-checked cells.

### Rule for T3–T5 (applies to every view)
- **Read roles = `module_roles(m)` ∪ that view's own write roles.** The union matters because the matrix
  maps `riuh` → "Compliance Officer", but in LSPU RIUH also runs personnel and outputs (Module Structure
  docx). Without the union, the matrix would lock people out of Manual-assigned duties (see conflicts C1–C6
  in `plan.md`).
- **Write roles stay exactly as they are now** (Manual-driven lists). Where the matrix's "full" is wider,
  nothing gets widened. It's listed in `plan.md` "Matrix wider than code" for Carl to decide later.
- Views that already check roles inside `post()` (forecast trigger, AHP, realignment review, renewal
  decide, terminal certify) keep that check. Only their GET/read gate changes.

### View → module key map (used by T3–T5)
| App / views | module key |
|---|---|
| accounts: users, pending, audit-logs, users/by-role | `user_management` (`roles/` stays open, needed at registration) |
| research_projects: programs, projects, studies | `project_management` |
| research_projects: milestones | `work_plan` |
| personnel: all | `personnel_tasks` |
| budget_lib: all · financial_monitoring: realignments, budgets/<pk>/summary | `budget` |
| financial_monitoring: disbursements | `disbursement` |
| compliance: all | `compliance` |
| document_management: all | `documents` |
| outputs: all | `research_outputs` |
| monitoring: monthly/midterm/terminal reports, renewal, status | `monitoring` |
| monitoring: evaluations | `evaluation` |
| dashboard: all (incl. exports/appendix-*) | `dashboard` |
| forecasting: all | `forecasting` |
| decision_support: all | `dss` |
| risk_indicators: all | **`risk` (NOT in the spec matrix, see Unknown R1)** |
| reports: all | `reports` |

### T3: Apply matrix: accounts, research_projects, personnel, budget_lib, financial_monitoring
**Description:** Replace `permissions.IsAuthenticated()` on reads with
`HasRole(module_roles(key) + <view write roles>)` using the map above. Don't touch write gates.
**Acceptance:**
- [ ] No read in these 5 apps is gated only by `IsAuthenticated` (except `roles/`, register, google auth)
- [ ] `project_staff` GET `budget/budgets/` → 403; `finance_budget` → 200
- [ ] `riuh` GET `personnel/assignments/` → 200 (union rule); `university_admin` GET
      `financial/realignments/` → 200
**Verification:** `manage.py check` + `APIRequestFactory` smoke test of the above (rolled back)
**Dependencies:** T2 · **Files:** `accounts/views.py`, `research_projects/views.py`, `personnel/views.py`,
`budget_lib/views.py`, `financial_monitoring/views.py` · **Scope:** M

### T4: Apply matrix: compliance, document_management, outputs, monitoring
**Acceptance:**
- [ ] `finance_budget` GET `outputs/publications/` → 403; `riuh` → 200
- [ ] `project_staff` GET `monitoring/evaluations/` → 403; `drd` → 200
- [ ] `project_staff` can still POST `compliance/ai-declarations/` (existing write kept)
**Verification:** same as T3 · **Dependencies:** T2
**Files:** those 4 apps' `views.py` · **Scope:** M

### T5: Apply matrix: dashboard, forecasting, decision_support, risk_indicators, reports
**Acceptance:**
- [ ] `project_staff` GET `forecasting/runs/` → 403; `program_leader` → 200 (view)
- [ ] `project_staff` GET `decision-support/recommendation-runs/` → 403
- [ ] Risk gating uses whatever R1 decides (default below)
**Verification:** same as T3 · **Dependencies:** T2, R1
**Files:** those 5 apps' `views.py` (+ `accounts/permissions.py` for a `risk` key) · **Scope:** M

### T5b: Scope helper + project-owned lists (research_projects, personnel, budget_lib, financial_monitoring)
**Description:** Add `scope_projects(user)` to `accounts/permissions.py`. It returns `None` (= no
filter) for admin/director/finance/compliance/management roles. For leader/researcher roles, it
returns the Project queryset where the user is project lead, lead of a study in it, lead of its
program, or has a `ProjectAssignment` on it or its studies. Apply it in `get_queryset` for these apps.
Detail views filter too, so an out-of-scope id → 404.
**Acceptance:**
- [ ] `project_staff` assigned to project A: `projects/` lists only A; `projects/<B>/` → 404
- [ ] `drd` still lists all
**Verification:** smoke test with 2 projects + 1 assigned staff (rolled back)
**Dependencies:** T3 · **Files:** `accounts/permissions.py` + 4 `views.py` · **Scope:** M

### T5c: Scope on compliance, document_management, outputs, monitoring lists
Same helper, applied to `get_queryset` (these all have a `project` FK).
**Acceptance:** same two checks as T5b on `documents/` and `outputs/publications/`.
**Dependencies:** T5b, T4 · **Scope:** M

### T5d: Scope on aggregations (dashboard, risk_indicators, reports project list)
Pass the scoped project set into the existing `_scoped_projects` / `compute_risk_dashboard` /
`project_list_report` filters. Per-project endpoints (`status/<id>/`, `appendix-e/<id>/`) → 404 when out
of scope. This also covers reports "Limited" for researchers.
**Acceptance:** `project_leader` dashboard counts = only their projects; `drd` = all.
**Dependencies:** T5b, T5 · **Files:** `dashboard/services.py`+views, `risk_indicators/services.py`+views,
`reports/views.py` · **Scope:** M

## Checkpoint 0
- [ ] check clean, all smoke tests rolled back
- [ ] List of frontend pages that will now 403 or show fewer rows for some roles, written into handover
- [ ] Carl reviews the "Matrix wider than code" list in `plan.md` (widen or keep)
- [ ] Carl picks Phase 1/2 order

---

## Phase 1: Core gaps (M1–M6)

### T6: Office + position (UAM-02/03) ✅ DONE 2026-09-24
**Result:** `office` + `position` put on `User` (not `StaffProfile`, which is project_staff-only). Exposed in
self-profile (`api/auth/user/` PATCH) + `admin/users/` list + Django admin. Migration `accounts/0005`.
Smoke-tested: PATCH saves both, `role` stays read-only, admin list shows them, no leaked rows.
Add `office` to `User` and `position` to `personnel.StaffProfile` (both free text). Expose them in
`CustomUserDetailsSerializer`, the admin user serializer, and the staff-profile serializer.
**Acceptance:** settable via admin + self profile PATCH; migration clean.
**Files:** `accounts/models.py`, `accounts/serializers.py`, `personnel/models.py`, `personnel/serializers.py` · **Scope:** S

### T7: Brevo password reset (UAM-07) — DROPPED (no auth changes)
Two endpoints: `auth/password-reset/` (email → token link via `send_brevo_email()`) and
`auth/password-reset/confirm/` (uid+token+new password), using Django's `default_token_generator`.
Always return 200 so the endpoint doesn't reveal which emails exist.
**Acceptance:** token works once and stops working after the password changes. Google-only users get a
message telling them to use Google.
**Files:** `accounts/views.py`, `accounts/urls.py`, `accounts/emails.py` · **Scope:** S

### T8a: Project detail + pre-RMIS reference fields (PM-03, #5) ✅ DONE 2026-09-24
**Result:** 5 detail text fields + 4 proposal reference fields on `Project` (migration 0003). Status choices untouched. Leader PATCH still 403 (RBAC unchanged).
Add `description`, `objectives`, `beneficiaries`, `expected_outcomes`, `expected_impacts` (all text,
blank) to `Project`. Per decision #5 (default, still reversible): add read-only-style *reference* fields
`proposal_submitted_on`, `proposal_reviewed_on`, `proposal_approved_on` (dates, nullable) +
`reviewing_body` (text). No approval workflow, and `STATUS_CHOICES` stays unchanged.
**Acceptance:**
- [ ] Fields settable on create/PATCH by registration roles; existing projects unaffected
- [ ] `status` choices unchanged → no `status="active"` filter breaks
**Verification:** check + makemigrations --check + smoke PATCH
**Files:** `research_projects/models.py`, `serializers.py`, migration · **Scope:** S

### T8b: Project status history (PM-09/10) ✅ DONE 2026-09-24
**Result:** `ProjectStatusHistory` (migration 0004), written in `ProjectDetailView.perform_update` (the only path that changes project status). Optional `status_remarks` in the PATCH body. GET `projects/<id>/status-history/`. Verified 0 rows for no-change/same-status, 1 per real change.
`ProjectStatusHistory` (project, from_status, to_status, changed_by, remarks, changed_at). Written in
`ProjectSerializer.update()` only when status actually changes. `projects/<id>/status-history/` GET,
newest first, same read gate as projects.
**Acceptance:**
- [ ] active→completed PATCH writes exactly 1 row; PATCH without a status change writes 0
- [ ] Endpoint lists rows newest first
**Verification:** smoke test (rolled back)
**Dependencies:** T8a · **Files:** `research_projects/models.py`, `serializers.py`, `views.py`, `urls.py`,
migration · **Scope:** S

### T9: Milestone details (PPW-02..05) ✅ DONE 2026-09-24
**Result:** `start_date`, `objective`, `deliverable`, `responsible` on `WorkPlanMilestone` (migration 0005). start>target → 400. `?delayed=true` verified.
Add `start_date`, `responsible` (User FK, nullable), `deliverable` (text), and `objective` (text
reference, since objectives stay a text field in T8) to `WorkPlanMilestone`. Add a `?delayed=true`
filter (target_date passed, not done).
**Acceptance:** fields settable; `?delayed=true` returns only past-target, non-done milestones.
**Verification:** smoke test with 1 overdue + 1 on-time milestone
**Dependencies:** T8a · **Files:** `research_projects/models.py`, `serializers.py`, `views.py` · **Scope:** S

### T10: Tasks: overdue, workload, updates (PTM-04..07) ✅ DONE 2026-09-24
**Result:** `?overdue=true` on `tasks/`. `TaskUpdate` model (personnel 0002) + `tasks/<id>/updates/`: assignee or task-assigner roles can post, and `new_status` moves the task. Other staff get 404. `personnel/workload/` gated with the existing `TASK_ASSIGNER_ROLES` (staff → 403).
`?overdue=true` on `tasks/`. `GET personnel/workload/` (open/overdue/done counts per assignee,
`?project=`). `TaskUpdate` model (task, author, note, status_change, at) + `tasks/<id>/updates/`.
**Acceptance:** overdue correct; workload one row per assignee; posting an update with a status changes
the task status.
**Verification:** smoke test with constructed tasks (rolled back)
**Files:** `personnel/models.py`, `serializers.py`, `views.py`, `urls.py` · **Scope:** M

### T11: Budget allocation fields (BM-02/04/05/06) ✅ DONE 2026-09-24
**Result:** `fiscal_year`, `funding_source`, `is_counterpart` on `LineItem` (budget_lib 0002). `budgets/<pk>/summary/` gained `utilization_pct` (actual/adjusted), `by_category`, `by_funding_source`, and `?fiscal_year=`. The existing `totals` keys are unchanged (only `utilization_pct` added). Math verified (40k/120k = 33.33%).
Add `fiscal_year` (nullable int), `funding_source` (text), and `is_counterpart` (bool) to `LineItem`.
Extend `budgets/<pk>/summary/` with `utilization_pct` per line + category subtotals + a
`?fiscal_year=` filter.
**Acceptance:** existing line items unaffected; summary math verified on constructed data.
**Files:** `budget_lib/models.py`, `budget_lib/serializers.py`, `financial_monitoring/views.py` · **Scope:** S

### T12: Disbursement details (M6) ✅ DONE 2026-09-24
**Result:** `payee` + `supporting_document` FK (financial_monitoring 0002). A document from another project → 400. Read-only `funding_source` comes from the line item. `?project=`, `?from=`, `?to=` filters verified.
Add `payee` (text), `supporting_document` (FK → `Document`, nullable) and inherit funding source from
the line item (no duplicate field). Add `?project=` and date-range filters on `disbursements/`.
**Acceptance:** payee/document settable; `?project=`, `?from=`/`?to=` filters correct.
**Verification:** smoke test · **Dependencies:** T11
**Files:** `financial_monitoring/models.py`, `serializers.py`, `views.py`, migration · **Scope:** S

## Checkpoint 1
- [x] Migrations applied, check clean, smoke tests clean (all rolled back, 0 leaked rows each)
- [ ] Carl reviews before Phase 2

---

## Phase 2 (revised 2026-09-24 after client answers) — Carl: "OK lahat, proceed"
Decisions: D1 RBAC = minimal subset (suspend, row-level scope, doc sensitivity, compliance leader-encode + RIUH
verify; NO permission tables / multi-role / per-doc sharing / login changes) · D2 Budget Office sync = XLSX
import + reconcile · D3 ₱100k cap = non-blocking warning · D4 cross-dept = department on assignment +
summary. Manual refs: procurement quarterly, >₱25k → University President / ≤₱25k → Campus Director (Art. III 1.2a);
extension approved ≥1 month before termination, DRD endorses, President approves (Art. III 1.3a).
Every task: check + makemigrations --check + rolled-back smoke test.

- [x] A. ✅ `exceeds_dry_cap` on budget serializer (per fiscal year). P77 flagged, not rejected. No migration.
- [x] B. ✅ `ProcurementRequest` (fm 0003) + `procurement-requests/` + `procurement-requests/<id>/status/`. Routing computed; transitions enforced; amount ≤ available − open requests; `?overdue=true` (30 days, `PROCUREMENT_DELAY_DAYS`). ASSUMPTION: released requests are recorded by Finance as disbursements, so they stop counting as 'committed'.
- [x] C. ✅ `ExtensionRequest` (monitoring 0002) + `extension-requests/` + `extension-requests/<id>/action/` (endorse: drd/crc_chair; approve/deny: university_admin). ≥30 days rule enforced at submit and approve; approval moves `target_end_date`.
- [x] D. ✅ 5×5 scoring in `risk_indicators/services.py`: per-trigger likelihood/impact/score, `risk_score` = max, `risk_level` low/medium/high/**critical**, `recommended_action`. New triggers: 2-month warning, deliverable_shortfall, procurement_delay. 70% checks only within 90 days of end (`RENEWAL_WINDOW_DAYS`). ⚠️ FRONTEND: `RisksPage.tsx` badge + `by_risk_level` need a `critical` case.
- [x] E. ✅ `ProjectRisk` + `RiskUpdate` (risk_indicators 0001) at `risk/register/`, `register/<id>/`, `register/<id>/updates/`. Open register risks feed the project's overall score.
- [x] F. ✅ Generic review bodies (trc/integrity_review/external_review). Leaders encode ethics-review/similarity (`ENCODE_ROLES`). `verified_by/at` on 4 record types (compliance 0002) + `<type>/<id>/verify/` (riuh/system_admin). Edits clear verification.
- [x] G. ✅ `User.account_status` (accounts 0006) + `admin/users/<id>/account-status/` (suspend/reactivate/deactivate). Deactivate is refused while the user still has active leadership/assignments. `toggle-active` now = active↔suspended. No existing users affected.
- [x] H. ✅ `scoped_projects()` + `BudgetScopedMixin` (hooks `filter_queryset`) on budgets, line items, disbursements, realignments, procurement, and summary. Out-of-scope POSTs → 400. Verified per role. NOT scoped: dashboards/forecasting/reports aggregates, and RIUH college scope (no college field).
- [x] I. ✅ `Document.sensitivity` (dm 0002) + `visible_documents()` on list/detail per the Q8 table. LIB uploads default to financial (upload path not live-tested, needs Supabase).
- [x] J. ✅ `ProjectAssignment.department` (personnel 0003, defaults to user.office) + `personnel/collaboration/` (`?cross_only=true`).
- [x] K. ✅ New app `budget_sync` (`api/budget-sync/`): `imports/` (xlsx upload, finance_budget/system_admin), `records/`, `records/<id>/` (manual link), `reconciliation/`. Tested on the REAL workbook: 49 filled sheets (32 blank templates skipped); real RMIS P77 = Budget Office ₱120,000 → matched. Ambiguous titles are left unlinked.
- [x] T15 ✅ `ExpectedOutput` (6Ps) + `ProjectOutcome` (outputs 0002): `outputs/expected-outputs/`, `expected-vs-actual/<project_id>/`, `outcomes/`. Publications/patents actual counts computed live, the other 4 Ps manual.
- [x] T16 ✅ `EvaluationCriterion` + `EvaluationScore` (monitoring 0003): `evaluation-criteria/`, `evaluations/<id>/scores/` (upsert). `weighted_score` on evaluations (null until fully scored). Rubric must total 100%. `monitoring/status/<id>/` now has an `indicators` block (15 client indicators, `monitoring/indicators.py`).
- [x] T18 ✅ `DecisionRecord` (dss 0002) at `recommendation-runs/<id>/decisions/` (DSS roles + university_admin, upsert per project). New criterion metric `risk_score_inverse`. No auto peso allocation.
- [x] T19 ✅ `dashboard/forecasting/`, `dashboard/funding-allocation/` (`?run=`), `dashboard/tasks/`.
- [x] T13 ✅ `ComplianceRequirement` (compliance 0003): `requirements/`, `<id>/`, `<id>/submit/` (responsible person), `<id>/review/` (riuh/system_admin). `?overdue=true`.
- [x] T14 ✅ `Document.review_status` (dm 0003) + `documents/<id>/review/` (approved/returned) + `?review_status=` filter.
- [x] T20 ✅ `reports/<financial|compliance|personnel|outputs>/` × csv/xlsx/pdf/docx, logged. Financial honors budget scope. FIXED a real renderer bug: xlsx crashed on titles containing '/' (Excel sheet-name rule).

## Checkpoint 2 / T21: Traceability + handover
- [ ] `docs/dpmis_traceability.html` (plain HTML, no CSS): every requirement ID → endpoint, all ✅
- [ ] `.claude/rules/handover.md`: new module numbering, role mapping, new endpoints, and a note
      that the "Module 15 pending" entry is superseded (Reports = spec Module 15)
- [ ] memory `module15-pending-and-thesis-objectives` updated
