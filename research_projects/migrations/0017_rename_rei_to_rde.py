from django.db import migrations, models


class Migration(migrations.Migration):
    """Client 2026-10-20: it's the RDE Agenda, so the internal REI names follow. Renames only; no data changes."""

    dependencies = [
        ("research_projects", "0016_seed_rde_agenda"),
    ]

    operations = [
        migrations.RenameModel("ReiThrust", "RdeThrust"),
        migrations.RenameField("program", "rei_thrust", "rde_thrust"),
        migrations.RenameField("program", "rei_priority", "rde_priority"),
        migrations.RenameField("project", "rei_thrust", "rde_thrust"),
        migrations.RenameField("project", "rei_priority", "rde_priority"),
        migrations.AlterField(
            "program", "rde_priority",
            models.CharField(blank=True, help_text="RDE Priority Area under rde_thrust", max_length=150),
        ),
        migrations.AlterField(
            "project", "rde_priority",
            models.CharField(blank=True, help_text="RDE Priority Area under rde_thrust", max_length=150),
        ),
    ]
