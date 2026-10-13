# Real-time updates (notify, then refetch) — 2026-10-13

## Objective
When one user saves a monitoring record, other logged-in users who care about that project see it without
pressing refresh. The WebSocket only carries a tiny signal; the browser refetches through the existing DRF endpoints,
so every permission rule stays in DRF. Nothing about the existing REST API changes.

## Fixed decisions (Carl, 2026-10-13)
- One Daphne process (`daphne -b 0.0.0.0 -p 8000 config.asgi:application`) behind the Cloudflare Tunnel. No Redis.
- `InMemoryChannelLayer` by default; `channels_redis` only when `REDIS_URL` is set.
- Deployment files (Dockerfile, entrypoint.sh, .dockerignore, requirements.txt) are Carl's. Not touched.
- Auth: SimpleJWT access token in `?token=`. Missing/invalid -> socket closed with code 4401.
- Origin check: `OriginValidator` with `settings.CORS_ALLOWED_ORIGINS`.
- Groups: `user_<id>`, `role_<role code>` (`User.role` is a FK to `Role`, so the group uses `role.code`), `all_users`.
- `notify()` runs in `transaction.on_commit` and never raises.

## Deviations from the pasted plan (flagged)
- Phase 1 was already done in 08240ca as `config/client_ip.py::CloudflareClientIPMiddleware` (also validates the
  value is an IP). Kept as-is instead of a second `config/middleware.py`. Only `CACHES = LocMemCache` is added
  (same as Django's default, so no behavior change).
- 4401: the reference closes before `accept()`. Per the ASGI spec a close before accept becomes an HTTP 403 handshake
  rejection, and browsers then see 1006, not 4401. The consumer accepts first, then closes with 4401.
- Tests use Django's own runner (async test methods + `WebsocketCommunicator`), not pytest-asyncio, so the whole
  suite still runs with one `python manage.py test --keepdb`.

## Event contract (server -> browser), JSON text frames
Every message: `{"type": "<event>", "id": <record id>, "project": <project id>, ...}`. No other model data.

| type | extra | sent when |
|---|---|---|
| `monitoring.report.created` | `kind`: monthly/midterm/terminal | a progress report is submitted |
| `monitoring.report.certified` | `kind`: terminal | RIUH certifies a terminal report |
| `monitoring.evaluation.changed` | | evaluation scheduled, outcome recorded, or a score saved |
| `monitoring.renewal.created` | `status` | renewal application submitted |
| `monitoring.renewal.decided` | `status` | renewal approved/denied |
| `monitoring.extension.created` | `status` | extension request submitted |
| `monitoring.extension.updated` | `status` | extension endorsed/approved/denied |
| `procurement.created` | `status` | leader files a procurement request (added 2026-10-13, Carl's test) |
| `procurement.updated` | `status` | Procurement Office receives / moves status / completes, or the leader resubmits |
| `pong` | | reply to the browser's `{"type": "ping"}` |

Frontend-only (synthetic): `realtime.reconnected`, emitted after every (re)connect so pages refetch once.

Browser -> server: only `{"type": "ping"}` every 25 s (Cloudflare drops idle sockets after ~100 s).

Close codes: 4401 = no/invalid/expired token (frontend refreshes the token, then reconnects); a bad Origin is
rejected at the handshake (403).

Procurement events go to every role holding a `financial.*` permission (leaders/staff excluded), the project lead
and the requester. Frontend: the Procurement page reloads and the bell refetches; bell items deep-link to
`/procurement?request=<id>` (row highlighted) or `/procurement?view=pending` (Procurement Office queue).

### Recipients of monitoring events
- `role_<code>` for every role that holds a `monitoring.*` permission in the DB, except leader roles and project_staff
  (those see only their own projects, so they get it per user instead).
- `user_<project lead>` and `user_<submitter>` of the record.
- The browser ignores events for a project it is not showing, then refetches through DRF anyway, so a signal never
  reveals data the user can't already read.

## Acceptance criteria
Backend (automated):
1. Valid access token + allowed Origin -> connected; `ping` -> `pong`.
2. Missing token and bad token -> accepted then closed with 4401.
3. Origin not in the allow-list -> handshake rejected.
4. A connected user receives a `notify()` sent to their user/role/all_users group after commit.
5. `notify()` inside an `atomic()` block that rolls back sends nothing.
6. `notify()` never raises even when the channel layer fails.
7. Each monitoring write above fires its event to the listed groups; failed writes (400/403) fire nothing.
8. The existing suite still passes; `manage.py check` and `makemigrations --check` clean (realtime has no models).

Frontend (manual, Carl):
9. Two browsers on the Monitoring page, same project: a report submitted in one appears in the other without refresh.
10. After 1 h (access token expiry) the socket reconnects by itself (4401 -> refresh -> reconnect).
11. Logout closes the socket.

## Tasks (one commit each)
1. Phase 1: explicit LocMem `CACHES`. Verify: suite + check.
2. Phase 2: settings (daphne, channels, realtime, ASGI_APPLICATION, CHANNEL_LAYERS, CONN_MAX_AGE=0), realtime app,
   new `config/asgi.py`, tests for criteria 1–6.
3. Phase 3a: monitoring `notify()` calls + tests for criterion 7.
4. Phase 3b (rmis-frontend): `src/hooks/useRealtime.ts`, start/stop in `AuthContext`, Monitoring page reloads on
   events. Verify: `npm run build` + lint.
