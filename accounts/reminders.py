"""Task 24 (2026-10-30): send a scheduled reminder at most once per kind, run, recipient and record (ReminderLog).
The log row is locked while sending, so two overlapping cron runs can't both send it; a failed send is retried by a
later run, up to MAX_ATTEMPTS."""
from django.db import transaction
from django.utils import timezone

from .emails import send_brevo_email
from .models import ReminderLog

MAX_ATTEMPTS = 5


def send_once(kind, run_key, recipient, object_ref, subject, html):
    """'sent', 'failed', or 'skipped' (already sent, or failed MAX_ATTEMPTS times)."""
    with transaction.atomic():
        log, _ = ReminderLog.objects.select_for_update().get_or_create(
            kind=kind, run_key=run_key, recipient=recipient, object_ref=object_ref, defaults={"status": "failed"},
        )
        if log.status == "sent" or log.attempts >= MAX_ATTEMPTS:
            return "skipped"
        ok = send_brevo_email(recipient.email, subject, html)
        log.attempts += 1
        log.status = "sent" if ok else "failed"
        log.sent_at = timezone.now() if ok else None
        log.last_error = "" if ok else "Brevo did not accept the e-mail (see the server log)."
        log.save()
    return log.status
