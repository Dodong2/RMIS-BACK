from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import HasRole, role_can
from config.concurrency import lock
from realtime.notify import notify, project_audience
from research_projects.models import Project

from .models import (
    EvaluationCriterion, ExtensionRequest, MidtermReport, MonthlyProgressReport, ProjectEvaluation, RenewalApplication, TerminalReport,
)
from .serializers import (
    EvaluationCriterionSerializer,
    EvaluationScoreSerializer,
    ExtensionRequestSerializer,
    MidtermReportSerializer,
    MonthlyProgressReportSerializer,
    ProjectEvaluationSerializer,
    ProjectMonitoringStatusSerializer,
    RenewalApplicationSerializer,
    TerminalReportSerializer,
    extension_deadline_passed,
)


def signal(event_type, record, *user_ids, **data):
    """Real-time "this project's monitoring records changed" (realtime/notify.py), sent after commit to the monitoring
    roles, the project lead and the given users. The browser refetches through these same endpoints."""
    notify(project_audience(record.project, "monitoring.", *user_ids), event_type, id=record.id, project=record.project_id,
           **data)


class RoleWritesMixin:
    write_permission = "monitoring.report"

    def get_permissions(self):
        if self.request.method in permissions.SAFE_METHODS:
            return [permissions.IsAuthenticated()]
        return [HasRole(self.write_permission)]


class ProjectScopedMixin:
    def get_queryset(self):
        qs = super().get_queryset()
        value = self.request.query_params.get("project")
        if value:
            qs = qs.filter(project_id=value)
        return qs


class MonthlyProgressReportListCreateView(RoleWritesMixin, ProjectScopedMixin, generics.ListCreateAPIView):
    queryset = MonthlyProgressReport.objects.all()
    serializer_class = MonthlyProgressReportSerializer

    def perform_create(self, serializer):
        report = serializer.save(submitted_by=self.request.user)
        signal("monitoring.report.created", report, report.submitted_by_id, kind="monthly")


class MidtermReportListCreateView(RoleWritesMixin, ProjectScopedMixin, generics.ListCreateAPIView):
    queryset = MidtermReport.objects.all().order_by("-submitted_at")
    serializer_class = MidtermReportSerializer

    def perform_create(self, serializer):
        report = serializer.save(submitted_by=self.request.user)
        signal("monitoring.report.created", report, report.submitted_by_id, kind="midterm")


class TerminalReportListCreateView(RoleWritesMixin, ProjectScopedMixin, generics.ListCreateAPIView):
    queryset = TerminalReport.objects.all().order_by("-submitted_at")
    serializer_class = TerminalReportSerializer

    def perform_create(self, serializer):
        report = serializer.save(submitted_by=self.request.user)
        signal("monitoring.report.created", report, report.submitted_by_id, kind="terminal")


class TerminalReportCertifyView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @transaction.atomic
    def post(self, request, pk):
        if not role_can(request.user, "monitoring.certify_terminal"):
            return Response({"detail": "Only RIUH/system_admin may certify a terminal report."}, status=status.HTTP_403_FORBIDDEN)
        report = lock(TerminalReport.objects.all(), pk=pk)
        if report.is_certified:
            return Response({"detail": "This terminal report is already certified."}, status=status.HTTP_400_BAD_REQUEST)
        report.is_certified = True
        report.certified_by = request.user
        report.certified_at = timezone.now()
        report.save()
        signal("monitoring.report.certified", report, report.submitted_by_id, kind="terminal")
        return Response(TerminalReportSerializer(report).data)


class ProjectEvaluationListCreateView(RoleWritesMixin, ProjectScopedMixin, generics.ListCreateAPIView):
    write_permission = "monitoring.evaluate"
    queryset = ProjectEvaluation.objects.all().order_by("-scheduled_date")
    serializer_class = ProjectEvaluationSerializer

    def perform_create(self, serializer):
        signal("monitoring.evaluation.changed", serializer.save())


class ProjectEvaluationDetailView(RoleWritesMixin, generics.RetrieveUpdateAPIView):
    write_permission = "monitoring.evaluate"
    queryset = ProjectEvaluation.objects.all()
    serializer_class = ProjectEvaluationSerializer

    def perform_update(self, serializer):
        if serializer.validated_data.get("outcome", serializer.instance.outcome) != "pending":
            serializer.save(evaluated_by=self.request.user, evaluated_at=timezone.now())
        else:
            serializer.save()
        signal("monitoring.evaluation.changed", serializer.instance)


class RenewalApplicationListCreateView(RoleWritesMixin, ProjectScopedMixin, generics.ListCreateAPIView):
    queryset = RenewalApplication.objects.all().order_by("-submitted_at")
    serializer_class = RenewalApplicationSerializer

    def perform_create(self, serializer):
        application = serializer.save(submitted_by=self.request.user)
        signal("monitoring.renewal.created", application, application.submitted_by_id, status=application.status)


class RenewalApplicationDecideView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        if not role_can(request.user, "monitoring.decide_renewal"):
            return Response({"detail": "Only RIUH/DRD/VPREI/system_admin may decide a renewal application."}, status=status.HTTP_403_FORBIDDEN)
        status_value = request.data.get("status")
        if status_value not in ("approved", "denied"):
            return Response({"status": "must be 'approved' or 'denied'."}, status=status.HTTP_400_BAD_REQUEST)
        with transaction.atomic():
            # Locked, and decided once: a second officer's conflicting decision can't silently overwrite the first.
            application = lock(RenewalApplication.objects.all(), pk=pk)
            if application.status != "pending":
                return Response({"detail": f"This application was already {application.status}."},
                                status=status.HTTP_400_BAD_REQUEST)
            application.status = status_value
            application.decided_by = request.user
            application.decided_at = timezone.now()
            application.save()
            signal("monitoring.renewal.decided", application, application.submitted_by_id, status=application.status)
        return Response(RenewalApplicationSerializer(application).data)


class EvaluationCriterionListCreateView(RoleWritesMixin, generics.ListCreateAPIView):
    write_permission = "monitoring.evaluate"
    queryset = EvaluationCriterion.objects.order_by("-is_active", "id")
    serializer_class = EvaluationCriterionSerializer


class EvaluationCriterionDetailView(RoleWritesMixin, generics.RetrieveUpdateAPIView):
    write_permission = "monitoring.evaluate"
    queryset = EvaluationCriterion.objects.all()
    serializer_class = EvaluationCriterionSerializer


class EvaluationScoreView(RoleWritesMixin, generics.ListCreateAPIView):
    """GET the scores of one evaluation; POST {criterion, score, remarks} creates or replaces that criterion's score."""

    write_permission = "monitoring.evaluate"
    serializer_class = EvaluationScoreSerializer

    def get_queryset(self):
        return get_object_or_404(ProjectEvaluation, pk=self.kwargs["pk"]).scores.select_related("criterion")

    def create(self, request, *args, **kwargs):
        evaluation = get_object_or_404(ProjectEvaluation, pk=self.kwargs["pk"])
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        score, _ = evaluation.scores.update_or_create(
            criterion=data["criterion"], defaults={"score": data["score"], "remarks": data.get("remarks", "")},
        )
        signal("monitoring.evaluation.changed", evaluation)
        return Response(EvaluationScoreSerializer(score).data, status=status.HTTP_201_CREATED)


class ExtensionRequestListCreateView(RoleWritesMixin, ProjectScopedMixin, generics.ListCreateAPIView):
    queryset = ExtensionRequest.objects.select_related("project").order_by("-submitted_at")
    serializer_class = ExtensionRequestSerializer
    write_permission = "monitoring.request_extension"

    def perform_create(self, serializer):
        project = serializer.validated_data["project"]
        extension = serializer.save(submitted_by=self.request.user, current_end_date=project.target_end_date)
        signal("monitoring.extension.created", extension, extension.submitted_by_id, status=extension.status)


class ExtensionRequestActionView(APIView):
    """POST {"action": "endorse" | "approve" | "deny", "remarks": ...}. Approval moves Project.target_end_date."""

    permission_classes = [permissions.IsAuthenticated]

    @transaction.atomic
    def post(self, request, pk):
        extension = lock(ExtensionRequest.objects.select_related("project"), pk=pk)
        action = request.data.get("action")
        allowed = {
            "endorse": "monitoring.endorse_extension",
            "approve": "monitoring.approve_extension",
            "deny": "monitoring.approve_extension",
        }
        if action not in allowed:
            return Response({"action": "must be 'endorse', 'approve', or 'deny'."}, status=status.HTTP_400_BAD_REQUEST)
        if not role_can(request.user, allowed[action]):
            return Response({"detail": f"You may not {action} extension requests."}, status=status.HTTP_403_FORBIDDEN)
        expected = "pending" if action == "endorse" else "endorsed"
        if extension.status != expected:
            return Response({"detail": f"Only a '{expected}' request can be {action}d."}, status=status.HTTP_400_BAD_REQUEST)
        if action == "approve" and extension_deadline_passed(extension.project):
            return Response(
                {"detail": "Too late: an extension must be approved at least one month before termination."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        now = timezone.now()
        extension.remarks = request.data.get("remarks", extension.remarks)
        if action == "endorse":
            extension.status, extension.endorsed_by, extension.endorsed_at = "endorsed", request.user, now
        else:
            extension.status = "approved" if action == "approve" else "denied"
            extension.decided_by, extension.decided_at = request.user, now
        extension.save()
        if action == "approve":
            Project.objects.filter(pk=extension.project_id).update(target_end_date=extension.requested_end_date)
        signal("monitoring.extension.updated", extension, extension.submitted_by_id, status=extension.status)
        return Response(ExtensionRequestSerializer(extension).data)


class ProjectMonitoringStatusView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, project_id):
        project = get_object_or_404(Project, pk=project_id)
        return Response(ProjectMonitoringStatusSerializer(project).data)
