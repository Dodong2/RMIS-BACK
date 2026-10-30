import base64
import logging

import requests
from django.conf import settings
from .models import User

logger = logging.getLogger(__name__)


def send_brevo_email(to_email, subject, html_content, attachments=None):
    """Returns True if Brevo accepted the e-mail. A failure is logged, never raised, so the caller's save stands.
    attachments: optional [(filename, bytes)], e.g. a task's .ics (Task 25)."""
    payload = {
        "sender": {"name": settings.BREVO_SENDER_NAME, "email": settings.BREVO_SENDER_EMAIL},
        "to": [{"email": to_email}],
        "subject": subject,
        "htmlContent": html_content,
    }
    if attachments:
        payload["attachment"] = [{"name": name, "content": base64.b64encode(data).decode()} for name, data in attachments]
    try:
        resp = requests.post(
            "https://api.brevo.com/v3/smtp/email",
            headers={
                "accept": "application/json",
                "api-key": settings.BREVO_API_KEY,
                "content-type": "application/json",
            },
            json=payload,
            timeout=10,
        )
    except requests.RequestException as error:
        logger.error("Brevo e-mail to %s failed: %s", to_email, error)
        return False
    if not resp.ok:
        logger.error("Brevo e-mail to %s failed: %s %s", to_email, resp.status_code, resp.text[:300])
    return resp.ok


def notify_admins_new_registration(user):
    admin_emails = list(
        User.objects.filter(role__code="system_admin", is_active=True).values_list("email", flat=True)
    )
    requested = user.requested_role.name if user.requested_role else "No role specified"
    method = "Email & Password" if user.registration_method == "email" else "Google"
    for admin_email in admin_emails:
        send_brevo_email(
            admin_email,
            "New RMIS Registration Pending",
            f"<p>{user.get_full_name()} ({user.email}) registered via {method} and requested the role: {requested}.</p>"
            f"<p>Go to the Pending Users page in RMIS to review and assign a role.</p>",
        )


def send_role_confirmation_email(user):
    login_url = f"{settings.FRONTEND_URL}/login"
    if user.registration_method == "google":
        instruction = "You must click Login with Google and choose the account that received this confirmation."
    else:
        instruction = "You must login with your email and password."

    html = (
        f"<p>Your RMIS account has been confirmed with the role: {user.role.name}.</p>"
        f"<p>{instruction}</p>"
        f"<p><a href='{login_url}'>Go to Login</a></p>"
    )
    send_brevo_email(user.email, "Your RMIS Account Has Been Confirmed", html)

def send_verification_email(user):
    from .tokens import verification_link_params

    uid, token = verification_link_params(user)
    link = f"{settings.FRONTEND_URL}/verify-email?uid={uid}&token={token}"
    html = (
        f"<p>Hi {user.get_full_name()},</p>"
        f"<p>Verify your e-mail address to finish your RMIS registration:</p>"
        f"<p><a href='{link}'>Verify my e-mail</a></p>"
        f"<p>The link works once and expires in 48 hours. After you verify, the System Admin reviews your "
        f"registration.</p>"
        f"<p>If you didn't register for RMIS, ignore this e-mail.</p>"
    )
    return send_brevo_email(user.email, "Verify your RMIS e-mail address", html)


def send_rejection_email(user, reason=""):
    from django.utils.html import escape

    why = f"<p>Reason: {escape(reason)}</p>" if reason else ""
    html = (
        f"<p>Hi {escape(user.get_full_name())},</p>"
        f"<p>Your RMIS registration was not approved.</p>{why}"
        f"<p>If you think this is a mistake, contact the RMIS System Admin.</p>"
    )
    return send_brevo_email(user.email, "Your RMIS registration was not approved", html)
