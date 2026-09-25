from django.db import transaction
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import HasRole

from . import services
from .models import BudgetOfficeImport, BudgetOfficeRecord
from .serializers import BudgetOfficeImportSerializer, BudgetOfficeRecordSerializer


class SyncWritesMixin:
    def get_permissions(self):
        if self.request.method in permissions.SAFE_METHODS:
            return [permissions.IsAuthenticated()]
        return [HasRole("budget_sync.manage")]


class ImportListCreateView(SyncWritesMixin, generics.ListCreateAPIView):
    queryset = BudgetOfficeImport.objects.order_by("-uploaded_at")
    serializer_class = BudgetOfficeImportSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        file_obj = serializer.validated_data["file"]
        with transaction.atomic():
            source = BudgetOfficeImport.objects.create(file_name=file_obj.name, uploaded_by=request.user)
            try:
                services.import_workbook(file_obj, source)
            except Exception as exc:  # unreadable/non-workbook file
                transaction.set_rollback(True)
                return Response({"file": f"Could not read workbook: {exc}"}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(source).data, status=status.HTTP_201_CREATED)


class RecordListView(generics.ListAPIView):
    serializer_class = BudgetOfficeRecordSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = BudgetOfficeRecord.objects.order_by("source_id", "id")
        params = self.request.query_params
        if params.get("import"):
            qs = qs.filter(source_id=params["import"])
        if params.get("linked") in ("true", "false"):
            qs = qs.filter(project__isnull=params["linked"] == "false")
        return qs


class RecordDetailView(SyncWritesMixin, generics.RetrieveUpdateAPIView):
    """PATCH {"project": <id or null>} to link/unlink a sheet the title match missed."""

    queryset = BudgetOfficeRecord.objects.all()
    serializer_class = BudgetOfficeRecordSerializer


class ReconciliationView(APIView):
    """?import=<id> (defaults to the latest import)."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        imports = BudgetOfficeImport.objects.order_by("-uploaded_at")
        source = imports.filter(pk=request.query_params["import"]).first() if request.query_params.get("import") else imports.first()
        if source is None:
            return Response({"detail": "No Budget Office import found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(services.reconcile(source))
