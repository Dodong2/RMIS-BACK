# TODO: 2026-10-01 Client Changes

Plan: `plan.md` (same folder). Spec: `docs/ideas/client-changes-2026-10-01.md`. BE = rmis-backend, FE = rmis-frontend.
Every task: BE `manage.py check` + `makemigrations --check` + focused tests; FE `npx tsc -b` + eslint + `npm run build`.

## Resume here (paused 2026-10-01 end of day)
- Done and committed: T1–T10 plus the added T5b (names) and T8b (strict project read scope). Branch
  `feat/client-changes-2026-10-01` in both repos, **not pushed**, not merged to main.
- Dev/Supabase DB already has migrations `accounts.0014`, `research_projects.0007`, `0008` and `monitoring.0004` applied.
- 2026-10-02: client follow-up F1–F3 done (peso inputs, SF-017 Appendix E, SF-16 Appendix F).
- 2026-10-02: N1–N5 done (task e-mails, % completed, calendar, accomplishment report, reminders command);
  migrations `personnel.0007` + `reports.0003` applied.
- 2026-10-02: Phase 3 (T11–T13) and Phase 4 (T14–T17) done; migration `personnel.0008` (Task.milestone) applied.
  Carl tests Checkpoints B, C and D together with the updated testing guide.
- Next: **Checkpoint B** (Carl reviews the whole
  registration flow, manual + Excel, as project_leader and crc_chair).
- Working rules: commit per task once verified; ask before migrating the shared DB or pushing. Local check servers:
  Django `runserver 8002` + Vite `5173` (`.env.local` points at 8002); `:8001` is the production container, don't
  touch it. Stop dev servers before the full test suite (Supabase pool max 15).
- Open notes for Carl: Leader Load page still shows "Active Programs"; manual-mode preview has no 6Ps/Work Plan
  (no wizard input for them); 2 of 9 accounts may still lack names until the admin fills them in.

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
- [x] BE: `UserListSerializer` gains `full_name` (first + last, fallback email)
- [x] FE: reusable searchable `UserPicker` (search name/email, all active users from `users/by-role/`), with
      "use typed name" fallback for non-accounts (e.g. "EIU Coordinators")
- [x] Picking an account saves `user` + `name` on the team row; free text saves `name` only
- Verify: register with 1 account member + 1 free-text group; both appear on the project page
- Files: BE `accounts/serializers.py`; FE `src/components/common/UserPicker.tsx` (new), `src/types/auth.ts`,
  `src/pages/RegisterProjectPage.tsx`
- Deps: T4

### T5b (BE+FE) Account names for the pickers — added 2026-10-01 · S
No account had a first/last name, so pickers and the Annex A auto-fill would show e-mails (Carl chose option 1).
- [x] Sign-up asks for first and last name (required); `auth/register/` saves them
- [x] `PATCH admin/users/<id>/profile/` (accounts.manage_users) edits name, office, position; admin user detail has
      "Edit Name, Office, and Position"
- Files: BE `accounts/views.py`, `serializers.py`, `urls.py`, `tests.py`; FE `src/pages/RegisterPage.tsx`,
  `src/pages/admin/UsersListPage.tsx`, `src/lib/authApi.ts`, `src/types/auth.ts`

### T6 (BE+FE) Study components — #7 · M
- [x] BE: `Study.lead` nullable (migration); lead role check only when a lead is given; importer accepts a blank lead
- [x] FE: Classification step has "Study Component Titles" rows (Study 1, Study 2, Add Study); saved as studies after
      the project is created
- [x] Existing Add Study on the project page still works with a lead
- Verify: BE test (study with and without lead); FE register with 2 studies → shown on project page
- Files: BE `research_projects/models.py`, `migrations/`, `serializers.py`, `importer.py`, `tests.py`;
  FE `src/pages/RegisterProjectPage.tsx`, `src/types/research.ts`
- Deps: T4

### T7 (BE+FE) Annex A endorsers — #8 · M
- [x] BE: `ProjectEndorser` model + `project-endorsers/` list/create/detail (projects.register / projects.edit, same
      as team rows); importer turns the Annex A sheet into endorser rows
- [x] FE: "Add Endorser" row: role select (the 12 roles) → user select of that role (auto-filled when only one;
      pick when several) → designation (prefilled from user.position) + date; add more rows
- [x] Project page Registration tab lists endorser rows (old fixed fields shown when there are none)
- Verify: BE test create/list + import; FE register with 2 endorsers of the same role
- Files: BE `research_projects/models.py`, `migrations/`, `serializers.py`, `views.py`, `urls.py`, `importer.py`;
  FE `src/pages/RegisterProjectPage.tsx`, `src/pages/ProjectDetailPage.tsx`, `src/lib/researchApi.ts`,
  `src/types/research.ts`
- Deps: T5 (UserPicker / full_name)
- Note: L-sized across both repos; split BE and FE commits

### T8 (BE+FE) LIB step in registration — #11 · M
- [x] BE: `POST projects/<id>/lib/` (projects.register, own-scope for leaders) creates the draft LIB v1 + line items
      with q1–q4, sharing the importer's budget code; 400 if the project already has a budget
- [x] FE: new wizard step "Budget Requirements (LIB)" before Endorsement: PS/MOOE/CO rows, QTR1–4, row and grand
      totals; posted after the project is created
- [x] BudgetPage shows that draft for the project (no duplicate "Create Budget")
- Verify: BE test as crc_chair and as project_leader; FE register BRIDGI's budget (grand total ₱163,500, the PDF's handwritten correction; the printed ₱144,000 under-adds MOOE)
- Files: BE `research_projects/views.py`, `urls.py`, `importer.py`, `tests.py`; FE `src/pages/RegisterProjectPage.tsx`,
  `src/lib/researchApi.ts`
- Deps: T4

### T8b (BE) Strict project read scope — added 2026-10-01 · M
Found during T8: GET projects/ was IsAuthenticated-only, so a new project leader listed every project (Carl: add it).
- [x] `accounts.permissions.visible_projects`: leaders/staff read only projects they lead or belong to (study/program
      lead, team row with their account, assignment, acting replacement); other roles follow `scoped_projects`
- [x] `ProjectVisibleMixin` on projects list/detail, studies, milestones, status history, team/beneficiary/endorser rows;
      out-of-scope detail → 404
- [x] Full suite: 79 tests, the one failure was the expected 400 → 404 on editing another leader's project (updated)
- Files: `accounts/permissions.py`, `research_projects/views.py`, `research_projects/tests.py`

### T9 (FE) SF-018 preview, manual mode — #9 · M
- [x] `ProposalPreview` modal mirrors BRIDGI_1's layout: I. details table (leader, co-leader, team, dates, cost,
      unit, campus, sector, classification, study components), II–IX sections, V. 6Ps, VII. beneficiaries,
      X. budget table, Annex A endorsement page
- [x] "View" button on Validate & Register opens it from the current form state (nothing saved)
- Verify: fill BRIDGI's data, compare side by side with the PDF
- Files: `src/components/registration/ProposalPreview.tsx` (new), `src/pages/RegisterProjectPage.tsx`
- Deps: T5–T8

### T10 (BE+FE) SF-018 preview, Excel mode — #9 · M
- [x] BE: `POST projects/import/?dry_run=1` parses + validates, returns the would-be payload, writes nothing
- [x] FE: Excel mode "View" button (after choosing a file) opens the same `ProposalPreview`; errors table unchanged
- Verify: BE test asserts row counts unchanged after dry-run; FE preview of the BRIDGI template
- Files: BE `research_projects/views.py`, `importer.py`, `tests.py`; FE `src/lib/researchApi.ts`,
  `src/pages/RegisterProjectPage.tsx`
- Deps: T9

## Client follow-up 2026-10-02 (before Checkpoint B)
Decisions: leader enters % per objective per quarter on the midterm report; SF-16 auto-fills what RMIS has
and leaves the other sections blank; all four export formats follow the same form layout.

### F1 (FE) Peso inputs show commas and decimals · S
- [x] `MoneyInput`: shows `10,000` while typing and `10,000.00` on blur; stores the plain number
- [x] Used for Total Project/Study Cost and the LIB QTR1–4 inputs in the registration wizard
- Files: `src/components/common/MoneyInput.tsx` (new), `src/pages/RegisterProjectPage.tsx`

### F2 (BE+FE) Appendix E follows SF-017 · M
- [x] `MidtermReport.objective_accomplishments` (JSON list of objective + q1–q4 %, 0–100), migration `monitoring/0004`
- [x] Midterm form: objectives prefilled from the project, Q1–Q4 % inputs per objective, add/remove rows
- [x] Export (PDF/Word/Excel/CSV) = SF-017: header, objectives × Q1–Q4 table, 6Ps matrix (item, particulars,
      quantity, remarks = actual), terminal note, Project Leader / Dean signatures; one form per project year
- Files: BE `monitoring/models.py`, `serializers.py`, `reports/forms.py` (new), `renderers.py`, `views.py`, `tests.py`;
  FE `src/components/monitoring/Reports.tsx`, `src/lib/monitoringApi.ts`, `src/types/monitoring.ts`

### F3 (BE) Appendix F follows SF-16 · M
- [x] Export = SF-16 outline: title page from the project; Executive Summary = terminal narrative; Project Rationale =
      Background; Objectives; Significance; Research Methodology; Literature Cited = References; other sections blank
- [x] Appendix E/F exports 404 for projects outside `visible_projects` (T8b scope)
- Files: `reports/forms.py`, `reports/views.py`, `reports/tests.py`

## Client follow-up 2026-10-02 (2): staff notifications and accomplishment report
Decisions: email via Brevo; calendar view in RMIS + Google Calendar link; monthly email to project staff (tasks +
accomplishments); quarterly email to leaders (SF-017 % reminder) and RIUH (summary); sent by a management command
Carl runs from cron; the accomplishment report has no official form, so it is a simple LSPU-headed table.

### N1 (BE) Task assignment email · S
- [x] On task create or assignee change, the assignee gets the task details, a link to the RMIS calendar
      (`/tasks?view=calendar&task=<id>`) and an "Add to Google Calendar" link for the due date
- Files: `personnel/notifications.py` (new), `personnel/views.py`, `personnel/tests.py` (new)

### N2 (BE+FE) % completed on task updates · S
- [x] `TaskUpdate.progress_pct` (0–100, optional), migration `personnel`; `Task.progress_pct` = latest given value
      (100 when done); shown on the task card/detail; the update form has a % input
- Files: BE `personnel/models.py`, `serializers.py`; FE `src/pages/TasksPage.tsx`, `src/types/personnel.ts`

### N3 (FE) Calendar view on the Tasks page · M
- [x] "Calendar" button on the Tasks page (all of the user's tasks, not per project): month grid by due date,
      prev/next month; `?view=calendar&task=<id>` opens that month with the task outlined; a click opens the task
- Files: `src/pages/TasksPage.tsx`

### N4 (BE+FE) Monthly Accomplishment Report · M
- [x] `GET reports/accomplishment/?user=&month=YYYY-MM&file_format=`: per task with activity that month or still
      open: project, task, % completed (latest by month end), hours that month, due date, status; totals; staff and
      leader signatures. Staff see only their own; leaders only staff on their projects
- [x] FE: "Accomplishment Report" (month + format) on the Tasks page for staff. Leaders can call the endpoint with
      `?user=` but have no UI for it yet (not in the report catalog)
- Files: BE `reports/forms.py`, `views.py`, `urls.py`, `tests.py`; FE `TasksPage.tsx`, `src/lib/reportCatalog.ts`

### N5 (BE) Monthly/quarterly reminders · S
- [x] `manage.py send_report_reminders --monthly`: each active project_staff gets open tasks + last month's
      accomplishments; `--quarterly`: project/study leaders get a reminder to update SF-017 % per objective; RIUH gets a
      summary of active projects. Cron lines documented in the command's docstring
- Files: `personnel/management/commands/send_report_reminders.py`, `personnel/tests.py`

### Checkpoint B
- [ ] Register BRIDGI end-to-end as project_leader, manual and Excel, preview matches the PDF
- [ ] Same as crc_chair (all leaders listed, LIB step works)
- [ ] Carl reviews

## Phase 3: Budget and procurement

### T11 (FE) Remove funding source from LIB UI — #12 · S
- [x] No Funding Source field/default/check in the Prepare LIB modal; no Funding Sources tab (also gone from the
      add-item form, the line-item table, the disbursement detail and the Excel template's Budget sheet)
- Verify: prepare a LIB, saves with blank funding_source
- Files: `src/pages/BudgetPage.tsx`
- Deps: none

### T12 (BE+FE) Leader procurement parity — #16 · S
- [x] Reproduce `/procurement` as project_leader vs system_admin; list every difference (403s, empty tabs, hidden UI)
      (2026-10-02: BE already scoped — leader gets own projects/budgets/APP items/requests, 400 on another project's
      item, 403 on status moves; the only UI gap was the hidden Action column)
- [x] Leader sees the same tabs/UI as admin, data limited to own projects; status actions stay officer/admin-only
      (Action column now shown to leaders as "Awaiting Procurement Office" / Released date)
- Verify: as leader, own requests and APP items visible, other projects' not
- Files: `src/pages/ProcurementPage.tsx`, maybe BE `budget_lib/views.py`, `financial_monitoring/views.py`
- Deps: none

### T13 (FE) Procurement officer KPI strip — #17 · S
- [x] KPI cards above the table: Total Requests, Completed (released), Ongoing (requested + processing), Cancelled;
      follow the project filter (plus Delayed and Open Amount; status/delayed filters now narrow only the table)
- Verify: counts match the table as procurement_officer_lib
- Files: `src/pages/ProcurementPage.tsx`
- Deps: T12

### Checkpoint C
- [ ] Builds clean; Carl reviews budget + procurement as leader and procurement officer

## Phase 4: Work plan and tasks

### T14 (BE) Task.milestone, progress, done-gate — #14 · M
- [x] `Task.milestone` FK (nullable, must be the same project)
- [x] Milestone serializer: `tasks_total`, `tasks_done`, `progress_pct`; `?milestone=` filter on tasks
- [x] Milestone → `done` with open tasks → 400; milestones without tasks unaffected
- Verify: `python manage.py test personnel research_projects --keepdb`
- Files: `personnel/models.py`, `migrations/`, `serializers.py`, `views.py`; `research_projects/serializers.py`, tests
- Deps: none

### T15 (FE) Work plan: expandable milestones + responsible picker — #14, #13 · M
- [x] Activities tab lists milestones; each expands to its tasks with a progress bar from `progress_pct`
- [x] "Add task" under a milestone; Done button disabled with a reason while tasks are open
- [x] Responsible Personnel lists project lead + team members with accounts + assignments (names, not emails)
- Verify: milestone with 2 tasks, finish 1 → 50%, can't mark done; finish both → can
- Files: `src/pages/WorkPlanPage.tsx`, `src/lib/researchApi.ts`, `src/lib/personnelApi.ts`, `src/types/*.ts`
- Deps: T14, T5

### T16 (FE) Tasks page: milestone + % completed — #15 · S
- [x] Task form has a Milestone select
- [x] Project selector options/title show "N% tasks completed"
- Verify: % matches done/total for the project
- Files: `src/pages/TasksPage.tsx`
- Deps: T14

### T17 (BE+FE) Overdue milestone alert to project leader — #14 · S
- [x] `risk/alerts/` includes an alert per overdue, not-done milestone for the project's leader (and admin)
- [x] Bell shows it; clicking opens the work plan
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
