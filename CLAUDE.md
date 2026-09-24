# RMIS Backend (Django)

## Stack
Django 6 + DRF + SimpleJWT (dj-rest-auth) + Postgres (Supabase-hosted) + Brevo for transactional email.

## Run
```
source venv/bin/activate
python manage.py runserver
```
Migrations: `python manage.py makemigrations <app> && python manage.py migrate`

## Apps and what they own
- `accounts` — custom User, Role, auth (email/password + Google-via-Supabase bridge), RBAC (`HasRole` permission class), admin confirmation flow (pending → active)
- `research_projects` — Module 2: Program → Project → Study hierarchy, work-plan milestones. (Named `research_projects`, not `projects` — that name conflicts with an existing module, don't rename back.)

## Conventions
- Every app that needs role-gated writes uses `accounts.permissions.HasRole([...])`, never a fresh permission class — reuse it.
- Role codes are fixed (12 total, seeded via `accounts/management/commands/seed_roles.py`): `system_admin, vprei, drd, riuh, crc_chair, finance_budget, procurement_officer_lib, program_leader, project_leader, study_leader, project_staff, university_admin`. Don't invent new codes without checking this file first.
- New user-facing model fields should be checked against `RMIS_Complete_Module_Structure_FORApproval.docx` and the R&D Manual (both in the `RMIS chap1` folder, add with `/add-dir` when needed) before naming — the client's terminology (e.g. "LSPU Faculty Research Number" for project code) should be preserved.
- Registration/confirmation email logic lives in `accounts/emails.py` using Brevo's REST API directly (no Django email backend). Reuse `send_brevo_email()`.
- No Redis, no Celery — not needed yet. Don't add without discussing first.
- Keep serializers simple; validation logic (like leader-concurrency checks) belongs in the serializer's `validate()`, not the view.

## Known simplifications (intentional, don't "fix" without asking)
- JWT returned in response body, stored in frontend localStorage — not httpOnly cookies. Documented trade-off for cross-domain (Vercel/Netlify ↔ Render) simplicity.
- No hard-delete anywhere on User records — only `is_active` toggling. Users are FK'd from research records; deleting would break history.

## Session start
Before trusting HANDOVER.md or your own memory as current, run `git log -8 --oneline` and `git status`. If there are commits or uncommitted changes you don't recognize (likely made manually, outside a Claude session), read the diff (`git show <hash>` or `git diff`) to catch up before doing anything else. Don't assume the last thing you remember is still the latest state.