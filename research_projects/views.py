from rest_framework import generics, permissions
from accounts.permissions import HasRole
from .models import Program, Project, Study, WorkPlanMilestone
from .serializers import ProgramSerializer, ProjectSerializer, StudySerializer, WorkPlanMilestoneSerializer

REGISTRATION_ROLES = ["system_admin", "crc_chair"]


class ProgramListCreateView(generics.ListCreateAPIView):
    queryset = Program.objects.all().order_by("-created_at")
    serializer_class = ProgramSerializer

    def get_permissions(self):
        if self.request.method == "POST":
            return [HasRole(REGISTRATION_ROLES)]
        return [permissions.IsAuthenticated()]


class ProgramDetailView(generics.RetrieveUpdateAPIView):
    queryset = Program.objects.all()
    serializer_class = ProgramSerializer

    def get_permissions(self):
        if self.request.method in ("PUT", "PATCH"):
            return [HasRole(REGISTRATION_ROLES)]
        return [permissions.IsAuthenticated()]


class ProjectListCreateView(generics.ListCreateAPIView):
    queryset = Project.objects.all().order_by("-created_at")
    serializer_class = ProjectSerializer

    def get_permissions(self):
        if self.request.method == "POST":
            return [HasRole(REGISTRATION_ROLES)]
        return [permissions.IsAuthenticated()]


class ProjectDetailView(generics.RetrieveUpdateAPIView):
    queryset = Project.objects.all()
    serializer_class = ProjectSerializer

    def get_permissions(self):
        if self.request.method in ("PUT", "PATCH"):
            return [HasRole(REGISTRATION_ROLES)]
        return [permissions.IsAuthenticated()]


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
            return [HasRole(REGISTRATION_ROLES)]
        return [permissions.IsAuthenticated()]


class StudyDetailView(generics.RetrieveUpdateAPIView):
    queryset = Study.objects.all()
    serializer_class = StudySerializer

    def get_permissions(self):
        if self.request.method in ("PUT", "PATCH"):
            return [HasRole(REGISTRATION_ROLES)]
        return [permissions.IsAuthenticated()]


class MilestoneListCreateView(generics.ListCreateAPIView):
    serializer_class = WorkPlanMilestoneSerializer

    def get_queryset(self):
        qs = WorkPlanMilestone.objects.all().order_by("target_date")
        project_id = self.request.query_params.get("project")
        if project_id:
            qs = qs.filter(project_id=project_id)
        return qs

    def get_permissions(self):
        if self.request.method == "POST":
            return [HasRole(REGISTRATION_ROLES)]
        return [permissions.IsAuthenticated()]


class MilestoneDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = WorkPlanMilestone.objects.all()
    serializer_class = WorkPlanMilestoneSerializer

    def get_permissions(self):
        if self.request.method in ("PUT", "PATCH", "DELETE"):
            return [HasRole(REGISTRATION_ROLES)]
        return [permissions.IsAuthenticated()]