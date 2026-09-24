from django.http import HttpResponse
from django.utils import timezone
from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import HasRole
from dashboard import services as dashboard_services

from . import services
from .models import GeneratedReportLog
from .renderers import CONTENT_TYPES, render
from .serializers import GeneratedReportLogSerializer

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


class AppendixEReportView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, project_id):
        data = dashboard_services.appendix_e_export(project_id)
        response, error = build_report_response(
            request, "appendix_e", "Appendix E - Midterm Progress Report", data, filters={"project_id": project_id}
        )
        if error:
            return Response({"detail": error}, status=400)
        return response


class AppendixFReportView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, project_id):
        data = dashboard_services.appendix_f_export(project_id)
        if data is None:
            return Response({"detail": "No terminal report submitted for this project."}, status=404)
        response, error = build_report_response(
            request, "appendix_f", "Appendix F - Terminal Report", data, filters={"project_id": project_id}
        )
        if error:
            return Response({"detail": error}, status=400)
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
    permission_classes = [HasRole(REPORT_LOG_VIEW_ROLES)]


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
