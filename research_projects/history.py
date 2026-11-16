"""Project History tab (client Task 65-C, 2026-11-16): the workflow a project actually went through, read from records
that already exist. Nothing is inferred from the current status: an event shows only when a row for it exists."""

from accounts.models import Role
from budget_lib.models import BudgetEventLog, BudgetReview

from .models import ProjectStatusHistory

REVIEW_TITLES = {
    "submitted": "Submitted for review",
    "review_started": "CRC/CRD review started",
    "for_checking": "Marked for checking by CRC/CRD",
    # The CRC/CRD's "Mark for checking" step (budget_lib for-checking) records action "ready".
    "ready": "Marked for checking by CRC/CRD — forwarded to Finance/Accounting/Budget for budget review",
    "endorsed": "Endorsed to Finance/Accounting/Budget",
    "certification_started": "Budget review started (certification in progress)",
    "held_crc": "Returned for revision by CRC/CRD",
    "held_budget": "Returned for revision by Finance/Accounting/Budget",
    "returned": "Returned for revision",
    "resubmitted": "Resubmitted after revision",
    "certified": "Certified by Finance/Accounting/Budget — project is Active",
    "commented": "Review comment",
}
LIB_UPDATE_EVENTS = ("LIB_LINE_ITEM_ADDED", "LIB_LINE_ITEM_EDITED", "LIB_LINE_ITEM_REMOVED", "LIB_LINE_ITEM_EDITED_BY_FINANCE")
LIFECYCLE_LABELS = {"active": "Ongoing", "completed": "Completed", "archived": "Closed"}


def _event(at, kind, title, actor_name="", actor_role="", remarks=""):
    return {"at": at, "kind": kind, "title": title, "actor_name": actor_name, "actor_role": actor_role, "remarks": remarks}


def project_history(project):
    """Newest first. kind: "status" (a workflow step or status change), "update" (LIB edited), "comment"."""
    role_names = dict(Role.objects.values_list("code", "name"))
    registered = (
        BudgetEventLog.objects.filter(project=project, event="LIB_CREATED_AT_REGISTRATION").order_by("created_at", "id").first()
    )
    events = [_event(
        project.created_at, "status", "Project registered in RMIS",
        registered.actor_name if registered else "", role_names.get(registered.actor_role, "") if registered else "",
        f"NTP {project.ntp_number}" if project.ntp_number else "",
    )]
    reviews = BudgetReview.objects.filter(budget__project=project).select_related("acted_by__role", "budget")
    for r in reviews.order_by("acted_at", "id"):
        title = REVIEW_TITLES.get(r.action, r.get_action_display())
        if r.budget.version_number > 1:
            title = f"{title} (LIB version {r.budget.version_number})"
        role = r.acted_by.role.name if r.acted_by.role else ""
        events.append(_event(r.acted_at, "comment" if r.action == "commented" else "status", title,
                             r.acted_by.display_name, role, r.remarks))
    for e in BudgetEventLog.objects.filter(project=project, event__in=LIB_UPDATE_EVENTS).order_by("created_at", "id"):
        events.append(_event(e.created_at, "update", "LIB updated", e.actor_name, role_names.get(e.actor_role, e.actor_role),
                             " ".join(filter(None, [e.description, e.remarks]))))
    for h in ProjectStatusHistory.objects.filter(project=project).select_related("changed_by__role").order_by("changed_at", "id"):
        title = f"Project status changed: {LIFECYCLE_LABELS.get(h.from_status, h.from_status)} → " \
                f"{LIFECYCLE_LABELS.get(h.to_status, h.to_status)}"
        role = h.changed_by.role.name if h.changed_by.role else ""
        events.append(_event(h.changed_at, "status", title, h.changed_by.display_name, role, h.remarks))
    # Stable sort: events with the same timestamp keep their recorded order, then the whole list is reversed.
    events.sort(key=lambda e: e["at"])
    return events[::-1]
