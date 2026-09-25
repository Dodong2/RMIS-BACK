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


---

## Phase 3 — Clarification-Answers audit + prototype task gaps (planned 2026-09-24)
Context/decisions: `tasks/plan.md` → "Audit" + "Phase 3 plan". Standard verification applies to every task
(check + makemigrations --check + rolled-back smoke test via `APIClient(HTTP_HOST="localhost")`).

### P1: Project Leader encodes LIB (Q12) ✅ DONE
**Result:** Program/project leaders added to budget_lib `MANAGE_ROLES`, and `ensure_in_scope` (new, shared in `accounts/permissions.py`; financial_monitoring's copy was replaced by it) limits them to their own projects. Also closed a hole: DELETE of a line item on a certified budget → 400 (it skipped serializer validation before).
Add program/project leaders to budget writes (create budget, add/edit/delete line items on **draft** budgets), limited to
their own projects via `scoped_projects`. Certification stays `finance_budget`/`system_admin`.
- [ ] Leader creates a budget + line items on own project → 201; on another project → 400
- [ ] Certified budget still locked for everyone
**Files:** `budget_lib/views.py`, `budget_lib/serializers.py` · **Scope:** S

### P2: Leaders write work-plan milestones (Module Structure M2) ✅ DONE
**Result:** `MILESTONE_ROLES` = registration roles + leaders. Serializer `validate` + `perform_destroy` enforce scope (another leader's milestone → 400).
Program/project/study leaders create/edit milestones on their own projects; `system_admin`/`crc_chair` unchanged.
- [ ] Leader → own project 201, other project 400; staff 403
**Files:** `research_projects/views.py`, `serializers.py` · **Scope:** S

### P3a: Task "For Review" + approval ✅ DONE
**Result:** personnel 0004. `Task.save()` sets `started_at`/`completed_at` from the status on every path. Assignee → done is refused (PATCH and task updates). `tasks/<id>/review/` approve/return is logged as a TaskUpdate.
Add `for_review` status, `started_at`, `completed_at` (auto-set on transitions). Assignee may move to in_progress/blocked/for_review
only; `tasks/<id>/review/` {approve|return, remarks} by `TASK_ASSIGNER_ROLES` → done / in_progress (logged as a TaskUpdate).
- [ ] Assignee PATCH status=done → 400; → for_review OK
- [ ] Approve sets done + completed_at; return sets in_progress
**Files:** `personnel/models.py`, `serializers.py`, `views.py`, `urls.py`, migration · **Scope:** M

### P3b: Task priority + hours + update kinds ✅ DONE
**Result:** personnel 0005. `priority`, `estimated_hours`, `TaskUpdate.kind` + `hours`, computed `logged_hours`, `?priority=`, and est/logged hours in the workload endpoint.
`priority` (critical/high/medium/low, default medium), `estimated_hours`; `TaskUpdate.hours` + `kind`
(update/comment/blocker/completion); `logged_hours` = sum of update hours (computed). Workload endpoint adds est/logged hours.
- [ ] logged_hours sums correctly; `?priority=` filter; workload shows hours
**Files:** same as P3a · **Dependencies:** P3a · **Scope:** S

### P3c: Task deliverables checklist + tags ✅ DONE
**Result:** personnel 0006. `tasks/<id>/deliverables/` (assigners add), `task-deliverables/<id>/` (assignee/assigner tick, assigners delete). `tags` normalized (deduped, sorted), `?tag=`.
`TaskDeliverable` (task, text, done) with `tasks/<id>/deliverables/` CRUD; `tags` JSON list + `?tag=` filter.
- [ ] Checklist toggling works; tag filter works
**Dependencies:** P3a · **Scope:** S

### P4: AI-use percentage (Q10 "~20% AI") ✅ DONE
**Result:** compliance 0004. `ai_content_pct` (0–100) + `exceeds_ai_threshold` (> `AI_CONTENT_THRESHOLD` = 20) + `ai_declarations` in the monitoring indicators.
`AIUseDeclaration.ai_content_pct` (nullable decimal) + computed `exceeds_ai_threshold` (> 20, constant) + count in the indicators block.
- [ ] 25% → flagged; 10% → not; null → not
**Files:** `compliance/models.py`, `serializers.py`, `monitoring/indicators.py`, migration · **Scope:** S

### Checkpoint 3A
- [x] check clean, all smoke tests rolled back · [x] Carl: Q2 GO, college = free text, **system_admin must keep full access everywhere (demo)** — verified: every gate list includes system_admin, and system_admin is never scoped

### P5 (Q2 — gated): Permission + RolePermission tables, seeded
Models + data migration seeding one code per current `*_ROLES` constant; `HasRole("code")` resolves from DB; `role_can(user, code)`;
`scripts/permission_parity.py` compares each constant vs DB for all 12 roles.
- [x] Seed contains every constant; parity script = 0 differences (12 roles × 36 codes, 2026-09-25)
- [x] `HasRole([...])` list form still works (no call site changed yet)
**Files:** `accounts/models.py`, `accounts/permissions.py`, migration, parity script · **Scope:** M

### P6 / P7 / P8 (gated): Convert call sites to permission codes
P6: accounts, research_projects, personnel, budget_lib, financial_monitoring, budget_sync · P7: compliance, document_management, outputs,
monitoring · P8: forecasting, decision_support, dashboard, risk_indicators, reports + the 15 inline checks.
- [x] No `*_ROLES` list used for gating in the group (constants kept only as seed source)
- [x] Parity script still 0 differences; the regression GET sweep has no 5xx/400
- [x] P6 done 2026-09-25: no role-list gates left in its 6 apps; parity 0; role-gate matrix old (c960c3f) vs new identical
  for all 243 route/methods × 12 roles; inline checks match; GET sweep (25 routes × 3 roles) no 5xx/400
- [x] P7 done 2026-09-25: compliance, document_management, outputs, monitoring (RoleWritesMixin.write_roles → write_permission);
  parity 0; matrix vs 9e8cb84 identical (243); 5 inline checks match; GET sweep (20 routes × 3 roles) no 5xx/400
- [x] P8 done 2026-09-25: forecasting, decision_support, dashboard, risk_indicators, reports; repo-wide no role-list gates left
  (remaining role.code uses are identity checks/filters by design); parity 0; matrix vs 5f3410a identical (243);
  inline checks match; GET sweep (22 routes × 3 roles) no 5xx/400
**Scope:** M each

### P9 (gated): Permission view + scope assignment API
`GET admin/permissions/` (matrix: permission × roles, read-only, system_admin); `PATCH admin/users/<id>/scope/` {campus, college}.
- [x] Matrix lists every seeded code; scope PATCH validates keys; non-admin 403 (2026-09-25: 16/16 checks vs real DB, rolled back;
  `scope` added to admin user list; `college` is stored but not enforced yet, no college field on Project)
**Scope:** S

### P10 (gated): Update CLAUDE.md convention (HasRole now takes a permission code; permission list lives in the DB)
**Scope:** XS

### Checkpoint 3B
- [ ] Parity 0 diffs · [ ] regression sweep clean · [ ] commit

### P11: `Project.college` + college/campus scope in `scoped_projects`; `LineItem.study` for Study Leader allocation
- [ ] riuh with scope.college sees only that college's projects; study leader sees only own-study line items
**Files:** `research_projects/models.py`, `budget_lib/models.py`, `accounts/permissions.py`, migrations · **Scope:** M

### P12a / P12b / P12c: Apply scope beyond budget (Q1c)
P12a: projects/programs/studies, milestones, monitoring, outputs · P12b: compliance, documents (combine with sensitivity) ·
P12c: dashboards, risk dashboard/status, reports, forecasting list.
- [ ] project_leader lists only own projects in each module; drd sees all; out-of-scope detail → 404
**Scope:** M each

### P13: Temporary replacement while a leader is suspended (Q3)
`Project.acting_lead` (+ `acting_until`), set via the `account-status` suspend action or project PATCH; `scoped_projects` includes acting leads.
- [ ] Suspend lead with acting_lead → acting lead sees/manages the project; reactivation clears it
**Scope:** S

### P14: Limited per-document sharing (Q8)
`DocumentShare(document, user, granted_by, expires_at)`; project leader grants; `visible_documents` includes unexpired shares.
- [ ] Shared user sees doc until expiry; non-leader grant → 403
**Scope:** S

### P15: Risk alerts inbox (Q7 actions)
`GET risk/alerts/`: leaders get medium+ on own projects, RIUH/CRC get high+ in scope, VP/DRD get critical. Live, no push.
- [ ] Each role gets the right band set for a constructed high + critical project
**Scope:** S

### Checkpoint 3C
- [ ] Regression sweep clean · [ ] handover (frontend impact list per endpoint) · [ ] commit

### Not planned (client says confirm first)
- Q6 indicative peso allocation · project-code format validation (Q4)
