from django.urls import path
from .views import (
    AIUseDeclarationDetailView,
    AIUseDeclarationListCreateView,
    COIDisclosureDetailView,
    COIDisclosureListCreateView,
    EthicsReviewDetailView,
    EthicsReviewListCreateView,
    MisconductCaseDetailView,
    MisconductCaseListCreateView,
    SimilarityCheckDetailView,
    SimilarityCheckListCreateView,
)

urlpatterns = [
    path("ethics-reviews/", EthicsReviewListCreateView.as_view()),
    path("ethics-reviews/<int:pk>/", EthicsReviewDetailView.as_view()),
    path("similarity-checks/", SimilarityCheckListCreateView.as_view()),
    path("similarity-checks/<int:pk>/", SimilarityCheckDetailView.as_view()),
    path("ai-declarations/", AIUseDeclarationListCreateView.as_view()),
    path("ai-declarations/<int:pk>/", AIUseDeclarationDetailView.as_view()),
    path("coi-disclosures/", COIDisclosureListCreateView.as_view()),
    path("coi-disclosures/<int:pk>/", COIDisclosureDetailView.as_view()),
    path("misconduct-cases/", MisconductCaseListCreateView.as_view()),
    path("misconduct-cases/<int:pk>/", MisconductCaseDetailView.as_view()),
]
