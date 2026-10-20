from django.db import transaction
from rest_framework import generics, permissions, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from accounts.permissions import BudgetScopedMixin, HasRole, acting_for, role_can
from config.concurrency import lock
from .models import LibItem, LineItem, LineItemBudget
from .serializers import LibItemSerializer, LineItemBudgetSerializer, LineItemSerializer, review_budget, total_cost_problem

# Lead proponents encode their own LIB (Manual; client clarification Q12), limited to their projects by
# ensure_in_scope. Certification stays with the Budget Officer (budget.certify).
# Client 2026-10-11: finance_budget and system_admin only certify/approve, they don't add or edit line items.
# Seed source for the permission table (accounts/permission_seed.py); gates use permission codes.
MANAGE_ROLES = ["procurement_officer_lib", "program_leader", "project_leader"]


class BudgetListCreateView(BudgetScopedMixin, generics.ListCreateAPIView):
    serializer_class = LineItemBudgetSerializer

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    def get_queryset(self):
        qs = LineItemBudget.objects.select_related("project").order_by("-created_at")
        project_id = self.request.query_params.get("project")
        if project_id:
            qs = qs.filter(project_id=project_id)
        return qs

    def get_permissions(self):
        if self.request.method == "POST":
            return [HasRole("budget.manage")]
        return [permissions.IsAuthenticated()]


class BudgetDetailView(BudgetScopedMixin, generics.RetrieveAPIView):
    queryset = LineItemBudget.objects.select_related("project")
    serializer_class = LineItemBudgetSerializer
    permission_classes = [permissions.IsAuthenticated]


class LineItemListCreateView(BudgetScopedMixin, generics.ListCreateAPIView):
    project_lookup = "budget__project"
    serializer_class = LineItemSerializer

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

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
            return [HasRole("budget.manage")]
        return [permissions.IsAuthenticated()]


class LineItemDetailView(BudgetScopedMixin, generics.RetrieveUpdateDestroyAPIView):
    project_lookup = "budget__project"
    queryset = LineItem.objects.all()
    serializer_class = LineItemSerializer

    def get_permissions(self):
        if self.request.method in ("PUT", "PATCH", "DELETE"):
            return [HasRole("budget.manage")]
        return [permissions.IsAuthenticated()]

    @transaction.atomic
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    @transaction.atomic
    def destroy(self, request, *args, **kwargs):
        return super().destroy(request, *args, **kwargs)

    def perform_destroy(self, instance):
        budget = lock(LineItemBudget.objects.all(), pk=instance.budget_id)
        if budget.status not in LineItemBudget.EDITABLE_STATUSES:
            raise ValidationError(f"This LIB is {budget.get_status_display().lower()} and can no longer be edited.")
        instance.delete()


class BudgetReviewView(BudgetScopedMixin, generics.GenericAPIView):
    """POST {"remarks"?}: one step of the LIB endorsement chain (client 2026-10-18).
    endorse: CRC Chair (budget.endorse), draft -> endorsed. certify: Budget Officer (budget.certify), endorsed ->
    certified. return: CRC Chair on a draft or the Budget Officer on an endorsed LIB, remarks required -> returned.
    resubmit: the project's own leader (or acting replacement), returned -> draft. Endorse and resubmit need the
    Grand Total to equal the Total Project/Study Cost. Out-of-scope LIBs 404."""

    queryset = LineItemBudget.objects.select_related("project")
    permission_classes = [permissions.IsAuthenticated]
    step = None

    @transaction.atomic
    def post(self, request, pk):
        budget = lock(LineItemBudget.objects.select_related("project"), pk=self.get_object().pk)
        remarks = (request.data.get("remarks") or "").strip()
        user = request.user

        if self.step == "returned":
            if budget.status not in ("draft", "endorsed"):
                return self.refuse(f"A {budget.get_status_display().lower()} LIB can't be returned.")
            needed = "budget.endorse" if budget.status == "draft" else "budget.certify"
            if not role_can(user, needed):
                who = "CRC Chair" if budget.status == "draft" else "Budget Officer"
                return self.refuse(f"Only the {who} can return this LIB now.", status.HTTP_403_FORBIDDEN)
            if not remarks:
                return Response({"remarks": "Say what needs to be revised."}, status=status.HTTP_400_BAD_REQUEST)
        else:
            if self.step == "resubmitted":
                allowed = budget.project.lead_id in [user.pk, *acting_for(user)]
            else:
                allowed = role_can(user, "budget.endorse" if self.step == "endorsed" else "budget.certify")
            if not allowed:
                return self.refuse("You may not take this step on this LIB.", status.HTTP_403_FORBIDDEN)
            expected = {"endorsed": "draft", "certified": "endorsed", "resubmitted": "returned"}[self.step]
            if budget.status != expected:
                return self.refuse(
                    f"Only a LIB that is {dict(LineItemBudget.STATUS_CHOICES)[expected].lower()} can be "
                    f"{self.step} (this one is {budget.get_status_display().lower()})."
                )
            if self.step in ("endorsed", "resubmitted"):
                problem = total_cost_problem(budget)
                if problem:
                    return self.refuse(problem)

        return Response(LineItemBudgetSerializer(review_budget(budget, user, self.step, remarks)).data)

    def refuse(self, detail, code=status.HTTP_400_BAD_REQUEST):
        return Response({"detail": detail}, status=code)


class LibItemListCreateView(generics.ListCreateAPIView):
    """Admin > LIB Items (client 2026-10-20). Everyone signed in reads the list (the LIB forms' Item dropdowns); only
    the System Admin edits it."""

    queryset = LibItem.objects.all()
    serializer_class = LibItemSerializer

    def get_permissions(self):
        if self.request.method == "POST":
            return [HasRole("accounts.manage_users")]
        return [permissions.IsAuthenticated()]


class LibItemDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = LibItem.objects.all()
    serializer_class = LibItemSerializer

    def get_permissions(self):
        if self.request.method in ("PUT", "PATCH", "DELETE"):
            return [HasRole("accounts.manage_users")]
        return [permissions.IsAuthenticated()]

    def destroy(self, request, *args, **kwargs):
        item = self.get_object()
        if LineItem.objects.filter(category=item.category, description__iexact=item.name).exists():
            return Response({"detail": "LIBs use this item, so it can't be deleted. Deactivate it instead."}, status=status.HTTP_400_BAD_REQUEST)
        return super().destroy(request, *args, **kwargs)
