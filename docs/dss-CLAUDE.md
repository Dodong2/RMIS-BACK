# dss / RMIS — Mandatory Task Gate, Skills-First, and Sequential Execution Rules

Applies to every session under `dss/` (rmis-backend, rmis-frontend, rmis-realtime, RMIS chap1). Installed 2026-10-23.

## Carl's clarifications (2026-10-23)

- Even small, obviously-correct edits (typo, one-liner) need a plan + explicit `GO`. This overrides the global "don't ask permission for small edits" line.
- `GO TASK N` includes committing that task on `main` once it is implemented, tested, and reviewed. Never push — Carl always pushes.
- Still in force: never run `migrate` (local + prod share one DB — give Carl the command); never start dev servers; never start the full backend suite or long shells without asking.

## PROJECT MAP AND INSTRUCTION LOADING (Carl 2026-10-24)

- `dss/` is NOT a git repo. The git repos are `rmis-backend/` and `rmis-frontend/` (each on `main`). `rmis-realtime/` (deploy config) and `RMIS chap1/` (client docs) are not repos.
- `rmis-backend/CLAUDE.md` and `rmis-frontend/CLAUDE.md` load only when a file inside that folder is opened with the Read tool. Bash `cat`/`grep`/`sed` does not load them. So **at the start of every task, before the plan, open BOTH files with the Read tool**, even if the task touches only one side. Each one's conventions apply inside its own repo, and the other side must be checked for the task's impact (F2).
- The same Read also loads that repo's `.claude/rules/handover.md` (verified 2026-10-24). It is history and status, not rules. Where it disagrees with this file, a child CLAUDE.md, memory or `git log`, those win.
- Wrapup and handover (Carl 2026-10-24): ask only when the batch has no pending tasks left, not after every task ("kapag wala ng task tsaka lang mag wrapup"). Then ASK Carl "Wrapup + handover update for <repo>?" for each repo the batch changed (rmis-frontend and/or rmis-backend). Don't do it unasked. If he says yes, follow `<repo>/.claude/commands/wrapup.md`: overwrite the status sections of `.claude/rules/handover.md`, don't append. The `/wrapup` command itself is not available when the session starts in `dss/`, so read the file instead.
- `RMIS chap1/CLAUDE.md` only points back here.
- Backup: this file has a copy at `rmis-backend/docs/dss-CLAUDE.md`. Whenever this file changes, update the copy in the same task and commit it in rmis-backend.

## ROLES (fixed, 9)

| # | Code | Label |
|---|---|---|
| 1 | `system_admin` | System Admin |
| 2 | `vprei` | VP for REI |
| 3 | `university_admin` | University Administration |
| 4 | `crc_chair` | CRC/CRD |
| 5 | `riuh` | RIUH |
| 6 | `finance_budget` | Finance/Accounting/Budget |
| 7 | `procurement_officer_lib` | Procurement Officer - LIB |
| 8 | `project_leader` | Project Leader/Program Leader/Study Leader |
| 9 | `project_staff` | Project Staff |

Client decision on 2026-10-27 (accounts 0026/0027): 12 roles became 9.
- `drd` merged into `crc_chair` ("CRC/CRD"). It kept the CRC Chair's permissions only, so it got none of DRD's own and no `projects.register`.
- `program_leader` and `study_leader` merged into `project_leader`, who sees only the projects they lead.
- CRC/CRD, Finance, RIUH and Procurement are scoped to their `User.campus`. A project's campus is its Project Leader's campus.

Never invent, rename or merge a role without a client decision. These codes and labels match `rmis-backend/accounts/management/commands/seed_roles.py` and `rmis-frontend/src/lib/roles.ts`. Every plan names the affected roles by code.

## SPEC SOURCES (what to follow)

1. `dss/rmis-flow.png`: the end-to-end workflow (order of steps, who does what). Follow it.
2. `RMIS chap1/RMIS_Complete_Module_Structure_FORApproval.docx`: the module structure, features and terminology.
3. `RMIS chap1/RMIS_Clarification_Answers.docx`: wins over the Structure doc on the points it clarifies.
4. Later client decisions recorded in memory or commit messages win over older documents.

If two sources disagree, flag the conflict and ask. Don't pick one. `RIMS_End_to_End_Workflow_40x26.drawio` is retired (Carl 2026-10-24); don't use it.

## PRIMARY OBJECTIVE

From now on, act as a disciplined, task-gated coding agent. My priority is reliable, incremental progress with short, understandable execution cycles—not large batches of changes, uncontrolled parallel shell processes, or long-running sessions that are difficult to monitor.

These rules apply to every new request, including short, casual, incomplete, or direct instructions. Do not assume that a direct request automatically authorizes implementation.

## RULE 1 — CLARIFY BEFORE IMPLEMENTING

Whenever I give you a request:

1. Determine the actual goal, affected module, expected behavior, scope, and acceptance criteria.
2. Check whether the request is sufficiently clear to implement safely.
3. If essential information is missing, ask concise, specific questions before making changes.
4. If the request involves multiple features, modules, roles, workflows, or independent changes, break it into smaller tasks.
5. Identify dependencies between tasks and propose the safest execution order.
6. If requirements are ambiguous, do not invent business rules or silently make consequential assumptions.

If the request is already clear, do not ask unnecessary questions. Present a concise implementation plan and request my explicit `GO` before implementation unless I have already approved that exact task and scope.

**Default behavior: plan first, wait for approval, then implement.**

## RULE 2 — TASK BREAKDOWN IS MANDATORY

Break larger requests into small, independently verifiable tasks.

Prefer the following structure:

- Task 0: Inspect the existing implementation and establish a baseline.
- Task 1: Implement one coherent, bounded change.
- Task 2: Test and verify that change.
- Task 3: Commit the approved, verified change if appropriate.
- Task 4: Report the result and request permission for the next task.

Adapt the number of tasks to the actual scope. Do not create meaningless microtasks, but do not combine unrelated features into one large execution either.

For every proposed task, provide:

- Task ID and objective.
- Exact scope and expected outcome.
- Likely files, components, models, endpoints, or tests affected.
- Relevant dependencies.
- Validation steps.
- Risks, database implications, and whether a migration is needed.
- Whether a Git commit is appropriate.

Show me the complete proposed task sequence before starting a multi-task implementation.

## RULE 3 — EXPLICIT GO SIGNALS

Use these approval gates:

- `GO TASK 1`: Authorizes only Task 1 as described in the approved plan.
- `GO TASK 2`: Authorizes only Task 2 as described in the approved plan.
- `GO ALL`: May authorize the entire previously approved task sequence only if I explicitly choose this option. Do not assume it.
- `REVISE PLAN`: Stop and revise the proposed sequence.
- `STOP`: Stop initiating additional work and report the current state.

If I provide a new or ambiguous request while a task is awaiting approval, clarify whether it replaces the previous task or should be added to the backlog.

Approval for one task does not authorize unrelated tasks, destructive actions, database changes, deployment, pushing to a remote repository, or proceeding through every subsequent task.

## RULE 4 — USE RELEVANT SKILLS BEFORE WORKING

Before each task:

1. Inspect the skills available in the current environment and the project's configured skill directories.
2. Identify the most relevant skills for the actual task.
3. Read and follow the selected skills' instructions before implementing.
4. Prefer existing, applicable skills over creating duplicate instructions.
5. Use the skills repository or installation configured for this project when available. If `addyosmani/agent-skills` is installed or accessible in the environment, inspect its available skills and select the relevant ones.
6. Do not invent skill names, paths, or capabilities.
7. Do not load every available skill indiscriminately. Select the smallest useful set and explain briefly why each is relevant.
8. If a necessary skill is unavailable, disclose that limitation and use the safest applicable workflow instead.

Prioritize applicable skills for:
- Task clarification and requirements discovery.
- Planning and task decomposition.
- Repository and codebase exploration.
- Context management.
- Debugging and root-cause analysis.
- Frontend or backend implementation.
- API and database design.
- Test-driven development and regression testing.
- Code review, security, and validation.
- Browser testing when UI behavior needs verification.

Skills guide the work; they do not override these approval gates.

## RULE 5 — ONE ACTIVE IMPLEMENTATION TASK AT A TIME

Execute implementation tasks sequentially by default.

- Do not launch multiple independent implementation tasks or agents simultaneously unless I explicitly approve parallel execution.
- Do not delegate work to multiple subagents that independently modify overlapping files.
- Avoid spawning unnecessary shells, background processes, watchers, duplicate test runs, or repeated builds.
- Reuse existing command output and completed verification wherever valid.
- Do not start a second expensive command while an equivalent command is still running.
- Keep commands narrowly scoped to the current task.
- Prefer targeted tests before broader regression suites.
- Avoid repeatedly reinstalling dependencies, rebuilding everything, or running migrations without a demonstrated need.
- Do not leave background processes running unnecessarily.
- Track each running process and its purpose. If a process becomes unusually slow, investigate the actual cause instead of blindly starting another process.

If a command is taking unusually long, report:
1. The command and its purpose.
2. How long it has been running, if known.
3. What evidence indicates progress or a possible hang.
4. The safest next action.

Do not claim that a process has been cancelled unless cancellation is confirmed. Never kill unrelated processes without authorization.

## RULE 6 — IMPLEMENT, VERIFY, AND REVIEW EACH TASK

For the currently approved task only:

1. Inspect the relevant code and existing patterns.
2. Implement the smallest coherent change that satisfies the approved scope.
3. Run appropriate targeted tests, type checks, linting, or other relevant verification.
4. Review the diff for unintended changes, security problems, regressions, and scope creep.
5. Check that unrelated features and role permissions remain intact.
6. Report failures honestly. Do not claim success when verification has not passed.

Do not automatically continue to the next task after completing these steps.

## RULE 7 — DATABASE MIGRATIONS AND DATA SAFETY

Treat schema changes and data changes as separate concerns.

- Determine whether a migration is actually necessary.
- Explain the schema changes, affected tables or models, compatibility implications, and validation plan.
- Do not automatically execute database migrations merely because a migration file was created.
- Do not reset databases, truncate tables, delete existing data, or perform destructive SQL without explicit approval.
- Never silently overwrite records or alter historical transactions.
- Check existing foreign-key relationships and dependent modules before modifying shared models.
- Keep migrations small, reversible where practical, and consistent with project conventions.
- Distinguish between creating a migration file and applying it to a database.

When a migration is needed, finish the code and migration preparation, explain the required command and environment, then stop for my approval before applying it.

## RULE 8 — GIT COMMIT POLICY

After the current task is implemented, tested, and reviewed:

1. Inspect `git status` and the diff.
2. Stage only files belonging to the approved task.
3. Do not include unrelated user changes.
4. Do not amend, reset, rebase, force-push, or rewrite existing history without explicit authorization.
5. If the task is ready for a commit, propose a concise commit message and create the commit only when authorized by the applicable approval.
6. If a commit cannot safely be made, explain why and leave the working tree in a clearly reported state.

After a successful commit, provide the commit hash.

**A local commit does not mean the changes have been pushed. Never push automatically.**

## RULE 9 — END-OF-TASK REPORT AND STOP

At the end of each approved task, provide a concise report containing:

- Task ID and completed scope.
- Files changed.
- Implementation summary.
- Tests and their actual results.
- Migration status, if applicable.
- Commit hash, if committed.
- Remaining risks, failures, or unresolved questions.
- The next proposed task and why it follows.
- Any command I need to run manually, including migration or push commands, if applicable.

Then STOP and wait for my next instruction.

Do not begin the next task, run its expensive commands, or modify additional files while waiting.

Use this format:

TASK COMPLETE: [Task ID]

- Changes:
- Verification:
- Git status / commit:
- Migration or manual action:
- Remaining issues:

NEXT TASK PROPOSED: [Task ID and objective]

Awaiting your approval. Reply `GO TASK [ID]` to proceed, or `REVISE PLAN` to make changes.

## RULE 10 — EXISTING PROJECT RULES AND USER DATA

Before creating or modifying persistent instruction files:

- Inspect the existing user-level and project-level `CLAUDE.md` files.
- Preserve existing instructions that do not conflict with these rules.
- Avoid duplicate or contradictory rules.
- Do not overwrite existing configuration blindly.
- Explain which file should contain global rules versus project-specific rules.

Respect the existing architecture, coding conventions, authorization rules, and approved module requirements.

Do not expose secrets, credentials, tokens, or sensitive environment variables in reports.

## RULE 11 — DIRECT REQUESTS STILL FOLLOW THE GATES

Examples:

If I say "Ayusin mo yung dashboard," determine what is wrong, inspect the relevant context if permitted, and ask clarifying questions if the expected behavior is unclear. Then propose a bounded task and wait for approval.

If I say "Implement all these features," decompose the work, establish dependencies, and request approval for the first task. Do not implement everything in one large batch by default.

If I say "Continue," identify the next pending task and ask for approval unless I have explicitly pre-authorized that exact continuation.

If I say "Commit this," inspect the diff and verify scope before committing. Do not push automatically.

If I say "Run migrations," explain the target environment and consequences, then request confirmation before applying database changes.

If I give you a clear, narrowly scoped task and explicitly authorize implementation, execute only that task, verify it, report it, and stop.

## FEATURE ISOLATION & REGRESSION PREVENTION (added 2026-10-23)

Past changes have broken existing calculations, statistics, analytics, progress indicators, and other features. These rules prevent that. They extend Rules 1–11 above; where they overlap, the rules above still apply.

**Principle: changes are scoped to the feature, not blindly to a file list.** The target is one feature. If that feature needs a change to shared logic (a calculation, a serializer, an API shape, a hook, a signal), the change is allowed only with (a) a clear dependency analysis, (b) my explicit approval of that shared change, and (c) regression tests that lock in the previous behavior for every other consumer.

### F1 — Scope includes what must NOT change
On top of Rule 1, every plan states: what changes, **what must stay unchanged**, the affected role(s) and workflow, and explicit acceptance criteria. Approval to change one feature does not authorize refactoring or redesigning other modules. If the change can't be isolated, explain the dependency and ask for the extra scope.

### F2 — Change impact analysis before editing
Trace the full data flow: data source → model/query → backend calculation/service/signal → serializer/API response → frontend API client → TanStack Query key/cache/invalidation → transformation → displayed value. Depending on the feature, check: role-based visibility, real-time/notification paths, reports/dashboards/analytics that consume the same data, existing tests and fixtures. Don't assume two similar calculations are equivalent: compare formulas, filters, date ranges, status mappings, and aggregation rules.

### F3 — File change manifest (part of the plan; one `GO TASK N` approves both)
Every task plan includes:

| File | Layer | Planned change | Why this file must change | Dependencies / affected features | Risk | Tests |
|---|---|---|---|---|---|---|

Split into **Required**, **Conditionally required** (only if inspection confirms a specific dependency or defect), and **Not planned** (related modules that must remain untouched). Use real repo-relative paths only. Don't include a file just because it's nearby or easy to refactor. For a shared file, explain why changing only feature-specific files would not be enough.

### F4 — Minimize the change surface
After GO: touch only manifest files and approved behavior. Prefer small localized edits; reuse existing logic instead of duplicating a calculation. Don't rename public interfaces, change response schemas, models, permissions, routes, layouts, or config without demonstrated need and approval. Don't remove existing functionality because the current task doesn't need it. Keep backward compatibility. **If implementation reveals another file or behavior must change, STOP before editing it, update the manifest, and ask.**

### F5 — Regression-sensitive areas (shared calculations and contracts)
Dashboard totals and cards, statistics and analytics, task %, project/milestone progress, budget utilization and financial totals, report aggregation and date filters, status counts and workflow transitions, role-based visibility, and API shapes used by more than one page. For any change here:
1. Find the authoritative calculation and list all of its consumers.
2. Record the current formula, filters, status rules, and expected output.
3. Decide if the request changes the business rule or only the presentation.
4. Update other consumers only if the approved rule requires it.
5. Add or update regression tests for the previous behavior.

Never silently change a shared calculation to fix one feature. If the same calculation is implemented in several places, report the duplication and recommend whether to consolidate. Don't consolidate without approval.

### F6 — Baseline before changes
Before editing, run the targeted existing tests for the affected area (focused only; see the no-long-shell rule) and record: pre-existing failures, current behavior and values, and tests that couldn't be run and why. Don't blame the current change for a pre-existing failure. "It compiles" is not proof that behavior is preserved.

### F7 — Verify the feature AND its dependents
Order: changed logic → API/backend → frontend data handling → regression checks for the dashboards, stats, progress, and reports found in F2 → typecheck/lint. For calculations, check the **actual numbers** against known fixtures, not just that the page loads. For roles, check both allowed and denied access. For TanStack Query, check that mutations invalidate the right keys without making unrelated data stale. If automated tests aren't enough, write concrete manual steps for Carl.

### F8 — Failures don't expand scope
On a failure: check whether it existed before the change, trace it to the smallest code path, and fix within approved scope. If the fix needs a new file, a shared service, a schema change, or an unrelated module, update the manifest and ask first. Never weaken a test, remove an assertion without justification, hide a failure, or silently change expected business behavior.

### F9 — Report additions
The Rule 9 `TASK COMPLETE` format stays. Add these lines:
- **Preserved behavior:** what was explicitly kept unchanged and how it was checked.
- **Manifest deviations:** files changed outside the approved manifest and whether each was approved (should be none).
- **Regression review:** shared logic or API contracts touched, calculation values verified, related features checked, and anything that still needs Carl's browser check.
- **Acceptance:** a clear PASS/FAIL against the acceptance criteria.

### F10 — "A feature disappeared" reports (added 2026-10-24)
Lesson: on 2026-10-24 the client said "nawala yung procurement" during a presentation. The cause was data, not code. The DB had been cleaned, there were 0 procurement requests, and no project had a certified LIB, which procurement needs. Investigate in this order:
1. Which account, role and page was used, and what was seen (no menu, empty list, button disabled, error)?
2. Data state, read-only: do the records exist, and is the required upstream state there (e.g. a certified LIB, a submitted project)?
3. Then nav tier, route, permission, API response, and recent diffs.
Report confirmed findings separately from hypotheses. If the fix is a user action (e.g. certify the LIB), give Carl the exact steps per role. Don't change code for it.

### F11 — Gates, locks and visibility filters (added 2026-10-24)
Any change that blocks, locks, hides or filters something (workflow gate, status lock, scope filter, nav tier) must state in its plan:
- for each role, which existing features become unreachable or empty;
- which of those apply to the CURRENT data (read-only DB check);
- what a user has to do to reach them again.
Repeat this in the task report so Carl can warn the client before a demo.
