from datetime import date

from django.db import transaction
from django.http import HttpResponse
from rest_framework import generics, permissions, status
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView
from accounts.permissions import HasRole, ProjectVisibleMixin, ensure_in_scope, role_can
from budget_lib.serializers import LineItemBudgetSerializer, LineItemSerializer
from . import importer
from .models import (
    CollegeUnit, Program, Project, ProjectStatusHistory, ProjectTeamMember, Study, TargetBeneficiary, WorkPlanMilestone,
)
from .serializers import (
    CollegeUnitSerializer, ProgramSerializer, ProjectEndorserSerializer, ProjectSerializer, ProjectStatusHistorySerializer,
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


class CollegeUnitListCreateView(generics.ListCreateAPIView):
    """Everyone signed in reads the list (it feeds the registration dropdown); only the System Admin edits it."""

    queryset = CollegeUnit.objects.all()
    serializer_class = CollegeUnitSerializer

    def get_permissions(self):
        if self.request.method == "POST":
            return [HasRole("accounts.manage_users")]
        return [permissions.IsAuthenticated()]


class CollegeUnitDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = CollegeUnit.objects.all()
    serializer_class = CollegeUnitSerializer

    def get_permissions(self):
        if self.request.method in ("PUT", "PATCH", "DELETE"):
            return [HasRole("accounts.manage_users")]
        return [permissions.IsAuthenticated()]


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


class ProjectListCreateView(ProjectVisibleMixin, generics.ListCreateAPIView):
    project_lookup = ""
    queryset = Project.objects.all().order_by("-created_at")
    serializer_class = ProjectSerializer

    def get_permissions(self):
        if self.request.method == "POST":
            return [HasRole("projects.register")]
        return [permissions.IsAuthenticated()]


class ProjectDetailView(ProjectVisibleMixin, generics.RetrieveUpdateAPIView):
    project_lookup = ""
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


class ProjectLibView(APIView):
    """POST {"line_items": [{category, description, fiscal_year?, q1_amount..q4_amount, amount?}]}: the registration
    wizard's Budget Requirements step (client meeting 2026-10-01, #11) as draft LIB v1. Gated by projects.register,
    not budget.manage, because CRC Chair/DRD/RIUH register projects but don't encode budgets otherwise.
    All-or-nothing; a project that already has a LIB is refused."""

    permission_classes = [HasRole("projects.register")]

    def post(self, request, pk):
        project = generics.get_object_or_404(Project, pk=pk)
        rows = request.data.get("line_items")
        if not isinstance(rows, list) or not rows:
            return Response({"line_items": "Send at least one line item."}, status=status.HTTP_400_BAD_REQUEST)
        if project.budgets.exists():
            return Response({"detail": "This project already has a LIB. Edit it under Budget Management."},
                            status=status.HTTP_400_BAD_REQUEST)
        context = {"request": request}
        with transaction.atomic():
            budget = LineItemBudgetSerializer(data={"project": project.pk}, context=context)
            budget.is_valid(raise_exception=True)
            budget = budget.save()
            errors = []
            for index, row in enumerate(rows, start=1):
                data = importer.fill_line_item_amount({**row, "budget": budget.pk})
                item = LineItemSerializer(data=data, context=context)
                if item.is_valid():
                    item.save()
                else:
                    errors.append({"row": index, "errors": item.errors})
            if errors:
                transaction.set_rollback(True)
                return Response({"errors": errors}, status=status.HTTP_400_BAD_REQUEST)
        return Response(LineItemBudgetSerializer(budget).data, status=status.HTTP_201_CREATED)


class ProjectImportTemplateView(APIView):
    """Blank LSPU-RDO-SF-018 Excel template for ProjectImportView."""

    permission_classes = [HasRole("projects.register")]

    def get(self, request):
        response = HttpResponse(importer.build_template(), content_type=XLSX_TYPE)
        response["Content-Disposition"] = 'attachment; filename="rmis_project_registration_template.xlsx"'
        return response


class ProjectImportView(APIView):
    """POST multipart `file`: registers one project (plus team, studies, 6Ps, beneficiaries, LIB, work plan)
    from a filled template. All-or-nothing: any row error rolls the whole import back and lists every error.
    `?dry_run=1` runs the same import, returns {"preview": ...} for the SF-018 preview, and always rolls back."""

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
            if request.query_params.get("dry_run") == "1":
                preview = importer.proposal_preview(project)
                transaction.set_rollback(True)
                return Response({"preview": preview})
        return Response(ProjectSerializer(project).data, status=status.HTTP_201_CREATED)


class ProjectChildListCreateView(ProjectVisibleMixin, generics.ListCreateAPIView):
    """List (?project=) and create rows of a project's form table; writes need projects.edit."""

    def get_queryset(self):
        qs = self.serializer_class.Meta.model.objects.order_by("id")
        project_id = self.request.query_params.get("project")
        return qs.filter(project_id=project_id) if project_id else qs

    def get_permissions(self):
        if self.request.method == "POST":
            return [HasRole("projects.edit")]
        return [permissions.IsAuthenticated()]


class ProjectChildDetailView(ProjectVisibleMixin, generics.RetrieveUpdateDestroyAPIView):
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


class ProjectStatusHistoryView(ProjectVisibleMixin, generics.ListAPIView):
    serializer_class = ProjectStatusHistorySerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return ProjectStatusHistory.objects.filter(project_id=self.kwargs["pk"]).select_related("changed_by").order_by("-changed_at", "-id")


class StudyListCreateView(ProjectVisibleMixin, generics.ListCreateAPIView):
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


class StudyDetailView(ProjectVisibleMixin, generics.RetrieveUpdateAPIView):
    queryset = Study.objects.all()
    serializer_class = StudySerializer

    def get_permissions(self):
        if self.request.method in ("PUT", "PATCH"):
            return [HasRole("projects.edit")]
        return [permissions.IsAuthenticated()]


class MilestoneListCreateView(ProjectVisibleMixin, generics.ListCreateAPIView):
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
            # Registrants enter Section XI (work plan) in the registration wizard, same as the Excel import.
            if self.request.user.is_authenticated and role_can(self.request.user, "projects.register"):
                return [permissions.IsAuthenticated()]
            return [HasRole("projects.manage_milestones")]
        return [permissions.IsAuthenticated()]


class MilestoneDetailView(ProjectVisibleMixin, generics.RetrieveUpdateDestroyAPIView):
    queryset = WorkPlanMilestone.objects.all()
    serializer_class = WorkPlanMilestoneSerializer

    def get_permissions(self):
        if self.request.method in ("PUT", "PATCH", "DELETE"):
            return [HasRole("projects.manage_milestones")]
        return [permissions.IsAuthenticated()]

    def perform_destroy(self, instance):
        ensure_in_scope(self.get_serializer(), instance.project)
        instance.delete()