from django.urls import path
from .views import (
    DocumentArchiveView, DocumentDetailView, DocumentListCreateView, DocumentReviewView, DocumentShareListCreateView,
    DocumentShareRevokeView, ProposalFormSaveView, StagedDocumentUploadView,
)

urlpatterns = [
    path("documents/", DocumentListCreateView.as_view()),
    path("documents/staged/", StagedDocumentUploadView.as_view()),
    path("documents/proposal-form/", ProposalFormSaveView.as_view()),
    path("documents/<int:pk>/", DocumentDetailView.as_view()),
    path("documents/<int:pk>/archive/", DocumentArchiveView.as_view()),
    path("documents/<int:pk>/review/", DocumentReviewView.as_view()),
    path("documents/<int:pk>/shares/", DocumentShareListCreateView.as_view()),
    path("documents/shares/<int:pk>/revoke/", DocumentShareRevokeView.as_view()),
]
