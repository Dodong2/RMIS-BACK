from django.urls import path
from .views import DocumentArchiveView, DocumentDetailView, DocumentListCreateView

urlpatterns = [
    path("documents/", DocumentListCreateView.as_view()),
    path("documents/<int:pk>/", DocumentDetailView.as_view()),
    path("documents/<int:pk>/archive/", DocumentArchiveView.as_view()),
]
