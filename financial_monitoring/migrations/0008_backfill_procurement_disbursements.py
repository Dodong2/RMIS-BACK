from django.db import migrations
from django.utils import timezone


def backfill(apps, schema_editor):
    """Client 2026-10-12: requests completed before auto-posting existed get their disbursement too."""
    ProcurementRequest = apps.get_model("financial_monitoring", "ProcurementRequest")
    Disbursement = apps.get_model("financial_monitoring", "Disbursement")
    for procurement in ProcurementRequest.objects.filter(status="completed", disbursement__isnull=True):
        Disbursement.objects.create(
            line_item_id=procurement.line_item_id,
            amount=procurement.amount,
            reference_number=f"PR-{procurement.pk:04d}",
            description=procurement.description[:300],
            disbursed_on=timezone.localdate(procurement.completed_at or procurement.requested_at),
            recorded_by_id=procurement.updated_by_id or procurement.requested_by_id,
            procurement_request_id=procurement.pk,
        )


def unbackfill(apps, schema_editor):
    Disbursement = apps.get_model("financial_monitoring", "Disbursement")
    Disbursement.objects.filter(procurement_request__isnull=False).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('financial_monitoring', '0007_disbursement_procurement_request'),
    ]

    operations = [
        migrations.RunPython(backfill, unbackfill),
    ]
