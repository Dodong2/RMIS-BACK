"""Catalog of permission codes and the role-list constant each one was seeded from (client clarification Q2).
The seed migration froze the role lists at the time; `scripts/permission_parity.py` compares the DB to them."""

# code: (module, name, "app.module:CONSTANT" it was seeded from)
PERMISSIONS = {
    "accounts.manage_users": ("accounts", "Approve users, assign roles/scope, activate/suspend, view audit logs", "accounts.permission_seed:SYSTEM_ADMIN_ONLY"),
    "accounts.view_users_by_role": ("accounts", "List active users by role (for leader/staff pickers)", "accounts.permission_seed:USERS_BY_ROLE"),
    "projects.register": ("research_projects", "Register/edit programs, projects, studies", "research_projects.views:REGISTRATION_ROLES"),
    "projects.manage_milestones": ("research_projects", "Create/edit work-plan milestones", "research_projects.views:MILESTONE_ROLES"),
    "personnel.manage": ("personnel", "Manage staff profiles, assignments, personnel changes", "personnel.serializers:MANAGE_ROLES"),
    "personnel.view_leader_load": ("personnel", "View leader concurrency load", "accounts.permission_seed:LEADER_LOAD"),
    "personnel.assign_tasks": ("personnel", "Assign, review, and manage tasks", "personnel.serializers:TASK_ASSIGNER_ROLES"),
    "personnel.clearance": ("personnel", "Acknowledge property clearance", "personnel.serializers:CLEARANCE_ROLES"),
    "budget.manage": ("budget_lib", "Encode LIB budgets and line items", "budget_lib.views:MANAGE_ROLES"),
    "budget.certify": ("budget_lib", "Certify a LIB budget (Budget Officer)", "budget_lib.serializers:CERTIFY_ROLES"),
    "financial.record_disbursement": ("financial_monitoring", "Record actual disbursements", "financial_monitoring.serializers:DISBURSEMENT_ROLES"),
    "financial.request_realignment": ("financial_monitoring", "Request a budget realignment", "financial_monitoring.serializers:REALIGNMENT_REQUEST_ROLES"),
    "financial.review_major_realignment": ("financial_monitoring", "Review major (33-100%) realignments", "financial_monitoring.serializers:REALIGNMENT_MAJOR_REVIEW_ROLES"),
    "financial.review_bor_realignment": ("financial_monitoring", "Record BOR-tier realignment approval", "financial_monitoring.serializers:REALIGNMENT_BOR_REVIEW_ROLES"),
    "financial.request_procurement": ("financial_monitoring", "File procurement requests", "financial_monitoring.serializers:PROCUREMENT_REQUEST_ROLES"),
    "financial.update_procurement": ("financial_monitoring", "Move procurement status (Procurement Office)", "financial_monitoring.serializers:PROCUREMENT_STATUS_ROLES"),
    "budget_sync.manage": ("budget_sync", "Import Budget Office workbooks and link records", "budget_sync.serializers:SYNC_ROLES"),
    "compliance.manage": ("compliance", "Verify/review compliance records, misconduct cases", "compliance.serializers:MANAGE_ROLES"),
    "compliance.encode": ("compliance", "Encode compliance records and requirements", "compliance.serializers:ENCODE_ROLES"),
    "documents.manage": ("document_management", "Review and archive documents", "document_management.serializers:MANAGE_ROLES"),
    "outputs.manage": ("outputs", "Maintain SENSE publisher list", "outputs.serializers:MANAGE_ROLES"),
    "outputs.report": ("outputs", "Record publications, IP, expected outputs, outcomes", "outputs.serializers:REPORT_ROLES"),
    "outputs.report_creative_work": ("outputs", "Record creative works", "outputs.serializers:CREATIVE_WORK_ROLES"),
    "monitoring.report": ("monitoring", "Submit monthly/midterm/terminal reports and renewals", "monitoring.serializers:REPORT_ROLES"),
    "monitoring.certify_terminal": ("monitoring", "Certify terminal reports", "monitoring.serializers:TERMINAL_CERTIFY_ROLES"),
    "monitoring.evaluate": ("monitoring", "Record evaluations, rubric, and scores (panel)", "monitoring.serializers:EVALUATION_PANEL_ROLES"),
    "monitoring.decide_renewal": ("monitoring", "Approve/deny renewal applications", "monitoring.serializers:RENEWAL_DECISION_ROLES"),
    "monitoring.request_extension": ("monitoring", "Request a project extension", "monitoring.serializers:EXTENSION_REQUEST_ROLES"),
    "monitoring.endorse_extension": ("monitoring", "Endorse an extension (DRD / campus coordinator)", "monitoring.serializers:EXTENSION_ENDORSE_ROLES"),
    "monitoring.approve_extension": ("monitoring", "Approve/deny an extension (University President)", "monitoring.serializers:EXTENSION_APPROVE_ROLES"),
    "dashboard.manage_targets": ("dashboard", "Set Planning Office targets", "dashboard.serializers:MANAGE_ROLES"),
    "forecasting.run": ("forecasting", "Trigger ARIMA forecast runs", "forecasting.serializers:FORECAST_ROLES"),
    "dss.manage": ("decision_support", "Manage criteria, AHP runs, WSM recommendation runs", "decision_support.serializers:DSS_ROLES"),
    "dss.decide": ("decision_support", "Record funding decisions on recommendations", "decision_support.serializers:DECISION_ROLES"),
    "risk.manage_register": ("risk_indicators", "Maintain the project risk register", "risk_indicators.serializers:RISK_REGISTER_ROLES"),
    "reports.view_logs": ("reports", "View the generated-report audit log", "reports.views:REPORT_LOG_VIEW_ROLES"),
}

# Gates that were inline HasRole([...]) lists rather than named constants.
SYSTEM_ADMIN_ONLY = ["system_admin"]
USERS_BY_ROLE = ["system_admin", "crc_chair", "drd", "riuh", "program_leader", "project_leader", "study_leader"]
LEADER_LOAD = ["system_admin", "crc_chair", "drd", "riuh", "program_leader", "project_leader"]
