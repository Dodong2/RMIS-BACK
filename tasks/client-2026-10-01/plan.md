# Implementation Plan: 2026-10-01 Client Changes (Project Leader Flow + Strict RBAC)

Spec: `docs/ideas/client-changes-2026-10-01.md` (18 client items, numbered #1–#18 there). Spans **rmis-backend** and
**rmis-frontend**; this folder is the single source for both repos. Task checklist: `todo.md` next to this file.
Older plans (`tasks/plan.md` DPMIS alignment here, `rmis-frontend/tasks/` prototype clone) are untouched.

## Overview
Make the Project Leader's whole flow work on their own records: register their own approved project (with study
components, endorsers and the LIB), review it in an SF-018-style preview, then run the work plan as milestones made
of tasks. System Admin keeps full access. Program disappears from the UI only.

## Architecture Decisions
- **Leader registration (#1/#4):** new migration `accounts.0014` adds `project_leader` back to `projects.register`
  (not program/study leaders). On create, a project_leader's `lead` must be themselves. `ensure_leader_keeps` stays
  for edits (code/lead/program still locked after creation).
- **Program (#2):** UI-only removal. Model, FKs, `program_leader` role and the importer's optional Program Code stay.
- **Duplicate code (#3):** new `GET projects/code-available/?code=` (projects.register). A leader's project list is
  scoped, so a client-side check can't see other people's codes. The 400 from `unique` is also mapped to a toast.
- **People pickers (#6/#8/#13):** reuse `GET users/by-role/` (no `code` = all active users; project_leader already
  has `accounts.view_users_by_role`). Add `full_name` (first + last, fallback email) to `UserListSerializer`.
  Team rows keep free-text `name`; picking an account also sets the existing `ProjectTeamMember.user`.
- **Study components (#7):** `Study.lead` becomes nullable (titles only on the form). Lead role check runs only when
  a lead is given.
- **Annex A endorsers (#8):** new child model `ProjectEndorser(project, role_code, user?, name, designation,
  signed_on, order)` on the existing team/beneficiary child-view pattern. Old fixed Annex A fields stay for old
  projects; the Excel importer writes endorser rows from the Annex A sheet.
- **LIB in registration (#11):** `POST projects/<id>/lib/` gated by `projects.register`, reusing the importer's
  budget-creation code. Needed because CRC/DRD/RIUH register but don't have `budget.manage`.
- **Preview (#9):** one `ProposalPreview` component (SF-018 layout) fed by a plain object. Manual mode feeds it the
  form state; Excel mode feeds it the result of `POST projects/import/?dry_run=1` (parse + validate, then roll back).
- **Milestone → tasks (#14):** `personnel.Task.milestone` FK (nullable, same project). Milestone serializer gets
  `tasks_total`, `tasks_done`, `progress_pct`. A milestone can't move to `done` with open tasks. An overdue milestone
  adds an alert to the project leader's bell (`risk/alerts/`).
- **Procurement (#16/#17):** leader gets the admin's page with data scoped by the existing `BudgetScopedMixin`. The
  officer's KPI strip is computed client-side from the request list (completed = released, ongoing =
  requested + processing).
- **Funding source (#12):** removed from the UI only; the column stays (`blank=True` already).

## Dependency Graph
```
accounts.0014 (leader register) ──► T2 frontend register/lead lock ──► T4 wizard gates
users full_name ──► T5 team picker, T7 endorsers, T14 responsible picker
Study.lead nullable ──► T6 study components
ProjectEndorser model ──► T7
projects/<id>/lib/ ──► T8 LIB step
T4–T8 (form shape final) ──► T9 manual preview ──► T10 excel dry-run preview
Task.milestone FK ──► T13 progress/gate ──► T14 work plan UI ──► T15 tasks page
                    └► T16 overdue alert
```

## Task List (detail in `todo.md`)

### Phase 1: RBAC foundation
- T1 Backend: project_leader registers own projects
- T2 Frontend: register button/route for leader, lead locked to self
- T3 Frontend: remove Program from the UI

### Checkpoint A

### Phase 2: Registration wizard
- T4 Per-step required gates, duplicate-code check, campus input removal (#10, #3, #5)
- T5 Team picker: accounts + free text (#6)
- T6 Study components (#7)
- T7 Annex A endorsers (#8)
- T8 LIB step in registration (#11)
- T9 SF-018 preview, manual mode (#9)
- T10 SF-018 preview, Excel mode via dry-run (#9)

### Checkpoint B

### Phase 3: Budget and procurement
- T11 Remove funding source from LIB UI (#12)
- T12 Leader procurement parity (#16)
- T13 Procurement officer KPI strip (#17)

### Checkpoint C

### Phase 4: Work plan and tasks
- T14 Backend: Task.milestone, progress, done-gate (#14)
- T15 Work plan UI: expandable milestones + responsible picker (#14, #13)
- T16 Tasks page: milestone field + % completed in project selector (#15)
- T17 Overdue milestone alert to project leader (#14)

### Checkpoint D

### Phase 5: Polish and wrap-up
- T18 Hover/cursor states on action buttons (#18)
- T19 Handover, docs, memory

### Checkpoint: Complete

## Risks and Mitigations
| Risk | Impact | Mitigation |
|---|---|---|
| Users have no first/last name filled (registration is email-based) | Med | `full_name` falls back to email; pickers search both |
| Leader can lead only 1 active institutional project (concurrency rule) | Med | Fresh leader per test; surface the 400 as a toast |
| Excel dry-run must not leave rows behind | High | `transaction.atomic` + `set_rollback(True)`; test asserts counts unchanged |
| Hiding Program leaves old projects with a program FK | Low | Detail page shows it read-only if set; nothing writes it |
| Milestone done-gate breaks existing milestones that have no tasks | Med | Gate only applies when the milestone has tasks |
| Budget created at registration conflicts with BudgetPage's "Create Budget" | Med | Registration creates version 1 draft; BudgetPage sees an existing draft |
| `ensure_leader_keeps` blocks a leader's own wizard follow-up PATCHes | Low | Follow-up writes are child POSTs, not project PATCHes |

## Open Questions
- If a leader registers, does the CRC still need to confirm the project code? (Clarification Q4: CRC issues it.)
  Not built; flag to client at the presentation.
- The required-field list in T4 is temporary; the client finalizes it. Kept in one constant.

## Verification commands
- Backend: `python manage.py check`, `python manage.py makemigrations --check --dry-run`,
  `python manage.py test <app> --keepdb`
- Frontend: `npx tsc -b`, `npx eslint <touched files>`, `npm run build`
- Manual: Django on :8001, Vite on :5173; test as system_admin, crc_chair, project_leader (fresh), procurement_officer_lib
