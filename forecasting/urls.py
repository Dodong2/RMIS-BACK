from django.urls import path

from .views import (
    ForecastProjectListView, ForecastRunDetailView, ForecastRunListView, ForecastRunSaveView, ForecastRunTriggerView,
)

urlpatterns = [
    path("projects/", ForecastProjectListView.as_view()),
    path("runs/", ForecastRunListView.as_view()),
    path("runs/<int:pk>/", ForecastRunDetailView.as_view()),
    path("runs/trigger/", ForecastRunTriggerView.as_view()),
    path("runs/<int:pk>/save/", ForecastRunSaveView.as_view()),
]
