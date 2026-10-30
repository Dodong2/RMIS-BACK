from django.urls import path
from .views import (
    BudgetSummaryView,
    DisbursementDetailView,
    DisbursementListCreateView,
    ProcurementBalanceView,
    ProcurementRequestListCreateView,
    ProcurementReceiveView,
    ProcurementResubmitView,
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
    path("procurement-balance/", ProcurementBalanceView.as_view()),
    path("procurement-requests/<int:pk>/receive/", ProcurementReceiveView.as_view()),
    path("procurement-requests/<int:pk>/status/", ProcurementStatusView.as_view()),
    path("procurement-requests/<int:pk>/resubmit/", ProcurementResubmitView.as_view()),
    path("budgets/<int:pk>/summary/", BudgetSummaryView.as_view()),
]
