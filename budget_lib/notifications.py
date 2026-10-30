"""Task 15 (2026-10-30): when a Project Leader submits or resubmits a proposal (its LIB), every active CRC/CRD of the
project's campus gets a Brevo e-mail; Task 19: when the CRC/CRD forwards it, every active Finance/Accounting/Budget of
the campus does. Sent after commit; a failed send is logged by send_brevo_email and never undoes the step. Repeating a
step is refused by the LIB workflow, so it can't send twice."""
from collections import defaultdict
from decimal import Decimal
from html import escape

from django.conf import settings

from accounts.emails import send_brevo_email
from accounts.models import User
from personnel.notifications import button, table

from .models import allocation_periods


def campus_reviewers(project, role="crc_chair"):
    """The active accounts of the role on the project's campus (the Project Leader's campus); none without a campus."""
    if not project.campus:
        return User.objects.none()
    return User.objects.filter(role__code=role, is_active=True, account_status="active", campus__iexact=project.campus)


def budget_by_year(budget):
    """[(label, amount)]: each project year's share of the saved quarterly allocations (Y2Q3 -> Year 2, Q1-Q4 of a
    one-year project -> Year 1), every year of the project's duration listed, then the LIB total. An item saved
    without allocations counts only in the total."""
    periods = allocation_periods(budget.project) or []
    year_of = lambda period: int(period[1:period.index("Q")]) if period[0] == "Y" else 1
    years = defaultdict(Decimal, {year_of(p): Decimal("0") for p in periods})
    total = Decimal("0")
    for item in budget.line_items.all():
        total += item.amount
        for row in item.allocations or []:
            if row.get("period") in periods:
                years[year_of(row["period"])] += Decimal(str(row["amount"]))
    return [(f"Year {year}", years[year]) for year in sorted(years)] + [("Total", total)]


def peso(amount):
    return f"₱{amount:,.2f}"


def budget_table(budget):
    return table(["Project Year", "Amount"], [(label, peso(amount)) for label, amount in budget_by_year(budget)])


def proposal_submitted(budget, resubmitted=False):
    project, lead = budget.project, budget.project.lead
    recipients = list(campus_reviewers(project).values_list("email", flat=True))
    if not recipients:
        return
    what = "resubmitted after revision" if resubmitted else "submitted"
    subject = f"{'Project Proposal Resubmitted' if resubmitted else 'New Project Proposal Submitted'} — {project.title}"
    html = (
        f"<p>A project proposal has been {what} and is ready for CRC/CRD review.</p>"
        f"<p><b>Project Leader:</b> {escape(lead.display_name)}<br><b>Email:</b> {escape(lead.email)}<br>"
        f"<b>Project Proposal:</b> {escape(project.title)}</p>"
        f"<p><b>Budget by Project Year:</b></p>{budget_table(budget)}"
        f"<p>Please open your RMIS account to review the submitted proposal and proceed with the appropriate review workflow.</p>"
        f"<p>{button(f'{settings.FRONTEND_URL}/projects', 'Open Project Management')}</p><p>Thank you.</p>"
    )
    for email in recipients:
        send_brevo_email(email, subject, html)


def ready_for_budget_review(budget, crc_user):
    project, lead = budget.project, budget.project.lead
    recipients = list(campus_reviewers(project, "finance_budget").values_list("email", flat=True))
    if not recipients:
        return
    subject = f"Project Proposal Ready for Budget Review — {project.title}"
    html = (
        "<p>A project proposal has been reviewed by CRC/CRD and is now ready for budget review and certification.</p>"
        f"<p><b>Project Leader:</b> {escape(lead.display_name)}<br><b>Project Leader Email:</b> {escape(lead.email)}<br>"
        f"<b>Project Proposal:</b> {escape(project.title)}<br><b>Submitted by CRC/CRD:</b> {escape(crc_user.display_name)}</p>"
        f"<p><b>Budget by Project Year:</b></p>{budget_table(budget)}"
        "<p>Please open your RMIS account to review the submitted proposal and proceed with the appropriate budget review "
        "and certification workflow.</p>"
        f"<p>{button(f'{settings.FRONTEND_URL}/budget', 'Open Budget Management')}</p><p>Thank you.</p>"
    )
    for email in recipients:
        send_brevo_email(email, subject, html)
