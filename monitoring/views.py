from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import HasRole
from research_projects.models import Project

from .models import MidtermReport, MonthlyProgressReport, ProjectEvaluation, RenewalApplication, TerminalReport
from .serializers import (
    EVALUATION_PANEL_ROLES,
    RENEWAL_DECISION_ROLES,
    REPORT_ROLES,
    TERMINAL_CERTIFY_ROLES,
    MidtermReportSerializer,
    MonthlyProgressReportSerializer,
    ProjectEvaluationSerializer,
    ProjectMonitoringStatusSerializer,
    RenewalApplicationSerializer,
    TerminalReportSerializer,
)


class RoleWritesMixin:
    write_roles = REPORT_ROLES

    def get_permissions(self):
        if self.request.method in permissions.SAFE_METHODS:
            return [permissions.IsAuthenticated()]
        return [HasRole(self.write_roles)]


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
        serializer.save(submitted_by=self.request.user)


class MidtermReportListCreateView(RoleWritesMixin, ProjectScopedMixin, generics.ListCreateAPIView):
    queryset = MidtermReport.objects.all().order_by("-submitted_at")
    serializer_class = MidtermReportSerializer

    def perform_create(self, serializer):
        serializer.save(submitted_by=self.request.user)


class TerminalReportListCreateView(RoleWritesMixin, ProjectScopedMixin, generics.ListCreateAPIView):
    queryset = TerminalReport.objects.all().order_by("-submitted_at")
    serializer_class = TerminalReportSerializer

    def perform_create(self, serializer):
        serializer.save(submitted_by=self.request.user)


class TerminalReportCertifyView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        user_role = request.user.role.code if request.user.role else None
        if user_role not in TERMINAL_CERTIFY_ROLES:
            return Response({"detail": "Only RIUH/system_admin may certify a terminal report."}, status=status.HTTP_403_FORBIDDEN)
        report = get_object_or_404(TerminalReport, pk=pk)
        report.is_certified = True
        report.certified_by = request.user
        report.certified_at = timezone.now()
        report.save()
        return Response(TerminalReportSerializer(report).data)


class ProjectEvaluationListCreateView(RoleWritesMixin, ProjectScopedMixin, generics.ListCreateAPIView):
    write_roles = EVALUATION_PANEL_ROLES
    queryset = ProjectEvaluation.objects.all().order_by("-scheduled_date")
    serializer_class = ProjectEvaluationSerializer


class ProjectEvaluationDetailView(RoleWritesMixin, generics.RetrieveUpdateAPIView):
    write_roles = EVALUATION_PANEL_ROLES
    queryset = ProjectEvaluation.objects.all()
    serializer_class = ProjectEvaluationSerializer

    def perform_update(self, serializer):
        if serializer.validated_data.get("outcome", serializer.instance.outcome) != "pending":
            serializer.save(evaluated_by=self.request.user, evaluated_at=timezone.now())
        else:
            serializer.save()


class RenewalApplicationListCreateView(RoleWritesMixin, ProjectScopedMixin, generics.ListCreateAPIView):
    queryset = RenewalApplication.objects.all().order_by("-submitted_at")
    serializer_class = RenewalApplicationSerializer

    def perform_create(self, serializer):
        serializer.save(submitted_by=self.request.user)


class RenewalApplicationDecideView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        user_role = request.user.role.code if request.user.role else None
        if user_role not in RENEWAL_DECISION_ROLES:
            return Response({"detail": "Only RIUH/DRD/VPREI/system_admin may decide a renewal application."}, status=status.HTTP_403_FORBIDDEN)
        application = get_object_or_404(RenewalApplication, pk=pk)
        status_value = request.data.get("status")
        if status_value not in ("approved", "denied"):
            return Response({"status": "must be 'approved' or 'denied'."}, status=status.HTTP_400_BAD_REQUEST)
        application.status = status_value
        application.decided_by = request.user
        application.decided_at = timezone.now()
        application.save()
        return Response(RenewalApplicationSerializer(application).data)


class ProjectMonitoringStatusView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, project_id):
        project = get_object_or_404(Project, pk=project_id)
        return Response(ProjectMonitoringStatusSerializer(project).data)
