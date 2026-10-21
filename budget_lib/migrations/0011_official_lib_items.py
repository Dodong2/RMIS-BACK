from django.db import migrations

from budget_lib.lib_items import LIB_ITEMS, seed_lib_items

# The 2026-10-20 starting list (DBM UACS 2013) that 0009 seeded before the client sent the official one.
OLD_STARTING_ITEMS = [
    ("ps", "Salaries and Wages - Casual/Contractual"), ("ps", "Overtime Pay"),
    ("mooe", "Medical, Dental and Laboratory Supplies Expenses"), ("mooe", "Fuel, Oil and Lubricants Expenses"),
    ("mooe", "Agricultural and Marine Supplies Expenses"), ("mooe", "Chemical and Filtering Supplies Expenses"),
    ("mooe", "Postage and Courier Services"), ("mooe", "Survey Expenses"),
    ("mooe", "Research, Exploration and Development Expenses"), ("mooe", "Consultancy Services"),
    ("mooe", "Printing and Publication Expenses"), ("mooe", "Rents - Motor Vehicles"), ("mooe", "Rents - Equipment"),
    ("co", "Agricultural and Forestry Equipment"), ("co", "Other Machinery and Equipment"),
]


def official_list(apps, schema_editor):
    """Client 2026-10-21: the LIB Items are the official 2027-LIB-proposed.xlsx list. Old starting items it doesn't have
    are deactivated, never deleted (Carl 2026-10-22), so nothing an LIB may point to goes away. Items the System Admin
    added are left alone."""
    LibItem = apps.get_model("budget_lib", "LibItem")
    seed_lib_items(LibItem)
    official = {(category, name.lower()) for category, name, _ in LIB_ITEMS}
    for category, name in OLD_STARTING_ITEMS:
        if (category, name.lower()) in official:
            continue
        LibItem.objects.filter(category=category, name__iexact=name).update(is_active=False)


class Migration(migrations.Migration):
    dependencies = [("budget_lib", "0010_lib_review_workflow")]

    operations = [migrations.RunPython(official_list, migrations.RunPython.noop)]
