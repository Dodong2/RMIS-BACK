"""
WebSocket authentication with the same SimpleJWT access token the REST API uses.

Browsers cannot set an Authorization header on a WebSocket, so the frontend sends the access token in the query
string: wss://<host>/ws/updates/?token=<access>. A missing, invalid or expired token (or an inactive account) leaves
scope["user"] as AnonymousUser, and the consumer closes the socket with 4401.
"""
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import AuthenticationFailed, TokenError


@database_sync_to_async
def _user_from_token(raw_token):
    auth = JWTAuthentication()
    try:
        user = auth.get_user(auth.get_validated_token(raw_token))
    except (AuthenticationFailed, TokenError):  # InvalidToken is an AuthenticationFailed
        return AnonymousUser()
    user.role  # load the FK here, in sync code: the async consumer can't run queries
    return user


class JWTAuthMiddleware:
    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        token = (parse_qs(scope.get("query_string", b"").decode()).get("token") or [""])[0]
        scope = dict(scope, user=await _user_from_token(token) if token else AnonymousUser())
        return await self.inner(scope, receive, send)
