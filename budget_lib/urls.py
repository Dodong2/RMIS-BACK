from django.urls import path
from .views import (
    BudgetDetailView,
    BudgetListCreateView,
    BudgetReviewView,
    LibItemDetailView,
    LibItemListCreateView,
    LineItemDetailView,
    LineItemListCreateView,
)

urlpatterns = [
    path("budgets/", BudgetListCreateView.as_view()),
    path("budgets/<int:pk>/", BudgetDetailView.as_view()),
    path("budgets/<int:pk>/endorse/", BudgetReviewView.as_view(step="endorsed")),
    path("budgets/<int:pk>/certify/", BudgetReviewView.as_view(step="certified")),
    path("budgets/<int:pk>/return/", BudgetReviewView.as_view(step="returned")),
    path("budgets/<int:pk>/resubmit/", BudgetReviewView.as_view(step="resubmitted")),
    path("line-items/", LineItemListCreateView.as_view()),
    path("line-items/<int:pk>/", LineItemDetailView.as_view()),
    path("lib-items/", LibItemListCreateView.as_view()),
    path("lib-items/<int:pk>/", LibItemDetailView.as_view()),
]
