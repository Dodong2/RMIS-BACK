from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import HasRole

from . import services
from .models import PlanningTarget
from .serializers import PlanningTargetSerializer


class PlanningTargetListCreateView(generics.ListCreateAPIView):
    queryset = PlanningTarget.objects.all().order_by("-target_year")
    serializer_class = PlanningTargetSerializer

    def get_permissions(self):
        if self.request.method == "POST":
            return [HasRole("dashboard.manage_targets")]
        return [permissions.IsAuthenticated()]

    def perform_create(self, serializer):
        serializer.save(set_by=self.request.user)


class ProjectDashboardView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(
            services.compute_project_dashboard(
                campus=request.query_params.get("campus"),
                funding_type=request.query_params.get("funding_type"),
            )
        )


class BudgetDashboardView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(services.compute_budget_dashboard(campus=request.query_params.get("campus")))


class ComplianceDashboardView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(services.compute_compliance_dashboard())


class OutputDashboardView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        year = request.query_params.get("year")
        return Response(services.compute_output_dashboard(year=int(year) if year else None))


class REIThrustAlignmentView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(services.compute_rei_thrust_alignment())


class PlanningTargetComparisonView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        year = request.query_params.get("year")
        return Response(services.compute_planning_target_comparison(year=int(year) if year else None))


class AppendixEExportView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, project_id):
        return Response(services.appendix_e_export(project_id))


class AppendixFExportView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, project_id):
        data = services.appendix_f_export(project_id)
        if data is None:
            return Response({"detail": "No terminal report submitted for this project."}, status=404)
        return Response(data)


class AppendixGExportView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        year = request.query_params.get("year")
        return Response(
            services.appendix_g_export(
                campus=request.query_params.get("campus"),
                year=int(year) if year else None,
            )
        )


class ForecastingDashboardView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(services.compute_forecasting_dashboard(
            campus=request.query_params.get("campus"), funding_type=request.query_params.get("funding_type"),
        ))


class FundingAllocationDashboardView(APIView):
    """?run=<id> (defaults to the latest recommendation run)."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        data = services.compute_funding_allocation_dashboard(run_id=request.query_params.get("run"))
        if data is None:
            return Response({"detail": "No funding recommendation run found."}, status=404)
        return Response(data)


class TaskDashboardView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(services.compute_task_dashboard(project_id=request.query_params.get("project")))
