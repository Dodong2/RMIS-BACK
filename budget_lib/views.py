from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import HasRole
from .models import LineItem, LineItemBudget
from .serializers import CERTIFY_ROLES, LineItemBudgetSerializer, LineItemSerializer, certify_budget

MANAGE_ROLES = ["system_admin", "finance_budget"]


class BudgetListCreateView(generics.ListCreateAPIView):
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


class BudgetDetailView(generics.RetrieveAPIView):
    queryset = LineItemBudget.objects.select_related("project")
    serializer_class = LineItemBudgetSerializer
    permission_classes = [permissions.IsAuthenticated]


class LineItemListCreateView(generics.ListCreateAPIView):
    serializer_class = LineItemSerializer

    def get_queryset(self):
        qs = LineItem.objects.all().order_by("category", "id")
        budget_id = self.request.query_params.get("budget")
        if budget_id:
            qs = qs.filter(budget_id=budget_id)
        return qs

    def get_permissions(self):
        if self.request.method == "POST":
            return [HasRole(MANAGE_ROLES)]
        return [permissions.IsAuthenticated()]


class LineItemDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = LineItem.objects.all()
    serializer_class = LineItemSerializer

    def get_permissions(self):
        if self.request.method in ("PUT", "PATCH", "DELETE"):
            return [HasRole(MANAGE_ROLES)]
        return [permissions.IsAuthenticated()]


class CertifyBudgetView(APIView):
    permission_classes = [HasRole(CERTIFY_ROLES)]

    def post(self, request, pk):
        budget = generics.get_object_or_404(LineItemBudget, pk=pk)
        if budget.status == "certified":
            return Response({"detail": "This budget is already certified."}, status=status.HTTP_400_BAD_REQUEST)
        return Response(LineItemBudgetSerializer(certify_budget(budget, request.user)).data)
