from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

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

    dependencies = [
        ('financial_monitoring', '0004_budgetrealignment_batch'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RenameField(model_name='procurementrequest', old_name='processing_at', new_name='received_at'),
        migrations.RenameField(model_name='procurementrequest', old_name='released_at', new_name='completed_at'),
        migrations.AddField(
            model_name='procurementrequest',
            name='received_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='procurement_received', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name='procurementrequest',
            name='status',
            field=models.CharField(choices=[('requested', 'Request Submitted'), ('under_review', 'Under Review'), ('returned_for_revision', 'Returned for Revision'), ('for_procurement', 'For Procurement'), ('procurement_in_progress', 'Procurement in Progress'), ('order_placed', 'Order Placed'), ('awaiting_delivery', 'Awaiting Delivery'), ('delivered', 'Delivered'), ('ready_for_release', 'Ready for Release'), ('completed', 'Completed'), ('cancelled', 'Cancelled')], default='requested', max_length=30),
        ),
        migrations.RunPython(forwards, backwards),
    ]
