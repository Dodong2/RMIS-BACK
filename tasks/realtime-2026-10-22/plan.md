# Implementation Plan: Real-time gaps (LIB workflow, realignment, project tasks, reconnect)

Date: 2026-10-22. Follows `tasks/realtime-2026-10-13/spec.md` (same contract: small "something changed" signal → the
browser refetches through REST, so DRF permissions stay the only gate). Cloudflare tunnel setup is OUT of scope.

## Overview
Real-time today covers Monitoring, Procurement and Quarterly Reports only. The client sees "inconsistent" real-time
because (1) the LIB review chain (Project Leader → CRC Chair → Budget Officer), realignments and project tasks send no
signals, so other users must refresh; (2) the browser stops reconnecting for good when one token refresh fails.

## Architecture Decisions
- **Reuse `realtime/notify.py` as is** (`notify` + `project_audience`, sent on commit). No new infra, still one Daphne
  process + InMemory layer, no Redis.
- **LIB + realignment: explicit calls in the views** (same as `procurement_signal`/monitoring `signal`), because each
  has 1–2 write paths.
- **Tasks: Django `post_save`/`post_delete` receivers** on Task, TaskUpdate, TaskDeliverable. Tasks are written from
  many places (task board, Work Log, review, deliverables, Work Plan), so model-level receivers catch all of them in one
  file. The one `queryset.update()` (personnel change reassignment) gets an explicit notify, since it skips signals.
- **Payload = `{type, id, project}` only.** No status in LIB signals, so a Budget Officer's socket doesn't learn about
  pre-Ready LIBs (client Q10). The refetch still hides them.
- **Frontend: one central event → query-key map** (`lib/realtimeInvalidation.ts`, mounted once). Every page on React
  Query (Budget, Topbar bell, Tasks board, Staff dashboard) updates without touching each page. Only the 2 pages with
  manual `useEffect` loads (Work Plan, Project Detail) get a `useRealtime(..., reload)` line.
- **Reconnect never gives up while logged in.** A failed refresh goes back into the normal backoff (max 30s). Coming
  back online or to the tab reconnects at once.

## Event contract (new)
| Event | Sent when | Audience |
|---|---|---|
| `budget.lib.updated` | LIB created; every review step (submit, start-review, for-checking, ready, start-certification, certify, hold, resubmit) | `project_audience(project, "budget.")` → CRC Chair/Budget Officer/admin roles + project lead |
| `financial.realignment.created` / `financial.realignment.reviewed` | filed (single or bulk) / approved or rejected | `project_audience(project, "financial.", requested_by)` |
| `personnel.task.changed` | task create/edit/delete, Work Log, review, deliverable change, reassignment on personnel change | `project_audience(project, "personnel.", assignee, assigned_by)` |

## Task List
See `todo.md`. Order: T1 (fail-fast, frontend only) → T2–T4 LIB/realignment slice → checkpoint → T5–T6 tasks slice →
final checkpoint.

## Risks and Mitigations
| Risk | Impact | Mitigation |
|---|---|---|
| One Work Log save fires 2–3 `personnel.task.changed` (update + task + deliverables) | Low: a few extra refetches | React Query dedupes in-flight refetches; frontend coalesces same-type events within ~300ms |
| Program leader / study leader not in `project_audience` (leader roles go per user) | Med: they'd still need a refresh on tasks | T5 adds `project.program.lead` and `task.study.lead` users to the task audience |
| Testing on local dev while the client is on prod (shared DB, separate process) | Med: "it didn't update" false alarms | Not a code fix. Test real-time only against the deployed backend, both browsers on prod |
| Redeploy drops all sockets | Low | Existing reconnect + `realtime.reconnected` refetch; T1 makes it reliable |
| Signal receivers slowing writes | Low | `notify` is on_commit + never raises; `project_audience` is one small query |

## Out of scope
- Cloudflare tunnel (Carl's call).
- Risk register / risk-alert bell (alerts are computed on GET; see Open Questions).
- Redis / multiple processes.

## Open Questions
- Risk bell: should it also refetch on `budget.lib.updated`/`personnel.task.changed` (cheap, 1 line in T4)? Default: **no**, not now.
- Line-item edits inside a Draft/On Hold LIB: signal them too? Default: **no**. Only the leader edits then, and the CRC
  Chair can't see the LIB until it is submitted.
