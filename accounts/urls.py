from django.urls import path
from .views import GoogleExchangeView, AdminOnlyView

urlpatterns = [
    path("google/exchange/", GoogleExchangeView.as_view()),
    path("test/admin-only/", AdminOnlyView.as_view()),
]