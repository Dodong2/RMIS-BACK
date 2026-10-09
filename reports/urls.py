from django.urls import path

from .views import (
    AccomplishmentReportView,
    AppendixEReportView,
    AppendixFReportView,
    AppendixGReportView,
    GeneratedReportLogListView,
    ModuleReportView,
    ProjectListReportView,
    ProposalFormReportView,
)

urlpatterns = [
    path("appendix-e/<int:project_id>/", AppendixEReportView.as_view()),
    path("appendix-f/<int:project_id>/", AppendixFReportView.as_view()),
    path("appendix-g/", AppendixGReportView.as_view()),
    path("proposal-form/<int:project_id>/", ProposalFormReportView.as_view()),
    path("accomplishment/", AccomplishmentReportView.as_view()),
    path("projects/", ProjectListReportView.as_view()),
    path("logs/", GeneratedReportLogListView.as_view()),
    path("<str:report_type>/", ModuleReportView.as_view()),
]
