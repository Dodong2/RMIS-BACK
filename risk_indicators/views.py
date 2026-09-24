from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import HasRole
from research_projects.models import Project

from . import services
from .models import ProjectRisk
from .serializers import RISK_REGISTER_ROLES, ProjectRiskSerializer, RiskUpdateSerializer


class RegisterWritesMixin:
    def get_permissions(self):
        if self.request.method in permissions.SAFE_METHODS:
            return [permissions.IsAuthenticated()]
        return [HasRole(RISK_REGISTER_ROLES)]


class ProjectRiskStatusView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, project_id):
        project = get_object_or_404(Project, pk=project_id)
        data = services.compute_project_risk(project)
        open_risks = project.risks.exclude(status="closed").order_by("-created_at")
        data["register"] = ProjectRiskSerializer(open_risks, many=True).data
        return Response(data)


class RiskDashboardView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(
            services.compute_risk_dashboard(
                campus=request.query_params.get("campus"),
                funding_type=request.query_params.get("funding_type"),
            )
        )


class ProjectRiskListCreateView(RegisterWritesMixin, generics.ListCreateAPIView):
    serializer_class = ProjectRiskSerializer

    def get_queryset(self):
        qs = ProjectRisk.objects.select_related("owner").order_by("-created_at")
        for param in ("project", "status", "category"):
            value = self.request.query_params.get(param)
            if value:
                qs = qs.filter(**{param: value})
        return qs

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class ProjectRiskDetailView(RegisterWritesMixin, generics.RetrieveUpdateAPIView):
    queryset = ProjectRisk.objects.select_related("owner")
    serializer_class = ProjectRiskSerializer


class RiskUpdateListCreateView(RegisterWritesMixin, generics.ListCreateAPIView):
    serializer_class = RiskUpdateSerializer

    def get_queryset(self):
        return get_object_or_404(ProjectRisk, pk=self.kwargs["pk"]).updates.order_by("-created_at", "-id")

    def perform_create(self, serializer):
        risk = get_object_or_404(ProjectRisk, pk=self.kwargs["pk"])
        update = serializer.save(risk=risk, author=self.request.user)
        if update.new_status and update.new_status != risk.status:
            risk.status = update.new_status
            risk.save(update_fields=["status", "updated_at"])
