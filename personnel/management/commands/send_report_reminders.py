"""Monthly and quarterly Brevo reminders (client follow-up 2026-10-02). RMIS has no scheduler (no Celery), so the
server's cron runs this command:

    # 08:00 on the 1st of every month: project staff get their tasks + last month's accomplishments
    0 8 1 * *        cd /path/to/rmis-backend && venv/bin/python manage.py send_report_reminders --monthly
    # 08:00 on the 1st of Jan/Apr/Jul/Oct: leaders update the SF-017 %, RIUH gets the summary
    0 8 1 1,4,7,10 * cd /path/to/rmis-backend && venv/bin/python manage.py send_report_reminders --quarterly

`--dry-run` lists who would get what without sending anything.
"""
import datetime
from html import escape

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q, Sum
from django.utils import timezone

from accounts.emails import send_brevo_email
from accounts.models import User
from monitoring.models import MidtermReport
from personnel.models import Task
from personnel.notifications import button, display_name, table
from reports.forms import month_bounds
from research_projects.models import Project


def latest_percent(project):
    """(project year, latest quarter with any %, average % of that quarter) from the newest SF-017, or None."""
    report = MidtermReport.objects.filter(project=project).order_by("-project_year").first()
    rows = report.objective_accomplishments if report else []
    for q in ("q4", "q3", "q2", "q1"):
        values = [row[q] for row in rows if row.get(q) is not None]
        if values:
            return report.project_year, q.upper(), sum(values) / len(values)
    return None


class Command(BaseCommand):
    help = "E-mail the monthly (project staff) or quarterly (leaders + RIUH) reminders through Brevo."

    def add_arguments(self, parser):
        parser.add_argument("--monthly", action="store_true")
        parser.add_argument("--quarterly", action="store_true")
        parser.add_argument("--dry-run", action="store_true", help="Print the recipients, send nothing")

    def handle(self, *args, monthly, quarterly, dry_run, **options):
        if monthly == quarterly:
            raise CommandError("Pass exactly one of --monthly or --quarterly.")
        self.dry_run = dry_run
        self.sent = 0
        today = timezone.localdate()
        if monthly:
            self.monthly(today.replace(day=1) - datetime.timedelta(days=1))
        else:
            self.quarterly(today)
        self.stdout.write(f"{'Would send' if dry_run else 'Sent'} {self.sent} e-mail(s).")

    def send(self, to, subject, html):
        self.sent += 1
        if self.dry_run:
            self.stdout.write(f"  {to}: {subject}")
        else:
            send_brevo_email(to, subject, html)

    def monthly(self, last_month):
        """Each active project staff with tasks: what is still open, and what they did last month."""
        start, end = month_bounds(last_month)
        staff = User.objects.filter(role__code="project_staff", is_active=True).order_by("id")
        for user in staff:
            open_tasks = Task.objects.filter(assignee=user).exclude(status="done").select_related("project").order_by("due_date")
            done_last_month = (
                Task.objects.filter(assignee=user)
                .filter(Q(updates__created_at__gte=start, updates__created_at__lt=end) | Q(completed_at__gte=start, completed_at__lt=end))
                .select_related("project").distinct()
            )
            if not open_tasks and not done_last_month:
                continue
            accomplished = [
                (t.project.project_code, t.title, f"{t.progress_as_of(end)}%",
                 f"{t.updates.filter(author=user, created_at__gte=start, created_at__lt=end).aggregate(h=Sum('hours'))['h'] or 0:g}")
                for t in done_last_month
            ]
            today = timezone.localdate()
            pending = [
                (t.project.project_code, t.title, f"{t.due_date:%b %d, %Y}" if t.due_date else "—",
                 "OVERDUE" if t.due_date and t.due_date < today else t.get_status_display(), f"{t.progress_pct}%")
                for t in open_tasks
            ]
            html = (
                f"<p>Hi {escape(display_name(user))},</p>"
                f"<p>Here is your monthly RMIS summary.</p>"
                f"<h3>Accomplishments in {last_month:%B %Y}</h3>"
                + (table(["Project", "Task", "% Completed", "Hours"], accomplished) if accomplished else "<p>No task updates last month.</p>")
                + "<h3>Open tasks</h3>"
                + (table(["Project", "Task", "Deadline", "Status", "% Completed"], pending) if pending else "<p>None.</p>")
                + "<p>Download your Monthly Accomplishment Report from the Tasks page and keep your task progress up to date.</p>"
                + f"<p>{button(f'{settings.FRONTEND_URL}/tasks', 'Open my tasks')}"
                + button(f"{settings.FRONTEND_URL}/tasks?view=calendar", "Open my calendar") + "</p>"
            )
            self.send(user.email, f"[RMIS] Your tasks and accomplishments for {last_month:%B %Y}", html)

    def quarterly(self, today):
        """Leaders: update the SF-017 % per objective. RIUH: where every active project stands."""
        quarter = f"Q{(today.month - 1) // 3 or 4} {today.year if today.month > 3 else today.year - 1}"
        projects = list(Project.objects.filter(status="active").select_related("lead").order_by("project_code"))
        leaders = {}
        for project in projects:
            leads = {project.lead, *(s.lead for s in project.studies.exclude(lead=None).select_related("lead"))}
            for lead in leads:
                if lead.is_active:
                    leaders.setdefault(lead, []).append(project)
        monitoring = f"{settings.FRONTEND_URL}/monitoring"
        for lead, own in leaders.items():
            rows = []
            for project in own:
                latest = latest_percent(project)
                rows.append((project.project_code, project.title,
                             f"Year {latest[0]} {latest[1]}: {latest[2]:.0f}% avg" if latest else "Nothing reported yet"))
            html = (
                f"<p>Hi {escape(display_name(lead))},</p>"
                f"<p>{quarter} has ended. Please update the % accomplishment per objective (LSPU-RDO-SF-017, Appendix E) "
                "of your projects in RMIS: Monitoring → Reports → Midterm.</p>"
                + table(["Project", "Title", "Latest SF-017 %"], rows)
                + f"<p>{button(monitoring, 'Open Monitoring')}</p>"
            )
            self.send(lead.email, f"[RMIS] {quarter}: update your projects' % accomplishment", html)

        today_date = timezone.localdate()
        summary = []
        for project in projects:
            latest = latest_percent(project)
            tasks = project.tasks.exclude(status="done")
            summary.append((
                project.project_code, display_name(project.lead),
                f"Year {latest[0]} {latest[1]}: {latest[2]:.0f}%" if latest else "Not reported",
                tasks.count(), tasks.filter(due_date__lt=today_date).count(),
            ))
        for riuh in User.objects.filter(role__code="riuh", is_active=True):
            html = (
                f"<p>Hi {escape(display_name(riuh))},</p><p>{quarter} summary of the {len(projects)} active project(s).</p>"
                + table(["Project", "Leader", "Latest SF-017 % (avg)", "Open tasks", "Overdue tasks"], summary)
                + f"<p>{button(monitoring, 'Open Monitoring')}</p>"
            )
            self.send(riuh.email, f"[RMIS] {quarter} project progress summary", html)
