from django.urls import path
from .views import (
    ProgramListCreateView,
    ProgramDetailView,
    ProjectListCreateView,
    ProjectDetailView,
    ProjectStatusHistoryView,
    StudyListCreateView,
    StudyDetailView,
    MilestoneListCreateView,
    MilestoneDetailView,
)

urlpatterns = [
    path("programs/", ProgramListCreateView.as_view()),
    path("programs/<int:pk>/", ProgramDetailView.as_view()),
    path("projects/", ProjectListCreateView.as_view()),
    path("projects/<int:pk>/", ProjectDetailView.as_view()),
    path("projects/<int:pk>/status-history/", ProjectStatusHistoryView.as_view()),
    path("studies/", StudyListCreateView.as_view()),
    path("studies/<int:pk>/", StudyDetailView.as_view()),
    path("milestones/", MilestoneListCreateView.as_view()),
    path("milestones/<int:pk>/", MilestoneDetailView.as_view()),
]