from django.urls import path

from .views import ForecastRunDetailView, ForecastRunListView, ForecastRunTriggerView

urlpatterns = [
    path("runs/", ForecastRunListView.as_view()),
    path("runs/<int:pk>/", ForecastRunDetailView.as_view()),
    path("runs/trigger/", ForecastRunTriggerView.as_view()),
]
