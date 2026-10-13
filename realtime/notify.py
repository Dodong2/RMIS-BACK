"""
Send a small real-time signal from ordinary (sync) Django code:

    notify([to_user(project.lead_id), to_role("riuh")], "monitoring.report.created", id=report.id, project=project.id)

- Sends only AFTER the database transaction commits, so a rolled-back save never produces a signal.
- Never raises: a real-time failure must not break the request that saved the data.
- With the default InMemoryChannelLayer it only reaches browsers connected to this same process (production runs one
  Daphne process). A management command or cron job is a different process: its signals reach nobody unless
  CHANNEL_LAYERS uses Redis (set REDIS_URL).
"""
import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction

from .consumers import group_name

logger = logging.getLogger(__name__)

ALL_USERS = "all_users"


def to_user(user_id):
    return group_name("user", user_id)


def to_role(role_code):
    return group_name("role", role_code)


def project_audience(project, permission_prefix, *user_ids):
    """Groups for a change to one project's records: every role holding a `<permission_prefix>...` permission in the
    DB, except leaders and project_staff (they see only their own projects, so they're reached per user), plus the
    project lead and the given users (e.g. the submitter)."""
    from accounts.models import Role
    from accounts.permissions import LEADER_ROLES

    codes = (Role.objects.filter(role_permissions__permission__code__startswith=permission_prefix)
             .exclude(code__in=[*LEADER_ROLES, "project_staff"]).values_list("code", flat=True).distinct())
    return [*map(to_role, codes), to_user(project.lead_id), *map(to_user, user_ids)]


def notify(groups, event_type, **data):
    try:
        payload = {"type": event_type, **data}
        groups = [g for g in dict.fromkeys(groups) if g]  # drop duplicates and empties, keep order

        def send():
            layer = get_channel_layer()
            if layer is None:
                return
            for group in groups:
                try:
                    async_to_sync(layer.group_send)(group, {"type": "notify", "payload": payload})
                except Exception:  # noqa: BLE001 — real-time is best effort
                    logger.warning("realtime notify failed for %s (%s)", group, event_type, exc_info=True)

        transaction.on_commit(send)
    except Exception:  # noqa: BLE001
        logger.warning("realtime notify not scheduled (%s)", event_type, exc_info=True)
