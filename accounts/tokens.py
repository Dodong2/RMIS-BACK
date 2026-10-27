from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode


class EmailVerificationTokenGenerator(PasswordResetTokenGenerator):
    """The e-mail verification link's token (client 2026-10-27): an HMAC of SECRET_KEY, nothing stored. It expires
    after PASSWORD_RESET_TIMEOUT (48 h), and email_verified_at is in the hash, so it stops working once used."""

    key_salt = "accounts.tokens.EmailVerificationTokenGenerator"

    def _make_hash_value(self, user, timestamp):
        return f"{user.pk}{user.email}{user.email_verified_at}{timestamp}"


email_verification_token = EmailVerificationTokenGenerator()


def verification_link_params(user):
    return urlsafe_base64_encode(force_bytes(user.pk)), email_verification_token.make_token(user)
