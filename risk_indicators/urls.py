from django.urls import path

from .views import ProjectRiskStatusView, RiskDashboardView

urlpatterns = [
    path("dashboard/", RiskDashboardView.as_view()),
    path("status/<int:project_id>/", ProjectRiskStatusView.as_view()),
]
