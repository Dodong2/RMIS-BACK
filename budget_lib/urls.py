from django.urls import path
from .views import (
    BudgetDetailView,
    BudgetListCreateView,
    CertifyBudgetView,
    LineItemDetailView,
    LineItemListCreateView,
)

urlpatterns = [
    path("budgets/", BudgetListCreateView.as_view()),
    path("budgets/<int:pk>/", BudgetDetailView.as_view()),
    path("budgets/<int:pk>/certify/", CertifyBudgetView.as_view()),
    path("line-items/", LineItemListCreateView.as_view()),
    path("line-items/<int:pk>/", LineItemDetailView.as_view()),
]
