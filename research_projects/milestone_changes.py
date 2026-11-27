"""Client Task 90 (2026-11-27): Work Plan milestone changes after registration. The Project Leader proposes, the RIUH
confirms (the change is applied) or returns it with remarks, and the campus CRC/CRD is notified of a confirmed change."""
import datetime
from html import escape

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import generics, permissions, serializers, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.emails import send_brevo_email
from accounts.permissions import HasRole, acting_for, scope_college, visible_projects
from budget_lib.notifications import campus_reviewers
from config.concurrency import idempotent, lock
from personnel.notifications import button, table
from realtime.notify import notify, project_audience

from .models import MilestoneChangeRequest, WorkPlanMilestone
from .workflow import EDITABLE_REVIEW_STATUSES, review_status

# Seed sources (accounts 0040). Not a projects.* code: other project_audience prefixes must not grow.
VIEW_ROLES = ["system_admin", "project_leader", "riuh", "crc_chair"]
REQUEST_ROLES = ["system_admin", "project_leader"]
REVIEW_ROLES = ["system_admin", "riuh"]

DATE_FIELDS = ("start_date", "target_date")
LABELS = {"title": "Activity", "start_date": "Start Date", "target_date": "Target Date", "objective": "Objective",
          "deliverable": "Deliverable", "remarks": "Remarks"}


def has_pending_change(milestone):
    return milestone.pk is not None and milestone.change_requests.filter(status="pending").exists()


def as_json(field, value):
    return value.isoformat() if isinstance(value, datetime.date) else value


def from_json(field, value):
    return datetime.date.fromisoformat(value) if field in DATE_FIELDS and value else value


class ChangesSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=300, required=False)
    start_date = serializers.DateField(required=False, allow_null=True)
    target_date = serializers.DateField(required=False)
    objective = serializers.CharField(required=False, allow_blank=True)
    deliverable = serializers.CharField(required=False, allow_blank=True)
    remarks = serializers.CharField(required=False, allow_blank=True)


class MilestoneChangeRequestSerializer(serializers.ModelSerializer):
    changes = ChangesSerializer(write_only=True)
    milestone_title = serializers.CharField(source="milestone.title", read_only=True)
    project_code = serializers.CharField(source="project.project_code", read_only=True)
    project_title = serializers.CharField(source="project.title", read_only=True)
    campus = serializers.CharField(source="project.campus", read_only=True)
    college = serializers.CharField(source="project.college", read_only=True)
    project_leader = serializers.CharField(source="project.lead.display_name", read_only=True)
    submitted_by_name = serializers.CharField(source="submitted_by.display_name", read_only=True)
    reviewed_by_name = serializers.CharField(source="reviewed_by.display_name", read_only=True, default=None)

    class Meta:
        model = MilestoneChangeRequest
        fields = [
            "id", "milestone", "milestone_title", "project", "project_code", "project_title", "campus", "college",
            "project_leader", "previous", "proposed", "changes", "reason", "status", "submitted_by", "submitted_by_name",
            "submitted_at", "reviewed_by", "reviewed_by_name", "reviewed_at", "review_remarks",
        ]
        read_only_fields = ["project", "previous", "proposed", "status", "submitted_by", "submitted_at", "reviewed_by",
                            "reviewed_at", "review_remarks"]

    def validate_reason(self, value):
        if not value.strip():
            raise serializers.ValidationError("Give the reason for the change.")
        return value.strip()

    def validate(self, attrs):
        user = self.context["request"].user
        milestone = attrs["milestone"]
        project = milestone.project
        visible = visible_projects(user)
        if visible is not None and not visible.filter(pk=project.pk).exists():
            raise serializers.ValidationError({"milestone": "This milestone is outside your scope."})
        if user.role and user.role.code == "project_leader" and project.lead_id not in (user.pk, *acting_for(user)):
            raise serializers.ValidationError({"milestone": "Only the project's Project Leader can propose a change."})
        if review_status(project) in EDITABLE_REVIEW_STATUSES:
            raise serializers.ValidationError("Registration is still open: edit the Work Plan directly.")
        if has_pending_change(milestone):
            raise serializers.ValidationError("This milestone already has a change waiting for RIUH confirmation.")
        previous, proposed = {}, {}
        for field, value in attrs.pop("changes").items():
            old = getattr(milestone, field)
            if (value or None) != (old or None):
                previous[field], proposed[field] = as_json(field, old), as_json(field, value)
        if not proposed:
            raise serializers.ValidationError({"changes": "Change at least one field."})
        start = from_json("start_date", proposed["start_date"]) if "start_date" in proposed else milestone.start_date
        target = from_json("target_date", proposed["target_date"]) if "target_date" in proposed else milestone.target_date
        if start and target and start > target:
            raise serializers.ValidationError({"changes": "Start date cannot be after the target date."})
        return {**attrs, "project": project, "previous": previous, "proposed": proposed}


class ChangePagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


def changes_for(user):
    qs = MilestoneChangeRequest.objects.select_related("milestone", "project__lead", "submitted_by", "reviewed_by")
    visible = visible_projects(user)
    return qs if visible is None else qs.filter(project__in=visible.values("pk"))


def signal(change, verb):
    notify(project_audience(change.project, "milestone_changes.", change.submitted_by_id),
           f"milestone_change.{verb}", id=change.id, project=change.project_id, milestone=change.milestone_id)


class MilestoneChangeListCreateView(generics.ListCreateAPIView):
    """GET ?status=&project=&milestone=&q=&page= (visible_projects scope); POST {milestone, reason, changes{...}}."""

    serializer_class = MilestoneChangeRequestSerializer
    pagination_class = ChangePagination

    def get_permissions(self):
        code = "milestone_changes.request" if self.request.method == "POST" else "milestone_changes.view"
        return [permissions.IsAuthenticated(), HasRole(code)]

    def get_queryset(self):
        qs, p = changes_for(self.request.user), self.request.query_params
        for key in ("status", "project", "milestone"):
            if p.get(key):
                qs = qs.filter(**{key: p[key]})
        if p.get("q", "").strip():
            q = p["q"].strip()
            qs = qs.filter(Q(project__project_code__icontains=q) | Q(project__title__icontains=q)
                           | Q(milestone__title__icontains=q) | Q(submitted_by__first_name__icontains=q)
                           | Q(submitted_by__last_name__icontains=q))
        return qs

    @idempotent
    def create(self, request, *args, **kwargs):
        with transaction.atomic():
            milestone = str(request.data.get("milestone", ""))
            if milestone.isdigit():  # one pending change per milestone; a bad id is left to the serializer (400)
                list(WorkPlanMilestone.objects.select_for_update().filter(pk=milestone))
            return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        change = serializer.save(submitted_by=self.request.user)
        signal(change, "submitted")
        transaction.on_commit(lambda: email_riuh(change))


class MilestoneChangeActionView(APIView):
    """POST milestone-changes/<id>/confirm/ (applies the change, e-mails the campus CRC/CRD) or .../return/
    {remarks} (required). RIUH (its campus and College Unit) or System Admin, pending changes only."""

    permission_classes = [permissions.IsAuthenticated, HasRole("milestone_changes.review")]

    def post(self, request, pk, action):
        if action not in ("confirm", "return"):
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        remarks = (request.data.get("remarks") or "").strip()
        if action == "return" and not remarks:
            return Response({"remarks": "Give the reason for returning the change."}, status=status.HTTP_400_BAD_REQUEST)
        with transaction.atomic():
            change = lock(changes_for(request.user), pk=pk)
            if change.status != "pending":
                return Response({"detail": f"This change is already {change.get_status_display().lower()}."},
                                status=status.HTTP_409_CONFLICT)
            if action == "confirm":
                milestone = lock(WorkPlanMilestone.objects.all(), pk=change.milestone_id)
                for field, value in change.proposed.items():
                    setattr(milestone, field, from_json(field, value))
                milestone.save(update_fields=list(change.proposed))
            change.status = "confirmed" if action == "confirm" else "returned"
            change.reviewed_by, change.reviewed_at, change.review_remarks = request.user, timezone.now(), remarks
            change.save(update_fields=["status", "reviewed_by", "reviewed_at", "review_remarks"])
            signal(change, change.status)
            if action == "confirm":
                transaction.on_commit(lambda: email_crc(change))
        return Response(MilestoneChangeRequestSerializer(change).data)


def change_table(change):
    return table(["Field", "Before", "Proposed"],
                 [(LABELS[f], change.previous.get(f) or "—", change.proposed[f] or "—") for f in change.proposed])


def email_riuh(change):
    project = change.project
    recipients = [u.email for u in campus_reviewers(project, "riuh")
                  if not scope_college(u) or scope_college(u).lower() == (project.college or "").lower()]
    subject = f"Work Plan Change for RIUH Confirmation — {project.title}"
    html = (
        "<p>A Project Leader proposed a change to a Work Plan milestone. It is applied only after RIUH confirmation.</p>"
        f"<p><b>Project:</b> {escape(project.project_code)} — {escape(project.title)}<br>"
        f"<b>Milestone:</b> {escape(change.milestone.title)}<br><b>Submitted by:</b> {escape(change.submitted_by.display_name)}<br>"
        f"<b>Reason:</b> {escape(change.reason)}</p>{change_table(change)}"
        f"<p>{button(f'{settings.FRONTEND_URL}/milestone-changes', 'Open Milestone Changes')}</p><p>Thank you.</p>"
    )
    for email in recipients:
        send_brevo_email(email, subject, html)


def email_crc(change):
    project = change.project
    subject = f"Work Plan Change Confirmed by RIUH — {project.title}"
    html = (
        "<p>A Work Plan milestone change was confirmed by RIUH and is now applied.</p>"
        f"<p><b>Project:</b> {escape(project.project_code)} — {escape(project.title)}<br>"
        f"<b>Milestone:</b> {escape(change.milestone.title)}<br><b>Edited by:</b> {escape(change.submitted_by.display_name)}<br>"
        f"<b>Confirmed by RIUH:</b> {escape(change.reviewed_by.display_name)}<br><b>Reason:</b> {escape(change.reason)}</p>"
        f"{change_table(change)}"
        f"<p>{button(f'{settings.FRONTEND_URL}/milestone-changes', 'Open Milestone Changes')}</p><p>Thank you.</p>"
    )
    for email in campus_reviewers(project).values_list("email", flat=True):
        send_brevo_email(email, subject, html)
