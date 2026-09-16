from django.urls import path
from accounts.views import GoogleExchangeView

urlpatterns = [
    path("google/exchange/", GoogleExchangeView.as_view()),
]