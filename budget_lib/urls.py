from django.urls import path
from .views import (
    TRANSITIONS,
    BudgetDetailView,
    BudgetExportView,
    BudgetListCreateView,
    BudgetReviewView,
    FinanceEditView,
    LibItemDetailView,
    LibItemListCreateView,
    LineItemDetailView,
    LineItemListCreateView,
)

urlpatterns = [
    path("budgets/", BudgetListCreateView.as_view()),
    path("budgets/<int:pk>/", BudgetDetailView.as_view()),
    path("budgets/<int:pk>/export/", BudgetExportView.as_view()),
    path("budgets/<int:pk>/finance-edit/", FinanceEditView.as_view()),
    *[path(f"budgets/<int:pk>/{step}/", BudgetReviewView.as_view(step=step)) for step in (*TRANSITIONS, "hold", "comment")],
    path("line-items/", LineItemListCreateView.as_view()),
    path("line-items/<int:pk>/", LineItemDetailView.as_view()),
    path("lib-items/", LibItemListCreateView.as_view()),
    path("lib-items/<int:pk>/", LibItemDetailView.as_view()),
]
