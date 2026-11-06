"""Event Logs Budget writer (client Task 46, 2026-11-06). Call log_budget_event() from a view after the action has
been checked and saved, inside the view's transaction.atomic(), so a refused or rolled-back action leaves no row.
The actor is always request.user and the project comes from the record that changed, never from the request body."""
from .models import BudgetEventLog

# Carl's Q5 (2026-11-06): the three budget/procurement roles, plus system_admin so a misused admin account is traced
LOGGED_ROLES = ("project_leader", "procurement_officer_lib", "finance_budget", "system_admin")
LINE_ITEM_FIELDS = ("category", "description", "specification", "unit", "quantity", "unit_cost", "amount", "allocations",
                    "justification", "fiscal_year")


def line_item_values(item):
    return {field: getattr(item, field) for field in LINE_ITEM_FIELDS}


def changed_values(before, after):
    """(previous, new) holding only the fields whose value changed."""
    keys = [k for k in before if before[k] != after[k]]
    return {k: before[k] for k in keys}, {k: after[k] for k in keys}


def log_budget_event(user, project, event, description, target, *, target_id=None, previous=None, new=None,
                     remarks="", amount=None, **details):
    """One BudgetEventLog row for an action `user` just took on `project`; None when the role isn't logged."""
    role = user.role.code if user.role else ""
    if role not in LOGGED_ROLES:
        return None
    return BudgetEventLog.objects.create(
        project=project, project_ref=project.pk, project_code=project.project_code or "", project_title=project.title or "",
        actor=user, actor_name=user.display_name, actor_email=user.email, actor_staff_id=user.staff_id or "", actor_role=role,
        event=event, description=description, target_type=target._meta.label,
        target_id=target.pk if target_id is None else target_id,
        previous=previous, new=new, remarks=remarks or "", amount=amount, details=details,
    )
