from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.http import HttpResponse
from rest_framework import generics, permissions, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from accounts.permissions import BudgetScopedMixin, HasRole, acting_for, role_can
from config.concurrency import lock, lock_line_items
from realtime.notify import notify, project_audience
from research_projects.workflow import missing_approval_documents, missing_registration_rows
from .models import LibItem, LineItem, LineItemBudget, LineItemEdit, allocation_periods
from .notifications import lib_updated, proposal_submitted, ready_for_budget_review
from .serializers import (LibItemSerializer, LineItemBudgetSerializer, LineItemSerializer, catalog_item_name, clean_allocations,
                          line_total, review_budget, total_cost_problem)

# Lead proponents encode their own LIB (Manual; client clarification Q12), limited to their projects by
# ensure_in_scope. Certification stays with the Budget Officer (budget.certify).
# Client 2026-10-11: finance_budget and system_admin only certify/approve, they don't add or edit line items.
# Client Q9 2026-10-21 (accounts 0023): the Procurement Officer and Program Leaders don't encode LIBs either.
# Seed source for the permission table (accounts/permission_seed.py); gates use permission codes.
MANAGE_ROLES = ["project_leader"]
# Client Q10 2026-10-21: the Budget Officer sees a LIB only from Ready for Certification on.
BUDGET_OFFICER_STATUSES = ("endorsed", "certifying", "certified")


class ReadyForBudgetOfficerMixin:
    """Hides LIBs (or their line items) that aren't Ready for Certification yet from the Budget Officer, in lists and
    detail lookups alike (list() and get_object() both go through filter_queryset). Other roles are unaffected."""

    status_lookup = "status"

    def filter_queryset(self, queryset):
        qs = super().filter_queryset(queryset)
        user = self.request.user
        if user.role and user.role.code == "finance_budget":
            qs = qs.filter(**{f"{self.status_lookup}__in": BUDGET_OFFICER_STATUSES})
        return qs


def lib_signal(budget):
    """Real-time "this LIB changed" (realtime/notify.py), sent after commit to the roles holding a budget.* permission
    (CRC Chair, Budget Officer, system_admin) and the project lead, so their Budget page and bell refetch. No status in
    the payload: the Budget Officer must not learn about a LIB before Ready for Certification (client Q10)."""
    notify(project_audience(budget.project, "budget."), "budget.lib.updated", id=budget.id, project=budget.project_id)


class BudgetListCreateView(ReadyForBudgetOfficerMixin, BudgetScopedMixin, generics.ListCreateAPIView):
    serializer_class = LineItemBudgetSerializer

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        super().perform_create(serializer)
        lib_signal(serializer.instance)

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


class BudgetDetailView(ReadyForBudgetOfficerMixin, BudgetScopedMixin, generics.RetrieveAPIView):
    queryset = LineItemBudget.objects.select_related("project")
    serializer_class = LineItemBudgetSerializer
    permission_classes = [permissions.IsAuthenticated]


class BudgetExportView(ReadyForBudgetOfficerMixin, BudgetScopedMixin, generics.GenericAPIView):
    """GET budgets/<id>/export/: the LIB as saved, in Step 4's Download LIB Template layout (Task 20, 2026-10-30).
    The uploaded workbook isn't kept, so manual entry, the LIB import and Upload via Excel all download the same way.
    Same scope as the LIB itself (the Budget Officer from Ready for Certification on)."""

    queryset = LineItemBudget.objects.select_related("project")
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        from research_projects.importer import build_lib_template

        budget = self.get_object()
        project = budget.project
        content = build_lib_template(project.start_date, project.target_end_date, allocation_periods(project) or [],
                                     budget.line_items.order_by("id"))
        response = HttpResponse(content, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        response["Content-Disposition"] = f'attachment; filename="LIB_{project.project_code}_v{budget.version_number}.xlsx"'
        return response


class LineItemListCreateView(ReadyForBudgetOfficerMixin, BudgetScopedMixin, generics.ListCreateAPIView):
    project_lookup = "budget__project"
    status_lookup = "budget__status"
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


class LineItemDetailView(ReadyForBudgetOfficerMixin, BudgetScopedMixin, generics.RetrieveUpdateDestroyAPIView):
    project_lookup = "budget__project"
    status_lookup = "budget__status"
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


# Client 2026-10-21: every step of the LIB review workflow, as step -> (from statuses, who, to status, history
# action). "leader" = the project's own leader (or acting replacement); the others are permission codes. Anything not
# here is refused, so no stage can be skipped (Q6: certification starts with a button, not by opening the LIB).
# Task 19 (2026-10-30, Q1): the CRC/CRD's one forward step, "Mark for checking", sends it straight to the Budget
# Officer; crc_processing/for_checking are only accepted for LIBs already there.
TRANSITIONS = {
    "submit": (("draft",), "leader", "submitted", "submitted"),
    "for-checking": (LineItemBudget.CRC_STATUSES, "budget.endorse", "endorsed", "ready"),
    "start-certification": (("endorsed",), "budget.certify", "certifying", "certification_started"),
    "certify": (("certifying",), "budget.certify", "certified", "certified"),
    "resubmit": (("returned",), "leader", "submitted", "resubmitted"),
}
# Put on Hold (Q1, Q2): the level holding the LIB sends it back to the Project Leader with remarks.
HOLDS = {
    **{status: ("budget.endorse", "held_crc", "CRC Chair") for status in LineItemBudget.CRC_STATUSES},
    **{status: ("budget.certify", "held_budget", "Budget Officer") for status in LineItemBudget.BUDGET_STATUSES},
}


class BudgetReviewView(ReadyForBudgetOfficerMixin, BudgetScopedMixin, generics.GenericAPIView):
    """POST budgets/<id>/<step>/ {"remarks"?}: one step of the LIB review workflow (TRANSITIONS, or "hold", which needs
    remarks). Submit and resubmit need the Grand Total to equal the Total Project/Study Cost. Out-of-scope LIBs 404."""

    queryset = LineItemBudget.objects.select_related("project")
    permission_classes = [permissions.IsAuthenticated]
    step = None

    @transaction.atomic
    def post(self, request, pk):
        budget = lock(LineItemBudget.objects.select_related("project"), pk=self.get_object().pk)
        remarks = (request.data.get("remarks") or "").strip()
        user = request.user

        if self.step == "hold":
            if budget.status not in HOLDS:
                return self.refuse(f"A LIB that is {budget.get_status_display().lower()} can't be put on hold.")
            permission, action, who = HOLDS[budget.status]
            if not role_can(user, permission):
                return self.refuse(f"Only the {who} can put this LIB on hold now.", status.HTTP_403_FORBIDDEN)
            if not remarks:
                return Response({"remarks": "Say what the Project Leader needs to correct."}, status=status.HTTP_400_BAD_REQUEST)
            to_status = "returned"
        else:
            from_statuses, who, to_status, action = TRANSITIONS[self.step]
            if who == "leader":
                allowed = budget.project.lead_id in [user.pk, *acting_for(user)]
            else:
                allowed = role_can(user, who)
            if not allowed:
                return self.refuse("You may not take this step on this LIB.", status.HTTP_403_FORBIDDEN)
            if budget.status not in from_statuses:
                expected = " or ".join(dict(LineItemBudget.STATUS_CHOICES)[s].lower() for s in from_statuses)
                return self.refuse(f"This step needs a LIB that is {expected} (this one is {budget.get_status_display().lower()}).")
            if self.step in ("submit", "resubmit"):
                problem = total_cost_problem(budget)
                if problem:
                    return self.refuse(problem)
                # Submitting the LIB submits the project (client 2026-10-24, D1): Step 7's attachments must be there
                missing = missing_approval_documents(budget.project)
                if missing:
                    return self.refuse(f"Attach the {', '.join(missing)} under Edit Registration before submitting the project.")
                missing = missing_registration_rows(budget.project)
                if missing:
                    return self.refuse(f"Add {', '.join(missing)} under Edit Registration before submitting the project.")

        budget = review_budget(budget, user, to_status, action, remarks)
        lib_signal(budget)
        if self.step in ("submit", "resubmit"):
            # Task 15 (2026-10-30): the campus CRC/CRD get an e-mail once the submission is saved
            transaction.on_commit(lambda: proposal_submitted(budget, resubmitted=self.step == "resubmit"))
        elif self.step == "for-checking":
            # Task 19 (2026-10-30): the campus Finance/Accounting/Budget get an e-mail once the forward is saved
            transaction.on_commit(lambda: ready_for_budget_review(budget, user))
        return Response(LineItemBudgetSerializer(budget).data)

    def refuse(self, detail, code=status.HTTP_400_BAD_REQUEST):
        return Response({"detail": detail}, status=code)


# Task 20 (2026-10-30): what Finance/Accounting/Budget may change on an existing line item (Carl's Q3: not the class)
FINANCE_EDIT_FIELDS = ("description", "specification", "unit", "quantity", "unit_cost", "allocations")


def _text(value):
    return "" if value is None else str(value)


class FinanceEditView(ReadyForBudgetOfficerMixin, BudgetScopedMixin, generics.GenericAPIView):
    """POST budgets/<id>/finance-edit/ {"items": [{"id", "reason", <FINANCE_EDIT_FIELDS>...}]}: Update This LIB
    (Task 20, 2026-10-30). The Budget Officer changes existing line items of a LIB forwarded to them and not yet
    certified; no item can be added, removed or moved to another class. Each changed item needs a reason and gets an
    append-only LineItemEdit; the Grand Total must still equal the Total Project/Study Cost. Unchanged items are
    skipped; nothing changed is a 400 and sends nothing. After commit the Project Leader and the campus CRC/CRD get an
    e-mail."""

    queryset = LineItemBudget.objects.select_related("project")
    permission_classes = [permissions.IsAuthenticated]

    @transaction.atomic
    def post(self, request, pk):
        if not role_can(request.user, "budget.certify"):
            return self.refuse("Only Finance/Accounting/Budget can update this LIB.", status.HTTP_403_FORBIDDEN)
        budget = lock(LineItemBudget.objects.select_related("project"), pk=self.get_object().pk)
        if budget.status not in LineItemBudget.BUDGET_STATUSES:
            return self.refuse(f"A LIB that is {budget.get_status_display().lower()} can't be updated.")
        rows = request.data.get("items")
        if not isinstance(rows, list) or not rows or not all(isinstance(r, dict) for r in rows):
            return self.refuse("Send the line items to update.")
        ids = [r.get("id") for r in rows]
        items = {item.pk: item for item in lock_line_items(*LineItem.objects.filter(budget=budget, pk__in=[i for i in ids if isinstance(i, int)]))}
        if len(set(ids)) != len(ids) or set(ids) != set(items):
            return self.refuse("Only this LIB's existing line items can be updated; items can't be added or removed here.")
        periods = allocation_periods(budget.project)
        edits = []
        for row in rows:
            item = items[row["id"]]
            extra = set(row) - {"id", "reason", *FINANCE_EDIT_FIELDS}
            if extra:
                return self.refuse(f"{item.description}: {', '.join(sorted(extra))} can't be changed here.")
            try:
                changes = self.apply(item, row, periods)
            except ValidationError as exc:
                detail = exc.detail
                while isinstance(detail, (dict, list)):
                    detail = next(iter(detail.values())) if isinstance(detail, dict) else detail[0]
                return self.refuse(f"{item.description}: {detail}")
            if not changes:
                continue
            reason = str(row.get("reason") or "").strip()
            if not reason:
                return self.refuse(f"{item.description}: give the reason for the change.")
            item.save()
            edits.append(LineItemEdit(line_item=item, budget=budget, changes=changes, reason=reason, edited_by=request.user))
        if not edits:
            return self.refuse("Nothing was changed.")
        problem = total_cost_problem(budget)
        if problem:
            return self.refuse(problem)
        edits = LineItemEdit.objects.bulk_create(edits)
        lib_signal(budget)
        transaction.on_commit(lambda: lib_updated(budget, request.user, edits))
        return Response(LineItemBudgetSerializer(budget).data)

    @staticmethod
    def apply(item, row, periods):
        """Set the row's new values on the item (not saved) and return {field: [old, new]} of what really changed."""
        before = {f: _text(getattr(item, f)) for f in ("description", "specification", "unit", "quantity", "unit_cost", "amount")}
        before_allocations = item.allocations or []
        if "description" in row and str(row["description"] or "").strip().lower() != item.description.lower():
            item.description = catalog_item_name(item.category, row["description"])
        if "specification" in row:
            item.specification = str(row["specification"] or "").strip()
            if len(item.specification) > 300:
                raise ValidationError({"specification": "Keep the specification to 300 characters."})
        if "unit" in row:
            if row["unit"] not in dict(LineItem.UNIT_CHOICES):
                raise ValidationError({"unit": "Pick a unit from the list."})
            item.unit = row["unit"]
        for field, label in (("quantity", "Qty"), ("unit_cost", "Unit Cost")):
            if field in row:
                try:
                    value = Decimal(str(row[field]).replace(",", ""))
                except InvalidOperation:
                    raise ValidationError({field: f"{label} is not a number."})
                if value < 0:
                    raise ValidationError({field: f"{label} can't be negative."})
                setattr(item, field, value.quantize(Decimal("0.01")))
        if item.quantity is None or item.unit_cost is None:
            raise ValidationError({"quantity": "Qty and Unit Cost are both needed."})
        item.amount = line_total(item.quantity, item.unit_cost)
        if item.amount <= 0:
            raise ValidationError({"amount": "Qty x Unit Cost must be more than 0."})
        item.allocations = clean_allocations(row.get("allocations", before_allocations), periods, item.amount)
        after = {f: _text(getattr(item, f)) for f in before}
        changes = {f: [before[f], after[f]] for f in before if _comparable(before[f]) != _comparable(after[f])}
        old_split = {a["period"]: Decimal(str(a["amount"])) for a in before_allocations}
        new_split = {a["period"]: Decimal(str(a["amount"])) for a in item.allocations}
        if any(old_split.get(p, Decimal(0)) != new_split.get(p, Decimal(0)) for p in periods or []):
            changes["allocations"] = [before_allocations, item.allocations]
        return changes

    def refuse(self, detail, code=status.HTTP_400_BAD_REQUEST):
        transaction.set_rollback(True)  # items saved before a later row failed are undone: all or nothing
        return Response({"detail": detail}, status=code)


def _comparable(value):
    """'20' and '20.00' are the same Qty; text compares as text."""
    try:
        return Decimal(value)
    except (InvalidOperation, TypeError):
        return value


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
