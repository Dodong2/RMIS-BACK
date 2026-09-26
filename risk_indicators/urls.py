from django.urls import path

from .views import (
    ProjectRiskDetailView,
    ProjectRiskListCreateView,
    ProjectRiskStatusView,
    RiskAlertsView,
    RiskDashboardView,
    RiskUpdateListCreateView,
)

urlpatterns = [
    path("dashboard/", RiskDashboardView.as_view()),
    path("alerts/", RiskAlertsView.as_view()),
    path("status/<int:project_id>/", ProjectRiskStatusView.as_view()),
    path("register/", ProjectRiskListCreateView.as_view()),
    path("register/<int:pk>/", ProjectRiskDetailView.as_view()),
    path("register/<int:pk>/updates/", RiskUpdateListCreateView.as_view()),
]
