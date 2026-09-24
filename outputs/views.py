from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import HasRole
from research_projects.models import Project
from .models import (
    SIX_PS, CreativeWorkRecord, ExpectedOutput, IPRecord, ProjectOutcome, PublicationRecord, SenseRankedPublisher,
)
from .serializers import (
    CREATIVE_WORK_ROLES,
    MANAGE_ROLES,
    REPORT_ROLES,
    CreativeWorkRecordSerializer,
    ExpectedOutputSerializer,
    ProjectOutcomeSerializer,
    IPRecordSerializer,
    PublicationRecordSerializer,
    SenseRankedPublisherSerializer,
)


class RoleWritesMixin:
    write_roles = REPORT_ROLES

    def get_permissions(self):
        if self.request.method in permissions.SAFE_METHODS:
            return [permissions.IsAuthenticated()]
        return [HasRole(self.write_roles)]


class ProjectScopedMixin:
    def get_queryset(self):
        qs = super().get_queryset()
        for param in ("project", "study"):
            value = self.request.query_params.get(param)
            if value:
                qs = qs.filter(**{f"{param}_id": value})
        return qs


class SenseRankedPublisherListCreateView(generics.ListCreateAPIView):
    queryset = SenseRankedPublisher.objects.all().order_by("name")
    serializer_class = SenseRankedPublisherSerializer

    def get_permissions(self):
        if self.request.method == "POST":
            return [HasRole(MANAGE_ROLES)]
        return [permissions.IsAuthenticated()]


class PublicationListCreateView(RoleWritesMixin, ProjectScopedMixin, generics.ListCreateAPIView):
    queryset = PublicationRecord.objects.all().order_by("-published_on")
    serializer_class = PublicationRecordSerializer

    def perform_create(self, serializer):
        serializer.save(recorded_by=self.request.user)


class PublicationDetailView(RoleWritesMixin, generics.RetrieveUpdateAPIView):
    queryset = PublicationRecord.objects.all()
    serializer_class = PublicationRecordSerializer


class IPRecordListCreateView(RoleWritesMixin, ProjectScopedMixin, generics.ListCreateAPIView):
    queryset = IPRecord.objects.all().order_by("-created_at")
    serializer_class = IPRecordSerializer

    def perform_create(self, serializer):
        serializer.save(recorded_by=self.request.user)


class IPRecordDetailView(RoleWritesMixin, generics.RetrieveUpdateAPIView):
    queryset = IPRecord.objects.all()
    serializer_class = IPRecordSerializer


class CreativeWorkListCreateView(RoleWritesMixin, ProjectScopedMixin, generics.ListCreateAPIView):
    write_roles = CREATIVE_WORK_ROLES
    queryset = CreativeWorkRecord.objects.all().order_by("-date_created")
    serializer_class = CreativeWorkRecordSerializer

    def perform_create(self, serializer):
        serializer.save(recorded_by=self.request.user)


class CreativeWorkDetailView(RoleWritesMixin, generics.RetrieveUpdateAPIView):
    write_roles = CREATIVE_WORK_ROLES
    queryset = CreativeWorkRecord.objects.all()
    serializer_class = CreativeWorkRecordSerializer


class ExpectedOutputListCreateView(RoleWritesMixin, ProjectScopedMixin, generics.ListCreateAPIView):
    queryset = ExpectedOutput.objects.select_related("project").order_by("project_id", "category")
    serializer_class = ExpectedOutputSerializer


class ExpectedOutputDetailView(RoleWritesMixin, generics.RetrieveUpdateDestroyAPIView):
    queryset = ExpectedOutput.objects.select_related("project")
    serializer_class = ExpectedOutputSerializer


class ProjectOutcomeListCreateView(RoleWritesMixin, ProjectScopedMixin, generics.ListCreateAPIView):
    queryset = ProjectOutcome.objects.order_by("-created_at")
    serializer_class = ProjectOutcomeSerializer

    def perform_create(self, serializer):
        serializer.save(recorded_by=self.request.user)


class ExpectedVsActualView(APIView):
    """Per-6P target vs actual for one project."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, project_id):
        project = generics.get_object_or_404(Project, pk=project_id)
        rows = ExpectedOutputSerializer(project.expected_outputs.all(), many=True).data
        by_category = []
        for code, label in SIX_PS:
            items = [r for r in rows if r["category"] == code]
            target = sum(r["target_count"] for r in items)
            # Computed categories count every record once per project, not per expected-output row.
            actual = items[0]["actual_count"] if items and code in ("publications", "patents") else sum(r["actual_count"] for r in items)
            by_category.append({
                "category": code, "label": label, "target": target, "actual": actual,
                "met": target > 0 and actual >= target,
            })
        return Response({"project": project.id, "by_category": by_category, "expected_outputs": rows})
