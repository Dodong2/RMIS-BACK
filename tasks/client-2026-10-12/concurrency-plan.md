# Concurrency and idempotency: design for approval (2026-10-12)

## Phase 1: Inspect

Stack facts that shape the design:
- **Database.** Postgres on Supabase, reached through the Supavisor host on port 5432 (session mode). That means
  `SELECT ... FOR UPDATE` and transactions behave like plain Postgres.
- **Transactions are opt-in.** `ATOMIC_REQUESTS` is off. Each ORM write autocommits unless the code uses
  `transaction.atomic()`.
- **No locking anywhere.** There is no `select_for_update` in the codebase. Three existing atomic blocks wrap only the
  final writes, not the checks.
- **One worker model.** gunicorn sync workers, one DB, no Redis/Celery, no background jobs.
- **External side effects** are Brevo e-mails:
  - role confirmation (`AssignRoleView`)
  - new-registration notice (`RegisterView`)
  - task assignment (`personnel.notify_assignee`)

  Supabase Storage uploads happen on document create.
- **Existing safety nets** are a handful of unique constraints:
  - `project_code`
  - (project, LIB version)
  - monthly/midterm/evaluation/renewal per period/year
  - AHP pair
  - DSS score/decision

  A collision on any of them is an unhandled `IntegrityError`, which the client sees as an HTTP 500.
- **Tests** use `accounts.testing.RMISTestCase`, a Django `TestCase` that wraps each test in one transaction. We run
  them with `--keepdb`.

Traced flows (request → checks → writes → side effects):
- **Procurement create / resubmit.**
  1. The serializer computes `line_item_balance(item).available - open requests`.
  2. It compares that to the amount.
  3. It INSERTs or UPDATEs the request.

  There is no lock between steps 1 and 3.
- **Procurement receive / status.** The view loads the row, checks the status, then saves. On Completed it also
  INSERTs the Disbursement inside an atomic block. The OneToOne prevents a second disbursement, but a duplicate attempt
  surfaces as a 500.
- **Disbursement create (manual).** Same balance check-then-insert as procurement.
- **Realignment create.** The serializer checks for "no pending request in this project" and checks the source's
  available balance. The view re-checks the batch total per source, then `atomic(save)`. The checks run before the
  atomic block.
- **Realignment review.** The view checks the status is pending, then calls `review_realignment()`. For a BOR "new
  item" request, that function INSERTs a LineItem and then saves the realignment. Approval never re-checks the source
  balance, so if money was spent between request and approval, the source item goes negative.
- **LIB.**
  - Budget create: reads the last version, then +1, demotes `is_current`, INSERTs.
  - Registration LIB step: `exists()`, then create.
  - Line-item create/update/delete: checks the budget is draft. Certify can happen at the same moment.
  - Certify: checks the status, then saves.
- **Registration and leader changes.** `validate_lead_concurrency` COUNTs the lead's active records, compares to the
  Manual cap, then the view INSERTs.
- **Personnel.**
  - Task review: checks `for_review`, then saves and writes a TaskUpdate.
  - Clearance: checks the status, then saves.
  - Complete change: checks `cleared`, then `complete_change()`. That ends the old assignment and INSERTs a new
    ProjectAssignment, which is not idempotent.
- **Monitoring.**
  - Extension action: checks the status, saves, then UPDATEs the project end date.
  - Renewal decide: no status check, so a decision can be overwritten.
  - Terminal certify: no check.
- **Compliance and documents.**
  - Compliance submit/review: status check, then save.
  - Compliance verify: no check, so it re-stamps verified_by.
  - Document review: no check.
- **Accounts.**
  - Assign role: no check. It saves, then sends the Brevo e-mail.
  - Update role, toggle, account status: last write wins.
  - Replacement end: checks, then saves.
- **DSS.** AHP finalize: no status check, so it overwrites weights. Comparisons submit: checks draft, then writes.

## Phase 2: Failure scenarios and design

### Failure scenarios

**F1. Overspend.** Line item Supplies has ₱10,000 available.
1. Leader A requests ₱8,000. At the same time, Finance records a ₱5,000 disbursement on the same item.
2. Both requests read available = ₱10,000, so both checks pass.
3. Both INSERT. Actual becomes ₱13,000 against ₱10,000.

The same race exists for any pair of {procurement create, procurement resubmit, disbursement create, realignment
create, realignment approval}.

**F2. Double approval.** The Budget Officer double-clicks Approve on a BOR "new item" realignment, or two officers
approve it at once.
1. Both requests read `pending_bor`.
2. Both INSERT a new LineItem.

The result is two new items holding the same money.

**F3. Lost update.** Officer 1 sets a renewal to approved, and officer 2 sets it to denied a moment later. The last
write silently wins, with no record of the conflict. Terminal certify, compliance verify, AHP finalize and document
review have the same "re-do overwrites" behaviour.

**F4. Duplicate create on retry.** A leader submits a procurement request and the tunnel times out after the server
committed. The leader clicks Submit again, and two identical requests now exist. Two realignments, two projects or two
disbursements can be created the same way.

**F5. Leader-cap bypass.** Two registrars register two institutional projects for the same leader at the same time.
Both COUNT 0 active records, so both INSERT. The Manual cap (1 institutional) is broken.

**F6. Version race.** Two "Create LIB" requests for one project both compute v2. One gets a 500 from the unique
constraint, and `is_current` can end up on the wrong row.

**F7. Draft/certify race.** A leader adds a line item while the Budget Officer certifies. The item lands inside an
already-certified baseline.

**F8. Double side effect.** Assign Role is clicked twice, so two confirmation e-mails go out. Complete personnel change
is clicked twice, so two assignments are created and tasks are re-assigned twice.

### Mechanisms chosen (smallest safe fit for one Postgres and no Redis)

**M1. Pessimistic row locks around every check-then-act.**
- The whole action runs inside `transaction.atomic()`. The row whose state or balance is checked is re-read with
  `select_for_update(of=("self",))`. `of=self` avoids locking joined rows and avoids Postgres's "FOR UPDATE on the
  nullable side of an outer join" error.
- A concurrent request blocks on the lock until the first one commits. It then re-reads the new state and fails the
  normal validation with a clean 400.
- What gets locked:

  | Check | Row locked |
  |---|---|
  | Balance (F1) | The LineItem(s), in id order |
  | Status transitions (F2, F3, F8) | The record itself |
  | Leader cap (F5) | The lead's User row |
  | LIB version and registration LIB step (F6) | The Project row |
  | Draft vs certify (F7) | The LineItemBudget row |
  | "One pending realignment per project" | The source item's LineItemBudget row |

- Why not optimistic locking (version columns): it needs a column and a migration on ~15 models, and the frontend would
  have to send versions back. Locks are held for milliseconds on a single DB, so contention is not a concern at RMIS
  scale.
- Deadlocks: multi-row locks are taken in ascending pk. A balance check locks the line items before anything else.

**M2. State machines become strict, which is what makes repeats idempotent.**
- A repeated or conflicting transition on an already-moved record returns 400 "already …" and writes nothing.
- Approved behaviour changes:
  - renewal decide: only `pending`
  - terminal certify: only if not certified
  - compliance verify: only if not verified
  - AHP finalize: only `draft`
  - Assign Role: only a pending registration, so the e-mail can't go out twice
- Document review stays re-reviewable, but under a lock.
- Realignment approval re-checks the source's available balance under the lock (stale-state fix).

**M3. An Idempotency-Key header on the five money and registration creates** (procurement request, disbursement,
realignment, project registration, registration LIB step):
- **Contract.** The header is optional, so old clients keep working. Its value is 8–64 chars of `[A-Za-z0-9-]`. The
  frontend generates it once per opened form, so it is derived from the intent and not the attempt.
- **Claim.** INSERT `IdempotencyKey(user, key, method+path, request_hash, state=in_progress)` in its own autocommit
  statement, *before* the work. The unique constraint on (user, key) picks the winner atomically, with no SELECT before
  the INSERT.
- **Duplicate whose claim already exists:**
  - Different path or body hash → **422** "Idempotency key reused with a different request".
  - `succeeded` → **replay** the stored status and body. Nothing is created.
  - `in_progress` and younger than 2 min → **409** "Still processing, refresh before retrying".
  - `in_progress` and older than 2 min → the first attempt died before commit. Its work rolled back, because the
    `succeeded` mark is written in the same transaction as the work. The new request re-claims the key and runs.
- **Work.** It runs in `atomic()`. On a 2xx response the key is marked `succeeded` with the response, inside the same
  transaction. If the work commits, the key says so; if it rolls back, the key never says succeeded.
- **Failure (4xx/5xx/exception).** The claim is deleted, so the user can fix the form and resubmit with the same key.
  The body is then different, and since no `succeeded` row exists there is no 422.
- **Security.** Keys are scoped per user, so nobody can replay another user's response. The request hash is SHA-256 of
  path + canonical JSON. Rows are kept 24h, which is longer than any retry path (no queues or DLQs exist). Expired rows
  for that user are purged when the user claims a new key.

**M4. Uniform conflict error.** A DRF exception handler maps any remaining `IntegrityError` (unique-constraint race),
and Postgres deadlock or serialization failures, to **409** `{"detail": "This record was changed at the same time by
someone else. Refresh and try again."}` instead of a 500. Internal details are logged, not returned.

**M5. Side effects after commit.** The Brevo e-mail in Assign Role moves to `transaction.on_commit`, so a rolled-back
approval never sends mail.

### Expected behaviour

| Situation | Result |
|---|---|
| Two simultaneous requests that each fit but together exceed the balance | First → 201. Second waits on the lock, re-reads, → 400 "exceeds what is still available". |
| Double-click Approve / Certify / Complete / Decide | First → 200. Second waits, sees the new state, → 400 "already …", no writes. |
| Two officers send conflicting decisions | First wins. Second → 400 naming the current state. No silent overwrite. |
| Retry after a timeout (same Idempotency-Key) | The original 201 response is replayed. No second record. |
| Retry while the first attempt is still running | 409. The client refreshes, and the next retry replays. |
| Crash or timeout mid-request | The DB transaction rolls back. The key stays in_progress and is re-claimable after 2 min. No half-written state. |
| Same key, different body | 422. |
| Unique-constraint collision anywhere else | 409 with a friendly message (was 500). |

## Phase 3: Proposed implementation

### Files
Backend:
- `config/concurrency.py` (new, ~80 lines):
  - `lock(queryset, **lookup)` (404-safe `select_for_update(of=self)`)
  - `lock_line_items(*items)` (sorted)
  - `AtomicMutationMixin` (wraps generic create/update/destroy in atomic)
  - `idempotent` view decorator
  - `conflict_exception_handler`
- `config/settings.py`: `REST_FRAMEWORK["EXCEPTION_HANDLER"]`.
- `accounts/models.py` + **`accounts/migrations/0018_idempotencykey.py`**. This is the only migration: one new table,
  no change to existing data.
- `financial_monitoring/serializers.py`, `views.py`: F1, F2, procurement transitions, realignment approval re-check.
- `budget_lib/serializers.py`, `views.py`: F6, F7, certify.
- `research_projects/serializers.py`, `views.py`: F5 lock, registration LIB step, atomic program/project/study writes,
  idempotent project create.
- `personnel/views.py`, `serializers.py`: task review, clearance, complete change, leader-change create.
- `monitoring/views.py`: extension, renewal (pending only), terminal certify (once).
- `compliance/views.py`: submit, review, verify (once).
- `document_management/views.py`: review under a lock.
- `accounts/views.py`: assign role (pending only, e-mail on_commit), update role, toggle, account status, replacement
  end.
- `decision_support/views.py`: finalize (draft only), comparisons (lock run).

Frontend (rmis-frontend):
- `src/lib/financialApi.ts`, `researchApi.ts`, `budgetApi.ts`: optional `idempotencyKey` argument sent as a header.
- The five create forms: `const [key] = useState(() => crypto.randomUUID())`, one key per opened form.

### Tests
Sequential, inside `RMISTestCase`:
- Each strict transition: a second call → 400 and no extra writes. Covers renewal, terminal, verify, AHP, assign role,
  complete change, task review, extension, certify and procurement.
- Realignment approval with an insufficient source balance → 400.
- Idempotency:
  - replay returns the same id and creates one row
  - same key with a different body → 422
  - a failed request doesn't store the key, so the corrected resubmit works
  - another user's key is not visible to me
  - a stale in_progress row gets re-claimed
- `IntegrityError` → 409 via the handler.

**Real concurrency**, in a new `ConcurrencyTestCase(TransactionTestCase)`: threads with their own DB connections,
released together with a `threading.Barrier`. To make the race deterministic instead of luck-based, the check is
widened with a patched `time.sleep` inside the balance / status read. **Without locks these tests fail. That is the RED
step, and I'll show it.**
1. Two procurement requests that together exceed a line item → exactly one is created; actual ≤ adjusted.
2. Procurement request + manual disbursement on one item → never overspends.
3. Two concurrent approvals of a BOR "new item" realignment → exactly one new LineItem.
4. Two concurrent "Completed" calls → one Disbursement, and the other is a 400 (not a 500).
5. Two concurrent registrations for one institutional leader → one succeeds.
6. Two concurrent requests with the same Idempotency-Key → one record. The other gets a replay or a 409.

### Why it stays correct under concurrency
- Every invariant check reads its inputs *after* acquiring the row lock, inside the same transaction that writes.
- Postgres guarantees that only one transaction holds `FOR UPDATE` on a row. The other blocks, and on wake it
  re-reads the committed data (READ COMMITTED re-evaluates the locked row).
- Every writer that can change a given invariant locks the same row:
  - All writers that reduce a line item's available balance lock that LineItem: procurement create/resubmit,
    disbursement, realignment create (source) and realignment approval (source + destination).
  - All writers that count a leader's load lock that User.
  - All transitions on a record lock that record.
- The idempotency claim relies on a unique-constraint INSERT, which is atomic in Postgres. Completion is written in the
  same transaction as the effect, so the key can never claim success for work that rolled back.

### Remaining limitations (to report honestly after implementing)
- Only the endpoints listed above are protected. Django admin and the shell bypass them, which is acceptable because
  only Carl uses those.
- Idempotency keys cover only the five creates. Other creates rely on unique constraints (→ 409) and the frontend's
  disabled buttons.
- A key is per opened form. Closing and reopening the form makes a new key, by design, because that is a new intent.
- Report and dashboard reads are not snapshot-consistent across tables. That's fine for display.
- Concurrency tests need the real Postgres test DB; they can't run on SQLite. They are slower (TransactionTestCase).
