from rest_framework import generics, permissions

from accounts.permissions import HasRole
from .models import (
    AIUseDeclaration,
    ConflictOfInterestDisclosure,
    EthicsReviewReference,
    MisconductCaseReference,
    SimilarityCheckRecord,
)
from .serializers import (
    MANAGE_ROLES,
    AIUseDeclarationSerializer,
    ConflictOfInterestDisclosureSerializer,
    EthicsReviewReferenceSerializer,
    MisconductCaseReferenceSerializer,
    SimilarityCheckRecordSerializer,
)


class ManageWritesMixin:
    """Authenticated read, MANAGE_ROLES (riuh/system_admin) write."""

    def get_permissions(self):
        if self.request.method in permissions.SAFE_METHODS:
            return [permissions.IsAuthenticated()]
        return [HasRole(MANAGE_ROLES)]


class ProjectScopedMixin:
    """Optional ?project= and ?study= query-param filtering."""

    def get_queryset(self):
        qs = super().get_queryset()
        for param in ("project", "study"):
            value = self.request.query_params.get(param)
            if value:
                qs = qs.filter(**{f"{param}_id": value})
        return qs


class EthicsReviewListCreateView(ManageWritesMixin, ProjectScopedMixin, generics.ListCreateAPIView):
    queryset = EthicsReviewReference.objects.all().order_by("-created_at")
    serializer_class = EthicsReviewReferenceSerializer

    def perform_create(self, serializer):
        serializer.save(recorded_by=self.request.user)


class EthicsReviewDetailView(ManageWritesMixin, generics.RetrieveUpdateAPIView):
    queryset = EthicsReviewReference.objects.all()
    serializer_class = EthicsReviewReferenceSerializer


class SimilarityCheckListCreateView(ManageWritesMixin, ProjectScopedMixin, generics.ListCreateAPIView):
    queryset = SimilarityCheckRecord.objects.all().order_by("-checked_on")
    serializer_class = SimilarityCheckRecordSerializer

    def perform_create(self, serializer):
        serializer.save(recorded_by=self.request.user)


class SimilarityCheckDetailView(ManageWritesMixin, generics.RetrieveUpdateAPIView):
    queryset = SimilarityCheckRecord.objects.all()
    serializer_class = SimilarityCheckRecordSerializer


class AIUseDeclarationListCreateView(ProjectScopedMixin, generics.ListCreateAPIView):
    """Any authenticated user may declare their own AI use; no gatekeeping needed."""

    queryset = AIUseDeclaration.objects.all().order_by("-created_at")
    serializer_class = AIUseDeclarationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        serializer.save(declared_by=self.request.user)


class AIUseDeclarationDetailView(generics.RetrieveAPIView):
    queryset = AIUseDeclaration.objects.all()
    serializer_class = AIUseDeclarationSerializer
    permission_classes = [permissions.IsAuthenticated]


class COIDisclosureListCreateView(ProjectScopedMixin, generics.ListCreateAPIView):
    """Any authenticated user may disclose their own conflict of interest."""

    queryset = ConflictOfInterestDisclosure.objects.all().order_by("-created_at")
    serializer_class = ConflictOfInterestDisclosureSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        serializer.save(recorded_by=self.request.user)


class COIDisclosureDetailView(ManageWritesMixin, generics.RetrieveUpdateAPIView):
    """Status/mitigation updates are RIUH-only; the initial disclosure is self-service."""

    queryset = ConflictOfInterestDisclosure.objects.all()
    serializer_class = ConflictOfInterestDisclosureSerializer


class MisconductCaseListCreateView(ManageWritesMixin, ProjectScopedMixin, generics.ListCreateAPIView):
    queryset = MisconductCaseReference.objects.all().order_by("-reported_on")
    serializer_class = MisconductCaseReferenceSerializer

    def perform_create(self, serializer):
        serializer.save(reported_by=self.request.user)


class MisconductCaseDetailView(ManageWritesMixin, generics.RetrieveUpdateAPIView):
    queryset = MisconductCaseReference.objects.all()
    serializer_class = MisconductCaseReferenceSerializer
