import re

from django.db import migrations, models

REI_CODE = re.compile(r"^([A-Za-z]+-?\d+)\s+(.+)$")


def split_existing(apps, schema_editor):
    """Fill code/title from the old single name where it can be told apart; `name` itself is left as is so projects
    and Excel imports that use it keep matching. Anything else waits for the System Admin to edit it."""
    for unit in apps.get_model("research_projects", "CollegeUnit").objects.all():
        if " - " in unit.name:
            unit.code, unit.title = (part.strip() for part in unit.name.split(" - ", 1))
        elif " " not in unit.name and len(unit.name) <= 20:
            unit.code = unit.name
        else:
            unit.title = unit.name
        unit.save(update_fields=["code", "title"])
    for thrust in apps.get_model("research_projects", "ReiThrust").objects.all():
        match = REI_CODE.match(thrust.name)
        if match:
            thrust.code, thrust.title = match.group(1), match.group(2).strip()
        else:
            thrust.title = thrust.name
        thrust.save(update_fields=["code", "title"])


class Migration(migrations.Migration):

    dependencies = [
        ("research_projects", "0010_rei_thrust_cooperating_agency"),
    ]

    operations = [
        migrations.AddField(model_name="collegeunit", name="code", field=models.CharField(blank=True, max_length=20)),
        migrations.AddField(model_name="collegeunit", name="title", field=models.CharField(blank=True, max_length=100)),
        migrations.AddField(model_name="reithrust", name="code", field=models.CharField(blank=True, max_length=20)),
        migrations.AddField(model_name="reithrust", name="title", field=models.CharField(blank=True, max_length=100)),
        migrations.RunPython(split_existing, migrations.RunPython.noop),
    ]
