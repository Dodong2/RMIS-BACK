# Implementation Plan: DPMIS-Based RMIS Spec Alignment

Source: `DPMIS-Based_RMIS_Functional_Requirements_and_Module_Specification.docx` (client, received 2026-09-24).

## Decisions confirmed by Carl (2026-09-24)
- **DO NOT change authentication or RBAC.** Carl: "RBAC is done na yun." The 12 roles + existing
  `HasRole` gates stay exactly as they are. So the whole access-matrix / scope-filtering track
  (T2 code reverted, T3–T5d dropped) and T7 (password reset) are OUT. The spec's 7→12 role mapping
  below is kept as documentation only (for the T21 traceability doc).
- Role mapping (#1) and every lean below (#2, #3, #6, #10, #12) are accepted.
- #5 Proposal workflow: default = read-only reference fields, no in-system approval. The client still
  has the final say, so this is kept reversible.
- Row-level scope filtering is added to Phase 0 (T5b). Multi-role: one role per user for now.
- **The docx will be followed.** Its functional requirements are in scope, not just framing.
- **The 12 role codes are FINAL.** The docx's 7 generic roles are *mapped onto* the 12 codes. They are
  never added as new roles.
- Anything the docx leaves unclear goes in "Unknowns" below. Don't guess.

## Client answers (2026-09-24) — `RMIS chap1/RMIS_Clarification_Answers.docx` + `RMIS_Module_Objective_Alignment.docx`
The client calls these FINAL. Checked against the code:

### ⚠️ Conflicts with Carl's "don't touch auth/RBAC" — needs Carl's decision (D1)
- Q2: seeded `Role_Permission` table in DB + read-only permission view + **UserRole (role + scope) assignment screen**
- Q3: **Suspend ≠ Deactivate.** Suspend = temporary login block that keeps assignments. Today we only have `toggle-active`
- Q8: document access = role + scope + **sensitivity level** (Project Team / Financial / Restricted) + limited per-doc
  sharing with expiry
- Q12 + Q1c: **row-level scope.** Project Leader sees own project budget, Study Leader own study (read-only),
  Project Staff sees no budget, CRC = campus, RIUH = college. Today every authenticated user reads everything
- Q1a: compliance records are **encoded by Project/Study Leader and verified by RIUH**. Today only `riuh`/`system_admin` write
- Alignment doc marks Module 1 "multi-role/scope + row-level filtering" as *Aligned*, but it is NOT built

### New gaps (no RBAC involved)
- **Procurement tracking (Module 5 renamed "Procurement, Realignment, and Financial Monitoring").** LSPU has no
  Disbursement office. Needs a procurement request with status Requested → Processing → Released, ₱25,000
  routing, quarterly cadence, and a delay → escalation flag. None of it exists
- **Module 15 = Budget Office Data Synchronization** (Objective 2d, "Need to Add"): sync or reconciliation feed
  with the central Budget Office system, plus discrepancy flagging
- **Module 3 cross-departmental collaboration** (Objective 1c, "Need to Add"). Not defined anywhere
- **Extension request** (approved ≥1 month before termination, Q10). No model
- **Risk scoring (Q7):** 5×5, Low 1–4 / Medium 5–9 / High 10–16 / Critical 20–25, with a default mapping from
  Manual triggers (2 months without a report = Medium 9, 3 months = High 16, 6 months = Critical 25, <70% utilization
  near renewal = 16, <70% deliverables = 16, forecast > adjusted budget = 12). Replaces the current 0/1–2/3+
  bucketing. Adds new triggers: the 2-month warning, procurement delay
- **Budget under-utilization is "near renewal"** per the client. The current Module 13 check is a flat <70% at any time (D5)
- **Dashboards (Objectives 5a–5d):** Compliance & Activity, Budget Monitoring, **Forecasting Analytics**, **Funding
  Allocation Decision**. The last two have no dashboard endpoint yet
- **Module 6 renamed "Compliance Tracking Module".** No ethics committee at LSPU, so the "Ethics Review Board"/"IACUC"
  choices in `EthicsReviewReference` should become generic review-status labels
- **6Ps = DOST standard** (Q11, still to confirm with RDO). This unblocks T15
- **Evaluation criteria configurable** (Q9). Matches T16
- **DSS (Q6):** ranking + score is enough. Optional *indicative* peso allocation via rank-ordered fulfillment
  (fund the top-ranked project fully, then the next, until the pool runs out), capped by LIB and ₱100k/yr dry. Client to confirm
- **Project ID (Q4):** matches today (auto PK + manual unique code). Format validation is pending the RDO format

### Other flags
- **D4 ₱100k dry-research cap:** the client docs cite it as a Manual rule (Q6; Module 4 "institutional cap validation" = Aligned).
  We REMOVED it on 2026-09-24 at Carl's request (sheet P77 = ₱120k). Contradiction
- **D6 "LSPU Faculty Research Number"** is not a Manual term (Q4). Our CLAUDE.md treats it as the client's term.
  Needs confirmation whether it equals the "R&D project code"
- Objective 1a is renamed to "Document Management Module" (doc-only, thesis wording)

## Overview
The 15 spec modules were checked against the actual backend API (every `urls.py`, plus models and
serializers). Most requirements already exist under LSPU names. The docx's "Module 15" is our Reports
app (Module 14) renumbered, so it's not a new module. The real work: (1) map the 7 spec roles to the 12
codes and enforce the docx's Role-to-Module Access Matrix, including read restrictions (today all reads
are open to any authenticated user); (2) fill the functional gaps below. All changes are additive. App
names and URLs stay the same.

## Architecture Decisions
- **Access matrix = one constant, not DB tables.** `MODULE_ACCESS` in `accounts/permissions.py` maps
  module → {"full": [...codes], "view": [...codes]}, and every view's `HasRole` list reads from it.
  This satisfies the docx note "granular permissions rather than hard-coded module access" in the
  simplest way, and it still reuses `HasRole` (CLAUDE.md convention). DB-editable
  `permissions`/`role_permissions` tables are NOT built unless Unknown #2 says otherwise.
- New models go into the app that already owns the concept (risk register → `risk_indicators`, generic
  requirements → `compliance`, etc.). No new apps.
- Computed values (overdue, utilization %, risk score) are computed live, following the Module 8/9/13
  pattern.
- Verification follows repo convention: `manage.py check` + `makemigrations --check` + a shell /
  `APIRequestFactory` smoke test in `transaction.atomic()` + savepoint rollback. No test files.

## Role mapping (7 spec roles → 12 codes) — CONFIRMED by Carl 2026-09-24, encoded in `accounts/permissions.py::SPEC_ROLES`
| Spec role | Our codes | Confidence |
|---|---|---|
| Super Administrator | `system_admin` | sure |
| Research Director | `drd`, `vprei`, `crc_chair` | per Module Structure docx (VPRDE/DRD/CRDs together) |
| Project Leader | `program_leader`, `project_leader`, `study_leader` | fairly sure |
| Researcher | `project_staff` | fairly sure |
| Finance Officer | `finance_budget`, `procurement_officer_lib` | procurement = LIB logging per client |
| Compliance Officer | `riuh` | per Module Structure docx Module 6 |
| Management / BOD | `university_admin` | per Module Structure docx Module 10 + BOR routed via admin |

Note: in its 2026-09-22 roles list, the client grouped "VP/Uni Admin/DRD" as one actor, and BOR actions
are routed through `university_admin` ("pwede sa admin muna"). So another possible reading is:
Director = `drd` + `vprei`, and Management/BOD = `university_admin` only.

## Verified alignment: spec requirement → current API
Legend: ✅ covered · 🟡 partial · ❌ gap

**M1 User & Access** (`accounts`, `personnel`)
- ✅ UAM-01 create accounts: `auth/register/`, `admin/pending-users/.../assign-role/`
- 🟡 UAM-02 personnel profile: `personnel/staff-profiles/` has only `staff_level`. No position.
- ❌ UAM-03 office/department: no field
- ✅ UAM-04 assign roles: `admin/users/<id>/update-role/`
- 🟡 UAM-05 restrict by role: writes only. Reads are open to all (see matrix)
- ✅ UAM-06 update profile: dj-rest-auth `api/auth/user/` PATCH
- ❌ UAM-07 password recovery: dj-rest-auth `password/reset/` exists, but there's no email backend
  (Brevo-only), so it would fail. Needs a Brevo-based reset.
- ✅ UAM-08 audit: `admin/audit-logs/`
- 🟡 UAM-09 activate/deactivate ✅ via `toggle-active/`. "Suspend" has no distinct state (Unknown #3)

**M2 Project Management** (`research_projects`)
- ✅ PM-01, 04, 06, 07, 08: `projects/`, `milestones/`, `personnel/assignments/`
- 🟡 PM-02 unique ID: `project_code` is unique but manually entered (LSPU Faculty Research Number).
  Not auto-generated (Unknown #4)
- 🟡 PM-03 details: no `description`, `objectives`, `beneficiaries`, expected outcomes/impacts fields
- 🟡 PM-05 status: only active/completed/archived. No proposal → review → approval states
- ❌ PM-09 status history
- 🟡 PM-10 completion: status=completed + certified `TerminalReport`. No explicit "closure" action

**M3 Work Plan** (`research_projects.WorkPlanMilestone`)
- ✅ PPW-01, 06
- ❌ PPW-02 link activity ↔ objective (no objectives entity)
- ❌ PPW-03 responsible personnel on milestone
- ❌ PPW-04 start date (only `target_date`)
- ❌ PPW-05 deliverables
- ✅ PPW-07 delayed: `delayed` status + `risk/status/` slippage flag. Completion % is in
  `monitoring.compute_deliverables_pct`

**M4 Personnel & Tasks** (`personnel`)
- ✅ PTM-01, 02 (`assignments/` + `role_label`), 03, 04, 05 (`tasks/` + status)
- ❌ PTM-06 overdue tasks filter
- ❌ PTM-07 workload endpoint (the `leaders/load/` endpoint covers only leader concurrency)
- ❌ task_updates / task_comments entities

**M5 Budget** (`budget_lib`, `financial_monitoring`)
- ✅ BM-01, 03 (PS/MOOE/CO), 06, 07, 08: `financial/budgets/<pk>/summary/` gives
  approved/adjusted/actual/available per line item plus totals
- 🟡 BM-06 no utilization % field (trivial add), no per-category subtotal
- ❌ BM-02 annual allocation (no fiscal year)
- ❌ BM-04 funding source (only `Project.funding_type`)
- ❌ BM-05 counterpart funding

**M6 Disbursement** (`financial_monitoring`)
- ✅ record, validate (certified-budget + available-balance check), balance update, utilization
- ❌ payee/vendor field
- ❌ supporting document FK
- ❌ funding source on disbursement
- 🟡 "generate financial reports": JSON summary only. No file report in `reports/`

**M7 Compliance** (`compliance`)
- 🟡 LSPU-specific records exist (ethics, similarity, AI, COI, misconduct)
- ❌ CM-01..06 generic requirement with responsible person, deadline, status, document, overdue list
- ❌ Review workflow (Compliant/Returned/Non-Compliant)
- 🟡 CM-07 report: `dashboard/compliance/` JSON only

**M8 Documents** (`document_management`)
- ✅ DM-01, 02, 03 (versioning), 04
- 🟡 DM-06 linked to project/study. Not linked to transactions (disbursements)
- ❌ DM-05 per-document access control
- ❌ Review/Approve step in the workflow

**M9 Research Outputs** (`outputs`)
- ✅ ROM-02..06: publications, IP, creative works
- ❌ ROM-01 expected outputs (expected vs actual)
- ❌ ROM-07 outcomes/impacts
- ❌ 6Ps classification (products, partnerships, policies)

**M10 Monitoring & Evaluation** (`monitoring`)
- ✅ monitoring events (monthly/midterm/terminal reports), evaluations, `status/<id>/`
- ❌ monitoring indicators
- ❌ evaluation criteria + scores (`ProjectEvaluation` has outcome only, no scores)
- 🟡 performance gaps: `risk/status/` flags cover this partly

**M11 Dashboard & Reporting** (`dashboard`)
- ✅ project, budget, compliance, and output dashboards + filters
- ❌ task data in dashboards
- ❌ role-based dashboard (the same data is shown to every role)

**M12 Forecasting** (`forecasting`)
- ✅ fully covered (ARIMA, budget comparison, overrun flag). Needs only the matrix access rule

**M13 DSS** (`decision_support`)
- ✅ performance score, prioritization (AHP+WSM), financial risk (overrun criterion)
- 🟡 risk score not a DSS input (Module 13 risk flags not used as a criterion)
- ❌ decision records: the management decision taken on a recommendation isn't recorded
- 🟡 "allocation recommendation": ranking only, no peso allocation (Unknown #6)

**M14 Risk Management** (`risk_indicators`)
- 🟡 computed flags only
- ❌ manual risk register: category, probability, impact, score, owner, mitigation, status,
  updates, close/escalate

**M15 Reports & Export** (`reports`)
- ✅ PDF/XLSX/CSV/DOCX rendering, `GeneratedReportLog`
- 🟡 project reports: Appendix E/F/G + project list
- ❌ financial, compliance, personnel, and research-output report types

## Task List (details in `tasks/todo.md`)
### Phase 0: Access (matrix + scope)
- [x] T1 Confirm role mapping + unknowns
- [~] T2 matrix helper: built, then REVERTED (RBAC out of scope)
- [DROPPED] T3 Matrix reads: accounts, research_projects, personnel, budget_lib, financial_monitoring
- [DROPPED] T4 Matrix reads: compliance, document_management, outputs, monitoring
- [DROPPED] T5 Matrix reads: dashboard, forecasting, decision_support, risk_indicators, reports (needs R1)
- [DROPPED] T5b Scope helper + project-owned lists (projects/personnel/budget/financial)
- [DROPPED] T5c Scope: compliance/documents/outputs/monitoring
- [DROPPED] T5d Scope: dashboard/risk/reports aggregations
### Checkpoint 0: 403/row-count changes listed for the frontend; Carl reviews "matrix wider than code"
### Phase 1: Core gaps (M1–M6)
- [x] T6 Office + position · [DROPPED] T7 password reset · [x] T8a Project detail + pre-RMIS reference fields ·
      [x] T8b Status history · [x] T9 Milestone details · [x] T10 Tasks overdue/workload/updates ·
      [x] T11 Budget fiscal year/funding/counterpart/utilization · [x] T12 Disbursement payee/document/filters
### Checkpoint 1
### Phase 2: Module gaps (M7–M15)
- [ ] T13 Compliance requirements · T14 Document review · T15 6Ps outputs (**blocked: #11**) ·
      T16 Indicators + evaluation scores · T17 Risk register (needs R1) · T18 DSS decision records ·
      T19 Dashboard tasks · T20 Report types
### Checkpoint 2
- [ ] T21 Traceability HTML + handover + memory update

Dependency order: T2 → T3/T4/T5 → T5b → T5c/T5d. Phase 1 tasks are independent of each other except
T9←T8a and T12←T11. T14←T5c, T19←T10+T5d, T20←T11+T13+T15.

## Access conflicts found while mapping views (2026-09-24)
The matrix maps `riuh` → Compliance Officer only. But in the Manual and the Module Structure docx, RIUH
also runs personnel and outputs, and other roles have Manual-assigned duties the matrix doesn't give
them. Applying the matrix literally would lock these out:
- **C1** `riuh` = "—" on Personnel/Tasks, but it's in personnel `MANAGE_ROLES` (Module Structure M3 lists RIUH)
- **C2** `procurement_officer_lib` = "—" on Personnel, but it signs property clearance (`CLEARANCE_ROLES`)
- **C3** `riuh` = View on Research Outputs, but it manages the SENSE list and outputs (Module Structure M8)
- **C4** `university_admin` = View on Budget, but it reviews major-tier realignments (client-confirmed)
- **C5** `project_leader` = View on Disbursement, but it requests realignments. Solved by mapping
  realignments to the `budget` key
- **C6** `project_staff` = View on Compliance, but it files its own AI-use and COI declarations

**Resolution (applied as the T3–T5 rule):** read roles = matrix readers ∪ that view's write roles, and
write lists stay unchanged. The matrix never removes a Manual-assigned duty. Explainable to a panel as:
"the DPMIS matrix is the baseline; LSPU Manual duties are layered on top."

## Matrix wider than code (NOT applied — Carl to decide at Checkpoint 0)
Here the matrix gives "full" (write) to roles the current Manual-driven write lists exclude:
- Project Mgmt / Work Plan writes: matrix adds `drd`, `vprei`, all leaders (+ `project_staff` on work
  plan). Code: `system_admin`, `crc_chair` only
- Budget writes: matrix adds `drd`, `vprei`, `crc_chair`, leaders. Code: admin/finance/procurement
- Research Outputs writes: matrix adds `drd`, `vprei`, `crc_chair`, `program_leader`
- Evaluation writes: matrix adds leaders, `riuh`, `university_admin`. Code: the en-banc panel only (Manual)
- Forecasting trigger: matrix adds `crc_chair`, `procurement_officer_lib`, `university_admin`
- DSS writes: matrix adds `crc_chair`, `university_admin`
Recommendation: keep the code as is for Evaluation (the Manual is explicit about the panel). The rest is
Carl's/client's call.

## R1 — Risk Management has no row in the spec matrix
The spec's section 16 lists Authorized Users = Project Leader, Research Director, Compliance Officer.
Default: add a `risk` key to `MODULE_ACCESS` with full = leader, director, compliance, admin and view =
management. That's taken straight from section 16, plus admin, and management as viewers because
the Module Structure dashboard is "all roles". Researcher/finance get no access. Needs Carl's OK before T5/T17.

## Risks and Mitigations
| Risk | Impact | Mitigation |
|---|---|---|
| Read-gating (T3–T5) breaks frontend pages that currently read freely | High | Do it per app group with checkpoints. List affected frontend pages in the handover |
| New Project statuses break `status="active"` filters (dashboard/risk/DSS) | Med | Existing rows stay `active`. Grep every usage in T8 |
| Role mapping wrong → wrong people locked out | High | Confirmed (T1). Union rule (C1–C6) prevents Manual duties being lost |
| Scope filtering (T5b–d) hides rows the frontend expects | Med | Directors/admin unaffected. Test each leader/staff page after T5d |
| Scope: ~20 tasks. Too big for one push | Med | Phases are independently shippable. Carl picks the order after Checkpoint 0 |

## Unknowns — checked against `RMIS chap1/RMIS_Complete_Module_Structure_FORApproval.docx` (2026-09-24)
Legend: ✅ answered by the Module Structure docx · 🟡 partly answered / leaning · ❌ not covered · ⚠️ conflicts with the DPMIS docx

1. ✅ **Role mapping.** In the Module Structure docx, "VPRDE/DRD" and "CRC/CRD" show up together as the
   evaluation panel, DSS users, and forecast users. Compliance's primary users are "Research Integrity
   and Assurance Unit, RIUH". Module 10 lists "University Administration" as a separate user. So:
   Director = `drd` + `vprei` + `crc_chair` · Compliance Officer = `riuh` · Management/BOD =
   `university_admin` · Finance = `finance_budget` + `procurement_officer_lib` · Project Leader =
   `program_leader` + `project_leader` + `study_leader` · Researcher = `project_staff`. Carl still needs to OK it.
2. 🟡 **Granular permissions.** Module 1: "permission + row-level scope filtering", and "role determines
   WHAT a user can do while assignment/scope determines WHICH records they can access." Nothing says
   permissions must be editable in an admin UI, so the matrix constant is enough. **NEW GAP it exposes:**
   row-level scope filtering (see below) is required by both docxes and isn't built.
3. 🟡 **Suspend vs deactivate.** Module 1 lists only "provisioning/deactivation". Leaning: suspend =
   the existing `toggle-active`. No new state.
4. ✅ **Project ID.** Module 2: "mandatory NTP/project-code/TOE fields". Keep the manual `project_code`
   (LSPU Faculty Research Number). The unique constraint already satisfies PM-02's "unique project ID".
5. ⚠️ **Proposal → Review → Approval.** CONFLICT. Module 2 explicitly: "Register already-approved
   Programs/Projects/Studies… Begins RMIS's involvement at Notice to Proceed rather than at proposal
   submission… read-only pre-RMIS pipeline reference." The DPMIS docx wants the full proposal
   workflow. Suggested middle ground: read-only reference fields (proposal submitted / reviewed /
   approved dates + reviewing body), no in-system approval workflow. **Client must decide.**
6. 🟡 **DSS allocation.** Module 12: "ranked, criteria-based, and fully explainable funding
   recommendations". Ranking only, no peso amount. Leaning: `DecisionRecord.amount` optional, not computed.
7. ❌ **Risk register scale.** Module 13 has computed "Manual-defined risk triggers" only. No manual
   register at all, so the register is purely a DPMIS addition. Default: 1–5 × 1–5.
   ⚠️ Mild conflict: Module 13's framing is "Manual-defined triggers", while DPMIS adds free-form
   risks. Additive, so it's fine to keep both.
8. ✅ **Document access.** Module 7 users = "All project personnel", and Module 1 = scope-based. So access
   = role (matrix) + project assignment (scope). No per-document sharing.
9. ❌ **Evaluation rubric.** Module 9 says only "annual evaluation-panel scheduling". No rubric. FYI:
   `LSPU Research Docs/019` (ITRC) has a *proposal* rubric (Relevance 10, Novelty 20, Patent/pub
   potential 20, Pertinence 10, Cost-effectiveness 15, Methodology 15, Gender 10; ≥85 minor revision,
   70–84 major, <70 not recommended). But that's for proposals, which are pre-RMIS per #5, not for
   annual project evaluation. Still needs the client.
10. 🟡 **Monitoring indicators.** Module 9/13 already define the indicators the system tracks: months
    since the last monthly report (3/6 escalation), budget used % (70%), deliverables % (70%), overdue
    milestones, personnel changes. Leaning: expose these existing computed values as the "monitoring
    indicators". No new free-form indicator table.
11. ❌ **6Ps.** Module 8 covers only publications, IP, and creative works. No 6Ps. Still needs a
    client/Carl confirm on the DOST 6P list.
12. 🟡 **Researcher budget access.** Module 4's users are "Program/Project Leaders, Budget Officer" (no
    staff), and Module 10 is "All roles (scope-filtered)". Leaning: `project_staff` is blocked from the
    Budget/Disbursement endpoints (matches the DPMIS matrix) but sees their own projects' figures in the
    scope-filtered dashboard.

### New gaps surfaced by this check (both docxes require them, not in `todo.md` yet)
- **Row-level scope filtering** (Module 1: "WHICH records they can access"; Module 10: "scope-filtered").
  Today every read returns all records. `User.scope` (JSONField) exists but nothing reads it.
  Simplest approach: scope = the projects a user leads or is assigned to (via `ProjectAssignment`);
  Director/Admin/Mgmt/Finance/Compliance roles see everything.
- **Multi-role assignment** (Module 1: "multi-role/multi-scope assignment"). `User.role` is a single
  FK. Needs a decision: is one role per user OK for the thesis?

## Audit: RMIS_Clarification_Answers.docx vs built backend (2026-09-24, after commit 80cf678)
Carl: this doc is the project core and must be followed ("must na makikita"). ✅ built · 🟡 partial · ❌ missing

| Q | Client answer | Status |
|---|---|---|
| 1a | Leaders encode compliance, RIUH verifies; CRC read-only campus-wide | ✅ encode/verify · 🟡 CRC campus limit not applied (reads are open to all) |
| 1b | VPREI with DRD; BOR = reference no. only; record who approved | ✅ |
| 1c | Scope levels: University / Campus (CRC, Finance, Procurement) / College (RIUH) / own program-project-study / Staff = own tasks | 🟡 only budget endpoints scoped; campus via `User.scope` (no API to set it); ❌ RIUH college (no college field); other modules unscoped |
| 2 | **Capstone scope: seeded Role_Permission table + read-only permission view screen + user role/scope assignment screen** | ❌ skipped as "future work" under the earlier minimal-RBAC decision — CONFLICTS with the doc |
| 3 | Suspend ≠ deactivate; suspend keeps assignments, **can assign a temporary replacement**; deactivate via personnel change first | ✅ states + deactivate guard · ❌ temporary replacement |
| 4 | Internal auto ID + manual unique code encoded by CRC, format validation | ✅ · 🟡 format pending RDO |
| 5 | Proposal flow outside RMIS, read-only reference | ✅ |
| 6 | Ranking + score; optional advisory peso (rank-ordered fulfillment, LIB + ₱100k dry cap), confirm | ✅ ranking · ❌ indicative allocation (client to confirm) |
| 7 | 5×5, 4 bands, actions (reminder to PL / notice to RIUH+CRC / escalate to VP-DRD) | ✅ scoring · 🟡 actions are text only, no notification |
| 8 | Role + scope + sensitivity; **limited per-doc sharing with expiry, logged** | ✅ sensitivity · ❌ per-doc sharing |
| 9 | Rubric configurable until Appendix B arrives | ✅ |
| 10 | 14 indicators | 🟡 13/14 — AI-use ~20% threshold not tracked (`AIUseDeclaration` has no percentage field) |
| 11 | DOST 6Ps | ✅ |
| 12 | View: Program Leader roll-up, Project Leader own, Study Leader **own study allocation**, Staff none, Procurement = campus procurement items, Finance = campus. Request: **Project Leader encodes LIB**, procurement, realignment | 🟡 Study Leader sees whole project budget (line items aren't per study) · ❌ **Project Leader can't encode LIB** (`budget_lib` MANAGE_ROLES = admin/finance/procurement) |

Also found while auditing (Module Structure M2 lists leaders as work-plan users): **leaders can't create milestones** —
milestone writes are `system_admin`/`crc_chair` only.

Task gaps come from the client UI prototype, not this doc (`rmis-frontend/University Research Operations Website/src/components/PersonnelTasks.tsx`):
For Review status + leader approval (also backed by MIT proposal: "Project Leader approves task and activity submissions"),
priority, estimated/logged hours, started/completed dates, update kinds (update/comment/blocker/completion),
deliverables checklist, tags.

## Phase 3 plan — close the Clarification-Answers audit + prototype task gaps (2026-09-24)
Tasks and acceptance criteria: `tasks/todo.md` → "Phase 3". Order is bottom-up and risk-first.

### Architecture decisions
- **Q2 permission table without a new permission class.** Add `Permission(code, name, module)` + `RolePermission(role, permission)`
  in `accounts`. A data migration seeds them from today's ~33 `*_ROLES` constants: one code per constant, e.g.
  `budget_lib MANAGE_ROLES` → `budget.manage`, so behavior is identical on day one. `HasRole` gets one change: if it's given
  a string, it's a permission code resolved from the DB at request time; a list still works as before. This keeps the
  CLAUDE.md rule "reuse HasRole". Inline checks (`user_role not in X`) switch to `role_can(user, code)`.
  Parity is proven with a script that checks old-constant membership == DB lookup for every code × 12 roles.
- **Screens are the frontend's job.** The backend adds `GET admin/permissions/` (read-only role×permission matrix) and
  `PATCH admin/users/<id>/scope/` (campus / college). Role assignment already exists (`update-role/`). Changes are
  audit-logged by the existing `AuditLogMiddleware`. No permission editor (client: "future enhancement").
- **Scope (Q1c).** Add `Project.college` (the RIUH college level; also unblocks best-performer-by-college). Reuse
  `accounts.permissions.scoped_projects()` everywhere reads are project-bound. Leaders and staff see only their own
  program/project/study (staff: assigned). Campus roles use `scope["campus"]` and RIUH uses `scope["college"]` when set.
  University-wide roles stay unrestricted. Study-leader budget view = line items tagged to their study (`LineItem.study`, nullable).
- **Tasks follow the client prototype** (`PersonnelTasks.tsx`) mapped onto existing codes: pending = To Do, done = Completed,
  plus a new `for_review`. Assignees can't jump to `done`; leaders/assigners approve or return.
- **No push notifications (no Celery).** Q7's "notice to RIUH/CRC / escalate to VP-DRD" becomes a live
  `risk/alerts/` inbox for the requesting user's role and scope, the same live-computed pattern as the risk dashboard.

### Dependency order
P1–P4 (independent, small) → **Q2 gate** → P5 → P6/P7/P8 → P9 → P11 (needs P5 for scope codes) → P12a/b/c → P13–P15.
P11–P15 don't strictly need Q2. If Carl says no to Q2, skip P5–P10 and the rest still applies.

### Risks
| Risk | Impact | Mitigation |
|---|---|---|
| Permission conversion silently changes who can do what | High | Seed from the exact constants + parity script before/after each app group |
| Scope on every module makes frontend pages show fewer rows for leaders/staff | High | Client-mandated (Q1c). Listed per endpoint in handover for the frontend |
| Assignees lose "mark done" (For Review) | Med | Client prototype + MIT proposal require approval. Frontend kanban gets a For Review column |
| DB lookup per request for permissions | Low | One small indexed query; fine at capstone scale |

### Open questions
1. **Q2 go/no-go.** It reverses the earlier "minimal RBAC" decision; the doc says it's capstone scope.
2. Q6 indicative peso allocation: the client itself says "i-confirm". Not planned until confirmed.
3. `Project.college` values: free text (like `campus`) or a fixed list of LSPU colleges (CA, CAS, CBAA, CCJE, CCS, CFND,
   CIHMT, COE, CTE… as seen in the Budget Office summary sheet)? Default: free text.
