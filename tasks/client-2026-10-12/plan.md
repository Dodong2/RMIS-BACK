# Implementation Plan: Completed procurement becomes a disbursement

## Problem
How might we make a Completed procurement request count as the project's "Actual" spending, so the Disbursement
Ledger, Budget Utilization, Variance Analysis and Budget Management > Utilization all move together?

Today the two are separate. Every one of those tabs reads only the `Disbursement` table, which Finance fills by hand
through "Record Disbursement". Completing a procurement request changes nothing. Example: PR-0008 (₱25,000) on
LSPU-RD-2024-001 (₱4,800,000) is Completed, and the project still has 0 disbursements.

Basis: the Module Structure doc says "LSPU has no separate Disbursement unit — fund release is coordinated through the
Procurement Office", and the Alignment doc lists Module 5 as "Procurement-status tracking … Approved–Adjusted–Actual
audit trail".

## Decisions (Carl, 2026-10-12)
- When the Procurement Officer sets a request to **Completed**, the system auto-posts one `Disbursement`:
  - the amount is the **request amount**
  - the date is the completion date
  - the reference is `PR-0008`
  - `recorded_by` is the officer
  - it carries a link back to the request
- Only Completed triggers this. Ready for Release does not.
- **Manual "Record Disbursement" stays** for spending that didn't go through procurement (e.g. PS/honoraria). The
  ledger labels each row Procurement or Manual.
- Budget Utilization keeps listing **every** line item, including fully used ones. It already does.
- Realignment tab: approved requests already stay listed in the code (e.g. BOR Approved #14). We only verify this while
  testing.

## Why auto-post, not computed
Ledger, summary/variance, dashboard, forecasting (ARIMA series) and risk all read `Disbursement`. One record per
completed request fixes all of them with a single backend change. Computing "Actual = disbursements + completed
procurement" would have to be repeated in each of those places.

## Not doing
- Partial or actual-amount entry at completion: Carl chose the request amount.
- Reversing a disbursement: Completed is terminal, and there's no un-complete action.
- Real-time updates: Carl decides after testing. For now the page refreshes on navigation and after a status change.
- Commitments (open requests lowering Available): the client asked for a deduction only once disbursed. Open requests
  already block over-requesting.

## Tasks

### Task 1 (backend): auto-post on Completed
- `Disbursement.procurement_request`: a nullable OneToOne to ProcurementRequest (PROTECT). It goes in migration
  `0007_disbursement_procurement_request`, which is schema only.
- `ProcurementStatusView`: on `completed`, create the Disbursement inside the same transaction.
- `DisbursementSerializer` exposes `procurement_request` (read-only).
- Acceptance:
  - Completing a request creates exactly 1 disbursement with the same line item and amount.
  - The budget summary `actual` goes up and `available` goes down by the request amount.
  - Non-completed statuses create nothing.
- Verify: `python manage.py test financial_monitoring --keepdb`.
- Files: `financial_monitoring/models.py`, `views.py`, `serializers.py`, `tests.py`, `migrations/0007`.

### Task 2 (backend): backfill already-completed requests
- Migration `0008_backfill_procurement_disbursements` is data only, kept separate from 0007 because of the "pending
  trigger events" lesson. It creates a disbursement for each completed request that has none:
  - date = `completed_at`, or `requested_at` if `completed_at` is empty
  - `recorded_by` = `updated_by`, or `requested_by` if `updated_by` is empty
- Acceptance: after migrating, PR-0008 shows in LSPU-RD-2024-001's ledger as ₱25,000.
- Files: `financial_monitoring/migrations/0008`.

### Task 3 (frontend): ledger source + refresh
- `types/financial.ts`: add `procurement_request: number | null`.
- Ledger: a Source column ("Procurement · PR-0008" or "Manual"), and the same in the transaction detail.
- ProcurementPage: after a status change, also invalidate `financialAll`, `budgetSummaries` and `budgets`, so the
  Financial Monitoring and Budget pages show the new figures.
- Verify: `npx tsc -b`, eslint, build.
- Files: `src/types/financial.ts`, `src/pages/DisbursementsPage.tsx`, `src/pages/ProcurementPage.tsx`.

### Checkpoint (Carl)
1. Migrate: `python manage.py migrate financial_monitoring` (0007 + 0008).
2. Financial Monitoring > LSPU-RD-2024-001:
   - Ledger shows PR-0008, ₱25,000. Transactions = 1. Available = ₱4,775,000.
   - Utilization and Variance show the ₱25,000 on that line item.
3. Budget Management > same project > Utilization shows the same Actual/Available.
4. Complete another request (e.g. PR-0010 after Received): the ledger adds a row, and the counts and balances update.
5. Realignment tab: the approved/BOR-approved request is still listed.

## Risks
| Risk | Impact | Mitigation |
|---|---|---|
| A realignment approved after the request lowered the item below the request amount | Low | The posting still happens (the money was spent). Available shows negative in red, which flags it. |
| Shared prod DB | Med | Claude never migrates. Carl runs it. |
