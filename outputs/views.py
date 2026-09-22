from rest_framework import generics, permissions

from accounts.permissions import HasRole
from .models import CreativeWorkRecord, IPRecord, PublicationRecord, SenseRankedPublisher
from .serializers import (
    CREATIVE_WORK_ROLES,
    MANAGE_ROLES,
    REPORT_ROLES,
    CreativeWorkRecordSerializer,
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
