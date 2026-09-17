import requests
from django.conf import settings
from .models import User


def send_brevo_email(to_email, subject, html_content):
    requests.post(
        "https://api.brevo.com/v3/smtp/email",
        headers={
            "accept": "application/json",
            "api-key": settings.BREVO_API_KEY,
            "content-type": "application/json",
        },
        json={
            "sender": {"name": settings.BREVO_SENDER_NAME, "email": settings.BREVO_SENDER_EMAIL},
            "to": [{"email": to_email}],
            "subject": subject,
            "htmlContent": html_content,
        },
    )


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
            f"<p>{user.email} registered via {method} and requested the role: {requested}.</p>"
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