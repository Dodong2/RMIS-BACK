from django.db import migrations


def add_dash(apps, schema_editor):
    """REI Thrust names were "REI-01 Title"; the client wants "REI-01 - Title" like College Units. Only choices with
    both a code and a title are rebuilt; projects keep the text they were registered with."""
    for thrust in apps.get_model("research_projects", "ReiThrust").objects.exclude(code="").exclude(title=""):
        thrust.title = thrust.title.lstrip("-").strip()
        thrust.name = f"{thrust.code} - {thrust.title}"
        thrust.save(update_fields=["title", "name"])


class Migration(migrations.Migration):

    dependencies = [
        ("research_projects", "0011_coded_choices"),
    ]

    operations = [
        migrations.RunPython(add_dash, migrations.RunPython.noop),
    ]
