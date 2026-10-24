"""Project review workflow (client 2026-10-24, Figma ProjectReviewWorkflow): a registered project stays a Draft until its
Project Leader submits it, then goes through the CRC Chair and the Budget Officer. Carl's decision D1 (2026-10-24): the
project's review status is read from its current LIB's workflow (budget_lib TRANSITIONS, client 2026-10-21), so the
LIB's Submit is the project's Submit and there is no second status to keep in step."""

from rest_framework import serializers
from rest_framework.fields import empty

REVIEW_STATUS_LABELS = {
    "draft": "Draft",
    "submitted": "Submitted",
    "pending_research_review": "Pending Research Review",
    "returned_research": "Returned for Revision – Research",
    "pending_budget_review": "Pending Budget Review",
    "returned_budget": "Returned for Revision – Budget",
    "reviews_completed": "Reviews Completed",
}
# The Project Leader can still change the registration (Carl 2026-10-24, D6: never after submitting, unless returned).
EDITABLE_REVIEW_STATUSES = ("draft", "returned_research", "returned_budget")
FROM_LIB_STATUS = {
    "draft": "draft",
    "submitted": "submitted",
    "crc_processing": "pending_research_review",
    "for_checking": "pending_research_review",
    "endorsed": "pending_budget_review",
    "certifying": "pending_budget_review",
    "certified": "reviews_completed",
}
# Step 7 of Register Approved Project (client 2026-10-24); required before the Project Leader submits.
APPROVAL_DOCUMENT_TYPES = ("notice_of_approval", "ntp", "moa")


def review_status(project):
    """The project's review status code (REVIEW_STATUS_LABELS). No LIB yet = Draft (D3: submitting needs one)."""
    budget = project.budgets.filter(is_current=True).order_by("-version_number").first()
    if budget is None:
        return "draft"
    if budget.status == "returned":
        last_hold = budget.reviews.filter(action__in=("held_crc", "held_budget", "returned")).last()
        return "returned_budget" if last_hold and last_hold.action == "held_budget" else "returned_research"
    return FROM_LIB_STATUS[budget.status]


def missing_approval_documents(project):
    """Labels of the Step 7 attachments the project doesn't have yet (a current, not archived version of each)."""
    from document_management.models import Document

    have = set(Document.objects.filter(
        project=project, document_type__in=APPROVAL_DOCUMENT_TYPES, is_current=True, is_archived=False,
    ).values_list("document_type", flat=True))
    labels = dict(Document.TYPE_CHOICES)
    return [labels[t] for t in APPROVAL_DOCUMENT_TYPES if t not in have]


def registration_changes(serializer, attrs, fields=None, exclude=()):
    """True when this save creates a row or changes one of `fields` (default: every field but `exclude`)."""
    if serializer.instance is None:
        return True
    guarded = [f for f in attrs if (f in fields if fields else f not in exclude)]
    return any(attrs[f] != getattr(serializer.instance, f) for f in guarded)


def ensure_registration_open(project, changed=True):
    """Refuses a change to a project's registration (the project, its form rows and work plan) once it was submitted,
    for every role (Carl 2026-10-24), until the CRC Chair or the Budget Officer returns it. `changed` False = an update
    that leaves the guarded fields as they were."""
    if project is None or not changed:
        return
    current = review_status(project)
    if current not in EDITABLE_REVIEW_STATUSES:
        raise serializers.ValidationError(
            f"This project is {REVIEW_STATUS_LABELS[current]} and can't be edited until it is returned for revision."
        )


def ensure_work_allowed(project):
    """Carl 2026-10-24 (D5): no work on a project (tasks, Work Logs, assignments, monitoring reports, outputs,
    compliance records) until its reviews are completed, i.e. the Budget Officer certified its LIB. Every role."""
    if project is None:
        return
    current = review_status(project)
    if current != "reviews_completed":
        raise serializers.ValidationError(
            f"This project is {REVIEW_STATUS_LABELS[current]}. Work on it starts once its reviews are completed "
            "(the Budget Officer certifies its LIB)."
        )


class WorkAfterReviewMixin:
    """For serializers of a project's work records: creating or changing one runs ensure_work_allowed. Hooks
    run_validation so a serializer's own validate() needn't call it. The project comes from the row (project, or its
    study or task) or, for a task's Work Logs and deliverables, from context["task"]."""

    def work_project(self, attrs):
        def get(field):
            return attrs.get(field, getattr(self.instance, field, None))

        for source in (get("project"), getattr(get("study"), "project", None), getattr(get("task"), "project", None),
                       getattr(self.context.get("task"), "project", None)):
            if source is not None:
                return source
        return None

    def run_validation(self, data=empty):
        attrs = super().run_validation(data)
        try:
            ensure_work_allowed(self.work_project(attrs))
        except serializers.ValidationError as exc:  # shaped like validate()'s errors ({"non_field_errors": [...]})
            raise serializers.ValidationError(serializers.as_serializer_error(exc))
        return attrs
