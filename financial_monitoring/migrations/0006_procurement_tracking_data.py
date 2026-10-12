from django.db import migrations

OLD_TO_NEW = {"processing": "under_review", "released": "completed"}


def forwards(apps, schema_editor):
    ProcurementRequest = apps.get_model("financial_monitoring", "ProcurementRequest")
    for old, new in OLD_TO_NEW.items():
        ProcurementRequest.objects.filter(status=old).update(status=new)
    for request in ProcurementRequest.objects.filter(received_at__isnull=False, received_by__isnull=True):
        request.received_by_id = request.updated_by_id
        request.save(update_fields=["received_by"])


def backwards(apps, schema_editor):
    ProcurementRequest = apps.get_model("financial_monitoring", "ProcurementRequest")
    ProcurementRequest.objects.filter(status="completed").update(status="released")
    ProcurementRequest.objects.exclude(status__in=("requested", "released", "cancelled")).update(status="processing")


class Migration(migrations.Migration):
    """Separate from 0005: Postgres can't build 0005's FK index while this data update has pending trigger events."""

    dependencies = [
        ('financial_monitoring', '0005_procurement_tracking_statuses'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
