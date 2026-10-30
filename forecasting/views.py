from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import role_can, scoped_projects
from research_projects.models import Project

from . import services
from .models import FORECASTABLE_FUNDING_TYPES, ForecastRun
from .serializers import ForecastRunSerializer


def in_scope(queryset, user):
    allowed = scoped_projects(user)
    return queryset if allowed is None else queryset.filter(project__in=allowed)


class ForecastRunTriggerView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = "compute"

    def post(self, request):
        if not role_can(request.user, "forecasting.run"):
            return Response(
                {"detail": "Only VPREI/Budget Officer/Project Leader/system_admin may run a forecast."},
                status=status.HTTP_403_FORBIDDEN,
            )
        allowed = scoped_projects(request.user)
        project = get_object_or_404(Project if allowed is None else allowed, pk=request.data.get("project"))
        if project.funding_type not in FORECASTABLE_FUNDING_TYPES:
            return Response(
                {"detail": f"Forecasting only supports {FORECASTABLE_FUNDING_TYPES} projects."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        run = services.run_forecast(project, request.user)
        return Response(ForecastRunSerializer(run).data, status=status.HTTP_201_CREATED)


class ForecastRunListView(generics.ListAPIView):
    serializer_class = ForecastRunSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = in_scope(ForecastRun.objects.all(), self.request.user)
        project_id = self.request.query_params.get("project")
        if project_id:
            qs = qs.filter(project_id=project_id)
        return qs


class ForecastRunDetailView(generics.RetrieveAPIView):
    serializer_class = ForecastRunSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return in_scope(ForecastRun.objects.all(), self.request.user)
