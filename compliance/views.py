from django.db import transaction
from django.utils import timezone
from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User
from accounts.permissions import HasRole, role_can
from accounts.serializers import UserListSerializer
from config.concurrency import lock
from .models import (
    ComplianceRequirement,
    AIUseDeclaration,
    ConflictOfInterestDisclosure,
    EthicsReviewReference,
    MisconductCaseReference,
    SimilarityCheckRecord,
)
from .serializers import (
    ComplianceRequirementSerializer,
    AIUseDeclarationSerializer,
    ConflictOfInterestDisclosureSerializer,
    EthicsReviewReferenceSerializer,
    MisconductCaseReferenceSerializer,
    SimilarityCheckRecordSerializer,
)


class ComplianceAccessMixin:
    """Client Task 79 (2026-11-18): every Compliance endpoint needs compliance.view (System Admin, VP for REI,
    University Administration), on top of the view's own read/write rule."""

    def get_permissions(self):
        return [HasRole("compliance.view"), *super().get_permissions()]


class ManageWritesMixin:
    """Authenticated read, compliance.manage (riuh/system_admin) write."""

    def get_permissions(self):
        if self.request.method in permissions.SAFE_METHODS:
            return [permissions.IsAuthenticated()]
        return [HasRole("compliance.manage")]


class EncodeWritesMixin:
    """Authenticated read, compliance.encode (leaders + riuh/system_admin) write. Edits clear RIUH verification."""

    def get_permissions(self):
        if self.request.method in permissions.SAFE_METHODS:
            return [permissions.IsAuthenticated()]
        return [HasRole("compliance.encode")]

    def perform_update(self, serializer):
        serializer.save(verified_by=None, verified_at=None)


class ProjectScopedMixin:
    """Optional ?project= and ?study= query-param filtering."""

    def get_queryset(self):
        qs = super().get_queryset()
        for param in ("project", "study"):
            value = self.request.query_params.get(param)
            if value:
                qs = qs.filter(**{f"{param}_id": value})
        return qs


class EthicsReviewListCreateView(ComplianceAccessMixin, EncodeWritesMixin, ProjectScopedMixin, generics.ListCreateAPIView):
    queryset = EthicsReviewReference.objects.all().order_by("-created_at")
    serializer_class = EthicsReviewReferenceSerializer

    def perform_create(self, serializer):
        serializer.save(recorded_by=self.request.user)


class EthicsReviewDetailView(ComplianceAccessMixin, EncodeWritesMixin, generics.RetrieveUpdateAPIView):
    queryset = EthicsReviewReference.objects.all()
    serializer_class = EthicsReviewReferenceSerializer


class SimilarityCheckListCreateView(ComplianceAccessMixin, EncodeWritesMixin, ProjectScopedMixin, generics.ListCreateAPIView):
    queryset = SimilarityCheckRecord.objects.all().order_by("-checked_on")
    serializer_class = SimilarityCheckRecordSerializer

    def perform_create(self, serializer):
        serializer.save(recorded_by=self.request.user)


class SimilarityCheckDetailView(ComplianceAccessMixin, EncodeWritesMixin, generics.RetrieveUpdateAPIView):
    queryset = SimilarityCheckRecord.objects.all()
    serializer_class = SimilarityCheckRecordSerializer


class AIUseDeclarationListCreateView(ComplianceAccessMixin, ProjectScopedMixin, generics.ListCreateAPIView):
    """Any authenticated user may declare their own AI use; no gatekeeping needed."""

    queryset = AIUseDeclaration.objects.all().order_by("-created_at")
    serializer_class = AIUseDeclarationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        serializer.save(declared_by=self.request.user)


class AIUseDeclarationDetailView(ComplianceAccessMixin, generics.RetrieveAPIView):
    queryset = AIUseDeclaration.objects.all()
    serializer_class = AIUseDeclarationSerializer
    permission_classes = [permissions.IsAuthenticated]


class COIDisclosureListCreateView(ComplianceAccessMixin, ProjectScopedMixin, generics.ListCreateAPIView):
    """Any authenticated user may disclose their own conflict of interest."""

    queryset = ConflictOfInterestDisclosure.objects.all().order_by("-created_at")
    serializer_class = ConflictOfInterestDisclosureSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        serializer.save(recorded_by=self.request.user)


class COIDisclosureDetailView(ComplianceAccessMixin, ManageWritesMixin, generics.RetrieveUpdateAPIView):
    """Status/mitigation updates are RIUH-only; the initial disclosure is self-service."""

    queryset = ConflictOfInterestDisclosure.objects.all()
    serializer_class = ConflictOfInterestDisclosureSerializer


class MisconductCaseListCreateView(ComplianceAccessMixin, ManageWritesMixin, ProjectScopedMixin, generics.ListCreateAPIView):
    queryset = MisconductCaseReference.objects.all().order_by("-reported_on")
    serializer_class = MisconductCaseReferenceSerializer

    def perform_create(self, serializer):
        serializer.save(reported_by=self.request.user)


class MisconductCaseDetailView(ComplianceAccessMixin, ManageWritesMixin, generics.RetrieveUpdateAPIView):
    queryset = MisconductCaseReference.objects.all()
    serializer_class = MisconductCaseReferenceSerializer


class VerifyRecordView(ComplianceAccessMixin, APIView):
    """RIUH verifies a leader-encoded compliance record. POST sets verified_by/at."""

    permission_classes = [HasRole("compliance.manage")]
    model = None
    serializer_class = None

    @transaction.atomic
    def post(self, request, pk):
        record = lock(self.model.objects.all(), pk=pk)
        if record.verified_at:
            return Response({"detail": "This record is already verified."}, status=400)
        record.verified_by, record.verified_at = request.user, timezone.now()
        record.save(update_fields=["verified_by", "verified_at"])
        return Response(self.serializer_class(record).data)


class ComplianceRequirementListCreateView(ComplianceAccessMixin, EncodeWritesMixin, ProjectScopedMixin, generics.ListCreateAPIView):
    serializer_class = ComplianceRequirementSerializer
    queryset = ComplianceRequirement.objects.order_by("deadline")

    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params
        for param in ("status", "responsible"):
            if params.get(param):
                qs = qs.filter(**{param: params[param]})
        if params.get("overdue") == "true":
            qs = qs.filter(status__in=("pending", "returned"), deadline__lt=timezone.localdate())
        return qs

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class ComplianceRequirementDetailView(ComplianceAccessMixin, EncodeWritesMixin, generics.RetrieveUpdateAPIView):
    serializer_class = ComplianceRequirementSerializer
    queryset = ComplianceRequirement.objects.all()

    def perform_update(self, serializer):
        serializer.save()  # requirements have their own review flow, not RIUH verification


class ComplianceRequirementSubmitView(ComplianceAccessMixin, APIView):
    """The responsible person (or an encoder) submits: POST {"document": <id>?}."""

    permission_classes = [permissions.IsAuthenticated]

    @transaction.atomic
    def post(self, request, pk):
        requirement = lock(ComplianceRequirement.objects.all(), pk=pk)
        if requirement.responsible_id != request.user.id and not role_can(request.user, "compliance.encode"):
            return Response({"detail": "Only the responsible person can submit this requirement."}, status=403)
        if requirement.status not in ("pending", "returned"):
            return Response({"detail": f"A '{requirement.status}' requirement can't be submitted."}, status=400)
        serializer = ComplianceRequirementSerializer(requirement, data={"document": request.data.get("document")}, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save(status="submitted", submitted_at=timezone.now())
        return Response(serializer.data)


class ComplianceRequirementReviewView(ComplianceAccessMixin, APIView):
    """RIUH reviews: POST {"status": "compliant" | "returned" | "non_compliant", "review_remarks": ...}."""

    permission_classes = [HasRole("compliance.manage")]

    @transaction.atomic
    def post(self, request, pk):
        requirement = lock(ComplianceRequirement.objects.all(), pk=pk)
        decision = request.data.get("status")
        if decision not in ("compliant", "returned", "non_compliant"):
            return Response({"status": "must be 'compliant', 'returned', or 'non_compliant'."}, status=400)
        if requirement.status != "submitted":
            return Response({"detail": "Only a submitted requirement can be reviewed."}, status=400)
        requirement.status = decision
        requirement.review_remarks = request.data.get("review_remarks", "")
        requirement.reviewed_by, requirement.reviewed_at = request.user, timezone.now()
        requirement.save()
        return Response(ComplianceRequirementSerializer(requirement).data)


class ComplianceAssignableUsersView(ComplianceAccessMixin, generics.ListAPIView):
    """Task 79-B: people a requirement can be assigned to = active accounts whose role has Compliance."""

    serializer_class = UserListSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return (
            User.objects.filter(is_active=True, is_pending_role=False, role__role_permissions__permission__code="compliance.view")
            .select_related("role").distinct().order_by("first_name", "last_name", "email")
        )
