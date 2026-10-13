"""
ASGI entry point (production: `daphne -b 0.0.0.0 -p 8000 config.asgi:application`).
HTTP goes to normal Django, so every REST endpoint is unchanged; WebSockets go through the origin check -> JWT auth ->
realtime routes (realtime/routing.py).
"""
import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

# Must run before importing anything that touches models (the realtime consumer and auth).
django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter  # noqa: E402
from django.conf import settings  # noqa: E402

from realtime.routing import websocket_application  # noqa: E402

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": websocket_application(settings.CORS_ALLOWED_ORIGINS),
})
