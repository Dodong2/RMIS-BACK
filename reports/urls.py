from django.urls import path

from .views import (
    AppendixEReportView,
    AppendixFReportView,
    AppendixGReportView,
    GeneratedReportLogListView,
    ProjectListReportView,
)

urlpatterns = [
    path("appendix-e/<int:project_id>/", AppendixEReportView.as_view()),
    path("appendix-f/<int:project_id>/", AppendixFReportView.as_view()),
    path("appendix-g/", AppendixGReportView.as_view()),
    path("projects/", ProjectListReportView.as_view()),
    path("logs/", GeneratedReportLogListView.as_view()),
]
