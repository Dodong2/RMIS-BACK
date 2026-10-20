from django.db import migrations

from research_projects.rde_agenda import seed_rde_agenda


def seed(apps, schema_editor):
    seed_rde_agenda(apps.get_model("research_projects", "ReiThrust"))


class Migration(migrations.Migration):
    dependencies = [("research_projects", "0015_rde_agenda_hierarchy")]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
