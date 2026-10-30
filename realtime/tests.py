import asyncio
from unittest import mock

from asgiref.sync import async_to_sync
from channels.db import database_sync_to_async
from channels.layers import get_channel_layer
from channels.testing import WebsocketCommunicator
from django.db import transaction
from django.test import TestCase
from rest_framework_simplejwt.tokens import AccessToken

from accounts.testing import RMISTestCase
from realtime.consumers import campus_role_group
from realtime.notify import ALL_USERS, notify, project_audience, to_role, to_user
from realtime.routing import websocket_application

ORIGIN = "https://rmis.test"
app = websocket_application([ORIGIN])


def receive_or_none(channel):
    """The next message on a channel-layer channel, or None if nothing arrives within 0.2 s."""
    async def receive():
        try:
            return await asyncio.wait_for(get_channel_layer().receive(channel), 0.2)
        except asyncio.TimeoutError:
            return None
    return async_to_sync(receive)()


def listen(group):
    layer = get_channel_layer()
    channel = async_to_sync(layer.new_channel)()
    async_to_sync(layer.group_add)(group, channel)
    return channel


class NotifyTests(TestCase):
    def test_sent_only_after_commit(self):
        channel = listen(ALL_USERS)
        with self.captureOnCommitCallbacks(execute=True):
            notify([ALL_USERS], "thing.created", id=7)
            self.assertIsNone(receive_or_none(channel))  # still inside the transaction
        self.assertEqual(receive_or_none(channel), {"type": "notify", "payload": {"type": "thing.created", "id": 7}})

    def test_rolled_back_transaction_sends_nothing(self):
        channel = listen(ALL_USERS)
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            with self.assertRaises(RuntimeError), transaction.atomic():
                notify([ALL_USERS], "thing.created", id=7)
                raise RuntimeError("save failed")
        self.assertEqual(callbacks, [])
        self.assertIsNone(receive_or_none(channel))

    def test_channel_layer_failure_never_raises(self):
        broken = mock.Mock(group_send=mock.AsyncMock(side_effect=ConnectionError("layer down")))
        with mock.patch("realtime.notify.get_channel_layer", return_value=broken), \
                self.assertLogs("realtime.notify", "WARNING"), self.captureOnCommitCallbacks(execute=True):
            notify([ALL_USERS, to_user(1)], "thing.created", id=7)
        self.assertEqual(broken.group_send.await_count, 2)  # one failing group doesn't stop the next

    def test_asgi_application_routes_websockets(self):
        from config.asgi import application

        self.assertEqual(set(application.application_mapping), {"http", "websocket"})


class SocketTests(RMISTestCase):
    """Real WebSocket handshakes through the same origin check -> JWT auth -> consumer stack as config/asgi.py."""

    def setUp(self):
        super().setUp()
        # channels closes "old" DB connections around each database_sync_to_async call; inside TestCase's wrapping
        # transaction that would break the test's own connection.
        self._patch("channels.db.close_old_connections")
        self.user = self.make_user("riuh")
        self.token = str(AccessToken.for_user(self.user))

    def socket(self, token=None, origin=ORIGIN):
        path = "/ws/updates/" + (f"?token={token}" if token else "")
        return WebsocketCommunicator(app, path, headers=[(b"origin", origin.encode())])

    async def connected(self):
        ws = self.socket(self.token)
        ok, _ = await ws.connect()
        self.assertTrue(ok)
        return ws

    async def test_valid_token_connects_and_answers_ping(self):
        ws = await self.connected()
        await ws.send_json_to({"type": "ping"})
        self.assertEqual(await ws.receive_json_from(), {"type": "pong"})
        await ws.disconnect()

    async def test_missing_or_bad_token_closes_with_4401(self):
        for token in (None, "not-a-jwt"):
            with self.subTest(token=token):
                ws = self.socket(token)
                ok, _ = await ws.connect()
                # Accepted first: a close before accept becomes an HTTP 403 and the browser never sees 4401.
                self.assertTrue(ok)
                self.assertEqual(await ws.receive_output(), {"type": "websocket.close", "code": 4401})

    async def test_unknown_origin_is_rejected(self):
        ws = self.socket(self.token, origin="https://evil.example")
        ok, _ = await ws.connect()
        self.assertFalse(ok)

    async def test_receives_its_user_role_and_all_users_signals_after_commit(self):
        ws = await self.connected()
        for group in (to_user(self.user.pk), to_role("riuh"), ALL_USERS):
            with self.subTest(group=group):
                await database_sync_to_async(self.notify_and_commit)(group)
                self.assertEqual(await ws.receive_json_from(), {"type": "thing.created", "id": 7})
        await database_sync_to_async(self.notify_and_commit)(to_role("vprei"))  # someone else's group
        self.assertTrue(await ws.receive_nothing())
        await ws.disconnect()

    async def test_a_campus_role_hears_its_own_campus_only(self):
        """Task 21 (2026-10-30): RIUH (like CRC/CRD, Finance, Procurement) joins its campus group; another campus's
        project signals never reach it."""
        await database_sync_to_async(type(self.user).objects.filter(pk=self.user.pk).update)(campus="Siniloan")
        ws = await self.connected()
        await database_sync_to_async(self.notify_and_commit)(campus_role_group("riuh", "siniloan"))
        self.assertEqual(await ws.receive_json_from(), {"type": "thing.created", "id": 7})
        for group in (campus_role_group("riuh", "Sta. Cruz"), campus_role_group("riuh", "")):
            await database_sync_to_async(self.notify_and_commit)(group)
            self.assertTrue(await ws.receive_nothing(), group)
        await ws.disconnect()

    def notify_and_commit(self, group):
        with self.captureOnCommitCallbacks(execute=True):  # TestCase never really commits
            notify([group], "thing.created", id=7)


class ProjectAudienceTests(RMISTestCase):
    """Task 21 (2026-10-30): campus-scoped roles are reached on the project's campus (and their campus-less accounts)
    only; other roles keep their role group, the lead their user group."""

    def test_campus_roles_get_the_projects_campus_group(self):
        from research_projects.models import Project

        lead = self.make_user("project_leader")
        project = Project.objects.create(title="P", project_code="P-1", funding_type="core_funded", lead=lead, campus="Siniloan")

        groups = project_audience(project, "budget.")

        self.assertLessEqual({to_role("system_admin"), campus_role_group("crc_chair", "Siniloan"), campus_role_group("crc_chair", ""),
                              campus_role_group("finance_budget", "Siniloan"), to_user(lead.pk)}, set(groups))
        for unscoped in (to_role("crc_chair"), to_role("finance_budget"), campus_role_group("crc_chair", "Sta. Cruz")):
            self.assertNotIn(unscoped, groups)
