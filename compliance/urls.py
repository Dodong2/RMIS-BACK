from django.urls import path
from .models import AIUseDeclaration, ConflictOfInterestDisclosure, EthicsReviewReference, SimilarityCheckRecord
from .serializers import (
    AIUseDeclarationSerializer,
    ConflictOfInterestDisclosureSerializer,
    EthicsReviewReferenceSerializer,
    SimilarityCheckRecordSerializer,
)
from .views import (
    ComplianceRequirementDetailView,
    ComplianceRequirementListCreateView,
    ComplianceRequirementReviewView,
    ComplianceRequirementSubmitView,
    VerifyRecordView,
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
    path("ethics-reviews/<int:pk>/verify/", VerifyRecordView.as_view(model=EthicsReviewReference, serializer_class=EthicsReviewReferenceSerializer)),
    path("similarity-checks/<int:pk>/verify/", VerifyRecordView.as_view(model=SimilarityCheckRecord, serializer_class=SimilarityCheckRecordSerializer)),
    path("ai-declarations/<int:pk>/verify/", VerifyRecordView.as_view(model=AIUseDeclaration, serializer_class=AIUseDeclarationSerializer)),
    path("coi-disclosures/<int:pk>/verify/", VerifyRecordView.as_view(model=ConflictOfInterestDisclosure, serializer_class=ConflictOfInterestDisclosureSerializer)),
    path("requirements/", ComplianceRequirementListCreateView.as_view()),
    path("requirements/<int:pk>/", ComplianceRequirementDetailView.as_view()),
    path("requirements/<int:pk>/submit/", ComplianceRequirementSubmitView.as_view()),
    path("requirements/<int:pk>/review/", ComplianceRequirementReviewView.as_view()),
    path("misconduct-cases/", MisconductCaseListCreateView.as_view()),
    path("misconduct-cases/<int:pk>/", MisconductCaseDetailView.as_view()),
]
