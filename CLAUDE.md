# RMIS Backend (Django)

## Stack
Django 6 + DRF + SimpleJWT (dj-rest-auth) + Postgres (Supabase-hosted) + Brevo for transactional email.

## Run
```
source venv/bin/activate
python manage.py runserver
```
Migrations: `python manage.py makemigrations <app>` only. Never run `migrate`: local and prod share one DB. Give Carl the command (`./venv/bin/python manage.py migrate`) and he runs it.

## Tests
- Tests run on a local Docker Postgres, never Supabase: `TEST_DB_HOST=127.0.0.1` in `.env` points `manage.py test` at the container `rmis-testdb` (postgres:17, `127.0.0.1:5433`). Check `docker ps --filter name=rmis-testdb` first; if it's stopped, `docker start rmis-testdb`. The app, `runserver` and `migrate` always stay on Supabase.
- Run `python manage.py test <label> --keepdb`. New migrations are applied to the local test DB automatically at the start of the run, so never `migrate` it by hand. Supabase still gets them only through Carl's `migrate`. A broken migration now fails locally first.
- When a migration file that was already applied locally is edited or deleted, `--keepdb` won't notice. Rebuild the local test DB once with `python manage.py test <label> --noinput` (no `--keepdb`). That deletes only the local `rmis-testdb` copy, about 20 s.

## Apps and what they own
- `accounts` — custom User, Role, auth (email/password + Google-via-Supabase bridge), RBAC (`HasRole` permission class), admin confirmation flow (pending → active)
- `research_projects` — Module 2: Program → Project → Study hierarchy, work-plan milestones. (Named `research_projects`, not `projects` — that name conflicts with an existing module, don't rename back.)

## Conventions
- Every app that needs role-gated writes uses `accounts.permissions.HasRole("<permission code>")` (e.g. `HasRole("budget.certify")`), never a fresh permission class — reuse it. Inline checks use `role_can(user, "<code>")`. Role → permission lives in the DB (`Permission`/`RolePermission`, client clarification Q2); don't gate on `*_ROLES` lists — those constants are only the seed source.
- New permission = add it to `accounts/permission_seed.py`, add a data migration that seeds it (system_admin always included), then run `python scripts/permission_parity.py` (must be 0 differences).
- Identity checks (`role.code == "project_staff"`, lead-role validation) and row scope (`scoped_projects`, `visible_documents`, `User.scope`) stay role-code based — they aren't permissions.
- Role codes are fixed (12 total, seeded via `accounts/management/commands/seed_roles.py`): `system_admin, vprei, drd, riuh, crc_chair, finance_budget, procurement_officer_lib, program_leader, project_leader, study_leader, project_staff, university_admin`. Don't invent new codes without checking this file first.
- New user-facing model fields should be checked against `RMIS_Complete_Module_Structure_FORApproval.docx` and the R&D Manual (both in the `RMIS chap1` folder, add with `/add-dir` when needed) before naming — the client's terminology (e.g. "LSPU Faculty Research Number" for project code) should be preserved.
- Registration/confirmation email logic lives in `accounts/emails.py` using Brevo's REST API directly (no Django email backend). Reuse `send_brevo_email()`.
- No Redis, no Celery — not needed yet. Don't add without discussing first.
- Real-time (2026-10-13, `realtime/`, spec in `tasks/realtime-2026-10-13/spec.md`): Channels + Daphne, ONE process, `InMemoryChannelLayer` (`REDIS_URL` switches to Redis). Notify, then refetch: after a write, call `realtime.notify.notify(groups, "<app>.<thing>.<verb>", id=..., project=...)` — ids only, never model data; it fires on commit and never raises. Project records use `project_audience(project, "<permission prefix>", *user_ids)` (see `monitoring/views.py::signal`). Add each new event to the spec's contract table and to the frontend page's event list. Signals from management commands/cron reach nobody (different process). `CONN_MAX_AGE` is 0 on purpose (ASGI threads).
- Keep serializers simple; validation logic (like leader-concurrency checks) belongs in the serializer's `validate()`, not the view.
- Concurrency (2026-10-12, `config/concurrency.py`, design in `tasks/client-2026-10-12/concurrency-plan.md`): any write that checks state/balance/caps and then saves must run in `transaction.atomic()` and re-read the checked row with `lock()` / `lock_line_items()` (budget row before line items, line items in id order). Generic views use `AtomicMutationMixin`; money/registration creates use `@idempotent` (Idempotency-Key). Every spend checks `uncommitted_balance()`. Tests for these paths: `ConcurrencyTestCase` (real threads, autocommit) — `RMISTestCase` can't catch a missing transaction. Never run two `manage.py test --keepdb` processes at once (same test DB).

## Known simplifications (intentional, don't "fix" without asking)
- JWT returned in response body, stored in frontend localStorage — not httpOnly cookies. Documented trade-off for cross-domain (Vercel/Netlify ↔ Render) simplicity.
- No hard-delete anywhere on User records — only `is_active` toggling. Users are FK'd from research records; deleting would break history.

## Session start
Before trusting `.claude/rules/handover.md` or your own memory as current, run `git log -8 --oneline` and `git status`. If there are commits or uncommitted changes you don't recognize (likely made manually, outside a Claude session), read the diff (`git show <hash>` or `git diff`) to catch up before doing anything else. Don't assume the last thing you remember is still the latest state.