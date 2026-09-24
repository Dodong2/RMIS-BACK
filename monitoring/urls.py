from django.urls import path

from .views import (
    EvaluationCriterionDetailView,
    EvaluationCriterionListCreateView,
    EvaluationScoreView,
    ExtensionRequestActionView,
    ExtensionRequestListCreateView,
    MidtermReportListCreateView,
    MonthlyProgressReportListCreateView,
    ProjectEvaluationDetailView,
    ProjectEvaluationListCreateView,
    ProjectMonitoringStatusView,
    RenewalApplicationDecideView,
    RenewalApplicationListCreateView,
    TerminalReportCertifyView,
    TerminalReportListCreateView,
)

urlpatterns = [
    path("monthly-reports/", MonthlyProgressReportListCreateView.as_view()),
    path("midterm-reports/", MidtermReportListCreateView.as_view()),
    path("terminal-reports/", TerminalReportListCreateView.as_view()),
    path("terminal-reports/<int:pk>/certify/", TerminalReportCertifyView.as_view()),
    path("evaluations/", ProjectEvaluationListCreateView.as_view()),
    path("evaluations/<int:pk>/", ProjectEvaluationDetailView.as_view()),
    path("evaluations/<int:pk>/scores/", EvaluationScoreView.as_view()),
    path("evaluation-criteria/", EvaluationCriterionListCreateView.as_view()),
    path("evaluation-criteria/<int:pk>/", EvaluationCriterionDetailView.as_view()),
    path("renewal-applications/", RenewalApplicationListCreateView.as_view()),
    path("renewal-applications/<int:pk>/decide/", RenewalApplicationDecideView.as_view()),
    path("extension-requests/", ExtensionRequestListCreateView.as_view()),
    path("extension-requests/<int:pk>/action/", ExtensionRequestActionView.as_view()),
    path("status/<int:project_id>/", ProjectMonitoringStatusView.as_view()),
]
