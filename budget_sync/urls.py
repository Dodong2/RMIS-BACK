from django.urls import path

from .views import ImportListCreateView, ReconciliationView, RecordDetailView, RecordListView

urlpatterns = [
    path("imports/", ImportListCreateView.as_view()),
    path("records/", RecordListView.as_view()),
    path("records/<int:pk>/", RecordDetailView.as_view()),
    path("reconciliation/", ReconciliationView.as_view()),
]
