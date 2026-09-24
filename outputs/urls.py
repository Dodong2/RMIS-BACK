from django.urls import path
from .views import (
    ExpectedOutputDetailView,
    ExpectedOutputListCreateView,
    ExpectedVsActualView,
    ProjectOutcomeListCreateView,
    CreativeWorkDetailView,
    CreativeWorkListCreateView,
    IPRecordDetailView,
    IPRecordListCreateView,
    PublicationDetailView,
    PublicationListCreateView,
    SenseRankedPublisherListCreateView,
)

urlpatterns = [
    path("publications/", PublicationListCreateView.as_view()),
    path("publications/<int:pk>/", PublicationDetailView.as_view()),
    path("sense-publishers/", SenseRankedPublisherListCreateView.as_view()),
    path("ip-records/", IPRecordListCreateView.as_view()),
    path("ip-records/<int:pk>/", IPRecordDetailView.as_view()),
    path("creative-works/", CreativeWorkListCreateView.as_view()),
    path("creative-works/<int:pk>/", CreativeWorkDetailView.as_view()),
    path("expected-outputs/", ExpectedOutputListCreateView.as_view()),
    path("expected-outputs/<int:pk>/", ExpectedOutputDetailView.as_view()),
    path("expected-vs-actual/<int:project_id>/", ExpectedVsActualView.as_view()),
    path("outcomes/", ProjectOutcomeListCreateView.as_view()),
]
