# RMIS Backend — Current Status

## Module we're on
Module 4: Line-Item Budget Management

## Backend status (this repo)
- Module 1 (Auth/RBAC): done, stable. Don't revisit unless something breaks.
- Module 2 (research_projects: Program/Project/Study/Milestone): done, stable.
- Module 3 (personnel app): done, stable.
- Module 4 (budget_lib app): models, serializers, views, urls, and initial migration done; not yet migrated to the DB or tested against a running server.

## What the frontend still needs from this module
- POST/GET /api/budget/budgets/ — create/list line-item budget versions per project, not yet called from frontend
- POST/GET /api/budget/line-items/ — add line items to a budget, not yet called from frontend
- POST /api/budget/budgets/<id>/certify/ — certify a draft budget (finance_budget/system_admin only), no frontend page yet

## Known open questions / decisions pending
- Empty stale placeholder dirs (`budget/`, `compliance/`, `outputs/` at repo root, not registered as Django apps) — flagged to user, left untouched pending their call on cleanup.
- version_number auto-increments per project on create, and creating a new version auto-demotes the prior `is_current` version — an assumption made from context, not explicitly confirmed with client/frontend yet.

## Last thing done in this repo
Scaffolded budget_lib app (LineItemBudget + LineItem models, serializers with institutional/dry-research ₱100k cap validation and >₱50k auto-flagging, certify endpoint, urls), wired into settings/urls, generated migration 0001. `manage.py check` passes.

## Next thing to do in this repo
Run `python manage.py migrate`, then smoke-test the endpoints (create budget → add line items → certify) against a real project record.