"""Client 2026-10-27: 12 roles become 9. DRD joins the CRC Chair as "CRC/CRD" (one person does both; the CRC Chair's
permissions only, none of DRD's own). Program and Study Leaders join the Project Leader, who sees only the projects
they lead. Accounts and Annex A rows on a legacy role move to the merged one, and the legacy roles lose every grant.
The legacy Role rows themselves are deleted by a later migration, once no code uses them."""

from django.db import migrations

MERGED = {"drd": "crc_chair", "program_leader": "project_leader", "study_leader": "project_leader"}
LABELS = {"crc_chair": ("CRC/CRD", "CRC Chairperson"),
          "project_leader": ("Project Leader/Program Leader/Study Leader", "Project Leader")}

# The legacy roles' grants on 2026-10-27, restored by the reverse migration.
LEGACY_GRANTS = {
    "drd": [
        "accounts.view_users_by_role", "dashboard.manage_targets", "dashboard.view_portfolio", "dss.decide", "dss.manage",
        "forecasting.run", "monitoring.decide_renewal", "monitoring.endorse_extension", "monitoring.evaluate",
        "monitoring.quarterly_approve", "monitoring.quarterly_review", "personnel.assign_tasks", "personnel.clearance",
        "personnel.manage", "personnel.view_leader_load", "projects.edit", "projects.register", "reports.view_logs",
        "risk.manage_register",
    ],
    "program_leader": [
        "accounts.view_users_by_role", "compliance.encode", "dashboard.view_portfolio", "financial.request_procurement",
        "monitoring.request_extension", "personnel.assign_tasks", "personnel.view_leader_load", "projects.edit",
        "projects.manage_milestones", "risk.manage_register",
    ],
    "study_leader": [
        "accounts.view_users_by_role", "compliance.encode", "monitoring.report", "outputs.report",
        "outputs.report_creative_work", "personnel.assign_tasks", "projects.edit", "projects.manage_milestones",
    ],
}


def forwards(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    User = apps.get_model("accounts", "User")
    RolePermission = apps.get_model("accounts", "RolePermission")
    ProjectEndorser = apps.get_model("research_projects", "ProjectEndorser")
    roles = {role.code: role for role in Role.objects.all()}
    for code, (label, _old) in LABELS.items():
        Role.objects.filter(code=code).update(name=label)
    for legacy, merged in MERGED.items():
        if legacy not in roles or merged not in roles:
            continue
        User.objects.filter(role=roles[legacy]).update(role=roles[merged])
        User.objects.filter(requested_role=roles[legacy]).update(requested_role=roles[merged])
        ProjectEndorser.objects.filter(role_code=legacy).update(role_code=merged)
        RolePermission.objects.filter(role=roles[legacy]).delete()


def backwards(apps, schema_editor):
    """Labels and grants come back; accounts and Annex A rows stay on the merged role (there is no record of which
    were moved, and there were none on 2026-10-27)."""
    Role = apps.get_model("accounts", "Role")
    Permission = apps.get_model("accounts", "Permission")
    RolePermission = apps.get_model("accounts", "RolePermission")
    for code, (_label, old) in LABELS.items():
        Role.objects.filter(code=code).update(name=old)
    permissions = {p.code: p for p in Permission.objects.all()}
    for code, grants in LEGACY_GRANTS.items():
        role = Role.objects.filter(code=code).first()
        if role:
            for permission in grants:
                if permission in permissions:
                    RolePermission.objects.get_or_create(role=role, permission=permissions[permission])


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0025_registration_fields"),
        ("research_projects", "0019_research_classification_not_applicable"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
