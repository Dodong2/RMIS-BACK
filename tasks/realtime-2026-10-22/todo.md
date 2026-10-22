# TODO: Real-time gaps 2026-10-22

Plan + decisions: `tasks/realtime-2026-10-22/plan.md`. Commit per task on main (Carl pushes). No migrations expected.
Backend tests: `venv/bin/python manage.py test <app> --keepdb`. Frontend: `npx vitest run`, `npx tsc -b`, `npm run build`.

## Task 1: Socket reconnect never gives up while logged in (frontend)
**Description:** In `useRealtime.ts`, a failed token refresh after a 4401 currently `return`s and real-time is dead
until reload. Put it back into the normal backoff instead; also reconnect right away on `online` and when the tab
becomes visible again if the socket is closed.
**Acceptance criteria:**
- [ ] 4401 + refresh failure → retries with backoff (max 30s), stops only on `stopRealtime()` (logout)
- [ ] `online` / `visibilitychange` (visible) with no open socket → connects immediately, resets backoff
- [ ] After reconnect, `realtime.reconnected` still fires (pages refetch what they missed)
**Verification:** vitest for the reconnect logic (fake WebSocket + timers); tsc; build.
**Dependencies:** None
**Files:** `src/hooks/useRealtime.ts`, `src/hooks/useRealtime.test.ts`, maybe `src/context/AuthContext.tsx`
**Scope:** S

## Task 2: LIB workflow sends `budget.lib.updated` (backend)
**Description:** After every step in `BudgetReviewView` (submit … certify, hold, resubmit) and after a LIB is created,
notify `project_audience(project, "budget.")` with `{id, project}`.
**Acceptance criteria:**
- [ ] Each successful step sends exactly one `budget.lib.updated` after commit; a refused step (400/403) sends none
- [ ] Recipients include the CRC Chair and Budget Officer role groups and the project lead's user group
- [ ] Payload has no `status`; event added to the contract table in `tasks/realtime-2026-10-13/spec.md`
**Verification:** `manage.py test budget_lib --keepdb` (new `budget_lib/test_realtime.py`, same style as
`monitoring/test_realtime.py`)
**Dependencies:** None
**Files:** `budget_lib/views.py`, `budget_lib/test_realtime.py`
**Scope:** S

## Task 3: Realignment sends `financial.realignment.created` / `financial.realignment.reviewed` (backend)
**Description:** Notify after filing (single or bulk, one signal per request) and after approve/reject.
**Acceptance criteria:**
- [ ] Create (single + bulk) → one `financial.realignment.created`; review → one `financial.realignment.reviewed`
- [ ] Validation errors / 403 send nothing
- [ ] Audience = `project_audience(project, "financial.", requested_by)`
**Verification:** `manage.py test financial_monitoring --keepdb` (extend `financial_monitoring/test_realtime.py`)
**Dependencies:** None
**Files:** `financial_monitoring/views.py`, `financial_monitoring/test_realtime.py`
**Scope:** S

## Task 4: Central event → query-key refetch (frontend)
**Description:** New `lib/realtimeInvalidation.ts` with a map of event type → React Query keys, plus a small hook
mounted once (AppProviders/AuthContext). `budget.lib.*` → budgets, budget-summary, projects, financial;
`financial.realignment.*` → financial, budgets. Same-type events within ~300ms coalesce. The Budget page, LIB list and Topbar bell
then update for the CRC Chair / Budget Officer / Project Leader without a refresh.
**Acceptance criteria:**
- [ ] Project Leader submits → CRC Chair's Budget page + bell show "Awaiting your review" without refresh
- [ ] CRC Chair marks Ready → Budget Officer sees it; Hold → Project Leader sees "On Hold"
- [ ] Realignment filed → Budget Officer's bell count updates; reviewed → leader's Realignment tab updates
**Verification:** vitest for the mapping/coalescing; tsc; build; manual two-browser check
**Dependencies:** T2, T3
**Files:** `src/lib/realtimeInvalidation.ts`, `src/lib/realtimeInvalidation.test.ts`, `src/components/AppProviders.tsx`
(or `src/context/AuthContext.tsx`)
**Scope:** S–M

## Checkpoint A (after T1–T4)
- [ ] budget_lib + financial_monitoring + realtime tests pass (--keepdb); vitest/tsc/build OK
- [ ] Carl: deploy, then two browsers on prod: full LIB chain PL → CRC Chair → Budget Officer + one Hold, all live
- [ ] Review with Carl before tasks

## Task 5: Task signals `personnel.task.changed` (backend)
**Description:** `personnel/signals.py` with post_save/post_delete receivers on Task, TaskUpdate, TaskDeliverable,
registered in `PersonnelConfig.ready()`. Audience = `project_audience(project, "personnel.", assignee, assigned_by)`
plus program lead and study lead users. Explicit notify after the bulk `.update()` reassignment in the personnel-change
serializer.
**Acceptance criteria:**
- [ ] Create/edit/delete task, Work Log (incl. auto-Done at 100%), review approve/return and deliverable tick each
      send `personnel.task.changed` with `{id, project}` after commit
- [ ] Assignee (project_staff), assigner and project lead are in the audience; other projects' staff are not
- [ ] Personnel-change reassignment sends one `personnel.task.changed` per affected project
**Verification:** `manage.py test personnel --keepdb` (new `personnel/test_realtime.py`); then research_projects +
dashboard (they read tasks)
**Dependencies:** None (independent of T2–T4)
**Files:** `personnel/signals.py`, `personnel/apps.py`, `personnel/serializers.py`, `personnel/test_realtime.py`
**Scope:** M

## Task 6: Task pages refetch live (frontend)
**Description:** Add `personnel.task.*` → tasks, task-updates, workload, milestones, dashboard-budget to the T4 map (covers Tasks
board, Staff dashboard, bell). Add `useRealtime(TASK_EVENTS, reload)` to Work Plan and Project Detail (manual
`useEffect` loads), only when `msg.project` is the open project.
**Acceptance criteria:**
- [ ] Staff logs work → leader's Tasks board, Work Plan % and Project Detail milestone cards update without refresh
- [ ] Leader assigns/edits a task → staff's dashboard and task list update without refresh
- [ ] An event for another project doesn't reload the open Work Plan
**Verification:** vitest (map); tsc; build; manual two-browser check (leader + project_staff)
**Dependencies:** T4, T5
**Files:** `src/lib/realtimeInvalidation.ts`, `src/hooks/useRealtime.ts` (TASK_EVENTS), `src/pages/WorkPlanPage.tsx`,
`src/pages/ProjectDetailPage.tsx`
**Scope:** M

## Checkpoint B (complete)
- [ ] Full backend suite `manage.py test --keepdb` OK; vitest/tsc/build OK
- [ ] Carl: deploy; two browsers on prod (NOT local, shared DB but separate process) for LIB, realignment, tasks
- [ ] Update memory + client notes
