from datetime import date

from rest_framework import generics, permissions
from accounts.permissions import HasRole, ensure_in_scope
from .models import Program, Project, ProjectStatusHistory, Study, WorkPlanMilestone
from .serializers import (
    ProgramSerializer, ProjectSerializer, ProjectStatusHistorySerializer, StudySerializer, WorkPlanMilestoneSerializer,
)

# Seed source for the permission table (accounts/permission_seed.py); gates use permission codes.
REGISTRATION_ROLES = ["system_admin", "crc_chair"]
# Leaders capture their own work plan (Module Structure M2); ensure_in_scope limits them to their projects.
MILESTONE_ROLES = REGISTRATION_ROLES + ["program_leader", "project_leader", "study_leader"]


class ProgramListCreateView(generics.ListCreateAPIView):
    queryset = Program.objects.all().order_by("-created_at")
    serializer_class = ProgramSerializer

    def get_permissions(self):
        if self.request.method == "POST":
            return [HasRole("projects.register")]
        return [permissions.IsAuthenticated()]


class ProgramDetailView(generics.RetrieveUpdateAPIView):
    queryset = Program.objects.all()
    serializer_class = ProgramSerializer

    def get_permissions(self):
        if self.request.method in ("PUT", "PATCH"):
            return [HasRole("projects.register")]
        return [permissions.IsAuthenticated()]


class ProjectListCreateView(generics.ListCreateAPIView):
    queryset = Project.objects.all().order_by("-created_at")
    serializer_class = ProjectSerializer

    def get_permissions(self):
        if self.request.method == "POST":
            return [HasRole("projects.register")]
        return [permissions.IsAuthenticated()]


class ProjectDetailView(generics.RetrieveUpdateAPIView):
    queryset = Project.objects.all()
    serializer_class = ProjectSerializer

    def get_permissions(self):
        if self.request.method in ("PUT", "PATCH"):
            return [HasRole("projects.register")]
        return [permissions.IsAuthenticated()]

    def perform_update(self, serializer):
        old_status = serializer.instance.status
        project = serializer.save()
        if project.status != old_status:
            ProjectStatusHistory.objects.create(
                project=project, from_status=old_status, to_status=project.status,
                remarks=self.request.data.get("status_remarks", ""), changed_by=self.request.user,
            )


class ProjectStatusHistoryView(generics.ListAPIView):
    serializer_class = ProjectStatusHistorySerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return ProjectStatusHistory.objects.filter(project_id=self.kwargs["pk"]).select_related("changed_by").order_by("-changed_at", "-id")


class StudyListCreateView(generics.ListCreateAPIView):
    serializer_class = StudySerializer

    def get_queryset(self):
        qs = Study.objects.all().order_by("-created_at")
        project_id = self.request.query_params.get("project")
        if project_id:
            qs = qs.filter(project_id=project_id)
        return qs

    def get_permissions(self):
        if self.request.method == "POST":
            return [HasRole("projects.register")]
        return [permissions.IsAuthenticated()]


class StudyDetailView(generics.RetrieveUpdateAPIView):
    queryset = Study.objects.all()
    serializer_class = StudySerializer

    def get_permissions(self):
        if self.request.method in ("PUT", "PATCH"):
            return [HasRole("projects.register")]
        return [permissions.IsAuthenticated()]


class MilestoneListCreateView(generics.ListCreateAPIView):
    serializer_class = WorkPlanMilestoneSerializer

    def get_queryset(self):
        qs = WorkPlanMilestone.objects.select_related("responsible").order_by("target_date")
        project_id = self.request.query_params.get("project")
        if project_id:
            qs = qs.filter(project_id=project_id)
        if self.request.query_params.get("delayed") == "true":
            qs = qs.filter(target_date__lt=date.today()).exclude(status="done")
        return qs

    def get_permissions(self):
        if self.request.method == "POST":
            return [HasRole("projects.manage_milestones")]
        return [permissions.IsAuthenticated()]


class MilestoneDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = WorkPlanMilestone.objects.all()
    serializer_class = WorkPlanMilestoneSerializer

    def get_permissions(self):
        if self.request.method in ("PUT", "PATCH", "DELETE"):
            return [HasRole("projects.manage_milestones")]
        return [permissions.IsAuthenticated()]

    def perform_destroy(self, instance):
        ensure_in_scope(self.get_serializer(), instance.project)
        instance.delete()