"""E-mails to project staff and leaders (client follow-up 2026-10-02), sent through Brevo like the account e-mails.

- task_assigned(): when a leader assigns (or reassigns) a task, the assignee gets its details, a link to the task in
  RMIS, an "Add to Google Calendar" link and a task.ics (Task 25, 2026-10-30).
- task_updated() / task_removed(): the assignee gets the changes, or the cancellation, with an .ics that has the same
  UID, so a calendar that imported the first one updates or removes that event instead of adding another.
- The monthly/quarterly reminders live in management/commands/send_report_reminders.py and reuse the helpers here.
"""
import datetime
from html import escape
from urllib.parse import urlencode, urlparse

from django.conf import settings
from django.utils import timezone

from accounts.emails import send_brevo_email


def display_name(user):
    return user.get_full_name() or user.email


def calendar_link(task):
    return f"{settings.FRONTEND_URL}/tasks?{urlencode({'view': 'calendar', 'task': task.pk})}"


def event_dates(task):
    """(first day, day after the last day) of the task as an all-day event, or None without dates. Tasks store dates
    only, so no times are invented; one date alone makes a one-day event."""
    start, end = task.start_date or task.due_date, task.due_date or task.start_date
    if not start:
        return None
    return start, max(start, end) + datetime.timedelta(days=1)


def event_details(task):
    return f"{task.project.project_code} · {task.project.title}\n\n{task.description}\n\nOpen in RMIS: {calendar_link(task)}"


def google_calendar_link(task):
    """All-day Google Calendar event from the start to the end date (Google's end date is exclusive)."""
    dates = event_dates(task)
    if not dates:
        return ""
    return "https://calendar.google.com/calendar/render?" + urlencode({
        "action": "TEMPLATE",
        "text": f"[RMIS] {task.title}",
        "dates": f"{dates[0]:%Y%m%d}/{dates[1]:%Y%m%d}",
        "details": event_details(task),
    })


def _ics_escape(value):
    return value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line):
    """RFC 5545: lines longer than 75 octets continue on the next line after a space."""
    out, current = [], ""
    for char in line:
        if len((current + char).encode()) > 74:
            out.append(current)
            current = " "
        current += char
    return "\r\n".join(out + [current])


def task_ics(task, cancel=False):
    """The task as an all-day iCalendar event (bytes), or None without dates. UID rmis-task-<id> stays the same for the
    task's life and SEQUENCE grows, so a re-imported update or cancellation replaces the event instead of adding one."""
    dates = event_dates(task)
    if not dates:
        return None
    now = timezone.now()
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//LSPU//RMIS//EN", f"METHOD:{'CANCEL' if cancel else 'PUBLISH'}",
        "BEGIN:VEVENT",
        f"UID:rmis-task-{task.pk}@{urlparse(settings.FRONTEND_URL).hostname or 'rmis'}",
        f"SEQUENCE:{int(now.timestamp())}",
        f"DTSTAMP:{now.astimezone(datetime.UTC):%Y%m%dT%H%M%SZ}",
        f"DTSTART;VALUE=DATE:{dates[0]:%Y%m%d}",
        f"DTEND;VALUE=DATE:{dates[1]:%Y%m%d}",
        f"SUMMARY:{_ics_escape('[RMIS] ' + task.title)}",
        f"DESCRIPTION:{_ics_escape(event_details(task))}",
        f"URL:{calendar_link(task)}",
        f"STATUS:{'CANCELLED' if cancel else 'CONFIRMED'}",
        "END:VEVENT", "END:VCALENDAR",
    ]
    return ("\r\n".join(_fold(line) for line in lines) + "\r\n").encode()


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


def _date(value):
    return f"{value:%B %d, %Y}" if value else "—"


def _task_rows(task):
    return [
        ("Project", f"{task.project.project_code} · {task.project.title}"),
        ("Task", task.title),
        ("Description", task.description or "—"),
        ("Start Date", _date(task.start_date)),
        ("End Date", _date(task.due_date)),
        ("Priority", task.get_priority_display()),
        ("Planned hours", task.estimated_hours or "—"),
        ("Assigned by", display_name(task.assigned_by)),
    ]


def _calendar_part(task):
    """Buttons + .ics attachment list for an e-mail about this task."""
    links = button(calendar_link(task), "Open task in RMIS")
    ics = task_ics(task)
    if not ics:
        return f"<p>{links}</p><p style='color:#64748b;font-size:12px'>No start or end date yet, so there is no calendar event.</p>", None
    links += button(google_calendar_link(task), "Add to Google Calendar")
    note = ("<p style='color:#64748b;font-size:12px'>All-day event from the start to the end date. The attached task.ics "
            "adds it to Google, Outlook or Apple Calendar too.</p>")
    return f"<p>{links}</p>{note}", [("task.ics", ics)]


def task_assigned(task):
    calendar, attachments = _calendar_part(task)
    html = (
        f"<p>Hi {escape(display_name(task.assignee))},</p>"
        "<p>You have been assigned a new task under the following project.</p>"
        f"{table(['Item', 'Details'], _task_rows(task))}{calendar}"
        "<p>Please open your RMIS account to review the task details and schedule.</p>"
        "<p style='color:#64748b;font-size:12px'>Post progress (% completed and hours) on the task in RMIS; your monthly "
        "accomplishment report is built from those updates.</p>"
    )
    send_brevo_email(task.assignee.email, f"New Task Assigned — {task.title}", html, attachments)


def task_updated(task, changes):
    """changes: [(label, old, new)] of the fields that changed (title, description, dates)."""
    show = lambda value: _date(value) if isinstance(value, datetime.date) else value or "—"  # noqa: E731
    changes = [(label, show(old), show(new)) for label, old, new in changes]
    calendar, attachments = _calendar_part(task)
    html = (
        f"<p>Hi {escape(display_name(task.assignee))},</p>"
        "<p>A task assigned to you has been updated.</p>"
        f"{table(['Field', 'Before', 'Now'], changes)}"
        f"<p><b>Current details:</b></p>{table(['Item', 'Details'], _task_rows(task))}{calendar}"
        "<p style='color:#64748b;font-size:12px'>If you added the task with the Google Calendar button, RMIS can't change "
        "that event: delete it and add the task again. Importing the attached task.ics replaces the earlier .ics event.</p>"
    )
    send_brevo_email(task.assignee.email, f"Task Updated — {task.title}", html, attachments)


def task_removed(task, recipient, reassigned=False):
    """The task was deleted, or reassigned away from `recipient`: a cancelling .ics for the same event."""
    ics = task_ics(task, cancel=True)
    what = "reassigned to another staff member" if reassigned else "removed by the Project Leader"
    html = (
        f"<p>Hi {escape(display_name(recipient))},</p>"
        f"<p>The following task has been {what} and is no longer assigned to you.</p>"
        f"{table(['Item', 'Details'], _task_rows(task)[:5])}"
        "<p style='color:#64748b;font-size:12px'>Remove it from your calendar if you added it. Importing the attached "
        "task.ics cancels the earlier .ics event.</p>"
    )
    send_brevo_email(recipient.email, f"Task Removed — {task.title}", html, [("task.ics", ics)] if ics else None)
