from django.urls import path

from .views import (
    ForecastingDashboardView,
    FundingAllocationDashboardView,
    TaskDashboardView,
    AppendixEExportView,
    AppendixFExportView,
    AppendixGExportView,
    BudgetDashboardView,
    ComplianceDashboardView,
    OutputDashboardView,
    PlanningTargetComparisonView,
    PlanningTargetListCreateView,
    ProjectDashboardView,
    REIThrustAlignmentView,
)

urlpatterns = [
    path("projects/", ProjectDashboardView.as_view()),
    path("budget/", BudgetDashboardView.as_view()),
    path("compliance/", ComplianceDashboardView.as_view()),
    path("outputs/", OutputDashboardView.as_view()),
    path("forecasting/", ForecastingDashboardView.as_view()),
    path("funding-allocation/", FundingAllocationDashboardView.as_view()),
    path("tasks/", TaskDashboardView.as_view()),
    path("rei-thrust-alignment/", REIThrustAlignmentView.as_view()),
    path("planning-targets/", PlanningTargetListCreateView.as_view()),
    path("planning-targets/comparison/", PlanningTargetComparisonView.as_view()),
    path("exports/appendix-e/<int:project_id>/", AppendixEExportView.as_view()),
    path("exports/appendix-f/<int:project_id>/", AppendixFExportView.as_view()),
    path("exports/appendix-g/", AppendixGExportView.as_view()),
]
