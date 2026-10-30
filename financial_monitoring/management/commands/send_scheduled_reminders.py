"""Task 24 (2026-10-30): scheduled reminder e-mails. RMIS has no scheduler, so the server runs this every hour:

    0 * * * *  cd /path/to/rmis-backend && venv/bin/python manage.py send_scheduled_reminders

Payment reminders (Carl Q7): three runs a month, the 7th, 14th and 21st at 08:00 Asia/Manila. Each hourly call works
out the latest run that is due, so a run the server missed is sent by the next call, and ReminderLog makes every
e-mail go out once per run (failed ones are retried). For that run, every project with Completed but unpaid
procurement requests gets one e-mail per active Finance/Accounting/Budget of its campus with the outstanding total.
Nothing but ReminderLog is written. `--dry-run` lists what would be sent.
"""
import datetime
from collections import defaultdict
from html import escape

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.reminders import send_once
from budget_lib.notifications import campus_reviewers, peso
from financial_monitoring.models import ProcurementRequest
from personnel.notifications import button, table

PAYMENT_DAYS = (7, 14, 21)
SEND_HOUR = 8


def payment_run(now):
    """The latest payment run (a date) due at `now`, in the configured timezone (Asia/Manila)."""
    local = timezone.localtime(now)
    due = [day for day in PAYMENT_DAYS if day < local.day or (day == local.day and local.hour >= SEND_HOUR)]
    if due:
        return datetime.date(local.year, local.month, due[-1])
    last_month = local.date().replace(day=1) - datetime.timedelta(days=1)
    return last_month.replace(day=PAYMENT_DAYS[-1])


def outstanding_by_project():
    """{project: [requests]} for every Completed request without a payment (Task 23: awaiting payment)."""
    requests = ProcurementRequest.objects.filter(status="completed", disbursement__isnull=True).select_related(
        "line_item__budget__project",
    ).order_by("completed_at", "id")
    grouped = defaultdict(list)
    for pr in requests:
        grouped[pr.line_item.budget.project].append(pr)
    return grouped


def payment_email(project, requests):
    total = sum(pr.amount for pr in requests)
    rows = [
        (f"PR-{pr.pk:04d}", pr.line_item.description, pr.description,
         (f"Year {pr.project_year}" if pr.project_year else "—") + (f" · Q{pr.quarter}" if pr.quarter else ""),
         peso(pr.amount))
        for pr in requests
    ]
    html = (
        "<p>Reminder: The following procurement payment requires your attention.</p>"
        f"<p><b>Project NTP Code:</b> {escape(project.project_code or '—')}<br>"
        f"<b>Project Proposal:</b> {escape(project.title)}</p>"
        f"<p><b>Payment Summary:</b></p>{table(['Request', 'LIB Item', 'Description', 'Year / Quarter', 'Amount'], rows)}"
        f"<p><b>Outstanding Amount:</b> {peso(total)}</p>"
        "<p>Please open your RMIS account to review the pending payment and complete the appropriate disbursement process.</p>"
        f"<p>{button(f'{settings.FRONTEND_URL}/budget?view=payments', 'Open Procurement Payments')}</p><p>Thank you.</p>"
    )
    return f"Payment Reminder — {project.title}", html


class Command(BaseCommand):
    help = "Send the due scheduled reminder e-mails (payment reminders on the 7th/14th/21st, 08:00 Manila)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="List the e-mails without sending or logging them.")

    def handle(self, *args, **options):
        run_key = payment_run(timezone.now()).isoformat()
        counts = defaultdict(int)
        for project, requests in outstanding_by_project().items():
            subject, html = payment_email(project, requests)
            for user in campus_reviewers(project, "finance_budget"):
                if options["dry_run"]:
                    self.stdout.write(f"[dry-run] payment {run_key} -> {user.email}: {project.project_code} ({len(requests)} request(s))")
                    continue
                counts[send_once("payment", run_key, user, f"project:{project.pk}", subject, html)] += 1
        self.stdout.write(
            f"Payment run {run_key}: {counts['sent']} sent, {counts['failed']} failed, {counts['skipped']} already done."
        )
