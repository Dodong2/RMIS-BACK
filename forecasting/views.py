from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import role_can, scoped_projects
from research_projects.models import Project

from . import services
from .models import ForecastRun
from .serializers import ForecastRunSerializer

DENIED = "Budget Forecast is for the Project Leader, RIUH, CRC/CRD, Finance/Accounting/Budget and System Admin."


def forecastable_projects(user):
    """Client Task 66 (2026-11-16): only Active projects (current LIB certified by Finance/Accounting/Budget), any
    funding type, within the user's budget scope. The dropdown, trigger, list and detail all use this."""
    allowed = scoped_projects(user)
    qs = Project.objects.all() if allowed is None else allowed
    return qs.filter(budgets__is_current=True, budgets__status="certified").distinct()


class ForecastRolePermission(permissions.BasePermission):
    message = DENIED

    def has_permission(self, request, view):
        return request.user.is_authenticated and role_can(request.user, "forecasting.run")


class ForecastProjectListView(APIView):
    permission_classes = [ForecastRolePermission]

    def get(self, request):
        rows = forecastable_projects(request.user).order_by("title").values("id", "project_code", "title")
        return Response(list(rows))


class ForecastRunTriggerView(APIView):
    permission_classes = [ForecastRolePermission]
    throttle_scope = "compute"

    def post(self, request):
        project = get_object_or_404(forecastable_projects(request.user), pk=request.data.get("project"))
        try:
            horizon = int(request.data.get("horizon", services.FORECAST_HORIZON_MONTHS))
        except (TypeError, ValueError):
            horizon = 0
        if not 1 <= horizon <= services.MAX_HORIZON_MONTHS:
            return Response({"horizon": f"must be 1 to {services.MAX_HORIZON_MONTHS} months."},
                            status=status.HTTP_400_BAD_REQUEST)
        run = services.run_forecast(project, request.user, horizon)
        return Response(ForecastRunSerializer(run).data, status=status.HTTP_201_CREATED)


class ForecastRunSaveView(APIView):
    """Save Forecast (client Task 86-A): keeps the caller's own preview; it then shows under Saved Forecasts."""

    permission_classes = [ForecastRolePermission]

    def post(self, request, pk):
        run = get_object_or_404(
            ForecastRun.objects.filter(project__in=forecastable_projects(request.user), run_by=request.user), pk=pk,
        )
        if not run.is_saved:
            run.is_saved = True
            run.save(update_fields=["is_saved"])
        return Response(ForecastRunSerializer(run).data)


class ForecastRunListView(generics.ListAPIView):
    serializer_class = ForecastRunSerializer
    permission_classes = [ForecastRolePermission]

    def get_queryset(self):
        qs = (ForecastRun.objects.filter(project__in=forecastable_projects(self.request.user), is_saved=True)
              .select_related("project").prefetch_related("forecasts"))  # Task 68-A: not per run
        project_id = self.request.query_params.get("project")
        if project_id:
            qs = qs.filter(project_id=project_id)
        return qs


class ForecastRunDetailView(generics.RetrieveAPIView):
    serializer_class = ForecastRunSerializer
    permission_classes = [ForecastRolePermission]

    def get_queryset(self):
        return ForecastRun.objects.filter(project__in=forecastable_projects(self.request.user))
