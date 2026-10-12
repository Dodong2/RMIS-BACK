"""Foundation tests for config/concurrency.py: the Idempotency-Key contract and the 409 conflict handler."""
from datetime import timedelta

from django.db import IntegrityError
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, force_authenticate
from rest_framework.views import APIView

from accounts.models import IdempotencyKey, Role
from accounts.testing import RMISTestCase
from config.concurrency import idempotent, request_hash

ENDPOINT = "POST /api/test/roles/"


class CreateRoleView(APIView):
    """A tiny create endpoint: makes one Role per call, or fails when asked to."""

    @idempotent
    def post(self, request):
        if request.data.get("fail"):
            return Response({"detail": "nope"}, status=status.HTTP_400_BAD_REQUEST)
        role = Role.objects.create(code=request.data["code"], name="Temp")
        return Response({"id": role.id, "code": role.code}, status=status.HTTP_201_CREATED)


class DuplicateRoleView(APIView):
    def post(self, request):
        Role.objects.create(code="system_admin", name="Duplicate")
        return Response(status=status.HTTP_201_CREATED)


class IdempotencyKeyTests(RMISTestCase):
    def setUp(self):
        super().setUp()
        self.user = self.make_user("project_leader")
        self.factory = APIRequestFactory()

    def call(self, data, key="key-0001-abcd", user=None):
        headers = {"HTTP_IDEMPOTENCY_KEY": key} if key else {}
        request = self.factory.post("/api/test/roles/", data, format="json", **headers)
        force_authenticate(request, user=user or self.user)
        return CreateRoleView.as_view()(request)

    def test_without_a_key_every_call_creates(self):
        self.assertEqual(self.call({"code": "a1"}, key=None).status_code, 201)
        self.assertEqual(self.call({"code": "a2"}, key=None).status_code, 201)
        self.assertFalse(IdempotencyKey.objects.exists())

    def test_retry_with_the_same_key_replays_without_creating_again(self):
        first = self.call({"code": "r1"})
        second = self.call({"code": "r1"})
        self.assertEqual((first.status_code, second.status_code), (201, 201))
        self.assertEqual(first.data, second.data)
        self.assertEqual(Role.objects.filter(code="r1").count(), 1)
        self.assertEqual(IdempotencyKey.objects.get().state, "succeeded")

    def test_same_key_with_a_different_body_is_rejected(self):
        self.call({"code": "b1"})
        response = self.call({"code": "b2"})
        self.assertEqual(response.status_code, 422)
        self.assertFalse(Role.objects.filter(code="b2").exists())

    def test_failed_request_frees_the_key_for_a_corrected_resubmit(self):
        self.assertEqual(self.call({"code": "c1", "fail": True}).status_code, 400)
        self.assertFalse(IdempotencyKey.objects.exists())
        self.assertEqual(self.call({"code": "c1"}).status_code, 201)

    def test_keys_are_scoped_per_user(self):
        self.call({"code": "u1"})
        other = self.make_user("project_leader")
        response = self.call({"code": "u1"}, user=other)
        self.assertNotEqual(response.status_code, 201)  # not a replay of someone else's response
        self.assertEqual(Role.objects.filter(code="u1").count(), 1)

    def test_in_flight_duplicate_gets_409(self):
        IdempotencyKey.objects.create(user=self.user, key="key-0001-abcd", endpoint=ENDPOINT,
                                      request_hash=request_hash(ENDPOINT, {"code": "f1"}))
        response = self.call({"code": "f1"})
        self.assertEqual(response.status_code, 409)

    def test_stale_claim_from_a_crashed_attempt_is_taken_over(self):
        IdempotencyKey.objects.create(user=self.user, key="key-0001-abcd", endpoint=ENDPOINT,
                                      request_hash=request_hash(ENDPOINT, {"code": "s1"}))
        IdempotencyKey.objects.update(created_at=timezone.now() - timedelta(minutes=5))
        self.assertEqual(self.call({"code": "s1"}).status_code, 201)

    def test_malformed_key_is_rejected(self):
        self.assertEqual(self.call({"code": "m1"}, key="bad key!").status_code, 400)


class ConflictHandlerTests(RMISTestCase):
    def test_unique_violation_becomes_409_not_500(self):
        request = APIRequestFactory().post("/api/test/dup/", {}, format="json")
        force_authenticate(request, user=self.make_user("system_admin"))
        response = DuplicateRoleView.as_view()(request)
        self.assertEqual(response.status_code, 409)
        self.assertIn("Refresh", response.data["detail"])

    def test_handler_leaves_other_integrity_errors_alone(self):
        from config.concurrency import conflict_exception_handler
        self.assertIsNone(conflict_exception_handler(IntegrityError("not null"), {}))
