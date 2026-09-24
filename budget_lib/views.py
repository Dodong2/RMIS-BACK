from rest_framework import generics, permissions, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import BudgetScopedMixin, HasRole
from .models import LineItem, LineItemBudget
from .serializers import CERTIFY_ROLES, LineItemBudgetSerializer, LineItemSerializer, certify_budget

# Lead proponents encode their own LIB (Manual; client clarification Q12), limited to their projects by
# ensure_in_scope. Certification stays with the Budget Officer (CERTIFY_ROLES).
MANAGE_ROLES = ["system_admin", "finance_budget", "procurement_officer_lib", "program_leader", "project_leader"]


class BudgetListCreateView(BudgetScopedMixin, generics.ListCreateAPIView):
    serializer_class = LineItemBudgetSerializer

    def get_queryset(self):
        qs = LineItemBudget.objects.select_related("project").order_by("-created_at")
        project_id = self.request.query_params.get("project")
        if project_id:
            qs = qs.filter(project_id=project_id)
        return qs

    def get_permissions(self):
        if self.request.method == "POST":
            return [HasRole(MANAGE_ROLES)]
        return [permissions.IsAuthenticated()]


class BudgetDetailView(BudgetScopedMixin, generics.RetrieveAPIView):
    queryset = LineItemBudget.objects.select_related("project")
    serializer_class = LineItemBudgetSerializer
    permission_classes = [permissions.IsAuthenticated]


class LineItemListCreateView(BudgetScopedMixin, generics.ListCreateAPIView):
    project_lookup = "budget__project"
    serializer_class = LineItemSerializer

    def get_queryset(self):
        qs = LineItem.objects.all().select_related("budget__project").order_by("category", "id")
        budget_id = self.request.query_params.get("budget")
        project_id = self.request.query_params.get("project")
        is_app_flagged = self.request.query_params.get("is_app_flagged")
        if budget_id:
            qs = qs.filter(budget_id=budget_id)
        if project_id:
            qs = qs.filter(budget__project_id=project_id)
        if is_app_flagged is not None:
            qs = qs.filter(is_app_flagged=is_app_flagged.lower() in ("true", "1", "yes"))
        return qs

    def get_permissions(self):
        if self.request.method == "POST":
            return [HasRole(MANAGE_ROLES)]
        return [permissions.IsAuthenticated()]


class LineItemDetailView(BudgetScopedMixin, generics.RetrieveUpdateDestroyAPIView):
    project_lookup = "budget__project"
    queryset = LineItem.objects.all()
    serializer_class = LineItemSerializer

    def get_permissions(self):
        if self.request.method in ("PUT", "PATCH", "DELETE"):
            return [HasRole(MANAGE_ROLES)]
        return [permissions.IsAuthenticated()]

    def perform_destroy(self, instance):
        if instance.budget.status == "certified":
            raise ValidationError("This budget is certified and can no longer be edited.")
        instance.delete()


class CertifyBudgetView(APIView):
    permission_classes = [HasRole(CERTIFY_ROLES)]

    def post(self, request, pk):
        budget = generics.get_object_or_404(LineItemBudget, pk=pk)
        if budget.status == "certified":
            return Response({"detail": "This budget is already certified."}, status=status.HTTP_400_BAD_REQUEST)
        return Response(LineItemBudgetSerializer(certify_budget(budget, request.user)).data)
