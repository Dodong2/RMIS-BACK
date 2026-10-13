"""Real client IP behind the Cloudflare tunnel. Every request reaches Django from cloudflared/Traefik, so REMOTE_ADDR
is the proxy's address for all users. Cloudflare puts the visitor's IP in CF-Connecting-IP (and overwrites any value
the client sends), so this copies it into REMOTE_ADDR, the one place the audit log and DRF throttling read.
Safe only while the server is reachable through the tunnel alone (no public port), which is the current setup.
X-Forwarded-For is never trusted: the client can write it, and REST_FRAMEWORK NUM_PROXIES = 0 makes DRF ignore it."""
from ipaddress import ip_address


class CloudflareClientIPMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        cf_ip = request.META.get("HTTP_CF_CONNECTING_IP", "").strip()
        if cf_ip:
            try:
                request.META["REMOTE_ADDR"] = str(ip_address(cf_ip))
            except ValueError:
                pass  # not an IP; keep the proxy's address
        return self.get_response(request)
