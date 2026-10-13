from channels.routing import URLRouter
from channels.security.websocket import OriginValidator
from django.urls import path

from .auth import JWTAuthMiddleware
from .consumers import UpdatesConsumer

websocket_urlpatterns = [
    path("ws/updates/", UpdatesConsumer.as_asgi()),
]


def websocket_application(allowed_origins):
    """Origin check -> JWT auth -> routes. config/asgi.py passes settings.CORS_ALLOWED_ORIGINS (the frontend's
    origin is netlify.app, not one of ALLOWED_HOSTS); tests pass their own."""
    return OriginValidator(JWTAuthMiddleware(URLRouter(websocket_urlpatterns)), allowed_origins)
