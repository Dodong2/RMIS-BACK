from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from research_projects.models import Project

from . import services
from .models import FORECASTABLE_FUNDING_TYPES, ForecastRun
from .serializers import FORECAST_ROLES, ForecastRunSerializer


class ForecastRunTriggerView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        user_role = request.user.role.code if request.user.role else None
        if user_role not in FORECAST_ROLES:
            return Response(
                {"detail": "Only DRD/VPREI/Budget Officer/system_admin may run a forecast."},
                status=status.HTTP_403_FORBIDDEN,
            )
        project = get_object_or_404(Project, pk=request.data.get("project"))
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
        qs = ForecastRun.objects.all()
        project_id = self.request.query_params.get("project")
        if project_id:
            qs = qs.filter(project_id=project_id)
        return qs


class ForecastRunDetailView(generics.RetrieveAPIView):
    queryset = ForecastRun.objects.all()
    serializer_class = ForecastRunSerializer
    permission_classes = [permissions.IsAuthenticated]
