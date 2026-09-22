from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import HasRole
from budget_lib.models import LineItemBudget
from .models import BudgetRealignment, Disbursement
from .serializers import (
    DISBURSEMENT_ROLES,
    REALIGNMENT_BOR_REVIEW_ROLES,
    REALIGNMENT_MAJOR_REVIEW_ROLES,
    REALIGNMENT_REQUEST_ROLES,
    BudgetRealignmentSerializer,
    DisbursementSerializer,
    RealignmentReviewSerializer,
    line_item_balance,
    review_realignment,
)


class DisbursementListCreateView(generics.ListCreateAPIView):
    serializer_class = DisbursementSerializer

    def get_queryset(self):
        qs = Disbursement.objects.select_related("line_item").order_by("-disbursed_on")
        line_item_id = self.request.query_params.get("line_item")
        budget_id = self.request.query_params.get("budget")
        if line_item_id:
            qs = qs.filter(line_item_id=line_item_id)
        if budget_id:
            qs = qs.filter(line_item__budget_id=budget_id)
        return qs

    def get_permissions(self):
        if self.request.method == "POST":
            return [HasRole(DISBURSEMENT_ROLES)]
        return [permissions.IsAuthenticated()]

    def perform_create(self, serializer):
        serializer.save(recorded_by=self.request.user)


class DisbursementDetailView(generics.RetrieveAPIView):
    queryset = Disbursement.objects.select_related("line_item")
    serializer_class = DisbursementSerializer
    permission_classes = [permissions.IsAuthenticated]


class RealignmentListCreateView(generics.ListCreateAPIView):
    serializer_class = BudgetRealignmentSerializer

    def get_queryset(self):
        qs = BudgetRealignment.objects.select_related("from_line_item", "to_line_item").order_by("-created_at")
        budget_id = self.request.query_params.get("budget")
        if budget_id:
            qs = qs.filter(from_line_item__budget_id=budget_id)
        return qs

    def get_permissions(self):
        if self.request.method == "POST":
            return [HasRole(REALIGNMENT_REQUEST_ROLES)]
        return [permissions.IsAuthenticated()]

    def perform_create(self, serializer):
        serializer.save(requested_by=self.request.user)


class RealignmentDetailView(generics.RetrieveAPIView):
    queryset = BudgetRealignment.objects.select_related("from_line_item", "to_line_item")
    serializer_class = BudgetRealignmentSerializer
    permission_classes = [permissions.IsAuthenticated]


class RealignmentReviewView(APIView):
    """
    Approve/reject a major or BOR-tier realignment. Major (33-100%) may be
    reviewed by University Administration; BOR-tier (>100%/new item) is
    system_admin only, per client confirmation (no Board of Regents role exists).
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        realignment = generics.get_object_or_404(BudgetRealignment, pk=pk)
        if realignment.status not in ("pending_approval", "pending_bor"):
            return Response({"detail": "This realignment is not awaiting review."}, status=status.HTTP_400_BAD_REQUEST)

        allowed_roles = REALIGNMENT_BOR_REVIEW_ROLES if realignment.tier == "bor" else REALIGNMENT_MAJOR_REVIEW_ROLES
        user_role = request.user.role.code if request.user.role else None
        if user_role not in allowed_roles:
            return Response({"detail": "You do not have permission to review this realignment."}, status=status.HTTP_403_FORBIDDEN)

        serializer = RealignmentReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        realignment = review_realignment(
            realignment, request.user,
            serializer.validated_data["decision"],
            serializer.validated_data.get("bor_resolution_number", ""),
        )
        return Response(BudgetRealignmentSerializer(realignment).data)


class BudgetSummaryView(APIView):
    """Approved / Adjusted / Actual figures per line item for a certified budget."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        budget = generics.get_object_or_404(LineItemBudget.objects.select_related("project"), pk=pk)
        items = []
        for item in budget.line_items.all().order_by("category", "id"):
            balance = line_item_balance(item)
            items.append({
                "line_item": item.pk, "category": item.category, "description": item.description, **balance,
            })
        totals = {
            key: sum(row[key] for row in items) for key in ("approved", "adjusted", "actual", "available")
        }
        return Response({"budget": budget.pk, "project": budget.project_id, "line_items": items, "totals": totals})
