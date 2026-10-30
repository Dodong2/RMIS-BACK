"""Task 24 (2026-10-30): scheduled reminder e-mails. RMIS has no scheduler, so the server runs this every hour:

    0 * * * *  cd /path/to/rmis-backend && venv/bin/python manage.py send_scheduled_reminders

Payment reminders (Task 26, Carl 2026-10-30, replaces 7th/14th/21st): once a month, the 7th at 08:00 Asia/Manila. Each
hourly call works out the latest run that is due, so a run the server missed is sent by the next call, and ReminderLog
makes every e-mail go out once per run (failed ones are retried). For that run, every project with requests Completed
before the run but still unpaid gets one e-mail per active Finance/Accounting/Budget of its campus with the outstanding
total; a request Completed after the run waits for the next 7th.
Task reminders (Task 26, Carl 2026-10-30, replaces every 3 days): Monday, Tuesday and Wednesday from 08:00 Asia/Manila,
never on a weekend (a missed Wednesday is sent on Thursday or Friday), from the task's start date until it is Done,
overdue ones included, to its current assignee only if that account is Project Staff (so reassigning or deleting a task
stops them for the previous assignee). One e-mail per task per reminder day, the same way.
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
from personnel.models import Task
from personnel.notifications import button, table, task_reminder

PAYMENT_DAY = 7
SEND_HOUR = 8
TASK_WEEKDAYS = (0, 1, 2)  # Monday, Tuesday, Wednesday


def payment_run(now):
    """The latest payment run (a date) due at `now`, in the configured timezone (Asia/Manila)."""
    local = timezone.localtime(now)
    if local.day > PAYMENT_DAY or (local.day == PAYMENT_DAY and local.hour >= SEND_HOUR):
        return local.date().replace(day=PAYMENT_DAY)
    last_month = local.date().replace(day=1) - datetime.timedelta(days=1)
    return last_month.replace(day=PAYMENT_DAY)


def task_reminder_day(task, now):
    """The latest reminder day (Mon/Tue/Wed from 08:00) of the task due at `now`, or None on a weekend or before the
    task's first reminder day."""
    local = timezone.localtime(now)
    if not task.start_date or local.weekday() >= 5:
        return None
    day = local.date() if local.hour >= SEND_HOUR else local.date() - datetime.timedelta(days=1)
    while day.weekday() not in TASK_WEEKDAYS:
        day -= datetime.timedelta(days=1)
    return day if day >= task.start_date else None


def tasks_to_remind():
    return Task.objects.exclude(status="done").filter(
        start_date__isnull=False, project__status="active", assignee__is_active=True, assignee__role__code="project_staff",
    ).select_related("project", "assignee", "assigned_by").order_by("id")


def outstanding_by_project(before):
    """{project: [requests]} for every request Completed before `before` without a payment (Task 23: awaiting payment)."""
    requests = ProcurementRequest.objects.filter(
        status="completed", disbursement__isnull=True, completed_at__lt=before,
    ).select_related(
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
    help = "Send the due scheduled reminder e-mails (payment: the 7th; tasks: Mon/Tue/Wed; 08:00 Manila)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="List the e-mails without sending or logging them.")

    def handle(self, *args, **options):
        run = payment_run(timezone.now())
        run_key = run.isoformat()
        run_at = timezone.make_aware(datetime.datetime.combine(run, datetime.time(SEND_HOUR)))
        counts = defaultdict(int)
        for project, requests in outstanding_by_project(run_at).items():
            subject, html = payment_email(project, requests)
            for user in campus_reviewers(project, "finance_budget"):
                if options["dry_run"]:
                    self.stdout.write(f"[dry-run] payment {run_key} -> {user.email}: {project.project_code} ({len(requests)} request(s))")
                    continue
                counts[send_once("payment", run_key, user, f"project:{project.pk}", subject, html)] += 1
        self.stdout.write(
            f"Payment run {run_key}: {counts['sent']} sent, {counts['failed']} failed, {counts['skipped']} already done."
        )

        now, counts = timezone.now(), defaultdict(int)
        for task in tasks_to_remind():
            day = task_reminder_day(task, now)
            if day is None:
                continue
            if options["dry_run"]:
                self.stdout.write(f"[dry-run] task {day} -> {task.assignee.email}: {task.title}")
                continue
            subject, html = task_reminder(task)
            counts[send_once("task", day.isoformat(), task.assignee, f"task:{task.pk}", subject, html)] += 1
        self.stdout.write(f"Task reminders: {counts['sent']} sent, {counts['failed']} failed, {counts['skipped']} already done.")
