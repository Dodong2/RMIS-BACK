from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


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
    ]
