from django.shortcuts import get_object_or_404
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from research_projects.models import Project

from . import services


class ProjectRiskStatusView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, project_id):
        project = get_object_or_404(Project, pk=project_id)
        return Response(services.compute_project_risk(project))


class RiskDashboardView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(
            services.compute_risk_dashboard(
                campus=request.query_params.get("campus"),
                funding_type=request.query_params.get("funding_type"),
            )
        )
