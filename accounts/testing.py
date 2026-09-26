"""Shared test helpers. Tests run on Django's temporary test database (test_<DB_NAME>), created and dropped by
`python manage.py test`; the real data is never touched."""
from unittest import mock

from django.core.management import call_command
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from accounts.models import Role, User

PASSWORD = "Str0ng-pass-for-tests"
# PBKDF2 takes ~2 s per hash on the dev laptop; tests only need a working hasher, not a strong one.
FAST_HASHER = override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])


@FAST_HASHER
class RMISTestCase(TestCase):
    """Seeds the 12 roles + their permissions once per class, and blocks every outbound call: Brevo e-mail and the
    Supabase auth/storage APIs are mocked, so no test sends a real e-mail or touches real storage."""

    @classmethod
    def setUpTestData(cls):
        call_command("seed_roles", stdout=open("/dev/null", "w"))

    def setUp(self):
        self.brevo_post = self._patch("accounts.emails.requests.post")
        self.supabase_get = self._patch("accounts.views.http.get")
        self._patch("document_management.serializers.upload_document")
        self._patch("document_management.serializers.get_signed_url", return_value="https://signed.example/file")

    def _patch(self, target, **kwargs):
        patcher = mock.patch(target, **kwargs)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def make_user(self, role_code=None, email=None, **fields):
        email = email or f"{role_code or 'norole'}-{User.objects.count()}@lspu.test"
        user = User.objects.create_user(
            username=email, email=email, password=PASSWORD, is_pending_role=role_code is None,
            role=Role.objects.get(code=role_code) if role_code else None, **fields,
        )
        return user

    def client_for(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client
