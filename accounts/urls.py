from django.urls import path
from accounts.views import GoogleExchangeView, ProjectManagementView, AdminOnlyView

urlpatterns = [
    path("google/exchange/", GoogleExchangeView.as_view()),
    path("test/project-management/", ProjectManagementView.as_view()),
    path("test/admin-only/", AdminOnlyView.as_view()),
]