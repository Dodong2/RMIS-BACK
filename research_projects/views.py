from datetime import date

from django.db import transaction
from django.http import HttpResponse
from rest_framework import generics, permissions, status
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView
from accounts.permissions import HasRole, ensure_in_scope
from . import importer
from .models import (
    Program, Project, ProjectStatusHistory, ProjectTeamMember, Study, TargetBeneficiary, WorkPlanMilestone,
)
from .serializers import (
    ProgramSerializer, ProjectEndorserSerializer, ProjectSerializer, ProjectStatusHistorySerializer,
    ProjectTeamMemberSerializer, StudySerializer,
    TargetBeneficiarySerializer, WorkPlanMilestoneSerializer, ensure_registrant_in_scope,
)

XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Seed source for the permission table (accounts/permission_seed.py); gates use permission codes.
# Client decision 2026-09-29 (Option A, per Clarification Answers Q4 + summary table): CRC Chair, DRD and RIUH
# register programs/projects/studies (manual entry and Excel import). Client meeting 2026-10-01 added the Project
# Leader back, for projects they lead only (serializers.ensure_project_leader_registers_self).
REGISTRATION_ROLES = ["system_admin", "crc_chair", "drd", "riuh", "project_leader"]
# Leaders are limited to records they are part of, and can't change the CRC-owned fields
# (serializers.ensure_registrant_in_scope / ensure_leader_keeps).
EDIT_ROLES = REGISTRATION_ROLES + ["program_leader", "study_leader"]
# Leaders capture their own work plan (Module Structure M2); ensure_in_scope limits them to their projects.
MILESTONE_ROLES = ["system_admin", "crc_chair", "program_leader", "project_leader", "study_leader"]


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
            return [HasRole("projects.edit")]
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
            return [HasRole("projects.edit")]
        return [permissions.IsAuthenticated()]

    def perform_update(self, serializer):
        old_status = serializer.instance.status
        project = serializer.save()
        if project.status != old_status:
            ProjectStatusHistory.objects.create(
                project=project, from_status=old_status, to_status=project.status,
                remarks=self.request.data.get("status_remarks", ""), changed_by=self.request.user,
            )


class ProjectCodeAvailableView(APIView):
    """GET ?code=: whether an official project code is still free (client meeting 2026-10-01, #3). A leader's project
    list only shows their own projects, so the wizard can't check this from the list."""

    permission_classes = [HasRole("projects.register")]

    def get(self, request):
        code = request.query_params.get("code", "").strip()
        if not code:
            return Response({"code": "Pass the project code as ?code=."}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"code": code, "available": not Project.objects.filter(project_code=code).exists()})


class ProjectImportTemplateView(APIView):
    """Blank LSPU-RDO-SF-018 Excel template for ProjectImportView."""

    permission_classes = [HasRole("projects.register")]

    def get(self, request):
        response = HttpResponse(importer.build_template(), content_type=XLSX_TYPE)
        response["Content-Disposition"] = 'attachment; filename="rmis_project_registration_template.xlsx"'
        return response


class ProjectImportView(APIView):
    """POST multipart `file`: registers one project (plus team, studies, 6Ps, beneficiaries, LIB, work plan)
    from a filled template. All-or-nothing: any row error rolls the whole import back and lists every error."""

    permission_classes = [HasRole("projects.register")]
    parser_classes = [MultiPartParser]

    def post(self, request):
        file_obj = request.FILES.get("file")
        if not file_obj:
            return Response({"file": "Upload the filled .xlsx template as `file`."}, status=status.HTTP_400_BAD_REQUEST)
        with transaction.atomic():
            project, errors = importer.import_workbook(file_obj, request)
            if errors:
                transaction.set_rollback(True)
                return Response({"errors": errors}, status=status.HTTP_400_BAD_REQUEST)
        return Response(ProjectSerializer(project).data, status=status.HTTP_201_CREATED)


class ProjectChildListCreateView(generics.ListCreateAPIView):
    """List (?project=) and create rows of a project's form table; writes need projects.edit."""

    def get_queryset(self):
        qs = self.serializer_class.Meta.model.objects.order_by("id")
        project_id = self.request.query_params.get("project")
        return qs.filter(project_id=project_id) if project_id else qs

    def get_permissions(self):
        if self.request.method == "POST":
            return [HasRole("projects.edit")]
        return [permissions.IsAuthenticated()]


class ProjectChildDetailView(generics.RetrieveUpdateDestroyAPIView):
    def get_queryset(self):
        return self.serializer_class.Meta.model.objects.all()

    def perform_destroy(self, instance):
        ensure_registrant_in_scope(self.get_serializer(), instance.project)
        instance.delete()

    def get_permissions(self):
        if self.request.method in ("PUT", "PATCH", "DELETE"):
            return [HasRole("projects.edit")]
        return [permissions.IsAuthenticated()]


class TeamMemberListCreateView(ProjectChildListCreateView):
    serializer_class = ProjectTeamMemberSerializer


class TeamMemberDetailView(ProjectChildDetailView):
    serializer_class = ProjectTeamMemberSerializer


class EndorserListCreateView(ProjectChildListCreateView):
    serializer_class = ProjectEndorserSerializer


class EndorserDetailView(ProjectChildDetailView):
    serializer_class = ProjectEndorserSerializer


class BeneficiaryListCreateView(ProjectChildListCreateView):
    serializer_class = TargetBeneficiarySerializer


class BeneficiaryDetailView(ProjectChildDetailView):
    serializer_class = TargetBeneficiarySerializer


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
            return [HasRole("projects.edit")]
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