from django.urls import path
from .views import (
    BudgetSummaryView,
    DisbursementDetailView,
    DisbursementListCreateView,
    ProcurementRequestListCreateView,
    ProcurementStatusView,
    RealignmentDetailView,
    RealignmentListCreateView,
    RealignmentReviewView,
)

urlpatterns = [
    path("disbursements/", DisbursementListCreateView.as_view()),
    path("disbursements/<int:pk>/", DisbursementDetailView.as_view()),
    path("realignments/", RealignmentListCreateView.as_view()),
    path("realignments/<int:pk>/", RealignmentDetailView.as_view()),
    path("realignments/<int:pk>/review/", RealignmentReviewView.as_view()),
    path("procurement-requests/", ProcurementRequestListCreateView.as_view()),
    path("procurement-requests/<int:pk>/status/", ProcurementStatusView.as_view()),
    path("budgets/<int:pk>/summary/", BudgetSummaryView.as_view()),
]
