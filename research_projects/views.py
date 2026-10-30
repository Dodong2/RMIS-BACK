import logging
from datetime import date

import requests
from django.db import transaction
from django.http import HttpResponse
from rest_framework import generics, permissions, status
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView
from accounts.permissions import HasRole, ProjectVisibleMixin, acting_for, ensure_in_scope, role_can
from budget_lib.models import allocation_periods
from budget_lib.serializers import LineItemBudgetSerializer, LineItemSerializer
from config.concurrency import AtomicMutationMixin, idempotent, lock
from document_management.storage import delete_documents
from outputs.serializers import ExpectedOutputSerializer
from . import importer
from .models import (
    CollegeUnit, CooperatingAgency, EndorserChoice, FundingType, Program, RdeThrust, Project, ProjectStatusHistory, ProjectTeamMember, Study, TargetBeneficiary, WorkPlanMilestone,
)
from .serializers import (
    CollegeUnitSerializer, CooperatingAgencySerializer, EndorserChoiceSerializer, FundingTypeSerializer, ProgramSerializer, RdeThrustSerializer, ProjectEndorserSerializer, ProjectSerializer, ProjectStatusHistorySerializer,
    ProjectTeamMemberSerializer, StudySerializer,
    TargetBeneficiarySerializer, WorkPlanMilestoneSerializer, can_edit_registration, ensure_registrant_in_scope,
)
from .workflow import REVIEW_STATUS_LABELS, ensure_registration_open, review_status

logger = logging.getLogger(__name__)

XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Seed source for the permission table (accounts/permission_seed.py); gates use permission codes.
# Client decision 2026-09-29 (Option A, per Clarification Answers Q4 + summary table): CRC Chair, DRD and RIUH
# register programs/projects/studies (manual entry and Excel import). Client meeting 2026-10-01 added the Project
# Leader back, for projects they lead only (serializers.ensure_project_leader_registers_self).
# Client 2026-10-24: the CRC Chair reviews submitted projects and no longer registers them (accounts 0024)
REGISTRATION_ROLES = ["system_admin", "riuh", "project_leader"]
# Leaders are limited to records they are part of, and can't change the CRC-owned fields
# (serializers.ensure_registrant_in_scope / ensure_leader_keeps).
EDIT_ROLES = REGISTRATION_ROLES + ["crc_chair"]
# Leaders capture their own work plan (Module Structure M2); ensure_in_scope limits them to their projects.
MILESTONE_ROLES = ["system_admin", "crc_chair", "project_leader"]

# Client 2026-10-29 (Task 4): Manual Entry may send the form's tables with the project. They are saved in the same
# transaction through the serializers of their own endpoints, so one bad row leaves nothing behind. A table that
# isn't sent, or is sent empty, adds no rows; "line_items" is the draft LIB (create_project_lib).
REGISTRATION_TABLES = {
    "team": ProjectTeamMemberSerializer, "studies": StudySerializer, "outputs": ExpectedOutputSerializer,
    "beneficiaries": TargetBeneficiarySerializer, "milestones": WorkPlanMilestoneSerializer,
    "endorsers": ProjectEndorserSerializer,
}


class AdminChoiceListCreateView(generics.ListCreateAPIView):
    """Registration dropdown choices (see AdminChoice). Everyone signed in reads the list; only the System Admin
    edits it. urls.py passes queryset/serializer_class per choice list."""

    def get_permissions(self):
        if self.request.method == "POST":
            return [HasRole("accounts.manage_users")]
        return [permissions.IsAuthenticated()]


class AdminChoiceDetailView(generics.RetrieveUpdateDestroyAPIView):
    def get_permissions(self):
        if self.request.method in ("PUT", "PATCH", "DELETE"):
            return [HasRole("accounts.manage_users")]
        return [permissions.IsAuthenticated()]

    def destroy(self, request, *args, **kwargs):
        # Projects store a Funding Type's code, so a used or system type can't go (the other choices are copied as text)
        choice = self.get_object()
        if isinstance(choice, RdeThrust) and choice.priorities.exists():
            return Response({"detail": "This thrust still has priority areas; delete those first."}, status=status.HTTP_400_BAD_REQUEST)
        if isinstance(choice, FundingType):
            if choice.is_system:
                return Response({"detail": "This is one of the Manual's funding types; rename it instead."}, status=status.HTTP_400_BAD_REQUEST)
            if Project.objects.filter(funding_type=choice.code).exists() or Program.objects.filter(funding_type=choice.code).exists():
                return Response({"detail": "Projects use this funding type, so it can't be deleted. Rename it instead."}, status=status.HTTP_400_BAD_REQUEST)
        return super().destroy(request, *args, **kwargs)


ADMIN_CHOICES = {
    "college-units": (CollegeUnit, CollegeUnitSerializer),
    "rde-thrusts": (RdeThrust, RdeThrustSerializer),
    "cooperating-agencies": (CooperatingAgency, CooperatingAgencySerializer),
    "endorsers": (EndorserChoice, EndorserChoiceSerializer),
    "funding-types": (FundingType, FundingTypeSerializer),
}


class ProgramListCreateView(AtomicMutationMixin, generics.ListCreateAPIView):
    queryset = Program.objects.all().order_by("-created_at")
    serializer_class = ProgramSerializer

    def get_permissions(self):
        if self.request.method == "POST":
            return [HasRole("projects.register")]
        return [permissions.IsAuthenticated()]


class ProgramDetailView(AtomicMutationMixin, generics.RetrieveUpdateAPIView):
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

    @idempotent  # registration: a retried submit replays the first result instead of a duplicate-code error
    def create(self, request, *args, **kwargs):
        tables = {key: request.data[key] for key in (*REGISTRATION_TABLES, "line_items") if key in request.data}
        if not tables:
            return super().create(request, *args, **kwargs)
        serializer = self.get_serializer(data={k: v for k, v in request.data.items() if k not in tables})
        serializer.is_valid(raise_exception=True)
        project = serializer.save()
        context = self.get_serializer_context()
        errors = {}
        for key, rows in tables.items():
            if not isinstance(rows, list):
                errors[key] = "Send a list."
                continue
            if key == "line_items":
                row_errors = create_project_lib(project, rows, request)[1] if rows else []
            else:
                row_errors = []
                for index, row in enumerate(rows, start=1):  # in order, so endorsers keep their Annex A order
                    if not isinstance(row, dict):
                        row_errors.append({"row": index, "errors": "Send each row as an object."})
                        continue
                    item = REGISTRATION_TABLES[key](data={**row, "project": project.pk}, context=context)
                    if item.is_valid():
                        item.save()
                    else:
                        row_errors.append({"row": index, "errors": item.errors})
            if row_errors:
                errors[key] = row_errors
        if errors:
            transaction.set_rollback(True)  # idempotent() commits a 4xx response's work otherwise
            return Response({"errors": errors}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(project).data, status=status.HTTP_201_CREATED)

    def get_permissions(self):
        if self.request.method == "POST":
            return [HasRole("projects.register")]
        return [permissions.IsAuthenticated()]


class ProjectDetailView(AtomicMutationMixin, ProjectVisibleMixin, generics.RetrieveUpdateDestroyAPIView):
    project_lookup = ""
    queryset = Project.objects.all()
    serializer_class = ProjectSerializer

    def get_permissions(self):
        if self.request.method in ("PUT", "PATCH"):
            return [HasRole("projects.edit")]
        return [permissions.IsAuthenticated()]

    @transaction.atomic
    def destroy(self, request, *args, **kwargs):
        """Task 15/16 (2026-10-30): only a Draft (never submitted) can be deleted, by its Project Leader (or acting
        replacement) or the System Admin. Its rows, draft LIB and documents go with it; the stored files are removed
        after commit, and a storage failure is only logged."""
        project = lock(Project.objects, pk=self.get_object().pk)
        user = request.user
        if not (user.role and user.role.code == "system_admin") and project.lead_id not in [user.pk, *acting_for(user)]:
            return Response({"detail": "Only the project's Project Leader can delete it."}, status=status.HTTP_403_FORBIDDEN)
        current = review_status(project)
        if current != "draft":
            return Response({"detail": f"Only a Draft can be deleted; this proposal is {REVIEW_STATUS_LABELS[current]}."},
                            status=status.HTTP_400_BAD_REQUEST)
        paths = list(project.documents.values_list("storage_path", flat=True))
        project.delete()
        if paths:
            transaction.on_commit(lambda: _delete_stored_files(paths))
        return Response(status=status.HTTP_204_NO_CONTENT)


def _delete_stored_files(paths):
    try:
        delete_documents(paths)
    except requests.RequestException:
        logger.exception("Deleting the stored files of a deleted Draft project failed: %s", paths)

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
        code = request.query_params.get("code", "").strip().upper()
        if not code:
            return Response({"code": "Pass the project code as ?code=."}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"code": code, "available": not Project.objects.filter(project_code=code).exists()})


def create_project_lib(project, rows, request):
    """The registration's draft LIB v1: the budget and its line items. Returns (budget, row errors); the caller rolls
    back when there are errors. Shared by ProjectLibView and Manual Entry's registration (client 2026-10-29)."""
    # Every row needs its per-year/per-quarter split once the project has dates (client meeting 2026-10-14)
    context = {"request": request, "require_allocations": allocation_periods(project) is not None}
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
    return budget, errors


class ProjectLibView(APIView):
    """POST {"line_items": [{category, description, fiscal_year?, unit, quantity, unit_cost, amount?, allocations}]}: the registration
    wizard's Budget Requirements step (client meeting 2026-10-01, #11) as draft LIB v1. Gated by projects.register,
    not budget.manage, because CRC Chair/DRD/RIUH register projects but don't encode budgets otherwise.
    All-or-nothing; a project that already has a LIB is refused."""

    permission_classes = [HasRole("projects.register")]

    @idempotent
    def post(self, request, pk):
        project = lock(Project.objects.all(), pk=pk)  # two submits of this step can't both see "no LIB yet"
        rows = request.data.get("line_items")
        if not isinstance(rows, list) or not rows:
            return Response({"line_items": "Send at least one line item."}, status=status.HTTP_400_BAD_REQUEST)
        if project.budgets.exists():
            return Response({"detail": "This project already has a LIB. Edit it under Budget Management."},
                            status=status.HTTP_400_BAD_REQUEST)
        with transaction.atomic():
            budget, errors = create_project_lib(project, rows, request)
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


class WorkPlanTemplateView(APIView):
    """Work Plan-only Excel template for Manual Entry's XI. Work Plan import (client 2026-10-29, Task 10)."""

    permission_classes = [HasRole("projects.register")]

    def get(self, request):
        response = HttpResponse(importer.build_work_plan_template(), content_type=XLSX_TYPE)
        response["Content-Disposition"] = 'attachment; filename="rmis_work_plan_template.xlsx"'
        return response


class LibTemplateView(APIView):
    """GET ?start_date=&target_end_date= (Step 1's dates): Step 4 Budget (LIB)'s own Excel template, one column per
    period of that duration (Task 12, 2026-10-29)."""

    permission_classes = [HasRole("projects.register")]

    def get(self, request):
        start, end = request.query_params.get("start_date"), request.query_params.get("target_end_date")
        periods, errors = importer.lib_periods(start, end)
        if errors:
            return Response({"errors": errors}, status=status.HTTP_400_BAD_REQUEST)
        response = HttpResponse(importer.build_lib_template(start, end, periods), content_type=XLSX_TYPE)
        response["Content-Disposition"] = 'attachment; filename="rmis_lib_template.xlsx"'
        return response


class LibImportView(APIView):
    """POST multipart `file` + start_date + target_end_date: the LIB sheet as {"rows": [...]} for Step 4, checked
    against the project's periods and the LineItem rules. All-or-nothing; saves nothing, and the upload is read in
    the request only (Task 12, 2026-10-29)."""

    permission_classes = [HasRole("projects.register")]
    parser_classes = [MultiPartParser]

    def post(self, request):
        periods, errors = importer.lib_periods(request.data.get("start_date"), request.data.get("target_end_date"))
        if errors:
            return Response({"errors": errors}, status=status.HTTP_400_BAD_REQUEST)
        file_obj = request.FILES.get("file")
        if not file_obj:
            return Response({"errors": [{"sheet": None, "row": None, "field": "file", "message": "Choose the filled LIB .xlsx file."}]},
                            status=status.HTTP_400_BAD_REQUEST)
        rows, errors = importer.read_lib(file_obj, periods)
        if errors:
            return Response({"errors": errors}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"rows": rows})


class ProjectImportView(APIView):
    """POST multipart `file`: registers one project (plus team, studies, 6Ps, beneficiaries, LIB, work plan)
    from a filled template. All-or-nothing: any row error rolls the whole import back and lists every error.
    `?dry_run=1` runs the same import, returns {"preview": ...} for the SF-018 preview and {"draft": ...} for Manual
    Entry to load and edit before registering (client 2026-10-23), and always rolls back."""

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
                draft = importer.registration_draft(project, request)
                transaction.set_rollback(True)
                return Response({"preview": preview, "draft": draft})
        return Response(ProjectSerializer(project).data, status=status.HTTP_201_CREATED)


class WorkPlanImportView(APIView):
    """POST multipart `file`: the workbook's Work Plan sheet as {"rows": [{title, start_date, target_date}]} for
    Manual Entry Step 5 (client 2026-10-23), checked with the Excel import's rules; saves nothing."""

    permission_classes = [HasRole("projects.register")]
    parser_classes = [MultiPartParser]

    def post(self, request):
        file_obj = request.FILES.get("file")
        if not file_obj:
            return Response({"file": "Upload the .xlsx with the Work Plan sheet as `file`."}, status=status.HTTP_400_BAD_REQUEST)
        rows, errors = importer.read_work_plan(file_obj)
        if errors:
            return Response({"errors": errors}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"rows": rows})


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
        if not can_edit_registration(self.request.user, instance.project):
            self.permission_denied(self.request, message="Only the System Admin or the project's Project Leader can edit a registered project.")
        ensure_registration_open(instance.project)
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


class ProposalPdfView(ProjectVisibleMixin, generics.GenericAPIView):
    """GET projects/<id>/proposal-pdf/: the proposal's saved information as a PDF in the Validate & Register Preview's
    layout, current fields only (Task 19, 2026-10-30: View Other Information). Shown inline so it opens in a tab;
    404 outside visible_projects."""

    queryset = Project.objects.all()
    project_lookup = ""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        from reports.forms import proposal_form, render_form_pdf

        project = self.get_object()
        response = HttpResponse(render_form_pdf(proposal_form(project.pk, current=True)), content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="Proposal_{project.project_code}.pdf"'
        return response


class StudyListCreateView(AtomicMutationMixin, ProjectVisibleMixin, generics.ListCreateAPIView):
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


class StudyDetailView(AtomicMutationMixin, ProjectVisibleMixin, generics.RetrieveUpdateAPIView):
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
        ensure_registration_open(instance.project)
        instance.delete()