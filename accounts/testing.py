"""Shared test helpers. Tests run on Django's temporary test database (test_<DB_NAME>), created and dropped by
`python manage.py test`; the real data is never touched."""
import importlib
import threading
import time
from unittest import mock

from django.core.management import call_command
from django.db import connection
from django.test import TestCase, TransactionTestCase, override_settings
from rest_framework.test import APIClient

from accounts.models import Role, User

PASSWORD = "Str0ng-pass-for-tests"
# PBKDF2 takes ~2 s per hash on the dev laptop; tests only need a working hasher, not a strong one.
FAST_HASHER = override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])


class TestHelpers:
    """Shared by RMISTestCase and ConcurrencyTestCase."""

    def setUp(self):
        self.brevo_post = self._patch("accounts.emails.requests.post")
        self.supabase_get = self._patch("accounts.views.http.get")
        self.upload_document = self._patch("document_management.serializers.upload_document")
        self.move_document = self._patch("document_management.serializers.move_document")
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


@FAST_HASHER
class RMISTestCase(TestHelpers, TestCase):
    """Seeds the 12 roles + their permissions once per class, and blocks every outbound call: Brevo e-mail and the
    Supabase auth/storage APIs are mocked, so no test sends a real e-mail or touches real storage."""

    @classmethod
    def setUpTestData(cls):
        call_command("seed_roles", stdout=open("/dev/null", "w"))


@FAST_HASHER
class ConcurrencyTestCase(TestHelpers, TransactionTestCase):
    """
    Real concurrent requests (config/concurrency.py). Unlike TestCase, nothing wraps the test in one transaction, so
    each thread gets its own DB connection and commits like a real request. `widen()` slows the read side of a race
    (the check) so both requests are inside the window together: without row locks both pass the check; with them
    the second waits and re-reads.
    """

    # TransactionTestCase empties every table after each test; this puts the migration-seeded rows back, so the
    # kept (--keepdb) test database stays complete for the TestCase suites that run after it.
    serialized_rollback = True

    def setUp(self):
        call_command("seed_roles", stdout=open("/dev/null", "w"))
        super().setUp()

    def widen(self, target, seconds=0.6, before=False):
        module_name, name = target.rsplit(".", 1)
        original = getattr(importlib.import_module(module_name), name)

        def slow(*args, **kwargs):
            if before:
                time.sleep(seconds)
            result = original(*args, **kwargs)
            if not before:
                time.sleep(seconds)
            return result

        self._patch(target, side_effect=slow)

    def run_concurrently(self, *calls):
        """Start every call at the same instant (a barrier) on its own thread; return their results in order."""
        barrier = threading.Barrier(len(calls))
        results = [None] * len(calls)

        def worker(index, call):
            try:
                barrier.wait()
                results[index] = call()
            except Exception as exc:  # surfaced to the test as a result, not swallowed
                results[index] = exc
            finally:
                connection.close()

        threads = [threading.Thread(target=worker, args=(i, c)) for i, c in enumerate(calls)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=120)
        return results

