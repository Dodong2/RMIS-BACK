"""
One WebSocket per logged-in browser tab: /ws/updates/

The socket only carries small "something changed" signals, e.g. {"type": "monitoring.report.created", "id": 42,
"project": 7}. The frontend then refetches through the normal REST API, so every permission rule stays in DRF and
this consumer never reads model data.
"""
import re

from channels.generic.websocket import AsyncJsonWebsocketConsumer

_UNSAFE = re.compile(r"[^A-Za-z0-9_.-]")


def group_name(prefix, value):
    """Channel-layer group names allow only ASCII letters, digits, _ . - (under 100 chars)."""
    return f"{prefix}_{_UNSAFE.sub('_', str(value))}"[:99]


class UpdatesConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        user = self.scope["user"]
        # Accept, then close: a close before accept becomes an HTTP 403 handshake failure (ASGI spec) and the
        # browser only sees 1006, not 4401, so it couldn't tell "refresh your token" from "server down".
        await self.accept()
        if not user.is_authenticated:
            await self.close(code=4401)
            return
        self.groups_joined = [group_name("user", user.pk), "all_users"]
        if user.role:  # loaded by realtime.auth
            self.groups_joined.append(group_name("role", user.role.code))
        for group in self.groups_joined:
            await self.channel_layer.group_add(group, self.channel_name)

    async def disconnect(self, code):
        for group in getattr(self, "groups_joined", []):
            await self.channel_layer.group_discard(group, self.channel_name)

    async def receive_json(self, content, **kwargs):
        # Keep-alive from the frontend; nothing else is accepted from clients.
        if content.get("type") == "ping":
            await self.send_json({"type": "pong"})

    async def notify(self, event):
        """Handler for group_send(group, {"type": "notify", "payload": {...}})."""
        await self.send_json(event["payload"])
