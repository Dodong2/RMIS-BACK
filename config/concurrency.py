"""
Concurrency control and idempotency (2026-10-12; design: tasks/client-2026-10-12/concurrency-plan.md).

- lock() / lock_line_items(): re-read a row with SELECT ... FOR UPDATE inside transaction.atomic(), so a check
  (status, balance, leader load) and the write that depends on it happen while no one else can change that row.
  A concurrent request waits, then re-reads the committed state and fails validation normally.
- @idempotent: honours an optional Idempotency-Key header on create endpoints. A retry of the same intent replays the
  first response instead of creating a second record.
- conflict_exception_handler: a unique-constraint race, deadlock or serialization failure becomes HTTP 409, not 500.
"""
import functools
import hashlib
import json
import logging
import re
from datetime import timedelta

from django.core.serializers.json import DjangoJSONEncoder
from django.db import IntegrityError, OperationalError, transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler

logger = logging.getLogger(__name__)

CONFLICT_MESSAGE = "This record was changed at the same time by someone else. Refresh and try again."
# Postgres SQLSTATEs: unique_violation, deadlock_detected, serialization_failure.
CONFLICT_SQLSTATES = {"23505", "40P01", "40001"}

KEY_PATTERN = re.compile(r"^[A-Za-z0-9-]{8,64}$")
KEY_TTL = timedelta(hours=24)  # longer than any retry path: no queues, a key lives as long as one opened form
STALE_CLAIM_AFTER = timedelta(minutes=2)  # well past gunicorn's request timeout, so the first attempt is dead


def lock(queryset, **lookup):
    """get_object_or_404 + row lock. Must run inside transaction.atomic()."""
    return get_object_or_404(queryset.select_for_update(of=("self",)), **lookup)


def lock_line_items(*items):
    """Lock line items in id order (a fixed order means two requests can't deadlock on each other)."""
    from budget_lib.models import LineItem

    pks = sorted({item.pk for item in items if item is not None})
    return list(LineItem.objects.select_for_update().filter(pk__in=pks).order_by("pk"))


def _sqlstate(exc):
    return getattr(exc.__cause__, "sqlstate", None) or getattr(exc.__cause__, "pgcode", None)


def conflict_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is None and isinstance(exc, (IntegrityError, OperationalError)) and _sqlstate(exc) in CONFLICT_SQLSTATES:
        logger.warning("Concurrent write conflict on %s: %s", context.get("request") and context["request"].path, exc)
        return Response({"detail": CONFLICT_MESSAGE}, status=status.HTTP_409_CONFLICT)
    return response


def request_hash(endpoint, data):
    payload = json.dumps(data, sort_keys=True, cls=DjangoJSONEncoder, default=str)
    return hashlib.sha256(f"{endpoint}\n{payload}".encode()).hexdigest()


def _claim(user, key, endpoint, digest):
    """Returns (claim, None) when this request owns the key, or (None, response) when it must not run."""
    from accounts.models import IdempotencyKey

    now = timezone.now()
    IdempotencyKey.objects.filter(user=user, created_at__lt=now - KEY_TTL).delete()
    for _ in range(2):  # a second pass covers a failed first attempt that freed the key in between
        try:
            with transaction.atomic():
                return IdempotencyKey.objects.create(user=user, key=key, endpoint=endpoint, request_hash=digest), None
        except IntegrityError:
            pass
        with transaction.atomic():
            existing = IdempotencyKey.objects.select_for_update().filter(user=user, key=key).first()
            if existing is None:
                continue
            if existing.endpoint != endpoint or existing.request_hash != digest:
                return None, Response({"detail": "This Idempotency-Key was already used for a different request."},
                                      status=status.HTTP_422_UNPROCESSABLE_ENTITY)
            if existing.state == "succeeded":
                return None, Response(existing.response_body, status=existing.response_status)
            if existing.created_at > now - STALE_CLAIM_AFTER:
                return None, Response({"detail": "This request is still being processed. Refresh before retrying."},
                                      status=status.HTTP_409_CONFLICT)
            existing.created_at = now  # the first attempt died before committing; take the key over
            existing.save(update_fields=["created_at"])
            return existing, None
    return None, Response({"detail": CONFLICT_MESSAGE}, status=status.HTTP_409_CONFLICT)


def idempotent(handler):
    """
    Wrap a view's create handler (post/create). The handler always runs in transaction.atomic(), so locks taken
    inside it hold until commit. With an Idempotency-Key header, the key is claimed first (its own committed
    INSERT, decided by the unique constraint), and marked succeeded in the same transaction as the work.
    """

    @functools.wraps(handler)
    def wrapper(view, request, *args, **kwargs):
        key = request.META.get("HTTP_IDEMPOTENCY_KEY")
        if key is None:
            with transaction.atomic():
                return handler(view, request, *args, **kwargs)
        if not KEY_PATTERN.match(key):
            return Response({"detail": "Idempotency-Key must be 8-64 letters, digits or dashes."},
                            status=status.HTTP_400_BAD_REQUEST)

        endpoint = f"{request.method} {request.path}"
        claim, early = _claim(request.user, key, endpoint, request_hash(endpoint, request.data))
        if early is not None:
            return early
        succeeded = False
        try:
            with transaction.atomic():
                response = handler(view, request, *args, **kwargs)
                ok = 200 <= response.status_code < 300
                if ok:
                    type(claim).objects.filter(pk=claim.pk).update(
                        state="succeeded", response_status=response.status_code, response_body=response.data,
                    )
            succeeded = ok  # only once the commit itself went through
            return response
        finally:
            if not succeeded:  # nothing committed for this intent: free the key so a corrected resubmit can use it
                type(claim).objects.filter(pk=claim.pk, state="in_progress").delete()

    return wrapper


class AtomicMutationMixin:
    """Generic views: run create/update/destroy in one transaction, so row locks taken in validate() hold until save."""

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @transaction.atomic
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    @transaction.atomic
    def destroy(self, request, *args, **kwargs):
        return super().destroy(request, *args, **kwargs)
