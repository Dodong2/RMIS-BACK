"""E-mails to project staff and leaders (client follow-up 2026-10-02), sent through Brevo like the account e-mails.

- task_assigned(): when a leader assigns (or reassigns) a task, the assignee gets its details, a link to the task in
  the RMIS calendar and an "Add to Google Calendar" link for the deadline.
- The monthly/quarterly reminders live in management/commands/send_report_reminders.py and reuse the helpers here.
"""
import datetime
from html import escape
from urllib.parse import urlencode

from django.conf import settings

from accounts.emails import send_brevo_email


def display_name(user):
    return user.get_full_name() or user.email


def calendar_link(task):
    return f"{settings.FRONTEND_URL}/tasks?{urlencode({'view': 'calendar', 'task': task.pk})}"


def google_calendar_link(task):
    """All-day Google Calendar event on the due date (Google's end date is exclusive, hence +1 day)."""
    if not task.due_date:
        return ""
    end = task.due_date + datetime.timedelta(days=1)
    return "https://calendar.google.com/calendar/render?" + urlencode({
        "action": "TEMPLATE",
        "text": f"[RMIS] {task.title}",
        "dates": f"{task.due_date:%Y%m%d}/{end:%Y%m%d}",
        "details": f"{task.project.project_code} · {task.project.title}\n\n{task.description}\n\n{calendar_link(task)}",
    })


def button(url, label):
    return (f'<a href="{escape(url)}" style="display:inline-block;padding:10px 16px;margin:4px 6px 4px 0;'
            f'background:#0d2a5e;color:#fff;border-radius:8px;text-decoration:none;font-weight:bold">{escape(label)}</a>')


def table(headers, rows):
    head = "".join(f'<th style="text-align:left;padding:6px 8px;background:#e0eaf7">{escape(h)}</th>' for h in headers)
    body = "".join(
        "<tr>" + "".join(f'<td style="padding:6px 8px;border-top:1px solid #e2e8f0">{escape(str(v))}</td>' for v in row) + "</tr>"
        for row in rows
    )
    return f'<table style="border-collapse:collapse;font-size:13px">{"<tr>" + head + "</tr>"}{body}</table>'


def task_assigned(task):
    due = f"{task.due_date:%B %d, %Y}" if task.due_date else "No deadline set"
    rows = [
        ("Project", f"{task.project.project_code} · {task.project.title}"),
        ("Task", task.title),
        ("Description", task.description or "—"),
        ("Deadline", due),
        ("Priority", task.get_priority_display()),
        ("Estimated hours", task.estimated_hours or "—"),
        ("Assigned by", display_name(task.assigned_by)),
    ]
    links = button(calendar_link(task), "Open in RMIS calendar")
    if task.due_date:
        links += button(google_calendar_link(task), "Add deadline to Google Calendar")
    html = (
        f"<p>Hi {escape(display_name(task.assignee))},</p>"
        f"<p>You have been assigned a task in RMIS.</p>"
        f"{table(['Item', 'Details'], rows)}<p>{links}</p>"
        "<p style='color:#64748b;font-size:12px'>Post progress (% completed and hours) on the task in RMIS; your monthly "
        "accomplishment report is built from those updates.</p>"
    )
    send_brevo_email(task.assignee.email, f"[RMIS] New task: {task.title} (due {due})", html)
