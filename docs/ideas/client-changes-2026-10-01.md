# RMIS Client Changes: Project Leader Flow + Strict RBAC (2026-10-01)

Source: client meeting 2026-10-01 (18 items). References: `RMIS chap1/RMIS_Complete_Module_Structure_FORApproval.docx`,
`RMIS chap1/RMIS_Clarification_Answers.docx`, `Dataset/BRIDGI_1.PDF` (LSPU-RDO-SF-018).

## Problem Statement
How might we let a Project Leader do the whole flow (register, LIB, work plan, tasks) on their own records only, while
System Admin keeps full access?

## Recommended Direction

**A. RBAC**
- #1/#4: `project_leader` gets `projects.register` back (new migration). Backend requires `lead = request.user` for
  leaders. Frontend locks the Project Leader field to their own account; admin can pick any leader. Study leader stays
  edit-only. This reverses the 2026-09-29 "Option A" (CRC-only) decision, by client request.
- #2: Program removed from the UI only (Register Program page/button, programs table, Parent Program field). Program
  model and FKs stay in the DB.
- #16: Project leader sees the same procurement UI as admin, data scoped to their own projects.
- #17: Procurement officer gets a KPI strip: total requests, completed, ongoing.

**B. Register Approved Project wizard**
- #3: Toast when the project code already exists.
- #5: Remove the campus free-text input; the highlighted campus card is the value.
- #6: Co-leader/team = searchable picker of all accounts, with a free-text fallback (BRIDGI lists the group
  "EIU Coordinators").
- #7: Study Components (Study 1, 2, …) in the Classification step. `Study.lead` becomes optional, defaulting to the
  project lead.
- #8: Annex A becomes "Add Endorser" rows: role (12 roles) → user (auto-fills name; pick one if several) + designation
  + date.
- #10: Per-step required fields; Next is blocked until filled, Previous always works. Temporary list:
  Project Details = Project Code; Proponents & Team = Campus; Classification = Sector; Proposal Content = III.
  Objectives; Beneficiaries = every added row; Endorsement & Approval = NTP No.; Validate & Register = none.
- #11: New "Budget Requirements (LIB)" step (PS/MOOE/CO with QTR1–4). Also part of the Excel import.
- #9: "View" button opens an SF-018-style preview modal of the entered data, in Manual and Excel modes.

**C. Budget**
- #12: Remove funding source from the Prepare LIB modal and the Funding Sources tab. DB column stays, saved blank.

**D. Work plan / Tasks**
- #14: Milestone is the parent; personnel `Task` gets a `milestone` FK and acts as the activity. Milestone is
  expandable, progress = % of its tasks done, can't be marked done while a task is open, and an overdue milestone
  raises an alert in the project leader's bell.
- #13: Responsible Personnel picker from the project's assigned accounts.
- #15: "% tasks completed" summary in the Personnel & Tasks project selector.

**E. UI polish**
- #18: Hover/cursor states on every action button.

## Key Assumptions to Validate
- [ ] The required-field list is temporary; the client finalizes it at the presentation, so it lives in one list.
- [ ] Non-fixed Annex A endorser rows are OK (the form has 5 fixed signatories; only VPRDE maps to a system role).
- [ ] A leader-registered project goes straight to "Ongoing", no CRC verification step.
- [ ] "Same view as admin" for procurement is still scoped to the leader's own projects.

## MVP Scope
Everything in A–E above. Out: see below.

## Not Doing (and Why)
- Dropping Program from the DB — UI-only for now, easy to restore if the panel asks.
- A new Activity model — personnel Tasks are reused as activities.
- An approval workflow for leader-registered projects — not requested.
- Dropping the `funding_source` column — UI-only removal.

## Open Questions
- If a leader registers, does the CRC still need to confirm the project code? (Clarification Q4 says the CRC issues it.)
