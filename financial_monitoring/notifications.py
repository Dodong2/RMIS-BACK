"""Task 23 (2026-10-30): Brevo e-mails along the procurement workflow. Filed -> every active Procurement Officer - LIB of
the project's campus; Received, Returned for Revision and Completed -> the requester; Completed also -> every active
Finance/Accounting/Budget of the campus (now awaiting payment). Sent after commit; a failed send is logged by
send_brevo_email and never undoes the step. Each step runs once per request under its row lock, so it can't send twice."""
from html import escape

from django.conf import settings

from accounts.emails import send_brevo_email
from budget_lib.notifications import campus_reviewers, peso
from personnel.notifications import button, table


def _summary(procurement):
    item = procurement.line_item
    rows = [
        ("Expense Category", item.get_category_display()),
        ("LIB Item", item.description),
        ("Project Year", f"Year {procurement.project_year}" if procurement.project_year else "—"),
    ]
    if procurement.quarter:
        rows.append(("Quarter", f"Q{procurement.quarter}"))
    rows += [("Description", procurement.description), ("Requested Amount", peso(procurement.amount))]
    return table(["Item", "Details"], rows)


def _header(procurement):
    project = procurement.line_item.budget.project
    return (f"<p><b>Project NTP Code:</b> {escape(project.project_code or '—')}<br>"
            f"<b>Project Proposal:</b> {escape(project.title)}<br>"
            f"<b>Request No.:</b> PR-{procurement.pk:04d}</p>")


def _link(label):
    return f"<p>{button(f'{settings.FRONTEND_URL}/procurement', label)}</p><p>Thank you.</p>"


def _send(recipients, subject, html):
    for email in dict.fromkeys(recipients):
        send_brevo_email(email, subject, html)


def request_filed(procurement):
    project, requester = procurement.line_item.budget.project, procurement.requested_by
    html = (
        "<p>A new procurement request has been submitted and is awaiting your review.</p>"
        f"{_header(procurement)}"
        f"<p><b>Requested by:</b><br>{escape(requester.display_name)}<br>{escape(requester.email)}</p>"
        f"<p><b>Procurement Request Summary:</b></p>{_summary(procurement)}"
        "<p>Please log in to your RMIS account and review the request under Pending Procurement Requests.</p>"
        f"{_link('Open Procurement')}"
    )
    _send(campus_reviewers(project, "procurement_officer_lib").values_list("email", flat=True),
          f"New Procurement Request — {project.title}", html)


def request_received(procurement):
    project = procurement.line_item.budget.project
    html = (
        "<p>Your procurement request has been received by the Procurement Office.</p>"
        f"{_header(procurement)}{_summary(procurement)}"
        f"<p><b>Received by:</b> {escape(procurement.received_by.display_name)}</p>"
        "<p>The Procurement Officer will review your request and provide an update through RMIS.</p>"
        f"{_link('Open Procurement')}"
    )
    _send([procurement.requested_by.email], f"Procurement Request Received — {project.title}", html)


def request_returned(procurement):
    project = procurement.line_item.budget.project
    html = (
        "<p>Your procurement request has been <b>returned for revision</b> by the Procurement Office.</p>"
        f"{_header(procurement)}{_summary(procurement)}"
        f"<p><b>Remarks from the Procurement Office:</b><br>{escape(procurement.remarks)}</p>"
        "<p>Please open the request in RMIS, use <b>Revise &amp; Resubmit</b>, and make the required correction.</p>"
        f"{_link('Open Procurement')}"
    )
    _send([procurement.requested_by.email], f"Procurement Request Returned for Revision — {project.title}", html)


def request_completed(procurement):
    project = procurement.line_item.budget.project
    summary = f"{_header(procurement)}{_summary(procurement)}"
    _send([procurement.requested_by.email], f"Procurement Request Completed — {project.title}", (
        "<p>Your procurement request has been completed by the Procurement Office.</p>"
        f"{summary}<p>Payment is confirmed separately by Finance/Accounting/Budget.</p>{_link('Open Procurement')}"
    ))
    _send(campus_reviewers(project, "finance_budget").values_list("email", flat=True),
          f"Procurement Completed — Awaiting Payment — {project.title}", (
        "<p>A procurement request has been completed by the Procurement Office and is now awaiting payment.</p>"
        f"{summary}<p><b>Requested by:</b> {escape(procurement.requested_by.display_name)}</p>"
        "<p>Please open your RMIS account to confirm the payment once it has been made.</p>"
        f"<p>{button(f'{settings.FRONTEND_URL}/budget', 'Open Budget Management')}</p><p>Thank you.</p>"
    ))
