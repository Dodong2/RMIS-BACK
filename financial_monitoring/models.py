from django.conf import settings
from django.db import models

from budget_lib.models import LineItem

APPLIED_STATUSES = ("implemented", "approved", "bor_approved")


class Disbursement(models.Model):
    """An actual expenditure recorded against a line item (the 'Actual' figure)."""

    line_item = models.ForeignKey(LineItem, on_delete=models.PROTECT, related_name="disbursements")
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    reference_number = models.CharField(max_length=100, blank=True, help_text="OR/voucher number")
    description = models.CharField(max_length=300, blank=True)
    disbursed_on = models.DateField()
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="disbursements_recorded"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.line_item} - {self.amount} ({self.disbursed_on})"


class BudgetRealignment(models.Model):
    """
    Transfer of funds from one line item to another (or into a brand-new item),
    tiered per the R&D Manual: <=33% of the source item is self-implementable,
    33-100% needs University Administration approval, >100% or a new expense
    item needs Board of Regents approval (tracked here as a reference only).
    """

    TIER_CHOICES = (
        ("minor", "Minor (<=33% of source item)"),
        ("major", "Major (33-100% of source item)"),
        ("bor", "Requires Board of Regents Approval"),
    )
    STATUS_CHOICES = (
        ("implemented", "Implemented"),
        ("pending_approval", "Pending University Administration Approval"),
        ("approved", "Approved"),
        ("pending_bor", "Pending Board of Regents Approval"),
        ("bor_approved", "Board of Regents Approved"),
        ("rejected", "Rejected"),
    )

    from_line_item = models.ForeignKey(LineItem, on_delete=models.PROTECT, related_name="realignments_from")
    to_line_item = models.ForeignKey(
        LineItem, on_delete=models.PROTECT, null=True, blank=True, related_name="realignments_to"
    )
    # Set only when realigning into a brand-new expense item (always the BOR tier).
    new_item_category = models.CharField(max_length=10, choices=LineItem.CATEGORY_CHOICES, blank=True)
    new_item_description = models.CharField(max_length=300, blank=True)

    amount = models.DecimalField(max_digits=14, decimal_places=2)
    tier = models.CharField(max_length=10, choices=TIER_CHOICES, editable=False)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="implemented")
    justification = models.TextField()

    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="realignments_requested"
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="realignments_reviewed"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    bor_resolution_number = models.CharField(max_length=100, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def budget(self):
        return self.from_line_item.budget

    def __str__(self):
        return f"Realignment #{self.pk} ({self.tier})"
