import datetime

from django.http import HttpResponse
from django.utils import timezone
from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User
from accounts.permissions import HasRole, visible_projects
from dashboard import services as dashboard_services

from . import forms, services
from .models import GeneratedReportLog
from .renderers import CONTENT_TYPES, render
from .serializers import GeneratedReportLogSerializer

# Seed source for the permission table (accounts/permission_seed.py); gates use permission codes.
REPORT_LOG_VIEW_ROLES = ["system_admin", "riuh", "drd", "vprei"]


def build_report_response(request, report_type, title, data, filters=None):
    # NOT "format" — DRF reserves that query param name for its own content
    # negotiation and raises Http404 before this view code even runs if an
    # unrecognized value (e.g. "pdf") is passed to it.
    fmt = request.query_params.get("file_format", "csv")
    try:
        content = render(fmt, title, data)
    except ValueError as exc:
        return None, str(exc)

    GeneratedReportLog.objects.create(
        report_type=report_type, format=fmt, filters=filters or {}, generated_by=request.user
    )
    filename = f"{report_type}_{timezone.now():%Y%m%d%H%M%S}.{fmt}"
    response = HttpResponse(content, content_type=CONTENT_TYPES[fmt])
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response, None


class FormReportView(APIView):
    """Appendix E/F as the official LSPU form (reports/forms.py), the same layout in every file format. Readable
    only for projects the user may see (visible_projects, client meeting 2026-10-01)."""

    permission_classes = [permissions.IsAuthenticated]
    report_type = build_form = missing = None

    def get(self, request, project_id):
        visible = visible_projects(request.user)
        if visible is not None and not visible.filter(pk=project_id).exists():
            return Response({"detail": "Not found."}, status=404)
        form = self.build_form(project_id)
        if form is None:
            return Response({"detail": self.missing}, status=404)
        fmt = request.query_params.get("file_format", "csv")
        if fmt not in forms.FORM_RENDERERS:
            return Response({"detail": f"Unsupported format: {fmt}. Choose one of {list(forms.FORM_RENDERERS)}."}, status=400)
        content = forms.FORM_RENDERERS[fmt](form)
        GeneratedReportLog.objects.create(
            report_type=self.report_type, format=fmt, filters={"project_id": project_id}, generated_by=request.user
        )
        response = HttpResponse(content, content_type=CONTENT_TYPES[fmt])
        response["Content-Disposition"] = f'attachment; filename="{self.report_type}_{timezone.now():%Y%m%d%H%M%S}.{fmt}"'
        return response


class AppendixEReportView(FormReportView):
    """LSPU-RDO-SF-017, one per submitted project year."""

    report_type = "appendix_e"
    build_form = staticmethod(forms.appendix_e_form)
    missing = "No midterm report submitted for this project."


class AppendixFReportView(FormReportView):
    """SF-16 terminal narrative report outline."""

    report_type = "appendix_f"
    build_form = staticmethod(forms.appendix_f_form)
    missing = "No terminal report submitted for this project."


class ProposalFormReportView(FormReportView):
    """LSPU-RDO-SF-018, laid out like the registration wizard's preview (client request 2026-10-09)."""

    report_type = "proposal_form"
    build_form = staticmethod(forms.proposal_form)
    missing = "Project not found."


class AccomplishmentReportView(APIView):
    """GET reports/accomplishment/?user=&month=YYYY-MM&file_format=: a project staff's Monthly Accomplishment Report,
    pulled from their tasks (client follow-up 2026-10-02). Staff get only their own (user defaults to them);
    leaders only for tasks on projects they can see."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user_id = request.query_params.get("user") or request.user.pk
        staff = User.objects.filter(pk=user_id).select_related("role").first() if str(user_id).isdigit() else None
        is_staff = request.user.role and request.user.role.code == "project_staff"
        if staff is None or (is_staff and staff.pk != request.user.pk):
            return Response({"detail": "Not found."}, status=404)
        try:
            month = datetime.datetime.strptime(request.query_params.get("month") or f"{timezone.localdate():%Y-%m}", "%Y-%m").date()
        except ValueError:
            return Response({"detail": "month must be YYYY-MM."}, status=400)
        fmt = request.query_params.get("file_format", "pdf")
        if fmt not in forms.FORM_RENDERERS:
            return Response({"detail": f"Unsupported format: {fmt}. Choose one of {list(forms.FORM_RENDERERS)}."}, status=400)
        projects = None if is_staff else visible_projects(request.user)
        form = forms.accomplishment_form(staff, month, projects)
        GeneratedReportLog.objects.create(
            report_type="accomplishment", format=fmt, filters={"user": staff.pk, "month": f"{month:%Y-%m}"},
            generated_by=request.user,
        )
        response = HttpResponse(forms.FORM_RENDERERS[fmt](form), content_type=CONTENT_TYPES[fmt])
        response["Content-Disposition"] = f'attachment; filename="accomplishment_{month:%Y%m}_{staff.pk}.{fmt}"'
        return response


class AppendixGReportView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        campus = request.query_params.get("campus")
        year = request.query_params.get("year")
        data = dashboard_services.appendix_g_export(campus=campus, year=int(year) if year else None)
        response, error = build_report_response(
            request, "appendix_g", "Appendix G - R&D Accomplishment Report", data, filters={"campus": campus, "year": year}
        )
        if error:
            return Response({"detail": error}, status=400)
        return response


class ProjectListReportView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        filters = {
            "campus": request.query_params.get("campus"),
            "funding_type": request.query_params.get("funding_type"),
            "status": request.query_params.get("status"),
            "rei_thrust": request.query_params.get("rei_thrust"),
            "year": request.query_params.get("year"),
        }
        data = services.project_list_report(
            campus=filters["campus"],
            funding_type=filters["funding_type"],
            status=filters["status"],
            rei_thrust=filters["rei_thrust"],
            year=int(filters["year"]) if filters["year"] else None,
        )
        response, error = build_report_response(request, "project_list", "Filtered Project List", data, filters=filters)
        if error:
            return Response({"detail": error}, status=400)
        return response


class GeneratedReportLogListView(generics.ListAPIView):
    queryset = GeneratedReportLog.objects.all()
    serializer_class = GeneratedReportLogSerializer
    permission_classes = [HasRole("reports.view_logs")]


MODULE_REPORTS = {
    "financial": ("Financial / Procurement Report", services.financial_report, True),
    "compliance": ("Compliance Report", services.compliance_report, False),
    "personnel": ("Personnel and Task Report", services.personnel_report, False),
    "outputs": ("Research Outputs (6Ps) Report", services.outputs_report, False),
}


class ModuleReportView(APIView):
    """GET reports/<financial|compliance|personnel|outputs>/?file_format=&campus=&funding_type="""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, report_type):
        if report_type not in MODULE_REPORTS:
            return Response({"detail": "Unknown report type."}, status=404)
        title, builder, needs_user = MODULE_REPORTS[report_type]
        filters = {"campus": request.query_params.get("campus"), "funding_type": request.query_params.get("funding_type")}
        data = builder(request.user, **filters) if needs_user else builder(**filters)
        response, error = build_report_response(request, report_type, title, data, filters=filters)
        if error:
            return Response({"detail": error}, status=400)
        return response
