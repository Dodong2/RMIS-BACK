from django.db import migrations

from budget_lib.lib_items import seed_lib_items


def seed(apps, schema_editor):
    seed_lib_items(apps.get_model("budget_lib", "LibItem"))


class Migration(migrations.Migration):
    dependencies = [("budget_lib", "0008_lib_items")]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
