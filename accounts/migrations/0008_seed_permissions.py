"""Seeds Permission + RolePermission (client clarification Q2). The role lists are frozen copies of the *_ROLES
constants named in accounts/permission_seed.py as of this migration; scripts/permission_parity.py checks they still match."""

from django.db import migrations

# code: (module, name, role codes)
SEED = {
    'accounts.manage_users': ('accounts', 'Approve users, assign roles/scope, activate/suspend, view audit logs', ['system_admin']),
    'accounts.view_users_by_role': ('accounts', 'List active users by role (for leader/staff pickers)', ['crc_chair', 'system_admin']),
    'projects.register': ('research_projects', 'Register/edit programs, projects, studies', ['crc_chair', 'system_admin']),
    'projects.manage_milestones': ('research_projects', 'Create/edit work-plan milestones', ['crc_chair', 'program_leader', 'project_leader', 'study_leader', 'system_admin']),
    'personnel.manage': ('personnel', 'Manage staff profiles, assignments, personnel changes', ['crc_chair', 'drd', 'riuh', 'system_admin']),
    'personnel.view_leader_load': ('personnel', 'View leader concurrency load', ['crc_chair', 'drd', 'program_leader', 'project_leader', 'riuh', 'system_admin']),
    'personnel.assign_tasks': ('personnel', 'Assign, review, and manage tasks', ['crc_chair', 'drd', 'program_leader', 'project_leader', 'riuh', 'study_leader', 'system_admin']),
    'personnel.clearance': ('personnel', 'Acknowledge property clearance', ['crc_chair', 'drd', 'procurement_officer_lib', 'riuh', 'system_admin']),
    'budget.manage': ('budget_lib', 'Encode LIB budgets and line items', ['finance_budget', 'procurement_officer_lib', 'program_leader', 'project_leader', 'system_admin']),
    'budget.certify': ('budget_lib', 'Certify a LIB budget (Budget Officer)', ['finance_budget', 'system_admin']),
    'financial.record_disbursement': ('financial_monitoring', 'Record actual disbursements', ['finance_budget', 'system_admin']),
    'financial.request_realignment': ('financial_monitoring', 'Request a budget realignment', ['project_leader', 'system_admin']),
    'financial.review_major_realignment': ('financial_monitoring', 'Review major (33-100%) realignments', ['system_admin', 'university_admin']),
    'financial.review_bor_realignment': ('financial_monitoring', 'Record BOR-tier realignment approval', ['system_admin']),
    'financial.request_procurement': ('financial_monitoring', 'File procurement requests', ['program_leader', 'project_leader', 'system_admin']),
    'financial.update_procurement': ('financial_monitoring', 'Move procurement status (Procurement Office)', ['procurement_officer_lib', 'system_admin']),
    'budget_sync.manage': ('budget_sync', 'Import Budget Office workbooks and link records', ['finance_budget', 'system_admin']),
    'compliance.manage': ('compliance', 'Verify/review compliance records, misconduct cases', ['riuh', 'system_admin']),
    'compliance.encode': ('compliance', 'Encode compliance records and requirements', ['program_leader', 'project_leader', 'riuh', 'study_leader', 'system_admin']),
    'documents.manage': ('document_management', 'Review and archive documents', ['riuh', 'system_admin']),
    'outputs.manage': ('outputs', 'Maintain SENSE publisher list', ['riuh', 'system_admin']),
    'outputs.report': ('outputs', 'Record publications, IP, expected outputs, outcomes', ['project_leader', 'riuh', 'study_leader', 'system_admin']),
    'outputs.report_creative_work': ('outputs', 'Record creative works', ['project_leader', 'project_staff', 'riuh', 'study_leader', 'system_admin']),
    'monitoring.report': ('monitoring', 'Submit monthly/midterm/terminal reports and renewals', ['project_leader', 'project_staff', 'riuh', 'study_leader', 'system_admin']),
    'monitoring.certify_terminal': ('monitoring', 'Certify terminal reports', ['riuh', 'system_admin']),
    'monitoring.evaluate': ('monitoring', 'Record evaluations, rubric, and scores (panel)', ['crc_chair', 'drd', 'system_admin', 'vprei']),
    'monitoring.decide_renewal': ('monitoring', 'Approve/deny renewal applications', ['drd', 'riuh', 'system_admin', 'vprei']),
    'monitoring.request_extension': ('monitoring', 'Request a project extension', ['program_leader', 'project_leader', 'system_admin']),
    'monitoring.endorse_extension': ('monitoring', 'Endorse an extension (DRD / campus coordinator)', ['crc_chair', 'drd', 'system_admin']),
    'monitoring.approve_extension': ('monitoring', 'Approve/deny an extension (University President)', ['system_admin', 'university_admin']),
    'dashboard.manage_targets': ('dashboard', 'Set Planning Office targets', ['drd', 'riuh', 'system_admin', 'vprei']),
    'forecasting.run': ('forecasting', 'Trigger ARIMA forecast runs', ['drd', 'finance_budget', 'system_admin', 'vprei']),
    'dss.manage': ('decision_support', 'Manage criteria, AHP runs, WSM recommendation runs', ['drd', 'system_admin', 'vprei']),
    'dss.decide': ('decision_support', 'Record funding decisions on recommendations', ['drd', 'system_admin', 'university_admin', 'vprei']),
    'risk.manage_register': ('risk_indicators', 'Maintain the project risk register', ['crc_chair', 'drd', 'program_leader', 'project_leader', 'riuh', 'system_admin', 'vprei']),
    'reports.view_logs': ('reports', 'View the generated-report audit log', ['drd', 'riuh', 'system_admin', 'vprei']),
}


def seed(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    Permission = apps.get_model("accounts", "Permission")
    RolePermission = apps.get_model("accounts", "RolePermission")
    roles = {r.code: r for r in Role.objects.all()}
    for code, (module, name, role_codes) in SEED.items():
        perm, _ = Permission.objects.update_or_create(code=code, defaults={"module": module, "name": name})
        for role_code in role_codes:
            if role_code in roles:
                RolePermission.objects.get_or_create(role=roles[role_code], permission=perm)


def unseed(apps, schema_editor):
    apps.get_model("accounts", "Permission").objects.filter(code__in=SEED).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0007_permission_rolepermission"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
