# TODO: 2026-10-01 Client Changes

Plan: `plan.md` (same folder). Spec: `docs/ideas/client-changes-2026-10-01.md`. BE = rmis-backend, FE = rmis-frontend.
Every task: BE `manage.py check` + `makemigrations --check` + focused tests; FE `npx tsc -b` + eslint + `npm run build`.

## Phase 1: RBAC foundation

### T1 (BE) project_leader registers own projects — #1, #4 · S
- [x] Migration `accounts/0014`: `project_leader` gets `projects.register` (reversible); `REGISTRATION_ROLES` +
      `permission_seed` updated
- [x] Creating a project as project_leader with `lead` ≠ self → 400; with `lead` = self → 201
- [x] program_leader/study_leader still 403 on POST `projects/`; leader edit restrictions (`ensure_leader_keeps`) unchanged
- Verify: `python manage.py test research_projects accounts --keepdb`
- Files: `accounts/migrations/0014_*.py`, `accounts/permission_seed.py`, `research_projects/views.py`,
  `research_projects/serializers.py`, `research_projects/tests.py`
- Deps: none

### T2 (FE) Register button + lead locked for leader — #1, #4 · S
- [x] `project_leader` added to `REGISTRATION_ROLE_CODES`; "Register Approved Project" button and `/projects/new` work
- [x] As project_leader, the Project Leader field shows only their own account (preselected, disabled)
- [x] As admin/CRC, the field lists all project leaders
- Verify: log in as fresh project_leader, register → lands on project page
- Files: `src/lib/roles.ts`, `src/App.tsx`, `src/pages/RegisterProjectPage.tsx`
- Deps: T1

### T3 (FE) Remove Program from the UI — #2 · S
- [x] No Register Program button, programs table/tab, `/programs/new` route, or Parent Program field anywhere
- [x] Project detail still shows an existing program read-only (old data), nothing writes it
- Verify: grep `RegisterProgramPage|getPrograms` has no live UI use; build clean
- Files: `src/App.tsx`, `src/pages/ProjectsPage.tsx`, `src/pages/RegisterProjectPage.tsx`,
  `src/pages/RegisterProgramPage.tsx` (delete), `src/pages/ProjectDetailPage.tsx`
- Deps: none

### Checkpoint A
- [ ] BE tests pass, FE builds clean
- [ ] Leader registers own project; admin sees all leaders; no Program UI left
- [ ] Carl reviews

## Phase 2: Registration wizard

### T4 (BE+FE) Step gates, duplicate code, campus input — #10, #3, #5 · M
- [x] BE: `GET projects/code-available/?code=` → `{available: bool}` (projects.register)
- [x] FE: `STEP_REQUIRED` constant (one place): Details = project code; Team = campus; Classification = sector;
      Proposal = ≥1 objective; Beneficiaries = every added row complete; Endorsement = NTP No.; Validate = none
- [x] Next is blocked with inline "Required" until the step's fields are filled; Previous and clicking a done step
      always work; the step header can't jump forward past an incomplete step
- [x] Leaving step 1 with a taken code → toast "Project code already exists"; a 400 on submit shows the same toast
- [x] Campus free-text input removed; highlighted card is the only value
- Verify: BE test for code-available; FE manual walk-through hitting every gate
- Files: BE `research_projects/views.py`, `urls.py`, `tests.py`; FE `src/lib/researchApi.ts`,
  `src/pages/RegisterProjectPage.tsx`
- Deps: T2

### T5 (BE+FE) Team picker: accounts + free text — #6 · M
- [ ] BE: `UserListSerializer` gains `full_name` (first + last, fallback email)
- [ ] FE: reusable searchable `UserPicker` (search name/email, all active users from `users/by-role/`), with
      "use typed name" fallback for non-accounts (e.g. "EIU Coordinators")
- [ ] Picking an account saves `user` + `name` on the team row; free text saves `name` only
- Verify: register with 1 account member + 1 free-text group; both appear on the project page
- Files: BE `accounts/serializers.py`; FE `src/components/common/UserPicker.tsx` (new), `src/types/auth.ts`,
  `src/pages/RegisterProjectPage.tsx`
- Deps: T4

### T6 (BE+FE) Study components — #7 · M
- [ ] BE: `Study.lead` nullable (migration); lead role check only when a lead is given; importer accepts a blank lead
- [ ] FE: Classification step has "Study Component Titles" rows (Study 1, Study 2, Add Study); saved as studies after
      the project is created
- [ ] Existing Add Study on the project page still works with a lead
- Verify: BE test (study with and without lead); FE register with 2 studies → shown on project page
- Files: BE `research_projects/models.py`, `migrations/`, `serializers.py`, `importer.py`, `tests.py`;
  FE `src/pages/RegisterProjectPage.tsx`, `src/types/research.ts`
- Deps: T4

### T7 (BE+FE) Annex A endorsers — #8 · M
- [ ] BE: `ProjectEndorser` model + `project-endorsers/` list/create/detail (projects.register / projects.edit, same
      as team rows); importer turns the Annex A sheet into endorser rows
- [ ] FE: "Add Endorser" row: role select (the 12 roles) → user select of that role (auto-filled when only one;
      pick when several) → designation (prefilled from user.position) + date; add more rows
- [ ] Project page Registration tab lists endorser rows (old fixed fields shown when there are none)
- Verify: BE test create/list + import; FE register with 2 endorsers of the same role
- Files: BE `research_projects/models.py`, `migrations/`, `serializers.py`, `views.py`, `urls.py`, `importer.py`;
  FE `src/pages/RegisterProjectPage.tsx`, `src/pages/ProjectDetailPage.tsx`, `src/lib/researchApi.ts`,
  `src/types/research.ts`
- Deps: T5 (UserPicker / full_name)
- Note: L-sized across both repos; split BE and FE commits

### T8 (BE+FE) LIB step in registration — #11 · M
- [ ] BE: `POST projects/<id>/lib/` (projects.register, own-scope for leaders) creates the draft LIB v1 + line items
      with q1–q4, sharing the importer's budget code; 400 if the project already has a budget
- [ ] FE: new wizard step "Budget Requirements (LIB)" before Endorsement: PS/MOOE/CO rows, QTR1–4, row and grand
      totals; posted after the project is created
- [ ] BudgetPage shows that draft for the project (no duplicate "Create Budget")
- Verify: BE test as crc_chair and as project_leader; FE register BRIDGI's budget (grand total ₱144,000)
- Files: BE `research_projects/views.py`, `urls.py`, `importer.py`, `tests.py`; FE `src/pages/RegisterProjectPage.tsx`,
  `src/lib/researchApi.ts`
- Deps: T4

### T9 (FE) SF-018 preview, manual mode — #9 · M
- [ ] `ProposalPreview` modal mirrors BRIDGI_1's layout: I. details table (leader, co-leader, team, dates, cost,
      unit, campus, sector, classification, study components), II–IX sections, V. 6Ps, VII. beneficiaries,
      X. budget table, Annex A endorsement page
- [ ] "View" button on Validate & Register opens it from the current form state (nothing saved)
- Verify: fill BRIDGI's data, compare side by side with the PDF
- Files: `src/components/registration/ProposalPreview.tsx` (new), `src/pages/RegisterProjectPage.tsx`
- Deps: T5–T8

### T10 (BE+FE) SF-018 preview, Excel mode — #9 · M
- [ ] BE: `POST projects/import/?dry_run=1` parses + validates, returns the would-be payload, writes nothing
- [ ] FE: Excel mode "View" button (after choosing a file) opens the same `ProposalPreview`; errors table unchanged
- Verify: BE test asserts row counts unchanged after dry-run; FE preview of the BRIDGI template
- Files: BE `research_projects/views.py`, `importer.py`, `tests.py`; FE `src/lib/researchApi.ts`,
  `src/pages/RegisterProjectPage.tsx`
- Deps: T9

### Checkpoint B
- [ ] Register BRIDGI end-to-end as project_leader, manual and Excel, preview matches the PDF
- [ ] Same as crc_chair (all leaders listed, LIB step works)
- [ ] Carl reviews

## Phase 3: Budget and procurement

### T11 (FE) Remove funding source from LIB UI — #12 · S
- [ ] No Funding Source field/default/check in the Prepare LIB modal; no Funding Sources tab
- Verify: prepare a LIB, saves with blank funding_source
- Files: `src/pages/BudgetPage.tsx`
- Deps: none

### T12 (BE+FE) Leader procurement parity — #16 · S
- [ ] Reproduce `/procurement` as project_leader vs system_admin; list every difference (403s, empty tabs, hidden UI)
- [ ] Leader sees the same tabs/UI as admin, data limited to own projects; status actions stay officer/admin-only
- Verify: as leader, own requests and APP items visible, other projects' not
- Files: `src/pages/ProcurementPage.tsx`, maybe BE `budget_lib/views.py`, `financial_monitoring/views.py`
- Deps: none

### T13 (FE) Procurement officer KPI strip — #17 · S
- [ ] KPI cards above the table: Total Requests, Completed (released), Ongoing (requested + processing), Cancelled;
      follow the project filter
- Verify: counts match the table as procurement_officer_lib
- Files: `src/pages/ProcurementPage.tsx`
- Deps: T12

### Checkpoint C
- [ ] Builds clean; Carl reviews budget + procurement as leader and procurement officer

## Phase 4: Work plan and tasks

### T14 (BE) Task.milestone, progress, done-gate — #14 · M
- [ ] `Task.milestone` FK (nullable, must be the same project)
- [ ] Milestone serializer: `tasks_total`, `tasks_done`, `progress_pct`; `?milestone=` filter on tasks
- [ ] Milestone → `done` with open tasks → 400; milestones without tasks unaffected
- Verify: `python manage.py test personnel research_projects --keepdb`
- Files: `personnel/models.py`, `migrations/`, `serializers.py`, `views.py`; `research_projects/serializers.py`, tests
- Deps: none

### T15 (FE) Work plan: expandable milestones + responsible picker — #14, #13 · M
- [ ] Activities tab lists milestones; each expands to its tasks with a progress bar from `progress_pct`
- [ ] "Add task" under a milestone; Done button disabled with a reason while tasks are open
- [ ] Responsible Personnel lists project lead + team members with accounts + assignments (names, not emails)
- Verify: milestone with 2 tasks, finish 1 → 50%, can't mark done; finish both → can
- Files: `src/pages/WorkPlanPage.tsx`, `src/lib/researchApi.ts`, `src/lib/personnelApi.ts`, `src/types/*.ts`
- Deps: T14, T5

### T16 (FE) Tasks page: milestone + % completed — #15 · S
- [ ] Task form has a Milestone select
- [ ] Project selector options/title show "N% tasks completed"
- Verify: % matches done/total for the project
- Files: `src/pages/TasksPage.tsx`
- Deps: T14

### T17 (BE+FE) Overdue milestone alert to project leader — #14 · S
- [ ] `risk/alerts/` includes an alert per overdue, not-done milestone for the project's leader (and admin)
- [ ] Bell shows it; clicking opens the work plan
- Verify: BE test with an overdue milestone; bell shows it as the leader
- Files: `risk_indicators/services.py`, tests; FE `src/components/layout/Topbar.tsx` (or bell component)
- Deps: T14

### Checkpoint D
- [ ] Milestone → task flow works end-to-end as project_leader; Carl reviews

## Phase 5: Polish and wrap-up

### T18 (FE) Hover/cursor states — #18 · S
- [ ] Every action button/icon button has `cursor-pointer` and a visible hover (shared class in `protoStyles` or
      `index.css`); sweep pages
- Verify: hover through every page as admin
- Files: `src/index.css`, pages with raw buttons
- Deps: none (do last to avoid conflicts)

### T19 Handover, docs, memory · S
- [ ] Both repos' `.claude/rules/handover.md` updated (frontend notes the Option A reversal)
- [ ] Spec checklist: all 18 items mapped to commits
- Deps: all

### Checkpoint: Complete
- [ ] All 18 items done or explicitly deferred; BE suite + FE build clean; Carl sign-off
