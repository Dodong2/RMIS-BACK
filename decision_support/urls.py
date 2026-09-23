from django.urls import path

from .views import (
    AHPComparisonSubmitView,
    AHPMatrixRunDetailView,
    AHPMatrixRunFinalizeView,
    AHPMatrixRunListCreateView,
    DecisionCriterionListCreateView,
    FundingRecommendationRunDetailView,
    FundingRecommendationRunListView,
    FundingRecommendationRunTriggerView,
    SensitivityAnalysisView,
)

urlpatterns = [
    path("criteria/", DecisionCriterionListCreateView.as_view()),
    path("ahp-runs/", AHPMatrixRunListCreateView.as_view()),
    path("ahp-runs/<int:pk>/", AHPMatrixRunDetailView.as_view()),
    path("ahp-runs/<int:pk>/comparisons/", AHPComparisonSubmitView.as_view()),
    path("ahp-runs/<int:pk>/finalize/", AHPMatrixRunFinalizeView.as_view()),
    path("recommendation-runs/", FundingRecommendationRunListView.as_view()),
    path("recommendation-runs/trigger/", FundingRecommendationRunTriggerView.as_view()),
    path("recommendation-runs/<int:pk>/", FundingRecommendationRunDetailView.as_view()),
    path("recommendation-runs/<int:pk>/sensitivity/", SensitivityAnalysisView.as_view()),
]
